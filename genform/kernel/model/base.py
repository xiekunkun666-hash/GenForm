"""建模内核共用的: 出错类型、轴、网格化精度和选择容差。"""
from __future__ import annotations



AXES = {'X': (1.0, 0.0, 0.0), 'Y': (0.0, 1.0, 0.0), 'Z': (0.0, 0.0, 1.0)}


LINEAR_DEFLECTION = 0.05        # 网格离真实曲面最多差这么多 (mm): 导出 STL 用它; 显示用的见 display_deflection


DISPLAY_RELATIVE = 1e-4         # 显示网格的精度不细于零件对角线的这么多倍 (5 米的车 ≈ 0.5 mm, 看不出来)


ANGULAR_DEFLECTION = 0.3        # 弧度


CURVE_SEGMENTS = 48             # 一条曲线边画成多少段


SELECT_TOLERANCE = 1e-4         # 选择器里 "同一高度/平行" 的容差 (相对模型尺寸)


def display_deflection(shape):
    """显示网格的精度 (mm): 小零件就是 LINEAR_DEFLECTION; 大零件按尺寸放宽 — 一律 0.05 mm 的话,
    5 米的车身要十几万个三角形, 网格化、传给界面、上传显卡、拾取都慢上十倍, 画出来却看不出差别。"""
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        return LINEAR_DEFLECTION
    low, high = box.CornerMin(), box.CornerMax()
    diagonal = ((high.X() - low.X()) ** 2 + (high.Y() - low.Y()) ** 2 + (high.Z() - low.Z()) ** 2) ** 0.5
    return max(LINEAR_DEFLECTION, diagonal * DISPLAY_RELATIVE)


class FeatureError(Exception):
    """某个特征算不出来; 文字直接给用户和 AI 看。"""
