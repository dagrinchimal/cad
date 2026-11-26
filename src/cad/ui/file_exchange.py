"""Dialogs for import/export and printing: options forms built from plugin Options, export, batch
export, plot (print) with preview, and the report shown afterwards."""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import QColor, QPageLayout, QPageSize, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..core.model import Document
from ..plugins import FormatPlugin, Option, PluginError, Report, registry

PDF_FILE = "__pdf_file__"


# ====================================================================== options form
class OptionsForm(QWidget):
    """Widgets for a list of plugin Options."""

    def __init__(self, options: list[Option], values: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.options = options
        self.widgets: dict[str, QWidget] = {}
        f = QFormLayout(self)
        f.setContentsMargins(0, 0, 0, 0)
        values = values or {}
        for o in options:
            v = values.get(o.key, o.default)
            if o.kind in ("choice", "scale"):
                w = QComboBox()
                for val, label in o.choice_items():
                    w.addItem(label, val)
                if o.kind == "scale":
                    w.setEditable(True)
                    w.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                i = w.findData(v)
                if i >= 0:
                    w.setCurrentIndex(i)
                elif o.kind == "scale":
                    w.setEditText(str(v))
                w.currentIndexChanged.connect(lambda *_: self.changed())
                if o.kind == "scale":
                    w.lineEdit().editingFinished.connect(self.changed)
            elif o.kind == "bool":
                w = QCheckBox()
                w.setChecked(bool(v))
                w.toggled.connect(lambda *_: self.changed())
            elif o.kind == "int":
                w = QSpinBox()
                w.setRange(int(o.minimum if o.minimum is not None else -10**9), int(o.maximum if o.maximum is not None else 10**9))
                w.setValue(int(v))
                w.valueChanged.connect(lambda *_: self.changed())
            elif o.kind in ("float", "length"):
                w = QDoubleSpinBox()
                w.setDecimals(4)
                w.setRange(o.minimum if o.minimum is not None else -1e9, o.maximum if o.maximum is not None else 1e9)
                w.setValue(float(v))
                w.valueChanged.connect(lambda *_: self.changed())
            else:
                w = QLineEdit(str(v if v is not None else ""))
                w.editingFinished.connect(self.changed)
            if o.help:
                w.setToolTip(o.help)
            self.widgets[o.key] = w
            f.addRow(o.label, w)
        self._listeners: list = []

    def on_change(self, fn) -> None:
        self._listeners.append(fn)

    def changed(self) -> None:
        for fn in self._listeners:
            fn()

    def values(self) -> dict:
        out = {}
        for o in self.options:
            w = self.widgets[o.key]
            if isinstance(w, QComboBox):
                if o.kind == "scale":
                    text = w.currentText().strip()
                    data = w.currentData()
                    idx = w.findText(text)
                    out[o.key] = w.itemData(idx) if idx >= 0 else (data if text == w.itemText(w.currentIndex()) else text)
                else:
                    out[o.key] = w.currentData()
            elif isinstance(w, QCheckBox):
                out[o.key] = w.isChecked()
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                out[o.key] = w.value()
            else:
                out[o.key] = w.text()
        return out


def remembered(settings, plugin_id: str, which: str = "export") -> dict:
    try:
        return json.loads(settings.get(f"exchange/{which}_{plugin_id}", "{}") or "{}")
    except (TypeError, ValueError):
        return {}


def remember(settings, plugin_id: str, values: dict, which: str = "export") -> None:
    keep = {k: v for k, v in values.items() if k != "what"}      # "what" depends on the drawing
    settings.set(f"exchange/{which}_{plugin_id}", json.dumps(keep))


# ====================================================================== report
class ReportDialog(QDialog):
    def __init__(self, title: str, report: Report, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        head = "Done." if report.ok else "There were problems."
        if report.warnings or report.skipped:
            head += " Some things couldn't be carried over exactly; details below."
        lay.addWidget(QLabel(head))
        t = QPlainTextEdit(report.summary())
        t.setReadOnly(True)
        t.setMinimumSize(520, 220)
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


def report_needs_dialog(report: Report) -> bool:
    return bool(report.warnings or report.errors or report.skipped)


# ====================================================================== export
class ExportDialog(QDialog):
    """Pick a format, a file and the format's options; see what the format can't keep."""

    def __init__(self, doc: Document, settings, start_path: str, preselect: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.doc = doc
        self.settings = settings
        self.plugins = [p for p in registry.exporters() if p.id != "cadz"]
        self.fmt = QComboBox()
        for p in self.plugins:
            self.fmt.addItem(f"{p.name} ({', '.join(p.extensions)})", p.id)
        last = preselect or settings.get("exchange/last_export", "pdf")
        i = self.fmt.findData(last)
        self.fmt.setCurrentIndex(max(0, i))
        self.path = QLineEdit()
        self._start = start_path
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        self.form_box = QGroupBox("Options")
        self.form_lay = QVBoxLayout(self.form_box)
        self.form: OptionsForm | None = None
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        top = QFormLayout()
        top.addRow("Format", self.fmt)
        top.addRow("File", row)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.form_box)
        lay.addWidget(self.note)
        lay.addStretch(1)
        lay.addWidget(self.buttons)
        self.fmt.currentIndexChanged.connect(self._format_changed)
        self._format_changed()
        self.resize(560, self.sizeHint().height())

    @property
    def plugin(self) -> FormatPlugin:
        return registry.get(self.fmt.currentData())

    def _format_changed(self) -> None:
        p = self.plugin
        if self.form is not None:
            self.form.setParent(None)
            self.form.deleteLater()
        self.form = OptionsForm(p.export_options(self.doc), remembered(self.settings, p.id), self)
        self.form_lay.addWidget(self.form)
        self.form_box.setVisible(bool(self.form.options))
        stem = os.path.splitext(self.path.text() or self._start)[0]
        self.path.setText(stem + p.extensions[0])
        ok, why = p.available()
        lines = []
        if not ok:
            lines.append(f"<b>Not available:</b> {why}")
        losses = p.losses(self.doc)
        if losses:
            lines.append("<b>This format can't keep:</b><br>• " + "<br>• ".join(losses))
        self.note.setText("<br><br>".join(lines))
        self.note.setVisible(bool(lines))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def _browse(self) -> None:
        p = self.plugin
        path, _ = QFileDialog.getSaveFileName(self, "Export to", self.path.text(), p.file_filter())
        if path:
            if not path.lower().endswith(p.extensions):
                path += p.extensions[0]
            self.path.setText(path)

    def _accept(self) -> None:
        if not self.path.text().strip():
            self.note.setText("Choose a file name.")
            self.note.setVisible(True)
            return
        try:
            self.plugin.checked_options("export", self.form.values(), self.doc)
        except PluginError as exc:
            self.note.setText(f"<b>{exc}</b>")
            self.note.setVisible(True)
            return
        self.settings.set("exchange/last_export", self.plugin.id)
        remember(self.settings, self.plugin.id, self.form.values())
        self.accept()

    def result_values(self) -> tuple[FormatPlugin, str, dict]:
        path = self.path.text().strip()
        p = self.plugin
        if not path.lower().endswith(p.extensions):
            path += p.extensions[0]
        return p, path, self.form.values()


# ====================================================================== batch export
class BatchExportDialog(QDialog):
    """Export the drawing to several formats at once, into one folder."""

    def __init__(self, doc: Document, settings, folder: str, base: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batch Export")
        self.doc = doc
        self.settings = settings
        self.list = QListWidget()
        chosen = set((settings.get("exchange/batch", "pdf,dxf") or "").split(","))
        for p in registry.exporters():
            if p.id == "cadz":
                continue
            it = QListWidgetItem(f"{p.name} ({p.extensions[0]})")
            it.setData(Qt.ItemDataRole.UserRole, p.id)
            ok, why = p.available()
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if (p.id in chosen and ok) else Qt.CheckState.Unchecked)
            if not ok:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                it.setToolTip(why)
            self.list.addItem(it)
        self.folder = QLineEdit(folder)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse)
        self.base = QLineEdit(base)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(b)
        f = QFormLayout()
        f.addRow("Folder", row)
        f.addRow("File name", self.base)
        hint = QLabel("Each format uses the options you last chose for it in Export. "
                      "Sheets (PDF, images) include the model and every layout.")
        hint.setWordWrap(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Export all")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Formats"))
        lay.addWidget(self.list)
        lay.addLayout(f)
        lay.addWidget(hint)
        lay.addWidget(bb)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Export into", self.folder.text())
        if d:
            self.folder.setText(d)

    def chosen(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out

    def _accept(self) -> None:
        if self.chosen() and self.base.text().strip() and os.path.isdir(self.folder.text()):
            self.settings.set("exchange/batch", ",".join(self.chosen()))
            self.accept()


def batch_export(doc: Document, settings, ids: list[str], folder: str, base: str) -> Report:
    """Run several exporters; one combined report."""
    total = Report(title=f"Batch export to {folder}")
    for pid in ids:
        p = registry.get(pid)
        r = Report()
        opts = remembered(settings, pid)
        if "what" in [o.key for o in p.export_options(doc)]:
            opts["what"] = "everything" if doc.layouts else "model"
        path = os.path.join(folder, base + p.extensions[0])
        try:
            p.export(doc, path, opts, r)
            total.info(f"{p.name}: {os.path.basename(path)}")
        except PluginError as exc:
            total.error(f"{p.name}: {exc}")
        except Exception as exc:                 # noqa: BLE001 - report, keep going with the others
            total.error(f"{p.name}: unexpected problem: {exc}")
        for w in r.warnings:
            total.warn(f"{p.name}: {w}")
    return total


# ====================================================================== plot / print
def print_sheets(printer, sheets) -> None:
    """Send sheets to a QPrinter (or a QPrinter writing a PDF) at exactly 1:1 paper size."""
    from ..render.plot_qt import paint_sheet

    def layout_for(sh):
        size = QPageSize(QSizeF(sh.width, sh.height), QPageSize.Unit.Millimeter, sh.name,
                         QPageSize.SizeMatchPolicy.FuzzyMatch)
        return QPageLayout(size, QPageLayout.Orientation.Portrait, printer.pageLayout().margins(),
                           QPageLayout.Unit.Millimeter)

    printer.setFullPage(True)
    printer.setPageLayout(layout_for(sheets[0]))
    p = QPainter()
    if not p.begin(printer):
        raise PluginError("The printer couldn't be started.")
    try:
        for i, sh in enumerate(sheets):
            if i:
                printer.setPageLayout(layout_for(sh))
                printer.newPage()
            dpi = printer.resolution()
            px = dpi / 25.4
            paint_sheet(p, sh, QRectF(0, 0, sh.width * px, sh.height * px), min_width_px=0.05 * px)
    finally:
        p.end()


class PlotDialog(QDialog):
    """AutoCAD-style Plot: printer, what to plot, paper, scale, colors, with a live preview."""

    def __init__(self, doc: Document, settings, start_pdf: str, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtPrintSupport import QPrinterInfo
        from ..plugins.formats.pdf import PdfPlugin
        self.setWindowTitle("Plot")
        self.doc = doc
        self.settings = settings
        self.plugin = PdfPlugin()
        self.printer = QComboBox()
        names = QPrinterInfo.availablePrinterNames()
        default = QPrinterInfo.defaultPrinterName()
        for n in names:
            self.printer.addItem(n, n)
        self.printer.addItem("Save as a PDF file", PDF_FILE)
        last = settings.get("plot/printer", default or PDF_FILE)
        i = self.printer.findData(last)
        self.printer.setCurrentIndex(i if i >= 0 else self.printer.findData(default) if default in names else self.printer.count() - 1)
        self.pdf_path = QLineEdit(start_pdf)
        self.pdf_row = QWidget()
        r = QHBoxLayout(self.pdf_row)
        r.setContentsMargins(0, 0, 0, 0)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse)
        r.addWidget(self.pdf_path, 1)
        r.addWidget(b)
        self.copies = QSpinBox()
        self.copies.setRange(1, 99)
        opts = [replace(o, label="What to plot") if o.key == "what" else o for o in self.plugin.export_options(doc)]
        self.form = OptionsForm(opts, remembered(settings, "plot"), self)
        self.form.on_change(self._schedule_preview)
        self.printer.currentIndexChanged.connect(self._printer_changed)
        top = QFormLayout()
        top.addRow("Printer", self.printer)
        top.addRow("PDF file", self.pdf_row)
        top.addRow("Copies", self.copies)
        left = QVBoxLayout()
        left.addLayout(top)
        left.addWidget(self.form)
        self.msg = QLabel()
        self.msg.setWordWrap(True)
        left.addWidget(self.msg)
        left.addStretch(1)
        self.preview = QLabel()
        self.preview.setMinimumSize(420, 320)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:#808080")
        body = QHBoxLayout()
        body.addLayout(left, 0)
        body.addWidget(self.preview, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = bb.button(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(body, 1)
        lay.addWidget(bb)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.update_preview)
        self._printer_changed()
        self.update_preview()

    def _printer_changed(self) -> None:
        pdf = self.printer.currentData() == PDF_FILE
        self.pdf_row.setEnabled(pdf)
        self.copies.setEnabled(not pdf)
        self.ok.setText("Save PDF" if pdf else "Print")

    def _browse(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Save plot as", self.pdf_path.text(), "PDF (*.pdf)")
        if p:
            self.pdf_path.setText(p if p.lower().endswith(".pdf") else p + ".pdf")

    def _schedule_preview(self) -> None:
        self._timer.start()

    def sheets(self):
        o = self.plugin.checked_options("export", self.form.values(), self.doc)
        return self.plugin.sheets(self.doc, o)

    def update_preview(self) -> None:
        from ..render.plot_qt import paint_sheet
        try:
            sheets = self.sheets()
        except PluginError as exc:
            self.msg.setText(f"<b>{exc}</b>")
            self.ok.setEnabled(False)
            return
        self.ok.setEnabled(True)
        self.msg.setText(f"{len(sheets)} sheet{'s' if len(sheets) > 1 else ''}" +
                         (" (preview shows the first)" if len(sheets) > 1 else "") +
                         f": {sheets[0].width:g} x {sheets[0].height:g} mm")
        sh = sheets[0]
        W, H = max(100, self.preview.width() - 20), max(100, self.preview.height() - 20)
        s = min(W / sh.width, H / sh.height)
        pm = QPixmap(max(1, int(sh.width * s)), max(1, int(sh.height * s)))
        pm.fill(QColor(255, 255, 255))
        p = QPainter(pm)
        paint_sheet(p, sh, QRectF(0, 0, pm.width(), pm.height()), min_width_px=0.6)
        p.end()
        self.preview.setPixmap(pm)
        self.last_sheets = sheets

    def resizeEvent(self, ev) -> None:          # noqa: N802
        super().resizeEvent(ev)
        self._schedule_preview()

    def _accept(self) -> None:
        if self.printer.currentData() == PDF_FILE and not self.pdf_path.text().strip():
            self.msg.setText("<b>Choose a PDF file name.</b>")
            return
        self.settings.set("plot/printer", self.printer.currentData())
        remember(self.settings, "plot", self.form.values())
        self.accept()

    def make_printer(self):
        from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
        target = self.printer.currentData()
        if target == PDF_FILE:
            pr = QPrinter(QPrinter.PrinterMode.HighResolution)
            pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            path = self.pdf_path.text().strip()
            pr.setOutputFileName(path if path.lower().endswith(".pdf") else path + ".pdf")
        else:
            pr = QPrinter(QPrinterInfo.printerInfo(target), QPrinter.PrinterMode.HighResolution)
            pr.setCopyCount(self.copies.value())
        pr.setDocName(Path(self.doc.path).stem if self.doc.path else "Drawing")
        return pr


# ====================================================================== import filter
def open_filter() -> str:
    imps = registry.importers()
    exts = " ".join("*" + e for p in imps for e in p.extensions)
    return ";;".join([f"All drawings ({exts})"] + [p.file_filter() for p in imps] + ["All files (*)"])


def save_filter() -> str:
    exps = [p for p in registry.exporters() if p.id in ("cadz", "dxf", "dwg")]
    return ";;".join(p.file_filter() for p in exps)
