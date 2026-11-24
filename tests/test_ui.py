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
    assert win.state.tool == "fill"  # back to filling, with the new signature selected so it can be moved
    assert c.selected_annot and c.is_signature(*c.selected_annot)
    out = tmp_path / "signed.pdf"
    save_as(win, monkeypatch, out)
    doc = pymupdf.open(out)
    page = doc[0]
    assert {w.field_name: w.field_value for w in page.widgets()}["name"] == "Dana Levi"
    from sheaf.core import ops
    assert [a for a in page.annots() if ops.is_signature(a)]


def _signed_doc(win, tmp_path, rotation=0):
    from PySide6.QtGui import QImage
    from sheaf.ui.dialogs import image_to_png
    src = make_pdf(tmp_path / f"r{rotation}.pdf")
    d = pymupdf.open(src)
    d[0].set_rotation(rotation)
    d.save(tmp_path / f"rot{rotation}.pdf")
    win.open_paths([str(tmp_path / f"rot{rotation}.pdf")])
    img = QImage(300, 100, QImage.Format_ARGB32)
    img.fill(Qt.black)
    win.state.signature, win.state.signature_aspect = image_to_png(img), 3.0
    win.set_mode("fill")
    win.set_tool("sign")
    c = win.cur.canvas
    c.handle_tool_release(c.pages[0], "sign", QPointF(200, 200), QPointF(200, 200), False, [])
    return c


def test_signature_upright_on_rotated_page(win, tmp_path):
    c = _signed_doc(win, tmp_path, rotation=90)
    page, xref = c.selected_annot
    pg = c.sdoc.doc[page]
    r = pg.load_annot(xref).rect
    assert r.height > r.width * 2  # a wide signature, stored turned so it reads upright on the 90-degree page


def test_signature_can_be_moved_and_resized(win, tmp_path):
    from sheaf.core import ops
    c = _signed_doc(win, tmp_path)
    page, xref = c.selected_annot
    pg = c.sdoc.doc[page]
    r = pymupdf.Rect(pg.load_annot(xref).rect)
    bigger = pymupdf.Rect(r.x0 + 50, r.y0 + 80, r.x0 + 50 + r.width * 1.5, r.y0 + 80 + r.height * 1.5)
    c.sdoc.edit("Move", lambda d: ops.move_annot(d[page], xref, bigger))
    pg = c.sdoc.doc[page]
    a = pg.load_annot(xref)
    assert abs(a.rect.x0 - bigger.x0) < 1 and abs(a.rect.width - bigger.width) < 1
    pix = c.sdoc.doc[page].get_pixmap(clip=bigger)
    assert min(pix.samples) < 50  # the signature's ink is drawn at the new place


def test_escape_cancels_signing(win, tmp_path):
    from PySide6.QtGui import QImage
    from sheaf.ui.dialogs import image_to_png
    win.open_paths([str(make_pdf(tmp_path / "a.pdf"))])
    img = QImage(30, 10, QImage.Format_ARGB32)
    img.fill(Qt.black)
    win.state.signature = image_to_png(img)
    win.set_mode("fill")
    win.set_tool("sign")
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    win.cur.canvas.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert win.state.tool == "fill"


def test_tabbing_through_fields_changes_nothing(win, tmp_path, monkeypatch):
    """Moving through a form with Tab must not tick checkboxes or pick drop-down options by itself."""
    win.open_paths([str(make_form(tmp_path / "form.pdf"))])
    win.set_mode("fill")
    c = win.cur.canvas
    for _ in range(4):
        c.next_field()
    c.close_editor(True)
    assert not win.cur.sdoc.dirty
    c.next_field()  # back to a field; find the checkbox and tick it with Space
    while c._editor_field[1] != c.widgets_for(0)[1][0]:
        c.next_field()
    c.editor.setChecked(True)  # what Space does
    c.close_editor(True)
    out = tmp_path / "ticked.pdf"
    save_as(win, monkeypatch, out)
    values = {w.field_name: w.field_value for w in pymupdf.open(out)[0].widgets()}
    assert values["agree"] not in (False, "Off", "", None)


def test_long_file_name_is_shortened(win, tmp_path):
    long = make_pdf(tmp_path / ("A" * 150 + ".pdf"))
    win.open_paths([str(long)])
    assert len(win.windowTitle()) < 90 and win.windowTitle().endswith("Sheaf")
    assert not win.tabbar.isVisible()  # one document: no tab strip
    win.open_paths([str(make_pdf(tmp_path / "b.pdf"))])
    assert win.tabbar.isVisible() and len(win.tabbar.tabText(0)) < 60


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
