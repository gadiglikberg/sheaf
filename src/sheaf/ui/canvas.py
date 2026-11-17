"""The page canvas: continuous scrolling, zoom, text selection and every on-page tool."""
from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QImage, QKeySequence, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QInputDialog, QLineEdit, QMenu, QPlainTextEdit,
                               QScrollArea, QVBoxLayout, QWidget)

from ..core import ops
from ..core.document import SheafDocument

MAX_RENDER_PIXELS = 60_000_000  # about 240 MB per page bitmap at most
PT_TO_PX = 96 / 72  # 100% zoom shows a page at its printed size on a standard screen
PAGE_GAP = 14

QT_FONTS = {"Helvetica": "Arial", "Times": "Times New Roman", "Courier": "Courier New"}

# Tools that work by dragging across text
TEXT_DRAG_TOOLS = {"select", "highlight", "underline", "strikeout"}
TOOL_LABELS = {
    "select": "Select", "text": "Add text", "edit_text": "Edit text", "highlight": "Highlight",
    "underline": "Underline", "strikeout": "Strike out", "note": "Note", "rect": "Box", "arrow": "Arrow",
    "ink": "Draw", "fill": "Fill form", "sign": "Sign", "check": "Check mark", "cross": "Cross",
    "date": "Date", "initials": "Initials", "redact": "Mark for redaction",
}


def qcolor(rgb) -> QColor:
    return QColor.fromRgbF(*rgb)


@dataclass
class ToolState:
    tool: str = "select"
    text_style: ops.TextStyle = field(default_factory=ops.TextStyle)
    markup_color: tuple = (1.0, 0.85, 0.0)
    shape_color: tuple = (0.85, 0.1, 0.1)
    line_width: float = 1.5
    signature: bytes | None = None
    signature_aspect: float = 3.0
    initials: str = ""


class PageWidget(QWidget):
    def __init__(self, canvas: "Canvas", index: int):
        super().__init__()
        self.canvas = canvas
        self.index = index
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self._press: QPointF | None = None
        self._drag: QPointF | None = None
        self._ink: list[QPointF] = []
        self._hover_span: QRectF | None = None
        self._move_origin: QRectF | None = None
        self.setAccessibleName(f"Page {index + 1}")

    # ------------------------------------------------------------ geometry

    @property
    def page(self) -> pymupdf.Page:
        return self.canvas.sdoc.doc[self.index]

    def scale(self) -> float:
        return self.canvas.scale

    def sizeHint(self) -> QSize:
        r = self.canvas.page_rect(self.index)
        s = self.scale()
        return QSize(int(r.width * s), int(r.height * s))

    def to_pdf(self, pos: QPointF) -> pymupdf.Point:
        s = self.scale()
        return pymupdf.Point(pos.x() / s, pos.y() / s) * self.page.derotation_matrix

    def pdf_rect_from(self, a: QPointF, b: QPointF) -> pymupdf.Rect:
        r = pymupdf.Rect(self.to_pdf(a), self.to_pdf(a))
        r.include_point(self.to_pdf(b))
        return r.normalize()

    def to_widget(self, rect) -> QRectF:
        r = pymupdf.Rect(rect) * self.page.rotation_matrix
        s = self.scale()
        return QRectF(r.x0 * s, r.y0 * s, r.width * s, r.height * s)

    def to_widget_point(self, p) -> QPointF:
        v = pymupdf.Point(p) * self.page.rotation_matrix
        s = self.scale()
        return QPointF(v.x * s, v.y * s)

    # ------------------------------------------------------------ painting

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pix = self.canvas.render(self.index)
        target = QRectF(0, 0, self.width(), self.height())
        if pix is not None:
            p.drawPixmap(target, pix, QRectF(pix.rect()))
        else:
            p.fillRect(target, Qt.white)
        p.setPen(QPen(QColor(0, 0, 0, 40), 1))
        p.drawRect(target.adjusted(0, 0, -1, -1))
        c = self.canvas
        accent = self.palette().highlight().color()

        # search hits
        for pno, r in c.search_hits:
            if pno == self.index:
                current = c.search_hits and c.search_index >= 0 and c.search_hits[c.search_index] == (pno, r)
                p.fillRect(self.to_widget(r), QColor(255, 140, 0, 150) if current else QColor(255, 210, 0, 110))

        # text selection
        if c.selection_page == self.index:
            sel = QColor(accent)
            sel.setAlpha(80)
            for q in ops.word_quads(c.selection_words):
                p.fillRect(self.to_widget(q.rect), sel)

        # form fields while filling
        if c.state.tool == "fill":
            p.setPen(QPen(QColor(40, 110, 220, 160), 1, Qt.DashLine))
            for w in c.widgets_for(self.index):
                p.fillRect(self.to_widget(w[1]), QColor(40, 110, 220, 28))
                p.drawRect(self.to_widget(w[1]))

        # hovered span in edit-text mode
        if self._hover_span is not None and c.state.tool == "edit_text":
            p.setPen(QPen(accent, 1, Qt.DashLine))
            p.drawRect(self._hover_span)

        # selected annotation with resize handle
        if c.selected_annot and c.selected_annot[0] == self.index:
            r = c.selected_annot_rect
            if r is not None:
                wr = self.to_widget(r)
                if self._move_origin is not None and self._drag is not None and self._press is not None:
                    wr = wr.translated(self._drag - self._press)
                p.setPen(QPen(accent, 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(wr.adjusted(-3, -3, 3, 3))
                p.setBrush(accent)
                p.setPen(Qt.NoPen)
                p.drawRect(QRectF(wr.right() - 1, wr.bottom() - 1, 8, 8))

        # drag previews
        if self._press is not None and self._drag is not None and self._move_origin is None:
            tool = c.state.tool
            rect = QRectF(self._press, self._drag).normalized()
            if tool in ("rect", "redact", "text") or (tool in TEXT_DRAG_TOOLS and c.selection_page != self.index):
                color = QColor(0, 0, 0) if tool == "redact" else qcolor(c.state.shape_color)
                p.setPen(QPen(color, 1.5, Qt.DashLine if tool != "rect" else Qt.SolidLine))
                p.setBrush(QColor(0, 0, 0, 70) if tool == "redact" else Qt.NoBrush)
                p.drawRect(rect)
            elif tool == "arrow":
                p.setPen(QPen(qcolor(c.state.shape_color), 2))
                p.drawLine(self._press, self._drag)
        if self._ink:
            p.setPen(QPen(qcolor(c.state.shape_color), max(1.0, c.state.line_width * self.scale()),
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath(self._ink[0])
            for pt in self._ink[1:]:
                path.lineTo(pt)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        p.end()

    # ------------------------------------------------------------ mouse

    def mousePressEvent(self, e):
        self.canvas.setFocus()
        self.canvas.close_editor(commit=True)
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        c = self.canvas
        tool = c.state.tool
        pdf_pt = self.to_pdf(pos)
        self._press, self._drag = pos, pos
        if tool in ("select", "text"):
            hit = c.annot_at(self.index, pdf_pt)
            if hit is not None:
                if tool == "text" and c.is_text_box(self.index, hit):
                    self._press = None
                    c.edit_text_box(self, hit)
                    return
                c.select_annot(self.index, hit)
                self._move_origin = self.to_widget(c.selected_annot_rect)
                return
        c.select_annot(None, None)
        if tool in TEXT_DRAG_TOOLS:
            clicks = c.register_click(self.index, pos)
            if clicks >= 2:
                c.select_by_click(self.index, pdf_pt, line=clicks >= 3)
                self._press = None
                return
            c.clear_selection()
        elif tool == "ink":
            self._ink = [pos]
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        c = self.canvas
        tool = c.state.tool
        if self._press is None:
            self._update_cursor(pos)
            return
        self._drag = pos
        if self._move_origin is not None:
            self.update()
            return
        if tool in TEXT_DRAG_TOOLS:
            c.set_selection(self.index, ops.words_between(self.page, self.to_pdf(self._press), self.to_pdf(pos)))
        elif tool == "ink":
            self._ink.append(pos)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._press is None or e.button() != Qt.LeftButton:
            return
        c = self.canvas
        tool = c.state.tool
        a, b = self._press, e.position()
        moved = (b - a).manhattanLength() > 4
        self._press = self._drag = None
        try:
            if self._move_origin is not None:
                self._move_origin = None
                if moved and c.selected_annot:
                    r = pymupdf.Rect(c.selected_annot_rect)
                    d0, d1 = self.to_pdf(a), self.to_pdf(b)
                    near_handle = self.to_widget(r).bottomRight()
                    if (a - near_handle).manhattanLength() < 14 and c.selected_kind() == "FreeText":
                        r = pymupdf.Rect(r.x0, r.y0, r.x1 + (d1 - d0).x, r.y1 + (d1 - d0).y).normalize()
                    else:
                        r = r + (d1 - d0, d1 - d0)
                    xref = c.selected_annot[1]
                    c.sdoc.edit("Move", lambda d: ops.move_annot(d[self.index], xref, r))
                    c.select_annot(self.index, xref)
                return
            c.handle_tool_release(self, tool, a, b, moved, list(self._ink))
        finally:
            self._ink = []
            self.update()

    def mouseDoubleClickEvent(self, e):
        c = self.canvas
        pdf_pt = self.to_pdf(e.position())
        hit = c.annot_at(self.index, pdf_pt)
        if hit is not None and c.is_text_box(self.index, hit) and c.state.tool in ("select", "text", "fill"):
            c.edit_text_box(self, hit)
            return
        if hit is not None and c.annot_kind(self.index, hit) == "Text":
            c.edit_note(self.index, hit)
            return
        self.mousePressEvent(e)

    def contextMenuEvent(self, e):
        self.canvas.context_menu(self, e.pos(), e.globalPos())

    def _update_cursor(self, pos: QPointF):
        c = self.canvas
        tool = c.state.tool
        shape = Qt.ArrowCursor
        pdf_pt = self.to_pdf(pos)
        if tool in TEXT_DRAG_TOOLS:
            if c.annot_at(self.index, pdf_pt) is not None and tool == "select":
                shape = Qt.SizeAllCursor
            elif c.word_at(self.index, pdf_pt):
                shape = Qt.IBeamCursor
        elif tool == "edit_text":
            span = ops.span_at(self.page, pdf_pt)
            new = self.to_widget(span["bbox"]) if span else None
            if new != self._hover_span:
                self._hover_span = new
                self.update()
            shape = Qt.IBeamCursor if span else Qt.ArrowCursor
        elif tool in ("text", "note", "check", "cross", "date", "initials", "sign"):
            shape = Qt.IBeamCursor if tool == "text" else Qt.PointingHandCursor
        elif tool in ("rect", "arrow", "ink", "redact"):
            shape = Qt.CrossCursor
        elif tool == "fill":
            shape = Qt.PointingHandCursor if c.widget_at(self.index, pdf_pt) else Qt.IBeamCursor
        self.setCursor(shape)


class Canvas(QScrollArea):
    currentPageChanged = Signal(int)
    message = Signal(str)
    selectionChanged = Signal()
    zoomChanged = Signal(float)
    annotSelected = Signal(int, int)  # page, xref (or -1)
    needSignature = Signal()

    def __init__(self, sdoc: SheafDocument, state: ToolState):
        super().__init__()
        self.sdoc = sdoc
        self.state = state
        self.zoom = 1.0
        self.fit_mode = "auto"  # auto | width | page | none
        self.setWidgetResizable(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Document pages")
        self.container = QWidget()
        self.container.setObjectName("canvasBackground")
        self.layout_ = QVBoxLayout(self.container)
        self.layout_.setSpacing(PAGE_GAP)
        self.layout_.setContentsMargins(24, 24, 24, 24)
        self.layout_.setAlignment(Qt.AlignHCenter)
        self.setWidget(self.container)
        self.pages: list[PageWidget] = []
        self._cache: dict[int, tuple[float, QPixmap]] = {}
        self._words: dict[int, list] = {}
        self._widgets: dict[int, list] = {}
        self.search_hits: list[tuple[int, pymupdf.Rect]] = []
        self.search_index = -1
        self.selection_page: int | None = None
        self.selection_words: list = []
        self.selected_annot: tuple[int, int] | None = None
        self.selected_annot_rect: pymupdf.Rect | None = None
        self.editor: QWidget | None = None
        self._editor_commit = None
        self._clicks = (0, None, 0)  # count, (page, pos), time
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self._last_page = -1
        self.rebuild()

    # ------------------------------------------------------------ layout and zoom

    @property
    def scale(self) -> float:
        return self.zoom * PT_TO_PX

    def page_rect(self, i: int) -> pymupdf.Rect:
        return self.sdoc.doc[i].rect

    def rebuild(self):
        current = self.current_page() if self.pages else 0
        self.close_editor(commit=False)
        for w in self.pages:
            self.layout_.removeWidget(w)
            w.deleteLater()
        self.pages = []
        self._cache.clear()
        self._words.clear()
        self._widgets.clear()
        self.clear_selection()
        self.select_annot(None, None)
        self.search_hits = []
        for i in range(self.sdoc.page_count):
            w = PageWidget(self, i)
            self.pages.append(w)
            self.layout_.addWidget(w, 0, Qt.AlignHCenter)
        self.apply_zoom()
        QTimer.singleShot(0, lambda: self.go_to(min(current, self.sdoc.page_count - 1)))

    def refresh(self):
        """Content changed: re-render pages but keep scroll position."""
        self._cache.clear()
        self._words.clear()
        self._widgets.clear()
        if self.selected_annot:
            self.select_annot(*self.selected_annot)
        for w in self.pages:
            w.updateGeometry()
            w.update()

    def apply_zoom(self):
        if self.fit_mode != "none" and self.sdoc.page_count:
            vw = self.viewport().width() - 48 - 4
            vh = self.viewport().height() - 48
            widest = max(self.page_rect(i).width for i in range(min(self.sdoc.page_count, 200)))
            first = self.page_rect(self.current_page() if self.pages else 0)
            if self.fit_mode == "width":
                self.zoom = max(0.1, vw / (widest * PT_TO_PX))
            elif self.fit_mode == "auto":  # on open: fit width, but never oversized on wide screens
                self.zoom = max(0.1, min(1.25, vw / (widest * PT_TO_PX)))
            else:
                self.zoom = max(0.1, min(vw / (first.width * PT_TO_PX), vh / (first.height * PT_TO_PX)))
        self._cache.clear()
        for w in self.pages:
            w.setFixedSize(w.sizeHint())
        self.zoomChanged.emit(self.zoom)

    def set_zoom(self, zoom: float, anchor_page: int | None = None):
        page = self.current_page() if anchor_page is None else anchor_page
        frac = self._page_fraction(page)
        self.fit_mode = "none"
        self.zoom = max(0.1, min(8.0, zoom))
        self.apply_zoom()
        QTimer.singleShot(0, lambda: self._restore_fraction(page, frac))

    def set_fit(self, mode: str):
        page = self.current_page()
        self.fit_mode = mode
        self.apply_zoom()
        QTimer.singleShot(0, lambda: self.go_to(page))

    def zoom_step(self, direction: int):
        steps = [0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 6.0, 8.0]
        if direction > 0:
            nxt = next((s for s in steps if s > self.zoom + 0.01), steps[-1])
        else:
            nxt = next((s for s in reversed(steps) if s < self.zoom - 0.01), steps[0])
        self.set_zoom(nxt)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode != "none":
            page = self.current_page()
            self.apply_zoom()
            QTimer.singleShot(0, lambda: self.go_to(page))

    def wheelEvent(self, e):
        # Ctrl+wheel, and touchpad pinch (Windows sends it as Ctrl+wheel), zoom around the current page.
        if e.modifiers() & Qt.ControlModifier:
            self.zoom_step(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    def _page_fraction(self, page: int) -> float:
        if not self.pages:
            return 0
        w = self.pages[page]
        top = self.verticalScrollBar().value()
        return (top - w.y()) / max(1, w.height())

    def _restore_fraction(self, page: int, frac: float):
        if 0 <= page < len(self.pages):
            w = self.pages[page]
            self.verticalScrollBar().setValue(int(w.y() + frac * w.height()))

    def current_page(self) -> int:
        if not self.pages:
            return 0
        mid = self.verticalScrollBar().value() + self.viewport().height() // 3
        for w in self.pages:
            if w.y() + w.height() + PAGE_GAP >= mid:
                return w.index
        return len(self.pages) - 1

    def go_to(self, page: int, rect: pymupdf.Rect | None = None):
        if not (0 <= page < len(self.pages)):
            return
        w = self.pages[page]
        y = w.y() - 12
        if rect is not None:
            y = int(w.y() + w.to_widget(rect).top() - self.viewport().height() / 3)
        self.verticalScrollBar().setValue(max(0, int(y)))
        self._scrolled()

    def _scrolled(self, *_):
        p = self.current_page()
        if p != self._last_page:
            self._last_page = p
            self.currentPageChanged.emit(p)

    # ------------------------------------------------------------ rendering and caches

    def render(self, i: int) -> QPixmap | None:
        dpr = self.devicePixelRatioF()
        scale = self.scale * dpr
        r = self.page_rect(i)
        area = max(1.0, r.width * r.height)
        scale = min(scale, (MAX_RENDER_PIXELS / area) ** 0.5)  # stretched on screen if capped
        cached = self._cache.get(i)
        if cached and abs(cached[0] - scale) < 1e-6:
            return cached[1]
        try:
            pix = self.sdoc.doc[i].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, annots=True)
        except Exception:
            return None
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        qp = QPixmap.fromImage(img)
        qp.setDevicePixelRatio(dpr)
        if len(self._cache) > 30:
            vis = {self.current_page() + k for k in range(-3, 6)}
            for k in [k for k in self._cache if k not in vis][:10]:
                del self._cache[k]
        self._cache[i] = (scale, qp)
        return qp

    def words_for(self, i: int) -> list:
        if i not in self._words:
            self._words[i] = self.sdoc.doc[i].get_text("words", sort=False)
        return self._words[i]

    def word_at(self, i: int, pt: pymupdf.Point):
        for w in self.words_for(i):
            if pymupdf.Rect(w[:4]).contains(pt):
                return w
        return None

    def widgets_for(self, i: int) -> list:
        if i not in self._widgets:
            self._widgets[i] = [(w.xref, pymupdf.Rect(w.rect), w.field_type, w.field_name)
                                for w in self.sdoc.doc[i].widgets()]
        return self._widgets[i]

    def widget_at(self, i: int, pt: pymupdf.Point):
        for w in self.widgets_for(i):
            if w[1].contains(pt):
                return w
        return None

    # ------------------------------------------------------------ annotations

    def annot_at(self, i: int, pt: pymupdf.Point) -> int | None:
        page = self.sdoc.doc[i]
        hit = None
        for a in page.annots():
            if a.type[0] in (pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_POPUP, pymupdf.PDF_ANNOT_LINK):
                continue
            if pymupdf.Rect(a.rect).contains(pt):
                hit = a.xref  # last one drawn is on top
        return hit

    def annot_kind(self, i: int, xref: int) -> str:
        page = self.sdoc.doc[i]
        a = page.load_annot(xref)
        return a.type[1] if a else ""

    def is_text_box(self, i: int, xref: int) -> bool:
        page = self.sdoc.doc[i]
        a = page.load_annot(xref)
        return bool(a and a.type[0] == pymupdf.PDF_ANNOT_FREE_TEXT
                    and a.info.get("subject", "").startswith(ops.SHEAF_TEXT_TAG))

    def select_annot(self, page: int | None, xref: int | None):
        if page is None or xref is None:
            self.selected_annot, self.selected_annot_rect = None, None
        else:
            a = self.sdoc.doc[page].load_annot(xref)
            if a is None:
                self.selected_annot, self.selected_annot_rect = None, None
            else:
                self.selected_annot, self.selected_annot_rect = (page, xref), pymupdf.Rect(a.rect)
        for w in self.pages:
            w.update()
        self.annotSelected.emit(*(self.selected_annot or (-1, -1)))

    def selected_kind(self) -> str:
        return self.annot_kind(*self.selected_annot) if self.selected_annot else ""

    def delete_selected_annot(self) -> bool:
        if not self.selected_annot:
            return False
        page, xref = self.selected_annot
        self.select_annot(None, None)
        self.sdoc.edit("Delete", lambda d: ops.delete_annot(d[page], xref))
        return True

    # ------------------------------------------------------------ selection and copy

    def register_click(self, page: int, pos: QPointF) -> int:
        count, where, _ = self._clicks
        if self._click_timer.isActive() and where and where[0] == page and (where[1] - pos).manhattanLength() < 6:
            count += 1
        else:
            count = 1
        self._clicks = (count, (page, pos), 0)
        self._click_timer.start(QApplication.doubleClickInterval())
        return count

    def select_by_click(self, page: int, pt: pymupdf.Point, line: bool):
        w = self.word_at(page, pt)
        if not w:
            return
        if line:
            words = [x for x in self.words_for(page) if (x[5], x[6]) == (w[5], w[6])]
        else:
            words = [w]
        self.set_selection(page, words)

    def set_selection(self, page: int, words: list):
        self.selection_page, self.selection_words = (page, words) if words else (None, [])
        for w in self.pages:
            w.update()
        self.selectionChanged.emit()

    def clear_selection(self):
        if self.selection_words:
            self.set_selection(0, [])

    def selected_text(self) -> str:
        return ops.words_text(self.selection_words)

    def copy(self) -> bool:
        text = self.selected_text()
        if not text:
            return False
        QGuiApplication.clipboard().setText(text)
        self.message.emit(f"Copied {len(text.split())} words")
        return True

    def select_all_on_page(self):
        p = self.current_page()
        self.set_selection(p, list(self.words_for(p)))

    def markup_selection(self, kind: str):
        if not self.selection_words or self.selection_page is None:
            return
        page, quads = self.selection_page, ops.word_quads(self.selection_words)
        color = self.state.markup_color if kind == "highlight" else self.state.shape_color
        self.sdoc.edit(kind.capitalize(), lambda d: ops.add_markup(d[page], quads, kind, color))
        self.clear_selection()

    # ------------------------------------------------------------ tool actions

    def handle_tool_release(self, pw: PageWidget, tool: str, a: QPointF, b: QPointF, moved: bool, ink: list):
        i = pw.index
        st = self.state
        pdf_a, pdf_b = pw.to_pdf(a), pw.to_pdf(b)
        if tool in ("highlight", "underline", "strikeout"):
            self.markup_selection(tool)
        elif tool == "text":
            self.new_text_box(pw, a, b if moved else None)
        elif tool == "edit_text":
            span = ops.span_at(pw.page, pdf_a)
            if span:
                self.edit_span(pw, span)
        elif tool == "note":
            text, ok = QInputDialog.getMultiLineText(self, "Add note", "Note:")
            if ok and text.strip():
                self.sdoc.edit("Add note", lambda d: ops.add_note(d[i], pdf_a, text.strip()))
        elif tool == "rect" and moved:
            r = pw.pdf_rect_from(a, b)
            self.sdoc.edit("Add box", lambda d: ops.add_rect(d[i], r, st.shape_color, st.line_width))
        elif tool == "arrow" and moved:
            self.sdoc.edit("Add arrow", lambda d: ops.add_arrow(d[i], pdf_a, pdf_b, st.shape_color, st.line_width))
        elif tool == "ink" and len(ink) > 1:
            pts = [tuple(pw.to_pdf(p)) for p in ink]
            self.sdoc.edit("Draw", lambda d: ops.add_ink(d[i], [pts], st.shape_color, st.line_width + 0.5))
        elif tool == "redact" and moved:
            r = pw.pdf_rect_from(a, b)
            self.sdoc.edit("Mark for redaction", lambda d: ops.mark_redaction(d[i], r))
            self.message.emit("Marked for redaction. Use Apply redactions in Protect to remove it for good.")
        elif tool == "redact" and not moved:
            w = self.word_at(i, pdf_a)
            if w:
                r = pymupdf.Rect(w[:4])
                self.sdoc.edit("Mark for redaction", lambda d: ops.mark_redaction(d[i], r))
        elif tool in ("check", "cross", "date", "initials"):
            if tool == "initials" and not st.initials:
                text, ok = QInputDialog.getText(self, "Your initials", "Initials:")
                if not ok or not text.strip():
                    return
                st.initials = text.strip()[:6]
            self.sdoc.edit(TOOL_LABELS[tool], lambda d: ops.add_stamp(
                d[i], pdf_a, tool, size=max(10.0, st.text_style.size + 2), initials=st.initials,
                color=st.text_style.color))
        elif tool == "sign":
            if not st.signature:
                self.needSignature.emit()
                return
            width = 160.0
            height = width / max(0.5, st.signature_aspect)
            vis_center = pymupdf.Point(a.x() / self.scale, a.y() / self.scale)
            vis = pymupdf.Rect(vis_center.x - width / 2, vis_center.y - height / 2,
                               vis_center.x + width / 2, vis_center.y + height / 2)
            r = (vis * pw.page.derotation_matrix).normalize()
            sig = st.signature
            self.sdoc.edit("Sign", lambda d: ops.place_image(d[i], r, sig))
        elif tool == "fill":
            hit = self.widget_at(i, pdf_a)
            if hit:
                self.fill_widget(pw, hit)
            else:
                self.new_text_box(pw, a, None)

    # inline editors ---------------------------------------------------

    def close_editor(self, commit: bool):
        ed, fn = self.editor, self._editor_commit
        self.editor, self._editor_commit = None, None
        if ed is None:
            return
        if commit and fn:
            try:
                fn()
            except Exception as e:  # never lose the app over one failed edit
                self.message.emit(f"Couldn't apply the change: {e}")
        ed.hide()
        ed.deleteLater()
        self.setFocus()

    def _style_editor(self, ed: QPlainTextEdit, style: ops.TextStyle):
        f = QFont(QT_FONTS.get(style.font, "Arial"))
        f.setPixelSize(max(6, int(style.size * self.scale)))
        f.setBold(style.bold)
        f.setItalic(style.italic)
        ed.setFont(f)
        ed.setStyleSheet(
            f"QPlainTextEdit {{ background: rgba(255,255,255,235); color: {qcolor(style.color).name()};"
            f" border: 1.5px dashed palette(highlight); padding: 0px; }}")

    def new_text_box(self, pw: PageWidget, a: QPointF, b: QPointF | None):
        style = ops.TextStyle(**vars(self.state.text_style))
        self._open_text_editor(pw, a, b, "", style, xref=None)

    def edit_text_box(self, pw: PageWidget, xref: int):
        annot = pw.page.load_annot(xref)
        if annot is None:
            return
        data = ops.text_box_data(annot)
        if not data:
            return
        text, style = data
        self.state.text_style = ops.TextStyle(**vars(style))
        r = pw.to_widget(annot.rect)
        self.select_annot(None, None)
        self._open_text_editor(pw, r.topLeft(), r.bottomRight(), text, style, xref=xref)

    def _open_text_editor(self, pw: PageWidget, a: QPointF, b: QPointF | None, text: str,
                          style: ops.TextStyle, xref: int | None):
        ed = QPlainTextEdit(pw)
        ed.setPlainText(text)
        ed.setLineWrapMode(QPlainTextEdit.NoWrap if b is None else QPlainTextEdit.WidgetWidth)
        ed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.setAccessibleName("Text box")
        self._style_editor(ed, style)
        fixed_width = abs(b.x() - a.x()) if b is not None else None
        origin = QPointF(min(a.x(), b.x()), min(a.y(), b.y())) if b is not None else a

        def grow():
            fm = ed.fontMetrics()
            lines = ed.toPlainText().split("\n") or [""]
            w = fixed_width or max(60, max(fm.horizontalAdvance(l) for l in lines) + fm.averageCharWidth() * 3)
            h = (ed.document().size().height() if fixed_width else len(lines)) * fm.lineSpacing() + 12
            ed.setGeometry(int(origin.x()), int(origin.y() - (0 if b is not None else fm.ascent() * 0.7)),
                           int(w), int(max(h, fm.lineSpacing() + 12)))
        ed.textChanged.connect(grow)
        grow()

        def commit():
            new_text = ed.toPlainText().rstrip()
            st = ops.TextStyle(**vars(self.state.text_style))
            geo = ed.geometry()
            vis = pymupdf.Rect(geo.x() / self.scale, geo.y() / self.scale,
                               geo.right() / self.scale, geo.bottom() / self.scale)
            if not fixed_width:
                w, h = ops.measure_text(new_text, st)
                vis = pymupdf.Rect(vis.x0, vis.y0, vis.x0 + w, vis.y0 + h)
            rect = (vis * pw.page.derotation_matrix).normalize()
            i = pw.index
            if xref is None:
                if new_text.strip():
                    self.sdoc.edit("Add text", lambda d: ops.add_text_box(d[i], rect, new_text, st))
            elif new_text != text or vars(st) != vars(style):
                self.sdoc.edit("Edit text box", lambda d: ops.replace_text_box(d[i], xref, new_text, st, rect))

        self.editor, self._editor_commit = ed, commit
        ed.installEventFilter(self)
        ed.show()
        ed.setFocus()
        ed.moveCursor(ed.textCursor().MoveOperation.End)

    def restyle_editor(self):
        if isinstance(self.editor, QPlainTextEdit):
            self._style_editor(self.editor, self.state.text_style)
            self.editor.textChanged.emit()

    def edit_span(self, pw: PageWidget, span: dict):
        ed = QLineEdit(pw)
        ed.setText(span["text"])
        ed.setAccessibleName("Edit text")
        r = pw.to_widget(span["bbox"])
        f = QFont("Arial")
        f.setPixelSize(max(6, int(span["size"] * self.scale * 0.95)))
        ed.setFont(f)
        ed.setStyleSheet("QLineEdit { background: white; color: black; border: 1.5px solid palette(highlight); }")
        ed.setGeometry(int(r.x()) - 2, int(r.y()) - 2,
                       int(max(r.width() + 40, ed.fontMetrics().horizontalAdvance(span["text"]) + 40)),
                       int(r.height()) + 6)
        i = pw.index

        def commit():
            new = ed.text()
            if new == span["text"]:
                return
            warning = self.sdoc.edit("Edit text", lambda d: ops.replace_span(d[i], span, new))
            self.message.emit(warning or "Text updated")
        self.editor, self._editor_commit = ed, commit
        ed.returnPressed.connect(lambda: self.close_editor(True))
        ed.installEventFilter(self)
        ed.show()
        ed.setFocus()
        ed.selectAll()

    def edit_note(self, i: int, xref: int):
        a = self.sdoc.doc[i].load_annot(xref)
        if a is None:
            return
        text, ok = QInputDialog.getMultiLineText(self, "Edit note", "Note:", a.info.get("content", ""))
        if ok:
            def fn(d):
                annot = d[i].load_annot(xref)
                annot.set_info(content=text)
                annot.update()
            self.sdoc.edit("Edit note", fn)

    def fill_widget(self, pw: PageWidget, hit):
        xref, rect, ftype, name = hit
        i = pw.index
        page = pw.page
        widget = next((w for w in page.widgets() if w.xref == xref), None)
        if widget is None:
            return
        if ftype in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON):
            on = widget.field_value not in (True, "Yes", widget.on_state()) if ftype == pymupdf.PDF_WIDGET_TYPE_CHECKBOX else True
            self.sdoc.edit("Fill form", lambda d: ops.set_field(d[i], xref, on))
            return
        r = pw.to_widget(rect)
        if ftype in (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX):
            ed = QComboBox(pw)
            values = [v if isinstance(v, str) else v[0] for v in (widget.choice_values or [])]
            ed.addItems(values)
            if widget.field_value in values:
                ed.setCurrentText(widget.field_value)
            get = ed.currentText
        else:
            ed = QLineEdit(pw)
            ed.setText(str(widget.field_value or ""))
            ed.returnPressed.connect(lambda: self.close_editor(True))
            get = ed.text
            if widget.field_flags & 8192:  # password field
                ed.setEchoMode(QLineEdit.Password)
        ed.setAccessibleName(name or "Form field")
        ed.setGeometry(r.toRect().adjusted(-1, -1, 1, 1))

        def commit():
            value = get()
            if value != (widget.field_value or ""):
                self.sdoc.edit("Fill form", lambda d: ops.set_field(d[i], xref, value))
        self.editor, self._editor_commit = ed, commit
        self._editor_field = (i, xref)
        ed.installEventFilter(self)
        ed.show()
        ed.setFocus()

    def next_field(self, backwards: bool = False):
        fields = [(i, w) for i in range(self.sdoc.page_count) for w in self.widgets_for(i)]
        if not fields:
            return
        cur = getattr(self, "_editor_field", None)
        idx = next((k for k, (i, w) in enumerate(fields) if cur and (i, w[0]) == cur), -1)
        self.close_editor(commit=True)
        fields = [(i, w) for i in range(self.sdoc.page_count) for w in self.widgets_for(i)]
        k = (idx + (-1 if backwards else 1)) % len(fields)
        i, w = fields[k]
        self.go_to(i, w[1])
        self.fill_widget(self.pages[i], w)

    def eventFilter(self, obj, e):
        if getattr(self, "editor", None) is None or obj is not self.editor:
            return super().eventFilter(obj, e)
        if e.type() == e.Type.KeyPress:
            if e.key() == Qt.Key_Escape:
                self.close_editor(commit=isinstance(obj, QPlainTextEdit) and bool(obj.toPlainText().strip()))
                return True
            if e.key() == Qt.Key_Return and e.modifiers() & Qt.ControlModifier:
                self.close_editor(True)
                return True
            if e.key() in (Qt.Key_Tab, Qt.Key_Backtab) and self.state.tool == "fill" and not isinstance(obj, QPlainTextEdit):
                self.next_field(backwards=e.key() == Qt.Key_Backtab)
                return True
        if obj is self.editor and e.type() == e.Type.FocusOut and isinstance(obj, (QLineEdit, QPlainTextEdit)):
            QTimer.singleShot(0, lambda: self.editor is obj and not obj.hasFocus() and self.close_editor(True))
        return super().eventFilter(obj, e)

    # ------------------------------------------------------------ keyboard and menus

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Copy):
            self.copy()
            return
        if e.matches(QKeySequence.SelectAll):
            self.select_all_on_page()
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.delete_selected_annot():
            return
        if e.key() == Qt.Key_Escape:
            self.clear_selection()
            self.select_annot(None, None)
            return
        if e.key() in (Qt.Key_Tab, Qt.Key_Backtab) and self.state.tool == "fill":
            self.next_field(backwards=e.key() == Qt.Key_Backtab)
            return
        super().keyPressEvent(e)

    def focusNextPrevChild(self, nxt: bool) -> bool:
        if self.state.tool == "fill":
            return False  # Tab moves between form fields instead of leaving the page
        return super().focusNextPrevChild(nxt)

    def context_menu(self, pw: PageWidget, pos, global_pos):
        menu = QMenu(self)
        pdf_pt = pw.to_pdf(QPointF(pos))
        hit = self.annot_at(pw.index, pdf_pt)
        if self.selection_words:
            menu.addAction("Copy", self.copy)
            menu.addAction("Highlight", lambda: self.markup_selection("highlight"))
            menu.addAction("Underline", lambda: self.markup_selection("underline"))
            menu.addAction("Strike out", lambda: self.markup_selection("strikeout"))
            text = self.selected_text()
            menu.addAction("Search for this", lambda: self.message.emit("search:" + text[:200]))
            menu.addSeparator()
        if hit is not None:
            self.select_annot(pw.index, hit)
            if self.is_text_box(pw.index, hit):
                menu.addAction("Edit text", lambda: self.edit_text_box(pw, hit))
            if self.annot_kind(pw.index, hit) == "Text":
                menu.addAction("Edit note", lambda: self.edit_note(pw.index, hit))
            menu.addAction("Delete", self.delete_selected_annot)
            menu.addSeparator()
        menu.addAction("Select all text on this page", self.select_all_on_page)
        menu.exec(global_pos)
