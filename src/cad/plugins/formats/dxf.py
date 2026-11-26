"""AutoCAD DXF, versions R12 to 2018 (ezdxf)."""
from __future__ import annotations

from ...core.model import Document
from ..base import Capabilities as C, FormatPlugin, Option, PluginError, Report
from .dxf_export import VERSIONS, write_dxf
from .dxf_import import read_dxf

VERSION_LABELS = {"R2018": "AutoCAD 2018 (newest)", "R2013": "AutoCAD 2013", "R2010": "AutoCAD 2010",
                  "R2007": "AutoCAD 2007", "R2004": "AutoCAD 2004", "R2000": "AutoCAD 2000",
                  "R12": "AutoCAD R12 (oldest; no layouts, splines become lines)"}
UNIT_CHOICES = (("auto", "Automatic (inches for feet-inch and inch drawings, otherwise mm)"),
                ("mm", "Millimeters"), ("inches", "Inches"))


class DxfPlugin(FormatPlugin):
    id = "dxf"
    name = "AutoCAD DXF"
    extensions = (".dxf",)
    can_import = True
    can_export = True
    capabilities = frozenset({C.LAYERS, C.COLORS, C.TRUE_COLORS, C.LINETYPES, C.LINEWEIGHTS, C.UNITS, C.PAPER_SPACE,
                              C.TEXT, C.HATCH, C.BLOCKS, C.ATTRIBUTES, C.DIMENSIONS, C.GROUPS, C.CURVES})
    description = "Drawing exchange format read by AutoCAD and almost every other CAD program."

    def export_options(self, doc: Document | None = None) -> list[Option]:
        return [
            Option("version", "DXF version", "choice", "R2018", tuple(VERSION_LABELS.items()),
                   help="Use an older version only if the program you're sending to is old."),
            Option("units", "Units in the file", "choice", "auto", UNIT_CHOICES,
                   help="AutoCAD users working in feet and inches expect inches."),
        ]

    def import_options(self) -> list[Option]:
        return [
            Option("units", "Units in the file", "choice", "auto",
                   (("auto", "Automatic (from the file)"), ("mm", "Millimeters"), ("cm", "Centimeters"),
                    ("m", "Meters"), ("inches", "Inches"), ("feet", "Feet")),
                   help="Only change this if the drawing comes in at the wrong size."),
            Option("layouts", "Import layouts (sheets)", "bool", True),
        ]

    def export(self, doc: Document, path: str, options: dict, report: Report) -> None:
        o = self.checked_options("export", options, doc)
        if o["version"] == "R12":
            from ..base import describe_losses
            r12_caps = self.capabilities - {C.PAPER_SPACE, C.HATCH, C.TRUE_COLORS, C.LINEWEIGHTS, C.GROUPS}
            for w in describe_losses(doc, r12_caps):
                if w not in report.warnings:
                    report.warn(f"R12 can't keep {w}.")
        write_dxf(doc, path, o["version"], o["units"], report)

    def import_(self, path: str, options: dict, report: Report) -> Document:
        o = self.checked_options("import", options)
        try:
            return read_dxf(path, report, o["units"], o["layouts"])
        except PluginError:
            raise
        except Exception as exc:
            raise PluginError(f"Couldn't read this DXF file: {exc}") from exc


assert set(VERSION_LABELS) == set(VERSIONS)
PLUGINS = [DxfPlugin()]
