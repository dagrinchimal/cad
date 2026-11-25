"""2D affine transforms: x' = a*x + b*y + c,  y' = d*x + e*y + f."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .vec import Vec


@dataclass(frozen=True, slots=True)
class Affine2:
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 0.0
    e: float = 1.0
    f: float = 0.0

    # ---------------------------------------------------------------- constructors
    @staticmethod
    def identity() -> "Affine2":
        return Affine2()

    @staticmethod
    def translate(dx: float, dy: float) -> "Affine2":
        return Affine2(1, 0, dx, 0, 1, dy)

    @staticmethod
    def rotate(angle: float, center: Vec = (0.0, 0.0)) -> "Affine2":
        co, si = math.cos(angle), math.sin(angle)
        cx, cy = center
        return Affine2(co, -si, cx - co * cx + si * cy, si, co, cy - si * cx - co * cy)

    @staticmethod
    def scale(sx: float, sy: float | None = None, center: Vec = (0.0, 0.0)) -> "Affine2":
        sy = sx if sy is None else sy
        cx, cy = center
        return Affine2(sx, 0, cx - sx * cx, 0, sy, cy - sy * cy)

    @staticmethod
    def mirror(p1: Vec, p2: Vec) -> "Affine2":
        """Reflection across the line through p1 and p2."""
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        L2 = dx * dx + dy * dy
        if L2 == 0:
            raise ValueError("Mirror line needs two different points")
        ux, uy = dx / math.sqrt(L2), dy / math.sqrt(L2)
        a, b, d, e = 2 * ux * ux - 1, 2 * ux * uy, 2 * ux * uy, 2 * uy * uy - 1
        return Affine2(a, b, p1[0] - a * p1[0] - b * p1[1], d, e, p1[1] - d * p1[0] - e * p1[1])

    @staticmethod
    def insert(insert: Vec, sx: float, sy: float, rotation: float, base: Vec = (0.0, 0.0)) -> "Affine2":
        """Block insertion: move base to origin, scale, rotate, move to insert."""
        return (Affine2.translate(*insert) @ Affine2.rotate(rotation) @ Affine2.scale(sx, sy)
                @ Affine2.translate(-base[0], -base[1]))

    # ---------------------------------------------------------------- algebra
    def __matmul__(self, o: "Affine2") -> "Affine2":
        """self @ o : apply o first, then self."""
        return Affine2(
            self.a * o.a + self.b * o.d, self.a * o.b + self.b * o.e, self.a * o.c + self.b * o.f + self.c,
            self.d * o.a + self.e * o.d, self.d * o.b + self.e * o.e, self.d * o.c + self.e * o.f + self.f,
        )

    def inverse(self) -> "Affine2":
        det = self.det
        if abs(det) < 1e-300:
            raise ValueError("Transform is not invertible")
        a, b, d, e = self.e / det, -self.b / det, -self.d / det, self.a / det
        return Affine2(a, b, -(a * self.c + b * self.f), d, e, -(d * self.c + e * self.f))

    # ---------------------------------------------------------------- application
    def apply(self, p: Vec) -> Vec:
        return (self.a * p[0] + self.b * p[1] + self.c, self.d * p[0] + self.e * p[1] + self.f)

    def apply_vec(self, v: Vec) -> Vec:
        return (self.a * v[0] + self.b * v[1], self.d * v[0] + self.e * v[1])

    def apply_array(self, pts: np.ndarray) -> np.ndarray:
        out = np.empty_like(pts, dtype=np.float64)
        out[:, 0] = self.a * pts[:, 0] + self.b * pts[:, 1] + self.c
        out[:, 1] = self.d * pts[:, 0] + self.e * pts[:, 1] + self.f
        return out

    # ---------------------------------------------------------------- properties
    @property
    def det(self) -> float:
        return self.a * self.e - self.b * self.d

    @property
    def is_mirror(self) -> bool:
        return self.det < 0

    @property
    def is_identity(self) -> bool:
        return self == Affine2()

    @property
    def is_similarity(self) -> bool:
        """Uniform scale + rotation (+ optional mirror): circles stay circles."""
        tol = 1e-9 * max(1.0, abs(self.a) + abs(self.b) + abs(self.d) + abs(self.e))
        same = abs(self.a - self.e) < tol and abs(self.b + self.d) < tol
        mirrored = abs(self.a + self.e) < tol and abs(self.b - self.d) < tol
        return same or mirrored

    @property
    def scale_factor(self) -> float:
        """Average linear scale (exact for similarities)."""
        return math.sqrt(abs(self.det))

    @property
    def rotation(self) -> float:
        """Rotation angle of the x axis."""
        return math.atan2(self.d, self.a)
