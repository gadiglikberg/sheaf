"""End-to-end checks of the real window, run off-screen. Exercises the six key flows from the PRD."""
from __future__ import annotations

import os

import pymupdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from conftest import make_form, make_pdf  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    from sheaf.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    yield w
    for t in w.tabs:
        t.sdoc.dirty = False
    w.close()


def save_as(win, monkeypatch, path):
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    assert win.save()


def test_flow_merge(win, tmp_path, monkeypatch):
    a = make_pdf(tmp_path / "a.pdf", pages=2, text="A{n}")
    b = make_pdf(tmp_path / "b.pdf", pages=2, text="B{n}")
    win.combine([str(a), str(b)])
    tab = win.cur
    assert win.mode == "organize" and tab.sdoc.page_count == 4
    tab.move_pages([2, 3], 0)  # drag file b's pages to the front
    out = tmp_path / "merged.pdf"
    save_as(win, monkeypatch, out)
    texts = [p.get_text() for p in pymupdf.open(out)]
    assert "B1" in texts[0] and "A2" in texts[3]


def test_flow_fix_scan(win, tmp_path, monkeypatch):
    src = make_pdf(tmp_path / "scan.pdf", pages=3)
    win.open_paths([str(src)])
    win.set_mode("organize")
    tab = win.cur
    tab.grid.pageButton.emit("rotate_right", 0)
    tab.grid.pageButton.emit("delete", 2)
    out = tmp_path / "fixed.pdf"
    save_as(win, monkeypatch, out)
    doc = pymupdf.open(out)
    assert doc.page_count == 2 and doc[0].rotation == 90


def test_flow_fill_and_sign(win, tmp_path, monkeypatch):
    win.open_paths([str(make_form(tmp_path / "form.pdf"))])
    win.set_mode("fill")
    tab = win.cur
    c = tab.canvas
    pw = c.pages[0]
    field = c.widgets_for(0)[0]
    c.fill_widget(pw, field)
    c.editor.setText("Dana Levi")
    c.close_editor(True)
    from PySide6.QtGui import QImage
    img = QImage(60, 20, QImage.Format_ARGB32)
    img.fill(Qt.black)
    from sheaf.ui.dialogs import image_to_png
    win.state.signature, win.state.signature_aspect = image_to_png(img), 3.0
    win.set_tool("sign")
    c.handle_tool_release(pw, "sign", QPointF(300, 400), QPointF(300, 400), False, [])
    out = tmp_path / "signed.pdf"
    save_as(win, monkeypatch, out)
    doc = pymupdf.open(out)
    page = doc[0]
    assert {w.field_name: w.field_value for w in page.widgets()}["name"] == "Dana Levi"
    assert page.get_images()


def test_flow_copy_passage(win, tmp_path):
    win.open_paths([str(make_pdf(tmp_path / "t.pdf"))])
    c = win.cur.canvas
    pw = c.pages[0]
    s = c.scale
    c.set_selection(0, pymupdf.Page.get_text(c.sdoc.doc[0], "words")[:4])
    assert c.copy()
    assert QGuiApplication.clipboard().text() == "Page 1 Hello world"


def test_flow_add_text(win, tmp_path, monkeypatch):
    win.open_paths([str(make_pdf(tmp_path / "t.pdf"))])
    win.set_tool("text")
    assert win.mode == "edit"
    c = win.cur.canvas
    pw = c.pages[0]
    c.new_text_box(pw, QPointF(100, 300), None)
    c.editor.setPlainText("Approved\nby Dana")
    c.close_editor(True)
    out = tmp_path / "text.pdf"
    save_as(win, monkeypatch, out)
    assert "Approved" in pymupdf.open(out)[0].get_text()


def test_flow_unlock(win, tmp_path, monkeypatch):
    src = make_pdf(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="o")
    monkeypatch.setattr(win, "ask_password", lambda name, attempt: "pw")
    win.open_paths([str(src)])
    win.set_mode("protect")
    win.cur.remove_password()
    out = tmp_path / "unlocked.pdf"
    save_as(win, monkeypatch, out)
    assert not pymupdf.open(out).needs_pass


def test_original_not_overwritten_by_ctrl_s(win, tmp_path, monkeypatch):
    src = make_pdf(tmp_path / "orig.pdf")
    before = src.read_bytes()
    win.open_paths([str(src)])
    win.cur.sdoc.rotate([0], 90)
    asked = {}

    def fake(*a, **k):
        asked["default"] = a[2]
        return ("", "")
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake)
    assert not win.save()
    assert asked["default"].endswith("orig (edited).pdf")
    assert src.read_bytes() == before


def test_every_mode_and_tool_switches(win, tmp_path):
    win.open_paths([str(make_pdf(tmp_path / "t.pdf"))])
    from sheaf.ui.main_window import MODES, MODE_TOOLS
    for key, _ in MODES:
        win.set_mode(key)
        for tool in MODE_TOOLS[key]:
            if tool != "sign":
                win.set_tool(tool)
                assert win.state.tool == tool
    win.cur.canvas.set_zoom(2.0)
    win.cur.canvas.set_fit("page")
    win.focus_search()
    win.cur.search.box.setText("Hello")
    win.cur.search.run()
    assert len(win.cur.canvas.search_hits) == 3


def test_recovery_copy_written_and_removed(win, tmp_path, monkeypatch):
    win.open_paths([str(make_pdf(tmp_path / "t.pdf"))])
    win.cur.sdoc.rotate([0], 90)
    win.write_recovery()
    rec = list((tmp_path / "appdata" / "Sheaf" / "recovery").glob("*.pdf"))
    assert len(rec) == 1
    save_as(win, monkeypatch, tmp_path / "saved.pdf")
    assert not list((tmp_path / "appdata" / "Sheaf" / "recovery").glob("*.pdf"))
