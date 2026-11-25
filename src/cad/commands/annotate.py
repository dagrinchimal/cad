"""Annotation and organization commands: dimensions, leaders, blocks, attributes, groups."""
from __future__ import annotations

import math
from dataclasses import replace

from ..core.geom2d import Seg
from ..core.geom2d.construct import line_line
from ..core.geom2d.transform import Affine2
from ..core.geom2d.vec import add, angle_of, dist, mul, normalize, sub
from ..core.model import (
    Arc, AttributeDefinition, BlockDefinition, BlockReference, Circle, Dimension, Group, Leader, Line, Polyline,
)
from .framework import (
    CommandContext, GetAngle, GetEntity, GetNumber, GetPoint, GetSelection, GetString, Keyword, command, kw,
)
from .modify import editable


def _dim(ctx: CommandContext, **kw_) -> Dimension:
    return Dimension(style=ctx.doc.header.current_dimstyle, layer=ctx.doc.header.current_layer, **kw_)


def _auto_angle(p1, p2, loc) -> float:
    lo_y, hi_y = sorted((p1[1], p2[1]))
    lo_x, hi_x = sorted((p1[0], p2[0]))
    if loc[1] > hi_y or loc[1] < lo_y:
        return 0.0
    if loc[0] > hi_x or loc[0] < lo_x:
        return math.pi / 2
    return 0.0


def _two_points_or_object(ctx: CommandContext):
    """First/second extension line origins, or Enter to pick a line, arc or polyline segment."""
    r = yield GetPoint("Specify first extension line origin or press Enter to select an object", allow_none=True,
                       rubber=None)
    if r is None:
        e, pick = yield GetEntity("Select object to dimension")
        g = ctx.doc.geometry(e)
        prims = g.prims(snappable_only=True)
        if not prims:
            return None
        prim = min(prims, key=lambda p: p.distance_to(pick))
        return prim.start, prim.end
    p2 = yield GetPoint("Specify second extension line origin", base=r)
    return r, p2


@command("DIMLINEAR", label="Linear Dimension", aliases=("DLI", "DIMLIN"), group="Annotation",
         description="Dimension a horizontal or vertical distance.", keywords=("measure", "dimension", "length"))
def dimlinear_cmd(ctx: CommandContext):
    pts = yield from _two_points_or_object(ctx)
    if not pts:
        return
    p1, p2 = pts
    text, lock = "", None
    while True:
        def prev(c):
            ang = lock if lock is not None else _auto_angle(p1, p2, c)
            return [_dim(ctx, dimtype="linear", p1=p1, p2=p2, location=c, angle=ang, text=text)]
        r = yield GetPoint("Specify dimension line location", keywords=kw("Text", "Horizontal", "Vertical"),
                           rubber=None, preview=prev)
        if r == "Text":
            text = yield GetString("Enter dimension text (<> = measured value)", default="<>", default_text="<>")
            continue
        if r == "Horizontal":
            lock = 0.0
            continue
        if r == "Vertical":
            lock = math.pi / 2
            continue
        break
    ang = lock if lock is not None else _auto_angle(p1, p2, r)
    d = ctx.doc.add(_dim(ctx, dimtype="linear", p1=p1, p2=p2, location=r, angle=ang, text="" if text == "<>" else text),
                    use_current_props=False)
    ctx.echo(f"Dimension text = {ctx.fmt(d.measurement())}")


@command("DIMALIGNED", label="Aligned Dimension", aliases=("DAL", "DIMALI"), group="Annotation",
         description="Dimension the true distance between two points, along a slanted line.",
         keywords=("slanted", "true length", "dimension"))
def dimaligned_cmd(ctx: CommandContext):
    pts = yield from _two_points_or_object(ctx)
    if not pts:
        return
    p1, p2 = pts
    r = yield GetPoint("Specify dimension line location", rubber=None,
                       preview=lambda c: [_dim(ctx, dimtype="aligned", p1=p1, p2=p2, location=c)])
    d = ctx.doc.add(_dim(ctx, dimtype="aligned", p1=p1, p2=p2, location=r))
    ctx.echo(f"Dimension text = {ctx.fmt(d.measurement())}")


@command("DIMANGULAR", label="Angular Dimension", aliases=("DAN", "DIMANG"), group="Annotation",
         description="Dimension the angle between two lines, or of an arc.", keywords=("angle", "degrees"))
def dimangular_cmd(ctx: CommandContext):
    r = yield GetEntity("Select arc, circle or line, or press Enter to pick 3 points", allow_none=True)
    if r is None:
        v = yield GetPoint("Specify angle vertex", rubber=None)
        a = yield GetPoint("Specify first angle endpoint", base=v)
        b = yield GetPoint("Specify second angle endpoint", base=v)
    else:
        e, pick = r
        if isinstance(e, Arc):
            v = e.center
            a, b = e.endpoints()
        elif isinstance(e, Circle):
            v = e.center
            a = pick
            b = yield GetPoint("Specify second angle endpoint", base=v)
        elif isinstance(e, Line):
            e2, pick2 = yield GetEntity("Select second line")
            if not isinstance(e2, Line):
                ctx.echo("Pick a second line.")
                return
            res = line_line(e.p1, sub(e.p2, e.p1), e2.p1, sub(e2.p2, e2.p1))
            if res is None:
                ctx.echo("The lines are parallel.")
                return
            v = res[0]
            a = max((e.p1, e.p2), key=lambda p: dist(p, v)) if dist(pick, v) < 1e-9 else pick
            b = max((e2.p1, e2.p2), key=lambda p: dist(p, v)) if dist(pick2, v) < 1e-9 else pick2
        else:
            ctx.echo("Pick an arc, circle or line.")
            return
    loc = yield GetPoint("Specify dimension arc line location", rubber=None,
                         preview=lambda c: [_dim(ctx, dimtype="angular", p1=v, p2=a, p3=b, location=c)])
    d = ctx.doc.add(_dim(ctx, dimtype="angular", p1=v, p2=a, p3=b, location=loc))
    ctx.echo(f"Dimension text = {math.degrees(d.measurement()):.4g}°")


def _radial(ctx: CommandContext, kind: str):
    e, pick = yield GetEntity("Select arc or circle")
    if not isinstance(e, (Arc, Circle)):
        g = ctx.doc.geometry(e)
        arcs = [p for p in g.prims(True) if hasattr(p, "r")]
        if not arcs:
            ctx.echo("Pick an arc or a circle.")
            return
        prim = min(arcs, key=lambda p: p.distance_to(pick))
        center, radius = prim.c, prim.r
    else:
        center, radius = e.center, e.radius

    def make(c):
        dirv = normalize(sub(c, center)) if dist(c, center) > 0 else (1.0, 0.0)
        return _dim(ctx, dimtype=kind, p1=center, p2=add(center, mul(dirv, radius)), location=c)
    loc = yield GetPoint("Specify dimension line location", rubber=None, preview=lambda c: [make(c)])
    d = ctx.doc.add(make(loc))
    ctx.echo(f"Dimension text = {ctx.fmt(d.measurement())}")


@command("DIMRADIUS", label="Radius Dimension", aliases=("DRA", "DIMRAD"), group="Annotation",
         description="Dimension the radius of an arc or circle.", keywords=("radius", "R"))
def dimradius_cmd(ctx: CommandContext):
    yield from _radial(ctx, "radius")


@command("DIMDIAMETER", label="Diameter Dimension", aliases=("DDI", "DIMDIA"), group="Annotation",
         description="Dimension the diameter of a circle or arc.", keywords=("diameter", "hole size"))
def dimdiameter_cmd(ctx: CommandContext):
    yield from _radial(ctx, "diameter")


@command("DIMORDINATE", label="Ordinate Dimension", aliases=("DOR", "DIMORD"), group="Annotation",
         description="Show the X or Y distance of a point from the origin (0,0), common on machined parts.",
         keywords=("datum", "coordinate dimension"))
def dimordinate_cmd(ctx: CommandContext):
    f = yield GetPoint("Specify feature location", rubber=None)
    axis_lock = None
    while True:
        def make(c, axis_lock=axis_lock):
            axis = axis_lock or ("x" if abs(c[1] - f[1]) >= abs(c[0] - f[0]) else "y")
            return _dim(ctx, dimtype="ordinate", p1=f, location=c, axis=axis)
        r = yield GetPoint("Specify leader endpoint", keywords=kw("Xdatum", "Ydatum"), base=f, rubber=None,
                           preview=lambda c: [make(c)])
        if r == "Xdatum":
            axis_lock = "x"
            continue
        if r == "Ydatum":
            axis_lock = "y"
            continue
        break
    d = ctx.doc.add(make(r))
    ctx.echo(f"Dimension text = {ctx.fmt(d.measurement())}")


@command("LEADER", label="Leader", aliases=("LE", "QLEADER", "MLEADER", "MLD"), group="Annotation",
         description="Draw an arrow pointing at something with a note at the end.",
         keywords=("callout", "note arrow", "label"))
def leader_cmd(ctx: CommandContext):
    pts = [(yield GetPoint("Specify arrowhead location", rubber=None))]
    while True:
        r = yield GetPoint("Specify next point (Enter when done)", base=pts[-1], allow_none=len(pts) >= 2,
                           preview=lambda c: [Leader(points=tuple(pts) + (c,), layer=ctx.doc.header.current_layer)])
        if r is None:
            break
        pts.append(r)
        if len(pts) >= 3:
            break
    text = yield GetString("Enter the note", multiline=True, allow_none=True)
    ctx.doc.add(Leader(points=tuple(pts), text=(text or "").strip("\n"), style=ctx.doc.header.current_dimstyle),
                use_current_props=True)


# ------------------------------------------------------------------ blocks
def _clean_name(name: str) -> str:
    return name.strip()


@command("BLOCK", label="Create Block", aliases=("B", "BMAKE"), group="Block",
         description="Turn selected objects into a named block (symbol) you can insert many times.",
         keywords=("symbol", "make block", "component"))
def block_cmd(ctx: CommandContext):
    doc = ctx.doc
    n = 1
    while f"Block{n}" in doc.blocks:
        n += 1
    name = _clean_name((yield GetString("Enter block name", default=f"Block{n}", default_text=f"Block{n}")))
    if not name or any(c in name for c in '<>/\\":;?*|=`'):
        ctx.echo("That name can't be used for a block.")
        return
    if name in doc.blocks:
        r = yield GetPoint(f"A block named {name} already exists. Redefine it?", keywords=kw("Yes", "No"),
                           default="No", default_text="No", rubber=None)
        if r != "Yes":
            return
    base = yield GetPoint("Specify insertion base point", rubber=None)
    ents = editable(ctx, (yield GetSelection("Select objects for the block")))
    if not ents:
        ctx.echo("No objects selected.")
        return
    mode = yield GetPoint("What to do with the selected objects?", keywords=kw("Convert", "Retain", "Delete"),
                          default="Convert", default_text="Convert", rubber=None)
    children = tuple(e.with_props(handle=i + 1, space="*Model") for i, e in enumerate(ents))
    doc.set_item("block", name, BlockDefinition(name=name, base=base, entities=children))
    if mode in ("Convert", "Delete"):
        for e in ents:
            doc.delete(e.handle)
    if mode == "Convert":
        doc.add(BlockReference(name=name, insert=base), use_current_props=True)
    ctx.echo(f"Block {name} created from {len(ents)} object(s).")


@command("INSERT", label="Insert Block", aliases=("I", "DDINSERT", "CLASSICINSERT"), group="Block",
         description="Place a copy of a block (symbol) in the drawing.", keywords=("place symbol", "add block"))
def insert_cmd(ctx: CommandContext):
    doc = ctx.doc
    names = sorted(n for n in doc.blocks if not n.startswith("*"))
    if not names:
        ctx.echo("This drawing has no blocks yet. Use BLOCK to make one.")
        return
    last = ctx.memory.get("insert_name", names[0])
    listing = ", ".join(names[:12]) + ("…" if len(names) > 12 else "")
    name = _clean_name((yield GetString(f"Enter block name ({listing})", default=last, default_text=last)))
    match = next((n for n in names if n.lower() == name.lower()), None)
    if match is None:
        ctx.echo(f"There's no block named {name}.")
        return
    ctx.memory["insert_name"] = match
    bdef = doc.blocks[match]
    scale, rot = 1.0, 0.0
    while True:
        def prev(c, scale=scale, rot=rot):
            return [BlockReference(name=match, insert=c, sx=scale, sy=scale, rotation=rot,
                                   layer=doc.header.current_layer)]
        ins = yield GetPoint("Specify insertion point", keywords=kw("Scale", "Rotate"), rubber=None, preview=prev)
        if ins == "Scale":
            scale = yield GetNumber("Specify scale factor", default=scale, default_text=f"{scale:g}", minimum=1e-12)
            continue
        if ins == "Rotate":
            rot = yield GetAngle("Specify rotation angle", default=rot, default_text=f"{math.degrees(rot):g}")
            continue
        break
    attribs = []
    for ad in bdef.attdefs():
        v = yield GetString(f"{ad.prompt or ad.tag}", default=ad.default, default_text=ad.default, allow_none=True)
        attribs.append((ad.tag, ad.default if v is None else v))
    doc.add(BlockReference(name=match, insert=ins, sx=scale, sy=scale, rotation=rot, attribs=tuple(attribs)),
            use_current_props=True)


@command("ATTDEF", label="Define Attribute", aliases=("ATT", "DDATTDEF"), group="Block",
         description="Add a fill-in field (like TITLE or DATE) to include in a block.",
         keywords=("field", "title block field", "attribute"))
def attdef_cmd(ctx: CommandContext):
    tag = (yield GetString("Enter attribute tag (no spaces), e.g. TITLE")).strip().upper().replace(" ", "_")
    if not tag:
        return
    prompt = yield GetString("Enter the question to ask when inserting", default=tag.title(),
                             default_text=tag.title())
    default = yield GetString("Enter the default value", allow_none=True, default="", default_text="")
    ins = yield GetPoint("Specify start point", rubber=None)
    h = ctx.doc.header.text_height
    from .framework import GetDistance
    height = yield GetDistance("Specify text height", base=ins, default=h, default_text=ctx.fmt(h))
    ctx.doc.add(AttributeDefinition(tag=tag, prompt=prompt, default=default or "", insert=ins, height=height),
                use_current_props=True)


# ------------------------------------------------------------------ groups
@command("GROUP", label="Group", aliases=("G",), group="Groups",
         description="Tie objects together so clicking one selects them all.", keywords=("bundle", "tie together"))
def group_cmd(ctx: CommandContext):
    doc = ctx.doc
    sel = yield GetSelection("Select objects to group")
    if not sel or len(sel) < 2:
        ctx.echo("Select at least two objects.")
        return
    n = 1
    while f"Group{n}" in doc.groups:
        n += 1
    name = (yield GetString("Enter group name", default=f"Group{n}", default_text=f"Group{n}")).strip() or f"Group{n}"
    if name in doc.groups:
        ctx.echo(f"A group named {name} already exists.")
        return
    doc.set_item("group", name, Group(name, frozenset(sel)))
    ctx.echo(f"Group {name} created with {len(sel)} objects.")


@command("UNGROUP", label="Ungroup", aliases=("UNG",), group="Groups",
         description="Remove the groups the selected objects belong to (the objects stay).",
         keywords=("split group",))
def ungroup_cmd(ctx: CommandContext):
    sel = yield GetSelection("Select a grouped object")
    gone = [g.name for g in ctx.doc.groups.values() if g.handles & set(sel or ())]
    for name in gone:
        ctx.doc.remove_item("group", name)
    ctx.echo(f"{len(gone)} group(s) removed." if gone else "Those objects aren't in a group.")


_ = (Seg, Affine2, Keyword, Polyline, replace, angle_of)
