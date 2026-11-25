"""Layouts (paper sheets): creating them with a border, title block and a viewport."""
from __future__ import annotations

from .geom2d import BBox
from .model import (
    MODEL_SPACE, AttributeDefinition, BlockDefinition, BlockReference, Document, Layer, Layout, Line, Polyline, Text,
    Viewport,
)
from .model.tables import PAPER_SIZES
from .units import UnitMode, standard_scales

TITLE_FIELDS = [
    # tag, label, default
    ("TITLE", "Title", "Untitled"),
    ("PROJECT", "Project", ""),
    ("DRAWN_BY", "Drawn by", ""),
    ("DATE", "Date", ""),
    ("SCALE", "Scale", ""),
    ("SHEET", "Sheet", "1 of 1"),
    ("DWG_NO", "Drawing no.", ""),
]

VIEWPORT_LAYER = "Viewports"
TITLE_LAYER = "Title Block"


def title_block_name(paper: str, portrait: bool) -> str:
    key = paper.split("(")[0].strip().replace(" ", "_").upper()
    return f"TITLE_BLOCK_{key}{'_P' if portrait else ''}"


def title_block(paper_w: float, paper_h: float, name: str) -> tuple[BlockDefinition, BBox]:
    """Border + title box with fill-in attributes. Returns the block and the free drawing area."""
    m = 10.0 if min(paper_w, paper_h) < 300 else 15.0
    x0, y0, x1, y1 = m, m, paper_w - m, paper_h - m
    ents: list = [Polyline(vertices=((x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)), closed=True,
                           lineweight=0.5, layer="0")]
    bw = min(180.0, (x1 - x0) * 0.6)
    row = 7.0
    bh = row * len(TITLE_FIELDS)
    bx0, by1 = x1 - bw, y0 + bh
    ents.append(Polyline(vertices=((bx0, y0, 0), (x1, y0, 0), (x1, by1, 0), (bx0, by1, 0)), closed=True,
                         lineweight=0.35, layer="0"))
    label_w = 28.0
    ents.append(Line(p1=(bx0 + label_w, y0), p2=(bx0 + label_w, by1), layer="0"))
    for i, (tag, label, default) in enumerate(TITLE_FIELDS):
        top = by1 - i * row
        if i:
            ents.append(Line(p1=(bx0, top), p2=(x1, top), layer="0"))
        base = top - row + 2.0
        ents.append(Text(insert=(bx0 + 2, base), text=label, height=2.0, layer="0"))
        height = 3.5 if tag == "TITLE" else 2.5
        ents.append(AttributeDefinition(tag=tag, prompt=label, default=default, insert=(bx0 + label_w + 2, base),
                                        height=height, layer="0"))
    for i, e in enumerate(ents):
        ents[i] = e.with_props(handle=i + 1)
    free = (x0 + 5, by1 + 5, x1 - 5, y1 - 5)
    return BlockDefinition(name=name, base=(0.0, 0.0), entities=tuple(ents),
                           description="Sheet border and title block"), free


def fit_scale(model_box: BBox | None, vp_w: float, vp_h: float, mode: UnitMode) -> float:
    """Largest standard scale that fits the model into the viewport."""
    if model_box is None:
        return 1.0
    mw = max(model_box[2] - model_box[0], 1e-9)
    mh = max(model_box[3] - model_box[1], 1e-9)
    exact = min(vp_w / mw, vp_h / mh)
    candidates = sorted({s.factor for s in standard_scales(mode)}, reverse=True)
    for f in candidates:
        if f <= exact * 1.0001:
            return f
    return exact


def ensure_layer(doc: Document, name: str, **kw) -> None:
    if name not in doc.layers:
        doc.add_layer(Layer(name, **kw))


def create_layout(doc: Document, name: str, paper: str | None = None, portrait: bool = False,
                  with_title_block: bool = True) -> Layout:
    """Add a layout sheet with a title block and one 'scale to fit' viewport (call inside a transaction)."""
    if paper is None:
        paper = "ISO A3" if doc.header.units.mode is UnitMode.MM else "Tabloid (11 x 17 in)"
    order = max((lo.order for lo in doc.layouts.values()), default=0) + 1
    layout = Layout(name, order=order).with_paper(paper, portrait)
    doc.set_item("layout", name, layout)
    w, h = layout.size
    free: BBox = (15, 15, w - 15, h - 15)
    if with_title_block:
        ensure_layer(doc, TITLE_LAYER, color=7)
        bname = title_block_name(paper, portrait)
        if bname not in doc.blocks:
            bdef, free = title_block(w, h, bname)
            doc.set_item("block", bname, bdef)
        else:
            _, free = title_block(w, h, bname)
        attribs = (("TITLE", "Untitled"), ("SHEET", f"{order} of {order}"))
        doc.add(BlockReference(name=bname, insert=(0.0, 0.0), attribs=attribs, layer=TITLE_LAYER, space=name))
    ensure_layer(doc, VIEWPORT_LAYER, color=8, plot=False)
    cx, cy = (free[0] + free[2]) / 2, (free[1] + free[3]) / 2
    doc.add(Viewport(center=(cx, cy), width=free[2] - free[0], height=free[3] - free[1], fit=True,
                     layer=VIEWPORT_LAYER, space=name))
    return layout


def resolve_viewport(doc: Document, vp: Viewport, model_box: BBox | None) -> tuple[tuple[float, float], float]:
    """(view center, scale) actually shown: 'fit' viewports follow the model's extents."""
    if not vp.fit:
        return vp.view_center, vp.scale
    if model_box is None:
        return vp.view_center, vp.scale
    mw = max(model_box[2] - model_box[0], 1e-9)
    mh = max(model_box[3] - model_box[1], 1e-9)
    scale = min(vp.width / mw, vp.height / mh) * 0.95
    return ((model_box[0] + model_box[2]) / 2, (model_box[1] + model_box[3]) / 2), scale


def delete_layout(doc: Document, name: str) -> None:
    for h in [h for h, e in doc.entities.items() if e.space == name]:
        doc.delete(h)
    doc.remove_item("layout", name)


def rename_layout(doc: Document, old: str, new: str) -> None:
    lo = doc.layouts[old]
    from dataclasses import replace
    doc.set_item("layout", new, replace(lo, name=new))
    for e in [e for e in doc.entities.values() if e.space == old]:
        doc.replace(e.with_props(space=new))
    doc.remove_item("layout", old)


_ = (MODEL_SPACE, PAPER_SIZES)
