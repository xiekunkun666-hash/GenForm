"""带面板的操作 (阵列、几何关系、修复) 和面板内容: 选中图形的精确尺寸、工具参数、改数。"""
from __future__ import annotations

import math

from ..sketchgeom import dist as _distance
from .. import sketchgeom as geom
from .common import _degrees, DIMENSIONS


class PanelMixin:
    """操作和面板 (草图编辑器的一部分)。"""

    # ---- 带面板的操作 ----
    def start_pattern(self):
        if not self.selection:
            self.message = '先选中要阵列的图形（点选，Ctrl 加选，或拖方框框选）'
            return
        self.set_tool('select') if self.tool != 'select' else None
        self.operation = {'kind': 'pattern', 'nx': 2, 'dx': 20.0, 'ny': 1, 'dy': 20.0}

    def start_circular_pattern(self):
        if not self.selection:
            self.message = '先选中要阵列的图形（点选，Ctrl 加选，或拖方框框选）'
            return
        selection = self.selection
        self.set_tool('select')
        self.selection = selection
        self.operation = {'kind': 'cpattern', 'count': 6, 'angle': 360.0, 'cx': 0.0, 'cy': 0.0}

    def start_relation(self):
        options = geom.relations_for(self._chosen()) if self.selection else []
        if not options:
            self.message = '先选中要加关系的图形：一条或几条直线、两个圆、一条线和一个圆…（第一个选中的不动，其余的向它看齐）'
            return
        selection = self.selection
        self.set_tool('select')
        self.selection = selection
        self.operation = {'kind': 'relation', 'choice': options[0]}

    def start_repair(self):
        selection = self.selection
        self.set_tool('select')
        self.selection = selection
        self.issues = geom.diagnose(self.shapes)
        self.operation = {'kind': 'repair'}

    def apply_operation(self):
        operation, self.operation = self.operation, None
        if operation is None:
            return
        if operation['kind'] in ('pattern', 'cpattern'):
            self.operation = operation
            copies = self._preview_shapes()
            self.operation = None
            self.shapes += copies
        elif operation['kind'] == 'relation':
            chosen = list(self.selection)
            self._try(lambda: geom.relate(self.shapes, chosen, operation['choice']))
            self.selection = chosen if not self.message else self.selection
        elif operation['kind'] == 'dimension':
            if operation['b'] is not None:
                self._apply_dimension(operation)
                if not self.message:
                    self.dims.append(self._dim_record(operation))
            self.selection = []
        elif operation['kind'] == 'repair':
            if any(issue['fixable'] for issue in self.issues):
                self.shapes, fixed = geom.repair(self.shapes)
                left = len(geom.diagnose(self.shapes))
                self.message = f'修了 {fixed} 处' + (f'，还有 {left} 处要自己改（见“修复草图”）' if left else '，草图没有问题了')
                self.selection, self.hover = [], None
            self.issues = []

    def cancel_operation(self):
        self.operation, self.issues = None, []

    # ---- 面板: 选中图形的精确尺寸、工具的参数、操作的参数 ----
    def panel(self):
        """现在该显示的面板 → {'title', 'fields', 'accept', 'cancel'} 或 None (不占地方)。"""
        operation = self.operation
        if operation and operation['kind'] == 'pattern':
            def count(key, label):
                return {'key': key, 'label': label, 'type': 'number', 'value': float(operation[key]), 'unit': '个'}

            def gap(key, label):
                return {'key': key, 'label': label, 'type': 'number', 'value': float(operation[key]), 'unit': 'mm'}
            return {'title': '线性草图阵列', 'accept': '确定', 'cancel': '取消',
                    'fields': [count('nx', 'X 方向数量'), gap('dx', 'X 方向间距'), count('ny', 'Y 方向数量'), gap('dy', 'Y 方向间距'),
                               {'key': 'hint', 'label': '', 'type': 'info', 'value': f'阵列选中的 {len(self.selection)} 个图形；数量包含原来的那个'}]}
        if operation and operation['kind'] == 'cpattern':
            def entry(key, label, unit):
                return {'key': key, 'label': label, 'type': 'number', 'value': float(operation[key]), 'unit': unit}
            return {'title': '圆周草图阵列', 'accept': '确定', 'cancel': '取消',
                    'fields': [entry('count', '数量', '个'), entry('angle', '总角度', '°'), entry('cx', '中心 X', 'mm'), entry('cy', '中心 Y', 'mm'),
                               {'key': 'hint', 'label': '', 'type': 'info',
                                'value': f'绕中心转着复制选中的 {len(self.selection)} 个图形；数量包含原来的那个，360° = 均布一圈'}]}
        if operation and operation['kind'] == 'relation':
            options = [{'value': key, 'label': geom.RELATIONS[key]} for key in geom.relations_for(self._chosen())]
            return {'title': '添加几何关系', 'accept': '添加', 'cancel': '取消',
                    'fields': [{'key': 'choice', 'label': '关系', 'type': 'choice', 'value': operation['choice'], 'options': options},
                               {'key': 'hint', 'label': '', 'type': 'info',
                                'value': '第一个选中的图形不动，其余的向它看齐。\n这是照关系摆一次：软件还没有约束求解，之后再拖动不会自动保持。'}]}
        if operation and operation['kind'] == 'dimension':
            if operation['b'] is not None:
                label = {'h': '水平距离', 'v': '竖直距离'}.get(operation.get('mode'), '距离')
                tip = '确定后第二处移动到这个距离：选的是直线端点就只挪那个端点（改一次，不是保持住的约束）' if operation.get('placed') \
                    else '移动鼠标拉出标注：往上下拉是水平距离，往左右拉是竖直距离，斜着拉是两点连线；点一下放下'
                return {'title': '智能尺寸', 'accept': '确定', 'cancel': '取消',
                        'fields': [{'key': 'distance', 'label': label, 'type': 'number', 'value': float(operation['distance']), 'unit': 'mm'},
                                   {'key': 'hint', 'label': '', 'type': 'info', 'value': tip}]}
            if operation['a'] < len(self.shapes) and self.selected == operation['a']:
                wanted = DIMENSIONS.get(self.shapes[operation['a']]['type'], ())
                rows = [field for field in self.fields() if field['key'] in wanted]
                tip = '移动鼠标拉出尺寸，点空白处放下；点另一处 = 标它们之间的距离。' if operation.get('single') \
                    else '改数字后图形立刻跟着变。再点另一处 = 标它们之间的距离。' if rows \
                    else '再点另一处（点或线）可以标它们之间的距离。'
                return {'title': '智能尺寸', 'accept': '好', 'cancel': '',
                        'fields': rows + [{'key': 'hint', 'label': '', 'type': 'info', 'value': tip}]}
        if operation and operation['kind'] == 'repair':
            if not self.issues:
                text = '没有发现问题：没有废线、重复的线和没接上的端点。'
            else:
                counts = {}
                for issue in self.issues:               # 同一种问题合成一行, 不然八个线头就是八行一样的字
                    counts[issue['text']] = counts.get(issue['text'], 0) + 1
                shown = [f'· {text}' + (f'　× {count}' if count > 1 else '') for text, count in counts.items()]
                text = f'发现 {len(self.issues)} 处（视图里用点标出来了）：\n' + '\n'.join(shown)
            fixable = any(issue['fixable'] for issue in self.issues)
            return {'title': '修复草图', 'accept': '修复' if fixable else '好', 'cancel': '关闭' if fixable else '',
                    'fields': [{'key': 'hint', 'label': '', 'type': 'info', 'value': text}]}
        if self.selected is not None:       # side: 界面上不放左边的面板, 放右边的属性栏 (见 properties)
            return {'title': geom.NAMES[self.shapes[self.selected]['type']], 'accept': '', 'cancel': '', 'fields': self.fields(),
                    'side': True}
        if self.tool == 'fillet':
            return {'title': '绘制圆角', 'accept': '', 'cancel': '',
                    'fields': [{'key': 'opt_radius', 'label': '圆角半径', 'type': 'number', 'value': float(self.options['radius']), 'unit': 'mm'}]}
        if self.tool == 'ngon':
            return {'title': '多边形', 'accept': '', 'cancel': '',
                    'fields': [{'key': 'opt_sides', 'label': '边数', 'type': 'number', 'value': float(self.options['sides']), 'unit': '边'}]}
        if len(self.selection) > 1:
            return {'title': f'选中了 {len(self.selection)} 个图形', 'accept': '', 'cancel': '', 'side': True,
                    'fields': [{'key': 'hint', 'label': '', 'type': 'info',
                                'value': '拖动可以一起移动；Delete 删除；草图页里的镜向、阵列、移动对它们生效。'}]}
        return None

    def fields(self):
        """选中图形的尺寸 → 面板字段 (和 forms.py 的格式一样)。"""
        rows = [{'key': 'offset', 'label': '基准面偏移', 'type': 'number', 'value': self.offset, 'unit': 'mm'}]
        if self.selected is None:
            text = '用上方的工具在视图里画图形；点选一个后可以在这里填精确尺寸。' if not self.shapes \
                else f'共 {len(self.shapes)} 个图形。点选一个可以改尺寸，拖动可以移动。'
            return rows + [{'key': 'hint', 'label': '', 'type': 'info', 'value': text}]
        shape = self.shapes[self.selected]
        kind = shape['type']

        def number(key, label, value, unit='mm'):
            return {'key': key, 'label': label, 'type': 'number', 'value': float(value), 'unit': unit}

        centre = [number('cx', '中心 X', shape.get('cx', 0.0)), number('cy', '中心 Y', shape.get('cy', 0.0))]
        if kind == 'rect':
            rows += [number('w', '宽度', shape['w']), number('h', '高度', shape['h'])] + centre
        elif kind == 'circle':
            rows += [number('d', '直径', shape['r'] * 2), number('cx', '圆心 X', shape.get('cx', 0.0)),
                     number('cy', '圆心 Y', shape.get('cy', 0.0))]
        elif kind == 'line':
            first, second = (shape['x1'], shape['y1']), (shape['x2'], shape['y2'])
            rows += [number('len', '长度', _distance(first, second)), number('dir', '角度', _degrees(first, second), '°'),
                     number('x1', '起点 X', first[0]), number('y1', '起点 Y', first[1]),
                     number('x2', '终点 X', second[0]), number('y2', '终点 Y', second[1])]
        elif kind == 'arc':
            rows += [number('r', '半径', shape['r']), number('a0', '起始角', shape['a0'], '°'), number('a1', '终止角', shape['a1'], '°'),
                     number('cx', '圆心 X', shape['cx']), number('cy', '圆心 Y', shape['cy'])]
        elif kind == 'slot':
            first, second = (shape['x1'], shape['y1']), (shape['x2'], shape['y2'])
            rows += [number('len', '圆心距', _distance(first, second)), number('w', '槽宽', shape['w']),
                     number('dir', '角度', _degrees(first, second), '°'),
                     number('x1', '圆心 1 X', first[0]), number('y1', '圆心 1 Y', first[1])]
        elif kind == 'arcslot':
            rows += [number('r', '中心线半径', shape['r']), number('w', '槽宽', shape['w']), number('a0', '起始角', shape['a0'], '°'),
                     number('a1', '终止角', shape['a1'], '°'), number('cx', '圆心 X', shape['cx']), number('cy', '圆心 Y', shape['cy'])]
        elif kind == 'equation':
            explicit = shape.get('mode', 'explicit') == 'explicit'
            rows += [{'key': 'mode', 'label': '类型', 'type': 'choice', 'value': shape.get('mode', 'explicit'),
                      'options': [{'value': 'explicit', 'label': '显性 y=f(x)'}, {'value': 'parametric', 'label': '参数 x(t), y(t)'}]}]
            if not explicit:
                rows.append({'key': 'fx', 'label': 'x(t) =', 'type': 'text', 'value': str(shape.get('fx', 't'))})
            rows += [{'key': 'fy', 'label': 'y =' if explicit else 'y(t) =', 'type': 'text', 'value': str(shape.get('fy', '0'))},
                     number('t0', '从 x =' if explicit else '从 t =', shape.get('t0', 0.0), ''),
                     number('t1', '到 x =' if explicit else '到 t =', shape.get('t1', 1.0), ''),
                     number('ox', '平移 X', shape.get('ox', 0.0)), number('oy', '平移 Y', shape.get('oy', 0.0))]
        elif kind == 'ngon':
            rows += [number('sides', '边数', shape.get('sides', 6), '边'), number('r', '外接圆半径', shape['r']),
                     number('angle', '转角', shape.get('angle', 0.0), '°')] + centre
        elif kind == 'ellipse':
            rows += [number('rx', '长半轴', shape['rx']), number('ry', '短半轴', shape['ry']),
                     number('angle', '转角', shape.get('angle', 0.0), '°')] + centre
        elif kind == 'point':
            rows += [number('x', 'X', shape['x']), number('y', 'Y', shape['y'])]
        elif kind == 'text':
            rows += [{'key': 'text', 'label': '文字', 'type': 'text', 'value': str(shape.get('text', ''))},
                     number('height', '字高', shape.get('height', 10.0))]
            if shape.get('path'):
                rows += [{'key': 'flip', 'label': '换一侧 / 反向', 'type': 'bool', 'value': bool(shape.get('flip'))},
                         {'key': 'hint', 'label': '', 'type': 'info', 'value': f'沿一条{geom.NAMES[shape["path"]["type"]]}排列'}]
            else:
                rows += [number('angle', '转角', shape.get('angle', 0.0), '°'),
                         number('x', '位置 X', shape['x']), number('y', '位置 Y', shape['y'])]
        else:
            if kind == 'spline':
                rows.append({'key': 'closed', 'label': '封闭', 'type': 'bool', 'value': bool(shape.get('closed'))})
            for index, (x, y) in enumerate(shape['points']):
                rows += [number(f'p{index}x', f'点 {index + 1} X', x), number(f'p{index}y', f'点 {index + 1} Y', y)]
        if kind not in ('point', 'text'):
            rows.append({'key': 'construction', 'label': '构造线（只作参考，不参与拉伸）', 'type': 'bool', 'value': bool(shape.get('construction'))})
        return rows

    def set_field(self, key, value):
        if key == 'dim_value' and self.relation and self.relation.startswith('dim:'):     # 尺寸页上改了数
            try:
                wanted = float(value)
            except (TypeError, ValueError):
                return
            dim = self.dims[int(self.relation[4:])]
            if math.isfinite(wanted) and wanted >= 0:
                self._apply_dimension(dict(dim, distance=wanted))
            return
        if key in ('edge_length',) and self._edge() is not None:     # 矩形一条边的长度 = 它的宽或高
            index, side = self._edge()
            key = 'w' if side % 2 == 0 else 'h'
        operation = self.operation
        if operation and key == 'choice' and 'choice' in operation:
            operation['choice'] = str(value)
            return
        if operation and key in operation:
            try:
                value = float(value)
            except (TypeError, ValueError):
                return
            if key in ('nx', 'ny', 'count'):
                if 1 <= round(value) <= 100:
                    operation[key] = int(round(value))
            elif math.isfinite(value):
                operation[key] = value
            return
        shape = self.shapes[self.selected] if self.selected is not None else None
        if shape is not None and shape.get('fixed') and key != 'offset':
            self.message = '这个图形固定着：先取消“固定”再改'
            return
        if key in ('dx', 'dy') and shape is not None and shape['type'] == 'line':
            try:
                shape['x2' if key == 'dx' else 'y2'] = shape['x1' if key == 'dx' else 'y1'] + float(value)
            except (TypeError, ValueError):
                pass
            return
        if key == 'text' and shape is not None and shape['type'] == 'text':
            shape['text'] = str(value)
            return
        if key in ('flip', 'closed', 'construction') and shape is not None:
            if key == 'closed' and value and len(shape['points']) < 3:
                self.message = '封闭的样条至少要 3 个点'
                return
            shape[key] = bool(value)
            return
        if key in ('fx', 'fy', 'mode') and shape is not None and shape['type'] == 'equation':
            trial = dict(shape, **{key: str(value)})
            try:
                geom.equation_points(trial)             # 式子写错了就不收, 把原因告诉用户
            except ValueError as error:
                self.message = str(error)
                return
            shape[key] = str(value)
            return
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(value):
            return
        if key == 'offset':
            self.offset = value
        elif key == 'opt_radius':
            if value > 0:
                self.options['radius'] = value
        elif key == 'opt_sides':
            if 3 <= round(value) <= 100:
                self.options['sides'] = int(round(value))
        elif shape is None:
            return
        elif key in ('w', 'h', 'r', 'rx', 'ry', 'height'):
            if value > 0:
                shape[key] = value
        elif key == 'd':
            if value > 0:
                shape['r'] = value / 2
        elif key == 'sides':
            if 3 <= round(value) <= 100:
                shape['sides'] = int(round(value))
        elif key in ('len', 'dir') and shape['type'] in ('line', 'slot'):
            first, second = (shape['x1'], shape['y1']), (shape['x2'], shape['y2'])
            span = value if key == 'len' else _distance(first, second)
            turn = math.radians(value if key == 'dir' else _degrees(first, second))
            if span > 0:
                shape['x2'], shape['y2'] = first[0] + span * math.cos(turn), first[1] + span * math.sin(turn)
        elif key.startswith('p') and key[-1] in 'xy' and key[1:-1].isdigit() and 'points' in shape:
            shape['points'][int(key[1:-1])][0 if key.endswith('x') else 1] = value
        elif key in ('t0', 't1') and shape['type'] == 'equation':
            if abs(value - float(shape['t1' if key == 't0' else 't0'])) > 1e-12:
                shape[key] = value
        elif key in ('cx', 'cy', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'a0', 'a1', 'angle', 'ox', 'oy') and (key in shape or key in ('cx', 'cy', 'angle')):
            shape[key] = value
