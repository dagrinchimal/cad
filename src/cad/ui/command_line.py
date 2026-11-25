"""Command line: history, prompt, input with live command suggestions."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QVBoxLayout, QWidget,
)

from ..commands import CommandRegistry


class _Input(QLineEdit):
    key_handler = None

    def keyPressEvent(self, ev: QKeyEvent) -> None:      # noqa: N802
        if self.key_handler and self.key_handler(ev):
            return
        super().keyPressEvent(ev)


class CommandLine(QWidget):
    submitted = Signal(str)          # text the user entered ("" = Enter on empty input)
    escape_pressed = Signal()
    run_command = Signal(str)        # a suggestion picked from the list

    def __init__(self, registry: CommandRegistry, parent=None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.idle = True
        self.history_inputs: list[str] = []
        self._hist_pos = 0

        self.history = QPlainTextEdit(objectName="CommandHistory")
        self.history.setReadOnly(True)
        self.history.setMaximumBlockCount(2000)
        self.history.setFixedHeight(76)
        self.history.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.prompt = QLabel("Type a command:", objectName="PromptLabel")
        self.input = _Input(objectName="CommandInput")
        self.input.setPlaceholderText("Type a command name (e.g. LINE or just 'circ'), or a value, then Enter")
        self.input.key_handler = self._key
        self.input.textEdited.connect(self._update_suggestions)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.prompt)
        row.addWidget(self.input, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(self.history)
        lay.addLayout(row)

        self.popup = QListWidget(self.window())
        self.popup.setWindowFlags(Qt.WindowType.ToolTip)
        self.popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.popup.itemClicked.connect(self._pick_item)
        self.popup.hide()

    # ------------------------------------------------------------------ API
    def set_prompt(self, text: str, idle: bool) -> None:
        self.idle = idle
        self.prompt.setText(text)
        if not idle:
            self.popup.hide()

    def append(self, text: str) -> None:
        self.history.appendPlainText(text)
        self.history.moveCursor(QTextCursor.MoveOperation.End)

    def type_text(self, text: str) -> None:
        self.input.setFocus()
        self.input.insert(text)
        self._update_suggestions(self.input.text())

    # ------------------------------------------------------------------ suggestions
    def _update_suggestions(self, text: str) -> None:
        if not self.idle or not text.strip():
            self.popup.hide()
            return
        found = self.registry.search(text, limit=8)
        if not found:
            self.popup.hide()
            return
        self.popup.clear()
        for c in found:
            alias = f" ({c.aliases[0]})" if c.aliases else ""
            item = QListWidgetItem(f"{c.label}{alias} — {c.description}")
            item.setData(Qt.ItemDataRole.UserRole, c.name)
            self.popup.addItem(item)
        self.popup.setCurrentRow(0)
        w = max(self.input.width(), 420)
        h = min(8, len(found)) * (self.popup.sizeHintForRow(0) + 2) + 6
        pos = self.input.mapToGlobal(self.input.rect().topLeft())
        self.popup.setGeometry(pos.x(), pos.y() - h - 2, w, h)
        self.popup.show()

    def _pick_item(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        self.popup.hide()
        self.input.clear()
        self.run_command.emit(name)

    # ------------------------------------------------------------------ keys
    def _submit(self) -> None:
        text = self.input.text()
        if self.popup.isVisible() and self.popup.currentItem() is not None:
            typed = text.strip().upper()
            exact = self.registry.get(typed) if typed else None
            if exact is None:
                self._pick_item(self.popup.currentItem())
                return
        self.popup.hide()
        if text.strip():
            self.history_inputs.append(text.strip())
        self._hist_pos = len(self.history_inputs)
        self.input.clear()
        self.submitted.emit(text)

    def _key(self, ev: QKeyEvent) -> bool:
        key = ev.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit()
            return True
        if key == Qt.Key.Key_Space:
            text = self.input.text().strip()
            # Space acts as Enter on an empty line or after a command name (like AutoCAD);
            # otherwise it's a real space, e.g. 3' 4 1/2"
            if not text or (self.idle and self.registry.get(text) is not None):
                self._submit()
                return True
            return False
        if key == Qt.Key.Key_Escape:
            if self.popup.isVisible():
                self.popup.hide()
            elif self.input.text():
                self.input.clear()
            else:
                self.escape_pressed.emit()
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            if self.popup.isVisible():
                row = self.popup.currentRow() + (-1 if key == Qt.Key.Key_Up else 1)
                self.popup.setCurrentRow(max(0, min(self.popup.count() - 1, row)))
                return True
            if self.history_inputs:
                self._hist_pos += -1 if key == Qt.Key.Key_Up else 1
                self._hist_pos = max(0, min(len(self.history_inputs), self._hist_pos))
                self.input.setText(self.history_inputs[self._hist_pos] if self._hist_pos < len(self.history_inputs) else "")
                return True
        return False

    def hide_popup(self) -> None:
        self.popup.hide()
