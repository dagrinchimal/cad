"""The 3D view: orbit, pan and zoom around the model, pick faces/edges/points for commands, select solids.

Mouse:  left-drag (no command) or Shift+middle-drag = orbit;  middle-drag or right-drag = pan;
        wheel = zoom at the cursor;  left-click = pick / select;  double-click middle = zoom extents.
Keys go to the command line like in the plan view.
"""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..commands.framework import (
    GetAngle, GetDistance, GetEdge, GetEntity, GetFace, GetNumber, GetPoint, GetSelection,
)
from ..core import solids as S
from ..core.solid_pick import pick_edge, pick_face, snap_points_3d
from ..render.camera3d import PRESETS, Camera3D
from ..render.raster3d import get_renderer
from ..render.scene3d import DEFAULT_STYLE, STYLES, Scene3DBuilder

SNAP_PX = 10.0
PICK_PX = 6.0


class View3D(QWidget):
    """Draws the model in 3D. Talks to the same command runner and selection as the plan view."""

    status = Signal(str)

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.ctl = controller
        self.doc = controller.doc
        self.cam = Camera3D()
        self.style = DEFAULT_STYLE
        self.builder = Scene3DBuilder(self.doc)
        self.renderer = None
        self._scene = None
        self._image = None
        self._dirty = True
        self._drag = None             # ("orbit"|"pan", last x, last y, moved)
        self._press = None
        self.hover = None             # solid handle under the cursor
        self.snap = None              # (xyz, kind) snapped point under the cursor
        self.cursor = None            # screen position
        self.last_point3 = None       # last picked 3D point (for rubber bands)
        self.fitted = False
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(200, 150)
        self.doc.add_listener(self._on_doc)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(30)
        self._hover_timer.timeout.connect(self._update_hover)

    # ------------------------------------------------------------ state
    def set_document(self, doc) -> None:
        try:
            self.doc.remove_listener(self._on_doc)
        except Exception:
            pass
        self.doc = doc
        self.builder = Scene3DBuilder(doc)
        doc.add_listener(self._on_doc)
        self.fitted = False
        self.invalidate()

    def _on_doc(self, doc, cs) -> None:
        self.invalidate()

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

    # ------------------------------------------------------------ painting
    def _background(self) -> QColor:
        return QColor(33, 40, 48) if getattr(self.ctl, "dark", True) else QColor(250, 250, 250)

    def render_image(self):
        if self.renderer is None:
            self.renderer = get_renderer()
        self.cam.width, self.cam.height = max(self.width(), 1), max(self.height(), 1)
        sel = set(self.ctl.runner.ctx.selection) | set(getattr(self.ctl, "pending_sel", set()))
        return self.renderer.render(self.scene(), self.cam, self.style, self._background(), sel, self.hover,
                                    getattr(self.ctl, "dark", True))

    def paintEvent(self, ev) -> None:
        if not self.fitted and self.width() > 1:
            self.zoom_extents()
        if self._image is None or self._image.width() != self.width() or self._image.height() != self.height():
            try:
                self._image = self.render_image()
            except Exception as exc:            # a GL failure falls back to the software renderer
                from ..render.raster3d import PainterRenderer
                if not isinstance(self.renderer, PainterRenderer):
                    self.renderer = PainterRenderer()
                    self._image = self.render_image()
                else:
                    raise exc
        p = QPainter(self)
        p.drawImage(0, 0, self._image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_overlay(p)
        p.end()

    def _paint_overlay(self, p: QPainter) -> None:
        dark = getattr(self.ctl, "dark", True)
        fg = QColor(230, 230, 230) if dark else QColor(40, 40, 40)
        # axis tripod (bottom left)
        o = np.array([46.0, self.height() - 46.0])
        for vec, name, col in (((1, 0, 0), "X", QColor(230, 80, 80)), ((0, 1, 0), "Y", QColor(90, 200, 90)),
                               ((0, 0, 1), "Z", QColor(90, 140, 255))):
            v = np.array(vec, float)
            d = np.array([v @ self.cam.right, -(v @ self.cam.up)]) * 30
            p.setPen(QPen(col, 2))
            p.drawLine(QPointF(*o), QPointF(*(o + d)))
            p.drawText(QPointF(*(o + d * 1.25 - (4, -4))), name)
        # view name and style (top left)
        f = QFont()
        f.setPointSizeF(9)
        p.setFont(f)
        p.setPen(fg)
        p.drawText(QRectF(8, 6, 600, 18), Qt.AlignmentFlag.AlignLeft,
                   f"[{self.view_name()}] [{self.style}]{' [Perspective]' if self.cam.perspective else ''}"
                   "   Drag: orbit · Middle/right drag: pan · Wheel: zoom")
        # snap marker / cursor
        if self.snap is not None:
            (sx, sy), _ = self.cam.project(np.array([self.snap[0]]))
            sx, sy = float(sx[0]) if np.ndim(sx) else sx, float(sy[0]) if np.ndim(sy) else sy
            p.setPen(QPen(QColor(80, 220, 80), 2))
            p.drawRect(QRectF(sx - 5, sy - 5, 10, 10))
            p.drawText(QPointF(sx + 8, sy - 8), self.snap[1])
        if self.last_point3 is not None and self.cursor is not None and self._wants_point():
            (a,), _ = self.cam.project(np.array([self.last_point3]))
            p.setPen(QPen(fg, 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(*a), QPointF(*self.cursor))

    def view_name(self) -> str:
        for name, (az, el) in PRESETS.items():
            if abs((self.cam.azimuth - az + 180) % 360 - 180) < 0.5 and abs(self.cam.elevation - el) < 0.5:
                return name
        return "Custom"

    # ------------------------------------------------------------ picking helpers
    def _request(self):
        return self.ctl.runner.request

    def _wants_point(self) -> bool:
        return isinstance(self._request(), (GetPoint, GetDistance, GetAngle, GetNumber))

    def _tolerance_mm(self, point=None) -> float:
        return PICK_PX * self.cam.mm_per_pixel(point)

    def _snap_at(self, sx, sy):
        pts = snap_points_3d(self.doc)
        if not pts:
            return None
        xyz = np.array([p for p, _ in pts], float)
        scr, depth = self.cam.project(xyz)
        d = np.hypot(scr[:, 0] - sx, scr[:, 1] - sy)
        near = np.where(d <= SNAP_PX)[0]
        if not len(near):
            return None
        i = near[np.argmin(depth[near] + d[near] * 1e-6)]
        # only snap to points the eye can see (or close to the hit surface)
        o, dvec = self.cam.ray(sx, sy)
        hit = pick_face(self.doc, o, dvec)
        if hit is not None:
            hp = np.array(hit.point)
            if (xyz[i] - hp) @ self.cam.forward > max(self._tolerance_mm(hp) * 3, 1e-6):
                return None
        return (tuple(float(v) for v in xyz[i]), pts[i][1])

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
                p = o + d * t
                return (float(p[0]), float(p[1]), 0.0)
        return None

    def solid_under(self, sx, sy):
        o, d = self.cam.ray(sx, sy)
        hit = pick_face(self.doc, o, d)
        return hit.entity.handle if hit is not None else None

    def wire_under(self, sx, sy):
        best = None
        for w in self.scene().wires:
            for ln in w.lines:
                scr, depth = self.cam.project(ln)
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

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, ev) -> None:
        self.setFocus()
        pos = ev.position()
        b = ev.buttons()
        if ev.button() == Qt.MouseButton.MiddleButton:
            mode = "orbit" if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier else "pan"
            self._drag = [mode, pos.x(), pos.y(), False]
        elif ev.button() == Qt.MouseButton.RightButton:
            self._drag = ["pan", pos.x(), pos.y(), False]
        elif ev.button() == Qt.MouseButton.LeftButton:
            self._press = (pos.x(), pos.y(), time.monotonic())
            if not self.ctl.runner.is_active or isinstance(self._request(), GetSelection):
                self._drag = ["orbit", pos.x(), pos.y(), False]
        _ = b

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        self.cursor = (pos.x(), pos.y())
        if self._drag is not None:
            mode, x0, y0, moved = self._drag
            dx, dy = pos.x() - x0, pos.y() - y0
            if not moved and math.hypot(dx, dy) < 4:
                return
            self._drag = [mode, pos.x(), pos.y(), True]
            if mode == "orbit":
                self.cam.orbit(dx, dy)
            else:
                self.cam.pan(dx, dy)
            self._image = None
            self.update()
            return
        self._hover_timer.start()
        self.update()

    def _update_hover(self) -> None:
        if self.cursor is None:
            return
        sx, sy = self.cursor
        self.snap = self._snap_at(sx, sy) if self._wants_point() else None
        req = self._request()
        h = None
        if not self.ctl.runner.is_active or isinstance(req, (GetSelection, GetFace, GetEntity)):
            h = self.solid_under(sx, sy)
        if h != self.hover:
            self.hover = h
            self._image = None
        pt = self.point_under(sx, sy) if self._wants_point() else None
        if pt is not None:
            u = self.ctl.runner.ctx.units
            from ..core.units import format_length
            self.status.emit(", ".join(format_length(v, u) for v in pt))
        self.update()

    def mouseReleaseEvent(self, ev) -> None:
        pos = ev.position()
        drag, self._drag = self._drag, None
        if ev.button() != Qt.MouseButton.LeftButton:
            if ev.button() == Qt.MouseButton.RightButton and drag is not None and not drag[3]:
                self.ctl.enter()       # right-click without dragging = Enter, like the plan view
                self._image = None
                self.update()
            return
        if drag is not None and drag[3]:
            return            # it was an orbit
        self.click(pos.x(), pos.y(), bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier))

    def mouseDoubleClickEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.zoom_extents()

    def wheelEvent(self, ev) -> None:
        steps = ev.angleDelta().y() / 120.0
        pos = ev.position()
        self.cam.width, self.cam.height = max(self.width(), 1), max(self.height(), 1)
        self.cam.zoom(1.2 ** steps, pos.x(), pos.y())
        self._image = None
        self.update()

    def keyPressEvent(self, ev) -> None:
        if not self.ctl.on_key_press(ev):
            super().keyPressEvent(ev)
        self._image = None
        self.update()

    def keyReleaseEvent(self, ev) -> None:
        self.ctl.on_key_release(ev)

    # ------------------------------------------------------------ clicking
    def click(self, sx: float, sy: float, shift: bool = False) -> None:
        """A left click at a screen position (also used by tests)."""
        runner = self.ctl.runner
        req = runner.request
        self.cam.width, self.cam.height = max(self.width(), 1), max(self.height(), 1)
        o, d = self.cam.ray(sx, sy)
        if isinstance(req, (GetFace, GetEdge)):
            hit = pick_face(self.doc, o, d)
            tol = self._tolerance_mm(hit.point if hit else None)
            runner.submit_ray(o, d, tolerance=tol)
        elif isinstance(req, (GetPoint, GetDistance, GetAngle, GetNumber)):
            self.snap = self._snap_at(sx, sy)
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
        self.snap = None
        self.ctl._after_input()
        self._image = None
        self.update()


__all__ = ["View3D", "STYLES", "PRESETS", "S"]
