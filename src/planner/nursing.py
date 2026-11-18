from ortools.sat.python import cp_model

from .models import RosterEntry, Scenario, to_hhmm
from .plan import build_plan
from .rules.builtin import _role_demand


def _segments(plan, role: str, week: str, day: str) -> list[dict]:
    segs: list[dict] = []
    for a, b, n, ids in _role_demand(plan, role, week, day):
        if segs and segs[-1]["end"] == a and segs[-1]["need"] == n:
            segs[-1]["end"] = b
            segs[-1]["sessions"] = sorted(set(segs[-1]["sessions"]) | set(ids))
        else:
            segs.append({"start": a, "end": b, "need": n, "sessions": sorted(ids)})
    return segs


def _shifts(segs: list[dict]) -> list[dict]:
    """Layer k is one nurse; she works wherever the need is at least k."""
    out = []
    for k in range(1, max((s["need"] for s in segs), default=0) + 1):
        cur = None
        for s in segs:
            if s["need"] < k:
                continue
            if cur and cur[1] == s["start"]:
                cur[1] = s["end"]
            else:
                cur = [s["start"], s["end"]]
                out.append((k, cur))
    return [{"nurse": k, "start": to_hhmm(a), "end": to_hhmm(b), "hours": (b - a) / 60} for k, (a, b) in out]


def _allowed(e: RosterEntry, all_days: list[str]) -> list[str]:
    return [d for d in all_days if e.days is None or d in e.days]


def _assign(roster: list[RosterEntry], peaks: dict[str, int], all_days: list[str]) -> tuple[dict, dict]:
    """Cover each day's peak with named people, minimising unfilled places, then total shifts."""
    m = cp_model.CpModel()
    need_days = [d for d, n in peaks.items() if n]
    x = {(i, d): m.NewBoolVar("") for i, e in enumerate(roster) for d in _allowed(e, all_days) if d in need_days}
    short = {d: m.NewIntVar(0, peaks[d], "") for d in need_days}
    for d in need_days:
        m.Add(sum(v for (i, dd), v in x.items() if dd == d) + short[d] >= peaks[d])
    for i, e in enumerate(roster):
        if e.max_shifts is not None:
            m.Add(sum(v for (j, _), v in x.items() if j == i) <= e.max_shifts)
    m.Minimize(1000 * sum(short.values()) + sum(x.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.Solve(m)
    assignment = {d: [roster[i].name for (i, dd), v in x.items() if dd == d and solver.BooleanValue(v)] for d in need_days}
    return assignment, {d: solver.Value(v) for d, v in short.items() if solver.Value(v)}


def nursing(sc: Scenario, role: str = "nurse") -> dict:
    plan = build_plan(sc)
    days = sc.calendar.days
    roster = sc.roster.get(role, [])
    weeks = []
    for w in sc.calendar.cycle_weeks:
        rows = []
        for d in days:
            segs = _segments(plan, role, w, d)
            rows.append({
                "day": d,
                "peak": max((s["need"] for s in segs), default=0),
                "hours": sum(s["need"] * (s["end"] - s["start"]) for s in segs) / 60,
                "sessions": sorted({i for s in segs for i in s["sessions"]}),
                "shifts": _shifts(segs),
                "segments": [{**s, "start": to_hhmm(s["start"]), "end": to_hhmm(s["end"])} for s in segs],
            })
        peaks = {r["day"]: r["peak"] for r in rows}
        week = {"week": w, "days": rows, "need_shifts": sum(peaks.values()), "nurse_hours": round(sum(r["hours"] for r in rows), 1)}
        if roster:
            assignment, short = _assign(roster, peaks, days)
            week["roster"] = {
                "capacity": sum(min(e.max_shifts if e.max_shifts is not None else len(days), len(_allowed(e, days))) for e in roster),
                "assignment": assignment,
                "shortfall": short,
                "short_total": sum(short.values()),
            }
        weeks.append(week)
    return {
        "role": role,
        "pool": sum(1 for p in sc.people if p.role == role),
        "people": [e.model_dump() for e in roster],
        "weeks": weeks,
    }


def nursing_text(data: dict) -> str:
    role = data["role"]
    lines = []
    if data["people"]:
        lines.append("Roster: " + ", ".join(
            f"{p['name']} (max {p['max_shifts'] if p['max_shifts'] is not None else 'any'}" + (f", {'/'.join(p['days'])} only" if p["days"] else "") + ")"
            for p in data["people"]))
    for wk in data["weeks"]:
        r = wk.get("roster")
        head = f"Week {wk['week']}: {wk['need_shifts']} {role}-shifts needed ({wk['nurse_hours']} {role}-hours)"
        if r:
            head += f"; roster can give {r['capacity']}" + (f" -> SHORT by {r['short_total']}" if r["short_total"] else " -> covered")
        lines += ["", head]
        for d in wk["days"]:
            if not d["peak"]:
                lines.append(f"  {d['day']}  none")
                continue
            segs = "; ".join(f"{s['start']}-{s['end']} x{s['need']}" for s in d["segments"])
            shifts = ", ".join(f"{s['start']}-{s['end']}" for s in d["shifts"])
            who = ""
            if r:
                names = ", ".join(r["assignment"].get(d["day"], [])) or "nobody"
                gap = r["shortfall"].get(d["day"])
                who = f"  -> {names}" + (f"  SHORT {gap}" if gap else "")
            lines.append(f"  {d['day']}  peak {d['peak']}  {segs}  ({', '.join(d['sessions'])}){who}")
            lines.append(f"       shifts: {shifts}")
    return "\n".join(lines).lstrip("\n")
