"""The Document: tables, entities, and undoable transactions."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field, replace
from typing import Callable, Iterator

from ..units import UnitMode, UnitSettings
from .entities import MODEL_SPACE, Entity
from .tables import BlockDefinition, DimStyle, Group, Layout, default_dimstyle
from .styles import BYLAYER, LW_BYLAYER, LW_DEFAULT, STANDARD_LINETYPES, ColorValue, Linetype


class DocumentError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Layer:
    name: str
    color: ColorValue = 7
    linetype: str = "Continuous"
    lineweight: float = LW_DEFAULT
    on: bool = True
    frozen: bool = False
    locked: bool = False
    plot: bool = True
    description: str = ""

    @property
    def visible(self) -> bool:
        return self.on and not self.frozen

    def to_dict(self) -> dict:
        return {"name": self.name, "color": self.color, "linetype": self.linetype,
                "lineweight": self.lineweight, "on": self.on, "frozen": self.frozen,
                "locked": self.locked, "plot": self.plot, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> "Layer":
        return cls(name=d["name"], color=d.get("color", 7), linetype=d.get("linetype", "Continuous"),
                   lineweight=float(d.get("lineweight", LW_DEFAULT)), on=bool(d.get("on", True)),
                   frozen=bool(d.get("frozen", False)), locked=bool(d.get("locked", False)),
                   plot=bool(d.get("plot", True)), description=d.get("description", ""))


@dataclass(frozen=True, slots=True)
class Header:
    units: UnitSettings = UnitSettings()
    ltscale: float = 1.0
    current_layer: str = "0"
    current_color: ColorValue = BYLAYER
    current_linetype: str = "ByLayer"
    current_lineweight: float = LW_BYLAYER
    grid_spacing: float = 10.0        # mm
    snap_spacing: float = 10.0        # mm
    point_size_px: float = 5.0
    text_height: float = 2.5          # default height for new text
    current_dimstyle: str = "Standard"
    hatch_pattern: str = "ANSI31"
    hatch_scale: float = 1.0
    hatch_angle: float = 0.0
    extra: dict = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict:
        d = {"units": self.units.to_dict(), "ltscale": self.ltscale, "current_layer": self.current_layer,
             "current_color": self.current_color, "current_linetype": self.current_linetype,
             "current_lineweight": self.current_lineweight, "grid_spacing": self.grid_spacing,
             "snap_spacing": self.snap_spacing, "point_size_px": self.point_size_px,
             "text_height": self.text_height, "current_dimstyle": self.current_dimstyle,
             "hatch_pattern": self.hatch_pattern, "hatch_scale": self.hatch_scale,
             "hatch_angle": self.hatch_angle}
        d.update(self.extra)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Header":
        known = {"units", "ltscale", "current_layer", "current_color", "current_linetype",
                 "current_lineweight", "grid_spacing", "snap_spacing", "point_size_px", "text_height",
                 "current_dimstyle", "hatch_pattern", "hatch_scale", "hatch_angle"}
        return cls(
            units=UnitSettings.from_dict(d.get("units", {})),
            ltscale=float(d.get("ltscale", 1.0)),
            current_layer=d.get("current_layer", "0"),
            current_color=d.get("current_color", BYLAYER),
            current_linetype=d.get("current_linetype", "ByLayer"),
            current_lineweight=float(d.get("current_lineweight", LW_BYLAYER)),
            grid_spacing=float(d.get("grid_spacing", 10.0)),
            snap_spacing=float(d.get("snap_spacing", 10.0)),
            point_size_px=float(d.get("point_size_px", 5.0)),
            text_height=float(d.get("text_height", 2.5)),
            current_dimstyle=str(d.get("current_dimstyle", "Standard")),
            hatch_pattern=str(d.get("hatch_pattern", "ANSI31")),
            hatch_scale=float(d.get("hatch_scale", 1.0)),
            hatch_angle=float(d.get("hatch_angle", 0.0)),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass(slots=True)
class ChangeSet:
    """What changed since the last notification. Listeners use it to update incrementally."""
    added: set[int] = field(default_factory=set)
    removed: set[int] = field(default_factory=set)
    modified: set[int] = field(default_factory=set)
    layers: bool = False
    linetypes: bool = False
    header: bool = False
    reset: bool = False      # whole document replaced
    tables: set[str] = field(default_factory=set)    # other tables: block, dimstyle, group, layout, constraint

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.modified or self.layers
                    or self.linetypes or self.header or self.reset or self.tables)

    def note_entity(self, handle: int, before, after) -> None:
        if before is None and after is not None:
            if handle in self.removed:
                self.removed.discard(handle)
                self.modified.add(handle)
            else:
                self.added.add(handle)
        elif before is not None and after is None:
            if handle in self.added:
                self.added.discard(handle)
            else:
                self.modified.discard(handle)
                self.removed.add(handle)
        elif handle not in self.added:
            self.modified.add(handle)


# change record: (table, key, before, after)
Change = tuple[str, object, object, object]


@dataclass(slots=True)
class Transaction:
    name: str
    changes: list[Change] = field(default_factory=list)


Listener = Callable[["Document", ChangeSet], None]


class Document:
    """A drawing. All edits go through transactions so they can be undone."""

    def __init__(self, units: UnitSettings | None = None) -> None:
        units = units or UnitSettings()
        header = Header(units=units)
        if units.mode is not UnitMode.MM:
            header = replace(header, grid_spacing=25.4, snap_spacing=25.4 / units.denominator * 4,
                             text_height=25.4 / 8)
        self.header: Header = header
        self.layers: dict[str, Layer] = {"0": Layer("0")}
        self.linetypes: dict[str, Linetype] = {lt.name: lt for lt in STANDARD_LINETYPES}
        self.entities: dict[int, Entity] = {}
        self.blocks: dict[str, BlockDefinition] = {}
        self.dimstyles: dict[str, DimStyle] = {"Standard": default_dimstyle(units)}
        self.groups: dict[str, Group] = {}
        self.layouts: dict[str, Layout] = {}
        self.constraints: dict[int, object] = {}
        self.next_handle: int = 1
        self.pre_commit_hooks: list = []      # fn(doc, tx) may add changes before a commit closes
        self._geo_cache: dict[int, tuple] = {}
        self._in_hooks = False
        self.extra: dict = {}              # unknown top-level keys from newer files
        self.manifest_extra: dict = {}     # unknown manifest keys from newer files
        self.extra_members: dict[str, bytes] = {}   # unknown files inside the .cadz zip
        self.path: str | None = None
        self.current_space: str = MODEL_SPACE     # where new objects go (UI state, not saved)

        self._tx: Transaction | None = None
        self._tx_depth = 0
        self._undo: list[Transaction] = []
        self._redo: list[Transaction] = []
        self._pending = ChangeSet()
        self._listeners: list[Listener] = []
        self.revision = 0
        self.saved_revision = 0

    # ------------------------------------------------------------ listeners
    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Listener) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(fn)

    def flush(self) -> None:
        """Send pending changes to listeners."""
        if self._pending.is_empty():
            return
        cs, self._pending = self._pending, ChangeSet()
        for fn in list(self._listeners):
            fn(self, cs)

    def notify_reset(self) -> None:
        self._pending = ChangeSet(reset=True)
        self.flush()

    # ------------------------------------------------------------ state
    @property
    def is_modified(self) -> bool:
        return self.revision != self.saved_revision

    def mark_saved(self) -> None:
        self.saved_revision = self.revision

    @property
    def in_transaction(self) -> bool:
        return self._tx is not None

    # ------------------------------------------------------------ transactions
    @contextlib.contextmanager
    def transaction(self, name: str) -> Iterator[Transaction]:
        """Group edits into one undo step. Nested calls join the outer transaction."""
        if self._tx is not None:
            self._tx_depth += 1
            try:
                yield self._tx
            finally:
                self._tx_depth -= 1
            return
        tx = self.begin(name)
        try:
            yield tx
        except BaseException:
            self.rollback()
            raise
        else:
            self.commit()

    def begin(self, name: str) -> Transaction:
        if self._tx is not None:
            raise DocumentError("A transaction is already open")
        self._tx = Transaction(name)
        return self._tx

    def commit(self) -> None:
        tx = self._require_tx()
        if tx.changes and not self._in_hooks:
            self._in_hooks = True
            try:
                for hook in list(self.pre_commit_hooks) + [_associativity_hook]:
                    hook(self, tx)
            except BaseException:
                self._in_hooks = False
                self.rollback()          # nothing of a refused edit is kept
                raise
            finally:
                self._in_hooks = False
        self._tx = None
        if tx.changes:
            self._undo.append(tx)
            self._redo.clear()
        self.flush()

    def rollback(self) -> None:
        tx = self._require_tx()
        self._tx = None
        for change in reversed(tx.changes):
            self._apply(change, undo=True)
        self.flush()

    def _require_tx(self) -> Transaction:
        if self._tx is None:
            raise DocumentError("Edits must happen inside doc.transaction(...)")
        return self._tx

    def _record(self, table: str, key, before, after) -> None:
        tx = self._require_tx()
        change = (table, key, before, after)
        tx.changes.append(change)
        self._apply(change, undo=False)

    def _apply(self, change: Change, undo: bool) -> None:
        table, key, before, after = change
        value = before if undo else after
        prev = after if undo else before
        if table == "entity":
            if value is None:
                self.entities.pop(key, None)
            else:
                self.entities[key] = value
            self._pending.note_entity(key, prev, value)
        elif table == "layer":
            if value is None:
                self.layers.pop(key, None)
            else:
                self.layers[key] = value
            self._pending.layers = True
        elif table == "linetype":
            if value is None:
                self.linetypes.pop(key, None)
            else:
                self.linetypes[key] = value
            self._pending.linetypes = True
        elif table == "header":
            self.header = value
            self._pending.header = True
            self._geo_cache.clear()
        else:
            store = self._table(table)
            if value is None:
                store.pop(key, None)
            else:
                store[key] = value
            self._pending.tables.add(table)
            if table in ("block", "dimstyle"):
                self._geo_cache.clear()
        if table == "entity":
            self._geo_cache.pop(key, None)
        self.revision += 1

    def _table(self, name: str) -> dict:
        return {"block": self.blocks, "dimstyle": self.dimstyles, "group": self.groups,
                "layout": self.layouts, "constraint": self.constraints}[name]

    # ------------------------------------------------------------ generic tables
    def set_item(self, table: str, key, value) -> None:
        """Create or replace an item in blocks / dimstyles / groups / layouts / constraints."""
        self._record(table, key, self._table(table).get(key), value)

    def remove_item(self, table: str, key) -> None:
        before = self._table(table).get(key)
        if before is not None:
            self._record(table, key, before, None)

    def new_handle(self) -> int:
        h = self.next_handle
        self.next_handle += 1
        return h

    # ------------------------------------------------------------ geometry cache
    def geometry(self, e: Entity):
        """Drawable/snappable geometry of an entity (cached)."""
        from ..text import engine_generation
        from .geometry import build_geometry
        gen = engine_generation()
        hit = self._geo_cache.get(e.handle) if e.handle else None
        if hit is not None and hit[0] is e and hit[1] == gen:
            return hit[2]
        g = build_geometry(self, e)
        if e.handle and self.entities.get(e.handle) is e:
            self._geo_cache[e.handle] = (e, gen, g)
        return g

    def entities_in(self, space: str = MODEL_SPACE) -> list[Entity]:
        return [e for e in self.entities.values() if e.space == space]

    def dimstyle(self, name: str) -> DimStyle:
        return self.dimstyles.get(name) or self.dimstyles.get("Standard") or DimStyle()

    # ------------------------------------------------------------ undo / redo
    @property
    def can_undo(self) -> bool:
        return bool(self._undo) and self._tx is None

    @property
    def can_redo(self) -> bool:
        return bool(self._redo) and self._tx is None

    @property
    def undo_name(self) -> str | None:
        return self._undo[-1].name if self._undo else None

    @property
    def redo_name(self) -> str | None:
        return self._redo[-1].name if self._redo else None

    def undo(self) -> str | None:
        if not self.can_undo:
            return None
        tx = self._undo.pop()
        for change in reversed(tx.changes):
            self._apply(change, undo=True)
        self._redo.append(tx)
        self.flush()
        return tx.name

    def redo(self) -> str | None:
        if not self.can_redo:
            return None
        tx = self._redo.pop()
        for change in tx.changes:
            self._apply(change, undo=False)
        self._undo.append(tx)
        self.flush()
        return tx.name

    def clear_history(self) -> None:  # noqa: D102
        self._undo.clear()
        self._redo.clear()

    # ------------------------------------------------------------ entities
    def add(self, entity: Entity, use_current_props: bool = False) -> Entity:
        if use_current_props:
            h = self.header
            entity = entity.with_props(layer=h.current_layer, color=h.current_color,
                                       linetype=h.current_linetype, lineweight=h.current_lineweight,
                                       space=self.current_space)
        if entity.layer not in self.layers:
            raise DocumentError(f"Layer '{entity.layer}' does not exist")
        if entity.space != MODEL_SPACE and entity.space not in self.layouts:
            raise DocumentError(f"Layout '{entity.space}' does not exist")
        handle = entity.handle if entity.handle and entity.handle not in self.entities else self.next_handle
        self.next_handle = max(self.next_handle, handle + 1)
        entity = entity.with_props(handle=handle)
        self._record("entity", handle, None, entity)
        return entity

    def replace(self, entity: Entity) -> Entity:
        before = self.entities.get(entity.handle)
        if before is None:
            raise DocumentError(f"No entity with handle {entity.handle}")
        if entity.layer not in self.layers:
            raise DocumentError(f"Layer '{entity.layer}' does not exist")
        self._record("entity", entity.handle, before, entity)
        return entity

    def delete(self, handle: int) -> None:
        before = self.entities.get(handle)
        if before is None:
            raise DocumentError(f"No entity with handle {handle}")
        self._record("entity", handle, before, None)
        for g in list(self.groups.values()):
            if handle in g.handles:
                rest = g.handles - {handle}
                if rest:
                    self.set_item("group", g.name, replace(g, handles=rest))
                else:
                    self.remove_item("group", g.name)
        for cid, c in list(self.constraints.items()):
            if handle in getattr(c, "handles", ()):
                self.remove_item("constraint", cid)

    def get(self, handle: int) -> Entity | None:
        return self.entities.get(handle)

    def __len__(self) -> int:
        return len(self.entities)

    # ------------------------------------------------------------ layers
    def add_layer(self, layer: Layer) -> None:
        if not layer.name or any(c in layer.name for c in '<>/\\":;?*|=`'):
            raise DocumentError(f"Invalid layer name '{layer.name}'")
        if self.find_layer(layer.name) is not None:
            raise DocumentError(f"Layer '{layer.name}' already exists")
        self._record("layer", layer.name, None, layer)

    def update_layer(self, layer: Layer) -> None:
        before = self.layers.get(layer.name)
        if before is None:
            raise DocumentError(f"No layer '{layer.name}'")
        if layer.name == self.header.current_layer and layer.frozen:
            raise DocumentError("The current layer can't be frozen")
        self._record("layer", layer.name, before, layer)

    def rename_layer(self, old: str, new: str) -> None:
        if old == "0":
            raise DocumentError("Layer 0 can't be renamed")
        layer = self.layers.get(old)
        if layer is None:
            raise DocumentError(f"No layer '{old}'")
        if old == new:
            return
        if self.find_layer(new) is not None and new.lower() != old.lower():
            raise DocumentError(f"Layer '{new}' already exists")
        self._record("layer", old, layer, None)
        self._record("layer", new, None, replace(layer, name=new))
        for e in list(self.entities.values()):
            if e.layer == old:
                self.replace(e.with_props(layer=new))
        if self.header.current_layer == old:
            self.set_header(replace(self.header, current_layer=new))

    def delete_layer(self, name: str) -> None:
        if name == "0":
            raise DocumentError("Layer 0 can't be deleted")
        if name == self.header.current_layer:
            raise DocumentError("The current layer can't be deleted")
        if any(e.layer == name for e in self.entities.values()):
            raise DocumentError(f"Layer '{name}' still has objects on it")
        before = self.layers.get(name)
        if before is None:
            raise DocumentError(f"No layer '{name}'")
        self._record("layer", name, before, None)

    def find_layer(self, name: str) -> Layer | None:
        low = name.lower()
        for n, layer in self.layers.items():
            if n.lower() == low:
                return layer
        return None

    def set_current_layer(self, name: str) -> None:
        layer = self.layers.get(name)
        if layer is None:
            raise DocumentError(f"No layer '{name}'")
        if layer.frozen:
            raise DocumentError("A frozen layer can't be made current")
        self.set_header(replace(self.header, current_layer=name))

    # ------------------------------------------------------------ linetypes / header
    def add_linetype(self, lt: Linetype) -> None:
        if lt.name in self.linetypes:
            raise DocumentError(f"Linetype '{lt.name}' already exists")
        self._record("linetype", lt.name, None, lt)

    def set_header(self, header: Header) -> None:
        if header == self.header:
            return
        self._record("header", None, self.header, header)

    # ------------------------------------------------------------ effective styles
    def effective_layer(self, e: Entity) -> Layer:
        return self.layers.get(e.layer) or self.layers["0"]

    def effective_color(self, e: Entity) -> ColorValue:
        if e.color == BYLAYER or e.color == 0:
            return self.effective_layer(e).color
        return e.color

    def effective_linetype(self, e: Entity) -> Linetype:
        name = e.linetype
        if name.lower() in ("bylayer", "byblock"):
            name = self.effective_layer(e).linetype
        return self.linetypes.get(name) or self.linetypes["Continuous"]

    def effective_lineweight(self, e: Entity) -> float:
        lw = e.lineweight
        if lw in (-1.0, -2.0):
            lw = self.effective_layer(e).lineweight
        return lw

    def is_visible(self, e: Entity) -> bool:
        layer = self.layers.get(e.layer)
        return layer is None or layer.visible

    def is_locked(self, e: Entity) -> bool:
        layer = self.layers.get(e.layer)
        return layer is not None and layer.locked


def _associativity_hook(doc: "Document", tx) -> None:
    """Dimensions, hatches and arrays follow their objects (always runs last, after constraints)."""
    from ..associative import AssociativityManager
    AssociativityManager.update(doc, tx)
