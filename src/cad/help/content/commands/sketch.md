---
id: sketch
type: command
title: Sketch
command: SKETCH
synonyms: [work plane, drawing plane, ucs, draw on face, draw on side]
related: [editsketch, exitsketch, extrude, revolve, 3d-modeling]
glossary: [sketch, plane, reference geometry]
---
Starts a sketch: a flat drawing plane placed in 3D. Everything you draw on it with the normal 2D tools (lines, circles, constraints, dimensions…) lives on that plane, ready to [Extrude](help:extrude), [Revolve](help:revolve) or [Loft](help:loft).

## How to use
1. Start **Sketch** and choose where:
   - **XY** (top), **XZ** (front) or **YZ** (side) through the origin;
   - **Face** (`F`): click a flat face of a solid;
   - **Offset** (`O`): one of the three planes moved by a distance, e.g. XY 10 up.
2. A tab "✎ Sketch1" opens. Draw as usual. The edges of your solids show as grey **reference lines** you can snap to (they're on a locked layer and don't print).
3. Extrude or revolve what you drew, then [Finish Sketch](help:exitsketch) (or click the **Model** tab).

## Tips
- On an XY or offset XY sketch, sketch coordinates are the plan's coordinates. On an XZ sketch, the sketch's Y is the model's height.
- Right-click a sketch tab to refresh its reference lines or delete it.
