"""More drawing commands: RECTANG, POLYGON, ELLIPSE, SPLINE, TEXT, MTEXT, HATCH, BOUNDARY."""
from __future__ import annotations

import math
from dataclasses import replace

from ..core.geom2d import Arc as ArcPrim
from ..core.geom2d.fill import loop_area
from ..core.geom2d.regions import find_boundary
from ..core.geom2d.vec import angle_of, dist, sub
from ..core.model import Circle, Ellipse, Hatch, MText, Polyline, Spline, Text
from ..core.model.hatch_patterns import PATTERN_NAMES
from .framework import (
    CommandCancelled, CommandContext, GetAngle, GetDistance, GetNumber, GetPoint, GetSelection, GetString, Keyword,
    command, kw,
)

UNDO = Keyword("Undo")


def _rect_poly(a, b, layer):
    return Polyline(vertices=((a[0], a[1], 0), (b[0], a[1], 0), (b[0], b[1], 0), (a[0], b[1], 0)), closed=True,
                    layer=layer)


@command("RECTANG", label="Rectangle", aliases=("REC", "RECTANGLE"), group="Draw",
         description="Draw a rectangle from two opposite corners, or by its length and width.",
         keywords=("box", "square"))
def rectang_cmd(ctx: CommandContext):
    layer = ctx.doc.header.current_layer
    a = yield GetPoint("Specify first corner point", rubber=None)
    r = yield GetPoint("Specify other corner point", base=a, keywords=kw("Dimensions"), rubber=None,
                       preview=lambda c: [_rect_poly(a, c, layer)] if dist(a, c) > 0 else [])
    if r == "Dimensions":
        length = yield GetDistance("Specify length for rectangles", base=a)
        width = yield GetDistance("Specify width for rectangles", base=a)
        c = yield GetPoint("Pick the side to draw towards", base=a, rubber=None,
                           preview=lambda c: [_rect_poly(a, (a[0] + math.copysign(length, c[0] - a[0] or 1),
                                                            a[1] + math.copysign(width, c[1] - a[1] or 1)), layer)])
        r = (a[0] + math.copysign(length, c[0] - a[0] or 1), a[1] + math.copysign(width, c[1] - a[1] or 1))
    if abs(r[0] - a[0]) < 1e-12 or abs(r[1] - a[1]) < 1e-12:
        ctx.echo("A rectangle needs width and height.")
        return
    ctx.doc.add(_rect_poly(a, r, layer), use_current_props=True)


def _polygon(center, radius, n, start_angle, inscribed=True):
    r = radius if inscribed else radius / math.cos(math.pi / n)
    a0 = start_angle if inscribed else start_angle - math.pi / n
    return Polyline(vertices=tuple((center[0] + r * math.cos(a0 + k * math.tau / n),
                                    center[1] + r * math.sin(a0 + k * math.tau / n), 0.0) for k in range(n)),
                    closed=True)


@command("POLYGON", label="Polygon", aliases=("POL",), group="Draw",
         description="Draw a regular polygon (triangle, hexagon…) around a center or on an edge.",
         keywords=("hexagon", "octagon", "triangle", "pentagon"))
def polygon_cmd(ctx: CommandContext):
    last_n = ctx.memory.get("polygon_sides", 4)
    n = yield GetNumber("Enter number of sides", integer=True, minimum=3, default=last_n, default_text=str(last_n))
    n = int(n)
    if n > 1024:
        ctx.echo("That's a lot of sides: the maximum is 1024.")
        return
    ctx.memory["polygon_sides"] = n
    r = yield GetPoint("Specify center of polygon", keywords=kw("Edge"), rubber=None)
    if r == "Edge":
        p1 = yield GetPoint("Specify first endpoint of edge", rubber=None)

        def by_edge(p2):
            side = dist(p1, p2)
            if side <= 0:
                return None
            R = side / (2 * math.sin(math.pi / n))
            mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            ang = angle_of(sub(p2, p1)) + math.pi / 2
            h = R * math.cos(math.pi / n)
            c = (mid[0] + h * math.cos(ang), mid[1] + h * math.sin(ang))
            return _polygon(c, R, n, angle_of(sub(p1, c)))
        p2 = yield GetPoint("Specify second endpoint of edge", base=p1,
                            preview=lambda c: [x for x in [by_edge(c)] if x])
        poly = by_edge(p2)
        if poly is None:
            return
        ctx.doc.add(poly, use_current_props=True)
        return
    center = r
    mode = ctx.memory.get("polygon_mode", "Inscribed")
    m = yield GetPoint("Inscribed in circle or Circumscribed about circle", keywords=kw("Inscribed", "Circumscribed"),
                       default=mode, default_text=mode, rubber=None)
    mode = m if isinstance(m, str) else mode
    ctx.memory["polygon_mode"] = mode
    ins = mode == "Inscribed"
    p = yield GetPoint("Specify radius of circle", base=center,
                       preview=lambda c: [_polygon(center, dist(center, c), n, angle_of(sub(c, center)), ins)]
                       if dist(center, c) > 0 else [])
    rad = dist(center, p)
    if rad <= 0:
        return
    ctx.doc.add(_polygon(center, rad, n, angle_of(sub(p, center)), ins), use_current_props=True)


@command("ELLIPSE", label="Ellipse", aliases=("EL",), group="Draw",
         description="Draw an ellipse (oval) by its axes, or an elliptical arc.", keywords=("oval",))
def ellipse_cmd(ctx: CommandContext):
    layer = ctx.doc.header.current_layer
    arc = False
    r = yield GetPoint("Specify axis endpoint of ellipse", keywords=kw("Arc", "Center"), rubber=None)
    if r == "Arc":
        arc = True
        r = yield GetPoint("Specify axis endpoint of elliptical arc", keywords=kw("Center"), rubber=None)
    if r == "Center":
        center = yield GetPoint("Specify center of ellipse", rubber=None)
        a_end = yield GetPoint("Specify endpoint of axis", base=center)
    else:
        a1 = r
        a2 = yield GetPoint("Specify other endpoint of axis", base=a1)
        center = ((a1[0] + a2[0]) / 2, (a1[1] + a2[1]) / 2)
        a_end = a2
    major = (a_end[0] - center[0], a_end[1] - center[1])
    if math.hypot(*major) <= 0:
        ctx.echo("The axis needs two different points.")
        return

    def make(c):
        b = abs((c[0] - center[0]) * -major[1] + (c[1] - center[1]) * major[0]) / math.hypot(*major)
        ratio = b / math.hypot(*major)
        if ratio <= 0:
            return None
        if ratio > 1:       # the second axis is longer: swap roles
            m2 = (-major[1] * ratio, major[0] * ratio)
            return Ellipse(center=center, major=m2, ratio=1 / ratio, layer=layer)
        return Ellipse(center=center, major=major, ratio=ratio, layer=layer)
    p = yield GetDistance("Specify distance to other axis", base=center,
                          preview=lambda c: [x for x in [make(c)] if x])
    half = p
    ratio = half / math.hypot(*major)
    if ratio > 1:
        el = Ellipse(center=center, major=(-major[1] * ratio, major[0] * ratio), ratio=1 / ratio)
    else:
        el = Ellipse(center=center, major=major, ratio=ratio)
    if arc:
        def param_of(pt):
            v = sub(pt, center)
            u = el.major
            mi = el.minor
            x = (v[0] * u[0] + v[1] * u[1]) / (math.hypot(*u) ** 2)
            y = (v[0] * mi[0] + v[1] * mi[1]) / (math.hypot(*mi) ** 2)
            return math.atan2(y, x) % math.tau
        s = yield GetPoint("Specify start angle", base=center)
        t0 = param_of(s)
        e = yield GetPoint("Specify end angle", base=center,
                           preview=lambda c: [replace(el, start_param=t0, end_param=t0 + ((param_of(c) - t0) % math.tau
                                                                                          or math.tau), layer=layer)])
        t1 = t0 + ((param_of(e) - t0) % math.tau or math.tau)
        el = replace(el, start_param=t0, end_param=t1)
    ctx.doc.add(el, use_current_props=True)


@command("SPLINE", label="Spline", aliases=("SPL",), group="Draw",
         description="Draw a smooth curve through the points you pick.", keywords=("curve", "smooth", "freeform"))
def spline_cmd(ctx: CommandContext):
    layer = ctx.doc.header.current_layer
    pts = [(yield GetPoint("Specify first point", rubber=None))]
    closed = False
    while True:
        kws = (Keyword("Close"), UNDO) if len(pts) >= 3 else (UNDO,)

        def prev(c, pts=pts):
            cand = pts + [c]
            try:
                return [Spline.through(cand, layer=layer)] if len(cand) >= 2 and dist(cand[-1], cand[-2]) > 0 else []
            except (ValueError, ArithmeticError):
                return []
        r = yield GetPoint("Enter next point", base=pts[-1], keywords=kws, allow_none=True, rubber=None, preview=prev)
        if r is None:
            break
        if r == "Undo":
            if len(pts) > 1:
                pts.pop()
            continue
        if r == "Close":
            closed = True
            break
        if dist(r, pts[-1]) <= 1e-9:
            continue
        pts.append(r)
    if len(pts) < 2:
        return
    ctx.doc.add(Spline.through(pts, closed=closed), use_current_props=True)


JUSTIFY = {
    "Left": ("left", "baseline"), "Center": ("center", "baseline"), "Right": ("right", "baseline"),
    "Middle": ("center", "middle"), "TL": ("left", "top"), "TC": ("center", "top"), "TR": ("right", "top"),
    "ML": ("left", "middle"), "MC": ("center", "middle"), "MR": ("right", "middle"),
    "BL": ("left", "bottom"), "BC": ("center", "bottom"), "BR": ("right", "bottom"),
}


@command("TEXT", label="Single Line Text", aliases=("DT", "DTEXT"), group="Annotation",
         description="Type one or more lines of text. Each line is a separate object.",
         keywords=("label", "words", "write", "dtext"))
def text_cmd(ctx: CommandContext):
    h = ctx.doc.header
    halign, valign = "left", "baseline"
    r = yield GetPoint("Specify start point of text", keywords=kw("Justify"), rubber=None)
    if r == "Justify":
        j = yield GetPoint("Enter an option", keywords=tuple(Keyword(k, k if len(k) == 2 else k[0])
                                                              for k in JUSTIFY), rubber=None)
        if isinstance(j, str):
            halign, valign = JUSTIFY[j]
        r = yield GetPoint("Specify insertion point of text", rubber=None)
    ins = r
    height = yield GetDistance("Specify height", base=ins, default=h.text_height, default_text=ctx.fmt(h.text_height))
    rot = yield GetAngle("Specify rotation angle of text", base=ins, default=0.0, default_text="0")
    if height != h.text_height:
        ctx.doc.set_header(replace(h, text_height=height))
    line_gap = height * 1.667
    n = 0
    while True:
        t = yield GetString("Enter text (press Enter on an empty line to finish)", allow_none=True)
        if not t:
            return
        dx, dy = math.sin(rot) * line_gap * n, -math.cos(rot) * line_gap * n
        ctx.doc.add(Text(insert=(ins[0] + dx, ins[1] + dy), text=t, height=height, rotation=rot, halign=halign,
                         valign=valign), use_current_props=True)
        n += 1


@command("MTEXT", label="Multiline Text", aliases=("T", "MT"), group="Annotation",
         description="Write a paragraph of text inside a box; it wraps to the box width.",
         keywords=("paragraph", "note", "notes", "text box"))
def mtext_cmd(ctx: CommandContext):
    h = ctx.doc.header
    a = yield GetPoint("Specify first corner", rubber=None)
    height = h.text_height
    while True:
        b = yield GetPoint("Specify opposite corner", base=a, keywords=kw("Height"), rubber="rect")
        if b == "Height":
            height = yield GetDistance("Specify height", base=a, default=height, default_text=ctx.fmt(height))
            continue
        break
    width = abs(b[0] - a[0])
    insert = (min(a[0], b[0]), max(a[1], b[1]))
    text = yield GetString("Enter the text", multiline=True)
    if not text or not text.strip():
        ctx.echo("No text entered.")
        return
    ctx.doc.add(MText(insert=insert, text=text.rstrip("\n"), height=height, width=width), use_current_props=True)


# ------------------------------------------------------------------ hatch
def closed_loop_of(e) -> tuple | None:
    """Boundary loop (x, y, bulge vertices) for closed objects, else None."""
    if isinstance(e, Circle):
        x, y, r = e.center[0], e.center[1], e.radius
        return ((x - r, y, 1.0), (x + r, y, 1.0))
    if isinstance(e, Polyline) and (e.closed or (len(e.vertices) > 2 and e.vertices[0][:2] == e.vertices[-1][:2])):
        vs = e.vertices if e.closed else e.vertices[:-1]
        return tuple(vs)
    if isinstance(e, Ellipse) and e.is_full:
        return tuple((float(p[0]), float(p[1]), 0.0) for p in e.points(96)[:-1])
    if isinstance(e, Spline) and e.closed:
        return tuple((float(p[0]), float(p[1]), 0.0) for p in e.curve_points(16)[:-1])
    return None


def pick_area(ctx: CommandContext, pt):
    """Loops around pt from the visible objects in the current space."""
    doc = ctx.doc
    # search the whole space when it's small enough; otherwise only what's on screen (like AutoCAD)
    rect = ctx.index.extents()
    if rect is not None and len(ctx.index.query(rect)) > 20_000:
        rect = ctx.view.visible_rect() if hasattr(ctx.view, "visible_rect") else rect
    if rect is None:
        return None, 1.0
    size = max(rect[2] - rect[0], rect[3] - rect[1], 1e-9)
    prims = []
    for h in ctx.index.query(rect):
        e = doc.entities.get(h)
        if e is None or not doc.is_visible(e) or e.TYPE in ("hatch", "text", "mtext", "dimension", "leader", "point"):
            continue
        prims.extend(doc.geometry(e).prims(snappable_only=True))
    if len(prims) > 60_000:
        ctx.echo("Too many objects in view to search. Zoom in closer to the area.")
        return None, size
    loops = find_boundary(prims, pt, tol=size * 1e-7, arc_tol=size * 2e-4)
    return loops, size


@command("HATCH", label="Hatch", aliases=("H", "BHATCH"), group="Draw",
         description="Fill an enclosed area with a pattern or solid color. Click inside the area.",
         keywords=("fill", "pattern", "shade", "solid fill", "cross hatch"))
def hatch_cmd(ctx: CommandContext):
    h = ctx.doc.header
    pattern, scale, angle = h.hatch_pattern, h.hatch_scale, h.hatch_angle
    loops_all: list[tuple] = []
    names = "/".join(PATTERN_NAMES)
    while True:
        r = yield GetPoint(f"Pick internal point (pattern {pattern}, scale {scale:g}, angle "
                           f"{math.degrees(angle):g}°)", keywords=(Keyword("Select objects", "S"), Keyword("Pattern", "P"),
                                                  Keyword("Scale", "SC"), Keyword("Angle", "A")),
                           allow_none=True, rubber=None)
        if r is None:
            break
        if r == "Pattern":
            p = yield GetString(f"Enter a pattern name [{names}]", default=pattern, default_text=pattern)
            if p.strip().upper() in PATTERN_NAMES:
                pattern = p.strip().upper()
            else:
                ctx.echo(f"Unknown pattern. Choose one of: {names}")
            continue
        if r == "Scale":
            scale = yield GetNumber("Specify pattern scale", default=scale, default_text=f"{scale:g}", minimum=1e-9)
            continue
        if r == "Angle":
            angle = yield GetAngle("Specify pattern angle", default=angle, default_text=f"{math.degrees(angle):g}")
            continue
        if r == "Select objects":
            sel = yield GetSelection("Select closed objects")
            for hd in sel or ():
                e = ctx.doc.get(hd)
                lp = closed_loop_of(e) if e is not None else None
                if lp:
                    loops_all.append(lp)
            if not loops_all:
                ctx.echo("None of those objects are closed shapes.")
            continue
        loops, _ = pick_area(ctx, r)
        if not loops:
            ctx.echo("That point isn't inside a closed area. Make sure the shape is fully closed and visible.")
            continue
        for lp in loops:
            loops_all.append(tuple((float(x), float(y), 0.0) for x, y in lp))
        ctx.echo(f"Area found ({len(loops) - 1} island(s)). Pick more areas or press Enter.")
    if not loops_all:
        return
    if (pattern, scale, angle) != (h.hatch_pattern, h.hatch_scale, h.hatch_angle):
        ctx.doc.set_header(replace(ctx.doc.header, hatch_pattern=pattern, hatch_scale=scale, hatch_angle=angle))
    hatch = Hatch(loops=tuple(loops_all), pattern=pattern, pattern_scale=scale, pattern_angle=angle)
    ctx.doc.add(hatch, use_current_props=True)
    ctx.echo(f"Hatch created, area = {ctx.fmt(math.sqrt(hatch.area()))} squared.")


@command("BOUNDARY", label="Boundary", aliases=("BO",), group="Draw",
         description="Create a closed polyline around an area by clicking inside it.",
         keywords=("outline", "region", "area outline"))
def boundary_cmd(ctx: CommandContext):
    count = 0
    while True:
        r = yield GetPoint("Pick internal point", allow_none=True, rubber=None)
        if r is None:
            break
        loops, _ = pick_area(ctx, r)
        if not loops:
            ctx.echo("That point isn't inside a closed area.")
            continue
        for lp in loops:
            pts = lp if loop_area(lp) > 0 else lp[::-1]
            ctx.doc.add(Polyline(vertices=tuple((float(x), float(y), 0.0) for x, y in pts), closed=True),
                        use_current_props=True)
            count += 1
    ctx.echo(f"{count} boundary polyline(s) created.")


_ = (ArcPrim, CommandCancelled)
