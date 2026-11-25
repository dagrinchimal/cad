"""OpenGL 3.3 canvas (moderngl inside a QOpenGLWidget).

Every line segment is one GPU instance expanded to a quad in the vertex
shader, so thickness (lineweight) and dash patterns (linetypes) cost no CPU.
The static scene (grid + entities) is rendered into an offscreen texture and
reused while only the cursor / previews change.
"""
from __future__ import annotations

import logging

import moderngl
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .canvas_base import CanvasEventsMixin, SceneData

log = logging.getLogger(__name__)

VERTEX_SHADER = """
#version 330
in vec2 in_p0;
in vec2 in_p1;
in float in_d0;
in vec4 in_color;
in float in_width;
in float in_lt;
in float in_lts;

uniform vec2 u_offset;     // origin - view center (model units)
uniform float u_scale;     // device pixels per model unit
uniform vec2 u_half;       // half viewport, device pixels
uniform float u_dpr;

out vec4 v_color;
out float v_dist;
out float v_side;
out float v_hw;
flat out int v_lt;
out float v_lts;

void main() {
    int c = gl_VertexID % 4;
    float t = (c == 1 || c == 3) ? 1.0 : 0.0;
    float side = (c >= 2) ? 1.0 : -1.0;
    vec2 a = (in_p0 + u_offset) * u_scale;
    vec2 b = (in_p1 + u_offset) * u_scale;
    vec2 d = b - a;
    float len = length(d);
    vec2 dir = len > 1e-6 ? d / len : vec2(1.0, 0.0);
    vec2 n = vec2(-dir.y, dir.x);
    float hw = max(in_width * u_dpr, 1.0) * 0.5;
    float ext = hw + 0.75;
    vec2 p = mix(a, b, t) + n * side * ext + dir * (t * 2.0 - 1.0) * 0.5;
    gl_Position = vec4(p / u_half, 0.0, 1.0);
    v_color = in_color;
    v_dist = in_d0 + t * length(in_p1 - in_p0);
    v_side = side * ext;
    v_hw = hw;
    v_lt = int(in_lt + 0.5);
    v_lts = in_lts;
}
"""

FRAGMENT_SHADER = """
#version 330
in vec4 v_color;
in float v_dist;
in float v_side;
in float v_hw;
flat in int v_lt;
in float v_lts;

uniform float u_pat[256];
uniform float u_patlen[32];
uniform int u_patn[32];
uniform float u_px;          // model units per device pixel
uniform float u_gltscale;

out vec4 frag;

void main() {
    float alpha = clamp(v_hw + 0.5 - abs(v_side), 0.0, 1.0);
    if (v_lt > 0) {
        float s = v_lts * u_gltscale;
        float L = u_patlen[v_lt] * s;
        if (L > u_px * 6.0) {
            float d = mod(v_dist, L);
            float acc = 0.0;
            bool on = true;
            int n = u_patn[v_lt];
            for (int i = 0; i < 8; i++) {
                if (i >= n) break;
                float e = u_pat[v_lt * 8 + i] * s;
                float seg = (e == 0.0) ? u_px * 1.5 : abs(e);
                if (d < acc + seg) { on = e >= 0.0; break; }
                acc += seg;
            }
            if (!on) discard;
        }
    }
    frag = vec4(v_color.rgb, v_color.a * alpha);
}
"""

BLIT_VS = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() { v_uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }
"""

BLIT_FS = """
#version 330
uniform sampler2D u_tex;
uniform float u_flip;
in vec2 v_uv;
out vec4 frag;
void main() { frag = texture(u_tex, vec2(v_uv.x, mix(v_uv.y, 1.0 - v_uv.y, u_flip))); }
"""

ATTRS = ("in_p0", "in_p1", "in_d0", "in_color", "in_width", "in_lt", "in_lts")
LAYOUT = "2f 2f 1f 4f 1f 1f 1f/i"


def default_surface_format() -> QSurfaceFormat:
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(0)
    return fmt


class _InstanceBuffer:
    def __init__(self, ctx: moderngl.Context, prog: moderngl.Program) -> None:
        self.ctx, self.prog = ctx, prog
        self.buf: moderngl.Buffer | None = None
        self.vao: moderngl.VertexArray | None = None
        self.count = 0

    def upload(self, data: np.ndarray) -> None:
        self.count = len(data)
        if self.count == 0:
            return
        raw = np.ascontiguousarray(data, dtype=np.float32).tobytes()
        if self.buf is None or self.buf.size < len(raw):
            if self.vao:
                self.vao.release()
            if self.buf:
                self.buf.release()
            self.buf = self.ctx.buffer(reserve=max(len(raw), 4096) * 3 // 2)
            self.vao = self.ctx.vertex_array(self.prog, [(self.buf, LAYOUT, *ATTRS)])
        self.buf.write(raw)

    def draw(self) -> None:
        if self.count and self.vao is not None:
            self.vao.render(moderngl.TRIANGLE_STRIP, vertices=4, instances=self.count)


class GLCanvas(CanvasEventsMixin, QOpenGLWidget):
    backend_name = "OpenGL"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFormat(default_surface_format())
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.data = SceneData()
        self.view = None              # set by the controller
        self.ctx: moderngl.Context | None = None
        self._uploaded = {"scene": -1, "grid": -1}
        self._cache_valid = False
        self._fbo: moderngl.Framebuffer | None = None
        self._tex: moderngl.Texture | None = None
        self._ov_tex: moderngl.Texture | None = None
        self.gl_info = ""
        self.failed = False

    # --------------------------------------------------------------- API used by the controller
    def invalidate(self) -> None:
        """Scene, grid or view changed: re-render the cached scene on next paint."""
        self._cache_valid = False
        self.update()

    # --------------------------------------------------------------- GL lifecycle
    def initializeGL(self) -> None:          # noqa: N802
        try:
            self.ctx = moderngl.create_context()
            self.prog = self.ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
            self.blit_prog = self.ctx.program(vertex_shader=BLIT_VS, fragment_shader=BLIT_FS)
            quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype=np.float32)
            self._quad_buf = self.ctx.buffer(quad.tobytes())
            self._quad = self.ctx.vertex_array(self.blit_prog, [(self._quad_buf, "2f", "in_pos")])
            self.bufs = {k: _InstanceBuffer(self.ctx, self.prog) for k in ("scene", "grid", "highlight", "preview")}
            self.gl_info = f"{self.ctx.info.get('GL_RENDERER', '?')} (OpenGL {self.ctx.version_code})"
            log.info("OpenGL canvas: %s", self.gl_info)
        except Exception:                       # noqa: BLE001
            log.exception("OpenGL initialisation failed")
            self.failed = True

    def _device_size(self) -> tuple[int, int]:
        dpr = self.devicePixelRatioF()
        return max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr))

    def _ensure_target(self, w: int, h: int) -> None:
        if self._tex is not None and self._tex.size == (w, h):
            return
        if self._fbo:
            self._fbo.release()
        if self._tex:
            self._tex.release()
        self._tex = self.ctx.texture((w, h), 4)
        self._fbo = self.ctx.framebuffer(color_attachments=[self._tex])
        self._cache_valid = False

    def _set_uniforms(self, w: int, h: int) -> None:
        v, d = self.view, self.data
        dpr = self.devicePixelRatioF()
        p = self.prog
        p["u_offset"].value = (d.origin[0] - v.cx, d.origin[1] - v.cy)
        p["u_scale"].value = v.scale * dpr
        p["u_half"].value = (w / 2.0, h / 2.0)
        p["u_dpr"].value = dpr
        p["u_px"].value = 1.0 / (v.scale * dpr)
        p["u_gltscale"].value = d.global_ltscale
        pats, lens, counts = d.linetypes
        p["u_pat"].value = pats
        p["u_patlen"].value = lens
        p["u_patn"].value = counts

    def paintGL(self) -> None:               # noqa: N802
        if self.failed or self.ctx is None or self.view is None:
            painter = QPainter(self)
            painter.fillRect(self.rect(), self.data.background)
            painter.end()
            return
        ctx = self.ctx
        d = self.data
        w, h = self._device_size()
        for key in ("scene", "grid"):
            version = d.scene_version if key == "scene" else d.grid_version
            if self._uploaded[key] != version:
                self.bufs[key].upload(d.scene if key == "scene" else d.grid)
                self._uploaded[key] = version
                self._cache_valid = False
        self._ensure_target(w, h)
        ctx.enable(moderngl.BLEND)
        ctx.disable(moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self._set_uniforms(w, h)
        bg = d.background
        if not self._cache_valid:
            self._fbo.use()
            ctx.viewport = (0, 0, w, h)
            ctx.clear(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
            self.bufs["grid"].draw()
            self.bufs["scene"].draw()
            self._cache_valid = True
        screen = ctx.detect_framebuffer(self.defaultFramebufferObject())
        screen.use()
        ctx.viewport = (0, 0, w, h)
        ctx.disable(moderngl.BLEND)
        self._tex.use(0)
        self.blit_prog["u_tex"].value = 0
        self.blit_prog["u_flip"].value = 0.0
        self._quad.render(moderngl.TRIANGLE_STRIP)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.bufs["highlight"].upload(d.highlight)
        self.bufs["highlight"].draw()
        self.bufs["preview"].upload(d.preview)
        self.bufs["preview"].draw()
        self._draw_overlay(w, h)

    def _draw_overlay(self, w: int, h: int) -> None:
        """Cursor, snap markers, tooltips: painted with QPainter on the CPU (reliable text on every
        driver) and composited as one texture."""
        if not self.client:
            return
        img = QImage(w, h, QImage.Format.Format_RGBA8888_Premultiplied)
        img.setDevicePixelRatio(self.devicePixelRatioF())
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.client.paint_overlay(p)
        p.end()
        if self._ov_tex is None or self._ov_tex.size != (w, h):
            if self._ov_tex is not None:
                self._ov_tex.release()
            self._ov_tex = self.ctx.texture((w, h), 4)
        self._ov_tex.write(bytes(img.constBits()))
        self.ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self._ov_tex.use(0)
        self.blit_prog["u_flip"].value = 1.0
        self._quad.render(moderngl.TRIANGLE_STRIP)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    def grab_image(self):
        return self.grabFramebuffer()
