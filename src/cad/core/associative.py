"""Associativity: dimensions, hatches and arrays follow the objects they belong to.

Runs as a pre-commit hook, so the follow-up changes land in the same undo step as the edit.
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from .geom2d.construct import line_line
from .geom2d.fill import loop_area, triangulate
from .geom2d.regions import find_boundary
from .geom2d.vec import angle_of, dist, sub
from .model import ArrayEntity, Circle, Arc, Dimension, Document, Ellipse, Hatch, Line, Polyline, Spline
from .points import point_of


def interior_point(loops) -> tuple[float, float] | None:
    """A point well inside the even-odd area (centroid of the biggest triangle)."""
    tris = triangulate([np.asarray(lp)[:, :2] if np.asarray(lp).shape[1] > 2 else np.asarray(lp) for lp in loops])
    if len(tris) == 0:
        return None
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    areas = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    k = int(np.argmax(areas))
    p = (a[k] + b[k] + c[k]) / 3
    return float(p[0]), float(p[1])


def closed_loop_of(e) -> tuple | None:
    if isinstance(e, Circle):
        x, y, r = e.center[0], e.center[1], e.radius
        return ((x - r, y, 1.0), (x + r, y, 1.0))
    if isinstance(e, Polyline) and (e.closed or (len(e.vertices) > 2 and e.vertices[0][:2] == e.vertices[-1][:2])):
        return tuple(e.vertices if e.closed else e.vertices[:-1])
    if isinstance(e, Ellipse) and e.is_full:
        return tuple((float(p[0]), float(p[1]), 0.0) for p in e.points(96)[:-1])
    if isinstance(e, Spline) and e.closed:
        return tuple((float(p[0]), float(p[1]), 0.0) for p in e.curve_points(16)[:-1])
    return None


def sources_of_loops(doc: Document, loops, handles, tol: float) -> frozenset[int]:
    """The objects whose outlines make up the boundary loops."""
    out = set()
    pts = np.vstack([np.asarray(lp)[:, :2] for lp in loops])
    for h in handles:
        e = doc.entities.get(h)
        if e is None:
            continue
        prims = doc.geometry(e).prims(snappable_only=True)
        for p in prims:
            b = p.bbox()
            near = pts[(pts[:, 0] >= b[0] - tol) & (pts[:, 0] <= b[2] + tol)
                       & (pts[:, 1] >= b[1] - tol) & (pts[:, 1] <= b[3] + tol)]
            if any(p.distance_to((float(x), float(y))) <= tol for x, y in near[:64]):
                out.add(h)
                break
    return frozenset(out)


def rebuild_hatch(doc: Document, h: Hatch) -> Hatch | None:
    """New boundary from the source objects, or None if it can't be rebuilt."""
    srcs = [doc.entities[k] for k in sorted(h.sources) if k in doc.entities]
    if not srcs:
        return None
    if h.seed is None:
        loops = [closed_loop_of(e) for e in srcs]
        if any(lp is None for lp in loops):
            return None
        return replace(h, loops=tuple(loops), sources=frozenset(e.handle for e in srcs))
    prims = []
    for e in srcs:
        prims.extend(doc.geometry(e).prims(snappable_only=True))
    boxes = [doc.geometry(e).bbox for e in srcs]
    size = max(max(b[2] for b in boxes) - min(b[0] for b in boxes), max(b[3] for b in boxes) - min(b[1] for b in boxes),
               1e-9)
    found = find_boundary(prims, h.seed, tol=size * 1e-7, arc_tol=size * 2e-4)
    if not found:
        # the seed may have ended up outside: try the middle of the old area
        p = interior_point([np.array([v[:2] for v in lp]) for lp in h.loops])
        found = find_boundary(prims, p, tol=size * 1e-7, arc_tol=size * 2e-4) if p else None
        if not found:
            return None
    loops = tuple(tuple((float(x), float(y), 0.0) for x, y in lp) for lp in found)
    seed = interior_point([np.asarray(lp) for lp in found]) or h.seed
    return replace(h, loops=loops, seed=seed)


def rebuild_dimension(doc: Document, d: Dimension, gone: set[int]) -> Dimension:
    refs = list(d.refs)
    for i, (hh, _) in enumerate(refs):
        if hh and (hh in gone or hh not in doc.entities):
            refs[i] = (0, "")
    refs_t = tuple(refs)
    if not any(h for h, _ in refs_t):
        return replace(d, refs=())

    def ent(i):
        return doc.entities.get(refs_t[i][0]) if i < len(refs_t) and refs_t[i][0] else None

    t = d.dimtype
    if t in ("radius", "diameter"):
        e = ent(0)
        if not isinstance(e, (Circle, Arc)):
            return replace(d, refs=())
        dirv = sub(d.p2, d.p1)
        L = math.hypot(*dirv) or 1.0
        c, r = e.center, e.radius
        shift = (c[0] - d.p1[0], c[1] - d.p1[1])
        return replace(d, p1=c, p2=(c[0] + dirv[0] / L * r, c[1] + dirv[1] / L * r), refs=refs_t,
                       location=(d.location[0] + shift[0], d.location[1] + shift[1]))
    if t == "angular":
        a, b = ent(0), ent(1)
        if not (isinstance(a, Line) and isinstance(b, Line)):
            return replace(d, refs=())
        res = line_line(a.p1, sub(a.p2, a.p1), b.p1, sub(b.p2, b.p1))
        if res is None:
            return d
        v = res[0]
        old1 = angle_of(sub(d.p2, d.p1))
        old2 = angle_of(sub(d.p3, d.p1))

        def leg(line, old):
            pts = [line.p1, line.p2]
            pts = [p for p in pts if dist(p, v) > 1e-12] or [line.p2]
            return min(pts, key=lambda p: abs(math.remainder(angle_of(sub(p, v)) - old, math.tau)))
        shift = (v[0] - d.p1[0], v[1] - d.p1[1])
        return replace(d, p1=v, p2=leg(a, old1), p3=leg(b, old2), refs=refs_t,
                       location=(d.location[0] + shift[0], d.location[1] + shift[1]))
    new = {}
    moved = []
    for i, name in enumerate(("p1", "p2", "p3")):
        e = ent(i)
        if e is None:
            continue
        p = point_of(e, refs_t[i][1])
        if p is None:
            refs[i] = (0, "")
            continue
        old = getattr(d, name)
        moved.append((p[0] - old[0], p[1] - old[1]))
        new[name] = p
    if not new:
        return replace(d, refs=tuple(refs))
    shift = (sum(m[0] for m in moved) / len(moved), sum(m[1] for m in moved) / len(moved))
    return replace(d, **new, refs=tuple(refs), location=(d.location[0] + shift[0], d.location[1] + shift[1]))


class AssociativityManager:
    """Called by Document.commit for every transaction (see model.document)."""

    @staticmethod
    def update(doc: Document, tx) -> None:
        changed: set[int] = set()
        gone: set[int] = set()
        for table, key, before, after in tx.changes:
            if table != "entity":
                continue
            changed.add(key)
            if after is None:
                gone.add(key)
            else:
                gone.discard(key)
        if not changed:
            return
        for e in list(doc.entities.values()):
            if isinstance(e, Dimension) and e.refs:
                hs = {h for h, _ in e.refs if h}
                if hs & changed:
                    new = rebuild_dimension(doc, e, gone)
                    if new != e:
                        doc.replace(new)
            elif isinstance(e, Hatch) and e.sources and e.sources & changed and e.handle not in changed:
                new = rebuild_hatch(doc, e)
                doc.replace(new if new is not None else replace(e, sources=frozenset(), seed=None))
            elif isinstance(e, ArrayEntity) and e.sources & changed:
                alive = frozenset(h for h in e.sources if h in doc.entities)
                if not alive:
                    doc.delete(e.handle)
                else:
                    doc.replace(replace(e, sources=alive))      # new object: copies redraw from the sources


_ = loop_area
