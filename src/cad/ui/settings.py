"""Program settings (not stored in drawings), and where files live.

Portable mode: if a file named `portable.flag` sits next to the program,
settings, autosaves and logs are kept in a `data` folder beside it, so the
program can run from a USB stick without touching the user profile.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

from .. import APP_ID, ORG_NAME
from ..core.snaps import DEFAULT_OSNAPS, Osnap, SnapSettings


def program_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]          # repo root when running from source


def is_portable() -> bool:
    return (program_dir() / "portable.flag").exists()


def data_dir() -> Path:
    override = os.environ.get("CAD_DATA_DIR")
    if override:
        d = Path(override)
    elif is_portable():
        d = program_dir() / "data"
    else:
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
        d = Path(base or Path.home()) / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def autosave_dir() -> Path:
    d = data_dir() / "autosave"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _qsettings() -> QSettings:
    return QSettings(str(data_dir() / "settings.ini"), QSettings.Format.IniFormat)


def _bool(v, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "yes", "on")


class AppSettings:
    """Typed access to settings.ini."""

    def __init__(self) -> None:
        self.q = _qsettings()

    def get(self, key: str, default=None):
        return self.q.value(key, default)

    def set(self, key: str, value) -> None:
        self.q.setValue(key, value)

    def sync(self) -> None:
        self.q.sync()

    # ------------------------------------------------------- appearance
    @property
    def dark_theme(self) -> bool:
        return _bool(self.get("ui/dark_theme"), True)

    @dark_theme.setter
    def dark_theme(self, v: bool) -> None:
        self.set("ui/dark_theme", v)

    @property
    def ui_scale(self) -> float:
        try:
            return min(3.0, max(0.75, float(self.get("ui/scale", 1.0))))
        except (TypeError, ValueError):
            return 1.0

    @ui_scale.setter
    def ui_scale(self, v: float) -> None:
        self.set("ui/scale", float(v))

    @property
    def font_scale(self) -> float:
        try:
            return min(2.0, max(0.8, float(self.get("ui/font_scale", 1.0))))
        except (TypeError, ValueError):
            return 1.0

    @font_scale.setter
    def font_scale(self, v: float) -> None:
        self.set("ui/font_scale", float(v))

    @property
    def renderer(self) -> str:
        return str(self.get("ui/renderer", "auto"))

    @renderer.setter
    def renderer(self, v: str) -> None:
        self.set("ui/renderer", v)

    @property
    def show_lineweights(self) -> bool:
        return _bool(self.get("view/show_lineweights"), False)

    @show_lineweights.setter
    def show_lineweights(self, v: bool) -> None:
        self.set("view/show_lineweights", v)

    # ------------------------------------------------------- autosave
    @property
    def autosave_minutes(self) -> int:
        try:
            return max(0, int(self.get("files/autosave_minutes", 5)))
        except (TypeError, ValueError):
            return 5

    @autosave_minutes.setter
    def autosave_minutes(self, v: int) -> None:
        self.set("files/autosave_minutes", int(v))

    @property
    def recent_files(self) -> list[str]:
        v = self.get("files/recent", [])
        if isinstance(v, str):
            v = [v] if v else []
        return [x for x in (v or []) if x]

    def add_recent(self, path: str) -> None:
        items = [p for p in self.recent_files if os.path.normcase(p) != os.path.normcase(path)]
        self.set("files/recent", ([path] + items)[:10])

    # ------------------------------------------------------- drafting
    def snap_settings(self) -> SnapSettings:
        modes_txt = self.get("draft/osnap_modes")
        if modes_txt is None:
            modes = DEFAULT_OSNAPS
        else:
            if isinstance(modes_txt, str):
                modes_txt = [m for m in modes_txt.split(",") if m]
            modes = frozenset(Osnap(m) for m in modes_txt if m in Osnap._value2member_map_)
        try:
            inc = float(self.get("draft/polar_increment", 45.0))
            aperture = float(self.get("draft/aperture_px", 10.0))
        except (TypeError, ValueError):
            inc, aperture = 45.0, 10.0
        return SnapSettings(
            osnap_on=_bool(self.get("draft/osnap_on"), True),
            modes=modes,
            grid_snap_on=_bool(self.get("draft/grid_snap_on"), False),
            grid_on=_bool(self.get("draft/grid_on"), True),
            ortho_on=_bool(self.get("draft/ortho_on"), False),
            polar_on=_bool(self.get("draft/polar_on"), True),
            polar_increment_deg=inc,
            otrack_on=_bool(self.get("draft/otrack_on"), True),
            aperture_px=aperture,
        )

    def save_snap_settings(self, s: SnapSettings) -> None:
        self.set("draft/osnap_on", s.osnap_on)
        self.set("draft/osnap_modes", ",".join(sorted(m.value for m in s.modes)))
        self.set("draft/grid_snap_on", s.grid_snap_on)
        self.set("draft/grid_on", s.grid_on)
        self.set("draft/ortho_on", s.ortho_on)
        self.set("draft/polar_on", s.polar_on)
        self.set("draft/polar_increment", s.polar_increment_deg)
        self.set("draft/otrack_on", s.otrack_on)
        self.set("draft/aperture_px", s.aperture_px)
