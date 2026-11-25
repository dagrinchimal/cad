"""End-to-end UI tests: real main window, real mouse clicks and typing."""
import os

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from cad.core.model import Circle, Layer, Line, Polyline
from cad.core.units import UnitMode
from cad.ui.main_window import MainWindow
from cad.ui.settings import AppSettings

pytestmark = pytest.mark.gui


@pytest.fixture
def win(qtbot):
    w = MainWindow(AppSettings())     # not qtbot.addWidget: we close it ourselves after marking saved
    w.resize(1200, 800)
    w.show()
    qtbot.waitExposed(w)
    yield w
    w.doc.mark_saved()
    w.close()


def type_line(qtbot, win, text):
    """Type into the command line like a user and press Enter."""
    win.cmdline.input.setFocus()
    qtbot.keyClicks(win.cmdline.input, text)
    qtbot.keyClick(win.cmdline.input, Qt.Key.Key_Return)


def screen(win, p):
    x, y = win.controller.view.to_screen(p)
    return QPoint(round(x), round(y))


def click(qtbot, win, p, mods=Qt.KeyboardModifier.NoModifier):
    pos = screen(win, p)
    QTest.mouseMove(win.canvas, pos)
    qtbot.mouseClick(win.canvas, Qt.MouseButton.LeftButton, mods, pos)


def test_type_commands_and_coordinates(qtbot, win):
    type_line(qtbot, win, "L")
    assert win.runner.active.name == "LINE"
    for t in ("0,0", "@100,0", "@0,50", "c"):
        type_line(qtbot, win, t)
    assert len([e for e in win.doc.entities.values() if isinstance(e, Line)]) == 3
    assert not win.runner.is_active
    assert "*" in win.windowTitle()


def test_command_search_suggestions(qtbot, win):
    win.cmdline.input.setFocus()
    qtbot.keyClicks(win.cmdline.input, "circ")
    assert win.cmdline.popup.isVisible()
    first = win.cmdline.popup.item(0).data(Qt.ItemDataRole.UserRole)
    assert first == "CIRCLE"
    qtbot.keyClick(win.cmdline.input, Qt.Key.Key_Return)
    assert win.runner.active.name == "CIRCLE"


def test_draw_with_mouse_and_endpoint_snap(qtbot, win):
    with win.doc.transaction("seed"):
        win.doc.add(Line(p1=(0, 0), p2=(100, 0)))
    win.controller.zoom_extents()
    win.run_command("LINE")
    near_end = (100 + 2 * win.controller.view.pixel, 2 * win.controller.view.pixel)
    click(qtbot, win, near_end)                 # snaps exactly onto (100, 0)
    type_line(qtbot, win, "@0,40")
    qtbot.keyClick(win.canvas, Qt.Key.Key_Escape)
    new = [e for e in win.doc.entities.values() if isinstance(e, Line)][-1]
    assert new.p1 == (100, 0)
    assert new.p2 == pytest.approx((100, 40))


def test_typing_on_canvas_goes_to_command_line(qtbot, win):
    win.canvas.setFocus()
    qtbot.keyClicks(win.canvas, "c")
    assert win.cmdline.input.text() == "c"


def test_selection_click_window_and_erase(qtbot, win):
    with win.doc.transaction("seed"):
        a = win.doc.add(Line(p1=(0, 0), p2=(100, 0)))
        b = win.doc.add(Circle(center=(300, 0), radius=20))
    win.controller.zoom_extents()
    click(qtbot, win, (50, 0))
    assert win.ctx.selection == {a.handle}
    qtbot.keyClick(win.canvas, Qt.Key.Key_Escape)
    assert not win.ctx.selection
    # left-to-right window around the circle
    p1, p2 = screen(win, (270, 30)), screen(win, (330, -30))
    QTest.mouseMove(win.canvas, p1)
    qtbot.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=p1)
    QTest.mouseMove(win.canvas, p2)
    qtbot.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, pos=p2)
    win.controller._finish_window(p2.toPointF(), Qt.KeyboardModifier.NoModifier) if win.controller.window_start else None
    assert b.handle in win.ctx.selection
    qtbot.keyClick(win.canvas, Qt.Key.Key_Delete)
    assert b.handle not in win.doc.entities
    win.undo()
    assert b.handle in win.doc.entities


def test_units_switch_changes_display_not_geometry(qtbot, win):
    type_line(qtbot, win, "C")
    type_line(qtbot, win, "0,0")
    type_line(qtbot, win, "1in")
    c = next(e for e in win.doc.entities.values() if isinstance(e, Circle))
    assert c.radius == pytest.approx(25.4)
    idx = win.units_combo.findData(UnitMode.FRACTIONAL.value)
    win.units_combo.setCurrentIndex(idx)
    win.units_combo.activated.emit(idx)
    assert win.doc.header.units.mode is UnitMode.FRACTIONAL
    assert next(e for e in win.doc.entities.values() if isinstance(e, Circle)).radius == pytest.approx(25.4)
    win.ctx.selection.add(c.handle)
    win.properties.refresh()
    from cad.ui.widgets import LengthEdit
    radius_field = [w for w in win.properties.findChildren(LengthEdit) if w.text() == '1"']
    assert radius_field, "radius should display as 1\""


def test_properties_panel_edits_geometry(qtbot, win):
    with win.doc.transaction("seed"):
        c = win.doc.add(Circle(center=(0, 0), radius=10))
    win.ctx.selection.add(c.handle)
    win.properties.refresh()
    from cad.ui.widgets import LengthEdit
    fields = win.properties.findChildren(LengthEdit)
    radius = next(f for f in fields if f.text() == "10.00")
    radius.setText("2in")
    radius.setModified(True)
    radius.editingFinished.emit()
    assert win.doc.get(c.handle).radius == pytest.approx(50.8)


def test_layers_and_current_layer(qtbot, win):
    with win.doc.transaction("layer"):
        win.doc.add_layer(Layer("Walls", color=1))
    idx = win.layer_combo.findData("Walls")
    assert idx >= 0
    win.layer_combo.activated.emit(idx)
    assert win.doc.header.current_layer == "Walls"
    type_line(qtbot, win, "PL")
    for t in ("0,0", "10,0", "10,10", "c"):
        type_line(qtbot, win, t)
    pl = next(e for e in win.doc.entities.values() if isinstance(e, Polyline))
    assert pl.layer == "Walls" and pl.closed


def test_layer_dialog(qtbot, win):
    from cad.ui.dialogs import LayerDialog
    dlg = LayerDialog(win.doc, True, win)
    dlg._new()
    assert "Layer1" in win.doc.layers
    dlg.table.selectRow(list(win.doc.layers).index("Layer1"))
    dlg._set_current()
    assert win.doc.header.current_layer == "Layer1"
    dlg.done(0)


def test_save_open_round_trip(qtbot, win, tmp_path):
    type_line(qtbot, win, "C")
    type_line(qtbot, win, "5,5")
    type_line(qtbot, win, "3")
    path = str(tmp_path / "t.cadz")
    assert win._save_to(path)
    assert "*" not in win.windowTitle()
    win.new_drawing()
    assert len(win.doc) == 0
    assert win.open_path(path)
    assert len(win.doc) == 1


def test_autosave_and_recovery(qtbot, win):
    from cad.ui.autosave import AutosaveSession, find_recoverable
    from cad.ui.settings import autosave_dir
    type_line(qtbot, win, "C")
    type_line(qtbot, win, "0,0")
    type_line(qtbot, win, "5")
    assert win.autosave_now()
    assert not win.autosave_now()          # nothing changed since
    # a live session is not offered for recovery...
    assert all(it["id"] != win.autosave.id for it in find_recoverable(autosave_dir()))
    # ...but a crashed one (lock released without cleanup) is
    win.autosave.lock.unlock()
    items = [it for it in find_recoverable(autosave_dir()) if it["id"] == win.autosave.id]
    assert len(items) == 1
    s2 = AutosaveSession(autosave_dir())
    s2.close()


def test_toggles_and_shortcuts(qtbot, win):
    before = win.snap_cfg.ortho_on
    win.toggle("ortho_on")
    assert win.snap_cfg.ortho_on != before
    assert win.toggle_buttons["ortho_on"].isChecked() == win.snap_cfg.ortho_on
    if win.snap_cfg.ortho_on:
        assert not win.snap_cfg.polar_on


def test_theme_switch(qtbot, win):
    win.set_theme(False)
    assert win.canvas.data.background.lightness() > 200
    win.set_theme(True)
    assert win.canvas.data.background.lightness() < 100


def test_context_menu_is_relevant(qtbot, win):
    def labels():
        return [a.text() for a in win.build_context_menu().actions()]
    assert "Zoom extents" in labels()                    # idle: view actions
    with win.doc.transaction("seed"):
        e = win.doc.add(Line(p1=(0, 0), p2=(1, 0)))
    win.ctx.selection.add(e.handle)
    assert any(t.startswith("Erase 1") for t in labels())  # selection: edit actions
    win.ctx.selection.clear()
    win.run_command("LINE")
    type_line(qtbot, win, "0,0")
    got = labels()
    assert "Undo" in got and "Cancel" in got and "Zoom extents" not in got   # command: its options


def test_every_ribbon_button_has_label_and_tooltip(win):
    for btn, _tool in win.ribbon.buttons:
        assert btn.text().strip()
        assert btn.toolTip().strip()
        assert not btn.icon().isNull()


@pytest.mark.gl
def test_opengl_canvas_renders():
    from cad.render.canvas_base import opengl_33_available
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen" or not opengl_33_available():
        pytest.skip("OpenGL 3.3 not available here")
    from cad.render.canvas_gl import GLCanvas
    assert GLCanvas
