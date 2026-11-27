# Architecture Plan — Phase 1

Status: **Approved**. Phases 1–3 complete.

App name: **CAD: Calling All Dumbies** (Python package `cad`, executable `CAD.exe`, file extension `.cadz`).

---

## 1. Decisions locked in

| Topic | Decision |
|---|---|
| Scope | Full 2D drafting + direct 3D solid modeling (extrude, revolve, sweep, loft, booleans, fillet/chamfer, shell, sections). No feature-history tree. |
| Constraints | AutoCAD-style parametric constraints (geometric + dimensional) in 2D drawings and in 3D sketch profiles |
| Target users | AutoCAD users: AutoCAD command names, aliases (L, C, TR, CO…), Enter/Space repeats the last command, Esc cancels |
| Platform | Windows 10/11 x64. Developed and tested on Linux, built and tested on Windows by GitHub Actions |
| Remote/VM support | Not required (no software-rendering fallback mandated) |
| Language | English only; UI strings kept in one place anyway |
| License | GPL-3.0 |
| Install size | 300–400 MB on disk is acceptable |
| DWG | Through the free ODA File Converter, installed by the user. DXF always works out of the box |

---

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Your recommendation; every dependency below has Windows 3.12 wheels (verified) |
| UI | PySide6 (Qt 6) | Mature, LGPL, native-looking, high-DPI aware |
| Viewport rendering | OpenGL 3.3 core via `QOpenGLWidget` + `moderngl` | Needed for 50,000+ entities at smooth frame rates on integrated graphics. Every Intel HD 4000-or-newer GPU supports GL 3.3 on Windows |
| 3D kernel | **OCP** (`cadquery-ocp-novtk`, OpenCascade 7.9) | **Change from pythonocc-core.** Same OpenCascade kernel, but it ships pip wheels instead of conda-only packages, which makes PyInstaller packaging far simpler. Verified here: STEP, IGES, STL, glTF writers, fillets, offsets, hidden-line removal all present |
| DXF | ezdxf | Reads/writes R12–R2018, includes audit/recover |
| 2D math | numpy (+ OCCT `Geom2dAPI` for spline/ellipse intersections and offsets) | Lines/arcs/circles use exact analytic code; hard curve cases go to the kernel |
| Constraint solver | **Written in-house** (numpy, Levenberg–Marquardt + rank analysis) | The GPL SolveSpace binding has no Windows/Python 3.12 wheel (verified). An in-house solver also gives us AutoCAD-style "fully constrained / over-constrained" feedback |
| Spatial index | `rtree` | Picking, snapping and window selection in O(log n) |
| Triangulation | `mapbox_earcut` | Hatch fills, text glyphs, solid fills |
| Fuzzy search | `rapidfuzz` | Command line search and help search |
| SVG import | `svgelements` | Robust path/transform parsing |
| Packaging | PyInstaller (`--onedir`) + Inno Setup | One-dir avoids the antivirus false positives common with one-file builds |
| Tests | pytest, pytest-qt (offscreen) | Headless on Linux and Windows CI |

Alternatives considered and rejected:
- **QGraphicsScene** for the canvas: easy, but too slow at 50k items and can't do AutoCAD-style linetypes/lineweights cheaply.
- **VTK** for display: adds ~150 MB and a second scene graph; we only need to draw triangles and lines.
- **C++/Qt**: faster, but would multiply development time several-fold. Python stays viable as long as hot paths are batched in numpy and rendering is on the GPU (see §6).

---

## 3. Repository layout

```
cad/
├─ pyproject.toml              dependencies, tool config
├─ src/cad/
│  ├─ core/                    NO Qt imports (enforced by a test)
│  │  ├─ units/                parser, formatter, unit modes, drawing scales
│  │  ├─ geom2d/               vectors, line/arc/circle/ellipse/spline math, intersections, offset, fillet
│  │  ├─ geom3d/               thin wrappers over OCP (solids, sketches → profiles)
│  │  ├─ model/                Document, entities, layers, linetypes, blocks, groups, layouts
│  │  ├─ constraints/          constraint types + solver
│  │  ├─ spatial.py            rtree wrapper
│  │  └─ transactions.py       undo/redo
│  ├─ commands/                command framework + one module per command
│  ├─ render/                  GL renderer, tessellation, linetype/lineweight shaders, overlays
│  ├─ ui/                      main window, ribbon, command line, status bar, properties, themes, dialogs
│  ├─ io/                      native format, plugin API, plugin registry, batch export
│  ├─ plugins/formats/         dxf.py, dwg_oda.py, pdf.py, svg.py, raster.py, hpgl.py, step.py, iges.py, stl.py, obj.py, threemf.py, gltf.py
│  └─ help/                    help loader, search index, viewer
├─ help_content/               Markdown: commands/, glossary/, tutorials/, synonyms.json
├─ tests/                      unit/, integration/, validation/, perf/
├─ packaging/                  PyInstaller spec, Inno Setup script, portable-zip script
├─ .github/workflows/          ci.yml (Linux + Windows), release.yml
└─ docs/                       ARCHITECTURE.md, FILE_FORMAT.md, PLUGINS.md, DEVELOPER_GUIDE.md
```

Dependency direction is one-way: `ui → commands → core`, `render → core`, `io/plugins → core`. `core` never imports anything above it, so the geometry and units logic is fully testable without a display.

---

## 4. Data model

### 4.1 Units and precision
- **Base unit: millimetre, stored as 64-bit float.** 1 in = 25.4 mm exactly, so every inch fraction down to 1/64" is represented to ~1e-13 mm.
- Each document has a **unit mode** (`MM`, `FRACTIONAL_IN`, `ARCHITECTURAL`) plus precision settings. These affect display and default input only.
- **Parser** (`core/units/parser.py`) accepts any of these in any mode:
  `25.4mm`, `2.54cm`, `1in`, `1"`, `40"`, `1 1/2`, `1-1/2"`, `3'`, `3'-4 1/2"`, `3' 4.5`, `3'4"`, `.5`, `-3/8`.
  A bare number uses the drawing's input unit (mm in MM mode, inches in both inch modes, as in AutoCAD).
- **Formatter** rounds with carry (e.g. 11.999" at 1/16 precision becomes `1'-0"`, not `11 16/16"`), reduces fractions, and handles negatives.
- **Drawing scales** are a ratio of paper length to model length: `1:1`, `1:50`, `1/4" = 1'-0"` (1:48), `1/8" = 1'-0"` (1:96), plus custom.
- **Exports** write in the drawing's display unit family (an inch drawing exports DXF with `$INSUNITS = inches`), converting from mm at write time.

### 4.2 Document
```
Document
├─ header: format version, unit mode, precision, limits, variables (snap, grid, ortho…)
├─ layers: Layer(name, color, linetype, lineweight, on, frozen, locked, plot)
├─ linetypes, text styles, dimension styles, hatch patterns
├─ blocks: BlockDefinition(name, base point, entities)   ← model space is a special block
├─ layouts: Layout(paper size, plot scale, viewports, title block)
├─ groups
├─ constraints: list of Constraint(type, entity refs, value)
└─ solids: 3D bodies (OCP TopoDS_Shape) + their layer/color
```

### 4.3 Entities
- Every entity has a stable **handle** (64-bit integer, never reused), layer, color (ByLayer/ByBlock/index/RGB), linetype, lineweight, and a geometry payload.
- Types: Point, Line, Polyline (with bulges), Circle, Arc, Ellipse, Spline, Text, MText, Hatch, Dimension (linear, aligned, angular, radial, diameter, ordinate), Leader, BlockReference (with attributes), Viewport, Solid3D, Sketch3D.
- Entities are plain Python dataclasses with slots. Geometry is immutable: an edit replaces the value, which keeps undo simple and safe.

### 4.4 Undo/redo
- Every command runs inside a **transaction**. A transaction records `(handle, before, after)` for each changed entity, plus table changes.
- Undo reverses the list; redo replays it. History is unlimited, bounded only by memory (only changed entities are stored, not whole drawing snapshots).

---

## 5. Commands and interaction

- Commands are **generators** that yield requests to the UI and receive answers. This maps directly onto AutoCAD's prompt flow:
  ```python
  def line(ctx):
      p1 = yield GetPoint("Specify first point")
      while True:
          p2 = yield GetPoint("Specify next point", base=p1, options=["Undo", "Close"])
          ...
  ```
  The same command works from the ribbon, the command line, a script, or a test, with no UI code inside it.
- **Command registry**: name, aliases, description, shortcut, ribbon tab, icon, help id. The ribbon, command-line search, tooltips and F1 help all read from it, so nothing can fall out of sync.
- **Command line** = input + search. It fuzzy-matches names, aliases and help synonyms (`circ` → Circle; `copy in a circle` → Polar Array).
- **Point input** accepts: mouse with snaps, `x,y`, `@dx,dy`, `@dist<angle`, a bare distance along the rubber-band direction, and `x,y,z` in 3D. All distances go through the unit parser.
- **Snaps**: endpoint, midpoint, center, intersection, perpendicular, tangent, nearest, quadrant, node, extension. Candidates come from the spatial index near the cursor and are ranked by type priority and distance. Markers are drawn in the overlay layer in AutoCAD's shapes, with a tooltip naming the snap. Polar tracking and object snap tracking draw dotted alignment paths.
- **Context menus** are built from the selection: entity types present, whether they're blocks, dimensions, etc.

---

## 6. Rendering (meeting 50,000+ entities smoothly)

- All geometry is tessellated in model coordinates into **per-layer GPU buffers**. Pan and zoom only change a matrix, so they cost nothing regardless of entity count.
- Tessellation is done in batches with numpy and cached per entity. An edit re-tessellates only the changed entities and patches the buffer.
- **Linetypes** are drawn in the fragment shader using distance along the polyline, so dashes stay correct at any zoom without extra geometry.
- **Lineweights** are expanded to quads in the vertex/geometry stage (core-profile GL has no thick lines).
- **Text** uses glyph outlines from Qt fonts, triangulated once per glyph and cached. TrueType fonts only; AutoCAD SHX fonts are substituted (see risks).
- **Overlays** (snap markers, grips, rubber band, selection window, tracking lines) are drawn with QPainter on top of the GL scene.
- **3D view** uses the same pipeline: OCP `BRepMesh` triangulates solids, and edges are drawn as lines. Shaded, wireframe and hidden-line modes.
- **Performance tests** in CI generate 50k and 100k-entity drawings and fail the build if open, regen or redraw times regress beyond set limits.

---

## 7. Constraints

- Geometric: coincident, collinear, concentric, fix, parallel, perpendicular, horizontal, vertical, tangent, smooth (G2), symmetric, equal.
- Dimensional: linear, horizontal, vertical, aligned, radial, diameter, angular, and simple expressions between them (`d2 = d1/2`).
- Solver: each constraint becomes residual equations; Levenberg–Marquardt solves them, starting from current geometry so it moves the minimum amount. Jacobian rank analysis reports degrees of freedom left, and which constraints conflict, so the UI can show "fully constrained" or highlight the conflict.
- The same solver drives 3D sketch profiles, which are 2D sketches on a plane.

---

### 7a. Associativity and direct value editing

- `core/points.py` names every grippable point (`p1`, `v3`, `center`, …). Grips, dimension
  references and the constraint solver all use these names.
- Dimensions store `refs` (which object point each measured point comes from), hatches store
  `sources` and the clicked `seed`, and `ArrayEntity` stores its `sources` plus the array rule
  (copies are computed, never stored).
- `core/associative.py` runs as the last pre-commit hook of every transaction: anything attached to
  a changed object is rebuilt in the same undo step. If a rebuild is impossible (boundary opened,
  object erased) the item keeps its last shape and drops the link.
- `core/dimedit.py` lists the values shown when one object is selected (temporary lengths/radii plus
  attached dimensions) and applies a typed value by moving geometry; the associativity hook then
  updates everything else.

## 8. 3D modeling (direct, no history)

- **Kernel**: `core/solids.py` wraps OpenCascade (OCP 7.9 / 8.0): profile wires from 2D entities,
  extrude/revolve/sweep/loft, primitives, booleans, fillet/chamfer, shell, slice, press/pull,
  transforms, mass properties, meshing for display, hidden-line views, ray picking.
- **Solid entity**: holds a `TopoDS_Shape` (immutable by convention; edits make a new shape). Always in
  model space. In the plan it draws as its edges seen from above; snaps use its vertices.
- **Sketches** are spaces (`"*Sketch:<name>"`) with a plane, so every 2D tool, snap, grip and constraint
  works on them unchanged. Reference lines (hidden-line projection of the solids) are added on a
  locked, non-plotting layer.
- **3D view** (`ui/view3d.py`): a camera (`render/camera3d.py`), a cached scene (`render/scene3d.py`) and
  two renderers (`render/raster3d.py`): offscreen moderngl with a depth buffer, or QPainter with depth
  sorting and ray-tested edge visibility when there's no OpenGL. Clicks become rays:
  `CommandRunner.submit_ray()` answers GetFace/GetEdge/GetPoint (with elevation in `ctx.point_z`).
  In the plan, face/edge picks cast a ray straight down.
- **Easy 3D (Phase 6b)**, all in `ui/view3d.py` on top of the same commands:
  drawing commands started in the 3D view draw on the face clicked first (a sketch is made for it with
  `aligned_face_plane`, so on a horizontal face typed x,y are the model's x,y) or on the ground;
  `GetDistance(drag_axis, preview3d)` lets distances follow the mouse with a live preview shape;
  `GetFace(allow_region)` answers a `RegionPick` for clicks inside closed shapes on the ground or a
  sketch (SketchUp-style push/pull); a selected solid shows handles (non-uniform `solids.scaled`,
  lift, body drag); the view cube is `render/viewcube.py`; the context toolbar passes the clicked
  face/edge to commands through `ctx.pending_picks`; `Solid.hole` marks Tinkercad-style hole shapes that
  COMBINE subtracts (exports, drawing views and Join/Cut ignore them); the Shapes panel drags a MIME
  payload that becomes DROPSHAPE. Tutorial `<hint …>` lines become "Show me where" ghost outlines.
- **2D from 3D**: VIEWBASE makes blocks of hidden-line projections (third-angle), inserted on layouts at
  the view scale, regenerated by VIEWUPDATE.

---

## 9. Native file format (`.cadz`)

- A **ZIP container**, readable with any unzip tool:
  - `manifest.json` — format name, **format version** (semver), app version, created/modified
  - `document.json` — header, tables, entities, constraints, layouts
  - `solids/<handle>.brep` — OpenCascade BREP for each 3D body
  - `thumbnail.png`
- **Backward compatibility**: every version bump ships a migration function `migrate_N_to_N+1`. Opening an old file runs the chain. Old test files are kept in `tests/data/format_versions/` and opened on every CI run.
- **Forward safety**: unknown keys are preserved on save, so an older app version doesn't silently destroy data from a newer one.
- Full spec: `docs/FILE_FORMAT.md` (written in Phase 2).

**Autosave & crash recovery**: autosave every N minutes (default 5) to `%LOCALAPPDATA%\CallingAllDumbies\autosave\`, written to a temp file then atomically renamed. A lock file marks open sessions; on startup an orphaned lock offers recovery.

---

## 10. Import/export plugin system

Each format is one self-contained module in `cad/plugins/formats/` (built-in) or `%APPDATA%\CallingAllDumbies\plugins\` (user-added). Core code never names a specific format.

```python
class FormatPlugin(Protocol):
    id: str                        # "dxf"
    name: str                      # "AutoCAD DXF"
    extensions: tuple[str, ...]    # (".dxf",)
    can_import: bool
    can_export: bool
    capabilities: Capabilities     # layers, colors, linetypes, lineweights, units, 3d, paper_space, text, hatch, blocks
    def export_options(self) -> OptionsSchema: ...      # drives an auto-generated options dialog
    def export(self, doc, path, options, report: Report) -> None: ...
    def import_(self, path, options, report: Report) -> Document: ...
```

- **Loss warnings are automatic**: before exporting, the registry compares what the document uses (layers, linetypes, 3D solids, paper space…) with the plugin's `capabilities` and lists what can't be carried over. Plugins add format-specific warnings to `report`.
- **Batch export**: choose a set of plugins and options once; each runs in turn, and a combined report is shown at the end.

| Format | Implementation |
|---|---|
| DXF R12–2018 import/export | ezdxf |
| DWG import/export | Export to DXF → ODA File Converter → DWG (and the reverse). Auto-detects the converter in its default install path; settings let you point to it. If not installed, the menu entry explains and links to the offline help page about it |
| PDF (vector, scaled, multi-sheet) | Qt `QPdfWriter` + the same draw code as the screen, one page per layout |
| SVG | In-house writer (one `<g>` per layer) |
| PNG/JPG/TIFF | Qt offscreen render |
| HPGL/PLT | In-house writer, pens mapped from colors |
| STEP AP203/AP214, IGES | OCCT XCAF writers (keeps colors and layers) |
| STL ASCII/binary | OCCT `StlAPI` / `RWStl` |
| glTF | OCCT `RWGltf_CafWriter` |
| OBJ, 3MF | In-house writers from OCCT triangulation (OCP does not wrap OCCT's OBJ writer; 3MF has no OCCT writer) |
| SVG import | svgelements |
| STEP/IGES/STL import | OCCT readers |

`docs/PLUGINS.md` walks through writing a new plugin, with a minimal working example (tested in CI).

**Phase 4 status:** DXF (R12–2018), DWG via ODA, PDF, SVG (export + import), PNG/JPG/TIFF, HP-GL/2,
batch export and printing are done. They all draw through `core/plot.py`, which turns a model window
or a layout into sheets of strokes and fills in paper millimeters (linetypes dashed, viewports clipped),
so every paper output looks the same. The 3D formats (STEP, IGES, STL, glTF, OBJ, 3MF and their
validators FreeCAD/Blender) move to Phase 6, where there is 3D geometry to export. Inkscape was
replaced by librsvg (`rsvg-convert`) and poppler as the SVG/PDF validators: same check, a much smaller
install on the CI runner.

---

## 11. Help system

- Content is Markdown with a small YAML header, under `help_content/`:
  ```markdown
  ---
  id: polar-array
  type: command
  title: Polar Array
  aliases: [ARRAYPOLAR]
  shortcut: AR
  synonyms: [copy in a circle, radial copy, circular pattern]
  related: [rectangular-array, rotate, copy]
  glossary: [array, center-point]
  ---
  ## Purpose
  ...
  ```
- Rendered in a `QTextBrowser`; cross-links work offline.
- Search: an index built at startup over titles, aliases, synonyms and body text. `rapidfuzz` handles typos; `synonyms.json` maps everyday phrases to terms. Results update on every keystroke.
- **F1** opens the help page of the active command (via the registry's help id); with no command active it opens the help home page.
- A CI test fails if any registered command has no help page, or any help link is broken.
- **Phase 5 status:** done. Pages are rendered with Qt's Markdown support in a `QTextBrowser` (no extra
  dependency). Tutorials are executable: their typed steps are run by `help/tutorial_runner.py` in CI.
- Tutorials: "Draw a simple floor plan" and "Draw a simple machined part", each step linked to its command pages.

---

## 12. Testing and validation

| Layer | What |
|---|---|
| Unit | Units parser/formatter (several hundred cases incl. round-trips), geometry ops (intersections, trim/extend, offset, fillet), constraints, transactions |
| Exporters | Every plugin has tests; DXF round-trip (export → import → compare entities within tolerance) for each DXF version |
| Independent validation | Exports re-read by software that isn't ours. Planned (final list confirmed in Phase 4, depending on what installs cleanly on the CI runner): ezdxf audit; **LibreCAD** CLI (`dxf2pdf`) for DXF; **FreeCAD** headless for STEP/IGES/STL/DXF; **ODA File Converter** for DXF/DWG; **Inkscape** CLI for SVG/PDF; **Blender** headless for OBJ/glTF/3MF/STL. Runs on the Linux CI runner |
| UI | pytest-qt, offscreen: commands driven end to end, screenshot artifacts of the main window and viewport for visual review |
| Performance | 50k/100k-entity benchmark with time limits |
| Windows | Full test suite + PyInstaller build + launch smoke test on `windows-latest` (Windows Server 2022/2025, the closest CI equivalent to Windows 10/11) |

What only your PC can check: speed on real integrated graphics, look and feel at your DPI, and the installer UX. I'll write a 15-minute checklist for that.

---

## 13. Build and release

- **CI** (every push): Linux tests, Windows tests, Windows build. Build artifacts (installer + portable zip) downloadable from the run.
- **Release** (on tag `v*`): attaches `CAD-Setup-x.y.z.exe` and `CAD-Portable-x.y.z.zip` to a GitHub Release.
- **Installer**: Inno Setup, per-user install by default (no admin needed), optional all-users install, `.cadz` file association, Start menu entry.
- **Portable**: same files zipped; detects a `portable.flag` next to the exe and stores settings/autosave in the folder instead of `%APPDATA%`.
- **Unsigned**: Windows SmartScreen will show "Windows protected your PC → More info → Run anyway" the first time. Documented in the README.

---

## 14. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | **Scope.** This spec is multi-person-year in commercial terms | Features will be solid but not AutoCAD-deep (e.g. no dynamic blocks, no xrefs, no sheet sets) | Each phase has explicit acceptance criteria (§15). Anything cut is listed, not silently dropped |
| 2 | Python speed with 50k+ entities during editing | Lag on regen/trim/selection | GPU rendering, numpy batching, spatial index, perf tests in CI from Phase 2 on |
| 3 | Old or buggy Intel GL drivers | Viewport fails to start | Check GL 3.3 at startup with a clear message; keep a slower QPainter fallback renderer behind the same interface |
| 4 | DXF/DWG fidelity with real AutoCAD files | SHX fonts, proxy objects, dynamic blocks, annotative scaling not fully supported | Import report lists everything skipped or approximated; SHX mapped to similar TrueType fonts |
| 5 | DWG depends on ODA File Converter | No DWG without the user installing it; ODA terms don't allow bundling | Clear in-app guidance; DXF always available |
| 6 | In-house constraint solver robustness | Solver fails or flips geometry on hard cases | Start from current geometry, damped steps, conflict reporting; large randomized test suite |
| 7 | OCCT failures on fillets/booleans of awkward geometry | Operation fails | Catch, report plainly, leave the model unchanged (transactions make this free) |
| 8 | Antivirus false positives on PyInstaller builds | Users can't run it | One-dir build, no UPX compression; submit to Microsoft as false positive if needed |
| 9 | I can't see the app on a real Windows desktop | UI issues missed | CI screenshots each phase + your checklist runs |

---

## 15. Phase plan with acceptance criteria

| Phase | Delivers | Done when |
|---|---|---|
| **2. Core** | Window, ribbon, command line, status bar; GL canvas with pan/zoom/extents; Line, Circle, Arc, Polyline; all three unit modes + parser; typed coordinates; all snaps, grid, ortho, polar & object tracking; layers; undo/redo; `.cadz` save/open; autosave; themes and UI scale | All units tests pass; 50k-entity drawing pans/zooms smoothly in CI benchmark; Windows build runs |
| **3. Editing & annotation** | All edit commands; rectangle, ellipse, spline, polygon, point, text, mtext, hatch; all dimension types + leader; blocks, groups; layouts/paper space with title blocks; 2D constraints | Every command has tests and a registry entry |
| **4. File exchange** | All import/export plugins, batch export, print/PDF with scales, DWG via ODA, `PLUGINS.md` | Every exporter passes its third-party validator in CI |
| **5. Help** | Command reference, glossary, search with synonyms, F1, two tutorials | Every command documented; link checker passes |
| **6. 3D** | Sketches, extrude/revolve/sweep/loft, booleans, fillet/chamfer/shell, 3D views, 2D drawings from 3D, 3D exports | Machined-part tutorial completable in 3D |
| **7. Ship** | Installer, portable build, README, developer guide, full test pass, your checklist | Your sign-off on a real PC |

Each phase ends with a pull request on this repo and a stop for your review.

---
