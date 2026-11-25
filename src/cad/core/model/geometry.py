"""Entity -> drawable/snappable geometry.

`build_geometry(doc, entity)` returns a Geometry: line primitives, filled areas,
text runs and snap points, split into Parts that may carry their own resolved
style (needed for block references, whose contents can be ByBlock / on layer 0).
Every consumer — snapping, picking, rendering, exporting — uses this, so a new
entity type only has to be taught here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..geom2d import Arc as ArcPrim
from ..geom2d import BBox, Primitive, Seg, Vec, bbox_union
from ..geom2d.fill import point_in_loops
from ..geom2d.transform import Affine2
from ..text import TextRun, text_engine
from .entities import (
    AttributeDefinition, BlockReference, Dimension, Entity, Hatch, Leader, MText, Text, UnknownEntity,
)
from .styles import BYBLOCK, BYLAYER, LW_BYBLOCK, LW_BYLAYER

MAX_BLOCK_DEPTH = 12


@dataclass(slots=True)
class Part:
    prims: list[Primitive] = field(default_factory=list)
    fills: list[list[np.ndarray]] = field(default_factory=list)   # each: loops filled together (even-odd)
    triangles: list[np.ndarray] = field(default_factory=list)     # already triangulated fills (k, 3, 2)
    texts: list[TextRun] = field(default_factory=list)
    color: object = None          # None: use the entity's own effective style
    linetype: str | None = None
    lineweight: float | None = None
    snappable: bool = True


@dataclass(slots=True)
class Geometry:
    parts: list[Part] = field(default_factory=list)
    endpoints: list[Vec] = field(default_factory=list)
    midpoints: list[Vec] = field(default_factory=list)
    centers: list[Vec] = field(default_factory=list)
    quadrants: list[Vec] = field(default_factory=list)
    nodes: list[Vec] = field(default_factory=list)
    insertions: list[Vec] = field(default_factory=list)
    grips: list[Vec] = field(default_factory=list)
    pick_areas: list[list[np.ndarray]] = field(default_factory=list)   # click inside selects (hatch, text)
    bbox: BBox | None = None

    def prims(self, snappable_only: bool = False) -> list[Primitive]:
        out: list[Primitive] = []
        for p in self.parts:
            if not snappable_only or p.snappable:
                out.extend(p.prims)
        return out

    def distance_to(self, pt: Vec) -> float:
        for loops in self.pick_areas:
            if point_in_loops(pt[0], pt[1], loops):
                return 0.0
        prims = self.prims()
        if not prims:
            if self.nodes or self.insertions:
                return min(math.dist(pt, p) for p in self.nodes + self.insertions)
            return math.inf
        return min(p.distance_to(pt) for p in prims)

    def compute_bbox(self) -> None:
        boxes = [p.bbox() for part in self.parts for p in part.prims]
        for part in self.parts:
            for loops in part.fills:
                for lp in loops:
                    if len(lp):
                        boxes.append((float(lp[:, 0].min()), float(lp[:, 1].min()),
                                      float(lp[:, 0].max()), float(lp[:, 1].max())))
        for loops in self.pick_areas:
            for lp in loops:
                if len(lp):
                    boxes.append((float(lp[:, 0].min()), float(lp[:, 1].min()),
                                  float(lp[:, 0].max()), float(lp[:, 1].max())))
        for p in self.nodes + self.insertions:
            boxes.append((p[0], p[1], p[0], p[1]))
        self.bbox = bbox_union(boxes)


# ================================================================== helpers
def transform_prim(p: Primitive, m: Affine2) -> list[Primitive]:
    if isinstance(p, Seg):
        return [Seg(m.apply(p.p), m.apply(p.q))]
    if m.is_similarity:
        c = m.apply(p.c)
        s = m.apply(p.start)
        a0 = math.atan2(s[1] - c[1], s[0] - c[0])
        sweep = -p.sweep if m.is_mirror else p.sweep
        return [ArcPrim(c, p.r * m.scale_factor, a0, sweep)]
    pts = m.apply_array(p.tessellate(p.r * 1e-3))
    return [Seg(tuple(pts[i]), tuple(pts[i + 1])) for i in range(len(pts) - 1)]


def text_part(run: TextRun) -> tuple[Part, list[np.ndarray]]:
    lay = text_engine().layout(run)
    box = np.array(lay.box, dtype=np.float64)
    part = Part(fills=[lay.loops] if lay.loops else [], texts=[run])
    if lay.triangles is not None and len(lay.triangles):
        part.triangles.append(lay.triangles)
    return part, box


def _simple(e: Entity) -> Geometry:
    g = Geometry(parts=[Part(prims=e.primitives())], endpoints=e.endpoints(), midpoints=e.midpoints(),
                 centers=e.centers(), quadrants=e.quadrants(), nodes=e.nodes(), insertions=e.insertion_points(),
                 grips=e.grip_points())
    return g


# ================================================================== builders
def build_geometry(doc, e: Entity, depth: int = 0) -> Geometry:
    if isinstance(e, UnknownEntity):
        return Geometry()
    if isinstance(e, (Text, AttributeDefinition)):
        g = _text_geometry(e)
    elif isinstance(e, MText):
        run = TextRun(e.text, e.insert, e.height, e.rotation, 1.0, e.halign, e.valign, e.font,
                      wrap_width=e.width, line_spacing=e.line_spacing, multiline=True)
        part, box = text_part(run)
        g = Geometry(parts=[part], insertions=[e.insert], grips=[e.insert], pick_areas=[[box]])
        g.nodes = []
    elif isinstance(e, Hatch):
        g = _hatch_geometry(doc, e)
    elif isinstance(e, Dimension):
        from .dimensions import dimension_geometry
        g = dimension_geometry(doc, e)
    elif isinstance(e, Leader):
        from .dimensions import leader_geometry
        g = leader_geometry(doc, e)
    elif isinstance(e, BlockReference):
        g = _block_geometry(doc, e, depth)
    else:
        g = _simple(e)
    g.compute_bbox()
    if not g.grips:
        g.grips = e.grip_points()
    return g


def _text_geometry(e) -> Geometry:
    text = e.text if isinstance(e, Text) else (e.tag or "")
    run = TextRun(text, e.insert, e.height, e.rotation, getattr(e, "width_factor", 1.0), e.halign, e.valign,
                  e.font)
    part, box = text_part(run)
    return Geometry(parts=[part], insertions=[e.insert], grips=[e.insert], pick_areas=[[box]])


def _hatch_geometry(doc, e: Hatch) -> Geometry:
    from .hatch_patterns import PatternTooDense, pattern_segments
    loops = e.loop_points()
    part = Part(snappable=False)
    if e.pattern.upper() == "SOLID":
        part.fills.append(loops)
    else:
        try:
            part.prims = pattern_segments(loops, e.pattern, e.pattern_scale, e.pattern_angle)
        except PatternTooDense:
            part.prims = e.boundary_primitives()        # too dense to draw: show the outline
    return Geometry(parts=[part], pick_areas=[loops], grips=e.grip_points())


def _resolve_child_style(doc, ref: BlockReference, child: Entity, inherited: dict | None):
    """Effective color / linetype / lineweight of an object inside a block reference."""
    ref_color = inherited["color"] if inherited else doc.effective_color(ref)
    ref_lt = inherited["linetype"] if inherited else doc.effective_linetype(ref).name
    ref_lw = inherited["lineweight"] if inherited else doc.effective_lineweight(ref)
    child_layer = doc.layers.get(child.layer)
    on_layer0 = child.layer == "0"

    if child.color == BYBLOCK or (child.color == BYLAYER and on_layer0):
        color = ref_color
    elif child.color == BYLAYER:
        color = child_layer.color if child_layer else 7
    else:
        color = child.color
    lt = child.linetype
    if lt.lower() == "byblock" or (lt.lower() == "bylayer" and on_layer0):
        lt = ref_lt
    elif lt.lower() == "bylayer":
        lt = child_layer.linetype if child_layer else "Continuous"
    lw = child.lineweight
    if lw == LW_BYBLOCK or (lw == LW_BYLAYER and on_layer0):
        lw = ref_lw
    elif lw == LW_BYLAYER:
        lw = child_layer.lineweight if child_layer else -3.0
    return {"color": color, "linetype": lt, "lineweight": lw}


def _block_geometry(doc, ref: BlockReference, depth: int, inherited: dict | None = None) -> Geometry:
    g = Geometry(insertions=[ref.insert], grips=[ref.insert])
    bdef = doc.blocks.get(ref.name)
    if bdef is None or depth > MAX_BLOCK_DEPTH:
        g.nodes = [ref.insert]
        return g
    m = ref.matrix(bdef.base)
    sf = m.scale_factor
    for child in bdef.entities:
        layer = doc.layers.get(child.layer)
        if layer is not None and child.layer != "0" and not layer.visible:
            continue
        style = _resolve_child_style(doc, ref, child, inherited)
        if isinstance(child, AttributeDefinition):
            if child.invisible:
                continue
            value = ref.attrib(child.tag, child.default)
            t = Text(insert=child.insert, text=value, height=child.height, rotation=child.rotation,
                     halign=child.halign, valign=child.valign, font=child.font).transformed(m)
            cg = _text_geometry(t)
        elif isinstance(child, BlockReference):
            nested = child.transformed(m)
            cg = _block_geometry(doc, nested, depth + 1, style)
            cg.compute_bbox()
            for part in cg.parts:
                g.parts.append(part)
            g.endpoints += cg.endpoints
            g.midpoints += cg.midpoints
            g.centers += cg.centers
            g.quadrants += cg.quadrants
            g.nodes += cg.nodes
            g.pick_areas += cg.pick_areas
            continue
        else:
            cg = build_geometry(doc, child, depth + 1)
            cg = _transform_geometry(cg, m, sf)
        for part in cg.parts:
            if part.color is None:
                part.color, part.linetype, part.lineweight = style["color"], style["linetype"], style["lineweight"]
            g.parts.append(part)
        g.endpoints += cg.endpoints
        g.midpoints += cg.midpoints
        g.centers += cg.centers
        g.quadrants += cg.quadrants
        g.nodes += cg.nodes
        g.pick_areas += cg.pick_areas
    return g


def _transform_geometry(cg: Geometry, m: Affine2, sf: float) -> Geometry:
    out = Geometry()
    for part in cg.parts:
        np_ = Part(snappable=part.snappable, color=part.color, linetype=part.linetype, lineweight=part.lineweight)
        for p in part.prims:
            np_.prims.extend(transform_prim(p, m))
        np_.fills = [[m.apply_array(lp) for lp in loops] for loops in part.fills]
        np_.triangles = [m.apply_array(t.reshape(-1, 2)).reshape(-1, 3, 2) for t in part.triangles]
        np_.texts = [TextRun(r.text, m.apply(r.insert), r.height * sf, r.rotation + m.rotation, r.width_factor,
                             r.halign, r.valign, r.font, r.wrap_width * sf, r.line_spacing, r.multiline)
                     for r in part.texts]
        out.parts.append(np_)
    tp = lambda pts: [m.apply(p) for p in pts]  # noqa: E731
    out.endpoints, out.midpoints, out.centers = tp(cg.endpoints), tp(cg.midpoints), tp(cg.centers)
    out.quadrants, out.nodes, out.insertions = tp(cg.quadrants), tp(cg.nodes), tp(cg.insertions)
    out.pick_areas = [[m.apply_array(lp) for lp in loops] for loops in cg.pick_areas]
    return out


def explode_block_reference(doc, ref: BlockReference) -> list[Entity]:
    """The block's contents as standalone entities, placed where the reference is."""
    bdef = doc.blocks.get(ref.name)
    if bdef is None:
        return []
    m = ref.matrix(bdef.base)
    out = []
    for child in bdef.entities:
        style = _resolve_child_style(doc, ref, child, None)
        if isinstance(child, AttributeDefinition):
            if child.invisible:
                continue
            t = Text(insert=child.insert, text=ref.attrib(child.tag, child.default), height=child.height,
                     rotation=child.rotation, halign=child.halign, valign=child.valign, font=child.font)
            child = t
        e = child.transformed(m)
        layer = child.layer if child.layer != "0" else ref.layer
        e = e.with_props(handle=0, layer=layer if layer in doc.layers else ref.layer,
                         color=style["color"] if child.color in (BYBLOCK,) or child.layer == "0" else child.color,
                         space=ref.space)
        out.append(e)
    return out
