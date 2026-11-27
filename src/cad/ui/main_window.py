"""Main window: ties document, commands, canvas, ribbon, command line and panels together."""
from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDockWidget, QFileDialog, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox,
    QStackedWidget, QTabBar, QToolButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME, FILE_EXTENSION
from ..commands import REGISTRY, CommandContext, CommandRunner, GetDistance, GetPoint, GetSelection
from ..core.model import MODEL_SPACE, Document, Layer
from ..core.model.tables import SKETCH_PREFIX, is_sketch_space, sketch_space
from ..core.spatial import SpatialIndex
from ..core.units import UnitMode, UnitSettings
from ..io import native
from ..render.canvas_base import create_canvas
from . import theme
from .autosave import AutosaveSession, find_recoverable, remove_recoverable
from .command_line import CommandLine
from .controller import CanvasController
from .dialogs import DraftingDialog, LayerDialog, OptionsDialog, RecoveryDialog, UnitsDialog
from .icons import IconProvider
from .properties import PropertiesPanel
from .ribbon import Group, Ribbon, Tool
from .settings import AppSettings, autosave_dir, data_dir, is_portable
from .widgets import swatch

log = logging.getLogger(__name__)
FILE_FILTER = f"CAD drawings (*{FILE_EXTENSION});;All files (*)"

TOGGLES = [
    # key, label, shortcut, tooltip
    ("grid_on", "GRID", "F7", "Show the background grid"),
    ("grid_snap_on", "SNAP", "F9", "Snap the cursor to the grid spacing"),
    ("ortho_on", "ORTHO", "F8", "Only horizontal and vertical lines"),
    ("polar_on", "POLAR", "F10", "Polar tracking: lock onto angle increments"),
    ("osnap_on", "OSNAP", "F3", "Object snap: lock onto ends, midpoints, centers…"),
    ("otrack_on", "OTRACK", "F11", "Object snap tracking: line up with snap points"),
    ("lwt", "LWT", "", "Show lineweights (line thickness)"),
]


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None, doc: Document | None = None) -> None:
        super().__init__()
        from ..core.text import set_text_engine
        from ..render.text_qt import QtTextEngine
        set_text_engine(QtTextEngine())
        self.settings = settings or AppSettings()
        self._load_plugins()
        self.setAcceptDrops(True)
        self.dark = self.settings.dark_theme
        self.icons = IconProvider(self.dark)
        self.snap_cfg = self.settings.snap_settings()

        self.doc = doc or self._blank_document()
        self.index = SpatialIndex(self.doc)
        from ..core.constraints import ConstraintManager
        self.cmgr = ConstraintManager(self.doc)
        self.ctx = CommandContext(doc=self.doc, index=self.index, view=self, ui=self,
                                  on_message=self._on_message, constraints=self.cmgr)
        self.runner = CommandRunner(self.ctx, REGISTRY)

        # canvas + controller
        self.canvas = create_canvas()
        self.controller = CanvasController(self.canvas, self.doc, self.index, self.runner, self.snap_cfg,
                                           dark=self.dark, show_lineweights=self.settings.show_lineweights)
        self.controller.coords_changed.connect(self._set_coords)
        self.controller.selection_changed.connect(self._schedule_properties)
        self.controller.context_menu_requested.connect(self._context_menu)
        self.controller.forward_text.connect(self._forward_text)
        self.controller.edit_requested.connect(self.edit_object)

        # command line
        self.cmdline = CommandLine(REGISTRY)
        self.cmdline.submitted.connect(self._on_submit)
        self.cmdline.run_command.connect(self.run_command)
        self.cmdline.escape_pressed.connect(self.controller.escape)
        self.runner.listeners.append(self._on_runner_changed)

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        from .view3d import View3D
        self.view3d = View3D(self.controller)
        self.view3d.status.connect(self._set_coords)
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.canvas)
        self.view_stack.addWidget(self.view3d)
        v.addWidget(self.view_stack, 1)
        self.layout_tabs = QTabBar()
        self.layout_tabs.setShape(QTabBar.Shape.RoundedSouth)
        self.layout_tabs.setExpanding(False)
        self.layout_tabs.setDrawBase(False)
        self.layout_tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.layout_tabs.setToolTip("Model: where you draw at full size.<br>Layouts: paper sheets for printing, "
                                    "with a title block and viewports.")
        self.layout_tabs.currentChanged.connect(self._layout_tab_changed)
        self.layout_tabs.customContextMenuRequested.connect(self._layout_tab_menu)
        v.addWidget(self.layout_tabs)
        v.addWidget(self.cmdline)
        self.setCentralWidget(central)

        self._build_actions()
        self._build_ribbon()
        self._build_status_bar()
        self._build_properties()

        self._props_timer = QTimer(self, singleShot=True, interval=0)
        self._props_timer.timeout.connect(self.properties.refresh)
        self.doc.add_listener(self._on_doc_change)

        self.autosave = AutosaveSession(autosave_dir())
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self.autosave_now)
        self._restart_autosave_timer()

        self.resize(1400, 900)
        geo = self.settings.get("window/geometry")
        if isinstance(geo, QByteArray):
            self.restoreGeometry(geo)
        self._on_runner_changed()
        self._refresh_all()
        self.cmdline.append(f"Welcome to {APP_NAME}. Type a command (try LINE or just 'circ'), "
                            "or click a tool above. Press F1 for help on any tool.")
        QTimer.singleShot(0, self.canvas.setFocus)

    # ================================================================ setup
    def _load_plugins(self) -> None:
        """Built-in formats, plus any user plugins in the data folder's plugins/ subfolder."""
        from ..plugins import registry
        registry.load_builtins()
        plugin_dir = data_dir() / "plugins"
        try:
            plugin_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        registry.load_folder(plugin_dir)
        self.apply_converter_setting()

    def apply_converter_setting(self) -> None:
        from ..plugins import registry
        try:
            registry.get("dwg").converter_path = self.settings.get("exchange/oda_converter", "") or None
        except Exception:                       # noqa: BLE001 - a user plugin may have replaced it
            pass

    def _blank_document(self) -> Document:
        mode = self.settings.get("drawing/default_units", "mm")
        try:
            units = UnitSettings(mode=UnitMode(mode))
        except ValueError:
            units = UnitSettings()
        return Document(units=units)

    def _build_actions(self) -> None:
        def act(text, shortcut, fn, tip=""):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(fn)
            if tip:
                a.setToolTip(tip)
            self.addAction(a)
            return a
        self.a_new = act("New", "Ctrl+N", lambda: self.run_command("NEW"))
        self.a_open = act("Open…", "Ctrl+O", lambda: self.run_command("OPEN"))
        self.a_save = act("Save", "Ctrl+S", lambda: self.run_command("QSAVE"))
        self.a_saveas = act("Save As…", "Ctrl+Shift+S", lambda: self.run_command("SAVEAS"))
        self.a_plot = act("Plot…", "Ctrl+P", lambda: self.run_command("PLOT"))
        self.a_undo = act("Undo", "Ctrl+Z", self.undo)
        self.a_redo = act("Redo", "Ctrl+Y", self.redo)
        act("Select all", "Ctrl+A", self.controller.select_all)
        act("Properties", "Ctrl+1", lambda: self.run_ui_action("PROPERTIES"))
        act("Help", "F1", lambda: self.show_help())
        for key, _label, sc, _tip in TOGGLES:
            if sc:
                act(key, sc, lambda _=False, k=key: self.toggle(k))

    def _build_ribbon(self) -> None:
        app_menu = QMenu(self)
        for name in ("NEW", "OPEN", "QSAVE", "SAVEAS"):
            c = REGISTRY.get(name)
            a = app_menu.addAction(self.icons.icon(c.icon), f"{c.label}\t{c.shortcut}")
            a.triggered.connect(lambda _=False, n=name: self.run_command(n))
        self.recent_menu = app_menu.addMenu("Open recent")
        app_menu.addSeparator()
        for name in ("IMPORT", "EXPORT", "BATCHEXPORT", "PLOT"):
            c = REGISTRY.get(name)
            a = app_menu.addAction(self.icons.icon(c.icon), f"{c.label}…" + (f"\t{c.shortcut}" if c.shortcut else ""))
            a.triggered.connect(lambda _=False, n=name: self.run_command(n))
        app_menu.addSeparator()
        a = app_menu.addAction(self.icons.icon("recover"), "Recover autosaved drawings…")
        a.triggered.connect(lambda: self.run_command("RECOVER"))
        a = app_menu.addAction(self.icons.icon("options"), "Options…")
        a.triggered.connect(lambda: self.run_command("OPTIONS"))
        app_menu.addSeparator()
        a = app_menu.addAction(self.icons.icon("exit"), "Exit")
        a.triggered.connect(self.close)
        app_menu.aboutToShow.connect(self._fill_recent)

        S = lambda name, label=None, then=None, icon=None: Tool(name, label, icon, then=then, large=False)  # noqa: E731
        home = [
            Group("Draw", [
                Tool("LINE"), Tool("PLINE"),
                Tool("CIRCLE", variants=[Tool("CIRCLE", "Center, Radius", "circle"),
                                         Tool("CIRCLE", "2-Point", "circle_2p", then="2P"),
                                         Tool("CIRCLE", "3-Point", "circle_3p", then="3P")]),
                Tool("ARC", variants=[Tool("ARC", "3-Point", "arc"),
                                      Tool("ARC", "Center, Start, End", "arc_center", then="C")]),
                S("RECTANG"), S("POLYGON"), S("ELLIPSE"), S("SPLINE"), S("POINT"), S("BOUNDARY"),
                Tool("HATCH"),
            ]),
            Group("Modify", [
                S("MOVE"), S("COPY"), S("STRETCH"), S("ROTATE"), S("MIRROR"), S("SCALE"),
                S("TRIM"), S("EXTEND"), S("OFFSET"), S("FILLET"), S("CHAMFER"), S("JOIN"),
                S("ARRAYRECT", "Array"), S("ARRAYPOLAR", "Polar Array"), S("BREAK"),
                S("EXPLODE"), S("ERASE"), S("UNDO"),
            ]),
            Group("Layers", ["layer_combo", Tool("LAYER", label="Layer\nProperties")]),
            Group("Block", [Tool("INSERT", label="Insert"), S("BLOCK", "Create"), S("ATTDEF", "Attribute"),
                            S("GROUP"), S("UNGROUP")]),
            Group("Utilities", [S("DIST", "Measure"), S("ID", "Locate Point"), S("UNITS"),
                                S("DSETTINGS", "Drafting Settings")]),
        ]
        annotate = [
            Group("Text", [Tool("MTEXT", label="Multiline\nText"), Tool("TEXT", label="Single\nLine")]),
            Group("Dimensions", [Tool("DIMLINEAR", label="Linear"), S("DIMALIGNED", "Aligned"),
                                 S("DIMANGULAR", "Angular"), S("DIMRADIUS", "Radius"), S("DIMDIAMETER", "Diameter"),
                                 S("DIMORDINATE", "Ordinate"), S("DIMSTYLE", "Dim Style")]),
            Group("Leaders", [Tool("LEADER")]),
        ]
        parametric = [
            Group("Geometric", [S("GCCOINCIDENT"), S("GCCOLLINEAR"), S("GCCONCENTRIC"), S("GCFIX"),
                                S("GCPARALLEL"), S("GCPERPENDICULAR"), S("GCHORIZONTAL"), S("GCVERTICAL"),
                                S("GCTANGENT"), S("GCSYMMETRIC"), S("GCEQUAL")]),
            Group("Dimensional", [Tool("DCLINEAR", label="Linear"), S("DCALIGNED", "Aligned"),
                                  S("DCANGULAR", "Angular"), S("DCRADIUS", "Radius"), S("DCDIAMETER", "Diameter")]),
            Group("Manage", [Tool("PARAMETERS"), S("DELCONSTRAINT", "Delete"), S("CONSTRAINTBAR", "Show/Hide"),
                             S("CONSTRAINTSTATUS", "Status")]),
        ]
        modeling = [
            Group("Sketch", [Tool("SKETCH"), S("EDITSKETCH", "Edit Sketch"), S("EXITSKETCH", "Finish Sketch"),
                             S("DELSKETCH", "Delete Sketch")]),
            Group("Create", [Tool("EXTRUDE"), Tool("REVOLVE"), S("SWEEP"), S("LOFT"), S("PRESSPULL", "Press/Pull")]),
            Group("Primitives", [Tool("BOX"), S("CYLINDER"), S("CONE"), S("SPHERE"), S("TORUS"), S("WEDGE")]),
            Group("Combine", [Tool("UNION"), Tool("SUBTRACT"), S("INTERSECT")]),
            Group("Edit Solids", [Tool("FILLETEDGE", label="Fillet\nEdge"), S("CHAMFEREDGE", "Chamfer Edge"),
                                  S("SHELL"), S("SLICE"), S("3DMOVE", "3D Move"), S("3DROTATE", "3D Rotate")]),
            Group("Inspect", [S("MASSPROP", "Mass Props"), S("FLATSHOT")]),
            Group("View", [Tool("VIEW3D", label="3D\nView", then="SW Iso"), Tool("ORBIT"),
                           Tool("PLAN", label="Plan\nView"), S("VSCURRENT", "Visual Style")]),
        ]
        layout_tab = [
            Group("Layout", [Tool("LAYOUT", label="New\nLayout", then="N"), Tool("MVIEW", label="Viewport"),
                             Tool("PAGESETUP", label="Page\nSetup")]),
        ]
        output = [
            Group("Plot", [Tool("PLOT"), Tool("PAGESETUP", label="Page\nSetup")]),
            Group("Export", [Tool("EXPORT"), S("EXPORTPDF", "PDF"), S("DXFOUT", "DXF"),
                             Tool("BATCHEXPORT", label="Batch\nExport")]),
            Group("Import", [Tool("IMPORT"), S("DXFIN", "Open DXF")]),
        ]
        view = [
            Group("Navigate", [Tool("ZOOMEXTENTS", label="Zoom\nExtents", icon="zoomextents"),
                               Tool("ZOOMWINDOW", label="Zoom\nWindow", icon="zoomwindow"),
                               Tool("ZOOM", label="Previous", icon="zoomprevious", then="P", large=False),
                               Tool("ZOOM", label="Zoom In", icon="zoomin", then="I", large=False),
                               Tool("ZOOM", label="Zoom Out", icon="zoomout", then="O", large=False),
                               Tool("PAN"), Tool("REGEN")]),
            Group("Show", [Tool("PROPERTIES"), Tool("OPTIONS"), Tool("HELP")]),
        ]
        self.layer_combo = QComboBox()
        self.layer_combo.setMinimumWidth(170)
        self.layer_combo.setToolTip("<b>Current layer</b><br>New objects go on this layer.")
        self.layer_combo.activated.connect(self._layer_combo_chosen)

        def layer_widget():
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(2, 6, 2, 2)
            lay.addWidget(QLabel("Current layer"))
            lay.addWidget(self.layer_combo)
            return w
        self.ribbon = Ribbon(REGISTRY, self.icons, [("Home", home), ("Annotate", annotate),
                                                    ("Parametric", parametric), ("3D", modeling),
                                                    ("Layout", layout_tab),
                                                    ("Output", output), ("View", view)], app_menu,
                             special={"layer_combo": layer_widget})
        self.ribbon.tool_triggered.connect(self._ribbon_tool)
        self.setMenuWidget(self.ribbon)

    def _build_status_bar(self) -> None:
        sb = self.statusBar()
        self.prompt_label = QLabel()
        self.prompt_label.setObjectName("PromptLabel")
        self.prompt_label.setMinimumWidth(20)          # long prompts are cut off, never widen the window
        self.coord_label = QLabel(objectName="CoordLabel")
        self.units_combo = QComboBox()
        for m in UnitMode:
            self.units_combo.addItem(m.label, m.value)
        self.units_combo.setToolTip("<b>Units</b><br>How lengths are shown. You can type any unit at any time.")
        self.units_combo.activated.connect(self._units_combo_chosen)
        sb.addWidget(self.prompt_label, 1)
        sb.addPermanentWidget(self.coord_label)
        sb.addPermanentWidget(self.units_combo)
        self.toggle_buttons: dict[str, QToolButton] = {}
        for key, label, sc, tip in TOGGLES:
            b = QToolButton(text=label)
            b.setCheckable(True)
            b.setToolTip(f"<b>{label}</b>{f' ({sc})' if sc else ''}<br>{tip}")
            b.clicked.connect(lambda _=False, k=key: self.toggle(k))
            sb.addPermanentWidget(b)
            self.toggle_buttons[key] = b
        self.renderer_label = QLabel(f"<span style='color:gray'>{self.canvas.backend_name}</span>")
        sb.addPermanentWidget(self.renderer_label)
        self._sync_toggles()

    def _build_properties(self) -> None:
        self.properties = PropertiesPanel(lambda: self.doc, lambda: self.ctx.selection, dark=self.dark)
        self.props_dock = QDockWidget("Properties", self)
        self.props_dock.setObjectName("PropertiesDock")
        self.props_dock.setWidget(self.properties)
        self.props_dock.setMinimumWidth(260)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.props_dock)

    # ================================================================ commands & input
    def run_command(self, name: str, then: str | None = None) -> None:
        self.cmdline.hide_popup()
        self.runner.run(name)
        if then and self.runner.is_active:
            self.runner.submit_text(then)
        self.controller._after_input()
        self.canvas.setFocus()

    def _ribbon_tool(self, name: str, then) -> None:
        self.run_command(name, then)

    def _on_submit(self, text: str) -> None:
        if self.runner.is_active:
            self.cmdline.append(f"{self.runner.prompt} {text.strip()}")
        if not text.strip() and isinstance(self.runner.request, GetSelection):
            self.controller.enter()
        else:
            self.runner.submit_text(text)
            self.controller._after_input()
        if self.runner.is_active:
            self.canvas.setFocus()

    def _forward_text(self, text: str) -> None:
        self.cmdline.type_text(text)

    def _on_message(self, text: str) -> None:
        self.cmdline.append(text)

    def _on_runner_changed(self) -> None:
        from ..commands import GetString
        req = self.runner.request
        if isinstance(req, GetString) and req.multiline and req is not getattr(self, "_text_dialog_for", None):
            self._text_dialog_for = req
            QTimer.singleShot(0, lambda r=req: self._ask_multiline(r))
        prompt = self.runner.prompt
        self.cmdline.set_prompt(prompt if self.runner.is_active else "Command:", not self.runner.is_active)
        self.prompt_label.setText(prompt if self.runner.is_active else
                                  "Ready — type a command or pick a tool")
        self._update_undo_actions()

    def _ask_multiline(self, req) -> None:
        if self.runner.request is not req:
            return
        from .dialogs import TextDialog
        dlg = TextDialog(req.prompt, req.initial, self)
        if dlg.exec():
            self.runner.submit_text(dlg.text())
        else:
            self.runner.cancel()
        self.controller._after_input()
        self.canvas.setFocus()

    def undo(self) -> None:
        if self.runner.is_active:
            self.runner.cancel()
        self.runner.run("UNDO")

    def redo(self) -> None:
        if self.runner.is_active:
            self.runner.cancel()
        self.runner.run("REDO")

    # ================================================================ ViewApi for commands
    def visible_rect(self):
        return self.controller.view.visible_rect()

    def pick_tolerance(self) -> float:
        from .controller import PICKBOX_PX
        return PICKBOX_PX * self.controller.view.pixel

    def zoom_extents(self) -> None:
        if self.in_3d:
            self.view3d.zoom_extents()
            return
        self.controller.zoom_extents()

    def zoom_window(self, p1, p2) -> None:
        self.controller.zoom_window(p1, p2)

    def zoom_previous(self) -> bool:
        return self.controller.zoom_previous()

    def zoom_factor(self, factor: float) -> None:
        if self.in_3d:
            self.view3d.cam.zoom(factor)
            self.view3d.invalidate()
            return
        self.controller.zoom_factor(factor)

    def regen(self) -> None:
        self.controller.regen()

    # ================================================================ UiApi for commands
    def run_ui_action(self, name: str) -> None:
        # Dialogs must open after the command finishes (outside its generator)
        QTimer.singleShot(0, lambda: self._ui_action(name))

    def _ui_action(self, name: str) -> None:
        handlers = {
            "NEW": self.new_drawing, "OPEN": self.open_dialog, "QSAVE": self.save, "SAVEAS": self.save_as,
            "RECOVER": lambda: self.offer_recovery(force=True), "EXIT": self.close,
            "LAYER": self.layer_dialog, "UNITS": self.units_dialog, "DSETTINGS": self.drafting_dialog,
            "OPTIONS": self.options_dialog, "HELP": self.show_help,
            "PROPERTIES": lambda: self.props_dock.setVisible(not self.props_dock.isVisible()),
        }
        handlers["PAGESETUP"] = self.page_setup_dialog
        handlers["EXPORT"] = self.export_dialog
        handlers["EXPORTPDF"] = lambda: self.export_dialog("pdf")
        handlers["DXFOUT"] = lambda: self.export_dialog("dxf")
        handlers["IMPORT"] = self.import_dialog
        handlers["DXFIN"] = lambda: self.open_dialog(dxf_only=True)
        handlers["PLOT"] = self.plot_dialog
        handlers["BATCHEXPORT"] = self.batch_export_dialog
        handlers["PARAMETERS"] = self.parameters_dialog
        handlers["CONSTRAINTBAR"] = self.toggle_constraint_display
        handlers["DIMSTYLE"] = self.dimstyle_dialog
        if name.startswith("VIEW3D:"):
            self.show_3d(name.split(":", 1)[1] or None)
            return
        if name.startswith("VSCURRENT:"):
            self.show_3d(None)
            self.view3d.set_style(name.split(":", 1)[1])
            return
        if name.startswith("PERSPECTIVE:"):
            self.show_3d(None)
            self.view3d.set_perspective(name.endswith("On"))
            return
        if name == "PLAN":
            self.show_plan()
            return
        if name.startswith("SHOWLAYOUT:"):
            self.show_space(name.split(":", 1)[1])
            return
        fn = handlers.get(name)
        if fn:
            fn()

    # ================================================================ documents
    def set_document(self, doc: Document) -> None:
        if self.runner.is_active:
            self.runner.cancel()
        self.doc.remove_listener(self._on_doc_change)
        self.index.detach()
        self.cmgr.detach()
        from ..core.constraints import ConstraintManager
        self.cmgr = ConstraintManager(doc)
        self.ctx.constraints = self.cmgr
        self.doc = doc
        self.index = SpatialIndex(doc)
        self.ctx.doc = doc
        self.ctx.index = self.index
        self.ctx.selection.clear()
        self.ctx.last_point = None
        self.controller.set_document(doc, self.index)
        self.view3d.set_document(doc)
        self.show_plan()
        doc.add_listener(self._on_doc_change)
        self.autosave.discard_copy()
        self._refresh_all()

    def maybe_save(self) -> bool:
        """Ask to save changes. Returns False if the user cancelled."""
        if not self.doc.is_modified:
            return True
        r = QMessageBox.question(
            self, "Save changes?", f"Save changes to {self.title()}?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return r == QMessageBox.StandardButton.Discard

    def new_drawing(self) -> None:
        if self.maybe_save():
            self.set_document(self._blank_document())

    def _start_dir(self) -> str:
        return os.path.dirname(self.doc.path) if self.doc.path else str(self.settings.get("exchange/last_dir", Path.home()))

    def open_dialog(self, dxf_only: bool = False) -> None:
        if not self.maybe_save():
            return
        from .file_exchange import open_filter
        flt = "AutoCAD DXF (*.dxf)" if dxf_only else open_filter()
        path, _ = QFileDialog.getOpenFileName(self, "Open drawing", self._start_dir(), flt)
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        """Open a .cadz drawing, or any importable file (DXF, DWG, SVG) as a new drawing."""
        from ..plugins import PluginError, Report, registry
        self.settings.set("exchange/last_dir", os.path.dirname(path))
        if path.lower().endswith(FILE_EXTENSION):
            try:
                doc, warnings = native.load(path)
            except Exception as exc:            # noqa: BLE001
                QMessageBox.critical(self, "Can't open drawing", f"{path}\n\n{exc}")
                return False
            self.set_document(doc)
            for w in warnings:
                self.cmdline.append(f"Note: {w}")
            self.settings.add_recent(path)
            self.cmdline.append(f"Opened {path}")
            return True
        report = Report(title=f"Opened {os.path.basename(path)}")
        try:
            plugin = registry.for_path(path, "import")
            ok, why = plugin.available()
            if not ok:
                raise PluginError(why)
            from .file_exchange import remembered
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                doc = plugin.import_(path, remembered(self.settings, plugin.id, "import"), report)
            finally:
                QApplication.restoreOverrideCursor()
        except PluginError as exc:
            QMessageBox.warning(self, "Can't open file", f"{path}\n\n{exc}")
            return False
        except Exception as exc:                # noqa: BLE001
            QMessageBox.critical(self, "Can't open file", f"{path}\n\n{exc}")
            return False
        # an opened DXF/DWG saves back to the same file and format with Ctrl+S, like AutoCAD
        doc.path = path if plugin.can_export and plugin.id in ("dxf", "dwg") else None
        doc.save_format = plugin.id if doc.path else None
        self.set_document(doc)
        self.controller.zoom_extents()
        self.settings.add_recent(path)
        self._show_report(report)
        return True

    def _show_report(self, report, title: str = "Report") -> None:
        from .file_exchange import ReportDialog, report_needs_dialog
        for line in report.summary().splitlines():
            self.cmdline.append(line)
        if report_needs_dialog(report) and not os.environ.get("CAD_NO_REPORT_DIALOGS"):
            ReportDialog(title, report, self).exec()

    def save(self) -> bool:
        if not self.doc.path:
            return self.save_as()
        return self._save_to(self.doc.path)

    def save_as(self) -> bool:
        from .file_exchange import save_filter
        start = self.doc.path or os.path.join(self._start_dir(), f"Drawing1{FILE_EXTENSION}")
        path, flt = QFileDialog.getSaveFileName(self, "Save drawing as", start, save_filter())
        if not path:
            return False
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".dxf", ".dwg", FILE_EXTENSION):
            ext = ".dxf" if "dxf" in flt.lower() else ".dwg" if "dwg" in flt.lower() else FILE_EXTENSION
            path += ext
        return self._save_to(path)

    def _save_to(self, path: str) -> bool:
        if not path.lower().endswith(FILE_EXTENSION):
            return self._save_foreign(path)
        try:
            native.save(self.doc, path, thumbnail_png=self._thumbnail())
        except Exception as exc:            # noqa: BLE001
            QMessageBox.critical(self, "Save failed", f"Couldn't save to {path}\n\n{exc}")
            return False
        self.doc.path = path
        self.doc.save_format = None
        self.doc.mark_saved()
        self.autosave.discard_copy()
        self.settings.add_recent(path)
        self.cmdline.append(f"Saved {path}")
        self._update_title()
        return True

    def _save_foreign(self, path: str) -> bool:
        """Save as DXF/DWG: warn once about what the format can't keep, then write it."""
        from ..plugins import PluginError, Report, registry
        from .file_exchange import remembered
        try:
            plugin = registry.for_path(path, "export")
            ok, why = plugin.available()
            if not ok:
                raise PluginError(why)
        except PluginError as exc:
            QMessageBox.warning(self, "Can't save", str(exc))
            return False
        losses = plugin.losses(self.doc)
        warned = getattr(self.doc, "_warned_losses", set())
        if losses and (path, plugin.id) not in warned and not os.environ.get("CAD_NO_REPORT_DIALOGS"):
            r = QMessageBox.question(
                self, f"Save as {plugin.name}?",
                f"{plugin.name} can't keep everything in this drawing:\n\n• " + "\n• ".join(losses) +
                f"\n\nTo keep everything, also save it as {FILE_EXTENSION}. Save as {plugin.name} anyway?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
            if r != QMessageBox.StandardButton.Save:
                return False
        warned.add((path, plugin.id))
        self.doc._warned_losses = warned
        report = Report(title=f"Saved {os.path.basename(path)}")
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                plugin.export(self.doc, path, remembered(self.settings, plugin.id), report)
            finally:
                QApplication.restoreOverrideCursor()
        except Exception as exc:                # noqa: BLE001
            QMessageBox.critical(self, "Save failed", f"Couldn't save to {path}\n\n{exc}")
            return False
        self.doc.path = path
        self.doc.save_format = plugin.id
        self.doc.mark_saved()
        self.autosave.discard_copy()
        self.settings.add_recent(path)
        self.cmdline.append(f"Saved {path} ({plugin.name})")
        self._update_title()
        return True

    # ================================================================ import / export / plot
    def export_dialog(self, preselect: str | None = None) -> None:
        from ..plugins import PluginError, Report
        from .file_exchange import ExportDialog
        base = os.path.splitext(self.doc.path)[0] if self.doc.path else os.path.join(self._start_dir(), "Drawing1")
        dlg = ExportDialog(self.doc, self.settings, base, preselect, self)
        if not dlg.exec():
            return
        plugin, path, values = dlg.result_values()
        self.run_export(plugin.id, path, values)

    def run_export(self, plugin_id: str, path: str, values: dict) -> bool:
        from ..plugins import PluginError, Report, registry
        plugin = registry.get(plugin_id)
        report = Report(title=f"Exported {os.path.basename(path)}")
        for w in plugin.losses(self.doc):
            report.warn(f"Not kept: {w}")
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                plugin.export(self.doc, path, values, report)
            finally:
                QApplication.restoreOverrideCursor()
        except PluginError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return False
        except Exception as exc:                # noqa: BLE001
            QMessageBox.critical(self, "Export failed", f"{path}\n\n{exc}")
            return False
        self.settings.set("exchange/last_dir", os.path.dirname(path))
        self._show_report(report, "Export")
        return True

    def import_dialog(self) -> None:
        from .file_exchange import open_filter
        path, _ = QFileDialog.getOpenFileName(self, "Import into this drawing", self._start_dir(), open_filter())
        if path:
            self.import_path(path)

    def import_path(self, path: str) -> bool:
        """Add another file's model-space objects to this drawing (one undo step)."""
        from ..core.merge import merge_into
        from ..plugins import PluginError, Report, registry
        from .file_exchange import remembered
        report = Report(title=f"Imported {os.path.basename(path)}")
        try:
            plugin = registry.for_path(path, "import")
            ok, why = plugin.available()
            if not ok:
                raise PluginError(why)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                src = plugin.import_(path, remembered(self.settings, plugin.id, "import"), report)
            finally:
                QApplication.restoreOverrideCursor()
        except PluginError as exc:
            QMessageBox.warning(self, "Can't import", f"{path}\n\n{exc}")
            return False
        if src.header.units.mode is not self.doc.header.units.mode:
            report.info("The file's units differ from this drawing's; sizes were kept in real-world units.")
        with self.doc.transaction(f"Import {os.path.basename(path)}"):
            added = merge_into(self.doc, src)
        self.ctx.selection = set(added)
        self.controller.update_highlight()
        report.info(f"{len(added)} objects added and selected (Move them if needed).")
        self._show_report(report, "Import")
        return True

    def plot_dialog(self) -> None:
        from ..plugins import PluginError
        from ..render.text_qt import ensure_qt_text_engine
        from .file_exchange import PlotDialog, print_sheets
        ensure_qt_text_engine()
        base = os.path.splitext(self.doc.path)[0] if self.doc.path else os.path.join(self._start_dir(), "Drawing1")
        dlg = PlotDialog(self.doc, self.settings, base + ".pdf", self)
        if self.controller.space != MODEL_SPACE:
            w = dlg.form.widgets.get("what")
            i = w.findData(self.controller.space) if w else -1
            if i >= 0:
                w.setCurrentIndex(i)
                dlg.update_preview()
        if not dlg.exec():
            return
        try:
            sheets = dlg.sheets()
            printer = dlg.make_printer()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                print_sheets(printer, sheets)
            finally:
                QApplication.restoreOverrideCursor()
        except PluginError as exc:
            QMessageBox.warning(self, "Plot", str(exc))
            return
        where = printer.outputFileName() or printer.printerName()
        self.cmdline.append(f"Plotted {len(sheets)} sheet{'s' if len(sheets) > 1 else ''} to {where}")

    def batch_export_dialog(self) -> None:
        from .file_exchange import BatchExportDialog, batch_export
        base = os.path.splitext(os.path.basename(self.doc.path))[0] if self.doc.path else "Drawing1"
        dlg = BatchExportDialog(self.doc, self.settings, self._start_dir(), base, self)
        if not dlg.exec():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            report = batch_export(self.doc, self.settings, dlg.chosen(), dlg.folder.text(), dlg.base.text().strip())
        finally:
            QApplication.restoreOverrideCursor()
        self._show_report(report, "Batch Export")

    # ================================================================ drag and drop
    def dragEnterEvent(self, ev) -> None:          # noqa: N802
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:               # noqa: N802
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            for p in paths:
                self.import_path(p)                # Ctrl+drop: add into this drawing
        elif self.maybe_save():
            self.open_path(paths[0])

    def _thumbnail(self) -> bytes | None:
        try:
            from PySide6.QtCore import QBuffer, QIODevice
            img = self.canvas.grab_image().scaled(QSize(256, 256), Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation)
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            img.save(buf, "PNG")
            return bytes(buf.data())
        except Exception:                   # noqa: BLE001
            return None

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        files = self.settings.recent_files
        if not files:
            self.recent_menu.addAction("(none yet)").setEnabled(False)
        for f in files:
            a = self.recent_menu.addAction(f)
            a.triggered.connect(lambda _=False, p=f: self.maybe_save() and self.open_path(p))

    # ================================================================ autosave / recovery
    def _restart_autosave_timer(self) -> None:
        mins = self.settings.autosave_minutes
        if mins > 0:
            self._autosave_timer.start(mins * 60_000)
        else:
            self._autosave_timer.stop()

    def autosave_now(self) -> bool:
        ok = self.autosave.save(self.doc, self.title())
        if ok:
            self.statusBar().showMessage("Autosaved", 2500)
        return ok

    def offer_recovery(self, force: bool = False) -> None:
        items = find_recoverable(autosave_dir())
        if not items:
            if force:
                QMessageBox.information(self, "Recover", "There are no autosaved drawings to recover.")
            return
        dlg = RecoveryDialog(items, self)
        if dlg.exec() != RecoveryDialog.DialogCode.Accepted:
            return
        if dlg.discard:
            for it in items:
                remove_recoverable(it)
            return
        chosen = dlg.chosen()
        if not chosen:
            return
        it = chosen[0]
        if not self.maybe_save():
            return
        try:
            doc, _ = native.load(it["file"])
        except Exception as exc:          # noqa: BLE001
            QMessageBox.critical(self, "Recover", f"Couldn't read the autosave: {exc}")
            return
        doc.path = it.get("original_path")
        doc.saved_revision = -1             # recovered work counts as unsaved
        self.set_document(doc)
        remove_recoverable(it)
        self.cmdline.append(f"Recovered '{it['title']}'. Save it to keep it.")
        if len(chosen) > 1:
            self.cmdline.append(f"{len(chosen) - 1} more recovered drawing(s) are waiting: use File > Recover.")

    # ================================================================ dialogs
    def layer_dialog(self) -> None:
        LayerDialog(self.doc, self.dark, self).exec()

    def units_dialog(self) -> None:
        dlg = UnitsDialog(self.doc.header.units, self)
        if dlg.exec():
            self._set_units(dlg.result_units())

    def _set_units(self, units: UnitSettings) -> None:
        if units == self.doc.header.units:
            return
        if self.runner.is_active:
            self.runner.cancel()
        with self.doc.transaction("Units"):
            self.doc.set_header(replace(self.doc.header, units=units))
        self.cmdline.append(f"Units: {units.mode.label}")

    def drafting_dialog(self) -> None:
        dlg = DraftingDialog(self.snap_cfg, self.doc, self)
        if dlg.exec():
            cfg, grid, snap = dlg.result(self.snap_cfg)
            self._apply_snap_cfg(cfg)
            if (grid, snap) != (self.doc.header.grid_spacing, self.doc.header.snap_spacing):
                with self.doc.transaction("Grid settings"):
                    self.doc.set_header(replace(self.doc.header, grid_spacing=grid, snap_spacing=snap))

    def options_dialog(self) -> None:
        dlg = OptionsDialog(self.settings, self.canvas.gl_info, str(data_dir()), is_portable(), self)
        if dlg.exec():
            ch = dlg.apply()
            self.apply_converter_setting()
            self.set_theme(ch["dark"])
            self._restart_autosave_timer()
            if ch["restart"]:
                QMessageBox.information(self, "Options", "Some changes take effect after you restart the program.")

    def set_theme(self, dark: bool) -> None:
        self.dark = dark
        theme.apply_theme(QApplication.instance(), dark, self.settings.font_scale)
        self.icons.set_dark(dark)
        self.ribbon.refresh_icons()
        self.controller.set_theme(dark)
        self.properties.set_dark(dark)
        self._refresh_layer_combo()

    # ================================================================ toggles
    def toggle(self, key: str) -> None:
        if key == "lwt":
            self.settings.show_lineweights = not self.settings.show_lineweights
            self.controller.set_show_lineweights(self.settings.show_lineweights)
        else:
            cfg = self.snap_cfg
            new_val = not getattr(cfg, key)
            setattr(cfg, key, new_val)
            if key == "ortho_on" and new_val:
                cfg.polar_on = False            # ortho and polar are mutually exclusive (as in AutoCAD)
            if key == "polar_on" and new_val:
                cfg.ortho_on = False
            self._apply_snap_cfg(cfg)
            label = next(t[1] for t in TOGGLES if t[0] == key)
            self.cmdline.append(f"<{label} {'on' if new_val else 'off'}>")
        self._sync_toggles()

    def _apply_snap_cfg(self, cfg) -> None:
        self.snap_cfg = cfg
        self.controller.cfg = cfg
        self.settings.save_snap_settings(cfg)
        self.controller.update_grid()
        self._sync_toggles()

    def _sync_toggles(self) -> None:
        for key, b in self.toggle_buttons.items():
            b.setChecked(self.settings.show_lineweights if key == "lwt" else bool(getattr(self.snap_cfg, key)))

    # ================================================================ refresh
    def _on_doc_change(self, doc, cs) -> None:
        if "layout" in cs.tables or "sketch" in cs.tables or cs.reset:
            if self.controller.space != "*Model" and not self._space_exists(self.controller.space):
                self.controller.set_space("*Model")
            self._refresh_layout_tabs()
        if cs.layers or cs.header or cs.reset:
            self._refresh_layer_combo()
            self._sync_units_combo()
        self._update_title()
        self._update_undo_actions()
        self._schedule_properties()

    def _schedule_properties(self) -> None:
        self._props_timer.start()

    # ================================================================ layouts
    def _refresh_layout_tabs(self) -> None:
        tb = self.layout_tabs
        tb.blockSignals(True)
        while tb.count():
            tb.removeTab(0)
        tb.addTab("Model")
        tb.setTabData(0, "*Model")
        layouts = sorted(self.doc.layouts.values(), key=lambda lo: lo.order)
        for name in sorted(self.doc.sketches):
            i = tb.addTab("✎ " + name)
            tb.setTabData(i, sketch_space(name))
            tb.setTabToolTip(i, f"Sketch {name}: a drawing plane in 3D. Right-click to delete.")
        for lo in layouts:
            i = tb.addTab(lo.name)
            tb.setTabData(i, lo.name)
        if not layouts:
            i = tb.addTab("Layout1")
            tb.setTabData(i, "+Layout1")
            tb.setTabToolTip(i, "Click to create a printable sheet with a title block")
        i = tb.addTab("+")
        tb.setTabData(i, "+")
        tb.setTabToolTip(i, "New layout sheet")
        cur = self.controller.space
        for k in range(tb.count()):
            if tb.tabData(k) == cur:
                tb.setCurrentIndex(k)
        tb.blockSignals(False)

    def _layout_tab_changed(self, idx: int) -> None:
        data = self.layout_tabs.tabData(idx)
        if data is None:
            return
        if data.startswith("+"):
            from ..core.layouts import create_layout
            n = len(self.doc.layouts) + 1
            while f"Layout{n}" in self.doc.layouts:
                n += 1
            name = data[1:] if len(data) > 1 else f"Layout{n}"
            if self.runner.is_active:
                self.runner.cancel()
            with self.doc.transaction("New layout"):
                create_layout(self.doc, name)
            data = name
        self.show_space(data)

    def _space_exists(self, space: str) -> bool:
        return space == "*Model" or space in self.doc.layouts or (
            is_sketch_space(space) and space[len(SKETCH_PREFIX):] in self.doc.sketches)

    @property
    def in_3d(self) -> bool:
        return self.view_stack.currentWidget() is self.view3d

    def show_3d(self, preset: str | None = None) -> None:
        """Switch to the 3D view of the model (optionally to a standard view)."""
        if self.controller.space != "*Model":
            self.show_space("*Model")
        first = not self.in_3d
        self.view_stack.setCurrentWidget(self.view3d)
        if preset:
            self.view3d.set_view(preset)
        elif first and not self.view3d.fitted:
            self.view3d.zoom_extents()
        self.view3d.invalidate()
        self.view3d.setFocus()

    def show_plan(self) -> None:
        self.view_stack.setCurrentWidget(self.canvas)
        self.canvas.setFocus()

    def show_space(self, space: str) -> None:
        if space != "*Model" and hasattr(self, "view_stack"):
            self.view_stack.setCurrentWidget(self.canvas)
        if not self._space_exists(space):
            space = "*Model"
        self.controller.set_space(space)
        self._refresh_layout_tabs()
        self.canvas.setFocus()

    def _layout_tab_menu(self, pos) -> None:
        idx = self.layout_tabs.tabAt(pos)
        name = self.layout_tabs.tabData(idx) if idx >= 0 else None
        if not name or name.startswith("+") or name == "*Model":
            return
        m = QMenu(self)
        if is_sketch_space(name):
            sk = name[len(SKETCH_PREFIX):]
            m.addAction("Refresh reference lines").triggered.connect(lambda: self._refresh_sketch_ref(sk))
            m.addAction("Delete sketch").triggered.connect(lambda: self._delete_sketch(sk))
            m.exec(self.layout_tabs.mapToGlobal(pos))
            return
        m.addAction("Rename…").triggered.connect(lambda: self._rename_layout(name))
        m.addAction("Page setup…").triggered.connect(lambda: (self.show_space(name), self.page_setup_dialog()))
        m.addSeparator()
        m.addAction("Delete").triggered.connect(lambda: self._delete_layout(name))
        m.exec(self.layout_tabs.mapToGlobal(pos))

    def _refresh_sketch_ref(self, name: str) -> None:
        from ..commands.sketch3d import refresh_reference
        with self.doc.transaction("Refresh sketch"):
            refresh_reference(self.doc, self.doc.sketches[name])

    def _delete_sketch(self, name: str) -> None:
        from ..commands.sketch3d import delete_sketch
        if QMessageBox.question(self, "Delete sketch", f"Delete sketch {name} and what's drawn on it? "
                                "Solids made from it stay.") != QMessageBox.StandardButton.Yes:
            return
        if self.controller.space == sketch_space(name):
            self.controller.set_space("*Model")
        with self.doc.transaction("Delete sketch"):
            delete_sketch(self.doc, name)
        self._refresh_layout_tabs()

    def _rename_layout(self, name: str) -> None:
        from ..core.layouts import rename_layout
        new, ok = QInputDialog.getText(self, "Rename layout", "New name:", text=name)
        new = new.strip()
        if not ok or not new or new == name:
            return
        if new in self.doc.layouts or new == "Model":
            QMessageBox.warning(self, "Rename layout", "That name is already used.")
            return
        with self.doc.transaction("Rename layout"):
            rename_layout(self.doc, name, new)
        if self.controller.space == name:
            self.controller.space = new
            self.controller.index.space = new
            self.doc.current_space = new
            self.ctx.space = new
        self.show_space(self.controller.space)

    def _delete_layout(self, name: str) -> None:
        from ..core.layouts import delete_layout
        if QMessageBox.question(self, "Delete layout", f"Delete layout {name} and everything on it?") \
                != QMessageBox.StandardButton.Yes:
            return
        if self.controller.space == name:
            self.controller.set_space("*Model")
        with self.doc.transaction("Delete layout"):
            delete_layout(self.doc, name)
        self._refresh_layout_tabs()

    def page_setup_dialog(self) -> None:
        name = self.controller.space
        lo = self.doc.layouts.get(name)
        if lo is None:
            QMessageBox.information(self, "Page setup", "Switch to a layout tab to set up its paper.")
            return
        from .dialogs import PageSetupDialog
        dlg = PageSetupDialog(lo, self)
        if dlg.exec():
            paper, portrait = dlg.result()
            with self.doc.transaction("Page setup"):
                self.doc.set_item("layout", name, lo.with_paper(paper, portrait))
            self.controller.rebuild_scene()
            self.controller.zoom_extents()

    def edit_object(self, e) -> None:
        """Double-click: edit text, notes, attribute values or dimension text in place."""
        from dataclasses import replace as _r

        from ..core.model import BlockReference, Dimension, Leader, MText, Text
        from .dialogs import AttributesDialog, TextDialog
        if self.doc.is_locked(e):
            self.cmdline.append("That object is on a locked layer.")
            return
        new = None
        if isinstance(e, (Text, MText, Leader)):
            dlg = TextDialog("Edit text", e.text, self)
            if dlg.exec():
                t = dlg.text()
                new = _r(e, text=t.replace("\n", " ") if isinstance(e, Text) else t.rstrip("\n"))
        elif isinstance(e, Dimension):
            t, ok = QInputDialog.getText(self, "Dimension text",
                                         "Text (empty = measured value, <> = the measured value inside your text):",
                                         text=e.text)
            if ok:
                new = _r(e, text=t)
        elif isinstance(e, BlockReference):
            bdef = self.doc.blocks.get(e.name)
            ads = bdef.attdefs() if bdef else []
            if not ads:
                self.ctx.selection = {e.handle}
                self.controller._selection_updated()
                self.props_dock.show()
                return
            dlg = AttributesDialog([(a.tag, a.prompt or a.tag, e.attrib(a.tag, a.default)) for a in ads], self)
            if dlg.exec():
                new = e
                for tag, val in dlg.values().items():
                    new = new.with_attrib(tag, val)
        else:
            self.ctx.selection = {e.handle}
            self.controller._selection_updated()
            self.props_dock.show()
            return
        if new is not None and new != e:
            with self.doc.transaction("Edit"):
                self.doc.replace(new)

    def parameters_dialog(self) -> None:
        from .dialogs import ParametersDialog
        ParametersDialog(self.doc, self).exec()

    def toggle_constraint_display(self) -> None:
        self.controller.show_constraints = not self.controller.show_constraints
        self.cmdline.append(f"Constraint symbols {'shown' if self.controller.show_constraints else 'hidden'}.")
        self.canvas.update()

    def dimstyle_dialog(self) -> None:
        from .dialogs import DimStyleDialog
        name = self.doc.header.current_dimstyle
        st = self.doc.dimstyle(name)
        dlg = DimStyleDialog(st, self.doc.header.units, self)
        if dlg.exec():
            with self.doc.transaction("Dimension style"):
                self.doc.set_item("dimstyle", st.name, dlg.result())

    def _refresh_all(self) -> None:
        self._refresh_layout_tabs()
        self._refresh_layer_combo()
        self._sync_units_combo()
        self._update_title()
        self._update_undo_actions()
        self._schedule_properties()

    def _refresh_layer_combo(self) -> None:
        cb = self.layer_combo
        cb.blockSignals(True)
        cb.clear()
        for name, layer in self.doc.layers.items():
            flags = []
            if not layer.on:
                flags.append("off")
            if layer.frozen:
                flags.append("frozen")
            if layer.locked:
                flags.append("locked")
            label = name + (f"  ({', '.join(flags)})" if flags else "")
            cb.addItem(swatch(layer.color, self.dark), label, name)
        cb.setCurrentIndex(cb.findData(self.doc.header.current_layer))
        cb.blockSignals(False)

    def _layer_combo_chosen(self, idx: int) -> None:
        name = self.layer_combo.itemData(idx)
        if name and name != self.doc.header.current_layer and not self.doc.in_transaction:
            try:
                with self.doc.transaction("Current layer"):
                    self.doc.set_current_layer(name)
            except Exception as exc:        # noqa: BLE001
                QMessageBox.warning(self, "Layer", str(exc))
                self._refresh_layer_combo()
        self.canvas.setFocus()

    def _sync_units_combo(self) -> None:
        self.units_combo.blockSignals(True)
        self.units_combo.setCurrentIndex(self.units_combo.findData(self.doc.header.units.mode.value))
        self.units_combo.blockSignals(False)

    def _units_combo_chosen(self, idx: int) -> None:
        mode = UnitMode(self.units_combo.itemData(idx))
        self._set_units(self.doc.header.units.with_mode(mode))
        self.canvas.setFocus()

    def title(self) -> str:
        return os.path.basename(self.doc.path) if self.doc.path else "Drawing1"

    def _update_title(self) -> None:
        self.setWindowTitle(f"{self.title()}{' *' if self.doc.is_modified else ''} — {APP_NAME}")

    def _update_undo_actions(self) -> None:
        self.a_undo.setEnabled(bool(self.doc.undo_name))
        self.a_redo.setEnabled(bool(self.doc.redo_name))

    def _set_coords(self, text: str) -> None:
        self.coord_label.setText(text)

    # ================================================================ context menu
    def _context_menu(self, pos: QPoint) -> None:
        self.build_context_menu().exec(pos)

    def build_context_menu(self) -> QMenu:
        """Menu offering only what fits the current state: command options, the selection, or the view."""
        m = QMenu(self)
        req = self.runner.request
        if self.runner.is_active:
            m.addAction("Enter").triggered.connect(self.controller.enter)
            m.addAction("Cancel").triggered.connect(self.controller.escape)
            if req is not None and req.keywords:
                m.addSeparator()
                for k in req.keywords:
                    m.addAction(k.name).triggered.connect(lambda _=False, n=k.name: (self.runner.submit_keyword(n),
                                                                                    self.controller._after_input()))
            if isinstance(req, (GetPoint, GetDistance)):
                m.addSeparator()
                snaps = m.addMenu("Snap settings")
                snaps.addAction("Drafting settings…").triggered.connect(self.drafting_dialog)
        elif self.ctx.selection:
            n = len(self.ctx.selection)
            m.addAction(self.icons.icon("erase"), f"Erase {n} object(s)").triggered.connect(lambda: self.run_command("ERASE"))
            for name in ("MOVE", "COPY", "ROTATE", "SCALE", "MIRROR"):
                c = REGISTRY.get(name)
                m.addAction(self.icons.icon(c.icon), c.label).triggered.connect(lambda _=False, n_=name: self.run_command(n_))
            from ..core.model import BlockReference, Dimension, Hatch, Polyline
            sel = [self.doc.entities[h] for h in self.ctx.selection if h in self.doc.entities]
            if any(isinstance(e, (Polyline, BlockReference, Dimension, Hatch)) for e in sel):
                m.addAction(self.icons.icon("explode"), "Explode").triggered.connect(lambda: self.run_command("EXPLODE"))
            if len(sel) >= 2:
                m.addAction(self.icons.icon("group"), "Group").triggered.connect(lambda: self.run_command("GROUP"))
            m.addAction(self.icons.icon("properties"), "Properties").triggered.connect(lambda: self.props_dock.show())
            m.addSeparator()
            m.addAction("Deselect all").triggered.connect(self.controller.clear_selection)
        else:
            last = self.runner.last_command
            if last is not None:
                m.addAction(f"Repeat {last.label}").triggered.connect(lambda: self.run_command(last.name))
            if self.doc.undo_name:
                m.addAction(self.icons.icon("undo"), f"Undo {self.doc.undo_name}").triggered.connect(self.undo)
            if self.doc.redo_name:
                m.addAction(self.icons.icon("redo"), f"Redo {self.doc.redo_name}").triggered.connect(self.redo)
            m.addSeparator()
            m.addAction(self.icons.icon("zoomextents"), "Zoom extents").triggered.connect(self.controller.zoom_extents)
            m.addAction(self.icons.icon("pan"), "Pan").triggered.connect(lambda: self.run_command("PAN"))
            m.addAction("Select all").triggered.connect(self.controller.select_all)
        return m

    # ================================================================ help (full help system arrives in Phase 5)
    def show_help(self, page_id: str | None = None) -> None:
        """F1: help on the running command, else on the ribbon button under the mouse, else the home page."""
        from PySide6.QtGui import QCursor
        from .help_window import HelpWindow
        if page_id is None:
            if self.runner.active is not None:
                page_id = self.runner.active.help_id
            else:
                w = QApplication.widgetAt(QCursor.pos())
                while w is not None and not (w.property("help_id") or ""):
                    w = w.parentWidget()
                page_id = (w.property("help_id") if w is not None else "") or "home"
        if getattr(self, "help_window", None) is None:
            self.help_window = HelpWindow(self)
            self.help_window.run_command.connect(self._help_run)
        hw = self.help_window
        if not hw.show_page(page_id):
            hw.show_page("home")
        hw.show()
        hw.raise_()
        hw.activateWindow()

    def _help_run(self, name: str) -> None:
        self.activateWindow()
        self.run_command(name)
        self.canvas.setFocus()

    # ================================================================ close
    def closeEvent(self, ev: QCloseEvent) -> None:     # noqa: N802
        if self.runner.is_active:
            self.runner.cancel()
        if not self.maybe_save():
            ev.ignore()
            return
        self.settings.set("window/geometry", self.saveGeometry())
        self.settings.sync()
        self.autosave.close()
        ev.accept()


_ = Layer
