"""Runs the typed steps of a tutorial against a fresh drawing, so tutorials are tested like code.

A tutorial's ```commands blocks hold one input per line:
  text            typed into the command line (a command name, a value, a keyword)
  <Enter>         press Enter
  <Esc>           cancel
  <click X,Y>     click a point (X and Y in the drawing's units)
  <select X,Y>    select the object at that point before the next command
  <crossing A B>  select with a crossing window between corners A and B (e.g. for STRETCH)
  <units mm|fractional|architectural>
  <layer NAME [color] [lineweight]>   create the layer if needed and make it current
  <dimscale N>    dimension style overall scale
"""
from __future__ import annotations

import re
from dataclasses import replace

from ..commands import CommandContext, CommandRunner, GetSelection
from ..core.model import Document, Layer
from ..core.spatial import SpatialIndex
from ..core.units import UnitMode, parse_length

BLOCK_RE = re.compile(r"```commands\n(.*?)```", re.S)
UNIT_MODES = {"mm": UnitMode.MM, "fractional": UnitMode.FRACTIONAL, "architectural": UnitMode.ARCHITECTURAL}


class TutorialError(Exception):
    pass


class _View:
    def visible_rect(self):
        return (-1e5, -1e5, 1e5, 1e5)

    def pick_tolerance(self):
        return 1.0

    def zoom_extents(self):
        pass

    def zoom_factor(self, f):
        pass

    def regen(self):
        pass


def command_blocks(markdown: str) -> list[list[str]]:
    return [[ln.strip() for ln in b.splitlines() if ln.strip()] for b in BLOCK_RE.findall(markdown)]


def _point(doc: Document, text: str) -> tuple[float, float]:
    x, y = text.split(",", 1)
    u = doc.header.units
    return (parse_length(x.strip(), u), parse_length(y.strip(), u))


def run_tutorial(markdown: str, doc: Document | None = None) -> tuple[Document, list[str]]:
    """Execute every commands block. Returns the drawing and the command-line messages."""
    doc = doc or Document()
    ctx = CommandContext(doc=doc, index=SpatialIndex(doc))
    ctx.view = _View()
    from ..core.constraints import ConstraintManager
    ctx.constraints = ConstraintManager(doc)          # as in the program: constraints drive the geometry
    r = CommandRunner(ctx)
    for bi, block in enumerate(command_blocks(markdown), 1):
        for line in block:
            where = f"block {bi}, line {line!r}"
            try:
                _do(r, doc, line)
            except TutorialError:
                raise
            except Exception as exc:              # noqa: BLE001
                raise TutorialError(f"{where}: {exc}; recent messages: {ctx.messages[-4:]}") from exc
        if r.is_active and isinstance(r.request, GetSelection):
            raise TutorialError(f"block {bi} ended while {r.active.name} still asks to select objects")
    if r.is_active:
        r.cancel()
    return doc, ctx.messages


def _do(r: CommandRunner, doc: Document, line: str) -> None:
    ctx = r.ctx
    m = re.fullmatch(r"<(\w+)\s*(.*)>", line)
    if not m:
        before = len(ctx.messages)
        if r.submit_text(line) is False:
            raise TutorialError(f"{line!r} was refused: {ctx.messages[before:] or ctx.messages[-3:]}")
        return
    tok, arg = m.group(1).lower(), m.group(2).strip()
    if tok == "enter":
        if isinstance(r.request, GetSelection):
            r.submit_selection(set(ctx.selection))
        else:
            r.submit_enter()
    elif tok == "esc":
        r.cancel()
    elif tok == "units":
        with doc.transaction("units"):
            doc.set_header(replace(doc.header, units=doc.header.units.with_mode(UNIT_MODES[arg.lower()])))
    elif tok == "layer":
        parts = arg.split()
        name = parts[0]
        with doc.transaction("layer"):
            if doc.find_layer(name) is None:
                kw = {}
                if len(parts) > 1:
                    kw["color"] = int(parts[1])
                if len(parts) > 2:
                    kw["lineweight"] = float(parts[2])
                doc.add_layer(Layer(name, **kw))
            doc.set_current_layer(name)
    elif tok == "dimscale":
        with doc.transaction("dimscale"):
            doc.set_item("dimstyle", "Standard", replace(doc.dimstyle("Standard"), scale=float(arg)))
    elif tok == "click":
        r.submit_point(_point(doc, arg))
    elif tok == "select":
        hit = ctx.index.pick(_point(doc, arg), ctx.view.pick_tolerance())
        if hit is None:
            raise TutorialError(f"nothing to select at {arg}")
        ctx.selection.add(hit.handle)
    elif tok == "crossing":
        a, b = arg.split()
        p, q = _point(doc, a), _point(doc, b)
        rect = (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
        found = set(ctx.index.select_window(rect, True))
        ctx.memory["last_window"] = rect
        if isinstance(r.request, GetSelection):
            r.submit_selection(found)
        else:
            ctx.selection |= found
    else:
        raise TutorialError(f"unknown step {line!r}")
