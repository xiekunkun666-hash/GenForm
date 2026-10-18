"""捕捉: 光标吸到端点 / 中点 / 圆心 / 交点 / 线上 / 水平竖直对齐 / 网格。"""
from __future__ import annotations

from ..sketchgeom import dist as _distance
from .. import sketchgeom as geom
from .common import ALIGN_PIXELS, grid_step, HIT_PIXELS, QUICK_PIXELS, SNAP_ORDER, SNAP_PIXELS, SPLINE_TOOLS


class SnapMixin:
    """捕捉 (草图编辑器的一部分)。"""

    # ---- 捕捉 ----
    def snap(self, point, pixel, skip=(), loose=True):
        """光标位置 → 捕捉后的位置。先吸特征点 (端点、中点、中心点、象限点、交叉点) 和原点, 再吸到线上, 再和已有的点
        对齐成水平 / 竖直, 最后吸格子 — 每一种都可以单独关掉 (self.snaps)。
        skip: 不参与的图形序号 (正在拖的那些); loose=False 时只吸特征点和格子 (拖动图形时用)。"""
        skipped = {skip} if isinstance(skip, int) else set(skip or ())
        only = self.snap_only
        on = {only} if only else self.snaps
        reach = (QUICK_PIXELS if only else SNAP_PIXELS) * pixel
        others = [shape for index, shape in enumerate(self.shapes) if index not in skipped]
        candidates = [('origin', (0.0, 0.0))] if 'end' in on and not only else []
        for shape in others:
            candidates += [item for item in geom.key_points(shape) if item[0] in on]
        if self.draft and self.tool in SPLINE_TOOLS and len(self.draft['points']) >= 3 and 'end' in on:
            candidates.append(('end', self.draft['points'][0]))
        close = [shape for shape in others if shape['type'] not in ('point', 'text') and geom.hit(shape, point, reach)] \
            if loose and ('int' in on or 'near' in on) else []
        if 'int' in on:
            for first in range(len(close)):
                for second in range(first + 1, len(close)):
                    for a in geom.prims(close[first]):
                        for b in geom.prims(close[second]):
                            candidates += [('int', crossing) for crossing in geom.intersections(a, b)]
        if candidates:
            # 两种点落在同一个位置 (比如交点正好在中点上) 时, 报更 "硬" 的那一种
            kind, best = min(candidates, key=lambda item: (round(_distance(item[1], point), 7), SNAP_ORDER.index(item[0])))
            if _distance(best, point) <= reach:
                self.snapped, self.snap_kind = True, kind
                return float(best[0]), float(best[1])
        if close and 'near' in on:
            gap, spot = min((geom.nearest(shape, point) for shape in close), key=lambda item: item[0])
            if gap <= (reach if only else HIT_PIXELS * pixel):
                self.snapped, self.snap_kind = True, 'near'
                return float(spot[0]), float(spot[1])
        self.snapped, self.snap_kind = False, ''
        step = grid_step(pixel)
        x, y = (round(point[0] / step) * step, round(point[1] / step) * step) if 'grid' in on else (float(point[0]), float(point[1]))
        if 'hv' in on and loose and not only:
            # 和已有的点对齐成水平 / 竖直: 只改对齐的那个坐标, 另一个坐标照常走格子。不算 "吸在点上": 半径这类长度还是按格子取整。
            # 正在画的这一串自己的点 (上一个点、起点) 优先; 别的图形只看端点和中心点, 而且要比格子更近才让它赢 —
            # 不然光标明明压在格子上, 却被远处某个点拉走一点点
            own = [self.draft['points'][-1], self.draft['points'][0]] if self.draft and self.draft.get('points') else []
            far = [(0.0, 0.0)] + [spot for shape in others for kind, spot in geom.key_points(shape) if kind in ('end', 'center')]
            tolerance, landed = ALIGN_PIXELS * pixel, [x, y]
            for axis in (0, 1):
                raw = point[axis]
                best = min((spot[axis] for spot in own), key=lambda value: abs(value - raw), default=None)
                if best is None or abs(best - raw) > tolerance:
                    best = min((spot[axis] for spot in far), key=lambda value: abs(value - raw), default=None)
                    if best is None or abs(best - raw) > tolerance or ('grid' in on and abs(best - raw) >= abs(landed[axis] - raw)):
                        continue
                if abs(best - landed[axis]) > 1e-12:
                    landed[axis], self.snap_kind = float(best), 'hv'
            x, y = landed
        return x, y

    def _round(self, value):
        """一个长度: 光标吸在某个点上就用原值 (过那个点); 否则取整到捕捉格子 — 用户要的是 5 而不是 4.757。"""
        if self.snapped:
            return value
        step = grid_step(self._pixel)
        return round(value / step) * step

    def _radius(self, centre, pixel=None):
        return _distance(centre, self.cursor) if self.snapped else self._round(_distance(centre, self._raw))
