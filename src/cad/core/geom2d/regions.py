"""Find the closed area around a point (HATCH / BOUNDARY 'pick internal point').

All curves are flattened to segments, split where they cross, and turned into a
planar graph. Walking the face that contains the point gives the outer boundary;
other closed shapes lying inside it become islands (holes), nested ones alternate.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from rtree import index as rindex

from .fill import loop_area, point_in_loop
from .primitives import Arc, Primitive, Seg
from .vec import Vec


class _Points:
    """Merges points closer than tol."""

    def __init__(self, tol: float) -> None:
        self.tol = tol
        self.cell = tol * 2
        self.pts: list[Vec] = []
        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)

    def id(self, p: Vec) -> int:
        cx, cy = int(math.floor(p[0] / self.cell)), int(math.floor(p[1] / self.cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in self.grid.get((cx + dx, cy + dy), ()):
                    q = self.pts[i]
                    if abs(q[0] - p[0]) <= self.tol and abs(q[1] - p[1]) <= self.tol:
                        return i
        self.pts.append(p)
        self.grid[(cx, cy)].append(len(self.pts) - 1)
        return len(self.pts) - 1


def flatten(prims: list[Primitive], arc_tol: float) -> list[tuple[Vec, Vec]]:
    segs: list[tuple[Vec, Vec]] = []
    for p in prims:
        if isinstance(p, Arc):
            pts = p.tessellate(arc_tol)
            segs.extend((tuple(pts[i]), tuple(pts[i + 1])) for i in range(len(pts) - 1))
        else:
            segs.append((p.p, p.q))
    return segs


def _split(segs: list[tuple[Vec, Vec]], tol: float) -> list[tuple[Vec, Vec]]:
    """Split segments at every crossing (rtree-accelerated)."""
    n = len(segs)
    if n == 0:
        return []
    arr = np.array([(a[0], a[1], b[0], b[1]) for a, b in segs], dtype=np.float64)
    boxes = np.column_stack((np.minimum(arr[:, 0], arr[:, 2]) - tol, np.minimum(arr[:, 1], arr[:, 3]) - tol,
                             np.maximum(arr[:, 0], arr[:, 2]) + tol, np.maximum(arr[:, 1], arr[:, 3]) + tol))
    tree = rindex.Index(((i, tuple(boxes[i]), None) for i in range(n)), interleaved=True)
    cuts: list[list[float]] = [[0.0, 1.0] for _ in range(n)]
    for i in range(n):
        p = arr[i, 0:2]
        r = arr[i, 2:4] - p
        rr = r @ r
        if rr <= 0:
            continue
        for j in tree.intersection(tuple(boxes[i])):
            if j <= i:
                continue
            q = arr[j, 0:2]
            s = arr[j, 2:4] - q
            den = r[0] * s[1] - r[1] * s[0]
            qp = q - p
            if abs(den) < 1e-15 * max(1.0, rr):
                # collinear overlap: cut each at the other's endpoints
                if abs(qp[0] * r[1] - qp[1] * r[0]) <= tol * math.sqrt(rr):
                    for k, pt in ((i, arr[j, 0:2]), (i, arr[j, 2:4])):
                        t = ((pt - p) @ r) / rr
                        if 0 < t < 1:
                            cuts[k].append(t)
                    ss = s @ s
                    if ss > 0:
                        for pt in (arr[i, 0:2], arr[i, 2:4]):
                            t = ((pt - q) @ s) / ss
                            if 0 < t < 1:
                                cuts[j].append(t)
                continue
            t = (qp[0] * s[1] - qp[1] * s[0]) / den
            u = (qp[0] * r[1] - qp[1] * r[0]) / den
            et = tol / math.sqrt(rr)
            eu = tol / max(math.sqrt(s @ s), 1e-300)
            if -et <= t <= 1 + et and -eu <= u <= 1 + eu:
                cuts[i].append(min(1.0, max(0.0, t)))
                cuts[j].append(min(1.0, max(0.0, u)))
    out = []
    for i in range(n):
        ts = sorted(set(cuts[i]))
        p, q = arr[i, 0:2], arr[i, 2:4]
        for a, b in zip(ts, ts[1:]):
            if b - a > 1e-12:
                out.append((tuple(p + (q - p) * a), tuple(p + (q - p) * b)))
    return out


class PlanarGraph:
    def __init__(self, segs: list[tuple[Vec, Vec]], tol: float) -> None:
        pts = _Points(tol)
        edges = set()
        for a, b in segs:
            i, j = pts.id(a), pts.id(b)
            if i != j:
                edges.add((min(i, j), max(i, j)))
        self.pts = pts.pts
        adj: dict[int, set[int]] = defaultdict(set)
        for i, j in edges:
            adj[i].add(j)
            adj[j].add(i)
        # prune dangling edges: they can't bound an area
        stack = [v for v, nb in adj.items() if len(nb) == 1]
        while stack:
            v = stack.pop()
            for w in list(adj.get(v, ())):
                adj[w].discard(v)
                if len(adj[w]) == 1:
                    stack.append(w)
            adj.pop(v, None)
        self.adj = {v: nb for v, nb in adj.items() if nb}
        self.order: dict[int, list[int]] = {}
        for v, nb in self.adj.items():
            px, py = self.pts[v]
            self.order[v] = sorted(nb, key=lambda w: math.atan2(self.pts[w][1] - py, self.pts[w][0] - px))

    def edges(self):
        for v, nb in self.adj.items():
            for w in nb:
                if v < w:
                    yield v, w

    def next_edge(self, a: int, b: int) -> int:
        """Next vertex after a->b keeping the face on the left."""
        ring = self.order[b]
        k = ring.index(a)
        return ring[k - 1]          # the one just clockwise of the way back

    def walk(self, a: int, b: int, limit: int = 1_000_000) -> list[int] | None:
        start = (a, b)
        loop = [a]
        u, v = a, b
        for _ in range(limit):
            loop.append(v)
            w = self.next_edge(u, v)
            u, v = v, w
            if (u, v) == start:
                return loop[:-1]
        return None

    def face_at(self, pt: Vec, edges: list[tuple[int, int]] | None = None) -> list[int] | None:
        """Vertices of the face whose interior contains pt (ray cast towards +x)."""
        best, best_x = None, math.inf
        x0, y0 = pt
        for i, j in (edges if edges is not None else self.edges()):
            (ax, ay), (bx, by) = self.pts[i], self.pts[j]
            if (ay > y0) == (by > y0):
                continue
            x = ax + (y0 - ay) * (bx - ax) / (by - ay)
            if x > x0 and x < best_x:
                best_x, best = x, (i, j)
        if best is None:
            return None
        i, j = best
        (ax, ay), (bx, by) = self.pts[i], self.pts[j]
        if (bx - ax) * (y0 - ay) - (by - ay) * (x0 - ax) < 0:     # keep pt on the left
            i, j = j, i
        return self.walk(i, j)

    def components(self) -> list[set[int]]:
        seen, comps = set(), []
        for v in self.adj:
            if v in seen:
                continue
            comp, stack = set(), [v]
            while stack:
                x = stack.pop()
                if x in comp:
                    continue
                comp.add(x)
                stack.extend(self.adj[x] - comp)
            seen |= comp
            comps.append(comp)
        return comps


def find_boundary(prims: list[Primitive], pt: Vec, tol: float, arc_tol: float | None = None,
                  islands: bool = True) -> list[np.ndarray] | None:
    """Loops (outer first, then islands) around pt, or None if pt isn't inside a closed area."""
    segs = _split(flatten(prims, arc_tol or tol), tol)
    g = PlanarGraph(segs, tol)
    if not g.adj:
        return None
    face = g.face_at(pt)
    if face is None or len(face) < 3:
        return None
    outer = np.array([g.pts[i] for i in face])
    if loop_area(outer) <= 0 or not point_in_loop(pt[0], pt[1], outer):
        return None
    loops = [outer]
    if islands:
        face_set = set(face)
        for comp in g.components():
            if comp & face_set:
                continue
            v = next(iter(comp))
            if not point_in_loop(g.pts[v][0], g.pts[v][1], outer):
                continue
            left = min(comp, key=lambda k: (g.pts[k][0], g.pts[k][1]))
            probe = (g.pts[left][0] - tol * 10, g.pts[left][1] + tol * 0.37)
            comp_edges = [(i, j) for i, j in g.edges() if i in comp]
            f = g.face_at(probe, comp_edges)
            if f and len(f) >= 3:
                isl = np.array([g.pts[i] for i in f])
                if abs(loop_area(isl)) > tol * tol:
                    loops.append(isl)
    return loops


_ = Seg
