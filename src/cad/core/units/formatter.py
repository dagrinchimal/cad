"""Format millimetre values for display in the active unit mode."""
from __future__ import annotations

import math

from .settings import MM_PER_INCH, UnitMode, UnitSettings


def _round_half_up(x: float) -> int:
    # tiny epsilon absorbs mm->inch conversion noise at exact halves
    return math.floor(x + 0.5 + 1e-9)


def _fraction(numerator: int, denominator: int) -> str:
    g = math.gcd(numerator, denominator)
    return f"{numerator // g}/{denominator // g}"


def format_decimal(value: float, places: int) -> str:
    text = f"{value:.{places}f}"
    # avoid "-0.00"
    if text.lstrip("-").strip("0.") == "" and text.startswith("-"):
        text = text[1:]
    return text


def format_fractional_inches(inches: float, denominator: int, mark: bool = True) -> str:
    sign = "-" if inches < 0 else ""
    n = _round_half_up(abs(inches) * denominator)
    if n == 0:
        return '0"' if mark else "0"
    whole, rem = divmod(n, denominator)
    if rem == 0:
        body = f"{whole}"
    elif whole == 0:
        body = _fraction(rem, denominator)
    else:
        body = f"{whole} {_fraction(rem, denominator)}"
    suffix = '"' if mark else ""
    return f"{sign}{body}{suffix}"


def format_architectural(inches: float, denominator: int) -> str:
    sign = "-" if inches < 0 else ""
    n = _round_half_up(abs(inches) * denominator)  # total in 1/denominator inch
    if n == 0:
        return "0\""
    per_foot = 12 * denominator
    feet, rem = divmod(n, per_foot)
    whole_in, frac = divmod(rem, denominator)
    if frac == 0:
        inch_text = f"{whole_in}"
    elif whole_in or feet:
        inch_text = f"{whole_in} {_fraction(frac, denominator)}"   # 1'-0 1/2"
    else:
        inch_text = _fraction(frac, denominator)                   # 1/2"
    if feet == 0:
        return f"{sign}{inch_text}\""
    return f"{sign}{feet}'-{inch_text}\""


def format_length(mm: float, settings: UnitSettings) -> str:
    """Format a length (stored in mm) for display."""
    if not math.isfinite(mm):
        return "∞" if mm > 0 else ("-∞" if mm < 0 else "NaN")
    if settings.mode is UnitMode.MM:
        return format_decimal(mm, settings.decimal_places)
    inches = mm / MM_PER_INCH
    if settings.mode is UnitMode.FRACTIONAL:
        return format_fractional_inches(inches, settings.denominator)
    return format_architectural(inches, settings.denominator)


def format_point(p: tuple[float, ...], settings: UnitSettings) -> str:
    return ", ".join(format_length(c, settings) for c in p)


def format_angle(degrees: float, settings: UnitSettings) -> str:
    return f"{format_decimal(degrees, settings.angle_decimal_places)}°"


def unit_suffix(settings: UnitSettings) -> str:
    return "mm" if settings.mode is UnitMode.MM else ""
