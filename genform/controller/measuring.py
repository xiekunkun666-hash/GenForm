"""测量: 在视图里点面 / 边 / 顶点, 看尺寸、距离和夹角。"""
from __future__ import annotations

from PySide6.QtCore import Property, Slot

from ..i18n import localized
from .common import MEASURE_NAMES
from .signals import measureChanged


class MeasureMixin:
    """测量 (控制器的一部分)。"""

    # ---- 测量 ----
    @Property(bool, notify=measureChanged)
    def measuring(self):
        return self._measure is not None

    @Slot()
    def toggleMeasure(self):
        """测量开关。开着时在视图里点面 / 边 / 顶点: 点一个看它自己的尺寸, 点两个看它们之间的距离和夹角。"""
        if self._measure is not None:
            self._stop_measure()
            return
        if self._sketch is not None:
            self.notice.emit('正在编辑草图：先点右上角的 ✓ 完成草图，再测量')
            return
        if self._kind == 'assembly':            # 装配体: 点零部件量它的尺寸, 点两个量它们之间的距离
            if not self.sim._parts:
                self.notice.emit('装配体里还没有零件可以测量')
                return
            self._drop_context()
            self.sim.selectPart(-1)
            self._measure = {'items': [], 'result': None, 'error': '', 'parts': True}
            self._show_measure()
            return
        if not self.session.model.get('has_body'):
            self.notice.emit('还没有实体可以测量')
            return
        self._close_form()
        self.sim.close()
        self._stop_picking_plane()
        self._drop_context()
        self._measure = {'items': [], 'result': None, 'error': ''}
        self.session.selection.update(faces=[], edges=[], plane=None, feature=None)
        if self.viewport is not None:
            self.viewport.pick_vertices = True
        self._show_measure()

    def _stop_measure(self):
        if self._measure is None:
            return
        parts = self._measure.get('parts')
        self._measure = None
        if parts:
            self.sim.markMeasured([])
        if self.viewport is not None:
            self.viewport.pick_vertices = False
            self.viewport.set_overlay()
            if parts:
                self.sim._paint()               # 实时检查的红叉再画回来
        self.session.selection.update(faces=[], edges=[])
        self._push_selection()
        self.measureChanged.emit()

    def _measure_part(self, index):
        """装配体里测量点了一个零部件 (-1 = 点了空白处, 重新选)。"""
        state = self._measure
        if index < 0:
            state.update(items=[], result=None, error='')
        elif index not in state['items']:
            if len(state['items']) >= 2:
                state['items'] = []
            state['items'].append(index)
            state.update(result=None, error='')
            wanted = list(state['items'])

            def done(result, error):
                if self._measure is not state or state['items'] != wanted:
                    return
                state.update(result=result, error=error or '')
                self._show_measure()
            posed = self.sim._posed_parts()             # 门开着就量开着的样子
            self.session.query('measure_parts', {'parts': [posed[number] for number in wanted]}, done)
        self._show_measure()

    def _parts_measure(self, state, result, infos, rows, add):
        """装配体里测量的面板: 一个零部件 → 长宽高、体积、表面积; 两个 → 最短距离、ΔX ΔY ΔZ, 再各自的长宽高。"""
        names = [self.sim.components[index]['label'] for index in state['items'] if index < len(self.sim._parts)]
        if len(infos) == 2:
            add('最短距离', result['distance'], strong=True)
            for axis, value in zip('XYZ', result['delta']):
                add(f'Δ{axis}', value)
        for number, info in enumerate(infos):
            rows.append({'label': f'零部件 {number + 1}' if len(infos) == 2 else '零部件',
                         'value': names[number] if number < len(names) else '', 'strong': False})
            for axis, value in zip(('长 (X)', '宽 (Y)', '高 (Z)'), info['size']):
                add(axis, value)
            add('体积', info['volume'] / 1000.0, 'cm³')
            add('表面积', info['area'] / 100.0, 'cm²')
        count = len(state['items'])
        if state['error']:
            hint = state['error']
        elif count and not result:
            hint = '计算中…'
        else:
            hint = ['点一个零部件：看它的长宽高、体积', '再点一个：看两个零件之间最短的距离（点空白处重新选）',
                    '再点别的 = 重新开始测量'][count]
        return {'hint': hint, 'rows': rows}

    def _measure_pick(self, kind, identifier):
        state = self._measure
        if kind not in ('face', 'edge', 'vertex'):
            state.update(items=[], result=None, error='')          # 点了空白处: 重新选
        else:
            item = {'kind': kind, 'id': int(identifier)}
            if item in state['items']:
                return
            if len(state['items']) >= 2:                            # 已经有两个了: 从这个重新开始
                state['items'] = []
            state['items'].append(item)
            state.update(result=None, error='')
            wanted = [dict(entry) for entry in state['items']]

            def done(result, error):
                if self._measure is not state or state['items'] != wanted:      # 结果回来时用户已经选了别的
                    return
                state.update(result=result, error=error or '')
                self._show_measure()
            self.session.query('measure', wanted, done)
        self._show_measure()

    def _show_measure(self):
        """把测量选中的东西和结果画到视图里 (高亮、最近两点之间的连线、距离)。"""
        state = self._measure
        if state is None:
            return
        if state.get('parts'):                  # 装配体: 点着的零部件变蓝 (第二个也是), 最近两点连一条线
            self.sim.markMeasured(state['items'])
            lines, points, labels = [], [], []
            result = state['result'] or {}
            if 'points' in result:
                first, second = (tuple(point) for point in result['points'])
                if result['distance'] > 1e-9:
                    lines.append((first, second))
                points += [first, second]
                labels.append((f'{result["distance"]:.4g} mm', tuple((a + b) / 2 for a, b in zip(first, second))))
            if self.viewport is not None:
                self.viewport.set_overlay(lines, points, labels)
            self.measureChanged.emit()
            return
        selection = self.session.selection
        selection.update(faces=[item['id'] for item in state['items'] if item['kind'] == 'face'],
                         edges=[item['id'] for item in state['items'] if item['kind'] == 'edge'], plane=None, feature=None)
        corners = self.session.model.get('vertices')
        points = [tuple(float(value) for value in corners[item['id']]) for item in state['items']
                  if item['kind'] == 'vertex' and corners is not None and item['id'] < len(corners)]
        lines, labels = [], []
        result = state['result']
        if result and 'points' in result:
            first, second = (tuple(point) for point in result['points'])
            if result['distance'] > 1e-9:
                lines.append((first, second))
                points += [first, second]
            labels.append((f'{result["distance"]:.4g} mm', tuple((a + b) / 2 for a, b in zip(first, second))))
        if self.viewport is not None:
            self.viewport.set_overlay(lines, points, labels)
        self._push_selection()
        self.measureChanged.emit()

    @Property('QVariantMap', notify=measureChanged)
    @localized
    def measure(self):
        """测量面板上显示的: {'hint' 现在该干什么, 'rows': [{'label', 'value', 'strong'}...]}。"""
        state = self._measure
        if state is None:
            return {'hint': '', 'rows': []}
        rows = []

        def add(label, value, unit='mm', strong=False):
            rows.append({'label': label, 'value': f'{value:.4f}'.rstrip('0').rstrip('.') + (f' {unit}' if unit else ''), 'strong': strong})

        result = state['result'] or {}
        infos = result.get('items', [])
        if state.get('parts'):
            return self._parts_measure(state, result, infos, rows, add)
        if len(infos) == 2:
            add('最短距离', result['distance'], strong=True)
            if 'normal_distance' in result:
                add('平行面间距', result['normal_distance'], strong=True)
            if 'center_distance' in result:
                add('中心距', result['center_distance'], strong=True)
            if 'angle' in result:
                add('夹角', result['angle'], '°', strong=True)
            for axis, value in zip('XYZ', result['delta']):
                add(f'Δ{axis}', value)
        for number, info in enumerate(infos):
            rows.append({'label': f'对象 {number + 1}' if len(infos) == 2 else '对象', 'value': MEASURE_NAMES.get(info['type'], ''), 'strong': False})
            if 'area' in info:
                add('面积', info['area'], 'mm²')
            if 'length' in info:
                add('长度', info['length'])
            if 'radius' in info:
                add('半径', info['radius'])
                add('直径', info['radius'] * 2)
            if 'half_angle' in info:
                add('半锥角', info['half_angle'], '°')
            if info['type'] == 'vertex':
                for axis, value in zip('XYZ', info['point']):
                    add(axis, value)
        count = len(state['items'])
        if state['error']:
            hint = state['error']
        elif count and not result:
            hint = '计算中…'
        else:
            hint = ['点一个面、一条边或一个顶点', '再点一个：看它们之间的距离和夹角（点空白处重新选）', '再点别的 = 重新开始测量'][count]
        return {'hint': hint, 'rows': rows}
