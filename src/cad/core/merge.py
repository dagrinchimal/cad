"""Copying one drawing's model space into another (IMPORT, and pasting a whole file)."""
from __future__ import annotations

from dataclasses import replace

from .model import MODEL_SPACE, BlockReference, Document, Entity
from .model.tables import BlockDefinition


def _rename_refs(ents, renames: dict[str, str]):
    out = []
    for e in ents:
        if isinstance(e, BlockReference) and e.name in renames:
            e = replace(e, name=renames[e.name])
        out.append(e)
    return tuple(out)


def merge_into(target: Document, source: Document, offset: tuple[float, float] = (0.0, 0.0)) -> list[int]:
    """Add source's model-space objects (and the layers, linetypes, dimension styles and blocks they use)
    to target. Call inside a transaction. Returns the new handles.

    Existing layers/styles keep their settings. A block whose name is taken by a different block is
    renamed (Name_2, Name_3...)."""
    for name, lt in source.linetypes.items():
        if name not in target.linetypes:
            target.linetypes[name] = lt
    existing = {n.lower() for n in target.layers}
    for name, lay in source.layers.items():
        if name.lower() not in existing:
            target.add_layer(lay)
    for name, ds in source.dimstyles.items():
        if name not in target.dimstyles:
            target.set_item("dimstyle", name, ds)
    renames: dict[str, str] = {}
    for name, bdef in source.blocks.items():
        if name in target.blocks and target.blocks[name] != bdef:
            i = 2
            while f"{name}_{i}" in target.blocks or f"{name}_{i}" in source.blocks:
                i += 1
            renames[name] = f"{name}_{i}"
    for name, bdef in source.blocks.items():
        new_name = renames.get(name, name)
        if new_name in target.blocks and new_name == name:
            continue
        target.set_item("block", new_name, BlockDefinition(new_name, bdef.base, _rename_refs(bdef.entities, renames),
                                                           bdef.description))
    from .geom2d.transform import Affine2
    m = Affine2.translate(*offset) if offset != (0.0, 0.0) else None
    from .model import ArrayEntity
    from .model.geometry import explode_array
    added: list[int] = []
    for e in source.entities.values():
        if e.space != MODEL_SPACE:
            continue
        parts = explode_array(source, e) if isinstance(e, ArrayEntity) else [e]   # links would dangle
        for e2 in _rename_refs(parts, renames):
            if m is not None:
                e2 = e2.transformed(m)
            e2 = _without_links(e2)
            added.append(target.add(replace(e2, handle=0), use_current_props=False).handle)
    return added


def _without_links(e: Entity) -> Entity:
    """Handles inside the source don't mean anything in the target: drop associativity links."""
    from .model import Dimension, Hatch
    if isinstance(e, Dimension) and e.refs:
        return replace(e, refs=())
    if isinstance(e, Hatch) and e.sources:
        return replace(e, sources=frozenset(), seed=None)
    return e


__all__ = ["merge_into"]
