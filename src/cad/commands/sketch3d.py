"""Sketches: 2D drawing planes placed in 3D (on XY/XZ/YZ, offset, or on a flat face of a solid)."""
from __future__ import annotations

import numpy as np

from ..core import solids as S
from ..core.model import MODEL_SPACE, Line, Polyline, is_sketch_space
from ..core.model.document import Layer
from ..core.model.tables import SKETCH_PREFIX, Sketch, sketch_space
from ..core.solid_pick import visible_solids
from .framework import CommandContext, GetDistance, GetFace, GetKeyword, GetString, command, kw

REFERENCE_LAYER = "Sketch reference"
STANDARD = {"XY": S.XY, "XZ": S.XZ, "YZ": S.YZ}


def next_sketch_name(doc) -> str:
    n = len(doc.sketches) + 1
    while f"Sketch{n}" in doc.sketches:
        n += 1
    return f"Sketch{n}"


def make_sketch(doc, plane: S.Plane, name: str | None = None) -> Sketch:
    name = name or next_sketch_name(doc)
    sk = Sketch(name=name, origin=tuple(float(v) for v in plane.origin),
                xdir=tuple(float(v) for v in plane.xdir), normal=tuple(float(v) for v in plane.normal))
    doc.set_item("sketch", name, sk)
    return sk


def _reference_layer(doc) -> str:
    if doc.find_layer(REFERENCE_LAYER) is None:
        doc.add_layer(Layer(REFERENCE_LAYER, color=8, locked=True, plot=False,
                            description="Edges of solids seen from sketches (made automatically)"))
    return REFERENCE_LAYER


def refresh_reference(doc, sketch: Sketch) -> int:
    """Replace the sketch's reference lines with the current solids seen square-on to its plane."""
    space = sketch.space
    for e in [e for e in doc.entities.values() if e.space == space and e.layer == REFERENCE_LAYER]:
        doc.delete(e.handle)
    sols = visible_solids(doc)
    if not sols:
        return 0
    layer = _reference_layer(doc)
    plane = sketch.plane()
    right, up = S.view_axes(tuple(-np.array(plane.normal)), plane.ydir)
    o = np.array(plane.origin)
    xd, yd = np.array(plane.xdir), np.array(plane.ydir)
    hidden_lt = "HIDDEN" if "HIDDEN" in doc.linetypes else "ByLayer"
    count = 0
    seen: set = set()

    def key(pts):
        k = tuple((round(x, 6) + 0.0, round(y, 6) + 0.0) for x, y in pts)
        return min(k, k[::-1])
    for s in sols:
        view = S.hidden_line_view(s.shape, tuple(-np.array(plane.normal)), up=plane.ydir)
        for kind in ("visible", "hidden"):
            for pl in view[kind]:
                world = [p[0] * right + p[1] * up for p in pl]      # on the plane through the world origin
                loc = [(float((w - o) @ xd), float((w - o) @ yd)) for w in world]
                clean = [loc[0]] + [b for a, b in zip(loc, loc[1:]) if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-9]
                if len(clean) < 2 or key(clean) in seen:
                    continue            # hidden edges right under visible ones add nothing
                seen.add(key(clean))
                props = dict(layer=layer, color=256, space=space,
                             linetype=hidden_lt if kind == "hidden" else "ByLayer")
                if len(clean) == 2:
                    doc.add(Line(p1=clean[0], p2=clean[1], **props))
                else:
                    doc.add(Polyline(vertices=tuple((x, y, 0.0) for x, y in clean), closed=False, **props))
                count += 1
    return count


def _ask_plane(ctx: CommandContext):
    choice = yield GetKeyword("Sketch on [XY (top)/XZ (front)/YZ (side)/Face/Offset]",
                              keywords=kw("XY", "XZ", "YZ", "Face", "Offset"), default="XY", default_text="XY")
    if choice in STANDARD:
        return STANDARD[choice]
    if choice == "Face":
        r = yield GetFace("Click a flat face of a solid", planar_only=True)
        pl = S.aligned_face_plane(S.faces(r.entity.shape)[r.face])
        if pl is None:
            ctx.echo("That face isn't flat.")
            return None
        return pl
    base = yield GetKeyword("Offset from [XY/XZ/YZ]", keywords=kw("XY", "XZ", "YZ"), default="XY", default_text="XY")
    d = yield GetDistance("Specify offset distance", positive=False)
    return STANDARD[base].offset(d)


@command("SKETCH", label="Sketch", aliases=("SK",), group="3D",
         description="Start a 2D drawing plane in 3D (top, front, side, offset or on a face). "
                     "Draw on it with any 2D tool, then Extrude or Revolve.",
         keywords=("work plane", "drawing plane", "ucs", "draw on face", "2d in 3d"), transaction=True)
def sketch_cmd(ctx: CommandContext):
    plane = yield from _ask_plane(ctx)
    if plane is None:
        return
    sk = make_sketch(ctx.doc, plane)
    n = refresh_reference(ctx.doc, sk)
    ctx.echo(f"{sk.name} made{f' with {n} reference lines from your solids' if n else ''}. "
             "Draw on it, then type EXITSKETCH (or click the Model tab) when done.")
    ctx.ui.run_ui_action("SHOWLAYOUT:" + sk.space)


@command("EDITSKETCH", label="Edit Sketch", aliases=("ES",), group="3D",
         description="Open an existing sketch to draw on it again (its reference lines are refreshed).",
         keywords=("open sketch", "go to sketch"))
def editsketch_cmd(ctx: CommandContext):
    if not ctx.doc.sketches:
        ctx.echo("There are no sketches yet. Use SKETCH.")
        return
    names = sorted(ctx.doc.sketches)
    name = yield GetString(f"Sketch name ({', '.join(names)})", default=names[-1], default_text=names[-1])
    sk = next((ctx.doc.sketches[n] for n in names if n.lower() == name.strip().lower()), None)
    if sk is None:
        ctx.echo(f"No sketch named {name}.")
        return
    refresh_reference(ctx.doc, sk)
    ctx.ui.run_ui_action("SHOWLAYOUT:" + sk.space)


@command("EXITSKETCH", label="Finish Sketch", aliases=("XS",), group="3D",
         description="Leave the sketch and go back to the model.", keywords=("done sketch", "close sketch"),
         transaction=False)
def exitsketch_cmd(ctx: CommandContext):
    if not is_sketch_space(ctx.space):
        ctx.echo("You're not in a sketch.")
    ctx.ui.run_ui_action("SHOWLAYOUT:" + MODEL_SPACE)
    yield from ()


@command("DELSKETCH", label="Delete Sketch", aliases=(), group="3D",
         description="Delete a sketch and everything drawn on it (solids made from it stay).",
         keywords=("remove sketch",))
def delsketch_cmd(ctx: CommandContext):
    if not ctx.doc.sketches:
        ctx.echo("There are no sketches.")
        return
    names = sorted(ctx.doc.sketches)
    cur = ctx.space[len(SKETCH_PREFIX):] if is_sketch_space(ctx.space) else names[-1]
    name = yield GetString(f"Sketch to delete ({', '.join(names)})", default=cur, default_text=cur)
    key = next((n for n in names if n.lower() == name.strip().lower()), None)
    if key is None:
        ctx.echo(f"No sketch named {name}.")
        return
    delete_sketch(ctx.doc, key)
    if ctx.space == sketch_space(key):
        ctx.ui.run_ui_action("SHOWLAYOUT:" + MODEL_SPACE)


def delete_sketch(doc, name: str) -> None:
    space = sketch_space(name)
    for e in [e for e in doc.entities.values() if e.space == space]:
        doc.delete(e.handle)
    doc.remove_item("sketch", name)
