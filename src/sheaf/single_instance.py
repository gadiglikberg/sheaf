"""One Sheaf window: a second launch (for example "Open with Sheaf" in Explorer) hands its files to the window
that is already open, then exits.

The hand-over uses Qt's QLocalServer and QLocalSocket: a named pipe on Windows, a local socket file on a Mac. These
connect programs on the same computer only and cannot reach the network. They accept the current user only,
messages are size limited, and the running window only opens paths that exist as files. (On a Mac, Finder itself
sends files to the running app, so this mostly matters on Windows.)
"""
from __future__ import annotations

import getpass
import hashlib
import json
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

MAX_MESSAGE = 256 * 1024


def default_name() -> str:
    return "sheaf-" + hashlib.sha256(getpass.getuser().encode("utf-8")).hexdigest()[:16]


def allow_foreground() -> None:
    """Let the running window come to the front when it receives our files (Windows only grants that to the
    program the user just started, which is this one)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except (AttributeError, OSError):
            pass


class Instance(QObject):
    filesReceived = Signal(list)

    def __init__(self, lock_dir: Path, name: str | None = None):
        super().__init__()
        self.name = name or default_name()
        self.lock = QLockFile(str(Path(lock_dir) / "running.lock"))
        self.lock.setStaleLockTime(0)  # a lock left by a crashed Sheaf is recognised by its process id instead
        self.primary = self.lock.tryLock(0)
        self.server: QLocalServer | None = None

    def send(self, paths: list[str], timeout_ms: int = 3000) -> bool:
        """Give files to the running window. False if it doesn't answer (then the caller opens its own window)."""
        data = json.dumps([str(Path(p).resolve()) for p in paths]).encode("utf-8") + b"\n"
        if len(data) > MAX_MESSAGE:
            return False
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if not sock.waitForConnected(timeout_ms):
            return False
        allow_foreground()
        sock.write(data)
        sock.flush()
        # On Windows a short message can be sent at once, and waiting would then report failure.
        if sock.bytesToWrite() and not sock.waitForBytesWritten(timeout_ms):
            return False
        reply = b""
        while not reply.endswith(b"\n"):
            if not sock.bytesAvailable() and not sock.waitForReadyRead(timeout_ms):
                break
            reply += sock.readAll().data()
        sock.disconnectFromServer()
        return reply.strip() == b"ok"

    def listen(self) -> bool:
        QLocalServer.removeServer(self.name)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        return self.server.listen(self.name)

    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            buf = bytearray()

            def read(sock=sock, buf=buf):
                buf += sock.readAll().data()
                if len(buf) > MAX_MESSAGE:
                    sock.abort()
                    return
                if not buf.endswith(b"\n"):
                    return
                try:
                    paths = json.loads(bytes(buf))
                except ValueError:
                    sock.abort()
                    return
                files = [p for p in paths if isinstance(p, str) and Path(p).is_file()] if isinstance(paths, list) else []
                sock.write(b"ok\n")  # the sender hangs up once it has read this
                sock.flush()
                if sock.bytesToWrite():
                    sock.waitForBytesWritten(1000)
                self.filesReceived.emit(files)  # an empty list just brings the window forward

            sock.readyRead.connect(read)
            sock.disconnected.connect(sock.deleteLater)
            if sock.bytesAvailable():
                read()
