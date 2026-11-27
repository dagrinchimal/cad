---
id: view3d
type: command
title: 3D View
command: VIEW3D
synonyms: [isometric, iso view, front view, side view, look at model]
related: [orbit, plan, vscurrent, 3d-modeling]
glossary: [isometric, view]
---
Switches to the 3D view, looking from a standard direction.

## How to use
1. Start **3D View** and pick a direction: **Top**, **Bottom**, **Front**, **BAck**, **Left**, **Right**, or an isometric corner **SW**, **SE**, **NE**, **NW** (press Enter for SW iso).
2. Type `P` (**Perspective**) for a natural-looking view with depth, `PA` (**PArallel**) to go back to a measured, parallel view.

## In the 3D view
- **Drag** with the left button to turn the model around (when no command is asking for a pick).
- **Middle-drag** or **right-drag** to pan, **wheel** to zoom, **double-click the wheel** to fit everything.
- Commands work here too: click faces, edges and points on the solids; clicks on empty space land on the ground (z = 0).
- **Drawing tools draw on what you click first:** start Line, Rectangle or Circle and click on a flat face, and you're drawing on that face (a sketch named Face1, Face2… is made for it); click empty space to draw on the ground.
- **Distances follow the mouse** when they have a direction (Press/Pull, Extrude height, Box and Cylinder height), with a live preview. Click, or type the value.
- **The view cube** (top right): click a face for that view, a corner for an iso view, the house for the starting view.
- **Click a solid** to select it: handles let you stretch, lift and drag it, and a small toolbar offers the tools for what you clicked (Push/Pull, Round, Hollow, Make hole, Combine…). Right-click for the same toolbar.
- **Shapes** can be dragged in from the [Shapes panel](help:shapespanel).
- Type [Plan](help:plan) to go back to the flat view, where 2D drawing tools work.
