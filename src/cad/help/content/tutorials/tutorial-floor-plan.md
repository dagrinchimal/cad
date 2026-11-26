---
id: tutorial-floor-plan
type: tutorial
title: Tutorial: Draw a simple floor plan
order: 1
synonyms: [floor plan, house plan, room layout, architectural tutorial, walls tutorial]
related: [rectang, offset, break, arc, hatch, text, dimlinear, layout, plot]
glossary: [layer, offset, hatch, dimension, layout]
---
You'll draw a 24' × 16' building with 6" walls, a partition with a door, a hatch, labels, dimensions and a printable sheet. About 20 minutes.

**How to read the steps:** each grey box is what to type, one line at a time, pressing **Enter** after each line.
`<Enter>` means just press Enter. `<click 12',0>` means click near that spot (snaps help), or type the coordinates instead.
Lines like `<units architectural>` or `<layer Walls>` are things to set in a dialog, described just above them.

## 1. Feet and inches
Click the units box at the bottom right of the window (or start [Units](help:units)) and choose **Architectural**. With the default Revit typing, a bare number means feet: `12` is 12', and `0 6` is 6".

```commands
<units architectural>
```

## 2. Layers
Open [Layer Properties](help:layer) and create these layers: **Walls** (lineweight 0.50 mm), **Doors** (color green), **Hatch** (color gray), **Text** and **Dims** (color yellow). Then make **Walls** current (the layer box on the Home tab).

```commands
<layer Doors 3>
<layer Hatch 8>
<layer Text 7>
<layer Dims 2>
<layer Walls 7 0.5>
```

## 3. Outer walls
Draw the outside of the building with [Rectangle](help:rectang), then make the 6" wall thickness with [Offset](help:offset): click the rectangle, then click inside it.

```commands
RECTANG
0,0
@24',16'
OFFSET
6"
<click 12',0>
<click 12',2'>
<Enter>
```

## 4. A partition with a door opening
Draw a partition across the inside, then cut a 3' opening in it with [Break](help:break): click the partition at the first edge of the opening, then the second.

```commands
LINE
12',6"
12',15'6"
<Enter>
BREAK
<click 12',3'>
12',6'
```

## 5. The door
Switch to the **Doors** layer. Draw the door leaf standing open, and its swing with [Arc](help:arc) › Center: the hinge, the open end, then the closed end.

```commands
<layer Doors>
LINE
12',3'
@3',0
<Enter>
ARC
C
12',3'
15',3'
12',6'
```

## 6. Hatch the walls
Switch to **Hatch**. With [Hatch](help:hatch), set the pattern to ANSI31 at scale 12 and click inside the wall thickness.

```commands
<layer Hatch>
HATCH
P
ANSI31
SC
12
<click 12',3">
<Enter>
```

## 7. Room names
Switch to **Text**. With [Single Line Text](help:text), justify to Middle Center, place each name in its room, 9" tall.

```commands
<layer Text>
TEXT
J
MC
6',12'
9"
0
LIVING ROOM
<Enter>
TEXT
J
MC
18',12'
9"
0
KITCHEN
<Enter>
```

## 8. Dimensions
Switch to **Dims**. Because the plan will print at 1/4" = 1'-0" (48 times smaller), open [Dimension Style](help:dimstyle) and set **Overall scale** to 48. Then add two [linear dimensions](help:dimlinear).

```commands
<layer Dims>
<dimscale 48>
DLI
0,0
24',0
12',-3'
DLI
24',0
24',16'
27',8'
```

## 9. Make the building longer
Plans change. With [Stretch](help:stretch), drag a **crossing** window from right to left around the right-hand wall only, then move it 2' to the right. The walls get longer, the hatch follows, and the 24' dimension becomes 26'.

```commands
STRETCH
<crossing 25',17' 23',-1'>
24',0
@2',0
```

Another way to do this: select the outer rectangle and click its blue length number (see [Grips and numbers](help:value-editing)).

## 10. A sheet to print
Make a layout sheet. It comes with a border, a title block and a viewport showing your plan.

```commands
LAYOUT
N
A-101
```

Click the **A-101** tab, select the viewport's edge, and in the Properties panel set **Scale** to `1/4" = 1'-0"`. Double-click the title block to fill in the title and date. Then [Plot](help:plot) (Ctrl+P): pick a printer or "Save as a PDF file", check the preview, and click Print.

**Done.** Save with Ctrl+S. To send it to an AutoCAD user, use File › Save As and pick DXF or DWG.
