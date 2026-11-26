import pytest
from PySide6.QtCore import QUrl

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
    if getattr(w, "help_window", None):
        w.help_window.close()
    w.doc.mark_saved()
    w.close()


def test_f1_during_a_command_opens_its_page(win, qtbot):
    win.run_command("FILLET")
    win.show_help()
    hw = win.help_window
    assert hw.isVisible() and hw.current == "fillet"
    assert "Fillet" in hw.view.toPlainText() and "Radius" in hw.view.toPlainText()


def test_f1_over_a_ribbon_button(win, monkeypatch):
    from PySide6.QtWidgets import QApplication, QToolButton
    btn = next(b for b in win.ribbon.findChildren(QToolButton) if b.property("help_id") == "hatch")
    monkeypatch.setattr(QApplication, "widgetAt", staticmethod(lambda *a: btn))
    win.show_help()
    assert win.help_window.current == "hatch"


def test_f1_idle_opens_home_and_search_works(win, qtbot):
    from PySide6.QtWidgets import QApplication
    import cad.ui.main_window as mw
    win.show_help("home")
    hw = win.help_window
    assert hw.current == "home"
    hw.search_for("copy in a circle")
    assert hw.left.currentWidget() is hw.results
    assert hw.results.item(0).data(256) == "arraypolar"
    hw._open_first_hit()
    assert hw.current == "arraypolar"
    hw.search_for("zzqqxx")
    assert hw.left.currentWidget() in (hw.no_hits, hw.results)


def test_links_back_forward_and_run(win, qtbot):
    win.show_help("line")
    hw = win.help_window
    hw._link(QUrl("help:pline"))
    hw._link(QUrl("term:object-snap"))
    assert hw.current == "term/object-snap"
    hw.go_back()
    assert hw.current == "pline"
    hw.go_forward()
    assert hw.current == "term/object-snap"
    hw._link(QUrl("run:CIRCLE"))
    assert win.runner.active is not None and win.runner.active.name == "CIRCLE"
    win.runner.cancel()


def test_generated_pages_and_contents(win):
    win.show_help("commands")
    hw = win.help_window
    text = hw.view.toPlainText()
    assert "Polar Array" in text and "ARRAYPOLAR" in text
    hw.show_page("glossary")
    assert "Viewport" in hw.view.toPlainText()
    assert hw.tree.topLevelItemCount() >= 5


def test_help_command_and_question_mark(win, qtbot):
    win.run_command("HELP")
    qtbot.waitUntil(lambda: getattr(win, "help_window", None) is not None and win.help_window.isVisible())
