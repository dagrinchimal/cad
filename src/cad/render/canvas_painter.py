"""Software (QPainter) canvas: slower, but works on any machine without OpenGL 3.3."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QLineF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .canvas_base import CanvasEventsMixin, SceneData


def draw_instances(painter: QPainter, inst: np.ndarray, data: SceneData, view, dpr: float = 1.0) -> None:
    if len(inst) == 0:
        return
    ox, oy = data.origin
    s = view.scale
    hw, hh = view.width / 2, view.height / 2
    x0 = (inst[:, 0] + ox - view.cx) * s + hw
    y0 = hh - (inst[:, 1] + oy - view.cy) * s
    x1 = (inst[:, 2] + ox - view.cx) * s + hw
    y1 = hh - (inst[:, 3] + oy - view.cy) * s
    # cull segments outside the window
    vis = ~(((x0 < 0) & (x1 < 0)) | ((x0 > view.width) & (x1 > view.width))
            | ((y0 < 0) & (y1 < 0)) | ((y0 > view.height) & (y1 > view.height)))
    if not vis.any():
        return
    idx = np.nonzero(vis)[0]
    styles = inst[idx][:, 5:12]
    keys, inverse = np.unique(styles, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    pats, lens, counts = data.linetypes
    for k, key in enumerate(keys):
        r, g, b, a, width, lt, lts = (float(x) for x in key)
        pen = QPen(QColor.fromRgbF(r, g, b, a))
        pen.setWidthF(max(1.0, width))
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        lti = int(round(lt))
        if lti > 0 and counts[lti]:
            scale = lts * data.global_ltscale * s / max(1.0, width)
            if lens[lti] * lts * data.global_ltscale * s > 6:
                dashes = []
                for v in pats[lti * 8: lti * 8 + counts[lti]]:
                    dashes.append(max(abs(v) * scale, 0.5 if v >= 0 else 1.0))
                if len(dashes) % 2:
                    dashes.append(dashes[-1])
                pen.setDashPattern(dashes)
        painter.setPen(pen)
        sel = idx[inverse == k]
        lines = [QLineF(a0, b0, a1, b1) for a0, b0, a1, b1 in
                 zip(x0[sel].tolist(), y0[sel].tolist(), x1[sel].tolist(), y1[sel].tolist())]
        painter.drawLines(lines)


class PainterCanvas(CanvasEventsMixin, QWidget):
    backend_name = "Software"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.data = SceneData()
        self.view = None
        self._cache: QImage | None = None
        self.gl_info = "Software renderer (QPainter)"

    def invalidate(self) -> None:
        self._cache = None
        self.update()

    def _render_cache(self) -> QImage:
        dpr = self.devicePixelRatioF()
        img = QImage(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(self.data.background)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        draw_instances(p, self.data.grid, self.data, self.view)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw_instances(p, self.data.scene, self.data, self.view)
        p.end()
        return img

    def paintEvent(self, ev):               # noqa: N802
        p = QPainter(self)
        if self.view is None:
            p.fillRect(self.rect(), self.data.background)
            p.end()
            return
        if self._cache is None or self._cache.size() != self.size() * self.devicePixelRatioF():
            self._cache = self._render_cache()
        p.drawImage(0, 0, self._cache)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw_instances(p, self.data.highlight, self.data, self.view)
        draw_instances(p, self.data.preview, self.data, self.view)
        if self.client:
            self.client.paint_overlay(p)
        p.end()

    def grab_image(self):
        return self.grab().toImage()
