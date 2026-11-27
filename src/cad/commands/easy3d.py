"""Beginner-friendly 3D (the Tinkercad way): drop ready-made shapes, turn shapes into holes, combine, align."""
from __future__ import annotations

import numpy as np

from ..core import solids as S
from ..core.geom2d.transform import Affine2
from ..core.model import MODEL_SPACE, Solid
from ..core.units import UnitMode, format_length
from .framework import CommandContext, GetKeyword, GetPoint, GetSelection, Keyword, command, kw
from .solids3d import ALL_GROUP, ask_solids, new_solid, replace_shape

SHAPES = ("Box", "Cylinder", "Sphere", "Cone", "Torus", "Wedge")
SHAPE_KEYS = {"Box": "B", "Cylinder": "CY", "Sphere": "S", "Cone": "CO", "Torus": "T", "Wedge": "W"}


def _shape_keywords():
    return tuple(Keyword(n, SHAPE_KEYS[n]) for n in SHAPES)
HOLE_COLOR = 8


def default_size(ctx: CommandContext) -> float:
    """20 mm, or 1 inch in inch drawings: a size you can see and then stretch."""
    return 20.0 if ctx.units.mode is UnitMode.MM else 25.4


def shape_at(kind: str, at, size):
    """A ready-made shape sitting on `at` (x, y, z): `size` across, or (width, depth, height)."""
    if isinstance(size, (tuple, list)):
        w, dp, h = (float(v) for v in size)
        x, y, z = at
        round_xy = abs(w - dp) < 1e-9
        if kind == "Box":                                     # exact shapes where possible
            return S.box((x - w / 2, y - dp / 2, z), (x + w / 2, y + dp / 2, z + h))
        if kind == "Cylinder" and round_xy:
            return S.cylinder((x, y, z), w / 2, h)
        if kind == "Cone" and round_xy:
            return S.cone((x, y, z), w / 2, 0.0, h)
        if kind == "Sphere" and round_xy and abs(w - h) < 1e-9:
            return S.sphere((x, y, z + h / 2), w / 2)
        if kind == "Wedge":
            return S.wedge((x - w / 2, y - dp / 2, z), w, dp, h)
        base = shape_at(kind, (0.0, 0.0, 0.0), 1.0)
        x0, y0, z0, x1, y1, z1 = S.bbox3(base)
        shp = S.scaled(base, (w / (x1 - x0), dp / (y1 - y0), h / (z1 - z0)), (0.0, 0.0, 0.0))
        bx0, by0, bz0, bx1, by1, _ = S.bbox3(shp)
        return S.translate(shp, (at[0] - (bx0 + bx1) / 2, at[1] - (by0 + by1) / 2, at[2] - bz0))
    x, y, z = at
    r = size / 2
    if kind == "Box":
        return S.box((x - r, y - r, z), (x + r, y + r, z + size))
    if kind == "Cylinder":
        return S.cylinder((x, y, z), r, size)
    if kind == "Sphere":
        return S.sphere((x, y, z + r), r)
    if kind == "Cone":
        return S.cone((x, y, z), r, 0.0, size)
    if kind == "Torus":
        return S.torus((x, y, z + size * 0.15), r - size * 0.15, size * 0.15)
    if kind == "Wedge":
        return S.wedge((x - r, y - r, z), size, size, size)
    raise S.SolidError(f"Unknown shape {kind}")


def drop_shape(ctx: CommandContext, kind: str, at, hole: bool = False, size=None) -> Solid:
    shape = shape_at(kind, at, size or default_size(ctx))
    e = new_solid(ctx, shape)
    if hole:
        e = ctx.doc.replace(e.with_props(hole=True, color=HOLE_COLOR, name=f"{kind} hole"))
    else:
        e = ctx.doc.replace(e.with_props(name=kind))
    return e


@command("DROPSHAPE", label="Add Shape", aliases=("SHAPE",), group=ALL_GROUP,
         description="Put a ready-made shape (box, cylinder, sphere…) where you click, then stretch it. "
                     "Choose Hole for a shape that cuts.",
         keywords=("add shape", "basic shapes", "tinkercad", "place shape", "drag shape", "hole shape"))
def dropshape_cmd(ctx: CommandContext):
    kind = ctx.memory.pop("dropshape_kind", None)
    hole = ctx.memory.pop("dropshape_hole", False)
    if kind is None:
        kind = yield GetKeyword("Shape [Box/CYlinder/Sphere/COne/Torus/Wedge/Hole]",
                                keywords=_shape_keywords() + (Keyword("Hole", "H"),),
                                default="Box", default_text="Box")
        if kind == "Hole":
            hole = True
            kind = yield GetKeyword("Hole shape [Box/CYlinder/Sphere/COne/Torus/Wedge]",
                                    keywords=_shape_keywords(), default="Cylinder",
                                    default_text="Cylinder")
    size = None
    while True:
        pt = yield GetPoint(f"Click where the {kind.lower()}{' hole' if hole else ''} goes "
                            "(type x,y,z to place it exactly; Enter when done) or [Size]", rubber=None,
                            allow_none=True, keywords=(Keyword("Size", "S"),))
        if pt is None:
            return
        if pt == "Size":
            size = yield from ask_size(ctx, "Size as width,depth,height (or one number for all three)")
            continue
        e = drop_shape(ctx, kind, (pt[0], pt[1], ctx.point_z), hole, size)
        ctx.selection.clear()
        ctx.selection.add(e.handle)
        ctx.echo(f"{kind}{' hole' if hole else ''} added. Drag its handles in the 3D view (or use Size 3D) "
                 "to size it, and drag it to move it.")
        ctx.doc.flush()


def parse_size(ctx: CommandContext, text: str):
    from ..core.units import parse_length
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) == 1:
        v = parse_length(parts[0], ctx.units)
        vals = (v, v, v)
    elif len(parts) == 3:
        vals = tuple(parse_length(p, ctx.units) for p in parts)
    else:
        raise ValueError("Type one size, or three: width,depth,height (e.g. 80,40,30)")
    if min(vals) <= 0:
        raise ValueError("Sizes must be more than zero.")
    return vals


def ask_size(ctx: CommandContext, prompt: str, default=None):
    from .framework import GetString
    while True:
        t = yield GetString(prompt, default=default, default_text="" if default is None else
                            ",".join(format_length(v, ctx.units) for v in default))
        if t is None or (isinstance(t, str) and not t.strip() and default is not None):
            return default
        if isinstance(t, tuple):
            return t
        try:
            return parse_size(ctx, t)
        except ValueError as exc:
            ctx.echo(str(exc))


@command("SIZE3D", label="Size 3D", aliases=("SZ",), group=ALL_GROUP,
         description="Give solids an exact width, depth and height (they stretch from their lower-left corner).",
         keywords=("resize", "dimensions", "make bigger", "set size", "stretch solid", "scale 3d"))
def size3d_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select solids to size")
    if not sols:
        return
    x0, y0, z0, x1, y1, z1 = S.bbox3(sols[0].shape)
    cur = (x1 - x0, y1 - y0, z1 - z0)
    size = yield from ask_size(ctx, "New size as width,depth,height (or one number for all three)", cur)
    for e in sols:
        b = S.bbox3(e.shape)
        old = (b[3] - b[0], b[4] - b[1], b[5] - b[2])
        f = tuple(n / o if o > 1e-9 else 1.0 for n, o in zip(size, old))
        replace_shape(ctx, e, S.scaled(e.shape, f, (b[0], b[1], b[2])))


@command("MAKEHOLE", label="Make Hole", aliases=("HOLE",), group=ALL_GROUP,
         description="Turn solids into hole shapes: see-through grey shapes that cut the solids you combine them with.",
         keywords=("hole shape", "negative shape", "cutter", "tinkercad hole"))
def makehole_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select solids to turn into holes")
    for s in sols:
        ctx.doc.replace(s.with_props(hole=True, color=HOLE_COLOR))
    if sols:
        ctx.echo(f"{len(sols)} hole(s). Select them with the solid to cut and use Combine.")


@command("MAKESOLID", label="Make Solid", aliases=(), group=ALL_GROUP,
         description="Turn hole shapes back into normal solids.", keywords=("solid shape", "undo hole"))
def makesolid_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select hole shapes to make solid")
    h = ctx.doc.header
    for s in sols:
        ctx.doc.replace(s.with_props(hole=False, color=h.current_color if s.color == HOLE_COLOR else s.color))


@command("COMBINE", label="Combine", aliases=("CB",), group=ALL_GROUP,
         description="Join the selected solids into one and cut away every hole shape among them "
                     "(Tinkercad's Group).",
         keywords=("group shapes", "merge with holes", "tinkercad group", "punch holes", "cut with hole"))
def combine_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select solids and hole shapes to combine")
    if len(sols) < 2:
        ctx.echo("Select at least two shapes (solids and/or holes).")
        return
    solid_parts = [s for s in sols if not s.hole]
    holes = [s for s in sols if s.hole]
    if not solid_parts:
        result = holes[0].shape
        for h in holes[1:]:
            result = S.union(result, h.shape)
        replace_shape(ctx, holes[0], result)
        for h in holes[1:]:
            ctx.doc.delete(h.handle)
        ctx.echo("The holes were joined into one hole.")
        return
    result = solid_parts[0].shape
    for s in solid_parts[1:]:
        result = S.union(result, s.shape)
    for h in holes:
        result = S.subtract(result, h.shape)
    if not S.solids_of(result):
        ctx.echo("The holes would remove everything; nothing was changed.")
        return
    keep = solid_parts[0]
    replace_shape(ctx, keep, result)
    for s in sols:
        if s.handle != keep.handle:
            ctx.doc.delete(s.handle)
    ctx.echo(f"Combined {len(solid_parts)} solid(s)" + (f", cut {len(holes)} hole(s)." if holes else "."))


def _bounds(e):
    if isinstance(e, Solid):
        return S.bbox3(e.shape)
    b = e.bbox()
    return None if b is None else (b[0], b[1], 0.0, b[2], b[3], 0.0)


@command("ALIGNOBJECTS", label="Align", aliases=("AO", "LINEUP"), group=ALL_GROUP,
         description="Line up objects: their left/right/front/back/top/bottom sides or centers, along X, Y or Z.",
         keywords=("align", "line up", "center objects", "even up", "tinkercad align"))
def alignobjects_cmd(ctx: CommandContext):
    sel = yield GetSelection("Select objects to line up")
    ents = [ctx.doc.get(h) for h in sel or ()]
    ents = [e for e in ents if e is not None and not ctx.doc.is_locked(e) and _bounds(e) is not None]
    if len(ents) < 2:
        ctx.echo("Select at least two objects.")
        return
    axis = yield GetKeyword("Along [X/Y/Z]", keywords=kw("X", "Y", "Z"), default="X", default_text="X")
    side = yield GetKeyword("Line up their [Min (left/front/bottom)/Center/Max (right/back/top)]",
                            keywords=(Keyword("Min", "MI"), Keyword("Center", "C"), Keyword("Max", "MA")),
                            default="Center", default_text="Center")
    i = "XYZ".index(axis)
    boxes = [_bounds(e) for e in ents]
    lo = min(b[i] for b in boxes)
    hi = max(b[i + 3] for b in boxes)
    target = {"Min": lo, "Max": hi, "Center": (lo + hi) / 2}[side]
    moved = 0
    for e, b in zip(ents, boxes):
        cur = {"Min": b[i], "Max": b[i + 3], "Center": (b[i] + b[i + 3]) / 2}[side]
        delta = target - cur
        if abs(delta) < 1e-9:
            continue
        d = [0.0, 0.0, 0.0]
        d[i] = delta
        if isinstance(e, Solid):
            ctx.doc.replace(e.with_props(shape=S.translate(e.shape, tuple(d))))
        elif i < 2:
            ctx.doc.replace(e.transformed(Affine2.translate(d[0], d[1])))
        else:
            continue
        moved += 1
    ctx.echo(f"{moved} object(s) lined up.")


_ = (np, MODEL_SPACE)
