"""Start Sheaf."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from . import __version__


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName("Sheaf")
    app.setOrganizationName("Sheaf")
    app.setApplicationVersion(__version__)

    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    win = MainWindow()
    apply_theme(app, win.settings.value("theme", "system", str))
    QGuiApplication.styleHints().colorSchemeChanged.connect(
        lambda *_: apply_theme(app, win.settings.value("theme", "system", str)))
    win.show()
    files = [a for a in argv[1:] if not a.startswith("-")]
    if files:
        win.open_paths(files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
