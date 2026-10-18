"""拉伸的拖动箭头和预览: 面板开着时视图里画 "假如现在点确定" 的样子, 拖箭头改深度。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Property, Slot

from ..document import DocumentError
from .. import features as table, forms, planes
from ..i18n import localized
from .common import PREVIEW_TINT
from .signals import formChanged


class PreviewMixin:
    """拉伸的拖动箭头和预览 (控制器的一部分)。"""

    # ---- 拉伸的拖动箭头: 面板开着时视图里有一根箭头, 拖它的头 = 改深度 ----
    def _form_picks(self):
        """面板刚开 / 换了要点的东西: 顶点能不能点、箭头在不在。"""
        pick = self._form.get('pick') if self._form else None
        if self.viewport is not None:
            self.viewport.pick_vertices = bool(pick and pick['kind'] == 'vertex') or self._measure is not None
            if not (pick and pick['kind'] == 'vertex') and self._measure is None:
                self.viewport.set_overlay()
        self._show_handle()
        self._show_axis()

    def _handle_axis(self):
        """拉伸面板开着并且深度是填出来的 (给定深度 / 两侧对称): → (草图轮廓的中心, 草图法向); 别的时候 None。"""
        form = self._form
        if form is None or form['kind'] != 'extrude' or self._sketch is not None:
            return None
        values = forms.values_of(form)
        if values.get('end') not in ('blind', 'mid'):
            return None
        identifier = values.get('sketch') or (self._find(form['editing']) or {}).get('params', {}).get('sketch')
        sketch = self._find(identifier) if identifier else None
        lines = self.session.model.get('sketches', {}).get(identifier)
        if sketch is None or lines is None or not len(lines):
            return None
        try:
            frame = table.plane_frame(sketch['params'].get('plane', 'XY'), self.session.document.features,
                                      float(sketch['params'].get('offset') or 0.0))
            _, _, _, normal = planes.frame(frame)
        except (ValueError, KeyError, TypeError):
            return None
        points = np.asarray(lines, dtype=float).reshape(-1, 3)
        return (points.min(axis=0) + points.max(axis=0)) / 2, np.asarray(normal, dtype=float)

    def _show_handle(self):
        if self.viewport is None:
            return
        axis = self._handle_axis()
        if axis is None:
            self.viewport.set_handle()
            return
        values = forms.values_of(self._form)
        reach = abs(values['distance']) / 2 if values['end'] == 'mid' else abs(values['distance']) * (-1 if values.get('reverse') else 1)
        self.viewport.set_handle(axis[0], axis[1], reach)

    def _on_handle(self, reach):
        """箭头被拖到了离草图平面 reach 的地方 (沿法向, 可正可负)。"""
        form = self._form
        if form is None or form['kind'] != 'extrude':
            return
        values = forms.values_of(form)
        step = 0.5 if abs(reach) >= 5 else 0.1          # 拖出来的数取整齐一点
        size = max(round(abs(reach) / step) * step, step)
        for field in form['fields']:
            if field['key'] == 'distance':
                field['value'] = size * 2 if values['end'] == 'mid' else size
            elif field['key'] == 'reverse' and values['end'] == 'blind':
                field['value'] = reach < 0
        self._form = dict(form)
        self.formChanged.emit()
        self._show_handle()
        self._preview()

    # ---- 预览: 面板开着的时候, 视图里画的是 "假如现在点确定" 的样子 ----
    @Property(str, notify=formChanged)
    @localized
    def previewNote(self):
        """预览算不出来的原因 (算得出来是空的)。"""
        return self._preview_note

    def _preview(self):
        self._preview_timer.start()

    def _clear_preview(self, note=''):
        self._preview_ticket += 1
        self._preview_timer.stop()
        if self.viewport is not None and not self.sim.mode:
            self.viewport.set_extras([])
        if note != self._preview_note:
            self._preview_note = note
            self.formChanged.emit()

    def _run_preview(self):
        form = self._form
        if form is None or self._sketch is not None or self.viewport is None:
            return
        spec = table.SPECS.get(form['kind'], {})
        if spec.get('reference') or spec.get('curve'):      # 基准面、曲线这些不改实体: 没有可预览的
            return
        try:
            name, args = forms.to_command(form, self.session)
        except (DocumentError, KeyError, ValueError, TypeError):
            self._clear_preview()                           # 还没填全 / 还没选边: 不是错, 只是还没东西可看
            return
        if name in ('fillet', 'chamfer') and not args.get('edges'):
            self._clear_preview()
            return
        if name == 'edit_feature':          # 编辑面板刚打开、还什么都没改: 结果就是现在的实体, 不用让内核再算一遍
            feature = self._find(args['id']) or {}
            current = feature.get('params') or {}
            if feature.get('type') in table.SPECS:          # 老文档里没有的新参数: 按默认值算
                current = dict(table.default_params(feature['type']), **current)
            elif feature.get('type') == 'extrude':
                current = dict({'end': 'mid' if current.get('symmetric') else 'blind', 'reverse': False, 'distance2': 0.0, 'gap': 0.0},
                               **current)
            if all(key in current and current[key] == value for key, value in args['params'].items()):
                self._clear_preview()
                return
        self._preview_ticket += 1
        ticket = self._preview_ticket

        def done(result, error):
            if ticket != self._preview_ticket or self._form is None:
                return
            if error or not result or result.get('verts') is None or result.get('errors'):
                self._clear_preview('预览：' + (error or '；'.join((result or {}).get('errors') or ['算不出实体'])))
                return
            self.viewport.set_extras([{'verts': result['verts'], 'normals': result['normals'], 'tris': result['tris'],
                                       'low': result['low'], 'high': result['high'], 'color': PREVIEW_TINT, 'cover': True, 'ghost': True}])
            if self._preview_note:
                self._preview_note = ''
                self.formChanged.emit()
        self.session.preview(name, args, done)

    @Slot()
    def acceptForm(self):
        form = self._form
        if form is None:
            return
        if self._sketch is not None:            # 草图里带 "确定" 的面板: 阵列、修复
            self._sketch.apply_operation()
            self._sketch_changed()
            return
        try:
            name, args = forms.to_command(form, self.session)
        except (DocumentError, KeyError, ValueError) as error:
            self.notice.emit(f'参数不对: {error}')
            return
        if name in ('fillet', 'chamfer') and not args['edges']:
            self.notice.emit('先在三维视图里点选要处理的边')
            return

        def done(result):
            # 新建的特征算失败了: 面板换成它的编辑面板, 改个数就能再试, 不用重新来一遍
            if not form['editing'] and result.get('id') and not result.get('ok'):
                self.editFeature(result['id'])
            elif not form['editing']:
                self._close_form()

        self._run(name, args, done)

    @Slot()
    def cancelForm(self):
        if self._sketch is not None:
            self._sketch.cancel_operation()
            self._sketch_changed()
            return
        self._close_form()

    def _close_form(self):
        if self._form is not None and self._sketch is None:
            self._form = None
            self.session.selection['vertices'] = []
            self._form_picks()
            self._clear_preview()
            self.formChanged.emit()

    def _refresh_form_info(self):
        """选边变了: 圆角 / 倒角面板上的 "已选 N 条边" 跟着变。"""
        form = self._form
        if not form or not form.get('pick'):
            return
        self._preview()                     # 选的边 / 面变了: 预览跟着变
        if form['kind'] in table.SPECS or form['kind'] == 'extrude':
            text = forms.pick_text(form, self.session)
        else:
            text = forms.edges_text(len(self.session.selection['edges']))
        for field in form['fields']:
            if field['key'] == form['pick']['key'] and field['type'] == 'info' and field['value'] != text:
                field['value'] = text
                self._form = dict(form)
                self.formChanged.emit()
