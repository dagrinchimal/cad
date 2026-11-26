---
id: units-and-typing
type: concept
title: Units: millimeters, inches, feet-inches
order: 3
synonyms: [imperial, metric, feet and inches, revit typing, architectural units, fractional inches, convert units]
related: [units, coordinates, dimstyle]
glossary: [units, precision]
---
Inside the program every size is stored exactly; the units only decide how numbers are shown and how a bare number is read. Choose them in [Units](help:units) or with the box at the bottom right.

| Units | Shown as | A bare `12` means |
|---|---|---|
| Millimeters | `1250.50` | 12 mm |
| Fractional inches | `3 1/2"` | 12 inches |
| Architectural (feet-inches) | `3'-4 1/2"` | 12 **feet** (Revit typing, the default) or 12 inches (AutoCAD typing) |

## Typing feet and inches
Revit typing (the default in architectural drawings):
- `3 4-1/2` = 3'-4 1/2"
- `0 1.5` = 1 1/2"
- `12` = 12'
- `3 4` = 3'-4"

AutoCAD typing (choose it in Units): a bare number is inches; use `'` for feet: `3'4-1/2`, `40.5`.

These always work in either style: `3'-4 1/2"`, `3' 4.5"`, `40.5"`, `1 1/2"`, `1250mm`, `1.25m`.

## Tips
- DXF and DWG files of feet-inch drawings are written in inches, which is what AutoCAD users expect.
- Dimension text follows the drawing's units unless the [dimension style](help:dimstyle) sets its own decimal places.
