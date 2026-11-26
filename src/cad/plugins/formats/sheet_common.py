"""Shared options and helpers for formats that draw sheets of paper (PDF, SVG, images, HPGL)."""
from __future__ import annotations

import os

from ...core.model import MODEL_SPACE, Document
from ...core.model.tables import PAPER_SIZES
from ...core.plot import PlotArea, PlotStyle, Sheet, plot_layout, plot_model
from ...core.units import UnitMode
from ...core.units.scales import parse_scale, standard_scales
from ..base import Capabilities as C, FormatPlugin, Option, PluginError

WHAT_MODEL = "model"
WHAT_LAYOUTS = "all_layouts"
WHAT_ALL = "everything"


def layout_names(doc: Document | None) -> list[str]:
    if doc is None:
        return []
    return [n for n, _ in sorted(doc.layouts.items(), key=lambda kv: kv[1].order)]


def default_paper(doc: Document | None) -> str:
    if doc is not None and doc.header.units.mode is not UnitMode.MM:
        return "Tabloid (11 x 17 in)"
    return "ISO A3"


class SheetPlugin(FormatPlugin):
    """Base for formats that draw sheets. Subclasses implement write_sheets()."""
    can_export = True
    capabilities = frozenset({C.COLORS, C.TRUE_COLORS, C.LINETYPES, C.LINEWEIGHTS, C.PAPER_SPACE, C.CURVES,
                              C.UNITS})
    multi_page = False            # True: all sheets in one file (PDF)

    def sheet_options(self, doc: Document | None) -> list[Option]:
        names = layout_names(doc)
        what = [(WHAT_MODEL, "Model (the drawing itself)")] + [(n, f"Layout: {n}") for n in names]
        if len(names) > 1:
            what.append((WHAT_LAYOUTS, "All layouts"))
        if names:
            what.append((WHAT_ALL, "Model and all layouts"))
        default_what = names[0] if names else WHAT_MODEL
        mode = doc.header.units.mode if doc is not None else UnitMode.MM
        scales = [("fit", "Fit to paper")] + [(s.name, s.name) for s in standard_scales(mode)]
        sep = "" if self.multi_page else " (several sheets make one file each)"
        return [
            Option("what", "What to export" + sep, "choice", default_what, tuple(what)),
            Option("paper", "Paper size (model only; layouts use their own)", "choice", default_paper(doc),
                   tuple(PAPER_SIZES)),
            Option("orientation", "Orientation (model only)", "choice", "landscape",
                   (("landscape", "Landscape"), ("portrait", "Portrait"))),
            Option("scale", "Scale (model only)", "scale", "fit", tuple(scales),
                   help="Fit to paper, or a scale like 1:50 or 1/4\" = 1'-0\". You can type your own."),
            Option("color_mode", "Colors", "choice", "color",
                   (("color", "As in the drawing (color 7 prints black)"), ("monochrome", "Black only"),
                    ("grayscale", "Shades of gray"))),
            Option("lineweights", "Use lineweights", "bool", True,
                   help="Off: every line prints at the default lineweight."),
        ]

    def export_options(self, doc: Document | None = None) -> list[Option]:
        return self.sheet_options(doc)

    def checked_options(self, which, values, doc=None):
        o = super().checked_options(which, values, doc)
        if which == "export" and "scale" in o and o["scale"] != "fit":
            try:
                parse_scale(str(o["scale"]))
            except Exception as exc:
                raise PluginError(f"Scale: {exc}") from exc
        return o

    def sheets(self, doc: Document, o: dict) -> list[Sheet]:
        style = PlotStyle(color_mode=o.get("color_mode", "color"), plot_lineweights=o.get("lineweights", True))
        names = layout_names(doc)
        what = o.get("what", WHAT_MODEL)
        if what == WHAT_MODEL:
            spaces = [MODEL_SPACE]
        elif what == WHAT_LAYOUTS:
            spaces = names
        elif what == WHAT_ALL:
            spaces = [MODEL_SPACE] + names
        elif what in names:
            spaces = [what]
        else:
            raise PluginError(f"There is no layout called {what!r}.")
        if not spaces:
            raise PluginError("This drawing has no layouts.")
        out = []
        for sp in spaces:
            if sp == MODEL_SPACE:
                w, h = PAPER_SIZES[o.get("paper", "ISO A3")]
                if o.get("orientation") == "portrait":
                    w, h = h, w
                sc = o.get("scale", "fit")
                scale = None if sc == "fit" else parse_scale(str(sc)).factor
                out.append(plot_model(doc, PlotArea(paper=(w, h), scale=scale, name="Model"), style))
            else:
                out.append(plot_layout(doc, sp, style))
        return out

    def export(self, doc: Document, path: str, options: dict, report) -> None:
        o = self.checked_options("export", options, doc)
        from ...render.text_qt import ensure_qt_text_engine
        ensure_qt_text_engine()
        sheets = self.sheets(doc, o)
        if self.multi_page or len(sheets) == 1:
            self.write_sheets(sheets, path, o, report)
            report.info(f"{len(sheets)} sheet{'s' if len(sheets) > 1 else ''} written to {os.path.basename(path)}.")
        else:
            stem, ext = os.path.splitext(path)
            for sh in sheets:
                p = f"{stem}-{safe_name(sh.name)}{ext}"
                self.write_sheets([sh], p, o, report)
                report.info(f"Wrote {os.path.basename(p)}.")
        report.count("sheet", len(sheets))

    def write_sheets(self, sheets: list[Sheet], path: str, o: dict, report) -> None:
        raise NotImplementedError


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "sheet"
