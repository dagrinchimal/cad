"""Parametric constraint commands (AutoCAD names: GC… geometric, DC… dimensional)."""
from __future__ import annotations

import math

from ..core.constraints import (
    Constraint, ConstraintError, ExpressionError, curve_ref, evaluate, nearest_point_ref, would_overconstrain,
)
from ..core.constraints.model import SUPPORTED, params_of, resolve_values
from ..core.geom2d.vec import dist
from ..core.model import Arc, Circle, Line
from .framework import CommandContext, GetDistance, GetEntity, GetPoint, GetSelection, GetString, command, kw


def _new_id(doc) -> int:
    return max(doc.constraints, default=0) + 1


def _new_name(doc, prefix: str) -> str:
    used = {c.name for c in doc.constraints.values()}
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def _check(e) -> bool:
    return isinstance(e, SUPPORTED)


def add_constraint(ctx: CommandContext, c: Constraint, keep_first: bool = True) -> bool:
    doc = ctx.doc
    if would_overconstrain(doc, c):
        ctx.echo("That constraint is already implied by the others (it would over-constrain the shape).")
        return False
    mgr = getattr(ctx, "constraints", None)
    if mgr is not None and keep_first and c.refs:
        mgr.prefer = {c.refs[0][0]: 1000.0}
    doc.set_item("constraint", c.id, c)
    return True


def _pick_point(ctx, prompt):
    while True:
        e, pick = yield GetEntity(prompt)
        if not _check(e):
            ctx.echo("Constraints work on lines, arcs, circles, polylines and points.")
            continue
        ref = nearest_point_ref(e, pick)
        if ref:
            return (e.handle, ref[0]), ref[1]


def _pick_curve(ctx, prompt, kinds=("line", "circle")):
    while True:
        e, pick = yield GetEntity(prompt)
        ref = curve_ref(e, pick) if _check(e) else None
        if ref is None or (ref.startswith("seg") and "line" not in kinds) or \
                (ref == "line" and "line" not in kinds) or (ref == "circle" and "circle" not in kinds):
            want = " or ".join("a line" if k == "line" else "an arc/circle" for k in kinds)
            ctx.echo(f"Pick {want}.")
            continue
        return (e.handle, ref), e


def _geo(name, label, desc, keywords=()):
    return command(name, label=label, description=desc, group="Parametric", keywords=keywords)


@_geo("GCCOINCIDENT", "Coincident", "Make two points meet (or put a point on a line or circle).",
      ("join points", "connect ends", "snap together"))
def gc_coincident(ctx: CommandContext):
    r1, _ = yield from _pick_point(ctx, "Select first point")
    r = yield GetEntity("Select second point, or a line/circle to put the point on", keywords=kw("Object"))
    if r == "Object":
        r2, _ = yield from _pick_curve(ctx, "Select line or circle")
    else:
        e, pick = r
        ref = nearest_point_ref(e, pick) if _check(e) else None
        if ref is None:
            ctx.echo("Pick a point of a line, arc, circle, polyline or point.")
            return
        r2 = (e.handle, ref[0])
    add_constraint(ctx, Constraint(_new_id(ctx.doc), "coincident", (r1, r2)))


def _two_curves(kind, label, desc, kinds=("line",), keywords=()):
    @_geo(f"GC{kind.upper()}", label, desc, keywords)
    def fn(ctx: CommandContext):
        r1, _ = yield from _pick_curve(ctx, "Select first object", kinds)
        r2, _ = yield from _pick_curve(ctx, "Select second object", kinds)
        if r1 == r2:
            ctx.echo("Pick two different objects.")
            return
        add_constraint(ctx, Constraint(_new_id(ctx.doc), kind, (r1, r2)))
    return fn


_two_curves("parallel", "Parallel", "Make two lines parallel.", keywords=("same direction",))
_two_curves("perpendicular", "Perpendicular", "Make two lines meet at 90 degrees.", keywords=("square", "90 degrees"))
_two_curves("collinear", "Collinear", "Put two lines on the same infinite line.", keywords=("in line", "aligned"))
_two_curves("concentric", "Concentric", "Give two circles or arcs the same center.", kinds=("circle",),
            keywords=("same center",))
_two_curves("equal", "Equal", "Make two lines the same length, or two circles the same size.",
            kinds=("line", "circle"), keywords=("same length", "same size"))


@_geo("GCTANGENT", "Tangent", "Make a line or circle touch a circle or arc smoothly.", ("touching", "smooth contact"))
def gc_tangent(ctx: CommandContext):
    r1, e1 = yield from _pick_curve(ctx, "Select first object")
    r2, e2 = yield from _pick_curve(ctx, "Select second object", ("circle",) if r1[1] != "circle" else ("line", "circle"))
    values = ()
    if r1[1] == "circle" and r2[1] == "circle":
        inside = dist(e1.center, e2.center) < max(e1.radius, e2.radius)
        values = (-1.0 if inside else 1.0,)
    add_constraint(ctx, Constraint(_new_id(ctx.doc), "tangent", (r1, r2), values=values))


def _hv(kind):
    @_geo(f"GC{kind.upper()}", kind.capitalize(),
          f"Make a line {'level (horizontal)' if kind == 'horizontal' else 'upright (vertical)'}, "
          f"or line up two points {'horizontally' if kind == 'horizontal' else 'vertically'}.",
          ("level", "flat") if kind == "horizontal" else ("plumb", "upright"))
    def fn(ctx: CommandContext):
        r = yield GetEntity("Select a line", keywords=kw("2Points"))
        if r == "2Points":
            r1, _ = yield from _pick_point(ctx, "Select first point")
            r2, _ = yield from _pick_point(ctx, "Select second point")
            refs = (r1, r2)
        else:
            e, pick = r
            ref = curve_ref(e, pick) if _check(e) else None
            if ref is None or ref == "circle":
                ctx.echo("Pick a line or a straight polyline segment.")
                return
            refs = ((e.handle, ref),)
        add_constraint(ctx, Constraint(_new_id(ctx.doc), kind, refs))
    return fn


_hv("horizontal")
_hv("vertical")


@_geo("GCFIX", "Fix", "Lock a point (or a whole object) in place.", ("lock", "anchor", "pin"))
def gc_fix(ctx: CommandContext):
    r = yield GetEntity("Select point to fix", keywords=kw("Object"))
    if r == "Object":
        e, _ = yield GetEntity("Select object to fix")
        if not _check(e):
            ctx.echo("That object can't be constrained.")
            return
        add_constraint(ctx, Constraint(_new_id(ctx.doc), "fix", ((e.handle, "all"),),
                                       values=tuple(float(v) for v in params_of(e))))
        return
    e, pick = r
    ref = nearest_point_ref(e, pick) if _check(e) else None
    if ref is None:
        ctx.echo("That object can't be constrained.")
        return
    add_constraint(ctx, Constraint(_new_id(ctx.doc), "fix", ((e.handle, ref[0]),), values=tuple(ref[1])))


@_geo("GCSYMMETRIC", "Symmetric", "Make two points mirror each other across a line.", ("mirror", "balanced"))
def gc_symmetric(ctx: CommandContext):
    r1, _ = yield from _pick_point(ctx, "Select first point")
    r2, _ = yield from _pick_point(ctx, "Select second point")
    r3, _ = yield from _pick_curve(ctx, "Select symmetry line", ("line",))
    add_constraint(ctx, Constraint(_new_id(ctx.doc), "symmetric", (r1, r2, r3)), keep_first=False)


# ------------------------------------------------------------------ dimensional
def _value_prompt(ctx: CommandContext, current: float, angle: bool = False):
    shown = f"{current:.6g}" if angle else ctx.fmt(current)
    t = yield GetString(f"Enter value or expression (e.g. {'45' if angle else '25'} or d1*2)", default=shown,
                        default_text=shown)
    return t


def _to_expression(ctx: CommandContext, text: str, angle: bool) -> str:
    """Keep plain numbers in mm (unit-aware typing); keep expressions as written."""
    from ..core.units import parse_length, try_parse_length
    names = resolve_values(ctx.doc.constraints)
    if angle:
        evaluate(text.replace("°", ""), names)
        return text.replace("°", "")
    mm = try_parse_length(text, ctx.units)
    if mm is not None:
        return f"{mm:.12g}"
    evaluate(text, names)
    _ = parse_length
    return text


def _add_dim(ctx: CommandContext, kind, refs, prefix, current, values=(), angle=False):
    text = yield from _value_prompt(ctx, current, angle)
    try:
        expr = _to_expression(ctx, text, angle)
    except (ExpressionError, ValueError) as exc:
        ctx.echo(f"Invalid value: {exc}")
        return
    c = Constraint(_new_id(ctx.doc), kind, refs, name=_new_name(ctx.doc, prefix), expression=expr, values=values)
    if add_constraint(ctx, c):
        ctx.echo(f"{c.name} = {expr}")


@command("DCLINEAR", label="Linear Constraint", aliases=("DCL",), group="Parametric",
         description="Lock the horizontal or vertical distance between two points.",
         keywords=("driving dimension", "parametric dimension"))
def dc_linear(ctx: CommandContext):
    r1, p1 = yield from _pick_point(ctx, "Select first point")
    r2, p2 = yield from _pick_point(ctx, "Select second point")
    loc = yield GetPoint("Specify where the dimension goes (above/below = horizontal, beside = vertical)", base=p2)
    lo_y, hi_y = sorted((p1[1], p2[1]))
    horizontal = loc[1] > hi_y or loc[1] < lo_y
    if horizontal:
        sign = 1.0 if p2[0] >= p1[0] else -1.0
        yield from _add_dim(ctx, "dim_horizontal", (r1, r2), "d", abs(p2[0] - p1[0]), (sign,))
    else:
        sign = 1.0 if p2[1] >= p1[1] else -1.0
        yield from _add_dim(ctx, "dim_vertical", (r1, r2), "d", abs(p2[1] - p1[1]), (sign,))


@command("DCALIGNED", label="Aligned Constraint", aliases=("DCA",), group="Parametric",
         description="Lock the true distance between two points.", keywords=("driving distance",))
def dc_aligned(ctx: CommandContext):
    r1, p1 = yield from _pick_point(ctx, "Select first point")
    r2, p2 = yield from _pick_point(ctx, "Select second point")
    yield from _add_dim(ctx, "distance", (r1, r2), "d", dist(p1, p2))


@command("DCRADIUS", label="Radius Constraint", aliases=("DCR",), group="Parametric",
         description="Lock the radius of a circle or arc.", keywords=("driving radius",))
def dc_radius(ctx: CommandContext):
    r, e = yield from _pick_curve(ctx, "Select arc or circle", ("circle",))
    yield from _add_dim(ctx, "radius", (r,), "rad", e.radius)


@command("DCDIAMETER", label="Diameter Constraint", aliases=("DCD",), group="Parametric",
         description="Lock the diameter of a circle or arc.", keywords=("driving diameter",))
def dc_diameter(ctx: CommandContext):
    r, e = yield from _pick_curve(ctx, "Select arc or circle", ("circle",))
    yield from _add_dim(ctx, "diameter", (r,), "dia", e.radius * 2)


@command("DCANGULAR", label="Angular Constraint", aliases=("DCAN",), group="Parametric",
         description="Lock the angle between two lines (in degrees).", keywords=("driving angle",))
def dc_angular(ctx: CommandContext):
    r1, e1 = yield from _pick_curve(ctx, "Select first line", ("line",))
    r2, e2 = yield from _pick_curve(ctx, "Select second line", ("line",))
    from ..core.constraints.model import GeomView
    ents = {e1.handle: e1, e2.handle: e2}
    import numpy as np
    offs, xs, o = {}, [], 0
    for h, e in ents.items():
        offs[h] = o
        p = params_of(e)
        xs.append(p)
        o += len(p)
    g = GeomView(ents, offs, np.concatenate(xs))
    (a, b), (p, q) = g.line(r1), g.line(r2)
    d1, d2 = (b[0] - a[0], b[1] - a[1]), (q[0] - p[0], q[1] - p[1])
    ang = math.degrees(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1]))
    sign = 1.0 if ang >= 0 else -1.0
    yield from _add_dim(ctx, "angle", (r1, r2), "ang", abs(ang), (sign,), angle=True)


@command("DELCONSTRAINT", label="Delete Constraints", aliases=("DELCON",), group="Parametric",
         description="Remove all constraints from the selected objects.", keywords=("unlock", "free"))
def del_constraint(ctx: CommandContext):
    sel = set((yield GetSelection("Select objects")) or ())
    gone = [cid for cid, c in ctx.doc.constraints.items() if c.handles & sel]
    for cid in gone:
        ctx.doc.remove_item("constraint", cid)
    ctx.echo(f"{len(gone)} constraint(s) removed.")


@command("CONSTRAINTSTATUS", label="Constraint Status", aliases=("CSTATUS",), group="Parametric",
         transaction=False, description="Show how many ways a constrained shape can still move.",
         keywords=("degrees of freedom", "fully constrained"))
def constraint_status(ctx: CommandContext):
    from ..core.constraints import solve_for
    e, _ = yield GetEntity("Select a constrained object")
    try:
        res = solve_for(ctx.doc, {e.handle})
    except ConstraintError as exc:
        ctx.echo(str(exc))
        return
    if res is None:
        ctx.echo("That object has no constraints.")
    elif res.dof == 0:
        ctx.echo("Fully constrained: nothing can move.")
    else:
        ctx.echo(f"{res.dof} degree(s) of freedom left (ways it can still move, slide, turn or resize).")


_ = (Arc, Circle, Line, GetDistance)
