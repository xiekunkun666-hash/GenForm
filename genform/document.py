# -*- coding: utf-8 -*-
"""文档 = 一串按顺序执行的特征 (纯数据)。不碰几何内核、不碰界面。

实体永远是 "把特征从头到尾算一遍" 的结果, 文档里不存几何: 改一个尺寸就是改一个数再重算。
撤销/重做存的是整份特征列表的快照 — 特征只是几十个小字典, 快照比逐条记录反操作简单可靠得多。
"""
from __future__ import annotations

import copy
import json

FORMAT = 'genform-document'
VERSION = 1
from .features import SPECS

TYPE_NAMES = {'sketch': '草图', 'extrude': '拉伸', 'fillet': '圆角', 'chamfer': '倒角'}
TYPE_NAMES.update({kind: spec['short'] for kind, spec in SPECS.items()})      # 其余的特征都登记在特征表里
UNDO_LIMIT = 200


class DocumentError(Exception):
    """对文档的操作不成立 (找不到特征等); 文字直接给用户和 AI 看。"""


class Document:
    def __init__(self):
        self.features = []
        self.upto = None            # 回滚线: 只算前 upto 个特征; None = 全部
        self.props = {}             # 零件的属性: material 材质名, color 外观颜色 '#RRGGBB', feature_colors {特征 id: 颜色}
                                    # (不影响几何, 不进撤销)
        self.path = None
        self.dirty = False
        self.revision = 0           # 每次内容变化加一: 界面和内核用它判断结果是不是过期了
        self._serial = 0
        self._undo, self._redo = [], []

    # ---- 查询 ----
    def find(self, identifier):
        for feature in self.features:
            if feature['id'] == identifier:
                return feature
        raise DocumentError(f'找不到特征 {identifier!r}')

    def index(self, identifier):
        return self.features.index(self.find(identifier))

    def last(self, kind):
        """最后一个该类型的特征 id (没有返回 None) — "拉伸" 不指定草图时用最近的草图。"""
        for feature in reversed(self.features):
            if feature['type'] == kind:
                return feature['id']
        return None

    # ---- 修改 (每个都是一步可撤销的操作) ----
    def _checkpoint(self):
        self._undo.append((copy.deepcopy(self.features), self.upto))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def _changed(self):
        self.dirty = True
        self.revision += 1

    def add(self, kind, params, name=None):
        if kind not in TYPE_NAMES:
            raise DocumentError(f'不认识的特征类型 {kind!r}')
        self._checkpoint()
        self._serial += 1
        count = sum(1 for feature in self.features if feature['type'] == kind) + 1
        feature = {'id': f'f{self._serial}', 'type': kind, 'name': name or f'{TYPE_NAMES[kind]}{count}',
                   'params': copy.deepcopy(params), 'suppressed': False}
        # 回滚线之后插入新特征: 接在回滚线的位置, 回滚线跟着后移 (和常见 CAD 的行为一致)
        if self.upto is not None:
            self.features.insert(self.upto, feature)
            self.upto += 1
        else:
            self.features.append(feature)
        self._changed()
        return feature['id']

    def edit(self, identifier, params):
        """改一个特征的参数: 只覆盖给出的键, 其余保持。"""
        feature = self.find(identifier)
        if not isinstance(params, dict):
            raise DocumentError('参数要写成对象')
        self._checkpoint()
        feature['params'].update(copy.deepcopy(params))
        self._changed()

    def rename(self, identifier, name):
        feature = self.find(identifier)
        if not str(name).strip():
            raise DocumentError('名称不能为空')
        self._checkpoint()
        feature['name'] = str(name).strip()
        self._changed()

    def set_folder(self, identifiers, folder):
        """把这些特征放进文件夹 folder ('车身/车窗' 这样用 / 分层; 写空 = 拿出文件夹)。只是设计树里怎么归类, 不影响几何。"""
        parts = [part.strip() for part in str(folder or '').replace(chr(92), '/').split('/') if part.strip()]
        features = [self.find(identifier) for identifier in identifiers]
        self._checkpoint()
        for feature in features:
            if parts:
                feature['folder'] = '/'.join(parts)
            else:
                feature.pop('folder', None)
        self._changed()

    def set_processes(self, bound):
        """给特征绑加工工艺: {特征 id: 工艺字典 (见 manufacturing.choose); None = 解除}。不影响几何, 但记进撤销。"""
        self._checkpoint()
        for identifier, process in bound.items():
            feature = self.find(identifier)
            if process:
                feature['process'] = process
            else:
                feature.pop('process', None)
        self._changed()

    def suppress(self, identifier, suppressed=True):
        feature = self.find(identifier)
        self._checkpoint()
        feature['suppressed'] = bool(suppressed)
        self._changed()

    def delete(self, identifier):
        position = self.index(identifier)
        self._checkpoint()
        del self.features[position]
        if self.upto is not None and position < self.upto:
            self.upto -= 1
        self._changed()

    def rollback(self, count):
        """把回滚线放到第 count 个特征之后 (None 或超过总数 = 不回滚)。"""
        if count is not None:
            count = int(count)
            if count < 0:
                raise DocumentError('回滚位置不能为负')
            if count >= len(self.features):
                count = None
        self._checkpoint()
        self.upto = count
        self._changed()

    def set_prop(self, key, value):
        """改零件的属性 (材质、外观)。不影响几何: 不用重算, 也不记进撤销。"""
        if value in (None, ''):
            self.props.pop(key, None)
        else:
            self.props[key] = value
        self.dirty = True

    # ---- 撤销 / 重做 ----
    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            raise DocumentError('没有可撤销的操作')
        self._redo.append((self.features, self.upto))
        self.features, self.upto = self._undo.pop()
        self._changed()

    def redo(self):
        if not self._redo:
            raise DocumentError('没有可重做的操作')
        self._undo.append((self.features, self.upto))
        self.features, self.upto = self._redo.pop()
        self._changed()

    # ---- 存取 ----
    def to_data(self):
        return {'format': FORMAT, 'version': VERSION, 'serial': self._serial,
                'upto': self.upto, 'props': dict(self.props), 'features': copy.deepcopy(self.features)}

    def load_data(self, data):
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            raise DocumentError('不是 GenForm 文档')
        if int(data.get('version', 0)) > VERSION:
            raise DocumentError('这份文档是更新版本的 GenForm 保存的，当前版本打不开')
        features = data.get('features')
        if not isinstance(features, list):
            raise DocumentError('文档内容损坏：没有特征列表')
        loaded = []
        for feature in features:
            if not isinstance(feature, dict) or not {'id', 'type', 'params'} <= set(feature):
                raise DocumentError('文档内容损坏：特征缺少字段')
            loaded.append({'id': str(feature['id']), 'type': str(feature['type']),
                           'name': str(feature.get('name') or feature['id']),
                           'params': copy.deepcopy(feature['params']),
                           'suppressed': bool(feature.get('suppressed'))})
            if isinstance(feature.get('process'), dict):
                loaded[-1]['process'] = copy.deepcopy(feature['process'])
            if feature.get('folder'):
                loaded[-1]['folder'] = str(feature['folder'])
        self.features = loaded
        self.upto = data.get('upto')
        self.props = {str(key): value for key, value in (data.get('props') or {}).items()} if isinstance(data.get('props'), dict) else {}
        self._serial = max([int(data.get('serial', 0))]
                           + [int(f['id'][1:]) for f in loaded if f['id'][1:].isdigit()])
        self._undo.clear()
        self._redo.clear()
        self.dirty = False
        self.revision += 1

    def save(self, path=None):
        path = path or self.path
        if not path:
            raise DocumentError('还没有指定保存位置')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(self.to_data(), handle, ensure_ascii=False, indent=1)
        self.path = str(path)
        self.dirty = False

    def open(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError) as error:
            raise DocumentError(f'打不开文档：{error}') from None
        self.load_data(data)
        self.path = str(path)

    def clear(self):
        self.features, self.upto, self.path = [], None, None
        self.props = {}
        self._serial = 0
        self._undo.clear()
        self._redo.clear()
        self.dirty = False
        self.revision += 1
