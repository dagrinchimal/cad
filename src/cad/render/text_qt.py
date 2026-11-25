"""Text engine using the system's TrueType fonts through Qt (needs a QGuiApplication)."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath

from ..core.text import TextLayout, TextRun, block_offset, wrap_lines

EM = 100.0          # outlines are extracted at this pixel size, then scaled


@lru_cache(maxsize=64)
def _font(name: str) -> tuple[QFont, QFontMetricsF, float]:
    f = QFont(name)
    f.setPixelSize(int(EM))
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    fm = QFontMetricsF(f)
    cap = fm.capHeight() or fm.ascent() * 0.7
    return f, fm, cap


@lru_cache(maxsize=8192)
def _outline(font_name: str, text: str) -> tuple[np.ndarray, ...]:
    f, _, _ = _font(font_name)
    path = QPainterPath()
    path.addText(0.0, 0.0, f, text)
    out = []
    for poly in path.toSubpathPolygons():
        n = poly.size()
        if n < 3:
            continue
        arr = np.array([(poly.at(i).x(), -poly.at(i).y()) for i in range(n)], dtype=np.float64)
        out.append(arr)
    return tuple(out)


@lru_cache(maxsize=4096)
def _glyph(font_name: str, ch: str) -> tuple[np.ndarray, float]:
    """Triangles of one character in font units (cached), and its advance width."""
    from ..core.geom2d.fill import triangulate
    _, fm, _ = _font(font_name)
    loops = list(_outline(font_name, ch)) if ch.strip() else []
    tris = triangulate(loops).reshape(-1, 2) if loops else np.zeros((0, 2))
    return tris, fm.horizontalAdvance(ch)


@lru_cache(maxsize=16384)
def _advance(font_name: str, text: str) -> float:
    _, fm, _ = _font(font_name)
    return fm.horizontalAdvance(text)


class QtTextEngine:
    def layout(self, run: TextRun) -> TextLayout:
        font_name = run.font or "Arial"
        _, _, cap = _font(font_name)
        s = run.height / cap
        sx = s * run.width_factor

        def measure(t: str) -> float:
            return _advance(font_name, t) * sx

        lines = wrap_lines(run.text, run.wrap_width, measure) if run.multiline else [run.text.replace("\n", " ")]
        lh = run.height * 1.667 * run.line_spacing
        widths = [measure(t) for t in lines]
        xs, y0 = block_offset(run, widths, lh)
        m = run.transform()
        chunks: list[np.ndarray] = []
        for i, (t, x) in enumerate(zip(lines, xs)):
            if not t.strip():
                continue
            yb = y0 - i * lh
            # glyph-by-glyph: each character is triangulated once and reused everywhere
            scale_line = measure(t) / max(sum(_glyph(font_name, ch)[1] for ch in t) * sx, 1e-12)
            pen = 0.0
            for ch in t:
                tris, adv = _glyph(font_name, ch)
                if len(tris):
                    chunks.append(np.column_stack(((tris[:, 0] + pen) * sx * scale_line + x, tris[:, 1] * s + yb)))
                pen += adv
        triangles = m.apply_array(np.vstack(chunks)).reshape(-1, 3, 2) if chunks else np.zeros((0, 3, 2))
        x_min = min(xs) if xs else 0.0
        x_max = max((x + w for x, w in zip(xs, widths)), default=0.0)
        top = y0 + run.height
        bottom = y0 - (len(lines) - 1) * lh - 0.3 * run.height
        box = [m.apply(p) for p in ((x_min, bottom), (x_max, bottom), (x_max, top), (x_min, top))]
        return TextLayout([], box, lines, triangles)
