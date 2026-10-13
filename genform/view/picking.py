# -*- coding: utf-8 -*-
"""拾取: 光标指着哪个面 / 哪条边 (纯 numpy, 在界面线程算)。

零件的显示网格通常只有几千到几万个三角面, 直接拿射线和全部三角面求交比另画一遍拾取缓冲简单,
也不用和渲染线程来回同步。模型大到这里变慢时再换成加速结构。
"""
from __future__ import annotations

import numpy as np

EDGE_REACH = 7.0            # 光标离边的屏幕距离在这么多像素内算指着这条边
EDGE_DEPTH_SLACK = 0.004    # 边比面略远一点点也算可见 (边就贴在面上), 相对于到相机的距离


def ray_triangles(origin, direction, verts, tris):
    """射线和一批三角面求交 → (最近命中的三角面序号或 -1, 距离)。"""
    if len(tris) == 0:
        return -1, np.inf
    a, b, c = (verts[tris[:, k]].astype(np.float64) for k in range(3))
    edge1, edge2 = b - a, c - a
    p = np.cross(direction, edge2)
    det = np.einsum('ij,ij->i', edge1, p)
    ok = np.abs(det) > 1e-12
    inverse = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    offset = origin - a
    u = np.einsum('ij,ij->i', offset, p) * inverse
    q = np.cross(offset, edge1)
    v = (q @ direction) * inverse
    distance = np.einsum('ij,ij->i', edge2, q) * inverse
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (distance > 1e-6)
    if not hit.any():
        return -1, np.inf
    distance = np.where(hit, distance, np.inf)
    nearest = int(distance.argmin())
    return nearest, float(distance[nearest])


def nearest_segment(camera, x, y, width, height, segments):
    """光标离哪条线段最近 → (线段序号或 -1, 像素距离, 那一点到相机的距离)。"""
    if len(segments) == 0:
        return -1, np.inf, np.inf
    screen, depth = camera.project(segments.reshape(-1, 3), width, height)
    start, end = screen[0::2], screen[1::2]
    depth0, depth1 = depth[0::2], depth[1::2]
    visible = (depth0 > 0) & (depth1 > 0)
    span = end - start
    length2 = np.einsum('ij,ij->i', span, span)
    cursor = np.array([x, y], dtype=float)
    along = np.clip(np.einsum('ij,ij->i', cursor - start, span) / np.where(length2 > 0, length2, 1.0), 0.0, 1.0)
    gap = np.linalg.norm(start + span * along[:, None] - cursor, axis=1)
    gap = np.where(visible, gap, np.inf)
    nearest = int(gap.argmin())
    if not np.isfinite(gap[nearest]):
        return -1, np.inf, np.inf
    # 屏幕上按比例插值的深度不是精确的三维距离, 但只用来和面的命中距离比远近, 够用
    return nearest, float(gap[nearest]), float(depth0[nearest] + (depth1[nearest] - depth0[nearest]) * along[nearest])


def pick(camera, x, y, width, height, model):
    """光标下的东西 → ('edge', 边 id) / ('face', 面 id) / None。边优先: 它细, 不优先就永远点不中。"""
    return pick_depth(camera, x, y, width, height, model)[0]


def pick_depth(camera, x, y, width, height, model):
    """和 pick 一样, 另外给出那一点沿视线方向离眼睛多远 → (命中或 None, 深度)。草图线拿这个深度比谁在前面。"""
    if not model or not model.get('has_body'):
        return None, np.inf
    origin, direction = camera.ray(x, y, width, height)
    triangle, distance = ray_triangles(origin, direction, model['verts'], model['tris'])
    segment, gap, depth = nearest_segment(camera, x, y, width, height, model['segments'])
    if segment >= 0 and gap <= EDGE_REACH:
        # 面的命中距离是沿射线量的, 边的深度是沿视线方向量的: 换成同一种再比
        face_depth = distance * float(direction @ camera.basis()[0]) if triangle >= 0 else np.inf
        if depth <= face_depth * (1 + EDGE_DEPTH_SLACK) + 0.05:
            return ('edge', int(model['segment_edge'][segment])), depth
    if triangle >= 0:
        return ('face', int(model['tri_face'][triangle])), distance * float(direction @ camera.basis()[0])
    return None, np.inf


def faces_along(origin, direction, model):
    """射线一路穿过哪些面 → 面 id, 从近到远 (每个面只算一次)。"选择其他"、"选择背面" 用。"""
    if not model or not model.get('has_body') or len(model['tris']) == 0:
        return []
    verts, tris = model['verts'], model['tris']
    a, b, c = (verts[tris[:, k]].astype(np.float64) for k in range(3))
    edge1, edge2 = b - a, c - a
    p = np.cross(direction, edge2)
    det = np.einsum('ij,ij->i', edge1, p)
    ok = np.abs(det) > 1e-12
    inverse = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    offset = origin - a
    u = np.einsum('ij,ij->i', offset, p) * inverse
    q = np.cross(offset, edge1)
    v = (q @ direction) * inverse
    distance = np.einsum('ij,ij->i', edge2, q) * inverse
    hit = np.nonzero(ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (distance > 1e-6))[0]
    found = []
    for triangle in hit[np.argsort(distance[hit])]:
        face = int(model['tri_face'][triangle])
        if face not in found:
            found.append(face)
    return found


def in_rect(screen, depth, low, high):
    """屏幕上的点 (N,2) 哪些在方框里 (在相机后面的不算)。"""
    return (depth > 0) & (screen[:, 0] >= low[0]) & (screen[:, 0] <= high[0]) & (screen[:, 1] >= low[1]) & (screen[:, 1] <= high[1])


def segments_touch_rect(start, end, low, high):
    """屏幕上的线段 (N,2)+(N,2) 哪些碰到了方框 (穿过去也算, 两头都在框外也可能碰到)。"""
    delta = end - start
    enter, leave = np.zeros(len(start)), np.ones(len(start))
    ok = np.ones(len(start), dtype=bool)
    for p, q in ((-delta[:, 0], start[:, 0] - low[0]), (delta[:, 0], high[0] - start[:, 0]),
                 (-delta[:, 1], start[:, 1] - low[1]), (delta[:, 1], high[1] - start[:, 1])):
        level = p == 0
        ok &= ~(level & (q < 0))
        ratio = q / np.where(level, 1.0, p)
        enter = np.where(~level & (p < 0), np.maximum(enter, ratio), enter)
        leave = np.where(~level & (p > 0), np.minimum(leave, ratio), leave)
    return ok & (enter <= leave)


def pick_plane(origin, direction, names, half):
    """射线打在哪个基准面的方框里 (半边长 half) → 基准面名; 打中多个取最近的; 都没打中返回 None。"""
    from .. import planes
    best, best_reach = None, np.inf
    for name in names:
        base, x_dir, y_dir, normal = planes.frame(name)
        slope = float(direction @ normal)
        if abs(slope) < 1e-9:
            continue
        reach = float((base - origin) @ normal) / slope
        if reach <= 0 or reach >= best_reach:
            continue
        hit = origin + direction * reach
        if abs(float(hit @ x_dir)) <= half and abs(float(hit @ y_dir)) <= half:
            best, best_reach = name, reach
    return best
