# -*- coding: utf-8 -*-
"""界面进程这一侧的内核客户端: 把重算交给工作进程 (worker.py), 结果回到界面线程。

- 一次只让工作进程算一件事; 它忙的时候新来的重算请求只留最新的一份 (拖着改尺寸时不排长队),
  被合并掉的请求的回调跟着最新那份一起回复 — 它们的修改都已经包含在里面了。
- 工作进程崩了: 当前请求回复错误, 自动换一个新进程, 文档不受影响。
- 工作进程卡死了 (OpenCascade 在某些曲面上会一直算下去): 一个特征超过 STUCK_AFTER 还没算完就结束它、换新进程,
  回复是哪个特征卡住了 — 不然界面一直显示 "正在重算", 怎么都等不到结果。
"""
from __future__ import annotations

import multiprocessing
import threading
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from . import worker
from ..operations import CURRENT_OPERATION, operation_scope


STUCK_AFTER = 120_000          # 毫秒: 一个特征 (或一次导出、试算) 算这么久还没完, 当作卡死了
TASK_TIMEOUT = 300_000


BODY_KEYS = ('verts', 'normals', 'tris', 'tri_face', 'faces', 'segments', 'segment_edge', 'edges', 'props', 'vertices')


class ProcessBuilder(QObject):
    _arrived = Signal(int, object)          # (第几代工作进程, 消息或 None=进程没了)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs = deque()                # 等着发的: ['build'|'export', 载荷, [回调...]]
        self._flight = None                 # 正在算的: (序号, 类型, [回调...])
        self._sequence = 0
        self._generation = 0
        self._closed = False
        self._body = None                   # 上一次重算送回来的实体显示数据 (实体没变时内核不再重送)
        self.on_progress = None             # 重算做到哪了: on_progress(第几个特征, 一共几个, 特征名)
        self.on_query_progress = None       # 查询自己报的进度: on_query_progress(第几个, 一共几个, 名字, 哪一种: parts 加载零件 / motion 运动干涉)
        self._arrived.connect(self._on_arrived)
        self._watch = QTimer(self)          # 看门狗: 每开始算一个特征重新计时, 到点了还没动静 = 卡死
        self._watch.setSingleShot(True)
        self._watch.timeout.connect(self._stuck)
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._expired)
        self._step = None                   # 正在算的特征名 (最近一条进度)
        self._stuck_text = None             # 是看门狗把进程停掉的: 回复用这句话
        self._start()

    def _start(self):
        self._generation += 1
        self._body = None                   # 新的工作进程不知道上一个送过什么
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
        owner = CURRENT_OPERATION.get()
        if self._jobs and self._jobs[-1][0] == 'build' and self._jobs[-1][3] is owner:
            self._jobs[-1][1] = (features, upto)
            self._jobs[-1][2].append(done)
        else:
            self._jobs.append(['build', (features, upto), [done], owner])
        self._pump()

    def keep(self, features, upto):
        """文档刚保存: 让内核把算好的样子存进磁盘缓存 (下次打开直接读)。"""
        self._jobs.append(['keep', (features, upto), [], CURRENT_OPERATION.get()])
        self._pump()

    def export(self, features, upto, path, done):
        self._jobs.append(['export', (features, upto, path), [done], CURRENT_OPERATION.get()])
        self._pump()

    def outline(self, features, upto, mode, frame, done):
        if mode == 'preview':               # 预览只要最新的: 还排着没发出去的旧预览直接扔掉, 不然连着点几下就排成长队, 后面的操作全被堵住
            for job in [job for job in self._jobs if job[0] == 'outline' and job[1][2] == 'preview']:
                self._jobs.remove(job)
        self._jobs.append(['outline', (features, upto, mode, frame), [done], CURRENT_OPERATION.get()])
        self._pump()

    def cancel(self, owner, reason='请求已取消，已停止对应的内核任务'):
        if owner is None:
            return False
        removed = [job for job in self._jobs if job[3] is owner]
        self._jobs = deque(job for job in self._jobs if job[3] is not owner)
        active = self._flight is not None and self._flight[3] is owner
        if active:
            self._stuck_text = reason
            self._process.terminate()
            self._connection.close()
            self._lost()
        for kind, payload, callbacks, job_owner in removed:
            with operation_scope(job_owner):
                for callback in callbacks:
                    callback(reason) if kind == 'export' else callback(None, reason)
        return active or bool(removed)

    def close(self):
        self._closed = True
        self._watch.stop()
        self._deadline.stop()
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
        kind, payload, callbacks, owner = self._jobs.popleft()
        if owner is not None and owner.cancelled.is_set():
            with operation_scope(owner):
                for callback in callbacks:
                    callback(owner.reason) if kind == 'export' else callback(None, owner.reason)
            self._pump()
            return
        self._sequence += 1
        self._flight = (self._sequence, kind, callbacks, owner)
        self._step = None
        try:
            self._connection.send((kind, self._sequence) + tuple(payload))
        except (OSError, ValueError):
            self._lost()
            return
        self._watch.start(STUCK_AFTER)
        self._deadline.start(TASK_TIMEOUT)

    def _expired(self):
        if self._flight is None or self._closed:
            return
        self._stuck_text = f'内核任务超过总时限 {TASK_TIMEOUT / 1000:g} 秒，已停止；请检查文档后再继续'
        self._process.terminate()
        self._connection.close()
        self._lost()

    def _stuck(self):
        """看门狗到点了: 工作进程卡在一个特征上出不来。结束它, 直接换新进程回复 — 不等读消息的线程收到断开:
        进程刚启动就被结束时 (管道的那一头还没交到它手里) 管道不会断, 那就永远等不到。旧进程的消息按代数不同会被扔掉。"""
        if self._flight is None or self._closed:
            return
        seconds = STUCK_AFTER // 1000
        what = f'特征“{self._step}”' if self._step else '这一步'
        self._stuck_text = (f'{what}算了超过 {seconds} 秒还没算完，已经停下（几何内核在这里卡住了）。'
                            '请撤销、删除它或换一组参数再试')
        self._process.terminate()
        try:
            self._connection.close()
        except OSError:
            pass
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
        if kind == 'progress':              # 还在算: 只是报一下做到哪了
            self._step = payload[2]
            self._watch.start(STUCK_AFTER)  # 开始算下一个特征了: 重新计时
            if self.on_progress is not None and self._flight[1] == 'build':      # 进度条只给文档的重算
                self.on_progress(*payload[:3])
            elif self.on_query_progress is not None and len(payload) > 3:     # 和查询自己报的 (零件里的特征那些不算)
                self.on_query_progress(*payload[:4])
            return
        _, wanted, callbacks, owner = self._flight
        self._flight = None
        self._watch.stop()
        self._deadline.stop()
        if kind == 'built' and wanted == 'build':
            if payload.pop('same_body', False) and self._body is not None:
                payload.update(self._body)          # 实体没变: 网格那些还是上次的 (同一批数组, 界面那边记着的也就都还作数)
            else:
                self._body = {key: payload[key] for key in BODY_KEYS if key in payload}
        with operation_scope(owner):
            for callback in callbacks:
                if wanted == 'export':
                    callback(payload)
                elif kind in ('built', 'outlined'):
                    callback(payload, None)
                else:
                    callback(None, payload)
        self._pump()

    def _lost(self):
        """工作进程没了 (崩溃或被杀): 告诉等结果的人, 换一个新进程接着干。"""
        flight, self._flight = self._flight, None
        self._watch.stop()
        self._deadline.stop()
        stuck, self._stuck_text = self._stuck_text, None
        if not self._closed:
            self._start()
        if flight is not None:
            text = stuck or '几何内核进程意外退出（已自动重启）。刚才这一步可能触发了内核缺陷，请撤销或修改参数后再试'
            with operation_scope(flight[3]):
                for callback in flight[2]:
                    callback(text) if flight[1] == 'export' else callback(None, text)
        self._pump()
