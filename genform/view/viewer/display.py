"""显示方式和数据: 样式 / 布景 / 剖切 / 外观、显示哪些东西、手势轮、模型和选中状态、基准面。"""
from __future__ import annotations

import math
import numpy as np
from PySide6.QtCore import Property

from ..scene import color_of, STYLES
from ... import planes
from .common import (
    _geometry, GESTURE_AIM, GESTURE_FIRE, GESTURE_SECTORS, GESTURE_START, ORIGIN_PIXELS, PLANE_MIN_HALF,
    _without_faces)
from .signals import gestureChanged, labelsChanged, planesVisibleChanged


class DisplayMixin:
    """显示方式和数据 (视图的一部分)。"""

    # ---- 显示方式 (样式、布景、剖切、外观) ----
    def set_display(self, **changes):
        """style 显示样式 / scene 布景 / cartoon 卡通 / origin 画不画原点 / color 实体颜色 (r, g, b) 或 None /
        section 剖切 {'plane', 'offset', 'flip'} 或 None / planes_off 主要基准面一律不画 / perspective 透视 /
        body 画不画实体。"""
        if 'perspective' in changes:
            self._camera.perspective = bool(changes.pop('perspective'))
        if changes.get('style', STYLES[0]) not in STYLES:
            raise ValueError(f'没有这种显示样式: {changes["style"]}')
        body = self._display['body']
        self._display.update(changes)
        if self._display['body'] != body:
            self._hover = None
            self._rebuild_geometry()
            self._set('states', self._make_states())
        self._set('planes', self._make_planes())
        self._set('drawing', self._make_drawing())
        self._redraw()

    def _render_options(self):
        display = self._display
        clip = None
        if display['section'] and self._sketch is None:         # 画草图时不剖: 草图要对着完整的零件画
            origin, _, _, normal = planes.frame(display['section']['plane'], float(display['section'].get('offset', 0.0)))
            sign = 1.0 if display['section'].get('flip') else -1.0
            clip = (*(normal * sign), float(-sign * (normal @ origin)))
        return {'style': display['style'], 'scene': display['scene'], 'cartoon': display['cartoon'],
                'origin': self._origin_reach() if display['origin'] else 0.0, 'face': display['color'], 'clip': clip}

    def _origin_reach(self):
        """原点坐标系的一根轴该画多长 (mm), 才能在屏幕上是 ORIGIN_PIXELS 那么长。原点在眼睛后面时不画 (0)。"""
        camera = self._camera
        pixel = camera.pixel_size(self.height())
        if camera.perspective:
            depth = float((np.zeros(3) - camera.eye()) @ camera.basis()[0])
            if depth <= camera.distance * 0.02:
                return 0.0
            pixel *= depth / camera.distance
        return pixel * ORIGIN_PIXELS

    def set_names(self, names):
        self._names = dict(names)

    def set_feature_colors(self, colors, opacity=None):
        """单独上色的特征 {特征 id: (r, g, b)}: 它做出来的面用这个颜色, 别的面还是零件的颜色。
        opacity: 半透明的特征 {特征 id: 0~1} (玻璃)。"""
        colors, opacity = dict(colors), dict(opacity or {})
        if colors != self._feature_colors or opacity != self._feature_opacity:
            self._feature_colors, self._feature_opacity = colors, opacity
            self._rebuild_geometry()
            self._redraw()

    def set_hidden(self, identifiers, rebuild=True):
        """这些特征 (草图、曲线、参考几何体) 的线不画。"""
        identifiers = set(identifiers)
        if identifiers != self._hidden:
            self._hidden = identifiers
            if rebuild:
                self._rebuild_geometry()
                self._set('states', self._make_states())
                self._redraw()

    def _get_planes_visible(self):
        return bool(self._plane_shown)

    def _set_planes_visible(self, value):
        if bool(self._plane_shown) != bool(value):
            self._plane_shown = set(planes.PLANES) if value else set()
            self._set('planes', self._make_planes())
            self.planesVisibleChanged.emit()
            self._redraw()

    def plane_shown(self, name):
        return name in self._plane_shown

    def toggle_plane(self, name):
        """单独显示 / 隐藏一个主要基准面。"""
        self._plane_shown.symmetric_difference_update({name})
        self._set('planes', self._make_planes())
        self.planesVisibleChanged.emit()
        self._redraw()

    def zoom_to_plane(self, name):
        """放大所选范围: 把这个基准面放满画面 (视角方向不变)。"""
        half = self.plane_half()
        corner = planes.to_world([(-half, -half), (half, half), (-half, half), (half, -half)], name)
        self._glide_to(None, (corner.min(axis=0), corner.max(axis=0)))

    planesVisible = Property(bool, _get_planes_visible, _set_planes_visible, notify=planesVisibleChanged)

    @Property('QVariantList', notify=labelsChanged)
    def labels(self):
        return self._labels

    # ---- 手势轮 ----
    @Property(bool, notify=gestureChanged)
    def gestureActive(self):
        return self._gesture is not None

    @Property(float, notify=gestureChanged)
    def gestureX(self):
        return self._gesture[0] if self._gesture else 0.0

    @Property(float, notify=gestureChanged)
    def gestureY(self):
        return self._gesture[1] if self._gesture else 0.0

    @Property(int, notify=gestureChanged)
    def gestureIndex(self):
        return self._gesture[2] if self._gesture else -1

    def _gesture_move(self, x0, y0, x, y):
        """右键拖动中: 更新手势轮。→ True 表示已经划中并执行了 (这次按键后面的移动不用再管)。"""
        dx, dy = x - x0, y - y0
        reach = math.hypot(dx, dy)
        if self._gesture is None:
            if reach < GESTURE_START:
                return False
            self._gesture = [x0, y0, -1]
        index = -1
        if reach >= GESTURE_AIM:
            index = int(round(math.degrees(math.atan2(-dy, dx)) / (360 / GESTURE_SECTORS))) % GESTURE_SECTORS
        if reach >= GESTURE_FIRE:
            self._gesture = None
            self.gestureChanged.emit()
            self.gestureTriggered.emit(index)
            return True
        if index != self._gesture[2]:
            self._gesture[2] = index
        self.gestureChanged.emit()
        return False

    def _gesture_end(self):
        """右键松开: 已经指着某一格就执行它 (不必非要划到图标上), 不然就是取消。"""
        gesture, self._gesture = self._gesture, None
        if gesture is not None:
            self.gestureChanged.emit()
            if gesture[2] >= 0:
                self.gestureTriggered.emit(gesture[2])

    # ---- 数据 ----
    def set_hidden_faces(self, faces, rebuild=True):
        """这些面 (被用户隐藏的实体块) 不画, 也点不着。"""
        faces = set(faces)
        if faces != self._hidden_faces:
            self._hidden_faces = faces
            if rebuild:
                self._model = _without_faces(self._full, faces)
                self._hover = None
                self._rebuild_geometry()
                self._set('states', self._make_states())
                self._redraw()

    def set_model(self, model):
        had_body = bool(self._full.get('has_body'))
        self._full = model or {}
        self._model = _without_faces(self._full, self._hidden_faces)
        self._rebuild_geometry()
        self._hover = None
        self._set('states', self._make_states())
        if not had_body and self._model.get('has_body') and self._plane_shown:
            # 有了实体以后三个大基准面只会挡视线: 自动收起来 (和常见 CAD 一样), 要用时点 "草图" 或在设计树里单独打开
            self._plane_shown = set()
            self.planesVisibleChanged.emit()
        self._set('planes', self._make_planes())
        if not self._fitted or (not had_body and self._model.get('has_body') and self._sketch is None):
            self._glide_to('iso' if self._fitted else None)     # 第一次有实体: 转到等轴测看它; 之后不抢用户摆好的视角
        self._redraw()

    def _rebuild_geometry(self):
        hidden = self._sketch.feature if self._sketch is not None else None
        geometry, self._vertex_face, self._point_edge, self._sketch_owner = _geometry(self._model, hidden, self._hidden,
                                                                                      self._display['body'], self._feature_colors,
                                                                                      self._feature_opacity)
        self._set('geometry', geometry)

    def set_selection(self, selection):
        self._selection = {'faces': list(selection.get('faces', ())), 'edges': list(selection.get('edges', ())),
                           'feature': selection.get('feature'), 'plane': selection.get('plane')}
        self._set('states', self._make_states())
        self._set('planes', self._make_planes())
        self._redraw()

    def _make_states(self):
        def marks(owner, chosen, hovered):
            states = np.zeros(len(owner), dtype=np.float32)
            if hovered is not None:
                states[owner == hovered] = 1.0
            if len(chosen):                 # 一次比完: 选中几千条边时, 一条一条去整张表里找要将近一秒
                states[np.isin(owner, np.asarray(list(chosen)))] = 2.0
            return states
        selection, hover = self._selection, self._hover
        pointed = hover[1] if hover and hover[0] == 'sketch' else None
        sketches = np.array([2.0 if owner == selection.get('feature') else 1.0 if owner == pointed else 0.0
                             for owner in self._sketch_owner], dtype=np.float32)
        chosen_faces = selection['faces']
        if not chosen_faces and not selection['edges'] and selection.get('feature') and self._sketch is None:
            # 只选着一个特征 (设计树里点的): 它做出来的那些面都亮起来
            chosen_faces = [face['id'] for face in self._model.get('faces', ()) if face.get('feature') == selection['feature']]
        return {'faces': marks(self._vertex_face, chosen_faces, hover[1] if hover and hover[0] == 'face' else None),
                'edges': marks(self._point_edge, selection['edges'], hover[1] if hover and hover[0] == 'edge' else None),
                'sketches': sketches}

    # ---- 基准面 ----
    def plane_half(self):
        """基准面画多大 (半边长): 比零件大一圈, 零件很小或还没有时用固定大小。"""
        corners = [np.asarray(part[key], float) for part in self._data.get('extras') or () if part.get('pick') is not None
                   for key in ('low', 'high')]         # 装配体里的零部件也算
        if self._model.get('has_body'):
            corners += [np.array(self._model['props']['bbox_min']), np.array(self._model['props']['bbox_max'])]
        if corners:
            return max(PLANE_MIN_HALF, float(np.abs(np.concatenate(corners)).max()) * 1.25)
        return PLANE_MIN_HALF

    def _shown_planes(self):
        """现在要画哪几个基准面。编辑草图时只留草图所在的那个 (由网格表示), 其余收起来免得挡视线。"""
        if self._sketch is not None:
            return []
        chosen = self._selection.get('plane')
        if self._display['planes_off']:
            return [name for name in planes.PLANES if name == chosen]
        return [name for name in planes.PLANES if name in self._plane_shown or name == chosen]

    def _make_planes(self):
        half = self.plane_half()
        tint = color_of('plane', self._gl_dark())
        fill, edge = [], []
        hovered = self._hover[1] if self._hover and self._hover[0] == 'plane' else None
        for name in self._shown_planes():
            chosen = name == self._selection.get('plane')
            fill_alpha = 0.26 if chosen else 0.15 if name == hovered else 0.05
            edge_alpha = 1.0 if chosen else 0.85 if name == hovered else 0.40
            corner = planes.to_world([(-half, -half), (half, -half), (half, half), (-half, half)], name)
            for a, b, c in ((0, 1, 2), (0, 2, 3)):
                fill += [(*corner[a], *tint, fill_alpha), (*corner[b], *tint, fill_alpha), (*corner[c], *tint, fill_alpha)]
            for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
                edge += [(*corner[a], *tint, edge_alpha), (*corner[b], *tint, edge_alpha)]
        return (np.array(fill, dtype=np.float32).reshape(-1, 7), np.array(edge, dtype=np.float32).reshape(-1, 7))
