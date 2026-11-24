"""Security properties that must not regress."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pymupdf
import pytest

from conftest import make_pdf
from sheaf.core import ops
from sheaf.core.document import SheafDocument

ROOT = Path(__file__).resolve().parents[1]


def test_no_network_code():
    sys.path.insert(0, str(ROOT / "tools"))
    import check_no_network
    found = [p for f in (ROOT / "src").rglob("*.py") for p in check_no_network.problems(f)]
    assert found == []


@pytest.mark.parametrize("code, ok", [
    ("from PySide6.QtNetwork import QLocalServer, QLocalSocket", True),
    ("from PySide6.QtNetwork import QTcpSocket", False),
    ("from PySide6.QtNetwork import QLocalSocket, QNetworkAccessManager", False),
    ("import PySide6.QtNetwork", False),
    ("from PySide6 import QtNetwork", False),
])
def test_network_check_allows_only_the_local_pipe(tmp_path, code, ok):
    sys.path.insert(0, str(ROOT / "tools"))
    import check_no_network
    f = tmp_path / "m.py"
    f.write_text(code, encoding="utf-8")
    assert (check_no_network.problems(f) == []) == ok


def test_pdf_javascript_is_disabled():
    """MuPDF can run form JavaScript when built with it; this build must not."""
    doc = pymupdf.open()
    doc.new_page()
    assert pymupdf.mupdf.pdf_js_supported(pymupdf._as_pdf_document(doc)) == 0


def test_links_and_launch_actions_are_never_followed():
    """The canvas has no code path that opens a URI or launches a file from a PDF."""
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py"))
    for needle in ("openUrl", "startfile", "LINK_LAUNCH", "LINK_URI", "get_links"):
        assert needle not in src


def test_redaction_with_hidden_data_removal(tmp_path):
    src = make_pdf(tmp_path / "s.pdf")
    doc = pymupdf.open(src)
    doc.set_metadata({"author": "Secret Author", "title": "Secret title Hello"})
    doc.set_toc([[1, "Hello world chapter", 1]])
    doc.embfile_add("notes.txt", b"secret attachment")
    doc.save(tmp_path / "s2.pdf")
    d = SheafDocument.open(str(tmp_path / "s2.pdf"))
    ops.mark_redaction(d.doc[0], pymupdf.Rect(60, 80, 400, 110))

    def fn(x):
        ops.apply_redactions(x)
        ops.remove_hidden_data(x)
    d.edit("Apply", fn)
    out = tmp_path / "out.pdf"
    d.save_to(str(out))
    again = pymupdf.open(out)
    assert "Hello" not in again[0].get_text()
    assert not again.get_toc()
    assert again.embfile_count() == 0
    assert "Secret" not in str(again.metadata)
    raw = out.read_bytes()
    assert b"Secret Author" not in raw and b"secret attachment" not in raw


def test_saves_are_full_rewrites_not_incremental(pdf, tmp_path):
    """An incremental save would leave the old (possibly redacted) content in the file."""
    d = SheafDocument.open(str(pdf))
    d.rotate([0], 90)
    out = tmp_path / "o.pdf"
    d.save_to(str(out))
    assert out.read_bytes().count(b"%%EOF") == 1


def test_password_never_written_to_recovery_metadata(tmp_path):
    src = make_pdf(tmp_path / "p.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="hunter22", owner_pw="o")
    d = SheafDocument.open(str(src), lambda n, a: "hunter22")
    data = d.save_bytes()  # what a recovery copy contains
    assert b"hunter22" not in data
    assert pymupdf.open("pdf", data).needs_pass  # recovery copy stays encrypted


def test_text_box_markup_is_escaped(pdf):
    d = SheafDocument.open(str(pdf))
    payload = '<img src="x"><script>alert(1)</script>'
    d.edit("t", lambda doc: ops.add_text_box(doc[0], pymupdf.Rect(50, 300, 400, 340), payload, ops.TextStyle()))
    assert payload in d.doc[0].get_text().replace("\n", "")
