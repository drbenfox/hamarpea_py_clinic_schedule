# Clinic room and staff planner

Plans how rooms, staff and devices are used across a two-week (A/B) clinic cycle. Scenarios are YAML; the plan lives in `scenarios/current.yaml` and git history is its version control.

## Run

```
uv sync
uv run clinic-planner check scenarios/current.yaml   # exit 1 if a hard rule is broken
uv run clinic-planner solve scenarios/current.yaml [--json out/solved.json] [--time 30]
uv run clinic-planner report scenarios/current.yaml  # room grid, people, idle time, utilisation
uv run clinic-planner whatif scenarios/current.yaml patches/01_roni_extra_day.yaml [more patches...]
uv run clinic-planner nursing                 # nurses needed per day vs the real roster
uv run clinic-planner serve                         # web UI at http://127.0.0.1:8765
uv run pytest
```

## Solve

A session field is fixed when it has a value, and open when it is null or unlocked. Unlock with `locked: {day: false}`, `{time: false}` or `{rooms: false}`.

- Open time needs `duration` (minutes). Open rooms need `rooms.count`.
- Narrow the search with `allowed_days` and `allowed_rooms`.
- The solver minimises weighted soft penalties plus a small term for peak nurse headcount per day.
- When nothing fits, it prints a minimal set of rules and sessions that conflict. Relax or unlock any one of them.

`check` lists hard violations, warnings (unplaced sessions and every `TODO`/`UNCONFIRMED` comment), soft penalties with weights, and info (nurse demand per day, `ASSUMED` notes).

## Web UI

One page: rooms by days with a Week A/B toggle, blocks coloured by lead, a room-timeline inside each cell (08-18). Click a session for details and its Day / Time / Rooms locks. Unlocked fields can be moved by Solve; moved sessions get an orange dashed outline and sessions in hard violations a red one. The side panel lists hard violations, soft penalties, open questions and info; click one to select its session.

Buttons: Check (re-run rules), Solve, Reset (reload the YAML), File…, PDF.

- **Closer row:** sales staff named in a session appear under Staff with the doctor's hours and colour (rooms are not involved). Click a block to select its session.
- **Nurses row:** the bottom row of the Gantt shows nurses needed over the day (bar height = headcount, nurses arrive `staff_prep_minutes` before a session). The dashed line is how many nurses the `roster` gives that day; bars above it turn red. Click a nurse cell for that day's shifts (who starts and finishes when) and the roster.
- **File…:** *Save to file* writes the plan back into the YAML, changing only the session lines that moved (comments are kept; it refuses if it cannot do that safely). *Save & commit* also makes a git commit of that file. History lists past versions with *Restore*. Pushing stays in the terminal.
- **PDF:** opens the browser's print dialog with one landscape page per week (the Gantt including the Nurses row). Choose "Save as PDF".
- Export JSON downloads the current plan. People, rooms, roster and rules are edited in the YAML.

## Nursing

Nurses are anonymous (`n1`..) for the solver. The real nurses and their limits live under `roster:` in the YAML; the nursing report assigns them to days to cover each day's peak and shows what is short.

## What-if patches

A patch is a YAML file in `patches/` applied in memory on top of the scenario; the base file is never changed. `whatif` solves both, then shows moved sessions, hard violations, soft penalties resolved or added, staff needed, and room utilisation changes. If the patched plan has no solution it prints the conflicting rules and sessions. Several patches can be combined, for example `08_room5_table_roni.yaml extra_nurse.yaml`.

```yaml
name: my_idea
description: One line.
changes:
  - {op: add, list: sessions, value: {id: ..., ...}}
  - {op: remove, list: sessions, id: beatrice_wed}
  - {op: update, list: rooms, id: r1, set: {attributes: [...]}}   # dicts merge, lists replace
  - {op: option, name: curtain_room5, value: true}
```

Adopting a what-if means editing `scenarios/current.yaml` and committing it.

## Edit the scenario

- **Room:** add an entry under `rooms` (`id`, `location`, free-text `attributes`).
- **Person:** add under `people` (`role`, optional `days`, `unavailable_days`, `max_shifts_per_week`). Nurses are anonymous placeholders (`n1`..); the plan says which days nurses are needed.
- **Device:** add under `devices` with `allowed_rooms`.
- **Session:** add under `sessions`. Leave `day`/`start`/`end`/`rooms` null to mark it unplaced.
- **Rule:** add under `rules` with `id`, `type`, `strength` (`hard`/`soft`) and `weight`.

Rule types: `pin`, `shared_access`, `mutex`, `pairing`, `avoid_pairing`, `prefer_pairing`, `prefer_room`, `stability`, `prefer_location`. Per-session `rooms.preferred` becomes a soft `prefer_room` automatically.

## Add a rule type

Subclass `Rule` in `src/planner/rules/`, set `type`, decorate with `@register`, and implement `check(plan) -> list[Violation]` using `self.violation(message)`. Import its module in `rules/__init__.py`. Built-in always-on checks subclass `Builtin` in `rules/builtin.py`.
