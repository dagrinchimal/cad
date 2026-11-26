---
id: hatch
type: command
title: Hatch
command: HATCH
synonyms: [fill, pattern, shading, solid fill, cross hatch, section lines, poche, color a room]
related: [boundary, explode, layer, associativity]
glossary: [hatch, island, associative, boundary]
---
Fills an enclosed area with a pattern (like diagonal section lines) or a solid color.

## How to use
1. Start **Hatch**.
2. Click inside each area you want filled. Holes inside it (islands) are left empty automatically.
3. Press **Enter** to finish.

## Options
- **Pattern** (`P`): type a pattern name. `SOLID` is a solid fill; `ANSI31` is the common 45° lines; others: ANSI32–ANSI38, LINE, NET, NET3, DOTS and more.
- **Scale** (`SC`): makes the pattern bigger or smaller. In feet-inch drawings try 12–48.
- **Angle** (`A`): turns the pattern.
- **Select objects** (`S`): pick closed objects (circles, closed polylines) instead of clicking inside.

## It follows its shape
A hatch remembers what it was made from. Stretch, move or resize the walls and the hatch updates. See [Associativity](help:associativity).

## Tips
- If nothing is found where you click, the area isn't fully closed: look for a small gap and close it with [Extend](help:extend) or [Fillet](help:fillet) at radius 0.
- Put hatches on their own layer so you can lock or hide them.
