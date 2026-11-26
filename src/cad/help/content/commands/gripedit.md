---
id: gripedit
type: command
title: Grip editing
command: GRIPEDIT
synonyms: [drag corner, move endpoint, reshape, grips, blue squares]
related: [stretch, move, value-editing]
glossary: [grip]
---
Reshapes objects by their **grips**, the blue squares that appear on selected objects.

## How to use
1. Click an object to select it. Blue grips appear on its ends, middle, center or corners.
2. Click a grip. It turns red and follows the cursor.
3. Click the new spot, or type it (`@2',0`, or point the mouse and type a distance).

## What each grip does
- Line ends: move that end. Line middle: move the whole line.
- Circle center: move it. Circle quadrants: change the radius.
- Polyline corners: move that corner. Segment middles: move that whole segment.
- Dimension points: move where it measures from, or where its line or text sits.

## Options
- **Copy** (`C`): leave the original and change a copy.
- **Base point** (`B`): measure the move from a different point.

## Tips
- When two selected objects share a corner, dragging that grip moves both, so walls stay joined.
