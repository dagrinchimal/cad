---
id: tutorial-easy-3d
type: tutorial
title: Tutorial: Your first 3D part (a pencil holder)
order: 3
synonyms: [easy 3d, first 3d model, 3d printing tutorial, tinkercad style, pencil holder, beginner 3d]
related: [dropshape, makehole, combine, size3d, presspull, shapespanel, 3d-modeling]
glossary: [solid, hole shape, handle, push/pull]
---
You'll make a pencil holder for a 3D printer the easy way: drop in a box, drop in three hole shapes, and combine them. Then you'll add a pen groove by drawing right on the top and pushing it in. About 10 minutes, no sketching skills needed.

**How to read the steps:** you can do each step with the mouse (described in the text) or by typing the grey box, one line at a time, pressing **Enter** after each line. Click **Show me where** above a box to see a ghost outline of where things go, in orange.

## 1. Into 3D
Make sure the units are **Millimeters**. Go to the **3D** tab and click **3D View** (or type `VIEW3D` and `SE`). The **Shapes** panel opens on the left. Use the cube in the top right corner to turn the view: click **TOP**, **FRONT**, or a corner. The little house goes back to the starting view.

```commands
<units mm>
VIEW3D
SE
```

## 2. The block
Drag a **Box** from the Shapes panel onto the ground. Click it: small square **handles** appear. Drag the side handles to stretch it and the blue one on top to make it taller, or click a size number and type it. Make it 80 wide, 40 deep and 30 tall, with its corner at 0,0.

Typed: [Add Shape](help:dropshape), Box, **Size** 80,40,30, placed with its center at 40,20 on the ground.

```commands
<hint box 0,0,0 80,40,30>
DROPSHAPE
Box
S
80,40,30
40,20,0
<Enter>
```

## 3. Three holes
Drag a **Cylinder hole** (the grey ones in the panel) onto the top of the block. Holes are see-through grey: they only cut once you combine. Make it 16 across and 30 tall, sitting 5 up from the bottom so the pencils have a floor. Do it three times, 20 apart.

Typed: three cylinder holes 16 × 16 × 30 at x 20, 40 and 60.

```commands
<hint circle 20,20 8 30>
<hint circle 40,20 8 30>
<hint circle 60,20 8 30>
DROPSHAPE
H
CY
S
16,16,30
20,20,5
40,20,5
60,20,5
<Enter>
```

## 4. Combine
Select the block and the three holes (click each, or drag a window around them in the plan), then click **Combine**. The holes are cut out of the block. Combine is like gluing everything together and punching out the holes in one go. Typing? Press **Esc** first so only what you pick is used.

```commands
<Esc>
COMBINE
ALL
<Enter>
```

## 5. A pen groove, drawn on the top
Start [Rectangle](help:rectang) and click on the top of the block: you're now drawing **on that face**. Draw a rectangle along the front edge. Then start **Press/Pull**, click inside the rectangle and move the mouse down: a live preview shows the groove. Click (or type 4) to push it 4 deep.

Typed: a sketch level with the top (XY plane, 30 up), the rectangle, then Press/Pull from above.

```commands
<hint rect 5,2 75,8 30>
SKETCH
Offset
XY
30
RECTANG
5,2
75,8
EXITSKETCH
PRESSPULL
<click 40,5>
-4
```

## 6. Check it and print it
[Mass Properties](help:massprop) shows the volume (multiply by your filament's density for the weight). Then [Export](help:export) › **3MF (3D printing)** or **STL** and open the file in your slicer.

```commands
MASSPROP
ALL
<Enter>
```

**Done!** You built a real part with four ideas: shapes, holes, combine, and push/pull. Next, try the [machined part tutorial](help:tutorial-machined-part) to see sketches, dimensions and shop drawings, or read [3D modeling](help:3d-modeling).
