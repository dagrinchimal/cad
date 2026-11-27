---
id: extrude
type: command
title: Extrude
command: EXTRUDE
synonyms: [solid from outline, give height, thicken, pull up, cut hole through]
related: [sketch, presspull, revolve, subtract, 3d-modeling]
glossary: [extrude, solid, profile]
---
Turns closed outlines into solids by giving them height. It can also add to a solid (**Join**) or cut into one (**Cut**), so most parts are just a few extrudes.

## How to use
1. Draw a closed outline: a [rectangle](help:rectang), [circle](help:circle), closed polyline, or any closed shape on a [sketch](help:sketch).
2. Start **Extrude** and select the outlines, then press Enter. Or type `A` (**Area**) and click inside areas, like [Hatch](help:hatch): holes inside the area are kept as holes.
3. Type the height, or in the 3D view move the mouse and click (a live preview shows the result). A negative height goes the other way.

## Options
- **Area** (`A`): click inside closed areas formed by any lines. The outlines stay in your drawing.
- **Join** (`J`): the new shape is added to the solids it touches.
- **Cut** (`C`): the new shape is cut out of the solids it touches (holes, pockets, slots).
- **New** (`N`): a separate solid (the default).
- **Both sides** (`B`): extrude the same amount on both sides of the outline.
- **Through all** (`T`): cut right through every solid, both ways. Handy for through holes.

## Tips
- Outlines you select in the plan are used up (they become the solid), like AutoCAD. Outlines on a sketch, and Area picks, are kept.
- Heights go along the sketch's normal: up for the plan and XY sketches, toward you for a Front (XZ) sketch.
- The height is remembered for next time.
