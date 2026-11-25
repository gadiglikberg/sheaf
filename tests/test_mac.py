"""The Mac-specific parts. Most run on any system; CI also runs the whole suite on macOS."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QFileOpenEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import make_pdf  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_settings_folder_on_a_mac(tmp_path, monkeypatch):
    from sheaf.core import fileio
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert fileio.app_data_dir() == tmp_path / "Library" / "Application Support" / "Sheaf"


def test_every_toolbar_icon_has_a_mac_symbol():
    from sheaf.ui import icons
    assert set(icons.GLYPHS) == set(icons.SF_SYMBOLS)


def test_files_from_finder_open_in_the_window(qapp, tmp_path, monkeypatch):
    """Finder sends files as FileOpen events, both before the window exists and after."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
    from sheaf.app import FinderFiles
    from sheaf.ui.main_window import MainWindow
    finder = FinderFiles()
    qapp.installEventFilter(finder)
    try:
        first, second = make_pdf(tmp_path / "first.pdf"), make_pdf(tmp_path / "second.pdf")
        QApplication.sendEvent(qapp, QFileOpenEvent(str(first)))
        assert finder.waiting == [str(first)]  # the launch file waits for the window
        win = MainWindow()
        finder.window = win
        win.open_paths(finder.waiting)
        QApplication.sendEvent(qapp, QFileOpenEvent(str(second)))
        assert [Path(t.sdoc.path).name for t in win.tabs] == ["first.pdf", "second.pdf"]
        win.close()
    finally:
        qapp.removeEventFilter(finder)
