"""Editing commands: MOVE, COPY, ROTATE, SCALE, MIRROR, OFFSET, TRIM, EXTEND, FILLET, CHAMFER,
ARRAYRECT, ARRAYPOLAR, BREAK, BREAKATPOINT, JOIN, EXPLODE, STRETCH."""
from __future__ import annotations

import math
from dataclasses import replace

from ..core.edit import (
    Curve,
    EditError,
    break_at,
    break_between,
    chamfer_lines,
    explode,
    extend,
    fillet_curves,
    fillet_lines,
    fillet_polyline,
    join,
    offset,
    trim,
)
from ..core.geom2d import Seg
from ..core.geom2d.construct import intersect
from ..core.geom2d.transform import Affine2
from ..core.geom2d.vec import angle_of, dist, sub
from ..core.model import (
    Arc,
    ArrayEntity,
    BlockReference,
    Circle,
    Dimension,
    Ellipse,
    Entity,
    Leader,
    Line,
    MText,
    Point,
    Polyline,
    Spline,
    Text,
    Viewport,
)
from ..core.model.entities import AttributeDefinition
from .framework import (
    CommandContext,
    EmptyPick,
    GetAngle,
    GetDistance,
    GetEntity,
    GetNumber,
    GetPoint,
    GetSelection,
    Keyword,
    command,
    kw,
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
    moving = {e.handle for e in ents}
    old_to_new: dict[int, int] = {}
    arrays = []
    for e in ents:
        if isinstance(e, ArrayEntity):
            arrays.append(e)
            continue
        try:
            t = e.transformed(m)
        except NotImplementedError:
            continue
        if copy:
            old_to_new[e.handle] = ctx.doc.add(t.with_props(handle=0)).handle
        else:
            ctx.doc.replace(t)
        n += 1
    for e in arrays:
        with_src = e.sources <= moving
        t = e.transformed_with_sources(m) if with_src else e.transformed(m)
        if copy:
            if with_src:
                t = t.with_props(sources=frozenset(old_to_new.get(h, h) for h in e.sources))
            ctx.doc.add(t.with_props(handle=0))
        else:
            ctx.doc.replace(t)
        n += 1
    return n


def _apply_transform_old(ctx: CommandContext, ents: list[Entity], m: Affine2, copy: bool) -> int:
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
def _trim_at(ctx: CommandContext, e: Entity, pick) -> tuple | None:
    """Trim e at pick. Returns an undo record (removed entity, added handles) or None."""
    g = ctx.doc.geometry(e)
    try:
        result = trim(e, cutting_prims(ctx, e.handle, g.bbox), pick)
    except EditError as exc:
        ctx.echo(str(exc))
        return None
    ctx.doc.delete(e.handle)
    added = []
    if result is not None:
        for piece in result:
            added.append(ctx.doc.add(piece.with_props(handle=0)).handle)
    ctx.doc.flush()              # keep the spatial index current for the next pick in this command
    return (e, added)


def _extend_at(ctx: CommandContext, e: Entity, pick, quiet: bool = False) -> tuple | None:
    try:
        new = extend(e, cutting_prims(ctx, e.handle, _big_box(ctx)), pick)
    except EditError as exc:
        if not quiet:
            ctx.echo(str(exc))
        return None
    if new is None:
        if not quiet:
            ctx.echo("There's nothing in that direction to extend to.")
        return None
    ctx.doc.replace(new)
    ctx.doc.flush()
    return (e, [e.handle])


def fence_hits(ctx: CommandContext, fence: list) -> list[tuple[int, tuple]]:
    """(handle, point) for every place the fence crosses an editable, visible object, in fence order."""
    out = []
    for a, b in zip(fence, fence[1:]):
        seg = Seg(a, b)
        box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        found = []
        for h in ctx.index.query(box):
            e = ctx.doc.get(h)
            if e is None or not ctx.doc.is_visible(e) or ctx.doc.is_locked(e) or e.TYPE in ("hatch", "dimension"):
                continue
            for prim in ctx.doc.geometry(e).prims(snappable_only=True):
                for p in intersect(seg, prim):
                    found.append((dist(a, p), h, p))
        found.sort(key=lambda t: t[0])
        out.extend((h, p) for _, h, p in found)
    return out


def _crossing_fence(rect) -> list:
    x0, y0, x1, y1 = rect
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def _inside_rect(ctx, rect) -> list[tuple[int, tuple]]:
    """Objects entirely inside the box (nothing to cut them at): pick them at their midpoint."""
    out = []
    for h in ctx.index.select_window(rect, crossing=False):
        e = ctx.doc.get(h)
        if e is None or ctx.doc.is_locked(e) or e.TYPE in ("hatch", "dimension"):
            continue
        prims = ctx.doc.geometry(e).prims(snappable_only=True)
        if prims:
            out.append((h, prims[0].mid))
    return out


def _gather_points(ctx: CommandContext, mode: str, start):
    """Fence or crossing input starting at `start`. Yields requests; returns the pick list."""
    if mode == "Crossing":
        corner = yield GetPoint("Specify opposite corner", base=start, rubber="rect")
        rect = (min(start[0], corner[0]), min(start[1], corner[1]), max(start[0], corner[0]), max(start[1], corner[1]))
        return fence_hits(ctx, _crossing_fence(rect)) + _inside_rect(ctx, rect)
    pts = [start]
    while True:
        p = yield GetPoint("Specify next fence point (Enter to finish)", base=pts[-1], allow_none=True)
        if p is None:
            break
        pts.append(p)
    return fence_hits(ctx, pts) if len(pts) > 1 else []


def _apply_many(ctx: CommandContext, hits, extend_mode: bool, history: list) -> int:
    """Trim (or extend) every object at each hit point. Pieces created by earlier cuts are found again by
    looking up what is under each point now."""
    n = 0
    tol = max(1e-6, ctx.view.pick_tolerance() * 1e-3)
    for h, p in hits:
        e = ctx.doc.get(h)
        if e is None or ctx.doc.geometry(e).bbox is None or min(pr.distance_to(p) for pr in ctx.doc.geometry(e).prims()) > tol:
            e = next((x for x in ctx.index.near(p, tol) if not ctx.doc.is_locked(x) and x.TYPE not in ("hatch", "dimension")), None)
        if e is None:
            continue
        rec = _extend_at(ctx, e, p, quiet=True) if extend_mode else _trim_at(ctx, e, p)
        if rec is not None:
            history.append(rec)
            n += 1
    return n


def _undo_last(ctx: CommandContext, history: list) -> None:
    if not history:
        ctx.echo("Nothing to undo.")
        return
    removed, added = history.pop()
    for h in added:
        if ctx.doc.get(h):
            ctx.doc.delete(h)
    ctx.doc.add(removed)
    ctx.doc.flush()


def _trim_extend(ctx: CommandContext, extending: bool):
    """Shared loop: click to trim (extend); Shift-click does the other one; click empty space for a fence
    (or a crossing box when Crossing is chosen); Fence/Crossing keywords switch the empty-click mode."""
    history: list = []
    mode = ctx.memory.get("trim_mode", "Fence")
    verb, other = ("extend", "trim") if extending else ("trim", "extend")
    while True:
        r = yield GetEntity(f"Select object to {verb} or Shift-select to {other} (click empty space: {mode.lower()})",
                            keywords=kw("Fence", "Crossing", "Undo"), allow_none=True, empty_ok=True)
        if r is None:
            return
        if r == "Undo":
            _undo_last(ctx, history)
            continue
        if r in ("Fence", "Crossing"):
            mode = r
            ctx.memory["trim_mode"] = mode
            start = yield GetPoint(f"Specify first {'fence point' if mode == 'Fence' else 'corner'}")
            r = EmptyPick(start)
        do_extend = extending != bool(ctx.shift)
        if isinstance(r, EmptyPick):
            hits = yield from _gather_points(ctx, mode, r.point)
            n = _apply_many(ctx, hits, do_extend, history)
            if not n:
                ctx.echo("Nothing was crossed." if not hits else f"Nothing could be {'extended' if do_extend else 'trimmed'}.")
            continue
        e, pick = r
        if ctx.doc.is_locked(e):
            ctx.echo("That object is on a locked layer.")
            continue
        rec = _extend_at(ctx, e, pick) if do_extend else _trim_at(ctx, e, pick)
        if rec is not None:
            history.append(rec)
            if not do_extend and not rec[1]:
                ctx.echo("Nothing crosses it, so the whole object was removed.")


@command("TRIM", label="Trim", aliases=("TR",), group="Modify",
         description="Cut off the parts of objects that stick past other objects. Click a part to remove it, "
                     "or click empty space and drag a fence across several. Shift-click extends instead.",
         keywords=("cut", "clip", "remove part", "fence"))
def trim_cmd(ctx: CommandContext):
    yield from _trim_extend(ctx, extending=False)


@command("EXTEND", label="Extend", aliases=("EX",), group="Modify",
         description="Lengthen lines and arcs until they reach other objects. Click near the end to extend, "
                     "or draw a fence across several. Shift-click trims instead.",
         keywords=("lengthen", "stretch to", "reach", "fence"))
def extend_cmd(ctx: CommandContext):
    yield from _trim_extend(ctx, extending=True)


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
    dy = dx = 0.0
    if rows > 1:
        dy = yield GetDistance("Specify the distance between rows", default=h * 1.5 or 1.0,
                               default_text=ctx.fmt(h * 1.5 or 1.0), positive=False)
    if cols > 1:
        dx = yield GetDistance("Specify the distance between columns", default=w * 1.5 or 1.0,
                               default_text=ctx.fmt(w * 1.5 or 1.0), positive=False)
    ctx.doc.add(ArrayEntity(sources=frozenset(e.handle for e in ents), kind="rect", rows=rows, cols=cols,
                            row_vec=(0.0, dy), col_vec=(dx, 0.0)), use_current_props=True)
    ctx.echo(f"Array of {rows} rows x {cols} columns created. Edit the original objects and the copies follow; "
             "change rows, columns or spacing in Properties; EXPLODE makes the copies independent.")


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
    ctx.doc.add(ArrayEntity(sources=frozenset(e.handle for e in ents), kind="polar", center=center, count=n,
                            fill_angle=math.tau if full else fill, rotate_items=(rot != "No")),
                use_current_props=True)
    ctx.echo(f"{n} items around the center. Edit the original and every copy follows.")


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
        if isinstance(e, ArrayEntity):
            from ..core.model.geometry import explode_array
            for p in explode_array(ctx.doc, e):
                ctx.doc.add(p)
            ctx.doc.delete(e.handle)
            count += 1
            continue
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
    mv = lambda p: (p[0] + d[0], p[1] + d[1]) if _inside(p, rect) else p
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
