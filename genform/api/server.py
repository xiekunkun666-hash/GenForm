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
import socket
import threading

from PySide6.QtCore import QObject, Signal

from .. import commands
from .wire import DEFAULT_PORT, encode

REPLY_TIMEOUT = 300.0           # 一条命令 (含重算) 最多等这么久


class ApiServer(QObject):
    _request = Signal(object, object)       # (请求字典, 回复函数) — 从网络线程投到界面线程

    def __init__(self, session, port=DEFAULT_PORT, parent=None):
        super().__init__(parent)
        self._session = session
        self.controller = None          # 界面控制器 (bootstrap 接上); 只给 'ui' 测试命令用
        self._request.connect(self._handle)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(('127.0.0.1', port))
        self._socket.listen(8)
        self.port = self._socket.getsockname()[1]
        threading.Thread(target=self._accept, name='api-accept', daemon=True).start()

    def close(self):
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
        with connection, connection.makefile('rwb') as stream:
            for line in stream:
                if not line.strip():
                    continue
                done = threading.Event()
                box = {}

                def reply(result, box=box, done=done):
                    box['result'] = result
                    done.set()

                try:
                    request = json.loads(line.decode('utf-8'))
                    if not isinstance(request, dict):
                        raise ValueError('请求要写成 JSON 对象')
                    self._request.emit(request, reply)
                    if not done.wait(REPLY_TIMEOUT):
                        box['result'] = {'ok': False, 'error': '命令超时没有完成'}
                except ValueError as error:
                    box['result'] = {'ok': False, 'error': f'请求格式不对: {error}'}
                except RuntimeError:        # 程序正在退出
                    return
                try:
                    stream.write(encode(box['result']).encode('utf-8') + b'\n')
                    stream.flush()
                except OSError:
                    return

    def _handle(self, request, reply):
        name = request.get('cmd')
        if name == 'tools':
            reply({'ok': True, 'tools': commands.catalog()})
        elif name == 'ping':
            reply({'ok': True, 'app': 'GenForm', 'pid': os.getpid()})
        elif name == 'ui':                  # 自动化测试用: 直接调界面控制器的槽 (模拟用户点按钮)
            target = getattr(self.controller, str(request.get('slot')), None)
            if self.controller is None or not callable(target):
                reply({'ok': False, 'error': '没有这个界面操作'})
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
            self._session.execute(str(name), request.get('args') or {}, reply)
