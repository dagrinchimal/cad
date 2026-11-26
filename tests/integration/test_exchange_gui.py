import os

import pytest
from PySide6.QtCore import Qt

from cad.core.model import BlockReference, Circle, Line
from cad.plugins import registry
from cad.samples import rich_document
from cad.ui.main_window import MainWindow
from cad.ui.settings import AppSettings


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("CAD_DATA_DIR", str(tmp_path / "data"))
    w = MainWindow(AppSettings())
    w.resize(1200, 800)
    w.show()
    qtbot.waitExposed(w)
    yield w
    w.doc.mark_saved()
    w.close()


def test_open_dxf_and_ctrl_s_saves_dxf_again(win, tmp_path):
    src = tmp_path / "plan.dxf"
    r = registry.get("dxf")
    from cad.plugins import Report
    r.export(rich_document(), str(src), {}, Report())
    assert win.open_path(str(src))
    assert win.doc.path == str(src) and win.doc.save_format == "dxf"
    assert len([e for e in win.doc.entities.values() if isinstance(e, Circle)]) == 3
    assert "plan.dxf" in win.windowTitle()
    with win.doc.transaction("add"):
        win.doc.add(Line(p1=(0, 0), p2=(999, 999)))
    assert win.save()
    back = r.import_(str(src), {}, Report())
    assert any(isinstance(e, Line) and e.p2 == pytest.approx((999, 999)) for e in back.entities.values())


def test_save_as_dxf_then_cadz(win, tmp_path):
    with win.doc.transaction("s"):
        win.doc.add(Circle(center=(1, 2), radius=3))
    p = str(tmp_path / "a.dxf")
    assert win._save_to(p) and os.path.isfile(p) and not win.doc.is_modified
    p2 = str(tmp_path / "a.cadz")
    assert win._save_to(p2) and win.doc.save_format is None


def test_import_merges_into_current_drawing(win, tmp_path):
    from cad.plugins import Report
    src = tmp_path / "parts.dxf"
    registry.get("dxf").export(rich_document(), str(src), {}, Report())
    with win.doc.transaction("s"):
        win.doc.add(Line(p1=(-50, -50), p2=(-40, -40)))
    before = len(win.doc.entities)
    assert win.import_path(str(src))
    assert len(win.doc.entities) > before + 20
    assert "Door" in win.doc.blocks and any(isinstance(e, BlockReference) for e in win.doc.entities.values())
    assert win.ctx.selection and len(win.ctx.selection) == len(win.doc.entities) - before
    win.doc.undo()
    assert len(win.doc.entities) == before


def test_export_dialog_options_and_losses(win, tmp_path):
    from cad.ui.file_exchange import ExportDialog
    win.set_document(rich_document())
    dlg = ExportDialog(win.doc, win.settings, str(tmp_path / "x"), "dxf", win)
    assert dlg.plugin.id == "dxf" and dlg.path.text().endswith(".dxf")
    assert "associativity" in dlg.note.text()
    dlg.fmt.setCurrentIndex(dlg.fmt.findData("pdf"))
    assert dlg.path.text().endswith(".pdf") and "what" in dlg.form.widgets
    w = dlg.form.widgets["scale"]
    w.setEditText("1:20")
    assert dlg.form.values()["scale"] == "1:20"
    w.setEditText("nonsense")
    dlg._accept()
    assert dlg.result() == 0 and "Scale" in dlg.note.text()
    w.setCurrentIndex(0)
    plugin, path, values = dlg.result_values()
    assert win.run_export(plugin.id, path, values) and os.path.isfile(path)


def test_plot_to_pdf_file(win, tmp_path, monkeypatch):
    import pypdf
    from cad.ui.file_exchange import PDF_FILE, PlotDialog, print_sheets
    win.set_document(rich_document())
    dlg = PlotDialog(win.doc, win.settings, str(tmp_path / "plot.pdf"), win)
    dlg.printer.setCurrentIndex(dlg.printer.findData(PDF_FILE))
    what = dlg.form.widgets["what"]
    what.setCurrentIndex(what.findData("everything"))
    dlg.update_preview()
    assert dlg.preview.pixmap() is not None and not dlg.preview.pixmap().isNull()
    print_sheets(dlg.make_printer(), dlg.sheets())
    r = pypdf.PdfReader(str(tmp_path / "plot.pdf"))
    assert len(r.pages) == 2
    w_mm = float(r.pages[1].mediabox.width) / 72 * 25.4
    assert w_mm == pytest.approx(420, abs=1)


def test_batch_export(win, tmp_path):
    from cad.ui.file_exchange import batch_export
    win.set_document(rich_document())
    rep = batch_export(win.doc, win.settings, ["dxf", "pdf", "svg", "png"], str(tmp_path), "set")
    assert rep.ok, rep.summary()
    names = set(os.listdir(tmp_path))
    assert {"set.dxf", "set.pdf"} <= names and any(n.startswith("set-") and n.endswith(".svg") for n in names)


def test_missing_dwg_converter_is_explained(win, tmp_path, monkeypatch):
    from cad.plugins.formats import dwg
    monkeypatch.setattr(dwg, "find_converter", lambda configured=None: None)
    shown = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    p = tmp_path / "x.dwg"
    p.write_bytes(b"AC1032")
    assert not win.open_path(str(p))
    assert shown and "ODA File Converter" in shown[0]


def test_output_commands_exist(win):
    from cad.commands import REGISTRY
    for name in ("PLOT", "EXPORT", "IMPORT", "BATCHEXPORT", "EXPORTPDF", "DXFOUT", "DXFIN"):
        assert REGISTRY.get(name) is not None
    assert REGISTRY.get("PRINT").name == "PLOT"
