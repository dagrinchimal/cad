"""The Shapes panel: ready-made solids and hole shapes. Drag one into the 3D view, or click it and then
click where it goes (Tinkercad-style)."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QGridLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from .view3d import SHAPE_MIME

SHAPES = ("Box", "Cylinder", "Sphere", "Cone", "Torus", "Wedge")


class ShapeButton(QToolButton):
    def __init__(self, kind: str, hole: bool, icon, parent=None) -> None:
        super().__init__(parent)
        self.kind, self.hole = kind, hole
        self.setText(f"{kind}\nhole" if hole else kind)
        if icon is not None:
            self.setIcon(icon)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setAutoRaise(True)
        self.setMinimumWidth(64)
        self.setToolTip(f"Drag into the 3D view, or click and then click where it goes.<br>"
                        f"{'A hole shape cuts the solids you Combine it with.' if hole else ''}")
        self._press: QPoint | None = None

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._press = ev.position().toPoint()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        if self._press is not None and (ev.position().toPoint() - self._press).manhattanLength() > 8:
            self._press = None
            self.setDown(False)
            md = QMimeData()
            md.setData(SHAPE_MIME, f"{self.kind}|{'hole' if self.hole else 'solid'}".encode())
            drag = QDrag(self)
            drag.setMimeData(md)
            drag.setPixmap(self.icon().pixmap(32, 32))
            drag.exec(Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        self._press = None
        super().mouseReleaseEvent(ev)


class ShapesPanel(QWidget):
    shape_clicked = Signal(str, bool)       # kind, hole

    def __init__(self, icon_for=None, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        tip = QLabel("Drag a shape into the 3D view, or click it and then click where it goes. "
                     "Grey hole shapes cut: select both and click <b>Combine</b>.")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self.buttons: list[ShapeButton] = []
        for hole in (False, True):
            v.addWidget(QLabel("<b>Hole shapes</b>" if hole else "<b>Solids</b>"))
            grid = QGridLayout()
            grid.setSpacing(2)
            for i, kind in enumerate(SHAPES):
                b = ShapeButton(kind, hole, icon_for(kind.lower()) if icon_for else None, self)
                b.clicked.connect(lambda _=False, k=kind, h=hole: self.shape_clicked.emit(k, h))
                grid.addWidget(b, i // 3, i % 3)
                self.buttons.append(b)
            v.addLayout(grid)
        v.addStretch(1)
