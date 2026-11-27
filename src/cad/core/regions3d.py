"""Closed areas drawn on the ground or on sketches, as faces ready to extrude (SketchUp-style push/pull)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import solids as S
from .model import MODEL_SPACE, Circle, Document, is_sketch_space
from .model.tables import SKETCH_PREFIX

REFERENCE_LAYER = "Sketch reference"
SKIP = ("hatch", "text", "mtext", "dimension", "leader", "point", "solid", "viewport", "insert")


@dataclass(frozen=True)
class RegionPick:
    space: str
    plane: S.Plane
    face: object                 # TopoDS_Face of the area (holes included)
    point: tuple                 # 3D point clicked
    local: tuple                 # the same point on the plane (x, y)


def plane_of(doc: Document, space: str) -> S.Plane:
    if is_sketch_space(space):
        sk = doc.sketches.get(space[len(SKETCH_PREFIX):])
        if sk is not None:
            return sk.plane()
    return S.XY


def _space_entities(doc: Document, space: str):
    return [e for e in doc.entities.values()
            if e.space == space and e.TYPE not in SKIP and e.layer != REFERENCE_LAYER and doc.is_visible(e)]


def exact_profile(entities, loop: np.ndarray):
    """A closed object whose outline is this loop (so circles stay true circles), or None."""
    from .geom2d.fill import loop_area
    area = abs(loop_area(loop))
    x0, y0 = loop.min(axis=0)
    x1, y1 = loop.max(axis=0)
    size = max(x1 - x0, y1 - y0, 1e-9)
    for e in entities:
        if not S.is_closed_profile(e):
            continue
        b = e.bbox()
        if b is None or max(abs(b[0] - x0), abs(b[1] - y0), abs(b[2] - x1), abs(b[3] - y1)) > size * 0.01:
            continue
        pts = np.array([p for prim in e.primitives() for p in prim.tessellate(size * 1e-4)])
        if len(pts) > 2 and abs(abs(loop_area(pts)) - area) <= area * 0.01:
            return e
    return None


def circle_of_loop(loop: np.ndarray):
    """A true circle if the loop is a tessellated circle (e.g. a copy inside an array)."""
    if len(loop) < 12:
        return None
    pts = loop[:-1] if np.allclose(loop[0], loop[-1]) else loop
    c = pts.mean(axis=0)
    r = np.linalg.norm(pts - c, axis=1)
    if r.mean() > 0 and np.ptp(r) <= r.mean() * 2e-3:
        return Circle(center=(float(c[0]), float(c[1])), radius=float(r.max()))
    return None


def face_from_loops2d(plane: S.Plane, loops, entities):
    wires = []
    for lp in loops:
        lp = np.asarray(lp, float)
        e = exact_profile(entities, lp) or circle_of_loop(lp)
        if e is not None:
            wires.append(S.wire_from_entity(plane, e))
        else:
            wires.append(S.wire_from_loop(plane, [(float(x), float(y), 0.0) for x, y in lp]))
    return S.face_from_wires(plane, wires[0], wires[1:])


def loops_at(doc: Document, space: str, pt, entities=None):
    """Loops (outer first, then islands) of the closed area around pt in a space, or None."""
    from .geom2d.regions import find_boundary
    ents = entities if entities is not None else _space_entities(doc, space)
    if not ents:
        return None
    prims, boxes = [], []
    for e in ents:
        prims.extend(doc.geometry(e).prims(snappable_only=True))
        b = e.bbox()
        if b:
            boxes.append(b)
    if not prims or len(prims) > 60_000:
        return None
    a = np.array(boxes)
    x0, y0, x1, y1 = a[:, 0].min(), a[:, 1].min(), a[:, 2].max(), a[:, 3].max()
    if not (x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1):
        return None
    size = max(x1 - x0, y1 - y0, 1e-9)
    return find_boundary(prims, pt, tol=size * 1e-7, arc_tol=size * 2e-4)


def region_face(doc: Document, space: str, pt):
    """(face, plane) of the closed area around a 2D point in a space, or None."""
    ents = _space_entities(doc, space)
    loops = loops_at(doc, space, pt, ents)
    if not loops:
        return None
    plane = plane_of(doc, space)
    try:
        return face_from_loops2d(plane, loops, ents), plane
    except S.SolidError:
        return None


def region_at_ray(doc: Document, origin, direction, max_t: float | None = None) -> tuple[float, RegionPick] | None:
    """The nearest closed area (on the ground or a visible sketch) the ray passes through."""
    o, d = np.asarray(origin, float), np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    spaces = [MODEL_SPACE] + [sk.space for sk in doc.sketches.values() if sk.visible]
    best = None
    for space in spaces:
        plane = plane_of(doc, space)
        n = np.array(plane.normal, float)
        den = d @ n
        if abs(den) < 1e-9:
            continue
        t = ((np.array(plane.origin) - o) @ n) / den
        if t <= 0 or (max_t is not None and t > max_t) or (best is not None and t >= best[0]):
            continue
        p = o + d * t
        x, y, _ = plane.to_local(tuple(p))
        hit = region_face(doc, space, (x, y))
        if hit is None:
            continue
        face, pl = hit
        best = (float(t), RegionPick(space, pl, face, tuple(float(v) for v in p), (x, y)))
    return best
