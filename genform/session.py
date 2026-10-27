# -*- coding: utf-8 -*-
"""会话: 一份文档 + 它算出来的模型 + 执行命令的入口。界面、AI 接口、测试都只跟它打交道。

不依赖界面库: 不开窗口也能用 (测试、无界面的 AI 调用), 那时用 SyncBuilder 在本进程里直接重算。
"""
from __future__ import annotations

import copy

from . import commands
from .document import Document, DocumentError
from .operations import CURRENT_OPERATION


BUSY_AFTER = 150                # 重算超过这么多毫秒还没完, 才让界面显示 "正在重算"


class SyncBuilder:
    """在调用者的线程里直接算 — 测试和无界面模式用。"""

    def build(self, features, upto, done):
        from .kernel import build
        try:
            done(build.build_model(features, upto), None)
        except Exception as error:
            done(None, f'内核错误 {type(error).__name__}: {error}')

    def export(self, features, upto, path, done):
        from .kernel import build
        try:
            build.export(features, path, upto)
            done(None)
        except build.FeatureError as error:
            done(str(error))
        except Exception as error:
            done(f'内核错误 {type(error).__name__}: {error}')

    def outline(self, features, upto, mode, frame, done):
        from .kernel import build
        try:
            done(build.outline(features, upto, mode, frame), None)
        except build.FeatureError as error:
            done(None, str(error))
        except Exception as error:
            done(None, f'内核错误 {type(error).__name__}: {error}')

    def close(self):
        pass


class Session:
    def __init__(self, builder=None):
        self.document = Document()
        self.builder = builder or SyncBuilder()
        self.model = {'status': {}, 'sketches': {}, 'has_body': False}
        self.model_revision = -1        # self.model 对应文档的哪一版
        self.selection = {'faces': [], 'edges': [], 'feature': None, 'plane': None}
        self.view = None                # 界面接上后提供 set_view / screenshot
        self.busy = False
        self.progress = None            # 正在重算时: (做到第几个特征, 一共几个, 特征名); 界面拿它画进度条
        self.query_progress = None      # 正在算一个会报进度的查询时 (装配体加载零件): (第几个, 一共几个, 名字)
        self.on_progress = None         # 进度变了叫一声 (不走 notify: 一秒二十次, 不该让整个界面跟着刷新)
        self.later = None               # 界面接上后: later(毫秒, 函数) 过一会儿再调 — "开始忙了" 晚一点再通知 (见 rebuild)
        self._listeners = []
        self._builds = set()
        if hasattr(self.builder, 'on_progress'):
            self.builder.on_progress = self._on_progress
        if hasattr(self.builder, 'on_query_progress'):
            self.builder.on_query_progress = self._on_query_progress

    # ---- 通知 ----
    def listen(self, callback):
        """文档、模型或忙碌状态变了就调 callback()。"""
        self._listeners.append(callback)

    def _on_progress(self, index, total, name):
        self.progress = (index, total, name)
        if self.on_progress is not None:
            self.on_progress()

    def _on_query_progress(self, index, total, name, what='parts'):
        self.query_progress = (index, total, name, what)
        if self.on_progress is not None:
            self.on_progress()

    def notify(self):
        for callback in list(self._listeners):
            callback()

    # ---- 执行命令 ----
    def execute(self, name, args=None, reply=None):
        """执行一条命令; 结果通过 reply(结果字典) 给出 (会改文档的命令要等重算完才回复)。
        结果里 ok=False 时 error 是给人和 AI 看的原因。"""
        reply = reply or (lambda result: None)
        try:
            item = commands.get(name)
            args = dict(args or {})
            commands.check(item, args)
            before = self.document.revision
            result = item.handler(self, args)
        except DocumentError as error:
            reply({'ok': False, 'error': str(error)})
            return
        except (TypeError, ValueError, KeyError) as error:
            reply({'ok': False, 'error': f'参数不对: {error}'})
            return
        if callable(result):            # 要等内核或界面的命令 (导出、截图): 它自己回复
            result(reply)
            return
        if not item.mutates or self.document.revision == before:
            reply({'ok': True, **result})
            return
        if not item.geometry and not self.busy and self.model_revision == before:
            self.model_revision = self.document.revision        # 只改了名字之类: 几何没变, 现成的模型照用, 不重算
            self.notify()
            reply(self._after_change(result))
            return
        self.rebuild(lambda: reply(self._after_change(result)))

    def _after_change(self, result):
        """改完并重算后给调用者的回复: 新特征算没算成、哪些特征出错、实体现在多大。"""
        status = self.model.get('status', {})
        errors = {identifier: text[7:] for identifier, text in status.items() if text.startswith('error: ')}
        answer = {'ok': not errors, **result}
        if errors:
            names = {f['id']: f['name'] for f in self.document.features}
            answer['error'] = '；'.join(f'{names.get(i, i)} ({i}): {text}' for i, text in errors.items())
            answer['hint'] = '出错的特征仍留在特征列表里：用 edit_feature 改参数，或用 undo 撤销这一步。'
        touched = [result.get('id')] + list(result.get('ids') or [])     # 这次新建 / 改的特征: 回复里带它们的参数
        answer['model'] = commands.describe(self, brief=True, focus={i for i in touched if i})
        return answer

    def rebuild(self, done=None):
        revision = self.document.revision
        owner = CURRENT_OPERATION.get()
        ticket = object()
        self._builds.add(ticket)
        self.busy = True
        if self.later is None:
            self.notify()
        else:                           # 大多数修改几十毫秒就算完: 不为 "开始忙了" 把整个界面刷一遍 (还会闪一下)
            self.later(BUSY_AFTER, lambda: self.notify() if self.busy else None)

        def built(model, error):
            self._builds.discard(ticket)
            # 期间文档又变了: 这份结果已经过期, 等更新的那次重算回来 (它会带上最新的回调)
            if not (owner is not None and owner.cancelled.is_set()) and (
                    revision == self.document.revision or self.model_revision < revision):
                if model is None:
                    status = {f['id']: f'error: {error}' for f in self.document.features}
                    model = {'status': status, 'sketches': {}, 'has_body': False}
                self.model, self.model_revision = model, revision
                self._prune_selection()
            self.busy = bool(self._builds)
            if not self.busy:
                self.progress = None
                if self.on_progress is not None:
                    self.on_progress()
            self.notify()
            if done:
                done()

        self.builder.build(copy.deepcopy(self.document.features), self.document.upto, built)

    def _prune_selection(self):
        """重算后面和边的编号可能都变了: 旧的选择不再可靠, 清掉。"""
        self.selection['faces'], self.selection['edges'] = [], []
        known = {f['id'] for f in self.document.features}
        if self.selection.get('feature') not in known:
            self.selection['feature'] = None

    # ---- 命令用到的两个外部能力 ----
    def export(self, path):
        def later(reply):
            def done(error):
                reply({'ok': False, 'error': error} if error else {'ok': True, 'path': str(path)})
            self.builder.export(copy.deepcopy(self.document.features), self.document.upto, str(path), done)
        return later

    def outline(self, mode, frame, done):
        """草图平面上看到的实体轮廓线 (mode: silhouette 侧影 / section 交线) → done(折线列表, 错误)。不改文档。"""
        self.builder.outline(copy.deepcopy(self.document.features), self.document.upto, mode,
                             [[float(value) for value in vector] for vector in frame], done)

    def query(self, mode, data, done):
        """让内核算一样不改文档的东西 (mode: measure 测量 …) → done(结果, 错误)。"""
        def finish(result, error):
            if self.query_progress is not None:     # 报过进度的查询算完了: 进度条收起来
                self.query_progress = None
                if self.on_progress is not None:
                    self.on_progress()
            done(result, error)
        self.builder.outline(copy.deepcopy(self.document.features), self.document.upto, mode, copy.deepcopy(data), finish)

    def preview(self, name, args, done):
        """试算一条会改文档的命令: 假如执行了, 实体会是什么样 → done(build.preview 的结果, 错误)。文档本身不动。"""
        probe = copy.copy(self)             # 命令的处理函数只认 session.document / model / selection
        probe.document = Document()
        try:
            probe.document.load_data(self.document.to_data())
            item = commands.get(name)
            args = dict(args or {})
            commands.check(item, args)
            item.handler(probe, args)
        except (DocumentError, TypeError, ValueError, KeyError) as error:
            done(None, str(error))
            return
        self.builder.outline(copy.deepcopy(probe.document.features), probe.document.upto, 'preview', None, done)

    def view_call(self, method, *args):
        if self.view is None:
            raise DocumentError('现在没有打开界面，视图命令不可用')
        return getattr(self.view, method)(*args)

    def close(self):
        self.builder.close()
