# Writing an import/export plugin

Every file format the program reads or writes is a **plugin**: one Python file with a class that
says what the format can do, plus `export()` and/or `import_()`. The core program never names a
format; it asks the plugin registry.

* Built-in plugins: `src/cad/plugins/formats/` (DXF, DWG, PDF, SVG, PNG/JPG/TIFF, HP-GL/2, .cadz)
* Your own plugins: the `plugins` folder inside the data folder. Options > Options shows where that is
  (normally `%APPDATA%\CallingAllDumbies\plugins`, or `data\plugins` next to `CAD.exe` in the portable
  version). Every `.py` file there is loaded at startup. A plugin with the same `id` as a built-in one
  replaces it.

## A complete example: comma-separated points

Save this as `points_csv.py` in your plugins folder and restart. **Export** and **Import** now list
"Point list (CSV)".

```python
"""Point list: one 'x,y' per line, in millimeters. Exports every POINT, line end and circle center."""
import csv

from cad.core.model import Circle, Document, Line, Point
from cad.plugins import Capabilities, FormatPlugin, Option, PluginError


class PointsCsv(FormatPlugin):
    id = "points_csv"                 # unique, lower case
    name = "Point list (CSV)"         # shown in the Export/Import dialogs
    extensions = (".csv",)
    can_import = True
    can_export = True
    capabilities = frozenset({Capabilities.UNITS})   # what it keeps; everything else is a "loss"

    def export_options(self, doc=None):
        return [Option("header", "Write a header row", "bool", True),
                Option("decimals", "Decimal places", "int", 3, minimum=0, maximum=8)]

    def export(self, doc, path, options, report):
        o = self.checked_options("export", options, doc)       # fills defaults, validates
        rows = []
        for e in doc.entities.values():
            if isinstance(e, Point):
                rows.append(e.position)
            elif isinstance(e, Line):
                rows += [e.p1, e.p2]
            elif isinstance(e, Circle):
                rows.append(e.center)
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            if o["header"]:
                w.writerow(["x_mm", "y_mm"])
            for x, y in rows:
                w.writerow([round(x, o["decimals"]), round(y, o["decimals"])])
        report.count("point", len(rows))

    def import_(self, path, options, report):
        doc = Document()
        with doc.transaction("Import CSV"):
            with open(path, newline="") as fh:
                for row in csv.reader(fh):
                    try:
                        x, y = float(row[0]), float(row[1])
                    except (ValueError, IndexError):
                        report.skip("unreadable row")
                        continue
                    doc.add(Point(position=(x, y)))
                    report.count("point")
        if not doc.entities:
            raise PluginError("No points found. Each line should be x,y in millimeters.")
        doc.clear_history()
        doc.mark_saved()
        return doc


PLUGINS = [PointsCsv()]           # the registry loads every object in this list
```

## The contract

| Member | Meaning |
|---|---|
| `id`, `name`, `extensions` | Identity. The first extension is the default for new files |
| `can_import`, `can_export` | Which directions are offered |
| `capabilities` | Feature names from `Capabilities` the format keeps (layers, colors, linetypes, text, hatch, blocks, dimensions, paper_space, ...). Before exporting, the user sees the features their drawing uses that aren't in this set |
| `export_options(doc)` / `import_options()` | A list of `Option`s. The options dialog is generated from them. Kinds: `choice`, `bool`, `int`, `float`, `length`, `string`, `scale` |
| `available()` | Return `(False, "what to install")` when the format needs something missing (DWG uses this for the ODA File Converter) |
| `export(doc, path, options, report)` | Write the file. Units inside the program are always millimeters |
| `import_(path, options, report)` | Return a new `Document` |
| `losses(doc)` | Extra warnings beyond the automatic ones |

Raise `PluginError("plain sentence")` for anything the user should read: it's shown as-is. Any
other exception is shown as an unexpected error.

`report` collects what happened: `report.count(kind)`, `report.skip(kind)` for things that couldn't be
carried over, `report.warn(text)`, `report.info(text)`. It's shown after the import/export.

## Drawing on paper

Formats that print sheets (like PDF or an image format) can subclass `SheetPlugin` from
`cad.plugins.formats.sheet_common`. It provides the standard options (what to export, paper, scale,
colors, lineweights) and turns them into `Sheet`s: flat lists of `Stroke` (polyline in paper
millimeters, color, width) and `Fill` (polygons, color), with linetypes already turned into dashes
and viewports already clipped. Implement only `write_sheets(sheets, path, options, report)`. See
`hpgl.py` (about 60 lines) for a full example.

## Testing a plugin

```python
from cad.plugins import registry, Report
registry.load_folder("path/to/your/plugins")
p = registry.get("points_csv")
p.export(doc, "out.csv", {}, Report())
```

Built-in plugins have tests in `tests/plugins/` and third-party validation in `tests/validators/`.
