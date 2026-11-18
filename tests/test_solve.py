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
