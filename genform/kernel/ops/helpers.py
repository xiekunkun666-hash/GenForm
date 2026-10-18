"""特征共用的小工具: 点 / 方向 / 向量、取数、遍历子形状、体积重心、草图轮廓 / 路径 / 轴、跑一个 OCC 操作。"""
from __future__ import annotations

import math
import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.GeomAPI import GeomAPI_Interpolate
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.gp import gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from ..build import FeatureError
from ..occ_compat import _as_face, _PointHandleArray, _ShapeList
from .. import build
from ... import features as table, planes


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _pnt(point):
    return gp_Pnt(float(point[0]), float(point[1]), float(point[2]))


def _dir(vector):
    return gp_Dir(float(vector[0]), float(vector[1]), float(vector[2]))


def _vec(vector):
    return gp_Vec(float(vector[0]), float(vector[1]), float(vector[2]))


def _xyz(point):
    return np.array([point.X(), point.Y(), point.Z()])


def _number(params, key, positive=False, least=None):
    try:
        value = float(params.get(key))
    except (TypeError, ValueError):
        raise FeatureError(f'参数 {key} 不是数字') from None
    if not math.isfinite(value) or (positive and value <= 0) or (least is not None and value < least):
        raise FeatureError(f'参数 {key} 必须{"是正数" if positive else f"不小于 {least:g}"}，现在是 {value:g}')
    return value


def _shape_list(shapes):
    items = _ShapeList()
    for shape in shapes:
        items.Append(shape)
    return items


def _explore(shape, kind):
    found, explorer = [], TopExp_Explorer(shape, kind)
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def _moved(shape, transform):
    return BRepBuilderAPI_Transform(shape, transform, True).Shape()


def _translation(vector):
    transform = gp_Trsf()
    transform.SetTranslation(_vec(vector))
    return transform


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props


def _centroid(shape):
    return _xyz(_volume(shape).CentreOfMass())


def _reach(body):
    """足够长的一段: 比实体的对角线长, 用来做 "贯穿"。"""
    return (build._model_size(body) if not build._is_empty(body) else 100.0) * 2 + 10.0


def _need_body(body, what):
    if build._is_empty(body):
        raise FeatureError(f'还没有实体，无法{what}')


def _sketch(ctx, params, key='sketch'):
    identifier = params.get(key)
    if identifier not in ctx.sketches:
        raise FeatureError(f'找不到草图 {identifier!r}（可能被删除、抑制或出错了；参数 {key} 要写草图特征的 id）')
    return ctx.sketches[identifier]


def _profile(ctx, params, key='sketch'):
    sketch = _sketch(ctx, params, key)
    if sketch.profile is None:
        raise FeatureError('这个草图里没有封闭轮廓：线要首尾相接围成一圈（草图页的“修复草图”能找出没接上的地方）')
    return sketch


def _wire(edges, what='路径'):
    maker = BRepBuilderAPI_MakeWire()
    maker.Add(_shape_list(edges))
    if not edges or not maker.IsDone():
        raise FeatureError(f'{what}的线要首尾相接连成一条（不能断开或分叉）')
    return maker.Wire()


def _path(ctx, identifier, what='路径'):
    if identifier in ctx.curves:
        return ctx.curves[identifier]
    if identifier in ctx.sketches:
        return _wire(_explore(ctx.sketches[identifier].curves, TopAbs_EDGE), what)
    raise FeatureError(f'找不到{what} {identifier!r}（要写草图或曲线特征的 id）')


def _axis(ctx, ref, sketch_frame=None):
    try:
        return table.axis_of(ref, ctx.features, sketch_frame)
    except ValueError as error:
        raise FeatureError(str(error)) from None


def _frame(ctx, ref, offset=0.0):
    try:
        return planes.frame(table.plane_frame(ref, ctx.features), offset)
    except ValueError as error:
        raise FeatureError(str(error)) from None


def _spots(sketch):
    """草图里的点和圆心 → 三维坐标。"""
    origin, x_dir, y_dir, _ = sketch.frame
    found = []
    for shape in sketch.shapes:
        if shape.get('type') == 'point':
            found.append(origin + x_dir * float(shape['x']) + y_dir * float(shape['y']))
        elif shape.get('type') in ('circle', 'arc'):
            found.append(origin + x_dir * float(shape.get('cx', 0.0)) + y_dir * float(shape.get('cy', 0.0)))
    if not found:
        raise FeatureError('位置草图里没有点：用草图页的“点”工具放几个点（圆的圆心也算）')
    return found


def _faces(body, refs, what, count=None):
    """特征里写的面引用 [{'point': 面中心}...] → 实体上的面。"""
    mapping = build._indexed(body, TopAbs_FACE)
    centres, faces = [], []
    for index in range(1, mapping.Extent() + 1):
        face = _as_face(mapping.FindKey(index))
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        centres.append(_xyz(props.CentreOfMass()))
        faces.append(face)
    chosen = []
    for ref in refs or ():
        point = ref.get('point') if isinstance(ref, dict) else None
        if point is None or len(point) != 3:
            raise FeatureError('面的引用要写成 {"point": [x, y, z]}（面中心坐标，用 list_faces 查）')
        gaps = np.linalg.norm(np.array(centres) - np.array(point, dtype=float), axis=1)
        nearest = int(gaps.argmin())
        if gaps[nearest] > 0.25 * build._model_size(body):
            raise FeatureError('引用的面找不到了（前面的特征改动后这个面可能已经消失），请重新选择面')
        if not any(faces[nearest].IsSame(face) for face in chosen):
            chosen.append(faces[nearest])
    if count is not None and len(chosen) != count:
        raise FeatureError(f'{what}要正好选 {count} 个面，现在是 {len(chosen)} 个')
    return chosen


def _spline(points, closed=False):
    if len(points) < 2:
        raise FeatureError('曲线至少要 2 个点')
    array = _PointHandleArray(1, len(points))
    for index, point in enumerate(points):
        array.SetValue(index + 1, _pnt(point))
    maker = GeomAPI_Interpolate(array, bool(closed), 1e-6)
    maker.Perform()
    if not maker.IsDone():
        raise FeatureError('这些点连不成光顺的曲线（有重合的点？）')
    return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(maker.Curve()).Edge()).Wire()


def _run(maker, what):
    """跑一个 OpenCascade 的造型算法; 它做不出来时给一句人话。"""
    try:
        maker.Build()
        shape = maker.Shape() if maker.IsDone() else None
    except Exception:
        shape = None
    if shape is None or shape.IsNull():
        raise FeatureError(what)
    return shape
