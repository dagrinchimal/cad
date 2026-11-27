---
id: tutorial-machined-part
type: tutorial
title: Tutorial: Draw a simple machined part
order: 2
synonyms: [machined part, mechanical drawing, plate with holes, metric tutorial, bracket]
related: [rectang, fillet, circle, arrayrect, dimordinate, dcdiameter, export, extrude, sketch, viewbase, 3d-modeling]
glossary: [fillet, array, ordinate dimension, dimensional constraint, solid, sketch, extrude]
---
You'll draw a 100 × 60 mm plate with rounded corners and three holes, dimension it the way machinists like, drive the hole size with a constraint, then turn it into a 3D solid with a pocket, make shop drawings from it and export it as STEP. About 25 minutes.

**How to read the steps:** each grey box is what to type, one line at a time, pressing **Enter** after each line.
`<Enter>` means just press Enter; `<click 50,0>` means click near that spot; `<select 26,30>` means click that object to select it before the next command.

## 1. Millimeters and a layer
Make sure the units are **Millimeters** (units box at the bottom right). Create a layer **Outline** with lineweight 0.50 mm and make it current, and a layer **Dims** in yellow.

```commands
<units mm>
<layer Dims 2>
<layer Outline 7 0.5>
```

## 2. The plate
A [Rectangle](help:rectang) from 0,0, then round all four corners at once with [Fillet](help:fillet) › Radius 10 › Polyline.

```commands
RECTANG
0,0
@100,60
FILLET
R
10
P
<click 50,0>
```

## 3. Three holes
One 12 mm [circle](help:circle), then a live [array](help:arrayrect) of 1 row and 3 columns, 30 mm apart.

```commands
CIRCLE
20,30
D
12
<select 26,30>
ARRAYRECT
1
3
30
```

## 4. Dimensions from one corner
Switch to **Dims**. [Ordinate dimensions](help:dimordinate) give each hole's distance from the corner at 0,0; a [diameter dimension](help:dimdiameter) gives the hole size; [linear dimensions](help:dimlinear) the overall size.

```commands
<layer Dims>
DOR
20,30
20,75
DOR
50,30
50,75
DOR
80,30
80,75
DDI
<click 26,30>
40,45
DLI
0,0
100,0
50,-15
DLI
100,0
100,60
115,30
```

## 5. Drive the hole size
Lock the hole's diameter with a [diameter constraint](help:dcdiameter) and give it a new value, 14. All three holes change (the array follows its original), and the Ø dimension updates.

```commands
DCD
<click 26,30>
14
```

Open [Parameters](help:parameters) to see it as `dia1`. Try typing `dia1` values like `10` or `16`.

## 6. Send it
[Export](help:export) a PDF at 1:1 on A4 (Format PDF, What: Model, Paper ISO A4, Scale 1:1), and a DXF for the machine shop (Format AutoCAD DXF).

## 7. Make it a solid
[Extrude](help:extrude) the plate 10 mm thick. Using **Area** (`A`) and clicking inside the plate (not in a hole) takes the outline *and* the three holes in one go, and keeps your 2D drawing as it is.

```commands
<layer Outline>
EXTRUDE
A
<click 50,10>
<Enter>
10
```

Type `VIEW3D` and `SE` (or click **3D View** on the **3D** tab) to look at it in 3D. Drag with the left mouse button to turn it around; type `PLAN` to come back to the flat view.

## 8. A pocket from a sketch
A [sketch](help:sketch) is a flat drawing plane placed in 3D. Make one level with the top of the plate (the XY plane, 10 mm up), draw the pocket outline on it, and extrude it **Cut** 4 mm down into the plate. On a sketch, the edges of your solids show as grey reference lines you can snap to.

```commands
SKETCH
Offset
XY
10
RECTANG
35,44
@30,10
<select 35,49>
EXTRUDE
C
-4
EXITSKETCH
```

Check it with [Mass Properties](help:massprop): the volume is the plate minus the holes and the pocket.

```commands
MASSPROP
ALL
<Enter>
```

## 9. Shop drawings from the solid
[Base View](help:viewbase) puts 2D views of the solid on a layout sheet, with hidden edges dashed. Place the **Front** view at 1:1, then click above it for the **Top** view and up-right for an iso view. Press Enter when done.

```commands
VIEWBASE
Front
1
<click 100,150>
<click 100,230>
<click 270,230>
<Enter>
```

You can dimension the views on the sheet like any drawing. If you change the solid later, [Update Views](help:viewupdate) redraws them.

## 10. Send the 3D model
[Export](help:export) › Format **STEP 3D model** gives the machine shop the exact 3D part; **STL** or **3MF** is for a 3D printer.

**Done.** You've gone from a 2D sketch to a dimensioned plate, a 3D part, shop drawings and a STEP file. See [3D modeling](help:3d-modeling) for everything else you can do in 3D.
