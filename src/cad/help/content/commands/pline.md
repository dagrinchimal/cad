---
id: pline
type: command
title: Polyline
command: PLINE
synonyms: [connected lines, outline, closed shape, one piece]
related: [line, rectang, offset, explode, join, fillet]
glossary: [polyline, bulge, vertex]
---
Draws one object made of connected straight and curved segments. A polyline moves, offsets and fillets as one piece, and a closed one can be hatched directly.

## How to use
1. Start **Polyline** and click the start point.
2. Click or type the next points.
3. Press **Enter** to finish, or choose **Close** to join back to the start.

## Options
- **Arc** (`A`): the next segments are arcs that continue smoothly from the last segment. Click their end points.
- **Line** (`L`): back to straight segments.
- **Close** (`C`): joins the last point to the first and finishes.
- **Undo** (`U`): removes the last segment.

## Tips
- To change a corner later, click the polyline, then click a blue [grip](help:gripedit) and the new spot.
- Click a polyline and type new segment lengths into the blue numbers ([Click a number to change a size](help:value-editing)).
- [Explode](help:explode) turns a polyline into separate lines and arcs; [Join](help:join) does the opposite.
