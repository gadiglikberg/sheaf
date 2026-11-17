"""Dialogs. Plain language, sensible defaults, everything reachable from the keyboard."""
from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QRadioButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..core import fileio


def _buttons(dlg: QDialog, ok_text: str = "OK") -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText(ok_text)
    box.button(QDialogButtonBox.Ok).setDefault(True)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    return box


def hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("color: palette(placeholder-text);")
    return lab


# ---------------------------------------------------------------- passwords

def ask_open_password(parent, name: str, attempt: int) -> str | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Password needed")
    lay = QVBoxLayout(dlg)
    msg = f"<b>{_esc(name)}</b> is protected. Enter its password to open it."
    if attempt:
        msg = f"That password didn't work. Try again.<br>{msg}"
    lab = QLabel(msg)
    lab.setWordWrap(True)
    lay.addWidget(lab)
    pw = QLineEdit()
    pw.setEchoMode(QLineEdit.Password)
    pw.setAccessibleName("Password")
    lay.addWidget(pw)
    show = QCheckBox("Show password")
    show.toggled.connect(lambda on: pw.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
    lay.addWidget(show)
    lay.addWidget(_buttons(dlg, "Open"))
    pw.setFocus()
    return pw.text() if dlg.exec() == QDialog.Accepted else None


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SetPasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add a password")
        lay = QVBoxLayout(self)
        lay.addWidget(hint("Anyone opening the saved file will need this password. "
                           "There is no way to recover it if it's lost."))
        form = QFormLayout()
        self.pw1, self.pw2 = QLineEdit(), QLineEdit()
        for w in (self.pw1, self.pw2):
            w.setEchoMode(QLineEdit.Password)
        form.addRow("Password:", self.pw1)
        form.addRow("Type it again:", self.pw2)
        lay.addLayout(form)
        self.error = QLabel()
        self.error.setStyleSheet("color: #d03030;")
        lay.addWidget(self.error)
        self.box = _buttons(self, "Add password")
        lay.addWidget(self.box)
        for w in (self.pw1, self.pw2):
            w.textChanged.connect(self._check)
        self._check()

    def _check(self):
        a, b = self.pw1.text(), self.pw2.text()
        ok = len(a) >= 6 and a == b
        self.error.setText("" if ok or not a else
                           "Use at least 6 characters." if len(a) < 6 else "The passwords don't match.")
        self.box.button(QDialogButtonBox.Ok).setEnabled(ok)

    def password(self) -> str:
        return self.pw1.text()


# ---------------------------------------------------------------- pages

class ExtractDialog(QDialog):
    """Extract chosen pages to one file, or split into several."""

    def __init__(self, parent, page_count: int, selected: list[int], split: bool = False):
        super().__init__(parent)
        self.page_count = page_count
        self.setWindowTitle("Split document" if split else "Extract pages")
        lay = QVBoxLayout(self)
        self.mode_one = QRadioButton("Save these pages as one new file")
        self.mode_ranges = QRadioButton("Save each range as its own file")
        self.mode_every = QRadioButton("Split every")
        self.ranges = QLineEdit(_ranges_text(selected) if selected else f"1-{page_count}")
        self.ranges.setPlaceholderText("For example 1-3, 5, 8-")
        self.every = QSpinBox()
        self.every.setRange(1, max(1, page_count))
        self.every.setValue(1)
        self.every.setSuffix(" pages")
        lay.addWidget(QLabel(f"Pages (1 to {page_count}):"))
        lay.addWidget(self.ranges)
        lay.addWidget(self.mode_one)
        lay.addWidget(self.mode_ranges)
        row = QHBoxLayout()
        row.addWidget(self.mode_every)
        row.addWidget(self.every)
        row.addStretch()
        lay.addLayout(row)
        (self.mode_every if split else self.mode_one).setChecked(True)
        self.error = QLabel()
        self.error.setStyleSheet("color: #d03030;")
        lay.addWidget(self.error)
        lay.addWidget(_buttons(self, "Choose where to save…"))

    def accept(self):
        from ..core import ops
        try:
            if self.mode_every.isChecked():
                self.groups = ops.split_every(self.page_count, self.every.value())
            else:
                groups = ops.parse_ranges(self.ranges.text(), self.page_count)
                self.groups = [sum(groups, [])] if self.mode_one.isChecked() else groups
        except ValueError as e:
            self.error.setText(str(e))
            return
        super().accept()


def _ranges_text(pages: list[int]) -> str:
    pages = sorted(set(pages))
    out, start, prev = [], None, None
    for p in pages + [None]:
        if start is None:
            start = prev = p
        elif p is not None and p == prev + 1:
            prev = p
        else:
            out.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
            start = prev = p
    return ", ".join(out)


class CompressDialog(QDialog):
    def __init__(self, parent, current_size: int):
        super().__init__(parent)
        self.setWindowTitle("Compress")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Current size: <b>{human_size(current_size)}</b>"))
        self.group = QButtonGroup(self)
        for key, title, desc in [
            ("low", "Light", "No visible change. Cleans up the file structure and fonts."),
            ("medium", "Balanced", "Images reduced to 150 dpi. Good for email and reading on screen."),
            ("high", "Smallest", "Images reduced to 96 dpi. Fine on screen, not for printing."),
        ]:
            rb = QRadioButton(title)
            rb.setProperty("level", key)
            self.group.addButton(rb)
            lay.addWidget(rb)
            lay.addWidget(hint("      " + desc))
            if key == "medium":
                rb.setChecked(True)
        lay.addWidget(hint("You'll see the new size and can undo it."))
        lay.addWidget(_buttons(self, "Compress"))

    def level(self) -> str:
        return self.group.checkedButton().property("level")


def human_size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


class PageNumbersDialog(QDialog):
    def __init__(self, parent, page_count: int):
        super().__init__(parent)
        self.page_count = page_count
        self.setWindowTitle("Add page numbers")
        form = QFormLayout(self)
        self.fmt = QComboBox()
        self.fmt.setEditable(True)
        self.fmt.addItems(["{n}", "Page {n}", "Page {n} of {total}", "{n} / {total}"])
        self.position = QComboBox()
        for key, label in [("bottom-center", "Bottom center"), ("bottom-right", "Bottom right"),
                           ("bottom-left", "Bottom left"), ("top-center", "Top center"),
                           ("top-right", "Top right"), ("top-left", "Top left")]:
            self.position.addItem(label, key)
        self.size = QSpinBox()
        self.size.setRange(6, 36)
        self.size.setValue(10)
        self.start = QSpinBox()
        self.start.setRange(0, 99999)
        self.start.setValue(1)
        self.pages = QLineEdit(f"1-{page_count}")
        form.addRow("Format:", self.fmt)
        form.addRow("", hint("{n} is the page number, {total} the number of pages."))
        form.addRow("Position:", self.position)
        form.addRow("Size:", self.size)
        form.addRow("Start at:", self.start)
        form.addRow("On pages:", self.pages)
        self.error = QLabel()
        self.error.setStyleSheet("color: #d03030;")
        form.addRow(self.error)
        form.addRow(_buttons(self, "Add numbers"))

    def accept(self):
        from ..core import ops
        try:
            self.page_list = sum(ops.parse_ranges(self.pages.text(), self.page_count), [])
        except ValueError as e:
            self.error.setText(str(e))
            return
        super().accept()


class WatermarkDialog(QDialog):
    def __init__(self, parent, page_count: int):
        super().__init__(parent)
        self.page_count = page_count
        self.setWindowTitle("Add watermark")
        form = QFormLayout(self)
        self.text = QComboBox()
        self.text.setEditable(True)
        self.text.addItems(["DRAFT", "COPY", "CONFIDENTIAL", "SAMPLE"])
        self.diagonal = QCheckBox("Diagonal")
        self.diagonal.setChecked(True)
        self.opacity = QSpinBox()
        self.opacity.setRange(5, 100)
        self.opacity.setValue(15)
        self.opacity.setSuffix(" %")
        self.pages = QLineEdit(f"1-{page_count}")
        form.addRow("Text:", self.text)
        form.addRow("", self.diagonal)
        form.addRow("Strength:", self.opacity)
        form.addRow("On pages:", self.pages)
        self.error = QLabel()
        self.error.setStyleSheet("color: #d03030;")
        form.addRow(self.error)
        form.addRow(_buttons(self, "Add watermark"))

    def accept(self):
        from ..core import ops
        if not self.text.currentText().strip():
            self.error.setText("Enter the watermark text.")
            return
        try:
            self.page_list = sum(ops.parse_ranges(self.pages.text(), self.page_count), [])
        except ValueError as e:
            self.error.setText(str(e))
            return
        super().accept()


class ExportImagesDialog(QDialog):
    def __init__(self, parent, page_count: int, selected: list[int]):
        super().__init__(parent)
        self.page_count = page_count
        self.setWindowTitle("Export as images")
        form = QFormLayout(self)
        self.pages = QLineEdit(_ranges_text(selected) if selected else f"1-{page_count}")
        self.fmt = QComboBox()
        self.fmt.addItem("PNG (sharp, larger)", "png")
        self.fmt.addItem("JPG (smaller)", "jpg")
        self.dpi = QComboBox()
        for d in (72, 150, 300):
            self.dpi.addItem(f"{d} dpi" + (" (screen)" if d == 72 else " (print)" if d == 300 else ""), d)
        self.dpi.setCurrentIndex(1)
        form.addRow("Pages:", self.pages)
        form.addRow("Format:", self.fmt)
        form.addRow("Quality:", self.dpi)
        self.error = QLabel()
        self.error.setStyleSheet("color: #d03030;")
        form.addRow(self.error)
        form.addRow(_buttons(self, "Choose folder…"))

    def accept(self):
        from ..core import ops
        try:
            self.page_list = sum(ops.parse_ranges(self.pages.text(), self.page_count), [])
        except ValueError as e:
            self.error.setText(str(e))
            return
        super().accept()


class OcrDialog(QDialog):
    def __init__(self, parent, languages: list[str], scanned_pages: int):
        super().__init__(parent)
        self.setWindowTitle("Recognize text")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Sheaf found <b>{scanned_pages}</b> scanned page(s) without searchable text."))
        lay.addWidget(hint("Recognition runs on this computer. Pages look the same afterwards, "
                           "but their words can be searched and copied."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Language:"))
        self.lang = QComboBox()
        self.lang.addItems(languages)
        if "eng" in languages:
            self.lang.setCurrentText("eng")
        row.addWidget(self.lang, 1)
        lay.addLayout(row)
        lay.addWidget(_buttons(self, "Recognize"))


# ---------------------------------------------------------------- signatures

def signatures_dir() -> Path:
    d = fileio.app_data_dir() / "signatures"
    d.mkdir(exist_ok=True)
    return d


def image_to_png(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba.data())


def crop_to_content(img: QImage) -> QImage:
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    xs, ys = [], []
    step = 2
    for y in range(0, h, step):
        for x in range(0, w, step):
            if img.pixelColor(x, y).alpha() > 20:
                xs.append(x)
                ys.append(y)
    if not xs:
        return img
    pad = 6
    r = QRect(max(0, min(xs) - pad), max(0, min(ys) - pad), 0, 0)
    r.setRight(min(w - 1, max(xs) + pad))
    r.setBottom(min(h - 1, max(ys) + pad))
    return img.copy(r)


class DrawPad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(460, 170)
        self.strokes: list[list[QPointF]] = []
        self.setCursor(Qt.CrossCursor)
        self.setAccessibleName("Signature drawing area")

    def mousePressEvent(self, e):
        self.strokes.append([e.position()])

    def mouseMoveEvent(self, e):
        if self.strokes:
            self.strokes[-1].append(e.position())
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.white)
        p.setPen(QPen(QColor(200, 200, 200), 1, Qt.DashLine))
        p.drawLine(20, self.height() - 40, self.width() - 20, self.height() - 40)
        self._draw(p, QColor(20, 20, 60))
        if not self.strokes:
            p.setPen(QColor(150, 150, 150))
            p.drawText(self.rect(), Qt.AlignCenter, "Sign here with your mouse, pen or finger")

    def _draw(self, p: QPainter, color: QColor):
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(color, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for s in self.strokes:
            if len(s) > 1:
                path = QPainterPath(s[0])
                for pt in s[1:]:
                    path.lineTo(pt)
                p.drawPath(path)

    def image(self) -> QImage | None:
        if not any(len(s) > 1 for s in self.strokes):
            return None
        scale = 3
        img = QImage(self.width() * scale, self.height() * scale, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.scale(scale, scale)
        self._draw(p, QColor(20, 20, 60))
        p.end()
        return crop_to_content(img)

    def clear(self):
        self.strokes = []
        self.update()


class SignatureDialog(QDialog):
    """Pick a saved signature, or create one by drawing, typing or importing an image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Signatures")
        self.resize(560, 420)
        self.chosen: tuple[bytes, float] | None = None
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        saved = QWidget()
        sl = QVBoxLayout(saved)
        self.list = QListWidget()
        self.list.setIconSize(QSize(220, 70))
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        sl.addWidget(self.list)
        row = QHBoxLayout()
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete)
        row.addStretch()
        row.addWidget(delete)
        sl.addLayout(row)
        self.tabs.addTab(saved, "Saved")

        draw = QWidget()
        dl = QVBoxLayout(draw)
        self.pad = DrawPad()
        dl.addWidget(self.pad)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.pad.clear)
        dl.addWidget(clear, 0, Qt.AlignRight)
        self.tabs.addTab(draw, "Draw")

        typed = QWidget()
        tl = QVBoxLayout(typed)
        self.typed = QLineEdit()
        self.typed.setPlaceholderText("Type your name")
        self.preview = QLabel()
        self.preview.setMinimumHeight(110)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background: white; color: #14143c;")
        self.typed.textChanged.connect(self._update_typed)
        tl.addWidget(self.typed)
        tl.addWidget(self.preview)
        tl.addStretch()
        self.tabs.addTab(typed, "Type")

        imp = QWidget()
        il = QVBoxLayout(imp)
        il.addWidget(hint("Choose a photo or scan of your signature. A white background is made transparent."))
        pick = QPushButton("Choose image…")
        pick.clicked.connect(self._import)
        il.addWidget(pick, 0, Qt.AlignLeft)
        self.import_preview = QLabel()
        self.import_preview.setAlignment(Qt.AlignCenter)
        il.addWidget(self.import_preview, 1)
        self._imported: QImage | None = None
        self.tabs.addTab(imp, "Import")

        self.remember = QCheckBox("Save this signature on this computer for next time")
        self.remember.setChecked(True)
        lay.addWidget(self.remember)
        lay.addWidget(hint("Signatures are stored only in your user folder on this computer."))
        lay.addWidget(_buttons(self, "Use signature"))
        self._load_saved()
        if self.list.count() == 0:
            self.tabs.setCurrentIndex(1)

    def _script_font(self) -> QFont:
        fams = set(QFontDatabase.families())
        for name in ("Segoe Script", "Brush Script MT", "Lucida Handwriting", "Ink Free"):
            if name in fams:
                f = QFont(name)
                break
        else:
            f = QFont()
            f.setItalic(True)
        f.setPixelSize(54)
        return f

    def _typed_image(self) -> QImage | None:
        text = self.typed.text().strip()
        if not text:
            return None
        f = self._script_font()
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        img = QImage(fm.horizontalAdvance(text) * 3 + 60, fm.height() * 3 + 30, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(3, 3)
        p.setFont(f)
        p.setPen(QColor(20, 20, 60))
        p.drawText(10, fm.ascent() + 5, text)
        p.end()
        return crop_to_content(img)

    def _update_typed(self):
        img = self._typed_image()
        self.preview.setPixmap(QPixmap.fromImage(img).scaledToHeight(90, Qt.SmoothTransformation) if img else QPixmap())

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose signature image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            return
        img = img.convertToFormat(QImage.Format_ARGB32)
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.red() > 215 and c.green() > 215 and c.blue() > 215:
                    img.setPixelColor(x, y, QColor(0, 0, 0, 0))
        if img.width() > 1600:
            img = img.scaledToWidth(1600, Qt.SmoothTransformation)
        self._imported = crop_to_content(img)
        self.import_preview.setPixmap(QPixmap.fromImage(self._imported).scaled(
            440, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _load_saved(self):
        self.list.clear()
        for p in sorted(signatures_dir().glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
            pm = QPixmap(str(p))
            if pm.isNull():
                continue
            it = QListWidgetItem(pm.scaled(220, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation), "")
            it.setData(Qt.UserRole, str(p))
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _delete(self):
        it = self.list.currentItem()
        if it:
            Path(it.data(Qt.UserRole)).unlink(missing_ok=True)
            self._load_saved()

    def accept(self):
        tab = self.tabs.currentIndex()
        img = None
        if tab == 0:
            it = self.list.currentItem()
            if it:
                img = QImage(it.data(Qt.UserRole))
        elif tab == 1:
            img = self.pad.image()
        elif tab == 2:
            img = self._typed_image()
        else:
            img = self._imported
        if img is None or img.isNull():
            return
        data = image_to_png(img)
        if tab != 0 and self.remember.isChecked():
            (signatures_dir() / f"{uuid.uuid4().hex}.png").write_bytes(data)
        self.chosen = (data, img.width() / max(1, img.height()))
        super().accept()


# ---------------------------------------------------------------- command palette

class CommandPalette(QDialog):
    def __init__(self, parent, actions: list[QAction]):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("commandPalette")
        self.actions_ = [a for a in actions if a.text() and a.isVisible()]
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search commands")
        self.search.setAccessibleName("Search commands")
        lay.addWidget(self.search)
        self.list = QListWidget()
        lay.addWidget(self.list)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run)
        self.list.itemActivated.connect(lambda _: self._run())
        self.search.installEventFilter(self)
        self._filter("")

    def _filter(self, text: str):
        self.list.clear()
        words = text.lower().split()
        for a in self.actions_:
            name = a.text().replace("&", "").replace("…", "")
            hay = (name + " " + (a.toolTip() or "")).lower()
            if all(w in hay for w in words):
                sc = a.shortcut().toString(QKeySequence.NativeText)
                it = QListWidgetItem(f"{name}" + (f"    {sc}" if sc else ""))
                it.setData(Qt.UserRole, a)
                it.setFlags(it.flags() if a.isEnabled() else it.flags() & ~Qt.ItemIsEnabled)
                self.list.addItem(it)
        for i in range(self.list.count()):
            if self.list.item(i).flags() & Qt.ItemIsEnabled:
                self.list.setCurrentRow(i)
                break

    def eventFilter(self, obj, e):
        if obj is self.search and e.type() == e.Type.KeyPress and e.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self.list.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return True
        return super().eventFilter(obj, e)

    def _run(self):
        it = self.list.currentItem()
        if it and it.flags() & Qt.ItemIsEnabled:
            action = it.data(Qt.UserRole)
            self.accept()
            action.trigger()
