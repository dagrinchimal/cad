import math

import pytest

from cad.core.model import Arc, Circle, Document, Line, Point, Polyline
from cad.core.snaps import Osnap, SnapEngine, SnapSettings
from cad.core.spatial import SpatialIndex


@pytest.fixture
def engine():
    doc = Document()
    with doc.transaction("setup"):
        doc.add(Line(p1=(0, 0), p2=(100, 0)))
        doc.add(Line(p1=(50, -50), p2=(50, 50)))
        doc.add(Circle(center=(200, 0), radius=20))
        doc.add(Arc(center=(300, 0), radius=10, start_angle=0, end_angle=math.pi))
        doc.add(Point(position=(400, 400)))
        doc.add(Polyline(vertices=((500, 0, 0), (510, 0, 0), (510, 10, 0)), closed=False))
    return SnapEngine(SpatialIndex(doc))


ONLY = lambda *m: SnapSettings(modes=frozenset(m), polar_on=False, otrack_on=False)  # noqa: E731


def snap(engine, cursor, cfg, base=None):
    return engine.snap(cursor, 1.0, cfg, base=base)


def test_endpoint_midpoint(engine):
    r = snap(engine, (98, 3), ONLY(Osnap.ENDPOINT))
    assert r.point == (100, 0) and r.osnap is Osnap.ENDPOINT and r.tooltip == "Endpoint"
    assert snap(engine, (24, 2), ONLY(Osnap.MIDPOINT, Osnap.ENDPOINT)).osnap is None   # nothing near
    r = snap(engine, (47, 1), ONLY(Osnap.MIDPOINT))
    assert r.point == pytest.approx((50, 0))


def test_intersection(engine):
    r = snap(engine, (52, 3), ONLY(Osnap.INTERSECTION))
    assert r.point == pytest.approx((50, 0)) and r.osnap is Osnap.INTERSECTION


def test_polyline_vertex_is_not_intersection(engine):
    r = snap(engine, (510, 0.5), ONLY(Osnap.INTERSECTION))
    assert r.osnap is None


def test_center_by_hovering_edge(engine):
    r = snap(engine, (220, 3), ONLY(Osnap.CENTER))
    assert r.point == pytest.approx((200, 0)) and r.osnap is Osnap.CENTER


def test_quadrant_and_node(engine):
    r = snap(engine, (201, 19), ONLY(Osnap.QUADRANT))
    assert r.point == pytest.approx((200, 20))
    r = snap(engine, (402, 398), ONLY(Osnap.NODE))
    assert r.point == (400, 400)
    r = snap(engine, (300, -9), ONLY(Osnap.QUADRANT))   # bottom quadrant isn't on the upper arc
    assert r.osnap is None


def test_perpendicular_and_tangent_need_base(engine):
    r = snap(engine, (30, 2), ONLY(Osnap.PERPENDICULAR), base=(30, 40))
    assert r.point == pytest.approx((30, 0))
    assert snap(engine, (30, 2), ONLY(Osnap.PERPENDICULAR)).osnap is None
    base = (200, 60)
    r = snap(engine, (215, 14), ONLY(Osnap.TANGENT), base=base)
    assert r.osnap is Osnap.TANGENT
    t = r.point
    assert (t[0] - 200) * (base[0] - t[0]) + (t[1] - 0) * (base[1] - t[1]) == pytest.approx(0, abs=1e-6)


def test_nearest(engine):
    r = snap(engine, (70, 4), ONLY(Osnap.NEAREST))
    assert r.point == pytest.approx((70, 0))


def test_nearest_loses_to_endpoint(engine):
    r = snap(engine, (99, 1), ONLY(Osnap.NEAREST, Osnap.ENDPOINT))
    assert r.osnap is Osnap.ENDPOINT


def test_extension_needs_acquired_point(engine):
    cfg = ONLY(Osnap.EXTENSION)
    assert snap(engine, (130, 1), cfg).osnap is None
    engine.toggle_acquire((100, 0), engine.extension_dir_for((100, 0), 1e-6))
    r = snap(engine, (130, 1), cfg)
    assert r.osnap is Osnap.EXTENSION and r.point == pytest.approx((130, 0))
    assert r.tooltip.startswith("Extension: 30.00")


def test_grid_snap_and_ortho(engine):
    cfg = SnapSettings(osnap_on=False, polar_on=False, otrack_on=False, grid_snap_on=True)
    r = engine.snap((1003, 1007), 1.0, cfg, snap_spacing=10)
    assert r.point == (1000, 1010) and r.kind == "grid"
    cfg = SnapSettings(osnap_on=False, polar_on=False, otrack_on=False, ortho_on=True)
    r = engine.snap((1050, 1010), 1.0, cfg, base=(1000, 1000))
    assert r.point == (1050, 1000) and r.kind == "ortho"


def test_polar_tracking(engine):
    cfg = SnapSettings(osnap_on=False, polar_on=True, polar_increment_deg=45, otrack_on=False)
    base = (1000, 1000)
    r = engine.snap((1070, 1072), 1.0, cfg, base=base)
    assert r.kind == "polar"
    assert r.point[0] - base[0] == pytest.approx(r.point[1] - base[1])
    assert "45" in r.tooltip
    r = engine.snap((1070, 1040), 1.0, cfg, base=base)       # not near any polar angle
    assert r.kind is None


def test_object_snap_tracking_intersection(engine):
    cfg = SnapSettings(osnap_on=False, polar_on=False, otrack_on=True)
    engine.toggle_acquire((1000, 1000))
    engine.toggle_acquire((1100, 1100))
    r = engine.snap((1101, 1001), 1.0, cfg)    # vertical from 2nd meets horizontal from 1st
    assert r.point == pytest.approx((1100, 1000)) and r.kind == "track"
    assert len(r.track_lines) == 2
    assert engine.toggle_acquire((1000, 1000)) is False     # toggles off
    assert len(engine.acquired) == 1


def test_hidden_layers_dont_snap():
    from cad.core.model import Layer
    doc = Document()
    with doc.transaction("s"):
        doc.add_layer(Layer("Off", on=False))
        doc.add(Line(p1=(0, 0), p2=(10, 0), layer="Off"))
    eng = SnapEngine(SpatialIndex(doc))
    assert eng.snap((10, 0), 1, ONLY(Osnap.ENDPOINT)).osnap is None
