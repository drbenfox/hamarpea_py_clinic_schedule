import subprocess
from pathlib import Path


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(path.parent), *args], capture_output=True, text=True)


def info(path: Path) -> dict:
    if _git(path, "rev-parse", "--is-inside-work-tree").returncode != 0:
        return {"repo": False, "dirty": False, "history": []}
    log = _git(path, "log", "-n", "30", "--format=%h%x09%ad%x09%s", "--date=format:%Y-%m-%d %H:%M", "--", path.name)
    history = [dict(zip(("sha", "date", "subject"), ln.split("\t", 2))) for ln in log.stdout.splitlines()]
    dirty = bool(_git(path, "status", "--porcelain", "--", path.name).stdout.strip())
    return {"repo": True, "dirty": dirty, "history": history}


def commit(path: Path, message: str) -> str:
    if not message.strip():
        raise ValueError("Write a commit message.")
    if not info(path)["dirty"]:
        raise ValueError("Nothing to commit: the file matches the last commit.")
    _git(path, "add", "--", path.name)
    r = _git(path, "commit", "-m", message.strip(), "--", path.name)
    if r.returncode != 0:
        raise ValueError(r.stderr.strip() or r.stdout.strip())
    return _git(path, "rev-parse", "--short", "HEAD").stdout.strip()


def restore(path: Path, sha: str) -> None:
    if sha not in {h["sha"] for h in info(path)["history"]}:
        raise ValueError("Unknown version.")
    r = _git(path, "checkout", sha, "--", path.name)
    if r.returncode != 0:
        raise ValueError(r.stderr.strip())
