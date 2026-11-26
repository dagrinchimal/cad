"""Canvas controller: mouse/keyboard interaction, snapping, selection, view and overlays."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QLineEdit

from ..commands import (
    CommandRunner,
    GetAngle,
    GetDistance,
    GetEntity,
    GetNumber,
    GetPoint,
    GetSelection,
)
from ..commands.grips import grips_at
from ..core.dimedit import (
    EditableValue,
    EditError,
    apply_value,
    editable_values,
    format_value,
    parse_value,
)
from ..core.geom2d import Vec
from ..core.geom2d.vec import angle_of, dist, sub
from ..core.model import MODEL_SPACE, Document, Line, Polyline, Viewport
from ..core.points import named_points
from ..core.snaps import TRACKABLE, Osnap, SnapEngine, SnapResult, SnapSettings
from ..core.spatial import SpatialIndex
from ..core.units import format_angle, format_length
from ..render.canvas_base import ViewportView
from ..render.scene import (
    SceneBuilder,
    StyleOptions,
    grid_instances,
    rect_tris,
    solid_color_instances,
    solid_color_tris,
)
from ..render.view import ViewState
from .theme import colors

PICKBOX_PX = 5
GRIP_PX = 6            # grips react within this many pixels
VALUE_OFFSET_PX = 22   # temporary dimensions sit this far from the object


def wants_point(req) -> bool:
    """Requests answered by picking a (snapped) point in the drawing."""
    if isinstance(req, GetPoint):
        return req.mode != "pan"
    if isinstance(req, (GetDistance, GetAngle)):
        return True
    return isinstance(req, GetNumber) and req.base is not None
ACQUIRE_MS = 450
MAX_GRIP_ENTITIES = 300


class CanvasController(QObject):
    coords_changed = Signal(str)
    selection_changed = Signal()
    context_menu_requested = Signal(QPoint)
    forward_text = Signal(str)
    edit_requested = Signal(object)
    view_changed_signal = Signal()

    def __init__(self, canvas, doc: Document, index: SpatialIndex, runner: CommandRunner,
                 snap_cfg: SnapSettings, dark: bool = True, show_lineweights: bool = False) -> None:
        super().__init__(canvas)
        self.canvas = canvas
        self.runner = runner
        self.view = ViewState(width=max(1, canvas.width()), height=max(1, canvas.height()))
        canvas.view = self.view
        canvas.client = self
        self.cfg = snap_cfg
        self.opts = StyleOptions(dark_background=dark, show_lineweights=show_lineweights)
        self.dark = dark
        self.cursor_screen: tuple[float, float] | None = None
        self.cursor_model: Vec = (0.0, 0.0)
        self.snap: SnapResult | None = None
        self.hover: int | None = None
        self.pending_sel: set[int] = set()
        self.window_start: tuple[float, float] | None = None
        self.window_dragged = False
        self.pan_last: QPointF | None = None
        self.show_constraints = True
        self.space = MODEL_SPACE
        self.layout_views: dict[str, tuple[float, float, float]] = {}   # remembered view per space
        self.view_history: list[ViewState] = []
        self._last_history_push = 0.0
        self._acquire_target: tuple[Vec, Osnap] | None = None
        self.hot_grip: Vec | None = None
        self.value_editor: QLineEdit | None = None
        self._editing_value: EditableValue | None = None

        self._rebuild_timer = QTimer(self, singleShot=True, interval=0)
        self._rebuild_timer.timeout.connect(self.rebuild_scene)
        self._acquire_timer = QTimer(self, singleShot=True, interval=ACQUIRE_MS)
        self._acquire_timer.timeout.connect(self._acquire)
        self._regen_timer = QTimer(self, singleShot=True, interval=250)
        self._regen_timer.timeout.connect(self._auto_regen)

        self.doc: Document | None = None
        self.builder: SceneBuilder | None = None
        self.engine: SnapEngine | None = None
        self._apply_theme_colors()
        self.set_document(doc, index)
        runner.direction_provider = self.current_direction
        runner.listeners.append(self._on_runner_changed)

    # ================================================================ document
    def set_document(self, doc: Document, index: SpatialIndex) -> None:
        if self.doc is not None:
            self.doc.remove_listener(self._on_doc_change)
        if self.builder is not None:
            self.builder.detach()
        self.doc = doc
        self.index = index
        self.space = MODEL_SPACE
        index.space = MODEL_SPACE
        doc.current_space = MODEL_SPACE
        self.runner.ctx.space = MODEL_SPACE
        self.layout_views = {}
        self.builder = SceneBuilder(doc)
        self.engine = SnapEngine(index, doc.header.units)
        doc.add_listener(self._on_doc_change)
        self.pending_sel.clear()
        self.hover = None
        self.view_history.clear()
        self.zoom_extents(push=False)
        self.rebuild_scene()

    def _on_doc_change(self, doc: Document, cs) -> None:
        if cs.header:
            self.engine.units = doc.header.units
            self.update_grid()
        sel = self.runner.ctx.selection
        gone = {h for h in sel | self.pending_sel if h not in doc.entities}
        if gone:
            sel.difference_update(gone)
            self.pending_sel.difference_update(gone)
            self.selection_changed.emit()
        elif cs.modified & sel:
            self.selection_changed.emit()
        if self.hover is not None and self.hover not in doc.entities:
            self.hover = None
        self._rebuild_timer.start()

    def _on_runner_changed(self) -> None:
        if not self.runner.is_active:
            self.hot_grip = None
            self.engine.clear_acquired()
            self.pending_sel.clear()
            self.snap = None
        self._recompute_at_cursor()
        self.update_highlight()

    # ================================================================ scene building
    def _apply_theme_colors(self) -> None:
        c = colors(self.dark)
        self.canvas.data.background = QColor(c["canvas"])
        if self.dark:
            self.fg = QColor(230, 235, 240)
            self.highlight_rgba = (0.30, 0.65, 1.0, 1.0)
            self.hover_rgba = (0.55, 0.80, 1.0, 0.9)
            self.marker = QColor(255, 200, 40)
            self.track = QColor(110, 220, 120)
        else:
            self.fg = QColor(30, 30, 30)
            self.highlight_rgba = (0.0, 0.45, 0.95, 1.0)
            self.hover_rgba = (0.25, 0.55, 1.0, 0.9)
            self.marker = QColor(220, 110, 0)
            self.track = QColor(20, 150, 40)

    def space_opts(self) -> StyleOptions:
        """Layout sheets are white paper: color 7 prints black there, whatever the theme."""
        return StyleOptions(dark_background=self.dark and self.space == MODEL_SPACE,
                            show_lineweights=self.opts.show_lineweights)

    def set_theme(self, dark: bool) -> None:
        self.dark = dark
        self.opts = StyleOptions(dark_background=dark, show_lineweights=self.opts.show_lineweights)
        self._apply_theme_colors()
        self.update_grid()
        self.rebuild_scene()

    def set_show_lineweights(self, on: bool) -> None:
        self.opts = StyleOptions(dark_background=self.dark, show_lineweights=on)
        self.rebuild_scene()

    def rebuild_scene(self) -> None:
        b = self.builder
        if b.origin is None:
            ext = self.index.extents(MODEL_SPACE)
            if ext:
                b.set_origin((round((ext[0] + ext[2]) / 2, 3), round((ext[1] + ext[3]) / 2, 3)))
            else:
                b.set_origin((0.0, 0.0))
        data = self.canvas.data
        self.opts = self.space_opts()
        data.scene, data.scene_fill = b.build(self.opts, self.space)
        data.origin = b.origin
        data.linetypes = b.linetype_table()
        data.global_ltscale = self.doc.header.ltscale
        if self.space != MODEL_SPACE:
            data.model, data.model_fill = b.build(self.opts, MODEL_SPACE)
            # model-space points aren't drawn inside viewports (overlay only knows the current space)
            b.build(self.opts, self.space)
            data.model_version += 1
            self._update_layout_underlay()
        else:
            data.underlay_fill = data.underlay_fill[:0]
            data.viewports = []
        data.scene_version += 1
        self.update_grid(invalidate=False)
        self.update_highlight(invalidate=False)
        self._update_preview()
        self.canvas.invalidate()

    # ================================================================ layouts
    def set_space(self, space: str) -> None:
        if space == self.space:
            return
        if self.runner.is_active:
            self.runner.cancel()
        self.layout_views[self.space] = (self.view.cx, self.view.cy, self.view.scale)
        self.runner.ctx.selection.clear()
        self.space = space
        self.index.space = space
        self.runner.ctx.space = space
        self.doc.current_space = space
        self.hover = None
        saved = self.layout_views.get(space)
        if saved:
            self.view.cx, self.view.cy, self.view.scale = saved
            self.rebuild_scene()
            self._view_changed()
        else:
            self.rebuild_scene()
            self.zoom_extents(push=False)
        self.selection_changed.emit()

    def _update_layout_underlay(self) -> None:
        data = self.canvas.data
        lo = self.doc.layouts.get(self.space)
        if lo is None:
            data.underlay_fill = data.underlay_fill[:0]
            data.viewports = []
            return
        import numpy as np
        w, h = lo.size
        sh = max(w, h) * 0.008
        shadow = (0.0, 0.0, 0.0, 0.35)
        o = self.builder.origin
        data.underlay_fill = np.concatenate([
            rect_tris(sh, -sh, w + sh, h - sh, shadow, o),
            rect_tris(0, 0, w, h, (1.0, 1.0, 1.0, 1.0) if not self.dark else (0.97, 0.97, 0.97, 1.0), o),
        ])
        self._update_viewports()

    def _update_viewports(self) -> None:
        data = self.canvas.data
        vps = []
        if self.space != MODEL_SPACE:
            from ..core.layouts import resolve_viewport
            model_box = self.index.extents(MODEL_SPACE)
            for e in self.doc.entities.values():
                if isinstance(e, Viewport) and e.space == self.space and self.doc.is_visible(e):
                    x0, y0, x1, y1 = e.rect()
                    sx0, sy0 = self.view.to_screen((x0, y1))
                    sx1, sy1 = self.view.to_screen((x1, y0))
                    clip = (sx0, sy0, max(1.0, sx1 - sx0), max(1.0, sy1 - sy0))
                    (vcx, vcy), vs = resolve_viewport(self.doc, e, model_box)
                    vps.append(ViewportView(clip, vcx, vcy, self.view.scale * vs, self.view.width, self.view.height))
        data.viewports = vps

    def update_grid(self, invalidate: bool = True) -> None:
        data = self.canvas.data
        if self.space != MODEL_SPACE:
            self._update_viewports()
        if self.cfg.grid_on and self.builder.origin is not None and self.space == MODEL_SPACE:
            data.grid = grid_instances(self.view.visible_rect(), self.doc.header.grid_spacing, self.view.pixel,
                                       self.builder.origin, self.dark)
        else:
            data.grid = data.grid[:0]
        data.grid_version += 1
        if invalidate:
            self.canvas.invalidate()

    def selection_target(self) -> set[int]:
        return self.pending_sel if isinstance(self.runner.request, GetSelection) else self.runner.ctx.selection

    def update_highlight(self, invalidate: bool = True) -> None:
        import numpy as np
        sel = self.runner.ctx.selection | self.pending_sel
        ents = [self.doc.entities[h] for h in sel if h in self.doc.entities]
        segs, tris = self.builder.build_entities(ents, self.opts)
        seg_parts = [solid_color_instances(segs, self.highlight_rgba, 2.0)] if len(segs) else []
        tri_parts = [solid_color_tris(tris, self.highlight_rgba)] if len(tris) else []
        if self.hover is not None and self.hover not in sel and self.hover in self.doc.entities:
            hs, ht = self.builder.build_entities([self.doc.entities[self.hover]], self.opts)
            if len(hs):
                seg_parts.append(solid_color_instances(hs, self.hover_rgba, 1.0))
            if len(ht):
                tri_parts.append(solid_color_tris(ht, self.hover_rgba))
        data = self.canvas.data
        data.highlight = np.concatenate(seg_parts) if seg_parts else segs[:0]
        data.highlight_fill = np.concatenate(tri_parts) if tri_parts else tris[:0]
        if invalidate:
            self.canvas.update()

    def _update_preview(self) -> None:
        req = self.runner.request
        import numpy as np
        data = self.canvas.data
        if not (wants_point(req) or isinstance(req, GetEntity)) or self.cursor_screen is None:
            data.preview = data.preview[:0]
            data.preview_fill = data.preview_fill[:0]
            return
        pt = self.snap.point if self.snap else self.cursor_model
        ents = [e.with_props(space=self.space) if e.space != self.space else e for e in self.runner.preview(pt)]
        segs, fills = [], []
        if ents:
            s_, f_ = self.builder.build_entities(ents, self.opts)
            segs.append(s_)
            fills.append(f_)
        base = getattr(req, "base", None)
        rubber = getattr(req, "rubber", "line") if isinstance(req, GetPoint) else "line"
        if base is not None and rubber == "line" and dist(base, pt) > 0:
            s_, _ = self.builder.build_entities([Line(p1=base, p2=pt)], self.opts)
            segs.append(solid_color_instances(s_, (0.6, 0.65, 0.7, 0.9)))
        elif base is not None and rubber == "rect":
            pl = Polyline(vertices=((base[0], base[1], 0), (pt[0], base[1], 0), (pt[0], pt[1], 0),
                                    (base[0], pt[1], 0)), closed=True)
            s_, _ = self.builder.build_entities([pl], self.opts)
            segs.append(solid_color_instances(s_, (0.6, 0.65, 0.7, 0.9)))
        data.preview = np.concatenate(segs) if segs else data.preview[:0]
        data.preview_fill = np.concatenate(fills) if fills else data.preview_fill[:0]

    # ================================================================ view API (used by commands)
    def _push_history(self, force: bool = True) -> None:
        now = time.monotonic()
        if force or now - self._last_history_push > 1.0:
            self.view_history.append(self.view.copy())
            del self.view_history[:-50]
        self._last_history_push = now

    def _view_changed(self) -> None:
        self.update_grid(invalidate=False)
        self.canvas.invalidate()
        self._regen_timer.start()
        self.view_changed_signal.emit()

    def zoom_extents(self, push: bool = True) -> None:
        if push:
            self._push_history()
        ext = self.index.extents(self.space)
        lo = self.doc.layouts.get(self.space)
        if lo is not None:
            w, h = lo.size
            ext = (min(0, ext[0]) if ext else 0, min(0, ext[1]) if ext else 0,
                   max(w, ext[2]) if ext else w, max(h, ext[3]) if ext else h)
        if ext is None:
            units = self.doc.header.units
            size = 300.0 if units.mode.value == "mm" else 12 * 25.4 * 4
            ext = (0.0, 0.0, size, size * 0.6)
        self.view.fit(ext)
        self._view_changed()

    def zoom_window(self, p1: Vec, p2: Vec) -> None:
        if dist(p1, p2) <= 0:
            return
        self._push_history()
        self.view.fit((min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])), margin=0.0)
        self._view_changed()

    def zoom_previous(self) -> bool:
        if not self.view_history:
            return False
        v = self.view_history.pop()
        self.view.cx, self.view.cy, self.view.scale = v.cx, v.cy, v.scale
        self._view_changed()
        return True

    def zoom_factor(self, factor: float) -> None:
        self._push_history()
        self.view.zoom_at(self.view.width / 2, self.view.height / 2, factor)
        self._view_changed()

    def regen(self) -> None:
        self.builder.set_tolerance(self.view.pixel * 0.5)
        self.builder.invalidate_all()
        self.rebuild_scene()

    def _auto_regen(self) -> None:
        target = self.view.pixel * 0.5
        tol = self.builder.tol
        if tol > target * 4 or tol < target / 32:
            self.builder.set_tolerance(target)
            self.rebuild_scene()

    # ================================================================ helpers
    def pixel(self) -> float:
        return self.view.pixel

    def current_point(self) -> Vec:
        return self.snap.point if self.snap else self.cursor_model

    def current_direction(self) -> float | None:
        req = self.runner.request
        base = getattr(req, "base", None)
        if base is None:
            return None
        pt = self.current_point()
        if dist(base, pt) <= 1e-12:
            return None
        return angle_of(sub(pt, base))

    def _recompute_at_cursor(self) -> None:
        if self.cursor_screen is None:
            return
        self.cursor_model = self.view.to_model(*self.cursor_screen)
        req = self.runner.request
        if wants_point(req):
            self.snap = self.engine.snap(self.cursor_model, self.view.pixel, self.cfg, base=req.base,
                                         grid_spacing=self.doc.header.grid_spacing,
                                         snap_spacing=self.doc.header.snap_spacing)
            self._track_acquisition()
            self._set_hover(None)
        else:
            self.snap = None
            self._acquire_timer.stop()
            hit = self.index.pick(self.cursor_model, PICKBOX_PX * self.view.pixel)
            self._set_hover(hit.handle if hit else None)
        self._update_preview()
        self._emit_coords()

    def _set_hover(self, h: int | None) -> None:
        if h != self.hover:
            self.hover = h
            self.update_highlight(invalidate=False)

    def _track_acquisition(self) -> None:
        s = self.snap
        if self.cfg.otrack_on or Osnap.EXTENSION in self.cfg.modes:
            if s and s.osnap in TRACKABLE:
                if self._acquire_target is None or dist(self._acquire_target[0], s.point) > 1e-9:
                    self._acquire_target = (s.point, s.osnap)
                    self._acquire_timer.start()
                return
        self._acquire_target = None
        self._acquire_timer.stop()

    def _acquire(self) -> None:
        if self._acquire_target is None or self.snap is None:
            return
        pt, mode = self._acquire_target
        if dist(self.snap.point, pt) > 1e-9:
            return
        ext = self.engine.extension_dir_for(pt, self.view.pixel) if mode is Osnap.ENDPOINT else None
        self.engine.toggle_acquire(pt, ext, tol=self.view.pixel * 0.5)
        self.canvas.update()

    def _emit_coords(self) -> None:
        u = self.doc.header.units
        p = self.current_point()
        text = f"X {format_length(p[0], u)}   Y {format_length(p[1], u)}"
        base = getattr(self.runner.request, "base", None)
        if base is not None and dist(base, p) > 0:
            text += (f"     Length {format_length(dist(base, p), u)}   "
                     f"Angle {format_angle(math.degrees(angle_of(sub(p, base))), u)}")
        self.coords_changed.emit(text)

    # ================================================================ events
    def on_resize(self, w: int, h: int) -> None:
        cx, cy = self.view.cx, self.view.cy
        self.view.width, self.view.height = max(1, w), max(1, h)
        self.view.cx, self.view.cy = cx, cy
        self._view_changed()

    def on_leave(self) -> None:
        self.cursor_screen = None
        self.snap = None
        self._set_hover(None)
        self.canvas.data.preview = self.canvas.data.preview[:0]
        self.canvas.update()

    def on_mouse_move(self, ev) -> None:
        pos = ev.position()
        if self.pan_last is not None:
            d = pos - self.pan_last
            self.pan_last = pos
            self.view.pan_pixels(d.x(), d.y())
            self._view_changed()
            return
        self.cursor_screen = (pos.x(), pos.y())
        if self.window_start is not None:
            if (abs(pos.x() - self.window_start[0]) > 4 or abs(pos.y() - self.window_start[1]) > 4) \
                    and ev.buttons() & Qt.MouseButton.LeftButton:
                self.window_dragged = True
            self.cursor_model = self.view.to_model(pos.x(), pos.y())
            self._emit_coords()
            self.canvas.update()
            return
        self._recompute_at_cursor()
        if self.runner.request is None and self.runner.ctx.selection:
            found = self.grip_targets_at(pos)
            self.hot_grip = found[0] if found else None
        elif not self.runner.is_active:
            self.hot_grip = None
        self.canvas.update()

    def on_mouse_press(self, ev) -> None:
        self.canvas.setFocus()
        btn = ev.button()
        pos = ev.position()
        req = self.runner.request
        if btn == Qt.MouseButton.MiddleButton or (
                btn == Qt.MouseButton.LeftButton and isinstance(req, GetPoint) and req.mode == "pan"):
            self.pan_last = pos
            self._push_history(force=False)
            return
        if btn != Qt.MouseButton.LeftButton:
            return
        self.cursor_screen = (pos.x(), pos.y())
        if wants_point(req):
            self._recompute_at_cursor()
            self.runner.submit_point(self.current_point())
            self._after_input()
            return
        self.runner.ctx.shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if isinstance(req, GetEntity):
            self.runner.submit_point(self.view.to_model(pos.x(), pos.y()))
            self._after_input()
            return
        # selecting (idle or a command asking for objects)
        if self.window_start is not None:
            self._finish_window(pos, ev.modifiers())
            return
        if req is None and self.runner.ctx.selection:
            for rect, target in self.value_boxes:
                if rect.contains(pos):
                    self.begin_value_edit(target, rect)
                    return
            if self.start_grip_edit(pos):
                return
        self.cursor_model = self.view.to_model(pos.x(), pos.y())
        hit = self.index.pick(self.cursor_model, PICKBOX_PX * self.view.pixel)
        if hit is not None:
            target = self.selection_target()
            members = self.with_groups({hit.handle})
            if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                target.difference_update(members)
            else:
                target.update(members)
            self._selection_updated()
            return
        self.window_start = (pos.x(), pos.y())
        self.window_dragged = False

    def on_mouse_release(self, ev) -> None:
        if ev.button() == Qt.MouseButton.MiddleButton or self.pan_last is not None:
            self.pan_last = None
            return
        if ev.button() == Qt.MouseButton.LeftButton and self.window_start is not None and self.window_dragged:
            self._finish_window(ev.position(), ev.modifiers())

    def on_double_click(self, ev) -> None:
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.zoom_extents()
        elif ev.button() == Qt.MouseButton.LeftButton and not self.runner.is_active:
            pos = ev.position()
            self.window_start = None
            hit = self.index.pick(self.view.to_model(pos.x(), pos.y()), PICKBOX_PX * self.view.pixel)
            if hit is not None:
                self.edit_requested.emit(hit)

    def on_wheel(self, ev) -> None:
        steps = ev.angleDelta().y() / 120.0
        if steps == 0:
            return
        pos = ev.position()
        self._push_history(force=False)
        self.view.zoom_at(pos.x(), pos.y(), 1.25 ** steps)
        self._view_changed()
        self.cursor_screen = (pos.x(), pos.y())
        self._recompute_at_cursor()

    def on_context_menu(self, ev) -> None:
        self.context_menu_requested.emit(ev.globalPos())

    def on_key_press(self, ev) -> bool:
        key = ev.key()
        if key == Qt.Key.Key_Escape:
            self.escape()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.enter()
            return True
        if key == Qt.Key.Key_Delete and not self.runner.is_active and self.runner.ctx.selection:
            self.runner.run("ERASE")
            return True
        text = ev.text()
        if text and text.isprintable() and not (ev.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                                                   | Qt.KeyboardModifier.AltModifier)):
            self.forward_text.emit(text)
            return True
        return False

    # ================================================================ actions
    def escape(self) -> None:
        if self.window_start is not None:
            self.window_start = None
            self.canvas.update()
        elif self.runner.is_active:
            self.runner.cancel()
        elif self.runner.ctx.selection:
            self.runner.ctx.selection.clear()
            self._selection_updated()

    def enter(self) -> None:
        if isinstance(self.runner.request, GetSelection):
            sel = set(self.pending_sel)
            self.pending_sel.clear()
            self.runner.submit_selection(sel)
        else:
            self.runner.submit_text("")
        self._after_input()

    def with_groups(self, handles: set[int]) -> set[int]:
        """Clicking one member of a group selects the whole group (AutoCAD PICKSTYLE 1)."""
        out = set(handles)
        for g in self.doc.groups.values():
            if g.handles & handles:
                out |= {h for h in g.handles if h in self.doc.entities and self.doc.entities[h].space == self.space}
        return out

    def select_all(self) -> None:
        target = self.selection_target()
        target.update(h for h, e in self.doc.entities.items() if self.doc.is_visible(e))
        self._selection_updated()

    def clear_selection(self) -> None:
        self.runner.ctx.selection.clear()
        self._selection_updated()

    def _after_input(self) -> None:
        self._recompute_at_cursor()
        self.update_highlight()

    def _selection_updated(self) -> None:
        self.cancel_value_edit()
        self.update_highlight()
        self.selection_changed.emit()

    def _finish_window(self, pos: QPointF, modifiers) -> None:
        sx, sy = self.window_start
        self.window_start = None
        p1 = self.view.to_model(sx, sy)
        p2 = self.view.to_model(pos.x(), pos.y())
        rect = (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
        crossing = pos.x() < sx
        found = self.index.select_window(rect, crossing)
        self.runner.ctx.memory["last_window"] = rect
        target = self.selection_target()
        found = self.with_groups(set(found))
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            target.difference_update(found)
        else:
            target.update(found)
        self._selection_updated()

    # ================================================================ overlay
    def paint_overlay(self, p: QPainter) -> None:
        v = self.view
        self._paint_points(p)
        self._paint_grips(p)
        if self.window_start is not None and self.cursor_screen is not None:
            sx, sy = self.window_start
            cx, cy = self.cursor_screen
            crossing = cx < sx
            col = QColor(60, 200, 90) if crossing else QColor(60, 140, 255)
            fill = QColor(col)
            fill.setAlpha(40)
            pen = QPen(col, 1, Qt.PenStyle.DashLine if crossing else Qt.PenStyle.SolidLine)
            p.setPen(pen)
            p.setBrush(fill)
            p.drawRect(QRectF(QPointF(sx, sy), QPointF(cx, cy)).normalized())
        s = self.snap
        if s is not None:
            pen = QPen(self.track, 1, Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for a, b in s.track_lines:
                sa, sb = v.to_screen(a), v.to_screen(b)
                dx, dy = sb[0] - sa[0], sb[1] - sa[1]
                ln = math.hypot(dx, dy) or 1.0
                far = (sb[0] + dx / ln * 3000, sb[1] + dy / ln * 3000)
                p.drawLine(QPointF(*sa), QPointF(*far))
        for acq in self.engine.acquired:
            x, y = v.to_screen(acq.point)
            p.setPen(QPen(self.track, 1.5))
            p.drawLine(QPointF(x - 5, y), QPointF(x + 5, y))
            p.drawLine(QPointF(x, y - 5), QPointF(x, y + 5))
        if s is not None and s.osnap is not None and s.marker_point is not None:
            self._paint_marker(p, s.osnap, v.to_screen(s.marker_point))
        elif s is not None and s.kind == "track" and s.marker_point is not None:
            x, y = v.to_screen(s.marker_point)
            p.setPen(QPen(self.track, 1.5))
            p.drawLine(QPointF(x - 6, y - 6), QPointF(x + 6, y + 6))
            p.drawLine(QPointF(x - 6, y + 6), QPointF(x + 6, y - 6))
        if self.show_constraints and self.doc.constraints:
            self._paint_constraints(p)
        self._paint_cursor(p)
        self._paint_ucs(p)

    GLYPHS = {"parallel": "∥", "perpendicular": "⊥", "horizontal": "H", "vertical": "V", "collinear": "C/",
              "concentric": "◎", "equal": "=", "tangent": "T", "fix": "F", "symmetric": "[]", "coincident": "•"}

    def _anchor(self, ref):
        from ..core.constraints.model import point_refs
        h, part = ref
        e = self.doc.entities.get(h)
        if e is None or e.space != self.space:
            return None
        if part in ("line",):
            return ((e.p1[0] + e.p2[0]) / 2, (e.p1[1] + e.p2[1]) / 2)
        if part.startswith("seg"):
            i = int(part[3:])
            vs = e.vertices
            a, b = vs[i], vs[(i + 1) % len(vs)]
            return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if part == "circle":
            return (e.center[0] + e.radius * 0.7071, e.center[1] + e.radius * 0.7071)
        if part == "all":
            g = self.doc.geometry(e).bbox
            return ((g[0] + g[2]) / 2, (g[1] + g[3]) / 2) if g else None
        for name, pt in point_refs(e):
            if name == part:
                return pt
        return None

    def _paint_constraints(self, p: QPainter) -> None:
        from ..core.constraints.model import resolve_values
        try:
            values = resolve_values(self.doc.constraints)
        except Exception:                      # noqa: BLE001
            values = {}
        f = QFont(p.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
        p.setFont(f)
        fm = QFontMetrics(f)
        slots: dict[tuple[int, int], int] = {}
        bg = QColor(60, 70, 85, 220) if self.dark else QColor(235, 240, 250, 235)
        fg = QColor(150, 200, 255) if self.dark else QColor(20, 80, 170)
        u = self.doc.header.units
        for i, c in enumerate(self.doc.constraints.values()):
            if i > 500:
                break
            if c.kind == "coincident":
                a = self._anchor(c.refs[0])
                if a is None:
                    continue
                x, y = self.view.to_screen(a)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fg)
                p.drawRect(QRectF(x - 3, y - 3, 6, 6))
                continue
            if c.is_dimensional:
                pts = [self._anchor(r) for r in c.refs]
                pts = [q for q in pts if q is not None]
                if not pts:
                    continue
                a = (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))
                v = values.get(c.name)
                vtxt = "" if v is None else (f"{v:g}°" if c.kind == "angle" else format_length(v, u))
                text = f"{c.name}={vtxt}"
                dy = -18
            else:
                a = self._anchor(c.refs[0])
                if a is None:
                    continue
                text = self.GLYPHS.get(c.kind, c.kind[:2])
                dy = 14
            x, y = self.view.to_screen(a)
            key = (int(x) // 6, int(y) // 6)
            k = slots.get(key, 0)
            slots[key] = k + 1
            w = fm.horizontalAdvance(text) + 8
            r = QRectF(x + 8 + k * (w + 2), y + dy - fm.height() / 2, w, fm.height() + 2)
            p.setPen(QPen(fg, 1))
            p.setBrush(bg)
            p.drawRoundedRect(r, 3, 3)
            p.setPen(fg)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_points(self, p: QPainter) -> None:
        pts = self.builder.points
        if not pts:
            return
        v = self.view
        size = self.doc.header.point_size_px
        p.setPen(QPen(self.fg, 1.2))
        x0, y0, x1, y1 = v.visible_rect()
        drawn = 0
        for pt in pts:
            if x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1:
                x, y = v.to_screen(pt)
                p.drawLine(QPointF(x - size / 2, y - size / 2), QPointF(x + size / 2, y + size / 2))
                p.drawLine(QPointF(x - size / 2, y + size / 2), QPointF(x + size / 2, y - size / 2))
                drawn += 1
                if drawn > 20000:
                    break

    def _paint_grips(self, p: QPainter) -> None:
        sel = self.runner.ctx.selection
        if not sel or self.runner.is_active:
            return
        p.setPen(QPen(QColor(255, 255, 255) if self.dark else QColor(0, 0, 0), 1))
        for i, h in enumerate(sel):
            if i >= MAX_GRIP_ENTITIES:
                break
            e = self.doc.entities.get(h)
            if e is None:
                continue
            for _, g in named_points(e):
                x, y = self.view.to_screen(g)
                hot = self.hot_grip is not None and dist(g, self.hot_grip) < 1e-9
                p.setBrush(QColor(255, 60, 60) if hot else QColor(40, 120, 255))
                p.drawRect(QRectF(x - 3.5, y - 3.5, 7, 7))
        if len(sel) == 1:
            e = self.doc.entities.get(next(iter(sel)))
            if e is not None and e.space == self.space:
                self._paint_values(p, e)

    # ------------------------------------------------------------ grips (click a grip, then the new point)
    def grip_targets_at(self, pos) -> tuple[Vec, list] | None:
        pt = self.view.to_model(pos.x(), pos.y())
        targets = grips_at(self.doc, list(self.runner.ctx.selection)[:MAX_GRIP_ENTITIES], pt, GRIP_PX * self.view.pixel)
        if not targets:
            return None
        from ..core.points import point_of
        h, part = targets[0]
        return point_of(self.doc.entities[h], part), targets

    def start_grip_edit(self, pos) -> bool:
        found = self.grip_targets_at(pos)
        if found is None:
            return False
        base, targets = found
        self.runner.ctx.memory["grip"] = (base, targets)
        self.hot_grip = base
        self.runner.ctx.last_point = base
        self.runner.run("GRIPEDIT")
        self._after_input()
        return True

    # ------------------------------------------------------------ Revit-style values
    def _value_text_color(self) -> QColor:
        return QColor(120, 190, 255) if self.dark else QColor(0, 90, 200)

    def value_layout(self) -> list[tuple[QRectF, EditableValue, str, list, bool]]:
        """Clickable numbers for the single selected object: (screen rect, target, text, lines, dashed).
        Computed from the view, independent of painting, so clicks work whatever the renderer."""
        sel = self.runner.ctx.selection
        if len(sel) != 1 or self.runner.is_active:
            return []
        e = self.doc.entities.get(next(iter(sel)))
        if e is None or e.space != self.space:
            return []
        v = self.view
        try:
            targets = editable_values(self.doc, e)
        except Exception:     # never let an overlay break the canvas
            return []
        if len(targets) > 40:
            targets = [t for t in targets if t.kind == "dim"] + [t for t in targets if t.kind != "dim"][:40]
        fm = QFontMetrics(self.canvas.font())
        out = []
        for t in targets:
            text = format_value(self.doc, t)
            lines: list = []
            dashed = False
            if t.kind == "dim":
                cx, cy = v.to_screen(t.label_at)
            elif t.kind == "radius":
                a, b = v.to_screen(t.a), v.to_screen(t.b)
                lines = [(a, b)]
                dashed = True
                cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                text = "R " + text
            else:
                a, b = v.to_screen(t.a), v.to_screen(t.b)
                dx, dy = b[0] - a[0], b[1] - a[1]
                L = math.hypot(dx, dy)
                if L < fm.horizontalAdvance(text) + 16:
                    continue                      # too small on screen to label
                nx, ny = -dy / L * VALUE_OFFSET_PX, dx / L * VALUE_OFFSET_PX
                a2, b2 = (a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny)
                lines = [(a, a2), (b, b2), (a2, b2)]
                lines += [((q[0] - 4, q[1] + 4), (q[0] + 4, q[1] - 4)) for q in (a2, b2)]   # slash ticks
                cx, cy = (a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2
            w, h = fm.horizontalAdvance(text) + 10, fm.height() + 4
            out.append((QRectF(cx - w / 2, cy - h / 2, w, h), t, text, lines, dashed))
        return out

    def _paint_values(self, p: QPainter, e) -> None:
        p.setFont(self.canvas.font())
        col = self._value_text_color()
        bg = QColor(30, 34, 40, 225) if self.dark else QColor(255, 255, 255, 230)
        for rect, t, text, lines, dashed in self.value_layout():
            p.setPen(QPen(col, 1, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
            for a, b in lines:
                p.drawLine(QPointF(*a), QPointF(*b))
            p.setPen(QPen(col, 1))
            p.setBrush(bg)
            p.drawRoundedRect(rect, 3, 3)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            p.setBrush(Qt.BrushStyle.NoBrush)

    @property
    def value_boxes(self) -> list[tuple[QRectF, EditableValue]]:
        return [(r, t) for r, t, *_ in self.value_layout()]

    def begin_value_edit(self, target: EditableValue, rect: QRectF) -> None:
        self.cancel_value_edit()
        ed = QLineEdit(self.canvas)
        ed.setObjectName("valueEditor")
        ed.setText(format_value(self.doc, target))
        ed.selectAll()
        ed.setToolTip("Type the value you want and press Enter (Esc cancels). Any unit format works, "
                      "e.g. 3 4-1/2 for 3'-4 1/2\", 1500mm, 2.5\".")
        w = max(rect.width() + 40, 110)
        ed.setGeometry(int(rect.center().x() - w / 2), int(rect.center().y() - 13), int(w), 26)
        ed.returnPressed.connect(self._commit_value_edit)
        ed.installEventFilter(self)
        self.value_editor = ed
        self._editing_value = target
        ed.show()
        ed.setFocus()

    def eventFilter(self, obj, ev) -> bool:   # Esc / focus loss on the inline value editor
        from PySide6.QtCore import QEvent
        if obj is self.value_editor:
            if ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
                self.cancel_value_edit()
                return True
            if ev.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(0, self.cancel_value_edit)
        return False

    def cancel_value_edit(self) -> None:
        ed, self.value_editor, self._editing_value = self.value_editor, None, None
        if ed is not None:
            ed.removeEventFilter(self)
            ed.hide()
            ed.deleteLater()
            self.canvas.setFocus()
            self.canvas.update()

    def _commit_value_edit(self) -> None:
        ed, target = self.value_editor, self._editing_value
        if ed is None or target is None:
            return
        msg = self.set_value(target, ed.text())
        if msg:
            self.runner.ctx.echo(msg)
            ed.selectAll()
            return
        self.cancel_value_edit()

    def set_value(self, target: EditableValue, text: str) -> str | None:
        """Apply a typed value. Returns an error message, or None when done."""
        sel = self.runner.ctx.selection
        selected = next(iter(sel)) if len(sel) == 1 else None
        try:
            value = parse_value(self.doc, target, text)
            with self.doc.transaction("Change dimension value"):
                apply_value(self.doc, target, value, selected=selected)
        except EditError as exc:
            return str(exc)
        except Exception as exc:          # e.g. a constraint conflict refused the change
            return f"Couldn't apply that value: {exc}"
        self.update_highlight()
        return None

    def _paint_marker(self, p: QPainter, mode: Osnap, at: tuple[float, float]) -> None:
        x, y = at
        r = 7.0
        p.setPen(QPen(self.marker, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if mode is Osnap.ENDPOINT:
            p.drawRect(QRectF(x - r, y - r, 2 * r, 2 * r))
        elif mode is Osnap.MIDPOINT:
            p.drawPolygon(QPolygonF([QPointF(x, y - r), QPointF(x + r, y + r * 0.8), QPointF(x - r, y + r * 0.8)]))
        elif mode is Osnap.CENTER:
            p.drawEllipse(QPointF(x, y), r, r)
        elif mode is Osnap.INTERSECTION:
            p.drawLine(QPointF(x - r, y - r), QPointF(x + r, y + r))
            p.drawLine(QPointF(x - r, y + r), QPointF(x + r, y - r))
        elif mode is Osnap.PERPENDICULAR:
            p.drawLine(QPointF(x - r, y - r), QPointF(x - r, y + r))
            p.drawLine(QPointF(x - r, y + r), QPointF(x + r, y + r))
            p.drawPolyline(QPolygonF([QPointF(x - r, y), QPointF(x, y), QPointF(x, y + r)]))
        elif mode is Osnap.TANGENT:
            p.drawEllipse(QPointF(x, y), r * 0.8, r * 0.8)
            p.drawLine(QPointF(x - r, y - r * 0.8), QPointF(x + r, y - r * 0.8))
        elif mode is Osnap.NEAREST:
            p.drawPolygon(QPolygonF([QPointF(x - r, y - r), QPointF(x + r, y - r),
                                     QPointF(x - r, y + r), QPointF(x + r, y + r)]))
        elif mode is Osnap.QUADRANT:
            p.drawPolygon(QPolygonF([QPointF(x, y - r), QPointF(x + r, y), QPointF(x, y + r), QPointF(x - r, y)]))
        elif mode is Osnap.NODE:
            p.drawEllipse(QPointF(x, y), r, r)
            p.drawLine(QPointF(x - r * 0.7, y - r * 0.7), QPointF(x + r * 0.7, y + r * 0.7))
            p.drawLine(QPointF(x - r * 0.7, y + r * 0.7), QPointF(x + r * 0.7, y - r * 0.7))
        elif mode is Osnap.EXTENSION:
            p.drawLine(QPointF(x - 4, y), QPointF(x + 4, y))
            p.drawLine(QPointF(x, y - 4), QPointF(x, y + 4))

    def _paint_tip(self, p: QPainter, x: float, y: float, lines: list[str]) -> None:
        lines = [t for t in lines if t]
        if not lines:
            return
        f = QFont(p.font())
        p.setFont(f)
        fm = QFontMetrics(f)
        w = max(fm.horizontalAdvance(t) for t in lines) + 12
        h = fm.height() * len(lines) + 8
        # keep the tip on screen without covering the cursor / snap marker
        if x + w > self.view.width - 4:
            x = x - w - 36
        if y + h > self.view.height - 4:
            y = y - h - 36
        bg = QColor(50, 56, 66, 235) if self.dark else QColor(255, 255, 240, 240)
        p.setPen(QPen(QColor(120, 128, 140), 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(x, y, w, h), 4, 4)
        p.setPen(QColor(235, 238, 242) if self.dark else QColor(20, 20, 20))
        for i, t in enumerate(lines):
            p.drawText(QPointF(x + 6, y + 4 + fm.ascent() + i * fm.height()), t)

    def _paint_cursor(self, p: QPainter) -> None:
        if self.cursor_screen is None or self.pan_last is not None:
            return
        x, y = self.cursor_screen
        req = self.runner.request
        picking_point = wants_point(req)
        p.setPen(QPen(self.fg, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        arm = 40
        p.drawLine(QPointF(x - arm, y), QPointF(x + arm, y))
        p.drawLine(QPointF(x, y - arm), QPointF(x, y + arm))
        if not picking_point:
            p.drawRect(QRectF(x - PICKBOX_PX, y - PICKBOX_PX, 2 * PICKBOX_PX, 2 * PICKBOX_PX))
        lines = []
        if self.snap is not None and self.snap.tooltip:
            lines.append(self.snap.tooltip)
        if self.runner.request is not None:
            lines.append(self.runner.request.full_prompt())
        self._paint_tip(p, x + 18, y + 18, lines)

    def _paint_ucs(self, p: QPainter) -> None:
        x0, y0 = 18, self.view.height - 18
        n = 36
        p.setPen(QPen(QColor(220, 80, 80), 2))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + n, y0))
        p.drawPolygon(QPolygonF([QPointF(x0 + n + 6, y0), QPointF(x0 + n, y0 - 3), QPointF(x0 + n, y0 + 3)]))
        p.setPen(QPen(QColor(80, 190, 90), 2))
        p.drawLine(QPointF(x0, y0), QPointF(x0, y0 - n))
        p.drawPolygon(QPolygonF([QPointF(x0, y0 - n - 6), QPointF(x0 - 3, y0 - n), QPointF(x0 + 3, y0 - n)]))
        p.setPen(self.fg)
        p.drawText(QPointF(x0 + n + 8, y0 + 4), "X")
        p.drawText(QPointF(x0 - 4, y0 - n - 9), "Y")


_ = (QBrush, QPainterPath)
