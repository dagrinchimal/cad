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

### Base point
The point you pick to say "this spot moves to there" in Move, Copy, Rotate, Scale and Stretch. Pick something you can name, like a corner.

### Block
A named group of objects saved as one symbol (a door, a bolt, a title block) that you can insert many times. Change the block and every copy changes. See [Create Block](help:block).

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

### DWG
AutoCAD's own drawing file format. Reading and writing it needs the free ODA File Converter. See [File formats](help:file-formats).

### DXF
Drawing Exchange Format: the open AutoCAD format nearly every CAD program reads and writes.

### Extension line
The short lines from the object to a dimension line, showing what's being measured.

### Extents
The smallest rectangle around everything in the drawing. Zoom Extents fits it in the window.

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

### Hatch
A pattern or solid fill inside a closed area. See [Hatch](help:hatch).

### HPGL
HP-GL/2, the language of pen plotters and many vinyl and laser cutters. Colors become pen numbers.

### Inscribed
Drawn inside a circle: an inscribed polygon's corners touch the circle. The opposite is circumscribed.

### Insertion point
The point a block or text is placed by. For a block it's the base point chosen when the block was made.

### Island
An enclosed area inside a hatched area, like a column inside a room. Hatch leaves islands empty.

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

### PDF
Portable Document Format. Exports here are vector and true to scale: print at 100% and the drawing scale is right.

### Perpendicular
At a right angle (90°).

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

### Radius
The distance from a circle's center to its edge: half the diameter. Shown with R.

### Relative coordinates
A point measured from the last point instead of from the origin, written with `@`: `@100,0`.

### Ribbon
The band of tabs and buttons at the top of the window.

### Scale factor
A multiplier for size: 2 doubles, 0.5 halves.

### Spline
A smooth freeform curve through a set of points. See [Spline](help:spline).

### SVG
Scalable Vector Graphics: a vector image format for the web, Inkscape and laser cutters.

### Tangent
Touching a curve at one point without crossing it, so the two meet smoothly.

### Temporary dimension
The blue numbers shown when one object is selected. Click one to type a new size. See [Grips and numbers](help:value-editing).

### Text height
The height of capital letters, as measured in the drawing.

### Title block
The labeled box on a sheet with the title, scale, date, sheet number and who drew it.

### Units
How lengths are shown and read: millimeters, fractional inches or feet-and-inches. See [Units](help:units-and-typing).

### Vertex
A corner point of a polyline. Plural: vertices.

### Viewport
A window on a layout sheet showing the model at a set scale. See [Viewport](help:mview).

### Window selection
A selection box dragged from left to right (solid outline): only objects completely inside are selected.
