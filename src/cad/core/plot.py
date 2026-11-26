"""Plotting: turns a drawing into flat sheets of strokes and fills in paper millimeters.

Every "drawn on paper" output (PDF, printing, SVG, PNG/JPG/TIFF, HPGL) uses this, so they all
look the same. A Sheet has its origin at the bottom-left corner of the paper, y up.

    sheet = plot_layout(doc, "Layout1", PlotStyle())
    sheet = plot_model(doc, PlotArea(paper=(420, 297), scale=1/50))

Linetypes are turned into real dashes here, so a backend only needs solid lines and filled polygons.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .geom2d.primitives import Arc as ArcPrim
from .model import MODEL_SPACE, Document, Entity, Point, Viewport
from .text import text_engine
from .model.styles import DEFAULT_LINEWEIGHT_MM, LW_DEFAULT, color_to_rgb

BBox = tuple[float, float, float, float]
RGB = tuple[int, int, int]

PAPER_TOL_MM = 0.01          # curves are split into chords no further than this from the true curve


@dataclass(frozen=True, slots=True)
class PlotStyle:
    color_mode: str = "color"          # color | monochrome | grayscale
    plot_lineweights: bool = True      # False: every line at the default lineweight
    default_lineweight: float = DEFAULT_LINEWEIGHT_MM
    scale_lineweights: bool = False    # model plots: scale lineweights with the plot scale
    hide_viewport_frames: bool = False
    background: RGB = (255, 255, 255)  # the paper; only used by raster backends


@dataclass(slots=True)
class Stroke:
    pts: np.ndarray                    # (n, 2) paper mm
    color: RGB
    width: float                       # mm
    layer: str
    closed: bool = False


@dataclass(slots=True)
class Fill:
    loops: list[np.ndarray]            # filled together, even-odd
    color: RGB
    layer: str


@dataclass(slots=True)
class Sheet:
    name: str
    width: float                       # paper mm
    height: float
    items: list = field(default_factory=list)       # Stroke | Fill, in draw order

    @property
    def layers(self) -> list[str]:
        seen: dict[str, None] = {}
        for it in self.items:
            seen.setdefault(it.layer, None)
        return list(seen)

    def bbox(self) -> BBox | None:
        xs, ys = [], []
        for it in self.items:
            arrs = [it.pts] if isinstance(it, Stroke) else it.loops
            for a in arrs:
                if len(a):
                    xs += [a[:, 0].min(), a[:, 0].max()]
                    ys += [a[:, 1].min(), a[:, 1].max()]
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None


@dataclass(frozen=True, slots=True)
class PlotArea:
    """How a model-space plot is placed on paper."""
    paper: tuple[float, float] = (420.0, 297.0)      # mm (width, height) as the sheet lies
    window: BBox | None = None                       # model area to plot; None = drawing extents
    scale: float | None = None                       # paper mm per model mm (1:50 -> 0.02); None = fit
    margin: float = 5.0                              # mm kept clear on every side
    center: bool = True
    offset: tuple[float, float] = (0.0, 0.0)         # mm, when not centered (from the lower-left margin)
    name: str = "Model"


# ------------------------------------------------------------------ transforms
@dataclass(frozen=True, slots=True)
class _Map:
    """model -> paper: p' = (p - c) * s + o"""
    cx: float
    cy: float
    s: float
    ox: float
    oy: float

    def arr(self, a: np.ndarray) -> np.ndarray:
        out = np.empty_like(a, dtype=np.float64)
        out[:, 0] = (a[:, 0] - self.cx) * self.s + self.ox
        out[:, 1] = (a[:, 1] - self.cy) * self.s + self.oy
        return out


IDENTITY = _Map(0.0, 0.0, 1.0, 0.0, 0.0)


def model_area_map(doc: Document, area: PlotArea, extents: BBox | None) -> tuple[_Map, float, BBox]:
    """(transform, scale used, paper clip rect) for a model plot."""
    pw, ph = area.paper
    m = area.margin
    avail_w, avail_h = max(1e-6, pw - 2 * m), max(1e-6, ph - 2 * m)
    win = area.window or extents or (0.0, 0.0, avail_w, avail_h)
    ww, wh = max(win[2] - win[0], 1e-9), max(win[3] - win[1], 1e-9)
    s = area.scale if area.scale else min(avail_w / ww, avail_h / wh)
    cx, cy = (win[0] + win[2]) / 2, (win[1] + win[3]) / 2
    if area.center:
        ox, oy = pw / 2, ph / 2
    else:
        ox, oy = m + area.offset[0] + ww * s / 2, m + area.offset[1] + wh * s / 2
    clip = (m, m, pw - m, ph - m)
    if area.window is not None:      # plot only what's inside the chosen window
        x0, y0 = (win[0] - cx) * s + ox, (win[1] - cy) * s + oy
        x1, y1 = (win[2] - cx) * s + ox, (win[3] - cy) * s + oy
        clip = (max(clip[0], x0), max(clip[1], y0), min(clip[2], x1), min(clip[3], y1))
    return _Map(cx, cy, s, ox, oy), s, clip


# ------------------------------------------------------------------ clipping
def _clip_polyline(pts: np.ndarray, rect: BBox) -> list[np.ndarray]:
    """Pieces of a polyline inside rect (Liang-Barsky per segment, joined back into runs)."""
    x0, y0, x1, y1 = rect
    if len(pts) < 2:
        return []
    if (pts[:, 0].min() >= x0 and pts[:, 0].max() <= x1 and pts[:, 1].min() >= y0 and pts[:, 1].max() <= y1):
        return [pts]
    if pts[:, 0].max() < x0 or pts[:, 0].min() > x1 or pts[:, 1].max() < y0 or pts[:, 1].min() > y1:
        return []
    runs: list[list] = []
    cur: list = []
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        dx, dy = bx - ax, by - ay
        t0, t1 = 0.0, 1.0
        ok = True
        for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
            if abs(p) < 1e-15:
                if q < 0:
                    ok = False
                    break
                continue
            r = q / p
            if p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
            if t0 > t1:
                ok = False
                break
        if not ok:
            if cur:
                runs.append(cur)
                cur = []
            continue
        a = (ax + t0 * dx, ay + t0 * dy)
        b = (ax + t1 * dx, ay + t1 * dy)
        if cur and (abs(cur[-1][0] - a[0]) > 1e-9 or abs(cur[-1][1] - a[1]) > 1e-9):
            runs.append(cur)
            cur = []
        if not cur:
            cur.append(a)
        cur.append(b)
        if t1 < 1.0:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [np.array(r, dtype=np.float64) for r in runs if len(r) >= 2]


def _clip_loop(loop: np.ndarray, rect: BBox) -> np.ndarray:
    """Sutherland-Hodgman against an axis-aligned rectangle."""
    x0, y0, x1, y1 = rect
    poly = [tuple(p) for p in loop]
    for axis, bound, keep_greater in ((0, x0, True), (0, x1, False), (1, y0, True), (1, y1, False)):
        if not poly:
            break
        out = []
        n = len(poly)
        for i in range(n):
            cur, prev = poly[i], poly[i - 1]
            cin = cur[axis] >= bound if keep_greater else cur[axis] <= bound
            pin = prev[axis] >= bound if keep_greater else prev[axis] <= bound
            if cin != pin:
                t = (bound - prev[axis]) / (cur[axis] - prev[axis])
                out.append((prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1])))
            if cin:
                out.append(cur)
        poly = out
    return np.array(poly, dtype=np.float64).reshape(-1, 2)


# ------------------------------------------------------------------ dashes
def dash_polyline(pts: np.ndarray, pattern: list[float], phase: float = 0.0) -> list[np.ndarray]:
    """Split a polyline into dash pieces. pattern in paper mm: >0 dash, <0 gap, 0 dot."""
    total = sum(abs(v) for v in pattern)
    if total <= 1e-9 or len(pts) < 2:
        return [pts]
    seglen = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    length = float(seglen.sum())
    if length <= 1e-12:
        return []
    if length / total > 20000:            # absurdly fine pattern for this line: draw it solid
        return [pts]
    cum = np.concatenate(([0.0], np.cumsum(seglen)))

    def at(d: float):
        i = int(np.searchsorted(cum, d, side="right") - 1)
        i = min(max(i, 0), len(seglen) - 1)
        t = (d - cum[i]) / seglen[i] if seglen[i] > 0 else 0.0
        return pts[i] + t * (pts[i + 1] - pts[i]), i

    out = []
    d = -phase
    k = 0
    dot = max(total * 1e-3, 0.05)
    while d < length:
        v = pattern[k % len(pattern)]
        k += 1
        if v < 0:
            d += -v
            continue
        a, b = max(d, 0.0), min(d + (v if v > 0 else dot), length)
        if b > a:
            pa, ia = at(a)
            pb, ib = at(b)
            piece = [pa] + [pts[j] for j in range(ia + 1, ib + 1)] + [pb]
            out.append(np.array(piece, dtype=np.float64))
        d += v
    return out


# ------------------------------------------------------------------ the plotter
class _Plotter:
    def __init__(self, doc: Document, style: PlotStyle, sheet: Sheet) -> None:
        self.doc = doc
        self.style = style
        self.sheet = sheet

    def rgb(self, color) -> RGB:
        if self.style.color_mode == "monochrome":
            return (0, 0, 0)
        r, g, b = color_to_rgb(color, dark_background=False)
        if self.style.color_mode == "grayscale":
            y = int(round(0.299 * r + 0.587 * g + 0.114 * b))
            return (y, y, y)
        return (r, g, b)

    def width(self, lw: float, scale: float) -> float:
        st = self.style
        if not st.plot_lineweights or lw == LW_DEFAULT or lw < 0:
            w = st.default_lineweight
        else:
            w = lw
        if st.scale_lineweights:
            w *= scale
        return max(w, 0.0)

    def plottable(self, e: Entity) -> bool:
        lay = self.doc.layers.get(e.layer)
        return lay is None or (lay.visible and lay.plot)

    def entity(self, e: Entity, m: _Map, clip: BBox | None, lt_paper_scale: float) -> None:
        """Draw one entity through transform m. lt_paper_scale: paper mm per linetype-pattern mm."""
        doc = self.doc
        items = self.sheet.items
        if isinstance(e, Point):
            p = m.arr(np.array([e.position], dtype=np.float64))[0]
            if clip is None or (clip[0] <= p[0] <= clip[2] and clip[1] <= p[1] <= clip[3]):
                d = 0.1
                items.append(Stroke(np.array([[p[0] - d, p[1]], [p[0] + d, p[1]]]),
                                    self.rgb(doc.effective_color(e)), self.width(doc.effective_lineweight(e), m.s),
                                    e.layer))
            return
        geo = doc.geometry(e)
        tol = PAPER_TOL_MM / max(m.s, 1e-12)
        base_color = doc.effective_color(e)
        base_lw = doc.effective_lineweight(e)
        base_lt = doc.effective_linetype(e)
        force_continuous = e.TYPE in ("hatch", "dimension", "leader")
        for part in geo.parts:
            if part.color is None:
                color, lw, lt = base_color, base_lw, base_lt
            else:
                color = part.color
                lw = part.lineweight if part.lineweight is not None else LW_DEFAULT
                lt = doc.linetypes.get(part.linetype or "Continuous") or doc.linetypes["Continuous"]
            rgb = self.rgb(color)
            # fills (hatches, text glyphs, arrowheads). Text: real outlines when the engine has them.
            fill_loops = list(part.fills)
            outlines = getattr(text_engine(), "outlines", None)
            if part.texts and outlines is not None:
                for run in part.texts:
                    lps = outlines(run)
                    if lps:
                        fill_loops.append(lps)
            elif part.triangles:
                for tris in part.triangles:
                    fill_loops += [[t] for t in np.asarray(tris).reshape(-1, 3, 2)]
            for loops in fill_loops:
                ml = [m.arr(np.asarray(lp, dtype=np.float64)) for lp in loops if len(lp) >= 3]
                if clip is not None:
                    ml = [c for c in (_clip_loop(lp, clip) for lp in ml) if len(c) >= 3]
                if ml:
                    items.append(Fill(ml, rgb, e.layer))
            if not part.prims:
                continue
            w = self.width(lw, m.s)
            pattern = None
            if not force_continuous and not lt.is_continuous:
                k = doc.header.ltscale * e.ltscale * lt_paper_scale
                pattern = [v * k for v in lt.pattern]
            for poly, closed in _chains(part.prims, tol):
                pp = m.arr(poly)
                pieces = dash_polyline(pp, pattern) if pattern else [pp]
                for piece in pieces:
                    for c in (_clip_polyline(piece, clip) if clip is not None else [piece]):
                        is_closed = closed and pattern is None and c is piece
                        items.append(Stroke(c, rgb, w, e.layer, closed=is_closed))


def _chains(prims, tol: float) -> list[tuple[np.ndarray, bool]]:
    """Join consecutive primitives that meet end to start into polylines."""
    out: list[tuple[np.ndarray, bool]] = []
    cur: list[np.ndarray] = []
    last = None
    for prim in prims:
        pts = prim.tessellate(tol) if isinstance(prim, ArcPrim) else np.array([prim.p, prim.q], dtype=np.float64)
        if len(pts) < 2:
            continue
        if cur and last is not None and abs(pts[0][0] - last[0]) <= 1e-9 * max(1, abs(last[0])) \
                and abs(pts[0][1] - last[1]) <= 1e-9 * max(1, abs(last[1])):
            cur.append(pts[1:])
        else:
            if cur:
                out.append(np.vstack(cur))
            cur = [pts]
        last = pts[-1]
    if cur:
        out.append(np.vstack(cur))
    res = []
    for a in out:
        closed = len(a) > 2 and np.allclose(a[0], a[-1], atol=1e-9 * max(1.0, float(np.abs(a).max())))
        res.append((a, closed))
    return res


def model_extents(doc: Document, space: str = MODEL_SPACE) -> BBox | None:
    box = None
    for e in doc.entities.values():
        if e.space != space or not doc.is_visible(e):
            continue
        b = e.bbox() if isinstance(e, Point) else doc.geometry(e).bbox
        if b is None:
            continue
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    return box


def plot_model(doc: Document, area: PlotArea = PlotArea(), style: PlotStyle = PlotStyle()) -> Sheet:
    """Model space on one sheet: fitted or at a scale, centered or offset."""
    pw, ph = area.paper
    sheet = Sheet(area.name, pw, ph)
    m, s, clip = model_area_map(doc, area, model_extents(doc))
    p = _Plotter(doc, style, sheet)
    for e in doc.entities.values():
        if e.space == MODEL_SPACE and not isinstance(e, Viewport) and p.plottable(e):
            p.entity(e, m, clip, s)
    return sheet


def viewport_map(doc: Document, vp: Viewport, model_box: BBox | None) -> _Map:
    from .layouts import resolve_viewport
    (vcx, vcy), s = resolve_viewport(doc, vp, model_box)
    return _Map(vcx, vcy, s, vp.center[0], vp.center[1])


def plot_layout(doc: Document, layout: str, style: PlotStyle = PlotStyle()) -> Sheet:
    """A layout sheet at 1:1 with every viewport showing model space, clipped to its frame."""
    lo = doc.layouts.get(layout)
    if lo is None:
        raise KeyError(f"There is no layout called {layout!r}.")
    w, h = lo.size
    sheet = Sheet(layout, w, h)
    p = _Plotter(doc, style, sheet)
    model_box = model_extents(doc)
    model_ents = [e for e in doc.entities.values() if e.space == MODEL_SPACE and p.plottable(e)]
    for e in doc.entities.values():
        if e.space != layout:
            continue
        if isinstance(e, Viewport):
            lay = doc.layers.get(e.layer)
            if lay is not None and not lay.visible:
                continue                                    # viewport layer off/frozen: nothing shows
            vm = viewport_map(doc, e, model_box)
            for me in model_ents:
                p.entity(me, vm, e.rect(), 1.0)            # PSLTSCALE=1: dashes keep their paper size
            if p.plottable(e) and not style.hide_viewport_frames:
                p.entity(e, IDENTITY, None, 1.0)            # the frame obeys its layer's Plot setting
        elif p.plottable(e):
            p.entity(e, IDENTITY, None, 1.0)
    return sheet


def plot_spaces(doc: Document, spaces: list[str], area: PlotArea = PlotArea(), style: PlotStyle = PlotStyle()) -> list[Sheet]:
    """One sheet per requested space: "*Model" (model space) uses `area`, layouts use their own paper."""
    out = []
    for sp in spaces:
        out.append(plot_model(doc, area, style) if sp == MODEL_SPACE else plot_layout(doc, sp, style))
    return out


__all__ = ["PlotStyle", "PlotArea", "Sheet", "Stroke", "Fill", "plot_model", "plot_layout", "plot_spaces",
           "dash_polyline", "model_extents"]
