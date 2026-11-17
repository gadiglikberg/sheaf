"""PDF editing operations.

Every function works on a pymupdf Document or Page in the page's *unrotated* PDF
coordinate space (the space PyMuPDF uses for text extraction and annotations).
The UI converts screen positions with page.derotation_matrix before calling in.
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

import pymupdf

RGB = tuple[float, float, float]

# ---------------------------------------------------------------- page structure


def rotate_pages(doc: pymupdf.Document, pages: Iterable[int], delta: int) -> None:
    for pno in pages:
        page = doc[pno]
        page.set_rotation((page.rotation + delta) % 360)


def reorder(doc: pymupdf.Document, order: Sequence[int]) -> None:
    """Rearrange pages so that new page i is old page order[i]."""
    if sorted(order) != list(range(doc.page_count)):
        raise ValueError("order must be a permutation of all pages")
    doc.select(list(order))


def move_order(count: int, pages: Sequence[int], to: int) -> list[int]:
    """Order that moves `pages` (kept in their relative order) to sit before index `to`."""
    moving = sorted(set(pages))
    rest = [i for i in range(count) if i not in moving]
    insert_at = len([i for i in rest if i < to])
    return rest[:insert_at] + moving + rest[insert_at:]


def insert_blank(doc: pymupdf.Document, at: int, like_page: int | None = None) -> None:
    if like_page is not None and 0 <= like_page < doc.page_count:
        r = doc[like_page].rect
        doc.new_page(at, width=r.width, height=r.height)
    else:
        doc.new_page(at, width=595, height=842)  # A4


def image_to_pdf(path: str) -> pymupdf.Document:
    with pymupdf.open(path) as img:
        pdf_bytes = img.convert_to_pdf()
    return pymupdf.open("pdf", pdf_bytes)


def extract_pages(doc: pymupdf.Document, pages: Sequence[int]) -> pymupdf.Document:
    out = pymupdf.open()
    for pno in pages:
        out.insert_pdf(doc, from_page=pno, to_page=pno)
    return out


def parse_ranges(text: str, page_count: int) -> list[list[int]]:
    """Parse '1-3, 5, 8-' into lists of 0-based page numbers. Raises ValueError with a readable message."""
    groups: list[list[int]] = []
    for part in [p.strip() for p in text.split(",") if p.strip()]:
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)|(\d+)", part)
        if not m:
            raise ValueError(f"'{part}' is not a page or range like 3 or 2-5.")
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else page_count
        if not (1 <= a <= page_count and 1 <= b <= page_count):
            raise ValueError(f"'{part}' is outside pages 1 to {page_count}.")
        step = 1 if b >= a else -1
        groups.append(list(range(a - 1, b - 1 + step, step)))
    if not groups:
        raise ValueError("Enter at least one page, for example 1-3, 5.")
    return groups


def split_every(page_count: int, n: int) -> list[list[int]]:
    if n < 1:
        raise ValueError("Split size must be at least 1.")
    return [list(range(i, min(i + n, page_count))) for i in range(0, page_count, n)]


# ---------------------------------------------------------------- text boxes

FONT_FAMILIES = ("Helvetica", "Times", "Courier")
_BASE14 = {  # family -> (regular, italic, bold, bold-italic) short names for measuring and drawing
    "Helvetica": ("helv", "heit", "hebo", "hebi"),
    "Times": ("tiro", "tiit", "tibo", "tibi"),
    "Courier": ("cour", "coit", "cobo", "cobi"),
}
SHEAF_TEXT_TAG = "sheaf-text"


@dataclass
class TextStyle:
    font: str = "Helvetica"
    size: float = 12.0
    color: RGB = (0.0, 0.0, 0.0)
    bold: bool = False
    italic: bool = False
    align: int = 0  # 0 left, 1 center, 2 right

    def base14(self) -> str:
        names = _BASE14.get(self.font, _BASE14["Helvetica"])
        return names[(2 if self.bold else 0) + (1 if self.italic else 0)]


def _hex(rgb: RGB) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c * 255))) for c in rgb)


def _is_latin1(text: str) -> bool:
    try:
        text.encode("latin-1")
        return True
    except UnicodeEncodeError:
        return False


def measure_text(text: str, style: TextStyle) -> tuple[float, float]:
    """Approximate (width, height) in points that a text box needs."""
    lines = text.split("\n") or [""]
    fn = style.base14()
    width = 0.0
    for line in lines:
        try:
            w = pymupdf.get_text_length(line, fontname=fn, fontsize=style.size)
        except Exception:
            w = len(line) * style.size * 0.6
        if not _is_latin1(line):
            w = max(w, len(line) * style.size * 0.6)
        width = max(width, w)
    height = len(lines) * style.size * 1.3
    return width + 8, height + 6


def add_text_box(page: pymupdf.Page, rect: pymupdf.Rect, text: str, style: TextStyle) -> pymupdf.Annot:
    """Add an editable FreeText annotation. Opens and stays editable in Acrobat, Edge and Chrome."""
    body = "<br/>".join(html.escape(line) for line in text.split("\n"))  # escape: user text is never markup
    css = (
        f"font-family:{style.font};font-size:{style.size:g}pt;color:{_hex(style.color)};"
        f"font-weight:{'bold' if style.bold else 'normal'};font-style:{'italic' if style.italic else 'normal'};"
        f"text-align:{('left', 'center', 'right')[style.align]}"
    )
    annot = page.add_freetext_annot(
        rect, f"<p>{body}</p>", richtext=True, style=css, rotate=page.rotation
    )
    meta = json.dumps({"text": text, "style": asdict(style)})
    annot.set_info(content=text, subject=f"{SHEAF_TEXT_TAG} {meta}")
    annot.update()
    return annot


def text_box_data(annot: pymupdf.Annot) -> tuple[str, TextStyle] | None:
    """Recover text and style of a text box created by Sheaf (for re-editing)."""
    subject = annot.info.get("subject", "")
    if annot.type[0] != pymupdf.PDF_ANNOT_FREE_TEXT:
        return None
    if subject.startswith(SHEAF_TEXT_TAG + " "):
        try:
            meta = json.loads(subject[len(SHEAF_TEXT_TAG) + 1:])
            s = meta.get("style", {})
            style = TextStyle(
                font=s.get("font", "Helvetica") if s.get("font") in FONT_FAMILIES else "Helvetica",
                size=float(s.get("size", 12)),
                color=tuple(float(c) for c in s.get("color", (0, 0, 0)))[:3],  # type: ignore[arg-type]
                bold=bool(s.get("bold")),
                italic=bool(s.get("italic")),
                align=int(s.get("align", 0)) % 3,
            )
            return str(meta.get("text", "")), style
        except (ValueError, TypeError):
            pass
    return annot.info.get("content", ""), TextStyle()


def replace_text_box(page: pymupdf.Page, annot_xref: int, text: str, style: TextStyle,
                     rect: pymupdf.Rect | None = None) -> pymupdf.Annot | None:
    annot = page.load_annot(annot_xref)
    if annot is None:
        return None
    r = rect or annot.rect
    page.delete_annot(annot)
    if not text.strip():
        return None
    return add_text_box(page, r, text, style)


# ---------------------------------------------------------------- annotations

def add_markup(page: pymupdf.Page, quads: list, kind: str, color: RGB) -> pymupdf.Annot | None:
    if not quads:
        return None
    adder = {
        "highlight": page.add_highlight_annot,
        "underline": page.add_underline_annot,
        "strikeout": page.add_strikeout_annot,
    }[kind]
    annot = adder(quads)
    annot.set_colors(stroke=color)
    annot.update()
    return annot


def add_note(page: pymupdf.Page, point: pymupdf.Point, text: str) -> pymupdf.Annot:
    annot = page.add_text_annot(point, text, icon="Comment")
    annot.update()
    return annot


def add_rect(page: pymupdf.Page, rect: pymupdf.Rect, color: RGB, width: float = 1.5) -> pymupdf.Annot:
    annot = page.add_rect_annot(rect)
    annot.set_colors(stroke=color)
    annot.set_border(width=width)
    annot.update()
    return annot


def add_arrow(page: pymupdf.Page, p1: pymupdf.Point, p2: pymupdf.Point, color: RGB, width: float = 1.5) -> pymupdf.Annot:
    annot = page.add_line_annot(p1, p2)
    annot.set_colors(stroke=color, fill=color)
    annot.set_border(width=width)
    annot.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_CLOSED_ARROW)
    annot.update()
    return annot


def add_ink(page: pymupdf.Page, strokes: list[list[tuple[float, float]]], color: RGB, width: float = 2.0) -> pymupdf.Annot | None:
    strokes = [s for s in strokes if len(s) >= 2]
    if not strokes:
        return None
    annot = page.add_ink_annot(strokes)
    annot.set_colors(stroke=color)
    annot.set_border(width=width)
    annot.update()
    return annot


def place_image(page: pymupdf.Page, rect: pymupdf.Rect, image_bytes: bytes) -> None:
    page.insert_image(rect, stream=image_bytes, keep_proportion=True, rotate=(-page.rotation) % 360)


STAMPS = {"check": ("zadb", "4"), "cross": ("zadb", "8")}


def add_stamp(page: pymupdf.Page, point: pymupdf.Point, kind: str, size: float = 14,
              initials: str = "", color: RGB = (0, 0, 0)) -> pymupdf.Annot | None:
    if kind in STAMPS:
        font, char = STAMPS[kind]
        rect = pymupdf.Rect(point.x, point.y - size, point.x + size * 1.2, point.y + size * 0.3)
        annot = page.add_freetext_annot(rect, char, fontname=font, fontsize=size, text_color=color,
                                        rotate=page.rotation)
        annot.update()
        return annot
    text = _dt.date.today().strftime("%d %b %Y") if kind == "date" else initials
    if not text:
        return None
    style = TextStyle(size=size * 0.85, color=color)
    w, h = measure_text(text, style)
    return add_text_box(page, pymupdf.Rect(point.x, point.y - h * 0.75, point.x + w, point.y + h * 0.25), text, style)


def delete_annot(page: pymupdf.Page, xref: int) -> None:
    annot = page.load_annot(xref)
    if annot is not None:
        page.delete_annot(annot)


def move_annot(page: pymupdf.Page, xref: int, rect: pymupdf.Rect) -> None:
    annot = page.load_annot(xref)
    if annot is None:
        return
    data = text_box_data(annot) if annot.type[0] == pymupdf.PDF_ANNOT_FREE_TEXT else None
    if data and annot.info.get("subject", "").startswith(SHEAF_TEXT_TAG):
        replace_text_box(page, xref, data[0], data[1], rect)  # rebuild so the appearance reflows
        return
    annot.set_rect(rect)
    annot.update()


FRIENDLY_KINDS = {
    "FreeText": "Text box", "Text": "Note", "Line": "Arrow", "Square": "Box", "Ink": "Drawing",
    "Highlight": "Highlight", "Underline": "Underline", "StrikeOut": "Strike out", "Circle": "Circle",
    "Stamp": "Stamp", "FileAttachment": "Attachment", "Polygon": "Shape", "PolyLine": "Line",
}


def marked_text(page: pymupdf.Page, annot: pymupdf.Annot) -> str:
    """The words a highlight, underline or strike-out covers (word centers inside its quads)."""
    v = annot.vertices or []
    quads = [pymupdf.Quad(v[i:i + 4]).rect for i in range(0, len(v) - 3, 4)]
    picked = []
    for w in page.get_text("words", sort=False):
        c = pymupdf.Rect(w[:4])
        center = pymupdf.Point((c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2)
        if any(q.contains(center) for q in quads):
            picked.append(w)
    return words_text(picked).replace("\n", " ")


def comments(doc: pymupdf.Document) -> list[dict]:
    """Annotations worth listing in the comments panel, with plain-language names."""
    out = []
    for page in doc:
        for a in page.annots():
            kind = FRIENDLY_KINDS.get(a.type[1], a.type[1])
            content = a.info.get("content", "")
            if kind in ("Highlight", "Underline", "Strike out") and not content:
                words = marked_text(page, a)
                content = f"\u201c{words[:120]}\u201d" if words else ""
            if a.type[0] == pymupdf.PDF_ANNOT_REDACT:
                kind, content = "Redaction (not applied)", content
            if a.type[0] in (pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_LINK, pymupdf.PDF_ANNOT_POPUP):
                continue
            out.append({"page": page.number, "xref": a.xref, "kind": kind, "text": content.strip(),
                        "rect": tuple(a.rect)})
    return out


# ---------------------------------------------------------------- text selection and copy

def words_in_rect(page: pymupdf.Page, rect: pymupdf.Rect) -> list[tuple]:
    words = page.get_text("words", sort=False)
    return [w for w in words if pymupdf.Rect(w[:4]).intersects(rect)]


def words_between(page: pymupdf.Page, a: pymupdf.Point, b: pymupdf.Point) -> list[tuple]:
    """Words from point a to point b in reading order, like dragging a text cursor."""
    words = page.get_text("words", sort=False)
    if not words:
        return []

    def nearest(p: pymupdf.Point) -> int:
        best, best_d = 0, float("inf")
        for i, w in enumerate(words):
            r = pymupdf.Rect(w[:4])
            if r.contains(p):
                return i
            dx = max(r.x0 - p.x, 0, p.x - r.x1)
            dy = max(r.y0 - p.y, 0, p.y - r.y1)
            d = dy * 4 + dx  # prefer the same line
            if d < best_d:
                best, best_d = i, d
        return best

    i, j = nearest(a), nearest(b)
    if i > j:
        i, j = j, i
    return words[i:j + 1]


def words_text(words: list[tuple]) -> str:
    """Join words with spaces inside a line and line breaks between lines and blocks."""
    out: list[str] = []
    prev = None
    for w in words:
        key = (w[5], w[6])  # block, line
        if prev is not None:
            out.append(" " if key == prev else "\n")
        out.append(w[4])
        prev = key
    return "".join(out)


def word_quads(words: list[tuple]) -> list[pymupdf.Quad]:
    """One quad per line, so highlights look continuous."""
    lines: dict[tuple, pymupdf.Rect] = {}
    for w in words:
        key = (w[5], w[6])
        r = pymupdf.Rect(w[:4])
        lines[key] = lines[key] | r if key in lines else r
    return [r.quad for r in lines.values()]


def search(doc: pymupdf.Document, needle: str, limit: int = 2000) -> list[tuple[int, pymupdf.Rect]]:
    hits: list[tuple[int, pymupdf.Rect]] = []
    if not needle.strip():
        return hits
    for page in doc:
        for r in page.search_for(needle):
            hits.append((page.number, r))
            if len(hits) >= limit:
                return hits
    return hits


# ---------------------------------------------------------------- edit existing text

def span_at(page: pymupdf.Page, point: pymupdf.Point) -> dict | None:
    d = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if pymupdf.Rect(span["bbox"]).contains(point) and span["text"].strip():
                    return {**span, "dir": line.get("dir", (1, 0))}
    return None


def _match_base14(span: dict) -> tuple[str, bool]:
    """Pick the closest standard font. Returns (fontname, exact_family_match)."""
    name = span.get("font", "").lower()
    flags = span.get("flags", 0)
    italic = bool(flags & 2) or "italic" in name or "oblique" in name
    bold = bool(flags & 16) or "bold" in name or "black" in name or "heavy" in name
    if flags & 8 or "courier" in name or "mono" in name or "consol" in name:
        family = "Courier"
    elif flags & 4 or "times" in name or "serif" in name and "sans" not in name or "georgia" in name or "garamond" in name:
        family = "Times"
    else:
        family = "Helvetica"
    exact = any(k in name for k in ("helvetica", "arial", "times", "courier"))
    return TextStyle(font=family, bold=bold, italic=italic).base14(), exact


def _system_font() -> str | None:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for name in ("arial.ttf", "segoeui.ttf", "tahoma.ttf"):
        p = Path(windir) / "Fonts" / name
        if p.exists():
            return str(p)
    return None


def replace_span(page: pymupdf.Page, span: dict, new_text: str) -> str | None:
    """Replace one run of existing text. Returns a warning when the original font can't be reused."""
    bbox = pymupdf.Rect(span["bbox"])
    h = bbox.height
    shrunk = pymupdf.Rect(bbox.x0 + 0.3, bbox.y0 + h * 0.3, bbox.x1 - 0.3, bbox.y1 - h * 0.3)

    # Redaction applies every pending redaction on the page, so set the user's marked
    # (not yet applied) redactions aside and put them back afterwards.
    pending = []
    for a in list(page.annots(types=[pymupdf.PDF_ANNOT_REDACT])):
        pending.append((pymupdf.Rect(a.rect), a.info.get("content", "")))
        page.delete_annot(a)
    page.add_redact_annot(shrunk)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    for r, content in pending:
        mark_redaction(page, r)

    color_int = span.get("color", 0)
    color = ((color_int >> 16 & 255) / 255, (color_int >> 8 & 255) / 255, (color_int & 255) / 255)
    size = span.get("size", 11)
    origin = pymupdf.Point(span.get("origin", (bbox.x0, bbox.y1)))
    dx, dy = span.get("dir", (1, 0))
    rotate = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}.get((round(dx), round(dy)), 0)
    fontname, exact = _match_base14(span)
    warning = None
    if not new_text:
        return None
    if _is_latin1(new_text):
        page.insert_text(origin, new_text, fontname=fontname, fontsize=size, color=color, rotate=rotate)
        if not exact:
            fam = {"h": "Helvetica", "t": "Times", "c": "Courier"}[fontname[0]]
            warning = f"The original font ({span.get('font', 'unknown')}) can't be reused; used {fam} as a close match."
    else:
        fontfile = _system_font()
        if fontfile is None:
            raise ValueError("No font with these characters was found on this computer.")
        rtl = bool(re.search(r"[\u0590-\u08ff]", new_text))
        box = pymupdf.Rect(bbox.x0 - 2, bbox.y0 - 1, max(bbox.x1, bbox.x0 + size * 0.6 * len(new_text)) + 4, bbox.y1 + size)
        page.insert_htmlbox(
            box,
            f"<p dir='{'rtl' if rtl else 'ltr'}' style='margin:0;font-size:{size:g}pt;color:{_hex(color)};"
            f"font-family:sheaffont'>{html.escape(new_text)}</p>",
            css=f"@font-face {{font-family: sheaffont; src: url({Path(fontfile).name});}}",
            archive=pymupdf.Archive(str(Path(fontfile).parent)),
            rotate=rotate,
        )
        warning = "Used a system font for these characters; it may differ slightly from the original."
    return warning


# ---------------------------------------------------------------- forms

def form_fields(page: pymupdf.Page) -> list[pymupdf.Widget]:
    return list(page.widgets())


def set_field(page: pymupdf.Page, xref: int, value) -> None:
    for w in page.widgets():
        if w.xref != xref:
            continue
        if w.field_type in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON):
            w.field_value = w.on_state() if value else "Off"
        else:
            w.field_value = value
        w.update()
        return


# ---------------------------------------------------------------- redaction

def mark_redaction(page: pymupdf.Page, rect: pymupdf.Rect) -> pymupdf.Annot:
    annot = page.add_redact_annot(rect, fill=(0, 0, 0), cross_out=True)
    annot.update()
    return annot


def pending_redactions(doc: pymupdf.Document) -> int:
    return sum(len(list(p.annots(types=[pymupdf.PDF_ANNOT_REDACT]))) for p in doc)


def apply_redactions(doc: pymupdf.Document) -> int:
    """Permanently remove text, images and drawings under every marked area.

    Comments and other annotations that overlap a redacted area are deleted too,
    so nothing under the black box survives in a note or a form field.
    """
    count = 0
    for page in doc:
        marks = [pymupdf.Rect(a.rect) for a in page.annots(types=[pymupdf.PDF_ANNOT_REDACT])]
        if not marks:
            continue
        for a in list(page.annots()):
            if a.type[0] == pymupdf.PDF_ANNOT_REDACT:
                continue
            if any(pymupdf.Rect(a.rect).intersects(m) for m in marks):
                page.delete_annot(a)
        for w in list(page.widgets()):
            if any(pymupdf.Rect(w.rect).intersects(m) for m in marks):
                page.delete_widget(w)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        count += len(marks)
    return count


def remove_hidden_data(doc: pymupdf.Document) -> None:
    """Strip what a reader can't see but a tool can find: document properties, XMP metadata,
    attached files, scripts, page thumbnails and invisible text. Bookmarks are removed too, since
    their titles can repeat redacted words. Form fields and visible content are kept."""
    doc.scrub(attached_files=True, clean_pages=True, embedded_files=True, hidden_text=True, javascript=True,
              metadata=True, redactions=False, remove_links=False, reset_fields=False, reset_responses=True,
              thumbnails=True, xml_metadata=True)
    doc.set_toc([])
    doc.set_metadata({})


# ---------------------------------------------------------------- stamping text on pages

def _visible_to_pdf(page: pymupdf.Page, p: pymupdf.Point) -> pymupdf.Point:
    return p * page.derotation_matrix


def add_page_numbers(doc: pymupdf.Document, pages: Iterable[int], fmt: str = "{n}",
                     position: str = "bottom-center", size: float = 10, start: int = 1,
                     margin: float = 28) -> None:
    pages = list(pages)
    total = doc.page_count
    for i, pno in enumerate(pages):
        page = doc[pno]
        text = fmt.replace("{n}", str(start + i)).replace("{total}", str(total))
        w = pymupdf.get_text_length(text, fontname="helv", fontsize=size)
        vr = page.rect  # visible (rotated) size
        vert, horiz = position.split("-")
        y = margin if vert == "top" else vr.height - margin + size
        x = {"left": margin, "center": (vr.width - w) / 2, "right": vr.width - margin - w}[horiz]
        page.insert_text(_visible_to_pdf(page, pymupdf.Point(x, y)), text, fontsize=size,
                         fontname="helv", color=(0.2, 0.2, 0.2), rotate=page.rotation)


def add_watermark(doc: pymupdf.Document, pages: Iterable[int], text: str, size: float = 60,
                  opacity: float = 0.15, color: RGB = (0.5, 0.5, 0.5), diagonal: bool = True) -> None:
    fontname = "hebo"
    for pno in pages:
        page = doc[pno]
        vr = page.rect
        fs = size
        w = pymupdf.get_text_length(text, fontname=fontname, fontsize=fs)
        max_w = (vr.width ** 2 + vr.height ** 2) ** 0.5 * 0.8 if diagonal else vr.width * 0.9
        if w > max_w:
            fs = fs * max_w / w
            w = max_w
        center = _visible_to_pdf(page, pymupdf.Point(vr.width / 2, vr.height / 2))
        # Lay the text out horizontally around the center (unrotated space), then rotate it into place.
        start = pymupdf.Point(center.x - w / 2, center.y + fs * 0.35)
        angle = page.rotation + (45 if diagonal else 0)
        page.insert_text(start, text, fontsize=fs, fontname=fontname, color=color,
                         fill_opacity=opacity, morph=(center, pymupdf.Matrix(angle)), overlay=True)


# ---------------------------------------------------------------- compress, export, OCR

COMPRESS_LEVELS = {
    "low": None,  # lossless clean-up only
    "medium": dict(dpi_threshold=200, dpi_target=150, quality=75),
    "high": dict(dpi_threshold=120, dpi_target=96, quality=55),
}


def compress(doc: pymupdf.Document, level: str) -> pymupdf.Document:
    """Return a compressed copy; the caller decides whether to keep it."""
    save = dict(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True, use_objstms=1)
    original = doc.tobytes(garbage=4, deflate=True, use_objstms=1)
    candidates = [original]
    lossless = pymupdf.open("pdf", doc.tobytes())
    try:
        lossless.subset_fonts()
    except Exception:
        pass
    candidates.append(lossless.tobytes(**save))
    opts = COMPRESS_LEVELS[level]
    if opts:
        lossy = pymupdf.open("pdf", candidates[-1])
        lossy.rewrite_images(**opts)
        candidates.append(lossy.tobytes(**save))
    # Never hand back something bigger than what we started with.
    return pymupdf.open("pdf", min(candidates, key=len))


def export_images(doc: pymupdf.Document, pages: Sequence[int], folder: str, base: str,
                  fmt: str = "png", dpi: int = 150) -> list[str]:
    fmt = fmt.lower()
    if fmt not in ("png", "jpg"):
        raise ValueError("Format must be PNG or JPG.")
    safe_base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .") or "page"
    out = []
    width = len(str(doc.page_count))
    for pno in pages:
        pix = doc[pno].get_pixmap(dpi=dpi, alpha=False)
        path = os.path.join(folder, f"{safe_base}-{pno + 1:0{width}d}.{fmt}")
        if fmt == "jpg":
            pix.save(path, jpg_quality=90)
        else:
            pix.save(path)
        out.append(path)
    return out


class OcrUnavailable(Exception):
    pass


def tessdata_dir() -> str | None:
    env = os.environ.get("TESSDATA_PREFIX")
    if env and Path(env).is_dir():
        return env
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")):
        if base and (Path(base) / "Tesseract-OCR" / "tessdata").is_dir():
            return str(Path(base) / "Tesseract-OCR" / "tessdata")
    return None


def ocr_languages() -> list[str]:
    td = tessdata_dir()
    if not td:
        return []
    return sorted(p.stem for p in Path(td).glob("*.traineddata") if p.stem != "osd")


def page_needs_ocr(page: pymupdf.Page) -> bool:
    return len(page.get_text("text").strip()) < 20 and bool(page.get_images())


def ocr_pages(doc: pymupdf.Document, pages: Sequence[int], language: str = "eng",
              progress: Callable[[int, int], bool] | None = None) -> int:
    """Add an invisible, searchable text layer to scanned pages. Runs fully offline."""
    td = tessdata_dir()
    if not td:
        raise OcrUnavailable("Text recognition needs Tesseract OCR installed on this computer.")
    fontfile = _system_font()
    done = 0
    for i, pno in enumerate(pages):
        if progress and not progress(i, len(pages)):
            break
        page = doc[pno]
        if not page_needs_ocr(page):
            continue
        tp = page.get_textpage_ocr(dpi=300, full=True, language=language, tessdata=td)
        words = page.get_text("words", textpage=tp)
        latin_font_ok = True
        for w in words:
            r = pymupdf.Rect(w[:4])
            word = w[4]
            if r.is_empty or not word.strip():
                continue
            if _is_latin1(word):
                kw = dict(fontname="helv")
            elif fontfile:
                kw = dict(fontname="sheafocr", fontfile=fontfile)
            else:
                latin_font_ok = False
                continue
            length = pymupdf.get_text_length(word, fontname="helv", fontsize=1) or 0.5 * len(word)
            fs = max(1.0, min(r.height * 0.9, r.width / length))
            page.insert_text(pymupdf.Point(r.x0, r.y1 - r.height * 0.2), word, fontsize=fs,
                             render_mode=3, **kw)
        done += 1 if latin_font_ok or words else 0
    if progress:
        progress(len(pages), len(pages))
    return done
