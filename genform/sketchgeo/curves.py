"""三点画圆 / 弧、延伸 (方程式曲线在 base 里: 别的块都要用)。"""
from __future__ import annotations

import copy
import math

from .base import _angle, dist, JOIN, NAMES, prim_ends, prims, TAU, _unit
from .editing import intersections


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
