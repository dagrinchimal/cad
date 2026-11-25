"""Geometry of dimensions and leaders (lines, arrowheads, text), computed from their points."""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from ..geom2d import Arc as ArcPrim
from ..geom2d import Seg, Vec
from ..geom2d.vec import add, angle_of, dist, mul, normalize, perp, sub
from ..text import BOTTOM, CENTER, LEFT, MIDDLE, RIGHT, TextRun
from ..units import format_angle, format_length
from .entities import Dimension, Leader
from .geometry import Geometry, Part, text_part
from .tables import DimStyle


def _readable(angle: float) -> float:
    """Keep text upright: angles in (-90°, 90°]."""
    a = math.remainder(angle, math.tau)
    if a > math.pi / 2 + 1e-9 or a <= -math.pi / 2 + 1e-9:
        a += math.pi
    return math.remainder(a, math.tau)


def arrowhead(tip: Vec, direction: Vec, size: float, kind: str, part: Part) -> None:
    """Arrow at `tip`, pointing along `direction` (unit vector pointing INTO the tip)."""
    d = normalize(direction)
    if d == (0.0, 0.0) or size <= 0:
        return
    n = perp(d)
    if kind == "tick":
        a = add(tip, mul(add(d, n), size * 0.5))
        b = sub(tip, mul(add(d, n), size * 0.5))
        part.prims.append(Seg(a, b))
    elif kind == "dot":
        t = np.linspace(0, math.tau, 17)[:-1]
        r = size * 0.25
        part.fills.append([np.column_stack((tip[0] + r * np.cos(t), tip[1] + r * np.sin(t)))])
    elif kind == "open":
        back = sub(tip, mul(d, size))
        part.prims.append(Seg(tip, add(back, mul(n, size / 6))))
        part.prims.append(Seg(tip, sub(back, mul(n, size / 6))))
    else:   # closed filled
        back = sub(tip, mul(d, size))
        part.fills.append([np.array([tip, add(back, mul(n, size / 6)), sub(back, mul(n, size / 6))])])


def dim_text(doc, e: Dimension, style: DimStyle, value: float, prefix: str = "") -> str:
    units = doc.header.units
    if style.decimal_places >= 0:
        units = replace(units, decimal_places=style.decimal_places, angle_decimal_places=style.decimal_places)
    if e.dimtype == "angular":
        measured = format_angle(math.degrees(value), units)
    else:
        measured = prefix + format_length(value, units)
    if not e.text:
        return measured
    return e.text.replace("<>", measured)


def _add_text(g: Geometry, part: Part, run: TextRun) -> None:
    tp, box = text_part(run)
    part.fills.extend(tp.fills)
    part.texts.extend(tp.texts)
    g.pick_areas.append([box])


def dimension_geometry(doc, e: Dimension) -> Geometry:
    st = doc.dimstyle(e.style)
    g = Geometry(grips=e.grip_points())
    part = Part()
    g.parts.append(part)
    th, ar = st.size("text_height"), st.size("arrow_size")
    gap, eo, ee = st.size("text_gap"), st.size("ext_offset"), st.size("ext_extension")
    t = e.dimtype
    if t in ("linear", "aligned"):
        u = (math.cos(e.angle), math.sin(e.angle)) if t == "linear" else normalize(sub(e.p2, e.p1))
        if u == (0.0, 0.0):
            u = (1.0, 0.0)
        n = perp(u)
        h1 = (e.location[0] - e.p1[0]) * n[0] + (e.location[1] - e.p1[1]) * n[1]
        h2 = (e.location[0] - e.p2[0]) * n[0] + (e.location[1] - e.p2[1]) * n[1]
        a, b = add(e.p1, mul(n, h1)), add(e.p2, mul(n, h2))
        for p, h, d in ((e.p1, h1, a), (e.p2, h2, b)):
            s = 1.0 if h >= 0 else -1.0
            if abs(h) > eo:
                part.prims.append(Seg(add(p, mul(n, s * eo)), add(d, mul(n, s * ee))))
        length = dist(a, b)
        dirv = normalize(sub(b, a)) if length > 0 else u
        if length >= 2.5 * ar:
            part.prims.append(Seg(a, b))
            arrowhead(a, mul(dirv, -1), ar, st.arrow, part)
            arrowhead(b, dirv, ar, st.arrow, part)
        else:     # not enough room: arrows outside
            part.prims.append(Seg(sub(a, mul(dirv, 2 * ar)), add(b, mul(dirv, 2 * ar))))
            arrowhead(a, dirv, ar, st.arrow, part)
            arrowhead(b, mul(dirv, -1), ar, st.arrow, part)
        rot = _readable(angle_of(dirv))
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        up = (-math.sin(rot), math.cos(rot))
        txt = dim_text(doc, e, st, e.measurement())
        _add_text(g, part, TextRun(txt, add(mid, mul(up, gap)), th, rot, 1.0, CENTER, BOTTOM, st.font))
        g.endpoints += [a, b]
        g.nodes += [e.p1, e.p2]
    elif t == "angular":
        V = e.p1
        a1, a2 = angle_of(sub(e.p2, V)), angle_of(sub(e.p3, V))
        al = angle_of(sub(e.location, V))
        R = max(dist(V, e.location), 1e-9)
        sweep = (a2 - a1) % math.tau
        start = a1
        if (al - a1) % math.tau > sweep:          # location is on the other side: dimension the outside angle
            start, sweep = a2, math.tau - sweep
        arc = ArcPrim(V, R, start, sweep)
        part.prims.append(arc)
        for leg_pt, ang in ((e.p2, a1), (e.p3, a2)):
            L = dist(V, leg_pt)
            if R > L + eo:
                part.prims.append(Seg(add(V, mul((math.cos(ang), math.sin(ang)), L + eo)),
                                      add(V, mul((math.cos(ang), math.sin(ang)), R + ee))))
        arrowhead(arc.start, mul(arc.start_tangent(), -1), ar, st.arrow, part)
        arrowhead(arc.end, arc.end_tangent(), ar, st.arrow, part)
        mid_a = start + sweep / 2
        pos = add(V, mul((math.cos(mid_a), math.sin(mid_a)), R + gap))
        rot = _readable(mid_a - math.pi / 2)
        txt = dim_text(doc, e, st, sweep)
        _add_text(g, part, TextRun(txt, pos, th, rot, 1.0, CENTER, BOTTOM, st.font))
        g.nodes += [V]
    elif t in ("radius", "diameter"):
        C = e.p1
        r = dist(e.p1, e.p2)
        d = normalize(sub(e.location, C)) if dist(e.location, C) > 1e-12 else normalize(sub(e.p2, C))
        A = add(C, mul(d, r))
        L = e.location
        inside = dist(L, C) < r
        if t == "radius":
            if inside:
                part.prims.append(Seg(C, A))
                arrowhead(A, d, ar, st.arrow, part)
            else:
                part.prims.append(Seg(A, L))
                arrowhead(A, mul(d, -1), ar, st.arrow, part)
            txt = dim_text(doc, e, st, r, "R")
        else:
            B = sub(C, mul(d, r))
            far = L if not inside else A
            part.prims.append(Seg(B, far))
            arrowhead(A, d if inside else mul(d, -1), ar, st.arrow, part)
            arrowhead(B, mul(d, -1) if inside else d, ar, st.arrow, part)
            txt = dim_text(doc, e, st, 2 * r, "Ø")
        cm = st.size("center_mark")
        if cm > 0 and not inside:
            part.prims += [Seg((C[0] - cm, C[1]), (C[0] + cm, C[1])), Seg((C[0], C[1] - cm), (C[0], C[1] + cm))]
        right = L[0] >= C[0]
        tpos = add(L, ((gap if right else -gap), 0.0))
        _add_text(g, part, TextRun(txt, tpos, th, 0.0, 1.0, LEFT if right else RIGHT, MIDDLE, st.font))
        g.centers += [C]
        g.endpoints += [A]
    elif t == "ordinate":
        F, L = e.p1, e.location
        if e.axis == "x":
            s = 1.0 if L[1] >= F[1] else -1.0
            start = (F[0], F[1] + s * eo)
            mid_y = F[1] + (L[1] - F[1]) * 0.5
            pts = [start, (F[0], mid_y), (L[0], mid_y + s * min(abs(L[1] - F[1]) * 0.25, 2 * ar)), L]
            rot = math.pi / 2
            txt = dim_text(doc, e, st, L[0] - L[0] + (F[0] - e.origin[0]))
            align = LEFT if s > 0 else RIGHT
        else:
            s = 1.0 if L[0] >= F[0] else -1.0
            start = (F[0] + s * eo, F[1])
            mid_x = F[0] + (L[0] - F[0]) * 0.5
            pts = [start, (mid_x, F[1]), (mid_x + s * min(abs(L[0] - F[0]) * 0.25, 2 * ar), L[1]), L]
            rot = 0.0
            txt = dim_text(doc, e, st, F[1] - e.origin[1])
            align = LEFT if s > 0 else RIGHT
        for i in range(len(pts) - 1):
            if dist(pts[i], pts[i + 1]) > 1e-12:
                part.prims.append(Seg(pts[i], pts[i + 1]))
        tpos = add(L, mul((math.cos(rot), math.sin(rot)), s * gap))
        _add_text(g, part, TextRun(txt, tpos, th, rot, 1.0, align, MIDDLE, st.font))
        g.nodes += [F]
    return g


def leader_geometry(doc, e: Leader) -> Geometry:
    st = doc.dimstyle(e.style)
    g = Geometry(grips=list(e.points))
    part = Part()
    g.parts.append(part)
    pts = list(e.points)
    ar, th, gap = st.size("arrow_size"), st.size("text_height"), st.size("text_gap")
    for i in range(len(pts) - 1):
        if dist(pts[i], pts[i + 1]) > 1e-12:
            part.prims.append(Seg(pts[i], pts[i + 1]))
    if len(pts) >= 2:
        arrowhead(pts[0], sub(pts[0], pts[1]), ar, "closed" if st.arrow == "tick" else st.arrow, part)
        g.endpoints += [pts[0], pts[-1]]
    if e.text and pts:
        end = pts[-1]
        right = len(pts) < 2 or pts[-1][0] >= pts[-2][0]
        landing = add(end, ((ar if right else -ar), 0.0))
        part.prims.append(Seg(end, landing))
        run = TextRun(e.text, add(landing, ((gap if right else -gap), 0.0)), th, 0.0, 1.0,
                      LEFT if right else RIGHT, MIDDLE, st.font, multiline=True)
        _add_text(g, part, run)
    return g
