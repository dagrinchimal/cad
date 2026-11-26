---
id: constraints
type: concept
title: Constraints
order: 9
synonyms: [parametric drawing, geometric constraints, dimensional constraints, design intent, keep parallel, driving dimensions]
related: [gccoincident, dclinear, parameters, constraintstatus, gcfix]
glossary: [geometric constraint, dimensional constraint, degrees of freedom, parameter]
---
Constraints are rules a shape keeps when you edit it.

- **Geometric constraints** (Parametric tab, left): coincident, parallel, perpendicular, horizontal, vertical, tangent, concentric, equal, collinear, symmetric, fix.
- **Dimensional constraints** (Parametric tab, middle): lock a distance, radius, diameter or angle to a value or a formula. They're named `d1`, `rad1`, `ang1`…; edit them in [Parameters](help:parameters).

When you edit a constrained object, the program moves the other objects just enough to keep every rule true. If a change can't satisfy all the rules, it's refused with a message, and nothing changes.

## A good way to work
1. Sketch the shape roughly.
2. Add geometric constraints (horizontal, perpendicular, coincident corners).
3. [Fix](help:gcfix) one corner so the shape can't drift.
4. Add dimensional constraints for the sizes.
5. [Constraint Status](help:constraintstatus) tells you what's still free to move; 0 means fully defined.
