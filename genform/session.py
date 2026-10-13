# -*- coding: utf-8 -*-
"""会话: 一份文档 + 它算出来的模型 + 执行命令的入口。界面、AI 接口、测试都只跟它打交道。

不依赖界面库: 不开窗口也能用 (测试、无界面的 AI 调用), 那时用 SyncBuilder 在本进程里直接重算。
"""
from __future__ import annotations

import copy

from . import commands
from .document import Document, DocumentError


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
        self._listeners = []

    # ---- 通知 ----
    def listen(self, callback):
        """文档、模型或忙碌状态变了就调 callback()。"""
        self._listeners.append(callback)

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
        answer['model'] = commands.describe(self)
        return answer

    def rebuild(self, done=None):
        revision = self.document.revision
        self.busy = True
        self.notify()

        def built(model, error):
            # 期间文档又变了: 这份结果已经过期, 等更新的那次重算回来 (它会带上最新的回调)
            if revision == self.document.revision or self.model_revision < revision:
                if model is None:
                    status = {f['id']: f'error: {error}' for f in self.document.features}
                    model = {'status': status, 'sketches': {}, 'has_body': False}
                self.model, self.model_revision = model, revision
                self._prune_selection()
            self.busy = revision != self.document.revision
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

    def view_call(self, method, *args):
        if self.view is None:
            raise DocumentError('现在没有打开界面，视图命令不可用')
        return getattr(self.view, method)(*args)

    def close(self):
        self.builder.close()
