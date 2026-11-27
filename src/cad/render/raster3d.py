"""Turning a 3D scene into a picture.

GLRenderer draws with the graphics card (moderngl, offscreen, real depth buffer).
PainterRenderer is the fallback with no OpenGL: QPainter and depth sorting.
Both return a QImage of the camera's size.

Solids with alpha < 1 (hole shapes, live previews, the X-ray style) are drawn see-through after the
opaque ones. `extra` items (previews) are drawn like solids. `overlay` lines are drawn on top:
[(points (k,3), QColor, width, dashed)].
"""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPolygonF

from .camera3d import Camera3D
from .scene3d import Scene3D, SolidItem, edge_segments

log = logging.getLogger(__name__)

LIGHT = np.array([0.35, 0.45, 0.82])
LIGHT = LIGHT / np.linalg.norm(LIGHT)
SELECT_RGB = np.array([0.31, 0.63, 1.0])
HOVER_RGB = np.array([1.0, 0.8, 0.3])


def _style_flags(style: str) -> tuple[bool, bool, bool, float]:
    """(fill faces, shade them, draw edges, face alpha)."""
    return {
        "Wireframe": (False, False, True, 1.0),
        "Hidden": (True, False, True, 1.0),
        "Shaded": (True, True, False, 1.0),
        "Shaded with edges": (True, True, True, 1.0),
        "X-ray": (True, True, True, 0.35),
    }.get(style, (True, True, True, 1.0))


def _light_in_view(cam: Camera3D) -> np.ndarray:
    """A headlight a little above-left of the eye, in model coordinates."""
    v = LIGHT[0] * -cam.right + LIGHT[1] * cam.up + LIGHT[2] * cam.eye_dir
    return v / np.linalg.norm(v)


def _face_rgb(rgb):
    r, g, b = rgb
    if min(r, g, b) > 0.95 or max(r, g, b) < 0.05:        # color 7 (white/black): a neutral grey part
        return (0.72, 0.74, 0.78)
    return (r, g, b)


def _item_rgb(s: SolidItem, shade: bool, dark: bool, highlight, hover) -> np.ndarray:
    base = np.array(_face_rgb(s.rgb)) if (shade or s.alpha < 1) else (
        np.array((0.15, 0.15, 0.17)) if dark else np.ones(3))
    if s.handle in highlight:
        base = base * 0.6 + SELECT_RGB * 0.4
    elif s.handle == hover and s.handle >= 0:
        base = base * 0.8 + HOVER_RGB * 0.2
    return base


def _edge_color(s: SolidItem, style: str, highlight) -> tuple:
    if s.handle in highlight:
        return tuple(SELECT_RGB)
    if style == "Wireframe" or s.alpha < 1:
        return tuple(s.rgb) if s.handle >= 0 else (1.0, 0.6, 0.1)
    return (0.08, 0.08, 0.09)


def _all_items(scene: Scene3D, extra) -> list[SolidItem]:
    return list(scene.solids) + [x for x in (extra or ()) if x is not None]


# ====================================================================== software
def _occluded(points: np.ndarray, cam: Camera3D, tris: np.ndarray, eps: float) -> np.ndarray:
    """For each point, is a triangle between it and the eye? tris is (m,3,3)."""
    out = np.zeros(len(points), bool)
    if not len(tris) or not len(points):
        return out
    v0, e1, e2 = tris[:, 0], tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    chunk = max(1, 2_000_000 // len(tris))
    for a in range(0, len(points), chunk):
        P = points[a:a + chunk]
        if cam.perspective:
            D = cam.eye - P
            D /= np.linalg.norm(D, axis=1)[:, None]
        else:
            D = np.broadcast_to(cam.eye_dir, P.shape)
        pv = np.cross(D[:, None, :], e2[None, :, :])
        det = np.einsum("mj,nmj->nm", e1, pv)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        tv = P[:, None, :] - v0[None, :, :]
        u = np.einsum("nmj,nmj->nm", tv, pv) * inv
        qv = np.cross(tv, e1[None, :, :])
        v = np.einsum("nmj,nj->nm", qv, D) * inv
        t = np.einsum("mj,nmj->nm", e2, qv) * inv
        hit = ok & (u >= 1e-6) & (v >= 1e-6) & (u + v <= 1 - 1e-6) & (t > eps)
        out[a:a + chunk] = hit.any(axis=1)
    return out


def _split_segments(segs: np.ndarray, cam: Camera3D, px: float = 10.0) -> np.ndarray:
    """Cut long segments into pieces about `px` pixels long (max 24) so hiding is per piece."""
    if not len(segs):
        return segs
    scr, _ = cam.project(segs.reshape(-1, 3))
    L = np.linalg.norm(scr[1::2] - scr[0::2], axis=1)
    n = np.clip(np.ceil(L / px), 1, 24).astype(int)
    if (n == 1).all():
        return segs
    out = []
    for seg, k in zip(segs, n):
        if k == 1:
            out.append(seg[None])
            continue
        t = np.linspace(0, 1, k + 1)[:, None]
        pts = seg[0] + (seg[1] - seg[0]) * t
        out.append(np.stack([pts[:-1], pts[1:]], axis=1))
    return np.concatenate(out)


def _qc(rgb, a: float = 1.0) -> QColor:
    c = QColor.fromRgbF(float(min(max(rgb[0], 0), 1)), float(min(max(rgb[1], 0), 1)),
                        float(min(max(rgb[2], 0), 1)))
    c.setAlphaF(float(a))
    return c


class PainterRenderer:
    name = "software"

    def render(self, scene: Scene3D, cam: Camera3D, style: str, background: QColor,
               highlight=frozenset(), hover: int | None = None, dark: bool = True,
               overlay: list | None = None, extra: list | None = None) -> QImage:
        img = QImage(max(cam.width, 1), max(cam.height, 1), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(background)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fill, shade, edges, style_alpha = _style_flags(style)
        light = _light_in_view(cam)
        items = []            # (depth, screen triangle, rgb, alpha)
        edge_jobs = []        # (segments, QColor)
        occ = []
        for s in _all_items(scene, extra):
            a = min(style_alpha, s.alpha)
            if (fill or s.alpha < 1) and len(s.triangles):
                tri_pts = s.vertices[s.triangles]
                n = np.cross(tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 0])
                ln = np.linalg.norm(n, axis=1)
                ok = ln > 1e-12
                n[ok] /= ln[ok, None]
                facing = (n @ -cam.forward) > 0 if not cam.perspective else \
                    (np.einsum("ij,ij->i", n, cam.eye - tri_pts[:, 0]) > 0)
                keep = ok & (facing | (a < 1))
                scr, depth = cam.project(tri_pts[keep].reshape(-1, 3))
                scr = scr.reshape(-1, 3, 2)
                depth = depth.reshape(-1, 3).mean(axis=1)
                base = _item_rgb(s, shade, dark, highlight, hover)
                k = 0.30 + 0.70 * np.abs(n[keep] @ light) if (shade or a < 1) else np.ones(int(keep.sum()))
                for i in range(len(scr)):
                    items.append((depth[i], scr[i], base * k[i], a))
                if a >= 1:
                    occ.append(tri_pts)
            if edges or s.alpha < 1:
                segs = edge_segments(s.edges)
                if len(segs):
                    edge_jobs.append((segs, _qc(_edge_color(s, style, highlight))))
        for w in scene.wires:
            segs = edge_segments(w.lines)
            if len(segs):
                edge_jobs.append((segs, _qc(SELECT_RGB if w.handle in highlight else w.rgb)))
        items.sort(key=lambda it: -it[0])          # far first
        for _d, pts, col, a in items:
            qc = _qc(col, a)
            p.setBrush(QBrush(qc))
            p.setPen(QPen(qc, 0.6) if a >= 1 else Qt.PenStyle.NoPen)     # hide seams
            p.drawPolygon(QPolygonF([QPointF(*pts[0]), QPointF(*pts[1]), QPointF(*pts[2])]))
        # edges on top, minus the pieces opaque faces cover (exact ray test)
        occluders = np.concatenate(occ) if (occ and style_alpha >= 1) else np.zeros((0, 3, 3))
        bb = scene.bbox()
        size = max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2], 1e-6) if bb is not None else 1.0
        for segs, col in edge_jobs:
            if len(occluders):
                pieces = _split_segments(segs, cam)
                pieces = pieces[~_occluded(pieces.mean(axis=1), cam, occluders, size * 1e-4)]
            else:
                pieces = segs
            scr, _ = cam.project(pieces.reshape(-1, 3))
            p.setPen(QPen(col, 1.4))
            for a, b in scr.reshape(-1, 2, 2):
                p.drawLine(QPointF(*a), QPointF(*b))
        draw_overlay(p, cam, overlay)
        p.end()
        return img


def draw_overlay(p: QPainter, cam: Camera3D, lines) -> None:
    """Lines drawn on top (rubber bands, drag arrows, hints): [(pts (k,3), QColor, width, dashed)]."""
    for item in lines or ():
        pts, col = item[0], item[1]
        width = item[2] if len(item) > 2 else 1.2
        dashed = item[3] if len(item) > 3 else False
        pts = np.asarray(pts, float)
        if len(pts) < 2:
            continue
        scr, _ = cam.project(pts)
        p.setPen(QPen(col, width, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
        p.drawPolyline(QPolygonF([QPointF(float(x), float(y)) for x, y in scr]))


# ====================================================================== OpenGL
_VS = """
#version 330
uniform mat4 u_mvp;
in vec3 in_pos;
in vec3 in_nrm;
in vec4 in_col;
out vec3 v_nrm;
out vec4 v_col;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_nrm = in_nrm;
    v_col = in_col;
}
"""
_FS = """
#version 330
uniform vec3 u_light;
uniform int u_shade;
in vec3 v_nrm;
in vec4 v_col;
out vec4 f_col;
void main() {
    if (u_shade == 1) {
        float k = 0.30 + 0.70 * abs(dot(normalize(v_nrm), u_light));
        f_col = vec4(v_col.rgb * k, v_col.a);
    } else {
        f_col = v_col;
    }
}
"""


def _mvp(cam: Camera3D, near: float, far: float) -> np.ndarray:
    r, u, f = cam.right, cam.up, cam.forward
    eye = cam.eye if cam.perspective else cam.target - f * (far * 0.5)
    view = np.eye(4)
    view[0, :3], view[1, :3], view[2, :3] = r, u, -f
    view[:3, 3] = -view[:3, :3] @ eye
    w2, h2 = cam.width / 2 / cam.scale, cam.height / 2 / cam.scale
    proj = np.zeros((4, 4))
    if cam.perspective:
        d = cam.distance
        n = max(near, d * 1e-3)
        proj[0, 0], proj[1, 1] = d / w2, d / h2
        proj[2, 2], proj[2, 3] = -(far + n) / (far - n), -2 * far * n / (far - n)
        proj[3, 2] = -1
    else:
        proj[0, 0], proj[1, 1] = 1 / w2, 1 / h2
        proj[2, 2], proj[2, 3] = -2 / (far - near), -(far + near) / (far - near)
        proj[3, 3] = 1
    return proj @ view


class GLRenderer:
    name = "opengl"

    def __init__(self) -> None:
        import sys

        import moderngl
        # On Linux use EGL: a GLX standalone context shares the X connection with Qt and can kill the
        # program with an X error when windows close. Windows/macOS use their native backend.
        backends = ("egl", None) if sys.platform.startswith("linux") else (None,)
        last = None
        for be in backends:
            try:
                self.ctx = (moderngl.create_standalone_context(require=330, backend=be) if be
                            else moderngl.create_standalone_context(require=330))
                break
            except Exception as exc:
                last = exc
        else:
            raise last
        self.prog = self.ctx.program(vertex_shader=_VS, fragment_shader=_FS)
        self._fbo = None
        self._size = (0, 0)

    def _target(self, w, h):
        if self._size != (w, h):
            if self._fbo is not None:
                self._fbo.release()
            self._fbo = self.ctx.simple_framebuffer((w, h), samples=0)
            self._size = (w, h)
        return self._fbo

    def render(self, scene: Scene3D, cam: Camera3D, style: str, background: QColor,
               highlight=frozenset(), hover: int | None = None, dark: bool = True,
               overlay: list | None = None, extra: list | None = None) -> QImage:
        import moderngl
        w, h = max(cam.width, 1), max(cam.height, 1)
        fbo = self._target(w, h)
        fbo.use()
        ctx = self.ctx
        ctx.viewport = (0, 0, w, h)
        fbo.clear(background.redF(), background.greenF(), background.blueF(), 1.0, depth=1.0)
        fill, shade, edges, style_alpha = _style_flags(style)
        items = _all_items(scene, extra)
        pts = [s.vertices for s in items if len(s.vertices)] + [ln for wi in scene.wires for ln in wi.lines]
        if pts:
            allp = np.vstack(pts)
            dz = (allp - cam.target) @ cam.forward
            span = float(np.abs(dz).max()) * 2 + float(np.ptp(allp, axis=0).max()) + 10.0
        else:
            span = 1000.0
        if cam.perspective:
            near, far = cam.distance * 0.01, cam.distance + span * 2
        else:
            near, far = 0.0, span * 4
        self.prog["u_mvp"].write(_mvp(cam, near, far).T.astype("f4").tobytes())
        self.prog["u_light"].value = tuple(float(v) for v in _light_in_view(cam))
        ctx.enable(moderngl.DEPTH_TEST)

        def tri_data(sel):
            out = []
            for s in sel:
                if not len(s.triangles):
                    continue
                a = min(style_alpha, s.alpha)
                base = _item_rgb(s, shade, dark, highlight, hover)
                idx = s.triangles.reshape(-1)
                v = s.vertices[idx]
                n = s.normals[idx] if len(s.normals) == len(s.vertices) else np.zeros_like(v)
                out.append(np.hstack([v, n, np.tile(np.append(base, a), (len(v), 1))]))
            return np.vstack(out) if out else None

        opaque = [s for s in items if s.alpha >= 1] if (fill and style_alpha >= 1) else []
        clear = [s for s in items if s.alpha < 1 or (fill and style_alpha < 1)]
        ctx.disable(moderngl.BLEND)
        data = tri_data(opaque)
        if data is not None:
            self._draw(data, moderngl.TRIANGLES, shade=1 if shade else 0, depth_write=True, offset=True)
        lines = []
        for s in items:
            if edges or s.alpha < 1:
                segs = edge_segments(s.edges).reshape(-1, 3)
                if len(segs):
                    col = _edge_color(s, style, highlight)
                    lines.append(np.hstack([segs, np.zeros_like(segs), np.tile((*col, 1.0), (len(segs), 1))]))
        for wi in scene.wires:
            segs = edge_segments(wi.lines).reshape(-1, 3)
            if len(segs):
                col = tuple(SELECT_RGB) if wi.handle in highlight else wi.rgb
                lines.append(np.hstack([segs, np.zeros_like(segs), np.tile((*col, 1.0), (len(segs), 1))]))
        if lines:
            ctx.line_width = 1.0
            self._draw(np.vstack(lines), moderngl.LINES, shade=0, depth_write=True, offset=False)
        data = tri_data(clear)
        if data is not None:                       # see-through faces last
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self._draw(data, moderngl.TRIANGLES, shade=1, depth_write=False, offset=True)
            ctx.disable(moderngl.BLEND)
        raw = fbo.read(components=4)
        rows = np.ascontiguousarray(np.frombuffer(raw, np.uint8).reshape(h, w * 4)[::-1])
        img = QImage(rows.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        if overlay:
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            draw_overlay(p, cam, overlay)
            p.end()
        return img

    def _draw(self, data: np.ndarray, mode, shade: int, depth_write: bool, offset: bool) -> None:
        ctx = self.ctx
        vbo = ctx.buffer(data.astype("f4").tobytes())
        vao = ctx.vertex_array(self.prog, [(vbo, "3f 3f 4f", "in_pos", "in_nrm", "in_col")])
        self.prog["u_shade"].value = shade
        ctx.depth_mask = depth_write
        if offset:
            ctx.polygon_offset = (1.0, 1.0)
        vao.render(mode)
        ctx.polygon_offset = (0.0, 0.0)
        ctx.depth_mask = True
        vao.release()
        vbo.release()


_RENDERER = None


def get_renderer(prefer: str = "auto"):
    """The OpenGL renderer when it works here, else the software one."""
    global _RENDERER
    import os
    if prefer == "software" or os.environ.get("CAD_RENDERER_3D") == "software":
        return PainterRenderer()
    if _RENDERER is None:
        try:
            _RENDERER = GLRenderer()
        except Exception as exc:          # no GPU / driver: still usable, just slower
            log.info("3D view: OpenGL not available (%s); using the software renderer", exc)
            _RENDERER = PainterRenderer()
    return _RENDERER
