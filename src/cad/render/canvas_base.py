"""Shared canvas plumbing: event forwarding and backend selection."""
from __future__ import annotations

import logging
import os
from typing import Protocol

import numpy as np
from PySide6.QtGui import QColor, QPainter

log = logging.getLogger(__name__)


class CanvasClient(Protocol):
    """What a canvas needs from its controller."""
    view: object

    def paint_overlay(self, painter: QPainter) -> None: ...
    def on_mouse_press(self, ev) -> None: ...
    def on_mouse_release(self, ev) -> None: ...
    def on_mouse_move(self, ev) -> None: ...
    def on_wheel(self, ev) -> None: ...
    def on_double_click(self, ev) -> None: ...
    def on_key_press(self, ev) -> bool: ...
    def on_leave(self) -> None: ...
    def on_resize(self, w: int, h: int) -> None: ...
    def on_context_menu(self, ev) -> None: ...


class CanvasEventsMixin:
    """Forwards Qt events to the controller. Mixed into QWidget/QOpenGLWidget subclasses."""
    client: CanvasClient | None = None

    def mousePressEvent(self, ev):          # noqa: N802
        if self.client:
            self.client.on_mouse_press(ev)

    def mouseReleaseEvent(self, ev):        # noqa: N802
        if self.client:
            self.client.on_mouse_release(ev)

    def mouseMoveEvent(self, ev):           # noqa: N802
        if self.client:
            self.client.on_mouse_move(ev)

    def mouseDoubleClickEvent(self, ev):    # noqa: N802
        if self.client:
            self.client.on_double_click(ev)

    def wheelEvent(self, ev):               # noqa: N802
        if self.client:
            self.client.on_wheel(ev)

    def keyPressEvent(self, ev):            # noqa: N802
        if not (self.client and self.client.on_key_press(ev)):
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):          # noqa: N802
        if self.client and hasattr(self.client, "on_key_release"):
            self.client.on_key_release(ev)
        super().keyReleaseEvent(ev)

    def leaveEvent(self, ev):               # noqa: N802
        if self.client:
            self.client.on_leave()
        super().leaveEvent(ev)

    def contextMenuEvent(self, ev):         # noqa: N802
        if self.client:
            self.client.on_context_menu(ev)

    def resizeEvent(self, ev):              # noqa: N802
        super().resizeEvent(ev)
        if self.client:
            self.client.on_resize(self.width(), self.height())


class ViewportView:
    """Where a layout viewport shows model space: a screen clip rectangle and an equivalent view."""

    def __init__(self, clip: tuple[float, float, float, float], cx: float, cy: float, scale: float,
                 width: int, height: int) -> None:
        self.clip = clip              # x, y, w, h in logical pixels
        self.cx, self.cy, self.scale = cx, cy, scale
        self.width, self.height = width, height


class SceneData:
    """Everything a canvas draws besides the overlay.

    Segment arrays have 12 floats per row (see render.scene); fill arrays have 6 per triangle vertex.
    In a layout, `scene`/`scene_fill` hold the paper-space objects, `underlay_fill` the sheet, and
    `model`/`model_fill` are drawn once per entry of `viewports`.
    """

    def __init__(self) -> None:
        empty = np.zeros((0, 12), dtype=np.float32)
        empty_f = np.zeros((0, 6), dtype=np.float32)
        self.scene = empty
        self.scene_fill = empty_f
        self.grid = empty
        self.highlight = empty
        self.highlight_fill = empty_f
        self.preview = empty
        self.preview_fill = empty_f
        self.underlay_fill = empty_f
        self.model = empty
        self.model_fill = empty_f
        self.viewports: list[ViewportView] = []
        self.origin = (0.0, 0.0)
        self.linetypes: tuple[list[float], list[float], list[int]] = ([0.0] * 256, [0.0] * 32, [0] * 32)
        self.global_ltscale = 1.0
        self.background = QColor(33, 40, 48)
        self.scene_version = 0
        self.grid_version = 0
        self.model_version = 0


def renderer_preference() -> str:
    """'gl', 'painter' or 'auto' from the CAD_RENDERER environment variable."""
    return os.environ.get("CAD_RENDERER", "auto").strip().lower()


def opengl_33_available() -> bool:
    """Try to create an OpenGL 3.3 core context (needs a QGuiApplication)."""
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        return False
    v = ctx.format().version()
    if (v[0], v[1]) < (3, 3):
        return False
    surf = QOffscreenSurface()
    surf.setFormat(ctx.format())
    surf.create()
    ok = ctx.makeCurrent(surf)
    if ok:
        ctx.doneCurrent()
    return ok


def create_canvas(parent=None):
    """Make the best canvas this machine supports."""
    pref = renderer_preference()
    if pref != "painter":
        try:
            if pref == "gl" or opengl_33_available():
                from .canvas_gl import GLCanvas
                return GLCanvas(parent)
        except Exception:                      # noqa: BLE001
            log.exception("OpenGL canvas unavailable; using the software renderer")
    from .canvas_painter import PainterCanvas
    return PainterCanvas(parent)
