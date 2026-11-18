from .base import Rule, Violation

REGISTRY: dict[str, type[Rule]] = {}


def register(cls: type[Rule]) -> type[Rule]:
    REGISTRY[cls.type] = cls
    return cls


# imported for their @register side effects
from . import builtin, pairing, pin, shared_access, soft  # noqa: E402,F401

__all__ = ["REGISTRY", "Rule", "Violation", "register"]
