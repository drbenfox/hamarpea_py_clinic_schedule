from pathlib import Path

from planner.checker import check
from planner.loader import load_scenario, load_text

SEED = Path(__file__).parent.parent / "scenarios" / "current.yaml"

BASE = """
calendar: {days: [sun, mon], open: "08:00", close: "18:00"}
rooms:
  - {id: r1, attributes: [drug_fridge]}
  - {id: r2}
  - {id: r4, attributes: [device_capable]}
  - {id: r5, attributes: [drug_fridge]}
people:
  - {id: doc1, role: doctor}
  - {id: doc2, role: doctor}
  - {id: n1, role: nurse, max_shifts_per_week: 1}
  - {id: n2, role: nurse}
devices:
  - {id: dev, allowed_rooms: [r4, r5]}
rules:
  - {id: fridge, type: shared_access, attribute: drug_fridge}
"""


def session(id, rooms, lead="doc1", day="sun", start="09:00", end="12:00", extra=""):
    return f"""
  - id: {id}
    lead: {lead}
    day: {day}
    start: "{start}"
    end: "{end}"
    rooms: {{primary: [{', '.join(rooms)}]}}
    {extra}"""


def run(*sessions, base=BASE):
    return check(load_text(base + "sessions:" + "".join(sessions)))


def messages(report, severity="error"):
    return [v.message for v in report.violations if v.severity == severity]


def test_seed_checks_clean():
    assert check(load_scenario(SEED)).errors == []


def test_room_double_booking():
    msgs = messages(run(session("a", ["r2"]), session("b", ["r2"], lead="doc2")))
    assert any("Double-booked room r2" in m for m in msgs)


def test_person_double_booking():
    msgs = messages(run(session("a", ["r1"]), session("b", ["r2"], start="11:00", end="13:00")))
    assert any("Double-booked person doc1" in m for m in msgs)


def test_device_double_booking():
    msgs = messages(run(
        session("a", ["r4"], extra="devices: [dev]"),
        session("b", ["r5"], lead="doc2", extra="devices: [dev]"),
    ))
    assert any("Double-booked device dev" in m for m in msgs)


def test_max_shifts_exceeded():
    msgs = messages(run(
        session("a", ["r2"], extra="staff: {named: [n1]}"),
        session("b", ["r4"], lead="doc2", day="mon", extra="staff: {named: [n1]}"),
    ))
    assert any("n1 works 2 days" in m for m in msgs)


def test_nurse_pool_exceeded():
    msgs = messages(run(session("a", ["r2"], extra="staff: {count: {nurse: 3}}")))
    assert any("needs 3 nurses" in m for m in msgs)


FRIDGE_USER = "needs_access: [drug_fridge]"
HOLD_R1 = session("liat", ["r1"], lead="doc2")


def test_device_in_fridge_room_blocks_fridge_session():
    msgs = messages(run(
        HOLD_R1,
        session("roni", ["r2"], extra=FRIDGE_USER),
        session("dev", ["r5"], lead="doc2", day="sun", extra="devices: [dev]").replace("lead: doc2", "lead: null"),
    ))
    assert any("roni needs drug_fridge" in m for m in msgs)


def test_fridge_session_holding_r5_allows_device_in_r4():
    msgs = messages(run(
        HOLD_R1,
        session("roni", ["r5"], extra=FRIDGE_USER),
        session("dev", ["r4"], lead="null", extra="devices: [dev]"),
    ))
    assert msgs == []


def test_curtain_option_downgrades_fridge_rule():
    base = BASE.replace("attribute: drug_fridge}", "attribute: drug_fridge, relaxed_by: curtain_room5}") + "options: {curtain_room5: true}\n"
    r = run(HOLD_R1, session("roni", ["r2"], extra=FRIDGE_USER), session("dev", ["r5"], lead="null"), base=base)
    assert messages(r) == []
    assert any("roni needs drug_fridge" in m for m in messages(r, "soft"))


def test_seventh_room_needs_no_code():
    base = BASE + "\n".join([])
    base = base.replace("rooms:\n", "rooms:\n  - {id: r7}\n")
    assert messages(run(session("a", ["r7"]), base=base)) == []


def test_unplaced_session_is_warning_not_crash():
    r = run("\n  - {id: free, lead: doc1, day: null, start: null, end: null}")
    assert any("free is not fully placed" in m for m in messages(r, "warning"))
