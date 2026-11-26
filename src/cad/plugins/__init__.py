"""Import/export plugins. Core code never names a file format; it asks the registry.

    from cad.plugins import registry
    plugin = registry.for_path("plan.dxf")
    doc = plugin.import_("plan.dxf", plugin.default_options("import"), report)

Built-in formats live in `cad/plugins/formats/`; users can drop extra `.py` files into the
plugins folder (see docs/PLUGINS.md).
"""
from .base import (
    Capabilities, ExportTarget, FormatPlugin, Option, PluginError, Report, describe_losses, document_features,
)
from .registry import PluginRegistry, registry

__all__ = ["Capabilities", "ExportTarget", "FormatPlugin", "Option", "PluginError", "Report",
           "describe_losses", "document_features", "PluginRegistry", "registry"]
