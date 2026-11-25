"""Reading and writing files safely.

Rules:
- Inputs are read fully into memory, so the original file is never locked or modified.
- Outputs are written to a temporary file in the same folder and renamed into place
  only once complete, so a crash or full disk never leaves a half-written PDF.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Refuse absurdly large inputs instead of exhausting memory.
MAX_INPUT_BYTES = 2 * 1024 ** 3  # 2 GB


class FileTooLarge(Exception):
    pass


def read_bytes(path: str | os.PathLike) -> bytes:
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_INPUT_BYTES:
        raise FileTooLarge(f"{p.name} is {size / 1024 ** 3:.1f} GB; the limit is 2 GB.")
    with open(p, "rb") as f:
        return f.read()


def atomic_write(path: str | os.PathLike, data: bytes) -> None:
    """Write data to path atomically (temp file in the same folder, then rename)."""
    target = Path(path)
    folder = target.parent
    fd, tmp = tempfile.mkstemp(prefix=".sheaf-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def same_file(a: str | os.PathLike | None, b: str | os.PathLike | None) -> bool:
    if not a or not b:
        return False
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def app_data_dir() -> Path:
    """Per-user folder for signatures, settings and recovery copies. Never synced by Sheaf."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        mac = Path.home() / "Library" / "Application Support"
        base = str(mac) if sys.platform == "darwin" else os.path.join(Path.home(), ".local", "share")
    d = Path(base) / "Sheaf"
    d.mkdir(parents=True, exist_ok=True)
    return d
