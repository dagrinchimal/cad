---
id: block
type: command
title: Create Block
command: BLOCK
synonyms: [symbol, make symbol, reusable part, component, define block]
related: [insert, attdef, explode, group]
glossary: [block, insertion point, attribute]
---
Turns objects into a named **block**: a symbol you can insert many times. Change the block definition and every copy changes.

## How to use
1. Draw the symbol (e.g. a door) on layer 0. Add [attributes](help:attdef) for fill-in text if needed.
2. Start **Create Block** (`B`) and type a name.
3. Click the insertion base point (the point you'll place it by, e.g. the hinge).
4. Select the objects and press **Enter**.
5. Choose what happens to the originals: **Convert** (replace them with the block, the default), **Retain** (keep them as they are), or **Delete**.

## Tips
- Objects on layer 0 with color ByBlock take the color of each inserted copy.
- Using an existing name asks whether to redefine that block.
