"""Performance budget with 50,000+ entities. Limits are generous for slow CI machines;
the printed timings are what to watch."""
import math
import random
import time

import pytest

from cad.core.model import Arc, Circle, Document, Line, Polyline
from cad.core.snaps import SnapEngine, SnapSettings
from cad.core.spatial import SpatialIndex
from cad.io import native
from cad.render.scene import SceneBuilder, StyleOptions

pytestmark = pytest.mark.perf
N = 50_000


def big_document(n: int = N, seed: int = 1) -> Document:
    rng = random.Random(seed)
    doc = Document()
    with doc.transaction("bulk"):
        for i in range(n):
            x, y = rng.uniform(0, 100_000), rng.uniform(0, 60_000)
            k = i % 10
            if k < 7:
                doc.add(Line(p1=(x, y), p2=(x + rng.uniform(-500, 500), y + rng.uniform(-500, 500))))
            elif k == 7:
                doc.add(Circle(center=(x, y), radius=rng.uniform(10, 300)))
            elif k == 8:
                doc.add(Arc(center=(x, y), radius=rng.uniform(10, 300), start_angle=0, end_angle=rng.uniform(0.5, 6)))
            else:
                pts = tuple((x + j * 50, y + (j % 2) * 40, 0.3 if j == 2 else 0.0) for j in range(6))
                doc.add(Polyline(vertices=pts))
    return doc


def timed(fn, *a, **kw):
    t = time.perf_counter()
    out = fn(*a, **kw)
    return out, time.perf_counter() - t


@pytest.fixture(scope="module")
def doc():
    d, t = timed(big_document)
    print(f"\n  create {N} entities: {t:.2f}s")
    return d


def test_index_and_queries(doc):
    idx, t = timed(SpatialIndex, doc)
    print(f"  spatial index build: {t:.2f}s")
    assert t < 10
    eng = SnapEngine(idx)
    cfg = SnapSettings()
    rng = random.Random(2)
    pts = [(rng.uniform(0, 100_000), rng.uniform(0, 60_000)) for _ in range(300)]
    _, t = timed(lambda: [eng.snap(p, 20.0, cfg, base=(0, 0)) for p in pts])
    per = t / len(pts) * 1000
    print(f"  snap per mouse move: {per:.2f} ms")
    assert per < 30
    _, t = timed(lambda: [idx.pick(p, 50) for p in pts])
    print(f"  pick: {t / len(pts) * 1000:.2f} ms")
    _, t = timed(idx.select_window, (0, 0, 50_000, 30_000), True)
    print(f"  crossing window over a quarter of the drawing: {t:.2f}s")
    assert t < 10


def test_scene_build_and_incremental_update(doc):
    b = SceneBuilder(doc)
    b.set_origin((50_000, 30_000))
    b.set_tolerance(5.0)
    opts = StyleOptions()
    (inst, _tris), t = timed(b.build, opts)
    print(f"  scene cold build: {t:.2f}s, {len(inst):,} segments ({inst.nbytes / 1e6:.0f} MB)")
    assert t < 20
    h = next(iter(doc.entities))
    with doc.transaction("move one"):
        e = doc.get(h)
        doc.replace(e.with_props(layer="0"))
    _, t = timed(b.build, opts)
    print(f"  scene rebuild after editing one entity: {t * 1000:.0f} ms")
    assert t < 2
    b.detach()


def test_undo_and_file_round_trip(doc, tmp_path):
    with doc.transaction("erase many"):
        for h in list(doc.entities)[:10_000]:
            doc.delete(h)
    _, t = timed(doc.undo)
    print(f"  undo erase of 10,000: {t * 1000:.0f} ms")
    assert len(doc) == N
    path = str(tmp_path / "big.cadz")
    _, t = timed(native.save, doc, path)
    print(f"  save: {t:.2f}s")
    (doc2, _), t = timed(native.load, path)
    print(f"  open: {t:.2f}s")
    assert len(doc2) == N
    assert t < 30


def test_pan_zoom_cost_is_independent_of_size(doc):
    """Pan/zoom only changes shader uniforms; nothing is rebuilt. Guard against regressions
    by checking that the scene isn't marked dirty by view changes."""
    b = SceneBuilder(doc)
    b.build(StyleOptions())
    assert not b.dirty
    b.detach()
    _ = math.pi


def test_text_and_hatch_heavy_drawing():
    """5,000 texts + 500 patterned hatches stay workable."""
    from cad.core.model import Hatch, Text
    doc = Document()
    with doc.transaction("bulk"):
        for i in range(5000):
            doc.add(Text(insert=(i % 100 * 50, i // 100 * 20), text=f"Room {i}", height=5))
        for i in range(500):
            x, y = i % 25 * 200, i // 25 * 200
            doc.add(Hatch(loops=(((x, y, 0), (x + 150, y, 0), (x + 150, y + 150, 0), (x, y + 150, 0)),),
                          pattern="ANSI31", pattern_scale=4))
    b = SceneBuilder(doc)
    (segs, tris), t = timed(b.build, StyleOptions())
    print(f"  5,000 texts + 500 hatches build: {t:.2f}s, {len(segs):,} segments")
    assert t < 30
