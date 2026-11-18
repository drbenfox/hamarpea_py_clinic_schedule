# Clinic room and staff planner

Plans how rooms, staff and devices are used across a two-week (A/B) clinic cycle. Scenarios are YAML; the plan lives in `scenarios/current.yaml` and git history is its version control.

## Run

```
uv sync
uv run planner check scenarios/current.yaml   # exit 1 if a hard rule is broken
uv run planner solve scenarios/current.yaml [--json out/solved.json] [--time 30]
uv run planner report scenarios/current.yaml  # room grid, people, idle time, utilisation
uv run pytest
```

## Solve

A session field is fixed when it has a value, and open when it is null or unlocked. Unlock with `locked: {day: false}`, `{time: false}` or `{rooms: false}`.

- Open time needs `duration` (minutes). Open rooms need `rooms.count`.
- Narrow the search with `allowed_days` and `allowed_rooms`.
- The solver minimises weighted soft penalties plus a small term for peak nurse headcount per day.
- When nothing fits, it prints a minimal set of rules and sessions that conflict. Relax or unlock any one of them.

`check` lists hard violations, warnings (unplaced sessions and every `TODO`/`UNCONFIRMED` comment), soft penalties with weights, and info (nurse demand per day, `ASSUMED` notes).

## Edit the scenario

- **Room:** add an entry under `rooms` (`id`, `location`, free-text `attributes`).
- **Person:** add under `people` (`role`, optional `days`, `unavailable_days`, `max_shifts_per_week`). Nurses are anonymous placeholders (`n1`..); the plan says which days nurses are needed.
- **Device:** add under `devices` with `allowed_rooms`.
- **Session:** add under `sessions`. Leave `day`/`start`/`end`/`rooms` null to mark it unplaced.
- **Rule:** add under `rules` with `id`, `type`, `strength` (`hard`/`soft`) and `weight`.

Rule types: `pin`, `shared_access`, `mutex`, `pairing`, `avoid_pairing`, `prefer_pairing`, `prefer_room`, `stability`, `prefer_location`. Per-session `rooms.preferred` becomes a soft `prefer_room` automatically.

## Add a rule type

Subclass `Rule` in `src/planner/rules/`, set `type`, decorate with `@register`, and implement `check(plan) -> list[Violation]` using `self.violation(message)`. Import its module in `rules/__init__.py`. Built-in always-on checks subclass `Builtin` in `rules/builtin.py`.
