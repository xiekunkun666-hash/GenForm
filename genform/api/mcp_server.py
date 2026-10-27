# -*- coding: utf-8 -*-
"""MCP 服务: 让 Claude 这类 AI 工具直接连上 GenForm。

    python -m genform.api.mcp_server              连到正在运行的 GenForm 窗口 (人能看着 AI 画)
    python -m genform.api.mcp_server --headless   不开窗口, 自己带一份文档 (视图类工具不可用)

走标准输入输出上的 JSON-RPC (MCP 的 stdio 传输): 只实现 initialize / tools/list / tools/call。
注意: 标准输出只能写协议消息, 其他任何输出都会让对方解析失败 — 日志一律写标准错误。
"""
from __future__ import annotations

import base64
import json
import os
import socket
import sys
import threading
import time

from ..operations import CURRENT_OPERATION

PROTOCOL = '2024-11-05'
INSTRUCTIONS = (
    'GenForm 是参数化三维建模软件：零件由一串按顺序执行的特征组成，单位毫米，Z 朝上。'
    '基准面：XY = 上视，XZ = 前视，YZ = 右视。\n'
    '典型流程：sketch（在基准面上画封闭轮廓）→ extrude（拉伸成实体；op=cut 是切除）→ fillet / chamfer（修边）→ export（导出 STEP / STL）。'
    '除此之外还有旋转、扫描、放样、孔、抽壳、拔模、筋、镜像、各种阵列、基准面/轴/点、曲线等，全部在工具清单里，每个工具的说明和参数都写在它自己的描述里。\n'
    '要连着做很多步时用 batch：把一串命令一次发过来，全部做完才重算一次，比一条条发快得多（见它的说明，"$1" 引用前面步骤的结果）。\n'
    '要点：\n'
    '1. 每次修改都会返回最新的特征列表（id、类型、名称、状态，如 f1、f2；只有这次新建 / 改的特征带参数）和实体尺寸；'
    '后面的命令用这些 id 引用草图和特征。要看别的特征的参数用 get_model（特征多时写 id 只看一个）。\n'
    '2. 某个特征算失败时 ok=false 并写明原因；用 edit_feature 改参数重试，或 undo 撤销。不要在失败的基础上继续往后做。\n'
    '3. 引用边 / 面：先用 list_edges / list_faces 看它们的位置，再用返回的坐标点引用；常见情况也可以直接用选择器（"|Z" 平行于 Z 的边，">Z" 最高处的）。\n'
    '4. 不确定现在是什么样：get_model 看特征和尺寸，screenshot 看图（图片直接附在结果里；需要 GenForm 窗口开着）。\n'
    '5. 做完一步检查一步：比对返回的实体尺寸和体积是否符合预期，再做下一步。\n'
    '用户能在窗口里看到你做的每一步，也可能自己动手改；开始前先 get_model 看一下现状。'
)


class WindowBackend:
    """把工具调用转给正在运行的 GenForm (本地端口)。一直用同一条连接: 本机上每次新建连接要十几毫秒,
    比查询命令本身 (不到 1 毫秒) 还慢得多。"""

    def __init__(self, port):
        self._port = port
        self._link = None
        self._buffer = b''
        self._owner = None
        self._state_lock = threading.Lock()

    def _drop(self):
        with self._state_lock:
            link, self._link = self._link, None
            self._buffer = b''
        if link is not None:
            try:
                link.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if link is not None:
            link.close()

    def _send(self, payload):
        if self._link is None:
            link = socket.create_connection(('127.0.0.1', self._port), timeout=3)
            with self._state_lock:
                if self._owner is not None and self._owner.cancelled.is_set():
                    link.close()
                    raise ConnectionAbortedError('请求已取消')
                self._link = link
        link = self._link
        if link is None:
            raise ConnectionAbortedError('请求已取消')
        link.settimeout(3)
        link.sendall(payload)
        link.settimeout(0.1)
        deadline = time.monotonic() + 295
        while b'\n' not in self._buffer:
            owner = CURRENT_OPERATION.get()
            if owner is not None and owner.cancelled.is_set():
                raise ConnectionAbortedError('请求已取消')
            if time.monotonic() >= deadline:
                raise TimeoutError('等待 GenForm 结果超时')
            try:
                chunk = link.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError('GenForm 断开了连接')
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b'\n', 1)
        return json.loads(line.decode('utf-8'))

    def _ask(self, request):
        owner = CURRENT_OPERATION.get()
        with self._state_lock:
            self._owner = owner
        if owner is not None:
            if owner.cancelled.is_set():
                return owner.failure()
            request = dict(request, request_id=owner.transport_id, timeout_s=285)
        try:
            return self._exchange(request)
        finally:
            with self._state_lock:
                if self._owner is owner:
                    self._owner = None

    def _exchange(self, request):
        payload = (json.dumps(request, ensure_ascii=False) + '\n').encode('utf-8')
        reused = self._link is not None
        try:
            return self._send(payload)
        except TimeoutError:
            self._drop()
            return {'ok': False, 'code': 'timeout',
                    'error': '等待 GenForm 结果超时，连接已关闭并请求取消；请检查模型，不要直接重发。'}
        except (OSError, ValueError):
            self._drop()
        owner = CURRENT_OPERATION.get()
        if owner is not None and owner.cancelled.is_set():
            return owner.failure()
        if reused and request.get('cmd') in {'tools', 'ping', 'get_model', 'get_selection',
                                             'get_design_rules', 'list_edges', 'list_faces', 'list_processes'}:
            try:
                return self._send(payload)
            except (OSError, ValueError):
                self._drop()
        return {'ok': False, 'error': f'连不上 GenForm（端口 {self._port}）或等待结果时连接中断。'
                                      '命令可能已经执行；请先检查模型，不要直接重发修改命令。'}

    def cancel(self, operation):
        with self._state_lock:
            if self._owner is not operation:
                return
            link = self._link
            if link is not None:
                try:
                    link.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        try:
            with socket.create_connection(('127.0.0.1', self._port), timeout=1) as control:
                request = {'cmd': 'cancel_request', 'request_id': operation.transport_id}
                control.sendall((json.dumps(request) + '\n').encode('utf-8'))
        except OSError:
            pass

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
        owner = CURRENT_OPERATION.get()
        if owner is not None and owner.cancelled.is_set():
            return owner.failure()
        box = []
        self._session.execute(name, args, box.append)
        return box[0] if box else {'ok': False, 'error': '命令没有返回结果'}


def _image(name, answer):
    """截图的结果: 把图片直接附上 (AI 不用再去读这个文件, 读不到本机文件的 AI 也能看)。"""
    path = answer.get('path') if name == 'screenshot' and answer.get('ok') else None
    try:
        with open(path, 'rb') as handle:
            data = base64.b64encode(handle.read()).decode('ascii')
    except (OSError, TypeError):
        return []
    return [{'type': 'image', 'data': data, 'mimeType': 'image/png'}]


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
        result = {'content': [{'type': 'text', 'text': encode(answer)}] + _image(params.get('name'), answer),
                  'isError': not answer.get('ok', False)}
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
    from .mcp_runtime import StdioRuntime

    def output(answer):
        protocol_out.write(json.dumps(answer, ensure_ascii=False) + '\n')
        protocol_out.flush()

    runtime = StdioRuntime(backend, respond, output)
    try:
        for line in sys.stdin.buffer:
            try:
                message = json.loads(line.decode('utf-8'))
            except ValueError:
                continue
            runtime.submit(message)
    finally:
        runtime.close()


if __name__ == '__main__':
    main()
