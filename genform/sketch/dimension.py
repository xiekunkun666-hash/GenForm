"""智能尺寸: 点一处 (线 / 圆 / 圆弧) 或两处 (点 / 线), 拉出标注放下, 存进草图 (dims), 改数挪图形。"""
from __future__ import annotations

import math

from ..sketchgeom import dist as _distance
from .. import sketchgeom as geom
from .common import HIT_PIXELS, _rect_from


def _dimension_spots(shape):
    """智能尺寸能点的点 → [(点键, (x, y))...]: 直线 / 圆弧端点 'e0' 'e1', 圆 / 圆弧 / 椭圆圆心 'c', 点图形自己 None。"""
    kind = shape['type']
    if kind == 'point':
        return [(None, (float(shape['x']), float(shape['y'])))]
    spots = []
    if kind in ('line', 'arc'):
        spots += [('e%d' % number, tuple(map(float, end))) for number, end in enumerate(geom.ends(shape) or ())]
    if kind in ('circle', 'arc', 'ellipse'):
        spots.append(('c', (float(shape.get('cx', 0.0)), float(shape.get('cy', 0.0)))))
    if kind in ('rect', 'polygon', 'ngon'):
        spots += [('v%d' % number, tuple(map(float, corner))) for number, corner in enumerate(geom.vertices(shape))]
    return spots


_DIM_PREFIX = {'d': 'Ø', 'r': 'R'}       # 直径 / 半径尺寸的数字前面加的记号


def _dim_value(mode, pair):
    (x1, y1), (x2, y2) = pair
    return abs(x2 - x1) if mode == 'h' else abs(y2 - y1) if mode == 'v' else _distance(pair[0], pair[1])


def _dim_direction(mode, p, q):
    """量的方向 (从第一处指向第二处的单位向量)。"""
    if mode == 'h':
        return (1.0 if q[0] >= p[0] else -1.0), 0.0
    if mode == 'v':
        return 0.0, (1.0 if q[1] >= p[1] else -1.0)
    span = _distance(p, q)
    return ((q[0] - p[0]) / span, (q[1] - p[1]) / span) if span > 1e-12 else (1.0, 0.0)


class DimensionMixin:
    """智能尺寸 (草图编辑器的一部分)。"""

    # ---- 智能尺寸 ----
    # 点一个图形 = 改它的主尺寸; 再点第二个 (点或线) = 两者之间的距离, 这时标注跟着鼠标走:
    # 往上下拉是水平距离、往左右拉是竖直距离、斜着拉是两点连线; 再点一下放下, 在面板里改数。
    # 端点 / 圆心 / 点图形附近先算点 (所以能选两个点), 点在线身上算整条线 (线到线、点到线量垂直距离)。
    def _press_dimension(self, pick):
        if pick is None:
            return
        index, spec = pick
        operation = self.operation
        if operation and operation['kind'] == 'dimension' and operation['b'] is None \
                and (index, spec) != (operation['a'], operation.get('pa')):
            trial = dict(operation, b=index, pb=spec, place=None, placed=False, single=None)
            pair = self._dim_points(trial)                  # 点了第二个: 标它们之间的距离
            if pair is None or _distance(*pair) < 1e-9:
                self.message = '这两处重合，标不了距离'
                return
            trial.update(mode='a', distance=round(_distance(*pair), 6))
            self.operation = trial
            self.selection = list(dict.fromkeys([operation['a'], index]))
            return
        self.selection = [index]
        self.operation = {'kind': 'dimension', 'a': index, 'pa': spec, 'b': None, 'single': self._single_kind(index, spec),
                          'place': None, 'placed': False}
        if self.operation['single']:                    # 一条线 / 一个圆: 尺寸先跟着鼠标走
            single = self.operation['single']
            self.operation['mode'] = single if single in ('d', 'r') else 'a'
            self.operation['distance'] = round(_dim_value(self.operation['mode'], self._dim_points(self.operation)), 6)

    def _single_kind(self, index, spec):
        """只点这一处能标什么: 'len' 线 / 边的长度, 'd' 圆的直径, 'r' 圆弧的半径; 点 (端点、圆心…) 是 None (等第二处)。"""
        if self._dim_line(index, spec) is not None:
            return 'len'
        kind = self.shapes[index]['type']
        if spec is None and kind == 'circle':
            return 'd'
        if spec is None and kind == 'arc':
            return 'r'
        return None

    def _single_points(self, operation):
        """单个尺寸量的两点: 线 = 两端; 圆 = 朝光标的那条直径的两端; 圆弧 = 圆心和朝光标的弧上一点。"""
        a, kind = operation['a'], operation.get('single')
        if kind == 'len':
            return self._dim_line(a, operation.get('pa'))
        shape = self.shapes[a]
        centre, radius = (float(shape.get('cx', 0.0)), float(shape.get('cy', 0.0))), float(shape['r'])
        place = operation.get('place')
        way = geom._unit(place[0] - centre[0], place[1] - centre[1]) \
            if place and _distance(place, centre) > 1e-9 else (0.7071, 0.7071)
        rim = (centre[0] + way[0] * radius, centre[1] + way[1] * radius)
        if kind == 'd':
            return (centre[0] - way[0] * radius, centre[1] - way[1] * radius), rim
        return centre, rim

    def _place_dimension(self):
        """把正在拉的尺寸放下: 存进草图 (dims), 选中它 (属性管理器里改数)。工具还是智能尺寸, 接着标下一个。"""
        operation = self.operation
        self.dims.append(self._dim_record(operation))
        self.operation, self.selection = None, []
        self.relation = f'dim:{len(self.dims) - 1}'

    def _dimension_pick(self, point, pixel):
        """智能尺寸点到了什么 → (图形序号, 点): 点 'e0' / 'e1' 端点, 'c' 圆心, 'v0'… 矩形 / 多边形的角, 's0'… 它们的边,
        None 整个图形 (点图形就是它自己); 没点到是 None。"""
        tolerance = HIT_PIXELS * pixel
        best = None
        for index, shape in enumerate(self.shapes):
            for spec, spot in _dimension_spots(shape):
                gap = _distance(spot, point)
                if gap <= tolerance and (best is None or gap < best[0]):
                    best = (gap, index, spec)
        if best is not None:
            return best[1], best[2]
        index = self._shape_at(point, pixel)
        if index is not None and self.shapes[index]['type'] in ('rect', 'polygon', 'ngon'):     # 点在边上: 选这条边
            corners = geom.vertices(self.shapes[index])
            sides = [geom._nearest_on_line(point, a, b) for a, b in zip(corners, corners[1:] + corners[:1])]
            side = min(range(len(corners)), key=lambda number: _distance(point, self._clamp_side(corners, number, sides[number])))
            return index, 's%d' % side
        return None if index is None else (index, None)

    @staticmethod
    def _clamp_side(corners, number, foot):
        """垂足夹回到这条边上 (算点离哪条边最近用)。"""
        a, b = corners[number], corners[(number + 1) % len(corners)]
        span = _distance(a, b) ** 2
        if span <= 1e-18:
            return a
        along = max(0.0, min(1.0, ((foot[0] - a[0]) * (b[0] - a[0]) + (foot[1] - a[1]) * (b[1] - a[1])) / span))
        return a[0] + (b[0] - a[0]) * along, a[1] + (b[1] - a[1]) * along

    def _dim_line(self, index, spec):
        """一处选取是 "一条线" (整条直线 / 矩形、多边形的一条边) → 它的两端; 是点就是 None。"""
        shape = self.shapes[index]
        if spec is None and shape['type'] == 'line':
            return (float(shape['x1']), float(shape['y1'])), (float(shape['x2']), float(shape['y2']))
        if spec and spec[0] == 's':
            corners = geom.vertices(shape)
            number = int(spec[1:]) % len(corners)
            return tuple(map(float, corners[number])), tuple(map(float, corners[(number + 1) % len(corners)]))
        return None

    def _dim_spot(self, index, spec):
        """一处选取 → 量距离用的点; 整条直线是 None (要按另一处找垂足)。"""
        shape = self.shapes[index]
        if self._dim_line(index, spec) is not None:
            return None
        if spec is None:
            return tuple(map(float, geom.anchor(shape)))      # 点、圆、矩形…: 用它自己的位置 / 中心
        return dict(_dimension_spots(shape)).get(spec)

    def _dim_points(self, operation):
        """两处选取 → (第一处上的点, 第二处上的点); 量不了是 None。整条线用垂足 (两条平行线 = 它们的间距)。"""
        a, b = operation['a'], operation.get('b')
        if b is None:
            return self._single_points(operation) if operation.get('single') and a < len(self.shapes) else None
        if max(a, b) >= len(self.shapes):
            return None
        p, q = self._dim_spot(a, operation.get('pa')), self._dim_spot(b, operation.get('pb'))

        first, second = self._dim_line(a, operation.get('pa')), self._dim_line(b, operation.get('pb'))

        def foot(line, point):                          # 落在直线 (不是线段) 上的垂足
            return geom._nearest_on_line(point, *line)

        if p is None and q is None:
            q = (second[0][0] + second[1][0]) / 2, (second[0][1] + second[1][1]) / 2
        if p is None:
            return foot(first, q), q
        if q is None:
            return p, foot(second, p)
        return p, q

    def _dim_mode(self, operation, pair):
        """标注放在哪 → 'h' 水平距离 / 'v' 竖直距离 / 'a' 连线距离。有一处是整条直线时只有垂直距离 ('a')。"""
        place = operation.get('place')
        single = operation.get('single') if operation.get('b') is None else None
        if single in ('d', 'r'):                        # 圆的直径 / 圆弧的半径
            return single
        whole = not single and any(self._dim_line(operation[key], operation.get('p' + key)) is not None for key in ('a', 'b'))
        if place is None or whole:
            return 'a'
        (x1, y1), (x2, y2) = pair
        if single == 'len':                             # 一条线: 光标在线旁边 (垂直投影落在线上) = 实际长度
            span = (x2 - x1) ** 2 + (y2 - y1) ** 2
            along = ((place[0] - x1) * (x2 - x1) + (place[1] - y1) * (y2 - y1)) / span if span > 1e-18 else 0.0
            if 0.0 <= along <= 1.0:
                return 'a'
        inside_x = min(x1, x2) <= place[0] <= max(x1, x2)
        inside_y = min(y1, y2) <= place[1] <= max(y1, y2)
        if inside_x and not inside_y:
            return 'h'
        if inside_y and not inside_x:
            return 'v'
        return 'a'

    def _dim_follow(self, point):
        """还没放下的标注跟着鼠标: 换量法, 数也跟着变。"""
        operation = self.operation
        if not (operation and operation['kind'] == 'dimension' and (operation.get('b') is not None or operation.get('single'))) \
                or operation.get('placed'):
            return
        pair = self._dim_points(operation)
        if pair is None:
            return
        operation['place'] = tuple(point)
        operation['mode'] = self._dim_mode(operation, pair)
        operation['distance'] = round(_dim_value(operation['mode'], pair), 6)

    def _dim_graphics(self, operation):
        """标注怎么画 → (线段 [(a, b)...], 数字放哪)。尺寸界线 + 两头带箭头的尺寸线。"""
        pair = self._dim_points(operation)
        if pair is None:
            return [], None
        p, q = pair
        mode = operation.get('mode', 'a')
        if mode in ('d', 'r'):                          # 直径: 穿过圆心两头带箭头; 半径: 圆心到弧上一个箭头; 光标在外面拉一根引线
            place = tuple(operation.get('place') or q)
            segments, size = [(p, q)], 9 * self._pixel
            for tip, back in ((q, p),) + (((p, q),) if mode == 'd' else ()):
                way = geom._unit(back[0] - tip[0], back[1] - tip[1])
                for side in (1, -1):
                    segments.append((tip, (tip[0] + way[0] * size - side * way[1] * size * 0.35,
                                           tip[1] + way[1] * size + side * way[0] * size * 0.35)))
            centre = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) if mode == 'd' else p
            if _distance(place, centre) > _distance(q, centre):
                segments.append((q, place))
            return segments, place
        direction = _dim_direction(mode, p, q)
        normal = (-direction[1], direction[0])
        place = operation.get('place') or ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)

        def level(point):
            return (place[0] - point[0]) * normal[0] + (place[1] - point[1]) * normal[1]

        ends = [(point[0] + normal[0] * level(point), point[1] + normal[1] * level(point)) for point in (p, q)]
        unit, segments = self._pixel, []
        for point, end in zip((p, q), ends):            # 尺寸界线: 离开图形一点, 越过尺寸线一点
            span = _distance(point, end)
            if span > 3 * unit:
                ux, uy = (end[0] - point[0]) / span, (end[1] - point[1]) / span
                segments.append(((point[0] + ux * 3 * unit, point[1] + uy * 3 * unit),
                                 (end[0] + ux * 6 * unit, end[1] + uy * 6 * unit)))
        segments.append((ends[0], ends[1]))
        span = _distance(*ends)
        if span > 1e-9:
            ux, uy = (ends[1][0] - ends[0][0]) / span, (ends[1][1] - ends[0][1]) / span
            size = 9 * unit
            for tip, sign in ((ends[0], 1), (ends[1], -1)):
                for side in (1, -1):
                    segments.append((tip, (tip[0] + sign * ux * size + side * normal[0] * size * 0.35,
                                           tip[1] + sign * uy * size + side * normal[1] * size * 0.35)))
        middle = ((ends[0][0] + ends[1][0]) / 2, (ends[0][1] + ends[1][1]) / 2)
        return segments, middle

    def _dim_record(self, operation):
        place = operation.get('place')
        return {'a': operation['a'], 'pa': operation.get('pa'), 'b': operation['b'], 'pb': operation.get('pb'),
                'mode': operation.get('mode', 'a'), 'place': list(place) if place else None,
                'ta': self.shapes[operation['a']]['type'],
                'tb': self.shapes[operation['b']]['type'] if operation.get('b') is not None else None,
                'single': operation.get('single') if operation.get('b') is None else None}

    def _live_dims(self):
        """还对得上的尺寸 → [(序号, 尺寸)...]。对不上的 (图形删了、换了种类) 不画也不存。"""
        alive = []
        for number, dim in enumerate(self.dims):
            a, b = dim.get('a'), dim.get('b')
            if not (isinstance(a, int) and 0 <= a < len(self.shapes)) or self.shapes[a]['type'] != dim.get('ta'):
                continue
            if b is None:                               # 单个图形的尺寸 (长度 / 直径 / 半径)
                if not dim.get('single'):
                    continue
            elif not (isinstance(b, int) and 0 <= b < len(self.shapes)) or self.shapes[b]['type'] != dim.get('tb'):
                continue
            try:
                pair = self._dim_points(dim)
            except (KeyError, IndexError, ValueError, TypeError):
                pair = None
            if pair is not None:
                alive.append((number, dim))
        return alive

    def _forget_shapes(self, removed):
        """删了这些序号的图形: 尺寸跟着改序号, 量到删掉的图形的尺寸去掉。"""
        removed = set(removed)
        kept = []
        for dim in self.dims:
            if dim.get('a') in removed or dim.get('b') in removed:
                continue
            dim = dict(dim)
            for key in ('a', 'b'):
                if isinstance(dim.get(key), int):
                    dim[key] -= sum(1 for index in removed if index < dim[key])
            kept.append(dim)
        self.dims = kept

    def dim_labels(self):
        """尺寸的数字 → [(文字, (x, y) 尺寸线中点, 编号)...]: 放下的 (编号 "dim:序号", 点它选中) 和正在拉的 (编号空)。"""
        rows = []
        for number, dim in self._live_dims():
            segments, middle = self._dim_graphics(dim)
            if middle is not None:
                mode = dim.get('mode', 'a')
                rows.append((_DIM_PREFIX.get(mode, '') + f'{_dim_value(mode, self._dim_points(dim)):.4g}', middle, f'dim:{number}'))
        operation = self.operation
        if self.tool == 'dimension' and operation and operation['kind'] == 'dimension' \
                and (operation.get('b') is not None or operation.get('single')):
            segments, middle = self._dim_graphics(operation)
            if middle is not None:
                rows.append((_DIM_PREFIX.get(operation.get('mode'), '') + f'{float(operation["distance"]):.4g}', middle, ''))
        return rows

    def _dim_at(self, point, pixel):
        """光标下的放下的尺寸 → 序号, 没有是 None。数字附近最优先; 尺寸线 / 尺寸界线上只在不压着图形时算
        (不然想拖线的端点却拖走了尺寸)。"""
        tolerance = HIT_PIXELS * pixel
        dims = list(reversed(self._live_dims()))
        drawn = [(number, *self._dim_graphics(dim)) for number, dim in dims]
        for number, _, middle in drawn:
            if middle is not None and _distance(point, middle) <= 2.5 * tolerance:
                return number
        if self._shape_at(point, pixel) is not None:
            return None
        for number, segments, _ in drawn:
            if any(_distance(point, geom._nearest_on_segment(point, a, b)) <= tolerance for a, b in segments):
                return number
        return None

    def move_dimension(self, number, point):
        """把放下的尺寸挪个地方: 尺寸线和数字跟着光标, 量法 (水平 / 竖直 / 连线 / 直径…) 和量出来的数都不变。"""
        if 0 <= number < len(self.dims):
            self.dims[number] = dict(self.dims[number], place=[float(point[0]), float(point[1])])

    def _apply_single(self, operation):
        """单个图形的尺寸改成 wanted: 圆 / 圆弧改半径 (圆心不动); 直线改长度 (起点不动, 按量法挪终点);
        矩形的边改宽 / 高 (左边 / 下边不动); 正多边形的边改边长; 多边形的边挪后一个角。"""
        kind, index, spec = operation.get('single'), operation['a'], operation.get('pa')
        wanted = float(operation['distance'])
        shape = self.shapes[index]
        if not kind or wanted <= 1e-9:
            self.message = '尺寸要大于 0'
            return
        if kind in ('d', 'r'):
            self.shapes[index] = dict(shape, r=wanted / 2 if kind == 'd' else wanted)
            return
        mode = operation.get('mode', 'a')
        if shape['type'] == 'line':
            p, q = (float(shape['x1']), float(shape['y1'])), (float(shape['x2']), float(shape['y2']))
            now = _dim_value(mode, (p, q))
            if mode == 'a' and now <= 1e-9:
                return
            way = _dim_direction(mode, p, q)
            self.shapes[index] = dict(shape, x2=q[0] + way[0] * (wanted - now), y2=q[1] + way[1] * (wanted - now))
            return
        side = int(spec[1:])
        if shape['type'] == 'rect':
            corners = geom.vertices(shape)
            if side % 2 == 0:
                left = min(x for x, _ in corners)
                self.shapes[index] = dict(shape, w=wanted, cx=left + wanted / 2)
            else:
                bottom = min(y for _, y in corners)
                self.shapes[index] = dict(shape, h=wanted, cy=bottom + wanted / 2)
        elif shape['type'] == 'ngon':
            sides = int(shape.get('sides', 6))
            self.shapes[index] = dict(shape, r=wanted / (2 * math.sin(math.pi / sides)))
        elif shape['type'] == 'polygon':
            points = [list(point) for point in shape['points']]
            start, end = points[side % len(points)], points[(side + 1) % len(points)]
            span = _distance(start, end)
            if span > 1e-9:
                points[(side + 1) % len(points)] = [start[0] + (end[0] - start[0]) * wanted / span,
                                                    start[1] + (end[1] - start[1]) * wanted / span]
                self.shapes[index] = dict(shape, points=points)

    def _apply_dimension(self, operation):
        """把第二处挪到要的距离: 选的是直线端点就只挪那个端点, 矩形的角 / 边就只挪那个角 / 那条边 (矩形跟着变大小),
        多边形的角就只挪那个角, 不然整个图形沿量的方向平移。"""
        if operation.get('b') is None:
            self._apply_single(operation)
            return
        pair = self._dim_points(operation)
        wanted = float(operation['distance'])
        if pair is None or wanted < 0:
            return
        mode = operation.get('mode', 'a')
        now = _dim_value(mode, pair)
        if mode == 'a' and now <= 1e-9:
            return
        direction = _dim_direction(mode, *pair)
        dx, dy = direction[0] * (wanted - now), direction[1] * (wanted - now)
        index, spec = operation['b'], operation.get('pb')
        shape = self.shapes[index]
        if shape['type'] == 'line' and spec in ('e0', 'e1'):
            moved = dict(shape)
            end = '1' if spec == 'e0' else '2'
            moved['x' + end], moved['y' + end] = float(shape['x' + end]) + dx, float(shape['y' + end]) + dy
            self.shapes[index] = moved
        elif shape['type'] == 'rect' and spec and spec[0] in 'vs':
            corners = [list(corner) for corner in geom.vertices(shape)]
            number = int(spec[1:]) % 4
            if spec[0] == 'v':                          # 挪一个角: 对角不动
                opposite = corners[(number + 2) % 4]
                corner = (corners[number][0] + dx, corners[number][1] + dy)
                made = _rect_from([corner, opposite])
            else:                                       # 挪一条边: 对边不动
                for moving in (number, (number + 1) % 4):
                    corners[moving] = [corners[moving][0] + dx, corners[moving][1] + dy]
                made = _rect_from(corners)
            if made['w'] > 1e-9 and made['h'] > 1e-9:
                self.shapes[index] = dict(shape, **made)
            else:
                self.message = '矩形会被压扁，没有改'
        elif shape['type'] == 'polygon' and spec and spec[0] == 'v':
            points = [list(point) for point in shape['points']]
            number = int(spec[1:]) % len(points)
            points[number] = [points[number][0] + dx, points[number][1] + dy]
            self.shapes[index] = dict(shape, points=points)
        else:
            self.shapes[index] = geom.moved(shape, dx, dy)
