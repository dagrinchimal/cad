"""Spatial index over document entities (picking, snapping, window selection)."""
from __future__ import annotations

import math

from rtree import index as rindex

from .geom2d import BBox, Vec, bbox_contains, segment_hits_rect
from .geom2d.primitives import Arc as ArcPrim
from .model import ChangeSet, Document, Entity, Point


class SpatialIndex:
    """Keeps an R-tree of entity bounding boxes in sync with a Document."""

    def __init__(self, doc: Document) -> None:
        self.doc = doc
        self._boxes: dict[int, BBox] = {}
        self._tree = rindex.Index(interleaved=True)
        self.rebuild()
        doc.add_listener(self._on_change)

    def detach(self) -> None:
        self.doc.remove_listener(self._on_change)

    # -------------------------------------------------------------- maintenance
    def rebuild(self) -> None:
        self._boxes = {}
        items = []
        for h, e in self.doc.entities.items():
            b = e.bbox()
            if b is not None:
                self._boxes[h] = b
                items.append((h, b, None))
        if items:
            self._tree = rindex.Index(iter(items), interleaved=True)
        else:
            self._tree = rindex.Index(interleaved=True)

    def _remove(self, h: int) -> None:
        b = self._boxes.pop(h, None)
        if b is not None:
            self._tree.delete(h, b)

    def _insert(self, h: int) -> None:
        e = self.doc.entities.get(h)
        if e is None:
            return
        b = e.bbox()
        if b is not None:
            self._boxes[h] = b
            self._tree.insert(h, b)

    def _on_change(self, doc: Document, cs: ChangeSet) -> None:
        if cs.reset:
            self.rebuild()
            return
        for h in cs.removed:
            self._remove(h)
        for h in cs.modified:
            self._remove(h)
            self._insert(h)
        for h in cs.added:
            self._insert(h)

    # -------------------------------------------------------------- queries
    def extents(self) -> BBox | None:
        if not self._boxes:
            return None
        b = self._tree.bounds
        if b[0] > b[2]:
            return None
        return (b[0], b[1], b[2], b[3])

    def query(self, rect: BBox) -> list[int]:
        return list(self._tree.intersection(rect))

    def near(self, pt: Vec, radius: float, visible_only: bool = True) -> list[Entity]:
        rect = (pt[0] - radius, pt[1] - radius, pt[0] + radius, pt[1] + radius)
        out = []
        for h in self._tree.intersection(rect):
            e = self.doc.entities.get(h)
            if e is not None and (not visible_only or self.doc.is_visible(e)):
                out.append(e)
        return out

    def pick(self, pt: Vec, tol: float) -> Entity | None:
        """The visible entity closest to pt within tol."""
        best, best_d = None, math.inf
        for e in self.near(pt, tol):
            d = e.distance_to(pt)
            if d <= tol and d < best_d:
                best, best_d = e, d
        return best

    def select_window(self, rect: BBox, crossing: bool) -> list[int]:
        """Window: fully inside. Crossing: inside or touching."""
        out = []
        for h in self._tree.intersection(rect):
            e = self.doc.entities.get(h)
            if e is None or not self.doc.is_visible(e):
                continue
            b = self._boxes[h]
            if bbox_contains(rect, b):
                out.append(h)
            elif crossing and entity_touches_rect(e, rect):
                out.append(h)
        return out


def entity_touches_rect(e: Entity, rect: BBox) -> bool:
    if isinstance(e, Point):
        x, y = e.position
        return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]
    for prim in e.primitives():
        if isinstance(prim, ArcPrim):
            # coarse tessellation is plenty for selection
            pts = prim.tessellate(prim.r * 0.002)
            for i in range(len(pts) - 1):
                if segment_hits_rect(tuple(pts[i]), tuple(pts[i + 1]), rect):
                    return True
        elif segment_hits_rect(prim.p, prim.q, rect):
            return True
    return False
