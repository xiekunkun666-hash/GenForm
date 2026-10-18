# -*- coding: utf-8 -*-
"""测量: 一个或两个对象 (面 / 边 / 顶点) → 尺寸、最短距离、夹角、中心距。只读, 不改文档。

对象的写法: {'kind': 'face' | 'edge' | 'vertex', 'id': 序号} (序号和显示模型里的一致)。
"""
from __future__ import annotations

import math

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import (GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane, GeomAbs_Sphere,
                         GeomAbs_Torus)
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_VERTEX
from OCP.TopoDS import TopoDS

from . import build
from .occ_compat import _as_edge, _as_face

_as_vertex = getattr(TopoDS, 'Vertex_s', None) or TopoDS.Vertex
_KINDS = {'face': TopAbs_FACE, 'edge': TopAbs_EDGE, 'vertex': TopAbs_VERTEX}


def _xyz(point):
    return [float(point.X()), float(point.Y()), float(point.Z())]


def vertices(shape):
    """实体的顶点坐标 (N,3): 序号就是测量时用的顶点 id。"""
    mapping = build._indexed(shape, TopAbs_VERTEX)
    points = [_xyz(BRep_Tool.Pnt_s(_as_vertex(mapping.FindKey(index)))) for index in range(1, mapping.Extent() + 1)]
    return np.array(points, dtype=np.float32).reshape(-1, 3)


def _describe(kind, shape):
    """一个对象自己的尺寸, 以及算夹角 / 中心距要用的方向和中心。"""
    info = {'kind': kind}
    if kind == 'vertex':
        info.update(type='vertex', point=_xyz(BRep_Tool.Pnt_s(_as_vertex(shape))))
    elif kind == 'edge':
        curve = BRepAdaptor_Curve(_as_edge(shape))
        info.update(type='curve', length=float(GCPnts_AbscissaPoint.Length_s(curve)))
        if curve.GetType() == GeomAbs_Line:
            direction = curve.Line().Direction()
            info.update(type='line', dir=_xyz(direction))
        elif curve.GetType() == GeomAbs_Circle:
            circle = curve.Circle()
            info.update(type='circle', radius=float(circle.Radius()), center=_xyz(circle.Location()),
                        axis=_xyz(circle.Axis().Direction()))
    else:
        face = _as_face(shape)
        surface = BRepAdaptor_Surface(face)
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        info.update(type='surface', area=float(props.Mass()))
        kind_of = surface.GetType()
        if kind_of == GeomAbs_Plane:
            plane = surface.Plane()
            sign = -1.0 if face.Orientation() == TopAbs_REVERSED else 1.0
            info.update(type='plane', normal=[sign * value for value in _xyz(plane.Axis().Direction())],
                        point=_xyz(plane.Location()))
        elif kind_of == GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            info.update(type='cylinder', radius=float(cylinder.Radius()), axis=_xyz(cylinder.Axis().Direction()),
                        axis_point=_xyz(cylinder.Location()))
        elif kind_of == GeomAbs_Cone:
            cone = surface.Cone()
            info.update(type='cone', axis=_xyz(cone.Axis().Direction()), axis_point=_xyz(cone.Location()),
                        half_angle=abs(math.degrees(cone.SemiAngle())))
        elif kind_of == GeomAbs_Sphere:
            sphere = surface.Sphere()
            info.update(type='sphere', radius=float(sphere.Radius()), center=_xyz(sphere.Location()))
        elif kind_of == GeomAbs_Torus:
            info.update(type='torus')
    return info


def _angle(first, second):
    """两个对象的夹角 (度, 0~90); 说不上夹角的 (曲面、点) 返回 None。"""
    def direction(info):
        if 'normal' in info:
            return 'normal', np.array(info['normal'])
        if 'dir' in info:
            return 'line', np.array(info['dir'])
        if 'axis' in info and info['type'] in ('cylinder', 'cone'):
            return 'line', np.array(info['axis'])
        if 'axis' in info:                              # 圆: 它所在平面的法向
            return 'normal', np.array(info['axis'])
        return None, None

    kind_a, a = direction(first)
    kind_b, b = direction(second)
    if a is None or b is None:
        return None
    between = math.degrees(math.acos(min(1.0, abs(float(a @ b)))))
    return between if kind_a == kind_b else 90.0 - between         # 线和面: 线与面的夹角 = 90° - 线与法向的夹角


def _center_distance(first, second):
    """圆 / 圆柱 / 球之间的中心距 (圆柱按轴线算); 不是这几种的返回 None。"""
    def centre(info):
        if 'center' in info:
            return 'point', np.array(info['center']), None
        if 'axis_point' in info:
            return 'line', np.array(info['axis_point']), np.array(info['axis'])
        return None, None, None

    kind_a, a, dir_a = centre(first)
    kind_b, b, dir_b = centre(second)
    if kind_a is None or kind_b is None:
        return None
    if kind_a == 'point' and kind_b == 'point':
        return float(np.linalg.norm(a - b))
    if kind_a == 'line' and kind_b == 'line':
        cross = np.cross(dir_a, dir_b)
        if np.linalg.norm(cross) < 1e-9:                # 平行的两根轴: 轴间距
            return float(np.linalg.norm(np.cross(b - a, dir_a)))
        return float(abs((b - a) @ cross) / np.linalg.norm(cross))
    point, base, along = (a, b, dir_b) if kind_a == 'point' else (b, a, dir_a)
    return float(np.linalg.norm(np.cross(point - base, along)))


def measure(features, upto, items):
    """→ {'items': [每个对象自己的信息...], 两个对象时另有 'distance' 最短距离, 'points' 最近的两点,
          'delta' 这两点在 X / Y / Z 上各差多少, 'angle', 'center_distance', 'normal_distance' (两个平行平面的间距)}。"""
    body, _, _ = build.rebuild(features, upto)
    if build._is_empty(body):
        raise build.FeatureError('还没有实体')
    maps = {kind: build._indexed(body, code) for kind, code in _KINDS.items()}
    shapes, infos = [], []
    for item in list(items)[:2]:
        kind, number = item.get('kind'), int(item.get('id', -1)) + 1
        if kind not in maps or not 1 <= number <= maps[kind].Extent():
            raise build.FeatureError('要测量的对象已经不在了（模型变了），请重新选')
        shape = maps[kind].FindKey(number)
        shapes.append(shape)
        infos.append(dict(_describe(kind, shape), id=number - 1))
    result = {'items': infos}
    if len(shapes) == 2:
        extrema = BRepExtrema_DistShapeShape(shapes[0], shapes[1])
        if not extrema.IsDone() or extrema.NbSolution() < 1:
            raise build.FeatureError('这两个对象之间的距离没有算出来')
        first, second = _xyz(extrema.PointOnShape1(1)), _xyz(extrema.PointOnShape2(1))
        result.update(distance=float(extrema.Value()), points=[first, second],
                      delta=[abs(b - a) for a, b in zip(first, second)])
        angle = _angle(infos[0], infos[1])
        if angle is not None:
            result['angle'] = angle
        centre = _center_distance(infos[0], infos[1])
        if centre is not None:
            result['center_distance'] = centre
        if infos[0]['type'] == 'plane' and infos[1]['type'] == 'plane' and angle is not None and angle < 1e-6:
            normal = np.array(infos[0]['normal'])
            result['normal_distance'] = float(abs((np.array(infos[1]['point']) - np.array(infos[0]['point'])) @ normal))
    return result
