import json
import re
import threading
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .checker import check
from .loader import load_text
from . import vcs
from .models import Session
from .nursing import nursing
from .paths import OUT
from .solve import solve
from .yamlsave import patch_text

STATIC = Path(__file__).parent / "static"
FIELDS = ("day", "time", "rooms")


def _placement(s: Session) -> tuple:
    return (s.day, s.start, s.end, tuple(s.rooms.primary))


def _locks(s: Session) -> dict[str, bool]:
    has = {"day": s.day is not None, "time": bool(s.start and s.end), "rooms": bool(s.rooms.primary)}
    return {f: has[f] and s.locked.get(f, True) for f in FIELDS}


def _session_json(s: Session) -> dict:
    return {
        "id": s.id,
        "lead": s.lead,
        "weeks": s.weeks,
        "day": s.day,
        "start": s.start,
        "end": s.end,
        "rooms": {"primary": s.rooms.primary, "overflow": s.rooms.overflow, "preferred": s.rooms.preferred},
        "staff": {"named": s.staff.named, "count": s.staff.count},
        "needs_access": s.needs_access or [],
        "focus": s.focus,
        "placed": bool(s.day and s.start and s.end and s.rooms.primary),
        "locks": _locks(s),
        "has": {"day": s.day is not None, "time": bool(s.start and s.end), "rooms": bool(s.rooms.primary)},
    }


class Workspace:
    """The plan being edited in the browser. Nothing is written back to disk."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.mutex = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.text = self.path.read_text()
        self.sc = load_text(self.text)
        self.changed: set[str] = set()
        self.notice: dict | None = None

    def state(self) -> dict:
        sc = self.sc
        ids = [s.id for s in sc.sessions]
        violations = []
        for v in check(sc).violations:
            involved = [i for i in ids if re.search(rf"\b{re.escape(i)}\b", v.message)]
            violations.append({"severity": v.severity, "rule": v.rule, "message": v.message, "weight": v.weight, "sessions": involved})
        pins = []
        for r in sc.rules:
            if r.type == "pin":
                person = next((p for p in sc.people if p.id == r.who), None)
                pins.append({"room": r.room, "who": r.who, "days": (person.days if person and person.days else sc.calendar.days)})
        return {
            "calendar": sc.calendar.model_dump(),
            "rooms": [{"id": r.id, "location": r.location, "attributes": r.attributes} for r in sc.rooms],
            "people": [{"id": p.id, "role": p.role} for p in sc.people],
            "sessions": [_session_json(s) for s in sc.sessions],
            "pins": pins,
            "violations": violations,
            "changed": sorted(self.changed),
            "notice": self.notice,
            "edited": sc.model_dump(mode="json") != load_text(self.text).model_dump(mode="json"),
        }

    def set_lock(self, session: str | None, field: str | None, locked: bool) -> None:
        self.changed, self.notice = set(), None
        for s in self.sc.sessions:
            if session is None or s.id == session:
                for f in ([field] if field else FIELDS):
                    s.locked[f] = locked

    def solve(self, time_limit: float = 30.0) -> None:
        result = solve(self.sc, time_limit)
        if result.status == "solved":
            before = {s.id: _placement(s) for s in self.sc.sessions}
            self.sc = result.scenario
            self.changed = {s.id for s in self.sc.sessions if _placement(s) != before[s.id]}
            self.notice = {"kind": "solved", "objective": result.objective, "moved": sorted(self.changed)}
        elif result.status == "infeasible":
            self.changed = set()
            self.notice = {"kind": "infeasible", "core": result.core}
        else:
            self.notice = {"kind": "timeout"}

    def save(self) -> None:
        new = patch_text(self.text, self.sc)
        self.path.write_text(new)
        self.text = new
        self.sc.notes = load_text(new).notes
        self.notice = {"kind": "saved"}

    def commit(self, message: str) -> None:
        self.save()
        sha = vcs.commit(self.path, message)
        self.notice = {"kind": "saved", "commit": sha}

    def restore(self, sha: str) -> None:
        vcs.restore(self.path, sha)
        self.reset()
        self.notice = {"kind": "saved", "restored": sha}

    def export(self) -> dict:
        return {"sessions": self.sc.model_dump(mode="json")["sessions"]}


class MessageBody(BaseModel):
    message: str


class ShaBody(BaseModel):
    sha: str


class LockBody(BaseModel):
    session: str | None = None
    field: Literal["day", "time", "rooms"] | None = None
    locked: bool


def create_app(path: str | Path) -> FastAPI:
    ws = Workspace(path)
    app = FastAPI(title="Clinic planner")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/state")
    @app.post("/api/check")
    def state() -> dict:
        with ws.mutex:
            return ws.state()

    @app.post("/api/solve")
    def solve_plan() -> dict:
        with ws.mutex:
            ws.solve()
            return ws.state()

    @app.post("/api/reset")
    def reset() -> dict:
        with ws.mutex:
            ws.reset()
            return ws.state()

    @app.post("/api/lock")
    def lock(body: LockBody) -> dict:
        with ws.mutex:
            ws.set_lock(body.session, body.field, body.locked)
            return ws.state()

    def guarded(fn) -> dict:
        with ws.mutex:
            try:
                fn()
            except ValueError as e:
                ws.notice = {"kind": "error", "message": str(e)}
            return ws.state()

    @app.get("/api/nursing")
    def nursing_report() -> dict:
        with ws.mutex:
            return nursing(ws.sc)

    @app.get("/api/history")
    def history() -> dict:
        with ws.mutex:
            return {**vcs.info(ws.path), "file": ws.path.name}

    @app.post("/api/save")
    def save() -> dict:
        return guarded(ws.save)

    @app.post("/api/commit")
    def commit(body: MessageBody) -> dict:
        return guarded(lambda: ws.commit(body.message))

    @app.post("/api/restore")
    def restore(body: ShaBody) -> dict:
        return guarded(lambda: ws.restore(body.sha))

    @app.get("/api/export")
    def export() -> FileResponse:
        with ws.mutex:
            out = OUT / "plan.json"
            out.parent.mkdir(exist_ok=True)
            out.write_text(json.dumps(ws.export(), indent=2))
        return FileResponse(out, media_type="application/json", filename="plan.json")

    return app
