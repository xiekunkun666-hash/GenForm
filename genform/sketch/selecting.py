"""选择和拖动: 点中哪个图形 / 端点 / 矩形的边, 拖动整体、控制点或一条边。"""
from __future__ import annotations

import copy
import math

from ..sketchgeom import dist as _distance
from .. import sketchgeom as geom
from .common import _degrees, handles, HIT_PIXELS, _line_distance, _rect_from, SNAP_PIXELS


class SelectMixin:
    """选择和拖动 (草图编辑器的一部分)。"""

    # ---- 选择和拖动 ----
    def _lines(self, shape):
        """图形 → 要画的折线。文本是字的轮廓 (界面给; 没有就画个占位框)。"""
        if shape['type'] == 'point':
            return []
        if shape['type'] != 'text':
            return geom.polylines(shape)
        if self.outliner is not None:
            return self.outliner(shape)
        height = float(shape.get('height', 10.0))
        wide = height * 0.9 * max(len(str(shape.get('text', ''))), 1)
        turn = math.radians(shape.get('angle', 0.0))
        cos, sin = math.cos(turn), math.sin(turn)
        box = [(0, 0), (wide, 0), (wide, height), (0, height), (0, 0)]
        return [[(shape['x'] + x * cos - y * sin, shape['y'] + x * sin + y * cos) for x, y in box]]

    def _hit(self, shape, point, tolerance):
        if shape['type'] != 'text':
            return geom.hit(shape, point, tolerance)
        spots = [spot for line in self._lines(shape) for spot in line] or [(shape['x'], shape['y'])]
        return min(x for x, _ in spots) - tolerance <= point[0] <= max(x for x, _ in spots) + tolerance \
            and min(y for _, y in spots) - tolerance <= point[1] <= max(y for _, y in spots) + tolerance

    def _shape_at(self, point, pixel):
        tolerance = HIT_PIXELS * pixel
        for index in self.selection:
            if self._hit(self.shapes[index], point, tolerance):
                return index
        for index in range(len(self.shapes) - 1, -1, -1):
            if self._hit(self.shapes[index], point, tolerance * (1.6 if self.shapes[index]['type'] == 'point' else 1.0)):
                return index
        return None

    def _reference_at(self, point, pixel):
        best = min(range(len(self.references)), key=lambda index: geom.nearest(self.references[index], point)[0], default=None)
        if best is not None and geom.nearest(self.references[best], point)[0] <= HIT_PIXELS * pixel:
            return best
        return None

    def _press_select(self, point, pixel, additive):
        if additive or self._edge() is None:
            self.edge = None
        if self.selected is not None and not additive and not self.shapes[self.selected].get('fixed'):
            for name, position in handles(self.shapes[self.selected]):
                if _distance(position, point) <= SNAP_PIXELS * pixel:
                    self._drag = {'handle': name, 'origin': point, 'base': self.selected,
                                  'shapes': {self.selected: copy.deepcopy(self.shapes[self.selected])}}
                    return
        if not additive:                    # 没选中也能直接点住端点 / 矩形的角拖 (选中它, 拖的是那个点)
            found = self._point_at(point, pixel)
            if found is not None:
                index, name = found
                self.selection = [index]
                if not self.shapes[index].get('fixed'):
                    self._drag = {'handle': name, 'origin': point, 'base': index, 'shapes': {index: copy.deepcopy(self.shapes[index])}}
                return
        index = self._shape_at(point, pixel)
        if not additive and index is not None and self.shapes[index]['type'] == 'rect' \
                and not (index in self.selection and self.edge is None and len(self.selection) >= 1):
            # 点在矩形的一条边上: 只选这条边; 拖它 = 对边不动, 矩形变大小 (整个矩形: 双击或框选后再拖)
            side = self._side_at(index, point)
            self.selection, self.edge = [index], (index, side)
            if not self.shapes[index].get('fixed'):
                self._drag = {'handle': f'side{side}', 'origin': point, 'base': index, 'shapes': {index: copy.deepcopy(self.shapes[index])}}
            return
        self.edge = None
        if additive:
            if index is not None:
                self.selection = [item for item in self.selection if item != index] if index in self.selection \
                    else self.selection + [index]
            return
        if index is None:
            self.selection, self._box = [], [point, point]
            return
        if index not in self.selection:
            self.selection = [index]
        if any(self.shapes[item].get('fixed') for item in self.selection):
            return                      # 固定着的: 点得中, 拖不动
        self._drag = {'handle': None, 'origin': point, 'base': index,
                      'shapes': {item: copy.deepcopy(self.shapes[item]) for item in self.selection}}

    def _edge(self):
        """选中的矩形的边 (还对得上时) → (序号, 边号), 不然 None。"""
        edge = self.edge
        if edge and self.selection == [edge[0]] and edge[0] < len(self.shapes) and self.shapes[edge[0]]['type'] == 'rect':
            return edge
        return None

    def _side_at(self, index, point):
        """矩形上离 point 最近的边号。"""
        corners = geom.vertices(self.shapes[index])
        return min(range(4), key=lambda side: _distance(point, self._clamp_side(corners, side, geom._nearest_on_line(
            point, corners[side], corners[(side + 1) % 4]))))

    def _point_at(self, point, pixel):
        """光标下的端点 / 角 (直线两头、圆弧两头、矩形和多边形的角) → (图形序号, 控制点名); 没有是 None。最近的那个。"""
        best, tolerance = None, SNAP_PIXELS * pixel
        for index, shape in enumerate(self.shapes):
            for name, position in handles(shape):
                if not (name in ('p1', 'p2', 'start', 'end') and shape['type'] in ('line', 'arc') or name.startswith(('corner', 'vertex'))):
                    continue
                gap = _distance(position, point)
                if gap <= tolerance and (best is None or gap < best[0]):
                    best = (gap, index, name)
        return None if best is None else (best[1], best[2])

    def _move_drag(self, point, pixel):
        drag, handle = self._drag, self._drag['handle']
        before = drag['shapes'][drag['base']]
        if handle is None:
            # 整体移动: 让按住的那个图形的基准点落在捕捉位置上, 选中的其余图形跟着平移
            base = geom.anchor(before)
            wanted = (base[0] + point[0] - drag['origin'][0], base[1] + point[1] - drag['origin'][1])
            target = self.snap(wanted, pixel, skip=self.selection, loose=False)
            for index, original in drag['shapes'].items():
                self.shapes[index] = geom.moved(original, target[0] - base[0], target[1] - base[1])
            self.cursor = target
            return
        shape = self.shapes[drag['base']]
        target = self.snap(point, pixel, skip=drag['base'], loose=False)
        self.cursor = target
        kind = shape['type']
        centre = (before.get('cx', 0.0), before.get('cy', 0.0))
        if handle.startswith('side'):                  # 矩形的一条边: 只沿它的法向挪, 对边不动
            side = int(handle[4:])
            corners = [list(corner) for corner in geom.vertices(before)]
            if side % 2 == 0:
                shift = (0.0, target[1] - corners[side][1])
            else:
                shift = (target[0] - corners[side][0], 0.0)
            for moving in (side, (side + 1) % 4):
                corners[moving] = [corners[moving][0] + shift[0], corners[moving][1] + shift[1]]
            made = _rect_from(corners)
            if made['w'] > 1e-9 and made['h'] > 1e-9:
                shape.update(made)
        elif handle.startswith('corner'):
            opposite = geom.vertices(before)[(int(handle[6:]) + 2) % 4]
            width, height = abs(target[0] - opposite[0]), abs(target[1] - opposite[1])
            if width > 1e-9 and height > 1e-9:
                shape.update(cx=(target[0] + opposite[0]) / 2, cy=(target[1] + opposite[1]) / 2, w=width, h=height)
        elif handle == 'center':
            shape['cx'], shape['cy'] = target
        elif handle == 'rim':
            radius = self._radius(centre)
            if radius > 1e-9:
                shape['r'] = radius
        elif handle.startswith('vertex') and kind in ('polygon', 'spline'):
            shape['points'][int(handle[6:])] = [target[0], target[1]]
        elif handle == 'vertex':                            # 正多边形的顶点: 改大小和朝向
            radius = self._radius(centre)
            if radius > 1e-9:
                shape['r'], shape['angle'] = radius, _degrees(centre, target)
        elif handle in ('p1', 'p2'):
            other = (before['x2'], before['y2']) if handle == 'p1' else (before['x1'], before['y1'])
            if _distance(other, target) > 1e-9:
                shape['x' + handle[1]], shape['y' + handle[1]] = target
        elif handle == 'at':
            shape['x'], shape['y'] = target
        elif handle in ('start', 'end') and _distance(centre, target) > 1e-9:
            shape['a0' if handle == 'start' else 'a1'] = _degrees(centre, target)
        elif handle == 'major' and _distance(centre, target) > 1e-9:
            shape['rx'], shape['angle'] = _distance(centre, target), _degrees(centre, target)
        elif handle == 'minor' and self._round(_distance(centre, self._raw)) > 1e-9:
            shape['ry'] = self._round(_distance(centre, self._raw))
        elif handle == 'width':
            width = self._round(2 * _line_distance(self._raw, (before['x1'], before['y1']), (before['x2'], before['y2'])))
            if width > 1e-9:
                shape['w'] = width
