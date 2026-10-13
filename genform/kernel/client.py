# -*- coding: utf-8 -*-
"""界面进程这一侧的内核客户端: 把重算交给工作进程 (worker.py), 结果回到界面线程。

- 一次只让工作进程算一件事; 它忙的时候新来的重算请求只留最新的一份 (拖着改尺寸时不排长队),
  被合并掉的请求的回调跟着最新那份一起回复 — 它们的修改都已经包含在里面了。
- 工作进程崩了: 当前请求回复错误, 自动换一个新进程, 文档不受影响。
"""
from __future__ import annotations

import multiprocessing
import threading
from collections import deque

from PySide6.QtCore import QObject, Signal

from . import worker


class ProcessBuilder(QObject):
    _arrived = Signal(int, object)          # (第几代工作进程, 消息或 None=进程没了)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs = deque()                # 等着发的: ['build'|'export', 载荷, [回调...]]
        self._flight = None                 # 正在算的: (序号, 类型, [回调...])
        self._sequence = 0
        self._generation = 0
        self._closed = False
        self._arrived.connect(self._on_arrived)
        self._start()

    def _start(self):
        self._generation += 1
        context = multiprocessing.get_context('spawn')
        self._connection, child = context.Pipe()
        self._process = context.Process(target=worker.run, args=(child,), name='genform-kernel', daemon=True)
        self._process.start()
        child.close()
        threading.Thread(target=self._read, args=(self._connection, self._generation),
                         name='kernel-reader', daemon=True).start()

    def _read(self, connection, generation):
        while True:
            try:
                message = connection.recv()
            except (EOFError, OSError):
                message = None
            try:
                self._arrived.emit(generation, message)
            except RuntimeError:            # 界面已经销毁
                return
            if message is None:
                return

    # ---- 对外 ----
    def build(self, features, upto, done):
        if self._jobs and self._jobs[-1][0] == 'build':
            self._jobs[-1][1] = (features, upto)
            self._jobs[-1][2].append(done)
        else:
            self._jobs.append(['build', (features, upto), [done]])
        self._pump()

    def export(self, features, upto, path, done):
        self._jobs.append(['export', (features, upto, path), [done]])
        self._pump()

    def outline(self, features, upto, mode, frame, done):
        self._jobs.append(['outline', (features, upto, mode, frame), [done]])
        self._pump()

    def close(self):
        self._closed = True
        try:
            self._connection.send(('quit',))
        except (OSError, ValueError):
            pass
        self._process.join(1.0)
        if self._process.is_alive():
            self._process.terminate()

    # ---- 内部 ----
    def _pump(self):
        if self._flight is not None or not self._jobs or self._closed:
            return
        kind, payload, callbacks = self._jobs.popleft()
        self._sequence += 1
        self._flight = (self._sequence, kind, callbacks)
        try:
            self._connection.send((kind, self._sequence) + tuple(payload))
        except (OSError, ValueError):
            self._lost()

    def _on_arrived(self, generation, message):
        if generation != self._generation or self._closed:
            return
        if message is None:
            self._lost()
            return
        kind, sequence, payload = message
        if self._flight is None or sequence != self._flight[0]:
            return
        _, wanted, callbacks = self._flight
        self._flight = None
        for callback in callbacks:
            if wanted == 'export':
                callback(payload)                       # None 或错误文字
            elif kind in ('built', 'outlined'):
                callback(payload, None)
            else:
                callback(None, payload)
        self._pump()

    def _lost(self):
        """工作进程没了 (崩溃或被杀): 告诉等结果的人, 换一个新进程接着干。"""
        flight, self._flight = self._flight, None
        if not self._closed:
            self._start()
        if flight is not None:
            text = '几何内核进程意外退出（已自动重启）。刚才这一步可能触发了内核缺陷，请撤销或修改参数后再试'
            for callback in flight[2]:
                callback(text) if flight[1] == 'export' else callback(None, text)
        self._pump()
