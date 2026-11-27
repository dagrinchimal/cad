"""Looking at the model in 3D: standard views, visual styles, perspective, back to the plan."""
from __future__ import annotations

from ..render.camera3d import PRESETS
from ..render.scene3d import STYLES
from .framework import CommandContext, GetKeyword, Keyword, command

_VIEW_KEYS = {"Top": "T", "Bottom": "B", "Front": "F", "Back": "BA", "Left": "L", "Right": "R",
              "SW Iso": "SW", "SE Iso": "SE", "NE Iso": "NE", "NW Iso": "NW"}


@command("VIEW3D", label="3D View", aliases=("3D",), group="3D", transaction=False,
         description="Look at the model in 3D from a standard direction (top, front, isometric…).",
         keywords=("isometric", "3d view", "iso", "front view", "side view", "look at"))
def view3d_cmd(ctx: CommandContext):
    kws = tuple(Keyword(n, k) for n, k in _VIEW_KEYS.items()) + (Keyword("Perspective", "P"),
                                                                    Keyword("Parallel", "PA"))
    v = yield GetKeyword("View [Top/Bottom/Front/BAck/Left/Right/SW/SE/NE/NW iso/Perspective/PArallel]",
                         keywords=kws, default="SW Iso", default_text="SW Iso")
    if v == "Perspective":
        ctx.ui.run_ui_action("PERSPECTIVE:On")
    elif v == "Parallel":
        ctx.ui.run_ui_action("PERSPECTIVE:Off")
    elif v in PRESETS:
        ctx.ui.run_ui_action("VIEW3D:" + v)


@command("ORBIT", label="Orbit", aliases=("3DORBIT", "3DO"), group="3D", transaction=False,
         description="Switch to the 3D view to turn the model around: drag with the left mouse button.",
         keywords=("rotate view", "spin view", "turn view", "look around"))
def orbit_cmd(ctx: CommandContext):
    ctx.ui.run_ui_action("VIEW3D:")
    ctx.echo("Drag to orbit, middle- or right-drag to pan, wheel to zoom. Type PLAN to go back to the flat view.")
    yield from ()


@command("PLAN", label="Plan View", aliases=("2D",), group="3D", transaction=False,
         description="Go back to the flat top-down drawing view (where 2D tools work).",
         keywords=("top view 2d", "flat view", "back to 2d", "exit 3d"))
def plan_cmd(ctx: CommandContext):
    ctx.ui.run_ui_action("PLAN")
    yield from ()


@command("VSCURRENT", label="Visual Style", aliases=("VS", "SHADEMODE"), group="3D", transaction=False,
         description="How solids look in the 3D view: wireframe, hidden lines, shaded, shaded with edges, x-ray.",
         keywords=("shade", "wireframe", "render style", "hidden line", "x-ray", "transparent"))
def vscurrent_cmd(ctx: CommandContext):
    keys = {"Wireframe": "W", "Hidden": "H", "Shaded": "S", "Shaded with edges": "E", "X-ray": "X"}
    v = yield GetKeyword("Visual style [Wireframe/Hidden/Shaded/shaded with Edges/X-ray]",
                         keywords=tuple(Keyword(n, k) for n, k in keys.items()),
                         default="Shaded with edges", default_text="Shaded with edges")
    if v in STYLES:
        ctx.ui.run_ui_action("VSCURRENT:" + v)


@command("SHAPESPANEL", label="Shapes Panel", aliases=("SHAPES",), group="3D", transaction=False,
         description="Show or hide the Shapes panel: drag boxes, cylinders and hole shapes into the 3D view.",
         keywords=("shape library", "basic shapes", "tinkercad", "parts bin"))
def shapespanel_cmd(ctx: CommandContext):
    ctx.ui.run_ui_action("SHAPESPANEL")
    yield from ()
