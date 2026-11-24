"""A second launch hands its files to the window that is already open."""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QElapsedTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import make_pdf  # noqa: E402
from sheaf.single_instance import Instance  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _wait(cond, ms=5000):
    t = QElapsedTimer()
    t.start()
    while not cond() and t.elapsed() < ms:
        QCoreApplication.processEvents()
    return cond()


SECOND_LAUNCH = """
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])
from sheaf.single_instance import Instance
inst = Instance(Path(sys.argv[1]), sys.argv[2])
sys.exit(0 if (not inst.primary and inst.send(sys.argv[3:])) else 1)
"""


def test_second_launch_hands_files_to_first(tmp_path):
    """Run a real second process, as Explorer's "Open with" does."""
    _app()
    name = f"sheaf-test-{uuid.uuid4().hex[:8]}"
    first = Instance(tmp_path, name)
    assert first.primary and first.listen()
    received = []
    first.filesReceived.connect(received.append)
    pdf = make_pdf(tmp_path / "a.pdf")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.Popen([sys.executable, "-c", SECOND_LAUNCH, str(tmp_path), name, str(pdf),
                             str(tmp_path / "missing.pdf")], env=env)
    assert _wait(lambda: proc.poll() is not None and received, 20000)
    assert proc.returncode == 0  # the second launch was told the files were taken
    assert [os.path.normcase(p) for p in received[0]] == [os.path.normcase(str(pdf.resolve()))]  # missing file dropped
    first.server.close()


def test_no_running_window_means_open_normally(tmp_path):
    _app()
    lonely = Instance(tmp_path, f"sheaf-test-{uuid.uuid4().hex[:8]}")
    assert lonely.primary
    assert lonely.send([], timeout_ms=300) is False


def test_lock_is_released_with_the_first_window(tmp_path):
    _app()
    name = f"sheaf-test-{uuid.uuid4().hex[:8]}"
    first = Instance(tmp_path, name)
    assert first.primary
    first.lock.unlock()
    assert Instance(tmp_path, name).primary
