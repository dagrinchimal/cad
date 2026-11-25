"""Spatial index over document entities (picking, snapping, window selection)."""
from __future__ import annotations

import math

from rtree import index as rindex

from .geom2d import BBox, Vec, bbox_contains, bbox_overlaps, segment_hits_rect
from .geom2d.fill import point_in_loops
from .geom2d.primitives import Arc as ArcPrim
from .model import MODEL_SPACE, ChangeSet, Document, Entity


class SpatialIndex:
    """Keeps an R-tree of entity bounding boxes in sync with a Document.

    Queries are limited to one space (model space or a layout) at a time; set `space`.
    """

    def __init__(self, doc: Document) -> None:
        self.doc = doc
        self.space = MODEL_SPACE
        self._boxes: dict[int, BBox] = {}
        self._tree = rindex.Index(interleaved=True)
        self.rebuild()
        doc.add_listener(self._on_change)

    def detach(self) -> None:
        self.doc.remove_listener(self._on_change)

    # -------------------------------------------------------------- maintenance
    def _bbox(self, e: Entity) -> BBox | None:
        return self.doc.geometry(e).bbox

    def rebuild(self) -> None:
        self._boxes = {}
        items = []
        for h, e in self.doc.entities.items():
            b = self._bbox(e)
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
        b = self._bbox(e)
        if b is not None:
            self._boxes[h] = b
            self._tree.insert(h, b)

    def _on_change(self, doc: Document, cs: ChangeSet) -> None:
        if cs.reset or "block" in cs.tables or "dimstyle" in cs.tables or cs.header:
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
    def _ok(self, e: Entity | None, visible_only: bool) -> bool:
        return e is not None and e.space == self.space and (not visible_only or self.doc.is_visible(e))

    def extents(self, space: str | None = None) -> BBox | None:
        space = space or self.space
        boxes = [b for h, b in self._boxes.items() if self.doc.entities[h].space == space] \
            if space != MODEL_SPACE or len(self.doc.layouts) else None
        if boxes is None:
            if not self._boxes:
                return None
            b = self._tree.bounds
            return None if b[0] > b[2] else (b[0], b[1], b[2], b[3])
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))

    def query(self, rect: BBox) -> list[int]:
        return [h for h in self._tree.intersection(rect) if self.doc.entities[h].space == self.space]

    def near(self, pt: Vec, radius: float, visible_only: bool = True) -> list[Entity]:
        rect = (pt[0] - radius, pt[1] - radius, pt[0] + radius, pt[1] + radius)
        out = []
        for h in self._tree.intersection(rect):
            e = self.doc.entities.get(h)
            if self._ok(e, visible_only):
                out.append(e)
        return out

    def pick(self, pt: Vec, tol: float) -> Entity | None:
        """The visible entity closest to pt within tol (inside a hatch or text counts as distance 0)."""
        best, best_d = None, math.inf
        for e in self.near(pt, tol):
            d = self.doc.geometry(e).distance_to(pt)
            # prefer real edges over areas when both are hit
            if d <= tol and (d < best_d or (d == best_d == 0 and e.TYPE not in ("hatch",))):
                best, best_d = e, d
        return best

    def select_window(self, rect: BBox, crossing: bool) -> list[int]:
        """Window: fully inside. Crossing: inside or touching."""
        out = []
        for h in self._tree.intersection(rect):
            e = self.doc.entities.get(h)
            if not self._ok(e, True):
                continue
            b = self._boxes[h]
            if bbox_contains(rect, b):
                out.append(h)
            elif crossing and entity_touches_rect(self.doc, e, rect):
                out.append(h)
        return out


def entity_touches_rect(doc: Document, e: Entity, rect: BBox) -> bool:
    g = doc.geometry(e)
    for p in g.nodes + g.insertions:
        if rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]:
            return True
    for prim in g.prims():
        if not bbox_overlaps(prim.bbox(), rect):
            continue
        if isinstance(prim, ArcPrim):
            pts = prim.tessellate(prim.r * 0.002)
            for i in range(len(pts) - 1):
                if segment_hits_rect(tuple(pts[i]), tuple(pts[i + 1]), rect):
                    return True
        elif segment_hits_rect(prim.p, prim.q, rect):
            return True
    # rectangle entirely inside a filled area / text box
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    for loops in g.pick_areas:
        if point_in_loops(cx, cy, loops):
            return True
        for lp in loops:
            for i in range(len(lp)):
                if segment_hits_rect(tuple(lp[i]), tuple(lp[(i + 1) % len(lp)]), rect):
                    return True
    return False
