import math
from collections import Counter
from dataclasses import replace

import ezdxf
import pytest

from cad.core.model import (
    Arc, BlockReference, Circle, Dimension, Document, Ellipse, Hatch, Layer, Line, MText, Polyline, Spline, Text,
    Viewport,
)
from cad.core.units import UnitMode, UnitSettings
from cad.plugins import Report, registry
from cad.samples import rich_document

VERSIONS = ["R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"]


@pytest.fixture(scope="module")
def sample():
    return rich_document()


def export(doc, path, **opts):
    p = registry.get("dxf")
    r = Report()
    p.export(doc, str(path), opts, r)
    return r


def load(path, **opts):
    r = Report()
    doc = registry.get("dxf").import_(str(path), opts, r)
    return doc, r


def of(doc, cls, space="*Model"):
    return [e for e in doc.entities.values() if isinstance(e, cls) and e.space == space]


@pytest.mark.parametrize("version", VERSIONS)
def test_every_version_passes_ezdxf_audit_and_reads_back(sample, tmp_path, version):
    path = tmp_path / f"s_{version}.dxf"
    rep = export(sample, path, version=version)
    assert rep.ok
    d = ezdxf.readfile(str(path))
    assert d.acad_release == version
    audit = d.audit()
    assert not audit.has_errors, [str(e.message) for e in audit.errors]
    doc, r2 = load(path)
    assert r2.ok and not r2.skipped, r2.summary()
    assert len(of(doc, Dimension)) == 6
    assert len(of(doc, Circle)) == 3                 # 2 circles + 1 array copy
    assert {"Walls", "Center", "Hidden", "NoPlot", "Off"} <= set(doc.layers)
    if version != "R12":
        assert len(of(doc, Ellipse)) == 2 and len(of(doc, Spline)) == 1 and len(of(doc, Hatch)) == 2
        assert "Sheet A3" in doc.layouts and len(of(doc, Viewport, "Sheet A3")) == 1


def test_round_trip_keeps_geometry_and_styles(sample, tmp_path):
    path = tmp_path / "s.dxf"
    export(sample, path)
    doc, _ = load(path)
    lay = doc.layers
    assert lay["Walls"].lineweight == 0.5 and lay["Center"].linetype == "CENTER" and lay["Center"].color == 1
    assert not lay["Off"].on and not lay["NoPlot"].plot
    # dashes keep their length in mm
    assert doc.linetypes["CENTER"].pattern == pytest.approx(sample.linetypes["CENTER"].pattern)
    pl = next(e for e in of(doc, Polyline) if any(v[2] for v in e.vertices))
    assert pl.vertices[1][2] == pytest.approx(0.5) and pl.color == 4 and pl.lineweight == 0.7
    assert any(c.color == "#3080ff" for c in of(doc, Circle))
    t = next(e for e in of(doc, Text) if e.text.startswith("Ø24"))
    assert (t.halign, t.height, t.rotation) == ("center", pytest.approx(3), pytest.approx(0.3))
    mt = of(doc, MText)
    assert any(m.text == "Note one\nSecond line of the note" for m in mt)
    meas = sorted(round(d.measurement(), 6) for d in of(doc, Dimension) if d.dimtype != "angular")
    assert meas == sorted(round(d.measurement(), 6) for d in of(sample, Dimension) if d.dimtype != "angular")
    ang = next(d for d in of(doc, Dimension) if d.dimtype == "angular")
    assert math.degrees(ang.measurement()) == pytest.approx(45)
    h = next(e for e in of(doc, Hatch) if e.pattern == "ANSI31")
    assert h.pattern_scale == pytest.approx(4) and h.area() == pytest.approx(1600)
    refs = of(doc, BlockReference)
    assert sorted(dict(r.attribs).get("NUM", "") for r in refs if r.name == "Door") == ["", "D7", "D8"]
    door = next(r for r in refs if dict(r.attribs).get("NUM") == "D8")
    assert door.sx == pytest.approx(1.5) and math.degrees(door.rotation) == pytest.approx(90)
    sp = of(doc, Spline)[0]
    sp0 = of(sample, Spline)[0]
    assert [c for p in sp.control_points for c in p] == pytest.approx([c for p in sp0.control_points for c in p]) and sp.knots == pytest.approx(sp0.knots)
    vp = of(doc, Viewport, "Sheet A3")[0]
    assert doc.layouts["Sheet A3"].size == pytest.approx((420, 297))
    from cad.core.layouts import resolve_viewport
    from cad.core.plot import model_extents
    _, s0 = resolve_viewport(sample, of(sample, Viewport, "Sheet A3")[0], model_extents(sample))
    assert vp.scale == pytest.approx(s0)


def test_feet_inch_drawing_is_written_in_inches(tmp_path):
    doc = Document()
    with doc.transaction("s"):
        doc.set_header(replace(doc.header, units=UnitSettings(mode=UnitMode.ARCHITECTURAL)))
        doc.add(Line(p1=(0, 0), p2=(3048, 0)))
        doc.add(Arc(center=(0, 0), radius=304.8, start_angle=0, end_angle=math.pi / 2))
    path = tmp_path / "ft.dxf"
    export(doc, path)
    d = ezdxf.readfile(str(path))
    assert d.header["$INSUNITS"] == 1 and d.header["$LUNITS"] == 4
    ln = d.modelspace().query("LINE")[0]
    assert ln.dxf.end[0] == pytest.approx(120)          # 10 feet = 120 inches
    back, _ = load(path)
    assert back.header.units.mode is UnitMode.ARCHITECTURAL
    assert of(back, Line)[0].p2[0] == pytest.approx(3048)
    assert of(back, Arc)[0].radius == pytest.approx(304.8)
    export(doc, path, units="mm")
    assert ezdxf.readfile(str(path)).modelspace().query("LINE")[0].dxf.end[0] == pytest.approx(3048)


def _foreign(path, units=4, version="R2018"):
    """A DXF made the way other programs make them, with things we only partly support."""
    d = ezdxf.new(version, setup=True)
    d.header["$INSUNITS"] = units
    msp = d.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "walls"})
    d.layers.add("WALLS", color=3) if "WALLS" not in d.layers else None
    msp.add_arc((0, 0), 5, 0, 90, dxfattribs={"extrusion": (0, 0, -1)})          # mirrored arc
    msp.add_circle((3, 4), 1, dxfattribs={"extrusion": (0, 0, -1)})
    msp.add_lwpolyline([(0, 0, 0), (10, 0, 1), (10, 10, 0)], format="xyb", dxfattribs={"extrusion": (0, 0, -1)})
    h = msp.add_hatch(color=2)
    ep = h.paths.add_edge_path()
    ep.add_line((0, 0), (10, 0))
    ep.add_arc((10, 5), 5, -90, 90, ccw=True)
    ep.add_line((10, 10), (0, 10))
    ep.add_line((0, 10), (0, 0))
    h.set_pattern_fill("ANSI31", scale=2)
    h2 = msp.add_hatch()
    ep = h2.paths.add_edge_path()
    ep.add_arc((0, 0), 3, 0, 180, ccw=False)                                        # clockwise arc edge
    ep.add_line((3, 0), (-3, 0))
    h2.set_solid_fill()
    st = d.styles.add("ROMANS", font="romans.shx")
    msp.add_text("SHX text", dxfattribs={"style": st.dxf.name, "height": 2})
    msp.add_solid([(20, 0), (30, 0), (20, 10), (30, 10)])
    msp.add_3dface([(40, 0, 0), (50, 0, 0), (50, 10, 0), (40, 10, 0)])
    msp.add_xline((0, 0), (1, 1))
    blk = d.blocks.new("TAG")
    blk.add_circle((0, 0), 1)
    ins = msp.add_blockref("TAG", (100, 0))
    ins.grid(size=(2, 3), spacing=(10, 20))                                         # a MINSERT
    msp.add_mline([(0, 50), (20, 50), (20, 70)]) if hasattr(msp, "add_mline") else None
    ml = msp.new_entity("ELLIPSE", {"center": (60, 60), "major_axis": (5, 0, 0), "ratio": 0.5})
    _ = ml
    sp = msp.add_rational_spline([(0, 100), (10, 120), (20, 100)], weights=[1, 2, 1], degree=2)
    _ = sp
    d.saveas(str(path))


def test_foreign_file_with_odd_objects(tmp_path):
    path = tmp_path / "foreign.dxf"
    _foreign(path)
    doc, rep = load(path)
    arc = of(doc, Arc)[0]
    assert arc.center == pytest.approx((0, 0)) and math.degrees(arc.start_angle) == pytest.approx(90)
    assert math.degrees(arc.end_angle) == pytest.approx(180)
    assert any(c.center == pytest.approx((-3, 4)) for c in of(doc, Circle))
    pl = of(doc, Polyline)
    assert any(p.vertices[1] == pytest.approx((-10, 0, -1)) for p in pl)
    hatches = of(doc, Hatch)
    ansi = next(h for h in hatches if h.pattern == "ANSI31")
    assert ansi.area() == pytest.approx(100 + math.pi * 25 / 2, rel=1e-2) and ansi.pattern_scale == 2
    solid_half = next(h for h in hatches if h.pattern == "SOLID" and h.area() == pytest.approx(math.pi * 9 / 2, rel=1e-2))
    assert solid_half
    assert next(t for t in of(doc, Text) if t.text == "SHX text").font == "Arial"
    assert any("SHX" in w for w in rep.warnings)
    assert len([b for b in of(doc, BlockReference) if b.name == "TAG"]) == 6
    assert rep.skipped.get("construction lines (XLINE)") == 1
    assert len([h for h in hatches if h.pattern == "SOLID"]) >= 2          # SOLID entity -> solid hatch
    assert "walls" in {n.lower() for n in doc.layers} and len([n for n in doc.layers if n.lower() == "walls"]) == 1


def test_unitless_imperial_drawing_comes_in_as_inches(tmp_path):
    d = ezdxf.new("R2010")
    d.header["$INSUNITS"] = 0
    d.header["$LUNITS"] = 4
    d.modelspace().add_line((0, 0), (12, 0))
    path = tmp_path / "u.dxf"
    d.saveas(str(path))
    doc, _ = load(path)
    assert of(doc, Line)[0].p2[0] == pytest.approx(304.8)
    assert doc.header.units.mode is UnitMode.ARCHITECTURAL
    doc2, _ = load(path, units="mm")
    assert of(doc2, Line)[0].p2[0] == pytest.approx(12)


def test_damaged_file_is_repaired_or_refused(tmp_path):
    good = tmp_path / "g.dxf"
    ezdxf.new("R2010").saveas(str(good))
    text = good.read_text().replace("ENDSEC", "ENDSE", 1)
    bad = tmp_path / "bad.dxf"
    bad.write_text(text)
    try:
        doc, rep = load(bad)
        assert any("damaged" in w for w in rep.warnings)
    except Exception as exc:
        from cad.plugins import PluginError
        assert isinstance(exc, PluginError)
    junk = tmp_path / "junk.dxf"
    junk.write_bytes(b"\x00\x01 not a dxf")
    from cad.plugins import PluginError
    with pytest.raises(PluginError):
        load(junk)


def test_loss_warnings_for_dxf(sample):
    p = registry.get("dxf")
    losses = p.losses(sample)
    assert any("associativity" in w for w in losses) and any("live arrays" in w for w in losses)
    assert not any("layers" in w for w in losses)


def test_groups_and_blocks_with_byblock_colors(tmp_path):
    from cad.core.model import Group
    from cad.core.model.tables import BlockDefinition
    doc = Document()
    with doc.transaction("s"):
        doc.add_layer(Layer("A", color=5))
        doc.set_item("block", "B", BlockDefinition("B", (0, 0), (Line(p1=(0, 0), p2=(1, 0), color=0),)))
        a = doc.add(BlockReference(name="B", insert=(5, 5), color=3))
        b = doc.add(Line(p1=(0, 0), p2=(2, 2), layer="A"))
        doc.set_item("group", "G1", Group("G1", frozenset({a.handle, b.handle})))
    path = tmp_path / "g.dxf"
    export(doc, path)
    back, _ = load(path)
    assert len(back.groups["G1"].handles) == 2
    assert back.blocks["B"].entities[0].color == 0
    assert of(back, BlockReference)[0].color == 3


def test_reexport_of_an_imported_file(sample, tmp_path):
    """A file we read (it has Defpoints and other AutoCAD layers) can be written again."""
    a = tmp_path / "a.dxf"
    export(sample, a)
    doc, _ = load(a)
    b = tmp_path / "b.dxf"
    assert export(doc, b).ok
    doc2, _ = load(b)
    assert len(doc2.entities) == len(doc.entities)
