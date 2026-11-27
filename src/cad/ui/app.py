"""Application entry point: logging, crash handling, theme, startup options."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import traceback

from .. import APP_ID, APP_NAME, ORG_NAME, __version__


def _setup_logging() -> str:
    from .settings import log_dir
    path = str(log_dir() / "cad.log")
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return path


def _install_crash_handler(get_window, log_path: str) -> None:
    def hook(exc_type, exc, tb):
        logging.getLogger("crash").error("Unhandled error", exc_info=(exc_type, exc, tb))
        win = get_window()
        saved = False
        if win is not None:
            try:
                saved = win.autosave_now() or not win.doc.is_modified
            except Exception:                    # noqa: BLE001
                pass
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                win, "Something went wrong",
                f"An unexpected error occurred:\n\n{exc}\n\n"
                + ("Your drawing was autosaved and can be recovered from File > Recover.\n\n" if saved else "")
                + f"Details were written to:\n{log_path}")
        except Exception:                        # noqa: BLE001
            traceback.print_exception(exc_type, exc, tb)
    sys.excepthook = hook


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="CAD", description=APP_NAME)
    p.add_argument("file", nargs="?", help="drawing to open")
    p.add_argument("--renderer", choices=["auto", "gl", "painter"], help="display engine")
    p.add_argument("--smoke-test", action="store_true", help="start, draw, save, reopen and exit (for CI)")
    p.add_argument("--screenshot", metavar="PNG", help="draw a demo drawing, save a screenshot and exit")
    p.add_argument("--screenshot-3d", metavar="PNG", help="model a demo part, screenshot the 3D view and exit")
    p.add_argument("--report", metavar="TXT", help="write the smoke-test result to this file")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    from .settings import AppSettings
    settings = AppSettings()
    if args.renderer:
        os.environ["CAD_RENDERER"] = args.renderer
    elif "CAD_RENDERER" not in os.environ:
        os.environ["CAD_RENDERER"] = settings.renderer
    if settings.ui_scale != 1.0 and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = f"{settings.ui_scale:g}"

    from PySide6.QtCore import QCoreApplication, QTimer
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setOrganizationName(ORG_NAME)
    QCoreApplication.setApplicationName(APP_ID)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationDisplayName(APP_NAME)
    log_path = _setup_logging()
    logging.getLogger(__name__).info("Starting %s %s", APP_NAME, __version__)

    from . import theme
    theme.apply_theme(app, settings.dark_theme, settings.font_scale)
    from .main_window import MainWindow
    win = MainWindow(settings)
    _install_crash_handler(lambda: win, log_path)
    win.show()

    if args.smoke_test:
        from .smoke import run_smoke_test
        return run_smoke_test(app, win, args.report)
    if args.screenshot_3d:
        from .smoke import take_screenshot_3d
        return take_screenshot_3d(app, win, args.screenshot_3d)
    if args.screenshot:
        from .smoke import take_screenshot
        return take_screenshot(app, win, args.screenshot)

    if args.file:
        QTimer.singleShot(0, lambda: win.open_path(args.file))
    else:
        QTimer.singleShot(300, win.offer_recovery)
    return app.exec()
