"""Small reusable widgets: color / linetype / lineweight / layer pickers, length fields."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QColorDialog, QComboBox, QLineEdit

from ..core.model import (
    BYBLOCK, BYLAYER, LW_BYBLOCK, LW_BYLAYER, LW_DEFAULT, STANDARD_LINEWEIGHTS, Document, color_label,
    color_to_rgb, lineweight_label,
)
from ..core.units import UnitParseError, UnitSettings, format_length, parse_length

BASIC_COLORS = [1, 2, 3, 4, 5, 6, 7, 8, 9]


def swatch(color, dark: bool = True, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    from PySide6.QtGui import QPainter
    p = QPainter(pm)
    r, g, b = color_to_rgb(color, dark)
    p.fillRect(1, 1, size - 2, size - 2, QColor(r, g, b))
    p.setPen(QColor(128, 128, 128))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pm)


class ColorCombo(QComboBox):
    color_chosen = Signal(object)

    def __init__(self, allow_by: bool = True, dark: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.dark = dark
        self.allow_by = allow_by
        self._fill()
        self.activated.connect(self._on_activated)

    def _fill(self, extra=None) -> None:
        self.blockSignals(True)
        self.clear()
        if self.allow_by:
            self.addItem("ByLayer", BYLAYER)
            self.addItem("ByBlock", BYBLOCK)
        for c in BASIC_COLORS:
            self.addItem(swatch(c, self.dark), color_label(c), c)
        if extra is not None and self.findData(extra) < 0:
            self.addItem(swatch(extra, self.dark), color_label(extra), extra)
        self.addItem("Choose color…", "__more__")
        self.blockSignals(False)

    def set_color(self, color) -> None:
        if color is None:
            self.setCurrentIndex(-1)
            return
        if self.findData(color) < 0:
            self._fill(extra=color)
        self.blockSignals(True)
        self.setCurrentIndex(self.findData(color))
        self.blockSignals(False)

    def _on_activated(self, idx: int) -> None:
        data = self.itemData(idx)
        if data == "__more__":
            c = QColorDialog.getColor(parent=self, title="Choose a color")
            if not c.isValid():
                return
            data = c.name()
            self.set_color(data)
        self.color_chosen.emit(data)


class LinetypeCombo(QComboBox):
    linetype_chosen = Signal(str)

    def __init__(self, doc: Document, allow_by: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.allow_by = allow_by
        self.set_document(doc)
        self.activated.connect(lambda i: self.linetype_chosen.emit(self.itemData(i)))

    def set_document(self, doc: Document) -> None:
        self.blockSignals(True)
        self.clear()
        if self.allow_by:
            self.addItem("ByLayer", "ByLayer")
            self.addItem("ByBlock", "ByBlock")
        for lt in doc.linetypes.values():
            self.addItem(f"{lt.name}   {lt.description}", lt.name)
        self.blockSignals(False)

    def set_linetype(self, name: str | None) -> None:
        self.blockSignals(True)
        self.setCurrentIndex(self.findData(name) if name is not None else -1)
        self.blockSignals(False)


class LineweightCombo(QComboBox):
    lineweight_chosen = Signal(float)

    def __init__(self, allow_by: bool = True, parent=None) -> None:
        super().__init__(parent)
        if allow_by:
            self.addItem("ByLayer", LW_BYLAYER)
            self.addItem("ByBlock", LW_BYBLOCK)
        self.addItem("Default", LW_DEFAULT)
        for lw in STANDARD_LINEWEIGHTS:
            self.addItem(lineweight_label(lw), lw)
        self.activated.connect(lambda i: self.lineweight_chosen.emit(float(self.itemData(i))))

    def set_lineweight(self, lw: float | None) -> None:
        self.blockSignals(True)
        if lw is None:
            self.setCurrentIndex(-1)
        else:
            best = min(range(self.count()), key=lambda i: abs(float(self.itemData(i)) - lw))
            self.setCurrentIndex(best)
        self.blockSignals(False)


class LengthEdit(QLineEdit):
    """Shows a length in the drawing's units; accepts any unit format when typing."""
    value_entered = Signal(float)

    def __init__(self, units: UnitSettings, parent=None, positive: bool = False) -> None:
        super().__init__(parent)
        self.units = units
        self.positive = positive
        self._value: float | None = None
        self.editingFinished.connect(self._commit)
        self.setToolTip("Type a value in any unit: 25.4mm, 1in, 1 1/2\", 3'-4 1/2\"…")

    def set_value(self, v: float | None, units: UnitSettings | None = None) -> None:
        if units is not None:
            self.units = units
        self._value = v
        self.setText("" if v is None else format_length(v, self.units))
        self.setStyleSheet("")

    def _commit(self) -> None:
        if not self.isModified():
            return
        self.setModified(False)
        try:
            v = parse_length(self.text(), self.units)
            if self.positive and v <= 0:
                raise UnitParseError("Must be greater than zero")
        except UnitParseError as exc:
            self.setStyleSheet("border: 1px solid #d33;")
            self.setToolTip(str(exc))
            return
        self.setStyleSheet("")
        self._value = v
        self.setText(format_length(v, self.units))
        self.value_entered.emit(v)
