"""Named tables stored in a drawing: blocks, dimension styles, groups, layouts."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..geom2d.vec import Vec
from ..units import UnitMode, UnitSettings
from .entities import Entity, entity_from_dict, entity_to_dict


@dataclass(frozen=True, slots=True)
class BlockDefinition:
    """A reusable named group of objects. Entity handles inside are local to the block."""
    name: str
    base: Vec = (0.0, 0.0)
    entities: tuple[Entity, ...] = ()
    description: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "base": list(self.base), "description": self.description,
                "entities": [entity_to_dict(e) for e in self.entities]}

    @classmethod
    def from_dict(cls, d: dict) -> "BlockDefinition":
        return cls(name=d["name"], base=(float(d.get("base", [0, 0])[0]), float(d.get("base", [0, 0])[1])),
                   entities=tuple(entity_from_dict(x) for x in d.get("entities", [])),
                   description=d.get("description", ""))

    def attdefs(self):
        from .entities import AttributeDefinition
        return [e for e in self.entities if isinstance(e, AttributeDefinition)]


@dataclass(frozen=True, slots=True)
class DimStyle:
    """Sizes are paper sizes in mm; `scale` multiplies them all (AutoCAD DIMSCALE)."""
    name: str = "Standard"
    text_height: float = 2.5
    arrow_size: float = 2.5
    arrow: str = "closed"           # closed, tick, dot, open
    ext_offset: float = 0.625       # gap between the object and the extension line
    ext_extension: float = 1.25     # how far extension lines go past the dimension line
    text_gap: float = 0.625
    center_mark: float = 2.5
    scale: float = 1.0
    decimal_places: int = -1        # -1: use the drawing's unit precision
    font: str = "Arial"

    def size(self, attr: str) -> float:
        return getattr(self, attr) * self.scale

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "DimStyle":
        fields_ = cls.__dataclass_fields__
        return cls(**{k: type(getattr(cls(), k))(v) for k, v in d.items() if k in fields_})


def default_dimstyle(units: UnitSettings) -> DimStyle:
    if units.mode is UnitMode.MM:
        return DimStyle()
    inch = 25.4
    return DimStyle(text_height=inch / 8, arrow_size=inch / 8,
                    arrow="tick" if units.mode is UnitMode.ARCHITECTURAL else "closed",
                    ext_offset=inch / 16, ext_extension=inch / 8, text_gap=inch / 16, center_mark=inch / 8)


@dataclass(frozen=True, slots=True)
class Group:
    name: str
    handles: frozenset[int] = frozenset()
    description: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "handles": sorted(self.handles), "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> "Group":
        return cls(d["name"], frozenset(int(h) for h in d.get("handles", [])), d.get("description", ""))


PAPER_SIZES: dict[str, tuple[float, float]] = {        # landscape width x height, mm
    "ISO A4": (297, 210), "ISO A3": (420, 297), "ISO A2": (594, 420), "ISO A1": (841, 594), "ISO A0": (1189, 841),
    "Letter (8.5 x 11 in)": (279.4, 215.9), "Tabloid (11 x 17 in)": (431.8, 279.4),
    "ANSI C (17 x 22 in)": (558.8, 431.8), "ANSI D (22 x 34 in)": (863.6, 558.8),
    "ARCH D (24 x 36 in)": (914.4, 609.6), "ARCH E (36 x 48 in)": (1219.2, 914.4),
}


@dataclass(frozen=True, slots=True)
class Layout:
    """A paper sheet. Its contents are the entities whose `space` is this layout's name."""
    name: str
    paper: str = "ISO A3"
    width: float = 420.0           # mm (landscape)
    height: float = 297.0
    order: int = 1
    portrait: bool = False

    @property
    def size(self) -> tuple[float, float]:
        return (self.height, self.width) if self.portrait else (self.width, self.height)

    def with_paper(self, paper: str, portrait: bool | None = None) -> "Layout":
        w, h = PAPER_SIZES[paper]
        return replace(self, paper=paper, width=w, height=h,
                       portrait=self.portrait if portrait is None else portrait)

    def to_dict(self) -> dict:
        return {"name": self.name, "paper": self.paper, "width": self.width, "height": self.height,
                "order": self.order, "portrait": self.portrait}

    @classmethod
    def from_dict(cls, d: dict) -> "Layout":
        return cls(d["name"], d.get("paper", "ISO A3"), float(d.get("width", 420)), float(d.get("height", 297)),
                   int(d.get("order", 1)), bool(d.get("portrait", False)))


_ = field


SKETCH_PREFIX = "*Sketch:"


def sketch_space(name: str) -> str:
    return SKETCH_PREFIX + name


def is_sketch_space(space: str) -> bool:
    return space.startswith(SKETCH_PREFIX)


@dataclass(frozen=True, slots=True)
class Sketch:
    """A drawing plane in 3D. Its 2D objects have space == "*Sketch:<name>"."""
    name: str
    origin: tuple = (0.0, 0.0, 0.0)
    xdir: tuple = (1.0, 0.0, 0.0)
    normal: tuple = (0.0, 0.0, 1.0)
    visible: bool = True

    @property
    def space(self) -> str:
        return sketch_space(self.name)

    def plane(self):
        from ..solids import Plane
        return Plane(tuple(self.origin), tuple(self.xdir), tuple(self.normal))

    def to_dict(self) -> dict:
        return {"name": self.name, "origin": list(self.origin), "xdir": list(self.xdir), "normal": list(self.normal),
                "visible": self.visible}

    @classmethod
    def from_dict(cls, d: dict) -> "Sketch":
        return cls(d["name"], tuple(float(v) for v in d.get("origin", (0, 0, 0))),
                   tuple(float(v) for v in d.get("xdir", (1, 0, 0))), tuple(float(v) for v in d.get("normal", (0, 0, 1))),
                   bool(d.get("visible", True)))
