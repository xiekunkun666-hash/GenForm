# -*- coding: utf-8 -*-
"""仿真里的计算 (都只读, 不改文档)。

static   静力分析: 把实体切成小方块 (体素), 每个方块一个八节点单元, 解线弹性方程 → 变形和应力。
         这是 "看趋势" 的精度: 斜面和圆弧被切成台阶, 尖角处的应力峰值不准; 薄壁至少要有三四层方块才可信。
drag     风阻估算: 迎风面积 (精确投影) × 你填的阻力系数。不是流场计算。

单位: 长度 mm, 力 N, 应力 MPa (= N/mm²), 弹性模量 MPa。
"""
from __future__ import annotations

import math

import numpy as np

from . import build

CELL_LIMITS = {'coarse': 2500, 'medium': 7000, 'fine': 16000}      # 网格密度 → 最多切成多少个方块


def _body_mesh(features, upto, normals=False):
    body, _, _ = build.rebuild(features, upto)
    if build._is_empty(body):
        raise build.FeatureError('还没有实体')
    verts, shading, tris, tri_face, _ = build.tessellate(body)
    if normals:
        return body, verts.astype(np.float64), tris.astype(np.int64), tri_face.astype(np.int64), shading.astype(np.float64)
    return body, verts.astype(np.float64), tris.astype(np.int64), tri_face.astype(np.int64)


def refine(verts, normals, tris, target, limit=300000):
    """把三角网格切细到边长不超过 target 左右 (云图要用: 大平面本来只有四个角有顶点, 中间的颜色全靠插值, 看不出分布)。
    每个三角形按自己的大小均匀切成 n² 个小的; 总数超过 limit 就放粗一些。→ verts, normals, tris。"""
    corners, shading = verts[tris], normals[tris]
    longest = np.max([np.linalg.norm(corners[:, first] - corners[:, second], axis=1) for first, second in ((0, 1), (1, 2), (2, 0))], axis=0)
    while True:
        counts = np.clip(np.ceil(longest / target), 1, 48).astype(int)
        if int((counts * counts).sum()) <= limit:
            break
        target *= 1.3
    out_verts, out_normals, out_tris, base = [], [], [], 0
    for count in np.unique(counts):
        chosen = np.where(counts == count)[0]
        grid = [(i, j) for i in range(count + 1) for j in range(count + 1 - i)]
        index = {pair: number for number, pair in enumerate(grid)}
        weights = np.array([[1 - (i + j) / count, i / count, j / count] for i, j in grid])
        small = []
        for i in range(count):
            for j in range(count - i):
                small.append((index[i, j], index[i + 1, j], index[i, j + 1]))
                if i + j < count - 1:
                    small.append((index[i + 1, j], index[i + 1, j + 1], index[i, j + 1]))
        small = np.array(small)
        out_verts.append(np.einsum('mk,tkd->tmd', weights, corners[chosen]).reshape(-1, 3))
        out_normals.append(np.einsum('mk,tkd->tmd', weights, shading[chosen]).reshape(-1, 3))
        offsets = base + np.arange(len(chosen))[:, None, None] * len(grid)
        out_tris.append((small[None] + offsets).reshape(-1, 3))
        base += len(chosen) * len(grid)
    out_normals = np.concatenate(out_normals)
    out_normals /= np.maximum(np.linalg.norm(out_normals, axis=1, keepdims=True), 1e-12)
    return np.concatenate(out_verts), out_normals, np.concatenate(out_tris)


def _crossings(verts, tris, origin, step, counts):
    """沿 Z 方向从每个格子中心往上打一根线, 和三角面相交在哪 → (格子列号, z) 两个数组。"""
    nx, ny = counts
    # 线稍微偏一点: 正好打在三角形的边或顶点上会被算两次
    xs = origin[0] + (np.arange(nx) + 0.5 + 3.7e-4) * step
    ys = origin[1] + (np.arange(ny) + 0.5 + 6.1e-4) * step
    columns, heights = [], []
    corners = verts[tris]
    for a, b, c in corners:
        low_x, high_x = min(a[0], b[0], c[0]), max(a[0], b[0], c[0])
        low_y, high_y = min(a[1], b[1], c[1]), max(a[1], b[1], c[1])
        i0, i1 = np.searchsorted(xs, low_x), np.searchsorted(xs, high_x)
        j0, j1 = np.searchsorted(ys, low_y), np.searchsorted(ys, high_y)
        if i0 >= i1 or j0 >= j1:
            continue
        det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(det) < 1e-14:
            continue
        gx, gy = np.meshgrid(xs[i0:i1], ys[j0:j1], indexing='ij')
        u = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / det
        v = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / det
        w = 1.0 - u - v
        inside = (u >= 0) & (v >= 0) & (w >= 0)
        if not inside.any():
            continue
        ii, jj = np.nonzero(inside)
        columns.append((ii + i0) * ny + (jj + j0))
        heights.append((u * a[2] + v * b[2] + w * c[2])[inside])
    if not columns:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    return np.concatenate(columns), np.concatenate(heights)


def voxelize(verts, tris, limit):
    """实体的表面网格 → (方块边长, 最小角, 实心与否的三维数组 [nx, ny, nz])。方块个数不超过 limit 左右。"""
    low, high = verts.min(axis=0), verts.max(axis=0)
    size = np.maximum(high - low, 1e-6)
    step = float((size.prod() / max(limit, 1)) ** (1.0 / 3.0))
    step = max(step, float(size.max()) / 160.0)
    for _ in range(6):                                  # 实体只占包围盒的一部分: 方块数够用就再切细一点
        counts = np.maximum(np.ceil(size / step - 1e-9).astype(int), 1)
        columns, heights = _crossings(verts, tris, low, step, counts[:2])
        solid = np.zeros(tuple(counts), dtype=bool)
        order = np.lexsort((heights, columns))
        columns, heights = columns[order], heights[order]
        start = 0
        while start < len(columns):
            end = start
            while end < len(columns) and columns[end] == columns[start]:
                end += 1
            hits = heights[start:end]
            ix, iy = divmod(int(columns[start]), int(counts[1]))
            for pair in range(0, len(hits) - 1, 2):     # 进、出成对: 两次相交之间是实心
                k0 = int(math.ceil((hits[pair] - low[2]) / step - 0.5))
                k1 = int(math.floor((hits[pair + 1] - low[2]) / step - 0.5))
                if k1 >= k0:
                    solid[ix, iy, max(k0, 0):min(k1, counts[2] - 1) + 1] = True
            start = end
        filled = int(solid.sum())
        if filled >= limit * 0.6 or filled == 0:
            break
        step *= max(0.6, (filled / (limit * 0.9)) ** (1.0 / 3.0))
    if not solid.any():
        raise build.FeatureError('实体太薄或太小，切不出计算用的网格')
    return step, low, solid


def _hex_stiffness(step, young, poisson):
    """边长 step 的八节点方块单元 → (24×24 刚度矩阵, 中心处的应变矩阵 B [6×24], 材料矩阵 D [6×6])。"""
    lam = young * poisson / ((1 + poisson) * (1 - 2 * poisson))
    mu = young / (2 * (1 + poisson))
    material = np.zeros((6, 6))
    material[:3, :3] = lam
    material[np.arange(3), np.arange(3)] += 2 * mu
    material[np.arange(3, 6), np.arange(3, 6)] = mu
    signs = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1], [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]], dtype=float)

    def strain_matrix(point):
        grads = np.empty((8, 3))
        for axis in range(3):
            other = [k for k in range(3) if k != axis]
            grads[:, axis] = signs[:, axis] * (1 + signs[:, other[0]] * point[other[0]]) * (1 + signs[:, other[1]] * point[other[1]]) / 8
        grads *= 2.0 / step
        matrix = np.zeros((6, 24))
        for node in range(8):
            dx, dy, dz = grads[node]
            matrix[:, node * 3:node * 3 + 3] = [[dx, 0, 0], [0, dy, 0], [0, 0, dz], [dy, dx, 0], [0, dz, dy], [dz, 0, dx]]
        return matrix

    stiffness = np.zeros((24, 24))
    gauss = 1 / math.sqrt(3)
    for gx in (-gauss, gauss):
        for gy in (-gauss, gauss):
            for gz in (-gauss, gauss):
                matrix = strain_matrix((gx, gy, gz))
                stiffness += matrix.T @ material @ matrix * (step / 2) ** 3
    return stiffness, [strain_matrix(tuple(corner)) for corner in signs], material, signs


def _face_samples(verts, tris, tri_face, faces, step):
    """这几张面上撒一层点 (间距不超过半个方块): 用来找挨着这些面的网格节点。"""
    chosen = tris[np.isin(tri_face, list(faces))]
    if len(chosen) == 0:
        return np.zeros((0, 3))
    points = []
    for a, b, c in verts[chosen]:
        longest = max(np.linalg.norm(b - a), np.linalg.norm(c - a), np.linalg.norm(c - b))
        parts = int(min(40, max(1, math.ceil(longest / (step * 0.5)))))
        for i in range(parts + 1):
            for j in range(parts + 1 - i):
                points.append(a + (b - a) * (i / parts) + (c - a) * (j / parts))
    return np.array(points)


def static(features, upto, data):
    """静力分析。data: {'fixed': [固定的面 id], 'loaded': [受力的面 id], 'force': [Fx, Fy, Fz] 合力 (N, 均摊到受力面上),
                      'young': 弹性模量 MPa, 'poisson': 泊松比, 'yield': 屈服强度 MPa (可以没有), 'quality': coarse/medium/fine}
    → {'max_stress', 'max_displacement', 'safety', 'cells', 'cell_size', 'stress': 每个显示顶点的 von Mises 应力,
       'move': 每个显示顶点的位移 [N, 3],
       'mesh': 画云图用的切细了的网格 {'verts', 'normals', 'tris', 'stress': 它每个顶点的应力}}。"""
    from scipy import sparse
    from scipy.sparse.linalg import cg, spsolve
    from scipy.spatial import cKDTree

    _, verts, tris, tri_face, shading = _body_mesh(features, upto, normals=True)
    young, poisson = float(data.get('young', 0)), float(data.get('poisson', 0.3))
    force = np.array([float(value) for value in data.get('force', (0, 0, 0))])
    if young <= 0 or not 0 <= poisson < 0.5:
        raise build.FeatureError('材料的弹性模量和泊松比不对')
    if not data.get('fixed'):
        raise build.FeatureError('先指定固定的面（零件被夹住、拧住的地方）')
    if not data.get('loaded') or not np.any(force):
        raise build.FeatureError('先指定受力的面，并填上力的大小')
    if set(data['fixed']) & set(data['loaded']):
        raise build.FeatureError('同一个面不能既固定又受力')
    step, low, solid = voxelize(verts, tris, CELL_LIMITS.get(data.get('quality'), CELL_LIMITS['medium']))
    nx, ny, nz = solid.shape
    cells = np.argwhere(solid)                                   # (单元数, 3): 每个实心方块的格子坐标
    offsets = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]])
    corner = cells[:, None, :] + offsets[None, :, :]             # (单元数, 8, 3)
    node_id = (corner[..., 0] * (ny + 1) + corner[..., 1]) * (nz + 1) + corner[..., 2]
    used, compact = np.unique(node_id, return_inverse=True)      # 只留实心方块用到的节点
    element_nodes = compact.reshape(-1, 8)
    count = len(used)
    grid = np.stack(np.unravel_index(used, (nx + 1, ny + 1, nz + 1)), axis=1)
    positions = low + grid * step

    tree = cKDTree(positions)

    def nodes_on(faces):
        samples = _face_samples(verts, tris, tri_face, faces, step)
        if len(samples) == 0:
            return np.zeros(0, dtype=np.int64)
        near = tree.query_ball_point(samples, step * 0.9)
        return np.unique(np.fromiter((node for group in near for node in group), dtype=np.int64))

    held, pushed = nodes_on(data['fixed']), nodes_on(data['loaded'])
    pushed = np.setdiff1d(pushed, held)
    if len(held) < 3:
        raise build.FeatureError('固定的面太小，网格上抓不住它：换成“精细”，或者选大一点的面')
    if len(pushed) == 0:
        raise build.FeatureError('受力的面太小，网格上找不到它：换成“精细”，或者选大一点的面')

    stiffness, corner_strain, material, _ = _hex_stiffness(step, young, poisson)
    dofs = (element_nodes[:, :, None] * 3 + np.arange(3)[None, None, :]).reshape(-1, 24)
    rows = np.repeat(dofs, 24, axis=1).ravel()
    cols = np.tile(dofs, (1, 24)).ravel()
    values = np.tile(stiffness.ravel(), len(dofs))
    matrix = sparse.coo_matrix((values, (rows, cols)), shape=(count * 3, count * 3)).tocsr()
    load = np.zeros(count * 3)
    for axis in range(3):
        load[pushed * 3 + axis] = force[axis] / len(pushed)
    free = np.ones(count * 3, dtype=bool)
    free[(held[:, None] * 3 + np.arange(3)[None, :]).ravel()] = False
    reduced = matrix[free][:, free].tocsc()
    if reduced.shape[0] <= 24000:
        solution = spsolve(reduced, load[free])
    else:
        diagonal = reduced.diagonal()
        preconditioner = sparse.diags(1.0 / np.where(diagonal > 0, diagonal, 1.0))
        solution, status = cg(reduced, load[free], rtol=1e-7, maxiter=8000, M=preconditioner)
        if status != 0:
            raise build.FeatureError('方程没有解收敛：零件可能有没连在一起的部分，或者固定得不够（会整体晃动）')
    if not np.all(np.isfinite(solution)):
        raise build.FeatureError('方程解不出来：零件可能有没连在一起的部分，或者固定得不够（会整体晃动）')
    moved = np.zeros(count * 3)
    moved[free] = solution
    # 应力算到节点上 (每个方块在它八个角上各算一次, 共用一个节点的几个方块取平均): 表面上的节点给出的就是表面的应力,
    # 比只看方块中心准 — 弯曲时最大的应力正好在表面
    total, shares = np.zeros((count, 6)), np.zeros(count)
    local = moved[dofs]
    for corner_index, matrix_at in enumerate(corner_strain):
        np.add.at(total, element_nodes[:, corner_index], local @ matrix_at.T @ material.T)
        np.add.at(shares, element_nodes[:, corner_index], 1.0)
    total /= shares[:, None]
    sx, sy, sz, txy, tyz, tzx = total.T
    mises = np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (txy ** 2 + tyz ** 2 + tzx ** 2))
    mises[held] = np.minimum(mises[held], np.percentile(mises, 99.0))      # 固定面上的节点被硬钉住, 那里的应力是假的尖峰
    _, nearest_node = tree.query(verts)
    shown_stress = mises[nearest_node]
    shown_move = moved.reshape(-1, 3)[nearest_node]
    top = float(np.percentile(mises, 99.5)) if len(mises) > 200 else float(mises.max())     # 丢掉台阶尖角上个别离谱的方块
    limit = float(data.get('yield') or 0)
    fine_verts, fine_normals, fine_tris = refine(verts, shading, tris, step)
    # 云图上每个点的应力: 周围最近几个节点按距离加权 (只取最近的一个会一块一块的)
    distance, around = tree.query(fine_verts, k=min(4, count))
    weight = 1.0 / np.maximum(distance, step * 0.05) ** 2
    fine_stress = (mises[around] * weight).sum(axis=1) / weight.sum(axis=1)
    mesh = {'verts': fine_verts.astype(np.float32), 'normals': fine_normals.astype(np.float32), 'tris': fine_tris.astype(np.uint32),
            'stress': fine_stress.astype(np.float32)}
    return {'max_stress': top, 'peak_stress': float(mises.max()), 'mesh': mesh,
            'max_displacement': float(np.linalg.norm(moved.reshape(-1, 3), axis=1).max()),
            'safety': (limit / top) if limit > 0 and top > 0 else None, 'cells': int(len(cells)), 'cell_size': step,
            'stress': shown_stress.astype(np.float32), 'move': shown_move.astype(np.float32)}


def frontal_area(verts, tris, direction, resolution=320):
    """沿 direction 看过去的投影面积 (mm²): 往这个方向打一片线, 数打中实体的有多少根。"""
    front = np.asarray(direction, dtype=float)
    length = np.linalg.norm(front)
    if length < 1e-12:
        raise build.FeatureError('风的方向不能是零')
    front /= length
    helper = np.array([0.0, 0.0, 1.0]) if abs(front[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    right = np.cross(helper, front)
    right /= np.linalg.norm(right)
    up = np.cross(front, right)
    local = np.stack([verts @ right, verts @ up, verts @ front], axis=1)
    low, high = local.min(axis=0), local.max(axis=0)
    step = float(max(high[0] - low[0], high[1] - low[1], 1e-6)) / resolution
    counts = np.maximum(np.ceil((high[:2] - low[:2]) / step).astype(int), 1)
    columns, _ = _crossings(local, tris, low, step, counts)
    return float(len(np.unique(columns))) * step * step


def drag(features, upto, data):
    """风阻估算。data: {'direction': 风吹过来的方向 [x, y, z], 'speed': 风速 m/s, 'density': 流体密度 kg/m³, 'cd': 阻力系数}
    → {'area': 迎风面积 mm², 'force': 阻力 N, 'pressure': 动压 Pa, 'power': 克服阻力的功率 W}。"""
    _, verts, tris, _ = _body_mesh(features, upto)
    speed, density, coefficient = float(data.get('speed', 0)), float(data.get('density', 1.225)), float(data.get('cd', 1.0))
    if speed <= 0 or density <= 0 or coefficient <= 0:
        raise build.FeatureError('风速、流体密度、阻力系数都要大于 0')
    area = frontal_area(verts, tris, data.get('direction', (0, 1, 0)))
    pressure = 0.5 * density * speed ** 2
    force = pressure * coefficient * area * 1e-6
    return {'area': area, 'force': force, 'pressure': pressure, 'power': force * speed}
