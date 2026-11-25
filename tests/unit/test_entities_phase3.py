import math

import numpy as np
import pytest

from cad.core.geom2d.fill import triangulate
from cad.core.geom2d.transform import Affine2
from cad.core.model import (
    Arc, AttributeDefinition, BlockDefinition, BlockReference, Circle, Dimension, Document, Ellipse, Hatch,
    Layer, Leader, Line, MText, Point, Polyline, Spline, Text, Viewport, entity_from_dict, entity_to_dict,
)
from cad.core.model.geometry import explode_block_reference
from cad.core.model.hatch_patterns import PATTERN_NAMES, pattern_segments
from cad.core.spatial import SpatialIndex
from cad.core.units import UnitMode, UnitSettings
from cad.io import native

A = pytest.approx


# ------------------------------------------------------------------ transforms
def test_affine_basics():
    m = Affine2.rotate(math.pi / 2, (1, 1))
    assert m.apply((2, 1)) == A((1, 2))
    assert (m @ m.inverse()).apply((5, 7)) == A((5, 7))
    mir = Affine2.mirror((0, 0), (0, 1))
    assert mir.apply((3, 4)) == A((-3, 4)) and mir.is_mirror and mir.is_similarity
    assert not Affine2.scale(2, 3).is_similarity
    ins = Affine2.insert((10, 0), 2, 2, math.pi / 2, base=(1, 0))
    assert ins.apply((2, 0)) == A((10, 2))


def test_line_circle_arc_transform():
    m = Affine2.translate(10, 0) @ Affine2.scale(2)
    assert Line(p1=(0, 0), p2=(1, 0)).transformed(m).p2 == A((12, 0))
    assert Circle(center=(1, 1), radius=2).transformed(m).radius == A(4)
    arc = Arc(center=(0, 0), radius=1, start_angle=0, end_angle=math.pi / 2)
    mirrored = arc.transformed(Affine2.mirror((0, 0), (0, 1)))
    s, e = mirrored.endpoints()
    assert {tuple(np.round(s, 9)), tuple(np.round(e, 9))} == {(-1.0, 0.0), (0.0, 1.0)}
    assert mirrored.sweep == A(math.pi / 2)
    el = Circle(center=(0, 0), radius=1).transformed(Affine2.scale(2, 1))
    assert isinstance(el, Ellipse) and el.major_length == A(2) and el.ratio == A(0.5)


def test_ellipse_transform_keeps_points_on_curve():
    e = Ellipse(center=(1, 2), major=(3, 1), ratio=0.4, start_param=0.3, end_param=2.5)
    m = Affine2.rotate(0.7) @ Affine2.scale(1.5, 0.8) @ Affine2.translate(4, -1)
    t = e.transformed(m)
    for p in (0.3, 1.0, 2.5):
        q = m.apply(e.point_at(p))
        dmin = min(math.dist(q, tuple(x)) for x in t.points(2000))
        assert dmin < 1e-2
    assert t.ratio <= 1.0
    assert math.dist(t.endpoints()[0], m.apply(e.point_at(0.3))) < 1e-6


def test_polyline_mirror_flips_bulges():
    pl = Polyline(vertices=((0, 0, 0.5), (10, 0, 0)), closed=False)
    m = pl.transformed(Affine2.mirror((0, 0), (1, 0)))
    assert m.vertices[0][2] == A(-0.5)


def test_text_mirror_stays_readable():
    t = Text(insert=(10, 0), text="AB", rotation=0.0, halign="left")
    m = t.transformed(Affine2.mirror((0, 0), (0, 1)))
    assert m.insert == A((-10, 0)) and math.cos(m.rotation) == A(1) and m.halign == "right"


def test_block_ref_transform_composes():
    r = BlockReference(name="B", insert=(1, 0), sx=2, sy=2, rotation=0)
    t = r.transformed(Affine2.rotate(math.pi / 2))
    assert t.insert == A((0, 1)) and t.rotation == A(math.pi / 2) and t.sx == A(2)
    mir = r.transformed(Affine2.mirror((0, 0), (0, 1)))
    assert mir.sy < 0 or mir.sx < 0


# ------------------------------------------------------------------ new entities
def test_spline_passes_through_fit_points():
    pts = [(0, 0), (10, 5), (20, -3), (30, 4)]
    s = Spline.through(pts)
    from cad.core.geom2d import spline as bs
    d = np.linalg.norm(np.diff(np.array(pts, float), axis=0), axis=1)
    params = np.concatenate(([0], np.cumsum(d) / d.sum()))
    on_curve = bs.evaluate(np.array(s.control_points), np.array(s.knots), s.degree, params)
    assert np.allclose(on_curve, pts, atol=1e-9)
    assert s.endpoints()[0] == A((0, 0)) and s.endpoints()[1] == A((30, 4))
    d = entity_to_dict(s)
    assert entity_from_dict(d) == s


def test_all_types_round_trip_json():
    ents = [
        Ellipse(center=(0, 0), major=(5, 0), ratio=0.5),
        Text(insert=(1, 2), text="Hello", height=3),
        MText(insert=(1, 2), text="Line one\nLine two", width=40),
        Hatch(loops=(((0, 0, 0), (10, 0, 0), (10, 10, 0)),), pattern="ANSI31"),
        Dimension(dimtype="linear", p1=(0, 0), p2=(10, 0), location=(5, 5)),
        Leader(points=((0, 0), (5, 5), (10, 5)), text="Note"),
        AttributeDefinition(tag="TITLE", prompt="Title", default="X"),
        BlockReference(name="B", insert=(1, 1), attribs=(("TITLE", "Plan"),)),
        Viewport(center=(100, 100), width=200, height=150, view_center=(0, 0), scale=0.02),
        Point(position=(1, 1), space="Layout1"),
    ]
    for e in ents:
        assert entity_from_dict(entity_to_dict(e)) == e, type(e).__name__


def test_triangulate_with_holes():
    sq = np.array([[0, 0], [10, 0], [10, 10], [0, 10.]])
    hole = np.array([[3, 3], [7, 3], [7, 7], [3, 7.]])
    t = triangulate([sq, hole])
    area = sum(abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2 for a, b, c in t)
    assert area == A(84)


def test_hatch_area_and_patterns():
    h = Hatch(loops=(((0, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0)),
                     ((25, 25, 0), (75, 25, 0), (75, 75, 0), (25, 75, 0))), pattern="ANSI31")
    assert h.area() == A(7500)
    loops = h.loop_points()
    segs = pattern_segments(loops, "ANSI31")
    assert len(segs) > 20
    for s in segs:                            # nothing inside the island
        mx, my = (s.p[0] + s.q[0]) / 2, (s.p[1] + s.q[1]) / 2
        assert not (26 < mx < 74 and 26 < my < 74)
    for name in PATTERN_NAMES[1:]:
        assert pattern_segments(loops, name, 2.0) or name == "SOLID"


def test_dimension_measurement_and_text():
    doc = Document()
    d = Dimension(dimtype="linear", p1=(0, 0), p2=(30, 40), location=(0, 50), angle=0.0)
    assert d.measurement() == A(30)
    assert Dimension(dimtype="aligned", p1=(0, 0), p2=(30, 40)).measurement() == A(50)
    ang = Dimension(dimtype="angular", p1=(0, 0), p2=(10, 0), p3=(0, 10), location=(5, 5))
    assert math.degrees(ang.measurement()) == A(90)
    from cad.core.model.dimensions import dim_text
    st = doc.dimstyle("Standard")
    assert dim_text(doc, d, st, d.measurement()) == "30.00"
    arch = Document(units=UnitSettings(mode=UnitMode.ARCHITECTURAL))
    d2 = Dimension(dimtype="aligned", p1=(0, 0), p2=(3 * 304.8 + 6 * 25.4, 0), location=(0, 10), text="<> TYP")
    assert dim_text(arch, d2, arch.dimstyle("Standard"), d2.measurement()) == "3'-6\" TYP"
    with doc.transaction("d"):
        for kind, kw in [("linear", {}), ("aligned", {}), ("radius", {}), ("diameter", {}),
                         ("angular", {"p3": (0, 10)}), ("ordinate", {})]:
            doc.add(Dimension(dimtype=kind, p1=(0, 0), p2=(10, 0), location=(5, 8), **kw))
        doc.add(Leader(points=((0, 0), (10, 10), (20, 10)), text="See note"))
    for e in doc.entities.values():
        g = doc.geometry(e)
        assert g.prims() and g.bbox is not None, e.dimtype if isinstance(e, Dimension) else e.TYPE


def test_blocks_geometry_byblock_and_explode():
    doc = Document()
    with doc.transaction("b"):
        doc.add_layer(Layer("Red", color=1))
        doc.set_item("block", "Chair", BlockDefinition(
            name="Chair", base=(0, 0),
            entities=(Line(p1=(0, 0), p2=(10, 0), color=0),            # ByBlock
                      Circle(center=(5, 5), radius=2, layer="Red"),
                      AttributeDefinition(tag="TAG", default="C1", insert=(0, -5), height=2))))
        ref = doc.add(BlockReference(name="Chair", insert=(100, 0), sx=2, sy=2, color=3,
                                     attribs=(("TAG", "C7"),)))
    g = doc.geometry(ref)
    assert g.bbox[0] == A(100) and g.bbox[2] >= 120 - 1e-9
    colors = [p.color for p in g.parts]
    assert 3 in colors and 1 in colors                                  # ByBlock -> ref color; layer Red
    assert any(r.text == "C7" for p in g.parts for r in p.texts)
    assert (120.0, 0.0) in [tuple(np.round(p, 9)) for p in g.endpoints]
    parts = explode_block_reference(doc, ref)
    assert {type(p).__name__ for p in parts} == {"Line", "Circle", "Text"}
    line = next(p for p in parts if isinstance(p, Line))
    assert line.p2 == A((120, 0)) and line.color == 3
    idx = SpatialIndex(doc)
    assert idx.pick((110, 0.1), 0.5).handle == ref.handle


def test_nested_and_recursive_blocks_are_safe():
    doc = Document()
    with doc.transaction("b"):
        doc.set_item("block", "A", BlockDefinition("A", entities=(BlockReference(name="A"),)))
        r = doc.add(BlockReference(name="A"))
    assert doc.geometry(r) is not None        # self reference doesn't recurse forever


def test_text_estimate_geometry_and_pick():
    doc = Document()
    with doc.transaction("t"):
        t = doc.add(Text(insert=(0, 0), text="HELLO", height=10))
    g = doc.geometry(t)
    assert g.bbox[2] > 20 and g.insertions == [(0, 0)]
    idx = SpatialIndex(doc)
    assert idx.pick((15, 5), 0.1).handle == t.handle


def test_layout_space_filtering(tmp_path):
    from cad.core.model import Layout
    doc = Document()
    with doc.transaction("l"):
        doc.set_item("layout", "Layout1", Layout("Layout1"))
        a = doc.add(Line(p1=(0, 0), p2=(10, 0)))
        b = doc.add(Line(p1=(0, 0), p2=(10, 0), space="Layout1"))
    idx = SpatialIndex(doc)
    assert idx.pick((5, 0), 1).handle == a.handle
    idx.space = "Layout1"
    assert idx.pick((5, 0), 1).handle == b.handle
    p = str(tmp_path / "x.cadz")
    native.save(doc, p)
    d2, _ = native.load(p)
    assert "Layout1" in d2.layouts and d2.get(b.handle).space == "Layout1"


def test_delete_cascades_to_groups():
    from cad.core.model import Group
    doc = Document()
    with doc.transaction("g"):
        a = doc.add(Point(position=(0, 0)))
        b = doc.add(Point(position=(1, 0)))
        doc.set_item("group", "G", Group("G", frozenset({a.handle, b.handle})))
    with doc.transaction("d"):
        doc.delete(a.handle)
    assert doc.groups["G"].handles == {b.handle}
    with doc.transaction("d2"):
        doc.delete(b.handle)
    assert "G" not in doc.groups
    doc.undo()
    doc.undo()
    assert doc.groups["G"].handles == {a.handle, b.handle}


def test_create_layout_with_title_block_and_viewport():
    from cad.core.layouts import create_layout, delete_layout, rename_layout, resolve_viewport
    doc = Document()
    with doc.transaction("l"):
        doc.add(Line(p1=(0, 0), p2=(1000, 500)))
        create_layout(doc, "Layout1")
    assert "Layout1" in doc.layouts and doc.layouts["Layout1"].size == (420, 297)
    space = [e for e in doc.entities.values() if e.space == "Layout1"]
    assert {e.TYPE for e in space} == {"insert", "viewport"}
    tb = next(e for e in space if e.TYPE == "insert")
    texts = [r.text for p in doc.geometry(tb).parts for r in p.texts]
    assert "Untitled" in texts and "1 of 1" in texts
    vp = next(e for e in space if e.TYPE == "viewport")
    center, scale = resolve_viewport(doc, vp, (0, 0, 1000, 500))
    assert center == (500, 250) and scale * 1000 <= vp.width
    with doc.transaction("r"):
        rename_layout(doc, "Layout1", "Sheet A")
    assert all(e.space != "Layout1" for e in doc.entities.values())
    with doc.transaction("d"):
        delete_layout(doc, "Sheet A")
    assert not doc.layouts and len(doc) == 1
    arch = Document(units=UnitSettings(mode=UnitMode.ARCHITECTURAL))
    with arch.transaction("l"):
        lo = create_layout(arch, "L")
    assert lo.paper.startswith("Tabloid")
