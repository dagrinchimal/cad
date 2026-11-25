"""Constructions: bulges, 3-point circles, tangents, intersections, clipping."""
from __future__ import annotations

import math

from .primitives import Arc, BBox, Primitive, Seg
from .vec import EPS, Vec, angle_of, cross, dist, dot, midpoint, normalize, perp, sub

# ----------------------------------------------------------------- bulges


def arc_from_bulge(p: Vec, q: Vec, bulge: float) -> Primitive:
    """Polyline segment p->q with DXF bulge (tan of a quarter of the included angle)."""
    c = dist(p, q)
    if abs(bulge) < 1e-12 or c < EPS:
        return Seg(p, q)
    theta = 4.0 * math.atan(bulge)
    u = normalize(sub(q, p))
    n = perp(u)
    m = midpoint(p, q)
    d = (c / 2.0) / math.tan(theta / 2.0)
    center = (m[0] + n[0] * d, m[1] + n[1] * d)
    r = c / (2.0 * abs(math.sin(theta / 2.0)))
    return Arc(center, r, angle_of(sub(p, center)), theta)


def bulge_for_tangent_arc(p: Vec, tangent: Vec, q: Vec) -> float:
    """Bulge of the arc starting at p with direction `tangent` and ending at q."""
    chord = sub(q, p)
    if math.hypot(*chord) < EPS or math.hypot(*tangent) < EPS:
        return 0.0
    ang = math.atan2(cross(tangent, chord), dot(tangent, chord))
    theta = 2.0 * ang
    if abs(abs(theta) - math.tau) < 1e-9:
        return 0.0
    return math.tan(theta / 4.0)


def bulge_from_arc(arc: Arc) -> float:
    return math.tan(arc.sweep / 4.0)


# ----------------------------------------------------------------- circles


def circle_from_3_points(a: Vec, b: Vec, c: Vec) -> tuple[Vec, float] | None:
    d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = a[0] ** 2 + a[1] ** 2, b[0] ** 2 + b[1] ** 2, c[0] ** 2 + c[1] ** 2
    ux = (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d
    uy = (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d
    center = (ux, uy)
    return center, dist(center, a)


def arc_from_3_points(a: Vec, b: Vec, c: Vec) -> Arc | None:
    """Arc starting at a, passing through b, ending at c."""
    res = circle_from_3_points(a, b, c)
    if res is None:
        return None
    center, r = res
    a0 = angle_of(sub(a, center))
    a1 = angle_of(sub(c, center))
    ccw = cross(sub(b, a), sub(c, b)) > 0   # turning left => CCW arc
    sweep = (a1 - a0) % math.tau if ccw else -((a0 - a1) % math.tau)
    return Arc(center, r, a0, sweep)


def arc_from_start_center_end(start: Vec, center: Vec, end: Vec) -> Arc | None:
    """CCW arc around center from start, ending on the ray towards `end` (AutoCAD rule)."""
    r = dist(start, center)
    if r < EPS:
        return None
    a0 = angle_of(sub(start, center))
    a1 = angle_of(sub(end, center))
    sweep = (a1 - a0) % math.tau
    if sweep < 1e-12:
        sweep = math.tau
    return Arc(center, r, a0, sweep)


def tangent_points(pt: Vec, center: Vec, r: float) -> list[Vec]:
    d = dist(pt, center)
    if d <= r + EPS:
        return []
    base = angle_of(sub(pt, center))
    alpha = math.acos(r / d)
    return [(center[0] + r * math.cos(base + s * alpha), center[1] + r * math.sin(base + s * alpha))
            for s in (1, -1)]


def perpendicular_foot(prim: Primitive, from_pt: Vec, on_segment_only: bool = True) -> list[Vec]:
    if isinstance(prim, Seg):
        t = prim.param_of(from_pt)
        if on_segment_only and not (-1e-9 <= t <= 1 + 1e-9):
            return []
        return [prim.point_at(t)]
    # arc / circle: the two points on the line through the center
    v = sub(from_pt, prim.c)
    if math.hypot(*v) < EPS:
        return []
    a = angle_of(v)
    out = []
    for ang in (a, a + math.pi):
        if prim.contains_angle(ang % math.tau):
            out.append((prim.c[0] + prim.r * math.cos(ang), prim.c[1] + prim.r * math.sin(ang)))
    return out


# ----------------------------------------------------------------- intersections


def line_line(a: Vec, da: Vec, b: Vec, db: Vec) -> tuple[Vec, float, float] | None:
    """Infinite lines a + s*da and b + t*db. Returns (point, s, t)."""
    den = cross(da, db)
    if abs(den) < 1e-12 * max(1.0, math.hypot(*da) * math.hypot(*db)):
        return None
    w = sub(b, a)
    s = cross(w, db) / den
    t = cross(w, da) / den
    return (a[0] + da[0] * s, a[1] + da[1] * s), s, t


def _line_circle(a: Vec, d: Vec, c: Vec, r: float) -> list[float]:
    fx, fy = a[0] - c[0], a[1] - c[1]
    A = d[0] * d[0] + d[1] * d[1]
    if A < EPS * EPS:
        return []
    B = 2 * (fx * d[0] + fy * d[1])
    C = fx * fx + fy * fy - r * r
    disc = B * B - 4 * A * C
    if disc < -1e-12 * max(1.0, B * B):
        return []
    if disc <= 1e-12 * max(1.0, B * B):
        return [-B / (2 * A)]
    sq = math.sqrt(disc)
    return [(-B - sq) / (2 * A), (-B + sq) / (2 * A)]


def _circle_circle(c1: Vec, r1: float, c2: Vec, r2: float) -> list[Vec]:
    d = dist(c1, c2)
    if d < EPS or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h2 = r1 * r1 - a * a
    h = math.sqrt(max(0.0, h2))
    ux, uy = (c2[0] - c1[0]) / d, (c2[1] - c1[1]) / d
    px, py = c1[0] + ux * a, c1[1] + uy * a
    if h < 1e-9:
        return [(px, py)]
    return [(px - uy * h, py + ux * h), (px + uy * h, py - ux * h)]


_T = 1e-9


def intersect(a: Primitive, b: Primitive) -> list[Vec]:
    """Intersection points of two bounded primitives."""
    if isinstance(a, Seg) and isinstance(b, Seg):
        res = line_line(a.p, sub(a.q, a.p), b.p, sub(b.q, b.p))
        if res and -_T <= res[1] <= 1 + _T and -_T <= res[2] <= 1 + _T:
            return [res[0]]
        return []
    if isinstance(a, Arc) and isinstance(b, Seg):
        a, b = b, a
    if isinstance(a, Seg) and isinstance(b, Arc):
        d = sub(a.q, a.p)
        out = []
        for t in _line_circle(a.p, d, b.c, b.r):
            if -_T <= t <= 1 + _T:
                pt = (a.p[0] + d[0] * t, a.p[1] + d[1] * t)
                if b.contains_angle(angle_of(sub(pt, b.c))):
                    out.append(pt)
        return out
    # arc / arc
    out = []
    for pt in _circle_circle(a.c, a.r, b.c, b.r):
        if a.contains_angle(angle_of(sub(pt, a.c))) and b.contains_angle(angle_of(sub(pt, b.c))):
            out.append(pt)
    return out


def intersect_extended(a: Primitive, b: Primitive) -> list[Vec]:
    """Intersections treating segments as infinite lines and arcs as full circles."""
    if isinstance(a, Seg) and isinstance(b, Seg):
        res = line_line(a.p, sub(a.q, a.p), b.p, sub(b.q, b.p))
        return [res[0]] if res else []
    if isinstance(a, Arc) and isinstance(b, Seg):
        a, b = b, a
    if isinstance(a, Seg):
        d = sub(a.q, a.p)
        return [(a.p[0] + d[0] * t, a.p[1] + d[1] * t) for t in _line_circle(a.p, d, b.c, b.r)]
    return _circle_circle(a.c, a.r, b.c, b.r)


# ----------------------------------------------------------------- clipping


def segment_hits_rect(p: Vec, q: Vec, rect: BBox) -> bool:
    """Liang-Barsky: does segment p-q touch the rectangle?"""
    x0, y0, x1, y1 = rect
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if abs(pk) < 1e-15:
            if qk < 0:
                return False
        else:
            t = qk / pk
            if pk < 0:
                if t > t1:
                    return False
                t0 = max(t0, t)
            else:
                if t < t0:
                    return False
                t1 = min(t1, t)
    return t0 <= t1
