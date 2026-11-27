---
id: viewbase
type: command
title: Base View
command: VIEWBASE
synonyms: [drawing views, orthographic, 2d drawing from 3d, shop drawing, projected view]
related: [viewupdate, layouts, 3d-modeling]
glossary: [drawing view, projected view, hidden line]
---
Puts 2D drawing views of your solids on a layout sheet: front, top, side and isometric, with hidden edges dashed. These are the views a machinist or builder works from.

## How to use
1. Start **Base View**. If you're in the model, it switches to a layout sheet (making one if needed).
2. Choose the base view, usually **Front**.
3. Type the scale (paper size per model size: `1` is full size, `0.5` is 1:2). Press Enter for the suggested scale.
4. Click where the view goes.
5. Click around it for **projected views**: straight above for the Top view, to the right for the Right view, diagonally for an iso view. Press Enter when done.

## Tips
- Views use third-angle projection (the North American standard): the top view sits above the front view.
- Visible edges go on layer **View visible** (0.5 mm), hidden edges on **View hidden** (dashed). Change those layers to restyle every view.
- Dimension the views on the sheet with the normal dimension tools.
- After changing the solid, run [Update Views](help:viewupdate).
