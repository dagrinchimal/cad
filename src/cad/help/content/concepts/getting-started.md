---
id: getting-started
type: concept
title: Getting started
order: 1
synonyms: [first steps, beginner, how to start, basics, tour, interface]
related: [coordinates, units-and-typing, selecting, keyboard, tutorial-floor-plan]
glossary: [command line, ribbon, model space]
---
## The window
- **Ribbon** (top): tools grouped on tabs: Home (draw, modify, layers, blocks), Annotate (text, dimensions), Parametric (constraints), Layout, Output (plot, export, import), View. The **File** menu is at the far left.
- **Drawing area** (middle): your drawing. Turn the mouse wheel to zoom; drag with the wheel pressed to pan; double-click the wheel to see everything.
- **Command line** (bottom): type a command name and press **Enter**, or type part of what you want ("circ", "fillet", "copy in a circle") and pick from the suggestions. It also shows what each command is asking for.
- **Status bar** (very bottom): coordinates, units, and the drawing aids (GRID, SNAP, ORTHO, POLAR, OSNAP, OTRACK, LWT).
- **Properties** panel (right): everything about the selected objects.
- **Tabs** under the drawing: **Model** (your drawing, full size) and layout sheets for printing.

## Draw something
1. Click **Line** on the Home tab (or type `L` and press **Enter**).
2. Click a point in the drawing area.
3. Type `@100,0` and press **Enter**: a line 100 long to the right.
4. Point the mouse upward and type `50`, **Enter**: 50 straight up.
5. Type `C` and press **Enter** to close the triangle.

Read the command line while you work: it always says what's needed next, and the options in **[brackets]** can be clicked or typed by their capital letters.

## Change it
- Click an object to select it. Blue squares (grips) appear; drag one by clicking it and then clicking the new spot.
- Blue numbers show its sizes: click one and type a new size.
- **Delete** erases; **Ctrl+Z** undoes.

## Save it
**Ctrl+S** saves as a `.cadz` drawing, which keeps everything. To send to AutoCAD users, save as DXF or DWG; to print or share, use [Plot](help:plot) or [Export](help:export).
