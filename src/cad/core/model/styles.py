"""Colors, linetypes and lineweights."""
from __future__ import annotations

from dataclasses import dataclass

from ezdxf.colors import aci2rgb

BYBLOCK = 0
BYLAYER = 256

LW_BYLAYER = -1.0
LW_BYBLOCK = -2.0
LW_DEFAULT = -3.0
DEFAULT_LINEWEIGHT_MM = 0.25

STANDARD_LINEWEIGHTS = (
    0.00, 0.05, 0.09, 0.13, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.53, 0.60,
    0.70, 0.80, 0.90, 1.00, 1.06, 1.20, 1.40, 1.58, 2.00, 2.11,
)

ColorValue = int | str     # ACI index 0..256, or "#rrggbb" true color

COLOR_NAMES = {1: "Red", 2: "Yellow", 3: "Green", 4: "Cyan", 5: "Blue", 6: "Magenta", 7: "White"}


def color_label(color: ColorValue) -> str:
    if isinstance(color, str):
        return color.upper()
    if color == BYLAYER:
        return "ByLayer"
    if color == BYBLOCK:
        return "ByBlock"
    return COLOR_NAMES.get(color, f"Color {color}")


def color_to_rgb(color: ColorValue, dark_background: bool = True) -> tuple[int, int, int]:
    """RGB of an explicit color (not ByLayer/ByBlock). ACI 7 flips with the background."""
    if isinstance(color, str):
        h = color.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if color == 7:
        return (255, 255, 255) if dark_background else (0, 0, 0)
    if color in (BYLAYER, BYBLOCK) or not 1 <= color <= 255:
        return (255, 255, 255) if dark_background else (0, 0, 0)
    r, g, b = aci2rgb(color)
    return int(r), int(g), int(b)


def lineweight_label(lw: float) -> str:
    if lw == LW_BYLAYER:
        return "ByLayer"
    if lw == LW_BYBLOCK:
        return "ByBlock"
    if lw == LW_DEFAULT:
        return "Default"
    return f"{lw:.2f} mm"


@dataclass(frozen=True, slots=True)
class Linetype:
    name: str
    description: str
    pattern: tuple[float, ...] = ()    # mm: >0 dash, <0 gap, 0 dot. Empty = continuous

    @property
    def is_continuous(self) -> bool:
        return not self.pattern

    @property
    def length(self) -> float:
        return sum(abs(x) for x in self.pattern)

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "pattern": list(self.pattern)}

    @classmethod
    def from_dict(cls, d: dict) -> "Linetype":
        return cls(d["name"], d.get("description", ""), tuple(float(x) for x in d.get("pattern", ())))


_IN = 25.4
STANDARD_LINETYPES: tuple[Linetype, ...] = (
    Linetype("Continuous", "Solid line"),
    Linetype("DASHED", "Dashed __ __ __ __", (0.5 * _IN, -0.25 * _IN)),
    Linetype("HIDDEN", "Hidden __ __ __ __ __", (0.25 * _IN, -0.125 * _IN)),
    Linetype("CENTER", "Center ____ _ ____ _", (1.25 * _IN, -0.25 * _IN, 0.25 * _IN, -0.25 * _IN)),
    Linetype("PHANTOM", "Phantom ____ _ _ ____",
             (1.25 * _IN, -0.25 * _IN, 0.25 * _IN, -0.25 * _IN, 0.25 * _IN, -0.25 * _IN)),
    Linetype("DOT", "Dot . . . . . . .", (0.0, -0.25 * _IN)),
    Linetype("DASHDOT", "Dash dot __ . __ .", (0.5 * _IN, -0.25 * _IN, 0.0, -0.25 * _IN)),
    Linetype("BORDER", "Border __ __ . __ __ .",
             (0.5 * _IN, -0.25 * _IN, 0.5 * _IN, -0.25 * _IN, 0.0, -0.25 * _IN)),
    Linetype("DIVIDE", "Divide ____ . . ____", (0.5 * _IN, -0.25 * _IN, 0.0, -0.25 * _IN, 0.0, -0.25 * _IN)),
)

MAX_PATTERN_ELEMENTS = 8
