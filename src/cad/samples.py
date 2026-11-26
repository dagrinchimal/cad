"""Sample drawings for tests, screenshots and exporter validation (no Qt needed).

`rich_document()` uses every kind of object the program has, on several layers, with a layout sheet.
"""
from __future__ import annotations

from dataclasses import replace

from .commands import CommandContext, CommandRunner
from .core.layouts import create_layout
from .core.model import (
    Circle, Document, Ellipse, Hatch, Layer, Line, MText, Point, Polyline, Spline, Text,
)
from .core.spatial import SpatialIndex


class _View:
    def visible_rect(self):
        return (-1000, -1000, 1000, 1000)

    def pick_tolerance(self):
        return 0.5

    def zoom_extents(self):
        pass


def _runner(doc: Document) -> CommandRunner:
    ctx = CommandContext(doc=doc, index=SpatialIndex(doc))
    ctx.view = _View()
    return CommandRunner(ctx)


def _go(r: CommandRunner, *items) -> None:
    for it in items:
        if isinstance(it, tuple):
            r.submit_point(it)
        elif it == "":
            r.submit_enter()
        else:
            if r.submit_text(it) is False:
                raise RuntimeError(f"sample drawing: {it!r} rejected: {r.ctx.messages[-3:]}")
    if r.is_active:
        r.cancel()


def rich_document(with_layout: bool = True) -> Document:
    """About 40 objects: lines, arcs, circles, bulged polylines, ellipse, spline, point, text, mtext,
    solid and pattern hatches, every dimension type, a leader, a block with an attribute, a live array,
    colors (index and RGB), linetypes, lineweights, and a layout with a viewport."""
    doc = Document()
    r = _runner(doc)
    with doc.transaction("Sample layers"):
        doc.add_layer(Layer("Walls", color=7, lineweight=0.5))
        doc.add_layer(Layer("Center", color=1, linetype="CENTER"))
        doc.add_layer(Layer("Hidden", color=5, linetype="HIDDEN"))
        doc.add_layer(Layer("Hatch", color=8))
        doc.add_layer(Layer("Dims", color=2))
        doc.add_layer(Layer("Text", color=3))
        doc.add_layer(Layer("NoPlot", color=6, plot=False))
        doc.add_layer(Layer("Off", color=4, on=False))
    with doc.transaction("Sample objects"):
        room = doc.add(Polyline(vertices=((0, 0, 0), (200, 0, 0), (200, 120, 0), (0, 120, 0)), closed=True,
                                layer="Walls"))
        doc.add(Line(p1=(100, 0), p2=(100, 80), layer="Walls"))
        doc.add(Line(p1=(-20, 60), p2=(220, 60), layer="Center"))
        doc.add(Line(p1=(0, -10), p2=(200, -10), layer="Hidden", lineweight=0.35))
        doc.add(Circle(center=(50, 60), radius=20, color=1))
        doc.add(Circle(center=(150, 90), radius=12, color="#3080ff"))
        doc.add(Polyline(vertices=((120, 10, 0), (170, 10, 0.5), (170, 40, 0), (120, 40, 0)), closed=True,
                         color=4, lineweight=0.7))
        doc.add(Ellipse(center=(260, 60), major=(30, 10), ratio=0.5))
        doc.add(Ellipse(center=(260, 10), major=(20, 0), ratio=0.6, start_param=0.0, end_param=3.14159))
        doc.add(Spline.through([(230, 100), (250, 130), (280, 110), (300, 140)]))
        doc.add(Point(position=(300, 0)))
        doc.add(Text(insert=(20, 100), text="LIVING ROOM", height=5, layer="Text"))
        doc.add(Text(insert=(150, 60), text="Ø24 ±0.1°", height=3, rotation=0.3, halign="center", layer="Text"))
        doc.add(MText(insert=(110, 115), text="Note one\nSecond line of the note", width=80, height=3, layer="Text"))
        doc.add(Line(p1=(0, 200), p2=(50, 200), layer="NoPlot"))
        doc.add(Line(p1=(0, 210), p2=(50, 210), layer="Off"))
        sq = doc.add(Polyline(vertices=((320, 0, 0), (360, 0, 0), (360, 40, 0), (320, 40, 0)), closed=True))
        doc.add(Hatch(loops=(((320, 50, 0), (360, 50, 0), (360, 90, 0), (320, 90, 0)),), pattern="SOLID",
                      color=30, layer="Hatch"))
    with doc.transaction("layer"):
        doc.set_current_layer("Hatch")
    _go(r, "H", "P", "ANSI31", "SC", "4", (340, 20), "")
    with doc.transaction("layer"):
        doc.set_current_layer("Dims")
    _go(r, "DLI", "0,0", "200,0", "100,-25")
    _go(r, "DAL", "200,0", "200,120", "215,60")
    _go(r, "DRA", (50, 80), "65,95")
    _go(r, "DDI", (162, 90), "175,100")
    a, b = Line(p1=(0, 150), p2=(60, 150), layer="Walls"), Line(p1=(0, 150), p2=(40, 190), layer="Walls")
    with doc.transaction("lines"):
        doc.add(a)
        doc.add(b)
    _go(r, "DAN", (50, 150), (20, 170), "45,165")
    _go(r, "DOR", "200,120", "200,140")
    _go(r, "LE", "150,90", "180,150", "", "Check size")
    with doc.transaction("layer"):
        doc.set_current_layer("0")
    # a block with an attribute, and two inserts
    with doc.transaction("door"):
        d1 = doc.add(Line(p1=(0, 0), p2=(20, 0)))
        d2 = doc.add(Polyline(vertices=((0, 0, 0), (0, 20, 0)), closed=False, color=0))
    _go(r, "ATT", "NUM", "Door number?", "D1", "0,-5", "2.5")
    att = max(doc.entities)               # newest handle
    r.ctx.selection = {d1.handle, d2.handle, att}
    _go(r, "B", "Door", "0,0", "")
    _go(r, "I", "Door", "S", "1", "400,0", "D7")
    _go(r, "I", "Door", "S", "1.5", "R", "90", "450,0", "D8")
    # a live array of the circle
    c = next(e for e in doc.entities.values() if isinstance(e, Circle) and e.radius == 20)
    r.ctx.selection = {c.handle}
    _go(r, "ARRAYRECT", "1", "2", "-60")
    if with_layout:
        with doc.transaction("Layout"):
            create_layout(doc, "Sheet A3", "ISO A3")
    doc.mark_saved()
    return doc


__all__ = ["rich_document"]
