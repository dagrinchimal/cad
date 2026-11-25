"""Drawing entities.

Entities are immutable: editing one means creating a changed copy and
replacing it in the Document (which records the change for undo).
Coordinates are millimetres; angles are radians, counter-clockwise from +X.

Simple entities (lines, circles, ...) describe their own geometry. Composite
ones (hatch, dimensions, block references, text) are turned into drawable
geometry by `model.geometry.build_geometry`, which can look things up in the
document (block definitions, dimension styles, fonts).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, replace
from typing import ClassVar

import numpy as np

from ..geom2d import Arc as ArcPrim
from ..geom2d import BBox, Primitive, Seg, Vec, arc_from_bulge, bbox_union
from ..geom2d import spline as bspline
from ..geom2d.transform import Affine2
from ..geom2d.vec import angle_of, dist
from .styles import BYLAYER, LW_BYLAYER, ColorValue

MODEL_SPACE = "*Model"


@dataclass(frozen=True, slots=True, kw_only=True)
class Entity:
    TYPE: ClassVar[str] = "entity"
    FIELDS: ClassVar[dict[str, str]] = {}     # geometry field -> serialization kind

    handle: int = 0
    layer: str = "0"
    color: ColorValue = BYLAYER
    linetype: str = "ByLayer"
    lineweight: float = LW_BYLAYER
    ltscale: float = 1.0
    space: str = MODEL_SPACE                    # "*Model" or a layout name
    extra: dict = field(default_factory=dict, compare=False)   # unknown keys from newer files

    # ---- geometry ------------------------------------------------------
    def primitives(self) -> list[Primitive]:
        return []

    def bbox(self) -> BBox | None:
        return bbox_union([p.bbox() for p in self.primitives()])

    # ---- snap points ----------------------------------------------------
    def endpoints(self) -> list[Vec]:
        return []

    def midpoints(self) -> list[Vec]:
        return []

    def centers(self) -> list[Vec]:
        return []

    def quadrants(self) -> list[Vec]:
        return []

    def nodes(self) -> list[Vec]:
        return []

    def insertion_points(self) -> list[Vec]:
        return []

    def grip_points(self) -> list[Vec]:
        return self.endpoints() + self.midpoints() + self.centers()

    def length(self) -> float:
        return sum(p.length for p in self.primitives())

    def distance_to(self, pt: Vec) -> float:
        prims = self.primitives()
        if not prims:
            return math.inf
        return min(p.distance_to(pt) for p in prims)

    # ---- editing -----------------------------------------------------------
    def transformed(self, m: Affine2) -> "Entity":
        raise NotImplementedError(f"{type(self).__name__} can't be transformed")

    def with_props(self, **changes) -> "Entity":
        return replace(self, **changes)

    # ---- serialization -------------------------------------------------------
    def geometry_dict(self) -> dict:
        return {name: _to_json(getattr(self, name), kind) for name, kind in self.FIELDS.items()}

    @classmethod
    def from_geometry_dict(cls, d: dict, **props) -> "Entity":
        kw = {}
        for name, kind in cls.FIELDS.items():
            if name in d:
                kw[name] = _from_json(d[name], kind)
        return cls(**kw, **props)


# ------------------------------------------------------------------ json helpers
def _to_json(v, kind: str):
    if kind in ("pt",):
        return [v[0], v[1]]
    if kind in ("pts", "verts"):
        return [list(p) for p in v]
    if kind == "loops":
        return [[list(p) for p in loop] for loop in v]
    if kind == "pairs":
        return [list(p) for p in v]
    if kind == "floats":
        return list(v)
    return v


def _from_json(v, kind: str):
    if kind == "pt":
        return (float(v[0]), float(v[1]))
    if kind == "pts":
        return tuple((float(p[0]), float(p[1])) for p in v)
    if kind == "verts":
        return tuple((float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0) for p in v)
    if kind == "loops":
        return tuple(tuple((float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0) for p in loop)
                     for loop in v)
    if kind == "pairs":
        return tuple((str(p[0]), str(p[1])) for p in v)
    if kind == "floats":
        return tuple(float(x) for x in v)
    if kind == "float":
        return float(v)
    if kind == "int":
        return int(v)
    if kind == "bool":
        return bool(v)
    if kind == "str":
        return str(v)
    return v


def _reflected_angle(m: Affine2, angle: float) -> float:
    """Angle of a direction after transforming it."""
    return angle_of(m.apply_vec((math.cos(angle), math.sin(angle))))


def tessellate_bulge_loop(verts, closed: bool, tol: float) -> list[tuple[float, float, float]]:
    """Replace bulge arcs by short straight segments (for non-uniform scaling)."""
    out = []
    n = len(verts)
    count = n if closed else n - 1
    for i in range(count):
        a, b = verts[i], verts[(i + 1) % n]
        if abs(a[2]) < 1e-12:
            out.append((a[0], a[1], 0.0))
            continue
        prim = arc_from_bulge((a[0], a[1]), (b[0], b[1]), a[2])
        pts = prim.tessellate(tol)
        for p in pts[:-1]:
            out.append((float(p[0]), float(p[1]), 0.0))
    if not closed and n:
        out.append((verts[-1][0], verts[-1][1], 0.0))
    return out


def transform_vertices(verts, closed: bool, m: Affine2, size: float) -> tuple:
    if not m.is_similarity and any(abs(v[2]) > 1e-12 for v in verts):
        verts = tessellate_bulge_loop(verts, closed, max(size, 1e-6) * 1e-3)
    sign = -1.0 if m.is_mirror else 1.0
    return tuple((*m.apply((v[0], v[1])), v[2] * sign) for v in verts)


# ================================================================== simple entities
@dataclass(frozen=True, slots=True, kw_only=True)
class Line(Entity):
    TYPE: ClassVar[str] = "line"
    FIELDS: ClassVar[dict[str, str]] = {"p1": "pt", "p2": "pt"}
    p1: Vec
    p2: Vec

    def primitives(self) -> list[Primitive]:
        return [Seg(self.p1, self.p2)]

    def endpoints(self) -> list[Vec]:
        return [self.p1, self.p2]

    def midpoints(self) -> list[Vec]:
        return [Seg(self.p1, self.p2).mid]

    def transformed(self, m: Affine2) -> "Line":
        return replace(self, p1=m.apply(self.p1), p2=m.apply(self.p2))


@dataclass(frozen=True, slots=True, kw_only=True)
class Circle(Entity):
    TYPE: ClassVar[str] = "circle"
    FIELDS: ClassVar[dict[str, str]] = {"center": "pt", "radius": "float"}
    center: Vec
    radius: float

    def _prim(self) -> ArcPrim:
        return ArcPrim(self.center, self.radius, 0.0, math.tau)

    def primitives(self) -> list[Primitive]:
        return [self._prim()]

    def bbox(self) -> BBox:
        x, y, r = self.center[0], self.center[1], self.radius
        return (x - r, y - r, x + r, y + r)

    def centers(self) -> list[Vec]:
        return [self.center]

    def quadrants(self) -> list[Vec]:
        return self._prim().quadrant_points()

    def grip_points(self) -> list[Vec]:
        return [self.center] + self.quadrants()

    @property
    def diameter(self) -> float:
        return self.radius * 2

    @property
    def area(self) -> float:
        return math.pi * self.radius ** 2

    def transformed(self, m: Affine2) -> Entity:
        if m.is_similarity:
            return replace(self, center=m.apply(self.center), radius=self.radius * m.scale_factor)
        e = Ellipse(center=self.center, major=(self.radius, 0.0), ratio=1.0, **_props(self))
        return e.transformed(m)


@dataclass(frozen=True, slots=True, kw_only=True)
class Arc(Entity):
    """Counter-clockwise arc from start_angle to end_angle (radians), like DXF."""
    TYPE: ClassVar[str] = "arc"
    FIELDS: ClassVar[dict[str, str]] = {"center": "pt", "radius": "float", "start_angle": "float",
                                        "end_angle": "float"}
    center: Vec
    radius: float
    start_angle: float
    end_angle: float

    @classmethod
    def from_primitive(cls, a: ArcPrim, **props) -> "Arc":
        if a.sweep >= 0:
            s, e = a.a0, a.a0 + a.sweep
        else:
            s, e = a.a0 + a.sweep, a.a0
        return cls(center=a.c, radius=a.r, start_angle=s % math.tau, end_angle=e % math.tau, **props)

    @property
    def sweep(self) -> float:
        s = (self.end_angle - self.start_angle) % math.tau
        return math.tau if s < 1e-12 else s

    def _prim(self) -> ArcPrim:
        return ArcPrim(self.center, self.radius, self.start_angle, self.sweep)

    def primitives(self) -> list[Primitive]:
        return [self._prim()]

    def endpoints(self) -> list[Vec]:
        p = self._prim()
        return [p.start, p.end]

    def midpoints(self) -> list[Vec]:
        return [self._prim().mid]

    def centers(self) -> list[Vec]:
        return [self.center]

    def quadrants(self) -> list[Vec]:
        return self._prim().quadrant_points()

    def transformed(self, m: Affine2) -> Entity:
        p = self._prim()
        if m.is_similarity:
            c = m.apply(self.center)
            s, e = m.apply(p.start), m.apply(p.end)
            a0, a1 = angle_of((s[0] - c[0], s[1] - c[1])), angle_of((e[0] - c[0], e[1] - c[1]))
            if m.is_mirror:
                a0, a1 = a1, a0
            return replace(self, center=c, radius=self.radius * m.scale_factor, start_angle=a0, end_angle=a1)
        el = Ellipse(center=self.center, major=(self.radius, 0.0), ratio=1.0,
                     start_param=self.start_angle, end_param=self.start_angle + self.sweep, **_props(self))
        return el.transformed(m)


Vertex = tuple[float, float, float]   # x, y, bulge (bulge applies to the segment that starts here)


@dataclass(frozen=True, slots=True, kw_only=True)
class Polyline(Entity):
    TYPE: ClassVar[str] = "polyline"
    FIELDS: ClassVar[dict[str, str]] = {"vertices": "verts", "closed": "bool"}
    vertices: tuple[Vertex, ...]
    closed: bool = False

    def points(self) -> list[Vec]:
        return [(v[0], v[1]) for v in self.vertices]

    def primitives(self) -> list[Primitive]:
        vs = self.vertices
        n = len(vs)
        out: list[Primitive] = []
        count = n if self.closed else n - 1
        for i in range(max(0, count)):
            a, b = vs[i], vs[(i + 1) % n]
            if a[0] == b[0] and a[1] == b[1]:
                continue
            out.append(arc_from_bulge((a[0], a[1]), (b[0], b[1]), a[2]))
        return out

    def endpoints(self) -> list[Vec]:
        return self.points()

    def midpoints(self) -> list[Vec]:
        return [p.mid for p in self.primitives()]

    def centers(self) -> list[Vec]:
        return [p.c for p in self.primitives() if isinstance(p, ArcPrim)]

    def quadrants(self) -> list[Vec]:
        out: list[Vec] = []
        for p in self.primitives():
            if isinstance(p, ArcPrim):
                out.extend(p.quadrant_points())
        return out

    def grip_points(self) -> list[Vec]:
        return self.points() + self.midpoints()

    def area(self) -> float:
        """Signed area enclosed if closed (includes bulge segments)."""
        if not self.closed or len(self.vertices) < 2:
            return 0.0
        total = 0.0
        for prim in self.primitives():
            p, q = prim.start, prim.end
            total += (p[0] * q[1] - q[0] * p[1]) / 2
            if isinstance(prim, ArcPrim):
                th = prim.sweep
                total += math.copysign(0.5 * prim.r ** 2 * (abs(th) - math.sin(abs(th))), th)
        return total

    def transformed(self, m: Affine2) -> "Polyline":
        b = self.bbox()
        size = max(b[2] - b[0], b[3] - b[1]) if b else 1.0
        return replace(self, vertices=transform_vertices(self.vertices, self.closed, m, size))


@dataclass(frozen=True, slots=True, kw_only=True)
class Point(Entity):
    TYPE: ClassVar[str] = "point"
    FIELDS: ClassVar[dict[str, str]] = {"position": "pt"}
    position: Vec

    def bbox(self) -> BBox:
        x, y = self.position
        return (x, y, x, y)

    def nodes(self) -> list[Vec]:
        return [self.position]

    def grip_points(self) -> list[Vec]:
        return [self.position]

    def distance_to(self, pt: Vec) -> float:
        return math.dist(pt, self.position)

    def transformed(self, m: Affine2) -> "Point":
        return replace(self, position=m.apply(self.position))


@dataclass(frozen=True, slots=True, kw_only=True)
class Ellipse(Entity):
    """Ellipse (or elliptical arc). point(t) = center + major*cos t + minor*sin t,
    minor = major rotated 90 degrees CCW times ratio. Parameters run CCW, like DXF."""
    TYPE: ClassVar[str] = "ellipse"
    FIELDS: ClassVar[dict[str, str]] = {"center": "pt", "major": "pt", "ratio": "float",
                                        "start_param": "float", "end_param": "float"}
    center: Vec
    major: Vec
    ratio: float = 1.0
    start_param: float = 0.0
    end_param: float = math.tau

    @property
    def minor(self) -> Vec:
        return (-self.major[1] * self.ratio, self.major[0] * self.ratio)

    @property
    def is_full(self) -> bool:
        return abs((self.end_param - self.start_param) - math.tau) < 1e-9 or \
            abs(self.end_param - self.start_param) < 1e-12

    @property
    def sweep(self) -> float:
        if self.is_full:
            return math.tau
        return (self.end_param - self.start_param) % math.tau or math.tau

    def point_at(self, t: float) -> Vec:
        c, s = math.cos(t), math.sin(t)
        mi = self.minor
        return (self.center[0] + self.major[0] * c + mi[0] * s, self.center[1] + self.major[1] * c + mi[1] * s)

    def points(self, n: int) -> np.ndarray:
        t = self.start_param + np.linspace(0, self.sweep, n + 1)
        mi = self.minor
        return np.column_stack((self.center[0] + self.major[0] * np.cos(t) + mi[0] * np.sin(t),
                                self.center[1] + self.major[1] * np.cos(t) + mi[1] * np.sin(t)))

    @property
    def major_length(self) -> float:
        return math.hypot(*self.major)

    def primitives(self) -> list[Primitive]:
        a = self.major_length
        n = max(16, min(720, int(48 * self.sweep / math.tau * max(1.0, math.log10(max(a, 1.0)) * 2))))
        pts = self.points(n)
        return [Seg(tuple(pts[i]), tuple(pts[i + 1])) for i in range(n)]

    def bbox(self) -> BBox:
        pts = self.points(128)
        return (float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max()))

    def _in_range(self, t: float) -> bool:
        if self.is_full:
            return True
        return (t - self.start_param) % math.tau <= self.sweep + 1e-9

    def endpoints(self) -> list[Vec]:
        return [] if self.is_full else [self.point_at(self.start_param), self.point_at(self.start_param + self.sweep)]

    def midpoints(self) -> list[Vec]:
        return [] if self.is_full else [self.point_at(self.start_param + self.sweep / 2)]

    def centers(self) -> list[Vec]:
        return [self.center]

    def quadrants(self) -> list[Vec]:
        return [self.point_at(k * math.pi / 2) for k in range(4) if self._in_range(k * math.pi / 2)]

    def grip_points(self) -> list[Vec]:
        return [self.center] + self.quadrants() + self.endpoints()

    def area(self) -> float:
        return math.pi * self.major_length ** 2 * self.ratio if self.is_full else 0.0

    def transformed(self, m: Affine2) -> "Ellipse":
        u = np.array(m.apply_vec(self.major))
        v = np.array(m.apply_vec(self.minor))
        M = np.column_stack((u, v))
        U, S, Vt = np.linalg.svd(M)
        a_vec, b_vec = U[:, 0] * S[0], U[:, 1] * S[1]
        flip = 1.0
        # minor must be the CCW perpendicular of major
        if a_vec[0] * b_vec[1] - a_vec[1] * b_vec[0] < 0:
            flip = -1.0
        ratio = float(S[1] / S[0]) if S[0] > 0 else 1.0
        c = m.apply(self.center)
        if self.is_full:
            return replace(self, center=c, major=(float(a_vec[0]), float(a_vec[1])), ratio=ratio,
                           start_param=0.0, end_param=math.tau)

        def new_param(t: float) -> float:
            w = Vt @ np.array([math.cos(t), math.sin(t)])
            return math.atan2(flip * w[1], w[0]) % math.tau
        t0, t1 = new_param(self.start_param), new_param(self.start_param + self.sweep)
        if m.is_mirror:
            t0, t1 = t1, t0
        if t1 <= t0:
            t1 += math.tau
        return replace(self, center=c, major=(float(a_vec[0]), float(a_vec[1])), ratio=ratio,
                       start_param=t0, end_param=t1)


@dataclass(frozen=True, slots=True, kw_only=True)
class Spline(Entity):
    """Cubic B-spline. If fit points are given, the curve passes through them."""
    TYPE: ClassVar[str] = "spline"
    FIELDS: ClassVar[dict[str, str]] = {"control_points": "pts", "knots": "floats", "degree": "int",
                                        "fit_points": "pts", "closed": "bool"}
    control_points: tuple[Vec, ...]
    knots: tuple[float, ...]
    degree: int = 3
    fit_points: tuple[Vec, ...] = ()
    closed: bool = False

    @classmethod
    def through(cls, pts: list[Vec], closed: bool = False, **props) -> "Spline":
        fit = list(pts)
        if closed and fit[0] != fit[-1]:
            fit = fit + [fit[0]]
        ctrl, knots = bspline.interpolate(np.array(fit), 3)
        degree = min(3, len(fit) - 1)
        return cls(control_points=tuple(map(tuple, ctrl.tolist())), knots=tuple(knots.tolist()),
                   degree=degree, fit_points=tuple(pts), closed=closed, **props)

    def curve_points(self, per_span: int = 24) -> np.ndarray:
        return bspline.tessellate(np.array(self.control_points), np.array(self.knots), self.degree, per_span)

    def primitives(self) -> list[Primitive]:
        pts = self.curve_points()
        return [Seg(tuple(pts[i]), tuple(pts[i + 1])) for i in range(len(pts) - 1)]

    def bbox(self) -> BBox:
        pts = self.curve_points(8)
        return (float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max()))

    def endpoints(self) -> list[Vec]:
        pts = self.curve_points(2)
        if self.closed:
            return [tuple(pts[0])]
        return [tuple(pts[0]), tuple(pts[-1])]

    def midpoints(self) -> list[Vec]:
        k = np.array(self.knots)
        u = (k[self.degree] + k[len(self.control_points)]) / 2
        return [tuple(bspline.evaluate(np.array(self.control_points), k, self.degree, np.array([u]))[0])]

    def nodes(self) -> list[Vec]:
        return list(self.fit_points)

    def grip_points(self) -> list[Vec]:
        return list(self.fit_points) if self.fit_points else list(self.control_points)

    def transformed(self, m: Affine2) -> "Spline":
        return replace(self, control_points=tuple(m.apply(p) for p in self.control_points),
                       fit_points=tuple(m.apply(p) for p in self.fit_points))


# ================================================================== text
@dataclass(frozen=True, slots=True, kw_only=True)
class Text(Entity):
    """Single-line text. Height is the capital-letter height."""
    TYPE: ClassVar[str] = "text"
    FIELDS: ClassVar[dict[str, str]] = {"insert": "pt", "text": "str", "height": "float", "rotation": "float",
                                        "width_factor": "float", "halign": "str", "valign": "str", "font": "str"}
    insert: Vec
    text: str
    height: float = 2.5
    rotation: float = 0.0
    width_factor: float = 1.0
    halign: str = "left"
    valign: str = "baseline"
    font: str = "Arial"

    def insertion_points(self) -> list[Vec]:
        return [self.insert]

    def grip_points(self) -> list[Vec]:
        return [self.insert]

    def transformed(self, m: Affine2) -> "Text":
        return replace(self, **_text_transform(self, m))


def _text_transform(t, m: Affine2) -> dict:
    rot = _reflected_angle(m, t.rotation)
    halign = t.halign
    if m.is_mirror:
        # keep text readable (AutoCAD MIRRTEXT=0): flip direction back and swap left/right
        alt = (rot + math.pi) % math.tau
        if abs(math.remainder(alt - t.rotation, math.tau)) < abs(math.remainder(rot - t.rotation, math.tau)):
            rot = alt
            halign = {"left": "right", "right": "left"}.get(halign, halign)
    return {"insert": m.apply(t.insert), "height": t.height * m.scale_factor, "rotation": rot, "halign": halign}


@dataclass(frozen=True, slots=True, kw_only=True)
class MText(Entity):
    """Multiline text, wrapped to `width` (0 = no wrapping). Attachment uses valign/halign."""
    TYPE: ClassVar[str] = "mtext"
    FIELDS: ClassVar[dict[str, str]] = {"insert": "pt", "text": "str", "height": "float", "width": "float",
                                        "rotation": "float", "halign": "str", "valign": "str",
                                        "line_spacing": "float", "font": "str"}
    insert: Vec
    text: str
    height: float = 2.5
    width: float = 0.0
    rotation: float = 0.0
    halign: str = "left"
    valign: str = "top"
    line_spacing: float = 1.0
    font: str = "Arial"

    def insertion_points(self) -> list[Vec]:
        return [self.insert]

    def grip_points(self) -> list[Vec]:
        return [self.insert]

    def transformed(self, m: Affine2) -> "MText":
        d = _text_transform(self, m)
        d["width"] = self.width * m.scale_factor
        return replace(self, **d)


# ================================================================== hatch
@dataclass(frozen=True, slots=True, kw_only=True)
class Hatch(Entity):
    """Filled or patterned area. Boundary loops use polyline vertices (x, y, bulge), always closed.
    Islands are simply more loops: the even-odd rule decides what's inside."""
    TYPE: ClassVar[str] = "hatch"
    FIELDS: ClassVar[dict[str, str]] = {"loops": "loops", "pattern": "str", "pattern_scale": "float",
                                        "pattern_angle": "float"}
    loops: tuple[tuple[Vertex, ...], ...]
    pattern: str = "SOLID"
    pattern_scale: float = 1.0
    pattern_angle: float = 0.0

    def loop_points(self, tol: float = 0.0) -> list[np.ndarray]:
        out = []
        for loop in self.loops:
            if not loop:
                continue
            size = 1.0
            xs = [v[0] for v in loop]
            ys = [v[1] for v in loop]
            size = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
            verts = tessellate_bulge_loop(loop, True, tol or size * 2e-3) if any(abs(v[2]) > 1e-12 for v in loop) \
                else list(loop)
            out.append(np.array([(v[0], v[1]) for v in verts], dtype=np.float64))
        return out

    def boundary_primitives(self) -> list[Primitive]:
        out: list[Primitive] = []
        for loop in self.loops:
            out.extend(Polyline(vertices=loop, closed=True).primitives())
        return out

    def bbox(self) -> BBox | None:
        return bbox_union([p.bbox() for p in self.boundary_primitives()])

    def area(self) -> float:
        from ..geom2d.fill import triangulate
        tris = triangulate(self.loop_points())
        if len(tris) == 0:
            return 0.0
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        return float(np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])).sum() / 2)

    def grip_points(self) -> list[Vec]:
        b = self.bbox()
        return [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)] if b else []

    def transformed(self, m: Affine2) -> "Hatch":
        b = self.bbox()
        size = max(b[2] - b[0], b[3] - b[1]) if b else 1.0
        loops = tuple(transform_vertices(lp, True, m, size) for lp in self.loops)
        return replace(self, loops=loops, pattern_scale=self.pattern_scale * m.scale_factor,
                       pattern_angle=_reflected_angle(m, self.pattern_angle))


# ================================================================== dimensions & leaders
DIM_TYPES = ("linear", "aligned", "angular", "radius", "diameter", "ordinate")


@dataclass(frozen=True, slots=True, kw_only=True)
class Dimension(Entity):
    """Dimension defined by points; its lines, arrows and text are computed from them.

    linear/aligned: p1, p2 = extension line origins; location = a point on the dimension line;
                    angle = dimension line direction for linear (0 horizontal, pi/2 vertical)
    angular:        p1 = vertex, p2 and p3 = points on the two legs; location = point on the arc
    radius/diameter: p1 = center, p2 = point on the curve, location = text position
    ordinate:       p1 = feature point, location = leader end, axis = "x" or "y"
    """
    TYPE: ClassVar[str] = "dimension"
    FIELDS: ClassVar[dict[str, str]] = {"dimtype": "str", "p1": "pt", "p2": "pt", "p3": "pt", "location": "pt",
                                        "angle": "float", "axis": "str", "text": "str", "style": "str",
                                        "origin": "pt"}
    dimtype: str
    p1: Vec
    p2: Vec = (0.0, 0.0)
    p3: Vec = (0.0, 0.0)
    location: Vec = (0.0, 0.0)
    angle: float = 0.0
    axis: str = "x"
    text: str = ""
    style: str = "Standard"
    origin: Vec = (0.0, 0.0)              # ordinate datum

    def measurement(self) -> float:
        """The measured value: length (mm) or angle (radians)."""
        t = self.dimtype
        if t == "linear":
            d = (self.p2[0] - self.p1[0], self.p2[1] - self.p1[1])
            return abs(d[0] * math.cos(self.angle) + d[1] * math.sin(self.angle))
        if t == "aligned":
            return dist(self.p1, self.p2)
        if t == "radius":
            return dist(self.p1, self.p2)
        if t == "diameter":
            return 2 * dist(self.p1, self.p2)
        if t == "angular":
            a1 = angle_of((self.p2[0] - self.p1[0], self.p2[1] - self.p1[1]))
            a2 = angle_of((self.p3[0] - self.p1[0], self.p3[1] - self.p1[1]))
            sweep = (a2 - a1) % math.tau
            return sweep
        if t == "ordinate":
            return abs(self.p1[0] - self.origin[0]) if self.axis == "x" else abs(self.p1[1] - self.origin[1])
        return 0.0

    def grip_points(self) -> list[Vec]:
        pts = [self.p1, self.location]
        if self.dimtype in ("linear", "aligned", "radius", "diameter"):
            pts.insert(1, self.p2)
        if self.dimtype == "angular":
            pts[1:1] = [self.p2, self.p3]
        return pts

    def transformed(self, m: Affine2) -> "Dimension":
        return replace(self, p1=m.apply(self.p1), p2=m.apply(self.p2), p3=m.apply(self.p3),
                       location=m.apply(self.location), origin=m.apply(self.origin),
                       angle=_reflected_angle(m, self.angle))


@dataclass(frozen=True, slots=True, kw_only=True)
class Leader(Entity):
    """Arrow pointing at something, with a note at the end."""
    TYPE: ClassVar[str] = "leader"
    FIELDS: ClassVar[dict[str, str]] = {"points": "pts", "text": "str", "style": "str"}
    points: tuple[Vec, ...]
    text: str = ""
    style: str = "Standard"

    def grip_points(self) -> list[Vec]:
        return list(self.points)

    def transformed(self, m: Affine2) -> "Leader":
        return replace(self, points=tuple(m.apply(p) for p in self.points))


# ================================================================== blocks
@dataclass(frozen=True, slots=True, kw_only=True)
class AttributeDefinition(Entity):
    """A labelled blank inside a block, filled in when the block is inserted (title blocks…)."""
    TYPE: ClassVar[str] = "attdef"
    FIELDS: ClassVar[dict[str, str]] = {"tag": "str", "prompt": "str", "default": "str", "insert": "pt",
                                        "height": "float", "rotation": "float", "halign": "str", "valign": "str",
                                        "invisible": "bool", "font": "str", "width_factor": "float"}
    tag: str
    prompt: str = ""
    default: str = ""
    insert: Vec = (0.0, 0.0)
    height: float = 2.5
    rotation: float = 0.0
    halign: str = "left"
    valign: str = "baseline"
    invisible: bool = False
    font: str = "Arial"
    width_factor: float = 1.0

    def insertion_points(self) -> list[Vec]:
        return [self.insert]

    def grip_points(self) -> list[Vec]:
        return [self.insert]

    def transformed(self, m: Affine2) -> "AttributeDefinition":
        return replace(self, **_text_transform(self, m))


@dataclass(frozen=True, slots=True, kw_only=True)
class BlockReference(Entity):
    """An inserted copy of a block definition."""
    TYPE: ClassVar[str] = "insert"
    FIELDS: ClassVar[dict[str, str]] = {"name": "str", "insert": "pt", "sx": "float", "sy": "float",
                                        "rotation": "float", "attribs": "pairs"}
    name: str
    insert: Vec = (0.0, 0.0)
    sx: float = 1.0
    sy: float = 1.0
    rotation: float = 0.0
    attribs: tuple[tuple[str, str], ...] = ()      # (tag, value)

    def attrib(self, tag: str, default: str = "") -> str:
        for t, v in self.attribs:
            if t.upper() == tag.upper():
                return v
        return default

    def with_attrib(self, tag: str, value: str) -> "BlockReference":
        items = [(t, v) for t, v in self.attribs if t.upper() != tag.upper()]
        items.append((tag, value))
        return replace(self, attribs=tuple(items))

    def matrix(self, base: Vec = (0.0, 0.0)) -> Affine2:
        return Affine2.insert(self.insert, self.sx, self.sy, self.rotation, base)

    def insertion_points(self) -> list[Vec]:
        return [self.insert]

    def grip_points(self) -> list[Vec]:
        return [self.insert]

    def transformed(self, m: Affine2) -> "BlockReference":
        full = m @ Affine2.insert(self.insert, self.sx, self.sy, self.rotation)
        sx = math.hypot(full.a, full.d)
        rot = math.atan2(full.d, full.a)
        sy = math.hypot(full.b, full.e) * (1 if full.det >= 0 else -1)
        return replace(self, insert=(full.c, full.f), sx=sx, sy=sy, rotation=rot)


# ================================================================== paper space viewports
@dataclass(frozen=True, slots=True, kw_only=True)
class Viewport(Entity):
    """A window on a layout sheet showing model space at a scale."""
    TYPE: ClassVar[str] = "viewport"
    FIELDS: ClassVar[dict[str, str]] = {"center": "pt", "width": "float", "height": "float",
                                        "view_center": "pt", "scale": "float", "locked": "bool"}
    center: Vec
    width: float
    height: float
    view_center: Vec = (0.0, 0.0)
    scale: float = 1.0                # paper mm per model mm (1:50 -> 0.02)
    locked: bool = False

    def rect(self) -> BBox:
        return (self.center[0] - self.width / 2, self.center[1] - self.height / 2,
                self.center[0] + self.width / 2, self.center[1] + self.height / 2)

    def corners(self) -> list[Vec]:
        x0, y0, x1, y1 = self.rect()
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def primitives(self) -> list[Primitive]:
        c = self.corners()
        return [Seg(c[i], c[(i + 1) % 4]) for i in range(4)]

    def endpoints(self) -> list[Vec]:
        return self.corners()

    def grip_points(self) -> list[Vec]:
        return self.corners()

    def model_to_paper(self) -> Affine2:
        return (Affine2.translate(*self.center) @ Affine2.scale(self.scale)
                @ Affine2.translate(-self.view_center[0], -self.view_center[1]))

    def transformed(self, m: Affine2) -> "Viewport":
        s = m.scale_factor
        return replace(self, center=m.apply(self.center), width=self.width * s, height=self.height * s,
                       scale=self.scale * s)


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownEntity(Entity):
    """An entity type this version doesn't know. Kept untouched and saved back."""
    TYPE: ClassVar[str] = "unknown"
    raw: dict = field(default_factory=dict, compare=False)

    def bbox(self) -> BBox | None:
        return None

    def transformed(self, m: Affine2) -> "UnknownEntity":
        return self


def _props(e: Entity) -> dict:
    return {k: getattr(e, k) for k in COMMON_PROP_NAMES if k != "handle"} | {"handle": e.handle}


ENTITY_TYPES: dict[str, type[Entity]] = {
    cls.TYPE: cls for cls in (Line, Circle, Arc, Polyline, Point, Ellipse, Spline, Text, MText, Hatch,
                              Dimension, Leader, AttributeDefinition, BlockReference, Viewport)
}

COMMON_PROP_NAMES = ("handle", "layer", "color", "linetype", "lineweight", "ltscale", "space")


def entity_to_dict(e: Entity) -> dict:
    if isinstance(e, UnknownEntity):
        return dict(e.raw)
    d = {"type": e.TYPE, "handle": e.handle, "layer": e.layer, "color": e.color,
         "linetype": e.linetype, "lineweight": e.lineweight, "ltscale": e.ltscale}
    if e.space != MODEL_SPACE:
        d["space"] = e.space
    d.update(e.geometry_dict())
    d.update(e.extra)
    return d


def entity_from_dict(d: dict) -> Entity:
    cls = ENTITY_TYPES.get(d.get("type", ""))
    props = {k: d[k] for k in COMMON_PROP_NAMES if k in d}
    if "handle" in props:
        props["handle"] = int(props["handle"])
    if cls is None:
        return UnknownEntity(raw=dict(d), **props)
    geo_keys = {f.name for f in fields(cls)} - set(COMMON_PROP_NAMES) - {"extra"}
    known = set(COMMON_PROP_NAMES) | geo_keys | {"type"}
    extra = {k: v for k, v in d.items() if k not in known}
    return cls.from_geometry_dict(d, extra=extra, **props)
