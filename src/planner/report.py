from .models import to_hhmm
from .plan import Occ, Plan, build_plan
from .models import Scenario, to_minutes


def _short(minutes: int) -> str:
    return str(minutes // 60) if minutes % 60 == 0 else to_hhmm(minutes)


def _cell(o: Occ) -> str:
    return f"{o.session.lead or o.session.id} {_short(o.start)}-{_short(o.end)}"


def _pinned(plan: Plan) -> dict[str, list[str]]:
    """room -> days a pinned person holds it."""
    out: dict[str, list[str]] = {}
    for spec in plan.scenario.rules:
        if spec.type != "pin":
            continue
        person = plan.person(spec.who)
        out[spec.room] = (person.days if person and person.days else plan.scenario.calendar.days)
    return out


def _table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
    return ["  " + "  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in rows]


def report(sc: Scenario) -> str:
    plan = build_plan(sc)
    cal = sc.calendar
    open_m, close_m = to_minutes(cal.open), to_minutes(cal.close)
    day_minutes = close_m - open_m
    pins = _pinned(plan)
    lines: list[str] = []
    for s, missing in plan.unplaced:
        lines.append(f"Note: {s.id} is not fully placed (missing {missing}) and is left out.")
    util: dict[str, dict[str, float]] = {r.id: {} for r in sc.rooms}

    for week in cal.cycle_weeks:
        lines += ["", f"=== Week {week}: rooms by day ==="]
        rows = [["room", *cal.days]]
        for room in sc.rooms:
            row = [room.id]
            busy = 0
            for day in cal.days:
                occs = [o for o in plan.occs_on(week, day) if room.id in o.rooms]
                cells = [_cell(o) for o in sorted(occs, key=lambda o: o.start)]
                if day in pins.get(room.id, []):
                    cells.append("(pinned)")
                    busy += day_minutes
                else:
                    cuts = sorted((o.start, o.end) for o in occs)
                    covered, end = 0, open_m
                    for a, b in cuts:
                        a = max(a, end)
                        covered += max(0, b - a)
                        end = max(end, b)
                    busy += covered
                row.append(", ".join(cells) or "-")
            util[room.id][week] = 100 * busy / (day_minutes * len(cal.days))
            rows.append(row)
        lines += _table(rows)

        lines += ["", f"--- Week {week}: people ---"]
        for person in sc.people:
            if person.role == "nurse" and person.id.startswith("n"):
                continue
            parts, idle = [], []
            for day in cal.days:
                if (person.days is not None and day not in person.days) or (person.unavailable_days and day in person.unavailable_days):
                    continue
                mine = sorted((o for o in plan.occs_on(week, day) if person.id in o.people), key=lambda o: o.start)
                if mine:
                    parts.append(f"{day} " + ", ".join(f"{o.session.id} {_short(o.start)}-{_short(o.end)}" for o in mine))
                else:
                    idle.append(day)
            lines.append(f"  {person.id} ({person.role}): {'; '.join(parts) or 'no sessions'}" + (f" | idle: {', '.join(idle)}" if idle else ""))

        roles = sorted({r for s in sc.sessions for r in s.staff.count})
        for role in roles:
            pool = sum(1 for p in sc.people if p.role == role)
            peaks = []
            for day in cal.days:
                occs = plan.occs_on(week, day)
                cuts = sorted({t for o in occs for t in (o.start, o.end)})
                peak = max((sum(o.session.staff.count.get(role, 0) for o in occs if o.start < b and a < o.end) for a, b in zip(cuts, cuts[1:])), default=0)
                peaks.append(f"{day} {peak}/{pool}")
            lines.append(f"  {role}s needed (peak/pool): {', '.join(peaks)}")

        idle_rooms = []
        for day in cal.days:
            free = [r.id for r in sc.rooms if r.location == "main" and "overflow_only" not in r.attributes and not any(r.id in o.rooms for o in plan.occs_on(week, day)) and day not in pins.get(r.id, [])]
            idle_rooms.append(f"{day}: {', '.join(free) or '-'}")
        lines += ["", f"--- Week {week}: idle rooms ---", *("  " + x for x in idle_rooms)]

    lines += ["", "=== Room utilisation (% of open hours) ==="]
    rows = [["room", *(f"week {w}" for w in cal.cycle_weeks)]]
    for room in sc.rooms:
        rows.append([room.id, *(f"{util[room.id][w]:.0f}%" for w in cal.cycle_weeks)])
    lines += _table(rows)
    return "\n".join(lines).lstrip("\n")
