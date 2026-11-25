"""2D parametric constraints (AutoCAD-style geometric and dimensional constraints)."""
from .manager import ConstraintManager
from .model import (
    DIMENSIONAL, GEOMETRIC, Constraint, ExpressionError, curve_ref, evaluate, nearest_point_ref, point_refs,
)
from .solver import ConstraintError, solve_for, would_overconstrain

__all__ = [
    "DIMENSIONAL", "GEOMETRIC", "Constraint", "ConstraintError", "ConstraintManager", "ExpressionError",
    "curve_ref", "evaluate", "nearest_point_ref", "point_refs", "solve_for", "would_overconstrain",
]
