"""Named points of entities: grips, associative references and click-to-edit dimensions.

Part names:
  line:      p1, p2, mid              circle:   center, q0..q3 (0/90/180/270°)
  arc:       start, end, mid, center  polyline: v<i> (vertex), m<i> (segment middle)
  ellipse:   center, q0..q3           spline:   f<i> (fit point)
  point:     pt                        text/mtext/attdef/insert: ins
  dimension: p1, p2, p3, loc          leader:   l<i>
  viewport:  c0..c3 (corners)         hatch:    center
"""
from __future__ import annotations

import math
from dataclasses import replace

from .geom2d import arc_from_3_points
from .geom2d.transform import Affine2
from .geom2d.vec import Vec, dist
from .model import (
    Arc, AttributeDefinition, BlockReference, Circle, Dimension, Ellipse, Entity, Hatch, Leader, Line, MText, Point,
    Polyline, Spline, Text, Viewport,
)


def named_points(e: Entity) -> list[tuple[str, Vec]]:
    if isinstance(e, Line):
        return [("p1", e.p1), ("p2", e.p2), ("mid", ((e.p1[0] + e.p2[0]) / 2, (e.p1[1] + e.p2[1]) / 2))]
    if isinstance(e, Circle):
        return [("center", e.center)] + [(f"q{k}", (e.center[0] + e.radius * math.cos(k * math.pi / 2),
                                                    e.center[1] + e.radius * math.sin(k * math.pi / 2)))
                                         for k in range(4)]
    if isinstance(e, Arc):
        s, t = e.endpoints()
        return [("start", s), ("end", t), ("mid", e.midpoints()[0]), ("center", e.center)]
    if isinstance(e, Polyline):
        out = [(f"v{i}", (v[0], v[1])) for i, v in enumerate(e.vertices)]
        out += [(f"m{i}", p.mid) for i, p in enumerate(e.primitives())]
        return out
    if isinstance(e, Ellipse):
        return [("center", e.center)] + [(f"q{k}", e.point_at(k * math.pi / 2)) for k in range(4)]
    if isinstance(e, Spline):
        return [(f"f{i}", p) for i, p in enumerate(e.fit_points)]
    if isinstance(e, Point):
        return [("pt", e.position)]
    if isinstance(e, (Text, MText, AttributeDefinition, BlockReference)):
        return [("ins", e.insert)]
    if isinstance(e, Dimension):
        pts = [("p1", e.p1)]
        if e.dimtype != "ordinate":
            pts.append(("p2", e.p2))
        if e.dimtype == "angular":
            pts.append(("p3", e.p3))
        pts.append(("loc", e.location))
        return pts
    if isinstance(e, Leader):
        return [(f"l{i}", p) for i, p in enumerate(e.points)]
    if isinstance(e, Viewport):
        return [(f"c{i}", p) for i, p in enumerate(e.corners())]
    if isinstance(e, Hatch):
        b = e.bbox()
        return [("center", ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))] if b else []
    return []


def point_of(e: Entity, part: str) -> Vec | None:
    for name, p in named_points(e):
        if name == part:
            return p
    return None


def find_point_ref(doc, pt: Vec, tol: float, space: str | None = None) -> tuple[int, str] | None:
    """Which entity point is exactly at pt (used to make dimensions associative)."""
    best, best_d = None, tol
    r = (pt[0] - tol, pt[1] - tol, pt[0] + tol, pt[1] + tol)
    for h in doc_index_query(doc, r):
        e = doc.entities.get(h)
        if e is None or (space and e.space != space) or isinstance(e, (Dimension, Hatch, Leader)):
            continue
        for name, p in named_points(e):
            if name.startswith("m") and isinstance(e, Polyline):
                continue                     # segment middles move when vertices move: don't anchor to them
            d = dist(p, pt)
            if d <= best_d:
                best, best_d = (e.handle, name), d
    return best


def doc_index_query(doc, rect):
    idx = getattr(doc, "_spatial_index", None)
    if idx is not None:
        return idx.query(rect)
    return [h for h, e in doc.entities.items()
            if (b := doc.geometry(e).bbox) and not (b[2] < rect[0] or b[0] > rect[2] or b[3] < rect[1] or b[1] > rect[3])]


def move_point(e: Entity, part: str, new: Vec) -> Entity:
    """The entity after dragging its named point `part` to `new` (grip editing)."""
    old = point_of(e, part)
    if old is None:
        return e
    d = (new[0] - old[0], new[1] - old[1])
    move = lambda: e.transformed(Affine2.translate(*d))  # noqa: E731
    if isinstance(e, Line):
        if part == "p1":
            return replace(e, p1=new)
        if part == "p2":
            return replace(e, p2=new)
        return move()
    if isinstance(e, Circle):
        if part == "center":
            return move()
        r = dist(e.center, new)
        return replace(e, radius=r) if r > 0 else e
    if isinstance(e, Arc):
        if part == "center":
            return move()
        s, t = e.endpoints()
        m = e.midpoints()[0]
        a, b, c = (new, m, t) if part == "start" else (s, new, t) if part == "mid" else (s, m, new)
        prim = arc_from_3_points(a, b, c)
        return Arc.from_primitive(prim, handle=e.handle, layer=e.layer, color=e.color, linetype=e.linetype,
                                  lineweight=e.lineweight, ltscale=e.ltscale, space=e.space) if prim else e
    if isinstance(e, Polyline):
        vs = list(e.vertices)
        i = int(part[1:])
        if part.startswith("v"):
            vs[i] = (new[0], new[1], vs[i][2])
        else:
            j = (i + 1) % len(vs)
            for k in (i, j):
                vs[k] = (vs[k][0] + d[0], vs[k][1] + d[1], vs[k][2])
        return replace(e, vertices=tuple(vs))
    if isinstance(e, Ellipse):
        if part == "center":
            return move()
        k = int(part[1:])
        r = dist(e.center, new)
        if r <= 0:
            return e
        ml = e.major_length
        if k in (0, 2):
            f = r / ml
            ratio = e.ratio / f
            if ratio > 1:
                return e
            return replace(e, major=(e.major[0] * f, e.major[1] * f), ratio=ratio)
        return replace(e, ratio=min(1.0, r / ml))
    if isinstance(e, Spline):
        pts = list(e.fit_points)
        pts[int(part[1:])] = new
        return Spline.through(pts, closed=e.closed, handle=e.handle, layer=e.layer, color=e.color,
                              linetype=e.linetype, lineweight=e.lineweight, ltscale=e.ltscale, space=e.space)
    if isinstance(e, Dimension):
        field_ = {"p1": "p1", "p2": "p2", "p3": "p3", "loc": "location"}[part]
        refs = tuple((h, p) if i != {"p1": 0, "p2": 1, "p3": 2}.get(part, -1) else (0, "")
                     for i, (h, p) in enumerate(e.refs))
        return replace(e, **{field_: new}, refs=refs)
    if isinstance(e, Leader):
        pts = list(e.points)
        pts[int(part[1:])] = new
        return replace(e, points=tuple(pts))
    if isinstance(e, Viewport):
        i = int(part[1:])
        opp = e.corners()[(i + 2) % 4]
        w, h = abs(new[0] - opp[0]), abs(new[1] - opp[1])
        if w <= 0 or h <= 0:
            return e
        return replace(e, center=((new[0] + opp[0]) / 2, (new[1] + opp[1]) / 2), width=w, height=h)
    return move()
