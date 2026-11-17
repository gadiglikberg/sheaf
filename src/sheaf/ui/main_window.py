"""Main window: document tabs, mode bar, context bar, menus, start screen and status bar."""
from __future__ import annotations

import json
import os
import uuid
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QPushButton, QSizePolicy, QStackedWidget, QStatusBar, QTabBar,
                               QToolButton, QVBoxLayout, QWidget)

from .. import __version__
from ..core import fileio, ops
from ..core.document import IMAGE_SUFFIXES, OpenCancelled, OpenFailed, SheafDocument
from . import dialogs
from .canvas import TOOL_LABELS, ToolState
from .tab import INSERT_FILTER, PDF_FILTER, DocumentTab

MODES = [("view", "View"), ("edit", "Edit"), ("annotate", "Annotate"), ("fill", "Fill & Sign"),
         ("organize", "Organize"), ("protect", "Protect")]
MODE_TOOLS = {
    "view": [],
    "edit": ["select", "text", "edit_text"],
    "annotate": ["select", "highlight", "underline", "strikeout", "note", "rect", "arrow", "ink"],
    "fill": ["fill", "text", "sign", "check", "cross", "date", "initials"],
    "organize": [],
    "protect": ["select", "redact"],
}
DEFAULT_TOOL = {"view": "select", "edit": "select", "annotate": "highlight", "fill": "fill",
                "organize": "select", "protect": "redact"}
TOOL_KEYS = {"select": "V", "text": "T", "edit_text": "E", "highlight": "H", "underline": "U",
             "strikeout": "K", "note": "N", "rect": "R", "arrow": "A", "ink": "D", "sign": "S",
             "redact": "X"}
TOOL_TIPS = {
    "select": "Select text and objects. Drag to select text, click a comment or text box to move it.",
    "text": "Click anywhere on the page and type. Drag to make a box of a set width.",
    "edit_text": "Click a line of existing text to change its words.",
    "highlight": "Drag across text to highlight it.",
    "underline": "Drag across text to underline it.",
    "strikeout": "Drag across text to strike it out.",
    "note": "Click to add a sticky note.",
    "rect": "Drag to draw a box.",
    "arrow": "Drag to draw an arrow.",
    "ink": "Draw freehand.",
    "fill": "Click a form field to fill it. Tab moves to the next field. Click elsewhere to type on flat forms.",
    "sign": "Click where your signature should go.",
    "check": "Click to place a check mark.",
    "cross": "Click to place a cross.",
    "date": "Click to place today's date.",
    "initials": "Click to place your initials.",
    "redact": "Drag over anything to remove, or click a word. Then Apply redactions.",
}
MAX_RECENT = 12


def color_icon(rgb, size=16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor.fromRgbF(*rgb))
    p.setPen(QColor(0, 0, 0, 90))
    p.drawRoundedRect(1, 1, size - 2, size - 2, 4, 4)
    p.end()
    return QIcon(pm)


class StartScreen(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.setAcceptDrops(True)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        card = QFrame()
        card.setObjectName("startCard")
        card.setMaximumWidth(620)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 32, 36, 32)
        lay.setSpacing(12)
        title = QLabel("Sheaf")
        title.setObjectName("startTitle")
        lay.addWidget(title)
        lay.addWidget(QLabel("Edit, sign and organize PDFs. Files never leave this computer."))
        drop = QPushButton("Open a PDF…\n\nor drop files here")
        drop.setObjectName("dropZone")
        drop.setMinimumHeight(150)
        drop.clicked.connect(win.open_dialog)
        drop.setAccessibleName("Open a PDF, or drop files here")
        lay.addWidget(drop)
        row = QHBoxLayout()
        combine = QPushButton("Combine files…")
        combine.clicked.connect(win.combine_dialog)
        row.addWidget(combine)
        row.addStretch()
        lay.addLayout(row)
        head = QHBoxLayout()
        rl = QLabel("Recent files")
        rl.setStyleSheet("font-weight: 600; margin-top: 8px;")
        head.addWidget(rl)
        head.addStretch()
        self.clear_btn = QPushButton("Clear list")
        self.clear_btn.setFlat(True)
        self.clear_btn.clicked.connect(win.clear_recent)
        head.addWidget(self.clear_btn)
        lay.addLayout(head)
        self.recent = QListWidget()
        self.recent.setAccessibleName("Recent files")
        self.recent.itemActivated.connect(lambda it: win.open_paths([it.data(Qt.UserRole)]))
        self.recent.setMaximumHeight(220)
        self.recent.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent.setTextElideMode(Qt.ElideMiddle)
        lay.addWidget(self.recent)
        h = QHBoxLayout()
        h.addStretch()
        h.addWidget(card, 10)
        h.addStretch()
        outer.addLayout(h)
        outer.addStretch(2)

    def refresh(self, recent: list[str]):
        self.recent.clear()
        for p in recent:
            folder = str(Path(p).parent)
            if len(folder) > 48:
                folder = folder[:20] + "\u2026" + folder[-26:]
            it = QListWidgetItem(f"{Path(p).name}    \u2014  {folder}")
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            self.recent.addItem(it)
        if not recent:
            it = QListWidgetItem("Files you open will appear here.")
            it.setFlags(Qt.NoItemFlags)
            self.recent.addItem(it)
        self.clear_btn.setVisible(bool(recent))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.win.handle_drop([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sheaf")
        self.resize(1320, 880)
        self.setAcceptDrops(True)
        self.settings = QSettings(QSettings.defaultFormat(), QSettings.UserScope, "Sheaf", "Sheaf")
        self.state = ToolState()
        self.state.initials = self.settings.value("initials", "", str)
        self.mode = "view"
        self.sidebar_visible = True
        self.tabs: list[DocumentTab] = []

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.stack = QStackedWidget()
        self.start = StartScreen(self)
        doc_area = QWidget()
        dv = QVBoxLayout(doc_area)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(0)
        self.tabbar = QTabBar()
        self.tabbar.setDocumentMode(True)
        self.tabbar.setTabsClosable(True)
        self.tabbar.setMovable(True)
        self.tabbar.setExpanding(False)
        self.tabbar.setElideMode(Qt.ElideMiddle)
        self.tabbar.currentChanged.connect(self._tab_switched)
        self.tabbar.tabCloseRequested.connect(self.close_tab)
        self.tabbar.tabMoved.connect(self._tab_moved)
        self.docstack = QStackedWidget()
        self._build_actions()
        dv.addWidget(self.tabbar)
        dv.addWidget(self._build_mode_bar())
        dv.addWidget(self._build_context_bar())
        dv.addWidget(self.docstack, 1)
        self.stack.addWidget(self.start)
        self.stack.addWidget(doc_area)
        v.addWidget(self.stack)
        self._build_menus()
        self._build_status()
        self.start.refresh(self.recent())
        self._update_ui()

        self.recovery_timer = QTimer(self)
        self.recovery_timer.timeout.connect(self.write_recovery)
        self.recovery_timer.start(90_000)
        QTimer.singleShot(300, self.offer_recovery)

    # ------------------------------------------------------------ actions and menus

    def _act(self, text, slot, shortcut=None, tip=None, checkable=False) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcuts(shortcut if isinstance(shortcut, list) else [QKeySequence(shortcut)])
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(lambda *_: slot())
        self.addAction(a)
        return a

    def _build_actions(self):
        A = self._act
        self.a_open = A("Open…", self.open_dialog, QKeySequence.Open)
        self.a_combine = A("Combine files…", self.combine_dialog, tip="Merge several PDFs or images into one")
        self.a_save = A("Save", self.save, QKeySequence.Save)
        self.a_save_as = A("Save as…", self.save_as, QKeySequence("Ctrl+Shift+S"))
        self.a_print = A("Print…", lambda: self.cur and self.cur.print_document(), QKeySequence.Print)
        self.a_close = A("Close document", lambda: self.close_tab(self.tabbar.currentIndex()), QKeySequence("Ctrl+W"))
        self.a_quit = A("Exit", self.close, QKeySequence("Ctrl+Q"))
        self.a_undo = A("Undo", lambda: self.cur and self.cur.sdoc.undo(), QKeySequence.Undo)
        self.a_redo = A("Redo", lambda: self.cur and self.cur.sdoc.redo(), [QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.a_copy = A("Copy", lambda: self.cur and self.cur.canvas.copy(), None)
        self.a_select_all = A("Select all text on page", lambda: self.cur and self.cur.canvas.select_all_on_page())
        self.a_delete = A("Delete", self.delete_selection, None,
                          tip="Delete the selected comment or text box, or the selected pages in Organize")
        self.a_find = A("Find…", self.focus_search, QKeySequence.Find)
        self.a_find_next = A("Find next", lambda: self.cur and self.cur.search.step(1), QKeySequence("F3"))
        self.a_find_prev = A("Find previous", lambda: self.cur and self.cur.search.step(-1), QKeySequence("Shift+F3"))
        self.a_zoom_in = A("Zoom in", lambda: self.cur and self.cur.canvas.zoom_step(1),
                           [QKeySequence("Ctrl+="), QKeySequence("Ctrl++")])
        self.a_zoom_out = A("Zoom out", lambda: self.cur and self.cur.canvas.zoom_step(-1), QKeySequence("Ctrl+-"))
        self.a_fit_page = A("Fit page", lambda: self.cur and self.cur.canvas.set_fit("page"), QKeySequence("Ctrl+0"))
        self.a_actual = A("Actual size", lambda: self.cur and self.cur.canvas.set_zoom(1.0), QKeySequence("Ctrl+1"))
        self.a_fit_width = A("Fit width", lambda: self.cur and self.cur.canvas.set_fit("width"), QKeySequence("Ctrl+2"))
        self.a_sidebar = A("Show page sidebar", self.toggle_sidebar, QKeySequence("F4"), checkable=True)
        self.a_sidebar.setChecked(True)
        self.a_comments = A("Show comments", self.toggle_comments, QKeySequence("Ctrl+Shift+C"), checkable=True)
        self.a_goto = A("Go to page…", self.goto_page, QKeySequence("Ctrl+G"))
        self.a_next_tab = A("Next document", lambda: self._cycle_tab(1), QKeySequence("Ctrl+Tab"))
        self.a_prev_tab = A("Previous document", lambda: self._cycle_tab(-1), QKeySequence("Ctrl+Shift+Tab"))
        self.a_palette = A("Search commands…", self.show_palette, QKeySequence("Ctrl+K"))

        self.a_rot_r = A("Rotate pages right", lambda: self.cur and self.cur.rotate(90), QKeySequence("Ctrl+Shift+R"),
                         tip="Rotate the selected or current page clockwise")
        self.a_rot_l = A("Rotate pages left", lambda: self.cur and self.cur.rotate(-90), QKeySequence("Ctrl+Shift+L"),
                         tip="Rotate the selected or current page counter-clockwise")
        self.a_del_pages = A("Delete pages", lambda: self.cur and self.cur.delete_pages(), None)
        self.a_insert = A("Insert pages from file…", lambda: self.cur and self.cur.insert_files_dialog(),
                          QKeySequence("Ctrl+Shift+I"), tip="Insert pages from PDFs or images")
        self.a_blank = A("Insert blank page", lambda: self.cur and self.cur.insert_blank())
        self.a_extract = A("Extract pages…", lambda: self.cur and self.cur.extract(False), QKeySequence("Ctrl+Shift+E"))
        self.a_split = A("Split document…", lambda: self.cur and self.cur.extract(True))
        self.a_numbers = A("Add page numbers…", lambda: self.cur and self.cur.page_numbers())
        self.a_watermark = A("Add watermark…", lambda: self.cur and self.cur.watermark())
        self.a_compress = A("Compress…", lambda: self.cur and self.cur.compress(), tip="Make the file smaller")
        self.a_ocr = A("Recognize text (OCR)…", lambda: self.cur and self.cur.ocr(),
                       tip="Make scanned pages searchable and copyable")
        self.a_export = A("Export as images…", lambda: self.cur and self.cur.export_images())
        self.a_password = A("Add password…", lambda: self.cur and self.cur.add_password())
        self.a_unlock = A("Remove password", lambda: self.cur and self.cur.remove_password(),
                          tip="Save an unprotected copy of a protected file")
        self.a_apply_redact = A("Apply redactions…", lambda: self.cur and self.cur.apply_redactions())
        self.a_signatures = A("Manage signatures…", self.choose_signature)
        self.a_initials = A("Set initials…", self.set_initials)
        self.a_shortcuts = A("Keyboard shortcuts", self.show_shortcuts, QKeySequence("F1"))
        self.a_about = A("About Sheaf", self.about)

        self.mode_actions = {}
        for k, (key, label) in enumerate(MODES, 1):
            self.mode_actions[key] = A(f"{label} mode", partial(self.set_mode, key), QKeySequence(f"Ctrl+{k + 2}"))
        self.tool_actions = {}
        for tool, key in TOOL_KEYS.items():
            a = A(TOOL_LABELS[tool], partial(self.set_tool, tool), QKeySequence(key), tip=TOOL_TIPS.get(tool))
            a.setShortcutContext(Qt.WindowShortcut)
            self.tool_actions[tool] = a
        for tool in ("fill", "check", "cross", "date", "initials"):
            self.tool_actions[tool] = A(TOOL_LABELS[tool], partial(self.set_tool, tool), tip=TOOL_TIPS.get(tool))
        self.doc_actions = [self.a_save, self.a_save_as, self.a_print, self.a_close, self.a_copy, self.a_select_all,
                            self.a_delete, self.a_find, self.a_find_next, self.a_find_prev, self.a_zoom_in,
                            self.a_zoom_out, self.a_fit_page, self.a_actual, self.a_fit_width, self.a_goto,
                            self.a_rot_r, self.a_rot_l, self.a_del_pages, self.a_insert, self.a_blank,
                            self.a_extract, self.a_split, self.a_numbers, self.a_watermark, self.a_compress,
                            self.a_ocr, self.a_export, self.a_password, self.a_unlock, self.a_apply_redact,
                            self.a_comments, *self.mode_actions.values(), *self.tool_actions.values()]

    def _build_menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        for a in (self.a_open, self.a_combine):
            f.addAction(a)
        self.recent_menu = f.addMenu("Open recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        f.addSeparator()
        for a in (self.a_save, self.a_save_as, None, self.a_print, None, self.a_close, self.a_quit):
            f.addSeparator() if a is None else f.addAction(a)
        e = mb.addMenu("&Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_copy, self.a_select_all, self.a_delete, None,
                  self.a_find, self.a_find_next, self.a_find_prev, None, self.a_palette):
            e.addSeparator() if a is None else e.addAction(a)
        vm = mb.addMenu("&View")
        for a in (self.a_zoom_in, self.a_zoom_out, self.a_actual, self.a_fit_width, self.a_fit_page, None,
                  self.a_goto, None, self.a_sidebar, self.a_comments, None, self.a_next_tab, self.a_prev_tab):
            vm.addSeparator() if a is None else vm.addAction(a)
        theme = vm.addMenu("Theme")
        group = QActionGroup(self)
        for key, label in (("system", "Follow Windows"), ("light", "Light"), ("dark", "Dark")):
            a = theme.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.settings.value("theme", "system") == key)
            a.triggered.connect(partial(self.set_theme, key))
            group.addAction(a)
        pages = mb.addMenu("&Pages")
        for a in (self.a_rot_l, self.a_rot_r, self.a_del_pages, None, self.a_insert, self.a_blank, None,
                  self.a_extract, self.a_split, None, self.a_numbers, self.a_watermark, None, self.a_compress,
                  self.a_ocr, self.a_export):
            pages.addSeparator() if a is None else pages.addAction(a)
        tools = mb.addMenu("&Tools")
        for key, _ in MODES:
            tools.addAction(self.mode_actions[key])
        tools.addSeparator()
        for a in (self.a_signatures, self.a_initials, None, self.a_password, self.a_unlock, self.a_apply_redact):
            tools.addSeparator() if a is None else tools.addAction(a)
        h = mb.addMenu("&Help")
        h.addAction(self.a_shortcuts)
        h.addAction(self.a_about)

    def _tool_button(self, action: QAction, text: str | None = None) -> QToolButton:
        b = QToolButton()
        b.setDefaultAction(action)
        if text:
            # setDefaultAction copies the action's long menu text on every change; keep the short label.
            b.setText(text)
            action.changed.connect(lambda b=b, t=text: b.text() != t and b.setText(t))
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.setAutoRaise(True)
        b.setObjectName("toolButton")
        sc = action.shortcut().toString(QKeySequence.NativeText)
        tip = action.toolTip() or action.text()
        b.setToolTip(f"{tip} ({sc})" if sc and "(" not in tip else tip)
        return b

    def _build_mode_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("modeBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(6)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for k, (key, label) in enumerate(MODES):
            b = QToolButton()
            b.setText(label.replace("&", "&&"))  # a single & would be read as a keyboard mnemonic
            b.setCheckable(True)
            b.setObjectName("modeButton")
            b.setAccessibleName(f"{label} mode")
            b.setToolTip(f"{label} (Ctrl+{k + 3})")
            b.clicked.connect(partial(self.set_mode, key))
            self.mode_group.addButton(b)
            self.mode_buttons[key] = b
            h.addWidget(b)
        h.addStretch()
        search = QPushButton("Search commands      Ctrl+K")
        search.setObjectName("paletteButton")
        search.clicked.connect(self.show_palette)
        h.addWidget(search)
        return bar

    def _build_context_bar(self) -> QWidget:
        self.context = QStackedWidget()
        self.context.setObjectName("contextBar")
        self.tool_buttons: dict[str, list[QToolButton]] = {}
        self.context_pages = {}
        for key, _ in MODES:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(12, 4, 12, 4)
            h.setSpacing(4)
            for tool in MODE_TOOLS[key]:
                act = self.tool_actions[tool]
                act.setCheckable(True)
                b = self._tool_button(act)
                self.tool_buttons.setdefault(tool, []).append(b)
                h.addWidget(b)
            if MODE_TOOLS[key]:
                h.addWidget(self._sep())
            getattr(self, f"_ctx_{key}")(h)
            h.addStretch()
            self.context.addWidget(w)
            self.context_pages[key] = w
        return self.context

    def _sep(self) -> QFrame:
        s = QFrame()
        s.setFrameShape(QFrame.VLine)
        s.setObjectName("sep")
        return s

    def _ctx_view(self, h):
        for a, t in ((self.a_zoom_out, "−"), (None, None), (self.a_zoom_in, "+"), (self.a_fit_width, None),
                     (self.a_fit_page, None)):
            if a is None:
                self.zoom_label = QPushButton("100%")
                self.zoom_label.setFlat(True)
                self.zoom_label.setToolTip("Click to type a zoom level")
                self.zoom_label.clicked.connect(self.ask_zoom)
                h.addWidget(self.zoom_label)
            else:
                h.addWidget(self._tool_button(a, t))
        h.addWidget(self._sep())
        h.addWidget(self._tool_button(self.a_find, "Find"))
        h.addWidget(self._tool_button(self.a_print, "Print"))

    def _ctx_edit(self, h):
        self.font_box = QComboBox()
        self.font_box.addItems(list(ops.FONT_FAMILIES))
        self.font_box.setAccessibleName("Font")
        self.font_box.currentTextChanged.connect(lambda t: self._style("font", t))
        self.size_box = QDoubleSpinBox()
        self.size_box.setRange(4, 144)
        self.size_box.setDecimals(1)
        self.size_box.setValue(12)
        self.size_box.setSuffix(" pt")
        self.size_box.setAccessibleName("Font size")
        self.size_box.valueChanged.connect(lambda v: self._style("size", v))
        self.color_btn = QToolButton()
        self.color_btn.setToolTip("Text color")
        self.color_btn.setAccessibleName("Text color")
        self.color_btn.setIcon(color_icon(self.state.text_style.color))
        self.color_btn.clicked.connect(self.pick_text_color)
        self.bold_btn = QToolButton()
        self.bold_btn.setText("B")
        self.bold_btn.setCheckable(True)
        self.bold_btn.setToolTip("Bold (Ctrl+B)")
        self.bold_btn.setShortcut(QKeySequence.Bold)
        self.bold_btn.setStyleSheet("font-weight: bold;")
        self.bold_btn.toggled.connect(lambda v: self._style("bold", v))
        self.italic_btn = QToolButton()
        self.italic_btn.setText("I")
        self.italic_btn.setCheckable(True)
        self.italic_btn.setToolTip("Italic (Ctrl+I)")
        self.italic_btn.setShortcut(QKeySequence.Italic)
        self.italic_btn.setStyleSheet("font-style: italic;")
        self.italic_btn.toggled.connect(lambda v: self._style("italic", v))
        self.align_box = QComboBox()
        self.align_box.addItems(["Left", "Center", "Right"])
        self.align_box.setAccessibleName("Alignment")
        self.align_box.currentIndexChanged.connect(lambda i: self._style("align", i))
        for w in (QLabel("Font"), self.font_box, self.size_box, self.color_btn, self.bold_btn, self.italic_btn,
                  self.align_box):
            h.addWidget(w)

    def _ctx_annotate(self, h):
        self.markup_btn = QToolButton()
        self.markup_btn.setText(" Highlight color")
        self.markup_btn.setIcon(color_icon(self.state.markup_color))
        self.markup_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.markup_btn.clicked.connect(lambda: self.pick_color("markup_color", self.markup_btn))
        self.shape_btn = QToolButton()
        self.shape_btn.setText(" Pen color")
        self.shape_btn.setIcon(color_icon(self.state.shape_color))
        self.shape_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.shape_btn.clicked.connect(lambda: self.pick_color("shape_color", self.shape_btn))
        width = QDoubleSpinBox()
        width.setRange(0.5, 12)
        width.setValue(self.state.line_width)
        width.setSuffix(" pt")
        width.setAccessibleName("Line width")
        width.valueChanged.connect(lambda v: setattr(self.state, "line_width", v))
        for w in (self.markup_btn, self.shape_btn, QLabel("Width"), width):
            h.addWidget(w)
        h.addWidget(self._sep())
        h.addWidget(self._tool_button(self.a_comments, "Comments list"))

    def _ctx_fill(self, h):
        h.addWidget(self._tool_button(self.a_signatures, "Signatures…"))
        h.addWidget(self._tool_button(self.a_initials, "Initials…"))
        tip = QLabel("Tab moves between form fields")
        tip.setObjectName("quiet")
        h.addWidget(tip)

    def _ctx_organize(self, h):
        for a, t in ((self.a_insert, "Insert file…"), (self.a_blank, "Blank page"), (None, None),
                     (self.a_rot_l, "Rotate left"), (self.a_rot_r, "Rotate right"), (self.a_del_pages, "Delete"),
                     (None, None), (self.a_extract, "Extract…"), (self.a_split, "Split…")):
            h.addWidget(self._sep() if a is None else self._tool_button(a, t))
        more = QToolButton()
        more.setText("More tools")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setAutoRaise(True)
        more.setObjectName("toolButton")
        menu = QMenu(more)
        for a in (self.a_numbers, self.a_watermark, None, self.a_compress, self.a_ocr, self.a_export):
            menu.addSeparator() if a is None else menu.addAction(a)
        more.setMenu(menu)
        h.addWidget(more)
        hint = QLabel("Drag pages to reorder · drop files between pages to insert them")
        hint.setObjectName("quiet")
        h.addWidget(hint)
        self.legend = QLabel()
        self.legend.setObjectName("quiet")
        self.legend.setToolTip("Which file each page came from")
        h.addWidget(self.legend)

    def _ctx_protect(self, h):
        h.addWidget(self._tool_button(self.a_apply_redact, "Apply redactions…"))
        h.addWidget(self._sep())
        h.addWidget(self._tool_button(self.a_password, "Add password…"))
        h.addWidget(self._tool_button(self.a_unlock, "Remove password"))
        self.protect_label = QLabel()
        self.protect_label.setObjectName("quiet")
        h.addWidget(self.protect_label)

    def _build_status(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.page_label = QPushButton("")
        self.page_label.setFlat(True)
        self.page_label.setToolTip("Go to page (Ctrl+G)")
        self.page_label.clicked.connect(self.goto_page)
        self.saved_label = QLabel("")
        local = QLabel("● Files stay on this PC")
        local.setObjectName("localBadge")
        local.setToolTip("Sheaf has no network code. Nothing you open or save is uploaded anywhere.")
        self.zoom_status = QPushButton("")
        self.zoom_status.setFlat(True)
        self.zoom_status.setToolTip("Zoom. Click to type a level (Ctrl+wheel or pinch to zoom)")
        self.zoom_status.clicked.connect(self.ask_zoom)
        sb.addWidget(self.page_label)
        sb.addWidget(self.zoom_status)
        sb.addWidget(self.saved_label)
        sb.addPermanentWidget(local)

    # ------------------------------------------------------------ tabs

    @property
    def cur(self) -> DocumentTab | None:
        w = self.docstack.currentWidget()
        return w if isinstance(w, DocumentTab) else None

    def add_tab(self, sdoc: SheafDocument) -> DocumentTab:
        tab = DocumentTab(sdoc, self.state)
        tab.titleChanged.connect(self._update_ui)
        tab.message.connect(lambda m: self.statusBar().showMessage(m, 6000))
        tab.pageChanged.connect(self._page_changed)
        tab.canvas.zoomChanged.connect(lambda z: (self.zoom_label.setText(f"{round(z * 100)}%"),
                                                  self.zoom_status.setText(f"{round(z * 100)}%")))
        tab.canvas.selectionChanged.connect(self._update_ui)
        tab.canvas.annotSelected.connect(self._annot_selected)
        self.tabs.append(tab)
        self.docstack.addWidget(tab)
        idx = self.tabbar.addTab(sdoc.title)
        self.tabbar.setTabToolTip(idx, sdoc.path or sdoc.title)
        self.tabbar.setCurrentIndex(idx)
        self.stack.setCurrentIndex(1)
        tab.set_organize(self.mode == "organize")
        self._update_ui()
        return tab

    def _tab_switched(self, idx: int):
        if 0 <= idx < len(self.tabs):
            self.docstack.setCurrentWidget(self.tabs[idx])
            self.tabs[idx].set_organize(self.mode == "organize")
            self.tabs[idx].comments.setVisible(self.a_comments.isChecked())
        self._update_ui()

    def _tab_moved(self, frm: int, to: int):
        self.tabs.insert(to, self.tabs.pop(frm))

    def _cycle_tab(self, d: int):
        if self.tabbar.count() > 1:
            self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + d) % self.tabbar.count())

    def close_tab(self, idx: int) -> bool:
        if not (0 <= idx < len(self.tabs)):
            return True
        tab = self.tabs[idx]
        tab.canvas.close_editor(commit=True)
        if tab.sdoc.dirty:
            self.tabbar.setCurrentIndex(idx)
            r = QMessageBox.question(self, "Sheaf", f"Save changes to {tab.sdoc.title} before closing?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if r == QMessageBox.Cancel or (r == QMessageBox.Save and not self.save()):
                return False
        self.drop_recovery(tab)
        self.tabs.pop(idx)
        self.tabbar.removeTab(idx)
        self.docstack.removeWidget(tab)
        tab.sdoc.doc.close()
        tab.deleteLater()
        if not self.tabs:
            self.stack.setCurrentIndex(0)
            self.start.refresh(self.recent())
        self._update_ui()
        return True

    # ------------------------------------------------------------ open and save

    def ask_password(self, name: str, attempt: int):
        return dialogs.ask_open_password(self, name, attempt)

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open", self._last_folder(),
                                                "PDF and image files (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp);;"
                                                + PDF_FILTER)
        if paths:
            self.open_paths(paths)

    def _last_folder(self) -> str:
        return self.settings.value("last_folder", str(Path.home() / "Documents"), str)

    def open_paths(self, paths: list[str]):
        for path in paths:
            for i, t in enumerate(self.tabs):
                if fileio.same_file(t.sdoc.path, path):
                    self.tabbar.setCurrentIndex(i)
                    break
            else:
                try:
                    sdoc = SheafDocument.open(path, self.ask_password)
                except OpenCancelled:
                    continue
                except OpenFailed as e:
                    QMessageBox.warning(self, "Sheaf", str(e))
                    if not Path(path).exists():
                        self.remove_recent(path)
                    continue
                self.add_tab(sdoc)
                if sdoc.path:
                    self.add_recent(path)
                self.settings.setValue("last_folder", str(Path(path).parent))

    def combine_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files to combine", self._last_folder(), INSERT_FILTER)
        if paths:
            self.combine(paths)

    def combine(self, paths: list[str]):
        try:
            sdoc = SheafDocument.open(paths[0], self.ask_password)
        except OpenCancelled:
            return
        except OpenFailed as e:
            QMessageBox.warning(self, "Sheaf", str(e))
            return
        sdoc.path = None  # a combined document is new; never saved over the first file
        sdoc.dirty = True
        tab = self.add_tab(sdoc)
        tab.insert_paths(paths[1:], sdoc.page_count)
        sdoc._undo.clear()
        self.set_mode("organize")
        self.statusBar().showMessage(f"Combined {len(paths)} files. Drag pages to reorder, then Save as.", 8000)

    def handle_drop(self, paths: list[str]):
        paths = [p for p in paths if Path(p).suffix.lower() in {".pdf", *IMAGE_SUFFIXES}]
        if not paths:
            return
        if len(paths) == 1:
            self.open_paths(paths)
            return
        box = QMessageBox(self)
        box.setWindowTitle("Sheaf")
        box.setText(f"You dropped {len(paths)} files.")
        combine = box.addButton("Combine into one PDF", QMessageBox.AcceptRole)
        separate = box.addButton("Open separately", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is combine:
            self.combine(paths)
        elif box.clickedButton() is separate:
            self.open_paths(paths)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.handle_drop([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def save(self) -> bool:
        tab = self.cur
        if not tab:
            return False
        tab.canvas.close_editor(commit=True)
        if tab.sdoc.needs_save_as():
            return self.save_as()
        return self._write(tab, tab.sdoc.save_path)

    def save_as(self) -> bool:
        tab = self.cur
        if not tab:
            return False
        tab.canvas.close_editor(commit=True)
        sd = tab.sdoc
        base = sd.save_path or sd.path
        if base and not sd.save_path:
            default = str(Path(base).with_name(f"{Path(base).stem} (edited).pdf"))
        elif base:
            default = base
        else:
            default = str(Path(self._last_folder()) / sd.title)
        path, _ = QFileDialog.getSaveFileName(self, "Save as", default, PDF_FILTER)
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if fileio.same_file(path, sd.path) and not fileio.same_file(path, sd.save_path):
            if QMessageBox.warning(self, "Replace the original?",
                                   f"This replaces the original {Path(path).name}. The old version can't be "
                                   "recovered from Sheaf.\n\nReplace it?",
                                   QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
                return False
        for other in self.tabs:
            if other is not tab and (fileio.same_file(path, other.sdoc.save_path)):
                QMessageBox.warning(self, "Sheaf", "That file is open in another tab. Pick a different name.")
                return False
        return self._write(tab, path)

    def _write(self, tab: DocumentTab, path: str) -> bool:
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            tab.sdoc.save_to(path)
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save", f"{Path(path).name} couldn't be saved: {e.strerror or e}\n\n"
                                "If it's open in another program, close it there and try again.")
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self.drop_recovery(tab)
        self.add_recent(path)
        self.settings.setValue("last_folder", str(Path(path).parent))
        self.statusBar().showMessage(f"Saved {Path(path).name}", 5000)
        self._update_ui()
        return True

    # ------------------------------------------------------------ recent files

    def recent(self) -> list[str]:
        v = self.settings.value("recent", [], list) or []
        return [p for p in v if isinstance(p, str)][:MAX_RECENT]

    def add_recent(self, path: str):
        path = str(Path(path).resolve())
        r = [p for p in self.recent() if not fileio.same_file(p, path)]
        self.settings.setValue("recent", [path] + r[:MAX_RECENT - 1])

    def remove_recent(self, path: str):
        self.settings.setValue("recent", [p for p in self.recent() if p != path])
        self.start.refresh(self.recent())

    def clear_recent(self):
        self.settings.setValue("recent", [])
        self.start.refresh([])

    def _fill_recent_menu(self):
        self.recent_menu.clear()
        for p in self.recent():
            self.recent_menu.addAction(Path(p).name, partial(self.open_paths, [p])).setToolTip(p)
        if not self.recent():
            self.recent_menu.addAction("No recent files").setEnabled(False)
        else:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear list", self.clear_recent)

    # ------------------------------------------------------------ recovery copies

    def _recovery_dir(self) -> Path:
        d = fileio.app_data_dir() / "recovery"
        d.mkdir(exist_ok=True)
        return d

    def write_recovery(self):
        for tab in self.tabs:
            sd = tab.sdoc
            # Password-protected documents are never written unencrypted: their copy keeps the password.
            if not sd.dirty:
                continue
            if tab.recovery_id is None:
                tab.recovery_id = uuid.uuid4().hex
            try:
                d = self._recovery_dir()
                fileio.atomic_write(d / f"{tab.recovery_id}.pdf", sd.save_bytes())
                fileio.atomic_write(d / f"{tab.recovery_id}.json",
                                    json.dumps({"title": sd.title, "path": sd.path,
                                                "protected": bool(sd.protection and sd.protection.user_pw)}).encode())
            except OSError:
                pass

    def drop_recovery(self, tab: DocumentTab):
        if tab.recovery_id:
            for ext in (".pdf", ".json"):
                (self._recovery_dir() / f"{tab.recovery_id}{ext}").unlink(missing_ok=True)
            tab.recovery_id = None

    def offer_recovery(self):
        d = self._recovery_dir()
        items = sorted(d.glob("*.json"))
        if not items:
            return
        r = QMessageBox.question(self, "Recover unsaved work?",
                                 f"Sheaf closed unexpectedly with {len(items)} unsaved document"
                                 f"{'s' if len(items) > 1 else ''}. Restore {'them' if len(items) > 1 else 'it'}?",
                                 QMessageBox.Yes | QMessageBox.Discard, QMessageBox.Yes)
        for meta_path in items:
            pdf = meta_path.with_suffix(".pdf")
            if r == QMessageBox.Yes and pdf.exists():
                try:
                    meta = json.loads(meta_path.read_text("utf-8"))
                    sdoc = SheafDocument.open(str(pdf), self.ask_password)
                    sdoc.path, sdoc.save_path, sdoc.dirty = meta.get("path"), None, True
                    sdoc.sources = [str(meta.get("title", "Recovered"))]
                    tab = self.add_tab(sdoc)
                    tab.recovery_id = meta_path.stem
                    self.tabbar.setTabText(self.tabbar.currentIndex(), f"Recovered: {sdoc.title}")
                    continue
                except (OpenFailed, OpenCancelled, ValueError, OSError):
                    pass
            pdf.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)

    # ------------------------------------------------------------ modes and tools

    def set_mode(self, mode: str):
        if self.cur:
            self.cur.canvas.close_editor(commit=True)
        self.mode = mode
        self.mode_buttons[mode].setChecked(True)
        self.context.setCurrentWidget(self.context_pages[mode])
        for t in self.tabs:
            t.set_organize(mode == "organize")
        self.set_tool(DEFAULT_TOOL[mode])
        self._update_ui()

    def set_tool(self, tool: str):
        if tool not in MODE_TOOLS.get(self.mode, []) and self.mode != "organize":
            for mode, tools in MODE_TOOLS.items():
                if tool in tools:
                    self.mode = mode
                    self.mode_buttons[mode].setChecked(True)
                    self.context.setCurrentWidget(self.context_pages[mode])
                    for t in self.tabs:
                        t.set_organize(False)
                    break
        if self.cur:
            self.cur.canvas.close_editor(commit=True)
            self.cur.canvas.clear_selection()
        self.state.tool = tool
        for t, act in self.tool_actions.items():
            act.setChecked(t == tool)
        if tool == "sign" and not self.state.signature:
            QTimer.singleShot(0, self.choose_signature)
        for t in self.tabs:
            for p in t.canvas.pages:
                p.update()
        if self.cur:
            if self.mode == "organize":
                tip = "Select pages, then rotate, delete or extract them. Double-click a page to open it."
            elif tool == "fill":
                n = sum(len(self.cur.canvas.widgets_for(i)) for i in range(self.cur.sdoc.page_count))
                tip = (f"This form has {n} field{'s' if n != 1 else ''}. Press Tab to start at the first one, "
                       "or click a field." if n else "This PDF has no form fields. Click anywhere to type on it.")
            else:
                tip = TOOL_TIPS.get(tool, "")
            self.statusBar().showMessage(tip, 8000)

    def _style(self, key: str, value):
        setattr(self.state.text_style, key, value)
        tab = self.cur
        if not tab:
            return
        c = tab.canvas
        if c.editor is not None:
            c.restyle_editor()
        elif c.selected_annot and c.is_text_box(*c.selected_annot):
            page, xref = c.selected_annot
            annot = tab.sdoc.doc[page].load_annot(xref)
            text, style = ops.text_box_data(annot)
            setattr(style, key, value)
            if key in ("size", "font", "bold", "italic"):
                w, h = ops.measure_text(text, style)
                r = annot.rect
                rect = type(r)(r.x0, r.y0, max(r.x1, r.x0 + w), max(r.y1, r.y0 + h))
            else:
                rect = None
            tab.sdoc.edit("Format text", lambda d: ops.replace_text_box(d[page], xref, text, style, rect))

    def _annot_selected(self, page: int, xref: int):
        tab = self.cur
        if not tab or xref < 0 or not tab.canvas.is_text_box(page, xref):
            return
        data = ops.text_box_data(tab.sdoc.doc[page].load_annot(xref))
        if data:
            self._show_style(data[1])

    def _show_style(self, st: ops.TextStyle):
        for w in (self.font_box, self.size_box, self.bold_btn, self.italic_btn, self.align_box):
            w.blockSignals(True)
        self.font_box.setCurrentText(st.font)
        self.size_box.setValue(st.size)
        self.bold_btn.setChecked(st.bold)
        self.italic_btn.setChecked(st.italic)
        self.align_box.setCurrentIndex(st.align)
        self.color_btn.setIcon(color_icon(st.color))
        for w in (self.font_box, self.size_box, self.bold_btn, self.italic_btn, self.align_box):
            w.blockSignals(False)

    def pick_text_color(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.state.text_style.color), self, "Text color")
        if c.isValid():
            rgb = (c.redF(), c.greenF(), c.blueF())
            self.color_btn.setIcon(color_icon(rgb))
            self._style("color", rgb)

    def pick_color(self, attr: str, btn: QToolButton):
        c = QColorDialog.getColor(QColor.fromRgbF(*getattr(self.state, attr)), self, "Color")
        if c.isValid():
            rgb = (c.redF(), c.greenF(), c.blueF())
            setattr(self.state, attr, rgb)
            btn.setIcon(color_icon(rgb))

    def choose_signature(self):
        dlg = dialogs.SignatureDialog(self)
        if dlg.exec() == dlg.Accepted and dlg.chosen:
            self.state.signature, self.state.signature_aspect = dlg.chosen
            if self.state.tool != "sign":
                self.set_tool("sign")
            self.statusBar().showMessage("Click where the signature should go.", 6000)
        elif not self.state.signature and self.state.tool == "sign":
            self.set_tool("fill")

    def set_initials(self):
        text, ok = QInputDialog.getText(self, "Your initials", "Initials:", text=self.state.initials)
        if ok:
            self.state.initials = text.strip()[:6]
            self.settings.setValue("initials", self.state.initials)

    # ------------------------------------------------------------ misc commands

    def delete_selection(self):
        tab = self.cur
        if not tab:
            return
        if tab.canvas.delete_selected_annot():
            return
        if self.mode == "organize" or tab.thumbs.hasFocus():
            tab.delete_pages()

    def focus_search(self):
        tab = self.cur
        if not tab:
            return
        if self.mode == "organize":
            self.set_mode("view")
        self.sidebar_visible = True
        self.a_sidebar.setChecked(True)
        tab.sidebar.show()
        tab.sidebar.setCurrentWidget(tab.search)
        if tab.canvas.selection_words:
            tab.search.box.setText(tab.canvas.selected_text()[:200])
        tab.search.box.setFocus()
        tab.search.box.selectAll()

    def toggle_sidebar(self):
        self.sidebar_visible = self.a_sidebar.isChecked()
        if self.cur and self.mode != "organize":
            self.cur.sidebar.setVisible(self.sidebar_visible)

    def toggle_comments(self):
        on = self.a_comments.isChecked()
        for t in self.tabs:
            t.comments.setVisible(on)
            if on:
                t.comments.refresh()

    def goto_page(self):
        tab = self.cur
        if not tab:
            return
        n, ok = QInputDialog.getInt(self, "Go to page", f"Page (1 to {tab.sdoc.page_count}):",
                                    tab.canvas.current_page() + 1, 1, tab.sdoc.page_count)
        if ok:
            if self.mode == "organize":
                self.set_mode("view")
            tab.canvas.go_to(n - 1)

    def ask_zoom(self):
        tab = self.cur
        if not tab:
            return
        z, ok = QInputDialog.getInt(self, "Zoom", "Zoom (%):", round(tab.canvas.zoom * 100), 10, 800)
        if ok:
            tab.canvas.set_zoom(z / 100)

    def show_palette(self):
        acts = [a for a in self.actions() if a.text()]
        seen, unique = set(), []
        for a in acts:
            if a.text() not in seen:
                seen.add(a.text())
                unique.append(a)
        pal = dialogs.CommandPalette(self, unique)
        g = self.geometry()
        pal.move(g.x() + (g.width() - pal.width()) // 2, g.y() + 90)
        pal.search.setFocus()
        pal.exec()

    def show_shortcuts(self):
        rows = []
        for a in self.actions():
            sc = a.shortcut().toString(QKeySequence.NativeText)
            if sc and a.text():
                rows.append(f"<tr><td>{a.text().replace(chr(8230), '')}</td><td><b>{sc}</b></td></tr>")
        QMessageBox.information(self, "Keyboard shortcuts",
                                "<table cellpadding=3>" + "".join(sorted(set(rows))) + "</table>")

    def about(self):
        QMessageBox.about(self, "About Sheaf",
                          f"<h3>Sheaf {__version__}</h3>"
                          "<p>A simple, private PDF editor. Sheaf has no network code: nothing you open or "
                          "save is uploaded, and it works with the internet unplugged.</p>"
                          "<p>Free software under the GNU AGPL-3.0. Source code: "
                          "<a href='https://github.com/gadiglikberg/sheaf'>github.com/gadiglikberg/sheaf</a></p>"
                          "<p>Built with PyMuPDF and Qt.</p>")

    def set_theme(self, key: str):
        self.settings.setValue("theme", key)
        from .theme import apply_theme
        apply_theme(QApplication.instance(), key)
        for t in self.tabs:
            t.canvas.refresh()

    # ------------------------------------------------------------ status

    def _update_legend(self, tab: DocumentTab):
        from .thumbs import SOURCE_COLORS
        used = sorted(set(tab.sdoc.page_sources))
        if len(used) < 2:
            self.legend.setText("")
            return
        parts = [f"<span style='color:{SOURCE_COLORS[i % len(SOURCE_COLORS)]}'>\u25ae</span> "
                 f"{dialogs._esc(tab.sdoc.sources[i])}" for i in used[:5]]
        self.legend.setText("&nbsp;&nbsp;".join(parts))

    def _page_changed(self, page: int, count: int):
        self.page_label.setText(f"Page {page + 1} of {count}")

    def _update_ui(self):
        tab = self.cur
        has = tab is not None
        for a in self.doc_actions:
            a.setEnabled(has)
        if has:
            sd = tab.sdoc
            self.a_undo.setEnabled(sd.can_undo())
            self.a_redo.setEnabled(sd.can_redo())
            self.a_undo.setText(f"Undo {sd.undo_label().lower()}" if sd.can_undo() else "Undo")
            self.a_redo.setText(f"Redo {sd.redo_label().lower()}" if sd.can_redo() else "Redo")
            self.a_copy.setEnabled(bool(tab.canvas.selection_words))
            self.a_unlock.setEnabled(sd.protection is not None)
            for i, t in enumerate(self.tabs):
                self.tabbar.setTabText(i, t.title)
            self.saved_label.setText("Unsaved changes" if sd.dirty else "All changes saved" if sd.save_path else "")
            self.page_label.setText(f"Page {tab.canvas.current_page() + 1} of {sd.page_count}")
            self.zoom_label.setText(f"{round(tab.canvas.zoom * 100)}%")
            self.zoom_status.setText(f"{round(tab.canvas.zoom * 100)}%")
            self._update_legend(tab)
            prot = sd.protection
            self.protect_label.setText(
                "This document has a password." if prot and prot.user_pw else
                "This document has restrictions but no open password." if prot else "No password.")
            self.setWindowTitle(f"{tab.title} — Sheaf")
        else:
            self.a_undo.setEnabled(False)
            self.a_redo.setEnabled(False)
            self.saved_label.setText("")
            self.page_label.setText("")
            self.zoom_status.setText("")
            self.setWindowTitle("Sheaf")
        self.mode_buttons[self.mode].setChecked(True)

    def closeEvent(self, e):
        for i in reversed(range(len(self.tabs))):
            self.tabbar.setCurrentIndex(i)
            if not self.close_tab(i):
                e.ignore()
                return
        e.accept()
