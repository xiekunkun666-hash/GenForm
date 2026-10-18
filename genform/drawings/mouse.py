"""图纸上的鼠标: 吸到端点 / 圆, 智能尺寸点两下放一个尺寸, 拖视图, 删除。"""
from __future__ import annotations

import math
import numpy as np
from PySide6.QtCore import Slot


class MouseMixin:
    """图纸上的鼠标 (工程图的一部分)。"""

    # ---- 图纸上的鼠标 (view/sheet.SheetView 转过来的; 坐标是图纸上的毫米) ----
    def _view_at(self, x, y, slack=3.0):
        for name, place in self._placed.items():
            box = self._data['views'][name]['box']
            half = ((box[2] - box[0]) * place[2] / 2 + slack, (box[3] - box[1]) * place[2] / 2 + slack)
            if abs(x - place[0]) <= half[0] and abs(y - place[1]) <= half[1]:
                return name
        return None

    def _snap(self, x, y, pixel, only=None):
        """离 (x, y) 最近的可吸的点 (端点、圆心) → (视图名, 视图坐标里的点) 或 None。轴测图上不标尺寸。"""
        best, limit = None, 10.0 * pixel
        for name, place in self._placed.items():
            if name == 'iso' or (only and name != only) or not len(self._snaps.get(name, ())):
                continue
            target = np.array(self._to_view(place, x, y))
            gaps = np.hypot(*(self._snaps[name] - target).T) * place[2]
            index = int(np.argmin(gaps))
            if gaps[index] < limit:
                best, limit = (name, tuple(float(value) for value in self._snaps[name][index])), float(gaps[index])
        return best

    def _circle_at(self, x, y, pixel):
        for name, place in self._placed.items():
            if name == 'iso':
                continue
            px, py = self._to_view(place, x, y)
            for cx, cy, radius, full in self._data['views'][name]['circles']:
                if abs(math.hypot(px - cx, py - cy) - radius) * place[2] < 6.0 * pixel:
                    return name, (cx, cy, radius, full), (px, py)
        return None

    def _aim(self, draft, x, y):
        """两个点都点好了, 鼠标在 (x, y): 尺寸往哪边标 — 上下拉出去是水平尺寸, 左右拉出去是竖直尺寸, 留在中间是斜着量。"""
        px, py = self._to_view(self._placed[draft['view']], x, y)
        (ax, ay), (bx, by) = draft['a'], draft['b']
        beyond_y = max(min(ay, by) - py, py - max(ay, by), 0.0)
        beyond_x = max(min(ax, bx) - px, px - max(ax, bx), 0.0)
        if beyond_y > 0 and beyond_y >= beyond_x and abs(bx - ax) > 1e-6:
            return dict(draft, kind='linear', mode='h', at=py)
        if beyond_x > 0 and abs(by - ay) > 1e-6:
            return dict(draft, kind='linear', mode='v', at=px)
        if abs(bx - ax) <= 1e-6:
            return dict(draft, kind='linear', mode='v', at=px)
        if abs(by - ay) <= 1e-6:
            return dict(draft, kind='linear', mode='h', at=py)
        length = math.hypot(bx - ax, by - ay)
        # 图纸上 y 向下, 视图里 y 向上: 法向的正负要和 _linear 里画的那一边对上
        offset = -((px - ax) * -(by - ay) + (py - ay) * (bx - ax)) / length
        return dict(draft, kind='linear', mode='a', at=offset)

    def hover(self, x, y, pixel):
        if not self._tool or not self._placed:
            return
        draft = self._draft
        if draft is not None and 'b' in draft:
            self._draft = self._aim({key: draft[key] for key in ('view', 'a', 'b')}, x, y)
            self._mark = None
        else:
            found = self._snap(x, y, pixel, draft['view'] if draft else None)
            self._mark = self._to_sheet(self._placed[found[0]], found[1]) if found else ((x, y) if draft else None)
        self._composed = None
        if self.view is not None:
            self.view.update()

    def click(self, x, y, pixel):
        if not self._placed:
            return
        if self._tool == 'dimension':
            draft = self._draft
            if draft is not None and 'b' in draft:          # 第三下: 放下
                placed = self._aim({key: draft[key] for key in ('view', 'a', 'b')}, x, y)
                self._dims.append({key: (list(value) if isinstance(value, tuple) else value) for key, value in placed.items()})
                self._draft, self._mark = None, None
                self._touch()
                return
            found = self._snap(x, y, pixel, draft['view'] if draft else None)
            if found is None and draft is None:
                circle = self._circle_at(x, y, pixel)
                if circle is not None:                      # 点在一个圆上: 直接标直径 / 半径
                    name, (cx, cy, radius, full), at = circle
                    reach = math.hypot(at[0] - cx, at[1] - cy) or 1.0
                    far = radius + 9.0 / self._placed[name][2]
                    self._dims.append({'view': name, 'kind': 'round', 'c': [cx, cy], 'r': radius, 'full': full,
                                       'at': [cx + (at[0] - cx) / reach * far, cy + (at[1] - cy) / reach * far]})
                    self._touch()
                    return
            if found is None:
                self.app.notice.emit('点在线的端点、圆心上，或者点一个圆' if draft is None else '第二个点要在同一个视图里的端点或圆心上')
                return
            if draft is None:
                self._draft = {'view': found[0], 'a': found[1]}
            elif found[1] != draft['a']:
                self._draft = dict(draft, b=found[1])
            self._refresh()
            return
        nearest, limit = -1, 7.0 * max(pixel, 0.5)
        for index, hx, hy in self._handles:                 # 平时: 点一个手标的尺寸 = 选中它 (Delete 删)
            gap = math.hypot(hx - x, hy - y)
            if gap < limit:
                nearest, limit = index, gap
        if nearest != self._selected:
            self._selected = nearest
            self._refresh()

    def cancel(self):
        """右键 / Esc: 先放弃标到一半的, 再退出标尺寸, 再取消选中。→ 有没有做事。"""
        if self._draft is not None:
            self._draft, self._mark = None, None
        elif self._tool:
            self._tool, self._mark = '', None
        elif self._selected >= 0:
            self._selected = -1
        else:
            return False
        self._refresh()
        return True

    @Slot()
    def deleteSelected(self):
        if 0 <= self._selected < len(self._dims):
            del self._dims[self._selected]
            self._selected = -1
            self._touch()

    @Slot()
    def clearDimensions(self):
        if self._dims:
            self._dims, self._selected = [], -1
            self._touch()

    def grab_at(self, x, y):
        """左键按在哪个视图上 (拖它挪位置); 正在标尺寸时不拖。"""
        return None if self._tool else self._view_at(x, y)

    def drag(self, name, dx, dy):
        offset = self._offsets.setdefault(name, [0.0, 0.0])
        offset[0] += dx
        offset[1] += dy
        self._composed = None
        if self.view is not None:
            self.view.update()

    def drag_done(self):
        self._touch()
