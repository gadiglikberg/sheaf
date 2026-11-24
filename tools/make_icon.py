"""Write assets/sheaf.ico (used for Sheaf.exe and the installer) from the icon drawn in sheaf.ui.icons.

Run after changing the icon:  python tools/make_icon.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sheaf.ui.icons import app_icon_image  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    app_icon_image(size).save(buf, "PNG")
    return bytes(buf.data())


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    images = [png_bytes(s) for s in SIZES]
    out = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    for size, data in zip(SIZES, images):
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out += b"".join(images)
    target = ROOT / "assets" / "sheaf.ico"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(out)
    print("wrote", target, len(out), "bytes")


if __name__ == "__main__":
    main()
