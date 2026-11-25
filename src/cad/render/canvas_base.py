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


class SceneData:
    """Everything a canvas draws besides the overlay."""

    def __init__(self) -> None:
        empty = np.zeros((0, 12), dtype=np.float32)
        self.scene = empty
        self.grid = empty
        self.highlight = empty
        self.preview = empty
        self.origin = (0.0, 0.0)
        self.linetypes: tuple[list[float], list[float], list[int]] = ([0.0] * 256, [0.0] * 32, [0] * 32)
        self.global_ltscale = 1.0
        self.background = QColor(33, 40, 48)
        self.scene_version = 0
        self.grid_version = 0


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
