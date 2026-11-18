from ..plan import Plan
from . import register
from .base import Rule, Violation


@register
class Pin(Rule):
    """spec: who (person id) and room. The person is in that room all day on their working days."""

    type = "pin"

    def check(self, plan: Plan) -> list[Violation]:
        spec = self.spec
        person = plan.person(spec.who)
        days = (person.days if person and person.days else plan.scenario.calendar.days)
        out = []
        for o in plan.occs:
            if o.day in days and spec.room in o.rooms and plan.canon(spec.who) not in o.people:
                out.append(self.violation(
                    f"Room {spec.room} is pinned to {spec.who}, but {o.label} holds it."
                ))
        return out
