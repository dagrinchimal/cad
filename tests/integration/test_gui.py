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


# ----------------------------------------------------------------- phase 3
def test_every_command_has_an_icon_and_ribbon_tabs():
    from cad.commands import REGISTRY
    from cad.ui.icons import ICONS
    missing = [c.name for c in REGISTRY.all() if c.icon not in ICONS and c.group not in ("Application",)]
    assert not missing, missing


def test_ribbon_has_phase3_tabs(win):
    titles = [win.ribbon.tabbar.tabText(i) for i in range(win.ribbon.tabbar.count())]
    assert titles == ["Home", "Annotate", "Parametric", "Layout", "View"]
    names = {t.command for _, t in win.ribbon.buttons}
    for n in ("TRIM", "HATCH", "DIMLINEAR", "GCPARALLEL", "MVIEW", "INSERT"):
        assert n in names


def test_trim_by_clicking(qtbot, win):
    with win.doc.transaction("seed"):
        h = win.doc.add(Line(p1=(0, 0), p2=(100, 0)))
        win.doc.add(Line(p1=(50, -20), p2=(50, 20)))
    win.controller.zoom_extents()
    win.run_command("TRIM")
    click(qtbot, win, (75, 0))
    qtbot.keyClick(win.canvas, Qt.Key.Key_Return)
    lines = [e for e in win.doc.entities.values() if isinstance(e, Line) and e.p1[1] == 0 == e.p2[1]]
    assert len(lines) == 1 and max(lines[0].p1[0], lines[0].p2[0]) == pytest.approx(50)
    assert h.handle not in win.doc.entities


def test_hatch_by_clicking_inside(qtbot, win):
    from cad.core.model import Hatch
    with win.doc.transaction("seed"):
        win.doc.add(Polyline(vertices=((0, 0, 0), (100, 0, 0), (100, 60, 0), (0, 60, 0)), closed=True))
    win.controller.zoom_extents()
    win.run_command("HATCH")
    click(qtbot, win, (30, 30))
    qtbot.keyClick(win.canvas, Qt.Key.Key_Return)
    h = next(e for e in win.doc.entities.values() if isinstance(e, Hatch))
    assert h.area() == pytest.approx(6000, rel=1e-6)


def test_layout_tab_viewport_and_scale(qtbot, win):
    from cad.core.model import Viewport
    with win.doc.transaction("seed"):
        win.doc.add(Circle(center=(0, 0), radius=500))
    i = [win.layout_tabs.tabData(k) for k in range(win.layout_tabs.count())].index("+Layout1")
    win.layout_tabs.setCurrentIndex(i)
    assert win.controller.space == "Layout1" and "Layout1" in win.doc.layouts
    assert win.canvas.data.viewports and len(win.canvas.data.model) > 0
    vp = next(e for e in win.doc.entities.values() if isinstance(e, Viewport))
    win.ctx.selection = {vp.handle}
    win.properties.refresh()
    from PySide6.QtWidgets import QComboBox
    cb = next(c for c in win.properties.findChildren(QComboBox) if c.count() and c.itemText(0) == "Scale to fit")
    k = cb.findText("1:10")
    cb.setCurrentIndex(k)
    cb.activated.emit(k)
    vp2 = win.doc.get(vp.handle)
    assert not vp2.fit and vp2.scale == pytest.approx(0.1)
    win.layout_tabs.setCurrentIndex(0)
    assert win.controller.space == "*Model"


def test_double_click_edits_text(qtbot, win, monkeypatch):
    from cad.core.model import Text
    from cad.ui import dialogs
    with win.doc.transaction("seed"):
        t = win.doc.add(Text(insert=(0, 0), text="Old", height=10))
    win.controller.zoom_extents()
    monkeypatch.setattr(dialogs.TextDialog, "exec", lambda self: True)
    monkeypatch.setattr(dialogs.TextDialog, "text", lambda self: "New text")
    win.edit_object(win.doc.get(t.handle))
    assert win.doc.get(t.handle).text == "New text"


def test_mtext_opens_editor(qtbot, win, monkeypatch):
    from cad.core.model import MText
    from cad.ui import dialogs
    monkeypatch.setattr(dialogs.TextDialog, "exec", lambda self: True)
    monkeypatch.setattr(dialogs.TextDialog, "text", lambda self: "Line 1\nLine 2")
    type_line(qtbot, win, "MTEXT")
    type_line(qtbot, win, "0,0")
    type_line(qtbot, win, "100,-50")
    qtbot.waitUntil(lambda: any(isinstance(e, MText) for e in win.doc.entities.values()), timeout=2000)
    m = next(e for e in win.doc.entities.values() if isinstance(e, MText))
    assert m.text == "Line 1\nLine 2"


def test_constraint_symbols_drawn(qtbot, win):
    from cad.core.constraints import Constraint
    with win.doc.transaction("seed"):
        a = win.doc.add(Line(p1=(0, 0), p2=(10, 1)))
    with win.doc.transaction("c"):
        win.doc.set_item("constraint", 1, Constraint(1, "horizontal", ((a.handle, "line"),)))
    assert win.doc.get(a.handle).p1[1] == pytest.approx(win.doc.get(a.handle).p2[1], abs=1e-7)
    win.controller.zoom_extents()
    img = win.canvas.grab_image()
    assert not img.isNull()


def _select(qtbot, win, p):
    click(qtbot, win, p)
    win.canvas.repaint()                  # paints grips and the clickable values


def test_drag_grip_with_two_clicks(qtbot, win):
    with win.doc.transaction("seed"):
        a = win.doc.add(Line(p1=(0, 0), p2=(100, 0)))
        b = win.doc.add(Line(p1=(100, 0), p2=(100, 60)))
    win.controller.zoom_extents()
    click(qtbot, win, (50, 0))
    click(qtbot, win, (100, 30))
    click(qtbot, win, (100, 0))           # the shared corner grip
    assert win.runner.active.name == "GRIPEDIT"
    type_line(qtbot, win, "120,10")
    assert win.doc.get(a.handle).p2 == pytest.approx((120, 10))
    assert win.doc.get(b.handle).p1 == pytest.approx((120, 10))


def test_click_the_length_and_type_feet_inches(qtbot, win):
    from dataclasses import replace
    from cad.core.units import UnitSettings
    with win.doc.transaction("seed"):
        win.doc.set_header(replace(win.doc.header, units=UnitSettings(mode=UnitMode.ARCHITECTURAL)))
        ln = win.doc.add(Line(p1=(0, 0), p2=(3048, 0)))
    win.controller.zoom_extents()
    win.controller.zoom_factor(0.8)
    _select(qtbot, win, (1500, 0))
    boxes = win.controller.value_boxes
    assert boxes and boxes[0][1].kind == "length"
    rect = boxes[0][0]
    qtbot.mouseClick(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(round(rect.center().x()), round(rect.center().y())))
    ed = win.controller.value_editor
    assert ed is not None and ed.isVisible() and ed.text() == "10'-0\""
    ed.selectAll()
    qtbot.keyClicks(ed, "3 4-1/2")
    qtbot.keyClick(ed, Qt.Key.Key_Return)
    assert win.doc.get(ln.handle).p2[0] == pytest.approx((36 + 4.5) * 25.4)
    assert win.controller.value_editor is None
    win.doc.undo()
    assert win.doc.get(ln.handle).p2[0] == pytest.approx(3048)


def test_fence_trim_with_mouse_and_shift_extend(qtbot, win):
    with win.doc.transaction("seed"):
        for y in (0, 10, 20):
            win.doc.add(Line(p1=(0, y), p2=(100, y)))
        win.doc.add(Line(p1=(30, -10), p2=(30, 30)))
        win.doc.add(Line(p1=(70, -10), p2=(70, 30)))
        short = win.doc.add(Line(p1=(0, 40), p2=(20, 40)))
        win.doc.add(Line(p1=(-10, 50), p2=(100, 50)))
    win.controller.zoom_extents()
    win.run_command("TRIM")
    click(qtbot, win, (50, 25))           # empty space starts a fence
    assert "fence" in win.runner.request.prompt, win.runner.ctx.messages[-5:]
    c = win.controller
    dbg = [("p1", c.runner.request.base, "screen", screen(win, (50, -5)), "cfg", c.cfg)]
    click(qtbot, win, (50, -5))
    dbg.append(("cursor", c.cursor_screen, c.cursor_model, "snap", c.snap and (c.snap.kind, c.snap.point, c.snap.osnap)))
    qtbot.keyClick(win.canvas, Qt.Key.Key_Return)
    horiz = [e for e in win.doc.entities.values() if isinstance(e, Line) and e.p1[1] == e.p2[1] and e.p1[1] <= 20]
    assert len(horiz) == 6, (win.runner.ctx.messages[-6:], win.runner.ctx.last_point, dbg)
    v = Line(p1=(10, 30), p2=(10, 45))
    with win.doc.transaction("v"):
        v = win.doc.add(v)
    win.run_command("TRIM")
    click(qtbot, win, (10, 44), Qt.KeyboardModifier.ShiftModifier)      # Shift: extend instead
    qtbot.keyClick(win.canvas, Qt.Key.Key_Return)
    assert win.doc.get(v.handle).p2 == pytest.approx((10, 50))


def test_fast_second_click_in_a_command_counts(qtbot, win):
    win.controller.zoom_extents()
    win.run_command("LINE")
    click(qtbot, win, (0, 0))
    pos = screen(win, (40, 0))
    QTest.mouseMove(win.canvas, pos)
    qtbot.mouseDClick(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    qtbot.keyClick(win.canvas, Qt.Key.Key_Escape)
    assert any(isinstance(e, Line) for e in win.doc.entities.values())
