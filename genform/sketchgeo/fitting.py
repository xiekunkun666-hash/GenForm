"""拟合直线、实体边投影到草图平面、沿曲线排文字。"""
from __future__ import annotations

import json
import math

from .base import _angle, dist, length, polylines, TAU, TINY, _unit
from .transform import _nearest_on_segment
from .loops import _same
from .curves import arc3, circle3


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
    from .. import planes
    if not model.get('has_body'):
        return []
    origin, x_dir, y_dir, normal = planes.frame(plane, offset_)
    segments, owner = np.asarray(model['segments'], dtype=float), np.asarray(model['segment_edge'])

    def flat(point):
        local = np.asarray(point, dtype=float) - origin
        return float(local @ x_dir), float(local @ y_dir)

    # 线段按所属的边排好, 每条边取自己那一段 (逐条边去整张表里筛的话, 边多了要算上百秒)
    order = np.argsort(owner, kind='stable')
    sorted_owner = owner[order]
    found, seen = [], set()

    def key(shape):
        return json.dumps({name: (round(value, 6) if isinstance(value, float) else value) for name, value in shape.items()},
                          sort_keys=True, default=lambda value: [round(float(item), 6) for item in value])

    for info in model.get('edges', ()):
        first, last = np.searchsorted(sorted_owner, info['id'], 'left'), np.searchsorted(sorted_owner, info['id'], 'right')
        if last <= first:
            continue
        mine = segments[order[first:last]]
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
        mark = key(shape)
        if mark not in seen and key(twin) not in seen:      # 重合的只留一条 (用一张表记着, 不两两比)
            seen.add(mark)
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
