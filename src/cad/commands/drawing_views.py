"""2D drawings from 3D: front/top/side/iso views of solids on a layout, with hidden lines, kept up to date.

A drawing view is a block named "View<n>" holding the projected lines at full size; it is inserted on the
sheet at the view scale. Its settings are kept as JSON in the block description so VIEWUPDATE can redo it.
"""
from __future__ import annotations

import json

import numpy as np

from ..core import solids as S
from ..core.layouts import create_layout, fit_scale
from ..core.model import BlockReference, Line, Polyline, Viewport, is_sketch_space
from ..core.model.document import Layer
from ..core.model.tables import BlockDefinition
from ..core.solid_pick import visible_solids
from .framework import CommandContext, GetKeyword, GetNumber, GetPoint, Keyword, command

VISIBLE_LAYER = "View visible"
HIDDEN_LAYER = "View hidden"

# name: (view direction from the eye into the model, up)
DIRECTIONS = {
    "Front": ((0, 1, 0), (0, 0, 1)), "Back": ((0, -1, 0), (0, 0, 1)),
    "Top": ((0, 0, -1), (0, 1, 0)), "Bottom": ((0, 0, 1), (0, -1, 0)),
    "Right": ((-1, 0, 0), (0, 0, 1)), "Left": ((1, 0, 0), (0, 0, 1)),
    "SW Iso": ((1, 1, -1), (0, 0, 1)), "SE Iso": ((-1, 1, -1), (0, 0, 1)),
    "NE Iso": ((-1, -1, -1), (0, 0, 1)), "NW Iso": ((1, -1, -1), (0, 0, 1)),
}
_KEYS = {"Front": "F", "Back": "BA", "Top": "T", "Bottom": "BO", "Right": "R", "Left": "L",
         "SW Iso": "SW", "SE Iso": "SE", "NE Iso": "NE", "NW Iso": "NW"}
# third-angle projection (ASME): from Front, the view placed above is Top, to the right is Right, ...
PROJECTED = {
    "Front": {"up": "Top", "down": "Bottom", "right": "Right", "left": "Left"},
    "Top": {"down": "Front", "up": "Back", "right": "Right", "left": "Left"},
    "Right": {"left": "Front", "right": "Back", "up": "Top", "down": "Bottom"},
}


def view_settings(bdef: BlockDefinition) -> dict | None:
    try:
        d = json.loads(bdef.description)
    except (ValueError, TypeError):
        return None
    return d.get("drawing_view") if isinstance(d, dict) else None


def _ensure_layers(doc) -> None:
    if doc.find_layer(VISIBLE_LAYER) is None:
        doc.add_layer(Layer(VISIBLE_LAYER, color=7, lineweight=0.5, description="Edges seen in drawing views"))
    if doc.find_layer(HIDDEN_LAYER) is None:
        doc.add_layer(Layer(HIDDEN_LAYER, color=8, linetype="HIDDEN", lineweight=0.25,
                            description="Hidden edges in drawing views"))


def view_entities(doc, settings: dict) -> tuple[list, tuple[float, float]]:
    """Projected lines (full size) for the view, centered on (0, 0), and the view's size."""
    handles = settings.get("solids")
    sols = [s for s in visible_solids(doc) if (handles is None or s.handle in handles) and not s.hole]
    if not sols:
        return [], (0.0, 0.0)
    shape = sols[0].shape if len(sols) == 1 else S.compound([s.shape for s in sols])
    direction, up = DIRECTIONS[settings["view"]]
    view = S.hidden_line_view(shape, direction, up)
    kinds = ["visible"] + (["hidden"] if settings.get("hidden", True) and "Iso" not in settings["view"] else [])
    allpts = [p for k in kinds for pl in view[k] for p in pl]
    if not allpts:
        return [], (0.0, 0.0)
    a = np.array(allpts)
    c = (a.min(axis=0) + a.max(axis=0)) / 2
    size = tuple(float(v) for v in a.max(axis=0) - a.min(axis=0))
    scale = float(settings.get("scale", 1.0))
    out = []
    seen = set()
    for kind in kinds:
        layer = VISIBLE_LAYER if kind == "visible" else HIDDEN_LAYER
        for pl in view[kind]:
            pts = [(float(x - c[0]), float(y - c[1])) for x, y in pl]
            pts = [pts[0]] + [q for p, q in zip(pts, pts[1:]) if abs(p[0] - q[0]) + abs(p[1] - q[1]) > 1e-9]
            if len(pts) < 2:
                continue
            key = tuple((round(x, 5), round(y, 5)) for x, y in pts)
            key = min(key, key[::-1])
            if key in seen:
                continue           # a hidden edge exactly behind a visible one
            seen.add(key)
            props = dict(layer=layer, color=256, linetype="ByLayer", ltscale=1.0 / scale if scale > 0 else 1.0)
            if len(pts) == 2:
                out.append(Line(p1=pts[0], p2=pts[1], **props))
            else:
                out.append(Polyline(vertices=tuple((x, y, 0.0) for x, y in pts), **props))
    return out, size


def make_view_block(doc, name: str, settings: dict) -> tuple[float, float]:
    ents, size = view_entities(doc, settings)
    ents = [e.with_props(handle=i + 1) if hasattr(e, "handle") else e for i, e in enumerate(ents)]
    doc.set_item("block", name, BlockDefinition(name=name, base=(0.0, 0.0), entities=tuple(ents),
                                                description=json.dumps({"drawing_view": settings})))
    return size


def _next_view_name(doc) -> str:
    n = 1
    while f"View{n}" in doc.blocks:
        n += 1
    return f"View{n}"


def place_view(ctx: CommandContext, settings: dict, at) -> BlockReference:
    doc = ctx.doc
    _ensure_layers(doc)
    name = _next_view_name(doc)
    make_view_block(doc, name, settings)
    s = float(settings["scale"])
    return doc.add(BlockReference(name=name, insert=(float(at[0]), float(at[1])), sx=s, sy=s,
                                  layer=VISIBLE_LAYER, space=ctx.space))


def _sheet_space(ctx: CommandContext):
    """Make sure we're drawing on a layout. Returns the layout name."""
    doc = ctx.doc
    if ctx.space in doc.layouts:
        return ctx.space
    name = None
    for lo in sorted(doc.layouts.values(), key=lambda lo: lo.order):
        if not any(e.space == lo.name and isinstance(e, BlockReference) and e.name in doc.blocks
                   and view_settings(doc.blocks[e.name]) for e in doc.entities.values()):
            name = lo.name
            break
    if name is None:
        n = len(doc.layouts) + 1
        while f"Layout{n}" in doc.layouts:
            n += 1
        name = f"Layout{n}"
        create_layout(doc, name)
        for e in [e for e in doc.entities.values() if e.space == name and isinstance(e, Viewport)]:
            doc.delete(e.handle)            # the views replace the model viewport
    return name


@command("VIEWBASE", label="Base View", aliases=("VB",), group="3D",
         description="Put 2D views of your solids (front, top, side, iso) on a layout sheet, with hidden lines. "
                     "Then click around it for projected views.",
         keywords=("drawing views", "orthographic", "2d drawing from 3d", "shop drawing", "projected view",
                   "front top side"))
def viewbase_cmd(ctx: CommandContext):
    doc = ctx.doc
    sols = [s for s in visible_solids(doc) if not s.hole]
    if not sols:
        ctx.echo("There are no solids to draw. Make some first (EXTRUDE, BOX…).")
        return
    if ctx.space not in doc.layouts or is_sketch_space(ctx.space):
        name = _sheet_space(ctx)
        ctx.space = name
        ctx.ui.run_ui_action("SHOWLAYOUT:" + name)
        ctx.echo(f"Drawing views go on layout {name}.")
    kws = tuple(Keyword(n, k) for n, k in _KEYS.items())
    view = yield GetKeyword("Base view [Front/Top/Right/Left/BAck/BOttom/SW/SE/NE/NW iso]", keywords=kws,
                            default="Front", default_text="Front")
    lo = doc.layouts[ctx.space]
    w, h = lo.size
    shape = sols[0].shape if len(sols) == 1 else S.compound([s.shape for s in sols])
    x0, y0, z0, x1, y1, z1 = S.bbox3(shape)
    biggest = max(x1 - x0, y1 - y0, z1 - z0, 1e-6)
    auto = fit_scale((0, 0, biggest * 2.6, biggest * 2.6), w - 40, h - 60, doc.header.units.mode)
    scale = yield GetNumber(f"Specify scale (paper per model, e.g. 0.5 = 1:2)", default=auto,
                            default_text=_scale_text(auto), minimum=1e-6)
    hidden = view not in ("SW Iso", "SE Iso", "NE Iso", "NW Iso")
    base_at = yield GetPoint("Specify location of base view", rubber=None, default=(w * 0.3, h * 0.4),
                             default_text="left of the sheet")
    settings = {"view": view, "scale": float(scale), "hidden": hidden, "solids": None}
    base_ref = place_view(ctx, settings, base_at)
    doc.flush()
    ctx.echo(f"{view} view placed at 1:{_ratio(scale)}.")
    # projected views: click above / beside / diagonally
    while True:
        pt = yield GetPoint("Specify location of projected view (Enter when done)", base=base_at, allow_none=True)
        if pt is None:
            break
        dx, dy = pt[0] - base_at[0], pt[1] - base_at[1]
        if abs(dx) > 3 * abs(dy) or abs(dy) > 3 * abs(dx):       # straight out: projected; else iso
            side = ("right" if dx > 0 else "left") if abs(dx) > abs(dy) else ("up" if dy > 0 else "down")
            pv = PROJECTED.get(view, {}).get(side)
            if pv is None:
                ctx.echo(f"Projected views come from Front, Top or Right views. Placing an iso view.")
                pv, at = "SE Iso", pt
            else:
                at = (pt[0], base_at[1]) if side in ("left", "right") else (base_at[0], pt[1])
        else:
            pv = {(1, 1): "NE Iso", (-1, 1): "NW Iso", (1, -1): "SE Iso", (-1, -1): "SW Iso"}[
                (1 if dx > 0 else -1, 1 if dy > 0 else -1)] if view in ("Front", "Top", "Right") else "SE Iso"
            pv = "SE Iso" if pv in ("NE Iso", "NW Iso") else pv     # iso views from above read best
            at = pt
        place_view(ctx, {"view": pv, "scale": float(scale), "hidden": "Iso" not in pv, "solids": None}, at)
        doc.flush()
        ctx.echo(f"{pv} view placed.")
    _ = base_ref


def _ratio(scale: float) -> str:
    if scale >= 1:
        return f"{1 / scale:g}" if abs(1 / scale - round(1 / scale)) > 1e-9 else str(round(1 / scale))
    r = 1 / scale
    return f"{r:g}"


def _scale_text(scale: float) -> str:
    return f"{scale:g} (1:{_ratio(scale)})" if scale < 1 else f"{scale:g}"


def update_views(doc) -> int:
    n = 0
    for name, bdef in list(doc.blocks.items()):
        st = view_settings(bdef)
        if st is None:
            continue
        make_view_block(doc, name, st)
        n += 1
    return n


@command("VIEWUPDATE", label="Update Views", aliases=("VU",), group="3D",
         description="Redraw all drawing views from the solids as they are now (after edits).",
         keywords=("refresh views", "regenerate drawing", "update drawing"))
def viewupdate_cmd(ctx: CommandContext):
    n = update_views(ctx.doc)
    ctx.echo(f"{n} drawing view(s) updated." if n else "There are no drawing views. Use VIEWBASE.")
    yield from ()
