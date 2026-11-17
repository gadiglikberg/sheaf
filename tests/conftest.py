"""Test fixtures. Every PDF here is generated on the fly; no real documents are used."""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def make_pdf(path: Path, pages: int = 3, text: str = "Page {n} Hello world", **save_opts) -> Path:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), text.format(n=i + 1), fontsize=14, fontname="helv")
        page.insert_text((72, 130), "Second line of text here", fontsize=11, fontname="tiro")
    doc.save(path, **save_opts)
    doc.close()
    return path


def make_form(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    w = pymupdf.Widget()
    w.field_name, w.field_type = "name", pymupdf.PDF_WIDGET_TYPE_TEXT
    w.rect = pymupdf.Rect(72, 72, 300, 92)
    page.add_widget(w)
    c = pymupdf.Widget()
    c.field_name, c.field_type = "agree", pymupdf.PDF_WIDGET_TYPE_CHECKBOX
    c.rect = pymupdf.Rect(72, 110, 86, 124)
    page.add_widget(c)
    doc.save(path)
    doc.close()
    return path


def make_scan(path: Path) -> Path:
    """A page that is only an image (like a scan)."""
    src = pymupdf.open()
    p = src.new_page(width=300, height=200)
    p.insert_text((20, 100), "Scanned text", fontsize=24)
    pix = p.get_pixmap(dpi=150)
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_image(page.rect, pixmap=pix)
    doc.save(path)
    return path


@pytest.fixture
def pdf(tmp_path):
    return make_pdf(tmp_path / "sample.pdf")
