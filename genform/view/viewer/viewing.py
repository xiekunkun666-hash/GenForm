"""视角: 适应窗口、正视、缓动到某个视角、视角历史、局部放大、截图。"""
from __future__ import annotations

import math
import numpy as np
import time
from PySide6.QtCore import Property, Qt, QTimer, Slot

from ..camera import Camera, VIEWS
from .. import picking
from ... import planes
from ...document import DocumentError
from . import offscreen
from .common import HISTORY_LIMIT, VIEW_GLIDE
from .screenshot import ScreenshotRequest
from .signals import zoomChanged


class ViewingMixin:
    """视角 (视图的一部分)。"""

    # ---- 视角 ----
    def _bounds(self):
        if self._sketch is not None:
            box = self._sketch.bounds()
            if box is None:
                box = ((-50.0, -40.0), (50.0, 40.0))
            margin = max(box[1][0] - box[0][0], box[1][1] - box[0][1], 20.0) * 0.25
            corner = planes.to_world([(box[0][0] - margin, box[0][1] - margin), (box[1][0] + margin, box[1][1] + margin)],
                                     self._sketch.plane, self._sketch.offset)
            return corner.min(axis=0), corner.max(axis=0)
        extras = [part for part in self._data['extras'] if part.get('low') is not None]
        if self._model.get('has_body') or extras:
            boxes = [(np.array(part['low'], float), np.array(part['high'], float)) for part in extras]     # 装配体: 别的零件也取进画面
            if self._model.get('has_body'):
                boxes.append((np.array(self._model['props']['bbox_min']), np.array(self._model['props']['bbox_max'])))
            return np.min([low for low, _ in boxes], axis=0), np.max([high for _, high in boxes], axis=0)
        points = self._data['geometry']['sketch_points']
        if len(points):
            return points.min(axis=0), points.max(axis=0)
        return (-60.0, -60.0, 0.0), (60.0, 60.0, 40.0)

    @Slot()
    def fit(self):
        self._glide_to(None)

    @Slot(str)
    def setView(self, name):
        if name == 'fit':
            self.fit()
        elif name in VIEWS:
            self._glide_to(name)

    def snap_view(self, name):
        """直接转到 name 这个视角, 不平滑过渡 — 截图前用: 过渡要几百毫秒, 紧跟着截的那一帧还是原来的角度。"""
        if self.width() <= 0 or self.height() <= 0:
            raise DocumentError('三维视图还没准备好')
        self._stop_glide()
        self._glide_to(name if name in VIEWS else None, instant=True)

    def look_at_plane(self, plane):
        """把视角转到正对一个基准面 (三个基准面的名称, 或基准面特征算出来的坐标系)。"""
        if isinstance(plane, str):
            self._glide_to(planes.VIEW[plane])
            return
        self.look_along(planes.frame(plane)[3])

    def look_along(self, normal, bounds=None):
        """把视角转到正对着法向是 normal 的面 (从法向那一侧看过去); bounds 给了就顺便把这个范围放满画面。"""
        front = -np.asarray(normal, dtype=float)
        front /= max(float(np.linalg.norm(front)), 1e-12)
        pitch = max(-89.9, min(89.9, -math.degrees(math.asin(max(-1.0, min(1.0, float(front[2])))))))
        self._glide_to((math.degrees(math.atan2(float(front[0]), float(front[1]))), pitch), bounds)

    def zoom_to(self, low, high):
        """放大所选范围: 把这个范围放满画面 (视角方向不变)。"""
        self._glide_to(None, (np.asarray(low, dtype=float), np.asarray(high, dtype=float)))

    def face_bounds(self, faces):
        """这几张面占的范围 → (最小角, 最大角); 一张都不在显示的网格里则是 None。"""
        verts = self._data['geometry']['verts']
        chosen = np.isin(self._vertex_face, list(faces)) if len(verts) else np.zeros(0, dtype=bool)
        if not chosen.any():
            return None
        return verts[chosen].min(axis=0), verts[chosen].max(axis=0)

    def faces_at(self, x, y):
        """视图里这个位置一路穿过哪些面 (从近到远)。"""
        if not self._display['body']:
            return []
        origin, direction = self._camera.ray(x, y, self.width(), self.height())
        return picking.faces_along(origin, direction, self._model)

    def _glide_to(self, view, bounds=None, instant=False):
        """把视角转到 view (None = 方向不变) 并把内容 (或 bounds 这个范围) 放满画面; 平滑转过去, 用户看得出是同一个
        场景转了个角度。第一次取景 (窗口刚出来) 和 instant 时直接到位。"""
        width, height = float(self.width()), float(self.height())
        if width <= 0 or height <= 0:
            return False
        goal = Camera()
        goal.yaw, goal.pitch = self._camera.yaw, self._camera.pitch
        if isinstance(view, tuple):
            goal.yaw, goal.pitch = view
        elif view is not None:
            goal.set_view(view)
        low, high = bounds or self._bounds()
        goal.fit(low, high, width / height)
        end = (goal.yaw, goal.pitch, np.array(goal.target, dtype=float), goal.distance)
        if instant and self._fitted:
            self._remember()
            self._apply_view(end)
            return
        if not self._fitted:
            self._fitted = True
            self._apply_view(end)
            return
        self._remember()
        self._glide_state(end)

    def view_state(self):
        camera = self._camera
        return (camera.yaw, camera.pitch, np.array(camera.target, dtype=float), camera.distance)

    def _remember(self):
        """视角要变了: 把现在的记下来, "上一个视图" 能回来。"""
        state = self.view_state()
        last = self._history[-1] if self._history else None
        if last is None or abs(last[0] - state[0]) + abs(last[1] - state[1]) + abs(last[3] - state[3]) \
                + float(np.abs(last[2] - state[2]).sum()) > 1e-6:
            self._history.append(state)
            del self._history[:-HISTORY_LIMIT]

    @Slot()
    def previousView(self):
        if self._history:
            self._glide_state(self._history.pop())

    def go_to(self, state):
        """转到一个存下来的视角 (view_state 给的)。"""
        self._remember()
        self._glide_state(state)

    def _glide_state(self, end):
        camera = self._camera
        start = (camera.yaw, camera.pitch, np.array(camera.target, dtype=float), camera.distance)
        turn = (end[0] - start[0] + 180.0) % 360.0 - 180.0             # 方位角、俯仰角都走近的那一边
        tilt = (end[1] - start[1] + 180.0) % 360.0 - 180.0
        end = (start[0] + turn, start[1] + tilt) + end[2:]
        self._glide = (time.perf_counter(), start, end)
        self._glide_timer.start()

    def _apply_view(self, state):
        self._camera.yaw = (state[0] + 180.0) % 360.0 - 180.0
        self._camera.pitch = (state[1] + 180.0) % 360.0 - 180.0
        self._camera.target, self._camera.distance = np.array(state[2]), state[3]
        self._redraw()

    def _glide_step(self):
        if self._glide is None:
            self._glide_timer.stop()
            return
        began, start, end = self._glide
        progress = min(1.0, (time.perf_counter() - began) / VIEW_GLIDE)
        eased = 1.0 - (1.0 - progress) ** 3
        self._apply_view(tuple(a + (b - a) * eased for a, b in zip(start, end)))
        if progress >= 1.0:
            self._glide = None
            self._glide_timer.stop()
            waiting, self._hover_wait = self._hover_wait, None
            if waiting is not None and self._sketch is None:
                QTimer.singleShot(0, lambda: self._hover_at(*waiting) if self._glide is None else None)

    # ---- 局部放大 ----
    @Property(bool, notify=zoomChanged)
    def zoomArmed(self):
        return self._zoom is not None

    @Property('QVariantList', notify=zoomChanged)
    def zoomRect(self):
        """正在拖的放大框 [x, y, 宽, 高] (视图里的像素); 没在拖是空的。"""
        if not isinstance(self._zoom, list):
            return []
        x0, y0, x1, y1 = self._zoom
        return [min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)]

    @Slot()
    def zoomBox(self):
        """局部放大: 接下来用左键拖一个框, 框里的内容放满画面。再点一次 / Esc = 不放大了。"""
        self._zoom = None if self._zoom is not None else 'armed'
        self.setCursor(Qt.CrossCursor if self._zoom else Qt.ArrowCursor)
        self.zoomChanged.emit()

    def cancel_zoom(self):
        if self._zoom is None:
            return False
        self._zoom = None
        self.setCursor(Qt.ArrowCursor if self._sketch is None or self._sketch.tool == 'select' else Qt.CrossCursor)
        self.zoomChanged.emit()
        return True

    def _finish_zoom(self):
        x0, y0, x1, y1 = self._zoom
        self.cancel_zoom()
        width, height = self.width(), self.height()
        box_w, box_h = abs(x1 - x0), abs(y1 - y0)
        if box_w < 6 or box_h < 6 or width <= 0 or height <= 0:
            return
        goal = self._camera.copy()
        goal.pan(width / 2 - (x0 + x1) / 2, height / 2 - (y0 + y1) / 2, height)     # 框的中心挪到画面中心
        goal.distance = max(goal.distance * max(box_w / width, box_h / height), 0.5)
        self._remember()
        self._glide_state((goal.yaw, goal.pitch, np.array(goal.target, dtype=float), goal.distance))

    def _stop_glide(self):
        """用户自己动了视角: 过渡到一半也停下, 听用户的。"""
        if self._glide is not None:
            self._glide = None
            self._glide_timer.stop()

    def request_shot(self, path=None, request=None):
        """让渲染线程把下一帧存成图片; 存好后发 shotSaved。"""
        if not self.screenshot_ready():
            raise DocumentError('三维视图还没准备好')
        current = getattr(self, '_shot_request', None)
        if current is not None and not current.done and not current.cancelled:
            raise DocumentError('已有截图正在保存')
        request = request or ScreenshotRequest(path)
        self._shot_request = request
        try:
            if self._shot_can_render():
                self._shot_path = request
                self.update()
            else:
                offscreen.start_offscreen(self, request)
        except Exception:
            self.cancel_shot(request)
            raise
        return request.path

    def screenshot_ready(self):
        """有尺寸和显示数据即可导出；窗口被遮挡时使用独立离屏上下文。"""
        try:
            return (self.width() > 0 and self.height() > 0 and self._camera is not None
                    and all(name in self._data for name in ('geometry', 'states', 'planes', 'drawing', 'extras')))
        except RuntimeError:
            return False

    def _shot_can_render(self):
        """仅前台帧路径需要场景图可绘制；后台截图不依赖这些条件。"""
        try:
            window = self.window()
            return (self.width() > 0 and self.height() > 0 and self.isVisible() and window is not None
                    and window.isVisible() and window.isExposed() and window.isSceneGraphInitialized()
                    and getattr(self, '_renderer', None) is not None)
        except RuntimeError:
            return False

    def cancel_shot(self, request=None):
        """取消尚未完成的截图; 渲染器下一次同步时会丢弃已过期的请求。"""
        current = getattr(self, '_shot_request', None)
        if current is None or (request is not None and request is not current):
            return
        current.cancel()
        if self._shot_path is current:
            self._shot_path = None
        self._shot_request = None

    def geometryChange(self, new, old):
        super().geometryChange(new, old)
        if new.width() > 0 and new.height() > 0:
            if not self._fitted:
                self._glide_to(None)
            else:
                self._update_labels()
