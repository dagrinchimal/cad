"""Properties panel: shows and edits the selection (or the defaults for new objects)."""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from ..core.geom2d.vec import dist
from ..core.model import (
    Arc, BlockReference, Circle, Dimension, Document, Ellipse, Entity, Hatch, Leader, Line, MText, Point, Polyline,
    Spline, Text, Viewport,
)
from ..core.model.hatch_patterns import PATTERN_NAMES
from ..core.units import format_angle, format_length, parse_angle, UnitParseError
from .widgets import ColorCombo, LengthEdit, LinetypeCombo, LineweightCombo

MIXED = None


class PropertiesPanel(QWidget):
    def __init__(self, get_doc: Callable[[], Document], get_selection: Callable[[], set[int]], dark: bool = True,
                 parent=None) -> None:
        super().__init__(parent)
        self.get_doc = get_doc
        self.get_selection = get_selection
        self.dark = dark
        self.header = QLabel()
        self.header.setWordWrap(True)
        self.header.setStyleSheet("font-weight: bold; padding: 4px 0;")

        doc = get_doc()
        self.layer = QComboBox()
        self.color = ColorCombo(dark=dark)
        self.linetype = LinetypeCombo(doc)
        self.lineweight = LineweightCombo()
        self.layer.activated.connect(lambda i: self._set_common(layer=self.layer.itemText(i)))
        self.color.color_chosen.connect(lambda c: self._set_common(color=c))
        self.linetype.linetype_chosen.connect(lambda n: self._set_common(linetype=n))
        self.lineweight.lineweight_chosen.connect(lambda w: self._set_common(lineweight=w))

        self.common = QFormLayout()
        self.common.addRow("Layer", self.layer)
        self.common.addRow("Color", self.color)
        self.common.addRow("Linetype", self.linetype)
        self.common.addRow("Lineweight", self.lineweight)

        self.geo_box = QWidget()
        self.geo = QFormLayout(self.geo_box)
        self.geo.setContentsMargins(0, 8, 0, 0)

        inner = QWidget()
        v = QVBoxLayout(inner)
        v.addWidget(self.header)
        v.addLayout(self.common)
        v.addWidget(self.geo_box)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.refresh()

    # ------------------------------------------------------------------ refresh
    def set_dark(self, dark: bool) -> None:
        self.dark = dark
        self.color.dark = dark
        self.color._fill()
        self.refresh()

    def refresh(self) -> None:
        doc = self.get_doc()
        sel = [doc.entities[h] for h in self.get_selection() if h in doc.entities]
        self.layer.blockSignals(True)
        self.layer.clear()
        self.layer.addItems(list(doc.layers))
        self.layer.blockSignals(False)
        self.linetype.set_document(doc)
        while self.geo.rowCount():
            self.geo.removeRow(0)
        if not sel:
            h = doc.header
            self.header.setText("Nothing selected — settings for new objects")
            self.layer.setCurrentText(h.current_layer)
            self.color.set_color(h.current_color)
            self.linetype.set_linetype(h.current_linetype)
            self.lineweight.set_lineweight(h.current_lineweight)
            return

        def same(attr):
            vals = {getattr(e, attr) for e in sel}
            return vals.pop() if len(vals) == 1 else MIXED

        kinds = sorted({type(e).__name__ for e in sel})
        self.header.setText(f"{len(sel)} selected: {', '.join(kinds)}" if len(sel) > 1 else kinds[0])
        lay = same("layer")
        self.layer.setCurrentIndex(self.layer.findText(lay) if lay is not MIXED else -1)
        self.color.set_color(same("color"))
        self.linetype.set_linetype(same("linetype"))
        self.lineweight.set_lineweight(same("lineweight"))
        if len(sel) == 1:
            self._geometry_rows(sel[0])
        else:
            total = sum(e.length() for e in sel)
            self._ro("Total length", format_length(total, doc.header.units))

    # ------------------------------------------------------------------ geometry rows
    def _ro(self, label: str, text: str) -> None:
        w = QLineEdit(text)
        w.setReadOnly(True)
        w.setStyleSheet("color: gray;")
        self.geo.addRow(label, w)

    def _len(self, label: str, value: float, apply: Callable[[float], Entity | None], positive=False) -> None:
        units = self.get_doc().header.units
        w = LengthEdit(units, positive=positive)
        w.set_value(value)
        w.value_entered.connect(lambda v: self._replace(apply(v)))
        self.geo.addRow(label, w)

    def _ang(self, label: str, radians: float, apply: Callable[[float], Entity | None]) -> None:
        units = self.get_doc().header.units
        w = QLineEdit(format_angle(math.degrees(radians), units))

        def done():
            if not w.isModified():
                return
            w.setModified(False)
            try:
                deg = parse_angle(w.text().replace("°", ""))
            except UnitParseError:
                w.setStyleSheet("border: 1px solid #d33;")
                return
            self._replace(apply(math.radians(deg)))
        w.editingFinished.connect(done)
        self.geo.addRow(label, w)

    def _geometry_rows(self, e: Entity) -> None:
        u = self.get_doc().header.units
        if isinstance(e, Line):
            self._len("Start X", e.p1[0], lambda v: replace(e, p1=(v, e.p1[1])))
            self._len("Start Y", e.p1[1], lambda v: replace(e, p1=(e.p1[0], v)))
            self._len("End X", e.p2[0], lambda v: replace(e, p2=(v, e.p2[1])))
            self._len("End Y", e.p2[1], lambda v: replace(e, p2=(e.p2[0], v)))

            def set_length(v):
                cur = dist(e.p1, e.p2)
                if cur <= 0:
                    return None
                k = v / cur
                return replace(e, p2=(e.p1[0] + (e.p2[0] - e.p1[0]) * k, e.p1[1] + (e.p2[1] - e.p1[1]) * k))
            self._len("Length", dist(e.p1, e.p2), set_length, positive=True)
            self._ro("Angle", format_angle(math.degrees(math.atan2(e.p2[1] - e.p1[1], e.p2[0] - e.p1[0])) % 360, u))
        elif isinstance(e, Circle):
            self._len("Center X", e.center[0], lambda v: replace(e, center=(v, e.center[1])))
            self._len("Center Y", e.center[1], lambda v: replace(e, center=(e.center[0], v)))
            self._len("Radius", e.radius, lambda v: replace(e, radius=v), positive=True)
            self._len("Diameter", e.diameter, lambda v: replace(e, radius=v / 2), positive=True)
            self._ro("Circumference", format_length(2 * math.pi * e.radius, u))
            self._ro("Area", f"{format_length(math.sqrt(e.area), u)} squared")
        elif isinstance(e, Arc):
            self._len("Center X", e.center[0], lambda v: replace(e, center=(v, e.center[1])))
            self._len("Center Y", e.center[1], lambda v: replace(e, center=(e.center[0], v)))
            self._len("Radius", e.radius, lambda v: replace(e, radius=v), positive=True)
            self._ang("Start angle", e.start_angle, lambda a: replace(e, start_angle=a % math.tau))
            self._ang("End angle", e.end_angle, lambda a: replace(e, end_angle=a % math.tau))
            self._ro("Arc length", format_length(e.length(), u))
        elif isinstance(e, Point):
            self._len("X", e.position[0], lambda v: replace(e, position=(v, e.position[1])))
            self._len("Y", e.position[1], lambda v: replace(e, position=(e.position[0], v)))
        elif isinstance(e, Ellipse):
            self._len("Center X", e.center[0], lambda v: replace(e, center=(v, e.center[1])))
            self._len("Center Y", e.center[1], lambda v: replace(e, center=(e.center[0], v)))
            ml = e.major_length

            def set_major(v):
                k = v / ml if ml else 1
                return replace(e, major=(e.major[0] * k, e.major[1] * k), ratio=min(1.0, e.ratio / k))
            self._len("Major radius", ml, set_major, positive=True)
            self._len("Minor radius", ml * e.ratio, lambda v: replace(e, ratio=min(1.0, v / ml)) if ml else None,
                      positive=True)
            if e.is_full:
                self._ro("Area", f"{format_length(math.sqrt(e.area()), u)} squared")
        elif isinstance(e, Spline):
            self._ro("Fit points", str(len(e.fit_points)))
            self._ro("Closed", "Yes" if e.closed else "No")
            self._ro("Length", format_length(e.length(), u))
        elif isinstance(e, (Text, MText)):
            self._text("Text", e.text, lambda t: replace(e, text=t), multiline=isinstance(e, MText))
            self._len("Height", e.height, lambda v: replace(e, height=v), positive=True)
            self._ang("Rotation", e.rotation, lambda a: replace(e, rotation=a))
            self._len("X", e.insert[0], lambda v: replace(e, insert=(v, e.insert[1])))
            self._len("Y", e.insert[1], lambda v: replace(e, insert=(e.insert[0], v)))
            if isinstance(e, MText):
                self._len("Box width (0 = none)", e.width, lambda v: replace(e, width=max(0.0, v)))
            self._choice("Justify", ["left", "center", "right"], e.halign, lambda v: replace(e, halign=v))
        elif isinstance(e, Hatch):
            self._choice("Pattern", list(PATTERN_NAMES), e.pattern, lambda v: replace(e, pattern=v))
            self._num("Pattern scale", e.pattern_scale, lambda v: replace(e, pattern_scale=v) if v > 0 else None)
            self._ang("Pattern angle", e.pattern_angle, lambda a: replace(e, pattern_angle=a))
            self._ro("Area", f"{format_length(math.sqrt(e.area()), u)} squared")
        elif isinstance(e, Dimension):
            val = e.measurement()
            self._ro("Measurement", f"{math.degrees(val):.4g}°" if e.dimtype == "angular" else format_length(val, u))
            self._text("Text override", e.text, lambda t: replace(e, text=t))
            self._ro("Hint", "Leave empty for the measured value; <> stands for it, e.g. <> TYP")
            styles = list(self.get_doc().dimstyles)
            self._choice("Style", styles, e.style, lambda v: replace(e, style=v))
        elif isinstance(e, Leader):
            self._text("Note", e.text, lambda t: replace(e, text=t), multiline=True)
        elif isinstance(e, BlockReference):
            self._ro("Block", e.name)
            self._len("X", e.insert[0], lambda v: replace(e, insert=(v, e.insert[1])))
            self._len("Y", e.insert[1], lambda v: replace(e, insert=(e.insert[0], v)))
            self._num("Scale", e.sx, lambda v: replace(e, sx=v, sy=v * (1 if e.sy >= 0 else -1)) if v > 0 else None)
            self._ang("Rotation", e.rotation, lambda a: replace(e, rotation=a))
            bdef = self.get_doc().blocks.get(e.name)
            for ad in (bdef.attdefs() if bdef else []):
                self._text(ad.prompt or ad.tag, e.attrib(ad.tag, ad.default),
                           lambda t, tag=ad.tag: e.with_attrib(tag, t))
        elif isinstance(e, Viewport):
            self._viewport_rows(e)
        elif isinstance(e, Polyline):
            self._ro("Vertices", str(len(e.vertices)))
            self._ro("Closed", "Yes" if e.closed else "No")
            self._ro("Length", format_length(e.length(), u))
            if e.closed:
                self._ro("Area", f"{format_length(math.sqrt(abs(e.area())), u)} squared")

    def _text(self, label: str, text: str, apply, multiline: bool = False) -> None:
        w = QLineEdit(text.replace("\n", " ⏎ ") if multiline else text)
        if multiline:
            w.setToolTip("Double-click the text in the drawing to edit it with line breaks")

        def done():
            if not w.isModified():
                return
            w.setModified(False)
            t = w.text().replace(" ⏎ ", "\n") if multiline else w.text()
            self._replace(apply(t))
        w.editingFinished.connect(done)
        self.geo.addRow(label, w)

    def _num(self, label: str, value: float, apply) -> None:
        w = QLineEdit(f"{value:g}")

        def done():
            if not w.isModified():
                return
            w.setModified(False)
            try:
                v = float(w.text())
            except ValueError:
                w.setStyleSheet("border: 1px solid #d33;")
                return
            self._replace(apply(v))
        w.editingFinished.connect(done)
        self.geo.addRow(label, w)

    def _choice(self, label: str, options: list[str], current: str, apply) -> None:
        cb = QComboBox()
        cb.addItems(options)
        if current not in options:
            cb.addItem(current)
        cb.setCurrentText(current)
        cb.activated.connect(lambda i: self._replace(apply(cb.itemText(i))))
        self.geo.addRow(label, cb)

    def _viewport_rows(self, e: Viewport) -> None:
        from ..core.units import standard_scales
        u = self.get_doc().header.units
        cb = QComboBox()
        cb.addItem("Scale to fit", None)
        for sc in standard_scales(u.mode):
            cb.addItem(sc.name, sc.factor)
        if e.fit:
            cb.setCurrentIndex(0)
        else:
            idx = next((i for i in range(1, cb.count()) if abs(cb.itemData(i) - e.scale) < 1e-12), -1)
            if idx < 0:
                cb.addItem(f"Custom (1:{1 / e.scale:.4g})", e.scale)
                idx = cb.count() - 1
            cb.setCurrentIndex(idx)

        def chosen(i):
            f = cb.itemData(i)
            if f is None:
                self._replace(replace(e, fit=True))
                return
            # keep showing the same middle of the model when switching from "fit"
            from ..core.layouts import resolve_viewport
            idx_ = getattr(self.window(), "index", None)
            box = idx_.extents("*Model") if idx_ else None
            center, _ = resolve_viewport(self.get_doc(), e, box)
            self._replace(replace(e, fit=False, scale=f, view_center=center))
        cb.activated.connect(chosen)
        self.geo.addRow("Scale", cb)
        self._len("Model center X", e.view_center[0], lambda v: replace(e, fit=False, view_center=(v, e.view_center[1])))
        self._len("Model center Y", e.view_center[1], lambda v: replace(e, fit=False, view_center=(e.view_center[0], v)))
        self._ro("Paper size", f"{e.width:.0f} x {e.height:.0f} mm")

    # ------------------------------------------------------------------ edits
    def _replace(self, new: Entity | None) -> None:
        if new is None:
            return
        doc = self.get_doc()
        if doc.in_transaction:
            return
        with doc.transaction("Properties"):
            doc.replace(new)

    def _set_common(self, **changes) -> None:
        doc = self.get_doc()
        if doc.in_transaction:
            return
        sel = [doc.entities[h] for h in self.get_selection() if h in doc.entities]
        if not sel:
            key_map = {"layer": "current_layer", "color": "current_color", "linetype": "current_linetype",
                       "lineweight": "current_lineweight"}
            hdr = replace(doc.header, **{key_map[k]: v for k, v in changes.items()})
            with doc.transaction("Current properties"):
                if "layer" in changes:
                    doc.set_current_layer(changes["layer"])
                    hdr = replace(hdr, current_layer=changes["layer"])
                doc.set_header(hdr)
            return
        with doc.transaction("Properties"):
            for e in sel:
                if "layer" in changes and doc.is_locked(e):
                    continue
                doc.replace(e.with_props(**changes))


_ = Qt
