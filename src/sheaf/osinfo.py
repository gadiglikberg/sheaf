"""The few things that differ between Windows and macOS."""
from __future__ import annotations

import sys

IS_MAC = sys.platform == "darwin"
SYSTEM = "macOS" if IS_MAC else "Windows"
MOD = "⌘" if IS_MAC else "Ctrl+"  # for hints such as "Ctrl+scroll" that aren't a single shortcut


def keys(seq: str) -> str:
    """A shortcut as people see it on this system: "Ctrl+K" on Windows, "⌘K" on a Mac."""
    from PySide6.QtGui import QKeySequence
    return QKeySequence(seq).toString(QKeySequence.NativeText)
