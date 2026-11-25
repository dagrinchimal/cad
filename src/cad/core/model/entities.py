"""Drawing entities.

Entities are immutable: editing one means creating a changed copy and
replacing it in the Document (which records the change for undo).
Coordinates are millimetres; angles are radians, counter-clockwise from +X.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, replace
from typing import ClassVar

from ..geom2d import Arc as ArcPrim
from ..geom2d import BBox, Primitive, Seg, Vec, arc_from_bulge, bbox_union
from .styles import BYLAYER, LW_BYLAYER, ColorValue


@dataclass(frozen=True, slots=True, kw_only=True)
class Entity:
    TYPE: ClassVar[str] = "entity"

    handle: int = 0
    layer: str = "0"
    color: ColorValue = BYLAYER
    linetype: str = "ByLayer"
    lineweight: float = LW_BYLAYER
    ltscale: float = 1.0
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

    def grip_points(self) -> list[Vec]:
        return self.endpoints() + self.midpoints() + self.centers()

    def length(self) -> float:
        return sum(p.length for p in self.primitives())

    def distance_to(self, pt: Vec) -> float:
        prims = self.primitives()
        if not prims:
            return math.inf
        return min(p.distance_to(pt) for p in prims)

    # ---- serialization ---------------------------------------------------
    def geometry_dict(self) -> dict:
        raise NotImplementedError

    @classmethod
    def from_geometry_dict(cls, d: dict, **props) -> "Entity":
        raise NotImplementedError

    def with_props(self, **changes) -> "Entity":
        return replace(self, **changes)


def _pt(v) -> Vec:
    return (float(v[0]), float(v[1]))


@dataclass(frozen=True, slots=True, kw_only=True)
class Line(Entity):
    TYPE: ClassVar[str] = "line"
    p1: Vec
    p2: Vec

    def primitives(self) -> list[Primitive]:
        return [Seg(self.p1, self.p2)]

    def endpoints(self) -> list[Vec]:
        return [self.p1, self.p2]

    def midpoints(self) -> list[Vec]:
        return [Seg(self.p1, self.p2).mid]

    def geometry_dict(self) -> dict:
        return {"p1": list(self.p1), "p2": list(self.p2)}

    @classmethod
    def from_geometry_dict(cls, d: dict, **props) -> "Line":
        return cls(p1=_pt(d["p1"]), p2=_pt(d["p2"]), **props)


@dataclass(frozen=True, slots=True, kw_only=True)
class Circle(Entity):
    TYPE: ClassVar[str] = "circle"
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

    def geometry_dict(self) -> dict:
        return {"center": list(self.center), "radius": self.radius}

    @classmethod
    def from_geometry_dict(cls, d: dict, **props) -> "Circle":
        return cls(center=_pt(d["center"]), radius=float(d["radius"]), **props)


@dataclass(frozen=True, slots=True, kw_only=True)
class Arc(Entity):
    """Counter-clockwise arc from start_angle to end_angle (radians), like DXF."""
    TYPE: ClassVar[str] = "arc"
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

    def geometry_dict(self) -> dict:
        return {"center": list(self.center), "radius": self.radius,
                "start_angle": self.start_angle, "end_angle": self.end_angle}

    @classmethod
    def from_geometry_dict(cls, d: dict, **props) -> "Arc":
        return cls(center=_pt(d["center"]), radius=float(d["radius"]),
                   start_angle=float(d["start_angle"]), end_angle=float(d["end_angle"]), **props)


Vertex = tuple[float, float, float]   # x, y, bulge (bulge applies to the segment that starts here)


@dataclass(frozen=True, slots=True, kw_only=True)
class Polyline(Entity):
    TYPE: ClassVar[str] = "polyline"
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

    def geometry_dict(self) -> dict:
        return {"vertices": [list(v) for v in self.vertices], "closed": self.closed}

    @classmethod
    def from_geometry_dict(cls, d: dict, **props) -> "Polyline":
        verts = tuple((float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0) for v in d["vertices"])
        return cls(vertices=verts, closed=bool(d.get("closed", False)), **props)


@dataclass(frozen=True, slots=True, kw_only=True)
class Point(Entity):
    TYPE: ClassVar[str] = "point"
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

    def geometry_dict(self) -> dict:
        return {"position": list(self.position)}

    @classmethod
    def from_geometry_dict(cls, d: dict, **props) -> "Point":
        return cls(position=_pt(d["position"]), **props)


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownEntity(Entity):
    """An entity type this version doesn't know. Kept untouched and saved back."""
    TYPE: ClassVar[str] = "unknown"
    raw: dict = field(default_factory=dict, compare=False)

    def bbox(self) -> BBox | None:
        return None


ENTITY_TYPES: dict[str, type[Entity]] = {
    cls.TYPE: cls for cls in (Line, Circle, Arc, Polyline, Point)
}

COMMON_PROP_NAMES = ("handle", "layer", "color", "linetype", "lineweight", "ltscale")


def entity_to_dict(e: Entity) -> dict:
    if isinstance(e, UnknownEntity):
        return dict(e.raw)
    d = {"type": e.TYPE, "handle": e.handle, "layer": e.layer, "color": e.color,
         "linetype": e.linetype, "lineweight": e.lineweight, "ltscale": e.ltscale}
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
