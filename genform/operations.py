from __future__ import annotations

import contextvars
import threading
import uuid
from contextlib import contextmanager


CURRENT_OPERATION = contextvars.ContextVar('genform_operation', default=None)


class Operation:
    def __init__(self, identifier=None):
        self.identifier = identifier if identifier is not None else uuid.uuid4().hex
        self.transport_id = uuid.uuid4().hex
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.started = False
        self.reason = '请求已取消'
        self.code = 'cancelled'
        self.result = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self.cancelled.is_set() or self.finished.is_set():
                return False
            self.started = True
            return True

    def cancel(self, reason='请求已取消', code='cancelled'):
        with self._lock:
            if self.finished.is_set() or self.cancelled.is_set():
                return False
            self.reason, self.code = reason, code
            self.cancelled.set()
            return True

    def failure(self):
        return {'ok': False, 'error': self.reason, 'code': self.code,
                'request_id': self.identifier, 'started': self.started,
                'hint': '已请求取消计算；文档修改可能已经发生，请检查模型状态，不要直接重发。'}

    def __call__(self, result):
        with self._lock:
            if self.finished.is_set():
                return False
            self.result = self.failure() if self.cancelled.is_set() else result
            self.finished.set()
            return True


@contextmanager
def operation_scope(operation):
    token = CURRENT_OPERATION.set(operation)
    try:
        yield
    finally:
        CURRENT_OPERATION.reset(token)
