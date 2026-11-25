"""Icons drawn in code (crisp at any UI scale, recolored for light/dark themes).

Each icon is a list of shapes on a 24x24 grid:
  ("l", x1, y1, x2, y2)          line
  ("c", cx, cy, r)               circle
  ("a", cx, cy, r, start, span)  arc, degrees, Qt convention (counter-clockwise, y up on screen)
  ("r", x, y, w, h)              rectangle
  ("p", [(x, y), ...], closed)   polyline
  ("d", x, y)                    accent dot (a picked point)
  ("t", x, y, text)              small text
Shapes after "accent" are drawn in the accent color.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

ICONS: dict[str, list] = {
    "line": [("l", 4, 20, 20, 4), "accent", ("d", 4, 20), ("d", 20, 4)],
    "pline": [("p", [(3, 19), (9, 7), (15, 15)], False), ("a", 15, 11, 4, 270, 180), ("l", 19, 11, 21, 4),
              "accent", ("d", 3, 19), ("d", 9, 7), ("d", 15, 15)],
    "circle": [("c", 12, 12, 8), "accent", ("d", 12, 12), ("l", 12, 12, 20, 12)],
    "circle_2p": [("c", 12, 12, 8), "accent", ("d", 4, 12), ("d", 20, 12)],
    "circle_3p": [("c", 12, 12, 8), "accent", ("d", 4, 12), ("d", 12, 4), ("d", 20, 12)],
    "arc": [("a", 12, 15, 9, 0, 180), "accent", ("d", 3, 15), ("d", 12, 6), ("d", 21, 15)],
    "arc_center": [("a", 12, 15, 9, 0, 180), "accent", ("d", 12, 15), ("d", 21, 15), ("d", 3, 15)],
    "point": [("l", 8, 12, 16, 12), ("l", 12, 8, 12, 16), "accent", ("d", 12, 12)],
    "erase": [("p", [(5, 15), (12, 6), (20, 12), (13, 21), (8, 21)], True), ("l", 9, 10, 16, 17),
              "accent", ("l", 13, 21, 21, 21)],
    "undo": [("a", 13, 13, 6, 90, -230), ("p", [(4, 8), (7, 13), (10, 8)], False)],
    "redo": [("a", 11, 13, 6, 90, 230), ("p", [(14, 8), (17, 13), (20, 8)], False)],
    "zoomextents": [("r", 3, 3, 18, 18), "accent", ("p", [(7, 10), (7, 7), (10, 7)], False),
                    ("p", [(14, 7), (17, 7), (17, 10)], False), ("p", [(17, 14), (17, 17), (14, 17)], False),
                    ("p", [(10, 17), (7, 17), (7, 14)], False)],
    "zoomwindow": [("c", 10, 10, 6), ("l", 14.5, 14.5, 20, 20), "accent", ("r", 7, 7, 6, 6)],
    "zoom": [("c", 10, 10, 6), ("l", 14.5, 14.5, 20, 20), "accent", ("l", 7, 10, 13, 10), ("l", 10, 7, 10, 13)],
    "zoomin": [("c", 10, 10, 6), ("l", 14.5, 14.5, 20, 20), "accent", ("l", 7, 10, 13, 10), ("l", 10, 7, 10, 13)],
    "zoomout": [("c", 10, 10, 6), ("l", 14.5, 14.5, 20, 20), "accent", ("l", 7, 10, 13, 10)],
    "zoomprevious": [("c", 11, 11, 6), ("l", 15.5, 15.5, 20, 20), "accent", ("p", [(9, 8), (7, 11), (9, 14)], False)],
    "pan": [("l", 12, 3, 12, 21), ("l", 3, 12, 21, 12), ("p", [(9, 6), (12, 3), (15, 6)], False),
            ("p", [(9, 18), (12, 21), (15, 18)], False), ("p", [(6, 9), (3, 12), (6, 15)], False),
            ("p", [(18, 9), (21, 12), (18, 15)], False)],
    "regen": [("a", 12, 12, 7, 30, 300), "accent", ("p", [(17, 4), (18.5, 8.5), (14, 9)], False)],
    "layer": [("p", [(12, 4), (21, 8), (12, 12), (3, 8)], True), ("p", [(3, 12), (12, 16), (21, 12)], False),
              "accent", ("p", [(3, 16), (12, 20), (21, 16)], False)],
    "units": [("r", 2, 9, 20, 7), ("l", 6, 9, 6, 12), ("l", 10, 9, 10, 14), ("l", 14, 9, 14, 12),
              ("l", 18, 9, 18, 14)],
    "dsettings": [("r", 4, 4, 16, 16), "accent", ("d", 4, 4), ("d", 12, 4), ("d", 20, 4), ("d", 4, 12),
                  ("d", 12, 12), ("d", 20, 12), ("d", 4, 20), ("d", 12, 20), ("d", 20, 20)],
    "options": [("c", 12, 12, 4), ("c", 12, 12, 8), "accent", ("l", 12, 2, 12, 6), ("l", 12, 18, 12, 22),
                ("l", 2, 12, 6, 12), ("l", 18, 12, 22, 12)],
    "new": [("p", [(6, 3), (15, 3), (19, 7), (19, 21), (6, 21)], True), ("p", [(15, 3), (15, 7), (19, 7)], False)],
    "open": [("p", [(3, 6), (9, 6), (11, 8), (20, 8), (20, 19), (3, 19)], True), "accent",
             ("l", 3, 11, 20, 11)],
    "qsave": [("p", [(4, 4), (17, 4), (20, 7), (20, 20), (4, 20)], True), ("r", 8, 4, 8, 5), "accent",
              ("r", 7, 13, 10, 7)],
    "saveas": [("p", [(4, 4), (17, 4), (20, 7), (20, 20), (4, 20)], True), ("r", 8, 4, 8, 5), "accent",
               ("l", 9, 17, 17, 9), ("l", 8, 18, 9, 17)],
    "recover": [("a", 12, 12, 7, 30, 300), ("l", 12, 8, 12, 12), ("l", 12, 12, 15, 14)],
    "exit": [("p", [(13, 4), (5, 4), (5, 20), (13, 20)], False), "accent", ("l", 10, 12, 21, 12),
             ("p", [(17, 8), (21, 12), (17, 16)], False)],
    "properties": [("r", 4, 3, 16, 18), ("l", 7, 8, 17, 8), ("l", 7, 12, 17, 12), ("l", 7, 16, 13, 16)],
    "dist": [("l", 3, 16, 21, 16), ("l", 3, 13, 3, 19), ("l", 21, 13, 21, 19), "accent", ("d", 3, 16),
             ("d", 21, 16), ("t", 12, 9, "↔")],
    "id": [("l", 4, 20, 4, 4), ("l", 4, 20, 20, 20), "accent", ("d", 14, 10), ("l", 14, 10, 14, 20),
           ("l", 4, 10, 14, 10)],
    "help": [("c", 12, 12, 9), ("t", 12, 13, "?")],
}



ICONS.update({
    "rectang": [("r", 4, 6, 16, 12), "accent", ("d", 4, 18), ("d", 20, 6)],
    "polygon": [("p", [(12, 3), (20, 8), (20, 16), (12, 21), (4, 16), (4, 8)], True), "accent", ("d", 12, 12)],
    "ellipse": [("p", [(3, 12), (5, 8), (9, 6), (15, 6), (19, 8), (21, 12), (19, 16), (15, 18), (9, 18), (5, 16)], True),
                "accent", ("d", 12, 12)],
    "spline": [("p", [(3, 18), (6, 10), (10, 7), (13, 12), (16, 17), (20, 12), (21, 6)], False), "accent",
               ("d", 3, 18), ("d", 13, 12), ("d", 21, 6)],
    "text": [("t", 12, 12, "A"), "accent", ("l", 6, 20, 18, 20)],
    "mtext": [("t", 8, 8, "A"), ("l", 13, 6, 21, 6), ("l", 4, 13, 21, 13), ("l", 4, 18, 17, 18)],
    "hatch": [("r", 4, 4, 16, 16), "accent", ("l", 4, 12, 12, 4), ("l", 4, 20, 20, 4), ("l", 12, 20, 20, 12)],
    "boundary": [("p", [(4, 6), (12, 4), (20, 8), (18, 18), (8, 20)], True), "accent", ("d", 12, 12)],
    "move": [("l", 12, 3, 12, 21), ("l", 3, 12, 21, 12), "accent", ("p", [(9, 6), (12, 3), (15, 6)], False),
             ("p", [(18, 9), (21, 12), (18, 15)], False)],
    "copy": [("r", 3, 3, 12, 12), "accent", ("r", 9, 9, 12, 12)],
    "rotate": [("a", 12, 12, 8, 30, 260), "accent", ("p", [(17, 3), (19.5, 7.5), (15, 8)], False), ("d", 12, 12)],
    "scale": [("r", 3, 10, 11, 11), "accent", ("r", 3, 3, 18, 18), ("l", 14, 10, 21, 3)],
    "mirror": [("p", [(3, 18), (9, 6), (9, 18)], True), "accent", ("p", [(21, 18), (15, 6), (15, 18)], True),
               ("l", 12, 3, 12, 21)],
    "offset": [("a", 14, 16, 8, 90, 90), "accent", ("a", 14, 16, 12, 90, 90)],
    "trim": [("l", 12, 3, 12, 21), ("l", 3, 12, 12, 12), "accent", ("l", 13, 12, 21, 12)],
    "extend": [("l", 20, 3, 20, 21), ("l", 3, 12, 11, 12), "accent", ("l", 12, 12, 19, 12),
               ("p", [(16, 9), (19, 12), (16, 15)], False)],
    "fillet": [("l", 4, 20, 4, 11), ("l", 13, 4, 20, 4), "accent", ("a", 13, 11, 9, 90, 90)],
    "chamfer": [("l", 4, 20, 4, 11), ("l", 11, 4, 20, 4), "accent", ("l", 4, 11, 11, 4)],
    "arrayrect": [("r", 3, 3, 5, 5), ("r", 10, 3, 5, 5), ("r", 17, 3, 4, 5), "accent", ("r", 3, 10, 5, 5),
                  ("r", 10, 10, 5, 5), ("r", 17, 10, 4, 5), ("r", 3, 17, 5, 4), ("r", 10, 17, 5, 4)],
    "arraypolar": [("c", 12, 12, 8), "accent", ("d", 12, 4), ("d", 19, 8), ("d", 19, 16), ("d", 12, 20), ("d", 5, 16),
                   ("d", 5, 8)],
    "break": [("l", 3, 12, 9, 12), ("l", 15, 12, 21, 12), "accent", ("d", 9, 12), ("d", 15, 12)],
    "breakatpoint": [("l", 3, 12, 21, 12), "accent", ("l", 12, 7, 12, 17)],
    "join": [("l", 3, 12, 11, 12), ("l", 13, 12, 21, 12), "accent", ("p", [(9, 8), (12, 12), (9, 16)], False),
             ("p", [(15, 8), (12, 12), (15, 16)], False)],
    "explode": [("l", 12, 2, 12, 7), ("l", 12, 17, 12, 22), ("l", 2, 12, 7, 12), ("l", 17, 12, 22, 12),
                "accent", ("l", 5, 5, 8, 8), ("l", 19, 19, 16, 16), ("l", 19, 5, 16, 8), ("l", 5, 19, 8, 16)],
    "stretch": [("p", [(3, 18), (8, 6), (21, 6)], False), "accent", ("r", 14, 3, 8, 6)],
    "dimlinear": [("l", 4, 18, 4, 8), ("l", 20, 18, 20, 8), "accent", ("l", 4, 11, 20, 11), ("t", 12, 6, "↔")],
    "dimaligned": [("l", 4, 20, 20, 4), "accent", ("l", 2, 14, 14, 2), ("t", 13, 13, "↗")],
    "dimangular": [("l", 4, 20, 20, 20), ("l", 4, 20, 16, 6), "accent", ("a", 4, 20, 11, 0, 50)],
    "dimradius": [("c", 12, 12, 8), "accent", ("l", 12, 12, 18, 6), ("t", 7, 16, "R")],
    "dimdiameter": [("c", 12, 12, 8), "accent", ("l", 6, 18, 18, 6), ("t", 7, 8, "Ø")],
    "dimordinate": [("l", 4, 20, 20, 20), ("l", 4, 20, 4, 4), "accent", ("l", 10, 20, 10, 8), ("l", 16, 20, 16, 12)],
    "leader": [("l", 4, 18, 12, 8), ("l", 12, 8, 20, 8), "accent", ("p", [(4, 18), (5, 13), (8, 16)], True)],
    "dimstyle": [("l", 4, 14, 20, 14), ("l", 4, 10, 4, 18), ("l", 20, 10, 20, 18), "accent", ("t", 12, 7, "Aa")],
    "block": [("r", 4, 4, 16, 16), "accent", ("c", 12, 12, 4)],
    "insert": [("r", 6, 6, 14, 14), "accent", ("l", 2, 2, 10, 10), ("p", [(6, 10), (10, 10), (10, 6)], False)],
    "attdef": [("r", 3, 7, 18, 10), "accent", ("t", 12, 12, "ab")],
    "group": [("r", 3, 3, 8, 8), ("c", 16, 16, 4), "accent", ("r", 2, 2, 20, 20)],
    "ungroup": [("r", 3, 3, 8, 8), ("c", 16, 16, 4)],
    "mview": [("r", 2, 4, 20, 16), "accent", ("r", 5, 7, 10, 8)],
    "layout": [("r", 4, 3, 16, 18), "accent", ("r", 12, 15, 7, 5)],
    "pagesetup": [("r", 5, 3, 14, 18), "accent", ("l", 8, 8, 16, 8), ("l", 8, 12, 16, 12)],
    "parameters": [("t", 12, 12, "fx")],
    "delconstraint": [("t", 12, 12, "∥"), "accent", ("l", 4, 4, 20, 20)],
    "constraintbar": [("r", 3, 8, 18, 8), "accent", ("t", 12, 12, "∥⊥")],
    "constraintstatus": [("c", 12, 12, 8), "accent", ("t", 12, 12, "?")],
    "dclinear": [("l", 4, 18, 4, 8), ("l", 20, 18, 20, 8), "accent", ("l", 4, 11, 20, 11), ("t", 12, 6, "d")],
    "dcaligned": [("l", 4, 20, 20, 4), "accent", ("t", 14, 12, "d")],
    "dcradius": [("c", 12, 12, 8), "accent", ("l", 12, 12, 18, 6), ("t", 8, 16, "r")],
    "dcdiameter": [("c", 12, 12, 8), "accent", ("t", 12, 12, "Ø")],
    "dcangular": [("l", 4, 20, 20, 20), ("l", 4, 20, 16, 6), "accent", ("t", 14, 15, "∠")],
})
for _name, _glyph in (("gccoincident", "•"), ("gccollinear", "⫽"), ("gcconcentric", "◎"), ("gcfix", "⚓"),
                      ("gcparallel", "∥"), ("gcperpendicular", "⊥"), ("gchorizontal", "—"), ("gcvertical", "|"),
                      ("gctangent", "T"), ("gcsymmetric", "[ ]"), ("gcequal", "=")):
    ICONS[_name] = [("r", 3, 3, 18, 18), "accent", ("t", 12, 12, _glyph)]


def render_icon(name: str, fg: QColor, accent: QColor, size: int = 48) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    shapes = ICONS.get(name)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    k = size / 24.0
    color = fg
    if shapes is None:
        # unknown icon: a rounded square with the first letter
        p.setPen(QPen(fg, 1.6 * k))
        p.drawRoundedRect(QRectF(3 * k, 3 * k, 18 * k, 18 * k), 3 * k, 3 * k)
        f = QFont()
        f.setPixelSize(int(11 * k))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, name[:1].upper())
        p.end()
        return pm
    for sh in shapes:
        if sh == "accent":
            color = accent
            continue
        pen = QPen(color, 1.7 * k)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        kind = sh[0]
        if kind == "l":
            p.drawLine(QPointF(sh[1] * k, sh[2] * k), QPointF(sh[3] * k, sh[4] * k))
        elif kind == "c":
            p.drawEllipse(QPointF(sh[1] * k, sh[2] * k), sh[3] * k, sh[3] * k)
        elif kind == "a":
            r = sh[3]
            p.drawArc(QRectF((sh[1] - r) * k, (sh[2] - r) * k, 2 * r * k, 2 * r * k), int(sh[4] * 16), int(sh[5] * 16))
        elif kind == "r":
            p.drawRect(QRectF(sh[1] * k, sh[2] * k, sh[3] * k, sh[4] * k))
        elif kind == "p":
            path = QPainterPath()
            pts = sh[1]
            path.moveTo(pts[0][0] * k, pts[0][1] * k)
            for x, y in pts[1:]:
                path.lineTo(x * k, y * k)
            if sh[2]:
                path.closeSubpath()
            p.drawPath(path)
        elif kind == "d":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(sh[1] * k, sh[2] * k), 2.1 * k, 2.1 * k)
        elif kind == "t":
            f = QFont()
            f.setPixelSize(int(10 * k))
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF((sh[1] - 8) * k, (sh[2] - 7) * k, 16 * k, 14 * k), Qt.AlignmentFlag.AlignCenter, sh[3])
    p.end()
    return pm


class IconProvider:
    def __init__(self, dark: bool) -> None:
        self.set_dark(dark)

    def set_dark(self, dark: bool) -> None:
        self.fg = QColor(225, 230, 236) if dark else QColor(45, 52, 62)
        self.accent = QColor(80, 170, 255) if dark else QColor(0, 110, 210)
        self._cache: dict[str, QIcon] = {}

    def icon(self, name: str) -> QIcon:
        if name not in self._cache:
            ic = QIcon()
            for s in (24, 32, 48, 64):
                ic.addPixmap(render_icon(name, self.fg, self.accent, s))
            self._cache[name] = ic
        return self._cache[name]
