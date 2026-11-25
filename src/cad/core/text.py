"""Text layout interface.

Core code never touches fonts. It asks the registered TextEngine for the size
and outline of a text run. The UI registers a Qt-based engine at start-up;
without one, a simple estimate is used (good enough for files and tests).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .geom2d.transform import Affine2
from .geom2d.vec import Vec

# horizontal alignment
LEFT, CENTER, RIGHT = "left", "center", "right"
# vertical alignment (single-line text)
BASELINE, BOTTOM, MIDDLE, TOP = "baseline", "bottom", "middle", "top"


@dataclass(frozen=True, slots=True)
class TextRun:
    """One piece of text to place. Height = capital-letter height, as in AutoCAD."""
    text: str
    insert: Vec
    height: float
    rotation: float = 0.0
    width_factor: float = 1.0
    halign: str = LEFT
    valign: str = BASELINE
    font: str = "Arial"
    wrap_width: float = 0.0          # >0: wrap lines to this width (multiline text)
    line_spacing: float = 1.0
    multiline: bool = False          # MText: valign refers to the whole block

    def transform(self) -> Affine2:
        return Affine2.translate(*self.insert) @ Affine2.rotate(self.rotation)


@dataclass(slots=True)
class TextLayout:
    loops: list[np.ndarray]          # outline loops in drawing coordinates (fill even-odd)
    box: list[Vec]                   # 4 corners of the text box in drawing coordinates
    lines: list[str]
    triangles: np.ndarray | None = None   # ready-made fill triangles (k, 3, 2), if the engine has them


class TextEngine(Protocol):
    def layout(self, run: TextRun) -> TextLayout: ...


def wrap_lines(text: str, width: float, measure) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        if width <= 0:
            out.append(para)
            continue
        line = ""
        for word in para.split(" "):
            trial = word if not line else f"{line} {word}"
            if line and measure(trial) > width:
                out.append(line)
                line = word
            else:
                line = trial
        out.append(line)
    return out


def block_offset(run: TextRun, widths: list[float], line_height: float) -> tuple[list[float], float]:
    """x offsets per line and the y of the first baseline, relative to the insert point."""
    n = len(widths)
    xs = []
    for w in widths:
        xs.append(0.0 if run.halign == LEFT else (-w / 2 if run.halign == CENTER else -w))
    h = run.height
    if run.multiline:
        total = h + (n - 1) * line_height
        y0 = {TOP: -h, MIDDLE: -h + total / 2, BOTTOM: -h + total, BASELINE: -h}.get(run.valign, -h)
    else:
        y0 = {BASELINE: 0.0, BOTTOM: h * 0.3, MIDDLE: -h / 2, TOP: -h}.get(run.valign, 0.0)
    return xs, y0


class EstimateEngine:
    """Font-free fallback: every character is 0.7 x height wide; no outlines."""

    def layout(self, run: TextRun) -> TextLayout:
        h = run.height
        cw = 0.7 * h * run.width_factor

        def measure(s: str) -> float:
            return len(s) * cw
        lines = wrap_lines(run.text, run.wrap_width, measure) if run.multiline else [run.text.replace("\n", " ")]
        lh = h * 1.667 * run.line_spacing
        widths = [measure(s) for s in lines]
        xs, y0 = block_offset(run, widths, lh)
        m = run.transform()
        x_min = min(xs) if xs else 0.0
        x_max = max((x + w for x, w in zip(xs, widths)), default=0.0)
        top = y0 + h
        bottom = y0 - (len(lines) - 1) * lh - 0.3 * h
        box = [m.apply(p) for p in ((x_min, bottom), (x_max, bottom), (x_max, top), (x_min, top))]
        return TextLayout([], box, lines)


_engine: TextEngine = EstimateEngine()
_generation = 0


def set_text_engine(engine: TextEngine) -> None:
    global _engine, _generation
    _engine = engine
    _generation += 1


def text_engine() -> TextEngine:
    return _engine


def engine_generation() -> int:
    """Changes when the engine is replaced (geometry caches use it)."""
    return _generation


def rotate_point(p: Vec, angle: float) -> Vec:
    c, s = math.cos(angle), math.sin(angle)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)
