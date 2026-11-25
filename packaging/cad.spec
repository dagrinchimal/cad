# PyInstaller spec: one-folder build (fewer antivirus false positives than one-file).
# Build:  pyinstaller packaging/cad.spec --noconfirm
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

hidden = collect_submodules("glcontext") + collect_submodules("cad") + collect_submodules("rtree")
binaries = collect_dynamic_libs("rtree") + collect_dynamic_libs("glcontext")
datas = collect_data_files("cad") + collect_data_files("ezdxf")

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
