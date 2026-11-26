---
id: troubleshooting
type: concept
title: When something goes wrong
order: 15
synonyms: [problem, not working, help, error, hatch not working, can't select, lost drawing, crash, blank screen]
related: [recover, options, zoomextents, hatch, layer]
glossary: []
---
**I can't see my drawing.** Double-click the mouse wheel (Zoom Extents). Check the layers aren't turned off or frozen.

**I can't select or change something.** Its layer may be locked (Layer Properties › Lock). Objects on frozen or off layers can't be selected.

**Hatch says no closed area.** The outline has a gap. Zoom in on the corners; close gaps with [Fillet](help:fillet) (radius 0) or [Extend](help:extend). Or use **Select objects** with a closed polyline.

**A command won't accept my number.** Read the command line: it says what it expects. In feet-inch drawings a bare number is feet (`12` = 12').

**Snaps grab the wrong point.** Turn off snaps you don't need in [Drafting Settings](help:dsettings), or zoom in.

**The program closed unexpectedly.** Start it again; it offers your autosaved drawings ([Recover](help:recover)).

**The display looks wrong or flickers.** In [Options](help:options) set Display engine to "Software (compatible)" and restart.

**DWG won't open.** Install the free ODA File Converter ([File formats](help:file-formats)), or ask for a DXF.

**My change was refused because of constraints.** The constraints can't all be true with that value. Change another value first, or remove a constraint with [Delete Constraints](help:delconstraint).
