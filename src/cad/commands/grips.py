"""Grip editing: click a blue grip on a selected object, then click (or type) where it goes.

The UI starts GRIPEDIT with ctx.memory["grip"] = (base point, [(handle, part), ...]); every selected
object that has a grip at the clicked spot moves with it (two lines sharing a corner stay joined).
"""
from __future__ import annotations

from ..core.geom2d.vec import Vec
from ..core.points import move_point, named_points, point_of
from .framework import CommandContext, GetPoint, command, kw

GRIP_ENTITY_LIMIT = 100


def grips_at(doc, handles, pt: Vec, tol: float) -> list[tuple[int, str]]:
    """All (handle, part) grips of the given objects within tol of pt (closest spot wins)."""
    best: list[tuple[float, int, str, Vec]] = []
    for i, h in enumerate(handles):
        if i >= GRIP_ENTITY_LIMIT:
            break
        e = doc.entities.get(h)
        if e is None or doc.is_locked(e) or not doc.is_visible(e):
            continue
        for part, p in named_points(e):
            d = max(abs(p[0] - pt[0]), abs(p[1] - pt[1]))
            if d <= tol:
                best.append((d, h, part, p))
    if not best:
        return []
    best.sort(key=lambda t: t[0])
    spot = best[0][3]
    same = 1e-9 * max(1.0, abs(spot[0]), abs(spot[1])) + tol * 1e-3
    out, seen = [], set()
    for _, h, part, p in best:
        if abs(p[0] - spot[0]) <= same and abs(p[1] - spot[1]) <= same and h not in seen:
            seen.add(h)                 # one grip per object (e.g. a closed polyline's first/last vertex)
            out.append((h, part))
    return out


def _moved(doc, targets, base: Vec, to: Vec):
    d = (to[0] - base[0], to[1] - base[1])
    out = []
    for h, part in targets:
        e = doc.entities.get(h)
        if e is None:
            continue
        p = point_of(e, part)
        if p is None:
            continue
        out.append(move_point(e, part, (p[0] + d[0], p[1] + d[1])))
    return out


@command("GRIPEDIT", label="Grip edit", group="Modify", repeatable=False, icon="stretch",
         description="Drag a grip of the selected objects to a new point. Started by clicking a blue grip.",
         keywords=("grip", "stretch point", "reshape", "drag"))
def gripedit_cmd(ctx: CommandContext):
    base, targets = ctx.memory.pop("grip", (None, []))
    if base is None or not targets:
        ctx.echo("Select objects, then click one of their blue grips.")
        return
    doc = ctx.doc
    while True:
        pt = yield GetPoint("Specify stretch point", base=base, keywords=kw("Base point", "Copy"),
                            preview=lambda c, b=base: _moved(doc, targets, b, c))
        if pt == "Base point":
            base = yield GetPoint("Specify base point", rubber=None)
            continue
        if pt == "Copy":
            pt = yield GetPoint("Specify stretch point (copy)", base=base,
                                preview=lambda c, b=base: _moved(doc, targets, b, c))
            for e in _moved(doc, targets, base, pt):
                doc.add(_fresh(e), use_current_props=False)
            ctx.last_point = pt
            return
        for e in _moved(doc, targets, base, pt):
            doc.replace(e)
        ctx.last_point = pt
        return


def _fresh(e):
    from dataclasses import replace
    return replace(e, handle=0)
