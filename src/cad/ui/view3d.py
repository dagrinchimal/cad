"""The 3D view: look around the model and build it by clicking and dragging.

Mouse:  left-drag on empty space (no command) or Shift+middle-drag = orbit;  middle- or right-drag = pan;
        wheel = zoom at the cursor;  left-click = pick / select;  double-click middle = zoom extents.
Easy 3D (Phase 6b):
  * drawing commands (Line, Rectangle, Circle…) draw on the face you click first, or on the ground;
  * distances that have a direction (Press/Pull, Extrude, Box height…) follow the mouse with a live preview;
  * a selected solid shows handles: drag the sides to stretch it, the cone on top to lift it, the body to move it;
  * the view cube (top right) turns the view; a small toolbar offers the tools for what you clicked;
  * shapes can be dragged in from the Shapes panel.
Typed commands and values work everywhere, as in the plan view.
"""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QToolButton, QWidget

from ..commands.framework import (
    GetAngle, GetDistance, GetEdge, GetEntity, GetFace, GetNumber, GetPoint, GetSelection,
)
from ..core import solids as S
from ..core.model import MODEL_SPACE, Solid, is_sketch_space
from ..core.solid_pick import EdgePick, FacePick, pick_edge, pick_face, snap_points_3d
from ..core.solids import aligned_face_plane
from ..render import viewcube
from ..render.camera3d import PRESETS, Camera3D
from ..render.raster3d import get_renderer
from ..render.scene3d import DEFAULT_STYLE, STYLES, Scene3DBuilder, item_from_shape

SNAP_PX = 10.0
PICK_PX = 6.0
HANDLE_PX = 7.0
SHAPE_MIME = "application/x-cad-shape"
DRAW_GROUPS = ("Draw",)          # commands whose points go on the work plane (face or ground)


def nice_step(mm_per_px: float) -> float:
    """A round step about 8 pixels long: 0.1, 0.5, 1, 5, 10 … mm."""
    raw = mm_per_px * 8
    for s in (0.01, 0.05, 0.1, 0.5, 1, 5, 10, 50, 100, 500, 1000, 5000):
        if s >= raw:
            return float(s)
    return 10000.0


def ray_axis_param(o, d, a0, a) -> float:
    """Parameter t of the point a0 + t·a closest to the ray o + s·d."""
    o, d, a0, a = (np.asarray(v, float) for v in (o, d, a0, a))
    a = a / np.linalg.norm(a)
    w = a0 - o
    b = a @ d
    den = 1 - b * b
    if abs(den) < 1e-9:
        return 0.0
    return float((b * (d @ w) - (a @ w)) / den)


def ray_plane(o, d, plane) -> np.ndarray | None:
    n = np.asarray(plane.normal, float)
    den = np.asarray(d, float) @ n
    if abs(den) < 1e-9:
        return None
    t = ((np.asarray(plane.origin, float) - o) @ n) / den
    return np.asarray(o, float) + np.asarray(d, float) * t


class ValueEditor(QLineEdit):
    """Inline box to type an exact size for a handle."""

    def __init__(self, parent, on_done) -> None:
        super().__init__(parent)
        self.on_done = on_done
        self.setFixedWidth(90)
        self.returnPressed.connect(lambda: self.on_done(self.text()))

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key.Key_Escape:
            self.on_done(None)
            return
        super().keyPressEvent(ev)

    def focusOutEvent(self, ev) -> None:
        super().focusOutEvent(ev)
        if self.isVisible():
            self.on_done(None)


class ContextBar(QFrame):
    """A small floating toolbar with the tools for what was just clicked (Shapr3D-style)."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(3, 3, 3, 3)
        self.lay.setSpacing(2)
        self.buttons: dict[str, QToolButton] = {}
        self.hide()

    def show_tools(self, tools, at, icon_for=None) -> None:
        """tools: [(key, label, tooltip, callback)]"""
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.buttons = {}
        for key, label, tip, cb in tools:
            b = QToolButton(self)
            b.setText(label)
            b.setToolTip(tip)
            if icon_for is not None:
                ic = icon_for(key)
                if ic is not None:
                    b.setIcon(ic)
                    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, f=cb: (self.hide(), f()))
            self.lay.addWidget(b)
            self.buttons[key] = b
        self.adjustSize()
        p = self.parentWidget()
        x = min(max(4, at[0] + 14), p.width() - self.width() - 4)
        y = min(max(4, at[1] + 14), p.height() - self.height() - 4)
        self.move(int(x), int(y))
        self.show()
        self.raise_()


class View3D(QWidget):
    """Draws the model in 3D. Talks to the same command runner and selection as the plan view."""

    status = Signal(str)
    run_requested = Signal(str, list)            # command, faces/edges picked beforehand
    drop_requested = Signal(str, bool, tuple)    # shape kind, hole?, (x, y, z)

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.ctl = controller
        self.doc = controller.doc
        self.cam = Camera3D()
        self.style = DEFAULT_STYLE
        self.builder = Scene3DBuilder(self.doc)
        self.renderer = None
        self.icon_for = None
        self.hints: list = []                    # overlay lines from tutorial hints
        self._scene = None
        self._image = None
        self._dirty = True
        self._drag = None             # [mode, last x, last y, moved, data]
        self.hover = None             # solid handle under the cursor
        self.cube_hover = None
        self.snap = None              # (xyz, kind)
        self.cursor = None
        self.last_point3 = None
        self.fitted = False
        # easy 3D state
        self.workplane = None         # (space, plane) while a drawing command runs in this view
        self._prev_space = None
        self.drag_value = None        # current value along a drag axis
        self.preview_item = None
        self._preview_key = None
        self.handle_drag = None       # live resize/move of a selected solid
        self.editor = None
        self.bar = ContextBar(self)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(200, 150)
        self.doc.add_listener(self._on_doc)
        self.ctl.runner.listeners.append(self._on_runner)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(25)
        self._hover_timer.timeout.connect(self._update_hover)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(40)
        self._preview_timer.timeout.connect(self._update_preview_shape)

    # ================================================================ state
    def set_document(self, doc) -> None:
        try:
            self.doc.remove_listener(self._on_doc)
        except Exception:
            pass
        self.doc = doc
        self.builder = Scene3DBuilder(doc)
        doc.add_listener(self._on_doc)
        self.workplane = None
        self.fitted = False
        self.invalidate()

    def _on_doc(self, doc, cs) -> None:
        self.invalidate()

    def _on_runner(self, *_a) -> None:
        """The command changed state: end the work plane when it's over, clear previews."""
        if not self.ctl.runner.is_active:
            self._end_workplane()
            self.drag_value = None
            self.preview_item = None
            self._preview_key = None
        self._image = None
        self.update()

    def invalidate(self) -> None:
        self._dirty = True
        self._image = None
        self.update()

    def set_style(self, style: str) -> None:
        if style in STYLES:
            self.style = style
            self._image = None
            self.update()

    def set_view(self, name: str) -> None:
        self.cam.set_view(name)
        self.zoom_extents()

    def set_perspective(self, on: bool) -> None:
        self.cam.perspective = on
        self._image = None
        self.update()

    def look_at_plane(self, plane) -> None:
        """Turn the view to look straight at a plane (like Fusion's Look At)."""
        n = np.array(plane.normal, float)
        self.cam.elevation = math.degrees(math.asin(max(-1.0, min(1.0, n[2]))))
        if abs(n[2]) < 0.999:
            self.cam.azimuth = math.degrees(math.atan2(n[1], n[0])) % 360
        self._image = None
        self.update()

    def set_hints(self, lines) -> None:
        self.hints = list(lines or [])
        self._image = None
        self.update()

    def scene(self):
        if self._dirty or self._scene is None:
            self.builder.dark = getattr(self.ctl, "dark", True)
            self._scene = self.builder.build()
            self._dirty = False
        return self._scene

    def zoom_extents(self) -> None:
        bb = self.scene().bbox()
        self.cam.width, self.cam.height = max(self.width(), 1), max(self.height(), 1)
        self.cam.fit(bb if bb is not None else (-50, -50, 0, 50, 50, 50))
        self.fitted = True
        self._image = None
        self.update()

    def _sync_cam(self) -> None:
        self.cam.width, self.cam.height = max(self.width(), 1), max(self.height(), 1)

    # ================================================================ painting
    def _background(self) -> QColor:
        return QColor(33, 40, 48) if getattr(self.ctl, "dark", True) else QColor(250, 250, 250)

    def _selection(self) -> set:
        return set(self.ctl.runner.ctx.selection) | set(getattr(self.ctl, "pending_sel", set()))

    def render_image(self):
        if self.renderer is None:
            self.renderer = get_renderer()
        self._sync_cam()
        extra = [self.preview_item] if self.preview_item is not None else []
        hide = set()
        if self.handle_drag is not None and self.handle_drag.get("item") is not None:
            extra.append(self.handle_drag["item"])
            hide.add(self.handle_drag["handle"])
        scene = self.scene()
        if hide:
            from ..render.scene3d import Scene3D
            scene = Scene3D([s for s in scene.solids if s.handle not in hide], scene.wires)
        return self.renderer.render(scene, self.cam, self.style, self._background(), self._selection(),
                                    self.hover, getattr(self.ctl, "dark", True), self.hints, extra)

    def paintEvent(self, ev) -> None:
        if not self.fitted and self.width() > 1:
            self.zoom_extents()
        if self._image is None or self._image.width() != self.width() or self._image.height() != self.height():
            try:
                self._image = self.render_image()
            except Exception:              # a GL failure falls back to the software renderer
                from ..render.raster3d import PainterRenderer
                if isinstance(self.renderer, PainterRenderer):
                    raise
                self.renderer = PainterRenderer()
                self._image = self.render_image()
        p = QPainter(self)
        p.drawImage(0, 0, self._image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_overlay(p)
        p.end()

    def _fg(self) -> QColor:
        return QColor(230, 230, 230) if getattr(self.ctl, "dark", True) else QColor(40, 40, 40)

    def _paint_overlay(self, p: QPainter) -> None:
        fg = self._fg()
        self._paint_tripod(p)
        f = QFont()
        f.setPointSizeF(9)
        p.setFont(f)
        p.setPen(fg)
        wp = ""
        if self.workplane is not None:
            sp = self.workplane[0]
            wp = "  ·  Drawing on: " + ("the ground" if sp == MODEL_SPACE else sp.split(":", 1)[1])
        p.drawText(QRectF(8, 6, 900, 18), Qt.AlignmentFlag.AlignLeft,
                   f"[{self.view_name()}] [{self.style}]{' [Perspective]' if self.cam.perspective else ''}{wp}")
        self._paint_viewcube(p)
        self._paint_handles(p)
        self._paint_drag(p)
        self._paint_workplane_preview(p)
        if self.snap is not None:
            (pt,), _ = self.cam.project(np.array([self.snap[0]]))
            p.setPen(QPen(QColor(80, 220, 80), 2))
            p.drawRect(QRectF(pt[0] - 5, pt[1] - 5, 10, 10))
            p.drawText(QPointF(pt[0] + 8, pt[1] - 8), self.snap[1])

    def _paint_tripod(self, p: QPainter) -> None:
        o = np.array([46.0, self.height() - 46.0])
        for vec, name, col in (((1, 0, 0), "X", QColor(230, 80, 80)), ((0, 1, 0), "Y", QColor(90, 200, 90)),
                               ((0, 0, 1), "Z", QColor(90, 140, 255))):
            v = np.array(vec, float)
            d = np.array([v @ self.cam.right, -(v @ self.cam.up)]) * 30
            p.setPen(QPen(col, 2))
            p.drawLine(QPointF(*o), QPointF(*(o + d)))
            p.drawText(QPointF(*(o + d * 1.25 - (4, -4))), name)

    def _paint_viewcube(self, p: QPainter) -> None:
        w = self.width()
        dark = getattr(self.ctl, "dark", True)
        face_col = QColor(70, 80, 95, 220) if dark else QColor(225, 230, 238, 230)
        hov_col = QColor(70, 140, 230, 230)
        f = QFont()
        f.setPointSizeF(7)
        f.setBold(True)
        p.setFont(f)
        for name, preset, poly, _d, facing in viewcube.visible_faces(self.cam, w):
            hovered = self.cube_hover == ("face", preset)
            p.setPen(QPen(self._fg(), 1))
            p.setBrush(hov_col if hovered else face_col)
            p.drawPolygon(QPolygonF([QPointF(*q) for q in poly]))
            if facing > 0.35:
                c = poly.mean(axis=0)
                p.drawText(QRectF(c[0] - 26, c[1] - 7, 52, 14), Qt.AlignmentFlag.AlignCenter, name)
        for pt, view in viewcube.corners(self.cam, w):
            hovered = self.cube_hover == ("corner", view)
            p.setBrush(hov_col if hovered else self._fg())
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(*pt), 3.5, 3.5)
        hx, hy, hr = viewcube.home_button(w)
        p.setPen(QPen(self._fg(), 1.4))
        p.setBrush(hov_col if self.cube_hover == ("home", None) else Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(hx, hy), hr, hr)
        p.drawPolyline(QPolygonF([QPointF(hx - 4, hy + 1), QPointF(hx, hy - 4), QPointF(hx + 4, hy + 1)]))
        p.drawRect(QRectF(hx - 3, hy + 1, 6, 4))

    def _paint_drag(self, p: QPainter) -> None:
        req = self._request()
        if not (isinstance(req, GetDistance) and req.drag_axis is not None):
            return
        o, d = (np.asarray(v, float) for v in req.drag_axis)
        d = d / np.linalg.norm(d)
        t = self.drag_value or 0.0
        (a, b), _ = self.cam.project(np.array([o, o + d * t]))
        col = QColor(255, 170, 40)
        p.setPen(QPen(col, 2))
        p.drawLine(QPointF(*a), QPointF(*b))
        # arrow head at the end, pointing along the axis
        (b2,), _ = self.cam.project(np.array([o + d * (t + self.cam.mm_per_pixel() * 12 * (1 if t >= 0 else -1))]))
        v = np.array(b2) - np.array(b)
        if np.linalg.norm(v) > 1e-6:
            v = v / np.linalg.norm(v) * 10
            nrm = np.array([-v[1], v[0]]) * 0.5
            p.setBrush(col)
            p.drawPolygon(QPolygonF([QPointF(*(b + v)), QPointF(*(b + nrm)), QPointF(*(b - nrm))]))
        if self.drag_value is not None:
            from ..core.units import format_length
            p.setPen(self._fg())
            p.drawText(QPointF(b[0] + 12, b[1] - 6), format_length(self.drag_value, self.ctl.runner.ctx.units))

    def _paint_workplane_preview(self, p: QPainter) -> None:
        """Rubber band and command preview on the work plane."""
        if self.workplane is None or self.cursor is None or not self._wants_point():
            return
        space, plane = self.workplane
        loc = self._plane_point(*self.cursor)
        if loc is None:
            return
        runner = self.ctl.runner
        req = runner.request
        col = QColor(150, 170, 190)
        lines = []
        base = getattr(req, "base", None)
        rubber = getattr(req, "rubber", "line") if isinstance(req, GetPoint) else "line"
        if base is not None and rubber == "line":
            lines.append([base, loc])
        elif base is not None and rubber == "rect":
            lines.append([base, (loc[0], base[1]), loc, (base[0], loc[1]), base])
        try:
            for e in runner.preview(loc):
                for prim in e.primitives():
                    lines.append([tuple(q) for q in prim.tessellate(self.cam.mm_per_pixel() * 2)])
        except Exception:
            pass
        p.setPen(QPen(col, 1.2, Qt.PenStyle.DashLine))
        for ln in lines:
            pts3 = np.array([plane.to_world(x, y) for x, y in ln])
            scr, _ = self.cam.project(pts3)
            p.drawPolyline(QPolygonF([QPointF(*q) for q in scr]))

    def view_name(self) -> str:
        for name, (az, el) in PRESETS.items():
            if abs((self.cam.azimuth - az + 180) % 360 - 180) < 0.5 and abs(self.cam.elevation - el) < 0.5:
                return name
        return "Custom"

    # ================================================================ helpers
    def _request(self):
        return self.ctl.runner.request

    def _command(self):
        return self.ctl.runner.active

    def _wants_point(self) -> bool:
        return isinstance(self._request(), (GetPoint, GetDistance, GetAngle, GetNumber))

    def _is_draw_command(self) -> bool:
        c = self._command()
        return c is not None and c.group in DRAW_GROUPS

    def _tolerance_mm(self, point=None) -> float:
        return PICK_PX * self.cam.mm_per_pixel(point)

    def _snap_at(self, sx, sy):
        pts = snap_points_3d(self.doc)
        if self.workplane is not None:
            pts = pts + self._workplane_snaps()
        if not pts:
            return None
        xyz = np.array([q for q, _ in pts], float)
        scr, depth = self.cam.project(xyz)
        d = np.hypot(scr[:, 0] - sx, scr[:, 1] - sy)
        near = np.where(d <= SNAP_PX)[0]
        if not len(near):
            return None
        i = near[np.argmin(depth[near] + d[near] * 1e-6)]
        o, dvec = self.cam.ray(sx, sy)
        hit = pick_face(self.doc, o, dvec)
        if hit is not None:
            hp = np.array(hit.point)
            if (xyz[i] - hp) @ self.cam.forward > max(self._tolerance_mm(hp) * 3, 1e-6):
                return None                # behind the surface under the cursor
        return (tuple(float(v) for v in xyz[i]), pts[i][1])

    def _workplane_snaps(self):
        space, plane = self.workplane
        out = []
        for e in self.doc.entities.values():
            if e.space != space or not self.doc.is_visible(e):
                continue
            g = self.doc.geometry(e)
            for kind, pts in (("endpoint", g.endpoints), ("midpoint", g.midpoints), ("center", g.centers)):
                for q in pts:
                    out.append((plane.to_world(q[0], q[1]), kind))
        return out

    def point_under(self, sx, sy):
        """(x, y, z) under the cursor: a snap point, a solid surface, else the ground (z = 0)."""
        if self.snap is not None:
            return self.snap[0]
        o, d = self.cam.ray(sx, sy)
        hit = pick_face(self.doc, o, d)
        if hit is not None:
            return hit.point
        if abs(d[2]) > 1e-9:
            t = -o[2] / d[2]
            if t > 0 or not self.cam.perspective:
                q = o + d * t
                return (float(q[0]), float(q[1]), 0.0)
        return None

    def _plane_point(self, sx, sy):
        """The cursor on the work plane, in the plane's 2D coordinates (snapped)."""
        space, plane = self.workplane
        if self.snap is not None:
            x, y, _ = plane.to_local(self.snap[0])
            return (x, y)
        o, d = self.cam.ray(sx, sy)
        q = ray_plane(o, d, plane)
        if q is None:
            return None
        x, y, _ = plane.to_local(tuple(q))
        return (x, y)

    def solid_under(self, sx, sy):
        o, d = self.cam.ray(sx, sy)
        hit = pick_face(self.doc, o, d)
        return hit.entity.handle if hit is not None else None

    def wire_under(self, sx, sy):
        best = None
        for w in self.scene().wires:
            for ln in w.lines:
                scr, _ = self.cam.project(ln)
                a, b = scr[:-1], scr[1:]
                u = b - a
                L2 = np.einsum("ij,ij->i", u, u)
                t = np.clip(np.einsum("ij,ij->i", np.array([sx, sy]) - a, u) / np.where(L2 > 0, L2, 1), 0, 1)
                dist = np.hypot(*(a + u * t[:, None] - (sx, sy)).T)
                i = int(np.argmin(dist))
                if dist[i] <= PICK_PX and (best is None or dist[i] < best[0]):
                    best = (float(dist[i]), w.handle)
        return best[1] if best else None

    def object_under(self, sx, sy):
        return self.wire_under(sx, sy) or self.solid_under(sx, sy)

    def _selected_solid(self):
        sel = self.ctl.runner.ctx.selection
        if self.ctl.runner.is_active or len(sel) != 1:
            return None
        e = self.doc.get(next(iter(sel)))
        return e if isinstance(e, Solid) and not self.doc.is_locked(e) else None

    # ================================================================ work plane (draw on faces)
    def _begin_workplane(self, sx, sy) -> None:
        """First click of a drawing command: draw on the flat face under the cursor, else the ground."""
        from ..commands.sketch3d import make_sketch, refresh_reference
        o, d = self.cam.ray(sx, sy)
        hit = pick_face(self.doc, o, d)
        space, plane = MODEL_SPACE, S.XY
        if hit is not None:
            pl = aligned_face_plane(S.faces(hit.entity.shape)[hit.face])
            if pl is not None:
                sk = self._sketch_on(pl)
                if sk is None:
                    with self.doc.transaction("Sketch on face"):
                        sk = make_sketch(self.doc, pl, self._face_sketch_name())
                        refresh_reference(self.doc, sk)
                space, plane = sk.space, sk.plane()
        self._set_space(space)
        self.workplane = (space, plane)
        if space != MODEL_SPACE:
            self.ctl.runner.ctx.echo(f"Drawing on the face ({space.split(':', 1)[1]}). Push/Pull or Extrude "
                                     "what you draw to add to the part or cut into it.")

    def _face_sketch_name(self) -> str:
        n = 1
        while f"Face{n}" in self.doc.sketches:
            n += 1
        return f"Face{n}"

    def _sketch_on(self, plane):
        n = np.array(plane.normal, float)
        for sk in self.doc.sketches.values():
            pl = sk.plane()
            if np.dot(pl.normal, n) > 0.9999 and abs((np.array(pl.origin) - np.array(plane.origin)) @ n) < 1e-6 \
                    and np.allclose(pl.xdir, plane.xdir, atol=1e-6):
                return sk
        return None

    def _set_space(self, space: str) -> None:
        ctx = self.ctl.runner.ctx
        if self._prev_space is None:
            self._prev_space = ctx.space
        ctx.space = space
        self.ctl.index.space = space
        self.doc.current_space = space

    def _end_workplane(self) -> None:
        if self._prev_space is not None:
            ctx = self.ctl.runner.ctx
            ctx.space = self._prev_space
            self.ctl.index.space = self._prev_space
            self.doc.current_space = self._prev_space
            self._prev_space = None
        self.workplane = None

    # ================================================================ handles on a selected solid
    def _handles(self):
        """[(name, xyz, axis or None)] for the selected solid."""
        e = self._selected_solid()
        if e is None:
            return []
        x0, y0, z0, x1, y1, z1 = S.bbox3(e.shape)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        lift = self.cam.mm_per_pixel() * 26
        return [
            ("+x", (x1, cy, z0), (1, 0, 0)), ("-x", (x0, cy, z0), (-1, 0, 0)),
            ("+y", (cx, y1, z0), (0, 1, 0)), ("-y", (cx, y0, z0), (0, -1, 0)),
            ("+z", (cx, cy, z1), (0, 0, 1)), ("lift", (cx, cy, z1 + lift), (0, 0, 1)),
        ]

    def _handle_at(self, sx, sy):
        best = None
        for name, xyz, axis in self._handles():
            (q,), _ = self.cam.project(np.array([xyz]))
            d = math.hypot(q[0] - sx, q[1] - sy)
            if d <= HANDLE_PX + 3 and (best is None or d < best[0]):
                best = (d, name, xyz, axis)
        return best[1:] if best else None

    def _paint_handles(self, p: QPainter) -> None:
        hs = self._handles()
        if not hs:
            return
        e = self._selected_solid()
        x0, y0, z0, x1, y1, z1 = S.bbox3(e.shape)
        if self.handle_drag is not None and self.handle_drag.get("bbox") is not None:
            x0, y0, z0, x1, y1, z1 = self.handle_drag["bbox"]
        # footprint outline on the base
        foot = np.array([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z0)])
        scr, _ = self.cam.project(foot)
        p.setPen(QPen(QColor(80, 160, 255), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(*q) for q in scr]))
        for name, xyz, _axis in hs:
            (q,), _ = self.cam.project(np.array([xyz]))
            if name == "lift":
                p.setBrush(QColor(255, 255, 255))
                p.setPen(QPen(QColor(30, 30, 30), 1))
                p.drawPolygon(QPolygonF([QPointF(q[0], q[1] - 8), QPointF(q[0] - 6, q[1] + 5),
                                         QPointF(q[0] + 6, q[1] + 5)]))
            else:
                p.setBrush(QColor(255, 255, 255) if name != "+z" else QColor(80, 160, 255))
                p.setPen(QPen(QColor(30, 30, 30), 1))
                p.drawRect(QRectF(q[0] - HANDLE_PX / 2 - 1, q[1] - HANDLE_PX / 2 - 1, HANDLE_PX + 2, HANDLE_PX + 2))
        # sizes, clickable
        from ..core.units import format_length
        u = self.ctl.runner.ctx.units
        p.setPen(self._fg())
        for label, xyz in self._size_labels(x0, y0, z0, x1, y1, z1):
            (q,), _ = self.cam.project(np.array([xyz]))
            val = {"x": x1 - x0, "y": y1 - y0, "z": z1 - z0, "elev": z0}[label]
            txt = format_length(val, u) if label != "elev" else "↑ " + format_length(val, u)
            p.drawText(QPointF(q[0] + 4, q[1] + 14), txt)

    def _size_labels(self, x0, y0, z0, x1, y1, z1):
        return [("x", ((x0 + x1) / 2, y0, z0)), ("y", (x1, (y0 + y1) / 2, z0)), ("z", (x0, y0, (z0 + z1) / 2)),
                ("elev", ((x0 + x1) / 2, (y0 + y1) / 2, z1 + self.cam.mm_per_pixel() * 40))]

    def _label_at(self, sx, sy):
        e = self._selected_solid()
        if e is None:
            return None
        bb = S.bbox3(e.shape)
        for label, xyz in self._size_labels(*bb):
            (q,), _ = self.cam.project(np.array([xyz]))
            if q[0] - 2 <= sx <= q[0] + 80 and q[1] + 2 <= sy <= q[1] + 18:
                return label
        return None

    def _resize_shape(self, e: Solid, name: str, start_bbox, delta: float):
        x0, y0, z0, x1, y1, z1 = start_bbox
        size = [x1 - x0, y1 - y0, z1 - z0]
        about = [x0, y0, z0]
        f = [1.0, 1.0, 1.0]
        if name == "lift":
            return S.translate(e.shape, (0, 0, delta)), (x0, y0, z0 + delta, x1, y1, z1 + delta)
        i = "xyz".index(name[1])
        new = max(size[i] + delta, max(size[i] * 1e-3, 1e-3))
        f[i] = new / size[i] if size[i] > 1e-9 else 1.0
        if name[0] == "-":
            about[i] = [x1, y1, z1][i]
        shape = S.scaled(e.shape, tuple(f), tuple(about))
        return shape, S.bbox3(shape)

    def _commit_resize(self, e: Solid, shape, what: str) -> None:
        with self.doc.transaction(what):
            self.doc.replace(e.with_props(shape=shape))

    def _edit_label(self, label: str) -> None:
        e = self._selected_solid()
        if e is None:
            return
        from ..core.units import format_length, parse_length
        bb = S.bbox3(e.shape)
        u = self.ctl.runner.ctx.units
        cur = {"x": bb[3] - bb[0], "y": bb[4] - bb[1], "z": bb[5] - bb[2], "elev": bb[2]}[label]
        xyz = dict(self._size_labels(*bb))[label]
        (q,), _ = self.cam.project(np.array([xyz]))

        def done(text):
            ed, self.editor = self.editor, None
            if ed is not None:
                ed.hide()
                ed.deleteLater()
            self.setFocus()
            if text is None:
                return
            try:
                v = parse_length(text, u)
            except Exception:
                self.ctl.runner.ctx.echo(f"Can't read {text!r} as a size.")
                return
            if label == "elev":
                shape = S.translate(e.shape, (0, 0, v - bb[2]))
            else:
                shape, _ = self._resize_shape(e, "+" + label, bb, v - cur)
            self._commit_resize(e, shape, "Resize" if label != "elev" else "Lift")
        self.editor = ValueEditor(self, done)
        self.editor.setText(format_length(cur, u))
        self.editor.move(int(q[0]), int(q[1]))
        self.editor.show()
        self.editor.selectAll()
        self.editor.setFocus()

    # ================================================================ live drag previews
    def _update_drag_value(self, sx, sy) -> None:
        req = self._request()
        o, d = self.cam.ray(sx, sy)
        a0, a = req.drag_axis
        t = ray_axis_param(o, d, a0, a)
        step = nice_step(self.cam.mm_per_pixel(a0))
        t = round(t / step) * step
        if getattr(req, "positive", False):
            t = max(t, step)
        self.drag_value = t
        if req.preview3d is not None:
            self._preview_timer.start()

    def _update_preview_shape(self) -> None:
        req = self._request()
        if not isinstance(req, GetDistance) or req.preview3d is None or self.drag_value is None:
            self.preview_item = None
            return
        key = (id(req), self.drag_value)
        if key == self._preview_key:
            return
        self._preview_key = key
        try:
            shape = req.preview3d(self.drag_value) if abs(self.drag_value) > 1e-9 else None
            self.preview_item = item_from_shape(shape) if shape is not None else None
        except Exception:
            self.preview_item = None
        self._image = None
        self.update()

    # ================================================================ mouse
    def mousePressEvent(self, ev) -> None:
        pos = ev.position()
        self.press(pos.x(), pos.y(), ev.button(), ev.modifiers())

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        self.move_to(pos.x(), pos.y(), ev.modifiers())

    def mouseReleaseEvent(self, ev) -> None:
        pos = ev.position()
        self.release(pos.x(), pos.y(), ev.button(), ev.modifiers())

    def press(self, x, y, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier) -> None:
        self.setFocus()
        self._sync_cam()
        if button == Qt.MouseButton.MiddleButton:
            mode = "orbit" if mods & Qt.KeyboardModifier.ShiftModifier else "pan"
            self._drag = [mode, x, y, False, None]
        elif button == Qt.MouseButton.RightButton:
            self._drag = ["pan", x, y, False, None]
        elif button == Qt.MouseButton.LeftButton:
            if viewcube.contains(self.width(), x, y) and viewcube.hit(self.cam, self.width(), x, y):
                self._drag = ["cube", x, y, False, None]
                return
            h = self._handle_at(x, y) if not self.ctl.runner.is_active else None
            if h is not None:
                e = self._selected_solid()
                self._drag = ["handle", x, y, False, {"name": h[0], "xyz": h[1], "axis": h[2], "solid": e,
                                                      "bbox": S.bbox3(e.shape)}]
                return
            if not self.ctl.runner.is_active:
                e = self._selected_solid()
                if e is not None and self.solid_under(x, y) == e.handle:
                    self._drag = ["body", x, y, False, {"solid": e, "bbox": S.bbox3(e.shape)}]
                    return
            if not self.ctl.runner.is_active or isinstance(self._request(), GetSelection):
                self._drag = ["orbit", x, y, False, None]

    def move_to(self, x, y, mods=Qt.KeyboardModifier.NoModifier) -> None:
        self.cursor = (x, y)
        if self._drag is not None:
            mode, x0, y0, moved, data = self._drag
            dx, dy = x - x0, y - y0
            if not moved and math.hypot(dx, dy) < 4:
                return
            self._drag[3] = True
            if mode == "orbit":
                self.cam.orbit(dx, dy)
                self._drag[1:3] = [x, y]
            elif mode == "pan":
                self.cam.pan(dx, dy)
                self._drag[1:3] = [x, y]
            elif mode in ("handle", "body"):
                self._drag_solid(mode, data, x, y, mods)
            self._image = None
            self.update()
            return
        req = self._request()
        if isinstance(req, GetDistance) and req.drag_axis is not None:
            self._update_drag_value(x, y)
        self._hover_timer.start()
        self.update()

    def _drag_solid(self, mode, data, x, y, mods) -> None:
        e = data["solid"]
        o, d = self.cam.ray(x, y)
        step = nice_step(self.cam.mm_per_pixel(data["bbox"][:3]))
        if mode == "handle":
            a0, axis = np.array(data["xyz"]), np.array(data["axis"], float)
            t = ray_axis_param(o, d, a0, axis)
            if "t0" not in data:
                ox, oy = self._drag[1], self._drag[2]
                o0, d0 = self.cam.ray(ox, oy)
                data["t0"] = ray_axis_param(o0, d0, a0, axis)
            delta = round((t - data["t0"]) / step) * step
            try:
                shape, bb = self._resize_shape(e, data["name"], data["bbox"], delta)
            except S.SolidError:
                return
        else:
            z = data["bbox"][2]
            plane = S.XY.offset(z)
            q = ray_plane(o, d, plane)
            if q is None:
                return
            if "q0" not in data:
                o0, d0 = self.cam.ray(self._drag[1], self._drag[2])
                data["q0"] = ray_plane(o0, d0, plane)
                if data["q0"] is None:
                    return
            dv = np.round((q - data["q0"]) / step) * step
            dv[2] = 0
            shape = S.translate(e.shape, tuple(float(v) for v in dv))
            bb = tuple(np.array(data["bbox"]) + np.concatenate([dv, dv]))
        data["shape"] = shape
        data["item"] = item_from_shape(shape, rgb=(0.31, 0.63, 1.0), alpha=0.85, handle=-2)
        self.handle_drag = {"handle": e.handle, "item": data["item"], "bbox": bb}

    def release(self, x, y, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier) -> None:
        drag, self._drag = self._drag, None
        if drag is not None and drag[0] in ("handle", "body"):
            data = drag[4]
            self.handle_drag = None
            if drag[3] and data.get("shape") is not None:
                self._commit_resize(data["solid"], data["shape"], "Move" if drag[0] == "body" else "Resize")
            self._image = None
            self.update()
            if drag[3]:
                return
        if drag is not None and drag[0] == "cube":
            self._cube_click(x, y)
            return
        if button != Qt.MouseButton.LeftButton:
            if button == Qt.MouseButton.RightButton and drag is not None and not drag[3]:
                if self.ctl.runner.is_active:
                    self.ctl.enter()       # right-click without dragging = Enter, like the plan view
                else:
                    self._context_tools(x, y)
                self._image = None
                self.update()
            return
        if drag is not None and drag[3]:
            return            # it was an orbit
        label = self._label_at(x, y) if not self.ctl.runner.is_active else None
        if label is not None:
            self._edit_label(label)
            return
        self.click(x, y, bool(mods & Qt.KeyboardModifier.ShiftModifier))

    def _cube_click(self, x, y) -> None:
        h = viewcube.hit(self.cam, self.width(), x, y)
        if h is None:
            return
        kind, val = h
        if kind == "home":
            self.set_view("SW Iso")
            return
        if kind == "face":
            self.cam.set_view(val)
        else:
            self.cam.azimuth, self.cam.elevation = val
        self._image = None
        self.update()

    def mouseDoubleClickEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.zoom_extents()

    def wheelEvent(self, ev) -> None:
        steps = ev.angleDelta().y() / 120.0
        pos = ev.position()
        self._sync_cam()
        self.cam.zoom(1.2 ** steps, pos.x(), pos.y())
        self._image = None
        self.update()

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key.Key_Escape and self.bar.isVisible() and not self.ctl.runner.is_active:
            self.bar.hide()
        if not self.ctl.on_key_press(ev):
            super().keyPressEvent(ev)
        self._image = None
        self.update()

    def keyReleaseEvent(self, ev) -> None:
        self.ctl.on_key_release(ev)

    def leaveEvent(self, ev) -> None:
        self.cube_hover = None
        self.update()

    def _update_hover(self) -> None:
        if self.cursor is None:
            return
        sx, sy = self.cursor
        cube = viewcube.hit(self.cam, self.width(), sx, sy) if viewcube.contains(self.width(), sx, sy) else None
        if cube != self.cube_hover:
            self.cube_hover = cube
        self.snap = self._snap_at(sx, sy) if self._wants_point() else None
        req = self._request()
        h = None
        if not self.ctl.runner.is_active or isinstance(req, (GetSelection, GetFace, GetEntity)):
            h = self.solid_under(sx, sy)
        if h != self.hover:
            self.hover = h
            self._image = None
        if self._wants_point():
            pt = self.point_under(sx, sy) if self.workplane is None else None
            if self.workplane is not None:
                loc = self._plane_point(sx, sy)
                pt = None if loc is None else self.workplane[1].to_world(*loc)
            if pt is not None:
                from ..core.units import format_length
                u = self.ctl.runner.ctx.units
                self.status.emit(", ".join(format_length(v, u) for v in pt))
        self.update()

    # ================================================================ drag and drop shapes
    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasFormat(SHAPE_MIME):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev) -> None:
        if ev.mimeData().hasFormat(SHAPE_MIME):
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        if not ev.mimeData().hasFormat(SHAPE_MIME):
            return
        kind, _, hole = bytes(ev.mimeData().data(SHAPE_MIME)).decode().partition("|")
        pos = ev.position()
        self._sync_cam()
        self.snap = None
        pt = self.point_under(pos.x(), pos.y()) or (0.0, 0.0, 0.0)
        ev.acceptProposedAction()
        self.drop_requested.emit(kind, hole == "hole", tuple(float(v) for v in pt))

    # ================================================================ clicking
    def click(self, sx: float, sy: float, shift: bool = False) -> None:
        """A left click at a screen position (also used by tests)."""
        runner = self.ctl.runner
        req = runner.request
        self._sync_cam()
        self.bar.hide()
        o, d = self.cam.ray(sx, sy)
        if isinstance(req, (GetFace, GetEdge)):
            hit = pick_face(self.doc, o, d)
            tol = self._tolerance_mm(hit.point if hit else None)
            runner.submit_ray(o, d, tolerance=tol)
        elif isinstance(req, GetDistance) and req.drag_axis is not None:
            self._update_drag_value(sx, sy)
            if self.drag_value is not None:
                runner.submit_value(self.drag_value)
        elif isinstance(req, (GetPoint, GetDistance, GetAngle, GetNumber)):
            if self.workplane is None and self._is_draw_command():
                self._begin_workplane(sx, sy)
            self.snap = self._snap_at(sx, sy)
            if self.workplane is not None:
                loc = self._plane_point(sx, sy)
                if loc is None:
                    runner.ctx.echo("Point at the drawing plane, or type the point.")
                    return
                self.last_point3 = self.workplane[1].to_world(*loc)
                runner.submit_ray(o, d, pt2=loc, z=0.0)
            else:
                pt = self.point_under(sx, sy)
                if pt is None:
                    runner.ctx.echo("Click on a solid or the ground (z = 0), or type x,y,z.")
                    return
                self.last_point3 = pt
                runner.submit_ray(o, d, pt2=(pt[0], pt[1]), z=pt[2])
        elif isinstance(req, GetEntity):
            h = self.object_under(sx, sy)
            if h is None:
                runner.ctx.echo("Nothing found there. Click right on an object.")
                return
            pt = self.point_under(sx, sy) or (0.0, 0.0, 0.0)
            runner.submit_entity(h, (pt[0], pt[1]))
        else:
            h = self.object_under(sx, sy)
            target = self.ctl.selection_target()
            if h is None:
                if not shift and not isinstance(req, GetSelection):
                    target.clear()
            elif shift or h in target:
                target.discard(h)
            else:
                target.add(h)
            self.ctl._selection_updated()
            if not runner.is_active and h is not None and h in target:
                self._context_tools(sx, sy, after_select=True)
        self.snap = None
        self.ctl._after_input()
        self._image = None
        self.update()

    # ================================================================ context toolbar
    def _context_tools(self, sx, sy, after_select: bool = False) -> None:
        """Tools for what's under the cursor (and the selection)."""
        o, d = self.cam.ray(sx, sy)
        face = pick_face(self.doc, o, d)
        tol = self._tolerance_mm(face.point if face else None)
        edge = pick_edge(self.doc, o, d, tol)
        sel = [self.doc.get(h) for h in self.ctl.runner.ctx.selection]
        sel_solids = [e for e in sel if isinstance(e, Solid)]
        tools = []

        def run(cmd, picks=()):
            return lambda: self.run_requested.emit(cmd, list(picks))
        if edge is not None:
            tools += [("filletedge", "Round", "Round this edge (Fillet Edge). Click more edges, then Enter.",
                       run("FILLETEDGE", [edge])),
                      ("chamferedge", "Bevel", "Bevel this edge (Chamfer Edge)", run("CHAMFEREDGE", [edge]))]
        if face is not None:
            f = S.faces(face.entity.shape)[face.face]
            pl = aligned_face_plane(f)
            if pl is not None:
                tools += [("presspull", "Push/Pull", "Push this face in or pull it out: move the mouse, click",
                           run("PRESSPULL", [face])),
                          ("sketch", "Draw on it", "Start a sketch on this face", lambda: self._sketch_here(pl)),
                          ("view3d", "Look at", "Turn the view to look straight at this face",
                           lambda: self.look_at_plane(pl))]
            tools.append(("shell", "Hollow", "Hollow out this solid, leaving this face open (Shell)",
                          run("SHELL", [face])))
        if sel_solids:
            if any(not s.hole for s in sel_solids):
                tools.append(("makehole", "Make hole", "Turn the selection into hole shapes", run("MAKEHOLE")))
            if any(s.hole for s in sel_solids):
                tools.append(("makesolid", "Make solid", "Turn the hole shapes back into solids", run("MAKESOLID")))
            if len(sel_solids) >= 2:
                tools += [("combine", "Combine", "Join the selected solids and cut the holes", run("COMBINE")),
                          ("alignobjects", "Align", "Line up the selected objects", run("ALIGNOBJECTS"))]
            tools += [("3dmove", "Move", "Move by x,y,z", run("3DMOVE")),
                      ("3drotate", "Rotate", "Turn around X, Y or Z", run("3DROTATE")),
                      ("massprop", "Volume", "Volume, area, center of mass", run("MASSPROP")),
                      ("erase", "Delete", "Delete the selection", run("ERASE"))]
        if not tools:
            tools = [("view3d", "Fit all", "Zoom to see everything", self.zoom_extents)]
        self.bar.show_tools(tools, (sx, sy), self.icon_for)

    def _sketch_here(self, plane) -> None:
        from ..commands.sketch3d import make_sketch, refresh_reference
        sk = self._sketch_on(plane)
        if sk is None:
            with self.doc.transaction("Sketch on face"):
                sk = make_sketch(self.doc, plane, self._face_sketch_name())
                refresh_reference(self.doc, sk)
        self.run_requested.emit("EDITSKETCH:" + sk.name, [])


__all__ = ["View3D", "STYLES", "PRESETS", "SHAPE_MIME", "aligned_face_plane", "nice_step", "ray_axis_param",
           "EdgePick", "FacePick", "time"]
