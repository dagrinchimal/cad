# CAD: Calling All Dumbies

A friendly 2D/3D CAD program for Windows with AutoCAD-style commands, three unit systems
(millimeters, fractional inches, feet-inches), and a built-in help system.

**Status:** Phase 6 of 7 (2D drafting, file exchange, help and 3D done; installer next). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full plan.

## What works now

- **Drawing:** Line, Polyline (with arcs), Circle (4 ways), Arc (3 ways), Rectangle, Polygon, Ellipse and elliptical arc, Spline, Point, Hatch (click inside an area; finds islands; 15 patterns + solid), Boundary
- **Text:** single-line text with justification, multiline text that wraps in a box, using your system's TrueType fonts
- **Dimensions:** linear, aligned, angular, radius, diameter, ordinate, leaders; dimension styles (arrow type, sizes, overall scale); measured text always in the drawing's units, with overrides like `<> TYP`
- **Editing:** Move, Copy, Rotate, Scale, Mirror, Offset, Trim, Extend, Fillet, Chamfer, rectangular and polar arrays, Break, Break at Point, Join, Explode, Stretch, Erase; unlimited Undo/Redo; double-click text, notes, dimensions and blocks to edit them
- **Grips:** select objects, click a blue grip, click (or type) where it goes. Corners shared by selected objects move together
- **Trim/Extend several at once:** in Trim or Extend, click empty space and click again to draw a fence across objects (or choose Crossing for a box). Shift-click extends while trimming, and trims while extending
- **Click the number, type the size (Revit style):** select one object and its lengths, radius and attached dimensions show as blue numbers. Click one, type the value, press Enter. Between two objects, the one you selected moves
- **Associative:** dimensions, hatches and arrays follow the objects they belong to. Arrays stay live (edit the original, every copy updates; Explode for separate copies)
- **Organization:** layers (color, linetype, lineweight, on/off, freeze, lock), blocks with attributes (BLOCK, INSERT, ATTDEF), groups
- **Layouts:** paper-space sheets (ISO A4–A0, Letter to ARCH E) with an automatic border and title block whose fields you fill in, viewports at standard scales (1:50, 1/4" = 1'-0"…) or "scale to fit"
- **Parametric constraints:** coincident, collinear, concentric, fix, parallel, perpendicular, horizontal, vertical, tangent, symmetric, equal; driving dimensions (linear, aligned, radius, diameter, angle) with formulas like `d1*2`; edits keep constraints satisfied; over-constraining is detected
- **Units:** millimeters, fractional inches (1/2 to 1/64), architectural feet-inches. Type any format anywhere: `25.4mm`, `1 1/2"`, `3'-4 1/2"`, `3' 4.5`. In feet-inch drawings, Revit typing is on by default: `3 4-1/2` = 3'-4 1/2", `0 1.5` = 1 1/2", a plain `12` = 12 feet (switch to AutoCAD style, where a plain number is inches, in Units)
- **Precise input:** `x,y`, `@dx,dy`, `@distance<angle`, or a distance in the cursor direction
- **Snaps:** endpoint, midpoint, center, intersection, perpendicular, tangent, nearest, quadrant, node, extension, insertion; grid snap, ortho, polar tracking, object snap tracking
- **Files:** native `.cadz` (open, documented, versioned), autosave and crash recovery
- **AutoCAD files:** open and save DXF (R12 to 2018) directly; Ctrl+S on an opened DXF saves it back as DXF. Feet-inch drawings are written in inches, like AutoCAD. DWG works too once you install the free [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter) (it can't be bundled); the program finds it automatically, or set its location in Options
- **Export:** PDF (vector, true scale, one page per layout), SVG (one group per layer), PNG/JPG/TIFF at any resolution, HP-GL/2 for plotters and cutters, DXF, DWG. Before exporting you're told exactly what the format can't keep (e.g. "associativity"). **Batch Export** writes several formats in one go
- **Import:** DXF, DWG and SVG, either opened as a new drawing or added into the current one (IMPORT). A report lists anything that couldn't be brought in (images, SHX fonts replaced by Arial...)
- **Plot (Ctrl+P):** any printer or a PDF file; model (fit or at a scale like 1:50 or 1/4" = 1'-0") or layouts; color, black only or grayscale; live preview
- **Plugins:** every format is a plugin; drop your own `.py` into the plugins folder (see [docs/PLUGINS.md](docs/PLUGINS.md))
- **Interface:** ribbon (Home, Annotate, Parametric, 3D, Layout, Output, View) with icons and labels, command line that doubles as search, status bar, context menus, Properties panel for every object type, light/dark themes, adjustable UI size
- **Speed:** GPU rendering; tested with 50,000+ objects
- **3D solids (direct modeling):** sketches on the top/front/side planes, offset planes or a face of a solid, using every 2D tool and constraint; Extrude (with Join, Cut, Through all, Both sides, or click inside areas), Revolve, Sweep, Loft; Box, Cylinder, Cone, Sphere, Torus, Wedge; Union, Subtract, Intersect; Fillet and Chamfer edges, Shell, Slice, Press/Pull, 3D Move/Rotate; Mass Properties
- **3D view:** orbit, pan, zoom, view cube, standard and isometric views, perspective, five visual styles; click faces, edges and points on solids for any command
- **Easy 3D (Tinkercad/SketchUp style):** drag shapes from the Shapes panel, stretch them with handles or type sizes, grey hole shapes + Combine, Align; draw right on a face and push/pull it with a live preview; a toolbar shows the tools for what you clicked. Every action can still be typed
- **2D drawings from 3D:** front/top/side/iso views on a layout with hidden lines dashed (third-angle), updated after edits
- **3D files:** STEP (with colors and names) and IGES open and save; STL opens and saves; 3MF, glTF (.glb) and OBJ export

- **Help (F1):** a page for every command, guides (units, snaps, selecting, layouts, file formats, constraints, coming from AutoCAD), a glossary of 70+ CAD words, and three tutorials (a floor plan in feet-inches; a machined part in mm, taken from 2D to a 3D solid, shop drawings and STEP; a drag-and-drop 3D pencil holder with "Show me where" hints). Search in your own words with typo tolerance ("copy in a circle", "make a wall thicker"); F1 opens the page of the command you're in or the ribbon button under the mouse; ▶ Start buttons run the command

Not yet: the Windows installer and signed release (Phase 7).

## Keyboard basics

| Key | Does |
|---|---|
| Type anything | Goes to the command line (e.g. `L` Enter for Line) |
| Enter / Space | Finish the current step; repeat the last command when idle |
| Esc | Cancel the command, or clear the selection |
| Delete | Erase the selection |
| Ctrl+Z / Ctrl+Y | Undo / Redo |
| Mouse wheel | Zoom at the cursor |
| Middle button drag | Pan (double-click middle = zoom extents) |
| F3 / F7 / F8 / F9 / F10 / F11 | Object snap / Grid / Ortho / Snap / Polar / Object tracking |
| Ctrl+1 | Properties panel |

## Run from source

Requires Python 3.12+.

```bash
pip install -e ".[dev]"
python -m cad                     # or: cad
python -m cad --renderer painter  # force the software renderer
```

## Tests

```bash
pytest -m "not perf"     # unit + GUI tests (headless, software renderer)
pytest -m perf -s        # 50,000-entity benchmark with timings
```

`pytest tests/validators` re-reads our exports with LibreCAD, the ODA File Converter, qpdf, poppler,
librsvg and hp2xx (each test is skipped when its program isn't installed; CI installs them).

GUI tests on the OpenGL renderer (Linux): `QT_QPA_PLATFORM=xcb CAD_RENDERER=gl xvfb-run pytest tests/integration`.

## Build the Windows program

On Windows with Python 3.12:

```bat
pip install -e ".[dev]"
cd packaging
pyinstaller cad.spec --noconfirm --distpath ..\dist --workpath ..\build
..\dist\CAD\CAD.exe
```

Every push also builds it on GitHub Actions (Windows Server). Download **CAD-Portable-windows** from
the run's *Artifacts* section, unzip, and run `CAD\CAD.exe`. It runs from the folder with no admin rights;
the included `portable.flag` keeps settings and autosaves in a `data` folder next to it.

Windows SmartScreen will warn the first time because the program isn't code-signed:
choose **More info → Run anyway**.

## Where things are stored

Settings, autosaves and logs: `%LOCALAPPDATA%\CallingAllDumbies\` (or the `data` folder in portable mode).
Override with the `CAD_DATA_DIR` environment variable.

## License

GPL-3.0-or-later.
