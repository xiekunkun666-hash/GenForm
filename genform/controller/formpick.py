"""参数面板: 开命令、编辑特征、填参数; 面板开着时在视图里点草图 / 轴 / 基准面直接填进去。"""
from __future__ import annotations

import copy
import numpy as np
from PySide6.QtCore import Slot

from ..document import DocumentError
from .. import features as table, forms, planes


class FormPickMixin:
    """参数面板 (控制器的一部分)。"""

    # ---- 参数面板 ----
    @Slot(str)
    def startCommand(self, kind):
        """点了特征页里的命令。正在画草图时点拉伸: 先把草图存了, 接着就拉它 (不用先退出草图再回来点)。"""
        base = kind[:-4] if kind.endswith('_cut') else kind
        spec = table.SPECS.get(base)
        if self._sketch is not None:
            if kind in ('extrude', 'cut') or (spec and any(field['kind'] == 'sketch' for field in spec['fields'])):
                self._finish_sketch(lambda: self.startCommand(kind))     # 用草图的特征: 先存草图, 接着就做它
            else:
                self.notice.emit('正在编辑草图：先点右上角的 ✓ 完成草图')
            return
        self._close_form()
        self._stop_picking_plane()
        self._stop_measure()
        if (kind == 'cut' or kind.endswith('_cut')) and not self.session.model.get('has_body'):
            self.notice.emit('还没有实体可以切：先用“拉伸凸台”做出实体')
            return
        if spec is not None and not spec['fields']:      # 质心、边界框: 没有要填的, 直接加上
            self._run(base)
            return
        self.sim.close()
        self._form = forms.new_form(kind, self.session)
        self._form_picks()
        self.formChanged.emit()
        self._preview()

    @Slot(str)
    def editFeature(self, identifier):
        """双击特征: 草图进入草图编辑, 其他特征打开参数面板。"""
        if not self._leave_modes():
            return
        try:
            feature = self.session.document.find(identifier)
        except DocumentError as error:
            self.notice.emit(str(error))
            return
        self.session.selection['feature'] = identifier
        self._push_selection()
        if feature['type'] == 'sketch':
            params = feature['params']
            try:
                self._enter_sketch(self._sketch_editor(params.get('plane', 'XY'), offset=params.get('offset', 0.0),
                                                       shapes=params.get('shapes', ()), feature=identifier, name=feature['name'],
                                                       dims=params.get('dims', ())))
            except ValueError as error:
                self.notice.emit(str(error))
            return
        self._form = forms.feature_form(feature, self.session)
        self._form_picks()
        self.formChanged.emit()
        self._preview()

    @Slot(str, 'QVariant')
    def setField(self, key, value):
        """面板上改了一项。草图的尺寸立刻生效 (看得见); 其他特征等点 "确定"。"""
        if self._sketch is not None:        # 草图: 左边的操作面板和右边的属性栏都从这里进
            editor = self._sketch
            editor.set_field(key, value)
            if self._sketch_seen != editor.shapes:
                self._sketch_history.append(self._sketch_seen)
                self._sketch_seen = copy.deepcopy(editor.shapes)
            if editor.message:
                self.notice.emit(editor.message)
                editor.message = ''
            # 只让视图跟上, 不重建面板: 重建会让正在用 Tab 逐项填尺寸的输入框丢掉焦点
            if self.viewport is not None:
                self.viewport.refresh_sketch()
            self.changed.emit()
            return
        if self._form is None:
            return
        for field in self._form['fields']:
            if field['key'] == key:
                field['value'] = float(value) if field['type'] == 'number' else value
        if self._form['kind'] == 'extrude':
            if key == 'end':                    # 换了终止条件: 露出来的项、视图里该点什么都跟着换
                self.session.selection.update(faces=[], edges=[], vertices=[])
                self._form = dict(forms.arrange(self._form, self.session))
                self._form_picks()
                self._push_selection()
                self.formChanged.emit()
            elif key in ('reverse', 'sketch', 'distance'):
                self._show_handle()
        self._show_axis()
        self._preview()

    # ---- 面板开着时在视图里点东西: 草图、轴、基准面直接点着选 ----
    def _form_take(self, accepts, value, label=None):
        key = forms.take(self._form, accepts, value, label)
        if key is None:
            return False
        if self._form['kind'] == 'extrude':
            self._show_handle()
        self._form = dict(self._form)
        self.formChanged.emit()
        self._show_axis()
        self._preview()
        return True

    @Slot(str)
    def focusField(self, key):
        """点了面板上一项的名字: 接下来在视图里点的东西填这一项。"""
        if self._form is not None and any(key == name for name, _ in forms.field_kinds(self._form)):
            self._form = dict(self._form, active=key)
            self.formChanged.emit()

    def _line_token(self, origin, direction):
        return '@' + ','.join(f'{float(value):.6g}' for value in origin) + ';' + ','.join(f'{float(value):.6g}' for value in direction)

    def _form_take_edge(self, identifier):
        """点了实体的一条边: 直边就用它当轴, 圆边用它的轴线。"""
        edge = next((item for item in self.session.model.get('edges') or () if item['id'] == identifier), None)
        if edge is None:
            return False
        if edge.get('dir') is not None:
            token = self._line_token(edge['mid'], edge['dir'])
        elif edge.get('axis') is not None and edge.get('center') is not None:
            token = self._line_token(edge['center'], edge['axis'])
        else:
            return False
        return self._form_take(('axis',), token, forms.PICKED_AXIS)

    def _sketch_line_at_click(self, feature):
        """刚才点在这个草图的哪条直线上 → (第几条构造线 或 None, 过点, 方向); 没点在直线上: None。"""
        view = self.viewport
        if view is None or feature['type'] != 'sketch':
            return None
        try:
            origin, x_dir, y_dir, normal = planes.frame(table.plane_frame(
                feature['params'].get('plane', 'XY'), self.session.document.features, float(feature['params'].get('offset') or 0.0)))
        except (ValueError, KeyError, TypeError):
            return None

        def on_plane(x, y):
            eye, look = view._camera.ray(x, y, view.width(), view.height())
            slope = float(look @ normal)
            if abs(slope) < 1e-9:
                return None
            spot = eye + look * (float((origin - eye) @ normal) / slope) - origin
            return np.array([float(spot @ x_dir), float(spot @ y_dir)])
        here, near = on_plane(*view.click_at), on_plane(view.click_at[0] + 9, view.click_at[1])
        if here is None or near is None:
            return None
        best, limit, centre = None, float(np.hypot(*(near - here))), 0
        for shape in feature['params'].get('shapes', ()):
            if shape.get('type') != 'line':
                continue
            start, end = np.array([shape['x1'], shape['y1']], dtype=float), np.array([shape['x2'], shape['y2']], dtype=float)
            along = end - start
            if float(along @ along) < 1e-12:
                continue
            reach = min(max(float((here - start) @ along) / float(along @ along), 0.0), 1.0)
            gap = float(np.hypot(*(here - start - along * reach)))
            if gap <= limit:
                limit = gap
                best = (centre if shape.get('construction') else None,
                        origin + x_dir * start[0] + y_dir * start[1], x_dir * along[0] + y_dir * along[1])
            centre += bool(shape.get('construction'))
        return best

    def _form_take_line_under_click(self):
        """面板上有轴要选, 而刚才点的位置正好压着某个草图里的一条直线 (被面或预览挡着, 没直接点中草图): 拿它当轴。"""
        form = self._form
        if not any(sort == 'axis' for _, sort in forms.field_kinds(form)):
            return False
        values = forms.values_of(form)
        mine = values.get('sketch')
        sketches = [feature for feature in self.session.document.features
                    if feature['type'] == 'sketch' and not feature.get('suppressed') and not self._is_hidden(feature)]
        for feature in sorted(sketches, key=lambda item: item['id'] != mine):       # 面板上选着的那个草图先看
            line = self._sketch_line_at_click(feature)
            if line is not None and (line[0] is not None or feature['id'] == mine):
                self._form_take_feature(feature['id'])
                return True
        return False

    def _form_take_feature(self, identifier):
        feature = self._find(identifier)
        form = self._form
        if feature is None or form is None:
            return
        kind = feature['type']
        if kind == 'axis':
            self._form_take(('axis',), identifier)
        elif kind == 'plane':
            self._form_take(('plane',), identifier)
        elif kind in table.CURVE_KINDS:
            self._form_take(('path',), identifier)
        elif kind == 'sketch':
            values = forms.values_of(form)
            has_axis = any(sort == 'axis' for _, sort in forms.field_kinds(form))
            line = self._sketch_line_at_click(feature) if has_axis else None
            # 点在草图里的一条直线上, 而且这个草图已经是面板上选着的草图 (或者点的是构造线): 这条线当轴
            if line is not None and (line[0] is not None or identifier in (values.get('sketch'), values.get('path'))):
                first_centre = line[0] == 0 and values.get('sketch') == identifier and \
                    any(option['value'] == 'CL' for field in form['fields'] if field['key'] == 'axis' for option in field['options'])
                if first_centre:
                    self._form_take(('axis',), 'CL')                # 草图自己的第一条中心线: 记成 "草图里的中心线", 草图改了它跟着走
                else:
                    self._form_take(('axis',), self._line_token(line[1], line[2]), forms.PICKED_AXIS)
                return
            self._form_take(('sketch', 'path', 'sketches'), identifier)

    def _show_axis(self):
        """面板上有轴的那一项: 在视图里把这根轴画出来 (看得见选的是哪根)。"""
        form, view = self._form, self.viewport
        if view is None or self._measure is not None or (form is not None and (form.get('pick') or {}).get('kind') == 'vertex'):
            return
        lines = []
        if form is not None and self._sketch is None and self.session.model.get('has_body') is not None:
            values = forms.values_of(form)
            sketch = self._find(values.get('sketch')) if values.get('sketch') else None
            frame = None
            if sketch is not None:
                try:
                    frame = planes.frame(table.plane_frame(sketch['params'].get('plane', 'XY'), self.session.document.features,
                                                           float(sketch['params'].get('offset') or 0.0)))
                except (ValueError, KeyError, TypeError):
                    frame = None
            points = np.asarray(self.session.model.get('segments', ()), dtype=float).reshape(-1, 3)
            for key, sort in forms.field_kinds(form):
                if sort != 'axis':
                    continue
                try:
                    origin, direction = table.axis_of(values[key], self.session.document.features, frame)
                except (ValueError, KeyError, TypeError):
                    continue                    # 草图里的中心线 (CL) 这里不画: 它本来就在草图里看得见
                if len(points):
                    spread = (points - origin) @ direction
                    low, high = float(spread.min()), float(spread.max())
                else:
                    low, high = -30.0, 30.0
                pad = max((high - low) * 0.15, 5.0)
                lines.append((origin + direction * (low - pad), origin + direction * (high + pad)))
        view.set_overlay(lines=lines)
