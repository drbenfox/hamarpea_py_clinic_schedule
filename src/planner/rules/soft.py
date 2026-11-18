from itertools import combinations

from ..plan import Plan
from . import register
from .base import Rule, Violation


@register
class PreferRoom(Rule):
    """spec: optional session; rooms (preferred, at least one must be a primary room); avoid (rooms to stay out of)."""

    type = "prefer_room"

    def check(self, plan: Plan) -> list[Violation]:
        spec = self.spec
        wanted = getattr(spec, "rooms", None)
        avoid = getattr(spec, "avoid", None) or []
        only = getattr(spec, "session", None)
        out, seen = [], set()
        for o in plan.occs:
            s = o.session
            if (only and s.id != only) or s.id in seen:
                continue
            seen.add(s.id)
            primary = set(s.rooms.primary)
            if wanted and not primary & set(wanted):
                out.append(self.violation(f"{s.id} is in {', '.join(s.rooms.primary)}; preferred: {', '.join(wanted)}."))
            used = sorted(set(o.rooms) & set(avoid))
            if used:
                out.append(self.violation(f"{s.id} uses {', '.join(used)}, which should be avoided."))
        return out


@register
class Stability(Rule):
    """spec: lead. That person's week-A and week-B sessions should use the same rooms."""

    type = "stability"

    def check(self, plan: Plan) -> list[Violation]:
        lead = plan.canon(self.spec.lead)
        weeks = plan.scenario.calendar.cycle_weeks
        rooms = {
            w: {r for o in plan.occs if o.week == w and o.session.lead and plan.canon(o.session.lead) == lead for r in o.session.rooms.primary}
            for w in weeks
        }
        if len({frozenset(v) for v in rooms.values() if v}) > 1:
            detail = "; ".join(f"week {w}: {', '.join(sorted(v))}" for w, v in rooms.items())
            return [self.violation(f"{lead} uses different rooms between weeks ({detail}).")]
        return []


@register
class PreferLocation(Rule):
    """spec: location. Sessions should stay at that site."""

    type = "prefer_location"

    def check(self, plan: Plan) -> list[Violation]:
        out, seen = [], set()
        for o in plan.occs:
            if o.session.id in seen:
                continue
            seen.add(o.session.id)
            away = sorted(r for r in o.rooms if plan.room(r) and plan.room(r).location != self.spec.location)
            if away:
                out.append(self.violation(f"{o.session.id} uses {', '.join(away)}, away from {self.spec.location}."))
        return out


@register
class Mutex(Rule):
    """spec: one of sessions / people / tags, a list of ids. No two entries may overlap in time."""

    type = "mutex"

    def check(self, plan: Plan) -> list[Violation]:
        spec = self.spec
        if getattr(spec, "sessions", None):
            match = lambda o, x: o.session.id == x
            items = spec.sessions
        elif getattr(spec, "people", None):
            match = lambda o, x: plan.canon(x) in o.people
            items = spec.people
        else:
            match = lambda o, x: x in o.session.focus
            items = getattr(spec, "tags", [])
        out = []
        for x, y in combinations(items, 2):
            for a in (o for o in plan.occs if match(o, x)):
                for b in (o for o in plan.occs if match(o, y) and a.overlaps(o)):
                    out.append(self.violation(f"{x} and {y} must never overlap, but {a.label} and {b.label} do."))
        return out
