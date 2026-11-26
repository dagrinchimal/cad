import math

import pytest

from cad.commands import REGISTRY, CommandContext, CommandRunner, GetPoint, GetSelection
from cad.commands.framework import InputError, parse_point_text
from cad.core.model import Arc, Circle, Document, Line, Point, Polyline
from cad.core.spatial import SpatialIndex
from cad.core.units import UnitMode, UnitSettings


@pytest.fixture
def runner():
    doc = Document()
    ctx = CommandContext(doc=doc, index=SpatialIndex(doc))
    return CommandRunner(ctx)


def typed(r: CommandRunner, *items):
    for it in items:
        if isinstance(it, tuple):
            r.submit_point(it)
        else:
            assert r.submit_text(it) is not False, r.ctx.messages[-3:]


def ents(r, cls):
    return [e for e in r.ctx.doc.entities.values() if isinstance(e, cls)]


# ------------------------------------------------------------- coordinate input
def test_parse_point_text():
    mm = UnitSettings()
    arch = UnitSettings(mode=UnitMode.ARCHITECTURAL)
    assert parse_point_text("10,20", mm, None, None) == (10, 20)
    assert parse_point_text("@10,-5", mm, (1, 1), None) == (11, -4)
    p = parse_point_text("@10<90", mm, (0, 0), None)
    assert p == pytest.approx((0, 10))
    assert parse_point_text("10<0", mm, (5, 5), None) == pytest.approx((10, 0))
    assert parse_point_text("#3,4", mm, (9, 9), None) == (3, 4)
    assert parse_point_text("@", mm, (2, 2), None) == (2, 2)
    assert parse_point_text("25", mm, (0, 0), math.pi / 2) == pytest.approx((0, 25))
    assert parse_point_text("3'-6\",1'", arch, None, None) == pytest.approx((42 * 25.4, 12 * 25.4))
    assert parse_point_text("@1'<45", arch, (0, 0), None)[0] == pytest.approx(304.8 / math.sqrt(2))
    assert parse_point_text("25.4mm,1in", arch, None, None) == pytest.approx((25.4, 25.4))
    for bad, last in [("@1,1", None), ("abc", None), ("10", None), ("1,2,3,4", None), ("@5", (0, 0))]:
        with pytest.raises(InputError):
            parse_point_text(bad, mm, last, None)


# ------------------------------------------------------------- registry/search
def test_registry_aliases_and_search():
    assert REGISTRY.get("l").name == "LINE"
    assert REGISTRY.get("_LINE").name == "LINE"
    assert REGISTRY.search("circ")[0].name == "CIRCLE"
    assert REGISTRY.search("pl")[0].name == "PLINE"
    assert "ERASE" in [c.name for c in REGISTRY.search("delete")]
    assert REGISTRY.get("nonsense") is None
    names = [c.name for c in REGISTRY.all()]
    assert len(names) == len(set(names))
    for c in REGISTRY.all():
        assert c.description and c.label


# ------------------------------------------------------------- LINE
def test_line_with_typed_coordinates_and_close(runner):
    typed(runner, "L", "0,0", "@100,0", "@0,50", "C")
    lines = ents(runner, Line)
    assert len(lines) == 3
    assert lines[-1].p2 == (0, 0)
    assert not runner.is_active
    runner.ctx.doc.undo()
    assert ents(runner, Line) == []        # whole command is one undo step


def test_line_undo_option_and_escape_keeps_segments(runner):
    typed(runner, "LINE", (0, 0), (10, 0), (10, 10), "U")
    assert len(ents(runner, Line)) == 1
    typed(runner, (20, 20))
    runner.cancel()
    assert len(ents(runner, Line)) == 2


def test_direct_distance_entry(runner):
    runner.direction_provider = lambda: 0.0
    typed(runner, "L", "5,5", "20")
    runner.submit_enter()
    assert ents(runner, Line)[0].p2 == pytest.approx((25, 5))


def test_invalid_input_keeps_prompt(runner):
    typed(runner, "L")
    assert runner.submit_text("banana") is False
    assert isinstance(runner.request, GetPoint)
    assert "Invalid input" in runner.ctx.messages[-1]


def test_enter_repeats_last_command(runner):
    typed(runner, "C", "0,0", "5")
    assert not runner.is_active
    runner.submit_text("")
    assert runner.active.name == "CIRCLE"


def test_unknown_command(runner):
    assert runner.submit_text("FLY") is False


# ------------------------------------------------------------- CIRCLE / ARC / PLINE / POINT
def test_circle_variants(runner):
    typed(runner, "CIRCLE", "0,0", "10")
    typed(runner, "C", "0,0", "D", "30")
    typed(runner, "C", "2P", "0,0", "10,0")
    typed(runner, "C", "3P", "1,0", "0,1", "-1,0")
    radii = [c.radius for c in ents(runner, Circle)]
    assert radii == pytest.approx([10, 15, 5, 1])
    typed(runner, "C", "50,50")
    runner.submit_enter()                  # default = last radius
    assert ents(runner, Circle)[-1].radius == pytest.approx(1)


def test_circle_in_feet_inches(runner):
    doc = runner.ctx.doc
    from dataclasses import replace
    with doc.transaction("u"):
        doc.set_header(replace(doc.header, units=UnitSettings(mode=UnitMode.ARCHITECTURAL)))
    typed(runner, "C", "0,0", "D", "3'-4 1/2\"")
    assert ents(runner, Circle)[0].radius == pytest.approx((40.5 * 25.4) / 2)


def test_arcs(runner):
    typed(runner, "ARC", "1,0", "0,1", "-1,0")
    typed(runner, "A", "C", "0,0", "10,0", "0,10")
    a1, a2 = ents(runner, Arc)
    assert a1.radius == pytest.approx(1) and a1.sweep == pytest.approx(math.pi)
    assert a2.radius == pytest.approx(10) and a2.sweep == pytest.approx(math.pi / 2)


def test_pline_with_arc_and_close(runner):
    typed(runner, "PL", "0,0", "10,0", "A", "10,10", "L", "0,10", "C")
    pl = ents(runner, Polyline)[0]
    assert pl.closed and len(pl.vertices) == 4
    assert pl.vertices[1][2] == pytest.approx(1.0)       # tangent semicircle
    assert pl.area() == pytest.approx(100 + math.pi * 25 / 2)


def test_pline_kept_on_escape(runner):
    typed(runner, "PL", "0,0", "10,0", "10,10")
    runner.cancel()
    assert len(ents(runner, Polyline)[0].vertices) == 3


def test_points(runner):
    typed(runner, "PO", "1,1", "2,2")
    runner.submit_enter()
    assert len(ents(runner, Point)) == 2


# ------------------------------------------------------------- selection based
def test_erase_with_pickfirst_and_locked_layer(runner):
    doc = runner.ctx.doc
    from cad.core.model import Layer
    with doc.transaction("s"):
        a = doc.add(Line(p1=(0, 0), p2=(1, 0)))
        doc.add_layer(Layer("L", locked=True))
        b = doc.add(Line(p1=(0, 1), p2=(1, 1), layer="L"))
    runner.ctx.selection = {a.handle, b.handle}
    runner.run("ERASE")
    assert set(doc.entities) == {b.handle}
    assert "skipped" in runner.ctx.messages[-1]


def test_erase_prompts_for_selection(runner):
    doc = runner.ctx.doc
    with doc.transaction("s"):
        a = doc.add(Line(p1=(0, 0), p2=(1, 0)))
    runner.run("E")
    assert isinstance(runner.request, GetSelection)
    runner.submit_selection({a.handle})
    assert len(doc) == 0


def test_undo_redo_commands(runner):
    typed(runner, "C", "0,0", "5", "U")
    assert len(runner.ctx.doc) == 0
    typed(runner, "REDO")
    assert len(runner.ctx.doc) == 1


def test_dist_reports_in_units(runner):
    typed(runner, "DI", "0,0", "3,4")
    assert runner.ctx.messages[-1].startswith("Distance = 5.00")


def test_failing_command_rolls_back(runner):
    from cad.commands.framework import CommandRegistry, command
    reg = CommandRegistry()

    @command("BOOM", label="Boom", description="x", registry=reg)
    def boom(ctx):
        ctx.doc.add(Point(position=(0, 0)))
        yield GetPoint("p")
        raise RuntimeError("kaboom")

    r = CommandRunner(runner.ctx, reg)
    r.run("BOOM")
    r.submit_point((1, 1))
    assert len(runner.ctx.doc) == 0
    assert "kaboom" in runner.ctx.messages[-1]
    assert not r.is_active


# ------------------------------------------------------------- phase 3 drawing commands
def test_rectangle_polygon_ellipse_spline(runner):
    from cad.core.model import Ellipse, Spline
    typed(runner, "REC", "0,0", "10,5")
    typed(runner, "REC", "20,0", "D", "4", "3", "30,10")
    typed(runner, "POL", "6", "0,0", "C", "@10<0")
    typed(runner, "POL", "", "E", "0,0", "10,0")          # Enter keeps 6 sides
    typed(runner, "EL", "0,0", "20,0", "5")
    typed(runner, "EL", "A", "C", "0,0", "10,0", "5", "10,0", "0,10")
    typed(runner, "SPL", "0,0", "10,10", "20,0", "30,10")
    runner.submit_enter()
    pls = ents(runner, Polyline)
    assert pls[0].area() == pytest.approx(50)
    assert abs(pls[1].area()) == pytest.approx(12)
    hexagon = pls[2]
    assert len(hexagon.vertices) == 6
    assert math.dist(hexagon.vertices[0][:2], (0, 0)) == pytest.approx(10 / math.cos(math.pi / 6))
    assert len(pls[3].vertices) == 6
    els = ents(runner, Ellipse)
    assert els[0].major_length == pytest.approx(10) and els[0].ratio == pytest.approx(0.5)
    assert not els[1].is_full and els[1].sweep == pytest.approx(math.pi / 2, abs=1e-6)
    assert len(ents(runner, Spline)[0].fit_points) == 4


def test_text_and_mtext(runner):
    from cad.core.model import MText, Text
    typed(runner, "DT", "0,0", "5", "0", "First line", "Second line")
    runner.submit_enter()
    t = ents(runner, Text)
    assert [x.text for x in t] == ["First line", "Second line"]
    assert t[1].insert[1] < t[0].insert[1]
    typed(runner, "T", "0,100", "50,80")
    runner.submit_text("Line A\nLine B")
    m = ents(runner, MText)[0]
    assert m.width == pytest.approx(50) and "\n" in m.text


def test_hatch_pick_point_with_island(runner):
    from cad.core.model import Circle, Hatch
    doc = runner.ctx.doc
    with doc.transaction("s"):
        for a, b in [((0, 0), (100, 0)), ((100, 0), (100, 50)), ((100, 50), (0, 50)), ((0, 50), (0, 0))]:
            doc.add(Line(p1=a, p2=b))
        doc.add(Circle(center=(50, 25), radius=10))
    typed(runner, "H", "P", "SOLID", "10,10")
    runner.submit_enter()
    h = ents(runner, Hatch)[0]
    assert h.pattern == "SOLID" and len(h.loops) == 2
    assert h.area() == pytest.approx(5000 - math.pi * 100, rel=1e-3)
    typed(runner, "H", "200,200")          # outside everything
    assert "isn't inside" in runner.ctx.messages[-1]
    runner.cancel()


def test_hatch_select_objects_and_boundary(runner):
    from cad.core.model import Circle, Hatch
    doc = runner.ctx.doc
    with doc.transaction("s"):
        c = doc.add(Circle(center=(0, 0), radius=5))
    typed(runner, "H", "S")
    runner.submit_selection({c.handle})
    runner.submit_enter()
    assert ents(runner, Hatch)[0].area() == pytest.approx(math.pi * 25, rel=1e-2)
    typed(runner, "BO", "1,1")
    runner.submit_enter()
    assert any(p.closed for p in ents(runner, Polyline))


# ------------------------------------------------------------- phase 3 modify commands
def _seed(runner, *ents_):
    doc = runner.ctx.doc
    with doc.transaction("seed"):
        return [doc.add(e) for e in ents_]


def pick(runner, pt):
    runner.submit_point(pt)


def test_move_copy_rotate_scale_mirror(runner):
    (a,) = _seed(runner, Line(p1=(0, 0), p2=(10, 0)))
    runner.ctx.selection = {a.handle}
    typed(runner, "M", "0,0", "5,5")
    assert runner.ctx.doc.get(a.handle).p1 == pytest.approx((5, 5))
    runner.ctx.selection = {a.handle}
    typed(runner, "CO", "5,5", "5,15", "5,25")
    runner.submit_enter()
    assert len(ents(runner, Line)) == 3
    runner.ctx.selection = {a.handle}
    typed(runner, "RO", "5,5", "90")
    assert runner.ctx.doc.get(a.handle).p2 == pytest.approx((5, 15))
    runner.ctx.selection = {a.handle}
    typed(runner, "SC", "5,5", "2")
    assert runner.ctx.doc.get(a.handle).p2 == pytest.approx((5, 25))
    runner.ctx.selection = {a.handle}
    typed(runner, "MI", "0,0", "0,10", "")
    assert len(ents(runner, Line)) == 4
    assert ents(runner, Line)[-1].p1 == pytest.approx((-5, 5))
    runner.ctx.selection = {a.handle}
    typed(runner, "RO", "5,5", "R", "90", "180")
    assert runner.ctx.doc.get(a.handle).p2 == pytest.approx((-15, 5))


def test_offset_trim_extend_commands(runner):
    h, v1, v2 = _seed(runner, Line(p1=(0, 0), p2=(100, 0)), Line(p1=(30, -10), p2=(30, 10)),
                      Line(p1=(60, -10), p2=(60, 10)))
    typed(runner, "O", "5")
    pick(runner, (50, 0))
    pick(runner, (50, 10))
    runner.submit_enter()
    assert any(x.p1 == pytest.approx((0, 5)) for x in ents(runner, Line))
    typed(runner, "TR")
    pick(runner, (45, 0))
    runner.submit_enter()
    lines = [x for x in ents(runner, Line) if x.p1[1] == 0 and x.p2[1] == 0]
    assert sorted((x.p1[0], x.p2[0]) for x in lines) == [(0, pytest.approx(30)), (pytest.approx(60), 100)]
    (short,) = _seed(runner, Line(p1=(0, -5), p2=(20, -5)))
    typed(runner, "EX")
    pick(runner, (19, -5))
    runner.submit_enter()
    assert runner.ctx.doc.get(short.handle).p2 == pytest.approx((30, -5))


def test_fillet_chamfer_commands(runner):
    a, b = _seed(runner, Line(p1=(0, 0), p2=(10, 0)), Line(p1=(12, 2), p2=(12, 10)))
    typed(runner, "F", "R", "2")
    pick(runner, (5, 0))
    pick(runner, (12, 8))
    assert len(ents(runner, Arc)) == 1
    c, d = _seed(runner, Line(p1=(100, 0), p2=(110, 0)), Line(p1=(112, 2), p2=(112, 10)))
    typed(runner, "CHA", "D", "1", "2")
    pick(runner, (105, 0))
    pick(runner, (112, 8))
    assert len(ents(runner, Line)) == 5


def test_arrays(runner):
    (c,) = _seed(runner, Circle(center=(0, 0), radius=1))
    from cad.core.model import ArrayEntity
    doc = runner.ctx.doc
    runner.ctx.selection = {c.handle}
    typed(runner, "ARRAYRECT", "2", "3", "10", "5")
    arr = ents(runner, ArrayEntity)[0]
    g = doc.geometry(arr)
    assert len(g.centers) == 5 and (10.0, 10.0) in [tuple(round(v, 9) for v in p) for p in g.centers]
    runner.ctx.selection = {c.handle}
    typed(runner, "ARRAYPOLAR", "20,0", "8", "360", "Y")
    pol = ents(runner, ArrayEntity)[1]
    assert len(doc.geometry(pol).centers) == 7
    # editing the source updates every copy
    with doc.transaction("grow"):
        doc.replace(doc.get(c.handle).with_props(radius=3))
    assert all(abs(p.r - 3) < 1e-9 for p in doc.geometry(arr).prims())
    # explode makes real copies
    runner.ctx.selection = {arr.handle}
    typed(runner, "X")
    assert len(ents(runner, Circle)) == 6 and len(ents(runner, ArrayEntity)) == 1
    # erasing the source removes its live array
    with doc.transaction("del"):
        doc.delete(c.handle)
    assert not ents(runner, ArrayEntity)


def test_break_join_explode_stretch(runner):
    (a,) = _seed(runner, Line(p1=(0, 0), p2=(10, 0)))
    typed(runner, "BR")
    pick(runner, (2, 0))
    typed(runner, "4,0")
    assert len(ents(runner, Line)) == 2
    runner.ctx.selection = set(runner.ctx.doc.entities)
    typed(runner, "J")
    assert len(ents(runner, Line)) == 2        # there's a gap: nothing joined
    l1, l2 = _seed(runner, Line(p1=(20, 0), p2=(30, 0)), Line(p1=(30, 0), p2=(30, 10)))
    runner.ctx.selection = {l1.handle, l2.handle}
    typed(runner, "J")
    pl = ents(runner, Polyline)[0]
    runner.ctx.selection = {pl.handle}
    typed(runner, "X")
    assert len(ents(runner, Polyline)) == 0
    (sq,) = _seed(runner, Polyline(vertices=((100, 0, 0), (110, 0, 0), (110, 10, 0), (100, 10, 0)), closed=True))
    runner.run("S")
    runner.ctx.memory["last_window"] = (105, -1, 120, 20)
    runner.submit_selection({sq.handle})
    typed(runner, "0,0", "5,0")
    assert abs(runner.ctx.doc.get(sq.handle).area()) == pytest.approx(150)


def test_locked_layer_objects_are_not_edited(runner):
    from cad.core.model import Layer
    doc = runner.ctx.doc
    with doc.transaction("s"):
        doc.add_layer(Layer("Lock", locked=True))
        a = doc.add(Line(p1=(0, 0), p2=(10, 0), layer="Lock"))
    runner.ctx.selection = {a.handle}
    typed(runner, "M")
    assert not runner.is_active and "locked" in runner.ctx.messages[-1]
    assert doc.get(a.handle).p1 == (0, 0)


# ------------------------------------------------------------- dimensions, blocks, groups
def test_dimension_commands(runner):
    from cad.core.model import Dimension, Leader
    (ln, c, l2) = _seed(runner, Line(p1=(0, 0), p2=(30, 40)), Circle(center=(100, 0), radius=10),
                        Line(p1=(0, 0), p2=(0, 50)))
    typed(runner, "DAN")
    pick(runner, (15, 20))
    pick(runner, (0, 25))
    typed(runner, "5,15")
    typed(runner, "DLI", "0,0", "30,40", "15,60")
    typed(runner, "DLI", "0,0", "30,40", "50,20")
    typed(runner, "DAL", "0,0", "30,40", "0,10")
    typed(runner, "DLI")
    runner.submit_enter()
    pick(runner, (15, 20))
    typed(runner, "15,70")
    typed(runner, "DRA")
    pick(runner, (110, 0))
    typed(runner, "130,10")
    typed(runner, "DDI")
    pick(runner, (100, 10))
    typed(runner, "120,30")
    typed(runner, "DOR", "30,40", "30,60")
    typed(runner, "LE", "0,0", "20,20")
    runner.submit_enter()
    runner.submit_text("Check this")
    ds = ents(runner, Dimension)
    ang = ds.pop(0)
    assert math.degrees(ang.measurement()) == pytest.approx(90 - math.degrees(math.atan2(40, 30)))
    vals = [round(d.measurement(), 6) for d in ds]
    assert vals[:3] == [30, 40, 50]
    assert ds[1].angle == pytest.approx(math.pi / 2)
    assert vals[3] == 30                      # picked the line: its endpoints
    assert vals[4] == 10 and vals[5] == 20    # radius and diameter
    assert ds[6].axis == "x" and ds[6].measurement() == pytest.approx(30)
    assert ents(runner, Leader)[0].text == "Check this"


def test_block_insert_attributes_and_explode(runner):
    from cad.core.model import AttributeDefinition, BlockReference
    a, b = _seed(runner, Line(p1=(0, 0), p2=(10, 0)), Circle(center=(5, 5), radius=2))
    typed(runner, "ATT", "NUM", "Door number?", "D1", "0,-5", "2")
    att = ents(runner, AttributeDefinition)[0]
    runner.ctx.selection = {a.handle, b.handle, att.handle}
    typed(runner, "B", "Door", "0,0", "")              # Enter = Convert
    assert "Door" in runner.ctx.doc.blocks
    assert len(ents(runner, BlockReference)) == 1 and len(ents(runner, Line)) == 0
    typed(runner, "I", "door", "S", "2", "100,100", "D42")
    ref = ents(runner, BlockReference)[-1]
    assert ref.sx == 2 and ref.attrib("NUM") == "D42"
    g = runner.ctx.doc.geometry(ref)
    assert any(r.text == "D42" for p in g.parts for r in p.texts)
    runner.ctx.selection = {ref.handle}
    typed(runner, "X")
    assert any(e.TYPE == "text" and e.text == "D42" for e in runner.ctx.doc.entities.values())
    assert any(isinstance(e, Line) and e.p2 == pytest.approx((120, 100)) for e in runner.ctx.doc.entities.values())


def test_groups(runner):
    a, b = _seed(runner, Line(p1=(0, 0), p2=(10, 0)), Line(p1=(0, 5), p2=(10, 5)))
    runner.ctx.selection = {a.handle, b.handle}
    typed(runner, "G", "")
    assert runner.ctx.doc.groups["Group1"].handles == {a.handle, b.handle}
    runner.ctx.selection = {a.handle}
    typed(runner, "UNGROUP")
    assert not runner.ctx.doc.groups
