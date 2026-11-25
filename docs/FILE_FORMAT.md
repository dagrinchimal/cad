# The .cadz file format (version 1.0.0)

A `.cadz` file is a standard ZIP archive. Rename it to `.zip` to look inside.

| Member | Required | Contents |
|---|---|---|
| `manifest.json` | yes | Format name and version, program version, timestamps |
| `document.json` | yes | The drawing: header, tables, entities |
| `thumbnail.png` | no | Preview image (up to 256×256) |
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

## Compatibility rules

1. **Older files always open.** Each format version bump ships a migration in
   `src/cad/io/native.py` (`MIGRATIONS`) that upgrades the previous version's `document.json`.
   Test files from every version are kept in `tests/data/format_versions/`.
2. **Newer minor versions open with a notice.** Unknown keys (top level, header, manifest, inside
   entities), unknown entity types and unknown ZIP members are preserved and written back unchanged.
3. **Newer major versions are refused** with a clear message to update the program.
4. **Saving is atomic:** the file is written to a temporary file in the same folder and then renamed,
   so a crash or full disk never leaves a half-written drawing.
