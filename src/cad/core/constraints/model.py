"""Constraint records and the geometry they act on.

A reference is (handle, part):
  points:  "p1", "p2", "mid" (lines), "center", "start", "end" (arcs/circles), "v<i>" (polyline vertex), "pt"
  curves:  "line" (a line), "seg<i>" (polyline segment), "circle" (circle or arc)
"""
from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass, replace

import numpy as np

from ..geom2d.vec import Vec
from ..model import Arc, Circle, Entity, Line, Point, Polyline

GEOMETRIC = ("coincident", "collinear", "concentric", "fix", "parallel", "perpendicular", "horizontal", "vertical",
             "tangent", "symmetric", "equal")
DIMENSIONAL = ("distance", "dim_horizontal", "dim_vertical", "radius", "diameter", "angle")


@dataclass(frozen=True, slots=True)
class Constraint:
    id: int
    kind: str
    refs: tuple[tuple[int, str], ...]
    name: str = ""                    # d1, rad1 … for dimensional constraints
    expression: str = ""              # "25.4", "d1 * 2"
    values: tuple[float, ...] = ()    # stored data: fixed coordinates, signs, tangent mode

    @property
    def handles(self) -> frozenset[int]:
        return frozenset(h for h, _ in self.refs)

    @property
    def is_dimensional(self) -> bool:
        return self.kind in DIMENSIONAL

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "refs": [list(r) for r in self.refs], "name": self.name,
                "expression": self.expression, "values": list(self.values)}

    @classmethod
    def from_dict(cls, d: dict) -> "Constraint":
        return cls(int(d["id"]), d["kind"], tuple((int(h), str(p)) for h, p in d.get("refs", [])),
                   d.get("name", ""), d.get("expression", ""), tuple(float(v) for v in d.get("values", [])))


def constraints_to_list(table: dict) -> list[dict]:
    return [c.to_dict() for c in table.values()]


def constraints_from_list(items: list[dict]) -> dict:
    out = {}
    for d in items:
        c = Constraint.from_dict(d)
        out[c.id] = c
    return out


# ------------------------------------------------------------------ parameters
SUPPORTED = (Line, Circle, Arc, Polyline, Point)


def params_of(e: Entity) -> np.ndarray:
    if isinstance(e, Line):
        return np.array([*e.p1, *e.p2], dtype=float)
    if isinstance(e, Circle):
        return np.array([*e.center, e.radius], dtype=float)
    if isinstance(e, Arc):
        return np.array([*e.center, e.radius, e.start_angle, e.start_angle + e.sweep], dtype=float)
    if isinstance(e, Polyline):
        return np.array([c for v in e.vertices for c in v[:2]], dtype=float)
    if isinstance(e, Point):
        return np.array(e.position, dtype=float)
    raise TypeError(f"{type(e).__name__} can't be constrained")


def with_params(e: Entity, x: np.ndarray) -> Entity:
    x = [float(v) for v in x]
    if isinstance(e, Line):
        return replace(e, p1=(x[0], x[1]), p2=(x[2], x[3]))
    if isinstance(e, Circle):
        return replace(e, center=(x[0], x[1]), radius=abs(x[2]))
    if isinstance(e, Arc):
        return replace(e, center=(x[0], x[1]), radius=abs(x[2]), start_angle=x[3] % math.tau,
                       end_angle=x[4] % math.tau)
    if isinstance(e, Polyline):
        vs = tuple((x[2 * i], x[2 * i + 1], v[2]) for i, v in enumerate(e.vertices))
        return replace(e, vertices=vs)
    if isinstance(e, Point):
        return replace(e, position=(x[0], x[1]))
    return e


class GeomView:
    """Reads points/lines/circles of entities from a parameter vector."""

    def __init__(self, ents: dict[int, Entity], offsets: dict[int, int], x: np.ndarray) -> None:
        self.ents, self.off, self.x = ents, offsets, x

    def _p(self, h):
        o = self.off[h]
        return self.x, o

    def point(self, ref) -> tuple:
        h, part = ref
        e = self.ents[h]
        x, o = self._p(h)
        if isinstance(e, Line):
            if part == "p1":
                return x[o], x[o + 1]
            if part == "p2":
                return x[o + 2], x[o + 3]
            return (x[o] + x[o + 2]) / 2, (x[o + 1] + x[o + 3]) / 2
        if isinstance(e, Circle):
            return x[o], x[o + 1]
        if isinstance(e, Arc):
            cx, cy, r = x[o], x[o + 1], x[o + 2]
            if part == "start":
                return cx + r * math.cos(x[o + 3]), cy + r * math.sin(x[o + 3])
            if part == "end":
                return cx + r * math.cos(x[o + 4]), cy + r * math.sin(x[o + 4])
            return cx, cy
        if isinstance(e, Polyline):
            i = int(part[1:]) if part.startswith("v") else 0
            return x[o + 2 * i], x[o + 2 * i + 1]
        return x[o], x[o + 1]

    def line(self, ref) -> tuple[tuple, tuple]:
        h, part = ref
        e = self.ents[h]
        x, o = self._p(h)
        if isinstance(e, Polyline):
            i = int(part[3:]) if part.startswith("seg") else 0
            n = len(e.vertices)
            j = (i + 1) % n
            return (x[o + 2 * i], x[o + 2 * i + 1]), (x[o + 2 * j], x[o + 2 * j + 1])
        return (x[o], x[o + 1]), (x[o + 2], x[o + 3])

    def circle(self, ref) -> tuple[tuple, float]:
        h, _ = ref
        x, o = self._p(h)
        return (x[o], x[o + 1]), x[o + 2]

    def kind(self, ref) -> str:
        e = self.ents[ref[0]]
        if ref[1] in ("line",) or ref[1].startswith("seg"):
            return "line"
        if ref[1] == "circle":
            return "circle"
        return "point"


def point_refs(e: Entity) -> list[tuple[str, Vec]]:
    """Named points of an entity that constraints can attach to."""
    if isinstance(e, Line):
        return [("p1", e.p1), ("p2", e.p2), ("mid", ((e.p1[0] + e.p2[0]) / 2, (e.p1[1] + e.p2[1]) / 2))]
    if isinstance(e, Circle):
        return [("center", e.center)]
    if isinstance(e, Arc):
        s, t = e.endpoints()
        return [("start", s), ("end", t), ("center", e.center)]
    if isinstance(e, Polyline):
        return [(f"v{i}", v[:2]) for i, v in enumerate(e.vertices)]
    if isinstance(e, Point):
        return [("pt", e.position)]
    return []


def nearest_point_ref(e: Entity, pick: Vec) -> tuple[str, Vec] | None:
    refs = point_refs(e)
    if not refs:
        return None
    return min(refs, key=lambda r: math.dist(r[1], pick))


def curve_ref(e: Entity, pick: Vec) -> str | None:
    if isinstance(e, Line):
        return "line"
    if isinstance(e, (Circle, Arc)):
        return "circle"
    if isinstance(e, Polyline):
        prims = e.primitives()
        if not prims:
            return None
        i = min(range(len(prims)), key=lambda k: prims[k].distance_to(pick))
        if hasattr(prims[i], "r"):
            return None             # arc segments of polylines can't be constrained
        return f"seg{i}"
    return None


# ------------------------------------------------------------------ expressions
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"sin": lambda d: math.sin(math.radians(d)), "cos": lambda d: math.cos(math.radians(d)),
          "tan": lambda d: math.tan(math.radians(d)), "sqrt": math.sqrt, "abs": abs, "round": round,
          "min": min, "max": max}
_CONSTS = {"pi": math.pi}


class ExpressionError(ValueError):
    pass


def evaluate(expr: str, names: dict[str, float]) -> float:
    """Safe arithmetic: numbers, + - * / ** ( ), other parameter names, sin cos tan sqrt abs min max pi."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"Can't read the expression '{expr}'") from exc

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Name):
            if n.id in names:
                return names[n.id]
            if n.id in _CONSTS:
                return _CONSTS[n.id]
            raise ExpressionError(f"Unknown name '{n.id}'")
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS:
            return float(_FUNCS[n.func.id](*[ev(a) for a in n.args]))
        raise ExpressionError("Only numbers, + - * / ( ), other parameters and sin/cos/tan/sqrt are allowed")
    try:
        return float(ev(tree))
    except ZeroDivisionError as exc:
        raise ExpressionError("Division by zero") from exc


def resolve_values(constraints: dict) -> dict[str, float]:
    """Values of all named (dimensional) constraints, following references between them."""
    exprs = {c.name: c.expression for c in constraints.values() if c.name}
    out: dict[str, float] = {}
    visiting: set[str] = set()

    def get(name: str) -> float:
        if name in out:
            return out[name]
        if name in visiting:
            raise ExpressionError(f"'{name}' refers to itself")
        visiting.add(name)
        refs = {n: None for n in exprs}

        class Lazy(dict):
            def __missing__(self, key):
                if key in refs:
                    return get(key)
                raise KeyError(key)
        try:
            v = evaluate(exprs[name], _LazyNames(get, exprs))
        finally:
            visiting.discard(name)
        out[name] = v
        return v

    for n in exprs:
        get(n)
    return out


class _LazyNames(dict):
    def __init__(self, getter, exprs) -> None:
        super().__init__()
        self._get, self._exprs = getter, exprs

    def __contains__(self, key) -> bool:
        return key in self._exprs

    def __getitem__(self, key):
        return self._get(key)
