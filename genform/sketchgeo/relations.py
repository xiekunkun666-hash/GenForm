"""几何关系: 能加哪些、照关系摆一次。"""
from __future__ import annotations

import copy
import math

from .base import dist, key_points, _unit
from .transform import moved


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
