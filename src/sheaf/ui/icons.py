"""Toolbar icons drawn from the icon font built into Windows (Segoe Fluent Icons, or Segoe MDL2 Assets on
Windows 10). Nothing is bundled or downloaded. The glyphs are painted with the current palette, so they follow
light and dark themes. Where neither font exists, icons are empty and buttons show their text."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon, QIconEngine, QPainter, QPalette, QPixmap

GLYPHS = {
    "select": 0xE8B0, "text": 0xE8D2, "edit_text": 0xE70F, "fill": 0xE8AC,
    "highlight": 0xE7E6, "underline": 0xE8DC, "strikeout": 0xEDE0, "note": 0xE90A, "rect": 0xE739,
    "arrow": 0xE72A, "ink": 0xE76D, "sign": 0xEE56, "check": 0xE73E, "cross": 0xE711, "date": 0xE787,
    "initials": 0xE8D3, "redact": 0xE745,
    "zoom_in": 0xE8A3, "zoom_out": 0xE71F, "fit_width": 0xE9A6, "fit_page": 0xE7C3, "find": 0xE721,
    "print": 0xE749, "comments": 0xE8BD, "insert": 0xECC8, "blank": 0xE8A5, "rotate_left": 0xE7AD,
    "rotate_right": 0xE7AD, "delete": 0xE74D, "extract": 0xE2B4, "split": 0xE8C6, "more": 0xE712,
    "lock": 0xE72E, "unlock": 0xE785, "apply": 0xE73E, "save": 0xE74E, "open": 0xE8E5,
}
MIRRORED = {"rotate_left"}


def icon_font() -> str | None:
    fams = set(QFontDatabase.families())
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in fams:
            return name
    return None


class GlyphEngine(QIconEngine):
    def __init__(self, family: str, code: int, mirrored: bool):
        super().__init__()
        self.family, self.code, self.mirrored = family, code, mirrored

    def clone(self):
        return GlyphEngine(self.family, self.code, self.mirrored)

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State):
        pal = QGuiApplication.palette()
        group = QPalette.Disabled if mode == QIcon.Disabled else QPalette.Active
        color = pal.color(group, QPalette.ButtonText)
        painter.save()
        painter.setRenderHint(QPainter.TextAntialiasing)
        f = QFont(self.family)
        f.setPixelSize(max(8, round(min(rect.width(), rect.height()) * 0.9)))
        painter.setFont(f)
        painter.setPen(color)
        if self.mirrored:
            painter.translate(rect.center().x() * 2 + 1, 0)
            painter.scale(-1, 1)
        painter.drawText(rect, Qt.AlignCenter, chr(self.code))
        painter.restore()

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pm = QPixmap(size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        self.paint(p, QRect(QPoint(0, 0), size), mode, state)
        p.end()
        return pm

    def scaledPixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float) -> QPixmap:
        pm = self.pixmap(size * scale, mode, state)
        pm.setDevicePixelRatio(scale)
        return pm


def icon(name: str) -> QIcon:
    family = icon_font()
    if family is None or name not in GLYPHS:
        return QIcon()
    return QIcon(GlyphEngine(family, GLYPHS[name], name in MIRRORED))
