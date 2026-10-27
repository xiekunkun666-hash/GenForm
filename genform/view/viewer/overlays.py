"""叠在模型上画的东西: 正在编辑的草图、选择框、拉伸箭头、额外线条、屏幕上的文字和关系图标。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Property, Qt

from ..scene import color_of
from .. import picking
from ... import planes
from .common import EMPTY3
from .signals import bandChanged


class OverlayMixin:
    """叠加层 (视图的一部分)。"""

    # ---- 草图编辑 ----
    def set_sketch(self, editor, turn=True):
        """进入 (editor) 或退出 (None) 草图编辑。进入时把视角转到正对草图平面 (turn=False 时留在现在的视角)。"""
        self._sketch = editor
        self._hover = None
        self._rebuild_geometry()
        self._set('states', self._make_states())
        self._set('planes', self._make_planes())
        self.refresh_sketch()
        if editor is not None and turn:
            self.look_at_plane(editor.plane)
        self.setCursor(Qt.ArrowCursor)
        self._redraw()

    def refresh_sketch(self):
        """草图编辑器里的东西变了 (外面改了工具或尺寸): 重新生成要画的线。"""
        self._set('drawing', self._make_drawing())
        if self._sketch is not None:
            self.setCursor(Qt.SizeAllCursor if self._sketch.hover_dim is not None       # 停在尺寸上: 能拖
                           else Qt.ArrowCursor if self._sketch.tool == 'select' else Qt.CrossCursor)
        self._sync_band()
        self._redraw()

    # ---- 选择框 (QML 画: 蓝色的半透明方框) ----
    @Property('QVariantList', notify=bandChanged)
    def band(self):
        """正在拖的选择框的四个角 [[x, y]...] (视图里的像素); 没在拖是空的。"""
        return self._band_points

    @Property(bool, notify=bandChanged)
    def bandCrossing(self):
        """从右往左拖的: 碰到框的都选中 (框画成虚线)。"""
        return self._band is not None and self._band[2] < self._band[0]

    def _sync_band(self):
        points = []
        if self._band is not None:
            x0, y0, x1, y1 = self._band
            points = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        elif self._sketch is not None and self._sketch.box() is not None and self.width() > 0:
            (x0, y0), (x1, y1) = self._sketch.box()
            world = planes.to_world([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], self._sketch.plane, self._sketch.offset)
            screen, _ = self._camera.project(world, self.width(), self.height())
            points = [[float(x), float(y)] for x, y in screen]
        if points != self._band_points:
            self._band_points = points
            self.bandChanged.emit()

    def _finish_band(self, additive):
        """松手: 看框住了什么。从左往右 = 整个在框里的; 从右往左 = 碰到框的。"""
        x0, y0, x1, y1 = self._band
        self._band = None
        self._sync_band()
        width, height = self.width(), self.height()
        low, high = (min(x0, x1), min(y0, y1)), (max(x0, x1), max(y0, y1))
        crossing = x1 < x0
        found = {'faces': [], 'edges': [], 'sketches': [], 'components': []}
        found['components'] = sorted({int(part['pick']) for part in self._data.get('extras', ())
                                      if part.get('pick') is not None
                                      and picking.mesh_in_rect(self._camera, width, height, part, low, high, crossing)})

        def lines(points, owner):
            """一串线段 (端点两两一对) 里, 哪些 owner 被框住了。"""
            if len(points) == 0:
                return []
            screen, depth = self._camera.project(points, width, height)
            owner = np.asarray(owner)
            if crossing:
                touched = picking.segments_touch_rect(screen[0::2], screen[1::2], low, high) & (depth[0::2] > 0) & (depth[1::2] > 0)
                return sorted(set(owner[0::2][touched].tolist()))
            inside = picking.in_rect(screen, depth, low, high)
            return sorted(set(owner.tolist()) - set(owner[~inside].tolist()))

        geometry = self._data['geometry']
        if picking.mesh_in_rect(self._camera, width, height, geometry, low, high, crossing):
            found['body'] = True
        found['edges'] = [int(value) for value in lines(geometry['edge_points'], self._point_edge)]
        if len(geometry['verts']):
            screen, depth = self._camera.project(geometry['verts'], width, height)
            inside = picking.in_rect(screen, depth, low, high)
            faces = set(self._vertex_face[inside].tolist()) if crossing else \
                set(self._vertex_face.tolist()) - set(self._vertex_face[~inside].tolist())
            faces.discard(-1)               # 隐藏了的实体块上的顶点
            found['faces'] = sorted(int(value) for value in faces)
        if self._sketch_owner:
            names = sorted(set(self._sketch_owner))
            index = {name: number for number, name in enumerate(names)}
            hit = lines(geometry['sketch_points'], [index[name] for name in self._sketch_owner])
            found['sketches'] = [names[number] for number in hit]
        self.boxed.emit(found, additive)

    def set_extras(self, parts):
        """另外画的网格 (只显示, 不能点): 装配体里别的零件 [{'verts', 'normals', 'tris', 'color', 'low', 'high'}...];
        应力云图是带 'tints' (每个顶点的颜色) 和 'cover': True 的一项 — 它盖在实体上, 实体自己的面不画。"""
        parts = list(parts)
        assembly = any(part.get('pick') is not None for part in parts)
        if assembly and self._plane_shown and not any(part.get('pick') is not None for part in self._data['extras']):
            # 装配体里的零部件第一次画出来: 三个基准面收起来 (和零件有了实体以后一样, 也和 SOLIDWORKS 的装配体一样)
            self._plane_shown = set()
            self.planesVisibleChanged.emit()
        self._set('extras', parts)
        self._set('planes', self._make_planes())         # 基准面的大小跟着装配体走
        self.update()

    def set_handle(self, origin=None, direction=None, reach=0.0):
        """拉伸面板开着时视图里的那根箭头: 从草图轮廓中心沿法向, 头在 reach 处; 拖它的头会发 handleDragged(新的 reach)。"""
        self._handle = None if origin is None else (np.asarray(origin, dtype=float), np.asarray(direction, dtype=float), float(reach))
        if self._handle is None:
            self._handle_drag = False
        self._set('drawing', self._make_drawing())
        self._redraw()

    def _handle_lines(self):
        """箭头要画的线段和它的头的位置: 一根杆 + 四条线拼的箭头尖 (大小按现在的缩放定, 屏幕上差不多 16 像素)。"""
        origin, direction, reach = self._handle
        tip = origin + direction * reach
        toward = direction * (1.0 if reach >= 0 else -1.0)
        screen, _ = self._camera.project([tip, tip + toward], self.width(), self.height())
        pixel = max(float(np.hypot(*(screen[1] - screen[0]))), 1e-6)       # 沿箭头方向 1 mm 是多少像素
        front, right, up = self._camera.basis()
        side = np.cross(toward, front)
        if np.linalg.norm(side) < 1e-6:                                     # 正对着箭头看: 随便取一个侧向
            side = right
        side = side / np.linalg.norm(side)
        other = np.cross(toward, side)
        length = min(18.0 / pixel, 1e6) if pixel > 0.05 else 18.0 / max(float(np.hypot(*(self._camera.project(
            [tip, tip + side], self.width(), self.height())[0][1] - screen[0]))), 1e-6)
        head = tip + toward * length                                        # 箭头尖伸出去一点, 好抓
        base, wide = tip, length * 0.38
        lines = [(origin, tip)]
        for across in (side, -side, other, -other):
            lines.append((base + across * wide, head))
        lines += [(base + side * wide, base - side * wide), (base + other * wide, base - other * wide)]
        return lines, head

    def set_overlay(self, lines=(), points=(), labels=()):
        """测量的标注线、标注点和文字 (不在草图里时画)。"""
        self._overlay = (list(lines), list(points), list(labels))
        self._set('drawing', self._make_drawing())
        self._redraw()

    def _make_drawing(self):
        editor = self._sketch
        if editor is None:
            lines, points, _ = self._overlay
            if self._handle is not None and self.width() > 1:
                lines = list(lines) + self._handle_lines()[0]
            ends = np.array([end for line in lines for end in line], dtype=np.float32).reshape(-1, 3)
            tint = color_of('draw_chosen', self._gl_dark())
            rows = np.array([(*point, *tint, 1.0) for point in points], dtype=np.float32).reshape(-1, 7)
            return ends, np.full(len(ends), 3.0, dtype=np.float32), rows
        lines, points, _ = editor.drawing()
        ends, states = [], []
        for start, end, state in lines:
            ends += [start, end]
            states += [state, state]
        line_points = planes.to_world(ends, editor.plane, editor.offset) if ends else EMPTY3
        colors = {0: 'draw', 1: 'draw_hover', 2: 'draw_chosen', 3: 'draw_draft', 4: 'draw_defined', 5: 'draw_defined'}
        rows = []
        if points:
            world = planes.to_world([position for position, _ in points], editor.plane, editor.offset)
            rows = [(*position, *color_of(colors[state], self._gl_dark()), 1.0) for position, (_, state) in zip(world, points)]
        return (np.asarray(line_points, dtype=np.float32), np.array(states, dtype=np.float32),
                np.array(rows, dtype=np.float32).reshape(-1, 7))

    def _grid_matrix(self):
        """网格摆在哪: 只有编辑草图、而且开着网格捕捉时画, 摆在草图平面上 (网格捕捉默认关: 草图背景是干净的)。"""
        if self._sketch is None or 'grid' not in self._sketch.snaps:
            return None
        origin, x_dir, y_dir, normal = planes.frame(self._sketch.plane, self._sketch.offset)
        matrix = np.eye(4)
        matrix[:3, 0], matrix[:3, 1], matrix[:3, 2], matrix[:3, 3] = x_dir, y_dir, normal, origin
        return matrix

    def _sketch_point(self, x, y):
        """屏幕位置 → 草图平面坐标 (视线和草图平面平行时返回 None)。"""
        origin, direction = self._camera.ray(x, y, self.width(), self.height())
        return planes.from_ray(origin, direction, self._sketch.plane, self._sketch.offset)

    def _sketch_pixel(self):
        return self._camera.pixel_size(self.height())

    # ---- 屏幕上的文字标注 (QML 画) ----
    def _update_labels(self):
        width, height = self.width(), self.height()
        rows = []
        if width > 0 and height > 0:
            if self._sketch is not None:
                for text, position in self._sketch.drawing()[2]:
                    world = planes.to_world([position], self._sketch.plane, self._sketch.offset)
                    screen, depth = self._camera.project(world, width, height)
                    if depth[0] > 0:
                        rows.append({'text': text, 'x': float(screen[0, 0]) + 12, 'y': float(screen[0, 1]) - 26, 'kind': 'size'})
                # 智能尺寸的数字: 压在尺寸线中间 (x, y 是中心); 放下的带编号, 点它选中
                for text, position, ident in self._sketch.dim_labels():
                    world = planes.to_world([position], self._sketch.plane, self._sketch.offset)
                    screen, depth = self._camera.project(world, width, height)
                    if depth[0] > 0:
                        rows.append({'text': text, 'x': float(screen[0, 0]), 'y': float(screen[0, 1]), 'kind': 'dim',
                                     'id': ident, 'chosen': bool(ident) and ident == self._sketch.relation,
                                     'hot': bool(ident) and ident == f'dim:{self._sketch.hover_dim}'})
                # 几何关系的小图标: 标在图形旁边, 一格 = 14 个像素 (x, y 是图标的中心)
                marks = self._sketch.relation_marks()[:300]
                if marks:
                    away = 14.0 * self._sketch_pixel()
                    spots = [(spot[0] + way[0] * away, spot[1] + way[1] * away) for _, _, spot, way, _ in marks]
                    world = planes.to_world(spots, self._sketch.plane, self._sketch.offset)
                    screen, depth = self._camera.project(world, width, height)
                    chosen = self._sketch.relation
                    for (kind, tag, _, _, ident), (x, y), ahead in zip(marks, screen, depth):
                        if ahead > 0 and -20 <= x <= width + 20 and -20 <= y <= height + 20:
                            rows.append({'text': tag, 'x': float(x), 'y': float(y), 'kind': 'relation', 'icon': 'rel_' + kind,
                                         'id': ident, 'chosen': bool(ident) and ident == chosen})
            else:
                for text, position, *kind in self._overlay[2]:
                    screen, depth = self._camera.project([position], width, height)
                    if depth[0] > 0 and kind == ['clash']:         # 装配体实时检查的红叉: x, y 是叉的中心
                        rows.append({'text': text, 'x': float(screen[0, 0]), 'y': float(screen[0, 1]), 'kind': 'clash'})
                    elif depth[0] > 0:
                        rows.append({'text': text, 'x': float(screen[0, 0]) + 10, 'y': float(screen[0, 1]) - 24, 'kind': 'size'})
                half = self.plane_half()
                for name in self._shown_planes():
                    world = planes.to_world([(-half, half)], name)
                    screen, depth = self._camera.project(world, width, height)
                    if depth[0] > 0:
                        rows.append({'text': planes.SHORT[name], 'x': float(screen[0, 0]) + 6, 'y': float(screen[0, 1]) + 4,
                                     'kind': 'plane'})
        if rows != self._labels:
            self._labels = rows
            self.labelsChanged.emit()
