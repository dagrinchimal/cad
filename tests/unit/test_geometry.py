import math
import random

import pytest

from cad.core.geom2d import (
    Arc, Seg, arc_from_3_points, arc_from_bulge, arc_from_start_center_end, arc_segment_count,
    bulge_for_tangent_arc, circle_from_3_points, intersect, intersect_extended, line_line,
    perpendicular_foot, segment_hits_rect, tangent_points,
)

A = pytest.approx


def P(p, abs=1e-9):
    return pytest.approx(p, abs=abs)


def test_seg_basics():
    s = Seg((0, 0), (10, 0))
    assert s.length == 10 and s.mid == (5, 0)
    assert s.nearest((3, 5)) == P((3, 0))
    assert s.nearest((-5, 5)) == P((0, 0))
    assert s.distance_to((15, 0)) == A(5)
    assert s.bbox() == (0, 0, 10, 0)


def test_arc_basics_and_contains():
    a = Arc((0, 0), 10, 0, math.pi / 2)
    assert a.start == P((10, 0)) and a.end == P((0, 10))
    assert a.mid == P((10 / math.sqrt(2), 10 / math.sqrt(2)))
    assert a.contains_angle(math.pi / 4) and not a.contains_angle(math.pi)
    assert a.quadrant_points() == [P((10, 0)), P((0, 10))]
    assert a.bbox() == P((0, 0, 10, 10))
    assert a.length == A(5 * math.pi)
    cw = Arc((0, 0), 10, math.pi / 2, -math.pi / 2)    # same arc, clockwise
    assert cw.contains_angle(math.pi / 4) and not cw.contains_angle(math.pi)
    assert cw.start == P((0, 10)) and cw.end == P((10, 0))


def test_arc_wrapping_through_zero():
    a = Arc((0, 0), 1, math.radians(350), math.radians(20))
    assert a.contains_angle(math.radians(5)) and a.contains_angle(math.radians(355))
    assert not a.contains_angle(math.radians(180))
    assert len(a.quadrant_points()) == 1


def test_tessellation_tolerance():
    a = Arc((0, 0), 100, 0, math.tau)
    tol = 0.01
    pts = a.tessellate(tol)
    assert pts[0] == P(pts[-1])
    # chord sagitta must be under tolerance
    n = len(pts) - 1
    sag = 100 * (1 - math.cos(math.pi / n))
    assert sag <= tol
    assert arc_segment_count(100, math.tau, 1000) >= 4
    assert arc_segment_count(1e9, math.tau, 1e-9) == 2048


@pytest.mark.parametrize("bulge", [0.25, 1.0, -1.0, 0.5, -0.3, 2.0, -3.0])
def test_bulge_round_trip(bulge):
    p, q = (0.0, 0.0), (10.0, 0.0)
    arc = arc_from_bulge(p, q, bulge)
    assert arc.start == P(p, 1e-7) and arc.end == P(q, 1e-7)
    assert math.tan(arc.sweep / 4) == A(bulge)
    if bulge == 1.0:      # semicircle, CCW from p to q bulges below the chord
        assert arc.mid == P((5, -5), 1e-7)


def test_bulge_zero_is_segment():
    assert isinstance(arc_from_bulge((0, 0), (1, 1), 0.0), Seg)


def test_tangent_arc_bulge():
    # leaving (0,0) heading +X, ending at (10,10): quarter circle CCW
    b = bulge_for_tangent_arc((0, 0), (1, 0), (10, 10))
    arc = arc_from_bulge((0, 0), (10, 10), b)
    assert arc.c == P((0, 10), 1e-7)
    t = arc.start_tangent()
    assert t == P((1, 0), 1e-7)


def test_three_point_circle_and_arc():
    c, r = circle_from_3_points((1, 0), (0, 1), (-1, 0))
    assert c == P((0, 0)) and r == A(1)
    assert circle_from_3_points((0, 0), (1, 1), (2, 2)) is None
    arc = arc_from_3_points((1, 0), (0, 1), (-1, 0))
    assert arc.sweep == A(math.pi)
    arc_cw = arc_from_3_points((-1, 0), (0, 1), (1, 0))
    assert arc_cw.sweep == A(-math.pi)
    assert arc_cw.mid == P((0, 1))


def test_start_center_end():
    arc = arc_from_start_center_end((10, 0), (0, 0), (0, 50))
    assert arc.sweep == A(math.pi / 2) and arc.r == A(10)


def test_intersections():
    assert intersect(Seg((0, 0), (10, 10)), Seg((0, 10), (10, 0))) == [P((5, 5))]
    assert intersect(Seg((0, 0), (1, 0)), Seg((0, 1), (1, 1))) == []
    assert intersect(Seg((0, 0), (4, 0)), Seg((5, -1), (5, 1))) == []
    assert intersect_extended(Seg((0, 0), (4, 0)), Seg((5, -1), (5, 1))) == [P((5, 0))]
    circle = Arc((0, 0), 5, 0, math.tau)
    pts = intersect(Seg((-10, 0), (10, 0)), circle)
    assert sorted(pts) == [P((-5, 0)), P((5, 0))]
    half = Arc((0, 0), 5, 0, math.pi)                     # upper half
    assert intersect(Seg((0, -10), (0, 10)), half) == [P((0, 5))]
    tangent = intersect(Seg((-10, 5), (10, 5)), circle)
    assert tangent == [P((0, 5), 1e-6)]
    cc = intersect(Arc((0, 0), 5, 0, math.tau), Arc((8, 0), 5, 0, math.tau))
    assert sorted(cc) == [P((4, -3)), P((4, 3))]


def test_random_intersections_lie_on_both():
    rng = random.Random(7)
    for _ in range(500):
        s = Seg((rng.uniform(-10, 10), rng.uniform(-10, 10)), (rng.uniform(-10, 10), rng.uniform(-10, 10)))
        a = Arc((rng.uniform(-5, 5), rng.uniform(-5, 5)), rng.uniform(1, 8), rng.uniform(0, 6.28), rng.uniform(-6, 6))
        for pt in intersect(s, a):
            assert s.distance_to(pt) < 1e-6
            assert a.distance_to(pt) < 1e-6


def test_tangent_and_perpendicular():
    pts = tangent_points((10, 0), (0, 0), 5)
    assert len(pts) == 2
    for p in pts:
        # radius is perpendicular to the tangent line
        assert (p[0] * (10 - p[0]) + p[1] * (0 - p[1])) == A(0, abs=1e-9)
    assert tangent_points((1, 0), (0, 0), 5) == []
    assert perpendicular_foot(Seg((0, 0), (10, 0)), (4, 7)) == [P((4, 0))]
    assert perpendicular_foot(Seg((0, 0), (10, 0)), (14, 7)) == []
    feet = perpendicular_foot(Arc((0, 0), 5, 0, math.tau), (10, 0))
    assert P((5, 0)) in feet and P((-5, 0)) in feet


def test_line_line_parallel():
    assert line_line((0, 0), (1, 0), (0, 1), (2, 0)) is None


def test_segment_hits_rect():
    r = (0, 0, 10, 10)
    assert segment_hits_rect((-5, 5), (15, 5), r)
    assert segment_hits_rect((2, 2), (3, 3), r)
    assert not segment_hits_rect((-5, -5), (-1, 20), r)
    assert not segment_hits_rect((11, 0), (20, 10), r)
