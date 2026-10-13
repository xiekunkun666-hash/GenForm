# -*- coding: utf-8 -*-
"""草图的二维几何: 图形 → 基本曲线、采样、最近点、求交、剪裁、圆角、等距、镜向、找封闭轮廓、检查修复。
纯数学, 不碰界面库也不碰内核 — 草图编辑器 (sketcher.py) 和内核 (kernel/build.py) 共用同一套定义,
所以编辑时看到的和算出来的实体是同一条曲线。

图形 (草图特征 params['shapes'] 里的一项), 坐标是草图平面内的毫米, 角度是度 (逆时针):
    line     x1 y1 x2 y2
    arc      cx cy r a0 a1          从 a0 逆时针到 a1
    circle   cx cy r
    rect     cx cy w h
    polygon  points [[x, y]...]     封闭折线
    ngon     cx cy r sides angle    正多边形: r 是外接圆半径, angle 是第一个顶点的方向
    slot     x1 y1 x2 y2 w          直槽口: 两个圆心和槽宽
    ellipse  cx cy rx ry angle
    arcslot  cx cy r a0 a1 w        圆弧槽口: 中心线是一段圆弧 (从 a0 逆时针到 a1), w 是槽宽
    spline   points closed [style]  过这些点的样条; style=True 是样式样条: 点是控制点, 曲线只过首尾两个
    equation mode fx fy t0 t1 ox oy 方程式驱动的曲线: mode='explicit' 时 y = fy(x), x 从 t0 到 t1;
                                    mode='parametric' 时 x = fx(t), y = fy(t); 整体再平移 (ox, oy)
    point    x y                    只当捕捉和参考用, 不参与围面
    text     x y text height angle font [path flip]   path 是一条曲线图形: 文字沿着它排

任何图形都可以带 construction=True: 构造线 (中心线), 只作参考 — 不围面、不拉伸, 可以当镜向轴和旋转轴。

基本曲线 (prims 的结果, 角度是弧度):
    ('line', a, b)  ('arc', c, r, a0, a1)  ('circle', c, r)  ('ellipse', c, rx, ry, rot)
    ('bezier', p0, p1, …, pn)  ('point', p)        贝塞尔曲线的控制点个数不限 (三次的是 4 个)
"""
from __future__ import annotations

import copy
import math

TAU = 2 * math.pi
JOIN = 1e-6                 # 两个端点离这么近就算接上了 (mm)
GAP = 0.1                   # 检查草图: 端点差这么多以内算 "差一点没接上", 可以自动合上
TINY = 1e-3                 # 比这短的线算废线
CLOSED = ('rect', 'circle', 'polygon', 'ngon', 'slot', 'arcslot', 'ellipse')
NAMES = {'line': '直线', 'arc': '圆弧', 'circle': '圆', 'rect': '矩形', 'polygon': '多边形', 'ngon': '正多边形',
         'slot': '直槽口', 'arcslot': '圆弧槽口', 'ellipse': '椭圆', 'spline': '样条曲线', 'equation': '方程式曲线',
         'point': '点', 'text': '文本'}
STYLE_POINTS = 12           # 样式样条最多这么多个控制点
EQUATION_STEPS = 60         # 方程式曲线取这么多段
DEFAULT_FONT = 'Microsoft YaHei'


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(dx, dy):
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 0 else (1.0, 0.0)


def _polar(centre, radius, angle):
    return centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)


def _angle(centre, point):
    return math.atan2(point[1] - centre[1], point[0] - centre[0])


def _in_sweep(angle, a0, a1, slack=1e-9):
    return (angle - a0 + slack) % TAU <= (a1 - a0) + 2 * slack


def num(shape, key, default=None, positive=False):
    value = shape.get(key, default)
    if value is None:
        raise ValueError(f'草图轮廓缺少参数 {key}')
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'草图轮廓的 {key} 不是数字: {value!r}') from None
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f'草图轮廓的 {key} 必须是正数，现在是 {value:g}')
    return value


def _points(shape, least):
    points = [(float(p[0]), float(p[1])) for p in shape.get('points', ())]
    if len(points) < least:
        raise ValueError(f'{NAMES[shape["type"]]}至少要 {least} 个点')
    return points


def is_closed(shape):
    return shape.get('type') in CLOSED or (shape.get('type') == 'spline' and bool(shape.get('closed')))


# ---------------------------------------------------------------------------
# 图形 → 基本曲线
# ---------------------------------------------------------------------------
def vertices(shape):
    """矩形 / 多边形 / 正多边形的顶点 (逆时针)。"""
    kind = shape['type']
    if kind == 'rect':
        cx, cy = num(shape, 'cx', 0.0), num(shape, 'cy', 0.0)
        half_w, half_h = num(shape, 'w', positive=True) / 2, num(shape, 'h', positive=True) / 2
        return [(cx - half_w, cy - half_h), (cx + half_w, cy - half_h), (cx + half_w, cy + half_h), (cx - half_w, cy + half_h)]
    if kind == 'ngon':
        sides = int(num(shape, 'sides', 6))
        if not 3 <= sides <= 100:
            raise ValueError('正多边形的边数要在 3 到 100 之间')
        centre, radius = (num(shape, 'cx', 0.0), num(shape, 'cy', 0.0)), num(shape, 'r', positive=True)
        start = math.radians(num(shape, 'angle', 0.0))
        return [_polar(centre, radius, start + TAU * k / sides) for k in range(sides)]
    return _points(shape, 3)


def _spline_beziers(points, closed):
    """过这些点的样条 → 一串三次贝塞尔 (Catmull-Rom): 每一段的切线取前后两个点的连线方向。"""
    count = len(points)
    if count == 2:
        closed = False

    def at(index):
        return points[index % count] if closed else points[max(0, min(count - 1, index))]

    curves = []
    for k in range(count if closed else count - 1):
        before, start, end, after = at(k - 1), at(k), at(k + 1), at(k + 2)
        curves.append(('bezier', start,
                       (start[0] + (end[0] - before[0]) / 6, start[1] + (end[1] - before[1]) / 6),
                       (end[0] - (after[0] - start[0]) / 6, end[1] - (after[1] - start[1]) / 6), end))
    return curves


def prims(shape):
    kind = shape.get('type')
    if kind == 'line':
        return [('line', (num(shape, 'x1'), num(shape, 'y1')), (num(shape, 'x2'), num(shape, 'y2')))]
    if kind in ('rect', 'polygon', 'ngon'):
        ring = vertices(shape)
        return [('line', a, b) for a, b in zip(ring, ring[1:] + ring[:1])]
    if kind == 'circle':
        return [('circle', (num(shape, 'cx', 0.0), num(shape, 'cy', 0.0)), num(shape, 'r', positive=True))]
    if kind == 'arc':
        start = math.radians(num(shape, 'a0'))
        sweep = (math.radians(num(shape, 'a1')) - start) % TAU or TAU
        return [('arc', (num(shape, 'cx', 0.0), num(shape, 'cy', 0.0)), num(shape, 'r', positive=True), start, start + sweep)]
    if kind == 'ellipse':
        return [('ellipse', (num(shape, 'cx', 0.0), num(shape, 'cy', 0.0)), num(shape, 'rx', positive=True),
                 num(shape, 'ry', positive=True), math.radians(num(shape, 'angle', 0.0)))]
    if kind == 'slot':
        first, second = (num(shape, 'x1'), num(shape, 'y1')), (num(shape, 'x2'), num(shape, 'y2'))
        half = num(shape, 'w', positive=True) / 2
        if dist(first, second) < JOIN:
            raise ValueError('直槽口的两个圆心不能重合')
        ux, uy = _unit(second[0] - first[0], second[1] - first[1])
        nx, ny = -uy * half, ux * half                  # 朝左的半个槽宽
        turn = math.atan2(-ny, -nx)                     # 朝右的方向
        return [('line', (first[0] - nx, first[1] - ny), (second[0] - nx, second[1] - ny)),
                ('arc', second, half, turn, turn + math.pi),
                ('line', (second[0] + nx, second[1] + ny), (first[0] + nx, first[1] + ny)),
                ('arc', first, half, turn + math.pi, turn + TAU)]
    if kind == 'arcslot':
        centre, radius, half = (num(shape, 'cx', 0.0), num(shape, 'cy', 0.0)), num(shape, 'r', positive=True), num(shape, 'w', positive=True) / 2
        if half >= radius:
            raise ValueError('圆弧槽口的槽宽要小于圆弧直径')
        start = math.radians(num(shape, 'a0'))
        end = start + ((math.radians(num(shape, 'a1')) - start) % TAU or TAU)
        return [('arc', centre, radius + half, start, end), ('arc', _polar(centre, radius, end), half, end, end + math.pi),
                ('arc', centre, radius - half, start, end), ('arc', _polar(centre, radius, start), half, start + math.pi, start + TAU)]
    if kind == 'spline':
        if shape.get('style'):
            poles = _points(shape, 2)
            if len(poles) > STYLE_POINTS:
                raise ValueError(f'样式样条最多 {STYLE_POINTS} 个控制点')
            return [('bezier', *poles)]
        return _spline_beziers(_points(shape, 2), bool(shape.get('closed')))
    if kind == 'equation':
        return _spline_beziers(equation_points(shape), False)
    if kind == 'point':
        return [('point', (num(shape, 'x'), num(shape, 'y')))]
    if kind == 'text':
        num(shape, 'height', 10.0, positive=True)
        return []
    raise ValueError(f'不认识的轮廓类型 {kind!r}，可用 {" / ".join(NAMES)}')


def sample(prim, fine=64):
    """基本曲线 → 折线上的点 (首尾都有; 封闭的首尾是同一个点)。"""
    kind = prim[0]
    if kind == 'line':
        return [prim[1], prim[2]]
    if kind in ('arc', 'circle'):
        centre, radius = prim[1], prim[2]
        start, end = (prim[3], prim[4]) if kind == 'arc' else (0.0, TAU)
        count = max(2, int(math.ceil(fine * (end - start) / TAU)))
        return [_polar(centre, radius, start + (end - start) * k / count) for k in range(count + 1)]
    if kind == 'ellipse':
        (cx, cy), rx, ry, turn = prim[1], prim[2], prim[3], prim[4]
        cos, sin = math.cos(turn), math.sin(turn)
        ring = []
        for k in range(fine + 1):
            x, y = rx * math.cos(TAU * k / fine), ry * math.sin(TAU * k / fine)
            ring.append((cx + x * cos - y * sin, cy + x * sin + y * cos))
        return ring
    if kind == 'bezier':
        poles = prim[1:]
        count = max(6, fine // 5) * max(1, (len(poles) - 1) // 3)
        curve = []
        for k in range(count + 1):
            t, level = k / count, list(poles)
            while len(level) > 1:               # 逐层在相邻控制点之间按比例取点, 最后剩下的就是曲线上的点
                level = [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) for a, b in zip(level, level[1:])]
            curve.append(level[0])
        return curve
    return []


def polylines(shape, fine=64):
    """图形 → 要画的折线 (每条基本曲线一条)。"""
    return [line for line in (sample(prim, fine) for prim in prims(shape)) if len(line) >= 2]


def length(shape):
    return sum(dist(a, b) for line in polylines(shape) for a, b in zip(line, line[1:]))


def prim_ends(prim):
    if prim[0] == 'line':
        return prim[1], prim[2]
    if prim[0] == 'arc':
        return _polar(prim[1], prim[2], prim[3]), _polar(prim[1], prim[2], prim[4])
    if prim[0] == 'bezier':
        return prim[1], prim[-1]
    return None


def ends(shape):
    """开口曲线 (直线 / 圆弧 / 不封闭的样条) 的两个端点; 其他返回 None。"""
    kind = shape.get('type')
    if kind == 'line' or kind == 'arc':
        return prim_ends(prims(shape)[0])
    if kind == 'spline' and (not shape.get('closed') or shape.get('style')):
        points = _points(shape, 2)
        return points[0], points[-1]
    if kind == 'equation':
        points = equation_points(shape)
        return points[0], points[-1]
    return None


def anchor(shape):
    """整体拖动时拿来对齐格子的那个点。"""
    kind = shape['type']
    if 'cx' in shape or kind in ('rect', 'circle', 'ngon', 'ellipse', 'arc'):
        return shape.get('cx', 0.0), shape.get('cy', 0.0)
    if kind in ('line', 'slot'):
        return shape['x1'], shape['y1']
    if kind in ('point', 'text'):
        return shape['x'], shape['y']
    if kind == 'equation':
        return equation_points(shape)[0]
    return tuple(shape['points'][0])


def key_points(shape):
    """可以吸附的特征点 → [(种类, 点)]; 种类: end 端点 / mid 中点 / center 圆心 / quad 象限点。"""
    kind = shape['type']
    found = []
    if kind in ('point', 'text'):
        return [('end', (shape['x'], shape['y']))]
    if kind == 'spline':
        points = _points(shape, 2)
        return [('end', point) for point in ((points[0], points[-1]) if shape.get('style') else points)]
    if kind == 'equation':
        return [('end', point) for point in ends(shape)]
    for prim in prims(shape):
        if prim[0] == 'line':
            found += [('end', prim[1]), ('mid', ((prim[1][0] + prim[2][0]) / 2, (prim[1][1] + prim[2][1]) / 2))]
            if kind in ('line', 'slot'):
                found.append(('end', prim[2]))
        elif prim[0] == 'arc':
            found.append(('center', prim[1]))
            if kind == 'arc':
                found += [('end', point) for point in prim_ends(prim)]
                found.append(('mid', _polar(prim[1], prim[2], (prim[3] + prim[4]) / 2)))
        elif prim[0] == 'circle':
            found.append(('center', prim[1]))
            found += [('quad', _polar(prim[1], prim[2], TAU * k / 4)) for k in range(4)]
        elif prim[0] == 'ellipse':
            found.append(('center', prim[1]))
            ring = sample(prim, 4)
            found += [('quad', point) for point in ring[:4]]
    if kind in ('rect', 'ngon'):
        found.append(('center', (shape.get('cx', 0.0), shape.get('cy', 0.0))))
    return found


# ---------------------------------------------------------------------------
# 最近点、点没点中
# ---------------------------------------------------------------------------
def _nearest_on_segment(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    along = 0.0 if length2 == 0 else max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2))
    return start[0] + dx * along, start[1] + dy * along


def nearest_on_prim(prim, point):
    kind = prim[0]
    if kind == 'point':
        return prim[1]
    if kind == 'line':
        return _nearest_on_segment(point, prim[1], prim[2])
    if kind in ('arc', 'circle'):
        centre, radius = prim[1], prim[2]
        angle = _angle(centre, point) if dist(centre, point) > 1e-12 else 0.0
        if kind == 'circle' or _in_sweep(angle, prim[3], prim[4]):
            return _polar(centre, radius, angle)
        return min(prim_ends(prim), key=lambda end: dist(end, point))
    line = sample(prim, 96)
    return min((_nearest_on_segment(point, a, b) for a, b in zip(line, line[1:])), key=lambda found: dist(found, point))


def nearest(shape, point):
    """→ (距离, 曲线上离 point 最近的点); 文本没有曲线, 按它的定位点算。"""
    if shape['type'] == 'text':
        spot = (shape['x'], shape['y'])
        return dist(spot, point), spot
    best = min((nearest_on_prim(prim, point) for prim in prims(shape)), key=lambda found: dist(found, point))
    return dist(best, point), best


def hit(shape, point, tolerance):
    return nearest(shape, point)[0] <= tolerance


def contains(ring, point):
    """point 在不在封闭折线 ring 里面。"""
    x, y = point
    inside = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def signed_area(ring):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])) / 2


def _oriented(parts):
    """封闭图形的几条基本曲线 → [(曲线, 是不是倒着走)...], 让它们首尾相接走成一圈 (圆弧槽口的内弧要倒着走)。"""
    if len(parts) == 1:
        return [(parts[0], False)]
    first, second = prim_ends(parts[0]), prim_ends(parts[1])
    tail = first[0] if min(dist(first[0], second[0]), dist(first[0], second[1])) < min(dist(first[1], second[0]), dist(first[1], second[1])) else first[1]
    loop = [(parts[0], tail is first[0])]
    for prim in parts[1:]:
        start, end = prim_ends(prim)
        backwards = dist(end, tail) < dist(start, tail)
        loop.append((prim, backwards))
        tail = start if backwards else end
    return loop


def _ring(shape):
    """封闭图形 → 一圈点 (不重复首尾)。"""
    return loop_ring(_oriented(prims(shape)), 64)


# ---------------------------------------------------------------------------
# 变换
# ---------------------------------------------------------------------------
def explode(shape):
    """矩形 / 多边形 / 槽口 拆成一条条直线和圆弧 (剪裁、圆角只认单条的线); 别的原样返回。"""
    if shape['type'] not in ('rect', 'polygon', 'ngon', 'slot', 'arcslot'):
        return [shape]
    pieces = []
    for prim in prims(shape):
        if prim[0] == 'line':
            pieces.append({'type': 'line', 'x1': prim[1][0], 'y1': prim[1][1], 'x2': prim[2][0], 'y2': prim[2][1]})
        else:
            pieces.append({'type': 'arc', 'cx': prim[1][0], 'cy': prim[1][1], 'r': prim[2],
                           'a0': math.degrees(prim[3]), 'a1': math.degrees(prim[4])})
    if shape.get('construction'):
        for piece in pieces:
            piece['construction'] = True
    return pieces


def _mapped(shape, move, turn=None, flips=False):
    """图形里的每个点过一遍 move; turn(度) 是方向量怎么变; flips = 这个变换会不会把逆时针变成顺时针。"""
    kind = shape['type']
    if kind == 'equation':              # 镜向、旋转后不再是原来那个方程: 按现在的样子变成一条样条
        shape = {'type': 'spline', 'points': [list(point) for point in equation_points(shape)], 'closed': False,
                 **({'construction': True} if shape.get('construction') else {})}
        kind = 'spline'
    result = copy.deepcopy(shape)
    if 'points' in shape:
        result['points'] = [list(move((p[0], p[1]))) for p in shape['points']]
    if kind in ('line', 'slot'):
        (result['x1'], result['y1']), (result['x2'], result['y2']) = move((shape['x1'], shape['y1'])), move((shape['x2'], shape['y2']))
    if kind in ('point', 'text'):
        result['x'], result['y'] = move((shape['x'], shape['y']))
        if shape.get('path'):
            result['path'] = _mapped(shape['path'], move, turn, flips)
    if kind in ('rect', 'circle', 'ngon', 'ellipse', 'arc', 'arcslot'):
        result['cx'], result['cy'] = move((shape.get('cx', 0.0), shape.get('cy', 0.0)))
    if turn is not None:
        if kind in ('ngon', 'ellipse') or (kind == 'text' and not flips and not shape.get('path')):
            result['angle'] = turn(shape.get('angle', 0.0))
        if kind in ('arc', 'arcslot'):
            first, second = turn(shape['a0']), turn(shape['a1'])
            result['a0'], result['a1'] = (second, first) if flips else (first, second)
    return result


def moved(shape, dx, dy):
    if shape['type'] == 'equation':
        return dict(copy.deepcopy(shape), ox=float(shape.get('ox', 0.0)) + dx, oy=float(shape.get('oy', 0.0)) + dy)
    return _mapped(shape, lambda p: (p[0] + dx, p[1] + dy))


def rotated(shape, centre, angle):
    """绕 centre 逆时针转 angle 度。"""
    cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def spin(point):
        dx, dy = point[0] - centre[0], point[1] - centre[1]
        return centre[0] + dx * cos - dy * sin, centre[1] + dx * sin + dy * cos

    if shape['type'] == 'rect' and abs(sin) > 1e-12:            # 转过以后不再横平竖直
        shape = {'type': 'polygon', 'points': [list(point) for point in vertices(shape)],
                 **({'construction': True} if shape.get('construction') else {})}
    return _mapped(shape, spin, lambda value: value + angle)


def mirrored(shape, first, second):
    """关于过 first、second 的直线镜向。"""
    ux, uy = _unit(second[0] - first[0], second[1] - first[1])
    axis = math.degrees(math.atan2(uy, ux))

    def reflect(point):
        dx, dy = point[0] - first[0], point[1] - first[1]
        along = dx * ux + dy * uy
        return first[0] + 2 * along * ux - dx, first[1] + 2 * along * uy - dy

    if shape['type'] == 'rect' and abs(ux * uy) > 1e-12:       # 斜着镜向后不再是横平竖直的矩形
        shape = {'type': 'polygon', 'points': [list(point) for point in vertices(shape)]}
    return _mapped(shape, reflect, lambda angle: 2 * axis - angle, flips=True)


# ---------------------------------------------------------------------------
# 求交
# ---------------------------------------------------------------------------
def _line_line(a, b, c, d):
    rx, ry, sx, sy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    cross = rx * sy - ry * sx
    if abs(cross) < 1e-12 * max(1.0, abs(rx) + abs(ry)) * max(1.0, abs(sx) + abs(sy)):
        return []
    t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / cross
    u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / cross
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return [(a[0] + rx * t, a[1] + ry * t)]
    return []


def _line_circle(a, b, centre, radius):
    dx, dy = b[0] - a[0], b[1] - a[1]
    fx, fy = a[0] - centre[0], a[1] - centre[1]
    qa = dx * dx + dy * dy
    if qa == 0:
        return []
    qb, qc = 2 * (fx * dx + fy * dy), fx * fx + fy * fy - radius * radius
    disc = qb * qb - 4 * qa * qc
    if disc < -1e-9 * qa * radius * radius:
        return []
    root = math.sqrt(max(disc, 0.0))
    found = []
    for t in {(-qb - root) / (2 * qa), (-qb + root) / (2 * qa)}:
        if -1e-9 <= t <= 1 + 1e-9:
            found.append((a[0] + dx * t, a[1] + dy * t))
    return found


def _circle_circle(c0, r0, c1, r1):
    gap = dist(c0, c1)
    if gap < 1e-12 or gap > r0 + r1 + 1e-9 or gap < abs(r0 - r1) - 1e-9:
        return []
    along = (r0 * r0 - r1 * r1 + gap * gap) / (2 * gap)
    height = math.sqrt(max(r0 * r0 - along * along, 0.0))
    ux, uy = (c1[0] - c0[0]) / gap, (c1[1] - c0[1]) / gap
    base = (c0[0] + ux * along, c0[1] + uy * along)
    if height < 1e-9:
        return [base]
    return [(base[0] - uy * height, base[1] + ux * height), (base[0] + uy * height, base[1] - ux * height)]


def _on_round(prim, point):
    return prim[0] == 'circle' or _in_sweep(_angle(prim[1], point), prim[3], prim[4], 1e-7)


def _simple(prim):
    if prim[0] in ('line', 'arc', 'circle'):
        return [prim]
    line = sample(prim, 96)
    return [('line', a, b) for a, b in zip(line, line[1:])]


def intersections(first, second):
    """两条基本曲线的交点。直线、圆、圆弧之间是精确的; 椭圆和样条按折线近似。"""
    found = []
    for a in _simple(first):
        for b in _simple(second):
            if a[0] == 'line' and b[0] == 'line':
                found += _line_line(a[1], a[2], b[1], b[2])
            elif a[0] == 'line':
                found += [p for p in _line_circle(a[1], a[2], b[1], b[2]) if _on_round(b, p)]
            elif b[0] == 'line':
                found += [p for p in _line_circle(b[1], b[2], a[1], a[2]) if _on_round(a, p)]
            else:
                found += [p for p in _circle_circle(a[1], a[2], b[1], b[2]) if _on_round(a, p) and _on_round(b, p)]
    return found


# ---------------------------------------------------------------------------
# 剪裁
# ---------------------------------------------------------------------------
def _along(prim, point):
    """点在曲线上的位置, 用从起点量过来的长度表示。"""
    if prim[0] == 'line':
        return dist(prim[1], _nearest_on_segment(point, prim[1], prim[2]))
    start = prim[3] if prim[0] == 'arc' else 0.0
    return ((_angle(prim[1], point) - start) % TAU) * prim[2]


def _piece(prim, start, end):
    if prim[0] == 'line':
        ux, uy = _unit(prim[2][0] - prim[1][0], prim[2][1] - prim[1][1])
        return {'type': 'line', 'x1': prim[1][0] + ux * start, 'y1': prim[1][1] + uy * start,
                'x2': prim[1][0] + ux * end, 'y2': prim[1][1] + uy * end}
    base = prim[3] if prim[0] == 'arc' else 0.0
    return {'type': 'arc', 'cx': prim[1][0], 'cy': prim[1][1], 'r': prim[2],
            'a0': math.degrees(base + start / prim[2]), 'a1': math.degrees(base + end / prim[2])}


def trim(shapes, index, point):
    """剪掉 shapes[index] 上 point 所在的那一段 (到它和别的线的交点为止; 没有交点就整条删掉) → 新的图形列表。"""
    shapes = copy.deepcopy(list(shapes))
    pieces = explode(shapes[index])
    if len(pieces) > 1:
        shapes[index:index + 1] = pieces
        index += min(range(len(pieces)), key=lambda k: nearest(pieces[k], point)[0])
    target = shapes[index]
    if target['type'] not in ('line', 'arc', 'circle'):
        raise ValueError(f'{NAMES.get(target["type"], "这种图形")}还不能剪裁（能剪直线、圆、圆弧，以及矩形、多边形、槽口的边）')
    prim = prims(target)[0]
    total = dist(prim[1], prim[2]) if prim[0] == 'line' else prim[2] * ((prim[4] - prim[3]) if prim[0] == 'arc' else TAU)
    cuts = set()
    for other_index, other in enumerate(shapes):
        if other_index == index or other['type'] in ('point', 'text'):
            continue
        for other_prim in prims(other):
            for crossing in intersections(prim, other_prim):
                where = _along(prim, crossing)
                if prim[0] == 'circle' or JOIN < where < total - JOIN:
                    cuts.add(round(where, 7))
    cuts = sorted(cuts)
    click = _along(prim, nearest_on_prim(prim, point))
    if prim[0] == 'circle':
        if len(cuts) < 2:
            del shapes[index]
            return shapes
        lower = max((cut for cut in cuts if cut <= click), default=cuts[-1] - total)
        upper = min((cut for cut in cuts if cut > click), default=cuts[0] + total)
        shapes[index] = _piece(prim, upper, lower + total)
        return shapes
    lower = max((cut for cut in cuts if cut <= click), default=0.0)
    upper = min((cut for cut in cuts if cut > click), default=total)
    kept = []
    if lower > 0.0:
        kept.append(_piece(prim, 0.0, lower))
    if upper < total:
        kept.append(_piece(prim, upper, total))
    shapes[index:index + 1] = kept
    return shapes


# ---------------------------------------------------------------------------
# 草图圆角
# ---------------------------------------------------------------------------
def corner_near(shapes, point, tolerance):
    """point 附近的线头 / 顶点 (圆角要找的那个尖角) → 点或 None。"""
    best = None
    for shape in shapes:
        if shape['type'] in ('line', 'rect', 'polygon', 'ngon'):
            for prim in prims(shape):
                for end in (prim[1], prim[2]):
                    if dist(end, point) <= tolerance and (best is None or dist(end, point) < dist(best, point)):
                        best = end
    return best


def fillet(shapes, point, radius, tolerance):
    """把 point 附近两条直线相交的尖角倒成半径 radius 的圆弧 → 新的图形列表。"""
    if radius <= 0:
        raise ValueError('圆角半径必须是正数')
    corner = corner_near(shapes, point, tolerance)
    if corner is None:
        raise ValueError('点在两条直线相交的尖角上')
    result = []
    for shape in copy.deepcopy(list(shapes)):      # 这个角所在的矩形 / 多边形先拆成一条条线
        if shape['type'] in ('rect', 'polygon', 'ngon') and any(dist(v, corner) <= JOIN for v in vertices(shape)):
            result += explode(shape)
        else:
            result.append(shape)
    meeting = []                                    # (线的序号, 它在角上的是哪一头)
    for index, shape in enumerate(result):
        if shape['type'] == 'line':
            for which, end in enumerate(prims(shape)[0][1:]):
                if dist(end, corner) <= JOIN:
                    meeting.append((index, which))
    if len(meeting) != 2 or meeting[0][0] == meeting[1][0]:
        raise ValueError('圆角要正好两条直线交在这个角上' if len(meeting) != 2 else '这条线的两头重合了')
    away, spans = [], []
    for index, which in meeting:
        line = prims(result[index])[0]
        far = line[2 - which]
        away.append(_unit(far[0] - corner[0], far[1] - corner[1]))
        spans.append(dist(far, corner))
    cosine = max(-1.0, min(1.0, away[0][0] * away[1][0] + away[0][1] * away[1][1]))
    if abs(cosine) > 1 - 1e-9:
        raise ValueError('这两条线在一条直线上，做不了圆角')
    half = math.acos(cosine) / 2
    setback = radius / math.tan(half)
    if setback > min(spans) - JOIN:
        raise ValueError(f'圆角半径 {radius:g} 太大：线不够长（这个角最大约 {min(spans) * math.tan(half):.4g}）')
    tangents = [(corner[0] + ux * setback, corner[1] + uy * setback) for ux, uy in away]
    bx, by = _unit(away[0][0] + away[1][0], away[0][1] + away[1][1])
    centre = (corner[0] + bx * radius / math.sin(half), corner[1] + by * radius / math.sin(half))
    for (index, which), tangent in zip(meeting, tangents):
        result[index]['x2' if which else 'x1'], result[index]['y2' if which else 'y1'] = tangent
    first, second = _angle(centre, tangents[0]), _angle(centre, tangents[1])
    if (second - first) % TAU > math.pi:
        first, second = second, first
    result.append({'type': 'arc', 'cx': centre[0], 'cy': centre[1], 'r': radius,
                   'a0': math.degrees(first), 'a1': math.degrees(second)})
    return result


# ---------------------------------------------------------------------------
# 等距
# ---------------------------------------------------------------------------
def signed_distance(shape, point):
    """point 到图形的距离, 带方向: 封闭图形外面为正; 开口曲线左边 (沿走向看) 为正; 圆弧外面为正。"""
    gap, spot = nearest(shape, point)
    kind = shape['type']
    if is_closed(shape):
        return gap if not contains(_ring(shape), point) else -gap
    if kind == 'arc':
        return gap if dist((shape['cx'], shape['cy']), point) >= shape['r'] else -gap
    line = [p for part in polylines(shape, 96) for p in part]
    a, b = min(zip(line, line[1:]), key=lambda seg: dist(_nearest_on_segment(point, *seg), point))
    side = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
    return gap if side >= 0 else -gap


def offset(shape, distance):
    """等距复制 (distance 的正负和 signed_distance 一致) → 新图形; 缩没了返回 None。"""
    kind = shape['type']
    result = copy.deepcopy(shape)
    if kind == 'circle' or kind == 'arc':
        result['r'] = shape['r'] + distance
        return result if result['r'] > TINY else None
    if kind == 'rect':
        result['w'], result['h'] = shape['w'] + 2 * distance, shape['h'] + 2 * distance
        return result if min(result['w'], result['h']) > TINY else None
    if kind == 'slot':
        result['w'] = shape['w'] + 2 * distance
        return result if result['w'] > TINY else None
    if kind == 'arcslot':
        result['w'] = shape['w'] + 2 * distance
        return result if TINY < result['w'] < 2 * shape['r'] - TINY else None
    if kind == 'ngon':
        result['r'] = shape['r'] + distance / math.cos(math.pi / int(shape.get('sides', 6)))
        return result if result['r'] > TINY else None
    if kind == 'line':
        ux, uy = _unit(shape['x2'] - shape['x1'], shape['y2'] - shape['y1'])
        return moved(shape, -uy * distance, ux * distance)
    if kind == 'polygon':
        ring = vertices(shape)
        turn = 1.0 if signed_area(ring) > 0 else -1.0
        shifted = []
        for a, b in zip(ring, ring[1:] + ring[:1]):
            ux, uy = _unit(b[0] - a[0], b[1] - a[1])
            nx, ny = uy * distance * turn, -ux * distance * turn
            shifted.append(((a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny)))
        points = []
        for before, after in zip(shifted[-1:] + shifted[:-1], shifted):
            rx, ry, sx, sy = before[1][0] - before[0][0], before[1][1] - before[0][1], after[1][0] - after[0][0], after[1][1] - after[0][1]
            cross = rx * sy - ry * sx
            if abs(cross) < 1e-12:
                points.append(list(after[0]))
            else:
                t = ((after[0][0] - before[0][0]) * sy - (after[0][1] - before[0][1]) * sx) / cross
                points.append([before[0][0] + rx * t, before[0][1] + ry * t])
        for (a, b), new_a, new_b in zip(zip(ring, ring[1:] + ring[:1]), points, points[1:] + points[:1]):
            if (b[0] - a[0]) * (new_b[0] - new_a[0]) + (b[1] - a[1]) * (new_b[1] - new_a[1]) <= TINY:
                return None                 # 有一条边缩没了或翻了个身: 往里偏得太多
        return {'type': 'polygon', 'points': points}
    if kind in ('ellipse', 'spline', 'equation'):
        result = {'type': 'spline'}
        closed = is_closed(shape)
        line = _ring(shape) if closed else [p for index, part in enumerate(polylines(shape, 96)) for p in part[0 if index == 0 else 1:]]
        turn = (-1.0 if signed_area(line) > 0 else 1.0) if closed else 1.0     # 封闭: 正 = 往外
        count, points = len(line), []
        step = max(1, count // 32)
        for index in range(0, count, step):
            before = line[(index - 1) % count] if closed else line[max(index - 1, 0)]
            after = line[(index + 1) % count] if closed else line[min(index + 1, count - 1)]
            ux, uy = _unit(after[0] - before[0], after[1] - before[1])
            points.append([line[index][0] - uy * distance * turn, line[index][1] + ux * distance * turn])
        if not closed and (count - 1) % step:
            ux, uy = _unit(line[-1][0] - line[-2][0], line[-1][1] - line[-2][1])
            points.append([line[-1][0] - uy * distance, line[-1][1] + ux * distance])
        if closed and signed_area([tuple(p) for p in points]) * signed_area(line) <= 0:
            return None
        return {'type': 'spline', 'points': points, 'closed': closed}
    return None


# ---------------------------------------------------------------------------
# 找封闭轮廓
# ---------------------------------------------------------------------------
def _nodes(points):
    """把离得不超过 JOIN 的点并成一个节点 → (每个点的节点号, 节点坐标)。"""
    spots, numbers = [], []
    for point in points:
        for number, spot in enumerate(spots):
            if dist(spot, point) <= JOIN:
                numbers.append(number)
                break
        else:
            numbers.append(len(spots))
            spots.append(point)
    return numbers, spots


def loops(shapes):
    """→ (封闭轮廓的列表, 没围成圈的开口曲线条数)。一个轮廓 = [(基本曲线, 是不是倒着走)...], 首尾相接。
    开口曲线只有正好两两首尾相接成一圈才算轮廓 — 有分叉或没接上的不算。"""
    found, loose = [], []
    for shape in shapes:
        if shape.get('type') in ('point', 'text') or shape.get('construction'):
            continue
        parts = prims(shape)
        if is_closed(shape):
            found.append(_oriented(parts))
        else:
            loose += [prim for prim in parts if dist(*prim_ends(prim)) > JOIN or prim[0] != 'line']
    tips = [end for prim in loose for end in prim_ends(prim)]
    numbers, _ = _nodes(tips)
    degree = {}
    for number in numbers:
        degree[number] = degree.get(number, 0) + 1
    at = {}
    for index in range(len(loose)):
        for which in (0, 1):
            at.setdefault(numbers[2 * index + which], []).append((index, which))
    used, leftover = set(), 0
    for start in range(len(loose)):
        if start in used:
            continue
        chain, index, which, good = [], start, 0, True
        while True:
            used.add(index)
            chain.append((loose[index], which == 1))
            node = numbers[2 * index + (1 - which)]         # 走到这条线的另一头
            if degree[node] != 2:
                good = False
                break
            index, which = next(item for item in at[node] if item != (index, 1 - which))
            if index == start:
                break
            if index in used:
                good = False
                break
        if good and degree[numbers[2 * start]] == 2:
            found.append(chain)
        else:
            leftover += 1
    return found, leftover


def loop_ring(loop, fine=48):
    """轮廓 → 一圈点 (不重复首尾), 判断里外和算面积用。"""
    ring = []
    for prim, backwards in loop:
        line = sample(prim, fine)
        ring += (line[::-1] if backwards else line)[:-1]
    return ring


def chain_of(shapes, index):
    """和 shapes[index] 首尾相接连成一串的图形序号 (含它自己)。"""
    tips = {}
    for number, shape in enumerate(shapes):
        both = ends(shape)
        if both:
            tips[number] = both
    if index not in tips:
        return [index]
    chain, front = {index}, [index]
    while front:
        current = front.pop()
        for number, both in tips.items():
            if number not in chain and any(dist(a, b) <= JOIN for a in both for b in tips[current]):
                chain.add(number)
                front.append(number)
    return sorted(chain)


# ---------------------------------------------------------------------------
# 检查和修复
# ---------------------------------------------------------------------------
def _open_tips(shapes):
    """→ [(图形序号, 哪一头 0/1, 点)]: 所有开口曲线的端点。"""
    tips = []
    for index, shape in enumerate(shapes):
        both = None if shape.get('construction') else ends(shape)
        if both:
            tips += [(index, 0, both[0]), (index, 1, both[1])]
    return tips


def _same(first, second):
    def rounded(value):
        if isinstance(value, float):
            return round(value, 6)
        if isinstance(value, (list, tuple)):
            return [rounded(item) for item in value]
        if isinstance(value, dict):
            return {key: rounded(item) for key, item in value.items()}
        return value
    return rounded(first) == rounded(second)


def diagnose(shapes):
    """检查草图 → 问题列表 [{'kind', 'text', 'point', 'fixable'}]。
    kind: tiny 废线 / duplicate 重复 / gap 差一点没接上 / open 线头悬空 / branch 多条线交在一点。"""
    issues, sound = [], []
    for index, shape in enumerate(shapes):
        if shape['type'] in ('point', 'text') or shape.get('construction'):
            continue
        if length(shape) < TINY:
            issues.append({'kind': 'tiny', 'text': f'{NAMES[shape["type"]]}长度接近 0', 'point': anchor(shape), 'fixable': True})
        elif any(_same(shape, other) for other in shapes[:index]):
            issues.append({'kind': 'duplicate', 'text': f'{NAMES[shape["type"]]}和另一个完全重合', 'point': anchor(shape), 'fixable': True})
        else:
            sound.append(shape)
    tips = _open_tips(sound)                # 废线和重复的线反正要删, 不拿它们的端点去挑毛病
    numbers, spots = _nodes([tip[2] for tip in tips])
    count = {}
    for number in numbers:
        count[number] = count.get(number, 0) + 1
    near = set()
    for first in range(len(spots)):
        for second in range(first + 1, len(spots)):
            gap = dist(spots[first], spots[second])
            if gap <= GAP:
                near.update((first, second))
                issues.append({'kind': 'gap', 'text': f'两个端点差 {gap:.3g} mm 没接上', 'point': spots[first], 'fixable': True})
    for number, spot in enumerate(spots):
        if count[number] >= 3:
            issues.append({'kind': 'branch', 'text': f'{count[number]} 条线交在同一点（围不成单一轮廓）', 'point': spot, 'fixable': False})
        elif count[number] == 1 and number not in near:
            issues.append({'kind': 'open', 'text': '线头没有接上别的线（开口轮廓不能拉伸）', 'point': spot, 'fixable': False})
    return issues


def _set_tip(shape, which, point):
    if shape['type'] == 'line':
        shape['x2' if which else 'x1'], shape['y2' if which else 'y1'] = point
        return True
    if shape['type'] == 'spline':
        shape['points'][-1 if which else 0] = [point[0], point[1]]
        return True
    return False                    # 圆弧的端点由圆心、半径、角度决定, 挪不了


def repair(shapes):
    """删掉废线和重复的, 把差一点没接上的端点合到一起 → (新的图形列表, 修了几处)。"""
    kept, fixed = [], 0
    for shape in copy.deepcopy(list(shapes)):
        if shape['type'] not in ('point', 'text') and (length(shape) < TINY or any(_same(shape, other) for other in kept)):
            fixed += 1
        else:
            kept.append(shape)
    tips = _open_tips(kept)
    for first in range(len(tips)):
        for second in range(first + 1, len(tips)):
            a, b = tips[first], tips[second]
            gap = dist(a[2], b[2])
            if not JOIN < gap <= GAP:
                continue
            if _set_tip(kept[b[0]], b[1], a[2]):        # 挪直线 / 样条的那一头去就圆弧
                tips[second] = (b[0], b[1], a[2])
                fixed += 1
            elif _set_tip(kept[a[0]], a[1], b[2]):
                tips[first] = (a[0], a[1], b[2])
                fixed += 1
    return kept, fixed


# ---------------------------------------------------------------------------
# 方程式曲线
# ---------------------------------------------------------------------------
_MATH = {name: getattr(math, name) for name in ('sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'atan2', 'sinh', 'cosh', 'tanh',
                                                 'sqrt', 'exp', 'log', 'log10', 'floor', 'ceil', 'radians', 'degrees', 'pi', 'e')}
_MATH.update(abs=abs, min=min, max=max, pow=pow)


def evaluate(text, **variables):
    """算一个数学式子 (只认数字、加减乘除乘方、括号、sin/cos/sqrt 这类函数和给定的变量) → 浮点数。"""
    import ast
    try:
        tree = ast.parse(str(text).replace('^', '**'), mode='eval')
    except SyntaxError:
        raise ValueError(f'方程式写得不对: {text!r}') from None
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant, ast.Add, ast.Sub, ast.Mult,
               ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd)
    for node in ast.walk(tree):
        if not isinstance(node, allowed) or (isinstance(node, ast.Name) and node.id not in _MATH and node.id not in variables) \
                or (isinstance(node, ast.Call) and not isinstance(node.func, ast.Name)) \
                or (isinstance(node, ast.Constant) and not isinstance(node.value, (int, float))):
            raise ValueError(f'方程式里有不认识的东西: {text!r}（可用 + - * / ^、括号、sin cos tan sqrt exp log abs pi 等和变量 {" ".join(variables)}）')
    try:
        value = float(eval(compile(tree, '<方程式>', 'eval'), {'__builtins__': {}}, dict(_MATH, **variables)))
    except (ArithmeticError, ValueError, TypeError) as error:
        raise ValueError(f'方程式 {text!r} 算不出来: {error}') from None
    if not math.isfinite(value):
        raise ValueError(f'方程式 {text!r} 算出了无穷大')
    return value


def equation_points(shape):
    start, end = num(shape, 't0', 0.0), num(shape, 't1', 1.0)
    if abs(end - start) < 1e-12:
        raise ValueError('方程式曲线的起止范围不能相同')
    shift = (num(shape, 'ox', 0.0), num(shape, 'oy', 0.0))
    points = []
    for step in range(EQUATION_STEPS + 1):
        value = start + (end - start) * step / EQUATION_STEPS
        if shape.get('mode', 'explicit') == 'parametric':
            point = (evaluate(shape.get('fx', 't'), t=value), evaluate(shape.get('fy', '0'), t=value))
        else:
            point = (value, evaluate(shape.get('fy', '0'), x=value))
        points.append((point[0] + shift[0], point[1] + shift[1]))
    return points


# ---------------------------------------------------------------------------
# 三点定圆 / 弧
# ---------------------------------------------------------------------------
def circle3(first, second, third):
    """过三个点的圆 → (圆心, 半径); 三点共线返回 None。"""
    ax, ay, bx, by, cx, cy = *first, *second, *third
    cross = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(cross) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / cross
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / cross
    return (ux, uy), dist((ux, uy), first)


def arc3(start, end, through):
    """从 start 到 end、中间经过 through 的圆弧 → arc 图形 (三点共线返回 None)。"""
    found = circle3(start, end, through)
    if found is None:
        return None
    centre, radius = found
    first, second, middle = _angle(centre, start), _angle(centre, end), _angle(centre, through)
    if (middle - first) % TAU > (second - first) % TAU:         # 逆时针从 start 到 end 不经过 through: 反过来走
        first, second = second, first
    return {'type': 'arc', 'cx': centre[0], 'cy': centre[1], 'r': radius, 'a0': math.degrees(first), 'a1': math.degrees(second)}


# ---------------------------------------------------------------------------
# 延伸
# ---------------------------------------------------------------------------
def extend(shapes, index, point):
    """把 shapes[index] 离 point 近的那一头延长到碰上别的线为止 → 新的图形列表。"""
    shapes = copy.deepcopy(list(shapes))
    target = shapes[index]
    if target['type'] not in ('line', 'arc'):
        raise ValueError(f'{NAMES.get(target["type"], "这种图形")}还不能延伸（能延伸单条的直线和圆弧）')
    prim = prims(target)[0]
    tips = prim_ends(prim)
    which = 0 if dist(tips[0], point) <= dist(tips[1], point) else 1
    if prim[0] == 'line':
        ux, uy = _unit(tips[which][0] - tips[1 - which][0], tips[which][1] - tips[1 - which][1])
        probe = ('line', tips[which], (tips[which][0] + ux * 1e5, tips[which][1] + uy * 1e5))
    else:
        spare = TAU - (prim[4] - prim[3])
        if spare < 1e-9:
            raise ValueError('这已经是一整个圆了')
        probe = ('arc', prim[1], prim[2], prim[4], prim[4] + spare) if which else ('arc', prim[1], prim[2], prim[3] - spare, prim[3])
    best = None
    for other_index, other in enumerate(shapes):
        if other_index == index or other['type'] in ('point', 'text'):
            continue
        for other_prim in prims(other):
            for crossing in intersections(probe, other_prim):
                if prim[0] == 'line':
                    reach = dist(crossing, tips[which])
                else:
                    turn = (_angle(prim[1], crossing) - prim[4]) % TAU if which else (prim[3] - _angle(prim[1], crossing)) % TAU
                    reach = turn * prim[2]
                if reach > JOIN and (best is None or reach < best[0]):
                    best = (reach, crossing)
    if best is None:
        raise ValueError('这一头延伸出去碰不到别的线')
    if prim[0] == 'line':
        target['x2' if which else 'x1'], target['y2' if which else 'y1'] = best[1]
    else:
        target['a1' if which else 'a0'] = target['a1' if which else 'a0'] + (1 if which else -1) * math.degrees(best[0] / prim[2])
    return shapes


# ---------------------------------------------------------------------------
# 几何关系: 没有约束求解, 这里是 "照这个关系摆一次" — 之后再拖动不会保持
# ---------------------------------------------------------------------------
RELATIONS = {'horizontal': '水平', 'vertical': '竖直', 'parallel': '平行', 'perpendicular': '垂直', 'collinear': '共线',
             'equal': '相等', 'concentric': '同心', 'coincident': '重合', 'tangent': '相切'}
_ROUND = ('circle', 'arc', 'arcslot')
_CENTRED = ('circle', 'arc', 'arcslot', 'ellipse', 'ngon', 'rect')


def relations_for(chosen):
    """这几个图形之间能加哪些关系 → [键...]。"""
    kinds = [shape['type'] for shape in chosen]
    lines, rounds = kinds.count('line'), sum(1 for kind in kinds if kind in _ROUND)
    found = []
    if lines == len(kinds) >= 1:
        found += ['horizontal', 'vertical']
    if lines == len(kinds) >= 2:
        found += ['parallel', 'perpendicular', 'collinear', 'equal']
    if rounds == len(kinds) >= 2:
        found += ['equal']
    if len(kinds) >= 2 and all(kind in _CENTRED for kind in kinds):
        found += ['concentric']
    if len(kinds) == 2 and lines == 1 and rounds == 1:
        found += ['tangent']
    if len(kinds) >= 2 and all(kind not in ('text',) for kind in kinds):
        found += ['coincident']
    return found


def _turned_line(shape, angle, length_=None):
    """把直线绕它的中点转到 angle (弧度), 长度不变 (或改成 length_)。"""
    first, second = (shape['x1'], shape['y1']), (shape['x2'], shape['y2'])
    middle, half = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2), (length_ or dist(first, second)) / 2
    current = math.atan2(second[1] - first[1], second[0] - first[0])
    if math.cos(angle - current) < 0:               # 取离现在的走向近的那个朝向, 不把线掉个头
        angle += math.pi
    return dict(shape, x1=middle[0] - half * math.cos(angle), y1=middle[1] - half * math.sin(angle),
                x2=middle[0] + half * math.cos(angle), y2=middle[1] + half * math.sin(angle))


def relate(shapes, selection, kind):
    """按关系 kind 把选中的图形摆一次 (第一个选中的不动, 其余的向它看齐) → 新的图形列表。"""
    shapes = copy.deepcopy(list(shapes))
    chosen = [shapes[index] for index in selection]
    if kind not in relations_for(chosen):
        raise ValueError(f'选中的这几个图形之间加不了“{RELATIONS.get(kind, kind)}”')
    lead = chosen[0]

    def heading(shape):
        return math.atan2(shape['y2'] - shape['y1'], shape['x2'] - shape['x1'])

    def span(shape):
        return dist((shape['x1'], shape['y1']), (shape['x2'], shape['y2']))

    for index in selection if kind in ('horizontal', 'vertical') else selection[1:]:
        shape = shapes[index]
        if kind in ('horizontal', 'vertical'):
            shapes[index] = _turned_line(shape, 0.0 if kind == 'horizontal' else math.pi / 2)
        elif kind in ('parallel', 'perpendicular'):
            shapes[index] = _turned_line(shape, heading(lead) + (math.pi / 2 if kind == 'perpendicular' else 0.0))
        elif kind == 'collinear':
            turned = _turned_line(shape, heading(lead))
            middle = ((turned['x1'] + turned['x2']) / 2, (turned['y1'] + turned['y2']) / 2)
            ux, uy = math.cos(heading(lead)), math.sin(heading(lead))
            along = (middle[0] - lead['x1']) * ux + (middle[1] - lead['y1']) * uy
            shapes[index] = moved(turned, lead['x1'] + ux * along - middle[0], lead['y1'] + uy * along - middle[1])
        elif kind == 'equal':
            shapes[index] = _turned_line(shape, heading(shape), span(lead)) if shape['type'] == 'line' else dict(shape, r=lead['r'])
        elif kind == 'concentric':
            shapes[index] = moved(shape, lead.get('cx', 0.0) - shape.get('cx', 0.0), lead.get('cy', 0.0) - shape.get('cy', 0.0))
        elif kind == 'tangent':
            line, round_ = (lead, shape) if lead['type'] == 'line' else (shape, lead)
            centre = (round_['cx'], round_['cy'])
            foot = _nearest_on_line(centre, (line['x1'], line['y1']), (line['x2'], line['y2']))
            gap = dist(centre, foot)
            ux, uy = _unit(centre[0] - foot[0], centre[1] - foot[1]) if gap > 1e-9 else (-math.sin(heading(line)), math.cos(heading(line)))
            shift = round_['r'] - gap               # 圆心要离直线正好一个半径
            shapes[index] = moved(shape, ux * shift, uy * shift) if shape is round_ else moved(shape, -ux * shift, -uy * shift)
        elif kind == 'coincident':
            mine, theirs = [point for _, point in key_points(shape)], [point for _, point in key_points(lead)]
            a, b = min(((p, q) for p in mine for q in theirs), key=lambda pair: dist(*pair))
            shapes[index] = moved(shape, b[0] - a[0], b[1] - a[1])
    return shapes


def _nearest_on_line(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    along = 0.0 if length2 == 0 else ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2
    return start[0] + dx * along, start[1] + dy * along


# ---------------------------------------------------------------------------
# 转换实体引用: 实体的边投影到草图平面
# ---------------------------------------------------------------------------
def fit_line(line, tolerance=1e-4):
    """一串采样点 → 能代表它的最简单的图形: 直线、圆、圆弧, 都不是就是样条。"""
    line = [(float(point[0]), float(point[1])) for point in line]
    whole = dist(line[0], line[-1]) <= 1e-5
    far = max(line, key=lambda p: dist(p, line[0]))
    widest = max(dist(_nearest_on_segment(p, line[0], far), p) for p in line)
    if widest < 1e-6:                                # 侧着看过去是一条直线
        low, high = min(line), max(line)
        return {'type': 'line', 'x1': low[0], 'y1': low[1], 'x2': high[0], 'y2': high[1]}
    count = len(line)
    if count >= 5:
        found = circle3(line[0], line[count // 3], line[(2 * count) // 3])
        if found and all(abs(dist(p, found[0]) - found[1]) <= tolerance * max(1.0, found[1]) for p in line):
            if whole:
                return {'type': 'circle', 'cx': found[0][0], 'cy': found[0][1], 'r': found[1]}
            arc = arc3(line[0], line[-1], line[count // 2])
            if arc is not None:
                return arc
    picked = line[:-1:4] + ([] if whole else [line[-1]])
    if len(picked) < (3 if whole else 2):
        picked = line[:-1] if whole else line
    return {'type': 'spline', 'points': [list(p) for p in picked], 'closed': whole}


def fit_lines(lines):
    """好几串采样点 → 图形列表 (太短的和重复的去掉)。"""
    found = []
    for line in lines:
        if len(line) < 2:
            continue
        shape = fit_line(line)
        if length(shape) < TINY:
            continue
        twin = dict(shape, x1=shape['x2'], y1=shape['y2'], x2=shape['x1'], y2=shape['y1']) if shape['type'] == 'line' else shape
        if not any(_same(shape, other) or _same(twin, other) for other in found):
            found.append(shape)
    return found


def project_edges(model, plane, offset_):
    """实体的每条边投影到草图平面 → 图形列表 (重合的只留一条)。直边成直线; 和草图平面平行的圆成圆 / 圆弧;
    其余的曲线成样条。是当时的一份拷贝: 实体以后变了, 草图里的这些线不会跟着变。"""
    import numpy as np
    from . import planes
    if not model.get('has_body'):
        return []
    origin, x_dir, y_dir, normal = planes.frame(plane, offset_)
    segments, owner = np.asarray(model['segments'], dtype=float), np.asarray(model['segment_edge'])

    def flat(point):
        local = np.asarray(point, dtype=float) - origin
        return float(local @ x_dir), float(local @ y_dir)

    found = []
    for info in model.get('edges', ()):
        mine = segments[owner == info['id']]
        if not len(mine):
            continue
        line = [flat(point) for point in mine[:, 0]] + [flat(mine[-1, 1])]
        whole = dist(line[0], line[-1]) <= 1e-5
        shape = None
        if info['type'] == 'line':
            shape = {'type': 'line', 'x1': line[0][0], 'y1': line[0][1], 'x2': line[-1][0], 'y2': line[-1][1]}
        elif info['type'] == 'circle' and info.get('center') is not None and abs(float(np.dot(info['axis'], normal))) > 1 - 1e-9:
            centre, radius = flat(info['center']), float(info['radius'])
            if whole:
                shape = {'type': 'circle', 'cx': centre[0], 'cy': centre[1], 'r': radius}
            else:
                first, second = _angle(centre, line[0]), _angle(centre, line[-1])
                step = (_angle(centre, line[1]) - first + math.pi) % TAU - math.pi
                if step < 0:
                    first, second = second, first
                shape = {'type': 'arc', 'cx': centre[0], 'cy': centre[1], 'r': radius,
                         'a0': math.degrees(first), 'a1': math.degrees(second)}
        else:
            shape = fit_line(line)
        if length(shape) < TINY:                     # 垂直于草图平面的边投下来是一个点
            continue
        twin = dict(shape, x1=shape['x2'], y1=shape['y2'], x2=shape['x1'], y2=shape['y1']) if shape['type'] == 'line' else shape
        if not any(_same(shape, other) or _same(twin, other) for other in found):
            found.append(shape)
    return found


# ---------------------------------------------------------------------------
# 文本排版
# ---------------------------------------------------------------------------
def text_layout(shape, advances):
    """每个字放在哪 → [(x, y, 转角弧度)...], 是字的左下基线点。advances 是每个字的前进宽度 (mm)。
    没有 path: 从 (x, y) 起沿 angle 排成一行。有 path: 沿曲线排, 每个字的中点压在曲线上并顺着曲线的方向;
    圆弧和圆默认顺时针走 (字在圆的外侧正着读), flip 反过来。"""
    path = shape.get('path')
    if not path:
        turn = math.radians(float(shape.get('angle', 0.0)))
        cos, sin = math.cos(turn), math.sin(turn)
        spots, run = [], 0.0
        for advance in advances:
            spots.append((shape['x'] + cos * run, shape['y'] + sin * run, turn))
            run += advance
        return spots
    line = []
    for index, part in enumerate(polylines(path, 96)):
        line += part[0 if index == 0 else 1:]
    if (path['type'] in ('arc', 'circle')) != bool(shape.get('flip')):
        line = line[::-1]
    marks = [0.0]
    for a, b in zip(line, line[1:]):
        marks.append(marks[-1] + dist(a, b))
    spots, run, segment = [], 0.0, 0
    for advance in advances:
        middle = run + advance / 2
        while segment < len(line) - 2 and marks[segment + 1] < middle:
            segment += 1
        a, b = line[segment], line[segment + 1]
        ux, uy = _unit(b[0] - a[0], b[1] - a[1])
        reach = middle - marks[segment]
        spots.append((a[0] + ux * (reach - advance / 2), a[1] + uy * (reach - advance / 2), math.atan2(uy, ux)))
        run += advance
    return spots
