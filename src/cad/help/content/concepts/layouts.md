---
id: layouts
type: concept
title: Layouts, viewports and printing
order: 10
synonyms: [paper space, sheets, print to scale, title block, plot to scale, drawing sheet]
related: [layout, mview, pagesetup, plot, export]
glossary: [layout, viewport, paper space, model space, title block]
---
You draw in **model space** at real size: a 30-foot wall is 30 feet long. To print, either:

- **Plot the model directly**: [Plot](help:plot) › What to plot: Model, choose paper and a scale (e.g. 1/4" = 1'-0"). Quick for simple prints.
- **Use a layout sheet**: a sheet of paper (tab at the bottom) with a border, title block, and one or more **viewports** showing the model at a scale. Best for real drawing sets.

## Making a sheet
1. Click **+** next to the tabs (or [Layout](help:layout) › New). It comes with a border, a title block and a viewport.
2. Select the viewport edge; in Properties choose its **Scale**.
3. Double-click the title block to fill in title, date, scale, sheet number.
4. Add notes or a second viewport with [Viewport](help:mview).
5. [Plot](help:plot) it (it prints at 1:1 on its paper size) or [Export](help:export) it to PDF.

## Text and dimension sizes
Text and dimensions drawn on the layout sheet are drawn at paper size (2.5 mm text is 2.5 mm). Those drawn in the model must be scaled up: at 1/4" = 1'-0" (×48), 1/8" text is 6" tall; set the dimension style's overall scale to 48.
