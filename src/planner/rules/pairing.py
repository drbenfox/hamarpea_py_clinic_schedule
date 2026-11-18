from ..plan import Plan
from . import register
from .base import Rule, Violation


@register
class Pairing(Rule):
    """spec: pairs [[a, b], ...]. `a` only works in sessions led by, or staffed with,
    one of their listed partners (all pairs with the same `a` form that partner set)."""

    type = "pairing"

    def check(self, plan: Plan) -> list[Violation]:
        partners: dict[str, set[str]] = {}
        for a, b in self.spec.pairs:
            partners.setdefault(plan.canon(a), set()).add(plan.canon(b))
        out = []
        for o in plan.occs:
            for a, allowed in partners.items():
                if a in o.people and not (allowed & set(o.people)):
                    out.append(self.violation(
                        f"{a} is in {o.label} without any of: {', '.join(sorted(allowed))}."
                    ))
        return out


@register
class AvoidPairing(Rule):
    """spec: people [a, b]. They should not share a session."""

    type = "avoid_pairing"

    def check(self, plan: Plan) -> list[Violation]:
        a, b = (plan.canon(p) for p in self.spec.people)
        return [
            self.violation(f"{a} and {b} are both in {o.label}.")
            for o in plan.occs if a in o.people and b in o.people
        ]


@register
class PreferPairing(Rule):
    """spec: people [a, b]. When one is in a session the other should be too."""

    type = "prefer_pairing"

    def check(self, plan: Plan) -> list[Violation]:
        a, b = (plan.canon(p) for p in self.spec.people)
        return [
            self.violation(f"{a} and {b} prefer to work together, but only one is in {o.label}.")
            for o in plan.occs if (a in o.people) != (b in o.people)
        ]
