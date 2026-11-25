"""Light and dark themes."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

DARK = {
    "window": "#2b3038", "base": "#1f242b", "alt": "#272c34", "text": "#e6e9ee", "muted": "#9aa3ae",
    "button": "#353b45", "border": "#454c58", "accent": "#3d8fe0", "accent_text": "#ffffff",
    "ribbon": "#323843", "canvas": "#212830", "tooltip": "#3a414c",
}
LIGHT = {
    "window": "#f3f4f6", "base": "#ffffff", "alt": "#f7f8fa", "text": "#1d232b", "muted": "#5c6672",
    "button": "#ffffff", "border": "#c9ced6", "accent": "#0a6fd1", "accent_text": "#ffffff",
    "ribbon": "#e9ecf0", "canvas": "#ffffff", "tooltip": "#ffffff",
}


def colors(dark: bool) -> dict[str, str]:
    return DARK if dark else LIGHT


def apply_theme(app: QApplication, dark: bool, font_scale: float = 1.0) -> None:
    c = colors(dark)
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(c["window"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(c["base"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(c["alt"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(c["button"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(c["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(c["accent_text"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["tooltip"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["muted"]))
    pal.setColor(QPalette.ColorRole.Link, QColor(c["accent"]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["muted"]))
    app.setPalette(pal)
    base_pt = 9.0 * font_scale
    app.setStyleSheet(f"""
        * {{ font-size: {base_pt:.1f}pt; }}
        QToolTip {{ background: {c['tooltip']}; color: {c['text']}; border: 1px solid {c['border']};
                    padding: 6px; }}
        #Ribbon {{ background: {c['ribbon']}; border-bottom: 1px solid {c['border']}; }}
        #Ribbon QTabBar::tab {{ padding: 5px 14px; background: transparent; color: {c['muted']}; border: none; }}
        #Ribbon QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
        #RibbonGroup {{ border-right: 1px solid {c['border']}; }}
        #RibbonGroupTitle {{ color: {c['muted']}; font-size: {base_pt * 0.9:.1f}pt; }}
        #Ribbon QToolButton {{ border: 1px solid transparent; border-radius: 4px; padding: 2px 4px; }}
        #Ribbon QToolButton:hover {{ background: {c['button']}; border-color: {c['border']}; }}
        #Ribbon QToolButton:checked {{ background: {c['accent']}; color: {c['accent_text']}; }}
        #AppButton {{ background: {c['accent']}; color: {c['accent_text']}; border-radius: 4px;
                      padding: 4px 12px; font-weight: bold; }}
        #CommandHistory {{ background: {c['base']}; border: 1px solid {c['border']}; }}
        #CommandInput {{ background: {c['base']}; border: 1px solid {c['accent']}; padding: 4px;
                        border-radius: 3px; }}
        #PromptLabel {{ color: {c['accent']}; font-weight: bold; }}
        QStatusBar QToolButton {{ border: 1px solid {c['border']}; border-radius: 3px; padding: 1px 6px;
                                  font-size: {base_pt * 0.9:.1f}pt; }}
        QStatusBar QToolButton:checked {{ background: {c['accent']}; color: {c['accent_text']};
                                          border-color: {c['accent']}; }}
        #CoordLabel {{ font-family: Consolas, 'DejaVu Sans Mono', monospace; min-width: 22em; }}
    """)
