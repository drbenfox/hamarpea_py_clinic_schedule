from pathlib import Path

import yaml

from .models import Scenario

MARKERS = ("TODO", "UNCONFIRMED", "ASSUMED")


def load_text(text: str) -> Scenario:
    scenario = Scenario.model_validate(yaml.safe_load(text) or {})
    for n, line in enumerate(text.splitlines(), start=1):
        if "#" in line and any(m in line.split("#", 1)[1] for m in MARKERS):
            scenario.notes.append((n, line.strip()))
    return scenario


def load_scenario(path: str | Path) -> Scenario:
    return load_text(Path(path).read_text())
