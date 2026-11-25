"""One open document: sidebar, canvas or Organize grid, search and comments, plus its actions."""
from __future__ import annotations

import os
from pathlib import Path

import pymupdf
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressDialog, QPushButton, QSplitter,
                               QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from ..core import fileio, ops
from ..osinfo import IS_MAC, keys
from ..core.document import OpenCancelled, OpenFailed, SheafDocument
from . import dialogs
from .canvas import Canvas, ToolState
from .thumbs import ThumbList

PDF_FILTER = "PDF files (*.pdf)"
INSERT_FILTER = "PDF and image files (*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)"


class SearchPanel(QWidget):
    def __init__(self, tab: "DocumentTab"):
        super().__init__()
        self.tab = tab
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.box = QLineEdit()
        self.box.setPlaceholderText("Find in document")
        self.box.setClearButtonEnabled(True)
        self.box.setAccessibleName("Find in document")
        lay.addWidget(self.box)
        row = QHBoxLayout()
        self.count = QLabel("")
        prev_b, next_b = QToolButton(), QToolButton()
        prev_b.setText("↑")
        next_b.setText("↓")
        prev_b.setToolTip(f"Previous match ({keys('Shift+F3')})")
        next_b.setToolTip(f"Next match ({keys('F3')})")
        prev_b.clicked.connect(lambda: self.step(-1))
        next_b.clicked.connect(lambda: self.step(1))
        row.addWidget(self.count, 1)
        row.addWidget(prev_b)
        row.addWidget(next_b)
        lay.addLayout(row)
        self.results = QListWidget()
        self.results.setWordWrap(True)
        lay.addWidget(self.results, 1)
        self.box.returnPressed.connect(self.run_or_next)
        self.box.textChanged.connect(lambda: self._debounce.start(300))
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.run)
        self.results.currentRowChanged.connect(self.show_hit)
        self._last = None

    def run_or_next(self):
        if self._last == self.box.text() and self.tab.canvas.search_hits:
            self.step(1)
        else:
            self.run()

    def run(self):
        text = self.box.text()
        self._last = text
        c = self.tab.canvas
        hits = ops.search(self.tab.sdoc.doc, text) if len(text.strip()) >= 2 else []
        c.search_hits, c.search_index = hits, -1
        self.results.blockSignals(True)
        self.results.clear()
        for pno, r in hits[:500]:
            snippet = self.tab.sdoc.doc[pno].get_textbox(r + (-120, -2, 120, 2)).replace("\n", " ").strip()
            self.results.addItem(QListWidgetItem(f"Page {pno + 1}: …{snippet}…"))
        self.results.blockSignals(False)
        self.count.setText(f"{len(hits)} match{'es' if len(hits) != 1 else ''}" if text.strip() else "")
        if hits:
            self.results.setCurrentRow(0)
        for w in c.pages:
            w.update()

    def step(self, d: int):
        c = self.tab.canvas
        if not c.search_hits:
            return
        self.results.setCurrentRow((max(c.search_index, 0 if d > 0 else 1) + d) % len(c.search_hits)
                                   if c.search_index >= 0 else 0)

    def show_hit(self, row: int):
        c = self.tab.canvas
        if 0 <= row < len(c.search_hits):
            c.search_index = row
            pno, r = c.search_hits[row]
            c.go_to(pno, r)
            for w in c.pages:
                w.update()


class CommentsPanel(QWidget):
    def __init__(self, tab: "DocumentTab"):
        super().__init__()
        self.tab = tab
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        title = QLabel("Comments")
        title.setStyleSheet("font-weight: 600;")
        lay.addWidget(title)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setAccessibleName("Comments and annotations")
        lay.addWidget(self.list, 1)
        self.empty = QLabel("No comments yet. Use Annotate to highlight text or add notes.")
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.empty)
        delete = QPushButton("Delete")
        delete.clicked.connect(self.delete_current)
        lay.addWidget(delete, 0, Qt.AlignRight)
        self.list.currentRowChanged.connect(self.go)
        self.items: list[dict] = []

    def refresh(self):
        self.items = ops.comments(self.tab.sdoc.doc)
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.items:
            text = c["text"] or ""
            self.list.addItem(f"Page {c['page'] + 1} · {c['kind']}" + (f"\n{text[:140]}" if text else ""))
        self.list.blockSignals(False)
        self.empty.setVisible(not self.items)

    def go(self, row: int):
        if 0 <= row < len(self.items):
            c = self.items[row]
            self.tab.canvas.go_to(c["page"], pymupdf.Rect(c["rect"]))
            self.tab.canvas.select_annot(c["page"], c["xref"])

    def delete_current(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.items):
            c = self.items[row]
            self.tab.canvas.select_annot(c["page"], c["xref"])
            self.tab.canvas.delete_selected_annot()


class DocumentTab(QWidget):
    titleChanged = Signal()
    message = Signal(str)
    pageChanged = Signal(int, int)

    def __init__(self, sdoc: SheafDocument, state: ToolState):
        super().__init__()
        self.sdoc = sdoc
        self.state = state
        self.recovery_id: str | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Horizontal)
        lay.addWidget(self.splitter)

        self.sidebar = QTabWidget()
        self.sidebar.setDocumentMode(True)
        self.thumbs = ThumbList(sdoc, grid=False)
        self.search = SearchPanel(self)
        self.sidebar.addTab(self.thumbs, "Pages")
        self.sidebar.addTab(self.search, "Search")
        self.sidebar.setMinimumWidth(150)

        self.center = QStackedWidget()
        self.canvas = Canvas(sdoc, state)
        self.grid = ThumbList(sdoc, grid=True)
        self.center.addWidget(self.canvas)
        self.center.addWidget(self.grid)

        self.comments = CommentsPanel(self)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.center)
        self.splitter.addWidget(self.comments)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([180, 900, 240])
        self.comments.hide()

        self.thumbs.pageActivated.connect(lambda p: self.canvas.go_to(p))
        for lst in (self.thumbs, self.grid):
            lst.pagesMoved.connect(self.move_pages)
            lst.filesDropped.connect(self.insert_paths)
        self.grid.pageActivated.connect(self._grid_open)
        self.grid.itemDoubleClicked.connect(lambda it: self.show_pages_view(it.data(Qt.UserRole + 1)))
        self.grid.pageButton.connect(self._grid_button)
        self.canvas.currentPageChanged.connect(self._page_changed)
        self.canvas.message.connect(self._canvas_message)
        self.canvas.needSignature.connect(lambda: self.window().choose_signature())
        sdoc.listeners.append(self._doc_changed)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh_light)
        self.comments.refresh()

    # ------------------------------------------------------------ state

    @property
    def title(self) -> str:
        return ("● " if self.sdoc.dirty else "") + self.sdoc.title

    def _canvas_message(self, text: str):
        if text.startswith("search:"):
            self.sidebar.setCurrentWidget(self.search)
            self.search.box.setText(text[7:])
            self.search.run()
        else:
            self.message.emit(text)

    def _page_changed(self, p: int):
        self.thumbs.set_current(p)
        self.pageChanged.emit(p, self.sdoc.page_count)

    def _doc_changed(self, what: str):
        if what == "structure":
            self.canvas.rebuild()
            self.thumbs.rebuild()
            self.grid.rebuild()
            self.comments.refresh()
        elif what == "content":
            self.canvas.refresh()
            self._refresh_timer.start(150)
        self.titleChanged.emit()

    def _refresh_light(self):
        cur = self.canvas.current_page()
        near = [p for p in range(cur - 2, cur + 3) if 0 <= p < self.sdoc.page_count]
        self.thumbs.refresh_icons(near)
        self.grid.refresh_icons(near)
        QTimer.singleShot(400, lambda: (self.thumbs.refresh_icons(), self.grid.refresh_icons()))
        self.comments.refresh()

    def set_organize(self, on: bool):
        self.center.setCurrentWidget(self.grid if on else self.canvas)
        self.sidebar.setVisible(not on and self.window().sidebar_visible if self.window() else not on)
        if on:
            self.grid.setFocus()
            self.grid.select_pages([self.canvas.current_page()])

    def show_pages_view(self, page: int):
        self.window().set_mode("view")
        QTimer.singleShot(0, lambda: self.canvas.go_to(page))

    def _grid_open(self, page: int):
        pass  # single click selects; double click opens the page

    def _grid_button(self, key: str, page: int):
        if key == "rotate_left":
            self.sdoc.rotate([page], -90)
        elif key == "rotate_right":
            self.sdoc.rotate([page], 90)
        elif key == "delete":
            self.delete_pages([page])

    def selected_pages(self) -> list[int]:
        if self.center.currentWidget() is self.grid:
            sel = self.grid.selected_pages()
        elif self.thumbs.hasFocus() and self.thumbs.selected_pages():
            sel = self.thumbs.selected_pages()
        else:
            sel = []
        return sel or [self.canvas.current_page()]

    # ------------------------------------------------------------ page actions

    def _try(self, fn, *args):
        try:
            return fn(*args)
        except (ValueError, OpenFailed) as e:
            QMessageBox.warning(self, "Sheaf", str(e))
        except OpenCancelled:
            pass
        return None

    def rotate(self, delta: int):
        pages = self.selected_pages()
        self.sdoc.rotate(pages, delta)
        self.grid.select_pages(pages)
        self.message.emit(f"Rotated {len(pages)} page{'s' if len(pages) > 1 else ''}")

    def delete_pages(self, pages: list[int] | None = None):
        pages = pages or self.selected_pages()
        try:
            self.sdoc.delete(pages)
        except ValueError as e:
            QMessageBox.warning(self, "Sheaf", str(e))
            return
        self.message.emit(f"Deleted {len(pages)} page{'s' if len(pages) > 1 else ''}. {keys('Ctrl+Z')} brings "
                          f"{'them' if len(pages) > 1 else 'it'} back.")

    def move_pages(self, pages: list[int], to: int):
        new_positions = self.sdoc.move_pages(pages, to)
        self.grid.select_pages(new_positions)
        self.thumbs.select_pages(new_positions)

    def insert_paths(self, paths: list[str], at: int):
        added = 0
        ask = lambda name, attempt: dialogs.ask_open_password(self, name, attempt)
        for path in paths:
            n = self._try(self.sdoc.insert_file, path, at, ask)
            if n:
                at += n
                added += n
        if added:
            self.message.emit(f"Inserted {added} page{'s' if added > 1 else ''}")

    def insert_files_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Insert files", self._folder(), INSERT_FILTER)
        if paths:
            sel = self.selected_pages()
            self.insert_paths(paths, (max(sel) + 1) if sel else self.sdoc.page_count)

    def insert_blank(self):
        sel = self.selected_pages()
        at = (max(sel) + 1) if sel else self.sdoc.page_count
        self.sdoc.insert_blank(at)
        self.grid.select_pages([at])

    def _folder(self) -> str:
        p = self.sdoc.save_path or self.sdoc.path
        return str(Path(p).parent) if p else str(Path.home() / "Documents")

    def _stem(self) -> str:
        return Path(self.sdoc.title).stem

    def extract(self, split: bool = False):
        dlg = dialogs.ExtractDialog(self, self.sdoc.page_count,
                                    [] if split else self.selected_pages(), split=split)
        if dlg.exec() != dlg.Accepted:
            return
        groups = dlg.groups
        if len(groups) == 1:
            default = os.path.join(self._folder(), f"{self._stem()} (pages {dialogs._ranges_text(groups[0])}).pdf")
            path, _ = QFileDialog.getSaveFileName(self, "Save extracted pages", default, PDF_FILTER)
            if not path:
                return
            if self._is_open_original(path):
                return
            fileio.atomic_write(path, self.sdoc.extract(groups[0]))
            self.message.emit(f"Saved {Path(path).name}")
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the new files", self._folder())
        if not folder:
            return
        width = len(str(len(groups)))
        for k, pages in enumerate(groups, 1):
            path = os.path.join(folder, f"{self._stem()} part {k:0{width}d}.pdf")
            if self._is_open_original(path):
                return
            fileio.atomic_write(path, self.sdoc.extract(pages))
        self.message.emit(f"Saved {len(groups)} files in {folder}")

    def _is_open_original(self, path: str) -> bool:
        if fileio.same_file(path, self.sdoc.path) or fileio.same_file(path, self.sdoc.save_path):
            QMessageBox.warning(self, "Sheaf", "Pick a different name so the open document isn't overwritten.")
            return True
        return False

    def page_numbers(self):
        dlg = dialogs.PageNumbersDialog(self, self.sdoc.page_count)
        if dlg.exec() == dlg.Accepted:
            pages, fmt, pos = dlg.page_list, dlg.fmt.currentText(), dlg.position.currentData()
            size, start = dlg.size.value(), dlg.start.value()
            self.sdoc.edit("Page numbers", lambda d: ops.add_page_numbers(d, pages, fmt, pos, size, start))

    def watermark(self):
        dlg = dialogs.WatermarkDialog(self, self.sdoc.page_count)
        if dlg.exec() == dlg.Accepted:
            text, pages = dlg.text.currentText().strip(), dlg.page_list
            opacity, diag = dlg.opacity.value() / 100, dlg.diagonal.isChecked()
            self.sdoc.edit("Watermark", lambda d: ops.add_watermark(d, pages, text, opacity=opacity, diagonal=diag))

    def compress(self):
        before = len(self.sdoc.save_bytes())
        dlg = dialogs.CompressDialog(self, before)
        if dlg.exec() != dlg.Accepted:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            small = ops.compress(self.sdoc.doc, dlg.level())
            self.sdoc.replace_with("Compress", small)
            after = len(self.sdoc.save_bytes())
        finally:
            QApplication.restoreOverrideCursor()
        saved = max(0, before - after)
        QMessageBox.information(
            self, "Compress",
            f"{dialogs.human_size(before)} → {dialogs.human_size(after)}"
            + (f"  ({saved * 100 // max(before, 1)}% smaller)" if saved else
               "\n\nThis file was already as small as it can get at this setting.")
            + f"\n\nSave the document to keep the smaller file. {keys('Ctrl+Z')} undoes it.")

    def ocr(self):
        langs = ops.ocr_languages()
        if not langs:
            QMessageBox.information(
                self, "Recognize text",
                "Text recognition needs the free Tesseract OCR engine installed on this computer.\n\n"
                + ("Install it with Homebrew (brew install tesseract), then try again. " if IS_MAC else
                   "Install it from the official Tesseract project, then try again. ")
                + "Sheaf still works offline: recognition runs entirely on this computer.")
            return
        scanned = [p.number for p in self.sdoc.doc if ops.page_needs_ocr(p)]
        if not scanned:
            QMessageBox.information(self, "Recognize text", "Every page already has searchable text.")
            return
        dlg = dialogs.OcrDialog(self, langs, len(scanned))
        if dlg.exec() != dlg.Accepted:
            return
        lang = dlg.lang.currentText()
        prog = QProgressDialog("Recognizing text…", "Cancel", 0, len(scanned), self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)

        def progress(i, n):
            prog.setValue(i)
            prog.setLabelText(f"Recognizing page {min(i + 1, n)} of {n}…")
            QApplication.processEvents()
            return not prog.wasCanceled()
        try:
            done = self.sdoc.edit("Recognize text", lambda d: ops.ocr_pages(d, scanned, lang, progress))
        except Exception as e:
            QMessageBox.warning(self, "Recognize text", f"Recognition failed: {e}")
            return
        finally:
            prog.close()
        self.message.emit(f"Recognized text on {done} page{'s' if done != 1 else ''}")

    def export_images(self):
        dlg = dialogs.ExportImagesDialog(self, self.sdoc.page_count,
                                         self.grid.selected_pages() if self.center.currentWidget() is self.grid else [])
        if dlg.exec() != dlg.Accepted:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the images", self._folder())
        if not folder:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            paths = ops.export_images(self.sdoc.doc, dlg.page_list, folder, self._stem(),
                                      dlg.fmt.currentData(), dlg.dpi.currentData())
        finally:
            QApplication.restoreOverrideCursor()
        self.message.emit(f"Saved {len(paths)} image{'s' if len(paths) != 1 else ''} in {folder}")

    # ------------------------------------------------------------ protect

    def add_password(self):
        dlg = dialogs.SetPasswordDialog(self)
        if dlg.exec() == dlg.Accepted:
            self.sdoc.set_password(dlg.password())
            self.message.emit("Password added. It takes effect when you save.")

    def remove_password(self):
        if not self.sdoc.protection:
            self.message.emit("This document has no password.")
            return
        if not self.sdoc.protection.user_pw and QMessageBox.question(
                self, "Remove restrictions",
                "This file opens without a password, but its author restricted what can be done with it "
                "(for example printing or copying).\n\nRemove these restrictions only if you have the right to.",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
            return
        self.sdoc.remove_password()
        self.message.emit("Password removed. Save to write an unprotected copy.")

    def apply_redactions(self):
        n = ops.pending_redactions(self.sdoc.doc)
        if not n:
            QMessageBox.information(self, "Apply redactions",
                                    "Nothing is marked yet. Choose Mark for redaction and drag over what to remove.")
            return
        box = QMessageBox(QMessageBox.Warning, "Apply redactions",
                          f"Permanently remove everything under {n} marked area{'s' if n > 1 else ''}?", parent=self)
        box.setInformativeText("Text, images and comments there are deleted, not just covered. "
                               "You can undo until you save.")
        from PySide6.QtWidgets import QCheckBox
        hidden = QCheckBox("Also remove hidden information (properties, bookmarks, attachments, scripts)")
        hidden.setChecked(True)
        box.setCheckBox(hidden)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText("Remove permanently")
        if box.exec() != QMessageBox.Yes:
            return
        scrub = hidden.isChecked()

        def fn(d):
            ops.apply_redactions(d)
            if scrub:
                ops.remove_hidden_data(d)
        self.sdoc.edit("Apply redactions", fn)
        self.message.emit("Redactions applied. Save to make them permanent in the file.")

    # ------------------------------------------------------------ print

    def print_document(self):
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(self.sdoc.title)
        printer.setFromTo(1, self.sdoc.page_count)
        dlg = QPrintDialog(printer, self)
        dlg.setMinMax(1, self.sdoc.page_count)
        if dlg.exec() != QPrintDialog.Accepted:
            return
        first = max(1, printer.fromPage() or 1) - 1
        last = (printer.toPage() or self.sdoc.page_count) - 1
        dpi = min(printer.resolution(), 300)
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "Print", "The printer couldn't be started.")
            return
        try:
            for k, pno in enumerate(range(first, last + 1)):
                if k:
                    printer.newPage()
                pix = self.sdoc.doc[pno].get_pixmap(dpi=dpi, alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                area = painter.viewport()
                size = img.size().scaled(area.size(), Qt.KeepAspectRatio)
                painter.setViewport(area.x(), area.y(), size.width(), size.height())
                painter.setWindow(img.rect())
                painter.drawImage(0, 0, img)
                painter.setViewport(area)
        finally:
            painter.end()
