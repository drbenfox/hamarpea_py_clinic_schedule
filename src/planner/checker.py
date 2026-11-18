from dataclasses import dataclass

from .models import RuleSpec, Scenario
from .plan import build_plan
from .rules import REGISTRY, Violation
from .rules.builtin import Builtin

ORDER = ("error", "warning", "soft", "info")


@dataclass
class Report:
    violations: list[Violation]

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    def text(self) -> str:
        titles = {"error": "HARD VIOLATIONS", "warning": "WARNINGS", "soft": "SOFT PENALTIES", "info": "INFO"}
        lines = []
        for sev in ORDER:
            items = [v for v in self.violations if v.severity == sev]
            if not items:
                continue
            lines.append(f"{titles[sev]} ({len(items)})")
            for v in items:
                suffix = f" [weight {v.weight}]" if sev == "soft" else ""
                lines.append(f"  - {v.message}{suffix}")
            lines.append("")
        if not self.errors:
            lines.append("No hard violations.")
        return "\n".join(lines)


def implicit_specs(sc: Scenario) -> list[RuleSpec]:
    """Per-session `rooms.preferred` becomes a soft prefer_room rule."""
    return [
        RuleSpec(id=f"{s.id}_preferred", type="prefer_room", strength="soft", weight=10, session=s.id, rooms=s.rooms.preferred)
        for s in sc.sessions if s.rooms.preferred
    ]


def check(scenario: Scenario) -> Report:
    plan = build_plan(scenario)
    out: list[Violation] = []
    for s, missing in plan.unplaced:
        out.append(Violation("warning", "unplaced", f"{s.id} is not fully placed (missing {missing}); skipped by the checks."))
    rules = [cls() for cls in REGISTRY.values() if issubclass(cls, Builtin)]
    for spec in scenario.rules + implicit_specs(scenario):
        if spec.type not in REGISTRY:
            out.append(Violation("warning", spec.id, f"Rule {spec.id} has unknown type '{spec.type}'; ignored."))
            continue
        rules.append(REGISTRY[spec.type](spec))
    for rule in rules:
        out.extend(rule.check(plan))
    for n, text in scenario.notes:
        sev = "info" if "ASSUMED" in text.split("#", 1)[1] and "TODO" not in text else "warning"
        out.append(Violation(sev, "open_question", f"line {n}: {text}"))
    return Report(out)
