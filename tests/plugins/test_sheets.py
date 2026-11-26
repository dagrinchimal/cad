import math
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from cad.core.model import Circle, Document, Hatch, Layer, Line, Polyline
from cad.core.plot import PlotArea, PlotStyle, dash_polyline, plot_layout, plot_model, Stroke, Fill
from cad.plugins import PluginError, Report, registry
from cad.samples import rich_document

import numpy as np


@pytest.fixture(scope="module")
def sample(qapp_text):
    return rich_document()


@pytest.fixture(scope="module")
def qapp_text():
    from cad.render.text_qt import ensure_qt_text_engine
    ensure_qt_text_engine()
    return True


def export(pid, doc, path, **opts):
    r = Report()
    registry.get(pid).export(doc, str(path), opts, r)
    return r


# ------------------------------------------------------------------ plot engine
def test_scale_is_exact_on_paper(qapp_text):
    doc = Document()
    with doc.transaction("s"):
        doc.add(Line(p1=(0, 0), p2=(5000, 0)))           # 5 m
    sh = plot_model(doc, PlotArea(paper=(420, 297), scale=1 / 50))
    (s,) = [it for it in sh.items if isinstance(it, Stroke)]
    assert np.hypot(*(s.pts[-1] - s.pts[0])) == pytest.approx(100)    # 5000 / 50 mm
    assert s.pts[:, 0].mean() == pytest.approx(210)                    # centered


def test_dashes_clipping_and_hidden_layers(qapp_text):
    doc = Document()
    with doc.transaction("s"):
        doc.add_layer(Layer("NoPlot", plot=False))
        doc.add_layer(Layer("Frozen", frozen=True))
        doc.add(Line(p1=(0, 0), p2=(100, 0), linetype="DASHED") if "DASHED" in doc.linetypes else Line(p1=(0, 0), p2=(100, 0)))
        doc.add(Line(p1=(0, 5), p2=(100, 5), layer="NoPlot"))
        doc.add(Line(p1=(0, 10), p2=(100, 10), layer="Frozen"))
    sh = plot_model(doc, PlotArea(paper=(200, 100), scale=1.0))
    ys = {round(float(it.pts[0][1]) - 50, 6) for it in sh.items}
    assert len(ys) == 1                                      # only the first line plots
    pieces = dash_polyline(np.array([[0.0, 0], [10, 0]]), [2, -1])
    assert len(pieces) == 4 and pieces[0][-1][0] == pytest.approx(2)
    from cad.core.plot import _clip_polyline
    out = _clip_polyline(np.array([[-5.0, 1], [5, 1], [15, 1]]), (0, 0, 10, 10))
    assert len(out) == 1 and out[0][0][0] == 0 and out[0][-1][0] == 10


def test_layout_viewport_is_clipped_and_scaled(sample):
    sh = plot_layout(sample, "Sheet A3")
    x0, y0, x1, y1 = sh.bbox()
    assert x0 >= 10 - 1e-6 and y0 >= 10 - 1e-6 and x1 <= 410 + 1e-6 and y1 <= 287 + 1e-6
    assert "NoPlot" not in sh.layers and "Off" not in sh.layers and "Text" in sh.layers


# ------------------------------------------------------------------ PDF
def test_pdf_pages_sizes_and_vectors(sample, tmp_path):
    import pypdf
    path = tmp_path / "s.pdf"
    rep = export("pdf", sample, path, what="everything", paper="ISO A4", orientation="portrait", scale="1:2")
    assert rep.ok
    r = pypdf.PdfReader(str(path))
    sizes = [(float(p.mediabox.width) / 72 * 25.4, float(p.mediabox.height) / 72 * 25.4) for p in r.pages]
    assert sizes[0] == pytest.approx((210, 297), abs=0.5) and sizes[1] == pytest.approx((420, 297), abs=0.5)
    content = r.pages[1].get_contents().get_data()
    assert content.count(b" l") + content.count(b" c") > 500       # real vector paths, not an image
    assert not r.pages[1].images
    if shutil.which("qpdf"):
        assert subprocess.run(["qpdf", "--check", str(path)], capture_output=True).returncode == 0


def test_pdf_true_scale_measured_from_the_file(qapp_text, tmp_path):
    import pdfplumber
    doc = Document()
    with doc.transaction("s"):
        doc.add(Line(p1=(0, 0), p2=(1000, 0)))
        doc.add(Line(p1=(0, 0), p2=(0, 10)))
    path = tmp_path / "scale.pdf"
    export("pdf", doc, path, paper="ISO A4", scale="1:10")
    with pdfplumber.open(str(path)) as pdf:
        objs = pdf.pages[0].lines + pdf.pages[0].curves + pdf.pages[0].rects
        widths = [abs(o["x1"] - o["x0"]) for o in objs]
    assert max(widths) / 72 * 25.4 == pytest.approx(100, abs=0.3)   # 1000 mm at 1:10 = 100 mm


# ------------------------------------------------------------------ SVG
def test_svg_layers_units_and_round_trip(sample, tmp_path):
    path = tmp_path / "s.svg"
    export("svg", sample, path, what="model", paper="ISO A3", scale="1:1")
    root = ET.parse(path).getroot()
    assert root.get("width") == "420mm" and root.get("viewBox") == "0 0 420 297"
    labels = [g.get("{http://www.inkscape.org/namespaces/inkscape}label") for g in root.iter("{http://www.w3.org/2000/svg}g")]
    assert {"Walls", "Center", "Text", "Hatch"} <= set(labels)
    if shutil.which("rsvg-convert"):
        assert subprocess.run(["rsvg-convert", "-o", str(tmp_path / "s.png"), str(path)], capture_output=True).returncode == 0
    doc = registry.get("svg").import_(str(path), {"scale": "mm"}, Report())
    assert len(doc.entities) > 50


def test_svg_import_shapes(tmp_path):
    svg = tmp_path / "in.svg"
    svg.write_text('''<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="50mm" viewBox="0 0 100 50">
      <rect x="10" y="10" width="30" height="20" fill="none" stroke="red"/>
      <circle cx="70" cy="25" r="10" fill="#0000ff"/>
      <line x1="0" y1="0" x2="100" y2="0" stroke="black"/>
      <path d="M 10 45 C 30 35 60 55 90 45" stroke="green" fill="none"/>
      <text x="5" y="5">hi</text>
    </svg>''')
    r = Report()
    doc = registry.get("svg").import_(str(svg), {}, r)
    rect = next(e for e in doc.entities.values() if isinstance(e, Polyline) and e.closed and len(e.vertices) == 4)
    xs = sorted({round(v[0], 6) for v in rect.vertices})
    assert xs == [pytest.approx(10), pytest.approx(40)]          # viewBox units are mm here
    ys = sorted({round(v[1], 6) for v in rect.vertices})
    assert ys == [pytest.approx(20), pytest.approx(40)]          # y flipped: SVG y=10..30 -> 40..20
    h = next(e for e in doc.entities.values() if isinstance(e, Hatch))
    assert h.area() == pytest.approx(math.pi * 100, rel=0.01) and h.color == "#0000ff"
    assert any(isinstance(e, Line) for e in doc.entities.values())
    assert r.skipped


# ------------------------------------------------------------------ images and HPGL
@pytest.mark.parametrize("pid,ext", [("png", "png"), ("jpg", "jpg"), ("tiff", "tif")])
def test_images_have_the_right_pixel_size(sample, tmp_path, pid, ext):
    from PIL import Image
    path = tmp_path / f"s.{ext}"
    export(pid, sample, path, what="Sheet A3", dpi=100)
    im = Image.open(path)
    assert im.size == (round(420 / 25.4 * 100), round(297 / 25.4 * 100))
    dpi = im.info.get("dpi")
    if dpi:
        assert round(dpi[0]) == 100
    px = np.asarray(im.convert("L"))
    assert (px < 128).mean() > 0.002                     # something was drawn


def test_png_transparent(sample, tmp_path):
    from PIL import Image
    path = tmp_path / "t.png"
    export("png", sample, path, what="model", dpi=30, transparent=True)
    im = Image.open(path)
    assert im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0


def test_hpgl_coordinates_and_pens(sample, tmp_path):
    path = tmp_path / "s.plt"
    r = export("hpgl", sample, path, what="Sheet A3", pens=4)
    text = path.read_text()
    assert text.startswith("IN;") and "SP1;" in text and "SP5;" not in text
    nums = [int(n) for n in re.findall(r"-?\d+", "".join(re.findall(r"P[DU][-\d,]+", text)))]
    assert max(nums) <= 420 * 40 and min(nums) >= 0
    assert any("pens" in w for w in r.warnings)
    if shutil.which("hp2xx"):
        res = subprocess.run(["hp2xx", "-m", "png", "-f", str(tmp_path / "hp.png"), str(path)], capture_output=True)
        assert res.returncode == 0 and (tmp_path / "hp.png").stat().st_size > 1000


def test_bad_options_are_refused(sample, tmp_path):
    with pytest.raises(PluginError):
        export("pdf", sample, tmp_path / "x.pdf", scale="huge")
    with pytest.raises(PluginError):
        export("pdf", sample, tmp_path / "x.pdf", what="Nope")
    with pytest.raises(PluginError):
        export("png", sample, tmp_path / "x.png", dpi=5)


def test_model_plot_of_empty_drawing(qapp_text, tmp_path):
    export("pdf", Document(), tmp_path / "empty.pdf")
    assert (tmp_path / "empty.pdf").stat().st_size > 100
