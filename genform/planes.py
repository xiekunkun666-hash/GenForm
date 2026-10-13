# -*- coding: utf-8 -*-
"""三个基准面的定义 (内核、草图编辑、三维视图共用; 只依赖 numpy)。

名称 → (平面内的 X 方向, 平面内的 Y 方向); 法向 = X × Y。和常见 CAD 的上视 / 前视 / 右视一致:
前视基准面的法向是 -Y, 朝着看图的人。
"""
import numpy as np

PLANES = {
    'XY': ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    'XZ': ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    'YZ': ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}
NAMES = {'XY': '上视基准面', 'XZ': '前视基准面', 'YZ': '右视基准面'}
SHORT = {'XY': '上视', 'XZ': '前视', 'YZ': '右视'}
VIEW = {'XY': 'top', 'XZ': 'front', 'YZ': 'right'}       # 正对这个基准面的视角


def frame(plane='XY', offset=0.0):
    """→ (原点, X 方向, Y 方向, 法向), numpy 向量。plane 是三个基准面的名称 (不认识时抛 KeyError),
    或者一个现成的坐标系 {'origin', 'x', 'y'} (基准面特征算出来的, 见 features.plane_frame)。"""
    if isinstance(plane, dict):
        base = np.array(plane['origin'], dtype=float)
        x_dir, y_dir = np.array(plane['x'], dtype=float), np.array(plane['y'], dtype=float)
    else:
        base = np.zeros(3)
        x_dir, y_dir = (np.array(v) for v in PLANES[str(plane).upper()])
    normal = np.cross(x_dir, y_dir)
    return base + normal * float(offset), x_dir, y_dir, normal


def to_world(points, plane='XY', offset=0.0):
    """平面内的二维点 (N,2) → 三维点 (N,3)。"""
    origin, x_dir, y_dir, _ = frame(plane, offset)
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    return origin + points[:, :1] * x_dir + points[:, 1:] * y_dir


def from_ray(origin, direction, plane='XY', offset=0.0):
    """射线和基准面的交点 → 平面内的 (x, y); 射线平行于平面或交点在身后返回 None。"""
    base, x_dir, y_dir, normal = frame(plane, offset)
    slope = float(np.dot(direction, normal))
    if abs(slope) < 1e-9:
        return None
    reach = float(np.dot(base - origin, normal)) / slope
    if reach <= 0:
        return None
    hit = np.asarray(origin, dtype=float) + np.asarray(direction, dtype=float) * reach - base
    return float(hit @ x_dir), float(hit @ y_dir)
