"""HP-GL/2 plotter files (.plt / .hpgl). Pens are assigned from colors."""
from __future__ import annotations

from ...core.plot import Fill, Stroke
from ..base import Option, PluginError
from .sheet_common import SheetPlugin

UNITS_PER_MM = 40            # 1 plotter unit = 0.025 mm


class HpglPlugin(SheetPlugin):
    id = "hpgl"
    name = "HP-GL/2 plotter file"
    extensions = (".plt", ".hpgl")
    description = "For pen plotters, vinyl cutters and older plotters. Colors become pen numbers."

    def export_options(self, doc=None):
        return super().export_options(doc) + [
            Option("pens", "Number of pens", "int", 8, minimum=1, maximum=256,
                   help="Colors beyond this many share the last pen."),
            Option("fills", "Fill solid areas", "bool", True,
                   help="Off for cutters: fills are left as outlines."),
        ]

    def write_sheets(self, sheets, path, o, report) -> None:
        sh = sheets[0]
        pens: dict[tuple, int] = {}
        npen = int(o["pens"])
        out = ["IN;", f"PS{round(sh.width * UNITS_PER_MM)},{round(sh.height * UNITS_PER_MM)};", "SC;", "PU0,0;"]
        widths: dict[int, float] = {}

        def pen(it) -> int:
            if it.color not in pens:
                pens[it.color] = min(len(pens) + 1, npen)
            p = pens[it.color]
            return p

        body = []
        cur = None
        for it in sh.items:
            p = pen(it)
            if isinstance(it, Stroke):
                widths.setdefault(p, it.width)
            if p != cur:
                body.append(f"SP{p};")
                cur = p
            if isinstance(it, Stroke):
                pts = [(round(x * UNITS_PER_MM), round(y * UNITS_PER_MM)) for x, y in it.pts]
                body.append(f"PU{pts[0][0]},{pts[0][1]};PD" + ",".join(f"{x},{y}" for x, y in pts[1:]) + ";")
            elif isinstance(it, Fill):
                for i, lp in enumerate(it.loops):
                    pts = [(round(x * UNITS_PER_MM), round(y * UNITS_PER_MM)) for x, y in lp]
                    first = f"PU{pts[0][0]},{pts[0][1]};"
                    if o["fills"]:
                        body.append(first + ("PM0;" if i == 0 else "") + "PD" + ",".join(f"{x},{y}" for x, y in pts[1:] + pts[:1]) + ";"
                                    + ("PM1;" if i < len(it.loops) - 1 else "PM2;FP;EP;"))
                    else:
                        body.append(first + "PD" + ",".join(f"{x},{y}" for x, y in pts[1:] + pts[:1]) + ";")
        out += [f"PW{w:.2f},{p};" for p, w in sorted(widths.items())]
        out += body
        out.append("PU;SP0;")
        try:
            with open(path, "w", encoding="ascii", newline="\n") as fh:
                fh.write("\n".join(out) + "\n")
        except OSError as exc:
            raise PluginError(f"Couldn't write {path}: {exc}") from exc
        if len(pens) > npen:
            report.warn(f"The drawing has {len(pens)} colors but only {npen} pens; some colors share a pen.")
        legend = ", ".join(f"pen {p}: rgb{c}" for c, p in list(pens.items())[:npen])
        report.info(f"Pens: {legend}.")


PLUGINS = [HpglPlugin()]
