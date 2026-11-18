import re

from .loader import load_text
from .models import Scenario, Session


def _view(s: Session) -> tuple:
    off = frozenset(k for k, v in s.locked.items() if v is False)
    return (s.id, s.day, s.start, s.end, tuple(s.rooms.primary), off)


def _blocks(lines: list[str]) -> dict[str, tuple[int, int]]:
    """session id -> (first line, end line) inside the top-level `sessions:` list."""
    start = next(i for i, ln in enumerate(lines) if ln.startswith("sessions:"))
    out, current = {}, None
    for i in range(start + 1, len(lines) + 1):
        ln = lines[i] if i < len(lines) else "x"
        head = re.match(r"^  - id:\s*(\S+)", ln)
        if head or re.match(r"^\S", ln):
            if current:
                out[current[0]] = (current[1], i)
            current = (head.group(1), i) if head else None
            if not head and i < len(lines):
                break
    return out


def _scalar(block: list[str], key: str, new: str) -> None:
    for i, ln in enumerate(block):
        m = re.match(rf"^(    {key}:\s*)([^#\n]*?)(\s*)(#.*)?$", ln)
        if m:
            block[i] = f"{m.group(1)}{new}{m.group(3)}{m.group(4) or ''}"
            return
    block.insert(1, f"    {key}: {new}")


def _rooms(block: list[str], primary: list[str]) -> None:
    lst = "[" + ", ".join(primary) + "]"
    for i, ln in enumerate(block):
        m = re.match(r"^(    rooms:\s*\{)(.*?)(\}\s*(#.*)?)$", ln)
        if m:
            inner = m.group(2)
            if "primary:" in inner:
                inner = re.sub(r"primary:\s*\[[^\]]*\]", f"primary: {lst}", inner)
            else:
                inner = f"primary: {lst}, {inner}" if inner.strip() else f"primary: {lst}"
            block[i] = m.group(1) + inner + m.group(3)
            return
    raise ValueError("a rooms line is not in {flow: style}")


def patch_text(text: str, sc: Scenario) -> str:
    """Rewrite only the session lines that differ from `text`, keeping comments and layout."""
    before = {_view(s)[0]: _view(s) for s in load_text(text).sessions}
    lines = text.split("\n")
    for s in sc.sessions:
        now = _view(s)
        if before.get(s.id) == now:
            continue
        blocks = _blocks(lines)
        a, b = blocks[s.id]
        block = lines[a:b]
        _, day, start, end, primary, off = now
        _, o_day, o_start, o_end, o_primary, o_off = before[s.id]
        if day != o_day:
            _scalar(block, "day", day or "null")
        if start != o_start:
            _scalar(block, "start", f'"{start}"' if start else "null")
        if end != o_end:
            _scalar(block, "end", f'"{end}"' if end else "null")
        if primary != o_primary:
            _rooms(block, list(primary))
        if off != o_off:
            block = [ln for ln in block if not re.match(r"^    locked:", ln)]
            if off:
                block.insert(1, "    locked: {" + ", ".join(f"{k}: false" for k in sorted(off)) + "}")
        lines[a:b] = block
    new = "\n".join(lines)
    if {i: v for i, v in ((x.id, _view(x)) for x in load_text(new).sessions)} != {s.id: _view(s) for s in sc.sessions}:
        raise ValueError("Could not write the plan without changing its meaning; edit the YAML by hand.")
    return new
