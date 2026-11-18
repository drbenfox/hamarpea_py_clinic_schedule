from pathlib import Path

from planner.checker import check
from planner.loader import load_scenario, load_text
from planner.report import report
from planner.solve import solve

from test_check import BASE, session

SEED = Path(__file__).parent.parent / "scenarios" / "current.yaml"


def scenario(*sessions, base=BASE):
    return load_text(base + "sessions:" + "".join(sessions))


def test_seed_solves_and_checks_clean():
    r = solve(load_scenario(SEED))
    assert r.status == "solved" and r.free == []
    assert check(r.scenario).errors == []


def test_open_session_gets_placed_without_conflicts():
    free = """
  - id: free
    lead: doc2
    duration: 180
    rooms: {count: 1}
    allowed_days: [sun]
"""
    r = solve(scenario(session("a", ["r1"]), free))
    assert r.status == "solved" and r.free == ["free"]
    placed = next(s for s in r.scenario.sessions if s.id == "free")
    assert placed.day == "sun" and len(placed.rooms.primary) == 1
    assert check(r.scenario).errors == []


def test_unlocking_moran_moves_her_to_a_preferred_room():
    sc = load_scenario(SEED)
    moran = next(s for s in sc.sessions if s.id == "moran_tue")
    moran.locked = {"rooms": False}
    r = solve(sc)
    placed = next(s for s in r.scenario.sessions if s.id == "moran_tue")
    assert set(placed.rooms.primary) <= {"r1", "r2"}
    assert [v for v in check(r.scenario).violations if v.severity == "soft"] == []


def test_surgery_with_one_nurse_is_infeasible_with_reason():
    base = BASE.replace("  - {id: n2, role: nurse}\n", "")
    surgery = session("surgery", ["r1", "r2"], extra="staff: {count: {nurse: 2}}")
    r = solve(scenario(surgery, base=base))
    assert r.status == "infeasible"
    assert any("Staff headcount" in c for c in r.core)
    assert any("surgery must be placed" in c for c in r.core)


def test_conflicting_locked_sessions_are_named():
    r = solve(scenario(session("a", ["r2"]), session("b", ["r2"], lead="doc2")))
    assert r.status == "infeasible"
    joined = " ".join(r.core)
    assert "a keeps its fixed" in joined and "b keeps its fixed" in joined and "No room" in joined


def test_report_utilisation():
    text = report(scenario(session("a", ["r1"])))
    assert "15%" in text  # 3h of 10h on 1 of 2 days


# ---------------------------------------------------------------- what-if
import pytest

from planner.whatif import apply_patch, load_patch, run_whatif

PATCHES = sorted((Path(__file__).parent.parent / "patches").glob("*.yaml"))
SEED_TEXT = SEED.read_text()


def whatif(*names):
    patches = [load_patch(SEED.parent.parent / "patches" / n) for n in names]
    return run_whatif(SEED_TEXT, patches)


def test_patch_ops():
    raw = {"rooms": [{"id": "r1", "attributes": ["a"]}], "options": {}}
    patch = {"changes": [
        {"op": "add", "list": "rooms", "value": {"id": "r2"}},
        {"op": "update", "list": "rooms", "id": "r1", "set": {"attributes": ["b"], "x": 1}},
        {"op": "option", "name": "flag", "value": True},
        {"op": "remove", "list": "rooms", "id": "r2"},
    ]}
    out = apply_patch(raw, patch)
    assert out == {"rooms": [{"id": "r1", "attributes": ["b"], "x": 1}], "options": {"flag": True}}
    assert raw["rooms"] == [{"id": "r1", "attributes": ["a"]}]  # input untouched
    with pytest.raises(ValueError, match="no item with id 'zz'"):
        apply_patch(raw, {"changes": [{"op": "remove", "list": "rooms", "id": "zz"}]})


@pytest.mark.parametrize("path", PATCHES, ids=lambda p: p.stem)
def test_every_patch_runs(path):
    text, _ = run_whatif(SEED_TEXT, [load_patch(path)])
    assert text.startswith("What-if:")


def test_roni_extra_day_alternates():
    text, ok = whatif("01_roni_extra_day.yaml")
    assert ok
    assert "roni_extra_a: A wed 10:00-15:00" in text
    assert "roni_extra_b: B mon 10:00-15:00" in text


def test_room5_table_is_blocked_by_nurses_until_a_fourth_is_added():
    text, ok = whatif("08_room5_table_roni.yaml")
    assert not ok and "Staff headcount never exceeds the pool" in text
    text, ok = whatif("08_room5_table_roni.yaml", "extra_nurse.yaml")
    assert ok and "roni_sun: weekly sun 10:00-15:00 in r4, r6  ->" in text


def test_curtain_screen_buys_the_device_session():
    text, ok = whatif("10_curtain_screen.yaml")
    assert ok and "new: roni_sun needs drug_fridge access" in text
    no_curtain = SEED.parent.parent / "patches" / "10_curtain_screen.yaml"
    patch = load_patch(no_curtain)
    patch["changes"][0]["value"] = False
    text, ok = run_whatif(SEED_TEXT, [patch])
    assert not ok and "Rule fridge_access" in text


def test_open_time_respects_window():
    free = """
  - id: free
    lead: doc2
    day: sun
    duration: 60
    window: ["14:00", "16:00"]
    rooms: {count: 1}
"""
    r = solve(scenario(free))
    placed = r.scenario.sessions[0]
    assert "14:00" <= placed.start and placed.end <= "16:00"
