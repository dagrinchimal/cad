"""Exports re-read by programs that aren't ours. Each test is skipped when its tool isn't installed,
unless CAD_REQUIRE_VALIDATORS=1 (set in CI), where a missing tool is a failure."""
import os
import shutil
import subprocess

import pytest

from cad.plugins import Report, registry
from cad.plugins.formats import dwg
from cad.samples import rich_document

VERSIONS = ["R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"]
REQUIRE = os.environ.get("CAD_REQUIRE_VALIDATORS") == "1"


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        if REQUIRE:
            pytest.fail(f"{tool} is required in CI but isn't installed")
        pytest.skip(f"{tool} not installed")
    return path


@pytest.fixture(scope="module")
def doc():
    from cad.render.text_qt import ensure_qt_text_engine
    ensure_qt_text_engine()
    return rich_document()


def export(d, pid, path, **o):
    r = Report()
    registry.get(pid).export(d, str(path), o, r)
    return r


def pdf_ink(pdf_path, tmp_path) -> float:
    """Fraction of dark pixels on page 1, rendered by poppler."""
    need("pdftoppm")
    out = tmp_path / "page"
    subprocess.run(["pdftoppm", "-r", "30", "-png", "-f", "1", "-l", "1", str(pdf_path), str(out)], check=True)
    from PIL import Image
    import numpy as np
    png = next(tmp_path.glob("page*.png"))
    a = np.asarray(Image.open(png).convert("L"))
    png.unlink()
    return float((a < 200).mean())


@pytest.mark.parametrize("version", VERSIONS)
def test_librecad_reads_our_dxf(doc, tmp_path, version):
    exe = need("librecad")
    path = tmp_path / f"s_{version}.dxf"
    export(doc, "dxf", path, version=version)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    res = subprocess.run([exe, "dxf2pdf", "-a", "-m", "-p", "420x297", "-t", str(tmp_path), str(path)],
                         capture_output=True, env=env, timeout=120)
    pdf = tmp_path / f"s_{version}.pdf"
    assert pdf.is_file(), res.stderr.decode(errors="replace")[-500:]
    assert pdf_ink(pdf, tmp_path) > 0.003          # LibreCAD drew our geometry


@pytest.mark.parametrize("version", ["R2000", "R2018"])
def test_oda_converter_reads_our_dxf_and_writes_dwg(doc, tmp_path, version):
    if not dwg.find_converter():
        if REQUIRE and os.environ.get("CAD_REQUIRE_ODA") == "1":
            pytest.fail("ODA File Converter required but not installed")
        pytest.skip("ODA File Converter not installed")
    src = tmp_path / "in.dxf"
    export(doc, "dxf", src, version=version)
    out = tmp_path / "out"
    out.mkdir()
    dwg_path = dwg.run_converter(dwg.find_converter(), str(src), str(out), "ACAD2018", "DWG")
    assert open(dwg_path, "rb").read(6) == b"AC1032"
    back = tmp_path / "back"
    back.mkdir()
    dxf2 = dwg.run_converter(dwg.find_converter(), dwg_path, str(back), "ACAD2018", "DXF")
    d2 = registry.get("dxf").import_(dxf2, {}, Report())
    assert len(d2.entities) >= len([e for e in doc.entities.values() if e.space == "*Model"]) - 2


def test_pdf_checked_by_qpdf_and_poppler(doc, tmp_path):
    exe = need("qpdf")
    path = tmp_path / "s.pdf"
    export(doc, "pdf", path, what="everything")
    res = subprocess.run([exe, "--check", str(path)], capture_output=True)
    assert res.returncode == 0, res.stdout.decode()[-400:]
    assert pdf_ink(path, tmp_path) > 0.003


def test_svg_rendered_by_librsvg(doc, tmp_path):
    exe = need("rsvg-convert")
    path = tmp_path / "s.svg"
    export(doc, "svg", path, what="Sheet A3")
    png = tmp_path / "s.png"
    res = subprocess.run([exe, "-w", "800", "-o", str(png), str(path)], capture_output=True)
    assert res.returncode == 0, res.stderr.decode()
    from PIL import Image
    import numpy as np
    a = np.asarray(Image.open(png).convert("RGBA"))
    assert (a[..., 3] > 0).mean() > 0.003


def test_hpgl_rendered_by_hp2xx(doc, tmp_path):
    exe = need("hp2xx")
    path = tmp_path / "s.plt"
    export(doc, "hpgl", path, what="Sheet A3")
    png = tmp_path / "hp.png"
    res = subprocess.run([exe, "-m", "png", "-f", str(png), str(path)], capture_output=True, timeout=120)
    assert res.returncode == 0 and png.stat().st_size > 1000, res.stderr.decode(errors="replace")[-400:]
