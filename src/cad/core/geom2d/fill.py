"""Even-odd area filling: turn boundary loops (with holes, nesting) into triangles."""
from __future__ import annotations

import mapbox_earcut as earcut
import numpy as np


def point_in_loop(x: float, y: float, loop: np.ndarray) -> bool:
    xs, ys = loop[:, 0], loop[:, 1]
    xj, yj = np.roll(xs, 1), np.roll(ys, 1)
    cond = (ys > y) != (yj > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = (xj - xs) * (y - ys) / (yj - ys) + xs
    return bool(np.count_nonzero(cond & (x < xint)) % 2)


def point_in_loops(x: float, y: float, loops: list[np.ndarray]) -> bool:
    """Even-odd rule over several loops."""
    return sum(point_in_loop(x, y, lp) for lp in loops) % 2 == 1


def loop_area(loop: np.ndarray) -> float:
    x, y = loop[:, 0], loop[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def _clean(loop: np.ndarray) -> np.ndarray:
    loop = np.asarray(loop, dtype=np.float64)
    if len(loop) > 1 and np.allclose(loop[0], loop[-1]):
        loop = loop[:-1]
    return loop


def triangulate(loops: list[np.ndarray]) -> np.ndarray:
    """Triangles (k, 3, 2) covering the even-odd interior of the loops."""
    loops = [_clean(lp) for lp in loops]
    loops = [lp for lp in loops if len(lp) >= 3 and abs(loop_area(lp)) > 1e-18]
    if not loops:
        return np.zeros((0, 3, 2))
    n = len(loops)
    areas = [abs(loop_area(lp)) for lp in loops]
    # nesting depth: how many loops contain each loop
    depth = [0] * n
    parent = [-1] * n
    for i in range(n):
        px, py = loops[i][0]
        best = -1
        for j in range(n):
            if i != j and areas[j] > areas[i] and point_in_loop(px, py, loops[j]):
                depth[i] += 1
                if best < 0 or areas[j] < areas[best]:
                    best = j
        parent[i] = best
    tris = []
    for i in range(n):
        if depth[i] % 2:
            continue
        holes = [loops[j] for j in range(n) if parent[j] == i and depth[j] % 2 == 1]
        rings = [loops[i]] + holes
        verts = np.vstack(rings)
        ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
        idx = earcut.triangulate_float64(verts, ends)
        if len(idx):
            tris.append(verts[np.asarray(idx).reshape(-1, 3)])
    if not tris:
        return np.zeros((0, 3, 2))
    return np.concatenate(tris)
