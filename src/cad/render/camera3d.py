"""A Z-up orbit camera: projection to the screen and picking rays back into the model."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# name: (azimuth, elevation) in degrees. Azimuth is where the eye sits, measured from +X toward +Y.
PRESETS: dict[str, tuple[float, float]] = {
    "Top": (-90.0, 90.0), "Bottom": (-90.0, -90.0),
    "Front": (-90.0, 0.0), "Back": (90.0, 0.0), "Left": (180.0, 0.0), "Right": (0.0, 0.0),
    "SW Iso": (225.0, 35.264), "SE Iso": (-45.0, 35.264), "NE Iso": (45.0, 35.264), "NW Iso": (135.0, 35.264),
}


@dataclass
class Camera3D:
    target: np.ndarray = None           # point the camera looks at (mm)
    azimuth: float = 225.0              # degrees
    elevation: float = 35.264           # degrees, -90..90
    scale: float = 2.0                  # pixels per mm at the target
    width: int = 800
    height: int = 600
    perspective: bool = False
    fov: float = 40.0                   # degrees, vertical (perspective only)

    def __post_init__(self) -> None:
        if self.target is None:
            self.target = np.zeros(3)
        self.target = np.asarray(self.target, float)

    # ------------------------------------------------------------ frame
    @property
    def eye_dir(self) -> np.ndarray:
        """Unit vector from the target toward the eye."""
        az, el = math.radians(self.azimuth), math.radians(self.elevation)
        return np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])

    @property
    def right(self) -> np.ndarray:
        az = math.radians(self.azimuth)
        return np.array([-math.sin(az), math.cos(az), 0.0])

    @property
    def forward(self) -> np.ndarray:
        return -self.eye_dir

    @property
    def up(self) -> np.ndarray:
        return np.cross(self.right, self.forward)

    @property
    def distance(self) -> float:
        """Eye distance for perspective, chosen so the target plane keeps `scale`."""
        half_h_mm = self.height / 2 / self.scale
        return half_h_mm / math.tan(math.radians(self.fov) / 2)

    @property
    def eye(self) -> np.ndarray:
        return self.target + self.eye_dir * self.distance

    # ------------------------------------------------------------ projection
    def view_coords(self, pts: np.ndarray) -> np.ndarray:
        """(N,3) model points -> (N,3) [x right, y up, depth along the view (larger = farther)] in mm."""
        p = np.asarray(pts, float).reshape(-1, 3) - self.target
        return np.stack([p @ self.right, p @ self.up, p @ self.forward], axis=1)

    def project(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(N,3) -> screen (N,2) pixels (y down) and depth (N,) (larger = farther)."""
        v = self.view_coords(pts)
        if self.perspective:
            d = self.distance
            k = d / np.maximum(d + v[:, 2], d * 1e-3)
            x, y = v[:, 0] * k, v[:, 1] * k
        else:
            x, y = v[:, 0], v[:, 1]
        sx = self.width / 2 + x * self.scale
        sy = self.height / 2 - y * self.scale
        return np.stack([sx, sy], axis=1), v[:, 2]

    def ray(self, sx: float, sy: float) -> tuple[np.ndarray, np.ndarray]:
        """Picking ray (origin, unit direction) through a screen pixel."""
        x = (sx - self.width / 2) / self.scale
        y = (self.height / 2 - sy) / self.scale
        on_target = self.target + self.right * x + self.up * y
        if self.perspective:
            o = self.eye
            d = on_target - o
            return o, d / np.linalg.norm(d)
        far = 1e5 / max(self.scale, 1e-9) + 1e4
        return on_target - self.forward * far, self.forward.copy()

    def mm_per_pixel(self, point=None) -> float:
        if not self.perspective or point is None:
            return 1.0 / self.scale
        depth = (np.asarray(point, float) - self.target) @ self.forward
        return (self.distance + depth) / self.distance / self.scale

    # ------------------------------------------------------------ navigation
    def set_view(self, name: str) -> None:
        self.azimuth, self.elevation = PRESETS[name]

    def orbit(self, dx_px: float, dy_px: float) -> None:
        self.azimuth = (self.azimuth - dx_px * 0.4) % 360.0
        self.elevation = float(np.clip(self.elevation + dy_px * 0.4, -90.0, 90.0))

    def pan(self, dx_px: float, dy_px: float) -> None:
        self.target = self.target - self.right * (dx_px / self.scale) + self.up * (dy_px / self.scale)

    def zoom(self, factor: float, sx: float | None = None, sy: float | None = None) -> None:
        """Zoom by `factor` (>1 = closer), keeping the point under the cursor still."""
        factor = float(np.clip(factor, 1e-3, 1e3))
        if sx is not None:
            x = (sx - self.width / 2) / self.scale
            y = (self.height / 2 - sy) / self.scale
            anchor = self.target + self.right * x + self.up * y
            self.target = anchor + (self.target - anchor) / factor
        self.scale = float(np.clip(self.scale * factor, 1e-6, 1e7))

    def fit(self, bbox3, margin: float = 0.12) -> None:
        """Zoom to show a box (x0, y0, z0, x1, y1, z1)."""
        x0, y0, z0, x1, y1, z1 = bbox3
        corners = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)
        self.target = corners.mean(axis=0)
        v = self.view_coords(corners)
        w = max(v[:, 0].max() - v[:, 0].min(), 1e-6)
        h = max(v[:, 1].max() - v[:, 1].min(), 1e-6)
        self.scale = min(self.width * (1 - 2 * margin) / w, self.height * (1 - 2 * margin) / h)

    def to_dict(self) -> dict:
        return {"target": [float(v) for v in self.target], "azimuth": self.azimuth, "elevation": self.elevation,
                "scale": self.scale, "perspective": self.perspective}

    def load(self, d: dict) -> None:
        self.target = np.array(d.get("target", (0, 0, 0)), float)
        self.azimuth = float(d.get("azimuth", 225.0))
        self.elevation = float(d.get("elevation", 35.264))
        self.scale = float(d.get("scale", 2.0))
        self.perspective = bool(d.get("perspective", False))
