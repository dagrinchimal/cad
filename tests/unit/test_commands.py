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
