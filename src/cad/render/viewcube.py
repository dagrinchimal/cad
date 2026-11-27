"""The view cube in the corner of the 3D view: click a face for that view, a corner for an iso view."""
from __future__ import annotations

import math

import numpy as np

from .camera3d import Camera3D

FACES = {   # name: (normal, preset)
    "TOP": ((0, 0, 1), "Top"), "BOTTOM": ((0, 0, -1), "Bottom"),
    "FRONT": ((0, -1, 0), "Front"), "BACK": ((0, 1, 0), "Back"),
    "RIGHT": ((1, 0, 0), "Right"), "LEFT": ((-1, 0, 0), "Left"),
}
SIZE = 30.0          # half-size on screen, pixels
MARGIN = 16.0


def center(width: int) -> tuple[float, float]:
    return (width - MARGIN - SIZE * 1.8, MARGIN + SIZE * 1.8)


def project(cam: Camera3D, width: int, pts) -> tuple[np.ndarray, np.ndarray]:
    """Cube points (unit cube coordinates) -> screen pixels and depth."""
    pts = np.asarray(pts, float).reshape(-1, 3)
    cx, cy = center(width)
    x = pts @ cam.right
    y = pts @ cam.up
    d = pts @ cam.forward
    return np.stack([cx + x * SIZE, cy - y * SIZE], axis=1), d


def face_polygon(normal) -> np.ndarray:
    n = np.array(normal, float)
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.5 else np.array([0, 1.0, 0])
    u = np.cross(n, a)
    v = np.cross(n, u)
    return np.array([n + u + v, n + u - v, n - u - v, n - u + v])


def visible_faces(cam: Camera3D, width: int):
    """[(name, preset, screen polygon (4,2), depth, facing)] far to near, only faces toward the eye."""
    out = []
    for name, (normal, preset) in FACES.items():
        facing = float(np.dot(normal, cam.eye_dir))
        if facing <= 0.02:
            continue
        scr, d = project(cam, width, face_polygon(normal))
        out.append((name, preset, scr, float(d.mean()), facing))
    out.sort(key=lambda f: -f[3])
    return out


def corners(cam: Camera3D, width: int):
    """Visible corners: [(screen xy, (azimuth, elevation))]."""
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                c = np.array([sx, sy, sz], float)
                if c @ cam.eye_dir <= 0.2:
                    continue
                (p,), _ = project(cam, width, [c])
                az = math.degrees(math.atan2(sy, sx)) % 360
                out.append((p, (az, 35.264 if sz > 0 else -35.264)))
    return out


def home_button(width: int) -> tuple[float, float, float]:
    cx, cy = center(width)
    return (cx - SIZE * 1.75, cy - SIZE * 1.55, 9.0)


def _inside(poly: np.ndarray, x: float, y: float) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            inside = not inside
    return inside


def hit(cam: Camera3D, width: int, x: float, y: float):
    """What's under the cursor: ("home", None), ("corner", (az, el)), ("face", preset) or None."""
    hx, hy, hr = home_button(width)
    if math.hypot(x - hx, y - hy) <= hr + 2:
        return ("home", None)
    for p, view in corners(cam, width):
        if math.hypot(x - p[0], y - p[1]) <= 8:
            return ("corner", view)
    for name, preset, poly, _d, _f in reversed(visible_faces(cam, width)):     # nearest first
        if _inside(poly, x, y):
            return ("face", preset)
    return None


def contains(width: int, x: float, y: float) -> bool:
    cx, cy = center(width)
    return abs(x - cx) < SIZE * 2.2 and abs(y - cy) < SIZE * 2.2
