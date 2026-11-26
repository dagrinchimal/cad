"""Draws plot Sheets with QPainter: used for PDF, printing, PNG/JPG/TIFF and print preview."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

from ..core.plot import Fill, Sheet, Stroke

MIN_PEN_PX = 0.0          # 0 = cosmetic hairline is not used; widths come from lineweights


def _poly(arr) -> QPolygonF:
    return QPolygonF([QPointF(float(x), float(y)) for x, y in arr])


def paint_sheet(p: QPainter, sheet: Sheet, target: QRectF, background: QColor | None = None,
                min_width_px: float = 0.5) -> None:
    """Draw `sheet` (paper mm, y up) scaled into `target` (device units, y down), keeping proportions.

    min_width_px keeps very thin lines visible on low-resolution outputs (images, preview)."""
    sx = target.width() / sheet.width
    sy = target.height() / sheet.height
    s = min(sx, sy)
    ox = target.left() + (target.width() - sheet.width * s) / 2
    oy = target.top() + (target.height() + sheet.height * s) / 2
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if background is not None:
        p.fillRect(QRectF(ox, oy - sheet.height * s, sheet.width * s, sheet.height * s), background)
    p.translate(ox, oy)
    p.scale(s, -s)                    # now in paper mm, y up
    min_w = min_width_px / s
    pen = QPen()
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    last_color = None
    for it in sheet.items:
        if isinstance(it, Stroke):
            if it.color != last_color:
                last_color = it.color
            pen.setColor(QColor(*it.color))
            pen.setWidthF(max(it.width, min_w))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if len(it.pts) == 2:
                (x0, y0), (x1, y1) = it.pts
                p.drawLine(QPointF(float(x0), float(y0)), QPointF(float(x1), float(y1)))
            elif it.closed:
                p.drawPolygon(_poly(it.pts[:-1]))
            else:
                p.drawPolyline(_poly(it.pts))
        elif isinstance(it, Fill):
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.OddEvenFill)
            for lp in it.loops:
                path.addPolygon(_poly(lp))
                path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(*it.color)))
            p.drawPath(path)
    p.restore()


def render_image(sheet: Sheet, dpi: float, background=(255, 255, 255), transparent: bool = False,
                 max_pixels: int = 400_000_000) -> QImage:
    """The sheet as an image at dpi (paper size x dpi)."""
    w = max(1, round(sheet.width / 25.4 * dpi))
    h = max(1, round(sheet.height / 25.4 * dpi))
    if w * h > max_pixels:
        raise ValueError(f"{w} x {h} pixels is too big; lower the resolution.")
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.setDotsPerMeterX(round(dpi / 0.0254))
    img.setDotsPerMeterY(round(dpi / 0.0254))
    img.fill(QColor(0, 0, 0, 0) if transparent else QColor(*background))
    p = QPainter(img)
    paint_sheet(p, sheet, QRectF(0, 0, w, h), min_width_px=1.0)
    p.end()
    return img
