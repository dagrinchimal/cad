"""Constraint solver: damped least squares (Levenberg–Marquardt) with degrees-of-freedom analysis.

Each constraint becomes one or more residual equations that are zero when it holds.
The solver changes the geometry as little as possible: every parameter also has a
small "stay where you are" term, much stronger for objects the user just edited.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from ..model import Entity
from .model import Constraint, ExpressionError, GeomView, params_of, resolve_values, with_params


class ConstraintError(Exception):
    """The constraints can't all be satisfied (conflict) or a value is invalid."""


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _norm(v):
    return math.hypot(v[0], v[1]) or 1e-300


def residuals_for(c: Constraint, g: GeomView, values: dict[str, float]) -> list[float]:
    k, r = c.kind, c.refs
    if k == "coincident":
        ka, kb = g.kind(r[0]), g.kind(r[1])
        if ka == "point" and kb == "point":
            a, b = g.point(r[0]), g.point(r[1])
            return [a[0] - b[0], a[1] - b[1]]
        pref, cref = (r[0], r[1]) if ka == "point" else (r[1], r[0])
        p = g.point(pref)
        if g.kind(cref) == "line":
            a, b = g.line(cref)
            d = (b[0] - a[0], b[1] - a[1])
            return [_cross(d, (p[0] - a[0], p[1] - a[1])) / _norm(d)]
        ctr, rad = g.circle(cref)
        return [math.hypot(p[0] - ctr[0], p[1] - ctr[1]) - rad]
    if k == "collinear":
        a, b = g.line(r[0])
        p, q = g.line(r[1])
        d = (b[0] - a[0], b[1] - a[1])
        n = _norm(d)
        return [_cross(d, (p[0] - a[0], p[1] - a[1])) / n, _cross(d, (q[0] - a[0], q[1] - a[1])) / n]
    if k == "concentric":
        (c1, _), (c2, _) = g.circle(r[0]), g.circle(r[1])
        return [c1[0] - c2[0], c1[1] - c2[1]]
    if k == "fix":
        if g.kind(r[0]) == "point":
            p = g.point(r[0])
            return [p[0] - c.values[0], p[1] - c.values[1]]
        x, o = g._p(r[0][0])
        n = len(c.values)
        return [x[o + i] - c.values[i] for i in range(n)]
    if k in ("parallel", "perpendicular"):
        a, b = g.line(r[0])
        p, q = g.line(r[1])
        d1, d2 = (b[0] - a[0], b[1] - a[1]), (q[0] - p[0], q[1] - p[1])
        n = _norm(d1) * _norm(d2)
        if k == "parallel":
            return [_cross(d1, d2) / n]
        return [(d1[0] * d2[0] + d1[1] * d2[1]) / n]
    if k in ("horizontal", "vertical"):
        if len(r) == 2:
            a, b = g.point(r[0]), g.point(r[1])
        else:
            a, b = g.line(r[0])
        return [b[1] - a[1]] if k == "horizontal" else [b[0] - a[0]]
    if k == "tangent":
        ka = g.kind(r[0])
        if ka == "line" or g.kind(r[1]) == "line":
            lref, cref = (r[0], r[1]) if ka == "line" else (r[1], r[0])
            a, b = g.line(lref)
            ctr, rad = g.circle(cref)
            d = (b[0] - a[0], b[1] - a[1])
            dist_ = abs(_cross(d, (ctr[0] - a[0], ctr[1] - a[1]))) / _norm(d)
            return [dist_ - rad]
        (c1, r1), (c2, r2) = g.circle(r[0]), g.circle(r[1])
        dd = math.hypot(c1[0] - c2[0], c1[1] - c2[1])
        return [dd - (r1 + r2)] if (c.values or (1.0,))[0] > 0 else [dd - abs(r1 - r2)]
    if k == "symmetric":
        a, b = g.point(r[0]), g.point(r[1])
        p, q = g.line(r[2])
        d = (q[0] - p[0], q[1] - p[1])
        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        n = _norm(d)
        return [_cross(d, (m[0] - p[0], m[1] - p[1])) / n, ((b[0] - a[0]) * d[0] + (b[1] - a[1]) * d[1]) / n]
    if k == "equal":
        if g.kind(r[0]) == "circle":
            return [g.circle(r[0])[1] - g.circle(r[1])[1]]
        a, b = g.line(r[0])
        p, q = g.line(r[1])
        return [math.hypot(b[0] - a[0], b[1] - a[1]) - math.hypot(q[0] - p[0], q[1] - p[1])]
    # ---- dimensional
    v = values.get(c.name, 0.0)
    if k == "distance":
        a, b = g.point(r[0]), g.point(r[1])
        return [math.hypot(b[0] - a[0], b[1] - a[1]) - v]
    if k == "dim_horizontal":
        a, b = g.point(r[0]), g.point(r[1])
        return [(b[0] - a[0]) * (c.values or (1.0,))[0] - v]
    if k == "dim_vertical":
        a, b = g.point(r[0]), g.point(r[1])
        return [(b[1] - a[1]) * (c.values or (1.0,))[0] - v]
    if k == "radius":
        return [g.circle(r[0])[1] - v]
    if k == "diameter":
        return [2 * g.circle(r[0])[1] - v]
    if k == "angle":
        a, b = g.line(r[0])
        p, q = g.line(r[1])
        d1, d2 = (b[0] - a[0], b[1] - a[1]), (q[0] - p[0], q[1] - p[1])
        s = (c.values or (1.0,))[0]
        ang = math.atan2(_cross(d1, d2) * s, d1[0] * d2[0] + d1[1] * d2[1])
        return [ang - math.radians(v)]
    raise ConstraintError(f"Unknown constraint type '{k}'")


@dataclass
class SolveResult:
    entities: dict[int, Entity]
    dof: int
    max_residual: float


class System:
    def __init__(self, ents: dict[int, Entity], constraints: list[Constraint], all_constraints: dict) -> None:
        self.ents = ents
        self.constraints = constraints
        self.offsets: dict[int, int] = {}
        chunks = []
        o = 0
        for h, e in ents.items():
            p = params_of(e)
            self.offsets[h] = o
            o += len(p)
            chunks.append(p)
        self.x0 = np.concatenate(chunks) if chunks else np.zeros(0)
        try:
            self.values = resolve_values(all_constraints)
        except ExpressionError as exc:
            raise ConstraintError(str(exc)) from exc
        size = np.abs(self.x0).max() if len(self.x0) else 1.0
        self.scale = max(size, 1.0)

    def residuals(self, x: np.ndarray) -> np.ndarray:
        g = GeomView(self.ents, self.offsets, x)
        out: list[float] = []
        for c in self.constraints:
            out.extend(residuals_for(c, g, self.values))
        return np.array(out, dtype=float)

    def jacobian(self, x: np.ndarray) -> np.ndarray:
        r0 = self.residuals(x)
        J = np.zeros((len(r0), len(x)))
        for i in range(len(x)):
            h = 1e-7 * max(1.0, abs(x[i]))
            xp = x.copy()
            xp[i] += h
            J[:, i] = (self.residuals(xp) - r0) / h
        return J

    def rank(self, x: np.ndarray) -> int:
        if not self.constraints or len(x) == 0:
            return 0
        J = self.jacobian(x)
        if J.size == 0:
            return 0
        s = np.linalg.svd(J, compute_uv=False)
        return int((s > 1e-6 * max(1.0, s.max())).sum())

    def _solve_masked(self, weights: np.ndarray, free: np.ndarray) -> np.ndarray:
        x0 = self.x0
        idx = np.nonzero(free)[0]
        if len(idx) == 0:
            return x0.copy()
        w = weights[idx] * 1e-3

        def full(z):
            x = x0.copy()
            x[idx] = z
            return x

        def fun(z):
            return np.concatenate((self.residuals(full(z)) * 1e3, w * (z - x0[idx])))
        res = least_squares(fun, x0[idx], method="lm", xtol=1e-14, ftol=1e-14, gtol=1e-14, max_nfev=4000)
        x = full(res.x)
        # polish: minimum-norm Newton steps make the constraints hold exactly while moving as little as possible
        for _ in range(12):
            r = self.residuals(x)
            if not len(r) or np.abs(r).max() < 1e-12 * self.scale:
                break
            J = self.jacobian(x)[:, idx]
            dz = np.linalg.lstsq(J, -r, rcond=None)[0]
            x[idx] = x[idx] + dz
        return x

    def solve(self, weights: np.ndarray) -> SolveResult:
        x0 = self.x0
        if not self.constraints:
            return SolveResult(self.ents, len(x0), 0.0)
        held = weights >= 1000.0
        x = None
        if held.any() and not held.all():
            # first try keeping what the user just edited exactly where it is
            cand = self._solve_masked(weights, ~held)
            if np.abs(self.residuals(cand)).max() <= 1e-6 * self.scale:
                x = cand
        if x is None:
            x = self._solve_masked(weights, np.ones(len(x0), dtype=bool))
        resid = self.residuals(x)
        maxr = float(np.abs(resid).max()) if len(resid) else 0.0
        if maxr > 1e-6 * self.scale:
            raise ConstraintError("The constraints conflict with each other, so the change can't be made.")
        out = {}
        for h, e in self.ents.items():
            o = self.offsets[h]
            n = len(params_of(e))
            out[h] = with_params(e, x[o:o + n])
        dof = len(x) - self.rank(x)
        return SolveResult(out, dof, maxr)


def component(constraints: dict, seeds: set[int]) -> tuple[set[int], list[Constraint]]:
    """All entities and constraints connected to the seed handles."""
    ents = set(seeds)
    cons: dict[int, Constraint] = {}
    grown = True
    while grown:
        grown = False
        for c in constraints.values():
            if c.id in cons:
                continue
            if c.handles & ents:
                cons[c.id] = c
                if not c.handles <= ents:
                    ents |= c.handles
                    grown = True
    return ents, list(cons.values())


def solve_for(doc, seeds: set[int], preferred: dict[int, float] | None = None) -> SolveResult | None:
    """Re-solve everything connected to `seeds`. Raises ConstraintError on conflict."""
    handles, cons = component(doc.constraints, seeds)
    if not cons:
        return None
    ents = {h: doc.entities[h] for h in sorted(handles) if h in doc.entities}
    if len(ents) != len(handles):
        cons = [c for c in cons if c.handles <= set(ents)]
    sys_ = System(ents, cons, doc.constraints)
    weights = np.ones(len(sys_.x0))
    for h, wt in (preferred or {}).items():
        if h in sys_.offsets:
            o = sys_.offsets[h]
            n = len(params_of(ents[h]))
            weights[o:o + n] = wt
    return sys_.solve(weights)


def would_overconstrain(doc, new: Constraint) -> bool:
    """True if `new` adds no independent equation to its group (redundant or conflicting)."""
    handles, cons = component(doc.constraints, set(new.handles))
    ents = {h: doc.entities[h] for h in sorted(handles | set(new.handles)) if h in doc.entities}
    table = dict(doc.constraints)
    table[new.id] = new
    before = System(ents, cons, table)
    after = System(ents, cons + [new], table)
    rows = len(after.residuals(after.x0))
    return after.rank(after.x0) < before.rank(before.x0) + (rows - len(before.residuals(before.x0)))
