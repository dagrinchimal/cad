"""Editing commands: MOVE, COPY, ROTATE, SCALE, MIRROR, OFFSET, TRIM, EXTEND, FILLET, CHAMFER,
ARRAYRECT, ARRAYPOLAR, BREAK, BREAKATPOINT, JOIN, EXPLODE, STRETCH."""
from __future__ import annotations

import math
from dataclasses import replace

from ..core.edit import (
    Curve, EditError, break_at, break_between, chamfer_lines, explode, extend, fillet_curves, fillet_lines,
    fillet_polyline, join, offset, trim,
)
from ..core.geom2d import Seg
from ..core.geom2d.transform import Affine2
from ..core.geom2d.vec import angle_of, dist, sub
from ..core.model import (
    Arc, BlockReference, Circle, Dimension, Ellipse, Entity, Leader, Line, MText, Point, Polyline, Spline, Text,
    Viewport,
)
from ..core.model.entities import AttributeDefinition
from .framework import (
    CommandContext, GetAngle, GetDistance, GetEntity, GetNumber, GetPoint, GetSelection, Keyword, command, kw,
)

PREVIEW_LIMIT = 300


# ------------------------------------------------------------------ helpers
def editable(ctx: CommandContext, handles) -> list[Entity]:
    out, locked = [], 0
    for h in handles or ():
        e = ctx.doc.get(h)
        if e is None:
            continue
        if ctx.doc.is_locked(e):
            locked += 1
            continue
        out.append(e)
    if locked:
        ctx.echo(f"{locked} object(s) on locked layers were left alone.")
    return out


def transformed_preview(ents: list[Entity], make):
    shown = ents[:PREVIEW_LIMIT]

    def fn(c):
        m = make(c)
        if m is None:
            return []
        out = []
        for e in shown:
            try:
                out.append(e.transformed(m).with_props(handle=0))
            except NotImplementedError:
                pass
        return out
    return fn


def apply_transform(ctx: CommandContext, ents: list[Entity], m: Affine2, copy: bool) -> int:
    n = 0
    for e in ents:
        try:
            t = e.transformed(m)
        except NotImplementedError:
            continue
        if copy:
            ctx.doc.add(t.with_props(handle=0))
        else:
            ctx.doc.replace(t)
        n += 1
    return n


def cutting_prims(ctx: CommandContext, exclude: int, around) -> list:
    """Snappable geometry of visible objects whose boxes touch `around` (a bbox)."""
    out = []
    for h in ctx.index.query(around):
        if h == exclude:
            continue
        e = ctx.doc.get(h)
        if e is None or not ctx.doc.is_visible(e) or e.TYPE in ("hatch",):
            continue
        out.extend(ctx.doc.geometry(e).prims(snappable_only=True))
    return out


def _big_box(ctx: CommandContext):
    ext = ctx.index.extents()
    vis = ctx.view.visible_rect()
    boxes = [b for b in (ext, vis) if b]
    if not boxes:
        return (-1e12, -1e12, 1e12, 1e12)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def select(ctx, prompt="Select objects"):
    return GetSelection(prompt)


# ------------------------------------------------------------------ move / copy
@command("MOVE", label="Move", aliases=("M",), group="Modify",
         description="Move objects by a distance and direction.", keywords=("shift", "relocate", "drag"))
def move_cmd(ctx: CommandContext):
    ents = editable(ctx, (yield select(ctx)))
    if not ents:
        return
    base = yield GetPoint("Specify base point", keywords=kw("Displacement"), rubber=None)
    if base == "Displacement":
        d = yield GetPoint("Specify displacement (as x,y)", rubber=None)
        m = Affine2.translate(*d)
    else:
        p2 = yield GetPoint("Specify second point (or press Enter to use the first point as displacement)",
                            base=base, allow_none=True,
                            preview=transformed_preview(ents, lambda c: Affine2.translate(c[0] - base[0], c[1] - base[1])))
        m = Affine2.translate(*base) if p2 is None else Affine2.translate(p2[0] - base[0], p2[1] - base[1])
    n = apply_transform(ctx, ents, m, copy=False)
    ctx.echo(f"{n} object(s) moved.")


@command("COPY", label="Copy", aliases=("CO", "CP"), group="Modify",
         description="Make copies of objects at new locations. Keep clicking to place more copies.",
         keywords=("duplicate", "clone"))
def copy_cmd(ctx: CommandContext):
    ents = editable(ctx, (yield select(ctx)))
    if not ents:
        return
    base = yield GetPoint("Specify base point", rubber=None)
    count = 0
    while True:
        p2 = yield GetPoint("Specify second point", base=base, allow_none=True, keywords=(Keyword("Exit"),),
                            preview=transformed_preview(ents, lambda c: Affine2.translate(c[0] - base[0], c[1] - base[1])))
        if p2 is None or p2 == "Exit":
            break
        apply_transform(ctx, ents, Affine2.translate(p2[0] - base[0], p2[1] - base[1]), copy=True)
        count += 1
    ctx.echo(f"{count} cop{'y' if count == 1 else 'ies'} made.")


# ------------------------------------------------------------------ rotate / scale / mirror
@command("ROTATE", label="Rotate", aliases=("RO",), group="Modify",
         description="Turn objects around a base point.", keywords=("turn", "spin", "angle"))
def rotate_cmd(ctx: CommandContext):
    ents = editable(ctx, (yield select(ctx)))
    if not ents:
        return
    base = yield GetPoint("Specify base point", rubber=None)
    copy = False
    last = ctx.memory.get("rotate_angle", 0.0)
    while True:
        r = yield GetAngle("Specify rotation angle", base=base, keywords=kw("Copy", "Reference"), default=last,
                           default_text=f"{math.degrees(last):g}",
                           preview=transformed_preview(ents, lambda c: Affine2.rotate(angle_of(sub(c, base)), base)
                                                       if dist(c, base) > 0 else None))
        if r == "Copy":
            copy = True
            ctx.echo("Rotating a copy.")
            continue
        if r == "Reference":
            ref = yield GetAngle("Specify the reference angle", base=base, default=0.0, default_text="0")
            new = yield GetAngle("Specify the new angle", base=base,
                                 preview=transformed_preview(ents, lambda c: Affine2.rotate(angle_of(sub(c, base)) - ref, base)
                                                             if dist(c, base) > 0 else None))
            r = new - ref
        break
    ctx.memory["rotate_angle"] = r
    apply_transform(ctx, ents, Affine2.rotate(r, base), copy)


@command("SCALE", label="Scale", aliases=("SC",), group="Modify",
         description="Make objects bigger or smaller around a base point.", keywords=("resize", "enlarge", "shrink"))
def scale_cmd(ctx: CommandContext):
    ents = editable(ctx, (yield select(ctx)))
    if not ents:
        return
    base = yield GetPoint("Specify base point", rubber=None)
    copy = False
    while True:
        f = yield GetNumber("Specify scale factor", base=base, keywords=kw("Copy", "Reference"), minimum=1e-12,
                            preview=transformed_preview(ents, lambda c: Affine2.scale(dist(c, base), center=base)
                                                        if dist(c, base) > 0 else None))
        if f == "Copy":
            copy = True
            continue
        if f == "Reference":
            ref = yield GetDistance("Specify reference length", base=base, default=1.0, default_text=ctx.fmt(1.0))
            new = yield GetDistance("Specify new length", base=base)
            f = new / ref
        break
    if f <= 0:
        ctx.echo("The scale factor must be greater than zero.")
        return
    apply_transform(ctx, ents, Affine2.scale(f, center=base), copy)


@command("MIRROR", label="Mirror", aliases=("MI",), group="Modify",
         description="Make a mirror image of objects across a line.", keywords=("flip", "reflect", "symmetry"))
def mirror_cmd(ctx: CommandContext):
    ents = editable(ctx, (yield select(ctx)))
    if not ents:
        return
    p1 = yield GetPoint("Specify first point of mirror line", rubber=None)
    p2 = yield GetPoint("Specify second point of mirror line", base=p1,
                        preview=transformed_preview(ents, lambda c: Affine2.mirror(p1, c) if dist(c, p1) > 0 else None))
    if dist(p1, p2) <= 0:
        ctx.echo("The mirror line needs two different points.")
        return
    erase = yield GetPoint("Erase source objects?", keywords=kw("Yes", "No"), default="No", default_text="No",
                           rubber=None)
    apply_transform(ctx, ents, Affine2.mirror(p1, p2), copy=(erase != "Yes"))


# ------------------------------------------------------------------ offset
@command("OFFSET", label="Offset", aliases=("O",), group="Modify",
         description="Make a parallel copy of a line, arc, circle or polyline at a set distance.",
         keywords=("parallel", "inset", "outset", "wall thickness"))
def offset_cmd(ctx: CommandContext):
    last = ctx.memory.get("offset_distance")
    d = yield GetDistance("Specify offset distance", keywords=kw("Through"), default=last,
                          default_text=ctx.fmt(last) if last else "")
    through = d == "Through"
    if not through:
        ctx.memory["offset_distance"] = d
    while True:
        r = yield GetEntity("Select object to offset", keywords=kw("Exit"), allow_none=True)
        if r is None or r == "Exit":
            return
        e, _ = r
        if ctx.doc.is_locked(e):
            ctx.echo("That object is on a locked layer.")
            continue
        try:
            if through:
                p = yield GetPoint("Specify through point", rubber=None,
                                   preview=lambda c: _safe([offset(e, ctx.doc.geometry(e).distance_to(c), c)]))
                new = offset(e, ctx.doc.geometry(e).distance_to(p), p)
            else:
                p = yield GetPoint("Specify point on side to offset", rubber=None,
                                   preview=lambda c: _safe([offset(e, d, c)]))
                new = offset(e, d, p)
        except EditError as exc:
            ctx.echo(str(exc))
            continue
        if new is not None:
            ctx.doc.add(new.with_props(handle=0, layer=e.layer, space=e.space))


def _safe(items):
    return [x for x in items if x is not None]


# ------------------------------------------------------------------ trim / extend
@command("TRIM", label="Trim", aliases=("TR",), group="Modify",
         description="Cut off the part of an object that sticks past other objects. Click the part to remove.",
         keywords=("cut", "clip", "remove part"))
def trim_cmd(ctx: CommandContext):
    history = []
    while True:
        r = yield GetEntity("Select object to trim", keywords=kw("Undo"), allow_none=True)
        if r is None:
            return
        if r == "Undo":
            if not history:
                ctx.echo("Nothing to undo.")
                continue
            removed, added = history.pop()
            for h in added:
                if ctx.doc.get(h):
                    ctx.doc.delete(h)
            ctx.doc.add(removed)
            continue
        e, pick = r
        if ctx.doc.is_locked(e):
            ctx.echo("That object is on a locked layer.")
            continue
        g = ctx.doc.geometry(e)
        try:
            result = trim(e, cutting_prims(ctx, e.handle, g.bbox), pick)
        except EditError as exc:
            ctx.echo(str(exc))
            continue
        ctx.doc.delete(e.handle)
        added = []
        if result is None:
            ctx.echo("Nothing crosses it, so the whole object was removed.")
        else:
            for piece in result:
                added.append(ctx.doc.add(piece.with_props(handle=0)).handle)
        history.append((e, added))


@command("EXTEND", label="Extend", aliases=("EX",), group="Modify",
         description="Lengthen a line or arc until it reaches another object. Click near the end to extend.",
         keywords=("lengthen", "stretch to", "reach"))
def extend_cmd(ctx: CommandContext):
    while True:
        r = yield GetEntity("Select object to extend", allow_none=True)
        if r is None:
            return
        e, pick = r
        if ctx.doc.is_locked(e):
            ctx.echo("That object is on a locked layer.")
            continue
        try:
            new = extend(e, cutting_prims(ctx, e.handle, _big_box(ctx)), pick)
        except EditError as exc:
            ctx.echo(str(exc))
            continue
        if new is None:
            ctx.echo("There's nothing in that direction to extend to.")
            continue
        ctx.doc.replace(new)


# ------------------------------------------------------------------ fillet / chamfer
def _which_segment(pl: Polyline, pick) -> int:
    prims = pl.primitives()
    return min(range(len(prims)), key=lambda i: prims[i].distance_to(pick))


@command("FILLET", label="Fillet", aliases=("F",), group="Modify",
         description="Round the corner between two objects with an arc (radius 0 makes a sharp corner).",
         keywords=("round corner", "radius corner", "blend"))
def fillet_cmd(ctx: CommandContext):
    radius = ctx.memory.get("fillet_radius", 0.0)
    while True:
        r = yield GetEntity(f"Select first object (radius {ctx.fmt(radius)})", keywords=kw("Radius", "Polyline"))
        if r == "Radius":
            radius = yield GetDistance("Specify fillet radius", default=radius, default_text=ctx.fmt(radius),
                                       positive=False)
            ctx.memory["fillet_radius"] = radius
            continue
        if r == "Polyline":
            r2 = yield GetEntity("Select polyline")
            pl = r2[0]
            if not isinstance(pl, Polyline):
                ctx.echo("That isn't a polyline.")
                return
            ctx.doc.replace(fillet_polyline(pl, radius))
            return
        break
    e1, p1 = r
    e2, p2 = yield GetEntity("Select second object")
    try:
        if e1.handle == e2.handle and isinstance(e1, Polyline):
            i, j = _which_segment(e1, p1), _which_segment(e1, p2)
            n = len(e1.vertices)
            if abs(i - j) == 1 or (e1.closed and abs(i - j) == n - 1):
                vertex = max(i, j) if abs(i - j) == 1 else 0
                ctx.doc.replace(fillet_polyline(e1, radius, only_vertex=vertex))
                return
            raise EditError("Pick two neighbouring segments of the polyline")
        if isinstance(e1, Line) and isinstance(e2, Line):
            a, b, arc = fillet_lines(e1, p1, e2, p2, radius)
        elif isinstance(e1, (Line, Arc, Circle)) and isinstance(e2, (Line, Arc, Circle)):
            a, b, arc = fillet_curves(e1, p1, e2, p2, radius)
        else:
            raise EditError("Fillet works on lines, arcs, circles and polylines")
    except EditError as exc:
        ctx.echo(str(exc))
        return
    for orig, new in ((e1, a), (e2, b)):
        if ctx.doc.is_locked(orig):
            continue
        ctx.doc.replace(new)
    if arc is not None:
        ctx.doc.add(arc.with_props(handle=0), use_current_props=False)


@command("CHAMFER", label="Chamfer", aliases=("CHA",), group="Modify",
         description="Cut a corner between two lines with a straight bevel.", keywords=("bevel", "angled corner"))
def chamfer_cmd(ctx: CommandContext):
    d1 = ctx.memory.get("chamfer_d1", 0.0)
    d2 = ctx.memory.get("chamfer_d2", 0.0)
    while True:
        r = yield GetEntity(f"Select first line (distances {ctx.fmt(d1)}, {ctx.fmt(d2)})", keywords=kw("Distance"))
        if r == "Distance":
            d1 = yield GetDistance("Specify first chamfer distance", default=d1, default_text=ctx.fmt(d1),
                                   positive=False)
            d2 = yield GetDistance("Specify second chamfer distance", default=d1, default_text=ctx.fmt(d1),
                                   positive=False)
            ctx.memory["chamfer_d1"], ctx.memory["chamfer_d2"] = d1, d2
            continue
        break
    e1, p1 = r
    e2, p2 = yield GetEntity("Select second line")
    if not (isinstance(e1, Line) and isinstance(e2, Line)):
        ctx.echo("Chamfer works on two lines.")
        return
    try:
        a, b, ch = chamfer_lines(e1, p1, e2, p2, d1, d2)
    except EditError as exc:
        ctx.echo(str(exc))
        return
    ctx.doc.replace(a)
    ctx.doc.replace(b)
    if ch is not None:
        ctx.doc.add(ch.with_props(handle=0))


# ------------------------------------------------------------------ arrays
@command("ARRAYRECT", label="Rectangular Array", aliases=("AR", "ARRAY"), group="Modify",
         description="Copy objects into rows and columns.", keywords=("grid copy", "rows columns", "pattern copy"))
def arrayrect_cmd(ctx: CommandContext):
    ents = editable(ctx, (yield select(ctx)))
    if not ents:
        return
    rows = int((yield GetNumber("Enter the number of rows", integer=True, minimum=1, default=3, default_text="3")))
    cols = int((yield GetNumber("Enter the number of columns", integer=True, minimum=1, default=4, default_text="4")))
    if rows * cols * len(ents) > 200_000:
        ctx.echo("That would make too many copies (over 200,000).")
        return
    b = [ctx.doc.geometry(e).bbox for e in ents]
    w = max(x[2] for x in b if x) - min(x[0] for x in b if x)
    h = max(x[3] for x in b if x) - min(x[1] for x in b if x)
    dy = yield GetDistance("Specify the distance between rows", default=h * 1.5 or 1.0,
                           default_text=ctx.fmt(h * 1.5 or 1.0), positive=False) if rows > 1 else 0.0
    dx = yield GetDistance("Specify the distance between columns", default=w * 1.5 or 1.0,
                           default_text=ctx.fmt(w * 1.5 or 1.0), positive=False) if cols > 1 else 0.0
    n = 0
    for i in range(rows):
        for j in range(cols):
            if i == 0 and j == 0:
                continue
            n += apply_transform(ctx, ents, Affine2.translate(j * dx, i * dy), copy=True)
    ctx.echo(f"{n} copies made ({rows} rows x {cols} columns).")


@command("ARRAYPOLAR", label="Polar Array", aliases=("ARP",), group="Modify",
         description="Copy objects around a center point, like spokes or bolt holes.",
         keywords=("copy in a circle", "circular array", "radial copy", "bolt circle", "around a center"))
def arraypolar_cmd(ctx: CommandContext):
    ents = editable(ctx, (yield select(ctx)))
    if not ents:
        return
    center = yield GetPoint("Specify center point of array", rubber=None)
    n = int((yield GetNumber("Enter the number of items", integer=True, minimum=2, default=6, default_text="6")))
    if n * len(ents) > 200_000:
        ctx.echo("That would make too many copies.")
        return
    fill = yield GetAngle("Specify the angle to fill", base=center, default=math.tau, default_text="360")
    rot = yield GetPoint("Rotate items as they are copied?", keywords=kw("Yes", "No"), default="Yes",
                         default_text="Yes", rubber=None)
    full = abs(abs(fill) - math.tau) < 1e-9 or abs(fill) < 1e-12
    step = (math.tau if full else fill) / (n if full else n - 1)
    for k in range(1, n):
        ang = step * k
        if rot == "No":
            ref = ctx.doc.geometry(ents[0]).bbox
            c0 = ((ref[0] + ref[2]) / 2, (ref[1] + ref[3]) / 2)
            c1 = Affine2.rotate(ang, center).apply(c0)
            m = Affine2.translate(c1[0] - c0[0], c1[1] - c0[1])
        else:
            m = Affine2.rotate(ang, center)
        apply_transform(ctx, ents, m, copy=True)
    ctx.echo(f"{n} items around the center.")


# ------------------------------------------------------------------ break / join / explode
@command("BREAK", label="Break", aliases=("BR",), group="Modify",
         description="Remove a piece of an object between two points.", keywords=("gap", "split", "cut out"))
def break_cmd(ctx: CommandContext):
    e, p1 = yield GetEntity("Select object (the click is the first break point)")
    r = yield GetPoint("Specify second break point", keywords=kw("First point"), rubber=None)
    if r == "First point":
        p1 = yield GetPoint("Specify first break point", rubber=None)
        r = yield GetPoint("Specify second break point", rubber=None)
    try:
        pieces = break_between(e, p1, r)
    except EditError as exc:
        ctx.echo(str(exc))
        return
    ctx.doc.delete(e.handle)
    for p in pieces:
        ctx.doc.add(p.with_props(handle=0))


@command("BREAKATPOINT", label="Break at Point", aliases=("BAP",), group="Modify",
         description="Split an object into two at one point.", keywords=("split", "divide"))
def break_at_point_cmd(ctx: CommandContext):
    e, _ = yield GetEntity("Select object")
    p = yield GetPoint("Specify break point", rubber=None)
    try:
        pieces = break_at(e, p)
    except EditError as exc:
        ctx.echo(str(exc))
        return
    ctx.doc.delete(e.handle)
    for piece in pieces:
        ctx.doc.add(piece.with_props(handle=0))


@command("JOIN", label="Join", aliases=("J",), group="Modify",
         description="Join touching lines, arcs and polylines into one object.", keywords=("merge", "connect", "weld"))
def join_cmd(ctx: CommandContext):
    ents = editable(ctx, (yield select(ctx, "Select objects to join")))
    if len(ents) < 2:
        ctx.echo("Select at least two objects.")
        return
    tol = max(ctx.view.pick_tolerance() * 0.05, 1e-6)
    result = join(ents, tol)
    if len(result) >= len(ents):
        ctx.echo("Those objects don't touch end to end, so nothing was joined.")
        return
    for e in ents:
        ctx.doc.delete(e.handle)
    for r in result:
        ctx.doc.add(r.with_props(handle=0))
    ctx.echo(f"{len(ents)} objects joined into {len(result)}.")


@command("EXPLODE", label="Explode", aliases=("X",), group="Modify",
         description="Break a polyline, block, dimension or hatch into its simple parts.",
         keywords=("ungroup parts", "decompose", "break apart"))
def explode_cmd(ctx: CommandContext):
    ents = editable(ctx, (yield select(ctx, "Select objects to explode")))
    count = 0
    for e in ents:
        parts = explode(ctx.doc, e)
        if parts is None:
            continue
        ctx.doc.delete(e.handle)
        for p in parts:
            layer = p.layer if p.layer in ctx.doc.layers else e.layer
            ctx.doc.add(p.with_props(handle=0, layer=layer, space=e.space))
        count += 1
    ctx.echo(f"{count} object(s) exploded." if count else "Nothing in the selection can be exploded.")


# ------------------------------------------------------------------ stretch
def _inside(p, rect) -> bool:
    return rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]


def stretch_entity(e: Entity, rect, d) -> Entity | None:
    mv = lambda p: (p[0] + d[0], p[1] + d[1]) if _inside(p, rect) else p   # noqa: E731
    if isinstance(e, Line):
        return replace(e, p1=mv(e.p1), p2=mv(e.p2))
    if isinstance(e, Polyline):
        return replace(e, vertices=tuple((*mv(v[:2]), v[2]) for v in e.vertices))
    if isinstance(e, Spline) and e.fit_points:
        pts = [mv(p) for p in e.fit_points]
        return Spline.through(pts, closed=e.closed, handle=e.handle, layer=e.layer, color=e.color,
                              linetype=e.linetype, lineweight=e.lineweight, space=e.space)
    if isinstance(e, Dimension):
        return replace(e, p1=mv(e.p1), p2=mv(e.p2), p3=mv(e.p3), location=mv(e.location))
    if isinstance(e, Leader):
        return replace(e, points=tuple(mv(p) for p in e.points))
    if isinstance(e, Arc):
        s, t = e.endpoints()
        if _inside(s, rect) and _inside(t, rect):
            return e.transformed(Affine2.translate(*d))
        return None
    key = {Circle: "center", Ellipse: "center", Text: "insert", MText: "insert", BlockReference: "insert",
           Point: "position", AttributeDefinition: "insert", Viewport: "center"}.get(type(e))
    if key and _inside(getattr(e, key), rect):
        return e.transformed(Affine2.translate(*d))
    return None


@command("STRETCH", label="Stretch", aliases=("S",), group="Modify",
         description="Stretch objects: points inside a crossing window move, the rest stays put.",
         keywords=("lengthen", "widen", "drag corners"))
def stretch_cmd(ctx: CommandContext):
    ctx.memory.pop("last_window", None)
    sel = yield GetSelection("Select objects to stretch with a crossing window (drag right-to-left)",
                             use_pickfirst=False)
    ents = editable(ctx, sel)
    if not ents:
        return
    win = ctx.memory.get("last_window")
    base = yield GetPoint("Specify base point", rubber=None)

    def make_preview(c):
        d = (c[0] - base[0], c[1] - base[1])
        out = []
        for e in ents[:PREVIEW_LIMIT]:
            s = stretch_entity(e, win, d) if win else e.transformed(Affine2.translate(*d))
            if s is not None:
                out.append(s.with_props(handle=0))
        return out
    p2 = yield GetPoint("Specify second point", base=base, preview=make_preview)
    d = (p2[0] - base[0], p2[1] - base[1])
    n = 0
    for e in ents:
        s = stretch_entity(e, win, d) if win else e.transformed(Affine2.translate(*d))
        if s is not None and s != e:
            ctx.doc.replace(s)
            n += 1
    ctx.echo(f"{n} object(s) stretched.")


_ = (Curve, Seg)
