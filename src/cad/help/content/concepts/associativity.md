---
id: associativity
type: concept
title: Associativity: things that follow their shapes
order: 8
synonyms: [associative dimensions, dimension updates, hatch follows boundary, live array, linked objects]
related: [hatch, dimlinear, arrayrect, value-editing, explode]
glossary: [associative]
---
Some objects remember what they belong to and update when it changes:

- **Dimensions** remember the points they measure. Move, stretch or grip-edit the wall and the dimension follows. Delete the wall and the dimension stays where it was, no longer linked.
- **Hatches** remember their boundary. Make the room bigger and the hatch grows. If the boundary opens up, the hatch keeps its last shape and stops following.
- **Arrays** are live. Change the original circle and every copy changes. Select the array to change rows, columns or spacing in the Properties panel.

The Properties panel shows "Associative: Yes" for linked dimensions and hatches.

## Breaking the link
[Explode](help:explode) turns a dimension, hatch or array into plain objects. DXF and DWG files can't store these links: dimensions and hatches stay, but stop following; arrays become separate copies.
