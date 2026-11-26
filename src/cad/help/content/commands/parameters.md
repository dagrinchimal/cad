---
id: parameters
type: command
title: Parameters
command: PARAMETERS
synonyms: [formulas, variables, constraint values, d1, equations, driving dimensions list]
related: [dclinear, constraints, constraintstatus]
glossary: [dimensional constraint, parameter]
---
Lists every dimensional constraint (`d1`, `rad1`, `ang1`…) with its value, and lets you change values or write formulas.

## How to use
1. Start **Parameters** (`PAR`).
2. Change a value in the **Expression** column: a number in any unit (`3'-6"`, `150`), or a formula using other names, like `d1*2` or `(d2 - 50)/2`.
3. The drawing updates as soon as you confirm.

## Tips
- A formula that refers to itself, or a value the shape can't reach, is refused with a message.
