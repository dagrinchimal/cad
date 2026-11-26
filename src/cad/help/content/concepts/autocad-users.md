---
id: autocad-users
type: concept
title: Coming from AutoCAD
order: 14
synonyms: [autocad differences, migrate from autocad, for autocad users, like autocad]
related: [keyboard, file-formats, value-editing, units-and-typing]
glossary: []
---
Most of what you know works: the same command names and short aliases, Enter/Space to repeat, typed coordinates (`@`, `<`), object snaps and tracking, layers, blocks with attributes, layouts with viewports, DXF/DWG.

## Differences worth knowing
- **Feet-inches typing**: by default a bare number is **feet** (Revit style): `3 4-1/2` = 3'-4 1/2". Switch to AutoCAD style in [Units](help:units).
- **Click a number to resize** (like Revit's temporary dimensions): select an object, click its blue length, type the size. See [Grips and numbers](help:value-editing).
- **Trim/Extend**: everything is a cutting edge (like AutoCAD's "quick" mode). Click empty space to start a fence; Shift-click swaps trim and extend.
- **Arrays** are always live, edited in Properties.
- **Dimensions and hatches** are associative by default.
- **No xrefs, dynamic blocks, sheet sets, or annotative scaling.** Use Import, regular blocks, layouts and the dimension style's overall scale.
- **Fonts**: TrueType fonts only; SHX fonts in DXF/DWG files are shown in Arial.
