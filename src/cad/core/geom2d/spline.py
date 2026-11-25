"""Cubic B-splines: evaluation (de Boor) and interpolation through fit points."""
from __future__ import annotations

import numpy as np


def clamped_knots(n_ctrl: int, degree: int, params: np.ndarray | None = None) -> np.ndarray:
    """Clamped knot vector; with params uses the averaging technique (good for interpolation)."""
    m = n_ctrl + degree + 1
    knots = np.zeros(m)
    knots[-(degree + 1):] = 1.0
    inner = n_ctrl - degree - 1
    if inner > 0:
        if params is None:
            knots[degree + 1:degree + 1 + inner] = np.arange(1, inner + 1) / (inner + 1)
        else:
            for j in range(1, inner + 1):
                knots[degree + j] = params[j:j + degree].mean()
    return knots


def basis_matrix(u: np.ndarray, knots: np.ndarray, degree: int, n_ctrl: int) -> np.ndarray:
    """B-spline basis functions N_i,p(u) for every u (rows) and control point (cols)."""
    u = np.asarray(u, dtype=np.float64)
    N = np.zeros((len(u), n_ctrl))
    for row, uu in enumerate(u):
        # find span
        if uu >= knots[n_ctrl]:
            span = n_ctrl - 1
        else:
            span = int(np.searchsorted(knots, uu, side="right") - 1)
            span = max(degree, min(span, n_ctrl - 1))
        # Cox-de Boor (The NURBS Book A2.2)
        left = np.zeros(degree + 1)
        right = np.zeros(degree + 1)
        b = np.zeros(degree + 1)
        b[0] = 1.0
        for j in range(1, degree + 1):
            left[j] = uu - knots[span + 1 - j]
            right[j] = knots[span + j] - uu
            saved = 0.0
            for r in range(j):
                den = right[r + 1] + left[j - r]
                tmp = b[r] / den if den != 0 else 0.0
                b[r] = saved + right[r + 1] * tmp
                saved = left[j - r] * tmp
            b[j] = saved
        N[row, span - degree:span + 1] = b
    return N


def evaluate(ctrl: np.ndarray, knots: np.ndarray, degree: int, u: np.ndarray) -> np.ndarray:
    N = basis_matrix(u, knots, degree, len(ctrl))
    return N @ ctrl


def interpolate(fit: np.ndarray, degree: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Control points and knots of a clamped B-spline passing through all fit points."""
    fit = np.asarray(fit, dtype=np.float64)
    n = len(fit)
    if n < 2:
        raise ValueError("A spline needs at least 2 points")
    degree = min(degree, n - 1)
    d = np.linalg.norm(np.diff(fit, axis=0), axis=1)
    total = d.sum()
    if total <= 0:
        raise ValueError("Spline points are all the same")
    params = np.concatenate(([0.0], np.cumsum(d) / total))
    knots = clamped_knots(n, degree, params)
    N = basis_matrix(params, knots, degree, n)
    ctrl = np.linalg.solve(N, fit)
    return ctrl, knots


def tessellate(ctrl: np.ndarray, knots: np.ndarray, degree: int, per_span: int = 24) -> np.ndarray:
    spans = max(1, len(ctrl) - degree)
    u = np.linspace(knots[degree], knots[len(ctrl)], spans * per_span + 1)
    return evaluate(ctrl, knots, degree, u)
