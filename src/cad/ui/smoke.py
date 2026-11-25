"""Self-tests the packaged program can run (used by CI on Windows and for screenshots)."""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from ..core.model import Layer
from ..io import native


def _pump(app: QApplication, ms: int = 50) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def demo_drawing(win) -> None:
    """A small floor plan in feet-inches with a few circles and arcs."""
    r = win.runner
    doc = win.doc
    with doc.transaction("Demo layers"):
        doc.add_layer(Layer("Walls", color=7, lineweight=0.5))
        doc.add_layer(Layer("Doors", color=3))
        doc.add_layer(Layer("Center", color=1, linetype="CENTER"))
        doc.add_layer(Layer("Furniture", color=4))
    win._set_units(doc.header.units.with_mode(__import__("cad.core.units", fromlist=["UnitMode"]).UnitMode.ARCHITECTURAL))

    def cmd(*parts):
        r.run(parts[0])
        for p in parts[1:]:
            if p == "":
                r.submit_enter()
            else:
                r.submit_text(p)
        if r.is_active:
            r.cancel()

    def layer(name):
        with doc.transaction("layer"):
            doc.set_current_layer(name)

    layer("Walls")
    cmd("PLINE", "0,0", "@24',0", "@0,16'", "@-24',0", "C")
    cmd("LINE", "12',0", "12',10'", "")
    cmd("LINE", "0,10'", "8',10'", "")
    layer("Doors")
    cmd("ARC", "C", "12',10'", "15',10'", "12',13'")
    cmd("LINE", "12',10'", "12',13'", "")
    layer("Furniture")
    cmd("CIRCLE", "6',5'", "2'")
    cmd("CIRCLE", "18',12'", "D", "3'-6\"")
    cmd("PLINE", "15',2'", "@6',0", "A", "@0,3'", "L", "@-6',0", "C")
    layer("Center")
    cmd("LINE", "-1',8'", "25',8'", "")
    layer("0")
    cmd("POINT", "20',4'", "")


def run_smoke_test(app: QApplication, win, report: str | None = None) -> int:
    def out(msg: str) -> None:
        print(msg)
        if report:
            with open(report, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
    try:
        _pump(app, 200)
        demo_drawing(win)
        _pump(app, 100)
        n = len(win.doc)
        assert n >= 10, f"expected entities, got {n}"
        win.controller.zoom_extents()
        win.runner.run("UNDO")
        win.runner.run("REDO")
        assert len(win.doc) == n
        path = os.path.join(tempfile.mkdtemp(), "smoke.cadz")
        assert win._save_to(path)
        doc, warnings = native.load(path)
        assert len(doc) == n and not warnings
        win.set_document(doc)
        _pump(app, 100)
        img = win.grab()
        assert not img.isNull()
        out(f"SMOKE TEST OK: {n} entities, renderer={win.canvas.backend_name} ({win.canvas.gl_info})")
        win.doc.mark_saved()
        win.close()
        return 0
    except Exception as exc:                  # noqa: BLE001
        import traceback
        out(traceback.format_exc())
        out(f"SMOKE TEST FAILED: {exc}")
        return 1


def grab_window(win):
    """Window screenshot including the canvas overlay (QWidget.grab skips it for OpenGL widgets)."""
    from PySide6.QtGui import QPainter
    pm = win.grab()
    img = win.canvas.grab_image()
    pos = win.canvas.mapTo(win, win.canvas.rect().topLeft())
    p = QPainter(pm)
    p.drawImage(pos, img)
    p.end()
    return pm


def take_screenshot(app: QApplication, win, path: str) -> int:
    win.resize(1500, 920)
    _pump(app, 300)
    demo_drawing(win)
    win.controller.zoom_extents()
    _pump(app, 200)
    # select the door arc, then start a LINE and hover near a wall corner to show a snap marker
    arc = next(e for e in win.doc.entities.values() if e.TYPE == "arc")
    win.ctx.selection.add(arc.handle)
    win.controller._selection_updated()
    win.runner.run("LINE")
    win.runner.submit_text("12',0")
    corner = win.controller.view.to_screen((24 * 304.8, 0.0))
    win.controller.cursor_screen = (corner[0] - 4, corner[1] - 3)
    win.controller._recompute_at_cursor()
    win.canvas.update()
    _pump(app, 300)
    grab_window(win).save(path)
    win.runner.cancel()
    win.doc.mark_saved()
    print(f"Screenshot saved: {path}")
    win.close()
    return 0
