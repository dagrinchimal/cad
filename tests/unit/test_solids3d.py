import math

import pytest

pytest.importorskip("OCP")

from cad.commands import CommandContext, CommandRunner
from cad.core import solids as S
from cad.core.model import Circle, Document, Line, Polyline, Solid
from cad.core.model.tables import Sketch, sketch_space
from cad.core.spatial import SpatialIndex
from cad.io.native import load, save


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
        if isinstance(it, set):
            r.submit_selection(it)
        elif isinstance(it, tuple):
            r.submit_point(it)
        elif it == "":
            r.submit_enter()
        else:
            assert r.submit_text(it) is not False, r.ctx.messages[-3:]


def solids(r):
    return [e for e in r.ctx.doc.entities.values() if isinstance(e, Solid)]


def vol(e):
    return S.mass_properties(e.shape)["volume"]


def rect(x0, y0, x1, y1):
    return Polyline(vertices=((x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)), closed=True)


def test_extrude_plate_with_hole_by_area(r):
    seed(r.ctx.doc, rect(0, 0, 100, 50), Circle(center=(50, 25), radius=10))
    go(r, "EXTRUDE", "A", (5, 5), "", "10")
    (s,) = solids(r)
    assert vol(s) == pytest.approx(100 * 50 * 10 - math.pi * 100 * 10, rel=1e-6)
    # Area picks keep the outlines
    assert len(r.ctx.doc.entities) == 3


def test_extrude_selection_deletes_profile_and_undo(r):
    (p,) = seed(r.ctx.doc, rect(0, 0, 10, 10))
    go(r, "EXTRUDE", {p.handle}, "5")
    (s,) = solids(r)
    assert vol(s) == pytest.approx(500)
    assert r.ctx.doc.get(p.handle) is None
    r.ctx.doc.undo()
    assert not solids(r) and r.ctx.doc.get(p.handle) is not None


def test_extrude_cut_through_all(r):
    (p,) = seed(r.ctx.doc, rect(0, 0, 10, 10))
    go(r, "EXTRUDE", {p.handle}, "5")
    (c,) = seed(r.ctx.doc, Circle(center=(5, 5), radius=2))
    go(r, "EXTRUDE", {c.handle}, "T")
    (s,) = solids(r)
    assert vol(s) == pytest.approx(500 - math.pi * 4 * 5, rel=1e-6)


def test_extrude_join(r):
    (p,) = seed(r.ctx.doc, rect(0, 0, 10, 10))
    go(r, "EXTRUDE", {p.handle}, "5")
    (q,) = seed(r.ctx.doc, rect(5, 0, 20, 10))
    go(r, "EXTRUDE", {q.handle}, "J", "5")
    (s,) = solids(r)
    assert vol(s) == pytest.approx(20 * 10 * 5)


def test_primitives_and_booleans(r):
    go(r, "BOX", (0, 0), (10, 10), "10")
    go(r, "CYLINDER", (5, 5), "2", "20")
    a, b = solids(r)
    go(r, "SUBTRACT", {a.handle}, {b.handle})
    (s,) = solids(r)
    assert vol(s) == pytest.approx(1000 - math.pi * 4 * 10, rel=1e-6)
    go(r, "SPHERE", (0, 0), "3")
    go(r, "MASSPROP", {s.handle})
    assert "volume" in r.ctx.messages[-1]


def test_box_at_typed_elevation(r):
    go(r, "BOX", "0,0,5", (10, 10), "10")
    (s,) = solids(r)
    assert S.bbox3(s.shape)[2] == pytest.approx(5)


def test_union_intersect(r):
    go(r, "BOX", (0, 0), (10, 10), "10")
    go(r, "BOX", (5, 0), (15, 10), "10")
    a, b = solids(r)
    go(r, "INTERSECT", {a.handle, b.handle})
    (s,) = solids(r)
    assert vol(s) == pytest.approx(500)


def test_revolve_and_presspull(r):
    (p,) = seed(r.ctx.doc, rect(5, 0, 10, 20))
    go(r, "REVOLVE", {p.handle}, "Y", "")
    (s,) = solids(r)
    assert vol(s) == pytest.approx(math.pi * (100 - 25) * 20, rel=1e-4)


def test_presspull_top_face(r):
    go(r, "BOX", (0, 0), (10, 10), "10")
    (s,) = solids(r)
    go(r, "PRESSPULL", (5, 5), "5")    # picked from above: the top face
    assert vol(solids(r)[0]) == pytest.approx(1500)


def test_filletedge_and_shell(r):
    go(r, "BOX", (0, 0), (10, 10), "10")
    go(r, "FILLETEDGE", "R", "1", (0, 5), "")   # vertical-ish pick from above hits the top edge at x=0
    (s,) = solids(r)
    assert vol(s) < 1000
    go(r, "BOX", (20, 0), (30, 10), "10")
    t = [e for e in solids(r) if e.handle != s.handle][0]
    go(r, "SHELL", (25, 5), "", "1")
    assert vol(r.ctx.doc.get(t.handle)) == pytest.approx(1000 - 8 * 8 * 9, rel=1e-6)


def test_slice_and_move_rotate(r):
    go(r, "BOX", (0, 0), (10, 10), "10")
    (s,) = solids(r)
    go(r, "SLICE", {s.handle}, (5, -1), (5, 20), "")
    assert sorted(round(vol(e)) for e in solids(r)) == [500, 500]
    a = solids(r)[0]
    go(r, "3DMOVE", {a.handle}, "0,0,25")
    assert S.bbox3(r.ctx.doc.get(a.handle).shape)[2] == pytest.approx(25)
    go(r, "3DROTATE", {a.handle}, "X", (0, 0), "90")
    assert r.ctx.doc.get(a.handle).shape is not None


def test_loft_on_one_plane_with_gap(r):
    a, b = seed(r.ctx.doc, rect(0, 0, 10, 10), Circle(center=(5, 5), radius=3))
    go(r, "LOFT", (0, 5), (8, 5), "", "10")
    (s,) = solids(r)
    assert 300 < vol(s) < 1000


def test_extrude_in_sketch_plane(r):
    doc = r.ctx.doc
    with doc.transaction("sk"):
        doc.sketches["Front"] = Sketch(name="Front", origin=(0, 0, 0), xdir=(1, 0, 0), normal=(0, -1, 0))
        c = doc.add(Circle(center=(0, 10), radius=2, space=sketch_space("Front")))
    go(r, "EXTRUDE", {c.handle}, "30")
    (s,) = solids(r)
    x0, y0, z0, x1, y1, z1 = S.bbox3(s.shape)
    assert (y0, y1) == (pytest.approx(-30), pytest.approx(0, abs=1e-6))
    assert z0 == pytest.approx(8) and s.space == "*Model"
    assert doc.get(c.handle) is not None     # sketch outlines stay


def test_solid_save_load(r, tmp_path):
    go(r, "BOX", (0, 0), (10, 10), "10")
    p = tmp_path / "a.cadz"
    save(r.ctx.doc, str(p))
    d2, _ = load(str(p))
    (s,) = [e for e in d2.entities.values() if isinstance(e, Solid)]
    assert vol(s) == pytest.approx(1000)


def test_flatshot(r):
    go(r, "BOX", (0, 0), (10, 10), "10")
    (s,) = solids(r)
    go(r, "FLATSHOT", {s.handle})
    assert sum(isinstance(e, Line) for e in r.ctx.doc.entities.values()) == 4


class Ui:
    def __init__(self):
        self.actions = []

    def run_ui_action(self, name):
        self.actions.append(name)


def test_sketch_on_face_reference_and_extrude(r):
    r.ctx.ui = ui = Ui()
    go(r, "BOX", (0, 0), (20, 10), "10")
    go(r, "SKETCH", "Face", (10, 5))
    doc = r.ctx.doc
    (sk,) = doc.sketches.values()
    assert sk.normal == pytest.approx((0, 0, 1)) and sk.origin[2] == pytest.approx(10)
    assert ui.actions[-1] == "SHOWLAYOUT:" + sk.space
    ref = [e for e in doc.entities.values() if e.space == sk.space]
    assert len(ref) == 4
    # reference lines lie on the box outline in sketch coordinates
    plane = sk.plane()
    for e in ref:
        for p in (e.p1, e.p2):
            w = plane.to_world(*p)
            assert w[0] == pytest.approx(0, abs=1e-6) or w[0] == pytest.approx(20) or \
                w[1] == pytest.approx(0, abs=1e-6) or w[1] == pytest.approx(10)
    # draw a circle on the sketch at the box center, cut a pocket
    r.ctx.space = sk.space
    r.ctx.index.space = sk.space
    local = plane.to_local((10, 5, 10))
    with doc.transaction("c"):
        c = doc.add(Circle(center=(local[0], local[1]), radius=2, space=sk.space))
    go(r, "EXTRUDE", {c.handle}, "C", "-3")
    (s,) = solids(r)
    assert vol(s) == pytest.approx(2000 - math.pi * 4 * 3, rel=1e-6)


def test_sketch_offset_and_delete(r):
    r.ctx.ui = Ui()
    go(r, "SKETCH", "Offset", "XY", "25")
    (sk,) = r.ctx.doc.sketches.values()
    assert sk.origin[2] == pytest.approx(25)
    go(r, "DELSKETCH", "")
    assert not r.ctx.doc.sketches


def test_viewbase_and_update(r):
    from cad.commands.drawing_views import view_settings
    from cad.core.model import BlockReference
    r.ctx.ui = Ui()
    go(r, "BOX", (0, 0), (40, 20), "10")
    go(r, "CYLINDER", (20, 10), "4", "10")
    a, b = solids(r)
    go(r, "SUBTRACT", {a.handle}, {b.handle})
    go(r, "VIEWBASE", "Front", "0.5", (100, 100), (200, 100), (100, 200), (200, 200), "")
    doc = r.ctx.doc
    refs = [e for e in doc.entities.values() if isinstance(e, BlockReference) and view_settings(doc.blocks[e.name])]
    assert sorted(view_settings(doc.blocks[e.name])["view"] for e in refs) == ["Front", "Right", "SE Iso", "Top"]
    front = next(e for e in refs if view_settings(doc.blocks[e.name])["view"] == "Front")
    assert front.space in doc.layouts and front.sx == 0.5
    lines = doc.blocks[front.name].entities
    assert any(e.layer == "View hidden" for e in lines)          # the hole, hidden in the front view
    xs = [p for e in lines if isinstance(e, Line) for p in (e.p1[0], e.p2[0])]
    assert max(xs) - min(xs) == pytest.approx(40)
    # top view sits straight above the front view
    top = next(e for e in refs if view_settings(doc.blocks[e.name])["view"] == "Top")
    assert top.insert[0] == pytest.approx(front.insert[0])
    # edit the solid, update
    s = solids(r)[0]
    with doc.transaction("grow"):
        doc.replace(s.with_props(shape=S.box((0, 0, 0), (60, 20, 10))))
    go(r, "VIEWUPDATE")
    lines = doc.blocks[front.name].entities
    xs = [p for e in lines if isinstance(e, Line) for p in (e.p1[0], e.p2[0])]
    assert max(xs) - min(xs) == pytest.approx(60)
