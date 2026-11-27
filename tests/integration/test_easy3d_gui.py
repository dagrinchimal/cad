"""Phase 6b: building in the 3D view by clicking and dragging."""
import math

import numpy as np
import pytest
from PySide6.QtCore import Qt

pytest.importorskip("OCP")

from cad.core import solids as S
from cad.core.model import Polyline, Solid
from cad.render import viewcube
from cad.ui.main_window import MainWindow
from cad.ui.settings import AppSettings


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("CAD_DATA_DIR", str(tmp_path / "data"))
    w = MainWindow(AppSettings())
    w.resize(1300, 850)
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


def scr(win, xyz):
    v = win.view3d
    v.cam.width, v.cam.height = v.width(), v.height()
    (p,), _ = v.cam.project(np.array([xyz], float))
    return float(p[0]), float(p[1])


def box(qtbot, win, x1=40, y1=30, h=10):
    for t in ("BOX", "0,0", f"{x1},{y1}", str(h)):
        type_line(qtbot, win, t)
    win.show_3d("SE Iso")
    win.view3d.zoom_extents()
    qtbot.wait(10)


def test_draw_rectangle_on_top_face_then_push_it_in(qtbot, win):
    box(qtbot, win)
    v = win.view3d
    type_line(qtbot, win, "RECTANG")
    v.click(*scr(win, (10, 10, 10)))
    assert v.workplane is not None and v.workplane[0] == "*Sketch:Face1"
    v.click(*scr(win, (20, 20, 10)))
    assert v.workplane is None and win.ctx.space == "*Model"          # back to the model when done
    rect = next(e for e in win.doc.entities.values() if isinstance(e, Polyline) and e.space == "*Sketch:Face1")
    sk = win.doc.sketches["Face1"]
    assert sk.origin[2] == pytest.approx(10)
    xs = sorted(x for x, _y, _b in rect.vertices)
    assert xs[0] == pytest.approx(10, abs=0.6) and xs[-1] == pytest.approx(20, abs=0.6)   # local = model x
    # Push/Pull: click inside the rectangle, type the depth
    type_line(qtbot, win, "PRESSPULL")
    v.click(*scr(win, (15, 15, 10)))
    type_line(qtbot, win, "-3")
    (s,) = solids(win)
    w = abs(xs[-1] - xs[0])
    ys = sorted(y for _x, y, _b in rect.vertices)
    hgt = abs(ys[-1] - ys[0])
    assert S.mass_properties(s.shape)["volume"] == pytest.approx(40 * 30 * 10 - w * hgt * 3, rel=1e-6)


def test_drag_presspull_with_live_preview(qtbot, win):
    box(qtbot, win)
    v = win.view3d
    type_line(qtbot, win, "PRESSPULL")
    v.click(*scr(win, (20, 15, 10)))                    # the top face
    req = win.runner.request
    assert req.drag_axis is not None
    v.move_to(*scr(win, (20, 15, 15)))                   # 5 up along the face normal
    v._update_preview_shape()
    assert v.drag_value == pytest.approx(5, abs=1.0)
    assert v.preview_item is not None
    v.repaint()
    v.click(*scr(win, (20, 15, 15)))
    (s,) = solids(win)
    top = S.bbox3(s.shape)[5]
    assert top == pytest.approx(10 + v.drag_value if v.drag_value else 15, abs=1e-6) or top > 13


def test_handles_stretch_lift_and_move(qtbot, win):
    box(qtbot, win)
    v = win.view3d
    (s,) = solids(win)
    v.click(*scr(win, (20, 15, 10)))                     # select it
    assert win.ctx.selection == {s.handle}
    assert v.bar.isVisible()                            # context tools popped up
    names = {n for n, _xyz, _a in v._handles()}
    assert {"+x", "-x", "+y", "-y", "+z", "lift"} <= names
    # stretch +x by about 10
    hx = next(xyz for n, xyz, _a in v._handles() if n == "+x")
    v.press(*scr(win, hx))
    v.move_to(*scr(win, (hx[0] + 5, hx[1], hx[2])))
    v.move_to(*scr(win, (hx[0] + 10, hx[1], hx[2])))
    v.release(*scr(win, (hx[0] + 10, hx[1], hx[2])))
    b = S.bbox3(win.doc.get(s.handle).shape)
    assert b[0] == pytest.approx(0, abs=1e-6) and b[3] == pytest.approx(50, abs=1.5)
    # type an exact height through the size label
    v._edit_label("z")
    v.editor.setText("25")
    v.editor.on_done("25")
    b = S.bbox3(win.doc.get(s.handle).shape)
    assert b[5] - b[2] == pytest.approx(25)
    # lift it 5
    v._edit_label("elev")
    v.editor.on_done("5")
    assert S.bbox3(win.doc.get(s.handle).shape)[2] == pytest.approx(5)
    # drag the body sideways
    b = S.bbox3(win.doc.get(s.handle).shape)
    c = (b[0] + 6, b[1] + 6, b[5])            # on the top, away from the handles
    v.press(*scr(win, c))
    v.move_to(*scr(win, (c[0] + 4, c[1], c[2])))
    v.move_to(*scr(win, (c[0] + 8, c[1], c[2])))
    v.release(*scr(win, (c[0] + 8, c[1], c[2])))
    b2 = S.bbox3(win.doc.get(s.handle).shape)
    assert b2[0] > b[0] + 4
    win.runner.run("UNDO")
    assert S.bbox3(win.doc.get(s.handle).shape)[0] == pytest.approx(b[0])


def test_view_cube(qtbot, win):
    box(qtbot, win)
    v = win.view3d
    top = next(f for f in viewcube.visible_faces(v.cam, v.width()) if f[1] == "Top")
    c = top[2].mean(axis=0)
    v.press(*c)
    v.release(*c)
    assert v.view_name() == "Top"
    hx, hy, _r = viewcube.home_button(v.width())
    v.press(hx, hy)
    v.release(hx, hy)
    assert v.view_name() == "SW Iso"


def test_context_toolbar_runs_presspull_on_that_face(qtbot, win):
    box(qtbot, win)
    v = win.view3d
    v.click(*scr(win, (20, 15, 10)))
    btn = v.bar.buttons["presspull"]
    btn.click()
    qtbot.wait(5)
    assert win.runner.is_active and win.runner.active.name == "PRESSPULL"
    assert win.runner.request.drag_axis is not None      # the face was already picked
    type_line(qtbot, win, "5")
    assert S.bbox3(solids(win)[0].shape)[5] == pytest.approx(15)


def test_drop_shapes_hole_and_combine(qtbot, win):
    box(qtbot, win)
    (plate,) = solids(win)
    win.drop_shape("Cylinder", True, (20.0, 15.0, 0.0))
    hole = next(e for e in solids(win) if e.hole)
    assert win.ctx.selection == {hole.handle}
    win.ctx.selection.add(plate.handle)
    win.view3d.repaint()                                 # holes draw see-through
    type_line(qtbot, win, "COMBINE")
    (s,) = solids(win)
    r = 10                                               # 20 mm default cylinder, radius 10, through 20 tall
    assert S.mass_properties(s.shape)["volume"] == pytest.approx(40 * 30 * 10 - math.pi * r * r * 10, rel=1e-6)


def test_shapes_panel_click_then_click_to_place(qtbot, win):
    win.show_3d("SE Iso")
    assert win.shapes_dock.isVisible()
    b = next(b for b in win.shapes_panel.buttons if b.kind == "Sphere" and not b.hole)
    b.click()
    assert win.runner.active.name == "DROPSHAPE"
    win.view3d.zoom_extents()
    win.view3d.click(*scr(win, (0, 0, 0)))
    s = solids(win)
    assert len(s) == 1 and s[0].name == "Sphere"


def test_hints_show_in_both_views(qtbot, win):
    win.set_hints([[(0, 0, 0), (100, 0, 0), (100, 60, 0), (0, 60, 0), (0, 0, 0)]])
    assert win.view3d.hints and win.controller.hints
    win.show_3d("SE Iso")
    win.view3d.repaint()
    win.set_hints([])
    assert not win.view3d.hints
