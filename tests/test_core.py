from __future__ import annotations

import hashlib
import os

import pymupdf
import pytest

from conftest import make_form, make_pdf, make_scan
from sheaf.core import fileio, ops
from sheaf.core.document import OpenCancelled, OpenFailed, SheafDocument


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def text_of(doc, pno=0):
    return doc[pno].get_text()


# ------------------------------------------------------------ files

def test_open_never_modifies_original(pdf, tmp_path):
    before = sha(pdf)
    d = SheafDocument.open(str(pdf))
    d.rotate([0], 90)
    d.save_to(str(tmp_path / "out.pdf"))
    assert sha(pdf) == before
    assert d.needs_save_as() is False


def test_ctrl_s_needs_save_as_for_opened_file(pdf):
    assert SheafDocument.open(str(pdf)).needs_save_as()


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "x.pdf"
    fileio.atomic_write(target, b"%PDF-1.7 test")
    assert target.read_bytes() == b"%PDF-1.7 test"
    assert [p.name for p in tmp_path.iterdir()] == ["x.pdf"]


def test_open_garbage_fails_cleanly(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pytest.raises(OpenFailed):
        SheafDocument.open(str(bad))


def test_open_image_becomes_pdf(tmp_path):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 40), False)
    pix.clear_with(200)
    img = tmp_path / "pic.png"
    pix.save(img)
    d = SheafDocument.open(str(img))
    assert d.page_count == 1 and d.path is None and d.dirty


# ------------------------------------------------------------ pages

def test_rotate_delete_reorder_undo_redo(tmp_path):
    d = SheafDocument.open(str(make_pdf(tmp_path / "a.pdf", pages=4)))
    d.rotate([1], 90)
    assert d.doc[1].rotation == 90
    d.delete([0])
    assert d.page_count == 3 and "Page 2" in text_of(d.doc, 0)
    d.move_pages([2], 0)
    assert "Page 4" in text_of(d.doc, 0)
    d.undo()
    assert "Page 2" in text_of(d.doc, 0)
    d.undo()
    assert d.page_count == 4
    d.redo()
    assert d.page_count == 3


def test_cannot_delete_every_page(pdf):
    d = SheafDocument.open(str(pdf))
    with pytest.raises(ValueError):
        d.delete([0, 1, 2])
    assert d.page_count == 3


def test_merge_tracks_sources(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", pages=2, text="A{n}")
    b = make_pdf(tmp_path / "b.pdf", pages=3, text="B{n}")
    d = SheafDocument.open(str(a))
    d.insert_file(str(b), at=1)
    assert d.page_count == 5
    assert [d.sources[i] for i in d.page_sources] == ["a.pdf", "b.pdf", "b.pdf", "b.pdf", "a.pdf"]
    assert "B1" in text_of(d.doc, 1)
    d.undo()
    assert d.page_count == 2 and d.sources == ["a.pdf"]


def test_move_order():
    assert ops.move_order(5, [3], 0) == [3, 0, 1, 2, 4]
    assert ops.move_order(5, [0, 1], 5) == [2, 3, 4, 0, 1]


def test_parse_ranges_and_split():
    assert ops.parse_ranges("1-3, 5", 6) == [[0, 1, 2], [4]]
    assert ops.parse_ranges("4-", 6) == [[3, 4, 5]]
    with pytest.raises(ValueError):
        ops.parse_ranges("9", 6)
    with pytest.raises(ValueError):
        ops.parse_ranges("abc", 6)
    assert ops.split_every(5, 2) == [[0, 1], [2, 3], [4]]


def test_extract(pdf):
    d = SheafDocument.open(str(pdf))
    out = pymupdf.open("pdf", d.extract([2, 0]))
    assert out.page_count == 2 and "Page 3" in out[0].get_text()


def test_insert_blank(pdf):
    d = SheafDocument.open(str(pdf))
    d.insert_blank(1)
    assert d.page_count == 4 and d.doc[1].get_text().strip() == ""


# ------------------------------------------------------------ text

def test_copy_text_reading_order(pdf):
    d = SheafDocument.open(str(pdf))
    page = d.doc[0]
    words = ops.words_between(page, pymupdf.Point(70, 95), pymupdf.Point(400, 128))
    assert ops.words_text(words) == "Page 1 Hello world\nSecond line of text here"


def test_text_box_round_trip_and_escaping(pdf, tmp_path):
    d = SheafDocument.open(str(pdf))
    style = ops.TextStyle(font="Times", size=14, color=(0.8, 0, 0), bold=True, align=1)
    text = "Signed by <b>me</b>\n& second line"
    d.edit("Add text", lambda doc: ops.add_text_box(doc[0], pymupdf.Rect(100, 300, 400, 360), text, style))
    out = tmp_path / "t.pdf"
    d.save_to(str(out))
    again = pymupdf.open(out)
    page0 = again[0]
    annot = next(page0.annots())
    got_text, got_style = ops.text_box_data(annot)
    assert got_text == text and got_style.font == "Times" and got_style.bold and got_style.align == 1
    assert "Signed by <b>me</b>" in again[0].get_text()  # literal, not bold markup


def test_edit_existing_text_keeps_pending_redactions(pdf):
    d = SheafDocument.open(str(pdf))
    page = d.doc[0]
    ops.mark_redaction(page, pymupdf.Rect(72, 115, 300, 135))  # over the second line, not applied
    span = ops.span_at(page, pymupdf.Point(80, 95))
    assert span and "Hello" in span["text"]
    d.edit("Edit text", lambda doc: ops.replace_span(doc[0], span, "Page 1 Howdy world"))
    t = d.doc[0].get_text()
    assert "Howdy" in t and "Hello" not in t
    assert "Second line" in t  # the marked redaction was not applied
    assert ops.pending_redactions(d.doc) == 1


def test_edit_text_warns_on_unknown_font():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello", fontname="helv")
    span = ops.span_at(page, pymupdf.Point(75, 68))
    span["font"] = "SomeCustomFont"
    warning = ops.replace_span(page, span, "Hi there")
    assert warning and "close match" in warning
    assert "Hi there" in page.get_text()


def test_markup_and_comments(pdf):
    d = SheafDocument.open(str(pdf))
    page = d.doc[0]
    words = ops.words_between(page, pymupdf.Point(70, 95), pymupdf.Point(200, 95))
    ops.add_markup(page, ops.word_quads(words), "highlight", (1, 0.9, 0))
    ops.add_note(page, pymupdf.Point(300, 300), "Check this")
    ops.add_arrow(page, pymupdf.Point(10, 10), pymupdf.Point(100, 100), (1, 0, 0))
    ops.add_ink(page, [[(10, 10), (20, 20), (30, 10)]], (0, 0, 1))
    ops.add_stamp(page, pymupdf.Point(400, 400), "check")
    ops.add_stamp(page, pymupdf.Point(400, 450), "date")
    kinds = [c["kind"] for c in ops.comments(d.doc)]
    assert {"Highlight", "Note", "Arrow", "Drawing", "Text box"} <= set(kinds)


def test_search(pdf):
    d = SheafDocument.open(str(pdf))
    hits = ops.search(d.doc, "hello")
    assert [p for p, _ in hits] == [0, 1, 2]


# ------------------------------------------------------------ forms and signatures

def test_fill_form(tmp_path):
    d = SheafDocument.open(str(make_form(tmp_path / "f.pdf")))
    page = d.doc[0]
    fields = {w.field_name: w.xref for w in ops.form_fields(page)}
    d.edit("Fill", lambda doc: (ops.set_field(doc[0], fields["name"], "Dana Levi"),
                                ops.set_field(doc[0], fields["agree"], True)))
    out = tmp_path / "filled.pdf"
    d.save_to(str(out))
    vals = {w.field_name: w.field_value for w in pymupdf.open(out)[0].widgets()}
    assert vals["name"] == "Dana Levi" and vals["agree"] not in ("Off", "", None)


def test_place_signature_image(pdf):
    d = SheafDocument.open(str(pdf))
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 20), True)
    pix.clear_with(0)
    d.edit("Sign", lambda doc: ops.place_image(doc[0], pymupdf.Rect(100, 500, 250, 550), pix.tobytes("png")))
    assert d.doc[0].get_images()


# ------------------------------------------------------------ redaction

def test_redaction_removes_text_for_good(pdf, tmp_path):
    d = SheafDocument.open(str(pdf))
    page = d.doc[0]
    ops.add_note(page, pymupdf.Point(100, 98), "secret note")
    ops.mark_redaction(page, pymupdf.Rect(60, 80, 400, 110))
    d.edit("Apply", lambda doc: ops.apply_redactions(doc))
    out = tmp_path / "r.pdf"
    d.save_to(str(out))
    again = pymupdf.open(out)
    assert "Hello" not in again[0].get_text()
    assert not again[0].search_for("Page 1")
    assert "secret note" not in str([a.info for a in again[0].annots()])
    assert "Second line" in again[0].get_text() and "Hello" in again[1].get_text()  # only the marked area


# ------------------------------------------------------------ passwords

def test_protected_file_open_and_save(tmp_path):
    src = make_pdf(tmp_path / "p.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256,
                   user_pw="open-sesame", owner_pw="owner")
    with pytest.raises(OpenCancelled):
        SheafDocument.open(str(src), lambda name, attempt: None)
    attempts = []

    def ask(name, attempt):
        attempts.append(attempt)
        return "wrong" if attempt == 0 else "open-sesame"
    d = SheafDocument.open(str(src), ask)
    assert attempts == [0, 1] and d.protection.user_pw == "open-sesame"
    out = tmp_path / "still-locked.pdf"
    d.save_to(str(out))
    assert pymupdf.open(out).needs_pass
    d.remove_password()
    out2 = tmp_path / "unlocked.pdf"
    d.save_to(str(out2))
    assert not pymupdf.open(out2).is_encrypted
    d.undo()
    assert d.protection is not None


def test_add_password(pdf, tmp_path):
    d = SheafDocument.open(str(pdf))
    d.set_password("pw123")
    out = tmp_path / "locked.pdf"
    d.save_to(str(out))
    doc = pymupdf.open(out)
    assert doc.needs_pass and doc.authenticate("pw123")


def test_restrictions_only_kept(tmp_path):
    src = make_pdf(tmp_path / "r.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner",
                   permissions=pymupdf.PDF_PERM_ACCESSIBILITY)
    d = SheafDocument.open(str(src))
    out = tmp_path / "r2.pdf"
    d.save_to(str(out))
    again = pymupdf.open(out)
    assert again.metadata.get("encryption") and not again.needs_pass


def test_extract_keeps_protection(tmp_path):
    src = make_pdf(tmp_path / "p.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    d = SheafDocument.open(str(src), lambda n, a: "x")
    assert pymupdf.open("pdf", d.extract([0])).needs_pass


# ------------------------------------------------------------ stamping, compress, export, OCR

def test_page_numbers_upright_on_rotated_page(tmp_path):
    d = SheafDocument.open(str(make_pdf(tmp_path / "a.pdf", pages=2)))
    d.rotate([1], 90)
    d.edit("Numbers", lambda doc: ops.add_page_numbers(doc, range(doc.page_count), fmt="Page {n} of {total}"))
    for pno in range(2):
        page = d.doc[pno]
        assert f"Page {pno + 1} of 2" in page.get_text()
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                if "of 2" in "".join(s["text"] for s in line["spans"]):
                    m, (dx, dy) = page.rotation_matrix, line["dir"]
                    vx, vy = m.a * dx + m.c * dy, m.b * dx + m.d * dy  # direction as seen on screen
                    assert round(vx) == 1 and round(vy) == 0  # reads left to right


def test_watermark(pdf):
    d = SheafDocument.open(str(pdf))
    d.edit("Watermark", lambda doc: ops.add_watermark(doc, range(doc.page_count), "DRAFT"))
    assert "DRAFT" in d.doc[0].get_text()


def test_compress_keeps_pages(tmp_path):
    d = SheafDocument.open(str(make_scan(tmp_path / "s.pdf")))
    before = len(d.save_bytes())
    small = ops.compress(d.doc, "high")
    d.replace_with("Compress", small)
    assert d.page_count == 1 and len(d.save_bytes()) <= before
    d.undo()
    assert d.page_count == 1


def test_export_images_sanitizes_names(pdf, tmp_path):
    d = SheafDocument.open(str(pdf))
    paths = ops.export_images(d.doc, [0, 2], str(tmp_path), '../evil:name', fmt="jpg", dpi=50)
    assert [os.path.basename(p) for p in paths] == ["_evil_name-1.jpg", "_evil_name-3.jpg"]
    assert all(os.path.dirname(p) == str(tmp_path) for p in paths)


def test_ocr_unavailable_without_tesseract(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "tessdata_dir", lambda: None)
    d = SheafDocument.open(str(make_scan(tmp_path / "s.pdf")))
    assert ops.page_needs_ocr(d.doc[0])
    with pytest.raises(ops.OcrUnavailable):
        ops.ocr_pages(d.doc, [0])


def test_failed_edit_rolls_back(pdf):
    d = SheafDocument.open(str(pdf))

    def boom(doc):
        doc.delete_page(0)
        raise RuntimeError("fail midway")
    with pytest.raises(RuntimeError):
        d.edit("Broken", boom)
    assert d.page_count == 3 and not d.can_undo()


def test_highlight_comment_quotes_exact_words(pdf):
    d = SheafDocument.open(str(pdf))
    page = d.doc[0]
    words = [w for w in page.get_text("words") if w[4] in ("Hello", "world")]
    ops.add_markup(page, ops.word_quads(words), "highlight", (1, 1, 0))
    texts = [c["text"] for c in ops.comments(d.doc) if c["kind"] == "Highlight"]
    assert texts == ["“Hello world”"]
