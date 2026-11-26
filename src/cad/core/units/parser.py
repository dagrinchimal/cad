"""Parse typed lengths and angles in any supported format.

Every format is accepted in every unit mode:

    25.4mm  2.54cm  0.0254m  1in  1"  40"  1 1/2  1-1/2"  3/8  .5
    3'  3ft  3'-4 1/2"  3' 4.5  3'4"  3 ft 4 in  -2'-6"

A bare number (no unit mark) uses the drawing's input unit: millimetres in MM
mode, inches in fractional-inch mode. In feet-inches mode it depends on the typing
style: Revit style (default) reads "3" as 3 feet and "3 4-1/2" or "0 1.5" as feet
then inches; AutoCAD style reads bare numbers as inches.
Returned lengths are always millimetres.
"""
from __future__ import annotations

import math
import re

from .settings import MM_PER_FOOT, MM_PER_INCH, UnitSettings


class UnitParseError(ValueError):
    """Raised when text cannot be read as a length or angle."""


_NUM = r"(?:\d+(?:\.\d*)?|\.\d+)"


def _mixed(prefix: str) -> str:
    """Regex for a mixed number: '3', '2.5', '1 1/2', '1-1/2', '3/8'."""
    return (
        rf"(?:(?P<{prefix}w>{_NUM})(?:(?:\s+|-)(?P<{prefix}n>\d+)\s*/\s*(?P<{prefix}d>\d+))?"
        rf"|(?P<{prefix}fn>\d+)\s*/\s*(?P<{prefix}fd>\d+))"
    )


_FEET_MARK = r"(?:'|ft|feet|foot)"
_INCH_MARK = r'(?:"|in|inch|inches)'
_METRIC = {
    "mm": 1.0, "millimeter": 1.0, "millimeters": 1.0, "millimetre": 1.0, "millimetres": 1.0,
    "cm": 10.0, "centimeter": 10.0, "centimeters": 10.0, "centimetre": 10.0, "centimetres": 10.0,
    "m": 1000.0, "meter": 1000.0, "meters": 1000.0, "metre": 1000.0, "metres": 1000.0,
}
_METRIC_MARK = "(?P<unit>" + "|".join(sorted(_METRIC, key=len, reverse=True)) + ")"

_RE_FEET_INCHES = re.compile(
    rf"^{_mixed('f')}\s*{_FEET_MARK}\s*-?\s*{_mixed('i')}\s*{_INCH_MARK}?$"
)
_RE_FEET = re.compile(rf"^{_mixed('f')}\s*{_FEET_MARK}$")
_RE_INCHES = re.compile(rf"^{_mixed('i')}\s*{_INCH_MARK}$")
_RE_METRIC = re.compile(rf"^{_mixed('m')}\s*{_METRIC_MARK}$")
_RE_BARE = re.compile(rf"^{_mixed('b')}$")
# Revit style: "3 4-1/2", "0 1.5", "3 4 1/2", "1 1/2" -> feet, then inches
_RE_REVIT = re.compile(rf"^(?P<rf>{_NUM})\s+{_mixed('i')}$")


def _normalize(text: str) -> str:
    t = text.strip().lower()
    t = (t.replace("′", "'").replace("″", '"').replace("“", '"')
         .replace("”", '"').replace("’", "'").replace("''", '"'))
    return t


def _mixed_value(m: re.Match, prefix: str) -> float:
    w = m.group(f"{prefix}w")
    if w is not None:
        value = float(w)
        n, d = m.group(f"{prefix}n"), m.group(f"{prefix}d")
        if n is not None:
            if "." in w:
                raise UnitParseError("A whole number can't have both a decimal point and a fraction")
            value += _frac(n, d)
        return value
    return _frac(m.group(f"{prefix}fn"), m.group(f"{prefix}fd"))


def _frac(n: str, d: str) -> float:
    den = int(d)
    if den == 0:
        raise UnitParseError("Fraction has a zero denominator")
    return int(n) / den


def parse_length(text: str, settings: UnitSettings | None = None) -> float:
    """Parse a typed length. Returns millimetres. Raises UnitParseError."""
    settings = settings or UnitSettings()
    t = _normalize(text)
    if not t:
        raise UnitParseError("Empty value")
    sign = 1.0
    if t[0] in "+-":
        sign = -1.0 if t[0] == "-" else 1.0
        t = t[1:].lstrip()
        if not t:
            raise UnitParseError("Missing number after sign")

    if m := _RE_FEET_INCHES.match(t):
        mm = _mixed_value(m, "f") * MM_PER_FOOT + _mixed_value(m, "i") * MM_PER_INCH
    elif m := _RE_FEET.match(t):
        mm = _mixed_value(m, "f") * MM_PER_FOOT
    elif m := _RE_INCHES.match(t):
        mm = _mixed_value(m, "i") * MM_PER_INCH
    elif m := _RE_METRIC.match(t):
        mm = _mixed_value(m, "m") * _METRIC[m.group("unit")]
    elif settings.revit_typing and (m := _RE_REVIT.match(t)):
        mm = float(m.group("rf")) * MM_PER_FOOT + _mixed_value(m, "i") * MM_PER_INCH
    elif m := _RE_BARE.match(t):
        mm = _mixed_value(m, "b") * settings.default_input_mm
    else:
        raise UnitParseError(f"Can't read '{text.strip()}' as a length")
    return sign * mm


def try_parse_length(text: str, settings: UnitSettings | None = None) -> float | None:
    try:
        return parse_length(text, settings)
    except UnitParseError:
        return None


_RE_DMS = re.compile(rf"^(?P<d>{_NUM})d(?:\s*(?P<m>{_NUM})')?(?:\s*(?P<s>{_NUM})\")?$")
_RE_ANGLE = re.compile(rf"^(?P<v>{_NUM})\s*(?P<u>°|deg|degrees?|d|r|rad|radians?|g|grad|grads)?$")


def parse_angle(text: str) -> float:
    """Parse an angle. Returns degrees.

    Accepts 45, 45d, 45°, 45d30'15", 0.785r (radians), 50g (grads), -30.
    """
    t = _normalize(text)
    if not t:
        raise UnitParseError("Empty angle")
    sign = 1.0
    if t[0] in "+-":
        sign = -1.0 if t[0] == "-" else 1.0
        t = t[1:].lstrip()
    if m := _RE_DMS.match(t):
        deg = float(m.group("d")) + float(m.group("m") or 0) / 60 + float(m.group("s") or 0) / 3600
        return sign * deg
    if m := _RE_ANGLE.match(t):
        v = float(m.group("v"))
        u = m.group("u") or "d"
        if u.startswith("r"):
            v = math.degrees(v)
        elif u.startswith("g"):
            v = v * 0.9
        return sign * v
    raise UnitParseError(f"Can't read '{text.strip()}' as an angle")
