from dataclasses import dataclass
from typing import ClassVar, Literal

from ..models import RuleSpec
from ..plan import Plan

Severity = Literal["error", "warning", "soft", "info"]


@dataclass
class Violation:
    severity: Severity
    rule: str
    message: str
    weight: int = 0


class Rule:
    """One rule type. `spec` is None for built-in rules that are always on."""

    type: ClassVar[str] = ""

    def __init__(self, spec: RuleSpec | None = None) -> None:
        self.spec = spec

    @property
    def rule_id(self) -> str:
        return self.spec.id if self.spec else self.type

    def violation(self, message: str, *, strength: str | None = None, weight: int | None = None) -> Violation:
        strength = strength or (self.spec.strength if self.spec else "hard")
        if strength == "hard":
            return Violation("error", self.rule_id, message)
        w = weight if weight is not None else (self.spec.weight if self.spec else 1)
        return Violation("soft", self.rule_id, message, w)

    def check(self, plan: Plan) -> list[Violation]:
        raise NotImplementedError
