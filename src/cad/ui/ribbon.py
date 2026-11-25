"""Ribbon: tabs of labelled tool groups. Every button has an icon AND a text label."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QMenu, QStackedWidget, QTabBar, QToolButton, QVBoxLayout,
    QWidget,
)

from ..commands import CommandRegistry
from .icons import IconProvider


@dataclass
class Tool:
    command: str                       # command name to run
    label: str | None = None           # defaults to the command's label
    icon: str | None = None
    then: str | None = None            # text to submit after starting (e.g. a keyword)
    variants: list["Tool"] = field(default_factory=list)   # drop-down choices
    large: bool = True
    checkable_key: str | None = None   # for toggles handled by the window


@dataclass
class Group:
    title: str
    tools: list[Tool | str]            # str = special widget id


def tooltip_html(registry: CommandRegistry, name: str, label: str | None = None) -> str:
    c = registry.get(name)
    if c is None:
        return label or name
    sc = c.tooltip_shortcut
    shortcut = f"<br><span style='color:gray'>Command: <b>{c.name}</b>{(' &nbsp;·&nbsp; ' + sc) if sc else ''}</span>"
    return (f"<b>{label or c.label}</b><br>{c.description}{shortcut}"
            f"<br><span style='color:gray'><i>Learn more: press F1</i></span>")


class Ribbon(QWidget):
    tool_triggered = Signal(str, object)      # command, follow-up text
    special_widget_requested = Signal(str, object)

    def __init__(self, registry: CommandRegistry, icons: IconProvider, tabs: list[tuple[str, list[Group]]],
                 app_menu: QMenu, special: dict[str, Callable[[], QWidget]] | None = None, parent=None) -> None:
        super().__init__(parent, objectName="Ribbon")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.registry = registry
        self.icons = icons
        self.special = special or {}
        self.buttons: list[tuple[QToolButton, Tool]] = []

        top = QHBoxLayout()
        top.setContentsMargins(6, 4, 6, 0)
        app_btn = QToolButton(objectName="AppButton", text="File")
        app_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        app_btn.setMenu(app_menu)
        app_btn.setToolTip("New, open, save, recover and exit")
        top.addWidget(app_btn)
        self.tabbar = QTabBar()
        self.tabbar.setDrawBase(False)
        self.tabbar.setExpanding(False)
        top.addWidget(self.tabbar)
        top.addStretch(1)
        self.top_right = QHBoxLayout()
        top.addLayout(self.top_right)

        self.stack = QStackedWidget()
        for title, groups in tabs:
            self.tabbar.addTab(title)
            self.stack.addWidget(self._make_panel(groups))
        self.tabbar.currentChanged.connect(self.stack.setCurrentIndex)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.stack)

    def _make_panel(self, groups: list[Group]) -> QWidget:
        from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(0)
        for g in groups:
            w = self._make_group(g)
            w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            row.addWidget(w)
        row.addStretch(1)
        # never squeeze (and cut off) button labels: scroll sideways on narrow windows instead
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        panel.setMinimumWidth(panel.sizeHint().width())
        scroll.setFixedHeight(panel.sizeHint().height() + 14)
        return scroll

    def _make_group(self, g: Group) -> QWidget:
        box = QWidget(objectName="RibbonGroup")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(box)
        v.setContentsMargins(6, 2, 8, 2)
        v.setSpacing(2)
        body = QHBoxLayout()
        body.setSpacing(2)
        small: list[QWidget] = []

        def flush_small():
            if not small:
                return
            grid = QGridLayout()
            grid.setSpacing(1)
            for i, w in enumerate(small):
                grid.addWidget(w, i % 3, i // 3)
            body.addLayout(grid)
            small.clear()

        for t in g.tools:
            if isinstance(t, str):
                flush_small()
                w = self.special[t]()
                body.addWidget(w)
                continue
            btn = self._make_button(t)
            if t.large:
                flush_small()
                body.addWidget(btn)
            else:
                small.append(btn)
        flush_small()
        v.addLayout(body, 1)
        title = QLabel(g.title, objectName="RibbonGroupTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(title)
        return box

    def _make_button(self, t: Tool) -> QToolButton:
        c = self.registry.get(t.command)
        label = t.label or (c.label if c else t.command)
        btn = QToolButton()
        btn.setText(label)
        btn.setAutoRaise(True)
        icon_name = t.icon or (c.icon if c else t.command.lower())
        btn.setIcon(self.icons.icon(icon_name))
        btn.setProperty("icon_name", icon_name)
        if t.large:
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            btn.setIconSize(QSize(30, 30))
            btn.setMinimumWidth(58)
        else:
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setIconSize(QSize(18, 18))
            btn.setMinimumWidth(btn.fontMetrics().horizontalAdvance(label) + 18 + 22)
        btn.setToolTip(tooltip_html(self.registry, t.command, label))
        btn.setProperty("help_id", c.help_id if c else "")
        if t.checkable_key:
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=t.checkable_key: self.special_widget_requested.emit(k, btn))
        else:
            btn.clicked.connect(lambda _=False, tt=t: self.tool_triggered.emit(tt.command, tt.then))
        if t.variants:
            menu = QMenu(btn)
            for var in t.variants:
                vc = self.registry.get(var.command)
                act = QAction(self.icons.icon(var.icon or (vc.icon if vc else "")), var.label or (vc.label if vc else var.command), menu)
                act.setToolTip(tooltip_html(self.registry, var.command, var.label))
                act.triggered.connect(lambda _=False, vv=var: self.tool_triggered.emit(vv.command, vv.then))
                menu.addAction(act)
            menu.setToolTipsVisible(True)
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.buttons.append((btn, t))
        return btn

    def refresh_icons(self) -> None:
        for btn, _t in self.buttons:
            name = btn.property("icon_name")
            if name:
                btn.setIcon(self.icons.icon(name))
        for w in self.findChildren(QToolButton):
            menu = w.menu()
            if menu is None or w.objectName() == "AppButton":
                continue

    def checkable_buttons(self, key: str) -> list[QToolButton]:
        return [b for b, t in self.buttons if t.checkable_key == key]


def make_combo(min_width: int = 150) -> QComboBox:
    cb = QComboBox()
    cb.setMinimumWidth(min_width)
    return cb
