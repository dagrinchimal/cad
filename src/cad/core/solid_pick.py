"""Finding solids, faces and edges under the cursor (a ray) or near a typed 3D point."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import solids as S
from .model import MODEL_SPACE, Document, Solid

Vec3 = tuple[float, float, float]
DOWN = np.array([0.0, 0.0, -1.0])


@dataclass(frozen=True, slots=True)
class FacePick:
    entity: Solid
    face: int
    point: Vec3


@dataclass(frozen=True, slots=True)
class EdgePick:
    entity: Solid
    edge: int
    point: Vec3


def visible_solids(doc: Document) -> list[Solid]:
    return [e for e in doc.entities.values() if isinstance(e, Solid) and e.space == MODEL_SPACE and doc.is_visible(e)]


def ray_from_above(doc: Document, xy) -> tuple[np.ndarray, np.ndarray]:
    top = max((S.bbox3(s.shape)[5] for s in visible_solids(doc)), default=0.0)
    return np.array([xy[0], xy[1], top + 1000.0]), DOWN


def _ray_box(o, d, box) -> bool:
    lo, hi = np.array(box[:3]) - 1e-6, np.array(box[3:]) + 1e-6
    with np.errstate(divide="ignore", invalid="ignore"):
        t1, t2 = (lo - o) / d, (hi - o) / d
    tmin = np.nanmax(np.minimum(t1, t2))
    tmax = np.nanmin(np.maximum(t1, t2))
    return tmax >= max(tmin, 0)


def pick_face(doc: Document, origin, direction) -> FacePick | None:
    o, d = np.asarray(origin, float), np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    best = None
    for s in visible_solids(doc):
        if not _ray_box(o, d, S.bbox3(s.shape)):
            continue
        hit = S.ray_hit(S.mesh(s.shape), o, d)
        if hit and (best is None or hit[0] < best[0]):
            best = (hit[0], s, hit[1])
    if best is None:
        return None
    t, s, fi = best
    p = o + d * t
    return FacePick(s, fi, (float(p[0]), float(p[1]), float(p[2])))


def _ray_segment_distance(o, d, a, b):
    """Distance between a ray and each segment a[i]-b[i], and the ray parameter of the closest point."""
    u = b - a
    w0 = a - o
    A = np.einsum("ij,ij->i", u, u)
    B = u @ d
    C = 1.0
    D = np.einsum("ij,ij->i", u, w0)
    E = w0 @ d
    den = A * C - B * B
    sc = np.where(den > 1e-12, (B * E - C * D) / np.where(den > 1e-12, den, 1), 0.0)
    sc = np.clip(sc, 0, 1)
    tc = np.maximum(sc * B + E, 0)            # along the ray (d is unit)
    p_seg = a + u * sc[:, None]
    p_ray = o + np.outer(tc, d)
    return np.linalg.norm(p_seg - p_ray, axis=1), tc, p_seg


def pick_edge(doc: Document, origin, direction, tolerance: float) -> EdgePick | None:
    """The edge closest to the ray (within tolerance); nearer to the eye wins ties."""
    o, d = np.asarray(origin, float), np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    best = None
    for s in visible_solids(doc):
        box = S.bbox3(s.shape)
        grown = (box[0] - tolerance, box[1] - tolerance, box[2] - tolerance,
                 box[3] + tolerance, box[4] + tolerance, box[5] + tolerance)
        if not _ray_box(o, d, grown):
            continue
        m = S.mesh(s.shape)
        for ei, pts in enumerate(m.edges):
            if len(pts) < 2:
                continue
            dist, t, p = _ray_segment_distance(o, d, pts[:-1], pts[1:])
            i = int(np.argmin(dist))
            if dist[i] > tolerance:
                continue
            key = (round(float(dist[i]) / max(tolerance, 1e-12) * 4), float(t[i]))   # coarse distance, then depth
            if best is None or key < best[0]:
                best = (key, s, ei, p[i])
    if best is None:
        return None
    _, s, ei, p = best
    return EdgePick(s, ei, (float(p[0]), float(p[1]), float(p[2])))


def face_near(doc: Document, point: Vec3) -> FacePick | None:
    """The face closest to a typed 3D point."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    v = BRepBuilderAPI_MakeVertex(S.P(point)).Vertex()
    best = None
    for s in visible_solids(doc):
        for fi, f in enumerate(S.faces(s.shape)):
            dd = BRepExtrema_DistShapeShape(v, f)
            if dd.IsDone() and (best is None or dd.Value() < best[0]):
                best = (dd.Value(), s, fi)
    if best is None:
        return None
    return FacePick(best[1], best[2], tuple(point))


def edge_near(doc: Document, point: Vec3) -> EdgePick | None:
    best = None
    for s in visible_solids(doc):
        m = S.mesh(s.shape)
        ei = S.nearest_edge(m, point)
        if ei is None:
            continue
        pts = m.edges[ei]
        a, b = pts[:-1], pts[1:]
        u = b - a
        L2 = np.einsum("ij,ij->i", u, u)
        t = np.clip(np.einsum("ij,ij->i", np.array(point) - a, u) / np.where(L2 > 0, L2, 1), 0, 1)
        dist = float(np.min(np.linalg.norm(a + u * t[:, None] - np.array(point), axis=1)))
        if best is None or dist < best[0]:
            best = (dist, s, ei)
    if best is None:
        return None
    return EdgePick(best[1], best[2], tuple(point))


def snap_points_3d(doc: Document) -> list[tuple[Vec3, str]]:
    """Vertices, edge midpoints and circle centers of all visible solids (for 3D snapping)."""
    out: list[tuple[Vec3, str]] = []
    for s in visible_solids(doc):
        for v in S.vertices(s.shape):
            out.append((v, "endpoint"))
        m = S.mesh(s.shape)
        for e, pts, kind in zip(S.edges(s.shape), m.edges, m.edge_kind):
            if len(pts) < 2:
                continue
            if kind == "line":
                out.append((tuple((pts[0] + pts[-1]) / 2), "midpoint"))
            elif kind == "circle":
                info = S.edge_info(e)
                out.append((info["center"], "center"))
    return out


__all__ = ["FacePick", "EdgePick", "pick_face", "pick_edge", "face_near", "edge_near", "ray_from_above",
           "visible_solids", "snap_points_3d"]
_ = math
