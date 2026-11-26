"""Dialogs: Layer Properties, Units, Drafting Settings, Options, Recovery."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..core.model import Document, DocumentError, Layer
from ..core.snaps import Osnap, SnapSettings
from ..core.units import (
    UnitMode, UnitSettings, format_angle, format_length,
)
from ..core.units.settings import FRACTION_DENOMINATORS
from .widgets import ColorCombo, LengthEdit, LinetypeCombo, LineweightCombo

# ====================================================================== layers


class LayerDialog(QDialog):
    COLS = ["", "Name", "On", "Freeze", "Lock", "Color", "Linetype", "Lineweight", "Description"]

    def __init__(self, doc: Document, dark: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Layer Properties")
        self.resize(900, 420)
        self.doc = doc
        self.dark = dark
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setStretchLastSection(True)
        self.table.itemChanged.connect(self._item_changed)

        new_btn = QPushButton("New layer")
        del_btn = QPushButton("Delete layer")
        cur_btn = QPushButton("Set current")
        new_btn.setToolTip("Add a layer")
        del_btn.setToolTip("Delete the selected layer (it must be empty and not current)")
        cur_btn.setToolTip("New objects will be drawn on the selected layer")
        new_btn.clicked.connect(self._new)
        del_btn.clicked.connect(self._delete)
        cur_btn.clicked.connect(self._set_current)
        self.table.cellDoubleClicked.connect(lambda r, c: self._set_current() if c == 0 else None)
        top = QHBoxLayout()
        for b in (new_btn, del_btn, cur_btn):
            top.addWidget(b)
        top.addStretch(1)
        top.addWidget(QLabel("Tip: double-click the ✓ column to make a layer current."))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table)
        lay.addWidget(close)
        self._listener = lambda d, cs: self.reload() if (cs.layers or cs.header or cs.reset) else None
        doc.add_listener(self._listener)
        self.reload()

    def done(self, r: int) -> None:
        self.doc.remove_listener(self._listener)
        super().done(r)

    def _guard(self, name: str, fn) -> None:
        try:
            with self.doc.transaction(name):
                fn()
        except DocumentError as exc:
            QMessageBox.warning(self, "Layer", str(exc))
            self.reload()

    def reload(self) -> None:
        self._loading = True
        self.table.blockSignals(True)
        sel_name = self.selected_name()
        self.table.setRowCount(0)
        for name, layer in self.doc.layers.items():
            r = self.table.rowCount()
            self.table.insertRow(r)
            cur = QTableWidgetItem("✓" if name == self.doc.header.current_layer else "")
            cur.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            cur.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 0, cur)
            item = QTableWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            if name == "0":
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 1, item)
            for col, attr in ((2, "on"), (3, "frozen"), (4, "locked")):
                cb = QCheckBox()
                cb.setChecked(getattr(layer, attr))
                cb.toggled.connect(lambda v, n=name, a=attr: self._update(n, **{a: v}))
                w = QWidget()
                hl = QHBoxLayout(w)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                hl.addWidget(cb)
                self.table.setCellWidget(r, col, w)
            cc = ColorCombo(allow_by=False, dark=self.dark)
            cc.set_color(layer.color)
            cc.color_chosen.connect(lambda c, n=name: self._update(n, color=c))
            self.table.setCellWidget(r, 5, cc)
            lt = LinetypeCombo(self.doc, allow_by=False)
            lt.set_linetype(layer.linetype)
            lt.linetype_chosen.connect(lambda v, n=name: self._update(n, linetype=v))
            self.table.setCellWidget(r, 6, lt)
            lw = LineweightCombo(allow_by=False)
            lw.set_lineweight(layer.lineweight)
            lw.lineweight_chosen.connect(lambda v, n=name: self._update(n, lineweight=v))
            self.table.setCellWidget(r, 7, lw)
            self.table.setItem(r, 8, QTableWidgetItem(layer.description))
            if name == sel_name:
                self.table.selectRow(r)
        self.table.blockSignals(False)
        self._loading = False

    def selected_name(self) -> str | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 1)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update(self, name: str, **changes) -> None:
        layer = self.doc.layers.get(name)
        if layer is None:
            return
        self._guard("Layer change", lambda: self.doc.update_layer(replace(layer, **changes)))

    def _item_changed(self, item: QTableWidgetItem) -> None:
        r = item.row()
        old = self.table.item(r, 1).data(Qt.ItemDataRole.UserRole)
        if item.column() == 1:
            new = item.text().strip()
            if new and new != old:
                self._guard("Rename layer", lambda: self.doc.rename_layer(old, new))
            else:
                self.reload()
        elif item.column() == 8:
            self._update(old, description=item.text())

    def _new(self) -> None:
        i = 1
        while self.doc.find_layer(f"Layer{i}") is not None:
            i += 1
        name = f"Layer{i}"
        self._guard("New layer", lambda: self.doc.add_layer(Layer(name)))
        for r in range(self.table.rowCount()):
            if self.table.item(r, 1).text() == name:
                self.table.selectRow(r)
                self.table.editItem(self.table.item(r, 1))

    def _delete(self) -> None:
        name = self.selected_name()
        if name:
            self._guard("Delete layer", lambda: self.doc.delete_layer(name))

    def _set_current(self) -> None:
        name = self.selected_name()
        if name:
            self._guard("Current layer", lambda: self.doc.set_current_layer(name))


# ====================================================================== units


class UnitsDialog(QDialog):
    SAMPLE = 3 * 304.8 + 4.5 * 25.4      # 3'-4 1/2"

    def __init__(self, units: UnitSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Drawing Units")
        self.group = QButtonGroup(self)
        box = QGroupBox("Show lengths as")
        v = QVBoxLayout(box)
        self.radios = {}
        examples = {UnitMode.MM: "e.g. 1028.70", UnitMode.FRACTIONAL: 'e.g. 40 1/2"',
                    UnitMode.ARCHITECTURAL: "e.g. 3'-4 1/2\""}
        for mode in UnitMode:
            rb = QRadioButton(f"{mode.label}   ({examples[mode]})")
            self.group.addButton(rb)
            self.radios[mode] = rb
            v.addWidget(rb)
            rb.toggled.connect(self._preview)
        self.radios[units.mode].setChecked(True)

        self.places = QSpinBox()
        self.places.setRange(0, 8)
        self.places.setValue(units.decimal_places)
        self.den = QComboBox()
        for d in FRACTION_DENOMINATORS:
            self.den.addItem(f"1/{d}\"", d)
        self.den.setCurrentIndex(FRACTION_DENOMINATORS.index(units.denominator))
        self.angle_places = QSpinBox()
        self.angle_places.setRange(0, 8)
        self.angle_places.setValue(units.angle_decimal_places)
        self.style_box = QComboBox()
        self.style_box.addItem('Revit style:  3 4-1/2 = 3\'-4 1/2",  0 1.5 = 1 1/2",  3 = 3 feet', "revit")
        self.style_box.addItem('AutoCAD style:  3 = 3 inches,  1 1/2 = 1 1/2"', "autocad")
        self.style_box.setCurrentIndex(0 if units.input_style == "revit" else 1)
        self.style_box.setToolTip("How plain numbers are read in feet-inches drawings. Numbers with ' or \" marks "
                                  "always mean what they say.")
        form = QFormLayout()
        form.addRow("Typing feet-inches", self.style_box)
        form.addRow("Millimeter decimal places", self.places)
        form.addRow("Inch precision (nearest)", self.den)
        form.addRow("Angle decimal places", self.angle_places)
        self.preview = QLabel()
        self.preview.setStyleSheet("font-size: 12pt; padding: 6px;")
        note = QLabel("Changing units only changes how numbers are shown and what a bare number like "
                      "<b>12</b> means when you type it. Your geometry keeps full precision. "
                      "You can always type any unit, like 25.4mm or 3'-4 1/2\".")
        note.setWordWrap(True)
        for w in (self.places, self.den, self.angle_places):
            (w.valueChanged if isinstance(w, QSpinBox) else w.currentIndexChanged).connect(self._preview)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addLayout(form)
        lay.addWidget(QLabel("Sample:"))
        lay.addWidget(self.preview)
        lay.addWidget(note)
        lay.addWidget(bb)
        self._preview()

    def result_units(self) -> UnitSettings:
        mode = next(m for m, rb in self.radios.items() if rb.isChecked())
        return UnitSettings(mode=mode, decimal_places=self.places.value(),
                            denominator=int(self.den.currentData()),
                            angle_decimal_places=self.angle_places.value(),
                            input_style=self.style_box.currentData())

    def _preview(self, *_):
        u = self.result_units()
        self.preview.setText(f"{format_length(self.SAMPLE, u)}   at   {format_angle(33.3333, u)}")


# ====================================================================== drafting settings


class DraftingDialog(QDialog):
    def __init__(self, cfg: SnapSettings, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Drafting Settings")
        self.doc = doc
        tabs = QTabWidget()
        units = doc.header.units

        # snap and grid
        sg = QWidget()
        f = QFormLayout(sg)
        self.grid_on = QCheckBox("Show grid (F7)")
        self.grid_on.setChecked(cfg.grid_on)
        self.snap_on = QCheckBox("Snap to grid (F9)")
        self.snap_on.setChecked(cfg.grid_snap_on)
        self.grid_sp = LengthEdit(units, positive=True)
        self.grid_sp.set_value(doc.header.grid_spacing)
        self.snap_sp = LengthEdit(units, positive=True)
        self.snap_sp.set_value(doc.header.snap_spacing)
        self.ortho = QCheckBox("Ortho: only horizontal and vertical (F8)")
        self.ortho.setChecked(cfg.ortho_on)
        f.addRow(self.grid_on)
        f.addRow("Grid spacing", self.grid_sp)
        f.addRow(self.snap_on)
        f.addRow("Snap spacing", self.snap_sp)
        f.addRow(self.ortho)
        tabs.addTab(sg, "Snap and Grid")

        # polar
        pol = QWidget()
        f2 = QFormLayout(pol)
        self.polar_on = QCheckBox("Polar tracking on (F10)")
        self.polar_on.setChecked(cfg.polar_on)
        self.inc = QComboBox()
        self.inc.setEditable(True)
        for a in ("90", "45", "30", "22.5", "18", "15", "10", "5"):
            self.inc.addItem(a)
        self.inc.setCurrentText(f"{cfg.polar_increment_deg:g}")
        f2.addRow(self.polar_on)
        f2.addRow("Increment angle (degrees)", self.inc)
        f2.addRow(QLabel("While drawing, the cursor locks onto these angles and shows a dotted guide."))
        tabs.addTab(pol, "Polar Tracking")

        # osnaps
        os_w = QWidget()
        g = QGridLayout(os_w)
        self.osnap_on = QCheckBox("Object snap on (F3)")
        self.osnap_on.setChecked(cfg.osnap_on)
        self.otrack_on = QCheckBox("Object snap tracking on (F11)")
        self.otrack_on.setChecked(cfg.otrack_on)
        g.addWidget(self.osnap_on, 0, 0)
        g.addWidget(self.otrack_on, 0, 1)
        self.mode_boxes: dict[Osnap, QCheckBox] = {}
        desc = {
            Osnap.ENDPOINT: "Endpoint – ends of lines and arcs", Osnap.MIDPOINT: "Midpoint – middle of a segment",
            Osnap.CENTER: "Center – center of circles and arcs", Osnap.INTERSECTION: "Intersection – where objects cross",
            Osnap.PERPENDICULAR: "Perpendicular – square to an object", Osnap.TANGENT: "Tangent – touching a curve",
            Osnap.NEAREST: "Nearest – anywhere on an object", Osnap.QUADRANT: "Quadrant – 0/90/180/270° on a circle",
            Osnap.NODE: "Node – point objects", Osnap.EXTENSION: "Extension – along a line past its end",
        }
        for i, m in enumerate(Osnap):
            cb = QCheckBox(desc[m])
            cb.setChecked(m in cfg.modes)
            self.mode_boxes[m] = cb
            g.addWidget(cb, 1 + i // 2, i % 2)
        all_btn = QPushButton("Select all")
        none_btn = QPushButton("Clear all")
        all_btn.clicked.connect(lambda: [b.setChecked(True) for b in self.mode_boxes.values()])
        none_btn.clicked.connect(lambda: [b.setChecked(False) for b in self.mode_boxes.values()])
        g.addWidget(all_btn, 7, 0)
        g.addWidget(none_btn, 7, 1)
        self.aperture = QSpinBox()
        self.aperture.setRange(3, 50)
        self.aperture.setValue(int(cfg.aperture_px))
        g.addWidget(QLabel("Snap reach (pixels)"), 8, 0)
        g.addWidget(self.aperture, 8, 1)
        g.addWidget(QLabel("Tip: hover over a snap point for half a second to start tracking from it."), 9, 0, 1, 2)
        tabs.addTab(os_w, "Object Snap")

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(bb)

    def result(self, old: SnapSettings) -> tuple[SnapSettings, float, float]:
        try:
            inc = float(self.inc.currentText())
            if not 0 < inc <= 180:
                raise ValueError
        except ValueError:
            inc = old.polar_increment_deg
        cfg = SnapSettings(
            osnap_on=self.osnap_on.isChecked(),
            modes=frozenset(m for m, b in self.mode_boxes.items() if b.isChecked()),
            grid_snap_on=self.snap_on.isChecked(), grid_on=self.grid_on.isChecked(),
            ortho_on=self.ortho.isChecked(), polar_on=self.polar_on.isChecked() and not self.ortho.isChecked(),
            polar_increment_deg=inc, otrack_on=self.otrack_on.isChecked(), aperture_px=float(self.aperture.value()),
        )
        return cfg, self.grid_sp._value or self.doc.header.grid_spacing, self.snap_sp._value or self.doc.header.snap_spacing


# ====================================================================== options


class OptionsDialog(QDialog):
    def __init__(self, settings, renderer_info: str, data_folder: str, portable: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Options")
        self.settings = settings
        f = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItems(["Dark", "Light"])
        self.theme.setCurrentIndex(0 if settings.dark_theme else 1)
        self.scale = QComboBox()
        for pct in (75, 100, 125, 150, 175, 200, 250, 300):
            self.scale.addItem(f"{pct}%", pct / 100)
        self.scale.setCurrentIndex(max(0, self.scale.findData(settings.ui_scale)))
        self.font = QComboBox()
        for pct in (80, 90, 100, 115, 130, 150, 175, 200):
            self.font.addItem(f"{pct}%", pct / 100)
        self.font.setCurrentIndex(max(0, self.font.findData(settings.font_scale)))
        self.autosave = QSpinBox()
        self.autosave.setRange(0, 120)
        self.autosave.setSuffix(" min")
        self.autosave.setSpecialValueText("Off")
        self.autosave.setValue(settings.autosave_minutes)
        self.renderer = QComboBox()
        self.renderer.addItem("Automatic (recommended)", "auto")
        self.renderer.addItem("OpenGL (fast)", "gl")
        self.renderer.addItem("Software (compatible)", "painter")
        self.renderer.setCurrentIndex(max(0, self.renderer.findData(settings.renderer)))
        f.addRow("Theme", self.theme)
        f.addRow("Interface size (restart)", self.scale)
        f.addRow("Text size", self.font)
        f.addRow("Autosave every", self.autosave)
        f.addRow("Display engine (restart)", self.renderer)
        info = QLabel(f"<span style='color:gray'>Display: {renderer_info}<br>"
                      f"Settings and autosaves: {data_folder}{' (portable mode)' if portable else ''}</span>")
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(info)
        lay.addWidget(bb)

    def apply(self) -> dict:
        s = self.settings
        changes = {
            "dark": self.theme.currentIndex() == 0,
            "restart": (self.scale.currentData() != s.ui_scale) or (self.renderer.currentData() != s.renderer),
        }
        s.dark_theme = changes["dark"]
        s.ui_scale = self.scale.currentData()
        s.font_scale = self.font.currentData()
        s.autosave_minutes = self.autosave.value()
        s.renderer = self.renderer.currentData()
        s.sync()
        return changes


# ====================================================================== recovery


class RecoveryDialog(QDialog):
    def __init__(self, items: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recover drawings")
        self.items = items
        lbl = QLabel("The program closed unexpectedly last time. These drawings were saved automatically. "
                     "Choose the ones to open:")
        lbl.setWordWrap(True)
        self.list = QListWidget()
        for it in items:
            li = QListWidgetItem(f"{it['title']}   —   autosaved {it['time']}")
            li.setFlags(li.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            li.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(li)
        bb = QDialogButtonBox()
        bb.addButton("Open selected", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton("Discard all", QDialogButtonBox.ButtonRole.DestructiveRole).clicked.connect(self._discard)
        bb.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.discard = False
        lay = QVBoxLayout(self)
        lay.addWidget(lbl)
        lay.addWidget(self.list)
        lay.addWidget(bb)

    def _discard(self) -> None:
        if QMessageBox.question(self, "Discard", "Delete these autosaved drawings? This can't be undone.") \
                == QMessageBox.StandardButton.Yes:
            self.discard = True
            self.accept()

    def chosen(self) -> list[dict]:
        return [it for i, it in enumerate(self.items) if self.list.item(i).checkState() == Qt.CheckState.Checked]


_ = (QDoubleSpinBox, QLineEdit)


# ====================================================================== text


class TextDialog(QDialog):
    """Simple multiline text editor (MTEXT, leader notes, attribute values)."""

    def __init__(self, title: str, text: str = "", parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QPlainTextEdit
        self.setWindowTitle(title)
        self.resize(520, 300)
        self.edit = QPlainTextEdit(text)
        self.edit.setPlaceholderText("Type your text. Press Enter for a new line; click OK when done.")
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.edit)
        lay.addWidget(bb)
        self.edit.setFocus()

    def text(self) -> str:
        return self.edit.toPlainText()


# ====================================================================== page setup / dim style


class PageSetupDialog(QDialog):
    def __init__(self, layout, parent=None) -> None:
        super().__init__(parent)
        from ..core.model import PAPER_SIZES
        self.setWindowTitle(f"Page Setup — {layout.name}")
        self.paper = QComboBox()
        for name, (w, h) in PAPER_SIZES.items():
            self.paper.addItem(f"{name}   ({w:g} x {h:g} mm)", name)
        self.paper.setCurrentIndex(max(0, self.paper.findData(layout.paper)))
        self.portrait = QCheckBox("Portrait (tall)")
        self.portrait.setChecked(layout.portrait)
        f = QFormLayout()
        f.addRow("Paper size", self.paper)
        f.addRow("", self.portrait)
        note = QLabel("The title block keeps its size. Delete it and create a new layout for a matching one.")
        note.setWordWrap(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(note)
        lay.addWidget(bb)

    def result(self) -> tuple[str, bool]:
        return self.paper.currentData(), self.portrait.isChecked()


class DimStyleDialog(QDialog):
    def __init__(self, style, units, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Dimension Style — {style.name}")
        self.style_ = style
        self.fields = {}
        f = QFormLayout()
        for attr, label in (("text_height", "Text height"), ("arrow_size", "Arrow size"),
                            ("ext_offset", "Gap from object"), ("ext_extension", "Extension past dimension line"),
                            ("text_gap", "Gap around text"), ("center_mark", "Center mark size")):
            w = LengthEdit(units, positive=attr != "center_mark")
            w.set_value(getattr(style, attr))
            self.fields[attr] = w
            f.addRow(label, w)
        self.arrow = QComboBox()
        for key, label in (("closed", "Closed filled arrow"), ("open", "Open arrow"), ("tick", "Architectural tick"),
                           ("dot", "Dot")):
            self.arrow.addItem(label, key)
        self.arrow.setCurrentIndex(max(0, self.arrow.findData(style.arrow)))
        f.addRow("Arrowheads", self.arrow)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.0001, 100000)
        self.scale.setDecimals(4)
        self.scale.setValue(style.scale)
        self.scale.setToolTip("Multiplies all sizes above. For a 1:50 drawing printed from model space, use 50.")
        f.addRow("Overall scale", self.scale)
        self.places = QSpinBox()
        self.places.setRange(-1, 8)
        self.places.setSpecialValueText("Use drawing units")
        self.places.setValue(style.decimal_places)
        f.addRow("Decimal places", self.places)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(bb)

    def result(self):
        from dataclasses import replace as _r
        vals = {k: (w._value if w._value is not None else getattr(self.style_, k)) for k, w in self.fields.items()}
        return _r(self.style_, arrow=self.arrow.currentData(), scale=self.scale.value(),
                  decimal_places=self.places.value(), **vals)


# ====================================================================== parameters


class ParametersDialog(QDialog):
    """Dimensional constraints: name, expression, current value. Edit an expression to drive the shape."""

    def __init__(self, doc, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Parameters")
        self.resize(520, 360)
        self.doc = doc
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Expression (formula)", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._changed)
        note = QLabel("Type a number (any unit) or a formula using other names, e.g. <b>d1 * 2</b>.")
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addWidget(note)
        lay.addWidget(self.table)
        lay.addWidget(close)
        self.reload()

    def reload(self) -> None:
        from ..core.constraints.model import resolve_values
        from ..core.units import format_length
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        try:
            values = resolve_values(self.doc.constraints)
        except Exception:                 # noqa: BLE001
            values = {}
        for c in sorted((c for c in self.doc.constraints.values() if c.name), key=lambda c: c.name):
            r = self.table.rowCount()
            self.table.insertRow(r)
            name = QTableWidgetItem(c.name)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name.setData(Qt.ItemDataRole.UserRole, c.id)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(c.expression))
            v = values.get(c.name)
            shown = "" if v is None else (f"{v:g}°" if c.kind == "angle" else format_length(v, self.doc.header.units))
            val = QTableWidgetItem(shown)
            val.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 2, val)
        self.table.blockSignals(False)

    def _changed(self, item) -> None:
        if item.column() != 1:
            return
        from dataclasses import replace as _r
        from ..core.constraints import ConstraintError, ExpressionError, evaluate
        from ..core.constraints.model import resolve_values
        from ..core.units import try_parse_length
        cid = self.table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        c = self.doc.constraints.get(cid)
        text = item.text().strip()
        try:
            if c.kind != "angle" and (mm := try_parse_length(text, self.doc.header.units)) is not None:
                text = f"{mm:.12g}"
            else:
                evaluate(text.replace("°", ""), {k: v for k, v in resolve_values(self.doc.constraints).items()
                                                  if k != c.name})
            with self.doc.transaction("Edit parameter"):
                self.doc.set_item("constraint", cid, _r(c, expression=text.replace("°", "")))
        except (ConstraintError, ExpressionError, ValueError) as exc:
            QMessageBox.warning(self, "Parameters", str(exc))
        self.reload()


class AttributesDialog(QDialog):
    """Fill in a block's attributes (title block fields, tags…)."""

    def __init__(self, fields: list[tuple[str, str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit attributes")
        self.edits: dict[str, QLineEdit] = {}
        f = QFormLayout()
        for tag, prompt, value in fields:
            w = QLineEdit(value)
            self.edits[tag] = w
            f.addRow(prompt, w)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(bb)

    def values(self) -> dict[str, str]:
        return {t: w.text() for t, w in self.edits.items()}
