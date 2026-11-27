---
id: 3d-modeling
type: concept
title: 3D modeling
order: 12
synonyms: [3d, solids, solid modeling, 3d printing, make a 3d part, model in 3d]
related: [sketch, extrude, revolve, subtract, presspull, filletedge, view3d, viewbase, export]
glossary: [solid, sketch, extrude, profile, drawing view]
---
3D here is **direct modeling**: you make solids and then edit them directly — extrude, cut, round edges, push faces. There's no feature history to manage; what you see is the part.

## The basic workflow
1. **Draw outlines** in the plan or on a [sketch](help:sketch) (a drawing plane in 3D: top, front, side, offset, or on a face of a solid). All the 2D tools work on sketches, including constraints.
2. **Make solids** with [Extrude](help:extrude), [Revolve](help:revolve), [Sweep](help:sweep) or [Loft](help:loft), or start from a [Box](help:box), [Cylinder](help:cylinder) and friends.
3. **Combine and cut** with [Union](help:union), [Subtract](help:subtract), [Intersect](help:intersect), or Extrude's **Join** / **Cut** / **Through all** options.
4. **Finish** with [Fillet Edge](help:filletedge), [Chamfer Edge](help:chamferedge), [Shell](help:shell), [Press/Pull](help:presspull) and [Slice](help:slice).
5. **Check** with [Mass Properties](help:massprop).
6. **Document** it with [Base View](help:viewbase): front/top/side views on a sheet with hidden lines.
7. **Send** it: [Export](help:export) as STEP for other CAD programs, STL or 3MF for 3D printing, glTF or OBJ for viewers.

## Seeing it in 3D
Type [3D View](help:view3d) (or `VIEW3D`, then `SE`) for an isometric view, [Orbit](help:orbit) to turn it around, [Plan](help:plan) to go back to the flat view. In the plan, solids show as their outline seen from above.

| In the 3D view | Does |
|---|---|
| Left-drag | Orbit (turn the model) |
| Middle-drag or right-drag | Pan |
| Wheel | Zoom at the cursor |
| Double-click wheel | Fit everything |
| Click | Pick a face, edge, point or solid for the current command; select when idle |

[Visual Style](help:vscurrent) switches between wireframe, hidden-line, shaded and x-ray.

## Heights
Points have an elevation. Type `x,y,z` (e.g. `0,0,20`) to start a box or cylinder above the ground, or click on a solid's face in the 3D view to start on it. Clicks on empty space land on the ground (z = 0).

## Where solids live
Solids are always in the model. Sketches are listed as tabs (✎) next to the layouts. Solids are saved inside the `.cadz` file as exact shapes (BREP), not triangles, so nothing is lost.

## Files
| Format | Open | Export | Use for |
|---|---|---|---|
| STEP (`.step`, `.stp`) | yes | yes | Other CAD programs. Exact shapes, colors and names |
| IGES (`.igs`) | yes | yes | Older CAD/CAM programs. Exact shapes |
| STL | yes | yes | 3D printing (triangles, no color) |
| 3MF | – | yes | Modern 3D printing (units and colors) |
| glTF (`.glb`) | – | yes | Web viewers, AR, Blender, Windows 3D Viewer |
| OBJ | – | yes | Almost any 3D program |

DXF, DWG and PDF exports show solids as their outline from above; for proper drawings use [Base View](help:viewbase) and export the layout.
