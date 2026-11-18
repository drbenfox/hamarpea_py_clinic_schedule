import copy
from pathlib import Path

import yaml

from .checker import check
from .loader import load_text
from .models import Scenario, Session
from .report import utilisation
from .solve import SolveResult, solve


def load_patch(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def _find(items: list[dict], item_id: str, list_name: str) -> dict:
    for item in items:
        if item.get("id") == item_id:
            return item
    raise ValueError(f"patch: no item with id '{item_id}' in {list_name}")


def _merge(dst: dict, src: dict) -> None:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge(dst[key], value)
        else:
            dst[key] = copy.deepcopy(value)


def apply_patch(raw: dict, patch: dict) -> dict:
    """Ops: add (list, value), remove (list, id), update (list, id, set: deep-merged), option (name, value)."""
    out = copy.deepcopy(raw)
    for change in patch.get("changes", []):
        op = change.get("op")
        if op == "option":
            out.setdefault("options", {})[change["name"]] = change["value"]
        elif op == "add":
            out.setdefault(change["list"], []).append(copy.deepcopy(change["value"]))
        elif op == "remove":
            items = out.get(change["list"], [])
            items.remove(_find(items, change["id"], change["list"]))
        elif op == "update":
            _merge(_find(out.get(change["list"], []), change["id"], change["list"]), change["set"])
        else:
            raise ValueError(f"patch: unknown op '{op}'")
    return out


def _place(s: Session) -> str:
    return f"{s.weeks} {s.day} {s.start}-{s.end} in {', '.join(s.rooms.primary)}"


def _soft(sc: Scenario) -> dict[str, int]:
    return {v.message: v.weight for v in check(sc).violations if v.severity == "soft"}


def _staff(sc: Scenario) -> list[str]:
    return [v.message for v in check(sc).violations if v.rule == "staff_demand"]


def _diff(base: SolveResult, new: SolveResult) -> list[str]:
    a, b = base.scenario, new.scenario
    out = [f"FEASIBLE. Objective {base.objective} -> {new.objective} (lower is better)", "", "Sessions"]
    before = {s.id: s for s in a.sessions}
    after = {s.id: s for s in b.sessions}
    changes = []
    for sid in before.keys() - after.keys():
        changes.append(f"  - removed {sid}")
    for sid, s in after.items():
        if sid not in before:
            changes.append(f"  + added {sid}: {_place(s)}")
        elif _place(before[sid]) != _place(s):
            changes.append(f"  ~ {sid}: {_place(before[sid])}  ->  {_place(s)}")
    out += changes or ["  no session moved"]

    errors = check(b).errors
    out += ["", "Hard violations: " + ("none" if not errors else "")]
    out += [f"  - {v.message}" for v in errors]

    sa, sb = _soft(a), _soft(b)
    resolved, new_pen = [m for m in sa if m not in sb], [m for m in sb if m not in sa]
    out += ["", "Soft penalties"]
    out += [f"  resolved: {m}" for m in resolved] + [f"  new: {m} [weight {sb[m]}]" for m in new_pen]
    if not resolved and not new_pen:
        out.append("  unchanged")

    staff_a, staff_b = _staff(a), _staff(b)
    out += ["", "Staff needed"]
    if staff_a == staff_b:
        out.append("  unchanged")
    else:
        for x, y in zip(staff_a, staff_b):
            if x != y:
                out += [f"  was: {x}", f"  now: {y}"]
        out += [f"  now: {y}" for y in staff_b[len(staff_a):]]

    ua, ub = utilisation(a), utilisation(b)
    rows = []
    for room, weeks in ub.items():
        for w, pct in weeks.items():
            before_pct = ua.get(room, {}).get(w)
            if before_pct is None or abs(pct - before_pct) >= 0.5:
                was = "new" if before_pct is None else f"{before_pct:.0f}%"
                rows.append(f"  {room} week {w}: {was} -> {pct:.0f}%")
    out += ["", "Room utilisation (changes only)"] + (rows or ["  unchanged"])
    return out


def run_whatif(base_text: str, patches: list[dict], time_limit: float = 30.0) -> tuple[str, bool]:
    raw = yaml.safe_load(base_text)
    base = load_text(base_text)
    base_result = solve(base, time_limit)
    if base_result.status != "solved":
        return "The base scenario itself has no solution:\n" + "\n".join(f"  - {c}" for c in base_result.core), False
    for p in patches:
        raw = apply_patch(raw, p)
    patched = Scenario.model_validate(raw)
    patched.notes = base.notes
    result = solve(patched, time_limit)

    title = " + ".join(p.get("name", "patch") for p in patches)
    head = [f"What-if: {title}"]
    head += [f"  {p['description']}" for p in patches if p.get("description")]
    head.append("")
    if result.status == "infeasible":
        body = ["INFEASIBLE. These cannot all hold together; relax or unlock any one to make progress:"]
        body += [f"  - {c}" for c in result.core]
        return "\n".join(head + body), False
    if result.status != "solved":
        return "\n".join(head + [f"No answer within {time_limit:.0f}s."]), False
    return "\n".join(head + _diff(base_result, result)), True
