"""2D vector helpers on plain (x, y) tuples (fast and immutable)."""
from __future__ import annotations

import math

Vec = tuple[float, float]

EPS = 1e-9


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1])


def mul(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Vec, b: Vec) -> float:
    return a[0] * b[1] - a[1] * b[0]


def length(a: Vec) -> float:
    return math.hypot(a[0], a[1])


def dist(a: Vec, b: Vec) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def normalize(a: Vec) -> Vec:
    n = math.hypot(a[0], a[1])
    if n < EPS:
        return (0.0, 0.0)
    return (a[0] / n, a[1] / n)


def perp(a: Vec) -> Vec:
    """Rotate 90 degrees counter-clockwise."""
    return (-a[1], a[0])


def lerp(a: Vec, b: Vec, t: float) -> Vec:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def midpoint(a: Vec, b: Vec) -> Vec:
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)


def angle_of(v: Vec) -> float:
    """Angle of a vector in radians, 0..2pi."""
    return math.atan2(v[1], v[0]) % math.tau


def angle_between_points(a: Vec, b: Vec) -> float:
    return angle_of(sub(b, a))


def polar(p: Vec, angle: float, distance: float) -> Vec:
    return (p[0] + math.cos(angle) * distance, p[1] + math.sin(angle) * distance)


def rotate(p: Vec, center: Vec, angle: float) -> Vec:
    c, s = math.cos(angle), math.sin(angle)
    x, y = p[0] - center[0], p[1] - center[1]
    return (center[0] + x * c - y * s, center[1] + x * s + y * c)


def close(a: Vec, b: Vec, tol: float = 1e-7) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def project_on_line(p: Vec, a: Vec, d: Vec) -> tuple[Vec, float]:
    """Project p onto the infinite line a + t*d (d need not be unit). Returns (point, t)."""
    dd = dot(d, d)
    if dd < EPS * EPS:
        return a, 0.0
    t = dot(sub(p, a), d) / dd
    return (a[0] + d[0] * t, a[1] + d[1] * t), t


def normalize_angle(a: float) -> float:
    return a % math.tau
