"""The help window: contents, search as you type, back/forward, and links that start commands."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QSplitter, QStackedWidget, QTextBrowser,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..commands import REGISTRY
from ..help import library

GROUP_ORDER = ["Draw", "Modify", "Annotation", "Block", "Groups", "Layers", "Parametric", "Layout", "Output",
               "View", "Utilities", "Edit", "Application"]
TYPE_LABEL = {"command": "Command", "concept": "Guide", "tutorial": "Tutorial", "term": "Glossary",
              "home": "Help", "glossary": "Glossary", "commands": "Reference"}


def commands_markdown() -> str:
    lib = library()
    lines = ["# All commands", "", "Every command, grouped as on the ribbon. Type the name (or the short "
             "name in brackets) in the command line and press Enter.", ""]
    groups: dict[str, list] = {}
    for c in REGISTRY.all():
        groups.setdefault(c.group or "Other", []).append(c)
    for g in sorted(groups, key=lambda g: GROUP_ORDER.index(g) if g in GROUP_ORDER else 99):
        lines += ["", f"## {g}", ""]
        for c in sorted(groups[g], key=lambda c: c.label):
            page = lib.get(c.help_id)
            short = f" ({', '.join(c.aliases[:2])})" if c.aliases else ""
            lines.append(f"- [{c.label}](help:{c.help_id}) `{c.name}`{short} — {page.summary if page else c.description}")
    return "\n".join(lines)


class HelpWindow(QWidget):
    run_command = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Help — CAD: Calling All Dumbies")
        self.resize(1100, 720)
        self.lib = library()
        self.history: list[str] = []
        self.pos = -1
        # toolbar
        self.back = QToolButton(text="◀", toolTip="Back (Alt+Left)")
        self.fwd = QToolButton(text="▶", toolTip="Forward (Alt+Right)")
        self.home = QToolButton(text="Home", toolTip="Help home page")
        self.back.clicked.connect(self.go_back)
        self.fwd.clicked.connect(self.go_forward)
        self.home.clicked.connect(lambda: self.show_page("home"))
        self.search = QLineEdit(placeholderText="Search help: a command, a word, or what you want to do…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search_changed)
        self.search.returnPressed.connect(self._open_first_hit)
        top = QHBoxLayout()
        for w in (self.back, self.fwd, self.home):
            top.addWidget(w)
        top.addWidget(self.search, 1)
        # left: contents tree / search results
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemActivated.connect(self._tree_item)
        self.tree.itemClicked.connect(self._tree_item)
        self.results = QListWidget()
        self.results.setWordWrap(True)
        self.results.setSpacing(3)
        self.results.itemActivated.connect(self._result_item)
        self.results.itemClicked.connect(self._result_item)
        self.no_hits = QLabel("No matches. Try other words, e.g. what you want to do.")
        self.no_hits.setWordWrap(True)
        self.no_hits.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.left = QStackedWidget()
        self.left.addWidget(self.tree)
        self.left.addWidget(self.results)
        self.left.addWidget(self.no_hits)
        # right: the page
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.view.document().setDocumentMargin(18)
        split = QSplitter()
        split.addWidget(self.left)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 800])
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        QShortcut(QKeySequence("Alt+Left"), self, self.go_back)
        QShortcut(QKeySequence("Alt+Right"), self, self.go_forward)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search.setFocus)
        QShortcut(QKeySequence("Esc"), self, self.close)
        self._timer = QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self._do_search)
        self._fill_tree()
        self.show_page("home")

    def sizeHint(self) -> QSize:          # noqa: N802
        return QSize(1100, 720)

    # ------------------------------------------------------------ contents
    def _fill_tree(self) -> None:
        lib = self.lib

        def add(parent, title, pid):
            it = QTreeWidgetItem(parent, [title])
            it.setData(0, Qt.ItemDataRole.UserRole, pid)
            return it
        add(self.tree, "Help home", "home")
        start = add(self.tree, "Start here", "getting-started")
        for p in lib.of_type("concept"):
            if p.order <= 3:
                add(start, p.title, p.id)
        tut = add(self.tree, "Tutorials", None)
        for p in lib.of_type("tutorial"):
            add(tut, p.title.replace("Tutorial: ", ""), p.id)
        how = add(self.tree, "How things work", None)
        for p in lib.of_type("concept"):
            if p.order > 3:
                add(how, p.title, p.id)
        cmds = add(self.tree, "Commands", "commands")
        groups: dict[str, QTreeWidgetItem] = {}
        for c in sorted(REGISTRY.all(), key=lambda c: (GROUP_ORDER.index(c.group) if c.group in GROUP_ORDER else 99,
                                                     c.label)):
            g = groups.get(c.group) or add(cmds, c.group or "Other", None)
            groups[c.group] = g
            add(g, c.label, c.help_id)
        add(self.tree, "Glossary", "glossary")
        start.setExpanded(True)
        tut.setExpanded(True)

    def _tree_item(self, item, _col=0) -> None:
        pid = item.data(0, Qt.ItemDataRole.UserRole)
        if pid:
            self.show_page(pid)
        else:
            item.setExpanded(not item.isExpanded())

    # ------------------------------------------------------------ search
    def _search_changed(self, _text: str) -> None:
        self._timer.start()

    def _do_search(self) -> None:
        q = self.search.text().strip()
        if not q:
            self.left.setCurrentWidget(self.tree)
            return
        hits = self.lib.search(q, 30)
        if hits:                                   # keep the clearly relevant ones
            best = hits[0].score
            hits = [h for h in hits if h.score >= best * 0.7][:15]
        self.results.clear()
        for h in hits:
            it = QListWidgetItem(f"{h.title}  —  {TYPE_LABEL.get(h.type, h.type)}")
            it.setData(Qt.ItemDataRole.UserRole, h.page_id)
            it.setToolTip(h.summary)
            self.results.addItem(it)
        self.left.setCurrentWidget(self.results if hits else self.no_hits)

    def search_for(self, text: str) -> None:
        self.search.setText(text)
        self._timer.stop()
        self._do_search()

    def _result_item(self, item) -> None:
        self.show_page(item.data(Qt.ItemDataRole.UserRole))

    def _open_first_hit(self) -> None:
        self._timer.stop()
        self._do_search()
        if self.results.count() and self.left.currentWidget() is self.results:
            self.show_page(self.results.item(0).data(Qt.ItemDataRole.UserRole))

    # ------------------------------------------------------------ pages
    def markdown_for(self, pid: str) -> str | None:
        if pid == "glossary":
            return self.lib.glossary_markdown()
        if pid == "commands":
            return commands_markdown()
        page = self.lib.get(pid)
        return self.lib.markdown(page) if page else None

    def show_page(self, pid: str, record: bool = True) -> bool:
        md = self.markdown_for(pid)
        if md is None:
            return False
        self.view.setMarkdown(md)
        self._style_document()
        self.view.verticalScrollBar().setValue(0)
        self.current = pid
        if record:
            del self.history[self.pos + 1:]
            self.history.append(pid)
            self.pos = len(self.history) - 1
        self.back.setEnabled(self.pos > 0)
        self.fwd.setEnabled(self.pos < len(self.history) - 1)
        page = self.lib.get(pid)
        self.setWindowTitle(f"Help: {page.title if page else pid} — CAD: Calling All Dumbies")
        return True

    def _style_document(self) -> None:
        """Grey boxes behind typed steps (code blocks) and a little air above headings."""
        from PySide6.QtGui import QColor, QTextCursor, QTextFormat
        doc = self.view.document()
        dark = self.palette().window().color().lightness() < 128
        code_bg = QColor(43, 47, 54) if dark else QColor(236, 239, 243)
        block = doc.begin()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        while block.isValid():
            fmt = block.blockFormat()
            changed = False
            if fmt.hasProperty(QTextFormat.Property.BlockCodeFence) or fmt.nonBreakableLines():
                fmt.setBackground(code_bg)
                fmt.setLeftMargin(12)
                changed = True
            elif fmt.headingLevel() > 0:
                fmt.setTopMargin(14 if fmt.headingLevel() > 1 else 4)
                fmt.setBottomMargin(4)
                changed = True
            if changed:
                cur.setPosition(block.position())
                cur.setBlockFormat(fmt)
            block = block.next()
        cur.endEditBlock()

    def go_back(self) -> None:
        if self.pos > 0:
            self.pos -= 1
            self.show_page(self.history[self.pos], record=False)

    def go_forward(self) -> None:
        if self.pos < len(self.history) - 1:
            self.pos += 1
            self.show_page(self.history[self.pos], record=False)

    def _link(self, url: QUrl) -> None:
        scheme = url.scheme()
        target = url.toString()[len(scheme) + 1:]
        if scheme == "help":
            self.show_page(target.split("#")[0])
        elif scheme == "term":
            t = self.lib.term(target) or self.lib.get(f"term/{target}")
            if t:
                self.show_page(t.id)
        elif scheme == "run":
            self.run_command.emit(target)
        elif scheme in ("http", "https"):
            QDesktopServices.openUrl(url)
