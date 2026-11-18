from collections import defaultdict
from itertools import combinations

from ..models import to_hhmm, to_minutes
from ..plan import Plan
from . import register
from .base import Rule, Violation


class Builtin(Rule):
    """Always-on rule; not selectable from YAML."""


@register
class References(Builtin):
    type = "references"

    def check(self, plan: Plan) -> list[Violation]:
        sc = plan.scenario
        out = []
        locs = {loc.id for loc in sc.locations}
        for r in sc.rooms:
            if locs and r.location not in locs:
                out.append(self.violation(f"Room {r.id} is in unknown location '{r.location}'."))
        for d in sc.devices:
            for rid in d.allowed_rooms:
                if not plan.room(rid):
                    out.append(self.violation(f"Device {d.id} allows unknown room '{rid}'."))
        devices = {d.id for d in sc.devices}
        for s in sc.sessions:
            for rid in s.rooms.primary + s.rooms.overflow + s.rooms.preferred:
                if not plan.room(rid):
                    out.append(self.violation(f"Session {s.id} uses unknown room '{rid}'."))
            for pid in ([s.lead] if s.lead else []) + s.staff.named:
                if not plan.person(pid):
                    out.append(self.violation(f"Session {s.id} names unknown person '{pid}'."))
            for did in s.devices or []:
                if did not in devices:
                    out.append(self.violation(f"Session {s.id} uses unknown device '{did}'."))
            for role in s.staff.count:
                if not any(p.role == role for p in sc.people):
                    out.append(self.violation(f"Session {s.id} needs role '{role}' but nobody has it."))
        return out


@register
class CalendarFit(Builtin):
    type = "calendar_fit"

    def check(self, plan: Plan) -> list[Violation]:
        cal = plan.scenario.calendar
        opens, closes = to_minutes(cal.open), to_minutes(cal.close)
        out = []
        for o in plan.occs:
            if o.week != plan.scenario.calendar.cycle_weeks[0] and o.session.weeks == "weekly":
                continue  # report weekly sessions once
            s = o.session
            if o.day not in cal.days:
                out.append(self.violation(f"{s.id} is on '{o.day}', which is not a working day."))
            if o.end <= o.start:
                out.append(self.violation(f"{s.id} ends ({s.end}) before it starts ({s.start})."))
            if o.start < opens or o.end > closes:
                out.append(self.violation(f"{s.id} runs {s.start}-{s.end}, outside clinic hours {cal.open}-{cal.close}."))
            if o.start % cal.slot_minutes or o.end % cal.slot_minutes:
                out.append(self.violation(f"{s.id} does not align to {cal.slot_minutes}-minute slots.", strength="soft", weight=1))
        return out


@register
class DoubleBooking(Builtin):
    type = "double_booking"

    def check(self, plan: Plan) -> list[Violation]:
        out = []
        for kind, key in (("room", lambda o: o.rooms), ("person", lambda o: o.people), ("device", lambda o: o.devices)):
            for a, b in combinations(plan.occs, 2):
                if not a.overlaps(b):
                    continue
                for shared in sorted(set(key(a)) & set(key(b))):
                    if a.session.id == b.session.id:
                        continue
                    lo, hi = max(a.start, b.start), min(a.end, b.end)
                    out.append(self.violation(
                        f"Double-booked {kind} {shared}: {a.session.id} and {b.session.id} "
                        f"overlap in week {a.week} on {a.day} {to_hhmm(lo)}-{to_hhmm(hi)}."
                    ))
        return out


@register
class Availability(Builtin):
    type = "availability"

    def check(self, plan: Plan) -> list[Violation]:
        out = []
        seen = set()
        for o in plan.occs:
            for pid in o.people:
                p = plan.person(pid)
                if not p or (pid, o.session.id, o.day) in seen:
                    continue
                seen.add((pid, o.session.id, o.day))
                if p.unavailable_days and o.day in p.unavailable_days:
                    out.append(self.violation(f"{pid} is unavailable on {o.day} but is in {o.session.id}."))
                if p.days is not None and o.day not in p.days:
                    out.append(self.violation(f"{pid} does not work on {o.day} but is in {o.session.id}."))
        return out


@register
class MaxShifts(Builtin):
    type = "max_shifts"

    def check(self, plan: Plan) -> list[Violation]:
        days = defaultdict(set)
        for o in plan.occs:
            for pid in o.people:
                days[(pid, o.week)].add(o.day)
        out = []
        for (pid, week), d in sorted(days.items()):
            p = plan.person(pid)
            if p and p.max_shifts_per_week is not None and len(d) > p.max_shifts_per_week:
                out.append(self.violation(
                    f"{pid} works {len(d)} days in week {week} ({', '.join(sorted(d))}); "
                    f"max is {p.max_shifts_per_week}."
                ))
        return out


@register
class RoomNeeds(Builtin):
    type = "room_needs"

    def check(self, plan: Plan) -> list[Violation]:
        out = []
        for s in plan.scenario.sessions:
            for rid in s.rooms.primary:
                room = plan.room(rid)
                missing = [a for a in s.room_needs if room and a not in room.attributes]
                if missing:
                    out.append(self.violation(f"{s.id} needs {', '.join(missing)} but room {rid} lacks it."))
            for did in s.devices or []:
                dev = next((d for d in plan.scenario.devices if d.id == did), None)
                if dev and not set(s.rooms.primary) & set(dev.allowed_rooms):
                    out.append(self.violation(f"{s.id} uses {did}, which is not allowed in {', '.join(s.rooms.primary)}."))
        return out


def _role_demand(plan: Plan, role: str, week: str, day: str) -> list[tuple[int, int, int, list[str]]]:
    """(start, end, headcount, session ids) for each stretch of the day."""
    occs = plan.occs_on(week, day)
    cuts = sorted({t for o in occs for t in (o.start, o.end)})
    named = {p.id for p in plan.scenario.people if p.role == role}
    rows = []
    for a, b in zip(cuts, cuts[1:]):
        active = [o for o in occs if o.start < b and a < o.end]
        n = sum(o.session.staff.count.get(role, 0) + len(set(o.people) & named) for o in active)
        if n:
            rows.append((a, b, n, [o.session.id for o in active if o.session.staff.count.get(role, 0) or set(o.people) & named]))
    return rows


@register
class StaffPool(Builtin):
    type = "staff_pool"

    def check(self, plan: Plan) -> list[Violation]:
        out = []
        roles = {r for s in plan.scenario.sessions for r in s.staff.count}
        for role in sorted(roles):
            pool = sum(1 for p in plan.scenario.people if p.role == role)
            for week in plan.scenario.calendar.cycle_weeks:
                for day in plan.scenario.calendar.days:
                    for a, b, n, ids in _role_demand(plan, role, week, day):
                        if n > pool:
                            out.append(self.violation(
                                f"Week {week} {day} {to_hhmm(a)}-{to_hhmm(b)} needs {n} {role}s "
                                f"({', '.join(ids)}) but the pool has {pool}."
                            ))
        return out


@register
class StaffDemand(Builtin):
    type = "staff_demand"

    def check(self, plan: Plan) -> list[Violation]:
        out = []
        cal = plan.scenario.calendar
        roles = sorted({r for s in plan.scenario.sessions for r in s.staff.count})
        for role in roles:
            for week in cal.cycle_weeks:
                peaks = {d: max((n for *_, n, _ in _role_demand(plan, role, week, d)), default=0) for d in cal.days}
                shifts = sum(
                    o.session.staff.count.get(role, 0)
                    for o in plan.occs if o.week == week
                )
                per_day = ", ".join(f"{d} {n}" for d, n in peaks.items())
                out.append(Violation("info", "staff_demand", f"{role}s needed, week {week}: {per_day} | {shifts} {role}-shifts total"))
        return out
