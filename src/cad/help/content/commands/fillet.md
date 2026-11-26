---
id: fillet
type: command
title: Fillet
command: FILLET
synonyms: [round corner, radius corner, rounded edge, clean corner, square corner]
related: [chamfer, trim, extend, pline]
glossary: [fillet, radius]
---
Rounds the corner between two objects with an arc. With radius **0** it makes a clean sharp corner: the quickest way to tidy up two lines that overshoot or don't meet.

## How to use
1. Start **Fillet**. The current radius is shown in the prompt.
2. Choose **Radius** (`R`) to change it if needed.
3. Click the first object, then the second, on the parts you want to keep.

## Options
- **Radius** (`R`): set the fillet radius.
- **Polyline** (`P`): rounds every corner of a polyline at once.

## Tips
- Works on lines, arcs, circles and polylines.
