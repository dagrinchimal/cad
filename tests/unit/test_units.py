import math
import random

import pytest

from cad.core.units import (
    MM_PER_INCH, UnitMode, UnitParseError, UnitSettings, format_length, parse_angle,
    parse_length, parse_scale, standard_scales,
)

MM = UnitSettings(mode=UnitMode.MM)
FRAC = UnitSettings(mode=UnitMode.FRACTIONAL)
ARCH = UnitSettings(mode=UnitMode.ARCHITECTURAL, input_style="autocad")
REVIT = UnitSettings(mode=UnitMode.ARCHITECTURAL)
IN = MM_PER_INCH
FT = 12 * MM_PER_INCH


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("text,expected_mm", [
    ("25.4mm", 25.4), ("25.4 mm", 25.4), ("2.54cm", 25.4), ("0.0254m", 25.4), ("1 m", 1000),
    ("1in", IN), ("1 in", IN), ('1"', IN), ('40"', 40 * IN), ("1 inch", IN), ("2 inches", 2 * IN),
    ('1 1/2"', 1.5 * IN), ('1-1/2"', 1.5 * IN), ('3/8"', 0.375 * IN), ('.5"', 0.5 * IN),
    ("3'", 3 * FT), ("3ft", 3 * FT), ("3 feet", 3 * FT), ("1 foot", FT), ("1 1/2'", 1.5 * FT),
    ("3'-4 1/2\"", 3 * FT + 4.5 * IN), ("3' 4.5", 3 * FT + 4.5 * IN), ("3'4\"", 3 * FT + 4 * IN),
    ("3'-4", 3 * FT + 4 * IN), ("3 ft 4 in", 3 * FT + 4 * IN), ("12'-6 3/4\"", 12 * FT + 6.75 * IN),
    ("0'-6\"", 6 * IN), ("3'-0\"", 3 * FT), ("3'-14\"", 3 * FT + 14 * IN),
    ("-2'-6\"", -(2 * FT + 6 * IN)), ("-25.4mm", -25.4), ("+1in", IN), ("- 3/8\"", -0.375 * IN),
    ("3′-4″", 3 * FT + 4 * IN), ("6''", 6 * IN), ("  1in  ", IN), ("1IN", IN),
])
def test_parse_explicit_units_same_in_every_mode(text, expected_mm):
    for settings in (MM, FRAC, ARCH):
        assert parse_length(text, settings) == pytest.approx(expected_mm, abs=1e-9), settings.mode


@pytest.mark.parametrize("text,value", [
    ("12", 12), ("2.5", 2.5), (".5", 0.5), ("1 1/2", 1.5), ("1-1/2", 1.5), ("3/8", 0.375),
    ("0", 0), ("1000000", 1e6),
])
def test_bare_numbers_use_drawing_unit(text, value):
    assert parse_length(text, MM) == pytest.approx(value)
    assert parse_length(text, FRAC) == pytest.approx(value * IN)
    assert parse_length(text, ARCH) == pytest.approx(value * IN)


@pytest.mark.parametrize("bad", [
    "", "   ", "abc", "1/0", "1//2", "3'-", "--3", "1.5 1/2", "mm", "'", "1 2", "1in2", "3''4",
    "1e3", "1,5", "-",
])
def test_rejects_bad_input(bad):
    with pytest.raises(UnitParseError):
        parse_length(bad, MM)


# ---------------------------------------------------------------- formatting
@pytest.mark.parametrize("mm,places,expected", [
    (25.4, 2, "25.40"), (0, 2, "0.00"), (-0.001, 2, "0.00"), (-12.345, 1, "-12.3"), (1e6, 0, "1000000"),
    (2.5, 0, "2"), (3.14159, 4, "3.1416"),
])
def test_format_mm(mm, places, expected):
    assert format_length(mm, UnitSettings(mode=UnitMode.MM, decimal_places=places)) == expected


@pytest.mark.parametrize("inches,den,expected", [
    (3 + 5 / 16, 16, '3 5/16"'), (0.5, 16, '1/2"'), (2, 16, '2"'), (0, 16, '0"'),
    (-1.25, 16, '-1 1/4"'), (1 / 64, 64, '1/64"'), (1 / 64, 32, '1/32"'),   # rounds half to even? -> 1/32
    (0.999, 16, '1"'), (2.03, 8, '2"'), (1 + 3 / 8, 2, '1 1/2"'), (100.75, 4, '100 3/4"'),
])
def test_format_fractional(inches, den, expected):
    s = UnitSettings(mode=UnitMode.FRACTIONAL, denominator=den)
    assert format_length(inches * IN, s) == expected


@pytest.mark.parametrize("inches,den,expected", [
    (12 * 12 + 6.75, 16, "12'-6 3/4\""), (6, 16, '6"'), (12, 16, "1'-0\""), (11.999, 16, "1'-0\""),
    (0.25, 16, '1/4"'), (-30, 16, "-2'-6\""), (12 + 0.5, 2, "1'-0 1/2\""), (0, 16, '0"'),
    (25 * 12 + 11 + 63 / 64, 64, "25'-11 63/64\""), (25 * 12 + 11 + 63 / 64, 16, "26'-0\""),
])
def test_format_architectural(inches, den, expected):
    s = UnitSettings(mode=UnitMode.ARCHITECTURAL, denominator=den)
    assert format_length(inches * IN, s) == expected


def test_format_non_finite():
    assert format_length(math.inf, MM) == "∞"


# ---------------------------------------------------------------- round trips
@pytest.mark.parametrize("den", [2, 4, 8, 16, 32, 64])
@pytest.mark.parametrize("mode", [UnitMode.FRACTIONAL, UnitMode.ARCHITECTURAL])
def test_round_trip_exact_on_grid(mode, den):
    """Any value on the 1/den grid formats and parses back exactly."""
    rng = random.Random(den)
    s = UnitSettings(mode=mode, denominator=den)
    for _ in range(300):
        n = rng.randint(-200000, 200000)
        mm = n / den * IN
        text = format_length(mm, s)
        assert parse_length(text, s) == pytest.approx(mm, abs=1e-9), text


def test_round_trip_mm():
    rng = random.Random(1)
    for places in range(0, 7):
        s = UnitSettings(mode=UnitMode.MM, decimal_places=places)
        for _ in range(200):
            mm = round(rng.uniform(-1e5, 1e5), places)
            assert parse_length(format_length(mm, s), s) == pytest.approx(mm, abs=10 ** -places)


def test_display_never_changes_storage():
    """Switching modes is display-only: the stored value is untouched."""
    value = 123.456789
    for mode in UnitMode:
        format_length(value, UnitSettings(mode=mode))
    assert value == 123.456789


def test_settings_validation_and_dict_round_trip():
    with pytest.raises(ValueError):
        UnitSettings(denominator=10)
    s = UnitSettings(mode=UnitMode.ARCHITECTURAL, denominator=32, decimal_places=3)
    assert UnitSettings.from_dict(s.to_dict()) == s


# ---------------------------------------------------------------- angles
@pytest.mark.parametrize("text,deg", [
    ("45", 45), ("45d", 45), ("45°", 45), ("-30", -30), ("45d30'", 45.5), ("10d30'36\"", 10.51),
    (f"{math.pi}r", 180), ("100g", 90), ("90 deg", 90), ("0.5", 0.5),
])
def test_parse_angle(text, deg):
    assert parse_angle(text) == pytest.approx(deg)


@pytest.mark.parametrize("bad", ["", "abc", "45x", "--4"])
def test_parse_angle_bad(bad):
    with pytest.raises(UnitParseError):
        parse_angle(bad)


# ---------------------------------------------------------------- scales
def test_scales():
    assert parse_scale("1:50").factor == pytest.approx(1 / 50)
    assert parse_scale("2:1").factor == pytest.approx(2)
    assert parse_scale('1/4" = 1\'-0"').ratio == pytest.approx(48)
    assert parse_scale('1/8" = 1\'-0"').ratio == pytest.approx(96)
    assert parse_scale('1" = 20\'').ratio == pytest.approx(240)
    with pytest.raises(UnitParseError):
        parse_scale("fifty")
    names = [s.name for s in standard_scales(UnitMode.ARCHITECTURAL)]
    assert names[0] == "1:1" and '1/4" = 1\'-0"' in names and "1:50" in names
    assert standard_scales(UnitMode.MM)[1].name == "1:2"


# ---------------------------------------------------------------- Revit-style typing
@pytest.mark.parametrize("text,feet,inches", [
    ("0 1.5", 0, 1.5), ("3 4-1/2", 3, 4.5), ("3 4 1/2", 3, 4.5), ("3 4.5", 3, 4.5), ("3", 3, 0),
    ("3.5", 3.5, 0), ("1 1/2", 1, 0.5), ("0 3/8", 0, 0.375), ("12 0", 12, 0), ("-2 6", -2, -6),
    ('6"', 0, 6), ("3'", 3, 0), ("3'-4\"", 3, 4), ("25.4mm", 0, 1), ("10 11 63/64", 10, 11 + 63 / 64),
])
def test_revit_style_feet_inches(text, feet, inches):
    assert parse_length(text, REVIT) == pytest.approx(feet * FT + inches * IN)


def test_revit_style_only_in_feet_inches_mode():
    assert parse_length("1 1/2", FRAC) == pytest.approx(1.5 * IN)
    assert parse_length("3", UnitSettings(mode=UnitMode.ARCHITECTURAL, input_style="autocad")) == pytest.approx(3 * IN)
    with pytest.raises(UnitParseError):
        parse_length("3 4", MM)
    assert UnitSettings.from_dict({"mode": "architectural"}).input_style == "revit"


def test_revit_round_trip():
    import random as _r
    rng = _r.Random(3)
    for _ in range(300):
        mm = rng.randint(-50000, 50000) / 16 * IN
        assert parse_length(format_length(mm, REVIT), REVIT) == pytest.approx(mm, abs=1e-9)
