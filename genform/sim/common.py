"""仿真共用的表 (模式、轴、网格质量、零件颜色) 和应力云图的色带。"""
from __future__ import annotations

import numpy as np


MODES = ('static', 'drag', 'assembly')


AXES = {'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}


QUALITIES = [('coarse', '粗'), ('medium', '中'), ('fine', '细')]


PART_COLORS = [(0.37, 0.76, 0.54), (0.91, 0.54, 0.24), (0.71, 0.52, 0.88), (0.89, 0.71, 0.24), (0.21, 0.65, 0.63),
               (0.88, 0.38, 0.35), (0.55, 0.60, 0.66)]


_RAMP = np.array([(0.13, 0.30, 0.85), (0.10, 0.75, 0.90), (0.20, 0.80, 0.30), (0.95, 0.85, 0.15), (0.90, 0.15, 0.12)],
                 dtype=np.float32)     # 应力从小到大: 蓝 青 绿 黄 红


def ramp(values, top):
    """一组数 → 云图的颜色 (N,3): 0 是蓝, top 及以上是红。"""
    level = np.clip(np.asarray(values, dtype=np.float32) / max(float(top), 1e-12), 0.0, 1.0) * (len(_RAMP) - 1)
    lower = np.minimum(level.astype(np.int32), len(_RAMP) - 2)
    part = (level - lower)[:, None]
    return _RAMP[lower] * (1 - part) + _RAMP[lower + 1] * part


def number(value, unit=''):
    """给人看的数: 四位有效数字, 太大太小的用科学计数。"""
    value = float(value)
    if 1e4 <= abs(value) < 1e9:
        text = f'{value:.0f}'
    else:
        text = f'{value:.4g}' if 1e-3 <= abs(value) < 1e4 or value == 0 else f'{value:.3e}'
    return f'{text} {unit}' if unit else text
