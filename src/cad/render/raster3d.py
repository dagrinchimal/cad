"""Turning a 3D scene into a picture.

GLRenderer draws with the graphics card (moderngl, offscreen, real depth buffer).
PainterRenderer is the fallback with no OpenGL: QPainter and depth sorting.
Both return a QImage of the camera's size.
"""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPolygonF

from .camera3d import Camera3D
from .scene3d import Scene3D, edge_segments

log = logging.getLogger(__name__)

LIGHT = np.array([0.35, 0.45, 0.82])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


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


def _face_rgb(rgb, background_dark: bool):
    r, g, b = rgb
    if max(r, g, b) > 0.95 and min(r, g, b) > 0.95:        # white/black color 7: use a neutral grey for faces
        return (0.72, 0.74, 0.78)
    return (r, g, b)


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
        pv = np.cross(D[:, None, :], e2[None, :, :])                  # (n,m,3)
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


class PainterRenderer:
    name = "software"

    def render(self, scene: Scene3D, cam: Camera3D, style: str, background: QColor,
               highlight: set[int] = frozenset(), hover: int | None = None, dark: bool = True,
               overlay_lines: list | None = None) -> QImage:
        img = QImage(max(cam.width, 1), max(cam.height, 1), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(background)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fill, shade, edges, alpha = _style_flags(style)
        light = _light_in_view(cam)
        items = []      # (depth, kind, payload)
        edge_jobs = []  # (segments (n,2,3), color)
        hl = QColor(80, 160, 255)
        for s in scene.solids:
            selected = s.handle in highlight
            hov = s.handle == hover
            if fill and len(s.triangles):
                tri_pts = s.vertices[s.triangles]                       # (m,3,3)
                n = np.cross(tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 0])
                ln = np.linalg.norm(n, axis=1)
                ok = ln > 1e-12
                n[ok] /= ln[ok, None]
                facing = (n @ -cam.forward) > 0 if not cam.perspective else \
                    (np.einsum("ij,ij->i", n, cam.eye - tri_pts[:, 0]) > 0)
                keep = ok & (facing | (alpha < 1))
                scr, depth = cam.project(tri_pts[keep].reshape(-1, 3))
                scr = scr.reshape(-1, 3, 2)
                depth = depth.reshape(-1, 3).mean(axis=1)
                base = np.array(_face_rgb(s.rgb, dark))
                if shade:
                    k = 0.30 + 0.70 * np.abs(n[keep] @ light)
                else:
                    k = np.ones(int(keep.sum()))
                for i in range(len(scr)):
                    c = base * k[i] if shade else ((0.15, 0.15, 0.17) if dark else (1, 1, 1))
                    if selected:
                        c = np.asarray(c) * 0.6 + np.array([0.31, 0.63, 1.0]) * 0.4
                    elif hov:
                        c = np.asarray(c) * 0.8 + np.array([1.0, 0.8, 0.3]) * 0.2
                    items.append((depth[i], 0, (scr[i], c)))
            if edges:
                segs = edge_segments(s.edges)
                if len(segs):
                    col = hl if selected else QColor(20, 20, 24)
                    if style == "Wireframe" and not selected:
                        col = QColor(*[int(v * 255) for v in s.rgb])
                    edge_jobs.append((segs, col))
        for w in scene.wires:
            segs = edge_segments(w.lines)
            if len(segs):
                edge_jobs.append((segs, hl if w.handle in highlight else QColor(*[int(v * 255) for v in w.rgb])))
        # edges: hide the pieces that faces cover (exact ray test, not depth sorting)
        occluders = np.zeros((0, 3, 3))
        if fill and alpha >= 1:
            occ = [s.vertices[s.triangles] for s in scene.solids if len(s.triangles)]
            if occ:
                occluders = np.concatenate(occ)
        size = 1.0
        bb = scene.bbox()
        if bb is not None:
            size = max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2], 1e-6)
        for segs, col in edge_jobs:
            pieces = _split_segments(segs, cam) if len(occluders) else segs
            vis = ~_occluded(pieces.mean(axis=1), cam, occluders, size * 1e-4) if len(occluders) else \
                np.ones(len(pieces), bool)
            scr, _ = cam.project(pieces[vis].reshape(-1, 3))
            scr = scr.reshape(-1, 2, 2)
            for i in range(len(scr)):
                items.append((-1e18, 1, (scr[i], col)))
        if fill:
            items.sort(key=lambda it: -it[0])   # far first; edges (-1e18) last
        a255 = int(alpha * 255)
        p.setPen(Qt.PenStyle.NoPen)
        for _d, kind, (pts, col) in items:
            if kind == 0:
                qc = QColor.fromRgbF(float(min(col[0], 1)), float(min(col[1], 1)), float(min(col[2], 1)))
                qc.setAlpha(a255)
                p.setBrush(QBrush(qc))
                p.setPen(QPen(qc, 0.6) if alpha >= 1 else Qt.PenStyle.NoPen)   # hide seams
                p.drawPolygon(QPolygonF([QPointF(*pts[0]), QPointF(*pts[1]), QPointF(*pts[2])]))
            else:
                p.setPen(QPen(col, 1.4 if kind == 1 else 1.0))
                p.drawLine(QPointF(*pts[0]), QPointF(*pts[1]))
        _draw_overlay(p, cam, overlay_lines)
        p.end()
        return img


def _draw_overlay(p: QPainter, cam: Camera3D, lines) -> None:
    """Lines drawn on top (rubber bands, previews): list of ((k,3) array, QColor)."""
    for pts, col in lines or ():
        if len(pts) < 2:
            continue
        scr, _ = cam.project(np.asarray(pts, float))
        p.setPen(QPen(col, 1.2, Qt.PenStyle.DashLine))
        p.drawPolyline(QPolygonF([QPointF(float(x), float(y)) for x, y in scr]))


# ---------------------------------------------------------------------- OpenGL
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
    if cam.perspective:
        eye = cam.eye
    else:
        eye = cam.target - f * (far * 0.5)
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
        import moderngl
        try:
            self.ctx = moderngl.create_standalone_context(require=330)
        except Exception:
            self.ctx = moderngl.create_standalone_context(require=330, backend="egl")
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
               highlight: set[int] = frozenset(), hover: int | None = None, dark: bool = True,
               overlay_lines: list | None = None) -> QImage:
        import moderngl
        w, h = max(cam.width, 1), max(cam.height, 1)
        fbo = self._target(w, h)
        fbo.use()
        ctx = self.ctx
        ctx.viewport = (0, 0, w, h)
        fbo.clear(background.redF(), background.greenF(), background.blueF(), 1.0, depth=1.0)
        fill, shade, edges, alpha = _style_flags(style)
        bb = scene.bbox()
        if bb is not None:
            corners = np.array([[x, y, z] for x in (bb[0], bb[3]) for y in (bb[1], bb[4]) for z in (bb[2], bb[5])])
            dz = (corners - cam.target) @ cam.forward
            span = float(np.ptp(dz)) + np.linalg.norm(corners[0] - corners[-1]) + 1.0
        else:
            span = 1000.0
        if cam.perspective:
            far = cam.distance + span * 2
            near = cam.distance * 0.01
        else:
            near, far = 0.0, span * 4 + 2 * float(np.abs((cam.target - (np.zeros(3) if bb is None else
                                                                     np.array(bb[:3]))) @ cam.forward)) + 10
        mvp = _mvp(cam, near, far)
        self.prog["u_mvp"].write(mvp.T.astype("f4").tobytes())
        self.prog["u_light"].value = tuple(float(v) for v in _light_in_view(cam))
        ctx.enable(moderngl.DEPTH_TEST)
        if alpha < 1:
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        else:
            ctx.disable(moderngl.BLEND)
        # faces
        if fill:
            tri_data = []
            for s in scene.solids:
                if not len(s.triangles):
                    continue
                base = np.array(_face_rgb(s.rgb, dark)) if shade else (
                    np.array((0.15, 0.15, 0.17)) if dark else np.ones(3))
                if s.handle in highlight:
                    base = base * 0.6 + np.array([0.31, 0.63, 1.0]) * 0.4
                elif s.handle == hover:
                    base = base * 0.8 + np.array([1.0, 0.8, 0.3]) * 0.2
                idx = s.triangles.reshape(-1)
                v = s.vertices[idx]
                n = s.normals[idx] if len(s.normals) == len(s.vertices) else np.zeros_like(v)
                c = np.tile(np.append(base, alpha), (len(v), 1))
                tri_data.append(np.hstack([v, n, c]))
            if tri_data:
                self._draw(np.vstack(tri_data), moderngl.TRIANGLES, shade=1 if shade else 0,
                           depth_write=alpha >= 1, offset=True)
        # edges and wires
        line_data = []
        if edges:
            for s in scene.solids:
                segs = edge_segments(s.edges).reshape(-1, 3)
                if not len(segs):
                    continue
                if s.handle in highlight:
                    col = (0.31, 0.63, 1.0)
                elif style == "Wireframe":
                    col = s.rgb
                else:
                    col = (0.08, 0.08, 0.09)
                line_data.append(np.hstack([segs, np.zeros_like(segs), np.tile((*col, 1.0), (len(segs), 1))]))
        for wi in scene.wires:
            segs = edge_segments(wi.lines).reshape(-1, 3)
            if len(segs):
                col = (0.31, 0.63, 1.0) if wi.handle in highlight else wi.rgb
                line_data.append(np.hstack([segs, np.zeros_like(segs), np.tile((*col, 1.0), (len(segs), 1))]))
        if line_data:
            ctx.line_width = 1.0
            self._draw(np.vstack(line_data), moderngl.LINES, shade=0, depth_write=True, offset=False)
        data = fbo.read(components=4)
        rows = np.ascontiguousarray(np.frombuffer(data, np.uint8).reshape(h, w * 4)[::-1])
        img = QImage(rows.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        if overlay_lines:
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            _draw_overlay(p, cam, overlay_lines)
            p.end()
        return img

    def _draw(self, data: np.ndarray, mode, shade: int, depth_write: bool, offset: bool) -> None:
        import moderngl
        ctx = self.ctx
        vbo = ctx.buffer(data.astype("f4").tobytes())
        vao = ctx.vertex_array(self.prog, [(vbo, "3f 3f 4f", "in_pos", "in_nrm", "in_col")])
        self.prog["u_shade"].value = shade
        ctx.depth_mask = depth_write
        if offset:
            ctx.enable(moderngl.POLYGON_OFFSET_FILL) if hasattr(moderngl, "POLYGON_OFFSET_FILL") else None
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
