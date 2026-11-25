"""Drawing commands: LINE, PLINE, CIRCLE, ARC, POINT."""
from __future__ import annotations

import math

from ..core.geom2d import (
    arc_from_3_points, arc_from_bulge, arc_from_start_center_end, bulge_for_tangent_arc,
    circle_from_3_points,
)
from ..core.geom2d.primitives import Arc as ArcPrim
from ..core.geom2d.vec import close, dist, midpoint, sub
from ..core.model import Arc, Circle, Line, Point, Polyline
from .framework import (
    CommandCancelled, CommandContext, GetDistance, GetPoint, Keyword, command, kw,
)

UNDO = Keyword("Undo")
CLOSE = Keyword("Close")


@command("LINE", label="Line", aliases=("L",), group="Draw",
         description="Draw straight line segments, one after another.",
         keywords=("segment", "straight"))
def line_cmd(ctx: CommandContext):
    start = yield GetPoint("Specify first point", rubber=None)
    p1 = start
    added: list = []
    while True:
        kws = (UNDO, CLOSE) if len(added) >= 2 else (UNDO,)
        r = yield GetPoint("Specify next point", base=p1, keywords=kws, allow_none=True)
        if r is None:
            return
        if r == "Undo":
            if added:
                last = added.pop()
                ctx.doc.delete(last.handle)
                p1 = last.p1
            else:
                ctx.echo("All segments already undone.")
            continue
        if r == "Close":
            added.append(ctx.doc.add(Line(p1=p1, p2=start), use_current_props=True))
            return
        if close(r, p1, 1e-9):
            ctx.echo("That's the same point. Pick a different one.")
            continue
        added.append(ctx.doc.add(Line(p1=p1, p2=r), use_current_props=True))
        p1 = r


@command("PLINE", label="Polyline", aliases=("PL",), group="Draw",
         description="Draw one connected object made of straight and arc segments.",
         keywords=("polyline", "connected lines", "outline"))
def pline_cmd(ctx: CommandContext):
    first = yield GetPoint("Specify start point", rubber=None)
    verts: list[list[float]] = [[first[0], first[1], 0.0]]
    arc_mode = False
    closed = False

    def last_tangent():
        if len(verts) < 2:
            return None
        a, b = verts[-2], verts[-1]
        prim = arc_from_bulge((a[0], a[1]), (b[0], b[1]), a[2])
        return prim.end_tangent()

    def preview_entities(cursor, pending_bulge):
        vs = [tuple(v) for v in verts]
        vs[-1] = (vs[-1][0], vs[-1][1], pending_bulge)
        vs.append((cursor[0], cursor[1], 0.0))
        return [Polyline(vertices=tuple(vs), layer=ctx.doc.header.current_layer)]

    def arc_bulge_to(pt):
        t = last_tangent() or (1.0, 0.0)
        return bulge_for_tangent_arc((verts[-1][0], verts[-1][1]), t, pt)

    try:
        while True:
            last = (verts[-1][0], verts[-1][1])
            can_close = len(verts) >= 2
            if arc_mode:
                kws = (Keyword("Line"), CLOSE, UNDO) if can_close else (Keyword("Line"), UNDO)
                r = yield GetPoint("Specify endpoint of arc", base=last, keywords=kws, allow_none=True,
                                   rubber=None, preview=lambda c: preview_entities(c, arc_bulge_to(c)))
            else:
                kws = (Keyword("Arc"), CLOSE, UNDO) if can_close else (Keyword("Arc"), UNDO)
                r = yield GetPoint("Specify next point", base=last, keywords=kws, allow_none=True,
                                   rubber=None, preview=lambda c: preview_entities(c, 0.0))
            if r is None:
                break
            if r == "Arc":
                arc_mode = True
                continue
            if r == "Line":
                arc_mode = False
                continue
            if r == "Undo":
                if len(verts) > 1:
                    verts.pop()
                    verts[-1][2] = 0.0
                else:
                    ctx.echo("Nothing left to undo.")
                continue
            if r == "Close":
                if arc_mode:
                    verts[-1][2] = arc_bulge_to((verts[0][0], verts[0][1]))
                closed = True
                break
            if close(r, last, 1e-9):
                ctx.echo("That's the same point. Pick a different one.")
                continue
            verts[-1][2] = arc_bulge_to(r) if arc_mode else 0.0
            verts.append([r[0], r[1], 0.0])
    except CommandCancelled:
        pass
    if len(verts) >= 2:
        ctx.doc.add(Polyline(vertices=tuple(tuple(v) for v in verts), closed=closed), use_current_props=True)


@command("CIRCLE", label="Circle", aliases=("C",), group="Draw",
         description="Draw a circle from its center and radius, or through 2 or 3 points.",
         keywords=("round", "ring"))
def circle_cmd(ctx: CommandContext):
    layer = ctx.doc.header.current_layer
    r = yield GetPoint("Specify center point for circle", keywords=kw("3P", "2P"), rubber=None)
    if r == "3P":
        p1 = yield GetPoint("Specify first point on circle", rubber=None)
        p2 = yield GetPoint("Specify second point on circle", base=p1)

        def prev3(c):
            res = circle_from_3_points(p1, p2, c)
            return [Circle(center=res[0], radius=res[1], layer=layer)] if res else []
        p3 = yield GetPoint("Specify third point on circle", base=p2, preview=prev3)
        res = circle_from_3_points(p1, p2, p3)
        if res is None:
            ctx.echo("The three points are in a straight line, so no circle passes through them.")
            return
        ctx.doc.add(Circle(center=res[0], radius=res[1]), use_current_props=True)
        ctx.memory["circle_radius"] = res[1]
        return
    if r == "2P":
        p1 = yield GetPoint("Specify first end point of circle's diameter", rubber=None)
        p2 = yield GetPoint("Specify second end point of circle's diameter", base=p1,
                            preview=lambda c: [Circle(center=midpoint(p1, c), radius=max(dist(p1, c) / 2, 1e-9), layer=layer)])
        if dist(p1, p2) <= 0:
            ctx.echo("The points are the same.")
            return
        ctx.doc.add(Circle(center=midpoint(p1, p2), radius=dist(p1, p2) / 2), use_current_props=True)
        ctx.memory["circle_radius"] = dist(p1, p2) / 2
        return
    center = r
    last_r = ctx.memory.get("circle_radius")
    radius = yield GetDistance(
        "Specify radius of circle", base=center, keywords=kw("Diameter"),
        default=last_r, default_text=ctx.fmt(last_r) if last_r else "",
        preview=lambda c: [Circle(center=center, radius=max(dist(center, c), 1e-9), layer=layer)])
    if radius == "Diameter":
        last_d = last_r * 2 if last_r else None
        diameter = yield GetDistance(
            "Specify diameter of circle", base=center, default=last_d,
            default_text=ctx.fmt(last_d) if last_d else "",
            preview=lambda c: [Circle(center=center, radius=max(dist(center, c) / 2, 1e-9), layer=layer)])
        radius = diameter / 2
    ctx.doc.add(Circle(center=center, radius=radius), use_current_props=True)
    ctx.memory["circle_radius"] = radius


@command("ARC", label="Arc", aliases=("A",), group="Draw",
         description="Draw an arc through 3 points, or from a start point, center and end.",
         keywords=("curve", "bend"))
def arc_cmd(ctx: CommandContext):
    layer = ctx.doc.header.current_layer

    def add_arc(prim: ArcPrim | None):
        if prim is None or prim.r <= 0:
            ctx.echo("Those points don't make an arc.")
            return
        ctx.doc.add(Arc.from_primitive(prim), use_current_props=True)

    def as_ent(prim):
        return [Arc.from_primitive(prim, layer=layer)] if prim is not None and prim.r > 0 else []

    r = yield GetPoint("Specify start point of arc", keywords=kw("Center"), rubber=None)
    if r == "Center":
        center = yield GetPoint("Specify center point of arc", rubber=None)
        start = yield GetPoint("Specify start point of arc", base=center)
        end = yield GetPoint("Specify end point of arc", base=center,
                             preview=lambda c: as_ent(arc_from_start_center_end(start, center, c)))
        add_arc(arc_from_start_center_end(start, center, end))
        return
    start = r
    r2 = yield GetPoint("Specify second point of arc", base=start, keywords=kw("Center"))
    if r2 == "Center":
        center = yield GetPoint("Specify center point of arc", base=start)
        end = yield GetPoint("Specify end point of arc", base=center,
                             preview=lambda c: as_ent(arc_from_start_center_end(start, center, c)))
        add_arc(arc_from_start_center_end(start, center, end))
        return
    second = r2
    end = yield GetPoint("Specify end point of arc", base=second,
                         preview=lambda c: as_ent(arc_from_3_points(start, second, c)))
    add_arc(arc_from_3_points(start, second, end))


@command("POINT", label="Point", aliases=("PO",), group="Draw",
         description="Place point markers (nodes) you can snap to. Press Enter when done.",
         keywords=("node", "marker"))
def point_cmd(ctx: CommandContext):
    while True:
        p = yield GetPoint("Specify a point", rubber=None, allow_none=True)
        if p is None:
            return
        ctx.doc.add(Point(position=p), use_current_props=True)


# keep math imported for subclasses/extensions
_ = (math, sub)
