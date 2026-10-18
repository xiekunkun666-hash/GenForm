"""曲线特征: 螺旋线、3D 草图、曲面上的曲线、过 XYZ 点、投影、组合。"""
from __future__ import annotations

import math
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeWire
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_EDGE, TopAbs_WIRE

from ..build import FeatureError
from ..occ_compat import _as_wire
from .. import build
from .helpers import _dir, _explore, _faces, _need_body, _number, _path, _pnt, _sketch, _spline, _wire


# ---------------------------------------------------------------------------
# 曲线
# ---------------------------------------------------------------------------
def curve_helix(body, params, ctx, identifier):
    sketch = _sketch(ctx, params)
    circle = next((shape for shape in sketch.shapes if shape.get('type') == 'circle'), None)
    if circle is None:
        raise FeatureError('螺旋线的草图里要有一个圆（它定出起始直径和位置）')
    origin, x_dir, y_dir, normal = sketch.frame
    centre = origin + x_dir * float(circle.get('cx', 0.0)) + y_dir * float(circle.get('cy', 0.0))
    radius, pitch = float(circle['r']), _number(params, 'pitch', positive=True)
    turns, taper = _number(params, 'turns', positive=True), _number(params, 'taper')
    spiral = params.get('kind') == 'spiral'
    sense = -1.0 if params.get('clockwise') else 1.0
    start = math.radians(float(params.get('start', 0.0)))
    count = max(int(turns * 24), 4)
    if count > 20000:
        raise FeatureError('圈数太多')
    points = []
    for index in range(count + 1):
        turn = turns * index / count
        reach = radius + (pitch if spiral else taper) * turn
        if reach <= 1e-6:
            raise FeatureError('锥度太大：半径缩到 0 了')
        angle = start + sense * math.tau * turn
        points.append(centre + (x_dir * math.cos(angle) + y_dir * math.sin(angle)) * reach + normal * (0.0 if spiral else pitch * turn))
    if not spiral:
        ctx.helix_axis[identifier] = normal
    return _spline(points)


def sketch3d(body, params, ctx, identifier):
    points = [np.array(row, dtype=float) for row in params.get('points') or []]
    closed = bool(params.get('closed'))
    if len(points) < (3 if closed else 2):
        raise FeatureError('3D 草图至少要 2 个点（闭合的要 3 个）')
    if params.get('kind') == 'spline':
        return _spline(points, closed)
    if any(np.linalg.norm(b - a) < 1e-9 for a, b in zip(points, points[1:])):
        raise FeatureError('相邻的两个点重合了')
    maker = BRepBuilderAPI_MakePolygon()
    for point in points:
        maker.Add(_pnt(point))
    if closed:
        maker.Close()
    return maker.Wire()


def curve_surface(body, params, ctx, identifier):
    from OCP.BRepLib import BRepLib
    from OCP.Geom2d import Geom2d_Line, Geom2d_TrimmedCurve
    from OCP.Geom2dAPI import Geom2dAPI_Interpolate
    from OCP.collections import HArray1_gp_Pnt2d
    from OCP.gp import gp_Dir2d, gp_Pnt2d
    _need_body(body, '在面上画样条')
    face = _faces(body, params.get('faces'), '曲面上的样条曲线', count=1)[0]
    adaptor = BRepAdaptor_Surface(face)                     # 这张面在自己曲面上占的那一块 (U, V 范围)
    low_u, high_u, low_v, high_v = (adaptor.FirstUParameter(), adaptor.LastUParameter(),
                                    adaptor.FirstVParameter(), adaptor.LastVParameter())
    rows = params.get('points') or []
    if len(rows) < 2:
        raise FeatureError('面上的样条至少要 2 个点')
    if any(not (0.0 <= float(value) <= 1.0) for row in rows for value in row):
        raise FeatureError('面上的点要写成 U,V，两个数都在 0 到 1 之间（它在这张面上的位置）')
    spots = [gp_Pnt2d(low_u + (high_u - low_u) * float(u), low_v + (high_v - low_v) * float(v)) for u, v in rows]
    if any(a.Distance(b) < 1e-12 for a, b in zip(spots, spots[1:])):
        raise FeatureError('相邻的两个点重合了')
    if len(spots) == 2:
        first, second = spots
        curve = Geom2d_TrimmedCurve(Geom2d_Line(first, gp_Dir2d(second.X() - first.X(), second.Y() - first.Y())),
                                    0.0, first.Distance(second))
    else:
        array = HArray1_gp_Pnt2d(1, len(spots))
        for index, spot in enumerate(spots):
            array.SetValue(index + 1, spot)
        maker = Geom2dAPI_Interpolate(array, False, 1e-9)
        maker.Perform()
        if not maker.IsDone():
            raise FeatureError('这些点连不成光顺的曲线')
        curve = maker.Curve()
    edge = BRepBuilderAPI_MakeEdge(curve, BRep_Tool.Surface_s(face)).Edge()
    BRepLib.BuildCurves3d_s(edge)
    return BRepBuilderAPI_MakeWire(edge).Wire()


def curve_xyz(body, params, ctx, identifier):
    return _spline([row for row in params.get('points') or []])


def curve_points(body, params, ctx, identifier):
    spots = []
    for ref in params.get('points') or []:
        feature = next((item for item in ctx.features if item['id'] == ref and item['type'] == 'point'), None)
        if feature is None:
            raise FeatureError(f'{ref} 不是参考点（要写“点”特征的 id）')
        spots.append(feature['params']['position'][0])
    return _spline(spots, params.get('closed'))


def curve_project(body, params, ctx, identifier):
    from OCP.BRepProj import BRepProj_Projection
    _need_body(body, '投影曲线')
    sketch = _sketch(ctx, params)
    spine = _wire(_explore(sketch.curves, TopAbs_EDGE), '要投影的草图')
    projection = BRepProj_Projection(spine, body, _dir(sketch.frame[3]))
    wires = _explore(projection.Shape(), TopAbs_WIRE) if projection.IsDone() else []
    if not wires:
        raise FeatureError('草图沿法向投不到实体上')
    ctx.display[identifier] = projection.Shape()
    return _as_wire(wires[0])


def curve_composite(body, params, ctx, identifier):
    edges = list(build.resolve_edges(body, params['edges'])) if params.get('edges') else []
    for ref in params.get('curves') or []:
        edges += _explore(_path(ctx, ref, '曲线'), TopAbs_EDGE)
    return _wire(edges, '组合曲线')


CURVES = {'sketch3d': sketch3d, 'curve_surface': curve_surface, 'curve_helix': curve_helix, 'curve_xyz': curve_xyz, 'curve_points': curve_points,
          'curve_project': curve_project, 'curve_composite': curve_composite}
