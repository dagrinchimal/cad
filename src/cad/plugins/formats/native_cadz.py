"""The program's own format (.cadz). Listed so Open/Save As show it with the others."""
from __future__ import annotations

from ...core.model import Document
from ...io import native
from ..base import Capabilities, FormatPlugin, PluginError, Report


class CadzPlugin(FormatPlugin):
    id = "cadz"
    name = "CAD: Calling All Dumbies drawing"
    extensions = (".cadz",)
    can_import = True
    can_export = True
    capabilities = Capabilities.ALL
    description = "Keeps everything: constraints, associativity, live arrays, layouts."

    def export(self, doc: Document, path: str, options: dict, report: Report) -> None:
        native.save(doc, path)

    def import_(self, path: str, options: dict, report: Report) -> Document:
        try:
            doc, warnings = native.load(path)
        except native.FileFormatError as exc:
            raise PluginError(str(exc)) from exc
        for w in warnings:
            report.warn(w)
        return doc


PLUGINS = [CadzPlugin()]
