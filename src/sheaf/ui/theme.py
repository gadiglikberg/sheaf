"""Native look with light and dark themes that follow the system (Windows or macOS)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

QSS = """
#modeBar { border-bottom: 1px solid palette(midlight); }
QFrame#modeSwitch { border: 1px solid palette(midlight); border-radius: 9px; background: palette(window); }
QToolButton#modeButton {
    border: none; border-radius: 6px; padding: 4px 16px; min-height: 20px; background: transparent;
}
QToolButton#modeButton:hover { background: palette(midlight); }
QToolButton#modeButton:checked {
    background: palette(highlight); color: palette(highlighted-text); font-weight: 600;
}
#contextBar { border-bottom: 1px solid palette(midlight); }
QToolButton#toolButton { padding: 4px 8px; border-radius: 6px; border: 1px solid transparent; }
QToolButton#toolButton:hover { background: palette(midlight); }
QToolButton#toolButton:checked { background: palette(midlight); border-color: palette(mid); font-weight: 600; }
QToolButton#toolButton[popupMode="1"] { padding-right: 18px; }
QToolButton#toolButton::menu-button { border: none; width: 16px; }
QToolButton#toolButton[popupMode="2"] { padding-right: 20px; }
QToolButton#toolButton::menu-indicator { subcontrol-origin: padding; subcontrol-position: right center; right: 4px; }
QFrame#sep { color: palette(midlight); margin: 4px 6px; }
QLabel#quiet { color: palette(placeholder-text); margin-left: 10px; }
QPushButton#zoomLabel { min-width: 48px; padding: 4px 2px; }
QPushButton#paletteButton {
    border: 1px solid palette(midlight); border-radius: 6px; padding: 4px 12px; color: palette(placeholder-text);
    text-align: left; min-width: 190px;
}
QLabel#localBadge { color: #1a9e4b; font-weight: 600; padding-right: 8px; }
#startTitle { font-size: 30px; font-weight: 700; }
QFrame#startCard { border: 1px solid palette(midlight); border-radius: 14px; background: palette(base); }
QPushButton#dropZone {
    border: 2px dashed palette(mid); border-radius: 12px; font-size: 15px; background: transparent;
}
QPushButton#dropZone:hover { border-color: palette(highlight); }
QDialog#commandPalette { border: 1px solid palette(mid); border-radius: 10px; }
"""

CANVAS = {"light": "#e8e9ed", "dark": "#1b1b1d"}


def is_dark(app: QApplication) -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def apply_theme(app: QApplication, choice: str = "system") -> None:
    hints = QGuiApplication.styleHints()
    if choice == "light":
        hints.setColorScheme(Qt.ColorScheme.Light)
    elif choice == "dark":
        hints.setColorScheme(Qt.ColorScheme.Dark)
    else:
        hints.unsetColorScheme()
    bg = CANVAS["dark" if is_dark(app) else "light"]
    app.setStyleSheet(QSS + f"\n#canvasBackground {{ background: {bg}; }}\n")
