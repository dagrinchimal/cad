import math

import pytest

from cad.commands import CommandContext, CommandRunner
from cad.core.geom2d.transform import Affine2
from cad.core.model import ArrayEntity, Circle, Dimension, Document, Hatch, Line, Polyline
from cad.core.spatial import SpatialIndex
from cad.io import native


@pytest.fixture
def r():
    doc = Document()
    return CommandRunner(CommandContext(doc=doc, index=SpatialIndex(doc)))


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


def of(r, cls):
    return [e for e in r.ctx.doc.entities.values() if isinstance(e, cls)]


def test_dimension_follows_line(r):
    doc = r.ctx.doc
    (ln,) = seed(doc, Line(p1=(0, 0), p2=(100, 0)))
    go(r, "DAL", "0,0", "100,0", "50,10")
    d = of(r, Dimension)[0]
    assert d.refs == ((ln.handle, "p1"), (ln.handle, "p2"))
    with doc.transaction("stretch"):
        doc.replace(Line(handle=ln.handle, p1=(0, 0), p2=(150, 0)))
    d = doc.get(d.handle)
    assert d.measurement() == pytest.approx(150) and d.p2 == (150, 0)
    with doc.transaction("move"):
        doc.replace(doc.get(ln.handle).transformed(Affine2.translate(0, 20)))
    d = doc.get(d.handle)
    assert d.p1 == pytest.approx((0, 20)) and d.location[1] == pytest.approx(30)
    doc.undo()
    assert doc.get(d.handle).p1 == pytest.approx((0, 0))
    with doc.transaction("del"):
        doc.delete(ln.handle)
    assert not doc.get(d.handle).is_associative


def test_dimension_by_selecting_object_and_radius(r):
    doc = r.ctx.doc
    pl, c = seed(doc, Polyline(vertices=((0, 0, 0), (40, 0, 0), (40, 30, 0)), closed=False),
                 Circle(center=(100, 0), radius=10))
    go(r, "DLI", "", (20, 0), "20,-10")
    go(r, "DRA", (110, 0), "130,0")
    d1, d2 = of(r, Dimension)
    with doc.transaction("edit"):
        doc.replace(Polyline(handle=pl.handle, vertices=((0, 0, 0), (55, 0, 0), (55, 30, 0))))
        doc.replace(doc.get(c.handle).with_props(radius=25))
    assert doc.get(d1.handle).measurement() == pytest.approx(55)
    assert doc.get(d2.handle).measurement() == pytest.approx(25)


def test_angular_dimension_follows_lines(r):
    doc = r.ctx.doc
    a, b = seed(doc, Line(p1=(0, 0), p2=(100, 0)), Line(p1=(0, 0), p2=(0, 100)))
    go(r, "DAN", (50, 0), (0, 50), "20,20")
    d = of(r, Dimension)[0]
    assert math.degrees(d.measurement()) == pytest.approx(90)
    with doc.transaction("rot"):
        doc.replace(doc.get(b.handle).transformed(Affine2.rotate(-math.pi / 4)))
    assert math.degrees(doc.get(d.handle).measurement()) == pytest.approx(45)


def test_hatch_follows_its_boundary(r):
    doc = r.ctx.doc
    (pl,) = seed(doc, Polyline(vertices=((0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)), closed=True))
    go(r, "H", "P", "SOLID", (5, 5), "")
    h = of(r, Hatch)[0]
    assert h.sources == {pl.handle} and h.area() == pytest.approx(100)
    with doc.transaction("grow"):
        doc.replace(Polyline(handle=pl.handle, vertices=((0, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0)), closed=True))
    assert doc.get(h.handle).area() == pytest.approx(200)
    # moving the whole room (shape + hatch together) keeps the hatch
    with doc.transaction("move"):
        for x in (pl.handle, h.handle):
            doc.replace(doc.get(x).transformed(Affine2.translate(100, 0)))
    assert doc.get(h.handle).bbox()[0] == pytest.approx(100)


def test_hatch_from_lines_follows_wall_move(r):
    doc = r.ctx.doc
    walls = seed(doc, Line(p1=(0, 0), p2=(10, 0)), Line(p1=(10, 0), p2=(10, 10)), Line(p1=(10, 10), p2=(0, 10)),
                 Line(p1=(0, 10), p2=(0, 0)))
    go(r, "H", (5, 5), "")
    h = of(r, Hatch)[0]
    assert len(h.sources) == 4
    right = walls[1]
    with doc.transaction("move wall"):
        doc.replace(Line(handle=right.handle, p1=(15, -2), p2=(15, 12)))
        doc.replace(Line(handle=walls[0].handle, p1=(0, 0), p2=(15, 0)))
        doc.replace(Line(handle=walls[2].handle, p1=(15, 10), p2=(0, 10)))
    assert doc.get(h.handle).area() == pytest.approx(150)


def test_selected_object_hatch_and_lost_association(r):
    doc = r.ctx.doc
    (c,) = seed(doc, Circle(center=(0, 0), radius=5))
    go(r, "H", "S")
    r.submit_selection({c.handle})
    go(r, "")
    h = of(r, Hatch)[0]
    with doc.transaction("r"):
        doc.replace(doc.get(c.handle).with_props(radius=10))
    assert doc.get(h.handle).area() == pytest.approx(math.pi * 100, rel=1e-2)
    with doc.transaction("d"):
        doc.delete(c.handle)
    assert not doc.get(h.handle).sources       # stays, no longer associative


def test_array_moves_with_sources_and_saves(r, tmp_path):
    doc = r.ctx.doc
    (c,) = seed(doc, Circle(center=(0, 0), radius=1))
    r.ctx.selection = {c.handle}
    go(r, "ARRAYRECT", "1", "3", "10")
    arr = of(r, ArrayEntity)[0]
    r.ctx.selection = {c.handle, arr.handle}
    go(r, "M", "0,0", "5,5")
    centers = sorted(tuple(round(v, 6) for v in p) for p in doc.geometry(doc.get(arr.handle)).centers)
    assert centers == [(15, 5), (25, 5)]
    p = str(tmp_path / "a.cadz")
    native.save(doc, p)
    d2, _ = native.load(p)
    assert d2.get(arr.handle) == doc.get(arr.handle)


def test_polar_array_without_rotation(r):
    doc = r.ctx.doc
    (ln,) = seed(doc, Line(p1=(9, 0), p2=(11, 0)))
    r.ctx.selection = {ln.handle}
    go(r, "ARRAYPOLAR", "0,0", "4", "360", "N")
    prims = doc.geometry(of(r, ArrayEntity)[0]).prims()
    assert all(abs(p.p[1] - p.q[1]) < 1e-9 for p in prims)        # all still horizontal
