"""Tutorial hints: ghost outlines showing where a step's shape goes (like Tinkercad's lesson hints).

In a ```commands block a hint line is one of:
  <hint box X0,Y0,Z0 X1,Y1,Z1>      the 12 edges of a box
  <hint rect X0,Y0 X1,Y1 [Z]>        a rectangle at height Z (default 0)
  <hint circle X,Y R [Z]>            a circle at height Z
  <hint line X0,Y0,Z0 X1,Y1,Z1>      a line
Values are in millimeters. The help window shows a "Show me where" link for the block; the runner
skips hint lines (but checks they parse)."""
from __future__ import annotations

import math
import re

HINT_RE = re.compile(r"<hint\s+(\w+)\s+(.*)>", re.I)
BLOCK_RE = re.compile(r"```commands\n(.*?)```", re.S)


def _nums(text: str) -> list[float]:
    return [float(v) for v in text.replace(",", " ").split()]


def hint_polylines(line: str) -> list[list[tuple]]:
    """3D polylines for one hint line. Raises ValueError if it doesn't parse."""
    m = HINT_RE.fullmatch(line.strip())
    if not m:
        raise ValueError(f"not a hint: {line!r}")
    kind, v = m.group(1).lower(), _nums(m.group(2))
    if kind == "box" and len(v) == 6:
        x0, y0, z0, x1, y1, z1 = v
        bot = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z0)]
        top = [(x, y, z1) for x, y, _ in bot]
        return [bot, top] + [[bot[i], top[i]] for i in range(4)]
    if kind == "rect" and len(v) in (4, 5):
        x0, y0, x1, y1 = v[:4]
        z = v[4] if len(v) == 5 else 0.0
        return [[(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), (x0, y0, z)]]
    if kind == "circle" and len(v) in (3, 4):
        cx, cy, r = v[:3]
        z = v[3] if len(v) == 4 else 0.0
        return [[(cx + r * math.cos(a), cy + r * math.sin(a), z)
                 for a in (i * math.tau / 48 for i in range(49))]]
    if kind == "line" and len(v) == 6:
        return [[tuple(v[:3]), tuple(v[3:])]]
    raise ValueError(f"bad hint {line!r}: use box, rect, circle or line with the right numbers")


def is_hint(line: str) -> bool:
    return line.strip().lower().startswith("<hint")


def block_hints(markdown: str) -> list[list[list[tuple]]]:
    """For each commands block: its hint polylines."""
    out = []
    for b in BLOCK_RE.findall(markdown):
        polys = []
        for ln in b.splitlines():
            if is_hint(ln):
                polys += hint_polylines(ln)
        out.append(polys)
    return out


def display_markdown(page_id: str, markdown: str) -> str:
    """The tutorial as shown: hint lines removed from blocks, a 'Show me where' link before such blocks."""
    n = [0]

    def repl(m):
        i = n[0]
        n[0] += 1
        lines = m.group(1).splitlines()
        kept = [ln for ln in lines if not is_hint(ln)]
        body = "```commands\n" + "\n".join(kept) + ("\n" if kept else "") + "```"
        if len(kept) != len(lines):
            return f"[👁 Show me where]({'hint:'}{page_id}/{i}) · [hide](hint:clear)\n\n" + body
        return body
    return BLOCK_RE.sub(repl, markdown)
