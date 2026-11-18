from pathlib import Path

from planner.web import Workspace

SEED = Path(__file__).parent.parent / "scenarios" / "current.yaml"


def test_state_has_everything_the_page_needs():
    st = Workspace(SEED).state()
    assert len(st["sessions"]) == 8 and st["calendar"]["days"][0] == "sun"
    assert st["pins"] == [{"room": "r3", "who": "dina", "days": ["sun", "mon", "tue", "wed", "thu"]}]
    assert not st["edited"] and st["notice"] is None
    assert any(v["severity"] == "soft" and v["sessions"] == ["moran_tue"] for v in st["violations"])


def test_unlock_then_solve_moves_session_and_reset_restores():
    ws = Workspace(SEED)
    ws.set_lock("moran_tue", "rooms", False)
    st = ws.state()
    moran = next(s for s in st["sessions"] if s["id"] == "moran_tue")
    assert st["edited"] and moran["locks"]["rooms"] is False and moran["locks"]["day"] is True
    ws.solve()
    st = ws.state()
    assert st["notice"]["kind"] == "solved" and st["changed"] == ["moran_tue"]
    assert next(s for s in st["sessions"] if s["id"] == "moran_tue")["rooms"]["primary"][0] in ("r1", "r2")
    ws.reset()
    st = ws.state()
    assert not st["edited"] and st["changed"] == []


def test_infeasible_solve_keeps_plan_and_reports_core(tmp_path):
    text = SEED.read_text().replace("  - id: n2\n    role: nurse\n", "").replace("  - id: n3\n    role: nurse\n", "")
    path = tmp_path / "s.yaml"
    path.write_text(text)
    ws = Workspace(path)
    ws.solve()
    assert ws.notice["kind"] == "infeasible" and ws.notice["core"]
    assert not ws.state()["edited"]


def test_bulk_unlock_and_lock():
    ws = Workspace(SEED)
    ws.set_lock(None, None, False)
    assert all(not any(s["locks"].values()) for s in ws.state()["sessions"])
    ws.set_lock(None, None, True)
    assert all(all(s["locks"].values()) for s in ws.state()["sessions"])


def test_state_carries_the_nurse_row():
    nursing = Workspace(SEED).state()["nursing"]
    sun = nursing["weeks"][0]["days"][0]
    assert sun["peak"] == 3 and sun["shifts"][0]["start"] == "09:30"
    assert nursing["weeks"][0]["roster"]["short_total"] == 1


def test_closers_work_the_doctors_hours_and_link_to_the_doctor():
    closers = Workspace(SEED).state()["closers"]
    assert closers["people"] == ["dina", "ruth"]
    sun = {i["person"]: i for i in closers["weeks"][0]["days"][0]["items"]}
    assert (sun["dina"]["doctor"], sun["dina"]["start"], sun["dina"]["end"], sun["dina"]["office"]) == ("liat", "10:00", "18:00", "r3")
    assert (sun["ruth"]["doctor"], sun["ruth"]["start"], sun["ruth"]["end"]) == ("roni", "10:00", "15:00")
    week_b_wed = {i["person"]: i["doctor"] for i in closers["weeks"][1]["days"][3]["items"]}
    assert week_b_wed == {"dina": "liat", "ruth": "beatrice"}
    assert closers["weeks"][0]["days"][1]["items"][0]["doctor"] == "beatrice"  # Monday, week A
