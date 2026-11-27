---
id: file-formats
type: concept
title: File formats: DXF, DWG, PDF and more
order: 11
synonyms: [autocad file, dwg converter, oda, export formats, compatibility, send to autocad, file types]
related: [open, saveas, export, import, plot, plugins]
glossary: [dxf, dwg, pdf, svg, hpgl, step, stl]
---
| Format | Open | Save / Export | Notes |
|---|---|---|---|
| `.cadz` (this program) | yes | yes | Keeps everything |
| DXF (AutoCAD R12 – 2018) | yes | yes | Layers, colors, linetypes, lineweights, text, hatches, blocks, attributes, dimensions, layouts, groups |
| DWG (AutoCAD) | yes* | yes* | *Needs the free ODA File Converter |
| PDF | – | yes | Vector, true to scale, one page per sheet |
| SVG | yes | yes | One group per layer; import turns shapes into polylines and fills |
| PNG, JPEG, TIFF | – | yes | Any resolution; PNG can be transparent |
| HP-GL/2 (`.plt`) | – | yes | For pen plotters and cutters; colors become pens |
| STEP, IGES | yes | yes | Exact 3D solids for other CAD programs (see [3D modeling](help:3d-modeling)) |
| STL, 3MF, glTF, OBJ | STL only | yes | 3D meshes for printing and viewers |

## What DXF and DWG can't keep
Constraints, associativity (dimensions and hatches still come across but stop following their shapes) and live arrays (exported as separate copies). The Export dialog and the first Save As DXF tell you exactly what applies to your drawing. Keep a `.cadz` copy if you'll edit it again here.

## Setting up DWG
DWG is AutoCAD's own format, and the free converter that reads and writes it can't be shipped with this program.
1. Download the **ODA File Converter** for Windows from opendesign.com (search "ODA File Converter") and install it.
2. That's it: the program finds it in its usual folder. If you installed it elsewhere, set its location in [Options](help:options).

Without it, use DXF: AutoCAD opens DXF files directly.

## When importing
A report lists anything not brought in from DXF/DWG: 3D solids (import STEP instead), images, proxy objects; AutoCAD's SHX stroke fonts are replaced by Arial.
