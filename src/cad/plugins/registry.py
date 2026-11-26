"""Finds format plugins: the built-in ones and any `.py` files in the user's plugins folder."""
from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import sys
import traceback
from pathlib import Path

from .base import FormatPlugin, PluginError


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, FormatPlugin] = {}
        self.load_errors: list[str] = []       # shown in Options > Plugins
        self._builtins_loaded = False

    # -------------------------------------------------------------- registration
    def register(self, plugin: FormatPlugin, replace: bool = False) -> None:
        if not isinstance(plugin, FormatPlugin):
            raise TypeError("plugins must subclass cad.plugins.FormatPlugin")
        if not plugin.id or not plugin.extensions:
            raise ValueError(f"plugin {plugin!r} needs an id and at least one extension")
        if plugin.id in self._plugins and not replace:
            raise ValueError(f"a plugin with id {plugin.id!r} is already registered")
        self._plugins[plugin.id] = plugin

    def unregister(self, plugin_id: str) -> None:
        self._plugins.pop(plugin_id, None)

    def load_builtins(self) -> None:
        if self._builtins_loaded:
            return
        self._builtins_loaded = True
        from . import formats
        names = {info.name for info in pkgutil.iter_modules(formats.__path__)} | set(formats.BUILTIN_MODULES)
        for name in sorted(names):
            try:
                mod = importlib.import_module(f"{formats.__name__}.{name}")
            except Exception:          # a broken built-in must not stop the app
                self.load_errors.append(f"Built-in plugin {name} failed to load:\n{traceback.format_exc(limit=3)}")
                continue
            for p in getattr(mod, "PLUGINS", ()):
                p.builtin = True
                self.register(p, replace=True)

    def load_folder(self, folder: str | os.PathLike) -> list[str]:
        """Load every `*.py` in folder that defines PLUGINS = [...]. Returns the ids loaded."""
        loaded: list[str] = []
        folder = Path(folder)
        if not folder.is_dir():
            return loaded
        for path in sorted(folder.glob("*.py")):
            name = f"cad_user_plugin_{path.stem}"
            try:
                spec = importlib.util.spec_from_file_location(name, path)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                plugins = list(getattr(mod, "PLUGINS", ()))
                if not plugins:
                    self.load_errors.append(f"{path.name}: defines no PLUGINS list")
                for p in plugins:
                    self.register(p, replace=True)       # a user plugin may override a built-in one
                    loaded.append(p.id)
            except Exception:
                self.load_errors.append(f"{path.name} failed to load:\n{traceback.format_exc(limit=3)}")
        return loaded

    # -------------------------------------------------------------- lookup
    def all(self) -> list[FormatPlugin]:
        self.load_builtins()
        return sorted(self._plugins.values(), key=lambda p: p.name.lower())

    def get(self, plugin_id: str) -> FormatPlugin:
        self.load_builtins()
        try:
            return self._plugins[plugin_id]
        except KeyError:
            raise PluginError(f"No file format called {plugin_id!r}.") from None

    def importers(self) -> list[FormatPlugin]:
        return [p for p in self.all() if p.can_import]

    def exporters(self) -> list[FormatPlugin]:
        return [p for p in self.all() if p.can_export]

    def for_path(self, path: str, purpose: str = "import") -> FormatPlugin:
        ext = os.path.splitext(path)[1].lower()
        cands = [p for p in (self.importers() if purpose == "import" else self.exporters()) if ext in p.extensions]
        if not cands:
            what = "open" if purpose == "import" else "save"
            raise PluginError(f"I can't {what} {ext or 'files without an extension'} files.")
        return cands[0]

    def import_filters(self) -> list[str]:
        return [p.file_filter() for p in self.importers()]

    def export_filters(self) -> list[str]:
        return [p.file_filter() for p in self.exporters()]


registry = PluginRegistry()
