"""草图几何的基础: 常量、取数、图形 → 基本曲线 (直线 / 圆弧 / 贝塞尔) → 采样折线、端点、特征点。"""
from __future__ import annotations

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
