"""Turns document entities into flat arrays of line segments for drawing.

Each segment is one row of a float32 array (an "instance"):

    p0x p0y p1x p1y  dist0  r g b a  width_px  linetype_index  ltscale

Coordinates are relative to `origin` (so float32 keeps sub-micron precision
around the drawing). Curves are tessellated to a chord tolerance tied to the
zoom level at the last regen, like AutoCAD's VIEWRES.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.geom2d.fill import triangulate
from ..core.geom2d.primitives import Arc as ArcPrim
from ..core.model import MODEL_SPACE, ChangeSet, Document, Entity, Point
from ..core.model.styles import (
    DEFAULT_LINEWEIGHT_MM, LW_DEFAULT, MAX_PATTERN_ELEMENTS, color_to_rgb,
)

STRIDE = 12
MAX_LINETYPES = 32
PX_PER_MM_LINEWEIGHT = 96 / 25.4


FILL_STRIDE = 6          # x y r g b a per triangle vertex


def _prim_segments(prims, tol: float) -> tuple[np.ndarray, np.ndarray] | None:
    chunks = []
    for prim in prims:
        pts = prim.tessellate(tol) if isinstance(prim, ArcPrim) else np.array([prim.p, prim.q], dtype=np.float64)
        if len(pts) >= 2:
            chunks.append(np.hstack((pts[:-1], pts[1:])))
    if not chunks:
        return None
    segs = np.vstack(chunks)
    lengths = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    dist0 = np.concatenate(([0.0], np.cumsum(lengths)[:-1]))
    return segs, dist0


def _has_curves(e: Entity | None) -> bool:
    if e is None:
        return True
    return e.TYPE in ("circle", "arc", "polyline", "ellipse", "spline", "insert", "dimension", "hatch")


@dataclass(slots=True)
class StyleOptions:
    dark_background: bool = True
    show_lineweights: bool = False


EMPTY_SEGS = np.zeros((0, STRIDE), dtype=np.float32)
EMPTY_TRIS = np.zeros((0, FILL_STRIDE), dtype=np.float32)


class SceneBuilder:
    """Caches one float32 block of segments and one of fill triangles per entity.

    Changing one entity re-tessellates only that entity. Layer/linetype/header/block
    changes, a new chord tolerance or new style options restyle everything.
    """

    def __init__(self, doc: Document) -> None:
        self.doc = doc
        self.tol = 0.05                         # chord tolerance (mm)
        self.origin: tuple[float, float] | None = None
        self._blocks: dict[int, tuple[np.ndarray | None, np.ndarray | None]] = {}
        self._opts: StyleOptions | None = None
        self.dirty = True
        self.linetype_index: dict[str, int] = {}
        self.points: list[tuple[float, float]] = []
        self.linetype_table()
        doc.add_listener(self._on_change)

    def detach(self) -> None:
        self.doc.remove_listener(self._on_change)

    def invalidate_all(self) -> None:
        self._blocks.clear()
        self.dirty = True

    def _on_change(self, doc: Document, cs: ChangeSet) -> None:
        if cs.reset:
            self.origin = None
            self.linetype_table()
            self.invalidate_all()
            return
        if cs.layers or cs.linetypes or cs.header or "block" in cs.tables or "dimstyle" in cs.tables:
            self.linetype_table()
            self.invalidate_all()
            return
        for h in cs.removed | cs.modified:
            self._blocks.pop(h, None)
        self.dirty = True

    def set_tolerance(self, tol: float) -> bool:
        """Set the chord tolerance. Returns True if curves need re-tessellation."""
        tol = max(tol, 1e-9)
        if abs(math.log(tol / self.tol)) < 1e-9:
            return False
        self.tol = tol
        for h in [h for h in self._blocks if _has_curves(self.doc.entities.get(h))]:
            del self._blocks[h]
        self.dirty = True
        return True

    def set_origin(self, origin: tuple[float, float]) -> None:
        if origin != self.origin:
            self.origin = origin
            self.invalidate_all()

    def linetype_table(self) -> tuple[list[float], list[float], list[int]]:
        """Flat pattern table for the shader: (patterns[32*8], lengths[32], counts[32])."""
        pats = [0.0] * (MAX_LINETYPES * MAX_PATTERN_ELEMENTS)
        lens = [0.0] * MAX_LINETYPES
        counts = [0] * MAX_LINETYPES
        self.linetype_index = {}
        i = 1                                   # 0 = continuous
        for lt in self.doc.linetypes.values():
            if lt.is_continuous or i >= MAX_LINETYPES:
                self.linetype_index[lt.name] = 0
                continue
            pat = list(lt.pattern[:MAX_PATTERN_ELEMENTS])
            for j, v in enumerate(pat):
                pats[i * MAX_PATTERN_ELEMENTS + j] = v
            lens[i] = sum(abs(v) for v in pat)
            counts[i] = len(pat)
            self.linetype_index[lt.name] = i
            i += 1
        return pats, lens, counts

    def _style(self, color, lw: float, lt_name: str, opts: StyleOptions) -> tuple[float, ...]:
        r, g, b = color_to_rgb(color, opts.dark_background)
        if lw == LW_DEFAULT or lw < 0:
            lw = DEFAULT_LINEWEIGHT_MM
        width = max(1.0, round(lw * PX_PER_MM_LINEWEIGHT)) if opts.show_lineweights else 1.0
        lt = self.doc.linetypes.get(lt_name)
        lti = self.linetype_index.get(lt.name, 0) if lt else 0
        return r / 255, g / 255, b / 255, width, float(lti)

    def entity_style(self, e: Entity, opts: StyleOptions) -> tuple[float, ...]:
        doc = self.doc
        st = self._style(doc.effective_color(e), doc.effective_lineweight(e), doc.effective_linetype(e).name, opts)
        return (*st, e.ltscale)

    def _make_block(self, e: Entity, opts: StyleOptions) -> tuple[np.ndarray | None, np.ndarray | None]:
        geo = self.doc.geometry(e)
        ox, oy = self.origin or (0.0, 0.0)
        base_style = self.entity_style(e, opts)
        force_continuous = e.TYPE in ("hatch", "dimension", "leader")
        seg_blocks, tri_blocks = [], []
        for part in geo.parts:
            if part.color is None:
                r, g, b, w, lt, lts = base_style
            else:
                r, g, b, w, lt = self._style(part.color, part.lineweight if part.lineweight is not None else -3.0,
                                             part.linetype or "Continuous", opts)
                lts = e.ltscale
            if force_continuous:
                lt = 0.0
            if part.prims:
                res = _prim_segments(part.prims, self.tol)
                if res is not None:
                    segs, dist0 = res
                    out = np.empty((len(segs), STRIDE), dtype=np.float32)
                    out[:, 0] = segs[:, 0] - ox
                    out[:, 1] = segs[:, 1] - oy
                    out[:, 2] = segs[:, 2] - ox
                    out[:, 3] = segs[:, 3] - oy
                    out[:, 4] = dist0
                    out[:, 5:9] = (r, g, b, 1.0)
                    out[:, 9] = w
                    out[:, 10] = lt
                    out[:, 11] = lts
                    seg_blocks.append(out)
            for loops in part.fills:
                tris = triangulate(loops)
                if len(tris) == 0:
                    continue
                v = tris.reshape(-1, 2)
                out = np.empty((len(v), FILL_STRIDE), dtype=np.float32)
                out[:, 0] = v[:, 0] - ox
                out[:, 1] = v[:, 1] - oy
                out[:, 2:6] = (r, g, b, 1.0)
                tri_blocks.append(out)
        segs = np.concatenate(seg_blocks) if seg_blocks else None
        tris = np.concatenate(tri_blocks) if tri_blocks else None
        return segs, tris

    def build(self, opts: StyleOptions, space: str = MODEL_SPACE) -> tuple[np.ndarray, np.ndarray]:
        """(segments, fill triangles) of every visible entity in a space, in draw order."""
        if self._opts != opts:
            self._opts = StyleOptions(opts.dark_background, opts.show_lineweights)
            self.invalidate_all()
        if self.origin is None:
            self.origin = (0.0, 0.0)
        doc = self.doc
        visible_layers = {n for n, layer in doc.layers.items() if layer.visible}
        segs, tris, points = [], [], []
        cache = self._blocks
        for h, e in doc.entities.items():
            if e.space != space or e.layer not in visible_layers:
                continue
            if isinstance(e, Point):
                points.append(e.position)
                continue
            blk = cache.get(h)
            if blk is None:
                blk = self._make_block(e, opts)
                cache[h] = blk
            if blk[0] is not None:
                segs.append(blk[0])
            if blk[1] is not None:
                tris.append(blk[1])
        self.points = points
        self.dirty = False
        return (np.concatenate(segs) if segs else EMPTY_SEGS, np.concatenate(tris) if tris else EMPTY_TRIS)

    def build_entities(self, entities: list[Entity], opts: StyleOptions) -> tuple[np.ndarray, np.ndarray]:
        """Arrays for temporary entities (previews) or a subset (highlight)."""
        segs, tris = [], []
        for e in entities:
            blk = self._blocks.get(e.handle) if e.handle and self.doc.entities.get(e.handle) is e else None
            if blk is None:
                blk = self._make_block(e, opts)
            if blk[0] is not None:
                segs.append(blk[0])
            if blk[1] is not None:
                tris.append(blk[1])
        return (np.concatenate(segs) if segs else EMPTY_SEGS, np.concatenate(tris) if tris else EMPTY_TRIS)


def solid_color_instances(inst: np.ndarray, rgba: tuple[float, float, float, float],
                          extra_width: float = 0.0) -> np.ndarray:
    out = inst.copy()
    out[:, 5:9] = rgba
    out[:, 9] += extra_width
    return out


def solid_color_tris(tris: np.ndarray, rgba: tuple[float, float, float, float]) -> np.ndarray:
    out = tris.copy()
    out[:, 2:6] = rgba
    return out


def rect_tris(x0: float, y0: float, x1: float, y1: float, rgba, origin=(0.0, 0.0)) -> np.ndarray:
    ox, oy = origin
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
    return np.array([(x - ox, y - oy, *rgba) for x, y in pts], dtype=np.float32)


def grid_instances(rect: tuple[float, float, float, float], spacing: float, pixel: float,
                   origin: tuple[float, float], dark: bool) -> np.ndarray:
    """Grid lines covering rect; minor lines vanish when too dense, every 5th is major."""
    if spacing <= 0:
        return np.zeros((0, STRIDE), dtype=np.float32)
    step = spacing
    while step / pixel < 14:
        step *= 5
        if step > 1e12:
            return np.zeros((0, STRIDE), dtype=np.float32)
    major = step * 5
    x0, y0, x1, y1 = rect
    xs = np.arange(math.floor(x0 / step), math.ceil(x1 / step) + 1) * step
    ys = np.arange(math.floor(y0 / step), math.ceil(y1 / step) + 1) * step
    if len(xs) + len(ys) > 4000:
        return np.zeros((0, STRIDE), dtype=np.float32)
    ox, oy = origin
    rows = []
    base = (0.165, 0.195, 0.23) if dark else (0.93, 0.94, 0.95)
    maj = (0.215, 0.25, 0.295) if dark else (0.86, 0.875, 0.895)
    xa = (0.55, 0.25, 0.25) if dark else (0.85, 0.55, 0.55)
    ya = (0.25, 0.50, 0.28) if dark else (0.55, 0.78, 0.58)
    for x in xs:
        c = ya if abs(x) < step * 1e-6 else (maj if abs(round(x / major) * major - x) < step * 1e-6 else base)
        rows.append((x - ox, y0 - oy, x - ox, y1 - oy, 0, *c, 1.0, 1.0, 0.0, 1.0))
    for y in ys:
        c = xa if abs(y) < step * 1e-6 else (maj if abs(round(y / major) * major - y) < step * 1e-6 else base)
        rows.append((x0 - ox, y - oy, x1 - ox, y - oy, 0, *c, 1.0, 1.0, 0.0, 1.0))
    return np.asarray(rows, dtype=np.float32)
