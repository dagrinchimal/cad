# PyInstaller spec: one-folder build (fewer antivirus false positives than one-file).
# Build:  pyinstaller packaging/cad.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules

import glob
import os

import OCP

hidden = (collect_submodules("glcontext") + collect_submodules("cad") + collect_submodules("rtree")
          + collect_submodules("ezdxf") + ["svgelements", "PySide6.QtPrintSupport"])
binaries = collect_dynamic_libs("rtree") + collect_dynamic_libs("glcontext")
ocp_datas, ocp_bins, ocp_hidden = collect_all("OCP")
hidden += ocp_hidden
binaries += ocp_bins
# OpenCascade's DLLs: next to OCP's .pyd, or in the wheel's "<dist>.libs" folder (delvewheel)
site = os.path.dirname(os.path.dirname(OCP.__file__))
for pattern in ("cadquery_ocp*.libs/*.dll", "OCP/*.dll"):
    for dll in glob.glob(os.path.join(site, pattern)):
        binaries.append((dll, os.path.relpath(os.path.dirname(dll), site)))
datas = collect_data_files("cad") + collect_data_files("ezdxf") + ocp_datas

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="CAD",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="CAD", upx=False)
