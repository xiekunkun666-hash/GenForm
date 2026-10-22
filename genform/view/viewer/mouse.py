"""拾取和鼠标: 点中什么、旋转 / 平移 / 缩放、框选、悬停、草图里的鼠标转给草图编辑器。"""
from __future__ import annotations

import math

import numpy as np
import time
from PySide6.QtCore import Qt

from .. import picking
from ... import planes
from .common import CLICK_SLOP, SKETCH_REACH


def _edge_text(entry):
    """一条边的尺寸: 直边报长度; 整圆报直径、半径、周长; 圆弧报直径、半径、弧长; 别的曲线报长度。"""
    length = entry['length']
    if entry['type'] == 'circle' and 'radius' in entry:
        radius = entry['radius']
        whole = abs(length - 2 * np.pi * radius) <= max(1e-6, 1e-4 * length)
        if whole:
            return f'圆，直径 {radius * 2:.4g} mm，半径 {radius:.4g} mm，周长 {length:.4g} mm'
        return f'圆弧，直径 {radius * 2:.4g} mm，半径 {radius:.4g} mm，弧长 {length:.4g} mm（{np.degrees(length / radius):.4g}°）'
    names = {'line': '直边', 'circle': '圆弧边', 'curve': '曲线边'}
    return f'{names.get(entry["type"], "边")}，长 {length:.4g} mm'


class MouseMixin:
    """拾取和鼠标 (视图的一部分)。"""

    # ---- 拾取 ----
    def _pick(self, x, y):
        width, height = self.width(), self.height()
        hit, depth = picking.pick_depth(self._camera, x, y, width, height, self._model) if self._display['body'] else (None, np.inf)
        corners = self._model.get('vertices') if self.pick_vertices and self._display['body'] else None
        if corners is not None and len(corners):
            # 顶点最小, 排在最前面; 被实体挡住的不算 (它就在面和边上, 所以深度放宽一点)
            screen, reach = self._camera.project(corners, width, height)
            gap = np.where(reach > 0, np.linalg.norm(screen - np.array([x, y]), axis=1), np.inf)
            nearest = int(gap.argmin())
            if gap[nearest] <= 8.0 and reach[nearest] <= depth * 1.01 + 0.1:
                return 'vertex', nearest
        if (hit is None or hit[0] == 'face') and self._sketch_owner:
            # 草图线 (和曲线、参考几何体的线): 细, 所以也排在面前面; 被实体挡住的不算
            segment, gap, reach = picking.nearest_segment(self._camera, x, y, width, height, self._data['geometry']['sketch_points'],
                                                         'sketches')
            if segment >= 0 and gap <= SKETCH_REACH and reach <= depth * (1 + picking.EDGE_DEPTH_SLACK) + 0.05:
                return 'sketch', self._sketch_owner[segment * 2]
        extras = self._data.get('extras') or ()
        if any(part.get('pick') is not None for part in extras):       # 装配体里的零部件: 比实体近就是它
            origin, direction = self._camera.ray(x, y, width, height)
            number, distance = picking.pick_extras(origin, direction, extras)
            if number is not None and distance * float(direction @ self._camera.basis()[0]) <= depth:
                return 'component', int(number)
        if hit is not None:
            return hit
        shown = self._shown_planes()
        if not shown:
            return None
        origin, direction = self._camera.ray(x, y, width, height)
        name = picking.pick_plane(origin, direction, shown, self.plane_half())
        return ('plane', name) if name else None

    def _describe(self, hit):
        if hit is None:
            return ''
        kind, identifier = hit
        if kind == 'part_edge':             # 装配体里零部件的一条边: 零件名 + 这条边的尺寸
            number, edge = identifier
            part = next((part for part in self._data.get('extras') or () if part.get('pick') == number), None) or {}
            name = part.get('label') or f'零部件 {number + 1}'
            kinds = ('line', 'circle', 'curve')
            kind_of = part.get('edge_kind')
            entry = {'type': kinds[int(kind_of[edge])] if kind_of is not None and edge < len(kind_of) else 'curve',
                     'length': float(part['edge_length'][edge]) if part.get('edge_length') is not None else 0.0}
            radius = float(part['edge_radius'][edge]) if part.get('edge_radius') is not None else float('nan')
            if radius == radius:
                entry['radius'] = radius
            return f'{name}　{_edge_text(entry)}'
        if kind == 'component':             # 装配体里的零部件: 它的名字 (和设计树上一样) + 能做什么
            part = next((part for part in self._data.get('extras') or () if part.get('pick') == identifier), None)
            name = (part or {}).get('label') or f'零部件 {identifier + 1}'
            about = (part or {}).get('about') or ''
            return f'{name}{"　" + about if about else ""}（单击选中，双击打开零件，右键菜单）'
        if kind == 'plane':
            return f'{planes.NAMES[identifier]}（单击选中，再点“草图”在它上面画）'
        if kind == 'sketch':
            return f'{self._names.get(identifier, "草图")}（单击选中）'
        if kind == 'vertex':
            x, y, z = (float(value) for value in self._model['vertices'][identifier])
            return f'顶点 X {x:.4g}　Y {y:.4g}　Z {z:.4g}'
        table = {entry['id']: entry for entry in self._model.get('edges' if kind == 'edge' else 'faces', ())}
        entry = table.get(identifier)
        if entry is None:
            return ''
        if kind == 'edge':
            return _edge_text(entry)
        names = {'plane': '平面', 'cylinder': '圆柱面', 'cone': '圆锥面', 'sphere': '球面', 'torus': '圆环面'}
        extra = f'，直径 {entry["radius"] * 2:.4g} mm，半径 {entry["radius"]:.4g} mm' if 'radius' in entry else ''
        return f'{names.get(entry["type"], "曲面")}，面积 {entry["area"]:.4g} mm²{extra}'

    # ---- 鼠标 ----
    def _draws(self, button, modifiers):
        """这次按键是不是交给草图编辑器 (而不是转视角)。"""
        return self._sketch is not None and button == Qt.LeftButton and not modifiers & Qt.AltModifier

    def mousePressEvent(self, event):
        point = event.position()
        self.forceActiveFocus()
        if self._zoom is not None and event.button() == Qt.LeftButton:
            self._zoom = [point.x(), point.y(), point.x(), point.y()]
            self._press = None
            self.zoomChanged.emit()
            event.accept()
            return
        if self._handle is not None and self._sketch is None and event.button() == Qt.LeftButton:
            _, head = self._handle_lines()                  # 按在箭头的头附近: 开始拖它
            origin, direction, reach = self._handle
            spots, _ = self._camera.project([head, origin + direction * reach], self.width(), self.height())
            if min(float(np.hypot(spot[0] - point.x(), spot[1] - point.y())) for spot in spots) < 16:
                self._handle_drag, self._press = True, None
                event.accept()
                return
        self._press = [event.button(), point.x(), point.y(), point.x(), point.y(), False, event.modifiers()]
        self._joint_drag = None
        if event.button() == Qt.LeftButton and self._sketch is None and self.joint_axis is not None \
                and not event.modifiers() & (Qt.AltModifier | Qt.ControlModifier):
            self._joint_drag = self._joint_grab(point.x(), point.y())      # 拖起来才算 (只点一下还是选中)
        if self._draws(event.button(), event.modifiers()):
            position = self._sketch_point(point.x(), point.y())
            if position is not None:
                self._sketch.press(position, self._sketch_pixel(), bool(event.modifiers() & Qt.ControlModifier))
                self.refresh_sketch()
                self.sketchEdited.emit()
        event.accept()

    def mouseMoveEvent(self, event):
        if isinstance(self._zoom, list):
            self._zoom[2], self._zoom[3] = event.position().x(), event.position().y()
            self.zoomChanged.emit()
            return
        if self._handle_drag and self._handle is not None:
            # 鼠标这条视线离箭头那根轴最近的地方, 就是头该去的位置
            origin, direction, _ = self._handle
            eye, look = self._camera.ray(event.position().x(), event.position().y(), self.width(), self.height())
            apart, slant = origin - eye, float(direction @ look)
            bottom = 1.0 - slant * slant
            if bottom > 1e-6:                               # 正对着轴看时拖不动 (算不出沿轴走了多少)
                reach = (slant * float(look @ apart) - float(direction @ apart)) / bottom
                self._handle = (origin, direction, reach)
                self._set('drawing', self._make_drawing())
                self._redraw()
                self.handleDragged.emit(reach)
            return
        if self._press is None:
            return
        point = event.position()
        button, x0, y0, last_x, last_y, dragging, modifiers = self._press
        if self._draws(button, modifiers):
            position = self._sketch_point(point.x(), point.y())
            if position is not None:
                self._sketch.move(position, self._sketch_pixel())
                self.refresh_sketch()
            return
        if button == Qt.RightButton:
            if self._gesture_move(x0, y0, point.x(), point.y()):
                self._press = None
            return
        if self._joint_drag is not None and button == Qt.LeftButton:
            if not dragging and abs(point.x() - x0) + abs(point.y() - y0) <= CLICK_SLOP:
                return
            self._press[5] = True
            step = self._joint_step(point.x() - last_x, point.y() - last_y)
            if step:
                self._joint_drag['turned'] += step
                self.jointDragged.emit(self._joint_drag['index'], step)
            self._press[3], self._press[4] = point.x(), point.y()
            return
        if not dragging and abs(point.x() - x0) + abs(point.y() - y0) > CLICK_SLOP:
            dragging = self._press[5] = True
            if button == Qt.LeftButton and not modifiers & Qt.AltModifier:
                self._band = [x0, y0, point.x(), point.y()]     # 左键拖: 拉选择框
            else:
                self._remember()
                self._pivot = self._orbit_pivot(x0, y0)
                self._orbit_flip = math.cos(math.radians(self._camera.pitch)) < 0   # 这一次拖动左右方向定死: 转过头顶也不突然反过来
        if self._band is not None:
            self._band[2], self._band[3] = point.x(), point.y()
            self._sync_band()
            return
        if dragging:
            dx, dy = point.x() - last_x, point.y() - last_y
            shifted = bool(modifiers & (Qt.ShiftModifier | Qt.ControlModifier))
            orbit = (button == Qt.MiddleButton and not shifted) or \
                    (button == Qt.LeftButton and modifiers & Qt.AltModifier)
            pan = button == Qt.MiddleButton and shifted
            if orbit:
                self._stop_glide()
                self._camera.orbit(dx, dy, self._pivot, getattr(self, '_orbit_flip', None))
                self._redraw()
            elif pan:
                self._stop_glide()
                self._camera.pan(dx, dy, self.height())
                self._redraw()
        self._press[3], self._press[4] = point.x(), point.y()

    def mouseReleaseEvent(self, event):
        if isinstance(self._zoom, list):
            self._zoom[2], self._zoom[3] = event.position().x(), event.position().y()
            self._finish_zoom()
            return
        if self._handle_drag:
            self._handle_drag = False
            return
        press, self._press = self._press, None
        grabbed, self._joint_drag = self._joint_drag, None
        if press is None:
            return
        if grabbed is not None and press[5]:        # 拖过车门: 松手, 不算点选
            self.jointReleased.emit()
            return
        point = event.position()
        if press[0] == Qt.RightButton:
            started = self._gesture is not None
            self._gesture_end()
            moved = abs(point.x() - press[1]) + abs(point.y() - press[2])
            if not started and moved < 8 and self._sketch is None:     # 右键单击 (没拖): 弹右键菜单, 和 SOLIDWORKS 一样
                hit = self._pick(point.x(), point.y())
                self.click_at = (point.x(), point.y())
                self.menuRequested.emit(hit[0] if hit else '', hit[1] if hit else -1)
            return
        if self._draws(press[0], press[6]):
            position = self._sketch_point(point.x(), point.y())
            if position is not None:
                self.click_at = (point.x(), point.y())
                self._sketch.release(position, self._sketch_pixel())
                self.refresh_sketch()
                self.sketchEdited.emit()
            return
        if self._band is not None:
            self._band[2], self._band[3] = point.x(), point.y()
            self._finish_band(bool(event.modifiers() & Qt.ControlModifier))
            return
        if press[5] or press[0] != Qt.LeftButton or self._sketch is not None:
            return
        hit = self._pick(point.x(), point.y())
        self.click_at = (point.x(), point.y())
        additive = bool(event.modifiers() & Qt.ControlModifier)
        if hit is None:
            self.picked.emit('', -1, additive)
        else:
            self.picked.emit(hit[0], hit[1], additive)

    def _joint_grab(self, x, y):
        """按下的地方是不是一个跟着运动副动的零部件 (车门) → 拖它要的东西; 不是 None。"""
        extras = self._data.get('extras') or ()
        if not any(part.get('pick') is not None for part in extras):
            return None
        origin, direction = self._camera.ray(x, y, self.width(), self.height())
        number, distance = picking.pick_extras(origin, direction, extras)
        if number is None:
            return None
        axis = self.joint_axis(int(number))
        if axis is None:
            return None
        kind, point, way = axis
        way = np.asarray(way, float) / max(float(np.linalg.norm(way)), 1e-12)
        return {'index': int(number), 'kind': kind, 'origin': np.asarray(point, float), 'axis': way,
                'point': origin + direction * distance, 'turned': 0.0}

    def _joint_step(self, dx, dy):
        """鼠标挪了 (dx, dy) 像素 → 运动副转多少度 (滑多少 mm): 按下的那一点绕轴转一点在屏幕上往哪走, 鼠标顺着它走多远。"""
        grab = self._joint_drag
        width, height = self.width(), self.height()
        relative = grab['point'] - grab['origin']
        if grab['kind'] == 'slide':
            tangent, radius = grab['axis'], 1.0
            spot = grab['point'] + grab['axis'] * grab['turned']
        else:
            angle = np.radians(grab['turned'])           # 按下的那一点跟着门转到哪了
            axis = grab['axis']
            along = axis * float(axis @ relative)
            across = relative - along
            radius = float(np.linalg.norm(across))
            if radius < 1e-6:
                return 0.0
            turned = across * np.cos(angle) + np.cross(axis, across) * np.sin(angle) + along
            spot = grab['origin'] + turned
            tangent = np.cross(axis, turned - along) / radius
        reach = max(radius, 1.0) * 0.05
        screen, depth = self._camera.project([spot, spot + tangent * reach], width, height)
        if depth[0] <= 0 or depth[1] <= 0:
            return 0.0
        way = (screen[1] - screen[0]) / reach              # 沿切线走 1 mm, 屏幕上走多少像素
        length = float(way @ way)
        if length < 1e-6:                                  # 正顺着切线看: 照水平挪动算, 一像素半度
            return float(dx) * 0.5 if grab['kind'] != 'slide' else float(dx)
        moved = float(np.array([dx, dy]) @ way) / length   # 沿切线走了多少 mm
        return moved if grab['kind'] == 'slide' else float(np.degrees(moved / radius))

    def mouseDoubleClickEvent(self, event):
        if self._draws(event.button(), event.modifiers()):
            self._sketch.double_click()
            self.refresh_sketch()
            self.sketchEdited.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def hoverMoveEvent(self, event):
        point = event.position()
        if self._sketch is not None:
            position = self._sketch_point(point.x(), point.y())
            if position is not None:
                self._sketch.move(position, self._sketch_pixel())
                self.refresh_sketch()
                cursor = self._sketch.cursor
                self.hoverChanged.emit(f'X {cursor[0]:.4g}　Y {cursor[1]:.4g}' if cursor is not None else '')
            return
        if time.perf_counter() - self._wheel_at < 0.25:     # 正滚着滚轮: 先不找光标下是什么 (视角一变就得重新筛一遍, 会顿)
            return
        if self._glide is not None:
            # 视角正转着 (点了视图定向、正视于…): 每帧视角都不一样, 找一次光标下是什么就要把整个零件重新投影一遍,
            # 大零件一次一百多毫秒, 鼠标一动动画就一顿一顿的。等转完了再按最后的位置找一次
            self._hover_wait = (point.x(), point.y())
            return
        self._hover_at(point.x(), point.y())

    def _hover_at(self, x, y):
        if self._hover_held:                # 截图中: 不按光标找悬停 (视角跳过去以后鼠标还停在窗口上, 会又亮起来一块)
            return
        hit = self._pick(x, y)
        if hit is not None and hit[0] == 'component':
            hit = self._part_edge(x, y, hit[1]) or hit
        if hit != self._hover:
            if (hit and hit[0] == 'part_edge') or (self._hover and self._hover[0] == 'part_edge'):
                self._show_part_edge(hit if hit and hit[0] == 'part_edge' else None)
            self._hover = hit
            self._set('states', self._make_states())
            self._set('planes', self._make_planes())
            self.hoverChanged.emit(self._describe(hit))
            self.update()

    def _part_edge(self, x, y, number):
        """光标在装配体的零部件上: 离光标 6 像素以内、没被挡住的那条边 → ('part_edge', (零部件序号, 边序号)), 没有是 None。"""
        part = next((part for part in self._data.get('extras') or () if part.get('pick') == number), None)
        segments = part.get('segments') if part else None
        if segments is None or not len(segments) or part.get('segment_edge') is None:
            return None
        width, height = self.width(), self.height()
        if part.get('matrix') is not None:      # 动着的件: 线段摆到现在的位置 (同一个矩阵只算一次)
            matrix = np.asarray(part['matrix'], float)
            cache = getattr(self, '_moved_segments', None)
            if cache is None or cache[0] is not segments or not np.array_equal(cache[1], matrix):
                moved = (np.asarray(segments, float).reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]).reshape(-1, 2, 3)
                cache = self._moved_segments = (segments, matrix, moved)
            segments = cache[2]
        segment, gap, reach = picking.nearest_segment(self._camera, x, y, width, height, segments, f'part{number}')
        if segment < 0 or gap > 6.0:
            return None
        origin, direction = self._camera.ray(x, y, width, height)
        _, distance = picking.pick_extras(origin, direction, [part])
        depth = distance * float(direction @ self._camera.basis()[0])
        if np.isfinite(depth) and reach > depth * (1 + picking.EDGE_DEPTH_SLACK) + 0.05:
            return None                         # 这条边在零件背面, 被挡住了
        return 'part_edge', (int(number), int(part['segment_edge'][segment]))

    def _show_part_edge(self, hit):
        """悬停的那条零件边亮出来: 把它的线段挂在那个零部件上送给视图 (只换这一项, 别的缓冲照用)。"""
        extras = [dict(part) for part in self._data.get('extras') or ()]
        for part in extras:
            part.pop('hover_points', None)
            if hit is not None and part.get('pick') == hit[1][0] and part.get('segments') is not None:
                chosen = np.asarray(part['segment_edge']) == hit[1][1]
                part['hover_points'] = np.asarray(part['segments'], dtype=np.float32)[chosen].reshape(-1, 3)
        self._set('extras', extras)

    def hoverLeaveEvent(self, event):
        self.clear_hover()

    def clear_hover(self, hold=False):
        """去掉光标下的悬停高亮 (光标移出视图; 截图前也调: 用户鼠标正好停在窗口上时, 给 AI 的截图里不该有那块高亮)。
        hold=True: 之后也先不找悬停, 等 release_hover (截图存好了再放开)。"""
        self._hover_held = bool(hold)
        self._hover_wait = None
        if self._hover is not None:
            if self._hover[0] == 'part_edge':
                self._show_part_edge(None)
            self._hover = None
            self._set('states', self._make_states())
            self._set('planes', self._make_planes())
            self.hoverChanged.emit('')
            self.update()

    def release_hover(self):
        self._hover_held = False

    def _orbit_pivot(self, x, y):
        """中键拖着转的时候绕哪一点转: 整个场景 (零件 + 装配体里显示着的零部件) 的中心 — 场景连同它的坐标系在原地转,
        不会绕着光标点到的某个表面点甩来甩去。什么都没有时绕画面中心 (返回 None)。x, y 不用了, 留着是为了接口不变。"""
        lows, highs = [], []
        for part in self._data.get('extras') or ():
            if part.get('low') is not None and part.get('high') is not None and part.get('visible', True) is not False:
                lows.append(np.asarray(part['low'], dtype=float))
                highs.append(np.asarray(part['high'], dtype=float))
        if self._model.get('has_body') and self._display['body'] is not False:
            props = self._model['props']
            lows.append(np.asarray(props['bbox_min'], dtype=float))
            highs.append(np.asarray(props['bbox_max'], dtype=float))
        if not lows:
            return None
        return (np.min(lows, axis=0) + np.max(highs, axis=0)) / 2

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        point = event.position()
        width, height = self.width(), self.height()
        now = time.perf_counter()
        fresh = now - self._wheel_at > 0.6                  # 连着滚的一串算一步
        spot = self._wheel_anchor
        # 朝光标指着的那一点缩放: 指着零件就是零件表面那一点, 指着空白处就是目标点所在深度上的那一点。
        # 这一点一串滚动里只找一次 (朝它缩放时它在屏幕上不动, 光标没挪就还是它): 零件面多了以后每滚一格都找一遍会卡
        if fresh or spot is None or abs(spot[0] - point.x()) + abs(spot[1] - point.y()) > 3:
            origin, direction = self._camera.ray(point.x(), point.y(), width, height)
            triangle, distance = (-1, np.inf)
            if self._model.get('has_body') and self._sketch is None:
                triangle, distance = picking.ray_model(self._camera, point.x(), point.y(), width, height, self._model)
            if triangle < 0:
                front = self._camera.basis()[0]
                distance = self._camera.distance / max(float(direction @ front), 1e-6)
            spot = self._wheel_anchor = (point.x(), point.y(), origin + direction * distance)
        self._stop_glide()
        if fresh:
            self._remember()
        self._wheel_at = now
        self._camera.zoom(0.88 ** steps, spot[2])
        self._redraw()
        event.accept()
