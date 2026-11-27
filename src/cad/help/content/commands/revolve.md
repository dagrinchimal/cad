---
id: revolve
type: command
title: Revolve
command: REVOLVE
synonyms: [lathe, turn, spin profile, rotate profile, shaft, axisymmetric]
related: [extrude, sketch, sweep, 3d-modeling]
glossary: [revolve, solid, profile, axis]
---
Spins closed outlines around an axis to make round parts: shafts, knobs, bowls, rings, washers.

## How to use
1. Draw half of the part's cross-section as a closed outline, on one side of the axis. A [Front (XZ) sketch](help:sketch) is the natural place: the plan's X axis becomes the part's axis.
2. Start **Revolve**, select the outlines, press Enter.
3. Pick two points on the axis, or type `X` or `Y` for the drawing's X or Y axis through 0,0.
4. Press Enter for a full 360° turn, or type an angle.

## Tips
- The outline must not cross the axis.
- A rectangle beside the axis makes a tube; a rectangle touching it makes a solid rod.
