"""AutoCAD DWG through the free ODA File Converter (DWG <-> DXF), which the user installs.

The converter can't be bundled (its license doesn't allow it). The app finds it in its usual install
folder, on the PATH, at the location set in Options > Files, or in the CAD_ODA_CONVERTER environment
variable.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile

from ...core.model import Document
from ..base import FormatPlugin, Option, PluginError, Report
from .dxf import DxfPlugin
from .dxf_export import write_dxf
from .dxf_import import read_dxf

DOWNLOAD_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"
ODA_VERSIONS = {"R2018": "ACAD2018", "R2013": "ACAD2013", "R2010": "ACAD2010", "R2007": "ACAD2007",
                "R2004": "ACAD2004", "R2000": "ACAD2000"}
TIMEOUT_S = 600


def find_converter(configured: str | None = None) -> str | None:
    """Path of ODAFileConverter, or None."""
    for cand in (configured, os.environ.get("CAD_ODA_CONVERTER")):
        if cand and os.path.isfile(cand):
            return cand
    if sys.platform == "win32":
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")]
        found = []
        for root in filter(None, roots):
            found += glob.glob(os.path.join(root, "ODA", "ODAFileConverter*", "ODAFileConverter.exe"))
        if found:
            return sorted(found)[-1]          # newest version folder
    exe = shutil.which("ODAFileConverter")
    if exe:
        return exe
    for p in ("/usr/bin/ODAFileConverter", "/usr/local/bin/ODAFileConverter", "/opt/ODAFileConverter/ODAFileConverter",
              "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"):
        if os.path.isfile(p):
            return p
    return None


def run_converter(exe: str, src: str, out_dir: str, version: str, out_type: str) -> str:
    """Convert one file. Returns the output path. out_type: "DWG" or "DXF"."""
    in_dir = tempfile.mkdtemp(prefix="cad-oda-in-")
    try:
        name = os.path.basename(src)
        shutil.copy2(src, os.path.join(in_dir, name))
        cmd = [exe, in_dir, out_dir, version, out_type, "0", "1", name]     # filter = the exact file name
        env = dict(os.environ)
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000          # CREATE_NO_WINDOW
        elif not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
            if shutil.which("xvfb-run"):
                cmd = ["xvfb-run", "-a"] + cmd
            else:
                env["QT_QPA_PLATFORM"] = "offscreen"
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, timeout=TIMEOUT_S, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise PluginError("The ODA File Converter took too long and was stopped.") from exc
        except OSError as exc:
            raise PluginError(f"The ODA File Converter couldn't be started: {exc}") from exc
        stem = os.path.splitext(name)[0]
        out = os.path.join(out_dir, f"{stem}.{out_type.lower()}")
        if not os.path.isfile(out):
            cands = [f for f in os.listdir(out_dir) if f.lower() == f"{stem.lower()}.{out_type.lower()}"]
            out = os.path.join(out_dir, cands[0]) if cands else out
        err = [f for f in os.listdir(out_dir) if f.lower().endswith(".err")]
        if not os.path.isfile(out):
            detail = ""
            if err:
                with open(os.path.join(out_dir, err[0]), errors="replace") as fh:
                    detail = fh.read().strip()[:500]
            detail = detail or (proc.stderr or proc.stdout or b"").decode(errors="replace").strip()[:500]
            raise PluginError("The ODA File Converter couldn't convert the file." + (f"\n{detail}" if detail else ""))
        return out
    finally:
        shutil.rmtree(in_dir, ignore_errors=True)


class DwgPlugin(FormatPlugin):
    id = "dwg"
    name = "AutoCAD DWG"
    extensions = (".dwg",)
    can_import = True
    can_export = True
    capabilities = DxfPlugin.capabilities
    description = "AutoCAD's own format. Needs the free ODA File Converter."
    converter_path: str | None = None          # set by the app from Options > Files

    def converter(self) -> str | None:
        return find_converter(self.converter_path)

    def available(self) -> tuple[bool, str]:
        if self.converter():
            return True, ""
        return False, ("DWG files need the free ODA File Converter. Download it from "
                       f"{DOWNLOAD_URL}, install it, then try again. If you installed it somewhere unusual, set "
                       "its location in Options > Files. DXF works without it and AutoCAD opens DXF directly.")

    def _need(self) -> str:
        ok, why = self.available()
        if not ok:
            raise PluginError(why)
        return self.converter()

    def export_options(self, doc: Document | None = None) -> list[Option]:
        return [Option("version", "DWG version", "choice", "R2018",
                       tuple((k, f"AutoCAD {k[1:]}") for k in ODA_VERSIONS)),
                Option("units", "Units in the file", "choice", "auto",
                       (("auto", "Automatic (inches for feet-inch and inch drawings, otherwise mm)"),
                        ("mm", "Millimeters"), ("inches", "Inches")))]

    def import_options(self) -> list[Option]:
        return DxfPlugin().import_options()

    def export(self, doc: Document, path: str, options: dict, report: Report) -> None:
        exe = self._need()
        o = self.checked_options("export", options, doc)
        work = tempfile.mkdtemp(prefix="cad-dwg-")
        try:
            stem = os.path.splitext(os.path.basename(path))[0]
            dxf = os.path.join(work, f"{stem}.dxf")
            write_dxf(doc, dxf, "R2018", o["units"], report)
            out_dir = os.path.join(work, "out")
            os.makedirs(out_dir)
            out = run_converter(exe, dxf, out_dir, ODA_VERSIONS[o["version"]], "DWG")
            shutil.copyfile(out, path)
            report.infos[:] = [i for i in report.infos if not i.startswith("Saved as DXF")]
            report.info(f"Saved as DWG {o['version']} with the ODA File Converter.")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def import_(self, path: str, options: dict, report: Report) -> Document:
        exe = self._need()
        o = self.checked_options("import", options)
        work = tempfile.mkdtemp(prefix="cad-dwg-")
        try:
            dxf = run_converter(exe, path, work, "ACAD2018", "DXF")
            return read_dxf(dxf, report, o["units"], o["layouts"])
        finally:
            shutil.rmtree(work, ignore_errors=True)


PLUGINS = [DwgPlugin()]
