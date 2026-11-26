"""Revit-style "click the number and type a new value".

When one object is selected the UI shows editable values:
  * temporary dimensions of the object itself (line length, circle/arc radius, polyline segment lengths)
  * every permanent associative dimension attached to it

`apply_value` changes the geometry so the chosen measurement becomes the typed value. Attached
dimensions, hatches and arrays follow through the normal associativity update.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .geom2d.transform import Affine2
from .geom2d.vec import Vec, dist, sub
from .model import Arc, Circle, Dimension, Document, Entity, Line, Polyline
from .points import move_point, point_of
from .text import BOTTOM, CENTER, LEFT, MIDDLE, RIGHT


@dataclass(frozen=True, slots=True)
class EditableValue:
    kind: str            # "length" (line), "radius", "segment" (polyline), "dim" (permanent dimension)
    handle: int          # the object measured, or the dimension for kind "dim"
    a: Vec               # what is measured (for drawing temporary dimensions)
    b: Vec
    value: float         # mm, or radians when angular
    index: int = 0       # polyline segment index
    angular: bool = False
    label_at: Vec | None = None   # where the value is shown (permanent dims: their text)


def editable_values(doc: Document, e: Entity) -> list[EditableValue]:
    out: list[EditableValue] = []
    if isinstance(e, Line):
        out.append(EditableValue("length", e.handle, e.p1, e.p2, dist(e.p1, e.p2)))
    elif isinstance(e, (Circle, Arc)):
        c, r = e.center, e.radius
        out.append(EditableValue("radius", e.handle, c, (c[0] + r * math.cos(math.pi / 4), c[1] + r * math.sin(math.pi / 4)), r))
    elif isinstance(e, Polyline):
        vs = e.vertices
        n = len(vs)
        for i in range(n if e.closed else n - 1):
            a, b = vs[i], vs[(i + 1) % n]
            if abs(a[2]) > 1e-12:
                continue                  # arc segments: not editable as a length
            pa, pb = (a[0], a[1]), (b[0], b[1])
            if dist(pa, pb) > 1e-9:
                out.append(EditableValue("segment", e.handle, pa, pb, dist(pa, pb), index=i))
    for d in attached_dimensions(doc, e.handle):
        out.append(EditableValue("dim", d.handle, d.p1, d.p2, d.measurement(), angular=d.dimtype == "angular",
                                 label_at=dimension_text_center(doc, d)))
    if isinstance(e, Dimension) and e.is_associative:
        out.append(EditableValue("dim", e.handle, e.p1, e.p2, e.measurement(), angular=e.dimtype == "angular",
                                 label_at=dimension_text_center(doc, e)))
    return out


def attached_dimensions(doc: Document, handle: int) -> list[Dimension]:
    return [d for d in doc.entities.values()
            if isinstance(d, Dimension) and any(h == handle for h, _ in d.refs)]


def dimension_text_center(doc: Document, d: Dimension) -> Vec:
    for part in doc.geometry(d).parts:
        for run in part.texts:
            th = run.height
            w = 0.6 * th * max(1, len(run.text))
            dx = {CENTER: 0.0, LEFT: w / 2, RIGHT: -w / 2}.get(run.halign, 0.0)
            dy = {BOTTOM: th / 2, MIDDLE: 0.0}.get(run.valign, th / 2)
            c, s = math.cos(run.rotation), math.sin(run.rotation)
            return (run.insert[0] + dx * c - dy * s, run.insert[1] + dx * s + dy * c)
    return d.location


# ------------------------------------------------------------------ applying a typed value
class EditError(ValueError):
    pass


def _unit(v: Vec) -> Vec:
    L = math.hypot(*v)
    if L < 1e-12:
        raise EditError("The measured points coincide.")
    return (v[0] / L, v[1] / L)


def _stretch_polyline(pl: Polyline, u: Vec, from_pt: Vec, delta: float) -> Polyline:
    """Move every vertex on the far side of `from_pt` (along u) by delta*u, like a STRETCH."""
    ref = from_pt[0] * u[0] + from_pt[1] * u[1]
    tol = 1e-6 * max(1.0, abs(ref))
    vs = []
    for x, y, b in pl.vertices:
        if x * u[0] + y * u[1] >= ref - tol:
            x, y = x + delta * u[0], y + delta * u[1]
        vs.append((x, y, b))
    return replace(pl, vertices=tuple(vs))


def apply_value(doc: Document, target: EditableValue, value: float, selected: int | None = None) -> None:
    """Make the measurement equal `value` (call inside a transaction). Raises EditError."""
    if not target.angular and value <= 0 and target.kind != "dim":
        raise EditError("The value must be greater than zero.")
    if target.kind == "dim":
        d = doc.get(target.handle)
        if not isinstance(d, Dimension):
            raise EditError("The dimension no longer exists.")
        _apply_dimension(doc, d, value, selected)
        return
    e = doc.get(target.handle)
    if target.kind == "length" and isinstance(e, Line):
        u = _unit(sub(e.p2, e.p1))
        doc.replace(replace(e, p2=(e.p1[0] + u[0] * value, e.p1[1] + u[1] * value)))
    elif target.kind == "radius" and isinstance(e, (Circle, Arc)):
        doc.replace(replace(e, radius=value))
    elif target.kind == "segment" and isinstance(e, Polyline):
        u = _unit(sub(target.b, target.a))
        doc.replace(_stretch_polyline(e, u, target.b, value - target.value))
    else:
        raise EditError("That object changed; select it again.")


def _apply_dimension(doc: Document, d: Dimension, value: float, selected: int | None) -> None:
    refs = list(d.refs) + [(0, "")] * (3 - len(d.refs))
    ent = lambda i: doc.entities.get(refs[i][0]) if refs[i][0] else None
    t = d.dimtype
    if t in ("radius", "diameter"):
        e = ent(0)
        if not isinstance(e, (Circle, Arc)):
            raise EditError("This dimension is not attached to a circle or arc.")
        r = value / 2 if t == "diameter" else value
        if r <= 0:
            raise EditError("The value must be greater than zero.")
        doc.replace(replace(e, radius=r))
        return
    if t == "angular":
        a, b = ent(0), ent(1)
        if not (isinstance(a, Line) and isinstance(b, Line)):
            raise EditError("This angle is not attached to two lines.")
        delta = value - d.measurement()
        if selected == a.handle:            # rotate the one the user selected
            doc.replace(a.transformed(Affine2.rotate(-delta, d.p1)))
        else:
            doc.replace(b.transformed(Affine2.rotate(delta, d.p1)))
        return
    if value <= 0 and t != "ordinate":
        raise EditError("The value must be greater than zero.")
    if t == "ordinate":
        e = ent(0)
        if e is None:
            raise EditError("This dimension is not attached to an object.")
        u = (1.0, 0.0) if d.axis == "x" else (0.0, 1.0)
        s = (d.p1[0] - d.origin[0]) * u[0] + (d.p1[1] - d.origin[1]) * u[1]
        delta = math.copysign(value, s or 1.0) - s
        doc.replace(e.transformed(Affine2.translate(delta * u[0], delta * u[1])))
        return
    u = (math.cos(d.angle), math.sin(d.angle)) if t == "linear" else _unit(sub(d.p2, d.p1))
    s = (d.p2[0] - d.p1[0]) * u[0] + (d.p2[1] - d.p1[1]) * u[1]
    if t == "linear" and s < 0:
        u, s = (-u[0], -u[1]), -s
    delta = value - s
    (h1, part1), (h2, part2) = refs[0], refs[1]
    if not h1 and not h2:
        raise EditError("This dimension is not attached to any object.")
    if h1 and h1 == h2:
        e = doc.get(h1)
        moving_part, sign = part2, 1.0
        if isinstance(e, Polyline):
            doc.replace(_stretch_polyline(e, u, d.p2, delta))
        else:
            p = point_of(e, moving_part)
            doc.replace(move_point(e, moving_part, (p[0] + sign * delta * u[0], p[1] + sign * delta * u[1])))
        return
    # two different objects: move the selected one (or the second), as a whole
    if selected and selected in (h1, h2):
        mover = selected
    else:
        mover = h2 or h1
    sign = 1.0 if mover == h2 else -1.0
    e = doc.get(mover)
    doc.replace(e.transformed(Affine2.translate(sign * delta * u[0], sign * delta * u[1])))


def format_value(doc: Document, target: EditableValue) -> str:
    from .units import format_angle, format_length
    if target.angular:
        return format_angle(math.degrees(target.value), doc.header.units)
    return format_length(target.value, doc.header.units)


def parse_value(doc: Document, target: EditableValue, text: str) -> float:
    from .units import parse_angle, parse_length
    try:
        if target.angular:
            return math.radians(parse_angle(text))
        return parse_length(text, doc.header.units)
    except ValueError as exc:
        raise EditError(str(exc)) from exc


__all__ = [
    "EditError",
    "EditableValue",
    "apply_value",
    "attached_dimensions",
    "dimension_text_center",
    "editable_values",
    "format_value",
    "parse_value",
]
