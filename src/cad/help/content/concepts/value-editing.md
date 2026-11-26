---
id: value-editing
type: concept
title: Grips and clicking a number to change a size
order: 7
synonyms: [revit style editing, temporary dimensions, type a new length, change size by number, resize line exactly, edit dimension value]
related: [gripedit, dimlinear, stretch, associativity]
glossary: [grip, temporary dimension]
---
Select **one** object and two things appear:

1. **Grips**: blue squares on its ends, middles, center or corners. Click one, then click (or type) its new position. See [Grip editing](help:gripedit).
2. **Blue numbers**: the object's own sizes (a line's length, a circle's radius, each straight segment of a polyline) and the values of every dimension attached to it.

## Click a number, type a size
1. Click the blue number.
2. Type the size you want, in any unit (`12'-6"`, `3 4-1/2`, `1500`).
3. Press **Enter** (or **Esc** to cancel).

What changes:
- **Line length**: the end you drew last moves along the line.
- **Polyline segment**: the far side moves, like a Stretch, so rectangles stay rectangular.
- **Radius**: the circle or arc changes size around its center.
- **A dimension between two objects** (e.g. two walls): the object **you selected** moves. Select the other wall first if you want that one to move.
- **An angle**: the line you selected turns.

Everything attached (dimensions, hatches, arrays) updates, and it's one step to undo.
