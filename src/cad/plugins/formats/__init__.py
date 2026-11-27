"""Built-in format plugins. Each module defines PLUGINS = [...]."""

# Listed explicitly too, for frozen builds where the package folder can't be scanned.
BUILTIN_MODULES = ("native_cadz", "dxf", "dwg", "pdf", "svg", "raster", "hpgl", "solid3d")
