from pathlib import Path

from planner.web import Workspace

SEED = Path(__file__).parent.parent / "scenarios" / "current.yaml"


def test_state_has_everything_the_page_needs():
    st = Workspace(SEED).state()
    assert len(st["sessions"]) == 9 and st["calendar"]["days"][0] == "sun"
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
