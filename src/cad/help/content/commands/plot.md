---
id: plot
type: command
title: Plot
command: PLOT
synonyms: [print, printer, print to scale, paper, hard copy, print pdf]
related: [export, pagesetup, layouts, mview]
glossary: [plot, viewport, layout]
---
Prints the model or a layout on a printer, or saves it as a PDF, with a live preview.

## How to use
1. Press **Ctrl+P**.
2. Pick the **Printer** (or "Save as a PDF file").
3. Choose **What to plot**: the model, a layout, or all layouts.
4. For the model: paper size, orientation and **Scale** ("Fit to paper", or e.g. `1:50` or `1/4" = 1'-0"`; you can type your own).
5. Choose **Colors** (as in the drawing, black only, or gray) and whether to use lineweights.
6. Check the preview and click **Print** (or **Save PDF**).

## Tips
- Layouts print at their own paper size, at 1:1, with each viewport at its scale.
- Layers whose **Plot** box is unticked in [Layer Properties](help:layer) don't print.
- In the printer's own settings, choose "actual size" / 100% (not "fit to page") so scales stay exact.
