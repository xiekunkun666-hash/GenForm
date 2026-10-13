# -*- coding: utf-8 -*-
"""MCP 服务: 让 Claude 这类 AI 工具直接连上 GenForm。

    python -m genform.api.mcp_server              连到正在运行的 GenForm 窗口 (人能看着 AI 画)
    python -m genform.api.mcp_server --headless   不开窗口, 自己带一份文档 (视图类工具不可用)

走标准输入输出上的 JSON-RPC (MCP 的 stdio 传输): 只实现 initialize / tools/list / tools/call。
注意: 标准输出只能写协议消息, 其他任何输出都会让对方解析失败 — 日志一律写标准错误。
"""
from __future__ import annotations

import json
import os
import socket
import sys

PROTOCOL = '2024-11-05'
INSTRUCTIONS = (
    'GenForm 是参数化三维建模软件：模型由按顺序执行的特征组成（草图 → 拉伸 → 圆角/倒角）。单位毫米。'
    '典型流程：sketch 画轮廓 → extrude 拉伸成实体 → fillet/chamfer 修边 → export 导出。'
    '每次修改都会返回最新的特征列表和实体尺寸；某个特征失败时 ok=false 并说明原因，'
    '可以用 edit_feature 改参数或 undo 撤销。引用边之前先用 list_edges 看边的中点坐标，'
    '或直接用选择器（如 "|Z"、">Z"）。想确认形状可以用 screenshot 看图。'
)


class WindowBackend:
    """把工具调用转给正在运行的 GenForm (本地端口)。"""

    def __init__(self, port):
        self._port = port

    def _ask(self, request):
        try:
            with socket.create_connection(('127.0.0.1', self._port), timeout=5) as link:
                link.settimeout(320)
                link.sendall((json.dumps(request, ensure_ascii=False) + '\n').encode('utf-8'))
                data = b''
                while not data.endswith(b'\n'):
                    chunk = link.recv(1 << 16)
                    if not chunk:
                        break
                    data += chunk
            return json.loads(data.decode('utf-8'))
        except OSError:
            return {'ok': False, 'error': f'连不上 GenForm（端口 {self._port}）。请先启动 GenForm，'
                                          '或者用 --headless 参数以无界面方式运行本服务。'}

    def tools(self):
        answer = self._ask({'cmd': 'tools'})
        if not answer.get('ok'):
            # 窗口还没开: 工具清单是固定的, 直接用本地这份, 调用时再报连不上
            from .. import commands
            return commands.catalog()
        return answer['tools']

    def call(self, name, args):
        return self._ask({'cmd': name, 'args': args})


class HeadlessBackend:
    """不开窗口: 本进程里直接持有一份文档。"""

    def __init__(self):
        from ..session import Session
        self._session = Session()

    def tools(self):
        from .. import commands
        return commands.catalog()

    def call(self, name, args):
        box = []
        self._session.execute(name, args, box.append)
        return box[0] if box else {'ok': False, 'error': '命令没有返回结果'}


def respond(backend, message):
    """处理一条 JSON-RPC 消息 → 应答字典 (通知类消息返回 None)。"""
    method, identifier = message.get('method'), message.get('id')
    if identifier is None:
        return None                         # 通知 (notifications/initialized 等): 不用回
    if method == 'initialize':
        result = {'protocolVersion': PROTOCOL, 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'genform', 'version': '0.1.0'}, 'instructions': INSTRUCTIONS}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': [{'name': tool['name'], 'description': tool['description'],
                             'inputSchema': tool['input_schema']} for tool in backend.tools()]}
    elif method == 'tools/call':
        params = message.get('params') or {}
        answer = backend.call(str(params.get('name')), params.get('arguments') or {})
        from .wire import encode
        result = {'content': [{'type': 'text', 'text': encode(answer)}], 'isError': not answer.get('ok', False)}
    else:
        return {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': -32601, 'message': f'不支持的方法 {method}'}}
    return {'jsonrpc': '2.0', 'id': identifier, 'result': result}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--headless' in argv:
        # 内核会往标准输出打日志 (写 STEP 时): 把文件描述符 1 挪到标准错误, 协议另用一个句柄写
        protocol_out = os.fdopen(os.dup(1), 'w', encoding='utf-8', newline='\n')
        os.dup2(2, 1)
        backend = HeadlessBackend()
    else:
        protocol_out = os.fdopen(os.dup(1), 'w', encoding='utf-8', newline='\n')
        from .wire import DEFAULT_PORT
        backend = WindowBackend(int(os.environ.get('GENFORM_PORT', DEFAULT_PORT)))
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line.decode('utf-8'))
        except ValueError:
            continue
        answer = respond(backend, message)
        if answer is not None:
            protocol_out.write(json.dumps(answer, ensure_ascii=False) + '\n')
            protocol_out.flush()


if __name__ == '__main__':
    main()
