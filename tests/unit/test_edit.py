import math

import pytest

from cad.core.edit import (
    Curve, EditError, break_at, break_between, chamfer_lines, explode, extend, fillet_curves, fillet_lines,
    fillet_polyline, join, offset, trim,
)
from cad.core.geom2d import Seg
from cad.core.model import Arc, Circle, Document, Ellipse, Line, Polyline, Spline

A = pytest.approx


def P(p):
    return pytest.approx(p, abs=1e-6)


def test_trim_line_between_cutters():
    e = Line(p1=(0, 0), p2=(10, 0))
    cutters = [Seg((3, -1), (3, 1)), Seg((7, -1), (7, 1))]
    out = trim(e, cutters, (5, 0))
    assert [(x.p1, x.p2) for x in out] == [(P((0, 0)), P((3, 0))), (P((7, 0)), P((10, 0)))]
    out = trim(e, cutters, (1, 0))
    assert len(out) == 1 and out[0].p1 == P((3, 0))
    assert trim(e, [Seg((20, -1), (20, 1))], (5, 0)) is None


def test_trim_circle_becomes_arc():
    c = Circle(center=(0, 0), radius=5)
    out = trim(c, [Seg((-10, 0), (10, 0))], (0, 5))      # remove the top half
    assert len(out) == 1 and isinstance(out[0], Arc)
    assert out[0].sweep == A(math.pi)
    assert out[0].midpoints()[0] == P((0, -5))


def test_trim_polyline_with_arc():
    pl = Polyline(vertices=((0, 0, 0), (10, 0, 1.0), (10, 10, 0), (0, 10, 0)))
    out = trim(pl, [Seg((5, -1), (5, 1))], (2, 0))
    assert len(out) == 1
    assert out[0].vertices[0][:2] == P((5, 0)) and out[0].vertices[-1][:2] == P((0, 10))
    assert out[0].vertices[1][2] == A(1.0)


def test_break_and_break_at():
    e = Line(p1=(0, 0), p2=(10, 0))
    a, b = break_between(e, (2, 0), (4, 0))
    assert a.p2 == P((2, 0)) and b.p1 == P((4, 0))
    a, b = break_at(e, (6, 0))
    assert a.p2 == P((6, 0)) and b.p1 == P((6, 0))
    (arc,) = break_between(Circle(center=(0, 0), radius=1), (1, 0), (0, 1))
    assert arc.sweep == A(3 * math.pi / 2)
    with pytest.raises(EditError):
        break_at(Circle(center=(0, 0), radius=1), (1, 0))


def test_extend_line_arc_polyline():
    b = [Seg((10, -5), (10, 5))]
    assert extend(Line(p1=(0, 0), p2=(5, 0)), b, (4, 0)).p2 == P((10, 0))
    assert extend(Line(p1=(0, 0), p2=(5, 0)), b, (1, 0)) is None     # start end: nothing behind
    arc = Arc(center=(0, 0), radius=5, start_angle=math.radians(100), end_angle=math.radians(170))
    ext = extend(arc, [Seg((-10, 0), (10, 0))], (-4.9, 0.9))
    assert ext.end_angle == A(math.pi)
    pl = Polyline(vertices=((0, 0, 0), (2, 0, 0), (2, 2, 0)))
    assert extend(pl, [Seg((-5, 6), (5, 6))], (2, 1.9)).vertices[-1][:2] == P((2, 6))


def test_offset_all_types():
    assert offset(Line(p1=(0, 0), p2=(10, 0)), 2, (5, 5)).p1 == P((0, 2))
    assert offset(Line(p1=(0, 0), p2=(10, 0)), 2, (5, -5)).p1 == P((0, -2))
    assert offset(Circle(center=(0, 0), radius=5), 1, (0, 0)).radius == A(4)
    assert offset(Circle(center=(0, 0), radius=5), 1, (9, 0)).radius == A(6)
    with pytest.raises(EditError):
        offset(Circle(center=(0, 0), radius=1), 2, (0, 0))
    sq = Polyline(vertices=((0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)), closed=True)
    inner = offset(sq, 1, (5, 5))
    assert abs(inner.area()) == A(64)
    outer = offset(sq, 1, (20, 5))
    assert abs(outer.area()) == A(144)
    rounded = Polyline(vertices=((0, 0, 0), (10, 0, 1.0), (10, 10, 0)))
    o = offset(rounded, 1, (5, 5))
    assert len(o.vertices) == 3
    assert isinstance(offset(Ellipse(center=(0, 0), major=(10, 0), ratio=0.5), 1, (0, 0)), Polyline)
    assert isinstance(offset(Spline.through([(0, 0), (5, 5), (10, 0)]), 1, (5, 0)), Spline)


def test_fillet_and_chamfer_lines():
    l1 = Line(p1=(0, 0), p2=(10, 0))
    l2 = Line(p1=(12, 2), p2=(12, 10))           # doesn't touch: fillet extends
    a, b, arc = fillet_lines(l1, (5, 0), l2, (12, 8), 2)
    assert a.p2 == P((10, 0)) and b.p1 == P((12, 2)) or b.p2 == P((12, 2))
    assert arc.radius == A(2) and arc.center == P((10, 2))
    a, b, arc = fillet_lines(l1, (5, 0), l2, (12, 8), 0)
    assert arc is None and (a.p2 == P((12, 0)))
    a, b, ch = chamfer_lines(l1, (5, 0), l2, (12, 8), 1, 2)
    assert ch.p1 == P((11, 0)) and ch.p2 == P((12, 2))
    with pytest.raises(EditError):
        fillet_lines(l1, (1, 0), Line(p1=(0, 1), p2=(10, 1)), (1, 1), 1)


def test_fillet_line_and_circle():
    l = Line(p1=(-10, 0), p2=(10, 0))
    c = Circle(center=(0, 5), radius=2)
    a, b, arc = fillet_curves(l, (-5, 0), c, (-2, 5), 2)
    assert arc.radius == A(2)
    assert abs(arc.center[1] - 2) < 1e-6           # radius above the line
    assert math.dist(arc.center, (0, 5)) == A(4)   # tangent to the circle (outside)
    assert arc.center[0] < 0                       # on the picked side
    with pytest.raises(EditError):
        fillet_curves(l, (-5, 0), c, (-2, 5), 1)  # gap too wide for that radius


def test_fillet_polyline_rounds_corners():
    sq = Polyline(vertices=((0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)), closed=True)
    r = fillet_polyline(sq, 2)
    assert len(r.vertices) == 8
    assert abs(r.area()) == A(100 - (4 - math.pi) * 4)


def test_join():
    out = join([Line(p1=(0, 0), p2=(5, 0)), Line(p1=(5, 0), p2=(10, 0))])
    assert len(out) == 1 and isinstance(out[0], Line) and out[0].p2 == P((10, 0))
    out = join([Line(p1=(0, 0), p2=(5, 0)), Line(p1=(5, 0), p2=(5, 5)), Line(p1=(5, 5), p2=(0, 0))])
    assert len(out) == 1 and isinstance(out[0], Polyline) and out[0].closed
    a1 = Arc(center=(0, 0), radius=1, start_angle=0, end_angle=math.pi)
    a2 = Arc(center=(0, 0), radius=1, start_angle=math.pi, end_angle=0)
    out = join([a1, a2])
    assert len(out) == 1 and isinstance(out[0], Circle)
    out = join([Line(p1=(0, 0), p2=(5, 0)), Arc(center=(5, 1), radius=1, start_angle=-math.pi / 2, end_angle=0)])
    assert isinstance(out[0], Polyline) and out[0].vertices[1][2] == A(math.tan(math.pi / 8))


def test_explode():
    doc = Document()
    pl = Polyline(vertices=((0, 0, 0), (10, 0, 1.0), (10, 10, 0)))
    parts = explode(doc, pl)
    assert [type(p).__name__ for p in parts] == ["Line", "Arc"]
    assert explode(doc, Line(p1=(0, 0), p2=(1, 0))) is None


def test_curve_params():
    c = Curve(Polyline(vertices=((0, 0, 0), (10, 0, 0), (10, 10, 0))))
    assert c.length == A(20)
    assert c.param_of((10, 4)) == A(14)
    assert c.point_at(15) == P((10, 5))
