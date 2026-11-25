"""Write a version number into src/sheaf/__init__.py. The Release workflow uses it to stamp a build.

    python tools/set_version.py 1.1.1
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

INIT = Path(__file__).resolve().parents[1] / "src" / "sheaf" / "__init__.py"


def main() -> None:
    version = sys.argv[1]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"Not a version number: {version!r}")
    text = INIT.read_text(encoding="utf-8")
    INIT.write_text(re.sub(r'__version__ = "[^"]*"', f'__version__ = "{version}"', text), encoding="utf-8")
    print("version", version)


if __name__ == "__main__":
    main()
