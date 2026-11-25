"""Editing, inquiry, view and application commands available in Phase 2."""
from __future__ import annotations

import math

from ..core.geom2d.vec import angle_of, sub
from ..core.units import format_angle
from .framework import CommandContext, GetPoint, GetSelection, command, kw

# ------------------------------------------------------------------ editing


@command("ERASE", label="Erase", aliases=("E",), shortcut="Delete", group="Modify",
         description="Delete the selected objects.", keywords=("delete", "remove", "rubber"))
def erase_cmd(ctx: CommandContext):
    sel = yield GetSelection("Select objects to erase")
    if not sel:
        return
    locked = 0
    count = 0
    for h in sel:
        e = ctx.doc.get(h)
        if e is None:
            continue
        if ctx.doc.is_locked(e):
            locked += 1
            continue
        ctx.doc.delete(h)
        count += 1
    msg = f"{count} object(s) erased."
    if locked:
        msg += f" {locked} on locked layers were skipped."
    ctx.echo(msg)


@command("UNDO", label="Undo", aliases=("U",), shortcut="Ctrl+Z", group="Edit", transaction=False,
         description="Undo the last action.", keywords=("back", "revert", "oops"))
def undo_cmd(ctx: CommandContext):
    name = ctx.doc.undo()
    ctx.echo(f"Undone: {name}" if name else "Nothing to undo.")
    return
    yield  # pragma: no cover  (makes this a generator)


@command("REDO", label="Redo", aliases=("MREDO",), shortcut="Ctrl+Y", group="Edit", transaction=False,
         description="Redo the last action you undid.", keywords=("again",))
def redo_cmd(ctx: CommandContext):
    name = ctx.doc.redo()
    ctx.echo(f"Redone: {name}" if name else "Nothing to redo.")
    return
    yield  # pragma: no cover


# ------------------------------------------------------------------ inquiry


@command("DIST", label="Distance", aliases=("DI",), group="Utilities", transaction=False,
         description="Measure the distance and angle between two points.", keywords=("measure", "length"))
def dist_cmd(ctx: CommandContext):
    p1 = yield GetPoint("Specify first point", rubber=None)
    p2 = yield GetPoint("Specify second point", base=p1)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    ang = math.degrees(angle_of(sub(p2, p1)))
    ctx.echo(f"Distance = {ctx.fmt(math.hypot(dx, dy))},  Angle = {format_angle(ang, ctx.units)},  "
             f"Delta X = {ctx.fmt(dx)},  Delta Y = {ctx.fmt(dy)}")


@command("ID", label="Point Coordinates", group="Utilities", transaction=False,
         description="Show the coordinates of a point.", keywords=("coordinates", "locate", "where"))
def id_cmd(ctx: CommandContext):
    p = yield GetPoint("Specify point", rubber=None)
    ctx.echo(f"X = {ctx.fmt(p[0])}   Y = {ctx.fmt(p[1])}")


# ------------------------------------------------------------------ view


@command("ZOOM", label="Zoom", aliases=("Z",), group="View", transaction=False,
         description="Zoom to the drawing's extents, a window, or the previous view.",
         keywords=("magnify", "view", "enlarge"))
def zoom_cmd(ctx: CommandContext):
    r = yield GetPoint("Specify corner of window", keywords=kw("Extents", "Previous", "In", "Out"),
                       rubber=None, default="Extents", default_text="Extents")
    if r == "Extents":
        ctx.view.zoom_extents()
    elif r == "Previous":
        if not ctx.view.zoom_previous():
            ctx.echo("No previous view.")
    elif r == "In":
        ctx.view.zoom_factor(2.0)
    elif r == "Out":
        ctx.view.zoom_factor(0.5)
    else:
        p2 = yield GetPoint("Specify opposite corner", base=r, rubber="rect")
        ctx.view.zoom_window(r, p2)


@command("ZOOMEXTENTS", label="Zoom Extents", aliases=("ZE",), group="View", transaction=False,
         description="Fit the whole drawing in the window.", keywords=("fit", "all", "show everything"))
def zoom_extents_cmd(ctx: CommandContext):
    ctx.view.zoom_extents()
    return
    yield  # pragma: no cover


@command("ZOOMWINDOW", label="Zoom Window", aliases=("ZW",), group="View", transaction=False,
         description="Zoom into a rectangle you pick.", keywords=("zoom area",))
def zoom_window_cmd(ctx: CommandContext):
    p1 = yield GetPoint("Specify first corner", rubber=None)
    p2 = yield GetPoint("Specify opposite corner", base=p1, rubber="rect")
    ctx.view.zoom_window(p1, p2)


@command("PAN", label="Pan", aliases=("P",), group="View", transaction=False,
         description="Drag the view around. You can also drag with the middle mouse button any time.",
         keywords=("move view", "scroll", "hand"))
def pan_cmd(ctx: CommandContext):
    yield GetPoint("Drag to pan. Press Enter or Esc to exit", rubber=None, allow_none=True, mode="pan")


@command("REGEN", label="Regen", aliases=("RE",), group="View", transaction=False,
         description="Redraw the drawing with smooth curves for the current zoom level.",
         keywords=("refresh", "redraw", "regenerate"))
def regen_cmd(ctx: CommandContext):
    ctx.view.regen()
    return
    yield  # pragma: no cover


# ------------------------------------------------------------------ application (handled by the UI)


def _ui_command(name: str, label: str, description: str, aliases=(), shortcut="", group="Application",
                keywords=()):
    def fn(ctx: CommandContext):
        ctx.ui.run_ui_action(name)
        return
        yield  # pragma: no cover
    command(name, label=label, description=description, aliases=aliases, shortcut=shortcut, group=group,
            transaction=False, repeatable=False, keywords=keywords)(fn)


_ui_command("NEW", "New", "Start a new drawing.", shortcut="Ctrl+N", keywords=("blank", "start"))
_ui_command("OPEN", "Open", "Open a saved drawing.", shortcut="Ctrl+O", keywords=("load", "file"))
_ui_command("QSAVE", "Save", "Save the drawing.", aliases=("SAVE",), shortcut="Ctrl+S", keywords=("store",))
_ui_command("SAVEAS", "Save As", "Save the drawing under a new name.", shortcut="Ctrl+Shift+S")
_ui_command("RECOVER", "Recover", "Open drawings saved automatically before a crash.",
            keywords=("crash", "autosave", "restore"))
_ui_command("EXIT", "Exit", "Close the program.", aliases=("QUIT",), keywords=("close", "quit"))
_ui_command("LAYER", "Layer Properties", "Create and manage layers: color, linetype, lineweight, on/off, lock.",
            aliases=("LA",), group="Layers", keywords=("layers", "level", "manage layers"))
_ui_command("UNITS", "Units", "Choose millimeters, fractional inches or feet-inches, and precision.",
            aliases=("UN",), group="Utilities", keywords=("inches", "feet", "metric", "imperial", "precision"))
_ui_command("DSETTINGS", "Drafting Settings", "Snap, grid, ortho, polar tracking and object snap options.",
            aliases=("DS", "OSNAP", "OS"), group="Utilities", keywords=("snap settings", "grid settings"))
_ui_command("OPTIONS", "Options", "Theme, UI size, autosave and other program settings.",
            aliases=("OP",), group="Application", keywords=("preferences", "settings", "dark mode", "theme"))
_ui_command("PROPERTIES", "Properties", "Show or hide the Properties panel.", aliases=("PR", "CH"),
            shortcut="Ctrl+1", group="Utilities", keywords=("inspect", "change"))
_ui_command("PAGESETUP", "Page Setup", "Choose the paper size and orientation of the current layout.",
            group="Layout", keywords=("paper size", "sheet size", "orientation"))
_ui_command("DIMSTYLE", "Dimension Style", "Set dimension text size, arrow size and style, and overall scale.",
            aliases=("D", "DDIM"), group="Annotation", keywords=("dim settings", "arrow size", "dimscale"))
