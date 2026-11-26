"""SVG export (in-house writer, one group per layer, millimeter units) and SVG import (svgelements)."""
from __future__ import annotations

import math
from xml.sax.saxutils import escape, quoteattr

from ...core.model import Document, Hatch, Line, Polyline
from ...core.plot import Fill, Stroke
from ..base import Capabilities as C, Option, PluginError, Report
from .sheet_common import SheetPlugin


def _f(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def svg_text(sheet) -> str:
    W, H = sheet.width, sheet.height
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
           f'version="1.1" width="{_f(W)}mm" height="{_f(H)}mm" viewBox="0 0 {_f(W)} {_f(H)}">',
           f"<title>{escape(sheet.name)}</title>"]
    by_layer: dict[str, list] = {}
    for it in sheet.items:
        by_layer.setdefault(it.layer, []).append(it)
    for i, (layer, items) in enumerate(by_layer.items()):
        out.append(f'<g id="layer{i}" inkscape:groupmode="layer" inkscape:label={quoteattr(layer)} '
                   'stroke-linecap="round" stroke-linejoin="round">')
        for it in items:
            color = "#%02x%02x%02x" % it.color
            if isinstance(it, Stroke):
                pts = " ".join(f"{_f(x)},{_f(H - y)}" for x, y in (it.pts[:-1] if it.closed else it.pts))
                tag = "polygon" if it.closed else "polyline"
                out.append(f'<{tag} points="{pts}" fill="none" stroke="{color}" stroke-width="{_f(it.width)}"/>')
            elif isinstance(it, Fill):
                d = " ".join("M" + " L".join(f"{_f(x)},{_f(H - y)}" for x, y in lp) + " Z" for lp in it.loops)
                out.append(f'<path d="{d}" fill="{color}" fill-rule="evenodd" stroke="none"/>')
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


class SvgPlugin(SheetPlugin):
    id = "svg"
    name = "SVG vector image"
    extensions = (".svg",)
    can_import = True
    capabilities = SheetPlugin.capabilities | {C.LAYERS}
    description = "Vector image for web pages, Inkscape and laser cutters. One group per layer."

    def write_sheets(self, sheets, path, o, report) -> None:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(svg_text(sheets[0]))
        except OSError as exc:
            raise PluginError(f"Couldn't write {path}: {exc}") from exc

    def import_options(self):
        return [Option("scale", "Size of one SVG unit", "choice", "auto",
                       (("auto", "As set in the file (px = 1/96 inch)"), ("mm", "1 unit = 1 mm"),
                        ("in", "1 unit = 1 inch"))),
                Option("tolerance", "Curve accuracy (mm)", "float", 0.05, minimum=0.001, maximum=10)]

    def import_(self, path: str, options: dict, report: Report) -> Document:
        o = self.checked_options("import", options)
        return read_svg(path, o, report)


def read_svg(path: str, o: dict, report: Report) -> Document:
    try:
        import svgelements as se
    except ImportError as exc:                       # pragma: no cover - bundled
        raise PluginError("SVG import needs the svgelements package.") from exc
    try:
        svg = se.SVG.parse(path, reify=True, ppi=96.0)
    except Exception as exc:
        raise PluginError(f"Couldn't read this SVG file: {exc}") from exc
    if o["scale"] == "mm":
        k = 1.0
    elif o["scale"] == "in":
        k = 25.4
    else:
        k = 25.4 / 96.0                              # svgelements resolves everything to px
    height = (svg.height or 0) * k
    tol = o["tolerance"]
    doc = Document()

    def P(x, y):
        return (x * k, height - y * k)               # SVG's y points down

    def color(c):
        if c is None or c.value is None or getattr(c, "alpha", 255) == 0:
            return None
        return f"#{c.red:02x}{c.green:02x}{c.blue:02x}"

    with doc.transaction("Import SVG"):
        for el in svg.elements():
            if isinstance(el, se.Text):
                report.skip("SVG text (outline it in your SVG editor first)")
                continue
            if isinstance(el, se.Image):
                report.skip("images")
                continue
            if not isinstance(el, se.Shape):
                continue
            try:
                path_ = se.Path(el)
            except Exception:
                continue
            stroke, fill = color(el.stroke), color(el.fill)
            for sub in path_.as_subpaths():
                sp = se.Path(sub)
                length = sp.length(error=1e-3)
                if not length:
                    continue
                n = max(2, min(20000, int(math.ceil(length * k / max(tol * 8, 1e-6)))))
                seg_pts = []
                simple = all(isinstance(s, (se.Move, se.Line, se.Close)) for s in sp)
                if simple:
                    for s in sp:
                        if isinstance(s, (se.Move, se.Line)) and s.end is not None:
                            seg_pts.append(P(s.end.x, s.end.y))
                else:
                    for i in range(n + 1):
                        pt = sp.point(i / n)
                        seg_pts.append(P(pt.x, pt.y))
                closed = isinstance(list(sp)[-1], se.Close) or (len(seg_pts) > 2 and math.dist(seg_pts[0], seg_pts[-1]) < 1e-9)
                if closed and len(seg_pts) > 2 and math.dist(seg_pts[0], seg_pts[-1]) < 1e-9:
                    seg_pts.pop()
                pts = []
                for p in seg_pts:
                    if not pts or math.dist(pts[-1], p) > 1e-9:
                        pts.append(p)
                if len(pts) < 2:
                    continue
                c = stroke or fill or 7
                if fill and closed and len(pts) >= 3:
                    doc.add(Hatch(loops=(tuple((x, y, 0.0) for x, y in pts),), pattern="SOLID", color=fill))
                    report.count("hatch")
                    if not stroke:
                        continue
                if len(pts) == 2 and not closed:
                    doc.add(Line(p1=pts[0], p2=pts[1], color=c))
                    report.count("line")
                else:
                    doc.add(Polyline(vertices=tuple((x, y, 0.0) for x, y in pts), closed=closed, color=c))
                    report.count("polyline")
    doc.clear_history()
    doc.mark_saved()
    return doc


PLUGINS = [SvgPlugin()]
