# -*- coding: utf-8 -*-
"""本地接口: 让别的程序 (AI、脚本、测试) 驱动正在运行的 GenForm。

只听 127.0.0.1。协议: TCP, 每行一个 JSON 请求, 每行一个 JSON 应答。
    {"cmd": "tools"}                          → {"ok": true, "tools": [工具清单]}
    {"cmd": "<命令名>", "args": {...}}        → 命令的结果 (见 genform/commands.py)
命令在界面线程上执行, 和用户点按钮走的是同一条路。mcp_server.py 是架在这个接口上的 MCP 适配。
"""
from __future__ import annotations

import json
import os
import select
import socket
import threading
import time

from PySide6.QtCore import QObject, Signal

from .. import commands
from .wire import DEFAULT_PORT, encode
from ..operations import Operation, operation_scope

READ_ONLY = {'get_model', 'get_selection', 'get_design_rules', 'list_edges', 'list_faces', 'list_processes', 'bbox', 'com',
             'check_design', 'screenshot'}    # 这些命令只看不改: 不收起开始页
REPLY_TIMEOUT = 300.0           # 一条命令 (含重算) 最多等这么久


class ApiServer(QObject):
    _request = Signal(object, object)       # (请求字典, 回复函数) — 从网络线程投到界面线程
    _cancel_request = Signal(object)

    def __init__(self, session, port=DEFAULT_PORT, parent=None):
        super().__init__(parent)
        self._session = session
        self.controller = None          # 界面控制器 (bootstrap 接上); 只给 'ui' 测试命令用
        self._request.connect(self._handle)
        self._cancel_request.connect(self._cancel_operation)
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._closing = threading.Event()
        self._links = set()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(('127.0.0.1', port))
        self._socket.listen(8)
        self.port = self._socket.getsockname()[1]
        threading.Thread(target=self._accept, name='api-accept', daemon=True).start()

    def close(self):
        self._closing.set()
        with self._pending_lock:
            pending = list(self._pending.values())
            links = list(self._links)
        for operation in pending:
            self._cancel(operation, 'GenForm 接口正在关闭')
        for connection in links:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            self._socket.close()
        except OSError:
            pass

    def _accept(self):
        while True:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(connection,), name='api-client', daemon=True).start()

    def _serve(self, connection):
        with self._pending_lock:
            self._links.add(connection)
        try:
            with connection, connection.makefile('rwb') as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        request = json.loads(line.decode('utf-8'))
                        if not isinstance(request, dict):
                            raise ValueError('请求要写成 JSON 对象')
                        result = self._receive(connection, request)
                    except (ValueError, TypeError) as error:
                        result = {'ok': False, 'error': f'请求格式不对: {error}'}
                    except RuntimeError:
                        return
                    stream.write(encode(result).encode('utf-8') + b'\n')
                    stream.flush()
        except OSError:
            pass
        finally:
            with self._pending_lock:
                self._links.discard(connection)

    def _cancel(self, operation, reason, code='cancelled'):
        if operation.cancel(reason, code):
            self._cancel_request.emit(operation)

    def _cancel_operation(self, operation):
        cancel = getattr(self._session.builder, 'cancel', None)
        if cancel is not None:
            cancel(operation, operation.reason)

    def _receive(self, connection, request):
        if request.get('cmd') == 'cancel_request':
            with self._pending_lock:
                operation = self._pending.get(request.get('request_id'))
            if operation is not None:
                self._cancel(operation, '调用方已取消请求')
            return {'ok': True, 'found': operation is not None}
        operation = Operation(request.get('request_id'))
        if not isinstance(operation.identifier, str):
            raise ValueError('request_id 必须是字符串')
        timeout = float(request.get('timeout_s', REPLY_TIMEOUT))
        if not 0 < timeout <= REPLY_TIMEOUT:
            raise ValueError(f'timeout_s 必须在 0 到 {REPLY_TIMEOUT:g} 秒之间')
        with self._pending_lock:
            if operation.identifier in self._pending:
                raise ValueError('request_id 正在执行，不可重复提交')
            self._pending[operation.identifier] = operation
        try:
            self._request.emit(request, operation)
            deadline = time.monotonic() + timeout
            while not operation.finished.wait(0.05):
                if self._closing.is_set() or self._disconnected(connection):
                    self._cancel(operation, '调用方已断开连接')
                elif time.monotonic() >= deadline:
                    self._cancel(operation, f'请求超过 {timeout:g} 秒，已请求停止对应的计算', 'timeout')
                if operation.cancelled.is_set():
                    operation(operation.failure())
            return operation.result
        finally:
            with self._pending_lock:
                self._pending.pop(operation.identifier, None)

    @staticmethod
    def _disconnected(connection):
        try:
            readable, _, _ = select.select([connection], [], [], 0)
            return bool(readable) and not connection.recv(1, socket.MSG_PEEK)
        except OSError:
            return True

    def _handle(self, request, reply):
        if isinstance(reply, Operation):
            if not reply.start():
                reply(reply.failure())
                return
        with operation_scope(reply if isinstance(reply, Operation) else None):
            try:
                self._dispatch(request, reply)
            except Exception as error:
                reply({'ok': False, 'error': f'命令执行失败 {type(error).__name__}: {error}'})

    def _dispatch(self, request, reply):
        name = request.get('cmd')
        if name == 'tools':
            reply({'ok': True, 'tools': commands.catalog()})
        elif name == 'ping':
            reply({'ok': True, 'app': 'GenForm', 'pid': os.getpid()})
        elif name == 'ui':                  # 自动化测试用: 直接调界面控制器的槽 (模拟用户点按钮)
            target = self.controller
            for part in str(request.get('slot')).split('.'):      # 'sim.open' = 控制器下面仿真页的槽
                target = getattr(target, part, None)
            if self.controller is None or target is None:
                reply({'ok': False, 'error': '没有这个界面操作'})
            elif not callable(target):          # 属性: 把它现在的值给回去 (测试里看界面状态)
                reply({'ok': True, 'value': json.loads(json.dumps(target, ensure_ascii=False, default=str))})
            else:
                target(*(request.get('args') or []))
                reply({'ok': True})
        elif name == 'quit':                # 自动化测试收尾用: 正常关窗退出
            from PySide6.QtCore import QMetaObject, Qt
            from PySide6.QtGui import QGuiApplication
            reply({'ok': True})
            # 排进事件队列让 Qt 自己去调, 不能从 Python 里直接调 quit(): 关窗口要等渲染线程收工, 而渲染线程
            # 正要画一帧 (比如视角过渡到一半) 时在等 Python 的全局锁 — 这边拿着锁等它, 两边就互相卡死
            QMetaObject.invokeMethod(QGuiApplication.instance(), 'quit', Qt.QueuedConnection)
        else:
            if self.controller is not None and str(name) not in READ_ONLY:
                self.controller.closeStart()
            self._session.execute(str(name), request.get('args') or {}, reply)
