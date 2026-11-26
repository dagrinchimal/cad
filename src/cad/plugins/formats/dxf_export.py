"""Writing DXF with ezdxf (R12 to 2018). Imported by the DXF plugin; no PLUGINS list here."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import ezdxf
from ezdxf.colors import rgb2int
from ezdxf.enums import TextEntityAlignment
from ezdxf.lldxf.const import VALID_DXF_LINEWEIGHTS

from ...core.geom2d.fill import triangulate
from ...core.geom2d.primitives import Arc as ArcPrim
from ...core.model import (
    MODEL_SPACE, Arc, ArrayEntity, AttributeDefinition, BlockReference, Circle, Dimension, Document, Ellipse,
    Entity, Hatch, Leader, Line, MText, Point, Polyline, Spline, Text, UnknownEntity, Viewport,
)
from ...core.model.geometry import explode_array
from ...core.model.hatch_patterns import PATTERNS
from ...core.model.styles import BYBLOCK, BYLAYER
from ...core.units import UnitMode
from ..base import Report

VERSIONS = {"R12": "AC1009", "R2000": "AC1015", "R2004": "AC1018", "R2007": "AC1021", "R2010": "AC1024",
            "R2013": "AC1027", "R2018": "AC1032"}
MM_PER_INCH = 25.4

_HALIGN = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}
_VALIGN = {"bottom": "BOTTOM", "middle": "MIDDLE", "top": "TOP"}
_MTEXT_ATTACH = {("top", "left"): 1, ("top", "center"): 2, ("top", "right"): 3,
                 ("middle", "left"): 4, ("middle", "center"): 5, ("middle", "right"): 6,
                 ("bottom", "left"): 7, ("bottom", "center"): 8, ("bottom", "right"): 9,
                 ("baseline", "left"): 7, ("baseline", "center"): 8, ("baseline", "right"): 9}


def text_alignment(halign: str, valign: str) -> TextEntityAlignment:
    h = _HALIGN.get(halign, "LEFT")
    if valign in _VALIGN:
        return TextEntityAlignment[f"{_VALIGN[valign]}_{h}"]
    return TextEntityAlignment[h]


def nearest_lineweight(mm: float) -> int:
    if mm < 0:
        return int(mm)               # -1 ByLayer, -2 ByBlock, -3 Default
    target = round(mm * 100)
    return min(VALID_DXF_LINEWEIGHTS, key=lambda v: abs(v - target))


def _rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def nearest_aci(rgb: tuple[int, int, int]) -> int:
    from ezdxf.colors import aci2rgb
    best, bd = 7, 1e18
    for i in range(1, 256):
        r, g, b = aci2rgb(i)
        d = (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
        if d < bd:
            best, bd = i, d
    return best


@dataclass
class Writer:
    doc: Document
    version: str
    k: float                                    # file units per mm
    report: Report
    dxf: ezdxf.document.Drawing = None
    handle_map: dict = field(default_factory=dict)   # our handle -> dxf entity (for groups)
    styles: dict = field(default_factory=dict)

    @property
    def r12(self) -> bool:
        return self.version == "R12"

    # ---------------------------------------------------------------- helpers
    def P(self, p) -> tuple[float, float]:
        return (p[0] * self.k, p[1] * self.k)

    def L(self, v: float) -> float:
        return v * self.k

    def attribs(self, e: Entity, color=None, layer=None) -> dict:
        a: dict = {"layer": layer or e.layer}
        c = e.color if color is None else color
        if isinstance(c, str):
            rgb = _rgb(c)
            a["color"] = nearest_aci(rgb)
            if not self.r12:
                a["true_color"] = rgb2int(rgb)
        else:
            a["color"] = c
        lt = e.linetype
        if lt not in ("ByLayer", "BYLAYER"):
            a["linetype"] = "BYBLOCK" if lt.lower() == "byblock" else lt
        if not self.r12:
            a["lineweight"] = nearest_lineweight(e.lineweight)
        if e.ltscale != 1.0:
            a["ltscale"] = e.ltscale
        return a

    def text_style(self, font: str | None) -> str:
        font = font or "Arial"
        if font in self.styles:
            return self.styles[font]
        name = "Standard" if font == "Arial" else font.replace(" ", "_")
        if name not in self.dxf.styles:
            self.dxf.styles.add(name, font=f"{font.lower().replace(' ', '')}.ttf")
        else:
            self.dxf.styles.get(name).dxf.font = f"{font.lower().replace(' ', '')}.ttf"
        self.styles[font] = name
        return name

    # ---------------------------------------------------------------- tables
    def tables(self) -> None:
        d, doc = self.dxf, self.doc
        for lt in doc.linetypes.values():
            if lt.is_continuous or lt.name in d.linetypes:
                if lt.name in d.linetypes and not lt.is_continuous:
                    d.linetypes.remove(lt.name)
                else:
                    continue
            pat = [self.L(v) for v in lt.pattern]
            d.linetypes.add(lt.name, [sum(abs(v) for v in pat)] + pat, description=lt.description)
        for lay in doc.layers.values():
            attrs: dict = {"linetype": lay.linetype if lay.linetype in d.linetypes else "Continuous"}
            if isinstance(lay.color, str):
                attrs["color"] = nearest_aci(_rgb(lay.color))
                if not self.r12:
                    attrs["true_color"] = rgb2int(_rgb(lay.color))
            else:
                attrs["color"] = lay.color
            if not self.r12:
                attrs["lineweight"] = nearest_lineweight(lay.lineweight)
                attrs["plot"] = 1 if lay.plot else 0
            if lay.name in d.layers:               # "0", "Defpoints" and the like already exist
                layer = d.layers.get(lay.name)
                for kk, vv in attrs.items():
                    layer.dxf.set(kk, vv)
            else:
                layer = d.layers.add(lay.name, **{kk: vv for kk, vv in attrs.items() if kk not in ("plot",)})
                if "plot" in attrs:
                    layer.dxf.plot = attrs["plot"]
            if not lay.on:
                layer.off()
            if lay.frozen:
                layer.freeze()
            if lay.locked:
                layer.lock()
            if lay.description and not self.r12:
                layer.description = lay.description
        self.text_style("Arial")
        # dimension styles
        for ds in doc.dimstyles.values():
            name = ds.name
            attrs = {"dimtxt": self.L(ds.text_height), "dimasz": self.L(ds.arrow_size), "dimexo": self.L(ds.ext_offset),
                     "dimexe": self.L(ds.ext_extension), "dimgap": self.L(ds.text_gap),
                     "dimcen": self.L(ds.center_mark), "dimscale": ds.scale}
            attrs["dimdec"] = ds.decimal_places if ds.decimal_places >= 0 else doc.header.units.decimal_places
            attrs["dimadec"] = doc.header.units.angle_decimal_places
            if ds.arrow == "tick":
                attrs["dimtsz"] = self.L(ds.arrow_size)
            st = d.dimstyles.get(name) if name in d.dimstyles else d.dimstyles.new(name)
            for kk, vv in attrs.items():
                st.dxf.set(kk, vv)
            mode = doc.header.units.mode
            st.dxf.dimlunit = 4 if mode is UnitMode.ARCHITECTURAL else 5 if mode is UnitMode.FRACTIONAL else 2
            st.dxf.dimtxsty = self.text_style(ds.font)

    def header(self) -> None:
        d, h = self.dxf, self.doc.header
        mode = h.units.mode
        inches = self.k != 1.0
        d.header["$INSUNITS"] = 1 if inches else 4
        d.header["$MEASUREMENT"] = 0 if inches else 1
        d.header["$LUNITS"] = 4 if mode is UnitMode.ARCHITECTURAL else 5 if mode is UnitMode.FRACTIONAL else 2
        d.header["$LTSCALE"] = h.ltscale
        d.header["$TEXTSIZE"] = self.L(h.text_height)
        if h.current_layer in d.layers:
            d.header["$CLAYER"] = h.current_layer
        d.header["$LUPREC"] = int(h.units.decimal_places)
        if not self.r12:
            d.header["$PSLTSCALE"] = 1

    # ---------------------------------------------------------------- entities
    def write(self, e: Entity, target, report_kind: bool = True) -> None:
        """Write one entity into an ezdxf layout or block."""
        try:
            done = self._write(e, target)
        except Exception as exc:                       # never lose the whole export over one object
            self.report.warn(f"A {e.TYPE} couldn't be written as itself ({exc}); it was exported as lines.")
            done = None
        if done is None:
            self.explode(e, target)
            if report_kind:
                self.report.count("array (as separate copies)" if isinstance(e, ArrayEntity)
                                  else f"{e.TYPE} (as lines)")
        elif report_kind:
            self.report.count(e.TYPE)
        if done is not None and e.handle:
            self.handle_map[e.handle] = done

    def _write(self, e: Entity, t):
        a = self.attribs(e)
        r12 = self.r12
        if isinstance(e, Line):
            return t.add_line(self.P(e.p1), self.P(e.p2), dxfattribs=a)
        if isinstance(e, Circle):
            return t.add_circle(self.P(e.center), self.L(e.radius), dxfattribs=a)
        if isinstance(e, Arc):
            return t.add_arc(self.P(e.center), self.L(e.radius), math.degrees(e.start_angle),
                             math.degrees(e.end_angle), dxfattribs=a)
        if isinstance(e, Point):
            return t.add_point(self.P(e.position), dxfattribs=a)
        if isinstance(e, Polyline):
            pts = [(x * self.k, y * self.k, b) for x, y, b in e.vertices]
            if r12:
                return t.add_polyline2d(pts, format="xyb", close=e.closed, dxfattribs=a)
            return t.add_lwpolyline(pts, format="xyb", close=e.closed, dxfattribs=a)
        if isinstance(e, Ellipse) and not r12:
            return t.add_ellipse(self.P(e.center), (e.major[0] * self.k, e.major[1] * self.k, 0), e.ratio,
                                 e.start_param, e.end_param, dxfattribs=a)
        if isinstance(e, Spline) and not r12:
            s = t.add_spline(dxfattribs=a)
            s.dxf.degree = e.degree
            s.control_points = [(x * self.k, y * self.k, 0) for x, y in e.control_points]
            s.knots = list(e.knots)
            if e.fit_points:
                s.fit_points = [(x * self.k, y * self.k, 0) for x, y in e.fit_points]
            if e.closed:
                s.closed = True
            return s
        if isinstance(e, Text):
            a.update(height=self.L(e.height), rotation=math.degrees(e.rotation), style=self.text_style(e.font))
            if e.width_factor != 1.0:
                a["width"] = e.width_factor
            txt = t.add_text(e.text, dxfattribs=a)
            txt.set_placement(self.P(e.insert), align=text_alignment(e.halign, e.valign))
            return txt
        if isinstance(e, MText) and not r12:
            a.update(char_height=self.L(e.height), width=self.L(e.width), insert=self.P(e.insert),
                     rotation=math.degrees(e.rotation), style=self.text_style(e.font),
                     attachment_point=_MTEXT_ATTACH.get((e.valign, e.halign), 1),
                     line_spacing_factor=max(0.25, min(4.0, e.line_spacing)))
            return t.add_mtext(e.text, dxfattribs=a)
        if isinstance(e, AttributeDefinition):
            a.update(height=self.L(e.height), rotation=math.degrees(e.rotation), prompt=e.prompt,
                     style=self.text_style(e.font))
            if e.invisible:
                a["flags"] = 1
            ad = t.add_attdef(e.tag, self.P(e.insert), e.default, dxfattribs=a)
            ad.set_placement(self.P(e.insert), align=text_alignment(e.halign, e.valign))
            return ad
        if isinstance(e, BlockReference):
            if e.name not in self.dxf.blocks:
                return None
            a.update(xscale=e.sx, yscale=e.sy, rotation=math.degrees(e.rotation))
            ref = t.add_blockref(e.name, self.P(e.insert), dxfattribs=a)
            if e.attribs:
                ref.add_auto_attribs(dict(e.attribs))
            return ref
        if isinstance(e, Hatch) and not r12:
            return self.hatch(e, t, a)
        if isinstance(e, Dimension):
            return self.dimension(e, t, a)
        if isinstance(e, Leader) and not r12:
            pts = [self.P(p) for p in e.points]
            ld = t.add_leader(pts, dimstyle=e.style if e.style in self.dxf.dimstyles else "Standard", dxfattribs=a)
            if e.text:
                ds = self.doc.dimstyle(e.style)
                h = self.L(ds.text_height * ds.scale)
                end, prev = e.points[-1], e.points[-2] if len(e.points) > 1 else e.points[-1]
                right = end[0] >= prev[0]
                ma = dict(self.attribs(e), char_height=h, insert=self.P((end[0] + (1 if right else -1) * h * 0.5, end[1])),
                          attachment_point=4 if right else 6)
                t.add_mtext(e.text, dxfattribs=ma)
            return ld
        if isinstance(e, Viewport):
            return None if self.r12 else self.viewport(e, t)
        if isinstance(e, UnknownEntity):
            self.report.skip(e.extra.get("dxftype", "unknown object"))
            return False
        return None                     # anything else: drawn as lines

    def hatch(self, e: Hatch, t, a):
        h = t.add_hatch(dxfattribs=a)
        for loop in e.loops:
            h.paths.add_polyline_path([(x * self.k, y * self.k, b) for x, y, b in loop], is_closed=True)
        if e.pattern.upper() == "SOLID":
            h.set_solid_fill(color=a["color"])
        else:
            lines = PATTERNS.get(e.pattern.upper())
            definition = None
            if lines:
                definition = [[pl.angle, (pl.origin[0] * self.k, pl.origin[1] * self.k),
                               (pl.shift * self.k, pl.spacing * self.k), [d * self.k for d in pl.dashes]]
                              for pl in lines]
            h.set_pattern_fill(e.pattern.upper(), color=a["color"], angle=math.degrees(e.pattern_angle),
                               scale=e.pattern_scale, definition=definition)
        if "true_color" in a:
            h.dxf.true_color = a["true_color"]
        return h

    def dimension(self, e: Dimension, t, a):
        ds_name = e.style if e.style in self.dxf.dimstyles else "Standard"
        text = e.text if e.text else "<>"
        k = self.k
        if e.dimtype == "linear":
            dim = t.add_linear_dim(base=self.P(e.location), p1=self.P(e.p1), p2=self.P(e.p2),
                                   angle=math.degrees(e.angle), text=text, dimstyle=ds_name, dxfattribs=a)
        elif e.dimtype == "aligned":
            dx, dy = e.p2[0] - e.p1[0], e.p2[1] - e.p1[1]
            L = math.hypot(dx, dy) or 1.0
            off = ((e.location[0] - e.p1[0]) * -dy + (e.location[1] - e.p1[1]) * dx) / L
            dim = t.add_aligned_dim(p1=self.P(e.p1), p2=self.P(e.p2), distance=off * k, text=text,
                                    dimstyle=ds_name, dxfattribs=a)
        elif e.dimtype == "radius":
            r = math.dist(e.p1, e.p2) * k
            dim = t.add_radius_dim(center=self.P(e.p1), radius=r, location=self.P(e.location),
                                   text=text, dimstyle=ds_name, dxfattribs=a)
        elif e.dimtype == "diameter":
            r = math.dist(e.p1, e.p2) * k
            dim = t.add_diameter_dim(center=self.P(e.p1), radius=r, location=self.P(e.location),
                                     text=text, dimstyle=ds_name, dxfattribs=a)
        elif e.dimtype == "angular":
            dim = t.add_angular_dim_3p(base=self.P(e.location), center=self.P(e.p1), p1=self.P(e.p2),
                                       p2=self.P(e.p3), text=text, dimstyle=ds_name, dxfattribs=a)
        elif e.dimtype == "ordinate":
            off = ((e.location[0] - e.p1[0]) * k, (e.location[1] - e.p1[1]) * k)
            fn = t.add_ordinate_x_dim if e.axis == "x" else t.add_ordinate_y_dim
            dim = fn(feature_location=self.P(e.p1), offset=off, origin=self.P(e.origin), text=text,
                     dimstyle=ds_name, dxfattribs=a)
        else:
            return None
        dim.render()
        return dim.dimension

    def viewport(self, e: Viewport, t):
        from ...core.layouts import resolve_viewport
        from ...core.plot import model_extents
        (vcx, vcy), s = resolve_viewport(self.doc, e, model_extents(self.doc))
        vp = t.add_viewport(center=self.P(e.center), size=(self.L(e.width), self.L(e.height)),
                            view_center_point=(vcx * self.k, vcy * self.k), view_height=self.L(e.height) / max(s, 1e-12),
                            dxfattribs={"layer": e.layer})
        if e.locked:
            vp.dxf.flags = vp.dxf.flags | 16384
        return vp

    def explode(self, e: Entity, t) -> None:
        """Fallback: write what the object looks like as lines, arcs, text and fills."""
        if isinstance(e, ArrayEntity):
            for c in explode_array(self.doc, e):
                self.write(c, t, report_kind=False)
            return
        if isinstance(e, Viewport):
            return
        geo = self.doc.geometry(e)
        for part in geo.parts:
            color = e.color if part.color is None else part.color
            a = self.attribs(e, color=color)
            if part.color is not None:
                a.pop("linetype", None)
                if part.linetype:
                    a["linetype"] = part.linetype
            for prim in part.prims:
                if isinstance(prim, ArcPrim):
                    if prim.is_full:
                        t.add_circle(self.P(prim.c), self.L(prim.r), dxfattribs=a)
                    else:
                        a0, a1 = prim.a0, prim.a0 + prim.sweep
                        if prim.sweep < 0:
                            a0, a1 = a1, a0
                        t.add_arc(self.P(prim.c), self.L(prim.r), math.degrees(a0), math.degrees(a1), dxfattribs=a)
                else:
                    t.add_line(self.P(prim.p), self.P(prim.q), dxfattribs=a)
            for run in part.texts:
                ta = dict(a, height=self.L(run.height), rotation=math.degrees(run.rotation),
                          style=self.text_style(run.font))
                for i, line in enumerate(run.text.split("\n") if run.multiline else [run.text]):
                    lh = run.height * 1.667 * run.line_spacing * i
                    c, s = math.cos(run.rotation), math.sin(run.rotation)
                    ins = (run.insert[0] + lh * s, run.insert[1] - lh * c)
                    txt = t.add_text(line, dxfattribs=ta)
                    txt.set_placement(self.P(ins), align=text_alignment(run.halign,
                                                                          "top" if run.multiline else run.valign))
            for loops in part.fills:
                if self.r12:
                    for tri in triangulate(loops):
                        p = [self.P(v) for v in tri]
                        t.add_solid([p[0], p[1], p[2]], dxfattribs=a)
                else:
                    h = t.add_hatch(dxfattribs=a)
                    for lp in loops:
                        h.paths.add_polyline_path([self.P(v) for v in lp], is_closed=True)
                    h.set_solid_fill(color=a["color"])

    # ---------------------------------------------------------------- the whole drawing
    def run(self) -> ezdxf.document.Drawing:
        doc = self.doc
        self.dxf = ezdxf.new(VERSIONS[self.version], setup=False, units=1 if self.k != 1 else 4)
        self.tables()
        self.header()
        # blocks first (inserts need them); skip our internal title-block helpers only if empty
        for name, bdef in doc.blocks.items():
            if self.r12 and name.startswith("*"):
                continue
            blk = self.dxf.blocks.new(name, base_point=self.P(bdef.base))
            for be in bdef.entities:
                self.write(be, blk, report_kind=False)
        msp = self.dxf.modelspace()
        layouts = {}
        if not self.r12:
            for name, lo in sorted(doc.layouts.items(), key=lambda kv: kv[1].order):
                w, h = lo.size
                pl = self.dxf.layouts.new(name) if name not in self.dxf.layouts else self.dxf.layouts.get(name)
                units = "inch" if self.k != 1 else "mm"
                pl.page_setup(size=(w * self.k, h * self.k), margins=(0, 0, 0, 0), units=units)
                layouts[name] = pl
            if layouts and "Layout1" in self.dxf.layouts and "Layout1" not in layouts:
                self.dxf.layouts.delete("Layout1")
        elif doc.layouts:
            self.report.warn("DXF R12 has no layouts: only model space was exported.")
        for e in doc.entities.values():
            if e.space == MODEL_SPACE:
                target = msp
            elif e.space in layouts:
                target = layouts[e.space]
            else:
                continue
            self.write(e, target)
        # groups
        if not self.r12:
            for g in doc.groups.values():
                members = [self.handle_map[h] for h in g.handles if self.handle_map.get(h) not in (None, False)]
                if members:
                    grp = self.dxf.groups.new(g.name, description=g.description)
                    grp.extend(members)
        return self.dxf


def write_dxf(doc: Document, path: str, version: str, file_units: str, report: Report) -> None:
    if version not in VERSIONS:
        raise ValueError(f"Unknown DXF version {version}")
    mode = doc.header.units.mode
    inches = file_units == "inches" or (file_units == "auto" and mode is not UnitMode.MM)
    w = Writer(doc, version, 1 / MM_PER_INCH if inches else 1.0, report)
    d = w.run()
    d.saveas(path)
    report.info(f"Saved as DXF {version}, {'inches' if inches else 'millimeters'}.")


__all__ = ["write_dxf", "VERSIONS", "text_alignment", "nearest_lineweight", "nearest_aci", "BYBLOCK", "BYLAYER"]
