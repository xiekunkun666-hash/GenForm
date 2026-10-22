"""参考几何体: 基准轴 / 点 / 坐标系, 只出显示用的线。"""
from __future__ import annotations

import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge

from ..build import FeatureError
from .. import build
from ... import features as table
from .helpers import _axis, _centroid, _frame, _need_body, _pnt


# ---------------------------------------------------------------------------
# 参考几何体: 只出显示用的线
# ---------------------------------------------------------------------------
def _segments(pairs):
    return build._compound([BRepBuilderAPI_MakeEdge(_pnt(a), _pnt(b)).Edge() for a, b in pairs])


def _cross(centre, size):
    return [(centre - axis * size, centre + axis * size) for axis in np.eye(3)]


def reference(kind, body, params, ctx, identifier):
    scale = build._model_size(body) if not build._is_empty(body) else 100.0
    if kind == 'plane':
        origin, x_dir, y_dir, _ = _frame(ctx, identifier)
        half = max(scale * 0.4, 20.0)
        corners = [origin + x_dir * a * half + y_dir * b * half for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        return _segments(zip(corners, corners[1:] + corners[:1]))
    if kind == 'axis':
        origin, direction = _axis(ctx, identifier)
        return _segments([(origin - direction * scale * 0.6, origin + direction * scale * 0.6)])
    if kind == 'csys':
        try:
            origin, matrix = table.csys_axes(params)
        except (KeyError, IndexError, ValueError):
            raise FeatureError('坐标系的原点要写成 [[x, y, z]]') from None
        size = max(scale * 0.15, 8.0)
        return _segments([(origin, origin + matrix[:, index] * size * (1.0, 0.75, 0.5)[index]) for index in range(3)])
    if kind == 'point':
        try:
            spot = np.asarray(params['position'][0], dtype=float)
        except (KeyError, IndexError, ValueError):
            raise FeatureError('点的坐标要写成 [[x, y, z]]') from None
        return _segments(_cross(spot, max(scale * 0.02, 1.5)))
    _need_body(body, '算这个')
    if kind == 'com':
        centre = _centroid(body)
        ctx.info[identifier] = f'质心 ({centre[0]:.4g}, {centre[1]:.4g}, {centre[2]:.4g})'
        return _segments(_cross(centre, max(scale * 0.05, 3.0)))
    low, high = (np.array(corner) for corner in build.bounds(body))
    ctx.info[identifier] = '边界框 {:.4g} × {:.4g} × {:.4g} mm'.format(*(high - low))
    pairs = []
    for axis in range(3):
        for a in (low, high):
            for b in (low, high):
                start = np.array([a[i] if i == (axis + 1) % 3 else b[i] if i == (axis + 2) % 3 else low[i] for i in range(3)])
                end = start.copy()
                end[axis] = high[axis]
                pairs.append((start, end))
    return _segments(pairs)


REFERENCES = ('plane', 'axis', 'csys', 'point', 'com', 'bbox', 'variables')     # variables: 全局变量, 重算时单独处理, 不出几何
