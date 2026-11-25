"""Drawing scales for printing: paper length per model length."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .parser import UnitParseError, parse_length
from .settings import UnitSettings, UnitMode


@dataclass(frozen=True, slots=True)
class DrawingScale:
    name: str
    paper: float      # paper length (mm)
    model: float      # model length (mm) shown by that paper length

    @property
    def factor(self) -> float:
        """Multiply a model length by this to get the printed length."""
        return self.paper / self.model

    @property
    def ratio(self) -> float:
        """The '50' in 1:50."""
        return self.model / self.paper


def _metric(paper: float, model: float) -> DrawingScale:
    name = f"{paper:g}:{model:g}"
    return DrawingScale(name, paper, model)


def _arch(paper_text: str, model_text: str) -> DrawingScale:
    s = UnitSettings(mode=UnitMode.ARCHITECTURAL)
    return DrawingScale(f'{paper_text} = {model_text}', parse_length(paper_text, s), parse_length(model_text, s))


METRIC_SCALES: tuple[DrawingScale, ...] = tuple(
    [_metric(1, 1)]
    + [_metric(1, n) for n in (2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000)]
    + [_metric(n, 1) for n in (2, 5, 10, 20, 50, 100)]
)

IMPERIAL_SCALES: tuple[DrawingScale, ...] = (
    _arch('1/128"', "1'-0\""),
    _arch('1/64"', "1'-0\""),
    _arch('1/32"', "1'-0\""),
    _arch('1/16"', "1'-0\""),
    _arch('3/32"', "1'-0\""),
    _arch('1/8"', "1'-0\""),
    _arch('3/16"', "1'-0\""),
    _arch('1/4"', "1'-0\""),
    _arch('3/8"', "1'-0\""),
    _arch('1/2"', "1'-0\""),
    _arch('3/4"', "1'-0\""),
    _arch('1"', "1'-0\""),
    _arch('1 1/2"', "1'-0\""),
    _arch('3"', "1'-0\""),
    _arch('6"', "1'-0\""),
    _arch('1"', "10'"),
    _arch('1"', "20'"),
    _arch('1"', "30'"),
    _arch('1"', "40'"),
    _arch('1"', "50'"),
    _arch('1"', "60'"),
    _arch('1"', "100'"),
)


def standard_scales(mode: UnitMode) -> tuple[DrawingScale, ...]:
    """Scales to offer first for a unit mode (the other list follows)."""
    if mode is UnitMode.MM:
        return METRIC_SCALES + IMPERIAL_SCALES
    return (METRIC_SCALES[0],) + IMPERIAL_SCALES + METRIC_SCALES[1:]


_RE_RATIO = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$")


def parse_scale(text: str) -> DrawingScale:
    """Parse '1:50', '2:1', '1/4\" = 1\\'-0\"', '1" = 20\\''."""
    if m := _RE_RATIO.match(text):
        paper, model = float(m.group(1)), float(m.group(2))
        if paper <= 0 or model <= 0:
            raise UnitParseError("Scale values must be positive")
        return _metric(paper, model)
    if "=" in text:
        left, right = text.split("=", 1)
        s = UnitSettings(mode=UnitMode.ARCHITECTURAL)
        paper, model = parse_length(left, s), parse_length(right, s)
        if paper <= 0 or model <= 0:
            raise UnitParseError("Scale values must be positive")
        return DrawingScale(f"{left.strip()} = {right.strip()}", paper, model)
    raise UnitParseError(f"Can't read '{text}' as a scale (try 1:50 or 1/4\" = 1'-0\")")
