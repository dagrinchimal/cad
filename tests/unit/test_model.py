import json
import math
import zipfile

import pytest

from cad.core.model import (
    Arc, Circle, Document, DocumentError, Layer, Line, Point, Polyline, UnknownEntity,
    entity_from_dict, entity_to_dict,
)
from cad.core.spatial import SpatialIndex
from cad.core.units import UnitMode, UnitSettings
from cad.io import native


def make_doc():
    doc = Document()
    with doc.transaction("setup"):
        doc.add_layer(Layer("Walls", color=1))
        doc.add(Line(p1=(0, 0), p2=(100, 0)))
        doc.add(Circle(center=(50, 50), radius=20, layer="Walls"))
        doc.add(Arc(center=(0, 0), radius=10, start_angle=0, end_angle=math.pi / 2))
        doc.add(Polyline(vertices=((0, 0, 0), (10, 0, 1.0), (10, 10, 0)), closed=True))
        doc.add(Point(position=(3, 4)))
    return doc


def test_edits_require_transaction():
    doc = Document()
    with pytest.raises(DocumentError):
        doc.add(Line(p1=(0, 0), p2=(1, 1)))


def test_undo_redo_unlimited():
    doc = Document()
    for i in range(500):
        with doc.transaction(f"line {i}"):
            doc.add(Line(p1=(i, 0), p2=(i, 1)))
    assert len(doc) == 500
    for _ in range(500):
        doc.undo()
    assert len(doc) == 0 and not doc.can_undo
    for _ in range(500):
        doc.redo()
    assert len(doc) == 500


def test_undo_restores_exact_state_and_redo_cleared_by_new_edit():
    doc = make_doc()
    before = {h: e for h, e in doc.entities.items()}
    h = next(iter(doc.entities))
    with doc.transaction("move"):
        doc.replace(doc.get(h).with_props(layer="Walls"))
        doc.delete(list(doc.entities)[1])
    assert doc.undo() == "move"
    assert doc.entities == before
    doc.redo()
    doc.undo()
    with doc.transaction("other"):
        doc.add(Point(position=(0, 0)))
    assert not doc.can_redo


def test_rollback_on_error():
    doc = make_doc()
    count = len(doc)
    with pytest.raises(RuntimeError):
        with doc.transaction("bad"):
            doc.add(Point(position=(9, 9)))
            raise RuntimeError("boom")
    assert len(doc) == count and doc.undo_name == "setup"


def test_nested_transactions_merge():
    doc = Document()
    with doc.transaction("outer"):
        doc.add(Point(position=(0, 0)))
        with doc.transaction("inner"):
            doc.add(Point(position=(1, 1)))
    doc.undo()
    assert len(doc) == 0


def test_listeners_receive_changesets():
    doc = Document()
    seen = []
    doc.add_listener(lambda d, cs: seen.append(cs))
    with doc.transaction("a"):
        e = doc.add(Point(position=(0, 0)))
        doc.replace(e.with_props(color=1))
    assert seen[-1].added == {e.handle} and not seen[-1].modified
    doc.undo()
    assert seen[-1].removed == {e.handle}


def test_layers():
    doc = make_doc()
    with doc.transaction("layers"):
        doc.rename_layer("Walls", "Exterior")
    assert all(e.layer != "Walls" for e in doc.entities.values())
    with pytest.raises(DocumentError):
        with doc.transaction("x"):
            doc.delete_layer("0")
    with pytest.raises(DocumentError):
        with doc.transaction("x"):
            doc.delete_layer("Exterior")      # still has objects
    with pytest.raises(DocumentError):
        with doc.transaction("x"):
            doc.add_layer(Layer("exterior"))  # case-insensitive duplicate
    with pytest.raises(DocumentError):
        with doc.transaction("x"):
            doc.add_layer(Layer("bad/name"))
    with doc.transaction("cur"):
        doc.set_current_layer("Exterior")
    with pytest.raises(DocumentError):
        with doc.transaction("x"):
            doc.update_layer(Layer("Exterior", frozen=True))


def test_effective_styles():
    doc = make_doc()
    circle = next(e for e in doc.entities.values() if isinstance(e, Circle))
    assert doc.effective_color(circle) == 1
    assert doc.effective_linetype(circle).name == "Continuous"
    with doc.transaction("hide"):
        doc.update_layer(Layer("Walls", color=1, on=False))
    assert not doc.is_visible(circle)


def test_entity_dict_round_trip_and_unknown_keys():
    doc = make_doc()
    for e in doc.entities.values():
        d = entity_to_dict(e)
        assert entity_from_dict(json.loads(json.dumps(d))) == e
    d = {"type": "line", "handle": 5, "p1": [0, 0], "p2": [1, 1], "future_key": {"a": 1}}
    e = entity_from_dict(d)
    assert e.extra == {"future_key": {"a": 1}} and entity_to_dict(e)["future_key"] == {"a": 1}
    u = entity_from_dict({"type": "spaceship", "handle": 9, "layer": "0", "warp": 9})
    assert isinstance(u, UnknownEntity) and entity_to_dict(u)["warp"] == 9


def test_polyline_area_with_bulge():
    # 10x10 square with a semicircle bulge on one side
    pl = Polyline(vertices=((0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)), closed=True)
    assert pl.area() == pytest.approx(100)
    # positive bulge = counter-clockwise arc, which bulges to the right of travel: outward here
    out = Polyline(vertices=((0, 0, 0), (10, 0, 1.0), (10, 10, 0), (0, 10, 0)), closed=True)
    assert out.area() == pytest.approx(100 + math.pi * 25 / 2)
    inward = Polyline(vertices=((0, 0, 0), (10, 0, -1.0), (10, 10, 0), (0, 10, 0)), closed=True)
    assert inward.area() == pytest.approx(100 - math.pi * 25 / 2)


def test_save_load_round_trip(tmp_path):
    doc = make_doc()
    with doc.transaction("units"):
        from dataclasses import replace
        doc.set_header(replace(doc.header, units=UnitSettings(mode=UnitMode.ARCHITECTURAL, denominator=32)))
    path = str(tmp_path / "a.cadz")
    native.save(doc, path)
    doc2, warnings = native.load(path)
    assert warnings == []
    assert doc2.entities == doc.entities
    assert doc2.layers == doc.layers
    assert doc2.header == doc.header
    assert doc2.next_handle == doc.next_handle
    assert not doc2.is_modified


def test_forward_compatibility_preserves_unknown_data(tmp_path):
    doc = make_doc()
    path = str(tmp_path / "a.cadz")
    native.save(doc, path)
    # simulate a newer minor version adding keys, a new entity type and a new zip member
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        data = json.loads(z.read("document.json"))
    manifest["format_version"] = "1.4.0"
    manifest["new_manifest_field"] = 1
    data["constraints"] = [{"kind": "parallel"}]
    data["entities"].append({"type": "hologram", "handle": 999, "layer": "0"})
    newer = str(tmp_path / "newer.cadz")
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("document.json", json.dumps(data))
        z.writestr("solids/1.brep", b"BREP")
    doc2, warnings = native.load(newer)
    assert len(warnings) == 2
    out = str(tmp_path / "resaved.cadz")
    native.save(doc2, out)
    with zipfile.ZipFile(out) as z:
        data3 = json.loads(z.read("document.json"))
        m3 = json.loads(z.read("manifest.json"))
        assert z.read("solids/1.brep") == b"BREP"
    assert data3["constraints"] == [{"kind": "parallel"}]
    assert any(e["type"] == "hologram" for e in data3["entities"])
    assert m3["new_manifest_field"] == 1


def test_rejects_bad_files(tmp_path):
    p = tmp_path / "x.cadz"
    p.write_text("hello")
    with pytest.raises(native.FileFormatError):
        native.load(str(p))
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "cadz", "format_version": "2.0.0"}))
        z.writestr("document.json", "{}")
    with pytest.raises(native.FileFormatError, match="newer version"):
        native.load(str(p))


def test_spatial_index_tracks_changes():
    doc = make_doc()
    idx = SpatialIndex(doc)
    assert idx.pick((50, 0.5), 1).p1 == (0, 0)
    assert idx.pick((70, 50), 0.5) is not None          # circle edge
    assert idx.pick((50, 50), 0.5) is None              # circle center is empty space
    with doc.transaction("add"):
        far = doc.add(Line(p1=(1000, 1000), p2=(1010, 1000)))
    assert idx.pick((1005, 1000), 1).handle == far.handle
    doc.undo()
    assert idx.pick((1005, 1000), 1) is None
    window = idx.select_window((-1, -1, 101, 1), crossing=False)
    assert len(window) == 1
    crossing = idx.select_window((40, -1, 60, 1), crossing=True)
    assert len(crossing) == 1
    assert idx.extents() is not None


def test_every_historic_format_version_still_opens():
    import glob
    import os
    files = glob.glob(os.path.join(os.path.dirname(__file__), "..", "data", "format_versions", "*.cadz"))
    assert files
    for f in files:
        doc, warnings = native.load(f)
        assert len(doc) >= 5 and warnings == []
