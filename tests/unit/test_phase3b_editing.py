import math
from dataclasses import replace

import pytest

from cad.commands import CommandContext, CommandRunner
from cad.commands.grips import grips_at
from cad.core.dimedit import EditError, apply_value, editable_values, parse_value
from cad.core.model import Circle, Dimension, Document, Line, Polyline
from cad.core.spatial import SpatialIndex
from cad.core.units import UnitMode, UnitSettings


class View:
    def visible_rect(self):
        return (-500, -500, 500, 500)

    def pick_tolerance(self):
        return 1.0

    def zoom_extents(self):
        pass


@pytest.fixture
def r():
    doc = Document()
    ctx = CommandContext(doc=doc, index=SpatialIndex(doc))
    ctx.view = View()
    return CommandRunner(ctx)


def seed(doc, *e):
    with doc.transaction("s"):
        return [doc.add(x) for x in e]


def go(r, *items):
    for it in items:
        if isinstance(it, tuple):
            r.submit_point(it)
        elif it == "":
            r.submit_enter()
        else:
            assert r.submit_text(it) is not False, r.ctx.messages[-3:]


def lines(r):
    return sorted((e for e in r.ctx.doc.entities.values() if isinstance(e, Line)), key=lambda e: (e.p1, e.p2))


# ------------------------------------------------------------------ grips
def test_grip_moves_shared_corner(r):
    doc = r.ctx.doc
    a, b = seed(doc, Line(p1=(0, 0), p2=(10, 0)), Line(p1=(10, 0), p2=(10, 10)))
    targets = grips_at(doc, {a.handle, b.handle}, (10.2, 0.1), 0.5)
    assert sorted(targets) == sorted([(a.handle, "p2"), (b.handle, "p1")])
    r.ctx.memory["grip"] = ((10, 0), targets)
    go(r, "GRIPEDIT", "20,5")
    assert doc.get(a.handle).p2 == (20, 5) and doc.get(b.handle).p1 == (20, 5)
    doc.undo()
    assert doc.get(a.handle).p2 == (10, 0)


def test_grip_relative_input_and_copy(r):
    doc = r.ctx.doc
    (c,) = seed(doc, Circle(center=(0, 0), radius=5))
    r.ctx.memory["grip"] = ((5, 0), grips_at(doc, {c.handle}, (5, 0), 0.1))
    go(r, "GRIPEDIT", "@3,0")
    assert doc.get(c.handle).radius == pytest.approx(8)
    r.ctx.memory["grip"] = ((0, 0), grips_at(doc, {c.handle}, (0, 0), 0.1))
    go(r, "GRIPEDIT", "C", "100,0")
    circles = [e for e in doc.entities.values() if isinstance(e, Circle)]
    assert len(circles) == 2 and {x.center for x in circles} == {(0, 0), (100, 0)}


def test_grip_on_polyline_vertex_keeps_dimension(r):
    doc = r.ctx.doc
    (pl,) = seed(doc, Polyline(vertices=((0, 0, 0), (40, 0, 0), (40, 30, 0)), closed=False))
    go(r, "DLI", "", (20, 0), "20,-10")
    r.ctx.memory["grip"] = ((40, 0), grips_at(doc, {pl.handle}, (40, 0), 0.1))
    go(r, "GRIPEDIT", "60,0")
    d = next(e for e in doc.entities.values() if isinstance(e, Dimension))
    assert d.measurement() == pytest.approx(60)


# ------------------------------------------------------------------ trim / extend
def grid(doc):
    """Three horizontal lines cut by two vertical ones."""
    hs = seed(doc, *(Line(p1=(0, y), p2=(100, y)) for y in (0, 10, 20)))
    vs = seed(doc, Line(p1=(30, -10), p2=(30, 30)), Line(p1=(70, -10), p2=(70, 30)))
    return hs, vs


def test_trim_fence_cuts_every_crossed_line(r):
    doc = r.ctx.doc
    grid(doc)
    go(r, "TR", (50, 25), "50,-5", "", "")
    pieces = [e for e in lines(r) if e.p1[1] == e.p2[1]]
    assert len(pieces) == 6                                    # each horizontal lost its middle
    assert all(max(e.p1[0], e.p2[0]) <= 30 + 1e-9 or min(e.p1[0], e.p2[0]) >= 70 - 1e-9 for e in pieces)
    doc.undo()
    assert len([e for e in lines(r) if e.p1[1] == e.p2[1]]) == 3


def test_trim_crossing_box(r):
    doc = r.ctx.doc
    grid(doc)
    go(r, "TR", "C", "45,5", "55,15", "")
    horiz = [e for e in lines(r) if e.p1[1] == e.p2[1]]
    assert len(horiz) == 4                                     # only y=10 is cut in two


def test_shift_click_extends_during_trim(r):
    doc = r.ctx.doc
    short, wall = seed(doc, Line(p1=(0, 0), p2=(50, 0)), Line(p1=(80, -10), p2=(80, 10)))
    r.ctx.shift = True
    go(r, "TR", (45, 0))
    r.ctx.shift = False
    go(r, "")
    assert doc.get(short.handle).p2 == pytest.approx((80, 0))


def test_extend_fence(r):
    doc = r.ctx.doc
    a, b, wall = seed(doc, Line(p1=(0, 0), p2=(50, 0)), Line(p1=(0, 10), p2=(50, 10)), Line(p1=(80, -10), p2=(80, 20)))
    go(r, "EX", (45, -5), "45,15", "", "")
    assert doc.get(a.handle).p2 == pytest.approx((80, 0)) and doc.get(b.handle).p2 == pytest.approx((80, 10))


# ------------------------------------------------------------------ click the number, type a value
def test_edit_line_length_and_attached_dimension(r):
    doc = r.ctx.doc
    (ln,) = seed(doc, Line(p1=(0, 0), p2=(100, 0)))
    vals = editable_values(doc, doc.get(ln.handle))
    assert [v.kind for v in vals] == ["length"] and vals[0].value == pytest.approx(100)
    with doc.transaction("v"):
        apply_value(doc, vals[0], 250)
    assert doc.get(ln.handle).p2 == pytest.approx((250, 0))
    go(r, "DAL", "0,0", "250,0", "50,10")
    vals = editable_values(doc, doc.get(ln.handle))
    assert [v.kind for v in vals] == ["length", "dim"]
    with doc.transaction("v"):
        apply_value(doc, vals[1], 120, selected=ln.handle)
    assert doc.get(ln.handle).p2 == pytest.approx((120, 0))
    d = next(e for e in doc.entities.values() if isinstance(e, Dimension))
    assert d.measurement() == pytest.approx(120)


def test_edit_distance_between_two_walls_moves_selected(r):
    doc = r.ctx.doc
    a, b = seed(doc, Line(p1=(0, 0), p2=(0, 100)), Line(p1=(50, 0), p2=(50, 100)))
    go(r, "DLI", "0,0", "50,0", "25,-10")
    d = next(e for e in doc.entities.values() if isinstance(e, Dimension))
    target = next(v for v in editable_values(doc, doc.get(a.handle)) if v.kind == "dim")
    with doc.transaction("v"):
        apply_value(doc, target, 80, selected=a.handle)       # moves the selected (left) wall
    assert doc.get(a.handle).p1 == pytest.approx((-30, 0)) and doc.get(b.handle).p1 == pytest.approx((50, 0))
    assert doc.get(d.handle).measurement() == pytest.approx(80)
    with doc.transaction("v"):
        apply_value(doc, target, 60, selected=b.handle)
    assert doc.get(b.handle).p1 == pytest.approx((30, 0))


def test_edit_rectangle_side_stretches(r):
    doc = r.ctx.doc
    (pl,) = seed(doc, Polyline(vertices=((0, 0, 0), (40, 0, 0), (40, 30, 0), (0, 30, 0)), closed=True))
    segs = [v for v in editable_values(doc, doc.get(pl.handle)) if v.kind == "segment"]
    assert len(segs) == 4
    with doc.transaction("v"):
        apply_value(doc, segs[0], 100)
    assert [v[:2] for v in doc.get(pl.handle).vertices] == [(0, 0), (100, 0), (100, 30), (0, 30)]


def test_edit_radius_and_angle(r):
    doc = r.ctx.doc
    c, a, b = seed(doc, Circle(center=(200, 0), radius=10), Line(p1=(0, 0), p2=(100, 0)), Line(p1=(0, 0), p2=(0, 100)))
    v = editable_values(doc, doc.get(c.handle))[0]
    with doc.transaction("v"):
        apply_value(doc, v, 4)
    assert doc.get(c.handle).radius == 4
    go(r, "DAN", (50, 0), (0, 50), "20,20")
    t = next(x for x in editable_values(doc, doc.get(b.handle)) if x.kind == "dim")
    assert t.angular
    with doc.transaction("v"):
        apply_value(doc, t, math.radians(60), selected=b.handle)
    d = next(e for e in doc.entities.values() if isinstance(e, Dimension))
    assert math.degrees(d.measurement()) == pytest.approx(60)
    with pytest.raises(EditError):
        with doc.transaction("bad"):
            apply_value(doc, v, -1)


def test_typed_value_uses_revit_style(r):
    doc = r.ctx.doc
    with doc.transaction("u"):
        doc.set_header(replace(doc.header, units=UnitSettings(mode=UnitMode.ARCHITECTURAL)))
    (ln,) = seed(doc, Line(p1=(0, 0), p2=(1000, 0)))
    v = editable_values(doc, doc.get(ln.handle))[0]
    assert parse_value(doc, v, "3 4-1/2") == pytest.approx((3 * 12 + 4.5) * 25.4)
    assert parse_value(doc, v, "0 1.5") == pytest.approx(1.5 * 25.4)
