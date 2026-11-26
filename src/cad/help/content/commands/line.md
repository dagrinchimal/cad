---
id: line
type: command
title: Line
command: LINE
synonyms: [straight line, segment, draw a line, wall line]
related: [pline, offset, trim, coordinates]
glossary: [object snap, polar tracking, ortho]
---
Draws straight lines, one after another. Each segment is a separate object.

## How to use
1. Start **Line** and click the first point (or type it, e.g. `0,0`).
2. Click the next point, or type it. Each click adds a segment that starts where the last one ended.
3. Press **Enter** or **Esc** to stop.

## Typing points
- `100,50` — an exact spot (x,y).
- `@100,0` — 100 to the right of the last point.
- `@100<45` — 100 long at 45°.
- Move the mouse in a direction and type `100` — 100 in that direction. In feet-inch drawings `12` means 12 feet and `3 4-1/2` means 3'-4 1/2". See [Typing coordinates](help:coordinates).

## Options
- **Undo** (`U`): removes the last segment and keeps going.
- **Close** (`C`): after two segments, draws one back to the start and finishes.

## Tips
- Hold **Shift** or press **F8** for Ortho to draw only horizontal and vertical lines.
- Snap to ends, middles and crossings of other objects with [object snaps](help:snaps).
- For one connected outline you can fillet or offset as a whole, use [Polyline](help:pline).
