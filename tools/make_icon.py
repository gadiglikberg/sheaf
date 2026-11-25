"""Write assets/sheaf.ico (used for Sheaf.exe and the installer) from the icon drawn in sheaf.ui.icons.

Run after changing the icon:  python tools/make_icon.py
For the Mac app:              python tools/make_icon.py --iconset build/Sheaf.iconset
                              iconutil -c icns build/Sheaf.iconset -o build/Sheaf.icns
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sheaf.ui.icons import app_icon_image  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    app_icon_image(size).save(buf, "PNG")
    return bytes(buf.data())


def mac_image(size: int) -> QImage:
    """Mac icons leave a margin around the tile (824 of 1024 pixels), so Sheaf sits well beside other apps."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    inner = round(size * 824 / 1024 * 256 / 240)  # the drawn tile fills 240 of its 256 pixels
    p = QPainter(img)
    p.drawImage((size - inner) // 2, (size - inner) // 2, app_icon_image(inner))
    p.end()
    return img


def write_iconset(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        mac_image(base).save(str(folder / f"icon_{base}x{base}.png"))
        mac_image(base * 2).save(str(folder / f"icon_{base}x{base}@2x.png"))
    print("wrote", folder)


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    if len(sys.argv) == 3 and sys.argv[1] == "--iconset":
        write_iconset(Path(sys.argv[2]))
        return
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
