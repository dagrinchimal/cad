---
id: snaps
type: concept
title: Snaps and tracking
order: 4
synonyms: [object snap, osnap, snap to endpoint, snap to midpoint, tracking, line up, polar, ortho, grid snap]
related: [dsettings, coordinates, line]
glossary: [object snap, polar tracking, ortho, object snap tracking, grid]
---
Drawing aids lock the cursor onto exact points and directions. Turn them on and off with the buttons in the status bar or the F-keys; set them up in [Drafting Settings](help:dsettings).

## Object snap (F3)
While a command asks for a point, the cursor jumps to nearby special points and shows a marker and a tooltip:
- **Endpoint** (square), **Midpoint** (triangle), **Center** (circle), **Intersection** (×), **Perpendicular**, **Tangent**, **Quadrant** (the 0°/90°/180°/270° points of circles), **Nearest**, **Node** (points), **Insertion** (of text and blocks), **Extension** (along the continuation of a line).

## Ortho (F8, or hold Shift)
Only horizontal and vertical directions from the last point.

## Polar tracking (F10)
The cursor locks onto angle steps (every 45° by default) with a dotted guide line; type a distance to go exactly that far along it.

## Object snap tracking (F11)
Rest the cursor on a snap point for half a second to "pick it up" (a small + appears). Then move away: dotted guides line you up horizontally or vertically with it, e.g. to start a line level with another object's corner.

## Grid (F7) and Snap (F9)
The grid shows dots at a spacing; Snap makes the cursor jump between them.
