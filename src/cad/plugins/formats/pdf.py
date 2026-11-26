"""PDF: vector, true to scale, one page per sheet (Qt's PDF writer)."""
from __future__ import annotations

from ..base import PluginError
from .sheet_common import SheetPlugin

PDF_DPI = 1200


def write_pdf(sheets, path: str, title: str = "") -> None:
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

    from ...render.plot_qt import paint_sheet
    w = QPdfWriter(path)
    w.setResolution(PDF_DPI)
    w.setCreator("CAD: Calling All Dumbies")
    if title:
        w.setTitle(title)

    def page(sh):
        size = QPageSize(QSizeF(sh.width, sh.height), QPageSize.Unit.Millimeter, sh.name,
                         QPageSize.SizeMatchPolicy.ExactMatch)
        w.setPageLayout(QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0),
                                    QPageLayout.Unit.Millimeter))

    page(sheets[0])
    p = QPainter()
    if not p.begin(w):
        raise PluginError(f"Couldn't write {path} (is it open in another program?).")
    try:
        for i, sh in enumerate(sheets):
            if i:
                page(sh)
                w.newPage()
            px = PDF_DPI / 25.4
            paint_sheet(p, sh, QRectF(0, 0, sh.width * px, sh.height * px), min_width_px=0.05 * px)
    finally:
        p.end()


class PdfPlugin(SheetPlugin):
    id = "pdf"
    name = "PDF"
    extensions = (".pdf",)
    multi_page = True
    description = "Vector PDF at true scale; one page per sheet."

    def write_sheets(self, sheets, path, o, report) -> None:
        write_pdf(sheets, path, title=sheets[0].name if len(sheets) == 1 else "")


PLUGINS = [PdfPlugin()]
