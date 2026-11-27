# Developer guide

Read [ARCHITECTURE.md](ARCHITECTURE.md) first. This guide covers the code as it stands.

## Layout

```
src/cad/
  core/        pure Python + numpy. Never imports Qt (a test enforces it)
    units/     parser.py (any typed format → mm), formatter.py (mm → display), scales.py
    geom2d/    vec.py, primitives.py (Seg, Arc), construct.py (bulges, intersections, tangents)
    model/     entities.py, document.py (tables + transactions), styles.py
    spatial.py R-tree index: pick, window/crossing selection, snap candidates
    snaps.py   object snaps, grid, ortho, polar tracking, object snap tracking
    model/geometry.py   entity -> drawable/snappable Geometry (parts, fills, text runs, snap points)
    model/dimensions.py dimension & leader geometry;  model/hatch_patterns.py
    edit.py    trim, extend, offset, fillet, chamfer, join, explode (Curve parameterization)
    layouts.py layouts, title blocks, viewports
    constraints/  model (refs, expressions), solver (LM + DOF), manager (re-solve on commit)
    text.py    text layout interface (Qt engine registered by the UI)
  commands/    framework.py, draw.py, draw2.py, modify.py, annotate.py, constraints.py, basic.py
  io/native.py .cadz save/load
  render/      view.py, scene.py (entities → GPU instance arrays), canvas_gl.py, canvas_painter.py
  ui/          main_window.py, controller.py (mouse/keys/snaps/overlay), ribbon, command line, dialogs
```

Dependency direction: `ui → commands → core`, `render → core`, `io → core`.

## Key ideas

**Geometry is immutable.** Entities are frozen dataclasses. To edit, build a changed copy and call
`doc.replace(new)`. Every mutation must happen inside `with doc.transaction("Name"):` — that is
one undo step. Listeners (spatial index, renderer, UI) receive a `ChangeSet` saying which handles
were added, removed or modified.

**Everything is millimetres internally.** Convert only at the edges: `parse_length(text, units)`
for input, `format_length(mm, units)` for output.

**Commands are generators.** They yield requests and receive answers:

```python
from cad.commands.framework import GetPoint, GetDistance, command, kw
from cad.core.model import Circle

@command("RING", label="Ring", aliases=("RI",), group="Draw",
         description="Draw two concentric circles.")
def ring_cmd(ctx):
    center = yield GetPoint("Specify center", rubber=None)
    r = yield GetDistance("Specify outer radius", base=center,
                          preview=lambda c: [Circle(center=center, radius=max(1e-9, ((c[0]-center[0])**2 + (c[1]-center[1])**2) ** .5))])
    ctx.doc.add(Circle(center=center, radius=r), use_current_props=True)
    ctx.doc.add(Circle(center=center, radius=r * 0.8), use_current_props=True)
```

- Importing the module registers the command (add it to `commands/__init__.py`).
- The runner wraps the command in a transaction, so the whole command is one undo step.
- Keywords: `GetPoint("…", keywords=kw("Close", "Undo"))` returns the string `"Close"` when chosen.
- `preview` returns temporary entities drawn under the cursor.
- The ribbon, command-line search, tooltips and (Phase 5) F1 help all read the registry entry.
- Test it without any UI: see `tests/unit/test_commands.py`.

**Geometry service.** Never read an entity's shape directly for drawing or snapping: call
`doc.geometry(e)`. It returns parts (line primitives, filled areas, text runs) with snap points, and
handles composite types (blocks with ByBlock/layer-0 styles, dimensions, hatches, text). It is cached
per entity and invalidated automatically. To add an entity type: a frozen dataclass in
`model/entities.py` with `FIELDS`, `transformed()`, and (if composite) a builder in `model/geometry.py`.

**Constraints.** `ConstraintManager` registers a pre-commit hook on the document. When a transaction
touches constrained geometry, the connected group is re-solved and the corrections are recorded in the
same undo step. A conflict rolls the whole edit back.

**Rendering.** `SceneBuilder` caches one float32 block per entity (segments + color + width +
linetype). Pan and zoom only change shader uniforms. Curves are re-tessellated when the zoom
changes a lot (auto-regen). The OpenGL canvas expands each segment to a quad in the vertex shader
and does dash patterns in the fragment shader. The QPainter canvas draws the same arrays for
machines without OpenGL 3.3. Overlays (cursor, snap markers, tooltips) are painted with QPainter.

## Help pages

Help content is Markdown under `src/cad/help/content/`: `commands/` (one page per command), `concepts/`,
`tutorials/`, `glossary.md` (one `### Term` per entry, optional `Also:` line) and `synonyms.json`
(everyday phrases -> page ids, used by search). Each page starts with a header:

```
---
id: offset                 # commands: the command's help_id (its name in lower case)
type: command              # command | concept | tutorial | home
title: Offset
command: OFFSET            # command pages only: the facts line and the Start button come from the registry
synonyms: [parallel copy, wall thickness]
related: [copy, trim]      # page ids shown under "See also"
glossary: [offset]         # glossary terms shown under "Words used here"
---
```

Links: `[text](help:page-id)`, `[text](term:glossary-term)`, `[text](run:COMMAND)`.

Tutorial steps go in ```` ```commands ```` blocks, one input per line (see `help/tutorial_runner.py` for
`<Enter>`, `<click x,y>`, `<select x,y>`, `<crossing a b>`, `<units ...>`, `<layer ...>`, `<dimscale n>`).
`tests/help/` runs every tutorial against a fresh drawing and checks the result, fails if a command has
no page or a link is broken, and checks that common questions find the right page.

**Adding a command? Add its page in `commands/` too**, or the tests fail.

## 3D

- New modeling operations go in `core/solids.py` (pure functions shape -> shape, no Qt); commands in
  `commands/solids3d.py` use `new_solid()` / `replace_shape()` so results land in model space with undo.
- Requests: `GetFace(planar_only)` and `GetEdge(solid)` return `FacePick` / `EdgePick` (entity, index,
  3D point). Face/edge indices follow `solids.faces()` / `solids.edges()` order.
- OCP 8 moved arrays and maps to `OCP.collections` and renamed some statics; `solids.py` has the
  compatibility imports. `Bnd_Box.Get()` is broken in OCP 8: use `CornerMin/CornerMax`.
- Set `CAD_RENDERER_3D=software` to force the QPainter 3D renderer.
- 3D formats live in `plugins/formats/solid3d.py`; `tests/plugins/test_3d_formats.py` re-reads mesh
  exports with trimesh and exact ones with OpenCascade (and FreeCAD when installed).

## Tests

| Folder | What |
|---|---|
| `tests/unit` | units, geometry, model, file format, commands, snaps, architecture rules |
| `tests/integration` | the real main window driven with mouse clicks and typing |
| `tests/perf` | 50,000-entity benchmark (`pytest -m perf -s`) |

CI runs all of them on Linux (software and OpenGL renderers) and Windows, builds `CAD.exe`
with PyInstaller, smoke-tests the built exe and uploads a portable zip plus screenshots.

## Conventions

- New user-facing text: plain English, no jargon without explanation.
- Every command needs `label` and a one-line `description`.
- Never block the UI with long work without feedback; never crash on bad input — report it in the
  command line and keep the prompt.
