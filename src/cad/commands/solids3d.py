"""3D modeling commands: make solids from profiles, primitives, booleans, and direct edits."""
from __future__ import annotations

import math

import numpy as np

from ..core import solids as S
from ..core.model import MODEL_SPACE, Circle, Entity, Polyline, Solid, is_sketch_space
from ..core.model.tables import SKETCH_PREFIX
from ..core.solid_pick import visible_solids
from ..core.units import format_length
from .framework import (
    CommandContext, GetAngle, GetDistance, GetEdge, GetEntity, GetFace, GetNumber, GetPoint, GetSelection,
    GetString, Keyword, command, kw,
)

ALL_GROUP = "3D"


# ====================================================================== helpers
def plane_of_space(ctx: CommandContext, space: str) -> S.Plane:
    if is_sketch_space(space):
        sk = ctx.doc.sketches.get(space[len(SKETCH_PREFIX):])
        if sk is not None:
            return sk.plane()
    return S.XY


def new_solid(ctx: CommandContext, shape, like: Entity | None = None) -> Solid:
    """Add a solid with the current layer/color (or the properties of `like`)."""
    h = ctx.doc.header
    if like is not None:
        props = dict(layer=like.layer, color=like.color, linetype="ByLayer", lineweight=like.lineweight)
    else:
        props = dict(layer=h.current_layer, color=h.current_color, linetype="ByLayer", lineweight=h.current_lineweight)
    if not S.solids_of(shape):
        raise S.SolidError("The result has no volume.")
    return ctx.doc.add(Solid(shape=shape, space=MODEL_SPACE, **props))


def replace_shape(ctx: CommandContext, e: Solid, shape) -> Solid:
    if not S.solids_of(shape):
        raise S.SolidError("The result has no volume.")
    new = e.with_props(shape=shape)
    ctx.doc.replace(new)
    return new


def ask_solids(ctx: CommandContext, prompt: str, use_pickfirst: bool = True) -> list[Solid]:
    sel = yield GetSelection(prompt, use_pickfirst=use_pickfirst)
    out = []
    skipped = 0
    for h in sel or ():
        e = ctx.doc.get(h)
        if isinstance(e, Solid) and not ctx.doc.is_locked(e):
            out.append(e)
        elif e is not None:
            skipped += 1
    if skipped:
        ctx.echo(f"{skipped} object(s) that aren't solids were left out.")
    return out


def _exact_profile_for_loop(ctx: CommandContext, loop: np.ndarray):
    """A closed object whose outline is this loop (so circles stay true circles), or None."""
    from ..core.geom2d.fill import loop_area
    area = abs(loop_area(loop))
    x0, y0 = loop.min(axis=0)
    x1, y1 = loop.max(axis=0)
    size = max(x1 - x0, y1 - y0, 1e-9)
    for h in ctx.index.query((x0 - size * 0.01, y0 - size * 0.01, x1 + size * 0.01, y1 + size * 0.01)):
        e = ctx.doc.get(h)
        if e is None or not S.is_closed_profile(e):
            continue
        b = e.bbox()
        if b is None or max(abs(b[0] - x0), abs(b[1] - y0), abs(b[2] - x1), abs(b[3] - y1)) > size * 0.01:
            continue
        pts = np.array([p for prim in e.primitives() for p in prim.tessellate(size * 1e-4)])
        if len(pts) > 2 and abs(abs(loop_area(pts)) - area) <= area * 0.01:
            return e
    return None


def _circle_of_loop(loop: np.ndarray):
    """A true circle if the loop is a tessellated circle (e.g. a copy inside an array)."""
    if len(loop) < 12:
        return None
    pts = loop[:-1] if np.allclose(loop[0], loop[-1]) else loop
    c = pts.mean(axis=0)
    r = np.linalg.norm(pts - c, axis=1)
    if r.mean() > 0 and np.ptp(r) <= r.mean() * 2e-3:
        return Circle(center=(float(c[0]), float(c[1])), radius=float(r.max()))
    return None


def area_face(ctx: CommandContext, plane: S.Plane, pt):
    """A face from the enclosed area around pt (holes included)."""
    from .draw2 import pick_area
    loops, size = pick_area(ctx, pt)
    if not loops:
        raise S.SolidError("That isn't inside a closed area.")
    wires = []
    for lp in loops:
        lp = np.asarray(lp, float)
        e = _exact_profile_for_loop(ctx, lp) or _circle_of_loop(lp)
        if e is not None:
            wires.append(S.wire_from_entity(plane, e))
        else:
            wires.append(S.wire_from_loop(plane, [(float(x), float(y), 0.0) for x, y in lp]))
    return S.face_from_wires(plane, wires[0], wires[1:])


def collect_profiles(ctx: CommandContext, verb: str):
    """Ask for closed objects (or areas). Returns (faces, plane, objects to delete afterwards)."""
    sel = yield GetSelection(f"Select closed objects to {verb}, or type A to click inside areas",
                             keywords=(Keyword("Area", "A"),))
    faces, used, plane = [], [], None
    if sel == "Area":
        plane = plane_of_space(ctx, ctx.space)
        while True:
            pt = yield GetPoint("Click inside an area (Enter when done)", allow_none=True, rubber=None)
            if pt is None:
                break
            try:
                faces.append(area_face(ctx, plane, pt))
            except S.SolidError as exc:
                ctx.echo(str(exc))
        return faces, plane, used
    for h in sel or ():
        e = ctx.doc.get(h)
        if e is None or isinstance(e, Solid):
            continue
        if not S.is_closed_profile(e):
            ctx.echo(f"A {e.TYPE} isn't a closed outline; skipped (use Area to click inside lines).")
            continue
        p = plane_of_space(ctx, e.space)
        if plane is None:
            plane = p
        try:
            faces.append(S.face_from_entity(p, e))
            used.append(e)
        except S.SolidError as exc:
            ctx.echo(str(exc))
    return faces, plane or S.XY, used


def _touching(ctx: CommandContext, shape) -> list[Solid]:
    """Existing solids whose box overlaps the shape's box."""
    b = S.bbox3(shape)
    out = []
    for s in visible_solids(ctx.doc):
        c = S.bbox3(s.shape)
        if all(c[i] <= b[i + 3] + 1e-9 and b[i] <= c[i + 3] + 1e-9 for i in range(3)) and not ctx.doc.is_locked(s):
            out.append(s)
    return out


def _apply_mode(ctx: CommandContext, shapes: list, mode: str) -> int:
    """New: add each shape. Join: fuse into the solids they touch. Cut: subtract from them."""
    made = 0
    for shape in shapes:
        if mode == "New":
            new_solid(ctx, shape)
            made += 1
            continue
        targets = _touching(ctx, shape)
        if not targets:
            if mode == "Cut":
                ctx.echo("Nothing to cut there.")
                continue
            new_solid(ctx, shape)
            made += 1
            continue
        if mode == "Join":
            first = targets[0]
            result = shape
            for t in targets:
                result = S.union(result, t.shape)
            replace_shape(ctx, first, result)
            for t in targets[1:]:
                ctx.doc.delete(t.handle)
        else:
            for t in targets:
                cut = S.subtract(t.shape, shape)
                if S.solids_of(cut):
                    replace_shape(ctx, t, cut)
                else:
                    ctx.doc.delete(t.handle)
        made += 1
    return made


def _through_all(ctx: CommandContext, faces, plane: S.Plane) -> float:
    """A height reaching through every solid along the plane normal (both ways)."""
    reach = 0.0
    for s in visible_solids(ctx.doc):
        x0, y0, z0, x1, y1, z1 = S.bbox3(s.shape)
        for corner in ((x0, y0, z0), (x1, y1, z1), (x0, y1, z1), (x1, y0, z0)):
            reach = max(reach, abs(plane.to_local(corner)[2]))
    return reach + 1.0


# ====================================================================== solids from profiles
@command("EXTRUDE", label="Extrude", aliases=("EXT",), group=ALL_GROUP,
         description="Turn closed outlines into solids by giving them height. Can also cut holes or add to solids.",
         keywords=("solid from outline", "give height", "thicken", "pull up", "3d"))
def extrude_cmd(ctx: CommandContext):
    faces, plane, used = yield from collect_profiles(ctx, "extrude")
    if not faces:
        ctx.echo("Nothing to extrude.")
        return
    mode, both = "New", False
    last = ctx.memory.get("extrude_height", 10.0)
    while True:
        d = yield GetDistance(f"Specify height ({mode}{', both sides' if both else ''})", positive=False,
                              default=last, default_text=format_length(last, ctx.units),
                              keywords=kw("Both sides", "Join", "Cut", "New", "Through all"))
        if d == "Both sides":
            both = not both
            continue
        if d in ("Join", "Cut", "New"):
            mode = d
            continue
        if d == "Through all":
            mode = "Cut" if mode == "New" else mode
            d = _through_all(ctx, faces, plane)
            both = True
            break
        break
    if abs(d) < 1e-9:
        ctx.echo("The height can't be zero.")
        return
    ctx.memory["extrude_height"] = abs(d)
    n = np.array(plane.normal)
    shapes = [S.extrude(f, abs(d) * (2 if both else 1), direction=tuple(n if d > 0 else -n), both=both)
              for f in faces]
    made = _apply_mode(ctx, shapes, mode)
    for e in used:
        if ctx.doc.get(e.handle) is not None and e.space == MODEL_SPACE:
            ctx.doc.delete(e.handle)          # like AutoCAD: the outlines become the solid
    ctx.echo(f"{made} solid(s) {'made' if mode == 'New' else 'joined' if mode == 'Join' else 'cut'}.")


@command("REVOLVE", label="Revolve", aliases=("REV",), group=ALL_GROUP,
         description="Spin closed outlines around an axis to make round solids (shafts, bowls, rings).",
         keywords=("lathe", "turn", "spin", "rotate profile", "axisymmetric"))
def revolve_cmd(ctx: CommandContext):
    faces, plane, used = yield from collect_profiles(ctx, "revolve")
    if not faces:
        return
    a = yield GetPoint("Specify start point of the axis, or [X/Y] for the drawing's X or Y axis",
                       keywords=kw("X", "Y"), rubber=None)
    if a in ("X", "Y"):
        p0, p1 = (0.0, 0.0), ((1.0, 0.0) if a == "X" else (0.0, 1.0))
    else:
        b = yield GetPoint("Specify end point of the axis", base=a)
        p0, p1 = a, b
    w0, w1 = np.array(plane.to_world(*p0)), np.array(plane.to_world(*p1))
    if np.linalg.norm(w1 - w0) < 1e-9:
        ctx.echo("The axis needs two different points.")
        return
    ang = yield GetAngle("Specify angle of revolution", default=math.tau, default_text="360")
    shapes = [S.revolve(f, tuple(w0), tuple(w1 - w0), ang) for f in faces]
    for s in shapes:
        new_solid(ctx, s)
    for e in used:
        if e.space == MODEL_SPACE:
            ctx.doc.delete(e.handle)


@command("SWEEP", label="Sweep", aliases=(), group=ALL_GROUP,
         description="Move a closed outline along a path to make pipes, rails and mouldings.",
         keywords=("pipe", "along path", "tube", "moulding", "rail", "follow path"))
def sweep_cmd(ctx: CommandContext):
    faces, plane, used = yield from collect_profiles(ctx, "sweep")
    if not faces:
        return
    r = yield GetEntity("Select the path (line, arc, polyline or spline)")
    path_e, _ = r
    try:
        path = S.wire_from_entity(plane_of_space(ctx, path_e.space), path_e)
    except S.SolidError as exc:
        ctx.echo(str(exc))
        return
    for f in faces:
        new_solid(ctx, S.sweep(f, path, plane))
    for e in used:
        if e.space == MODEL_SPACE:
            ctx.doc.delete(e.handle)


@command("LOFT", label="Loft", aliases=(), group=ALL_GROUP,
         description="Make a solid that blends between outlines on different planes (in the order you pick them).",
         keywords=("blend", "transition", "between shapes", "taper between"))
def loft_cmd(ctx: CommandContext):
    picked: list[Entity] = []
    while True:
        r = yield GetEntity(f"Select profile {len(picked) + 1} in order (Enter when done)", allow_none=True)
        if r is None:
            break
        e, _ = r
        if not S.is_closed_profile(e):
            ctx.echo("Pick closed outlines (circles, closed polylines…).")
            continue
        if any(p.handle == e.handle for p in picked):
            continue
        picked.append(e)
    if len(picked) < 2:
        ctx.echo("Pick at least two profiles, on different planes (sketches).")
        return
    gap = None
    planes = [plane_of_space(ctx, e.space) for e in picked]
    if all(p == planes[0] for p in planes):
        gap = yield GetDistance("They're all on one plane. Specify the distance between them", positive=True)
    wires = []
    for i, e in enumerate(picked):
        pl = planes[i].offset(gap * i) if gap else planes[i]
        wires.append(S.wire_from_entity(pl, e))
    new_solid(ctx, S.loft(wires))


# ====================================================================== primitives
def _base_z(ctx: CommandContext) -> float:
    return ctx.point_z


@command("BOX", label="Box", aliases=(), group=ALL_GROUP,
         description="Make a box from two corners and a height.", keywords=("cube", "block solid", "rectangular solid"))
def box_cmd(ctx: CommandContext):
    a = yield GetPoint("Specify first corner", rubber=None)
    z = _base_z(ctx)
    b = yield GetPoint("Specify other corner", base=a, rubber="rect", keywords=kw("Cube"))
    if b == "Cube":
        L = yield GetDistance("Specify length", base=a, positive=True)
        new_solid(ctx, S.box((a[0], a[1], z), (a[0] + L, a[1] + L, z + L)))
        return
    h = yield GetDistance("Specify height", base=b, positive=False)
    new_solid(ctx, S.box((a[0], a[1], z), (b[0], b[1], z + h)))


@command("CYLINDER", label="Cylinder", aliases=("CYL",), group=ALL_GROUP,
         description="Make a cylinder from a center, radius and height.", keywords=("rod", "post", "shaft", "column"))
def cylinder_cmd(ctx: CommandContext):
    c = yield GetPoint("Specify center point of base", rubber=None)
    z = _base_z(ctx)
    r = yield GetDistance("Specify base radius", base=c, positive=True, keywords=kw("Diameter"))
    if r == "Diameter":
        r = (yield GetDistance("Specify diameter", base=c, positive=True)) / 2
    h = yield GetDistance("Specify height", base=c, positive=False)
    new_solid(ctx, S.cylinder((c[0], c[1], z), r, h))


@command("CONE", label="Cone", aliases=(), group=ALL_GROUP,
         description="Make a cone (or a cut-off cone) from a center, radius and height.", keywords=("taper", "funnel"))
def cone_cmd(ctx: CommandContext):
    c = yield GetPoint("Specify center point of base", rubber=None)
    z = _base_z(ctx)
    r = yield GetDistance("Specify base radius", base=c, positive=True)
    top = 0.0
    h = yield GetDistance("Specify height or [Top radius]", base=c, positive=False, keywords=kw("Top radius"))
    if h == "Top radius":
        top = yield GetDistance("Specify top radius", default=0.0, default_text="0", positive=False)
        h = yield GetDistance("Specify height", base=c, positive=False)
    new_solid(ctx, S.cone((c[0], c[1], z), r, max(top, 0.0), h))


@command("SPHERE", label="Sphere", aliases=(), group=ALL_GROUP,
         description="Make a sphere from a center and radius.", keywords=("ball", "globe"))
def sphere_cmd(ctx: CommandContext):
    c = yield GetPoint("Specify center point", rubber=None)
    z = _base_z(ctx)
    r = yield GetDistance("Specify radius", base=c, positive=True)
    new_solid(ctx, S.sphere((c[0], c[1], z), r))


@command("TORUS", label="Torus", aliases=("TOR",), group=ALL_GROUP,
         description="Make a ring (donut) from a center, ring radius and tube radius.", keywords=("ring", "donut", "o-ring"))
def torus_cmd(ctx: CommandContext):
    c = yield GetPoint("Specify center point", rubber=None)
    z = _base_z(ctx)
    r = yield GetDistance("Specify radius of the ring", base=c, positive=True)
    t = yield GetDistance("Specify radius of the tube", positive=True)
    new_solid(ctx, S.torus((c[0], c[1], z), r, t))


@command("WEDGE", label="Wedge", aliases=("WE",), group=ALL_GROUP,
         description="Make a wedge: a box sloping from full height down to nothing.", keywords=("ramp", "slope", "incline"))
def wedge_cmd(ctx: CommandContext):
    a = yield GetPoint("Specify first corner", rubber=None)
    z = _base_z(ctx)
    b = yield GetPoint("Specify other corner", base=a, rubber="rect")
    h = yield GetDistance("Specify height", base=b, positive=True)
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    new_solid(ctx, S.wedge((x0, y0, z), abs(b[0] - a[0]), abs(b[1] - a[1]), h))


# ====================================================================== booleans
@command("UNION", label="Union", aliases=("UNI",), group=ALL_GROUP,
         description="Join solids into one.", keywords=("combine", "merge solids", "add solids", "weld"))
def union_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select solids to join")
    if len(sols) < 2:
        ctx.echo("Select at least two solids.")
        return
    result = sols[0].shape
    for s in sols[1:]:
        result = S.union(result, s.shape)
    replace_shape(ctx, sols[0], result)
    for s in sols[1:]:
        ctx.doc.delete(s.handle)


@command("SUBTRACT", label="Subtract", aliases=("SU",), group=ALL_GROUP,
         description="Cut solids out of other solids (holes, pockets, notches).", keywords=("cut", "remove material", "hole", "difference"))
def subtract_cmd(ctx: CommandContext):
    keep = yield from ask_solids(ctx, "Select solids to subtract FROM")
    if not keep:
        return
    tools = yield from ask_solids(ctx, "Select solids to subtract (they're removed)", use_pickfirst=False)
    tools = [t for t in tools if t.handle not in {k.handle for k in keep}]
    if not tools:
        ctx.echo("Nothing to subtract.")
        return
    for k in keep:
        result = k.shape
        for t in tools:
            result = S.subtract(result, t.shape)
        if S.solids_of(result):
            replace_shape(ctx, k, result)
        else:
            ctx.doc.delete(k.handle)
            ctx.echo("A solid was completely removed.")
    for t in tools:
        ctx.doc.delete(t.handle)


@command("INTERSECT", label="Intersect", aliases=("IN",), group=ALL_GROUP,
         description="Keep only the part where solids overlap.", keywords=("common", "overlap", "shared volume"))
def intersect_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select solids to intersect")
    if len(sols) < 2:
        ctx.echo("Select at least two solids.")
        return
    result = sols[0].shape
    for s in sols[1:]:
        result = S.intersect(result, s.shape)
    replace_shape(ctx, sols[0], result)
    for s in sols[1:]:
        ctx.doc.delete(s.handle)


# ====================================================================== edge and face edits
def _pick_edges(ctx: CommandContext, prompt: str, keyword: str, value_name: str, default: float):
    """Pick edges of one solid; the keyword changes the value. Returns (solid, edge indices, value)."""
    solid, picked, value = None, [], default
    while True:
        r = yield GetEdge(f"{prompt} ({value_name} {format_length(value, ctx.units)}; Enter when done)",
                          keywords=(Keyword(keyword),), allow_none=True,
                          solid=solid.handle if solid is not None else None)
        if r is None:
            break
        if r == keyword:
            value = yield GetDistance(f"Specify {value_name}", positive=True, default=value,
                                     default_text=format_length(value, ctx.units))
            continue
        if solid is None:
            solid = r.entity
        if r.edge in picked:
            picked.remove(r.edge)
            ctx.echo("Edge removed from the selection.")
        else:
            picked.append(r.edge)
            ctx.echo(f"{len(picked)} edge(s) picked.")
    return solid, picked, value


@command("FILLETEDGE", label="Fillet Edge", aliases=("FE",), group=ALL_GROUP,
         description="Round the edges of a solid.", keywords=("round edge", "radius edge", "soften edge", "3d fillet"))
def filletedge_cmd(ctx: CommandContext):
    solid, picked, r = yield from _pick_edges(ctx, "Select edges to round or [Radius]", "Radius", "radius",
                                              ctx.memory.get("fillet3d", 1.0))
    if not picked:
        return
    ctx.memory["fillet3d"] = r
    edges = S.edges(solid.shape)
    replace_shape(ctx, solid, S.fillet(solid.shape, [edges[i] for i in picked], r))


@command("CHAMFEREDGE", label="Chamfer Edge", aliases=("CE",), group=ALL_GROUP,
         description="Bevel the edges of a solid.", keywords=("bevel edge", "3d chamfer", "break edge"))
def chamferedge_cmd(ctx: CommandContext):
    solid, picked, d = yield from _pick_edges(ctx, "Select edges to bevel or [Distance]", "Distance", "distance",
                                              ctx.memory.get("chamfer3d", 1.0))
    if not picked:
        return
    ctx.memory["chamfer3d"] = d
    edges = S.edges(solid.shape)
    replace_shape(ctx, solid, S.chamfer(solid.shape, [edges[i] for i in picked], d))


@command("SHELL", label="Shell", aliases=(), group=ALL_GROUP,
         description="Hollow out a solid, leaving walls of a set thickness; picked faces are left open.",
         keywords=("hollow", "wall thickness", "box with open top", "container"))
def shell_cmd(ctx: CommandContext):
    solid, open_faces = None, []
    while True:
        r = yield GetFace("Select faces to leave open (Enter when done; none = closed hollow)", allow_none=True)
        if r is None:
            break
        if solid is None:
            solid = r.entity
        elif r.entity.handle != solid.handle:
            ctx.echo("Pick faces of the same solid.")
            continue
        if r.face not in open_faces:
            open_faces.append(r.face)
    if solid is None:
        sols = yield from ask_solids(ctx, "Select the solid to hollow out")
        if not sols:
            return
        solid = sols[0]
    t = yield GetDistance("Specify wall thickness", positive=True, default=ctx.memory.get("shell", 1.0),
                          default_text=format_length(ctx.memory.get("shell", 1.0), ctx.units))
    ctx.memory["shell"] = t
    fs = S.faces(solid.shape)
    replace_shape(ctx, solid, S.shell(solid.shape, [fs[i] for i in open_faces], t))


@command("PRESSPULL", label="Press/Pull", aliases=("PP",), group=ALL_GROUP,
         description="Click a flat face and push it in or pull it out by a distance.",
         keywords=("push pull", "move face", "thicken face", "make taller"))
def presspull_cmd(ctx: CommandContext):
    r = yield GetFace("Click a flat face of a solid", planar_only=True)
    d = yield GetDistance("Specify distance (positive pulls out, negative pushes in)", positive=False)
    f = S.faces(r.entity.shape)[r.face]
    replace_shape(ctx, r.entity, S.presspull(r.entity.shape, f, d))


@command("SLICE", label="Slice", aliases=("SL",), group=ALL_GROUP,
         description="Cut solids in two with a plane. In the plan view, pick two points of a vertical cutting line.",
         keywords=("cut in two", "split solid", "section cut"))
def slice_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select solids to slice")
    if not sols:
        return
    a = yield GetPoint("Specify first point of the cutting line, or [XY/YZ/ZX] for a plane through a point",
                       keywords=kw("XY", "YZ", "ZX"), rubber=None)
    if a in ("XY", "YZ", "ZX"):
        p = yield GetPoint("Specify a point on the plane (type x,y,z for a height)", rubber=None)
        point = (p[0], p[1], ctx.point_z)
        normal = {"XY": (0, 0, 1), "YZ": (1, 0, 0), "ZX": (0, 1, 0)}[a]
    else:
        b = yield GetPoint("Specify second point of the cutting line", base=a)
        d = np.array([b[0] - a[0], b[1] - a[1], 0.0])
        if np.linalg.norm(d) < 1e-9:
            ctx.echo("Pick two different points.")
            return
        normal = tuple(np.cross(d, [0, 0, 1.0]) / np.linalg.norm(d))
        point = (a[0], a[1], 0.0)
    keep = yield GetPoint("Keep [Both/First side/Other side]", keywords=kw("Both", "First side", "Other side"),
                          default="Both", default_text="Both", rubber=None)
    cut = 0
    for s in sols:
        try:
            pos, neg = S.slice_solid(s.shape, point, normal)
        except S.SolidError:
            continue
        cut += 1
        if keep in ("Both", "First side"):
            replace_shape(ctx, s, pos)
            if keep == "Both":
                new_solid(ctx, neg, like=s)
        else:
            replace_shape(ctx, s, neg)
    ctx.echo(f"{cut} solid(s) sliced." if cut else "The plane doesn't cut through those solids.")


# ====================================================================== moving in 3D
def _parse_xyz(ctx, text: str):
    from ..core.units import parse_length
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 3:
        raise ValueError("Type three values: x,y,z (e.g. 0,0,10)")
    return tuple(parse_length(p, ctx.units) for p in parts)


@command("3DMOVE", label="3D Move", aliases=("3M",), group=ALL_GROUP,
         description="Move solids by x, y and z (up and down too).", keywords=("move up", "raise", "lower", "elevate"))
def move3d_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select solids to move")
    if not sols:
        return
    while True:
        t = yield GetString("Specify displacement as x,y,z (e.g. 0,0,25)")
        try:
            d = _parse_xyz(ctx, t)
            break
        except ValueError as exc:
            ctx.echo(str(exc))
    for s in sols:
        replace_shape(ctx, s, S.translate(s.shape, d))


@command("3DROTATE", label="3D Rotate", aliases=("ROTATE3D", "3R"), group=ALL_GROUP,
         description="Turn solids around the X, Y or Z axis through a point (e.g. stand a part on its side).",
         keywords=("tip over", "turn on side", "rotate about x", "rotate about y"))
def rotate3d_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select solids to rotate")
    if not sols:
        return
    ax = yield GetPoint("Rotate around which axis? [X/Y/Z]", keywords=kw("X", "Y", "Z"), default="Z",
                        default_text="Z", rubber=None)
    p = yield GetPoint("Specify a point on the axis (type x,y,z for a height)", rubber=None)
    point = (p[0], p[1], ctx.point_z)
    ang = yield GetAngle("Specify rotation angle")
    d = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[ax if ax in ("X", "Y", "Z") else "Z"]
    for s in sols:
        replace_shape(ctx, s, S.rotate(s.shape, point, d, ang))


@command("MASSPROP", label="Mass Properties", aliases=("MP",), group=ALL_GROUP,
         description="Volume, surface area, center of mass and size of solids.",
         keywords=("volume", "weight", "center of gravity", "surface area", "measure solid"))
def massprop_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select solids")
    u = ctx.units
    for s in sols:
        mp = S.mass_properties(s.shape)
        x0, y0, z0, x1, y1, z1 = mp["bbox"]
        cx, cy, cz = mp["centroid"]
        k = 25.4 if u.mode.value != "mm" else 1.0
        vol = mp["volume"] / k ** 3
        area = mp["area"] / k ** 2
        unit = "in" if k != 1 else "mm"
        ctx.echo(f"Solid {s.name or s.handle}: volume {vol:,.3f} {unit}³, surface area {area:,.3f} {unit}², "
                 f"center of mass {format_length(cx, u)}, {format_length(cy, u)}, {format_length(cz, u)}; "
                 f"size {format_length(x1 - x0, u)} × {format_length(y1 - y0, u)} × {format_length(z1 - z0, u)}")


# ====================================================================== converting
@command("FLATSHOT", label="Flatshot", aliases=("FLAT",), group=ALL_GROUP,
         description="Make 2D lines of how the selected solids look from above (their edges), in the plan.",
         keywords=("flatten", "2d from 3d", "outline of solid", "plan of solid"))
def flatten_cmd(ctx: CommandContext):
    sols = yield from ask_solids(ctx, "Select solids to flatten")
    from ..core.model import Line
    n = 0
    for s in sols:
        view = S.hidden_line_view(s.shape, (0, 0, -1), up=(0, 1, 0))
        right, upv = S.view_axes((0, 0, -1), (0, 1, 0))
        for pl in view["visible"]:
            for a, b in zip(pl[:-1], pl[1:]):
                pa = (float(a[0] * right[0] + a[1] * upv[0]), float(a[0] * right[1] + a[1] * upv[1]))
                pb = (float(b[0] * right[0] + b[1] * upv[0]), float(b[0] * right[1] + b[1] * upv[1]))
                if math.dist(pa, pb) > 1e-9:
                    ctx.doc.add(Line(p1=pa, p2=pb), use_current_props=True)
                    n += 1
    ctx.echo(f"{n} lines made.")


_ = (Circle, Polyline, GetNumber)
