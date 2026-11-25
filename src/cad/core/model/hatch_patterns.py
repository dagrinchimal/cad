"""Hatch patterns (AutoCAD acadiso.pat-compatible definitions, millimetres) and pattern line generation."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..geom2d import Seg


@dataclass(frozen=True, slots=True)
class PatternLine:
    angle: float                 # degrees
    origin: tuple[float, float]
    shift: float                 # offset along the line from one row to the next
    spacing: float               # distance between rows
    dashes: tuple[float, ...] = ()   # >0 dash, <0 gap, 0 dot; empty = continuous


def _p(*rows) -> tuple[PatternLine, ...]:
    out = []
    for r in rows:
        a, ox, oy, dx, dy, *d = r
        out.append(PatternLine(a, (ox, oy), dx, dy, tuple(d)))
    return tuple(out)


PATTERNS: dict[str, tuple[PatternLine, ...]] = {
    "ANSI31": _p((45, 0, 0, 0, 3.175)),
    "ANSI32": _p((45, 0, 0, 0, 9.525), (45, 4.49013, 0, 0, 9.525)),
    "ANSI33": _p((45, 0, 0, 0, 6.35), (45, 4.49013, 0, 0, 6.35, 3.175, -1.5875)),
    "ANSI34": _p((45, 0, 0, 0, 19.05), (45, 4.49013, 0, 0, 19.05), (45, 8.98026, 0, 0, 19.05),
                 (45, 13.4704, 0, 0, 19.05)),
    "ANSI37": _p((45, 0, 0, 0, 3.175), (135, 0, 0, 0, 3.175)),
    "ANSI38": _p((45, 0, 0, 0, 3.175), (135, 0, 0, 6.35, 3.175, 7.9375, -4.7625)),
    "LINE": _p((0, 0, 0, 0, 3.175)),
    "NET": _p((0, 0, 0, 0, 3.175), (90, 0, 0, 0, 3.175)),
    "NET3": _p((0, 0, 0, 0, 3.175), (60, 0, 0, 0, 3.175), (120, 0, 0, 0, 3.175)),
    "DOTS": _p((0, 0, 0, 0.79375, 1.5875, 0, -1.5875)),
    "BRICK": _p((0, 0, 0, 0, 6.35), (90, 0, 0, 0, 12.7, 6.35, -6.35), (90, 6.35, 0, 0, 12.7, -6.35, 6.35)),
    "SQUARE": _p((0, 0, 0, 0, 3.175, 3.175, -3.175), (90, 0, 0, 0, 3.175, 3.175, -3.175)),
    "DASH": _p((0, 0, 0, 3.175, 3.175, 3.175, -3.175)),
    "CROSS": _p((0, 0, 0, 6.35, 6.35, 3.175, -9.525), (90, 1.5875, -1.5875, 6.35, 6.35, 3.175, -9.525)),
}

DESCRIPTIONS = {
    "SOLID": "Solid fill", "ANSI31": "Diagonal lines (general / iron)", "ANSI32": "Steel", "ANSI33": "Bronze, brass",
    "ANSI34": "Plastic, rubber", "ANSI37": "Diagonal cross-hatch (lead, zinc)", "ANSI38": "Aluminum",
    "LINE": "Horizontal lines", "NET": "Square grid", "NET3": "Triangle grid", "DOTS": "Dots",
    "BRICK": "Brick", "SQUARE": "Dashed squares", "DASH": "Dashed lines", "CROSS": "Crosses",
}

PATTERN_NAMES = ("SOLID",) + tuple(PATTERNS)

MAX_SEGMENTS = 250_000


class PatternTooDense(Exception):
    pass


def _edges(loops: list[np.ndarray]) -> np.ndarray:
    parts = []
    for lp in loops:
        if len(lp) >= 2:
            parts.append(np.hstack((lp, np.roll(lp, -1, axis=0))))
    return np.vstack(parts) if parts else np.zeros((0, 4))


def pattern_segments(loops: list[np.ndarray], name: str, scale: float = 1.0, angle: float = 0.0,
                     limit: int = MAX_SEGMENTS) -> list[Seg]:
    """Pattern lines clipped to the even-odd interior of the loops."""
    fams = PATTERNS.get(name.upper())
    if not fams or not loops:
        return []
    edges = _edges(loops)
    if len(edges) == 0:
        return []
    allpts = np.vstack(loops)
    out: list[Seg] = []
    ca, sa = math.cos(angle), math.sin(angle)
    for fam in fams:
        A = math.radians(fam.angle) + angle
        u = np.array([math.cos(A), math.sin(A)])
        n = np.array([-u[1], u[0]])
        ox, oy = fam.origin[0] * scale, fam.origin[1] * scale
        O = np.array([ox * ca - oy * sa, ox * sa + oy * ca])
        step = fam.spacing * scale
        shift = fam.shift * scale
        if step <= 0:
            continue
        proj = (allpts - O) @ n
        k0, k1 = math.ceil(proj.min() / step), math.floor(proj.max() / step)
        if (k1 - k0 + 1) > limit:
            raise PatternTooDense(name)
        dashes = [d * scale for d in fam.dashes]
        period = sum(abs(d) for d in dashes)
        # edge endpoints relative to each row computed with one linear solve per edge
        p, q = edges[:, 0:2], edges[:, 2:4]
        e = q - p
        for k in range(k0, k1 + 1):
            P = O + k * step * n + k * shift * u
            # half-open crossing rule: robust when a row passes exactly through a corner
            da = (p - P) @ n
            db = (q - P) @ n
            ok = (da > 0) != (db > 0)
            if not ok.any():
                continue
            t = da[ok] / (da[ok] - db[ok])
            hits = p[ok] + e[ok] * t[:, None]
            s = np.sort((hits - P) @ u)
            for i in range(0, len(s) - 1, 2):
                a, b = s[i], s[i + 1]
                if b - a <= 1e-12:
                    continue
                if not dashes or period <= 0:
                    out.append(Seg(tuple(P + u * a), tuple(P + u * b)))
                else:
                    # walk the dash pattern from the row origin
                    j0 = math.floor(a / period)
                    pos = j0 * period
                    while pos < b:
                        for d in dashes:
                            seg_len = abs(d)
                            s0, s1 = pos, pos + seg_len
                            if d >= 0 and s1 >= a and s0 <= b:
                                c0, c1 = max(s0, a), min(s1, b)
                                out.append(Seg(tuple(P + u * c0), tuple(P + u * c1)))
                            pos = s1
                            if pos >= b:
                                break
                    if len(out) > limit:
                        raise PatternTooDense(name)
            if len(out) > limit:
                raise PatternTooDense(name)
    return out
