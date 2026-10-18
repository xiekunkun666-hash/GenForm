"""阵列和镜向: 线性、圆周、沿曲线、按草图点、按表格、填充、变量阵列。"""
from __future__ import annotations

import math
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_CompCurve
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from ..build import FeatureError
from .. import build
from ... import sketchgeom
from .helpers import (
    _axis, _centroid, _dir, _frame, _moved, _need_body, _number, _path, _pnt, _profile, _reach, _sketch, _spots,
    _translation, _xyz)
from .modify import draft, rib, shell, split, thread, wrap


# ---- 阵列 ----
class _Seeds(list):
    """要复制的东西, 外加这次复制出来的 [(工具体, 方式)...] (made): 重算时记成这个阵列特征的工具体,
    后面的阵列 / 镜像就能把这个阵列整个当对象 (比如先阵列螺栓孔, 再把轮子连孔一起镜像到另一边)。"""

    def __init__(self, items=()):
        super().__init__(items)
        self.made = []
        self.origins = []               # 和 made 一一对应: 每一份是照着哪个特征复制的 (阵列的阵列 → 最早的原件)
        self.origins_of = []            # 和种子一一对应: 每个种子的原件特征 (整个实体当种子的是 None)


def _seeds(body, params, ctx, need=False):
    """要复制的东西 → [(工具体, 方式, 造它的特征或 None)...]。不写对象 = 整个实体。"""
    identifiers = params.get('features') or []
    seeds = _Seeds()
    ctx.copied = seeds.made
    ctx.copied_origins = seeds.origins
    if not identifiers:
        if need:
            raise FeatureError('要选对象：写上造型特征的 id（features）')
        _need_body(body, '阵列')
        seeds.append((body, 'add', None))
        seeds.origins_of.append(None)
        return seeds
    for identifier in identifiers:
        if identifier not in ctx.tools:
            raise FeatureError(f'{identifier} 不能被阵列或镜像：只有拉伸、旋转、扫描、放样、孔、螺柱这类特征和阵列、镜像可以'
                               '（并且要算成功了）')
        feature = next(item for item in ctx.features if item['id'] == identifier)
        made = ctx.tools[identifier]
        origins = ctx.sources.get(identifier) or []
        for number, (solid, op) in enumerate(made if isinstance(made, list) else [made]):  # 阵列 / 镜像: 它复制出来的每一份
            seeds.append((solid, op, feature))
            seeds.origins_of.append(origins[number] if number < len(origins) else identifier)
    return seeds


def _replicate(body, seeds, transforms):
    """把每个工具体按每个变换复制一份, 用它原来的方式并进实体: 加料的攒到一起一次并进去, 再把切除的攒到一起一次切
    (一份一份来的话, 每一份都要和越来越大的实体整个求交一遍: 911 的车身上镜像一套轮子要 15 次、将近 7 秒)。"""
    adds, cuts = [], []
    for transform in transforms:
        for number, (solid, op, _) in enumerate(seeds):
            copy = _moved(solid, transform)
            if isinstance(seeds, _Seeds):
                seeds.made.append((copy, op))
                seeds.origins.append(seeds.origins_of[number])
            if op == 'cut':
                cuts.append(copy)
            elif op == 'add':
                adds.append(copy)
            else:
                body = build.combine(body, copy, op, '阵列')
    if adds:
        body = build.combine(body, adds[0] if len(adds) == 1 else build._compound(adds), 'add', '阵列')
    if cuts:
        body = build.combine(body, build._compound(cuts), 'cut', '阵列')
    return body


def _count(params, key):
    count = int(round(_number(params, key)))
    if not 1 <= count <= 500:
        raise FeatureError('数量要在 1 到 500 之间')
    return count


def pattern_linear(body, params, ctx):
    seeds = _seeds(body, params, ctx)
    first, second = _axis(ctx, params.get('axis1', 'X'))[1], _axis(ctx, params.get('axis2', 'Y'))[1]
    count1, count2 = _count(params, 'count1'), _count(params, 'count2')
    step1, step2 = _number(params, 'spacing1'), _number(params, 'spacing2')
    moves = [_translation(first * step1 * i + second * step2 * j) for j in range(count2) for i in range(count1) if i or j]
    return _replicate(body, seeds, moves)


def pattern_circular(body, params, ctx):
    seeds = _seeds(body, params, ctx)
    origin, direction = _axis(ctx, params.get('axis', 'Z'))
    count, total = _count(params, 'count'), _number(params, 'angle')
    if count < 2:
        return body
    step = total / count if abs(abs(total) - 360.0) < 1e-9 else total / (count - 1)
    moves = []
    for index in range(1, count):
        turn = gp_Trsf()
        turn.SetRotation(gp_Ax1(_pnt(origin), _dir(direction)), math.radians(step * index))
        moves.append(turn)
    return _replicate(body, seeds, moves)


def mirror(body, params, ctx):
    seeds = _seeds(body, params, ctx)
    origin, _, _, normal = _frame(ctx, params.get('plane', 'YZ'), float(params.get('offset', 0.0)))
    flip = gp_Trsf()
    flip.SetMirror(gp_Ax2(_pnt(origin), _dir(normal)))
    return _replicate(body, seeds, [flip])


def pattern_curve(body, params, ctx):
    seeds = _seeds(body, params, ctx)
    adaptor = BRepAdaptor_CompCurve(_path(ctx, params.get('path')))
    count, spacing = _count(params, 'count'), _number(params, 'spacing', least=0.0)
    total = GCPnts_AbscissaPoint.Length_s(adaptor)
    closed = adaptor.Value(adaptor.FirstParameter()).Distance(adaptor.Value(adaptor.LastParameter())) < 1e-6
    if spacing <= 0:
        spacing = total / (count if closed else max(count - 1, 1))
    if spacing * (count - 1) > total + 1e-6:
        raise FeatureError(f'路径不够长：全长 {total:.4g} mm，放不下 {count} 个间距 {spacing:.4g} mm 的实例')

    def at(distance):
        parameter = GCPnts_AbscissaPoint(adaptor, distance, adaptor.FirstParameter()).Parameter()
        point, tangent = gp_Pnt(), gp_Vec()
        adaptor.D1(parameter, point, tangent)
        return point, tangent

    start, heading = at(0.0)
    moves = []
    for index in range(1, count):
        point, tangent = at(min(spacing * index, total))
        move = _translation(_xyz(point) - _xyz(start))
        if params.get('align') and heading.Magnitude() > 1e-9 and tangent.Magnitude() > 1e-9:
            pivot = heading.Crossed(tangent)
            if pivot.Magnitude() > 1e-9:
                turn = gp_Trsf()
                turn.SetRotation(gp_Ax1(start, gp_Dir(pivot)), heading.Angle(tangent))
                move = move.Multiplied(turn)
        moves.append(move)
    return _replicate(body, seeds, moves)


def _to_spots(body, seeds, spots, normal=None):
    """把对象的质心挪到每个位置上 (normal: 只在垂直于它的平面里挪)。"""
    centre = _centroid(seeds[0][0])
    moves = []
    for spot in spots:
        shift = np.asarray(spot, dtype=float) - centre
        if normal is not None:
            shift = shift - normal * float(np.dot(shift, normal))
        if np.linalg.norm(shift) > 1e-9:
            moves.append(_translation(shift))
    return _replicate(body, seeds, moves)


def pattern_sketch(body, params, ctx):
    sketch = _sketch(ctx, params)
    return _to_spots(body, _seeds(body, params, ctx), _spots(sketch), sketch.frame[3])


def pattern_table(body, params, ctx):
    seeds = _seeds(body, params, ctx)
    centre = _centroid(seeds[0][0])
    rows = params.get('points') or []
    if not rows:
        raise FeatureError('坐标表是空的')
    return _to_spots(body, seeds, [list(row[:2]) + [row[2] if len(row) > 2 else centre[2]] for row in rows])


def pattern_fill(body, params, ctx):
    _need_body(body, '填充阵列')
    sketch = _profile(ctx, params)
    spacing, margin = _number(params, 'spacing', positive=True), _number(params, 'margin', least=0.0)
    loops, _ = sketchgeom.loops(sketch.shapes)
    ring = max((sketchgeom.loop_ring(loop) for loop in loops), key=lambda item: abs(sketchgeom.signed_area(item)))
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    centre = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    half = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / 2 + spacing
    turn = math.radians(float(params.get('angle', 0.0)))
    cos, sin = math.cos(turn), math.sin(turn)
    hexagonal = params.get('layout') == 'hex'
    row_step = spacing * (math.sqrt(3) / 2 if hexagonal else 1.0)
    rows, spots = int(half / row_step) + 1, []
    if (2 * rows + 1) * (2 * int(half / spacing) + 3) > 20000:
        raise FeatureError('间距相对边界太小，实例太多')
    for row in range(-rows, rows + 1):
        shift = spacing / 2 if hexagonal and row % 2 else 0.0
        for column in range(-int(half / spacing) - 1, int(half / spacing) + 2):
            x, y = column * spacing + shift, row * row_step
            point = (centre[0] + x * cos - y * sin, centre[1] + x * sin + y * cos)
            if sketchgeom.contains(ring, point) and \
                    min(sketchgeom.dist(point, sketchgeom._nearest_on_segment(point, a, b)) for a, b in zip(ring, ring[1:] + ring[:1])) >= margin:
                spots.append(point)
    if not spots:
        raise FeatureError('边界里一个实例也放不下：间距或离边界的距离太大')
    origin, x_dir, y_dir, normal = sketch.frame
    world = [origin + x_dir * x + y_dir * y for x, y in spots]
    if params.get('features'):
        return _to_spots(body, _seeds(body, params, ctx), world, normal)
    diameter, reach = _number(params, 'diameter', positive=True), _reach(body)
    holes = [BRepPrimAPI_MakeCylinder(gp_Ax2(_pnt(spot - normal * reach), _dir(normal)), diameter / 2, reach * 2).Shape() for spot in world]
    return build.combine(body, build._compound(holes), 'cut', '填充阵列')


def pattern_variable(body, params, ctx):
    seeds = _seeds(body, params, ctx, need=True)
    rows = [row.strip() for row in str(params.get('rows', '')).replace('；', ';').replace('\n', ';').split(';') if row.strip()]
    if not rows:
        raise FeatureError('实例表是空的：每行写 "dx,dy,dz,参数=值,…"，行之间用分号')
    for row in rows:
        parts = [part.strip() for part in row.replace('，', ',').split(',') if part.strip()]
        try:
            shift = [float(part) for part in parts if '=' not in part]
            changes = {part.split('=')[0].strip(): float(part.split('=')[1]) for part in parts if '=' in part}
        except ValueError:
            raise FeatureError(f'实例表这一行看不懂: {row!r}') from None
        if len(shift) != 3:
            raise FeatureError(f'实例表每行开头要有 dx,dy,dz 三个数: {row!r}')
        for _, op, feature in seeds:
            if feature['type'] in MODIFIERS:
                raise FeatureError(f'{feature["name"]} 是阵列 / 镜像，变量阵列只能放造型特征（要按参数重做一遍）')
            unknown = [key for key in changes if key not in feature['params']]
            if unknown:
                raise FeatureError(f'{feature["name"]} 没有参数 {", ".join(unknown)}；它有: {", ".join(feature["params"])}')
            solid = ctx.make(feature['type'], dict(feature['params'], **changes), body)
            body = build.combine(body, _moved(solid, _translation(shift)), op, '变量阵列')
    return body


MODIFIERS = {'thread': thread, 'rib': rib, 'draft': draft, 'shell': shell, 'wrap': wrap, 'split': split,
             'pattern_linear': pattern_linear, 'pattern_circular': pattern_circular, 'mirror': mirror,
             'pattern_curve': pattern_curve, 'pattern_sketch': pattern_sketch, 'pattern_table': pattern_table,
             'pattern_fill': pattern_fill, 'pattern_variable': pattern_variable}
