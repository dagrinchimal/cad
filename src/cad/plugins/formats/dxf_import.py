"""Reading DXF with ezdxf. Imported by the DXF plugin; no PLUGINS list here."""
from __future__ import annotations

import math
import os

import ezdxf
from ezdxf import recover
from ezdxf.enums import TextEntityAlignment
from ezdxf.lldxf.const import DXFError, DXFStructureError

from ...core.model import (
    MODEL_SPACE, Arc, AttributeDefinition, BlockReference, Circle, Dimension, Document, Ellipse, Entity, Group,
    Hatch, Layer, Leader, Line, MText, Point, Polyline, Spline, Text, Viewport,
)
from ...core.model.document import Linetype
from ...core.model.hatch_patterns import PATTERNS
from ...core.model.tables import BlockDefinition, DimStyle, Layout
from ...core.units import UnitMode
from ..base import PluginError, Report

# DXF $INSUNITS -> mm per unit
INSUNITS_MM = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 8: 0.0000254, 9: 0.0254, 10: 914.4, 14: 100.0}
FILE_UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inches": 25.4, "feet": 304.8}

_ALIGN = {
    "LEFT": ("left", "baseline"), "CENTER": ("center", "baseline"), "RIGHT": ("right", "baseline"),
    "ALIGNED": ("center", "baseline"), "FIT": ("center", "baseline"), "MIDDLE": ("center", "middle"),
}
_MTEXT_ALIGN = {1: ("top", "left"), 2: ("top", "center"), 3: ("top", "right"), 4: ("middle", "left"),
                5: ("middle", "center"), 6: ("middle", "right"), 7: ("bottom", "left"), 8: ("bottom", "center"),
                9: ("bottom", "right")}
_SKIP_MESSAGES = {
    "3DSOLID": "3D solids", "BODY": "3D bodies", "REGION": "regions", "SURFACE": "surfaces",
    "IMAGE": "raster images", "OLE2FRAME": "OLE objects", "WIPEOUT": "wipeouts", "ACAD_PROXY_ENTITY": "proxy objects",
    "XLINE": "construction lines (XLINE)", "RAY": "rays", "UNDERLAY": "PDF/DWF underlays", "PDFUNDERLAY": "PDF underlays",
    "LIGHT": "lights", "HELIX": "helixes", "TOLERANCE": "geometric tolerance frames",
}


def _align_of(name: str) -> tuple[str, str]:
    if name in _ALIGN:
        return _ALIGN[name]
    v, h = name.split("_", 1)
    return h.lower(), v.lower()


def _font_family(font_file: str, report: Report) -> str:
    base = os.path.splitext(os.path.basename(font_file or ""))[0]
    if not base or font_file.lower().endswith(".shx") or "." not in font_file and base.lower() in (
            "txt", "simplex", "romans", "romand", "isocp", "isoct", "monotxt", "italic", "complex", "gothic"):
        if base:
            report.warn("SHX (AutoCAD stroke) fonts were replaced by Arial.")
        return "Arial"
    known = {"arial": "Arial", "arialn": "Arial Narrow", "times": "Times New Roman", "cour": "Courier New",
             "calibri": "Calibri", "verdana": "Verdana", "tahoma": "Tahoma", "segoeui": "Segoe UI"}
    return known.get(base.lower(), base)


class Reader:
    def __init__(self, d: ezdxf.document.Drawing, report: Report, k: float) -> None:
        self.d = d
        self.report = report
        self.k = k                    # mm per file unit
        self.doc = Document()
        self.fonts: dict[str, str] = {}
        self.handle_map: dict[str, int] = {}

    # ---------------------------------------------------------------- helpers
    def P(self, v) -> tuple[float, float]:
        return (float(v[0]) * self.k, float(v[1]) * self.k)

    def L(self, v: float) -> float:
        return float(v) * self.k

    def common(self, e) -> dict:
        dx = e.dxf
        out = {"layer": dx.get("layer", "0") or "0"}
        tc = dx.get("true_color")
        if tc is not None:
            r, g, b = ezdxf.colors.int2rgb(tc)
            out["color"] = f"#{r:02x}{g:02x}{b:02x}"
        else:
            c = dx.get("color", 256)
            out["color"] = c if 0 <= c <= 256 else 256
        lt = dx.get("linetype", "BYLAYER") or "BYLAYER"
        out["linetype"] = {"bylayer": "ByLayer", "byblock": "ByBlock", "continuous": "Continuous"}.get(lt.lower(), lt)
        if out["linetype"] not in ("ByLayer", "ByBlock") and out["linetype"] not in self.doc.linetypes:
            out["linetype"] = "ByLayer"
        lw = dx.get("lineweight", -1)
        out["lineweight"] = float(lw) if lw < 0 else lw / 100.0
        lts = dx.get("ltscale", 1.0)
        if lts and lts != 1.0:
            out["ltscale"] = float(lts)
        out["layer"] = self.layer_name(out["layer"])
        return out

    def layer_name(self, name: str) -> str:
        """DXF layer names ignore case: find the existing layer, or create it."""
        if name in self.doc.layers:
            return name
        low = name.lower()
        for n in self.doc.layers:
            if n.lower() == low:
                return n
        self.doc.add_layer(Layer(name))
        return name

    def font(self, style_name: str) -> str:
        if style_name in self.fonts:
            return self.fonts[style_name]
        f = "Arial"
        if style_name in self.d.styles:
            st = self.d.styles.get(style_name)
            f = _font_family(st.dxf.get("font", ""), self.report)
            if not st.dxf.get("font") and st.has_extended_font_data():
                family, _, _ = st.get_extended_font_data()
                f = family or f
        self.fonts[style_name] = f
        return f

    @staticmethod
    def flipped(e) -> bool:
        ext = e.dxf.get("extrusion", (0, 0, 1))
        return ext[2] < 0

    # ---------------------------------------------------------------- tables
    def tables(self) -> None:
        d, doc = self.d, self.doc
        for lt in d.linetypes:
            name = lt.dxf.name
            if name.lower() in ("bylayer", "byblock", "continuous") or name in doc.linetypes:
                continue
            try:
                simple = lt.simplified_line_pattern()
            except Exception:
                simple = ()
            pat = tuple((self.L(v) if i % 2 == 0 else -self.L(abs(v))) for i, v in enumerate(simple))
            doc.linetypes[name] = Linetype(name, lt.dxf.get("description", ""), pat)
        for lay in d.layers:
            name = lay.dxf.name
            tc = lay.dxf.get("true_color")
            if tc is not None:
                r, g, b = ezdxf.colors.int2rgb(tc)
                color = f"#{r:02x}{g:02x}{b:02x}"
            else:
                color = abs(lay.dxf.get("color", 7)) or 7
            lw = lay.dxf.get("lineweight", -3)
            lt = lay.dxf.get("linetype", "Continuous")
            if lt not in doc.linetypes:
                lt = "Continuous"
            layer = Layer(name, color=color, linetype=lt, lineweight=float(lw) if lw < 0 else lw / 100.0,
                          on=lay.is_on(), frozen=lay.is_frozen(), locked=lay.is_locked(),
                          plot=bool(lay.dxf.get("plot", 1)), description=lay.description or "")
            if name == "0":
                doc.layers["0"] = layer
            else:
                doc.add_layer(layer)
        luprec = int(d.header.get("$LUPREC", 4))
        for ds in d.dimstyles:
            dx = ds.dxf
            dec = int(dx.get("dimdec", luprec))
            style = DimStyle(name=dx.name, text_height=self.L(dx.get("dimtxt", 2.5)),
                             arrow_size=self.L(dx.get("dimasz", 2.5)), ext_offset=self.L(dx.get("dimexo", 0.625)),
                             ext_extension=self.L(dx.get("dimexe", 1.25)), text_gap=self.L(abs(dx.get("dimgap", 0.625))),
                             center_mark=self.L(abs(dx.get("dimcen", 2.5))), scale=dx.get("dimscale", 1.0) or 1.0,
                             decimal_places=-1 if dec == luprec else dec,
                             arrow="tick" if dx.get("dimtsz", 0) > 0 else "closed")
            doc.dimstyles[dx.name] = style

    # ---------------------------------------------------------------- entities
    def convert(self, e, depth: int = 0) -> list[Entity]:
        t = e.dxftype()
        try:
            out = self._convert(e, t, depth)
        except Exception as exc:          # a damaged object must not stop the import
            self.report.warn(f"A {t} couldn't be read ({exc}).")
            self.report.skip(t)
            return []
        if out is None:
            msg = _SKIP_MESSAGES.get(t)
            self.report.skip(msg or t)
            return []
        return out

    def _convert(self, e, t: str, depth: int):
        c = self.common(e)
        k = self.k
        if t == "LINE":
            return [Line(p1=self.P(e.dxf.start), p2=self.P(e.dxf.end), **c)]
        if t in ("CIRCLE", "ARC"):
            cx, cy = self.P(e.dxf.center)
            r = self.L(e.dxf.radius)
            if t == "CIRCLE":
                return [Circle(center=(-cx if self.flipped(e) else cx, cy), radius=r, **c)]
            a0, a1 = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
            if self.flipped(e):
                cx, a0, a1 = -cx, math.pi - a1, math.pi - a0
            return [Arc(center=(cx, cy), radius=r, start_angle=a0 % math.tau, end_angle=a1 % math.tau, **c)]
        if t == "POINT":
            return [Point(position=self.P(e.dxf.location), **c)]
        if t == "LWPOLYLINE":
            pts = [(x * k, y * k, b) for x, y, b in e.get_points("xyb")]
            if self.flipped(e):
                pts = [(-x, y, -b) for x, y, b in pts]
            if e.dxf.get("const_width", 0):
                self.report.warn("Polyline widths were not kept.")
            return [Polyline(vertices=tuple(pts), closed=e.closed, **c)] if len(pts) >= 2 else []
        if t == "POLYLINE":
            if e.is_2d_polyline:
                pts = [(v.dxf.location[0] * k, v.dxf.location[1] * k, v.dxf.get("bulge", 0.0)) for v in e.vertices]
                if self.flipped(e):
                    pts = [(-x, y, -b) for x, y, b in pts]
                return [Polyline(vertices=tuple(pts), closed=e.is_closed, **c)] if len(pts) >= 2 else []
            if e.is_3d_polyline:
                self.report.warn("3D polylines were flattened onto the drawing plane.")
                pts = [(v.dxf.location[0] * k, v.dxf.location[1] * k, 0.0) for v in e.vertices]
                return [Polyline(vertices=tuple(pts), closed=e.is_closed, **c)] if len(pts) >= 2 else []
            return self.virtual(e, depth)          # meshes / polyface: their edges
        if t == "ELLIPSE":
            cx, cy = self.P(e.dxf.center)
            mx, my = e.dxf.major_axis[0] * k, e.dxf.major_axis[1] * k
            return [Ellipse(center=(cx, cy), major=(mx, my), ratio=e.dxf.ratio, start_param=e.dxf.start_param,
                            end_param=e.dxf.end_param, **c)]
        if t == "SPLINE":
            cps = [(p[0] * k, p[1] * k) for p in e.control_points]
            fits = [(p[0] * k, p[1] * k) for p in e.fit_points]
            rational = e.weights is not None and len(e.weights) and any(abs(w - 1) > 1e-9 for w in e.weights)
            if rational:
                pts = [self.P(p) for p in e.flattening(0.01 / max(k, 1e-12))]
                return [Polyline(vertices=tuple((x, y, 0.0) for x, y in pts), closed=False, **c)]
            if not cps and len(fits) >= 2:
                s = Spline.through(fits)
                return [Spline(control_points=s.control_points, knots=s.knots, degree=s.degree, fit_points=s.fit_points,
                               closed=e.closed, **c)]
            if len(cps) < 2:
                return []
            return [Spline(control_points=tuple(cps), knots=tuple(float(x) for x in e.knots), degree=e.dxf.degree,
                           fit_points=tuple(fits), closed=bool(e.closed), **c)]
        if t in ("TEXT", "ATTDEF", "ATTRIB"):
            align, p1, p2 = e.get_placement()
            pt = p1 if align in (TextEntityAlignment.LEFT, TextEntityAlignment.ALIGNED, TextEntityAlignment.FIT) \
                or p2 is None else p2
            if align in (TextEntityAlignment.ALIGNED, TextEntityAlignment.FIT) and p2 is not None:
                pt = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            h, v = _align_of(align.name)
            x, y = self.P(pt)
            rot = math.radians(e.dxf.get("rotation", 0.0))
            if self.flipped(e):
                x, rot = -x, math.pi - rot
            style = e.dxf.get("style", "Standard")
            kw = dict(insert=(x, y), height=self.L(e.dxf.get("height", 2.5)), rotation=rot, halign=h, valign=v,
                      font=self.font(style), width_factor=e.dxf.get("width", 1.0) or 1.0)
            if t == "ATTDEF":
                return [AttributeDefinition(tag=e.dxf.tag, prompt=e.dxf.get("prompt", ""), default=e.dxf.get("text", ""),
                                            invisible=e.is_invisible, **kw, **c)]
            return [Text(text=e.plain_text(), **kw, **c)]
        if t == "MTEXT":
            v, h = _MTEXT_ALIGN.get(e.dxf.get("attachment_point", 1), ("top", "left"))
            return [MText(insert=self.P(e.dxf.insert), text=e.plain_text(split=False), height=self.L(e.dxf.get("char_height", 2.5)),
                          width=self.L(e.dxf.get("width", 0.0) or 0.0), rotation=math.radians(e.get_rotation()),
                          halign=h, valign=v, line_spacing=e.dxf.get("line_spacing_factor", 1.0) or 1.0,
                          font=self.font(e.dxf.get("style", "Standard")), **c)]
        if t == "HATCH":
            return self.hatch(e, c)
        if t in ("SOLID", "TRACE", "3DFACE"):
            vs = [self.P(e.dxf.get(n)) for n in ("vtx0", "vtx1", "vtx3", "vtx2")]
            if t == "3DFACE":
                vs = [self.P(e.dxf.get(n)) for n in ("vtx0", "vtx1", "vtx2", "vtx3")]
            pts = []
            for p in vs:
                if not pts or math.dist(pts[-1], p) > 1e-9:
                    pts.append(p)
            if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-9:
                pts.pop()
            loop = tuple((x, y, 0.0) for x, y in pts)
            if t == "3DFACE":
                return [Polyline(vertices=loop, closed=True, **c)]
            return [Hatch(loops=(loop,), pattern="SOLID", **c)]
        if t == "DIMENSION":
            dim = self.dimension(e, c)
            return [dim] if dim is not None else self.virtual(e, depth)
        if t == "LEADER":
            pts = tuple(self.P(v) for v in e.vertices)
            if len(pts) < 2:
                return []
            return [Leader(points=pts, text="", style=e.dxf.get("dimstyle", "Standard"), **c)]
        if t == "INSERT":
            return self.insert(e, c, depth)
        if t == "VIEWPORT":
            if e.dxf.get("id", 2) == 1:
                return []                       # the sheet's own "paper" viewport
            w, h = self.L(e.dxf.width), self.L(e.dxf.height)
            vh = self.L(e.dxf.get("view_height", 1.0)) or 1.0
            vc = self.P(e.dxf.get("view_center_point", (0, 0)))
            return [Viewport(center=self.P(e.dxf.center), width=w, height=h, view_center=vc, scale=h / vh,
                             locked=bool(e.dxf.get("flags", 0) & 16384), **c)]
        if t in ("MULTILEADER", "MLEADER", "MLINE", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION", "ACAD_TABLE", "MESH"):
            return self.virtual(e, depth)
        return None

    def virtual(self, e, depth: int) -> list[Entity] | None:
        """Things we don't have as objects: import what they look like."""
        if depth > 8:
            return []
        try:
            parts = list(e.virtual_entities())
        except Exception:
            return None
        out: list[Entity] = []
        for v in parts:
            out += self.convert(v, depth + 1)
        if out:
            self.report.warn(f"{e.dxftype()} objects were imported as plain lines and text.")
        return out

    def hatch(self, e, c) -> list[Entity]:
        from ezdxf.entities.boundary_paths import ArcEdge, EllipseEdge, LineEdge, PolylinePath, SplineEdge
        k = self.k
        loops = []
        for path in e.paths:
            if isinstance(path, PolylinePath):
                vs = [(x * k, y * k, b) for x, y, b in ((v[0], v[1], v[2] if len(v) > 2 else 0.0) for v in path.vertices)]
            else:
                vs = []
                for edge in path.edges:
                    if isinstance(edge, LineEdge):
                        vs.append((edge.start[0] * k, edge.start[1] * k, 0.0))
                    elif isinstance(edge, ArcEdge):
                        span = math.radians(edge.construction_tool().angle_span) or math.tau
                        sweep = span if edge.ccw else -span
                        sp = edge.real_start_point
                        vs.append((sp[0] * k, sp[1] * k, math.tan(sweep / 4)))
                    elif isinstance(edge, (EllipseEdge, SplineEdge)):
                        from ezdxf import path as ezpath
                        try:
                            pts = list(ezpath.from_hatch_edge_path(path).flattening(0.01 / max(k, 1e-12)))
                        except Exception:
                            pts = []
                        vs = [(p[0] * k, p[1] * k, 0.0) for p in pts[:-1]]
                        break
            if len(vs) >= 3 or (len(vs) == 2 and any(abs(v[2]) > 1e-12 for v in vs)):
                if self.flipped(e):
                    vs = [(-x, y, -b) for x, y, b in vs]
                loops.append(tuple(vs))
        if not loops:
            return []
        if e.dxf.solid_fill or e.has_gradient_data:
            if e.has_gradient_data:
                self.report.warn("Gradient fills were imported as solid fills.")
            name, scale, angle = "SOLID", 1.0, 0.0
        else:
            name = (e.dxf.get("pattern_name", "ANSI31") or "ANSI31").upper()
            scale = e.dxf.get("pattern_scale", 1.0) or 1.0
            angle = math.radians(e.dxf.get("pattern_angle", 0.0))
            if name not in PATTERNS:
                self.report.warn(f"Hatch pattern {name} isn't available; ANSI31 was used instead.")
                name = "ANSI31"
        return [Hatch(loops=tuple(loops), pattern=name, pattern_scale=scale, pattern_angle=angle, **c)]

    def dimension(self, e, c) -> Dimension | None:
        dx = e.dxf
        kind = dx.get("dimtype", 0) & 7
        txt = dx.get("text", "") or ""
        if txt == "<>":
            txt = ""
        if txt == " ":
            txt = ""
        base = dict(style=dx.get("dimstyle", "Standard"), text=txt, **c)
        if base["style"] not in self.doc.dimstyles:
            base["style"] = "Standard"
        g = lambda n: self.P(dx.get(n, (0, 0)))   # noqa: E731
        if kind == 0:
            return Dimension(dimtype="linear", p1=g("defpoint2"), p2=g("defpoint3"), location=g("defpoint"),
                             angle=math.radians(dx.get("angle", 0.0)), **base)
        if kind == 1:
            return Dimension(dimtype="aligned", p1=g("defpoint2"), p2=g("defpoint3"), location=g("defpoint"), **base)
        if kind == 4:
            return Dimension(dimtype="radius", p1=g("defpoint"), p2=g("defpoint4"), location=g("text_midpoint"), **base)
        if kind == 3:
            a, b = g("defpoint"), g("defpoint4")
            ctr = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            return Dimension(dimtype="diameter", p1=ctr, p2=b, location=g("text_midpoint"), **base)
        if kind == 5:
            return Dimension(dimtype="angular", p1=g("defpoint4"), p2=g("defpoint2"), p3=g("defpoint3"),
                             location=g("defpoint"), **base)
        if kind == 2:
            from ...core.geom2d.construct import line_line
            a1, a2, b1, b2 = g("defpoint2"), g("defpoint3"), g("defpoint4"), g("defpoint")
            hit = line_line(a1, (a2[0] - a1[0], a2[1] - a1[1]), b1, (b2[0] - b1[0], b2[1] - b1[1]))
            if hit is None:
                return None
            v = hit[0]
            loc = g("defpoint5")
            return Dimension(dimtype="angular", p1=v, p2=a2 if math.dist(v, a2) > math.dist(v, a1) else a1,
                             p3=b2 if math.dist(v, b2) > math.dist(v, b1) else b1, location=loc, **base)
        if kind == 6:
            axis = "x" if dx.get("dimtype", 0) & 64 else "y"
            return Dimension(dimtype="ordinate", p1=g("defpoint2"), location=g("defpoint3"), origin=g("defpoint"),
                             axis=axis, **base)
        return None

    def insert(self, e, c, depth: int) -> list[Entity]:
        if e.mcount > 1:
            out = []
            for sub in e.multi_insert():
                out += self.insert(sub, c, depth)
            return out
        name = e.dxf.name
        if name not in self.doc.blocks:
            if not self.block(name, depth):
                return self.virtual(e, depth) or []
        x, y = self.P(e.dxf.insert)
        sx, sy = e.dxf.get("xscale", 1.0), e.dxf.get("yscale", 1.0)
        rot = math.radians(e.dxf.get("rotation", 0.0))
        if self.flipped(e):
            x, sx, rot = -x, -sx, -rot
        attribs = tuple((a.dxf.tag, a.dxf.get("text", "")) for a in e.attribs)
        return [BlockReference(name=name, insert=(x, y), sx=sx, sy=sy, rotation=rot, attribs=attribs, **c)]

    def block(self, name: str, depth: int) -> bool:
        if depth > 16 or name not in self.d.blocks:
            return False
        blk = self.d.blocks.get(name)
        ents: list[Entity] = []
        self.doc.blocks[name] = BlockDefinition(name=name, base=(0.0, 0.0))     # guards against recursion
        for be in blk:
            ents += self.convert(be, depth + 1)
        bp = blk.block.dxf.get("base_point", (0, 0, 0))
        self.doc.blocks[name] = BlockDefinition(name=name, base=self.P(bp), entities=tuple(ents),
                                                description=blk.block.dxf.get("description", "") or "")
        return True

    # ---------------------------------------------------------------- the whole file
    def run(self, layouts: bool = True) -> Document:
        doc, d = self.doc, self.d
        self.tables()
        msp = d.modelspace()
        spaces: list[tuple[str, object]] = [(MODEL_SPACE, msp)]
        if layouts:
            for i, lo in enumerate(d.layouts.names_in_taborder()):
                if lo.lower() == "model":
                    continue
                pl = d.layouts.get(lo)
                if len(pl) <= 1 and lo.startswith("Layout") and not any(True for _ in pl.query("INSERT")):
                    continue                                    # an empty default sheet
                w, h = self._paper_size(pl)
                doc.layouts[lo] = Layout(lo, paper="Custom", width=max(w, h), height=min(w, h), order=i,
                                         portrait=h > w)
                spaces.append((lo, pl))
        for space, src in spaces:
            for e in src:
                for ent in self.convert(e):
                    ent = ent.with_props(space=space)
                    added = doc.add(ent, use_current_props=False)
                    self.handle_map[e.dxf.handle] = added.handle
                    self.report.count(added.TYPE)
        for g in d.groups:
            name, grp = g
            hs = frozenset(self.handle_map[x.dxf.handle] for x in grp if x.dxf.handle in self.handle_map)
            if hs:
                doc.groups[name] = Group(name, hs, grp.dxf.get("description", "") or "")
        return doc

    def _paper_size(self, pl) -> tuple[float, float]:
        dx = pl.dxf_layout.dxf
        w, h = dx.get("paper_width", 0.0), dx.get("paper_height", 0.0)
        if dx.get("plot_rotation", 0) in (1, 3):
            w, h = h, w
        if w <= 0 or h <= 0:
            lim = (dx.get("limmin", (0, 0)), dx.get("limmax", (420, 297)))
            w, h = self.L(lim[1][0] - lim[0][0]), self.L(lim[1][1] - lim[0][1])
        return float(w), float(h)


def detect_units(d, override: str) -> tuple[float, UnitMode]:
    lunits = d.header.get("$LUNITS", 2)
    if override != "auto":
        k = FILE_UNITS[override]
    else:
        ins = d.header.get("$INSUNITS", 0)
        if ins in INSUNITS_MM:
            k = INSUNITS_MM[ins]
        elif lunits in (3, 4) or d.header.get("$MEASUREMENT", 1) == 0:
            k = 25.4                       # unitless imperial drawing: AutoCAD means inches
        else:
            k = 1.0
    if lunits == 4 or (k in (25.4, 304.8) and lunits == 3):
        mode = UnitMode.ARCHITECTURAL
    elif k in (25.4, 304.8):
        mode = UnitMode.FRACTIONAL
    else:
        mode = UnitMode.MM
    return k, mode


def read_dxf(path: str, report: Report, file_units: str = "auto", layouts: bool = True) -> Document:
    try:
        d = ezdxf.readfile(path)
    except IOError as exc:
        raise PluginError(f"Couldn't open {os.path.basename(path)}: {exc}") from exc
    except (DXFStructureError, DXFError, UnicodeDecodeError):
        try:
            d, auditor = recover.readfile(path)
        except Exception as exc:
            raise PluginError(f"{os.path.basename(path)} isn't a readable DXF file ({exc}).") from exc
        report.warn(f"The file was damaged; {len(auditor.fixes)} problems were repaired while reading it.")
    k, mode = detect_units(d, file_units)
    r = Reader(d, report, k)
    from dataclasses import replace
    with r.doc.transaction("Import DXF"):
        r.doc.set_header(replace(r.doc.header, units=r.doc.header.units.with_mode(mode),
                                 ltscale=float(d.header.get("$LTSCALE", 1.0) or 1.0)))
        r.run(layouts)
        cl = d.header.get("$CLAYER", "0")
        if cl in r.doc.layers:
            r.doc.set_current_layer(cl)
    r.doc.clear_history()
    r.doc.mark_saved()
    report.info(f"DXF version {d.acad_release}; units: {'inches' if k == 25.4 else 'feet' if k == 304.8 else 'mm' if k == 1 else f'{k:g} mm per unit'}.")
    return r.doc


__all__ = ["read_dxf", "detect_units"]
