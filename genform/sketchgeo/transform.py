"""点中和变换: 最近点、点没点中、在不在里面、炸开、平移 / 旋转 / 镜向。"""
from __future__ import annotations

import copy
import math

from .base import _angle, dist, equation_points, _in_sweep, _oriented, _polar, prim_ends, prims, sample, _unit, vertices
from .loops import loop_ring


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
