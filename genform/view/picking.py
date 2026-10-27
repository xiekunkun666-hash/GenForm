# -*- coding: utf-8 -*-
"""拾取: 光标指着哪个面 / 哪条边 (纯 numpy, 在界面线程算)。

拿射线和三角面求交比另画一遍拾取缓冲简单, 也不用和渲染线程来回同步。三角面、边线段多了 (十万个) 以后每次都和全部
求交太慢 (鼠标动一下几十毫秒), 所以先筛一遍: 每个三角面、每条线段在空间里的包围盒只在零件变了的时候算一次 (_space),
射线先和这些盒子比, 只有碰得到的那几个才去求交 / 投影到屏幕上。原来筛的是屏幕上的方框, 视角一变 (转完视角、点了
视图定向) 就要把整个零件重新投影一遍, 大零件第一下要几十上百毫秒; 空间里的盒子和视角无关, 不会顿这一下。
"""
from __future__ import annotations

import numpy as np

EDGE_REACH = 7.0            # 光标离边的屏幕距离在这么多像素内算指着这条边
EDGE_DEPTH_SLACK = 0.004    # 边比面略远一点点也算可见 (边就贴在面上), 相对于到相机的距离
NEAR_PIXELS = 24.0          # 找 "离光标最近的线段" 时只看屏幕上离光标这么近的: 再远的反正够不着
_kept = {}                  # 记着的包围盒、屏幕方框: 名称 → (凭据, 内容, 它们来自的数组)


def _screen(name, camera, width, height, arrays, make):
    """这批几何体在现在这个视角下的屏幕方框; 视角、窗口大小、几何体都没变时用上次记着的。"""
    token = _token(camera, width, height, arrays)
    found = _kept.get(name)
    if found is None or found[0] != token:
        found = (token, make(), arrays)         # 留着 arrays: 它们活着, id 才不会被别的数组占去
        _kept[name] = found
    return found[1]


def _token(camera, width, height, arrays):
    return (tuple(float(value) for value in camera.target), camera.yaw, camera.pitch, camera.distance, camera.perspective,
            width, height) + tuple(id(array) for array in arrays)


def _space(name, arrays, make):
    """这批几何体在空间里的包围盒 (low, high): 和视角无关, 几何体换了才重算。"""
    found = _kept.get(name)
    if found is None or found[0] != tuple(id(array) for array in arrays):
        found = (tuple(id(array) for array in arrays), make(), arrays)
        _kept[name] = found
    return found[1]


def _along_ray(boxes, origin, direction, reach, forward=True):
    """射线穿过哪些盒子 (每个盒子先往外放宽 reach) → 序号。boxes: (low, high, ...), 都是 (3, 盒子数) 单精度 —
    按分量连续存放, 一次取一个分量比从 (盒子数, 3) 里跳着取快好几倍; 中间结果就地算在复用的数组里 (每次新开
    十几万个数的数组比算本身还慢)。forward: 只算起点前面的 (透视; 平行投影眼睛后面也看得见)。"""
    low, high = boxes[0], boxes[1]
    count = low.shape[1]
    found = _kept.get('ray_buffers')
    if found is None or len(found[0]) < count:
        found = tuple(np.empty(count, dtype=np.float32) for _ in range(5))
        _kept['ray_buffers'] = found
    enter, leave, first, second, spare = (buffer[:count] for buffer in found)
    enter.fill(0.0 if forward else -np.inf)
    leave.fill(np.inf)
    reach = float(reach) + 1e-3                     # 单精度的盒子: 留一点余量, 只会多挑不会漏
    for axis in range(3):                           # 射线穿过盒子在三个方向上的那三段要有重叠
        start, step = float(origin[axis]), float(direction[axis])
        if abs(step) < 1e-12:
            outside = (low[axis] > start + reach) | (high[axis] < start - reach)
            leave[outside] = -np.inf
            continue
        np.subtract(low[axis], start + reach, out=first)
        first *= np.float32(1.0 / step)
        np.subtract(high[axis], start - reach, out=second)
        second *= np.float32(1.0 / step)
        np.maximum(enter, np.minimum(first, second, out=spare), out=enter)
        np.minimum(leave, np.maximum(first, second, out=spare), out=leave)
    return np.nonzero(leave >= enter)[0]


def ray_model(camera, x, y, width, height, model):
    """光标下最近的三角面 → (序号或 -1, 沿射线的距离)。"""
    origin, direction = camera.ray(x, y, width, height)
    return ray_boxed(origin, direction, model)


def ray_boxed(origin, direction, model):
    """一条射线打在零件的哪个三角面上 → (序号或 -1, 距离)。结果和 ray_triangles 一样, 只是三角面多时先用空间里的
    包围盒筛过 (和视角无关, 零件变了才重算): 转视角、缩放一开始找 "光标指着零件上哪一点" 也不会顿一下。"""
    verts, tris = model['verts'], model['tris']
    if len(tris) < 4000:
        return ray_triangles(origin, direction, verts, tris)

    def boxes():
        corners = verts[tris].astype(np.float64)                # (三角面, 3 个顶点, xyz)
        return np.ascontiguousarray(corners.min(axis=1).T, dtype=np.float32), np.ascontiguousarray(corners.max(axis=1).T, dtype=np.float32)
    near = _along_ray(_space('boxes3d', (verts, tris), boxes), origin, direction, 0.0)
    hit, distance = ray_triangles(origin, direction, verts, tris[near])
    return (int(near[hit]), distance) if hit >= 0 else (-1, np.inf)


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


def ray_box(origin, direction, low, high):
    """射线进包围盒的距离 (没碰到是 inf)。"""
    with np.errstate(divide='ignore', invalid='ignore'):
        inverse = 1.0 / np.where(np.abs(direction) < 1e-12, 1e-12, direction)
    near = (np.asarray(low, float) - origin) * inverse
    far = (np.asarray(high, float) - origin) * inverse
    enter, leave = float(np.max(np.minimum(near, far))), float(np.min(np.maximum(near, far)))
    return max(enter, 0.0) if leave >= max(enter, 0.0) else np.inf


def pick_extras(origin, direction, extras):
    """装配体里别的零件 (视图另外画的网格, 带 'pick' 的才能点): 射线最先碰到哪一个 → (它的 'pick', 距离) 或 (None, inf)。
    先按包围盒从近到远排, 碰到了一个以后比它远的包围盒就不用算了。"""
    order = sorted((ray_box(origin, direction, part['low'], part['high']), number) for number, part in enumerate(extras)
                   if part.get('pick') is not None and part.get('low') is not None)
    best, reach = None, np.inf
    for enter, number in order:
        if enter >= reach:
            break
        part = extras[number]
        start, way = origin, direction
        if part.get('matrix') is not None:     # 动着的件 (网格没变, 带摆放矩阵): 射线换到它自己的坐标里去算
            back = np.linalg.inv(np.asarray(part['matrix'], float))
            start, way = back[:3, :3] @ origin + back[:3, 3], back[:3, :3] @ direction
        triangle, distance = ray_triangles(start, way, np.asarray(part['verts']), np.asarray(part['tris']))
        if triangle >= 0 and distance < reach:
            best, reach = part['pick'], distance
    return best, reach


def nearest_segment(camera, x, y, width, height, segments, name='edges'):
    """光标离哪条线段最近 → (线段序号或 -1, 像素距离, 那一点到相机的距离)。
    segments: (线段数, 2, 3), 或者两点一段摊平的 (2×线段数, 3) (草图线是这样给的)。
    name: 记着的包围盒放在哪一格 — 实体的边和草图线轮流查, 共用一格就会互相顶掉、每次都重算。"""
    source = segments
    segments = np.asarray(segments).reshape(-1, 2, 3)
    if len(segments) == 0:
        return -1, np.inf, np.inf

    def projected(chosen=slice(None)):
        screen, depth = camera.project(segments[chosen].reshape(-1, 3), width, height)
        return screen[0::2], screen[1::2], depth[0::2], depth[1::2]
    picked = None
    if len(segments) > 4000:
        # 线段多: 不把全部线段投影一遍, 先在空间里挑出离视线够近 (屏幕上不超过 NEAR_PIXELS) 的那些
        def boxes():
            low = np.ascontiguousarray(np.minimum(segments[:, 0], segments[:, 1]).T, dtype=np.float32)
            high = np.ascontiguousarray(np.maximum(segments[:, 0], segments[:, 1]).T, dtype=np.float32)
            bottom, top = [low[axis].min() for axis in range(3)], [high[axis].max() for axis in range(3)]
            corners = np.array([[float(a), float(b), float(c)] for a in (bottom[0], top[0]) for b in (bottom[1], top[1]) for c in (bottom[2], top[2])])
            return low, high, corners
        low, high, corners = _space(('segments3d', name), (source,), boxes)
        origin, direction = camera.ray(x, y, width, height)
        reach = NEAR_PIXELS * camera.pixel_size(height)
        if camera.perspective:          # 越远一个像素越大: 按零件最远的那一点放宽
            farthest = float(((corners - camera.eye()) @ camera.basis()[0]).max())
            reach *= max(farthest, 0.0) / max(camera.distance, 1e-9)
        picked = _along_ray((low, high), origin, direction, reach * 1.05, camera.perspective)
        if len(picked) == 0:
            return -1, np.inf, np.inf
        start, end, depth0, depth1 = projected(picked)
    else:
        start, end, depth0, depth1 = _screen(('segments', name), camera, width, height, (source,), projected)
    chosen = None
    if picked is not None:              # 挑出来的里面再只看屏幕上挨着光标的那些
        chosen = np.nonzero((np.minimum(start[:, 0], end[:, 0]) <= x + NEAR_PIXELS) & (np.maximum(start[:, 0], end[:, 0]) >= x - NEAR_PIXELS)
                            & (np.minimum(start[:, 1], end[:, 1]) <= y + NEAR_PIXELS) & (np.maximum(start[:, 1], end[:, 1]) >= y - NEAR_PIXELS))[0]
        if len(chosen) == 0:
            return -1, np.inf, np.inf
        start, end, depth0, depth1 = start[chosen], end[chosen], depth0[chosen], depth1[chosen]
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
    # 透视时屏幕上按比例走的是 1/深度, 不是深度: 按深度插值, 长直边的中点会差出一毫米多, 比面的命中还远, 边就点不中了
    near, far, part = float(depth0[nearest]), float(depth1[nearest]), float(along[nearest])
    reach = 1.0 / (1.0 / near + (1.0 / far - 1.0 / near) * part) if camera.perspective else near + (far - near) * part
    index = nearest if chosen is None else int(chosen[nearest])
    return (index if picked is None else int(picked[index])), float(gap[nearest]), reach


def pick(camera, x, y, width, height, model):
    """光标下的东西 → ('edge', 边 id) / ('face', 面 id) / None。边优先: 它细, 不优先就永远点不中。"""
    return pick_depth(camera, x, y, width, height, model)[0]


def pick_depth(camera, x, y, width, height, model):
    """和 pick 一样, 另外给出那一点沿视线方向离眼睛多远 → (命中或 None, 深度)。草图线拿这个深度比谁在前面。"""
    if not model or not model.get('has_body'):
        return None, np.inf
    origin, direction = camera.ray(x, y, width, height)
    triangle, distance = ray_model(camera, x, y, width, height, model)
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


def triangles_touch_rect(screen, depth, tris, low, high):
    """投影三角面与矩形相交，包括矩形完全落在大三角面内的情况。"""
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if len(tris) == 0:
        return np.zeros(0, dtype=bool)
    points = np.asarray(screen)[tris]
    visible = (np.asarray(depth)[tris] > 0).all(axis=1)
    touched = np.zeros(len(tris), dtype=bool)
    for number in range(3):
        touched |= segments_touch_rect(points[:, number], points[:, (number + 1) % 3], low, high)
    corner = np.asarray(low, dtype=float)
    sides = []
    for number in range(3):
        start, end = points[:, number], points[:, (number + 1) % 3]
        delta, offset = end - start, corner - start
        sides.append(delta[:, 0] * offset[:, 1] - delta[:, 1] * offset[:, 0])
    sides = np.asarray(sides)
    area = ((points[:, 1, 0] - points[:, 0, 0]) * (points[:, 2, 1] - points[:, 0, 1])
            - (points[:, 1, 1] - points[:, 0, 1]) * (points[:, 2, 0] - points[:, 0, 0]))
    touched |= ((sides >= 0).all(axis=0) | (sides <= 0).all(axis=0)) & (np.abs(area) > 1e-12)
    return visible & touched


def mesh_in_rect(camera, width, height, mesh, low, high, crossing):
    """按显示网格判断组件框选；matrix 是动态摆放，不能使用原始包围盒代替。"""
    verts = np.asarray(mesh['verts'], dtype=float).reshape(-1, 3)
    tris = np.asarray(mesh['tris'], dtype=np.int64).reshape(-1, 3)
    if len(verts) == 0 or len(tris) == 0:
        return False
    if mesh.get('matrix') is not None:
        matrix = np.asarray(mesh['matrix'], dtype=float)
        verts = verts @ matrix[:3, :3].T + matrix[:3, 3]
    screen, depth = camera.project(verts, width, height)
    inside = in_rect(screen, depth, low, high)[tris]
    if not crossing:
        return bool(inside.all())
    if inside.any() or triangles_touch_rect(screen, depth, tris, low, high).any():
        return True
    partial = tris[(depth[tris] > 0).any(axis=1) & ~(depth[tris] > 0).all(axis=1)]
    near = 1e-6
    for triangle in partial:
        polygon = []
        for number in range(3):
            start, end = triangle[number], triangle[(number + 1) % 3]
            if depth[start] >= near:
                polygon.append(verts[start])
            if (depth[start] >= near) != (depth[end] >= near):
                amount = (near - depth[start]) / (depth[end] - depth[start])
                polygon.append(verts[start] + amount * (verts[end] - verts[start]))
        if len(polygon) >= 3:
            clipped, ahead = camera.project(polygon, width, height)
            fan = [[0, number, number + 1] for number in range(1, len(polygon) - 1)]
            if triangles_touch_rect(clipped, ahead, fan, low, high).any():
                return True
    return False


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
