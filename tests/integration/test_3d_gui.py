import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt

pytest.importorskip("OCP")

from cad.core import solids as S
from cad.core.model import Solid
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


def type_line(qtbot, win, text):
    win.cmdline.input.setFocus()
    qtbot.keyClicks(win.cmdline.input, text)
    qtbot.keyClick(win.cmdline.input, Qt.Key.Key_Return)
    qtbot.wait(5)


def solids(win):
    return [e for e in win.doc.entities.values() if isinstance(e, Solid)]


def screen3d(win, xyz):
    v = win.view3d
    v.cam.width, v.cam.height = v.width(), v.height()
    (p,), _ = v.cam.project(np.array([xyz], float))
    return float(p[0]), float(p[1])


def test_box_then_3d_view_and_presspull_by_click(qtbot, win):
    for t in ("BOX", "0,0", "40,30", "20"):
        type_line(qtbot, win, t)
    (s,) = solids(win)
    type_line(qtbot, win, "VIEW3D")
    type_line(qtbot, win, "SE")
    qtbot.waitUntil(lambda: win.in_3d)
    assert win.view3d.view_name() == "SE Iso"
    win.view3d.repaint()
    img = win.view3d._image
    assert img is not None and img.width() == win.view3d.width()
    # PRESSPULL: click the top face in the 3D view
    type_line(qtbot, win, "PRESSPULL")
    win.view3d.click(*screen3d(win, (20, 15, 20)))
    type_line(qtbot, win, "10")
    assert S.mass_properties(win.doc.get(s.handle).shape)["volume"] == pytest.approx(40 * 30 * 30)


def test_click_selects_solid_and_styles(qtbot, win):
    for t in ("BOX", "0,0", "10,10", "10"):
        type_line(qtbot, win, t)
    type_line(qtbot, win, "ORBIT")
    qtbot.waitUntil(lambda: win.in_3d)
    win.view3d.zoom_extents()
    win.view3d.click(*screen3d(win, (5, 5, 10)))
    assert win.ctx.selection == {solids(win)[0].handle}
    for style in ("W", "H", "S", "X", "E"):
        type_line(qtbot, win, "VSCURRENT")
        type_line(qtbot, win, style)
        qtbot.wait(5)
        win.view3d.repaint()
    assert win.view3d.style == "Shaded with edges"
    type_line(qtbot, win, "PLAN")
    qtbot.waitUntil(lambda: not win.in_3d)


def test_filletedge_by_clicking_edges_in_3d(qtbot, win):
    for t in ("BOX", "0,0", "20,20", "20"):
        type_line(qtbot, win, t)
    win.show_3d("SW Iso")
    type_line(qtbot, win, "FILLETEDGE")
    type_line(qtbot, win, "R")
    type_line(qtbot, win, "2")
    win.view3d.click(*screen3d(win, (10, 0, 20)))       # front top edge
    win.view3d.click(*screen3d(win, (0, 10, 20)))       # left top edge
    type_line(qtbot, win, "")
    (s,) = solids(win)
    assert len(S.faces(s.shape)) == 8


def test_point_on_solid_gives_elevation(qtbot, win):
    for t in ("BOX", "0,0", "20,20", "20"):
        type_line(qtbot, win, t)
    win.show_3d("SW Iso")
    type_line(qtbot, win, "CYLINDER")
    win.view3d.click(*screen3d(win, (10, 10, 20)))       # center on the top face
    type_line(qtbot, win, "3")
    type_line(qtbot, win, "5")
    cyl = [e for e in solids(win) if S.bbox3(e.shape)[2] > 19][0]
    assert S.bbox3(cyl.shape)[5] == pytest.approx(25)


def test_sketch_tab_and_extrude(qtbot, win):
    for t in ("BOX", "0,0", "20,20", "10"):
        type_line(qtbot, win, t)
    type_line(qtbot, win, "SKETCH")
    type_line(qtbot, win, "XZ")
    qtbot.waitUntil(lambda: win.controller.space.startswith("*Sketch:"))
    tabs = [win.layout_tabs.tabText(i) for i in range(win.layout_tabs.count())]
    assert "✎ Sketch1" in tabs
    for t in ("CIRCLE", "10,15", "3"):
        type_line(qtbot, win, t)
    type_line(qtbot, win, "EXITSKETCH")
    qtbot.waitUntil(lambda: win.controller.space == "*Model")
    win.show_3d("SW Iso")
    win.view3d.repaint()
    assert any(w.sketch == "Sketch1" for w in win.view3d.scene().wires)


def test_viewbase_switches_to_layout_and_keeps_running(qtbot, win):
    from cad.core.model import BlockReference
    for t in ("BOX", "0,0", "40,20", "10"):
        type_line(qtbot, win, t)
    type_line(qtbot, win, "VIEWBASE")
    qtbot.waitUntil(lambda: win.controller.space in win.doc.layouts)
    assert win.runner.is_active
    type_line(qtbot, win, "Front")
    type_line(qtbot, win, "1")
    x, y = win.controller.view.to_screen((120, 120))
    qtbot.mouseClick(win.canvas, Qt.MouseButton.LeftButton, pos=QPoint(round(x), round(y)))
    type_line(qtbot, win, "")
    refs = [e for e in win.doc.entities.values() if isinstance(e, BlockReference) and e.name.startswith("View")]
    assert len(refs) == 1 and abs(refs[0].insert[0] - 120) < 3
    win.repaint()
