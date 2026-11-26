---
id: dimlinear
type: command
title: Linear Dimension
command: DIMLINEAR
synonyms: [measure length, horizontal dimension, vertical dimension, dimension a wall, size line]
related: [dimaligned, dimstyle, dimordinate, value-editing, associativity]
glossary: [dimension, extension line, dimension line, associative]
---
Shows a horizontal or vertical distance with extension lines, arrows and the measured size.

## How to use
1. Start **Linear Dimension** (`DLI`).
2. Click the first point, then the second (snap to ends of the object).
   Or press **Enter** and click a line or polyline segment to dimension it.
3. Move the mouse to place the dimension line and click. Above or below gives a horizontal size, beside gives a vertical one.

## Options
- **Horizontal** (`H`) / **Vertical** (`V`): force the direction.
- **Text** (`T`): type your own text. `<>` stands for the measured value, e.g. `<> TYP`.

## It follows its object
The dimension is attached to the points you picked. Move or stretch the object and the dimension updates. Select the object and click the dimension's number to type a new size: the geometry changes to match ([Click a number to change a size](help:value-editing)).

## Tips
- Text size and arrows come from the [dimension style](help:dimstyle).
