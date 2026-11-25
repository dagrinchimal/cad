"""Object snaps, grid snap, ortho, polar tracking and object snap tracking.

The engine is pure geometry: the UI gives it the cursor position (model units),
the size of one screen pixel in model units and the command's base point, and
gets back the point to use plus what to draw (marker, tooltip, tracking lines).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from .geom2d import Seg, Vec, perpendicular_foot, tangent_points
from .geom2d.construct import intersect, line_line
from .geom2d.primitives import Arc as ArcPrim
from .geom2d.vec import angle_of, dist, normalize, sub
from .model import Line
from .spatial import SpatialIndex
from .units import UnitSettings, format_angle, format_length


class Osnap(str, Enum):
    ENDPOINT = "endpoint"
    MIDPOINT = "midpoint"
    CENTER = "center"
    INTERSECTION = "intersection"
    PERPENDICULAR = "perpendicular"
    TANGENT = "tangent"
    NEAREST = "nearest"
    QUADRANT = "quadrant"
    NODE = "node"
    EXTENSION = "extension"

    @property
    def label(self) -> str:
        return self.value.capitalize()


DEFAULT_OSNAPS = frozenset({
    Osnap.ENDPOINT, Osnap.MIDPOINT, Osnap.CENTER, Osnap.INTERSECTION, Osnap.PERPENDICULAR,
    Osnap.QUADRANT, Osnap.NODE, Osnap.EXTENSION,
})

# lower = preferred when two snaps are about the same distance from the cursor
_PENALTY = {
    Osnap.ENDPOINT: 0.0, Osnap.INTERSECTION: 0.0, Osnap.NODE: 0.0,
    Osnap.MIDPOINT: 0.05, Osnap.CENTER: 0.1, Osnap.QUADRANT: 0.05,
    Osnap.PERPENDICULAR: 0.15, Osnap.TANGENT: 0.15, Osnap.EXTENSION: 0.3, Osnap.NEAREST: 1.0,
}

TRACKABLE = {Osnap.ENDPOINT, Osnap.MIDPOINT, Osnap.CENTER, Osnap.INTERSECTION, Osnap.QUADRANT, Osnap.NODE}


@dataclass(slots=True)
class SnapSettings:
    osnap_on: bool = True
    modes: frozenset[Osnap] = DEFAULT_OSNAPS
    grid_snap_on: bool = False
    grid_on: bool = True
    ortho_on: bool = False
    polar_on: bool = True
    polar_increment_deg: float = 45.0
    otrack_on: bool = True
    aperture_px: float = 10.0


@dataclass(slots=True)
class TrackLine:
    origin: Vec
    direction: Vec        # unit vector
    label: str


@dataclass(slots=True)
class SnapResult:
    point: Vec
    kind: str | None = None             # Osnap value, "grid", "polar", "ortho", "track" or None
    tooltip: str = ""
    marker_point: Vec | None = None
    track_lines: list[tuple[Vec, Vec]] = field(default_factory=list)   # segments to draw dotted
    osnap: Osnap | None = None


@dataclass(slots=True)
class AcquiredPoint:
    point: Vec
    extension_dir: Vec | None = None    # set for line endpoints (Extension snap)


class SnapEngine:
    MAX_ACQUIRED = 7

    def __init__(self, index: SpatialIndex, units: UnitSettings | None = None) -> None:
        self.index = index
        self.units = units or UnitSettings()
        self.acquired: list[AcquiredPoint] = []

    # ------------------------------------------------------------ tracking points
    def toggle_acquire(self, point: Vec, extension_dir: Vec | None = None, tol: float = 1e-9) -> bool:
        """Acquire (or release) a tracking point. Returns True if now acquired."""
        for i, a in enumerate(self.acquired):
            if dist(a.point, point) <= tol:
                del self.acquired[i]
                return False
        self.acquired.append(AcquiredPoint(point, extension_dir))
        if len(self.acquired) > self.MAX_ACQUIRED:
            self.acquired.pop(0)
        return True

    def clear_acquired(self) -> None:
        self.acquired.clear()

    # ------------------------------------------------------------ main entry
    def snap(self, cursor: Vec, pixel: float, cfg: SnapSettings, base: Vec | None = None,
             grid_spacing: float = 10.0, snap_spacing: float = 10.0) -> SnapResult:
        tol = cfg.aperture_px * pixel

        if cfg.osnap_on and cfg.modes:
            hit = self.object_snap(cursor, tol, cfg.modes, base)
            if hit is not None:
                return hit

        tracking = self.tracking(cursor, tol, cfg, base)
        if tracking is not None:
            return tracking

        if base is not None and cfg.ortho_on:
            dx, dy = cursor[0] - base[0], cursor[1] - base[1]
            pt = (cursor[0], base[1]) if abs(dx) >= abs(dy) else (base[0], cursor[1])
            if cfg.grid_snap_on:
                pt = self._snap_along_ortho(pt, base, snap_spacing)
            return SnapResult(pt, "ortho", "Ortho")

        if cfg.grid_snap_on and snap_spacing > 0:
            pt = (round(cursor[0] / snap_spacing) * snap_spacing, round(cursor[1] / snap_spacing) * snap_spacing)
            return SnapResult(pt, "grid")
        return SnapResult(cursor)

    @staticmethod
    def _snap_along_ortho(pt: Vec, base: Vec, step: float) -> Vec:
        if step <= 0:
            return pt
        if pt[1] == base[1]:
            return (base[0] + round((pt[0] - base[0]) / step) * step, pt[1])
        return (pt[0], base[1] + round((pt[1] - base[1]) / step) * step)

    # ------------------------------------------------------------ object snaps
    def object_snap(self, cursor: Vec, tol: float, modes: frozenset[Osnap],
                    base: Vec | None = None) -> SnapResult | None:
        ents = self.index.near(cursor, tol)
        if len(ents) > 60:
            ents.sort(key=lambda e: e.distance_to(cursor))
            ents = ents[:60]
        cands: list[tuple[float, Vec, Osnap]] = []

        def add(pt: Vec, mode: Osnap, d: float | None = None) -> None:
            dd = dist(pt, cursor) if d is None else d
            if dd <= tol:
                cands.append((dd / tol + _PENALTY[mode], pt, mode))

        for e in ents:
            if Osnap.ENDPOINT in modes:
                for p in e.endpoints():
                    add(p, Osnap.ENDPOINT)
            if Osnap.MIDPOINT in modes:
                for p in e.midpoints():
                    add(p, Osnap.MIDPOINT)
            if Osnap.QUADRANT in modes:
                for p in e.quadrants():
                    add(p, Osnap.QUADRANT)
            if Osnap.NODE in modes:
                for p in e.nodes():
                    add(p, Osnap.NODE)
            if Osnap.CENTER in modes and e.centers():
                edge = e.distance_to(cursor)
                for p in e.centers():
                    if dist(p, cursor) <= tol:
                        add(p, Osnap.CENTER)
                    elif edge <= tol:            # hovering the curve shows its center
                        add(p, Osnap.CENTER, d=edge)
            prims = e.primitives()
            if base is not None and Osnap.PERPENDICULAR in modes:
                for prim in prims:
                    for f in perpendicular_foot(prim, base):
                        if dist(f, base) > 1e-9:
                            add(f, Osnap.PERPENDICULAR)
            if base is not None and Osnap.TANGENT in modes:
                for prim in prims:
                    if isinstance(prim, ArcPrim):
                        for t in tangent_points(base, prim.c, prim.r):
                            if prim.contains_angle(angle_of(sub(t, prim.c))):
                                add(t, Osnap.TANGENT)
            if Osnap.NEAREST in modes:
                for prim in prims:
                    add(prim.nearest(cursor), Osnap.NEAREST)

        if Osnap.INTERSECTION in modes and len(ents) > 0:
            all_prims = [(i, p) for i, e in enumerate(ents[:30]) for p in e.primitives()]
            for a in range(len(all_prims)):
                ia, pa = all_prims[a]
                for b in range(a + 1, len(all_prims)):
                    ib, pb = all_prims[b]
                    for pt in intersect(pa, pb):
                        if ia == ib and _is_shared_vertex(pa, pb, pt):
                            continue
                        add(pt, Osnap.INTERSECTION)

        if Osnap.EXTENSION in modes:
            for acq in self.acquired:
                if acq.extension_dir is None:
                    continue
                d = acq.extension_dir
                t = (cursor[0] - acq.point[0]) * d[0] + (cursor[1] - acq.point[1]) * d[1]
                if t <= tol:
                    continue
                pt = (acq.point[0] + d[0] * t, acq.point[1] + d[1] * t)
                if dist(pt, cursor) <= tol:
                    cands.append((dist(pt, cursor) / tol + _PENALTY[Osnap.EXTENSION], pt, Osnap.EXTENSION))

        if not cands:
            return None
        _, pt, mode = min(cands, key=lambda c: c[0])
        res = SnapResult(pt, mode.value, mode.label, marker_point=pt, osnap=mode)
        if mode is Osnap.EXTENSION:
            acq = next(a for a in self.acquired if a.extension_dir is not None
                       and abs((pt[0] - a.point[0]) * a.extension_dir[1] - (pt[1] - a.point[1]) * a.extension_dir[0]) < 1e-6 * max(1.0, tol))
            res.track_lines.append((acq.point, pt))
            res.tooltip = f"Extension: {format_length(dist(acq.point, pt), self.units)} < " \
                          f"{format_angle(math.degrees(angle_of(acq.extension_dir)), self.units)}"
        return res

    def extension_dir_for(self, point: Vec, tol: float) -> Vec | None:
        """If point is the end of a line, the direction pointing outward from it."""
        for e in self.index.near(point, tol):
            if isinstance(e, Line):
                if dist(e.p2, point) <= tol:
                    return normalize(sub(e.p2, e.p1))
                if dist(e.p1, point) <= tol:
                    return normalize(sub(e.p1, e.p2))
            else:
                for prim in e.primitives():
                    if isinstance(prim, Seg):
                        if dist(prim.q, point) <= tol:
                            return normalize(sub(prim.q, prim.p))
                        if dist(prim.p, point) <= tol:
                            return normalize(sub(prim.p, prim.q))
        return None

    # ------------------------------------------------------------ polar & object tracking
    def _track_lines(self, cfg: SnapSettings, base: Vec | None) -> list[TrackLine]:
        lines: list[TrackLine] = []
        inc = cfg.polar_increment_deg if cfg.polar_on and cfg.polar_increment_deg > 0 else 90.0
        angles = [k * inc for k in range(int(round(360 / inc)))] if inc > 0 else [0, 90, 180, 270]
        if base is not None and cfg.polar_on and not cfg.ortho_on:
            for a in angles:
                r = math.radians(a)
                lines.append(TrackLine(base, (math.cos(r), math.sin(r)), "Polar"))
        if cfg.otrack_on:
            track_angles = angles if cfg.polar_on else [0, 90, 180, 270]
            for acq in self.acquired:
                for a in track_angles:
                    r = math.radians(a)
                    lines.append(TrackLine(acq.point, (math.cos(r), math.sin(r)), "Track"))
        return lines

    def tracking(self, cursor: Vec, tol: float, cfg: SnapSettings, base: Vec | None) -> SnapResult | None:
        lines = self._track_lines(cfg, base)
        if not lines:
            return None
        active: list[tuple[float, TrackLine, Vec, float]] = []
        for ln in lines:
            ox, oy = ln.origin
            dx, dy = ln.direction
            t = (cursor[0] - ox) * dx + (cursor[1] - oy) * dy
            if t < tol * 0.5:               # tracking only runs forward from its origin
                continue
            px, py = ox + dx * t, oy + dy * t
            d = math.hypot(cursor[0] - px, cursor[1] - py)
            if d <= tol:
                active.append((d, ln, (px, py), t))
        if not active:
            return None
        active.sort(key=lambda a: a[0])
        # two tracking paths crossing near the cursor
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                la, lb = active[i][1], active[j][1]
                if la.origin == lb.origin:
                    continue
                res = line_line(la.origin, la.direction, lb.origin, lb.direction)
                if res and res[1] > 0 and res[2] > 0 and dist(res[0], cursor) <= tol * 1.5:
                    pt = res[0]
                    return SnapResult(pt, "track", "Intersection of tracking paths",
                                      marker_point=pt, track_lines=[(la.origin, pt), (lb.origin, pt)])
        d, ln, pt, t = active[0]
        if cfg.grid_snap_on and ln.label == "Polar":
            pass  # polar snap increments could go here
        angle = math.degrees(angle_of(ln.direction))
        label = "Polar" if ln.label == "Polar" else "Track"
        tip = f"{label}: {format_length(t, self.units)} < {format_angle(angle, self.units)}"
        return SnapResult(pt, "polar" if label == "Polar" else "track", tip, track_lines=[(ln.origin, pt)])


def _is_shared_vertex(pa, pb, pt: Vec) -> bool:
    """Adjacent segments of one polyline meet at a vertex; that's an endpoint, not an intersection."""
    ends_a = (pa.start, pa.end)
    ends_b = (pb.start, pb.end)
    return any(dist(pt, x) < 1e-9 for x in ends_a) and any(dist(pt, x) < 1e-9 for x in ends_b)
