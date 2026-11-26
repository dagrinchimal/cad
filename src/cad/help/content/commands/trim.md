---
id: trim
type: command
title: Trim
command: TRIM
synonyms: [cut, clip, remove part, cut off overhang, clean up corners]
related: [extend, break, fillet]
glossary: [cutting edge, fence, crossing window]
---
Cuts off the parts of objects that stick past other objects. Everything is a cutting edge, so you just click what to remove.

## How to use
1. Start **Trim**.
2. Click each piece you want gone. It's cut back to the nearest crossing objects.
3. Press **Enter** when done.

## Several at once
- Click on **empty space**, then click a second point: every object your **fence** line crosses is trimmed where it crosses. Press **Enter** to add more fence points.
- **Crossing** (`C`): click empty space and drag a box instead; everything crossing the box's edges is trimmed there.
- **Fence** (`F`): back to fence lines.

## Options
- **Shift-click**: extends that object instead of trimming it.
- **Undo** (`U`): undoes the last trim and stays in the command.

## Tips
- A piece with nothing crossing it is deleted entirely.
