"""PNG, JPEG and TIFF images of sheets (Qt offscreen rendering)."""
from __future__ import annotations

from ..base import Option, PluginError
from .sheet_common import SheetPlugin


class _RasterPlugin(SheetPlugin):
    qt_format = "PNG"
    supports_alpha = False

    def export_options(self, doc=None):
        opts = super().export_options(doc) + [
            Option("dpi", "Resolution (dots per inch)", "int", 150, minimum=10, maximum=2400,
                   help="150 is fine on screen; 300 for printing."),
        ]
        if self.supports_alpha:
            opts.append(Option("transparent", "Transparent background", "bool", False))
        return opts

    def write_sheets(self, sheets, path, o, report) -> None:
        from ...render.plot_qt import render_image
        sh = sheets[0]
        try:
            img = render_image(sh, o["dpi"], transparent=bool(o.get("transparent", False)))
        except ValueError as exc:
            raise PluginError(str(exc)) from exc
        if self.qt_format == "JPG":
            from PySide6.QtGui import QImage
            img = img.convertToFormat(QImage.Format.Format_RGB32)
        from PySide6.QtGui import QImageWriter
        w = QImageWriter(path, self.qt_format.encode())
        if self.qt_format == "JPG":
            w.setQuality(92)
        if self.qt_format == "TIFF":
            w.setCompression(1)                       # LZW: lossless and much smaller
        if not w.write(img):
            raise PluginError(f"Couldn't write {path}: {w.errorString()}")


class PngPlugin(_RasterPlugin):
    id = "png"
    name = "PNG image"
    extensions = (".png",)
    qt_format = "PNG"
    supports_alpha = True


class JpegPlugin(_RasterPlugin):
    id = "jpg"
    name = "JPEG image"
    extensions = (".jpg", ".jpeg")
    qt_format = "JPG"


class TiffPlugin(_RasterPlugin):
    id = "tiff"
    name = "TIFF image"
    extensions = (".tif", ".tiff")
    qt_format = "TIFF"


PLUGINS = [PngPlugin(), JpegPlugin(), TiffPlugin()]
