"""3D export/import. Mesh files are re-read by trimesh (not our code); STEP/IGES by OpenCascade's readers."""
import math
import os
import shutil
import subprocess
import zipfile

import pytest

pytest.importorskip("OCP")

from cad.core import solids as S
from cad.core.model import Document, Line, Solid
from cad.plugins import PluginError, Report, registry

REQUIRE = os.environ.get("CAD_REQUIRE_VALIDATORS") == "1"
PLATE = 80 * 50 * 10 - math.pi * 8 ** 2 * 10


@pytest.fixture(scope="module")
def doc():
    d = Document()
    with d.transaction("x"):
        plate = S.subtract(S.box((0, 0, 0), (80, 50, 10)), S.cylinder((40, 25, 0), 8, 10))
        d.add(Solid(shape=plate, name="Plate", color=1))
        d.add(Solid(shape=S.box((100, 0, 0), (110, 10, 10)), name="Cube", color="#20a0ff"))
        d.add(Line(p1=(0, 0), p2=(10, 0)))
    return d


def trimesh_or_skip():
    try:
        import trimesh
        return trimesh
    except ImportError:
        if REQUIRE:
            pytest.fail("trimesh is required in CI")
        pytest.skip("trimesh not installed")


def export(doc, pid, path, **opts):
    r = Report()
    registry.get(pid).export(doc, str(path), opts, r)
    assert r.ok, r.summary()
    return r


@pytest.mark.parametrize("pid,ext,opts", [("stl", "stl", {}), ("stl", "stl", {"binary": False}),
                                          ("gltf", "glb", {}), ("obj", "obj", {}), ("3mf", "3mf", {})])
def test_mesh_exports_read_by_trimesh(doc, tmp_path, pid, ext, opts):
    tm = trimesh_or_skip()
    p = tmp_path / f"a.{ext}"
    r = export(doc, pid, p, quality="fine", **opts)
    assert any("2D object" in w for w in r.warnings)
    scene = tm.load(str(p), force="scene")
    geoms = list(scene.geometry.values())
    assert geoms
    vol = sum(abs(g.volume) for g in geoms)
    k = 1e9 if pid == "gltf" else 1.0          # glTF is in meters
    assert vol * k == pytest.approx(PLATE + 1000, rel=5e-3)
    if pid == "3mf":
        assert all(g.is_watertight for g in geoms)


def test_glb_colors_and_axes(doc, tmp_path):
    tm = trimesh_or_skip()
    p = tmp_path / "a.glb"
    export(doc, "gltf", p)
    scene = tm.load(str(p), force="scene")
    b = scene.bounds
    assert b[1][1] == pytest.approx(0.010, abs=1e-6)          # model z (10 mm) is glTF y
    cols = sorted(tuple(g.visual.material.baseColorFactor[:3]) for g in scene.geometry.values())
    assert (32, 160, 255) in [tuple(int(c) for c in x) for x in cols] or len(cols) == 2


@pytest.mark.parametrize("pid,ext", [("step", "step"), ("iges", "igs")])
def test_exact_round_trip(doc, tmp_path, pid, ext):
    p = tmp_path / f"a.{ext}"
    export(doc, pid, p)
    r = Report()
    d2 = registry.get(pid).import_(str(p), {}, r)
    sols = [e for e in d2.entities.values() if isinstance(e, Solid)]
    assert len(sols) == 2, r.summary()
    vols = sorted(S.mass_properties(e.shape)["volume"] for e in sols)
    assert vols == [pytest.approx(1000, rel=1e-6), pytest.approx(PLATE, rel=1e-6)]


def test_step_keeps_colors_and_names(doc, tmp_path):
    p = tmp_path / "a.step"
    export(doc, "step", p)
    assert "Plate" in p.read_text(errors="replace")
    d2 = registry.get("step").import_(str(p), {}, Report())
    by_name = {e.name: e for e in d2.entities.values() if isinstance(e, Solid)}
    assert set(by_name) == {"Plate", "Cube"}
    assert by_name["Cube"].color == "#20a0ff"


def test_stl_import(doc, tmp_path):
    p = tmp_path / "a.stl"
    export(doc, "stl", p, one_file=True)
    d2 = registry.get("stl").import_(str(p), {}, Report())
    sols = [e for e in d2.entities.values() if isinstance(e, Solid)]
    total = sum(S.mass_properties(e.shape)["volume"] for e in sols)
    assert total == pytest.approx(PLATE + 1000, rel=1e-2)


def test_no_solids_is_a_clear_error(tmp_path):
    d = Document()
    with d.transaction("x"):
        d.add(Line(p1=(0, 0), p2=(1, 1)))
    with pytest.raises(PluginError, match="no 3D solids"):
        registry.get("stl").export(d, str(tmp_path / "x.stl"), {}, Report())


def test_3mf_package(doc, tmp_path):
    p = tmp_path / "a.3mf"
    export(doc, "3mf", p)
    with zipfile.ZipFile(p) as z:
        assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= set(z.namelist())
        assert 'unit="millimeter"' in z.read("3D/3dmodel.model").decode()


def test_freecad_reads_step(doc, tmp_path):
    exe = shutil.which("freecadcmd") or shutil.which("FreeCADCmd")
    if not exe:
        pytest.skip("FreeCAD not installed")
    p = tmp_path / "a.step"
    export(doc, "step", p)
    script = tmp_path / "check.py"
    script.write_text(f"import Part\ns = Part.read(r'{p}')\nprint('VOL', s.Volume)\n")
    out = subprocess.run([exe, str(script)], capture_output=True, text=True, timeout=180)
    vol = [ln for ln in out.stdout.splitlines() if ln.startswith("VOL")]
    assert vol and float(vol[0].split()[1]) == pytest.approx(PLATE + 1000, rel=1e-6), out.stdout + out.stderr
