"""What the 3D view draws: shaded solids, their edges, and 2D objects placed on their planes (model z=0 or sketches)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core import solids as S
from ..core.model import MODEL_SPACE, Document, Solid, color_to_rgb, is_sketch_space
from ..core.model.tables import SKETCH_PREFIX

SKIP_WIRES = ("hatch", "text", "mtext", "dimension", "leader", "point", "viewport")
REFERENCE_LAYER = "Sketch reference"

STYLES = ("Wireframe", "Hidden", "Shaded", "Shaded with edges", "X-ray")
DEFAULT_STYLE = "Shaded with edges"


@dataclass
class SolidItem:
    handle: int
    vertices: np.ndarray           # (n,3)
    normals: np.ndarray            # (n,3)
    triangles: np.ndarray          # (m,3)
    tri_face: np.ndarray
    edges: list                    # (k,3) arrays
    rgb: tuple
    hole: bool = False             # see-through grey "hole shape"
    alpha: float = 1.0             # < 1 for holes and live previews


@dataclass
class WireItem:
    handle: int
    lines: list                    # (k,3) arrays
    rgb: tuple
    sketch: str = ""


@dataclass
class Scene3D:
    solids: list[SolidItem] = field(default_factory=list)
    wires: list[WireItem] = field(default_factory=list)

    def bbox(self):
        pts = [s.vertices for s in self.solids if len(s.vertices)]
        pts += [ln for w in self.wires for ln in w.lines]
        if not pts:
            return None
        a = np.vstack(pts)
        return (*a.min(axis=0), *a.max(axis=0))


class Scene3DBuilder:
    """Builds the scene from a document, re-meshing only entities that changed."""

    def __init__(self, doc: Document) -> None:
        self.doc = doc
        self._cache: dict[int, tuple[object, object]] = {}
        self.dark = True

    def _rgb(self, e) -> tuple:
        r, g, b = color_to_rgb(self.doc.effective_color(e), self.dark)
        return (r / 255.0, g / 255.0, b / 255.0)

    def build(self, show_wires: bool = True) -> Scene3D:
        doc = self.doc
        sc = Scene3D()
        alive = set()
        for h, e in doc.entities.items():
            if not doc.is_visible(e):
                continue
            if isinstance(e, Solid):
                if e.space != MODEL_SPACE:
                    continue
            elif not show_wires or e.TYPE in SKIP_WIRES or e.layer == REFERENCE_LAYER:
                continue
            elif e.space != MODEL_SPACE and not is_sketch_space(e.space):
                continue
            alive.add(h)
            hit = self._cache.get(h)
            key = (e, self._rgb(e), getattr(e, "hole", False))
            if hit is not None and hit[0] == key:
                item = hit[1]
            else:
                item = self._make(e)
                self._cache[h] = (key, item)
            if item is None:
                continue
            if isinstance(item, SolidItem):
                sc.solids.append(item)
            else:
                sk = doc.sketches.get(item.sketch) if item.sketch else None
                if item.sketch and (sk is None or not sk.visible):
                    continue
                sc.wires.append(item)
        for h in [h for h in self._cache if h not in alive]:
            del self._cache[h]
        return sc

    def _make(self, e):
        if isinstance(e, Solid):
            try:
                m = S.mesh(e.shape)
            except Exception:       # a broken shape shouldn't break the view
                return None
            return SolidItem(e.handle, m.vertices.astype(float), m.normals.astype(float), m.triangles,
                             m.tri_face, [np.asarray(x, float) for x in m.edges],
                             (0.70, 0.76, 0.86) if e.hole else self._rgb(e), e.hole, 0.3 if e.hole else 1.0)
        sketch = e.space[len(SKETCH_PREFIX):] if is_sketch_space(e.space) else ""
        plane = None
        if sketch:
            sk = self.doc.sketches.get(sketch)
            if sk is None:
                return None
            plane = sk.plane()
        lines = []
        try:
            prims = self.doc.geometry(e).prims()
        except Exception:
            return None
        b = e.bbox()
        tol = max((max(b[2] - b[0], b[3] - b[1]) if b else 1.0) * 2e-3, 1e-3)
        for p in prims:
            pts = np.asarray(p.tessellate(tol), float)
            if len(pts) < 2:
                continue
            if plane is None:
                xyz = np.column_stack([pts, np.zeros(len(pts))])
            else:
                o, xd, yd = np.array(plane.origin), np.array(plane.xdir), np.array(plane.ydir)
                xyz = o + np.outer(pts[:, 0], xd) + np.outer(pts[:, 1], yd)
            lines.append(xyz)
        if not lines:
            return None
        return WireItem(e.handle, lines, self._rgb(e), sketch)


def item_from_shape(shape, rgb=(1.0, 0.75, 0.25), alpha: float = 0.55, handle: int = -1) -> SolidItem | None:
    """A transient item (live preview while dragging)."""
    try:
        m = S.mesh(shape)
    except Exception:
        return None
    return SolidItem(handle, m.vertices.astype(float), m.normals.astype(float), m.triangles, m.tri_face,
                     [np.asarray(x, float) for x in m.edges], rgb, False, alpha)


def edge_segments(lines: list) -> np.ndarray:
    """List of (k,3) polylines -> (n, 2, 3) segments."""
    segs = [np.stack([ln[:-1], ln[1:]], axis=1) for ln in lines if len(ln) >= 2]
    return np.concatenate(segs) if segs else np.zeros((0, 2, 3))
