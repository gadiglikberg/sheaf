"""The open document: a pymupdf Document plus undo history, sources and protection settings."""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pymupdf

from . import fileio, ops

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
UNDO_MEMORY_LIMIT = 1024 ** 3  # total bytes kept for undo snapshots
UNDO_MAX_STEPS = 100


class OpenCancelled(Exception):
    """The user declined to enter a password."""


class OpenFailed(Exception):
    pass


@dataclass
class Protection:
    user_pw: str
    owner_pw: str
    permissions: int = -1  # -1 = everything allowed

    @property
    def needs_password(self) -> bool:
        return bool(self.user_pw)


PasswordPrompt = Callable[[str, int], "str | None"]  # (file name, attempt) -> password or None


def load_pdf(path: str, ask_password: PasswordPrompt | None) -> tuple[pymupdf.Document, Protection | None]:
    """Open a PDF or image from disk into memory, unlocked. Never touches the original file."""
    p = Path(path)
    try:
        data = fileio.read_bytes(p)
    except fileio.FileTooLarge as e:
        raise OpenFailed(str(e)) from e
    except OSError as e:
        raise OpenFailed(f"Couldn't read {p.name}: {e.strerror or e}") from e

    if p.suffix.lower() in IMAGE_SUFFIXES:
        try:
            with pymupdf.open(stream=data, filetype=p.suffix.lower().lstrip(".")) as img:
                return pymupdf.open("pdf", img.convert_to_pdf()), None
        except Exception as e:
            raise OpenFailed(f"{p.name} isn't an image Sheaf can read.") from e

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        raise OpenFailed(f"{p.name} isn't a PDF Sheaf can read. It may be damaged.") from e
    if not doc.is_pdf or doc.page_count == 0:
        raise OpenFailed(f"{p.name} has no pages Sheaf can show.")

    protection = None
    if doc.needs_pass:
        attempt = 0
        while True:
            pw = ask_password(p.name, attempt) if ask_password else None
            if pw is None:
                raise OpenCancelled()
            if doc.authenticate(pw):
                break
            attempt += 1
        protection = Protection(user_pw=pw, owner_pw=pw, permissions=doc.permissions)
    elif (doc.metadata or {}).get("encryption"):
        # Restrictions only (no open password). Keep the same restrictions when saving.
        protection = Protection(user_pw="", owner_pw=secrets.token_urlsafe(24), permissions=doc.permissions)

    if protection:
        plain = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE)
        doc.close()
        doc = pymupdf.open("pdf", plain)
    return doc, protection


class SheafDocument:
    def __init__(self, doc: pymupdf.Document, path: str | None = None,
                 protection: Protection | None = None, source_label: str = "Untitled"):
        self.doc = doc
        self.path = path  # the file this document was opened from
        self.save_path: str | None = None  # where Ctrl+S writes; set after the first Save as
        self.protection = protection
        self.page_sources: list[int] = [0] * doc.page_count  # index into self.sources per page
        self.sources: list[str] = [source_label]
        self._undo: list[tuple[str, tuple]] = []
        self._redo: list[tuple[str, tuple]] = []
        self.dirty = False
        self.listeners: list[Callable[[str], None]] = []

    # ------------------------------------------------------------ open / save

    @classmethod
    def open(cls, path: str, ask_password: PasswordPrompt | None = None) -> "SheafDocument":
        doc, protection = load_pdf(path, ask_password)
        sd = cls(doc, path=path, protection=protection, source_label=Path(path).name)
        if Path(path).suffix.lower() in IMAGE_SUFFIXES:
            sd.path = None  # an image becomes a new, unsaved PDF
            sd.dirty = True
        return sd

    @property
    def title(self) -> str:
        p = self.save_path or self.path
        return Path(p).name if p else "Untitled.pdf"

    def save_bytes(self) -> bytes:
        opts = dict(garbage=4, deflate=True, use_objstms=1)  # garbage=4 drops removed content for good
        prot = self.protection
        if prot:
            opts.update(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=prot.user_pw,
                        owner_pw=prot.owner_pw or secrets.token_urlsafe(24))
            if prot.permissions != -1:
                opts["permissions"] = prot.permissions
        return self.doc.tobytes(**opts)

    def save_to(self, path: str) -> None:
        fileio.atomic_write(path, self.save_bytes())
        self.save_path = path
        self.dirty = False
        self._notify("saved")

    def needs_save_as(self) -> bool:
        """Ctrl+S on a file opened from disk asks where to save, so originals aren't overwritten by accident."""
        return self.save_path is None

    # ------------------------------------------------------------ undo

    def _snapshot(self) -> tuple:
        return (self.doc.tobytes(), list(self.page_sources), list(self.sources), self.protection)

    def _restore(self, snap: tuple) -> None:
        data, page_sources, sources, protection = snap
        old = self.doc
        self.doc = pymupdf.open("pdf", data)
        self.page_sources, self.sources, self.protection = list(page_sources), list(sources), protection
        if old is not self.doc:
            old.close()

    def _trim_undo(self) -> None:
        while len(self._undo) > UNDO_MAX_STEPS or (
            len(self._undo) > 1 and sum(len(s[1][0]) for s in self._undo) > UNDO_MEMORY_LIMIT
        ):
            self._undo.pop(0)

    def edit(self, label: str, fn: Callable[[pymupdf.Document], object], structure: bool = False):
        """Run fn on the document as one undoable step. Restores the document if fn fails."""
        snap = self._snapshot()
        try:
            result = fn(self.doc)
        except BaseException:
            self._restore(snap)
            raise
        self._undo.append((label, snap))
        self._redo.clear()
        self._trim_undo()
        self.dirty = True
        self._notify("structure" if structure else "content")
        return result

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_label(self) -> str:
        return self._undo[-1][0] if self._undo else ""

    def redo_label(self) -> str:
        return self._redo[-1][0] if self._redo else ""

    def undo(self) -> None:
        if not self._undo:
            return
        label, snap = self._undo.pop()
        self._redo.append((label, self._snapshot()))
        self._restore(snap)
        self.dirty = True
        self._notify("structure")

    def redo(self) -> None:
        if not self._redo:
            return
        label, snap = self._redo.pop()
        self._undo.append((label, self._snapshot()))
        self._restore(snap)
        self.dirty = True
        self._notify("structure")

    def _notify(self, what: str) -> None:
        for fn in list(self.listeners):
            fn(what)

    # ------------------------------------------------------------ page structure (keeps sources in step)

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def rotate(self, pages: list[int], delta: int) -> None:
        self.edit("Rotate", lambda d: ops.rotate_pages(d, pages, delta))

    def delete(self, pages: list[int]) -> None:
        pages = sorted(set(pages))
        if len(pages) >= self.page_count:
            raise ValueError("A PDF needs at least one page. Use Extract to keep only some pages.")

        def fn(d):
            d.delete_pages(pages)
            self.page_sources = [s for i, s in enumerate(self.page_sources) if i not in pages]
        self.edit("Delete pages", fn, structure=True)

    def reorder(self, order: list[int]) -> None:
        if order == list(range(self.page_count)):
            return

        def fn(d):
            ops.reorder(d, order)
            self.page_sources = [self.page_sources[i] for i in order]
        self.edit("Reorder pages", fn, structure=True)

    def move_pages(self, pages: list[int], to: int) -> list[int]:
        order = ops.move_order(self.page_count, pages, to)
        self.reorder(order)
        moved = sorted(set(pages))
        return [order.index(p) for p in moved]

    def insert_file(self, path: str, at: int, ask_password: PasswordPrompt | None = None) -> int:
        src, _ = load_pdf(path, ask_password)
        label = Path(path).name
        n = src.page_count

        def fn(d):
            d.insert_pdf(src, start_at=at)
            self.sources.append(label)
            idx = len(self.sources) - 1
            self.page_sources[at:at] = [idx] * n
        try:
            self.edit(f"Insert {label}", fn, structure=True)
        finally:
            src.close()
        return n

    def insert_blank(self, at: int) -> None:
        def fn(d):
            ops.insert_blank(d, at, like_page=min(at, d.page_count - 1) if d.page_count else None)
            self.page_sources[at:at] = [self.page_sources[at - 1] if at > 0 and self.page_sources else 0]
        self.edit("Insert blank page", fn, structure=True)

    def extract(self, pages: list[int]) -> bytes:
        out = ops.extract_pages(self.doc, pages)
        try:
            prot = self.protection
            opts = dict(garbage=4, deflate=True)
            if prot:
                opts.update(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=prot.user_pw,
                            owner_pw=prot.owner_pw or secrets.token_urlsafe(24))
            return out.tobytes(**opts)
        finally:
            out.close()

    def replace_with(self, label: str, new_doc: pymupdf.Document) -> None:
        """Swap in a transformed copy (for example after compression) as one undoable step."""
        data = new_doc.tobytes()
        new_doc.close()

        def fn(_d):
            self.doc = pymupdf.open("pdf", data)  # the old document stays alive in the undo snapshot bytes
        self.edit(label, fn, structure=True)

    # ------------------------------------------------------------ protection

    def set_password(self, password: str) -> None:
        def fn(_d):
            self.protection = Protection(user_pw=password, owner_pw=secrets.token_urlsafe(24))
        self.edit("Add password", fn)

    def remove_password(self) -> None:
        def fn(_d):
            self.protection = None
        self.edit("Remove password", fn)
