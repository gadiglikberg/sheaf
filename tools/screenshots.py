"""Render screenshots of every main screen for usability review and the README.

Uses generated sample documents only. Run:  python tools/screenshots.py OUTPUT_FOLDER [--dark] [--scale 2]
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--dark", action="store_true")
ap.add_argument("--scale", default="1")
ap.add_argument("--size", default="1366x768")
args = ap.parse_args()
os.environ["QT_SCALE_FACTOR"] = args.scale
tmp = Path(tempfile.mkdtemp(prefix="sheaf-shots-"))
os.environ["LOCALAPPDATA"] = str(tmp / "appdata")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pymupdf  # noqa: E402
from PySide6.QtCore import QPointF, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp / "settings"))

LOREM = ("This agreement is made between the parties named below. The tenant agrees to pay rent on the first day "
         "of each month and to keep the property in good condition. Either party may end this agreement with "
         "sixty days written notice. Any changes must be agreed in writing and signed by both parties.")


def sample_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    for n in range(1, 7):
        page = doc.new_page()
        page.insert_text((72, 80), f"Sample Rental Agreement — page {n}", fontsize=18, fontname="hebo")
        page.insert_textbox(pymupdf.Rect(72, 110, 523, 400), (LOREM + " ") * 3, fontsize=11, fontname="tiro")
        if n == 1:
            page.insert_text((72, 470), "Tenant name:", fontsize=11)
            w = pymupdf.Widget()
            w.field_name, w.field_type = "tenant", pymupdf.PDF_WIDGET_TYPE_TEXT
            w.rect = pymupdf.Rect(160, 456, 400, 476)
            page.add_widget(w)
            page.insert_text((72, 510), "I agree to the terms:", fontsize=11)
            c = pymupdf.Widget()
            c.field_name, c.field_type = "agree", pymupdf.PDF_WIDGET_TYPE_CHECKBOX
            c.rect = pymupdf.Rect(200, 498, 214, 512)
            page.add_widget(c)
    doc.save(path)
    return path


app = QApplication([])
from sheaf.ui.main_window import MainWindow  # noqa: E402
from sheaf.ui.theme import apply_theme  # noqa: E402
from sheaf.core import ops  # noqa: E402

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
w, h = (int(x) for x in args.size.split("x"))
win = MainWindow()
win.setAttribute(Qt.WA_DontShowOnScreen)
apply_theme(app, "dark" if args.dark else "light")
win.resize(w, h)
win.show()
suffix = ("-dark" if args.dark else "") + (f"-x{args.scale}" if args.scale != "1" else "")


def shot(name):
    for _ in range(5):
        app.processEvents()
    win.grab().save(str(out / f"{name}{suffix}.png"))


win.add_recent(str(tmp / "Quarterly report.pdf"))
win.start.refresh(win.recent())
shot("01-start")
src = sample_pdf(tmp / "Rental agreement.pdf")
other = sample_pdf(tmp / "Appendix.pdf")
win.open_paths([str(src)])
tab = win.cur
c = tab.canvas
shot("02-view")
words = c.sdoc.doc[0].get_text("words")[8:30]
c.set_selection(0, words)
shot("03-select-text")
c.clear_selection()
win.set_mode("edit")
win.set_tool("text")
c.new_text_box(c.pages[0], QPointF(110 * c.scale, 430 * c.scale), None)
c.editor.setPlainText("Approved, pending signature")
shot("04-edit-text-box")
c.close_editor(True)
win.set_mode("annotate")
page_words = c.sdoc.doc[0].get_text("words")
c.set_selection(0, page_words[12:24])
c.markup_selection("highlight")
tab.sdoc.edit("note", lambda d: ops.add_note(d[0], pymupdf.Point(500, 140), "Check the notice period"))
tab.sdoc.edit("arrow", lambda d: ops.add_arrow(d[0], pymupdf.Point(420, 560), pymupdf.Point(330, 480), (0.85, 0.1, 0.1)))
win.a_comments.setChecked(True)
win.toggle_comments()
shot("05-annotate")
win.a_comments.setChecked(False)
win.toggle_comments()
win.set_mode("fill")
c.fill_widget(c.pages[0], c.widgets_for(0)[0])
c.editor.setText("Dana Levi")
shot("06-fill")
c.close_editor(True)
tab.insert_paths([str(other)], 6)
win.set_mode("organize")
tab.grid.select_pages([1, 2])
shot("07-organize")
win.set_mode("protect")
tab.sdoc.edit("mark", lambda d: ops.mark_redaction(d[0], pymupdf.Rect(72, 125, 400, 160)))
shot("08-protect")
win.set_mode("view")
from sheaf.ui.dialogs import CommandPalette  # noqa: E402
pal = CommandPalette(win, [a for a in win.actions() if a.text()])
pal.search.setText("rot")
pal.resize(560, 300)
pal.show()
for _ in range(5):
    app.processEvents()
pal.grab().save(str(out / f"09-palette{suffix}.png"))
pal.close()
win.resize(1024, 640)
shot("10-small-window")
for t in win.tabs:
    t.sdoc.dirty = False
win.close()
print("saved to", out)
