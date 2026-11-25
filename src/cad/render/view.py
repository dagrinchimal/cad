"""View transform between model space (mm, Y up) and the screen (pixels, Y down)."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.geom2d import BBox, Vec

MIN_SCALE = 1e-7     # pixels per mm
MAX_SCALE = 1e7


@dataclass(slots=True)
class ViewState:
    cx: float = 0.0          # model point at the window center
    cy: float = 0.0
    scale: float = 2.0       # screen pixels per model unit (logical pixels)
    width: int = 800
    height: int = 600

    @property
    def pixel(self) -> float:
        """Model units per logical pixel."""
        return 1.0 / self.scale

    def to_screen(self, p: Vec) -> tuple[float, float]:
        return ((p[0] - self.cx) * self.scale + self.width / 2,
                self.height / 2 - (p[1] - self.cy) * self.scale)

    def to_model(self, sx: float, sy: float) -> Vec:
        return ((sx - self.width / 2) / self.scale + self.cx,
                (self.height / 2 - sy) / self.scale + self.cy)

    def visible_rect(self) -> BBox:
        x0, y1 = self.to_model(0, 0)
        x1, y0 = self.to_model(self.width, self.height)
        return (x0, y0, x1, y1)

    def zoom_at(self, sx: float, sy: float, factor: float) -> None:
        """Zoom keeping the model point under (sx, sy) fixed."""
        before = self.to_model(sx, sy)
        self.scale = min(MAX_SCALE, max(MIN_SCALE, self.scale * factor))
        after = self.to_model(sx, sy)
        self.cx += before[0] - after[0]
        self.cy += before[1] - after[1]

    def pan_pixels(self, dx: float, dy: float) -> None:
        self.cx -= dx / self.scale
        self.cy += dy / self.scale

    def fit(self, box: BBox, margin: float = 0.05) -> None:
        w = max(box[2] - box[0], 1e-9)
        h = max(box[3] - box[1], 1e-9)
        if box[2] - box[0] < 1e-9 and box[3] - box[1] < 1e-9:
            w = h = 100.0
        sx = self.width * (1 - 2 * margin) / w
        sy = self.height * (1 - 2 * margin) / h
        self.scale = min(MAX_SCALE, max(MIN_SCALE, min(sx, sy)))
        self.cx = (box[0] + box[2]) / 2
        self.cy = (box[1] + box[3]) / 2

    def copy(self) -> "ViewState":
        return ViewState(self.cx, self.cy, self.scale, self.width, self.height)
