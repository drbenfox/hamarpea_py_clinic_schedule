from ..models import to_hhmm
from ..plan import Plan
from . import register
from .base import Rule, Violation


@register
class SharedAccess(Rule):
    """spec: attribute. A session with `needs_access: [attribute]` must, at every moment,
    hold one room with that attribute or find one empty."""

    type = "shared_access"

    def check(self, plan: Plan) -> list[Violation]:
        spec = self.spec
        attr = spec.attribute
        strength, weight = spec.strength, spec.weight
        relax = getattr(spec, "relaxed_by", None)
        if relax and getattr(plan.scenario.options, relax, False):
            strength, weight = "soft", getattr(spec, "relaxed_weight", spec.weight)
        fridge_rooms = plan.rooms_with(attr)
        out = []
        for o in plan.occs:
            if attr not in (o.session.needs_access or []):
                continue
            others = [x for x in plan.occs_on(o.week, o.day) if x is not o and x.overlaps(o)]
            cuts = sorted({o.start, o.end} | {t for x in others for t in (x.start, x.end) if o.start < t < o.end})
            blocked = []
            for a, b in zip(cuts, cuts[1:]):
                active = [x for x in others if x.start < b and a < x.end]
                held = {r for x in active for r in x.rooms}
                if not any(r in o.rooms or r not in held for r in fridge_rooms):
                    blocked.append((a, b, active))
            # merge adjacent blocked stretches
            merged = []
            for a, b, active in blocked:
                if merged and merged[-1][1] == a:
                    merged[-1] = (merged[-1][0], b, merged[-1][2] | {x.session.id for x in active})
                else:
                    merged.append((a, b, {x.session.id for x in active}))
            for a, b, ids in merged:
                out.append(self.violation(
                    f"{o.session.id} needs {attr} access in week {o.week} {o.day} {to_hhmm(a)}-{to_hhmm(b)}, "
                    f"but every {attr} room ({', '.join(fridge_rooms)}) is held by other sessions ({', '.join(sorted(ids))}).",
                    strength=strength, weight=weight,
                ))
        return out
