"""Fail if Sheaf's source imports anything that can reach the network or run other programs.

Sheaf promises that files never leave the computer. This check runs in CI on every pull request,
so the promise can be verified by anyone, not just trusted.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

BANNED_MODULES = {
    "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
    "poplib", "imaplib", "telnetlib", "xmlrpc", "websocket", "websockets", "subprocess", "webbrowser",
    "PySide6.QtNetwork", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
}
# The one exception: Qt's local pipe between two Sheaf processes on the same computer ("Open with" hands files to
# the window that is already open). These classes cannot connect to the network. Every other QtNetwork name stays
# banned, as does importing the module as a whole.
ALLOWED_FROM = {"PySide6.QtNetwork": {"QLocalServer", "QLocalSocket"}}
BANNED_NAMES = {"QDesktopServices", "QNetworkAccessManager", "QProcess", "system", "popen", "startfile"}


def problems(path: Path) -> list[str]:
    out = []
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            allowed = ALLOWED_FROM.get(node.module, set())
            if allowed and all(a.name in allowed for a in node.names):
                continue
            mods = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            out += [f"{path}:{node.lineno}: imports {a.name}" for a in node.names if a.name in BANNED_NAMES]
        for m in mods:
            if any(m == b or m.startswith(b + ".") for b in BANNED_MODULES):
                out.append(f"{path}:{node.lineno}: imports {m}")
        if isinstance(node, ast.Attribute) and node.attr in BANNED_NAMES and isinstance(node.value, ast.Name) \
                and node.value.id in ("os", "QDesktopServices"):
            out.append(f"{path}:{node.lineno}: calls {node.value.id}.{node.attr}")
    return out


def main() -> int:
    root = Path(__file__).resolve().parents[1] / "src"
    found = [p for f in sorted(root.rglob("*.py")) for p in problems(f)]
    for line in found:
        print(line)
    print("OK: no network or process-launching code found." if not found else f"{len(found)} problem(s).")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
