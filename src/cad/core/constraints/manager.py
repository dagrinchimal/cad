"""Keeps constraints satisfied: re-solves inside the same undo step whenever constrained geometry changes."""
from __future__ import annotations

from ..model import Document
from .solver import ConstraintError, solve_for


class ConstraintManager:
    def __init__(self, doc: Document) -> None:
        self.doc = doc
        self.prefer: dict[int, float] = {}      # set by commands: these objects should move least
        self.last_dof: int | None = None
        self.enabled = True
        doc.pre_commit_hooks.append(self._hook)

    def detach(self) -> None:
        if self._hook in self.doc.pre_commit_hooks:
            self.doc.pre_commit_hooks.remove(self._hook)

    def _hook(self, doc: Document, tx) -> None:
        if not self.enabled or not doc.constraints:
            return
        changed: set[int] = set()
        table_changed = False
        for table, key, before, after in tx.changes:
            if table == "entity" and after is not None:
                changed.add(key)
            elif table == "constraint":
                table_changed = True
                c = after or before
                changed |= set(c.handles)
        constrained = set()
        for c in doc.constraints.values():
            constrained |= c.handles
        seeds = changed & constrained
        if not seeds:
            return
        prefer = dict(self.prefer)
        if not table_changed:
            for h in changed:                     # what the user just moved should stay where they put it
                prefer.setdefault(h, 1000.0)
        try:
            result = solve_for(doc, seeds, prefer)
        finally:
            self.prefer = {}
        if result is None:
            return
        self.last_dof = result.dof
        for h, e in result.entities.items():
            if doc.entities.get(h) != e:
                doc.replace(e)


__all__ = ["ConstraintManager", "ConstraintError"]
