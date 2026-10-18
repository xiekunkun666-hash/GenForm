"""画图工具点完以后生成图形: 各种工具点下的点 → 图形字典, 以及正在画的预览。"""
from __future__ import annotations

import math

from ..sketchgeom import dist as _distance
from .. import sketchgeom as geom
from .common import CHAIN_TOOLS, _degrees, grid_step, _line_distance, SPLINE_TOOLS, STEPS


class BuildMixin:
    """完成一个图形 (草图编辑器的一部分)。"""

    # ---- 完成一个图形 ----
    def _add(self, shape):
        self.shapes.append(shape)
        self.selection = [len(self.shapes) - 1]

    def _commit(self, last):
        tool, points = self.tool, self.draft['points'] + [last]
        self._track_sweep()
        made = self._preview_shapes()
        chosen = list(self.selection)
        self.draft = None
        if tool == 'mirror':
            copies = made[:-1]                              # 最后一条是镜向轴
            self.shapes += copies
            self.selection = list(range(len(self.shapes) - len(copies), len(self.shapes)))
            self.tool = 'select'
        elif tool == 'move':
            for index, shape in zip(chosen, made):
                self.shapes[index] = shape
            self.tool = 'select'
        elif made and len(points) == STEPS[tool]:
            self._add(made[0])

    def _commit_spline(self, closed):
        points = self.draft['points']
        self.draft = None
        if self.tool == 'sspline' and len(points) > geom.STYLE_POINTS:
            self.message = f'样式样条最多 {geom.STYLE_POINTS} 个控制点，多出来的没有用上'
            points = points[:geom.STYLE_POINTS]
        if len(points) >= (3 if closed else 2):
            self._add({'type': 'spline', 'points': [[x, y] for x, y in points], 'closed': closed,
                       **({'style': True} if self.tool == 'sspline' else {})})

    def _track_sweep(self):
        """画圆弧时记着光标绕圆心转过了多少: 往哪边转弧就往哪边画, 转过半圈也不会突然翻到另一边。"""
        draft = self.draft
        if self.tool not in ('arc', 'caslot') or draft is None or len(draft['points']) != 2:
            return
        centre, start = draft['points']
        if _distance(centre, draft['cursor']) < 1e-9:
            return
        raw = math.atan2(draft['cursor'][1] - centre[1], draft['cursor'][0] - centre[0]) \
            - math.atan2(start[1] - centre[1], start[0] - centre[0])
        best = min((raw + turn * geom.TAU for turn in (-2, -1, 0, 1, 2)), key=lambda value: abs(value - draft['sweep']))
        draft['sweep'] = max(-geom.TAU, min(geom.TAU, best))

    def _swept_arc(self, centre, start):
        """圆心 + 起点 + 记下来的转角 → 圆弧图形。"""
        begin, sweep = _degrees(centre, start), math.degrees(self.draft['sweep']) if self.draft else 0.0
        if abs(sweep) < 1e-6:
            return None
        low, high = (begin, begin + sweep) if sweep > 0 else (begin + sweep, begin)
        return {'type': 'arc', 'cx': centre[0], 'cy': centre[1], 'r': _distance(centre, start), 'a0': low, 'a1': high}

    def _build(self, tool, points):
        """已经点下的点 + 光标 → 现在这个图形的样子; 点得还不够时给一条示意线。"""
        first, last = points[0], points[-1]
        if tool in ('rect', 'crect'):
            width, height = abs(last[0] - first[0]), abs(last[1] - first[1])
            if width < 1e-9 or height < 1e-9:
                return None
            if tool == 'crect':                         # 中心矩形: 第一个点是中心
                return {'type': 'rect', 'cx': first[0], 'cy': first[1], 'w': width * 2, 'h': height * 2}
            return {'type': 'rect', 'cx': (first[0] + last[0]) / 2, 'cy': (first[1] + last[1]) / 2, 'w': width, 'h': height}
        if tool == 'midline':
            return self._line((2 * first[0] - last[0], 2 * first[1] - last[1]), last) if _distance(first, last) > 1e-9 else None
        if tool == 'circle':
            radius = self._radius(first)
            return {'type': 'circle', 'cx': first[0], 'cy': first[1], 'r': radius} if radius > 1e-9 else None
        if tool == 'ngon':
            radius = self._radius(first)
            if radius <= 1e-9:
                return None
            return {'type': 'ngon', 'cx': first[0], 'cy': first[1], 'r': radius, 'sides': int(self.options['sides']),
                    'angle': _degrees(first, last) if _distance(first, last) > 1e-9 else 0.0}
        second = points[1]
        if _distance(first, second) < 1e-9:
            return None
        if len(points) == 2:
            return self._line(first, second)
        third = points[2]
        if tool == 'circle3':
            found = geom.circle3(first, second, third)
            return {'type': 'circle', 'cx': found[0][0], 'cy': found[0][1], 'r': found[1]} if found else None
        if tool == 'pgram':
            corners = [first, second, third, (first[0] + third[0] - second[0], first[1] + third[1] - second[1])]
            return {'type': 'polygon', 'points': [list(corner) for corner in corners]} if abs(geom.signed_area(corners)) > 1e-9 else None
        if tool in ('rect3', 'crect3'):
            ux, uy = (second[0] - first[0]) / _distance(first, second), (second[1] - first[1]) / _distance(first, second)
            rise = (third[0] - first[0]) * -uy + (third[1] - first[1]) * ux      # 第三个点离第一条线多远 (带方向)
            if abs(rise) < 1e-9:
                return None
            side = (-uy * rise, ux * rise)
            if tool == 'rect3':
                corners = [first, second, (second[0] + side[0], second[1] + side[1]), (first[0] + side[0], first[1] + side[1])]
            else:                                       # 第一个点是中心, 第二个点是一条边的中点
                back = (2 * first[0] - second[0], 2 * first[1] - second[1])
                corners = [(second[0] + side[0], second[1] + side[1]), (second[0] - side[0], second[1] - side[1]),
                           (back[0] - side[0], back[1] - side[1]), (back[0] + side[0], back[1] + side[1])]
            return {'type': 'polygon', 'points': [list(corner) for corner in corners]}
        if tool == 'arc':
            return self._swept_arc(first, second)
        if tool in ('aslot3', 'caslot'):
            spine = geom.arc3(first, second, third) if tool == 'aslot3' else self._swept_arc(first, second)
            if spine is None or len(points) == 3:
                return spine
            centre = (spine['cx'], spine['cy'])
            width = self._round(2 * abs(_distance(centre, last if self.snapped else self._raw) - spine['r']))
            if not 1e-9 < width < 2 * spine['r']:
                return None
            return dict(spine, type='arcslot', w=width)
        side = _line_distance(last if self.snapped else self._raw, first, second)
        if tool in ('slot', 'cslot'):
            width = self._round(side * 2)
            if width <= 1e-9:
                return None
            start = first if tool == 'slot' else (2 * first[0] - second[0], 2 * first[1] - second[1])
            return {'type': 'slot', 'x1': start[0], 'y1': start[1], 'x2': second[0], 'y2': second[1], 'w': width}
        if tool == 'ellipse':
            minor = self._round(side)
            if minor <= 1e-9:
                return None
            return {'type': 'ellipse', 'cx': first[0], 'cy': first[1], 'rx': _distance(first, second), 'ry': minor,
                    'angle': _degrees(first, second)}
        return None

    def _preview_shapes(self):
        """正在画 / 正在做的操作现在会得到什么 → 图形列表 (还没定下来)。"""
        operation = self.operation
        if operation and operation['kind'] == 'pattern':
            return [geom.moved(shape, operation['dx'] * column, operation['dy'] * row)
                    for row in range(int(operation['ny'])) for column in range(int(operation['nx']))
                    if row or column for shape in self._chosen()]
        if operation and operation['kind'] == 'cpattern':
            count, total = int(operation['count']), float(operation['angle'])
            step = total / count if abs(abs(total) - 360.0) < 1e-9 else total / max(count - 1, 1)
            return [geom.rotated(shape, (operation['cx'], operation['cy']), step * turn)
                    for turn in range(1, count) for shape in self._chosen()]
        draft, tool = self.draft, self.tool
        if draft is None:
            return []
        points = draft['points'] + [draft['cursor']]
        if tool in CHAIN_TOOLS:
            return [self._line(points[0], points[1], tool == 'centerline')] if _distance(points[0], points[1]) > 1e-9 else []
        if tool in SPLINE_TOOLS:
            if _distance(points[-1], points[-2]) <= 1e-9:
                points = points[:-1]
            points = points[:geom.STYLE_POINTS] if tool == 'sspline' else points
            return [{'type': 'spline', 'points': [list(p) for p in points], 'closed': False,
                     **({'style': True} if tool == 'sspline' else {})}] if len(points) >= 2 else []
        if tool == 'offset':
            source = self.shapes[draft['source']]
            gap = geom.signed_distance(source, draft['cursor'])
            step = grid_step(self._pixel)
            made = geom.offset(source, round(gap / step) * step)
            return [made] if made is not None and round(gap / step) != 0 else []
        if tool == 'mirror':
            if _distance(points[0], points[1]) <= 1e-9:
                return []
            return [geom.mirrored(shape, points[0], points[1]) for shape in self._chosen()] + [self._line(points[0], points[1])]
        if tool == 'move':
            return [geom.moved(shape, points[1][0] - points[0][0], points[1][1] - points[0][1]) for shape in self._chosen()]
        shape = self._build(tool, points)
        return [shape] if shape is not None else []

    @staticmethod
    def _line(first, second, construction=False):
        line = {'type': 'line', 'x1': first[0], 'y1': first[1], 'x2': second[0], 'y2': second[1]}
        if construction:
            line['construction'] = True
        return line

    def preview(self):
        """正在画的图形现在的样子 → 图形字典或 None。"""
        made = self._preview_shapes() if self.draft is not None else []
        return made[0] if made else None
