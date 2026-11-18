# Brief: clinic room and staff planner

You are building a small local tool that plans how a clinic uses its rooms, staff and devices across the week. Read this whole brief before writing code. Where it says CONFIRM, ask me rather than guessing.

## 1. What I want

A reusable constraint model I run on my own machine. I describe rooms, people, devices, sessions and rules as data. The tool then:

1. **Checks** a plan I wrote by hand and lists every rule it breaks, in plain English.
2. **Solves**: places any session I have left unplaced, or tells me why it cannot.
3. **Answers what-ifs**: "can Roni have a second day?", "what if room 1 gets a treatment bed?", "what if a nurse is off?".
4. **Reports** utilisation: which rooms and which people are idle, and when.

I must be able to add a room, a device, a doctor or a rule by editing data, not code. A new *kind* of rule may need code, but it should be one small class.

This is a planning tool for the weekly template. It is not a patient appointment system.

## 2. Stack

- Python 3.12+, managed with `uv`.
- Google OR-Tools CP-SAT for solving. Check the current OR-Tools docs for the API before using it; do not rely on memory.
- Pydantic models for the domain. Scenarios stored as YAML files I can edit by hand.
- A CLI first (`planner check`, `planner solve`, `planner whatif`, `planner report`).
- Then a local web UI: FastAPI serving one static HTML page with plain JavaScript. No build step, no frontend framework.
- `pytest` for tests.

Keep it simple. No database, no auth, no Docker, no Odoo code. Ask before adding any dependency not listed here. Small modules, type hints, no speculative abstraction.

## 3. Domain model

**Time.** Working week is Sunday to Thursday. Use 30-minute slots. The plan covers a **two-week cycle** (week A and week B), because some sessions happen every other week. Every session is tagged `weekly`, `A` or `B`.

**Location.** There are two sites. Almost everything happens at the main one. The second is barely used and is a fallback. Rooms belong to a location.

**Room.** An id plus a free list of attributes (for example `treatment_bed`, `drug_fridge`, `meeting_room`, `surgery_capable`, `device_capable`). Attributes are plain strings so I can invent new ones.

**Person.** Name, role (`doctor`, `nurse`, `sales`), and availability:
- days and hours they can work,
- maximum shifts per week (nurses are not all full time),
- days they cannot work.

**Device.** A named machine that can be in one room at a time.

**Session.** The thing being placed. Fields:
- label and lead person (optional, device sessions have none),
- week tag (`weekly` / `A` / `B`),
- day and start/end time, each either fixed or left open with allowed values,
- rooms: how many, which attributes they need, and optionally an allowed or preferred list,
- staff: named people and/or a count per role ("2 nurses"),
- devices used,
- tasks it covers (see below),
- a `locked` flag per field, so a hand-made plan loads as fully locked and I can unlock parts for the solver.

**Task.** A piece of work that must be covered but is not necessarily its own session. Example: suture removal is today done by the nurse already working with Liat, so it is a task covered by Liat's clinic session. Later it may become a separate session with its own nurse and room. Moving it from one to the other must be a data change only.

## 4. Rules

Built in, always on:
- A room, person or device is never in two sessions at once.
- People only work inside their availability and within their max shifts per week.
- A session only uses rooms that have the attributes it needs.

Data-driven rule types to implement first:
- **pin**: a person or session is always in a given room.
- **shared_access**: a session can declare that it needs access to a room attribute it may not occupy (for example `needs_access: drug_fridge`). While that session runs, the room with that attribute must either be one of the session's own rooms or be empty. A scenario-level option can downgrade this to a soft penalty (the "curtain screen" workaround), so I can compare both.
- **mutex**: two sessions, people or tags never overlap in time. Generic; not used in the seed data.
- **pairing**: a person works with a named person (Dina with Liat, Ruth with Beatrice and Roni).
- **avoid_pairing** / **prefer_pairing**: two named people should not (or should) be staffed on the same session. Hard or soft with a weight. Covers personal preferences such as a doctor who would rather not work with a particular nurse.
- **prefer_room** (soft): a session prefers certain rooms.
- **stability** (soft): the same session uses the same rooms in week A and week B.
- **prefer_location** (soft): use the main site unless there is no other way.

Every rule is `hard` or `soft` with a weight. Rule types live in a registry: one class per type, each turning its YAML entry into CP-SAT constraints or objective terms, and each able to describe a violation in a sentence.

## 5. Behaviour

- `check`: load a fully placed plan, report violations and warnings. No solving.
- `solve`: place unlocked sessions. Objective is the weighted soft rules.
- When there is no solution, **explain it**: name the smallest set of rules and sessions that conflict you can find (assumption literals or iterative relaxation). "Infeasible" alone is not acceptable.
- `whatif`: apply a small patch file to a scenario (add a session, change a room, remove a person) and show the difference from the base plan.
- `report`: room-by-day grid for week A and B, per-person schedule, idle rooms and idle staff by day, and a utilisation percentage per room.
- Export the solved plan as JSON. A future Odoo module may import it; do not build that now.

## 6. UI (second milestone)

One page. A grid of rooms by days with a week A/B toggle, coloured by lead person. Clicking a session shows its details and lets me lock or unlock it. A side panel lists violations. Buttons: Check, Solve, Reset. Editing people, rooms and rules can stay in YAML for now.

## 7. Seed scenario: the current hand-made plan

I am supplying `clinic.yaml` alongside this brief. It is the source of truth and I will keep editing it; where it disagrees with the tables below, the YAML wins. Use it as `scenarios/current.yaml`. Build the Pydantic models to load it as written. If you think the schema should change, propose the change and wait for my answer. `null` values marked TODO are unknowns: the loader must accept them and `check` must list them as warnings, not crash. Its `appointment_types` and `proposals` sections are for later; load and preserve them but do not model patient flow inside a session yet.

It should pass `check` with no hard violations.

**Rooms (main site)**

| Room | Notes |
|---|---|
| 1 | Has a fridge. No treatment bed: Liat had it removed by choice, so putting one back is her call |
| 2 | Treatment room |
| 3 | Meeting room, not a clinic room. Dina is always here |
| 4 | Treatment room, surgery-capable, device-capable |
| 5 | Treatment room that also holds the drug fridge. Has no table, so it does not suit a doctor's clinic as it stands. Surgery-capable, device-capable |
| 6 | Treatment room, surgery-capable, device-capable |

The fridge is the reason for my handwritten rule "no devices while Roni is working": staff working in rooms 4 and 6 need to walk into room 5 for drugs, so room 5 cannot host a private treatment at the same time. Model the cause, not the symptom: use `shared_access` on the fridge, not a Roni-vs-devices mutex. A curtain screen in room 5 is a possible workaround that I consider suboptimal, so it is a soft, penalised option that is off by default.

The fit-out has only just been finished, so fridge positions and room layout are fixed. Do not propose building changes; work with scheduling and loose furniture only.

There are two fridges (rooms 1 and 5), so `shared_access` must be satisfied by **any one** room carrying the attribute, not a specific room. CONFIRM: whether the two fridges are interchangeable (same stock) or each serves particular doctors; if not interchangeable, give them distinct attributes.

CONFIRM: which sessions need fridge access (Roni yes, Moran no; Beatrice, Liat's clinic?). CONFIRM: rooms at the second site.

**Doctors**

| Doctor | When | Rooms | Works with |
|---|---|---|---|
| Liat | Clinic Sun and Wed 10:00–18:00 | 1 and 2 | Dina, 1 nurse (that nurse also removes sutures) |
| Liat | Out of office Tue | | |
| Liat | Surgery Thu 08:00–17:00 | 4, 5 and 6 (needs 3 rooms) | 2 nurses |
| Beatrice | Week A Mon, week B Wed, 09:00–16:00 | 5–6 on my grid, 6 in my notes (CONFIRM) | Ruth, 1 nurse |
| Roni | Clinic Sun 10:00–15:00 | Wants 2 rooms; currently 4 and 6 | Ruth, 2 nurses |
| Moran | Clinic Tue 10:00–15:00, consultations only | Currently 4; she should be in 1 or 2. Needs no treatment bed and no fridge access | Works alone |

**Sales**
- Dina: works with Liat. Always in room 3, closing surgery sales and talking to clients. CONFIRM which days.
- Ruth: works with Beatrice and Roni.

**Nurses**: Daria, Stav, Batzi. They assist doctors and run devices. Not all full time. CONFIRM for each: max shifts per week and any day restrictions. Use placeholders clearly marked TODO until I supply them.

**Devices**: Sofwave and Morpheus. Nurse-run consults and treatments. Any of rooms 4–6. Today they never run while Roni is working, because of fridge access (see Rooms). Currently Tuesday: device in room 5, consults in room 6. CONFIRM hours.

**Rules to seed**
- pin: Dina in room 3 (hard).
- shared_access: sessions that need the drug fridge vs anything else occupying room 5 (hard; curtain option off).
- pairing: Dina–Liat; Ruth–Beatrice; Ruth–Roni.
- Surgery needs 3 surgery-capable rooms and 2 nurses (hard).
- Prefer main site (soft, heavy weight).

**Clinic hours**: assume 08:00–18:00 Sun–Thu. CONFIRM.

## 8. First what-ifs to ship as patch files

1. **Roni extra day**: add a second weekly Roni clinic and let the solver pick the day. Expected: only the Mon/Wed that Beatrice is not using works, because they share Ruth.
2. **Moran moves to room 1 on Tuesday** (consultation only, so the missing bed does not matter), freeing room 4 for a second device room and keeping room 2 spare.
3. **Extra device sessions**: Sunday after 15:00, Monday, Wednesday in room 4.
4. **Room 1 gets a treatment bed.**
5. **Beatrice on a fixed weekly day** instead of alternating.
6. **Dina moves to the second site**, releasing room 3.
7. **Suture removal becomes its own session** with its own nurse and room.
8. **Room 5 gets a table and Roni takes it as one of her two rooms** (5+6 or 4+5), so the fridge is inside her own space and the remaining room is free for a device.
9. **Roni flow model** (my idea, not yet agreed): Roni's clinic holds rooms 4, 5 and 6 as one block. Rooms 4 and 6 are full treatment rooms, so she consults and injects in either, alternating between them while Ruth closes the sale in the room she has just left. A nurse preps injections at the fridge in room 5, which also serves as overflow: incoming patients waiting, and treatment-only patients (already consulted and paid) who need no consult or sales close. For the weekly planner this is simply a Roni session with two primary rooms (4, 6) and one attached overflow room (5), with the fridge inside her block. Support an optional `overflow` role on a session's rooms; do not model the patient flow inside the session.
10. **Curtain screen in room 5**: turn the fridge rule soft and show what it buys.

## 9. Acceptance tests

- `current.yaml` checks clean.
- Double-booking a room, a person or a device is each caught and described.
- A nurse over her max shifts is caught.
- A device session in room 5 while a fridge-needing session runs in other rooms is caught; the same device session in room 4 or 6 while that session holds room 5 is allowed.
- Surgery with only 1 nurse available is reported infeasible with the reason.
- What-if 1 returns the expected alternating answer.
- Adding a seventh room in YAML needs no code change.

## 10. How to work

1. Start by restating the model back to me in a few lines and listing your CONFIRM questions.
2. Milestone 1: domain models, YAML loading, `check`, tests.
3. Milestone 2: `solve`, infeasibility explanation, `report`.
4. Milestone 3: `whatif` and the patch files above.
5. Milestone 4: the web UI.

Stop after each milestone and show me the output on the seed scenario before continuing. Write a short README covering how to run it, how to add a room, person, device or rule, and how to add a new rule type.
