"""扫描自己的几何前置条件和工具体验证, 不遍历已有零件。"""
from __future__ import annotations

import math
import numpy as np
from OCP.BRep import BRep_Tool
from OCP.gp import gp_Pnt, gp_Vec

from ..build import FeatureError
from .solid_validation import checked_tool_solid


def check_closed_sweep_profile(spine, adaptor, sketch):
    if not BRep_Tool.IsClosed_s(spine):
        return
    spot, derivative = gp_Pnt(), gp_Vec()
    try:
        adaptor.D1(adaptor.FirstParameter(), spot, derivative)
    except Exception:
        raise FeatureError('闭合路径扫描失败：起点没有确定的切向，请调整路径起点') from None
    tangent = np.array([derivative.X(), derivative.Y(), derivative.Z()])
    magnitude = float(np.linalg.norm(tangent))
    if not math.isfinite(magnitude) or magnitude < 1e-12:
        raise FeatureError('闭合路径扫描失败：起点没有确定的切向，请调整路径起点')
    tangent /= magnitude
    normal = np.asarray(sketch.frame[3], dtype=float)
    deviation = float(np.linalg.norm(np.cross(normal, tangent)))
    if not math.isfinite(deviation) or deviation > 1e-4:
        cosine = float(np.clip(abs(normal @ tangent), 0.0, 1.0))
        direction = ', '.join(f'{value:.9g}' for value in tangent)
        raise FeatureError(
            f'闭合路径扫描的截面必须垂直于起点的实际切向（当前偏差 {math.degrees(math.acos(cosine)):.3g}°）；'
            f'请把截面基准面的 normal 设为 [[{direction}]] 或其反向，'
            '不要用相邻采样点的差代替样条切向')
    start = np.array([spot.X(), spot.Y(), spot.Z()])
    if abs(float((start - sketch.frame[0]) @ normal)) > 1e-6:
        raise FeatureError('闭合路径扫描的截面平面必须经过路径起点：请把截面基准面移到路径起点并将草图偏移设为 0')


def checked_sweep_solid(shape):
    return checked_tool_solid(shape, '扫描')
