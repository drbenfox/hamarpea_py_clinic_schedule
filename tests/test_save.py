import shutil
import subprocess
from pathlib import Path

import pytest

from planner import vcs
from planner.loader import load_text
from planner.nursing import nursing
from planner.web import Workspace
from planner.yamlsave import patch_text

SEED = Path(__file__).parent.parent / "scenarios" / "current.yaml"


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "current.yaml"
    shutil.copy(SEED, path)
    run = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    run("init", "-q"), run("config", "user.email", "t@t"), run("config", "user.name", "t")
    run("add", "."), run("commit", "-q", "-m", "start")
    return path


def test_save_keeps_comments_and_changes_only_edited_lines(repo):
    ws = Workspace(repo)
    ws.set_lock("moran_tue", "rooms", False)
    ws.solve()
    before = repo.read_text()
    ws.save()
    after = repo.read_text()
    assert not ws.state()["edited"]
    assert "# TODO" in after and after.count("\n") == before.count("\n") + 1  # one new locked line
    diff = [l for l in after.splitlines() if l not in before.splitlines()]
    assert any("primary: [r2]" in l for l in diff) and any("locked: {rooms: false}" in l for l in diff)
    assert len(diff) == 2


def test_save_roundtrips_and_unlocking_back_removes_the_line(repo):
    ws = Workspace(repo)
    ws.set_lock("moran_tue", "rooms", False)
    ws.save()
    ws2 = Workspace(repo)
    assert ws2.sc.sessions[6].locked == {"rooms": False}
    ws2.set_lock("moran_tue", "rooms", True)
    ws2.save()
    assert "locked:" not in repo.read_text().split("id: moran_tue")[1].split("id:")[0]


def test_unwritable_layout_is_refused():
    text = SEED.read_text().replace("    rooms: {primary: [r4]", "    rooms:\n      {primary: [r4]", 1)
    sc = load_text(text)
    sc.sessions[6].rooms.primary = ["r1"]
    with pytest.raises(ValueError):
        patch_text(text, sc)


def test_commit_history_and_restore(repo):
    ws = Workspace(repo)
    ws.set_lock("moran_tue", "rooms", False)
    ws.solve()
    ws.commit("Moran to r2")
    info = vcs.info(repo)
    assert info["dirty"] is False and info["history"][0]["subject"] == "Moran to r2"
    first = info["history"][-1]["sha"]
    ws.restore(first)
    assert "primary: [r2]" not in repo.read_text()
    assert next(s for s in ws.state()["sessions"] if s["id"] == "moran_tue")["rooms"]["primary"] == ["r4"]
    with pytest.raises(ValueError):
        vcs.restore(repo, "deadbee")


def test_commit_needs_message_and_changes(repo):
    with pytest.raises(ValueError, match="Nothing to commit"):
        vcs.commit(repo, "x")
    repo.write_text(repo.read_text() + "\n")
    with pytest.raises(ValueError, match="message"):
        vcs.commit(repo, " ")


def test_nursing_numbers_for_seed():
    data = nursing(load_text(SEED.read_text()))
    a, b = data["weeks"]
    assert [d["peak"] for d in a["days"]] == [3, 1, 2, 1, 2] and a["need_shifts"] == 9
    assert [d["peak"] for d in b["days"]] == [3, 0, 2, 2, 2]
    assert a["roster"]["capacity"] == 7 and a["roster"]["short_total"] == 2
    assert a["roster"]["assignment"]["tue"] and "batzi" not in sum((v for k, v in a["roster"]["assignment"].items() if k != "tue"), [])
