---
id: tutorial-machined-part
type: tutorial
title: Tutorial: Draw a simple machined part
order: 2
synonyms: [machined part, mechanical drawing, plate with holes, metric tutorial, bracket]
related: [rectang, fillet, circle, arrayrect, dimordinate, dcdiameter, export]
glossary: [fillet, array, ordinate dimension, dimensional constraint]
---
You'll draw a 100 × 60 mm plate with rounded corners and three holes, dimension it the way machinists like, and drive the hole size with a constraint. About 15 minutes.

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

**Done.** In Phase 6 this tutorial continues in 3D: the plate becomes a solid you can export as STEP.
