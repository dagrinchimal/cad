---
id: coordinates
type: concept
title: Typing sizes and coordinates
order: 2
synonyms: [exact point, type coordinates, relative coordinates, polar coordinates, direct distance, precise input, how to type a length]
related: [units-and-typing, line, snaps, id]
glossary: [coordinates, origin, relative coordinates, polar coordinates]
---
Whenever a command asks for a point, you can click or type.

| You type | It means |
|---|---|
| `100,50` | the point x = 100, y = 50 (measured from the origin 0,0) |
| `@100,50` | 100 right and 50 up **from the last point** |
| `@100<30` | 100 away from the last point, at 30° (0° is to the right, counter-clockwise is positive) |
| `100` | 100 in the direction the mouse points from the last point ("direct distance") |

When a command asks for a distance, radius or angle you can type it or click a point.

## Any unit, anywhere
In every drawing you can type `25.4mm`, `1"`, `2'`, `2'-6"`, `3'4.5`, `1 1/2"`. The drawing's units decide what a number **without** a unit means. See [Units](help:units-and-typing).

## Tips
- Combine with Ortho (**F8** or hold **Shift**) or polar tracking (**F10**) to point exactly along 0°, 90°, 45°…, then type the distance.
- Lengths can be negative in relative coordinates: `@-100,0` goes left.
