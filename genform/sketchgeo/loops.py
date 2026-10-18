"""轮廓: 首尾相接成环、一串、检查和修复草图 (废线、重复、没接上的端点)。"""
from __future__ import annotations

import copy

from .base import anchor, dist, ends, GAP, is_closed, JOIN, length, NAMES, _oriented, prim_ends, prims, sample, TINY


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
