from __future__ import annotations

import queue
import threading

from ..operations import Operation, operation_scope


class StdioRuntime:
    def __init__(self, backend, respond, output, timeout=290.0):
        self.backend, self.respond, self.output = backend, respond, output
        self.timeout = timeout
        self._pending = {}
        self._lock = threading.Lock()
        self._output_lock = threading.Lock()
        self._queue = queue.Queue()
        self._closed = False
        self._worker = threading.Thread(target=self._run, name='mcp-requests', daemon=True)
        self._worker.start()

    def submit(self, message):
        if not isinstance(message, dict):
            return
        if message.get('method') == 'notifications/cancelled':
            params = message.get('params') or {}
            self.cancel(params.get('requestId'))
            return
        identifier = message.get('id')
        if identifier is None or isinstance(identifier, (list, dict, bool)):
            return
        with self._lock:
            if self._closed:
                return
            if identifier in self._pending:
                return
            operation = Operation(identifier)
            timer = threading.Timer(self.timeout, self.cancel, (identifier, '请求超过总时限', 'timeout'))
            timer.daemon = True
            self._pending[identifier] = (operation, timer)
        timer.start()
        self._queue.put((operation, message))

    def _write(self, response):
        with self._output_lock:
            if not self._closed:
                self.output(response)

    def _finish(self, operation, response):
        if not operation(response):
            return
        if operation.cancelled.is_set():
            response = self._cancelled_response(operation)
        with self._lock:
            entry = self._pending.pop(operation.identifier, None)
        if entry is not None:
            entry[1].cancel()
        self._write(response)

    @staticmethod
    def _cancelled_response(operation):
        return {'jsonrpc': '2.0', 'id': operation.identifier,
                'error': {'code': -32800 if operation.code == 'cancelled' else -32000,
                          'message': operation.reason,
                          'data': {'code': operation.code, 'started': operation.started,
                                   'hint': '文档修改可能已经发生，请先检查模型，不要直接重发。'}}}

    def cancel(self, identifier, reason='调用方已取消请求', code='cancelled', silent=False):
        if isinstance(identifier, (list, dict)):
            return
        with self._lock:
            entry = self._pending.get(identifier)
        if entry is None:
            return
        operation = entry[0]
        if not operation.cancel(reason, code):
            return
        response = self._cancelled_response(operation)
        if silent:
            operation(response)
            with self._lock:
                self._pending.pop(identifier, None)
            entry[1].cancel()
        else:
            self._finish(operation, response)
        cancel = getattr(self.backend, 'cancel', None)
        if cancel is not None and operation.started:
            threading.Thread(target=cancel, args=(operation,), name='mcp-cancel', daemon=True).start()

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            operation, message = item
            if not operation.start():
                continue
            try:
                with operation_scope(operation):
                    response = self.respond(self.backend, message)
            except Exception as error:
                response = {'jsonrpc': '2.0', 'id': operation.identifier,
                            'error': {'code': -32603, 'message': f'{type(error).__name__}: {error}'}}
            if response is not None:
                self._finish(operation, response)

    def close(self):
        with self._lock:
            self._closed = True
            identifiers = list(self._pending)
        for identifier in identifiers:
            self.cancel(identifier, 'MCP 输入已关闭', silent=True)
        self._queue.put(None)
