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

    from .core import fileio
    from .single_instance import Instance
    from .ui.icons import app_icon
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    app.setWindowIcon(app_icon())

    files = [a for a in argv[1:] if not a.startswith("-")]
    instance = Instance(fileio.app_data_dir())
    if not instance.primary and instance.send(files):
        return 0  # the window that is already open took the files
    # If another Sheaf is running but didn't answer, open a separate window and leave its recovery copies alone.
    win = MainWindow(offer_recovery=instance.primary)
    if instance.primary:
        instance.listen()
        instance.filesReceived.connect(win.open_from_elsewhere)
    win._instance = instance  # keep the lock for the life of the window
    apply_theme(app, win.settings.value("theme", "system", str))
    QGuiApplication.styleHints().colorSchemeChanged.connect(
        lambda *_: apply_theme(app, win.settings.value("theme", "system", str)))
    win.show()
    if files:
        win.open_paths(files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
