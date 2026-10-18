"""单次截图的回执和取消状态，跨渲染线程传递，不依赖窗口。"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import uuid

from PySide6.QtCore import QObject, Signal


class ScreenshotRequest(QObject):
    finished = Signal(str)

    def __init__(self, path=None):
        super().__init__()
        self.path = os.fspath(path) if path else os.path.join(tempfile.gettempdir(), f'genform_view_{uuid.uuid4().hex}.png')
        self.cancelled = False
        self.done = False
        self.error = ''
        self.stopped = threading.Event()
        self.deadline = time.monotonic() + 15.0

    def start_timeout(self, milliseconds):
        self.deadline = time.monotonic() + milliseconds / 1000.0

    def cancel(self):
        self.cancelled = True
        self.stopped.set()

    def finish(self, saved=False, error=''):
        if self.cancelled or self.done:
            return False
        self.done = True
        self.error = error
        self.finished.emit(self.path if saved else '')
        return True
