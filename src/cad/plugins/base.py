"""The plugin contract: what a file format plugin declares and implements."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..core.model import MODEL_SPACE, Document


class PluginError(Exception):
    """A problem the user should read (bad file, missing converter, ...). The message is shown as-is."""


# ------------------------------------------------------------------ capabilities and loss warnings
class Capabilities:
    """Feature names a format can carry. A plugin lists the ones it keeps; anything a drawing uses that
    the format can't keep is reported before export."""
    LAYERS = "layers"
    COLORS = "colors"                  # AutoCAD index colors
    TRUE_COLORS = "true_colors"
    LINETYPES = "linetypes"
    LINEWEIGHTS = "lineweights"
    UNITS = "units"
    PAPER_SPACE = "paper_space"        # layouts with viewports
    TEXT = "text"                      # editable text (otherwise drawn as shapes)
    HATCH = "hatch"                    # editable hatches (otherwise drawn as lines/fills)
    BLOCKS = "blocks"
    ATTRIBUTES = "attributes"
    DIMENSIONS = "dimensions"          # editable dimensions (otherwise drawn as lines and text)
    CONSTRAINTS = "constraints"
    ASSOCIATIVITY = "associativity"    # dimensions/hatches/arrays following their objects
    ARRAYS = "arrays"                  # live arrays (otherwise separate copies)
    SOLIDS_3D = "3d"
    GROUPS = "groups"
    CURVES = "curves"                  # true arcs/splines (otherwise short straight pieces)

    ALL: ClassVar[frozenset[str]] = frozenset()


Capabilities.ALL = frozenset(v for k, v in vars(Capabilities).items() if k.isupper() and isinstance(v, str))

_FEATURE_TEXT = {
    "layers": "layers (everything is put on one layer)",
    "colors": "colors",
    "true_colors": "true (RGB) colors (nearest index color is used)",
    "linetypes": "linetypes (dashed lines become solid or are drawn as dashes)",
    "lineweights": "lineweights",
    "units": "the drawing's units setting",
    "paper_space": "layouts / sheets",
    "text": "editable text (text is drawn as shapes)",
    "hatch": "editable hatches (hatches are drawn as lines and fills)",
    "blocks": "blocks (block references are exploded)",
    "attributes": "block attributes (exported as plain text)",
    "dimensions": "editable dimensions (dimensions are drawn as lines and text)",
    "constraints": "geometric and dimensional constraints",
    "associativity": "associativity (dimensions, hatches and arrays won't follow their objects any more)",
    "arrays": "live arrays (copies are exported as separate objects)",
    "3d": "3D solids",
    "groups": "groups",
    "curves": "true curves (arcs and splines become short straight pieces)",
}


def document_features(doc: Document) -> dict[str, int]:
    """Which features this drawing uses, with how many things use each (for the loss warning)."""
    from ..core.model import (
        ArrayEntity, AttributeDefinition, BlockReference, Dimension, Hatch, MText, Text, Viewport,
    )
    from ..core.model.styles import BYBLOCK, BYLAYER
    f: dict[str, int] = {}

    def add(k: str, n: int = 1) -> None:
        f[k] = f.get(k, 0) + n

    if len(doc.layers) > 1:
        add("layers", len(doc.layers))
    for e in doc.entities.values():
        c = e.color
        if isinstance(c, str):
            add("true_colors")
        elif c not in (BYLAYER, BYBLOCK, 7):
            add("colors")
        if e.linetype not in ("ByLayer", "ByBlock", "Continuous"):
            add("linetypes")
        if e.lineweight >= 0:
            add("lineweights")
        if e.TYPE in ("circle", "arc", "ellipse", "spline") or (e.TYPE == "polyline" and any(v[2] for v in e.vertices)):
            add("curves")
        if isinstance(e, (Text, MText)):
            add("text")
        elif isinstance(e, Hatch):
            add("hatch")
            if e.sources:
                add("associativity")
        elif isinstance(e, Dimension):
            add("dimensions")
            if e.is_associative:
                add("associativity")
        elif isinstance(e, BlockReference):
            add("blocks")
            if e.attribs:
                add("attributes")
        elif isinstance(e, AttributeDefinition):
            add("attributes")
        elif isinstance(e, ArrayEntity):
            add("arrays")
            add("associativity")
        elif isinstance(e, Viewport):
            add("paper_space")
    for lay in doc.layers.values():
        if isinstance(lay.color, str):
            add("true_colors")
        elif lay.color != 7:
            add("colors")
        if lay.linetype != "Continuous":
            add("linetypes")
        if lay.lineweight >= 0:
            add("lineweights")
    if len(doc.layouts) > 0 and any(e.space != MODEL_SPACE for e in doc.entities.values()):
        add("paper_space")
    if doc.constraints:
        add("constraints", len(doc.constraints))
    if doc.groups:
        add("groups", len(doc.groups))
    f["units"] = 1                       # every drawing has units
    return f


def describe_losses(doc: Document, caps: frozenset[str] | set[str]) -> list[str]:
    """Plain-English list of what the format can't keep, for this drawing."""
    used = document_features(doc)
    out = []
    for k, n in used.items():
        if k in caps:
            continue
        if k == "true_colors" and "colors" not in caps:
            continue                                  # covered by the colors line
        if k == "attributes" and "blocks" not in caps:
            continue
        out.append(f"{_FEATURE_TEXT.get(k, k)}" + (f" — {n} in this drawing" if n > 1 else ""))
    return out


# ------------------------------------------------------------------ options
@dataclass(frozen=True, slots=True)
class Option:
    """One setting in a plugin's options dialog (the dialog is generated from these)."""
    key: str
    label: str
    kind: str = "choice"               # choice | bool | int | float | length | string | layout_set | path
    default: Any = None
    choices: tuple = ()                # for "choice": values, or (value, label) pairs
    help: str = ""
    minimum: float | None = None
    maximum: float | None = None

    def choice_items(self) -> list[tuple[Any, str]]:
        return [c if isinstance(c, tuple) else (c, str(c)) for c in self.choices]

    def validate(self, value: Any) -> Any:
        if self.kind == "choice":
            vals = [v for v, _ in self.choice_items()]
            if value not in vals:
                raise PluginError(f"{self.label}: choose one of {', '.join(map(str, vals))}.")
        elif self.kind == "bool":
            value = bool(value)
        elif self.kind in ("int", "float", "length"):
            value = int(value) if self.kind == "int" else float(value)
            if self.minimum is not None and value < self.minimum:
                raise PluginError(f"{self.label} must be at least {self.minimum:g}.")
            if self.maximum is not None and value > self.maximum:
                raise PluginError(f"{self.label} must be at most {self.maximum:g}.")
        return value


# ------------------------------------------------------------------ report
@dataclass
class Report:
    """What happened during an import or export. Shown to the user afterwards."""
    title: str = ""
    infos: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)     # e.g. {"LINE": 120} written/read
    skipped: dict[str, int] = field(default_factory=dict)    # what couldn't be read/written, by kind

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def count(self, kind: str, n: int = 1) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + n

    def skip(self, kind: str, n: int = 1) -> None:
        self.skipped[kind] = self.skipped.get(kind, 0) + n

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [self.title] if self.title else []
        if self.counts:
            lines.append("Objects: " + ", ".join(f"{n} {k}" for k, n in sorted(self.counts.items())))
        if self.skipped:
            lines.append("Not carried over: " + ", ".join(f"{n} {k}" for k, n in sorted(self.skipped.items())))
        lines += [f"Warning: {w}" for w in self.warnings]
        lines += [f"Error: {e}" for e in self.errors]
        lines += self.infos
        return "\n".join(lines)

    def merge(self, other: "Report") -> None:
        self.infos += other.infos
        for w in other.warnings:
            self.warn(w)
        self.errors += other.errors
        for k, n in other.counts.items():
            self.count(k, n)
        for k, n in other.skipped.items():
            self.skip(k, n)


# ------------------------------------------------------------------ the plugin contract
@dataclass(frozen=True, slots=True)
class ExportTarget:
    """What to export when a format draws sheets (PDF, images): the model, or named layouts."""
    spaces: tuple[str, ...] = ("*Model",)


class FormatPlugin:
    """Subclass this and set the class attributes. Implement `export` and/or `import_`."""
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    extensions: ClassVar[tuple[str, ...]] = ()
    can_import: ClassVar[bool] = False
    can_export: ClassVar[bool] = False
    capabilities: ClassVar[frozenset[str]] = frozenset()
    description: ClassVar[str] = ""
    builtin: bool = False

    def available(self) -> tuple[bool, str]:
        """(usable now, reason if not). E.g. DWG needs the ODA File Converter."""
        return True, ""

    def export_options(self, doc: Document | None = None) -> list[Option]:
        return []

    def import_options(self) -> list[Option]:
        return []

    def default_options(self, which: str = "export", doc: Document | None = None) -> dict[str, Any]:
        opts = self.export_options(doc) if which == "export" else self.import_options()
        return {o.key: o.default for o in opts}

    def checked_options(self, which: str, values: dict[str, Any], doc: Document | None = None) -> dict[str, Any]:
        opts = self.export_options(doc) if which == "export" else self.import_options()
        out = self.default_options(which, doc)
        for o in opts:
            if o.key in values:
                out[o.key] = o.validate(values[o.key])
        return out

    def export(self, doc: Document, path: str, options: dict[str, Any], report: Report) -> None:
        raise PluginError(f"{self.name} can't be exported.")

    def import_(self, path: str, options: dict[str, Any], report: Report) -> Document:
        raise PluginError(f"{self.name} can't be imported.")

    def losses(self, doc: Document) -> list[str]:
        return describe_losses(doc, self.capabilities)

    def file_filter(self) -> str:
        return f"{self.name} ({' '.join('*' + x for x in self.extensions)})"
