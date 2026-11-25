"""Low-level curve primitives: straight segments and circular arcs.

Every entity decomposes into these, so snapping, intersection, selection and
tessellation are written once.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .vec import EPS, Vec, dist, polar

BBox = tuple[float, float, float, float]   # xmin, ymin, xmax, ymax

MIN_ARC_SEGMENTS = 4
MAX_ARC_SEGMENTS = 2048


@dataclass(frozen=True, slots=True)
class Seg:
    p: Vec
    q: Vec

    @property
    def length(self) -> float:
        return dist(self.p, self.q)

    @property
    def start(self) -> Vec:
        return self.p

    @property
    def end(self) -> Vec:
        return self.q

    @property
    def mid(self) -> Vec:
        return ((self.p[0] + self.q[0]) * 0.5, (self.p[1] + self.q[1]) * 0.5)

    def point_at(self, t: float) -> Vec:
        return (self.p[0] + (self.q[0] - self.p[0]) * t, self.p[1] + (self.q[1] - self.p[1]) * t)

    def param_of(self, pt: Vec) -> float:
        dx, dy = self.q[0] - self.p[0], self.q[1] - self.p[1]
        dd = dx * dx + dy * dy
        if dd < EPS * EPS:
            return 0.0
        return ((pt[0] - self.p[0]) * dx + (pt[1] - self.p[1]) * dy) / dd

    def nearest(self, pt: Vec) -> Vec:
        t = min(1.0, max(0.0, self.param_of(pt)))
        return self.point_at(t)

    def distance_to(self, pt: Vec) -> float:
        return dist(pt, self.nearest(pt))

    def bbox(self) -> BBox:
        return (min(self.p[0], self.q[0]), min(self.p[1], self.q[1]),
                max(self.p[0], self.q[0]), max(self.p[1], self.q[1]))

    def tessellate(self, tol: float) -> np.ndarray:
        return np.array([self.p, self.q], dtype=np.float64)

    def start_tangent(self) -> Vec:
        return (self.q[0] - self.p[0], self.q[1] - self.p[1])

    def end_tangent(self) -> Vec:
        return self.start_tangent()


def arc_segment_count(radius: float, sweep: float, tol: float) -> int:
    """Segments needed so the chord error stays below tol."""
    sweep = abs(sweep)
    if radius <= EPS or sweep <= EPS:
        return 1
    if tol <= 0 or tol >= radius:
        n = MIN_ARC_SEGMENTS * sweep / math.tau
    else:
        step = 2.0 * math.acos(1.0 - tol / radius)
        n = sweep / step if step > 1e-12 else MAX_ARC_SEGMENTS
    full_min = max(1, math.ceil(MIN_ARC_SEGMENTS * sweep / math.tau))
    return int(min(MAX_ARC_SEGMENTS, max(full_min, math.ceil(n))))


@dataclass(frozen=True, slots=True)
class Arc:
    """Circular arc from angle a0 sweeping by `sweep` radians (positive = CCW).

    A full circle has sweep = 2*pi.
    """
    c: Vec
    r: float
    a0: float
    sweep: float

    @property
    def is_full(self) -> bool:
        return abs(abs(self.sweep) - math.tau) < 1e-12

    @property
    def a1(self) -> float:
        return self.a0 + self.sweep

    @property
    def start(self) -> Vec:
        return polar(self.c, self.a0, self.r)

    @property
    def end(self) -> Vec:
        return polar(self.c, self.a1, self.r)

    @property
    def mid(self) -> Vec:
        return polar(self.c, self.a0 + self.sweep * 0.5, self.r)

    @property
    def length(self) -> float:
        return abs(self.sweep) * self.r

    def point_at(self, t: float) -> Vec:
        return polar(self.c, self.a0 + self.sweep * t, self.r)

    def param_of_angle(self, a: float) -> float | None:
        """Parameter t in [0,1] of the point at absolute angle a, or None if outside."""
        if self.is_full:
            return ((a - self.a0) % math.tau) / math.tau if self.sweep > 0 else ((self.a0 - a) % math.tau) / math.tau
        if self.sweep >= 0:
            d = (a - self.a0) % math.tau
            t = d / self.sweep if self.sweep > EPS else 0.0
        else:
            d = (self.a0 - a) % math.tau
            t = d / -self.sweep
        if t <= 1.0 + 1e-9:
            return min(t, 1.0)
        # tolerance near the start (d close to tau)
        if math.tau - d < 1e-9:
            return 0.0
        return None

    def contains_angle(self, a: float) -> bool:
        return self.param_of_angle(a) is not None

    def nearest(self, pt: Vec) -> Vec:
        dx, dy = pt[0] - self.c[0], pt[1] - self.c[1]
        if abs(dx) < EPS and abs(dy) < EPS:
            return self.start
        a = math.atan2(dy, dx)
        if self.contains_angle(a):
            return polar(self.c, a, self.r)
        s, e = self.start, self.end
        return s if dist(s, pt) <= dist(e, pt) else e

    def distance_to(self, pt: Vec) -> float:
        return dist(pt, self.nearest(pt))

    def quadrant_points(self) -> list[Vec]:
        return [polar(self.c, k * math.pi / 2, self.r) for k in range(4)
                if self.contains_angle(k * math.pi / 2)]

    def bbox(self) -> BBox:
        pts = [self.start, self.end] + self.quadrant_points()
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def tessellate(self, tol: float) -> np.ndarray:
        n = arc_segment_count(self.r, self.sweep, tol)
        ang = self.a0 + self.sweep * np.linspace(0.0, 1.0, n + 1)
        return np.column_stack((self.c[0] + self.r * np.cos(ang), self.c[1] + self.r * np.sin(ang)))

    def tangent_at(self, t: float) -> Vec:
        a = self.a0 + self.sweep * t
        s = 1.0 if self.sweep >= 0 else -1.0
        return (-math.sin(a) * s, math.cos(a) * s)

    def start_tangent(self) -> Vec:
        return self.tangent_at(0.0)

    def end_tangent(self) -> Vec:
        return self.tangent_at(1.0)


Primitive = Seg | Arc


def bbox_union(boxes: list[BBox]) -> BBox | None:
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def bbox_contains(outer: BBox, inner: BBox) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def bbox_overlaps(a: BBox, b: BBox) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])
