# -*- coding: utf-8 -*-
"""工程图的投影 (只读): 把一个零件朝几个方向投到平面上, 看得见的线和被挡住的线分开给。

视图是第一角画法 (国标): 主视图从前往后看, 俯视图从上往下看、摆在主视图下面, 左视图从左往右看、摆在主视图右边。
各视图的平面坐标 (x 向右, y 向上, 单位 mm, 都是零件自己的尺寸, 没乘比例):
    front 主视图  x = 零件的 X,  y = Z          top 俯视图  x = X,  y = Y
    left  左视图  x = -Y,        y = Z          iso 轴测图  从右前上方看

零件面很多时 (FACE_LIMIT 以上) 改用网格来消隐: 精确算法要几分钟, 网格的几秒, 代价是曲面的轮廓线是折线、认不出圆。
"""
from __future__ import annotations

import math

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepLib import BRepLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Bnd import Bnd_Box
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape, HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from . import build
from .occ_compat import _as_edge

_S = math.sqrt(0.5)
FRAMES = {                                  # 视图 → (屏幕 x 方向, 屏幕 y 方向); 人站在 x × y 那一边往回看
    'front': ((1, 0, 0), (0, 0, 1)),
    'top': ((1, 0, 0), (0, 1, 0)),
    'left': ((0, -1, 0), (0, 0, 1)),
    'iso': ((_S, _S, 0), (-1 / math.sqrt(6), 1 / math.sqrt(6), 2 / math.sqrt(6))),
}
FACE_LIMIT = 900                            # 面比这多: 用网格消隐
CURVE_SEGMENTS = 48                         # 一条曲线折成多少段
FULL_TURN = 2 * math.pi - 1e-6


def _polylines(shape, circles=None):
    """投影出来的一堆边 → 折线 [[(x, y)...]...]; circles 给了就顺手把里面的圆和圆弧记进去 (圆心 x, y, 半径, 是不是整圆)。"""
    lines = []
    if shape is None or shape.IsNull():
        return lines
    BRepLib.BuildCurves3d_s(shape)
    mapping = build._indexed(shape, TopAbs_EDGE)
    for index in range(1, mapping.Extent() + 1):
        edge = _as_edge(mapping.FindKey(index))
        if BRep_Tool.Degenerated_s(edge):
            continue
        try:
            curve = BRepAdaptor_Curve(edge)
        except Exception:
            continue
        first, last = curve.FirstParameter(), curve.LastParameter()
        if not (math.isfinite(first) and math.isfinite(last)) or last - first < 1e-12:
            continue
        kind = curve.GetType()
        if kind == GeomAbs_Circle and circles is not None:
            circle = curve.Circle()
            center = circle.Location()
            circles.append((float(center.X()), float(center.Y()), float(circle.Radius()), bool(last - first >= FULL_TURN)))
        count = 1 if kind == GeomAbs_Line else CURVE_SEGMENTS
        points = []
        for step in range(count + 1):
            point = curve.Value(first + (last - first) * step / count)
            points.append((round(float(point.X()), 5), round(float(point.Y()), 5)))
        lines.append(points)
    return lines


def _project(shape, frame, exact, hidden):
    x_dir, y_dir = (np.asarray(vector, dtype=float) for vector in frame)
    normal = np.cross(x_dir, y_dir)
    projector = HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*normal.tolist()), gp_Dir(*x_dir.tolist())))
    circles = []
    if exact:
        algo = HLRBRep_Algo()
        algo.Add(shape)
        algo.Projector(projector)
        algo.Update()
        algo.Hide()
        out = HLRBRep_HLRToShape(algo)
        visible = _polylines(out.VCompound(), circles) + _polylines(out.OutLineVCompound())
        covered = (_polylines(out.HCompound()) + _polylines(out.OutLineHCompound())) if hidden else []
    else:
        algo = HLRBRep_PolyAlgo()
        algo.Load(shape)
        algo.Projector(projector)
        algo.Update()
        out = HLRBRep_PolyHLRToShape()
        out.Update(algo)
        visible = _polylines(out.VCompound()) + _polylines(out.OutLineVCompound())
        covered = (_polylines(out.HCompound()) + _polylines(out.OutLineHCompound())) if hidden else []
    return visible, covered, circles


def _unique(circles):
    """同一个圆的两半、同一根轴上前后两个一样大的圆: 只留一个。整圆优先。"""
    kept = {}
    for x, y, radius, full in circles:
        key = (round(x, 3), round(y, 3), round(radius, 3))
        kept[key] = kept.get(key, False) or full
    return [[x, y, radius, full] for (x, y, radius), full in kept.items()]


def views(features, upto, data):
    """data: {'part': 零件 (写法同 assembly: 有 path 读文件, 没有 = 现在打开的零件), 'views': [视图名...], 'hidden': 要不要被挡住的线}
    → {'size': [长, 宽, 高], 'exact': 是不是精确算的, 'views': {名: {'visible', 'hidden', 'circles', 'box': [x0, y0, x1, y1]}}}"""
    from . import assembly
    shape = assembly._load(data.get('part') or {}, features, upto)
    faces = build._indexed(shape, TopAbs_FACE).Extent()
    exact = faces <= FACE_LIMIT
    if not exact:
        BRepMesh_IncrementalMesh(shape, build.LINEAR_DEFLECTION, False, build.ANGULAR_DEFLECTION, True)
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False) if exact else BRepBndLib.Add_s(shape, box)
    low, high = box.CornerMin(), box.CornerMax()            # box.Get() 在 OCP 8 里返回不了 Python 值
    result = {'size': [high.X() - low.X(), high.Y() - low.Y(), high.Z() - low.Z()], 'exact': exact, 'faces': faces, 'views': {}}
    for name in data.get('views') or ('front', 'top', 'left'):
        if name not in FRAMES:
            raise build.FeatureError(f'不认识的视图 {name!r}')
        visible, covered, circles = _project(shape, FRAMES[name], exact, bool(data.get('hidden', True)) and name != 'iso')
        points = [point for line in visible for point in line]
        if not points:
            raise build.FeatureError('投影出来是空的')
        array = np.asarray(points)
        low, high = array.min(axis=0), array.max(axis=0)
        result['views'][name] = {'visible': visible, 'hidden': covered, 'circles': _unique(circles),
                                 'box': [float(low[0]), float(low[1]), float(high[0]), float(high[1])]}
    return result
