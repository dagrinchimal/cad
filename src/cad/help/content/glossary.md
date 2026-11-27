# Glossary

### Arc
A piece of a circle. Defined by its center, radius and start and end angles. See [Arc](help:arc).

### Array
Copies of objects in a regular pattern: rows and columns ([Rectangular Array](help:arrayrect)) or around a center ([Polar Array](help:arraypolar)). Arrays here stay live: edit the original and the copies follow.

### Associative
Linked to the objects it describes. An associative dimension or hatch updates when its objects change. See [Associativity](help:associativity).

### Attribute
A fill-in text field inside a block, such as a door number or a title block's DATE. You're asked for its value when you insert the block. See [Define Attribute](help:attdef).

### Autosave
A safety copy the program saves every few minutes, so you can [recover](help:recover) your work after a crash.

### Axis
A straight line something turns around (for [Revolve](help:revolve) or [3D Rotate](help:3drotate)), or one of the drawing's X, Y and Z directions.

### Base point
The point you pick to say "this spot moves to there" in Move, Copy, Rotate, Scale and Stretch. Pick something you can name, like a corner.

### Block
A named group of objects saved as one symbol (a door, a bolt, a title block) that you can insert many times. Change the block and every copy changes. See [Create Block](help:block).

### Boolean
Combining solids like shapes in a Venn diagram: [Union](help:union) adds, [Subtract](help:subtract) takes away, [Intersect](help:intersect) keeps the overlap.

### Boundary
The closed outline around an area, e.g. the walls around a room. Hatches fill boundaries; [Boundary](help:boundary) traces one into a polyline.

### Boundary edge
An object that another one is extended up to. In [Extend](help:extend) every object can be a boundary edge.

### Bulge
How much a polyline segment curves. 0 is straight; 1 is a half circle. You don't type bulges; you draw arcs in [Polyline](help:pline) and the program works them out.

### ByLayer
A setting meaning "use the layer's". An object whose color is ByLayer takes its layer's color. ByBlock means "use the color of the block it's inserted as".

### Chamfer
A straight cut across a corner, like a bevel. See [Chamfer](help:chamfer).

### Circumscribed
Drawn around a circle: a circumscribed polygon's sides touch the circle. The opposite is inscribed.

### Command alias
A short name for a command, like `L` for Line or `TR` for Trim. See [Keyboard shortcuts](help:keyboard).

### Command line
The box at the bottom where you type commands and values, and where commands tell you what they need next. It also searches: type what you want to do.

### Concentric
Sharing the same center.

### Coordinates
A point's position as x,y measured from the origin (0,0). x grows to the right, y grows upward. See [Typing coordinates](help:coordinates).

### Crossing window
A selection box dragged from right to left (dashed outline). It selects everything it touches, not only what's fully inside.

### Cutting edge
An object that another one is trimmed against. In [Trim](help:trim) every object is a cutting edge.

### Datum
The reference point or edge that measurements start from, like the corner of a machined part at 0,0.

### Degrees of freedom
The number of independent ways a constrained shape can still move or change size. 0 means it's fully defined. See [Constraint Status](help:constraintstatus).

### Diameter
The distance across a circle through its center: twice the radius. Shown with Ø.

### Dimension
A measurement shown on the drawing: extension lines, a dimension line with arrows, and the size. See [Linear Dimension](help:dimlinear).

### Dimension line
The line with arrowheads at each end that a dimension's text sits on.

### Dimension style
The settings that control how dimensions look: text size, arrows, gaps, decimal places and overall scale. See [Dimension Style](help:dimstyle).

### Dimensional constraint
A constraint that locks a size (a distance, radius or angle) to a value or formula. Change the value and the shape changes. See [Constraints](help:constraints).

### DIMSCALE
AutoCAD's name for the dimension style's overall scale: it multiplies every dimension size so dimensions in a scaled model print at the right size.

### Displacement
How far and in which direction something moves, as x,y.

### Drawing view
A 2D view of a 3D part (front, top, side, iso) on a layout sheet, made by [Base View](help:viewbase). Hidden edges are dashed.

### DWG
AutoCAD's own drawing file format. Reading and writing it needs the free ODA File Converter. See [File formats](help:file-formats).

### DXF
Drawing Exchange Format: the open AutoCAD format nearly every CAD program reads and writes.

### Edge
Where two faces of a solid meet, like the corner line of a box. [Fillet Edge](help:filletedge) rounds edges.

### Extension line
The short lines from the object to a dimension line, showing what's being measured.

### Extents
The smallest rectangle around everything in the drawing. Zoom Extents fits it in the window.

### Extrude
Give a flat outline height to make a solid, like pushing dough through a shaped hole. See [Extrude](help:extrude).

### Face
One surface of a solid: the top of a box, the inside of a hole. [Press/Pull](help:presspull) moves faces.

### Fence
A line you draw in Trim or Extend: every object it crosses is trimmed or extended where it crosses.

### Fillet
A rounded corner made with an arc. With radius 0, a fillet makes a clean sharp corner. See [Fillet](help:fillet).

### Fit point
A point a spline passes through.

### Freeze
Hide a layer and skip it completely when redrawing, which also makes big drawings faster. Frozen objects can't be selected or printed.

### Geometric constraint
A rule between objects, such as parallel, perpendicular, horizontal, tangent or coincident, that stays true when you edit them. See [Constraints](help:constraints).

### Grid
Evenly spaced dots behind the drawing (F7) to help judge sizes. With Snap (F9) the cursor jumps between them.

### Grip
The small blue squares on a selected object. Click one to move that point. See [Grip editing](help:gripedit).

### Group
Objects tied together so clicking one selects them all, while each stays editable. See [Group](help:group).

### Handle
A small square or cone on a selected solid in the 3D view. Drag it to stretch, lift or resize the solid.

### Hatch
A pattern or solid fill inside a closed area. See [Hatch](help:hatch).

### Hidden line
An edge you couldn't see from where you're looking because the part is in the way. Drawing views show them dashed.

### Hole shape
A see-through grey shape that cuts away material where it overlaps solids, once you [Combine](help:combine) them. Tinkercad calls these holes.

### HPGL
HP-GL/2, the language of pen plotters and many vinyl and laser cutters. Colors become pen numbers.

### Inscribed
Drawn inside a circle: an inscribed polygon's corners touch the circle. The opposite is circumscribed.

### Insertion point
The point a block or text is placed by. For a block it's the base point chosen when the block was made.

### Intersect
Keep only where solids overlap. See [Intersect](help:intersect).

### Island
An enclosed area inside a hatched area, like a column inside a room. Hatch leaves islands empty.

### Isometric
A 3D view looking from a corner, so the top and two sides show equally. See [3D View](help:view3d).

### Justification
Which point of a text the insertion point is: left, center, right, middle, top-left and so on.

### Layer
A named category of objects with its own color, linetype and lineweight, which can be hidden, locked or kept off prints. See [Layers](help:layers).

### Layout
A paper sheet for printing, with a border, title block and viewports showing the model at a scale. Also called paper space. See [Layouts](help:layouts).

### Leader
An arrow pointing at something, with a note. See [Leader](help:leader).

### Linetype
The dash pattern of a line: continuous, dashed, center (long-short), hidden and so on.

### Lineweight
How thick a line prints, in millimeters (0.25 mm is a normal line; 0.5 mm a heavy one). Turn on LWT in the status bar to see them on screen.

### Loft
A solid that blends from one outline to another. See [Loft](help:loft).

### Major axis
The longest line across an ellipse, through its center. The minor axis is the shortest one.

### Minor axis
The shortest line across an ellipse, through its center, at right angles to the major axis.

### Mirror line
The line objects are reflected across in [Mirror](help:mirror).

### Model space
Where you draw, at real size. Layouts show model space through viewports.

### Node
A point object (drawn with [Point](help:point)). The Node snap grabs points.

### Object snap
Also: osnap
Snapping the cursor exactly onto special points of objects: ends, middles, centers, intersections. See [Snaps and tracking](help:snaps).

### Object snap tracking
Dotted guide lines from snap points you've hovered over, to line new points up with them (F11).

### Offset
A parallel copy at a set distance. See [Offset](help:offset).

### Ordinate dimension
A dimension showing a point's X or Y distance from the origin, used on machined parts. See [Ordinate Dimension](help:dimordinate).

### Origin
The point 0,0, where coordinates are measured from.

### Ortho
A mode (F8, or hold Shift) that restricts drawing to horizontal and vertical directions.

### Paper space
The space of a layout sheet, measured in paper units. Text on a layout is drawn at the size it prints.

### Parameter
A named value of a dimensional constraint (`d1`, `rad1`…) that other constraints can use in formulas. See [Parameters](help:parameters).

### Path
The line or curve a [Sweep](help:sweep) follows.

### PDF
Portable Document Format. Exports here are vector and true to scale: print at 100% and the drawing scale is right.

### Perpendicular
At a right angle (90°).

### Plan
The view from straight above: the normal flat drawing view. See [Plan View](help:plan).

### Plane
A flat, endless surface in 3D, like a sheet of glass. Sketches are drawn on planes.

### Plot
To print, on paper or to a PDF. See [Plot](help:plot).

### Polar coordinates
A point given by distance and angle, like `@100<30`: 100 away at 30°.

### Polar tracking
A mode (F10) that locks the cursor onto angle steps, such as every 45°, with a dotted guide.

### Polyline
One object made of connected straight and curved segments. See [Polyline](help:pline).

### Precision
How many decimal places, or which smallest fraction (like 1/16"), numbers are shown with.

### Primitive
A basic ready-made solid: box, cylinder, cone, sphere, torus or wedge.

### Profile
The closed outline you extrude, revolve, sweep or loft into a solid: a cross-section of the part.

### Projected view
A drawing view lined up with another one: the top view directly above the front view, the side view beside it.

### Push/Pull
Dragging a flat face or a drawn shape in or out to add or remove material. See [Press/Pull](help:presspull).

### Radius
The distance from a circle's center to its edge: half the diameter. Shown with R.

### Reference geometry
The grey lines on a sketch showing your solids' edges seen square-on, to snap to. They're locked and don't print.

### Relative coordinates
A point measured from the last point instead of from the origin, written with `@`: `@100,0`.

### Revolve
Spin an outline around an axis to make a round solid. See [Revolve](help:revolve).

### Ribbon
The band of tabs and buttons at the top of the window.

### Scale factor
A multiplier for size: 2 doubles, 0.5 halves.

### Shell
A hollowed-out solid with walls of even thickness. See [Shell](help:shell).

### Sketch
A flat drawing plane placed in 3D (top, front, side, offset or on a face). You draw on it with the normal 2D tools, then extrude or revolve. See [Sketch](help:sketch).

### Slice
Cut a solid in two with a flat plane. See [Slice](help:slice).

### Solid
A closed 3D shape with volume, like a real part. Made with [Extrude](help:extrude), [Box](help:box) and so on. See [3D modeling](help:3d-modeling).

### Spline
A smooth freeform curve through a set of points. See [Spline](help:spline).

### STEP
The standard file format for exchanging exact 3D parts between CAD programs (`.step` or `.stp`).

### STL
A 3D file made of triangles, used by 3D printers. Curved faces become many small flat ones.

### Subtract
Cut one solid out of another. See [Subtract](help:subtract).

### SVG
Scalable Vector Graphics: a vector image format for the web, Inkscape and laser cutters.

### Sweep
Move an outline along a path to make a solid. See [Sweep](help:sweep).

### Tangent
Touching a curve at one point without crossing it, so the two meet smoothly.

### Temporary dimension
The blue numbers shown when one object is selected. Click one to type a new size. See [Grips and numbers](help:value-editing).

### Text height
The height of capital letters, as measured in the drawing.

### Title block
The labeled box on a sheet with the title, scale, date, sheet number and who drew it.

### Union
Join solids into one. See [Union](help:union).

### Units
How lengths are shown and read: millimeters, fractional inches or feet-and-inches. See [Units](help:units-and-typing).

### Vertex
A corner point of a polyline. Plural: vertices.

### View
The direction you're looking at the model from: plan (top), front, side or isometric.

### View cube
The cube in the top right of the 3D view. Click a face or corner to look from that side.

### Viewport
A window on a layout sheet showing the model at a set scale. See [Viewport](help:mview).

### Visual style
How solids look in the 3D view: wireframe, hidden lines, shaded, shaded with edges or x-ray. See [Visual Style](help:vscurrent).

### Volume
How much space a solid fills, in mm³ or in³. See [Mass Properties](help:massprop).

### Window selection
A selection box dragged from left to right (solid outline): only objects completely inside are selected.
