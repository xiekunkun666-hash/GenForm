"""修改: 求交点、剪裁、圆角、等距。"""
from __future__ import annotations

import copy
import math

from .base import (
    _angle, dist, _in_sweep, is_closed, JOIN, NAMES, polylines, prims, sample, signed_area, TAU, TINY, _unit, vertices)
from .transform import contains, explode, moved, nearest, nearest_on_prim, _nearest_on_segment, _ring


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
