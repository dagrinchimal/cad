"""Unit modes and per-drawing unit settings.

All geometry is stored in millimetres (float64). These settings only affect
how lengths are displayed and how bare numbers typed by the user are read.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

MM_PER_INCH = 25.4
MM_PER_FOOT = 304.8

FRACTION_DENOMINATORS = (2, 4, 8, 16, 32, 64)


class UnitMode(str, Enum):
    MM = "mm"
    FRACTIONAL = "fractional"          # 3 5/16"
    ARCHITECTURAL = "architectural"    # 12'-6 3/4"

    @property
    def label(self) -> str:
        return {
            UnitMode.MM: "Millimeters",
            UnitMode.FRACTIONAL: "Fractional inches",
            UnitMode.ARCHITECTURAL: "Architectural (feet-inches)",
        }[self]

    @property
    def is_imperial(self) -> bool:
        return self is not UnitMode.MM


@dataclass(frozen=True, slots=True)
class UnitSettings:
    mode: UnitMode = UnitMode.MM
    decimal_places: int = 2          # used in MM mode
    denominator: int = 16            # used in both inch modes (1/2 .. 1/64)
    angle_decimal_places: int = 0
    input_style: str = "revit"       # feet-inches typing: "revit" (3 4-1/2 = 3'-4 1/2", 3 = 3') or "autocad"

    def __post_init__(self) -> None:
        if self.input_style not in ("revit", "autocad"):
            raise ValueError("input_style must be 'revit' or 'autocad'")
        if self.denominator not in FRACTION_DENOMINATORS:
            raise ValueError(f"denominator must be one of {FRACTION_DENOMINATORS}")
        if not 0 <= self.decimal_places <= 8:
            raise ValueError("decimal_places must be 0..8")
        if not 0 <= self.angle_decimal_places <= 8:
            raise ValueError("angle_decimal_places must be 0..8")

    @property
    def default_input_mm(self) -> float:
        """Millimetres represented by a bare typed number such as '12'."""
        if self.mode is UnitMode.MM:
            return 1.0
        if self.mode is UnitMode.ARCHITECTURAL and self.input_style == "revit":
            return MM_PER_FOOT
        return MM_PER_INCH

    @property
    def revit_typing(self) -> bool:
        return self.mode is UnitMode.ARCHITECTURAL and self.input_style == "revit"

    def with_mode(self, mode: UnitMode) -> "UnitSettings":
        return replace(self, mode=mode)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "decimal_places": self.decimal_places,
            "denominator": self.denominator,
            "angle_decimal_places": self.angle_decimal_places,
            "input_style": self.input_style,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UnitSettings":
        return cls(
            mode=UnitMode(d.get("mode", "mm")),
            decimal_places=int(d.get("decimal_places", 2)),
            denominator=int(d.get("denominator", 16)),
            angle_decimal_places=int(d.get("angle_decimal_places", 0)),
            input_style=str(d.get("input_style", "revit")),
        )
