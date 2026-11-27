# The .cadz file format (version 1.4.0)

A `.cadz` file is a standard ZIP archive. Rename it to `.zip` to look inside.

| Member | Required | Contents |
|---|---|---|
| `manifest.json` | yes | Format name and version, program version, timestamps |
| `document.json` | yes | The drawing: header, tables, entities |
| `thumbnail.png` | no | Preview image (up to 256×256) |
| `solids/<handle>_<n>.brep` | if the drawing has solids | One exact 3D shape per solid, in OpenCascade's text BREP format |
| anything else | no | Kept untouched when an older version re-saves the file |

All lengths are **millimetres** stored as JSON numbers (64-bit floats). All angles are **radians**,
counter-clockwise from +X. Unit settings only control display.

## manifest.json

```json
{
  "format": "cadz",
  "format_version": "1.0.0",
  "app": "CAD: Calling All Dumbies",
  "app_version": "0.2.0",
  "created": "2026-11-25T17:00:00+00:00",
  "modified": "2026-11-25T18:30:00+00:00"
}
```

## document.json

```json
{
  "header": {
    "units": {"mode": "architectural", "decimal_places": 2, "denominator": 16, "angle_decimal_places": 0},
    "ltscale": 1.0,
    "current_layer": "Walls",
    "current_color": 256,
    "current_linetype": "ByLayer",
    "current_lineweight": -1.0,
    "grid_spacing": 25.4,
    "snap_spacing": 6.35,
    "point_size_px": 5.0
  },
  "layers": [
    {"name": "0", "color": 7, "linetype": "Continuous", "lineweight": -3.0,
     "on": true, "frozen": false, "locked": false, "plot": true, "description": ""}
  ],
  "linetypes": [
    {"name": "DASHED", "description": "Dashed __ __", "pattern": [12.7, -6.35]}
  ],
  "entities": [ ... ],
  "next_handle": 42
}
```

`units.mode` is `mm`, `fractional` or `architectural`. `denominator` is 2, 4, 8, 16, 32 or 64.

### Styles

- **Color:** integer AutoCAD Color Index 1–255, `256` = ByLayer, `0` = ByBlock, or a string `"#rrggbb"`.
- **Lineweight:** millimetres, or `-1` ByLayer, `-2` ByBlock, `-3` Default (0.25 mm).
- **Linetype pattern:** millimetres; positive = dash, negative = gap, `0` = dot. Empty = continuous.

### Entities

Every entity has these keys:

| Key | Type | Meaning |
|---|---|---|
| `type` | string | `line`, `circle`, `arc`, `polyline`, `point` |
| `handle` | integer | Unique, never reused within the file |
| `layer` | string | Layer name |
| `color`, `linetype`, `lineweight` | see above | Usually ByLayer |
| `ltscale` | number | Per-object linetype scale |

Geometry by type:

| Type | Keys |
|---|---|
| `line` | `p1: [x, y]`, `p2: [x, y]` |
| `circle` | `center: [x, y]`, `radius` |
| `arc` | `center`, `radius`, `start_angle`, `end_angle` (counter-clockwise from start to end) |
| `polyline` | `vertices: [[x, y, bulge], ...]`, `closed: bool`. Bulge = tan(¼ of the arc angle) of the segment starting at that vertex; positive = counter-clockwise, 0 = straight |
| `point` | `position: [x, y]` |

### Entity types added in 1.1

| Type | Keys |
|---|---|
| `ellipse` | `center`, `major` (vector to the end of the major axis), `ratio` (minor/major), `start_param`, `end_param` |
| `spline` | `control_points`, `knots`, `degree`, `fit_points`, `closed` (cubic B-spline; passes through `fit_points`) |
| `text` | `insert`, `text`, `height` (capital height), `rotation`, `width_factor`, `halign` (left/center/right), `valign` (baseline/bottom/middle/top), `font` |
| `mtext` | `insert`, `text` (`\n` = new line), `height`, `width` (wrap width, 0 = none), `rotation`, `halign`, `valign`, `line_spacing`, `font` |
| `hatch` | `loops` (list of closed vertex loops `[x, y, bulge]`, even-odd), `pattern` (`SOLID`, `ANSI31`…), `pattern_scale`, `pattern_angle` |
| `dimension` | `dimtype` (linear/aligned/angular/radius/diameter/ordinate), `p1`, `p2`, `p3`, `location`, `angle`, `axis`, `text` (override; `<>` = measured), `style`, `origin` |
| `leader` | `points`, `text`, `style` |
| `attdef` | `tag`, `prompt`, `default`, `insert`, `height`, `rotation`, `halign`, `valign`, `invisible`, `font`, `width_factor` |
| `insert` | `name` (block), `insert`, `sx`, `sy`, `rotation`, `attribs` (`[[tag, value], …]`) |
| `viewport` | `center`, `width`, `height` (paper mm), `view_center` (model), `scale` (paper per model), `locked`, `fit` |

Every entity may also have `space`: omitted for model space, otherwise the name of the layout it sits on.

### Tables added in 1.1

| Key | Contents |
|---|---|
| `blocks` | `[{name, base, description, entities: [...]}]` — entity handles are local to the block |
| `dimstyles` | `[{name, text_height, arrow_size, arrow, ext_offset, ext_extension, text_gap, center_mark, scale, decimal_places, font}]` |
| `groups` | `[{name, handles, description}]` |
| `layouts` | `[{name, paper, width, height, order, portrait}]` |
| `constraints` | `[{id, kind, refs: [[handle, part], …], name, expression, values}]` (see `core/constraints/model.py` for parts and kinds) |

New header keys: `text_height`, `current_dimstyle`, `hatch_pattern`, `hatch_scale`, `hatch_angle`.
Version 1.0 files open unchanged (all additions have defaults).

### Added in 1.2 (associativity)

| Where | Keys |
|---|---|
| `dimension` | `refs: [[handle, part], …]` — what `p1`, `p2`, `p3` are attached to (`[0, ""]` = not attached). Parts are named points (`p1`, `p2`, `mid` on lines; `v3` = polyline vertex 3; `center`, `start`, `end`…, see `core/points.py`). Radius/diameter dimensions use `[[circle, "curve"]]` |
| `hatch` | `sources` (handles of the boundary objects), `seed` (the point clicked inside, or `null` for a hatch made from selected objects) |
| `array` (new type) | `sources`, `kind` (`rect`/`polar`), `rows`, `cols`, `row_vec`, `col_vec`, `center`, `count`, `fill_angle`, `rotate_items`, `placement` (a 2×3 affine matrix applied to every copy). The copies are not stored: they are recomputed from the source objects |

When an attached object changes, the program updates the dimension, hatch or array in the same
undo step. Programs that don't understand associativity can ignore these keys: the stored points
and loops are always current. Version 1.0 and 1.1 files open unchanged.

### Added in 1.3 (3D)

| Where | Keys |
|---|---|
| `solid` (new type) | `name`, `hole` (1.4: true for a hole shape), `shape: {"file": "solids/38_1.brep"}` — the exact shape (B-rep) in the named zip member, in mm, model coordinates. Solids are always in model space. |
| `sketches` (new table) | `[{name, origin: [x,y,z], xdir: [x,y,z], normal: [x,y,z], visible}]` — a drawing plane. Entities on it have `space: "*Sketch:<name>"` and 2D coordinates on the plane: model point = origin + x·xdir + y·(normal × xdir) |
| `blocks[].description` | Drawing views (blocks named `View<n>`, made by VIEWBASE) hold `{"drawing_view": {view, scale, hidden, solids}}` as JSON so they can be regenerated; their entities are plain lines |

BREP files are written by `BRepTools::Write` (OCCT 7.9 / 8.0, text format, triangulation stripped)
and can be read by any OpenCascade-based program (FreeCAD: `Part.read`). A solid whose BREP member
is missing loads as `solid_missing` and is kept, with a warning. Older files open unchanged.

### Added in 1.4

`hole` on solids (hole shapes for COMBINE). Version 1.3 files open unchanged (`hole` defaults to false);
programs that only know 1.3 keep the key as an unknown field and show the shape as a normal solid.

## Compatibility rules

1. **Older files always open.** Each format version bump ships a migration in
   `src/cad/io/native.py` (`MIGRATIONS`) that upgrades the previous version's `document.json`.
   Test files from every version are kept in `tests/data/format_versions/`.
2. **Newer minor versions open with a notice.** Unknown keys (top level, header, manifest, inside
   entities), unknown entity types and unknown ZIP members are preserved and written back unchanged.
3. **Newer major versions are refused** with a clear message to update the program.
4. **Saving is atomic:** the file is written to a temporary file in the same folder and then renamed,
   so a crash or full disk never leaves a half-written drawing.
