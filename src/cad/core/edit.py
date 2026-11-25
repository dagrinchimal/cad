"""Geometric editing operations used by the modify commands.

A `Curve` wraps a line, arc, circle, polyline, ellipse or spline and gives it a
length parameter s (0..length) so that trimming, breaking and extending work the
same way for every type.
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from .geom2d import Arc as ArcPrim
from .geom2d import Primitive, Seg, Vec
from .geom2d.construct import intersect, intersect_extended, line_line, perpendicular_foot
from .geom2d.vec import add, angle_of, cross, dist, dot, mul, normalize, perp, sub
from .model import Arc, Circle, Dimension, Ellipse, Entity, Hatch, Leader, Line, MText, Point, Polyline, Spline, Text
from .model.entities import BlockReference
from .model.geometry import explode_block_reference

EPS = 1e-9


class EditError(Exception):
    """A user-facing reason why an edit can't be done."""


# ================================================================== curves
class Curve:
    TYPES = (Line, Arc, Circle, Polyline, Ellipse, Spline)

    def __init__(self, e: Entity) -> None:
        if not isinstance(e, self.TYPES):
            raise EditError(f"{type(e).__name__} objects can't be cut or extended")
        self.e = e
        self.closed = isinstance(e, Circle) or (isinstance(e, Polyline) and e.closed) or \
            (isinstance(e, Ellipse) and e.is_full) or (isinstance(e, Spline) and e.closed)
        self.ellipse_params: np.ndarray | None = None
        if isinstance(e, Circle):
            self.prims: list[Primitive] = [ArcPrim(e.center, e.radius, 0.0, math.tau)]
        elif isinstance(e, Ellipse):
            n = 360
            self.ellipse_params = e.start_param + np.linspace(0, e.sweep, n + 1)
            pts = e.points(n)
            self.prims = [Seg(tuple(pts[i]), tuple(pts[i + 1])) for i in range(n)]
        elif isinstance(e, Spline):
            pts = e.curve_points(48)
            self.prims = [Seg(tuple(pts[i]), tuple(pts[i + 1])) for i in range(len(pts) - 1)]
        else:
            self.prims = e.primitives()
        self.starts = [0.0]
        for p in self.prims:
            self.starts.append(self.starts[-1] + p.length)
        self.length = self.starts[-1]

    # ---------------------------------------------------------------- parameters
    def _local(self, prim: Primitive, pt: Vec) -> float:
        if isinstance(prim, Seg):
            return min(1.0, max(0.0, prim.param_of(pt))) * prim.length
        t = prim.param_of_angle(math.atan2(pt[1] - prim.c[1], pt[0] - prim.c[0]))
        if t is None:
            t = 0.0 if dist(prim.start, pt) <= dist(prim.end, pt) else 1.0
        return t * prim.length

    def param_of(self, pt: Vec) -> float:
        best, best_d = 0.0, math.inf
        for i, prim in enumerate(self.prims):
            q = prim.nearest(pt)
            d = dist(q, pt)
            if d < best_d:
                best_d, best = d, self.starts[i] + self._local(prim, q)
        return best

    def point_at(self, s: float) -> Vec:
        if self.closed:
            s %= self.length
        s = min(max(s, 0.0), self.length)
        for i, prim in enumerate(self.prims):
            if s <= self.starts[i + 1] + 1e-12 or i == len(self.prims) - 1:
                L = prim.length or 1.0
                return prim.point_at((s - self.starts[i]) / L)
        return self.prims[-1].end

    def intersections(self, cutters: list[Primitive]) -> list[float]:
        out = []
        for i, prim in enumerate(self.prims):
            pb = prim.bbox()
            for c in cutters:
                cb = c.bbox()
                if cb[2] < pb[0] - EPS or cb[0] > pb[2] + EPS or cb[3] < pb[1] - EPS or cb[1] > pb[3] + EPS:
                    continue
                for pt in intersect(prim, c):
                    out.append(self.starts[i] + self._local(prim, pt))
        out = sorted(set(round(s, 9) for s in out))
        return out

    # ---------------------------------------------------------------- pieces
    def piece(self, s0: float, s1: float) -> Entity | None:
        """The part of the curve from s0 to s1 (s1 may exceed length on closed curves)."""
        if s1 - s0 <= 1e-9 * max(1.0, self.length):
            return None
        e = self.e
        if isinstance(e, Line):
            return replace(e, handle=0, p1=self.point_at(s0), p2=self.point_at(s1))
        if isinstance(e, (Arc, Circle)):
            r = e.radius
            a0 = (e.start_angle if isinstance(e, Arc) else 0.0) + s0 / r
            a1 = (e.start_angle if isinstance(e, Arc) else 0.0) + s1 / r
            if abs((a1 - a0) - math.tau) < 1e-12:
                return Circle(center=e.center, radius=r, **_props(e))
            return Arc(center=e.center, radius=r, start_angle=a0 % math.tau, end_angle=a1 % math.tau, **_props(e))
        if isinstance(e, Ellipse):
            n = len(self.prims)
            to_t = lambda s: e.start_param + (s / self.length) * e.sweep  # noqa: E731
            if self.closed:
                return replace(e, handle=0, start_param=to_t(s0) % math.tau, end_param=to_t(s0) % math.tau + (to_t(s1) - to_t(s0)))
            _ = n
            return replace(e, handle=0, start_param=to_t(s0), end_param=to_t(s1))
        if isinstance(e, Spline):
            pts = [self.point_at(s) for s in np.linspace(s0, s1, 16)]
            return Spline.through(pts, **_props(e))
        # polyline
        verts: list[list[float]] = []
        L = self.length
        prims = self.prims
        for k in range(2 if self.closed else 1):
            for i, prim in enumerate(prims):
                a, b = self.starts[i] + k * L, self.starts[i + 1] + k * L
                lo, hi = max(a, s0), min(b, s1)
                if hi - lo <= 1e-12:
                    continue
                pl = prim.length or 1.0
                t0, t1 = (lo - a) / pl, (hi - a) / pl
                p0, p1 = prim.point_at(t0), prim.point_at(t1)
                bulge = math.tan(prim.sweep * (t1 - t0) / 4) if isinstance(prim, ArcPrim) else 0.0
                if verts and math.dist(verts[-1][:2], p0) < 1e-9:
                    verts[-1][2] = bulge
                else:
                    verts.append([p0[0], p0[1], bulge])
                verts.append([p1[0], p1[1], 0.0])
        if len(verts) < 2:
            return None
        return Polyline(vertices=tuple(tuple(v) for v in verts), closed=False, **_props(e))


def _props(e: Entity) -> dict:
    return {"layer": e.layer, "color": e.color, "linetype": e.linetype, "lineweight": e.lineweight,
            "ltscale": e.ltscale, "space": e.space}


# ================================================================== trim / break / extend
def trim(e: Entity, cutters: list[Primitive], pick: Vec) -> list[Entity] | None:
    """Remove the part of e between the cutting edges around `pick`.
    Returns replacement entities ([] = delete), or None if nothing crosses it."""
    c = Curve(e)
    cuts = c.intersections(cutters)
    if not cuts:
        return None
    sp = c.param_of(pick)
    L = c.length
    if c.closed:
        if len(cuts) < 2:
            return None
        before = [x for x in cuts if x < sp]
        after = [x for x in cuts if x > sp]
        a = before[-1] if before else cuts[-1] - L
        b = after[0] if after else cuts[0] + L
        piece = c.piece(b, a + L)
        return [piece] if piece else []
    before = [x for x in cuts if x < sp - 1e-9]
    after = [x for x in cuts if x > sp + 1e-9]
    a = before[-1] if before else 0.0
    b = after[0] if after else L
    if a <= 1e-9 and b >= L - 1e-9:
        return None
    return [p for p in (c.piece(0.0, a), c.piece(b, L)) if p is not None]


def break_between(e: Entity, p1: Vec, p2: Vec) -> list[Entity]:
    c = Curve(e)
    s1, s2 = c.param_of(p1), c.param_of(p2)
    if c.closed:
        if abs(s1 - s2) < 1e-9:
            raise EditError("Pick two different points to break a closed shape")
        # AutoCAD: remove counter-clockwise from the first point to the second
        piece = c.piece(s2, s1 + c.length) if s2 > s1 else c.piece(s2, s1)
        return [piece] if piece else []
    a, b = sorted((s1, s2))
    return [p for p in (c.piece(0, a), c.piece(b, c.length)) if p is not None]


def break_at(e: Entity, pt: Vec) -> list[Entity]:
    c = Curve(e)
    if c.closed:
        raise EditError("A closed shape can't be split at a single point")
    s = c.param_of(pt)
    return [p for p in (c.piece(0, s), c.piece(s, c.length)) if p is not None]


def extend(e: Entity, boundaries: list[Primitive], pick: Vec) -> Entity | None:
    """Lengthen the end of e nearest `pick` to the next boundary. None if nothing is in the way."""
    if isinstance(e, Line):
        at_end = dist(pick, e.p2) <= dist(pick, e.p1)
        a, b = (e.p1, e.p2) if at_end else (e.p2, e.p1)
        d = sub(b, a)
        best = None
        for c in boundaries:
            for pt in intersect_extended(Seg(a, b), c):
                t = dot(sub(pt, a), d) / dot(d, d)
                if t > 1 + 1e-9 and c.distance_to(pt) < 1e-7 * max(1.0, abs(t) * math.hypot(*d)):
                    if best is None or t < best[0]:
                        best = (t, pt)
        if best is None:
            return None
        return replace(e, p2=best[1]) if at_end else replace(e, p1=best[1])
    if isinstance(e, Arc):
        prim = e.primitives()[0]
        at_end = dist(pick, prim.end) <= dist(pick, prim.start)
        circle = ArcPrim(e.center, e.radius, 0.0, math.tau)
        best = None
        for c in boundaries:
            for pt in intersect_extended(circle, c) if isinstance(c, Seg) else intersect(circle, c):
                if c.distance_to(pt) > 1e-7 * max(1.0, e.radius):
                    continue
                ang = angle_of(sub(pt, e.center))
                if at_end:
                    delta = (ang - e.end_angle) % math.tau
                else:
                    delta = (e.start_angle - ang) % math.tau
                if 1e-9 < delta < math.tau - e.sweep - 1e-9 and (best is None or delta < best):
                    best = delta
        if best is None:
            return None
        if at_end:
            return replace(e, end_angle=(e.end_angle + best) % math.tau)
        return replace(e, start_angle=(e.start_angle - best) % math.tau)
    if isinstance(e, Polyline) and not e.closed and len(e.vertices) >= 2:
        vs = list(e.vertices)
        at_end = dist(pick, vs[-1][:2]) <= dist(pick, vs[0][:2])
        if at_end:
            seg = Line(p1=vs[-2][:2], p2=vs[-1][:2]) if abs(vs[-2][2]) < 1e-12 else None
        else:
            seg = Line(p1=vs[1][:2], p2=vs[0][:2]) if abs(vs[0][2]) < 1e-12 else None
        if seg is None:
            raise EditError("Extending a polyline that ends in an arc isn't supported yet")
        ext = extend(seg, boundaries, seg.p2)
        if ext is None:
            return None
        if at_end:
            vs[-1] = (ext.p2[0], ext.p2[1], vs[-1][2])
        else:
            vs[0] = (ext.p2[0], ext.p2[1], vs[0][2])
        return replace(e, vertices=tuple(vs))
    raise EditError(f"{type(e).__name__} objects can't be extended")


# ================================================================== offset
def offset(e: Entity, distance: float, side: Vec) -> Entity | None:
    """Parallel copy at `distance` on the side of point `side`."""
    if isinstance(e, Line):
        d = normalize(sub(e.p2, e.p1))
        n = perp(d)
        s = 1.0 if dot(sub(side, e.p1), n) >= 0 else -1.0
        o = mul(n, s * distance)
        return replace(e, handle=0, p1=add(e.p1, o), p2=add(e.p2, o))
    if isinstance(e, (Circle, Arc)):
        outward = dist(side, e.center) > e.radius
        r = e.radius + distance if outward else e.radius - distance
        if r <= 1e-12:
            raise EditError("The offset distance is bigger than the radius")
        return replace(e, handle=0, radius=r)
    if isinstance(e, Polyline):
        return _offset_polyline(e, distance, side)
    if isinstance(e, Ellipse):
        pts = e.points(180)
        return _offset_points(e, pts, distance, side, e.is_full)
    if isinstance(e, Spline):
        return _offset_points(e, e.curve_points(32), distance, side, e.closed)
    raise EditError(f"{type(e).__name__} objects can't be offset")


def _offset_points(e, pts: np.ndarray, distance: float, side: Vec, closed: bool) -> Entity:
    tang = np.gradient(pts, axis=0)
    norm = np.column_stack((-tang[:, 1], tang[:, 0]))
    norm /= np.linalg.norm(norm, axis=1, keepdims=True) + 1e-300
    i = int(np.argmin(np.linalg.norm(pts - np.array(side), axis=1)))
    s = 1.0 if np.dot(np.array(side) - pts[i], norm[i]) >= 0 else -1.0
    q = pts + norm * distance * s
    if isinstance(e, Spline):
        fit = [tuple(p) for p in q[::4]] + ([] if len(q) % 4 == 1 else [tuple(q[-1])])
        return Spline.through(fit[:-1] if closed else fit, closed=closed, **_props(e))
    return Polyline(vertices=tuple((float(x), float(y), 0.0) for x, y in (q[:-1] if closed else q)), closed=closed,
                    **_props(e))


def _offset_polyline(e: Polyline, distance: float, side: Vec) -> Polyline:
    prims = e.primitives()
    if not prims:
        raise EditError("Empty polyline")
    # which side: compare with the nearest segment's left normal
    nearest = min(prims, key=lambda p: p.distance_to(side))
    q = nearest.nearest(side)
    if isinstance(nearest, Seg):
        left = perp(normalize(sub(nearest.q, nearest.p)))
    else:
        t = nearest.param_of_angle(angle_of(sub(q, nearest.c))) or 0.0
        left = perp(nearest.tangent_at(t))
    s = 1.0 if dot(sub(side, q), left) >= 0 else -1.0
    off = []
    for p in prims:
        if isinstance(p, Seg):
            n = mul(perp(normalize(sub(p.q, p.p))), s * distance)
            off.append(Seg(add(p.p, n), add(p.q, n)))
        else:
            # left of a CCW arc is towards the center
            toward_center = (p.sweep > 0) == (s > 0)
            r = p.r - distance if toward_center else p.r + distance
            if r <= 1e-12:
                raise EditError("The offset distance is too big for an arc in this polyline")
            off.append(ArcPrim(p.c, r, p.a0, p.sweep))
    pts = [off[0].start]
    bulges = []
    count = len(off)
    for i in range(count):
        cur = off[i]
        bulges.append(math.tan(cur.sweep / 4) if isinstance(cur, ArcPrim) else 0.0)
        nxt = off[(i + 1) % count] if (e.closed or i < count - 1) else None
        if nxt is None:
            pts.append(cur.end)
            break
        j = _join_point(cur, nxt)
        pts.append(j)
    if e.closed:
        pts[0] = pts[-1]
        pts = pts[:-1]
    verts = []
    for i, p in enumerate(pts):
        verts.append((p[0], p[1], bulges[i] if i < len(bulges) else 0.0))
    return Polyline(vertices=tuple(verts), closed=e.closed, **_props(e))


def _join_point(a: Primitive, b: Primitive) -> Vec:
    """Where two consecutive offset pieces meet (extended corner)."""
    if isinstance(a, Seg) and isinstance(b, Seg):
        res = line_line(a.p, sub(a.q, a.p), b.p, sub(b.q, b.p))
        return res[0] if res else a.q
    return a.end if dist(a.end, b.start) < 1e-9 else ((a.end[0] + b.start[0]) / 2, (a.end[1] + b.start[1]) / 2)


# ================================================================== fillet / chamfer
def _line_side_keep(line: Line, at: Vec, pick: Vec) -> Line:
    """Line from `at` to the original endpoint on the picked side of `at`."""
    d = sub(line.p2, line.p1)
    tp = dot(sub(pick, line.p1), d)
    ta = dot(sub(at, line.p1), d)
    far = line.p2 if tp >= ta else line.p1
    return replace(line, p1=at, p2=far) if far is line.p2 else replace(line, p1=far, p2=at)


def fillet_lines(l1: Line, pick1: Vec, l2: Line, pick2: Vec, radius: float) -> tuple[Line, Line, Arc | None]:
    res = line_line(l1.p1, sub(l1.p2, l1.p1), l2.p1, sub(l2.p2, l2.p1))
    if res is None:
        raise EditError("The lines are parallel")
    X = res[0]
    if radius <= 1e-12:
        return _line_side_keep(l1, X, pick1), _line_side_keep(l2, X, pick2), None
    f1 = perpendicular_foot(Seg(l1.p1, l1.p2), pick1, on_segment_only=False)[0]
    f2 = perpendicular_foot(Seg(l2.p1, l2.p2), pick2, on_segment_only=False)[0]
    u1, u2 = normalize(sub(f1, X)), normalize(sub(f2, X))
    if u1 == (0.0, 0.0) or u2 == (0.0, 0.0):
        raise EditError("Pick the lines away from where they meet")
    cos_a = max(-1.0, min(1.0, dot(u1, u2)))
    half = math.acos(cos_a) / 2
    if half < 1e-9 or abs(half - math.pi / 2) < 1e-9:
        raise EditError("The lines are parallel")
    d = radius / math.tan(half)
    T1, T2 = add(X, mul(u1, d)), add(X, mul(u2, d))
    bis = normalize(add(u1, u2))
    C = add(X, mul(bis, radius / math.sin(half)))
    a0 = angle_of(sub(T1, C))
    a1 = angle_of(sub(T2, C))
    sweep = (a1 - a0) % math.tau
    if sweep > math.pi:
        a0, a1 = a1, a0
    arc = Arc(center=C, radius=radius, start_angle=a0, end_angle=a1, **_props(l1))
    return _line_side_keep(l1, T1, pick1), _line_side_keep(l2, T2, pick2), arc


def chamfer_lines(l1: Line, pick1: Vec, l2: Line, pick2: Vec, d1: float, d2: float) -> tuple[Line, Line, Line | None]:
    res = line_line(l1.p1, sub(l1.p2, l1.p1), l2.p1, sub(l2.p2, l2.p1))
    if res is None:
        raise EditError("The lines are parallel")
    X = res[0]
    if d1 <= 1e-12 and d2 <= 1e-12:
        return _line_side_keep(l1, X, pick1), _line_side_keep(l2, X, pick2), None
    f1 = perpendicular_foot(Seg(l1.p1, l1.p2), pick1, on_segment_only=False)[0]
    f2 = perpendicular_foot(Seg(l2.p1, l2.p2), pick2, on_segment_only=False)[0]
    u1, u2 = normalize(sub(f1, X)), normalize(sub(f2, X))
    P1, P2 = add(X, mul(u1, d1)), add(X, mul(u2, d2))
    return _line_side_keep(l1, P1, pick1), _line_side_keep(l2, P2, pick2), Line(p1=P1, p2=P2, **_props(l1))


def fillet_curves(e1: Entity, pick1: Vec, e2: Entity, pick2: Vec, radius: float) -> tuple[Entity, Entity, Arc]:
    """Fillet between a line and an arc/circle, or two arcs/circles (circles are left whole)."""
    if radius <= 0:
        raise EditError("Use a radius greater than zero for arcs and circles")

    def offsets(e, toward):
        if isinstance(e, Line):
            d = normalize(sub(e.p2, e.p1))
            n = perp(d)
            s = 1.0 if dot(sub(toward, e.p1), n) >= 0 else -1.0       # the side facing the other object
            return [Seg(add(e.p1, mul(n, s * radius)), add(e.p2, mul(n, s * radius)))], s
        rs = [e.radius + radius] + ([e.radius - radius] if e.radius > radius else [])
        return [ArcPrim(e.center, r, 0.0, math.tau) for r in rs], 0

    def anchor(e, pick):
        return e.center if isinstance(e, (Arc, Circle)) else pick
    o1, _ = offsets(e1, anchor(e2, pick2))
    o2, _ = offsets(e2, anchor(e1, pick1))
    cands = []
    for a in o1:
        for b in o2:
            cands.extend(intersect_extended(a, b))
    if not cands:
        raise EditError("Those objects are too far apart for this radius")
    C = min(cands, key=lambda c: dist(c, pick1) + dist(c, pick2))

    def tangent(e):
        if isinstance(e, Line):
            return perpendicular_foot(Seg(e.p1, e.p2), C, on_segment_only=False)[0]
        return add(e.center, mul(normalize(sub(C, e.center)), e.radius))
    T1, T2 = tangent(e1), tangent(e2)
    a0, a1 = angle_of(sub(T1, C)), angle_of(sub(T2, C))
    if (a1 - a0) % math.tau > math.pi:
        a0, a1 = a1, a0
    arc = Arc(center=C, radius=radius, start_angle=a0, end_angle=a1, **_props(e1))

    def trimmed(e, T, pick):
        if isinstance(e, Line):
            return _line_side_keep(e, T, pick)
        if isinstance(e, Arc):
            ta = angle_of(sub(T, e.center))
            pa = angle_of(sub(pick, e.center))
            # keep the part between T and the end on the picked side
            if (pa - ta) % math.tau <= (e.end_angle - ta) % math.tau:
                return replace(e, start_angle=ta)
            return replace(e, end_angle=ta)
        return e
    return trimmed(e1, T1, pick1), trimmed(e2, T2, pick2), arc


def fillet_polyline(pl: Polyline, radius: float, only_vertex: int | None = None) -> Polyline:
    """Round every corner between two straight segments (or just one vertex)."""
    vs = list(pl.vertices)
    n = len(vs)
    if n < 3:
        return pl
    out: list[tuple[float, float, float]] = []
    idxs = range(n) if pl.closed else range(n)
    for i in idxs:
        prev_i, next_i = (i - 1) % n, (i + 1) % n
        is_corner = (pl.closed or 0 < i < n - 1) and abs(vs[prev_i][2]) < 1e-12 and abs(vs[i][2]) < 1e-12
        if only_vertex is not None and i != only_vertex:
            is_corner = False
        if not is_corner or radius <= 0:
            out.append(vs[i])
            continue
        P, V, N = vs[prev_i][:2], vs[i][:2], vs[next_i][:2]
        u1, u2 = normalize(sub(P, V)), normalize(sub(N, V))
        half = math.acos(max(-1.0, min(1.0, dot(u1, u2)))) / 2
        if half < 1e-6 or abs(half - math.pi / 2) < 1e-6:
            out.append(vs[i])
            continue
        d = radius / math.tan(half)
        if d > dist(P, V) * 0.999 or d > dist(N, V) * 0.999:
            out.append(vs[i])          # too short for this radius: leave the corner
            continue
        T1, T2 = add(V, mul(u1, d)), add(V, mul(u2, d))
        turn = cross(sub(V, P), sub(N, V))
        sweep = (math.pi - 2 * half) * (1 if turn > 0 else -1)
        out.append((T1[0], T1[1], math.tan(sweep / 4)))
        out.append((T2[0], T2[1], 0.0))
    return replace(pl, vertices=tuple(out))


# ================================================================== join
def join(entities: list[Entity], tol: float = 1e-6) -> list[Entity]:
    """Join lines/arcs/open polylines that touch end to end. Collinear lines become one line;
    arcs on the same circle become one arc; mixed chains become polylines."""
    items = [e for e in entities if isinstance(e, (Line, Arc, Polyline)) and not (isinstance(e, Polyline) and e.closed)]
    if len(items) < 2:
        return entities

    def ends(e):
        if isinstance(e, Line):
            return e.p1, e.p2
        if isinstance(e, Arc):
            p = e.primitives()[0]
            return p.start, p.end
        return e.vertices[0][:2], e.vertices[-1][:2]

    def as_verts(e, reverse=False):
        if isinstance(e, Line):
            v = [(e.p1[0], e.p1[1], 0.0), (e.p2[0], e.p2[1], 0.0)]
        elif isinstance(e, Arc):
            p = e.primitives()[0]
            v = [(p.start[0], p.start[1], math.tan(p.sweep / 4)), (p.end[0], p.end[1], 0.0)]
        else:
            v = list(e.vertices)
        if reverse:
            pts = [x[:2] for x in v][::-1]
            bul = [-x[2] for x in v][:-1][::-1] + [0.0]
            v = [(p[0], p[1], b) for p, b in zip(pts, bul)]
        return v

    # collinear lines first
    lines = [e for e in items if isinstance(e, Line)]
    others = [e for e in items if not isinstance(e, Line)]
    merged = True
    while merged:
        merged = False
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                a, b = lines[i], lines[j]
                da = sub(a.p2, a.p1)
                if abs(cross(da, sub(b.p1, a.p1))) > tol * math.hypot(*da) or \
                        abs(cross(da, sub(b.p2, a.p1))) > tol * math.hypot(*da):
                    continue
                dd = dot(da, da)
                ts = sorted([0.0, 1.0, dot(sub(b.p1, a.p1), da) / dd, dot(sub(b.p2, a.p1), da) / dd])
                tb = sorted([dot(sub(b.p1, a.p1), da) / dd, dot(sub(b.p2, a.p1), da) / dd])
                if tb[0] > 1 + tol or tb[1] < -tol:
                    continue           # collinear but apart
                p1 = (a.p1[0] + da[0] * ts[0], a.p1[1] + da[1] * ts[0])
                p2 = (a.p1[0] + da[0] * ts[-1], a.p1[1] + da[1] * ts[-1])
                lines[i] = replace(a, p1=p1, p2=p2)
                del lines[j]
                merged = True
                break
            if merged:
                break
    # arcs on the same circle that touch
    arcs = [e for e in others if isinstance(e, Arc)]
    rest = [e for e in others if not isinstance(e, Arc)]
    merged = True
    while merged:
        merged = False
        for i in range(len(arcs)):
            for j in range(len(arcs)):
                if i == j:
                    continue
                a, b = arcs[i], arcs[j]
                if dist(a.center, b.center) > tol or abs(a.radius - b.radius) > tol:
                    continue
                if abs(math.remainder(a.end_angle - b.start_angle, math.tau)) * a.radius <= tol:
                    sweep = a.sweep + b.sweep
                    new = Circle(center=a.center, radius=a.radius, **_props(a)) if sweep >= math.tau - 1e-9 \
                        else replace(a, end_angle=b.end_angle)
                    arcs = [x for k, x in enumerate(arcs) if k not in (i, j)]
                    if isinstance(new, Arc):
                        arcs.append(new)
                    else:
                        rest.append(new)
                    merged = True
                    break
            if merged:
                break
    pool = lines + arcs + [e for e in rest if not isinstance(e, Circle)]
    circles = [e for e in rest if isinstance(e, Circle)]
    # chain the rest into polylines
    result: list[Entity] = []
    used = [False] * len(pool)
    for i, start in enumerate(pool):
        if used[i]:
            continue
        used[i] = True
        chain = as_verts(start)
        grown = True
        while grown:
            grown = False
            for j, e in enumerate(pool):
                if used[j]:
                    continue
                a, b = ends(e)
                head, tail = chain[0][:2], chain[-1][:2]
                if dist(tail, a) <= tol:
                    chain = chain[:-1] + as_verts(e)
                elif dist(tail, b) <= tol:
                    chain = chain[:-1] + as_verts(e, reverse=True)
                elif dist(head, b) <= tol:
                    chain = as_verts(e)[:-1] + chain
                elif dist(head, a) <= tol:
                    chain = as_verts(e, reverse=True)[:-1] + chain
                else:
                    continue
                used[j] = True
                grown = True
        n_parts = sum(1 for _ in [0])
        _ = n_parts
        if len(chain) == 2 and isinstance(start, (Line, Arc)) and chain == as_verts(start):
            result.append(start)
            continue
        closed = len(chain) > 2 and dist(chain[0][:2], chain[-1][:2]) <= tol
        if closed:
            chain = chain[:-1]
        result.append(Polyline(vertices=tuple(chain), closed=closed, **_props(start)))
    others_untouched = [e for e in entities if e not in items]
    return result + circles + others_untouched


# ================================================================== explode
def explode(doc, e: Entity) -> list[Entity] | None:
    """Simpler objects that make up e, or None if it can't be exploded."""
    from .geom2d.fill import loop_area
    props = _props(e)
    if isinstance(e, Polyline):
        out = []
        for p in e.primitives():
            if isinstance(p, Seg):
                out.append(Line(p1=p.p, p2=p.q, **props))
            else:
                out.append(Arc.from_primitive(p, **props))
        return out
    if isinstance(e, BlockReference):
        return explode_block_reference(doc, e)
    if isinstance(e, MText):
        g = doc.geometry(e)
        out = []
        for part in g.parts:
            for run in part.texts:
                lay = __import__("cad.core.text", fromlist=["text_engine"]).text_engine().layout(run)
                lh = run.height * 1.667 * run.line_spacing
                for i, line in enumerate(lay.lines):
                    ins = (lay.box[3][0] + math.sin(run.rotation) * lh * i - math.sin(run.rotation) * run.height,
                           lay.box[3][1] - math.cos(run.rotation) * (run.height + lh * i))
                    out.append(Text(insert=ins, text=line, height=run.height, rotation=run.rotation, font=run.font,
                                    **props))
        return out
    if isinstance(e, (Dimension, Leader, Hatch)):
        g = doc.geometry(e)
        out: list[Entity] = []
        for part in g.parts:
            for p in part.prims:
                out.append(Line(p1=p.p, p2=p.q, **props) if isinstance(p, Seg) else Arc.from_primitive(p, **props))
            for loops in part.fills:
                if part.texts:
                    continue
                verts = tuple(tuple((float(x), float(y), 0.0) for x, y in lp) for lp in loops
                              if abs(loop_area(lp)) > 0)
                if verts:
                    out.append(Hatch(loops=verts, pattern="SOLID", **props))
            for run in part.texts:
                out.append(Text(insert=run.insert, text=run.text, height=run.height, rotation=run.rotation,
                                halign=run.halign, valign=run.valign if not run.multiline else "middle",
                                font=run.font, **props))
        return out
    return None


_ = (Point, ArcPrim)
