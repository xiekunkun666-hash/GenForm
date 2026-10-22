# -*- coding: utf-8 -*-
"""装配体里量零件的边 (界面这边算, 不走内核): 边的折线点 (世界坐标) + 种类 / 长度 / 半径 → 尺寸; 两条边 → 距离、夹角、中心距、同轴度。

折线点是按边的参数均匀取的、都在真的曲线上, 所以圆弧的圆心用首、中、尾三点的外接圆算就是准的。
"""
from __future__ import annotations

import math

import numpy as np

KINDS = ('line', 'circle', 'curve')


def describe(points, kind, length, radius=None):
    """一条边 → {'type', 'length', 'radius'?, 'diameter'?, 'whole' 整圆?, 'center'?, 'axis'?, 'direction'? (直边), 'points'}。"""
    points = np.asarray(points, float)
    info = {'type': kind, 'length': float(length), 'points': points}
    if kind == 'line' and len(points) >= 2:
        span = points[-1] - points[0]
        norm = np.linalg.norm(span)
        if norm > 1e-12:
            info['direction'] = span / norm
    if kind == 'circle' and radius:
        info['radius'] = float(radius)
        info['diameter'] = 2 * float(radius)
        info['whole'] = abs(float(length) - 2 * math.pi * float(radius)) <= max(1e-6, 1e-4 * float(length))
        centre, axis = _circle(points)
        if centre is not None:
            info['center'], info['axis'] = centre, axis
    return info


def _circle(points):
    """圆弧上的点 → (圆心, 轴的方向)。点太少或在一条线上是 (None, None)。"""
    if len(points) < 3:
        return None, None
    a, b, c = points[0], points[len(points) // 2], points[-1]
    if np.linalg.norm(c - a) < 1e-9:                # 整圆: 首尾是同一点, 换四分之一处那一点
        c = points[len(points) // 4]
    ab, ac = b - a, c - a
    normal = np.cross(ab, ac)
    area = np.linalg.norm(normal)
    if area < 1e-12:
        return None, None
    centre = a + (np.cross(normal, ab) * float(ac @ ac) + np.cross(ac, normal) * float(ab @ ab)) / (2 * area * area)
    return centre, normal / area


def _segment_pair(p0, p1, q0, q1):
    """两条线段之间最近的两点 (每组都是 (n, 3) 的数组, 一次算完所有组合)。"""
    d1, d2, r = p1 - p0, q1 - q0, p0 - q0
    a, e, f = np.einsum('ij,ij->i', d1, d1), np.einsum('ij,ij->i', d2, d2), np.einsum('ij,ij->i', d2, r)
    c, b = np.einsum('ij,ij->i', d1, r), np.einsum('ij,ij->i', d1, d2)
    denom = a * e - b * b
    s = np.where(denom > 1e-12, np.clip((b * f - c * e) / np.where(denom > 1e-12, denom, 1.0), 0.0, 1.0), 0.0)
    t = np.where(e > 1e-12, (b * s + f) / np.where(e > 1e-12, e, 1.0), 0.0)
    s = np.where(t < 0, np.where(a > 1e-12, np.clip(-c / np.where(a > 1e-12, a, 1.0), 0.0, 1.0), 0.0), s)
    s = np.where(t > 1, np.where(a > 1e-12, np.clip((b - c) / np.where(a > 1e-12, a, 1.0), 0.0, 1.0), 0.0), s)
    t = np.clip(t, 0.0, 1.0)
    return p0 + d1 * s[:, None], q0 + d2 * t[:, None]


def nearest(first, second):
    """两条折线之间最短的距离和两端的点。"""
    first, second = np.asarray(first, float), np.asarray(second, float)
    if len(first) == 1:
        first = np.vstack([first, first])
    if len(second) == 1:
        second = np.vstack([second, second])
    p0, p1 = first[:-1], first[1:]
    q0, q1 = second[:-1], second[1:]
    count, other = len(p0), len(q0)
    p0, p1 = np.repeat(p0, other, axis=0), np.repeat(p1, other, axis=0)
    q0, q1 = np.tile(q0, (count, 1)), np.tile(q1, (count, 1))
    a, b = _segment_pair(p0, p1, q0, q1)
    gaps = np.linalg.norm(a - b, axis=1)
    best = int(gaps.argmin())
    return float(gaps[best]), a[best], b[best]


def compare(first, second):
    """两条边 (describe 的结果) → {'distance', 'points', 'delta', 'angle'? 两根直边 / 两个圆的轴的夹角,
    'center_distance'? 两个圆心, 'axis_offset'? 两个圆的轴线相距多远 (0 = 同轴)}。"""
    distance, a, b = nearest(first['points'], second['points'])
    out = {'distance': distance, 'points': [a.tolist(), b.tolist()], 'delta': (b - a).tolist()}
    if 'direction' in first and 'direction' in second:
        out['angle'] = math.degrees(math.acos(min(1.0, abs(float(first['direction'] @ second['direction'])))))
    if 'center' in first and 'center' in second:
        out['center_distance'] = float(np.linalg.norm(second['center'] - first['center']))
        axis_a, axis_b = first['axis'], second['axis']
        out['angle'] = math.degrees(math.acos(min(1.0, abs(float(axis_a @ axis_b)))))
        apart = second['center'] - first['center']
        out['axis_offset'] = float(np.linalg.norm(apart - axis_a * float(apart @ axis_a)))
    return out
