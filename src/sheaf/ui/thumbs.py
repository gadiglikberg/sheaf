"""Page thumbnails: the narrow sidebar list and the full-window Organize grid."""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QListView, QListWidget, QListWidgetItem, QStyle,
                               QStyledItemDelegate)

from ..core.document import SheafDocument

SOURCE_COLORS = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#84cc16"]
PAGE_ROLE = Qt.UserRole + 1
BUTTONS = [("rotate_left", "↺", "Rotate left"), ("rotate_right", "↻", "Rotate right"),
           ("delete", "✕", "Delete page")]


class ThumbDelegate(QStyledItemDelegate):
    def __init__(self, view: "ThumbList"):
        super().__init__(view)
        self.view = view

    def button_rects(self, rect: QRect) -> list[tuple[str, QRect]]:
        size = 28
        out = []
        x = rect.right() - 8 - size
        for key, _, _ in reversed(BUTTONS):
            out.append((key, QRect(x, rect.top() + 8, size, size)))
            x -= size + 4
        return list(reversed(out))

    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(4, 4, -4, -4)
        pal = option.palette
        selected = option.state & QStyle.State_Selected
        hovered = option.state & QStyle.State_MouseOver
        if selected:
            bg = QColor(pal.highlight().color())
            bg.setAlpha(60)
            p.setBrush(bg)
            p.setPen(QPen(pal.highlight().color(), 2))
            p.drawRoundedRect(rect, 8, 8)
        elif hovered:
            bg = QColor(pal.text().color())
            bg.setAlpha(18)
            p.setBrush(bg)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(rect, 8, 8)
        icon: QIcon = index.data(Qt.DecorationRole)
        label_h = 22
        area = rect.adjusted(10, 10, -10, -label_h - 6)
        pix_rect = QRect(area)
        if icon and not icon.isNull():
            pm = icon.pixmap(area.size(), self.view.devicePixelRatioF())
            sz = pm.size() / pm.devicePixelRatio()
            pix_rect = QRect(0, 0, sz.width(), sz.height())
            pix_rect.moveCenter(area.center())
            p.drawPixmap(pix_rect, pm)
        else:
            p.fillRect(QRect(area.x() + area.width() // 6, area.y(), area.width() * 2 // 3, area.height()), Qt.white)
        p.setPen(QPen(QColor(0, 0, 0, 50), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(pix_rect)
        # source color strip (only when pages come from more than one file)
        src = index.data(Qt.UserRole + 2)
        if src is not None and self.view.multi_source:
            p.fillRect(QRect(pix_rect.left() - 6, pix_rect.top(), 3, pix_rect.height()),
                       QColor(SOURCE_COLORS[src % len(SOURCE_COLORS)]))
        p.setPen(pal.text().color())
        f = QFont(option.font)
        f.setPointSizeF(f.pointSizeF() * (0.95 if self.view.grid else 0.9))
        p.setFont(f)
        p.drawText(QRect(rect.left(), rect.bottom() - label_h, rect.width(), label_h), Qt.AlignCenter,
                   index.data(Qt.DisplayRole))
        if self.view.grid and hovered:
            for key, r in self.button_rects(rect):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(30, 30, 30, 200) if key != "delete" else QColor(200, 40, 40, 220))
                p.drawEllipse(r)
                p.setPen(Qt.white)
                bf = QFont(option.font)
                bf.setPixelSize(16)
                bf.setBold(True)
                p.setFont(bf)
                p.drawText(r, Qt.AlignCenter, dict((k, s) for k, s, _ in BUTTONS)[key])
        p.restore()

    def sizeHint(self, option, index):
        return self.view.cell_size()


class ThumbList(QListWidget):
    """grid=False: sidebar; grid=True: Organize mode."""
    pageActivated = Signal(int)
    pagesMoved = Signal(list, int)       # pages, insert position
    filesDropped = Signal(list, int)     # paths, insert position
    pageButton = Signal(str, int)        # action, page

    def __init__(self, sdoc: SheafDocument, grid: bool):
        super().__init__()
        self.sdoc = sdoc
        self.grid = grid
        self.thumb_width = 210 if grid else 120
        self.multi_source = False
        self.setItemDelegate(ThumbDelegate(self))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        if grid:
            self.setViewMode(QListView.IconMode)
            self.setFlow(QListView.LeftToRight)
            self.setWrapping(True)
            self.setResizeMode(QListView.Adjust)
            self.setMovement(QListView.Snap)
            self.setSpacing(6)
            self.setAccessibleName("Pages, arranged as a grid. Drag to reorder.")
        else:
            self.setViewMode(QListView.ListMode)
            self.setFlow(QListView.TopToBottom)
            self.setMovement(QListView.Snap)
            self.setAccessibleName("Page thumbnails. Drag to reorder.")
        self.viewport().installEventFilter(self)
        self.itemClicked.connect(lambda it: self.pageActivated.emit(it.data(PAGE_ROLE)))
        self.itemActivated.connect(lambda it: self.pageActivated.emit(it.data(PAGE_ROLE)))
        self._pending: list[int] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._render_some)
        self.verticalScrollBar().valueChanged.connect(lambda *_: self._prioritize_visible())
        self.rebuild()

    def cell_size(self) -> QSize:
        return QSize(self.thumb_width + 28, int(self.thumb_width * 1.35) + 40)

    def rebuild(self):
        sel = set(self.selected_pages())
        self.clear()
        n = self.sdoc.page_count
        self.multi_source = len(set(self.sdoc.page_sources)) > 1
        for i in range(n):
            it = QListWidgetItem(str(i + 1))
            it.setData(PAGE_ROLE, i)
            it.setData(Qt.UserRole + 2, self.sdoc.page_sources[i] if i < len(self.sdoc.page_sources) else 0)
            it.setSizeHint(self.cell_size())
            it.setToolTip(f"Page {i + 1} · from {self.sdoc.sources[self.sdoc.page_sources[i]]}"
                          if self.multi_source else f"Page {i + 1}")
            self.addItem(it)
            if i in sel:
                it.setSelected(True)
        self._pending = list(range(n))
        self._prioritize_visible()
        self._timer.start(0)

    def refresh_icons(self, pages: list[int] | None = None):
        self._pending = list(range(self.count())) if pages is None else list(pages) + self._pending
        self._prioritize_visible()
        self._timer.start(0)

    def _prioritize_visible(self):
        top = self.indexAt(QPoint(10, 10)).row()
        if top < 0:
            top = 0
        vis = [r for r in range(top, min(self.count(), top + 40))]
        self._pending = [r for r in vis if r in self._pending] + [r for r in self._pending if r not in vis]

    def _render_some(self):
        for _ in range(4):
            if not self._pending:
                self._timer.stop()
                return
            row = self._pending.pop(0)
            it = self.item(row)
            if it is None or row >= self.sdoc.page_count:
                continue
            page = self.sdoc.doc[row]
            dpr = self.devicePixelRatioF()
            zoom = self.thumb_width * dpr / max(page.rect.width, page.rect.height * 0.74, 1)
            try:
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            # A damaged page keeps its blank placeholder.
            except Exception:  # nosec B112
                continue
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            it.setIcon(QIcon(pm))

    def selected_pages(self) -> list[int]:
        return sorted(it.data(PAGE_ROLE) for it in self.selectedItems())

    def select_pages(self, pages: list[int]):
        self.clearSelection()
        for p in pages:
            it = self.item(p)
            if it:
                it.setSelected(True)
        if pages and self.item(pages[0]):
            self.scrollToItem(self.item(pages[0]))

    def set_current(self, page: int):
        it = self.item(page)
        if it and not it.isSelected():
            self.blockSignals(True)
            self.setCurrentItem(it)
            self.blockSignals(False)
            self.scrollToItem(it)

    # drag and drop --------------------------------------------------

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def _drop_row(self, pos) -> int:
        idx = self.indexAt(pos)
        if not idx.isValid():
            return self.count()
        r = self.visualRect(idx)
        after = pos.x() > r.center().x() if self.grid else pos.y() > r.center().y()
        return idx.row() + (1 if after else 0)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.filesDropped.emit(paths, self._drop_row(e.position().toPoint()))
            e.acceptProposedAction()
            return
        if e.source() is self:
            moving = self.selected_pages()
            to = self._drop_row(e.position().toPoint())
            e.setDropAction(Qt.IgnoreAction)
            e.accept()
            if moving:
                self.pagesMoved.emit(moving, to)
            return
        super().dropEvent(e)

    # hover buttons ------------------------------------------------------

    def eventFilter(self, obj, e):
        if obj is self.viewport() and self.grid and e.type() == QEvent.MouseButtonPress:
            idx = self.indexAt(e.position().toPoint())
            if idx.isValid():
                rect = self.visualRect(idx).adjusted(4, 4, -4, -4)
                for key, r in self.itemDelegate().button_rects(rect):
                    if r.contains(e.position().toPoint()):
                        self.pageButton.emit(key, idx.data(PAGE_ROLE))
                        return True
        if obj is self.viewport() and e.type() == QEvent.ToolTip and self.grid:
            idx = self.indexAt(e.pos())
            if idx.isValid():
                rect = self.visualRect(idx).adjusted(4, 4, -4, -4)
                for key, r in self.itemDelegate().button_rects(rect):
                    if r.contains(e.pos()):
                        from PySide6.QtWidgets import QToolTip
                        QToolTip.showText(e.globalPos(), dict((k, t) for k, _, t in BUTTONS)[key], self)
                        return True
        return super().eventFilter(obj, e)
