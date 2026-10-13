# -*- coding: utf-8 -*-
"""三维视图控件 (QML 里的 Viewport): 显示模型和基准面、转动视角、点选、编辑草图。

操作 (和常见 CAD 接近):
    左键单击      选择面 / 边 / 草图线 / 基准面 (按住 Ctrl 加选或取消; 点空白处清空)
    左键拖动      拉出蓝色的选择框: 从左往右拖 = 整个在框里的才选中; 从右往左拖 = 碰到框的都选中
    中键拖动      旋转视角         (没有中键: Alt + 左键拖动)
    Ctrl + 中键   平移视角         (Shift + 中键也行)
    右键拖动      手势轮: 朝某个方向一划就执行那个方向上的命令 (建模和草图各一套, 内容由控制器给)
    滚轮          朝光标所指的位置缩放
编辑草图时左键交给草图编辑器 (画、选、拖), 其余不变。

界面线程管相机、拾取、选择; 渲染线程只负责把同步过去的数据画出来。只在内容变了的时候重画, 空闲不占显卡。
"""
from __future__ import annotations

import math
import os
import tempfile
import time

import numpy as np
from PySide6.QtCore import Property, Qt, QTimer, Signal, Slot
from PySide6.QtQuick import QQuickFramebufferObject

from .. import planes
from . import picking
from .camera import VIEWS, Camera
from .scene import SCENES, STYLES, color_of

CLICK_SLOP = 4              # 按下到松开移动不超过这么多像素算单击
GESTURE_START = 8           # 右键按住拖出这么多像素, 手势轮出现
GESTURE_AIM = 22            # 离中心超过这么多像素才算指向了某一格 (中心附近不选任何东西)
GESTURE_FIRE = 62           # 划到离中心这么远 (图标那一圈) 就执行, 不用松手
GESTURE_SECTORS = 8         # 0=右, 逆时针每 45 度一格: 1=右上, 2=上, 3=左上, 4=左, 5=左下, 6=下, 7=右下
PLANE_MIN_HALF = 45.0       # 基准面至少画这么大 (半边长, mm)
VIEW_GLIDE = 0.26           # 切换视角 (点视图按钮、进出草图) 用这么多秒平滑转过去, 不是瞬间跳
HISTORY_LIMIT = 30          # "上一个视图" 最多记这么多步
ORIGIN_PIXELS = 58.0        # 原点坐标系的一根轴在屏幕上画这么长 (像素): 拉近拉远都一样大
SKETCH_REACH = 6.0          # 光标离草图线的屏幕距离在这么多像素内算指着它
EMPTY3 = np.zeros((0, 3), dtype=np.float32)


def _geometry(model, hidden_sketch=None, hidden=(), body=True):
    """模型数据 → 要上传到显卡的数组, 以及 "顶点属于哪个面/边/草图" 的对照表。body=False: 实体不画 (被隐藏了)。"""
    if model.get('has_body') and body:
        verts, normals, tris = model['verts'], model['normals'], model['tris']
        vertex_face = np.zeros(len(verts), dtype=np.int64)
        vertex_face[tris.ravel()] = np.repeat(model['tri_face'].astype(np.int64), 3)
        edge_points = model['segments'].reshape(-1, 3)
        point_edge = np.repeat(model['segment_edge'].astype(np.int64), 2)
    else:
        verts = normals = edge_points = EMPTY3
        tris = np.zeros((0, 3), dtype=np.uint32)
        vertex_face = point_edge = np.zeros(0, dtype=np.int64)
    sketch_parts, sketch_owner = [], []
    for identifier, lines in (model.get('sketches') or {}).items():
        if identifier == hidden_sketch or identifier in hidden:     # 正在编辑的草图由编辑器自己画; 用户关掉显示的不画
            continue
        points = np.asarray(lines, dtype=np.float32).reshape(-1, 3)
        sketch_parts.append(points)
        sketch_owner += [identifier] * len(points)
    sketch_points = np.concatenate(sketch_parts) if sketch_parts else EMPTY3
    return ({'verts': verts, 'normals': normals, 'tris': tris, 'edge_points': edge_points,
             'sketch_points': sketch_points}, vertex_face, point_edge, sketch_owner)


class _Renderer(QQuickFramebufferObject.Renderer):
    def __init__(self):
        super().__init__()
        from .scene import Scene
        self._scene = Scene()
        self._pending = {}
        self._versions = {}
        self._frame = None
        self._shot = None
        self._item = None

    def createFramebufferObject(self, size):
        from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        fmt.setSamples(8)               # 边线细, 不开多重采样全是锯齿
        self._fbo = QOpenGLFramebufferObject(size, fmt)     # 留一个引用: 生命周期归 Qt 管, 但不能被 Python 先回收
        return self._fbo

    def synchronize(self, item):
        """界面线程此刻被挂起: 把这一帧要用的东西拷过来 (之后渲染线程不再碰控件)。"""
        self._item = item
        for name in ('geometry', 'states', 'planes', 'drawing'):
            version = item._versions[name]
            if self._versions.get(name) != version:
                self._versions[name] = version
                self._pending[name] = item._data[name]
        if 'geometry' in self._pending:
            self._pending['states'] = item._data['states']      # 几何换了, 状态数组长度也跟着变
        width, height = max(int(item.width()), 1), max(int(item.height()), 1)
        self._frame = (item._camera.matrix(width, height), tuple(item._camera.eye()), item._gl_dark(), item._grid_matrix(),
                       item._render_options())
        self._shot, item._shot_path = item._shot_path, None

    def render(self):
        from OpenGL.GL import glGetError, GL_NO_ERROR
        from PySide6.QtQuick import QQuickOpenGLUtils
        for _ in range(8):              # 清掉场景图留下的旧错误标志, 免得算到我们头上
            if glGetError() == GL_NO_ERROR:
                break
        if self._frame is None:
            return
        target = self.framebufferObject()
        pending, self._pending = self._pending, {}
        if 'geometry' in pending:
            self._scene.set_geometry(pending['geometry'])
        if 'states' in pending:
            self._scene.set_states(pending['states'])
        if 'planes' in pending:
            self._scene.set_planes(*pending['planes'])
        if 'drawing' in pending:
            self._scene.set_drawing(*pending['drawing'])
        matrix, eye, dark, grid, options = self._frame
        self._scene.render(target.width(), target.height(), matrix, eye, dark, grid, options)
        if self._shot:
            path, self._shot = self._shot, None
            saved = target.toImage().save(path)
            target.bind()               # toImage 会把绑定换到它的中转缓冲上: 不换回来之后的画面就画到别处去了
            self._item.shotSaved.emit(path if saved else '')
        QQuickOpenGLUtils.resetOpenGLState()


class Viewport(QQuickFramebufferObject):
    picked = Signal(str, object, bool)      # ('face'|'edge'|'sketch'|'plane'|'', 编号 / 特征 id / 基准面名, 是否加选)
    boxed = Signal(object, bool)            # 框选的结果 {'faces': [...], 'edges': [...], 'sketches': [...]}, 是否加选
    bandChanged = Signal()                  # 选择框出现 / 变了 / 没了
    hoverChanged = Signal(str)              # 光标下的东西的文字说明 (状态栏用)
    shotSaved = Signal(str)                 # 截图存好了 (路径; 失败为空字符串)
    sketchEdited = Signal()                 # 草图编辑器里的内容变了 (画完一笔、选中变了、拖完了)
    darkChanged = Signal()
    labelsChanged = Signal()
    axesChanged = Signal()                  # 视角转了 (左下角的坐标系跟着转)
    planesVisibleChanged = Signal()
    gestureChanged = Signal()               # 手势轮出现 / 消失 / 指向的格子变了
    gestureTriggered = Signal(int)          # 划中了第几格
    zoomChanged = Signal()                  # 局部放大: 开始等用户拖框 / 框的大小变了 / 结束

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMirrorVertically(True)
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.MiddleButton | Qt.RightButton)
        self.setAcceptHoverEvents(True)
        self._camera = Camera()
        self._dark = True
        self._model = {}
        self._selection = {'faces': [], 'edges': [], 'feature': None, 'plane': None}
        self._hover = None
        self._plane_shown = set(planes.PLANES)      # 显示着的主要基准面 (每个可以单独开关)
        self._display = {'style': 'shaded_edges', 'scene': 'auto', 'cartoon': False, 'origin': True,
                         'section': None, 'color': None, 'planes_off': False, 'body': True}
        self._names = {}                    # 特征 id → 名称 (状态栏里说光标指着哪个草图)
        self._band = None                   # 建模时左键拖出来的选择框 [x0, y0, x1, y1]
        self._band_points = []              # 现在画着的选择框的四个角 (屏幕像素)
        self.click_at = (0.0, 0.0)          # 最近一次单击的位置 (视图里的像素): 弹出的小工具条摆在它旁边
        self._hidden = set()                # 不显示的草图 / 曲线 / 参考几何体 (特征 id)
        self._history = []                  # 之前的视角 ("上一个视图")
        self._wheel_at = 0.0
        self._zoom = None                   # 局部放大: None / 'armed' 等用户拖框 / [x0, y0, x1, y1] 正在拖
        self._sketch = None                 # 正在用的草图编辑器 (SketchEditor) 或 None
        self._labels = []
        self._gesture = None                # 手势轮: None 或 [中心 x, 中心 y, 指向的格子 (-1 = 还没指向谁)]
        self._glide = None                  # 视角过渡: (开始时刻, 起点, 终点), 起终点 = (方位, 俯仰, 目标点, 距离)
        self._glide_timer = QTimer(self)
        self._glide_timer.setInterval(15)
        self._glide_timer.timeout.connect(self._glide_step)
        self._press = None
        self._shot_path = None
        self._fitted = False
        self._data, self._versions = {}, {'geometry': 0, 'states': 0, 'planes': 0, 'drawing': 0}
        self._data['geometry'], self._vertex_face, self._point_edge, self._sketch_owner = _geometry({})
        self._data['states'] = self._make_states()
        self._data['planes'] = self._make_planes()
        self._data['drawing'] = self._make_drawing()

    def createRenderer(self):
        # 留一个 Python 引用: 渲染器归 Qt 管, 但 Python 这边的包装对象先被回收的话退出时会直接 abort
        self._renderer = _Renderer()
        return self._renderer

    def _set(self, name, value):
        self._data[name] = value
        self._versions[name] += 1

    def _redraw(self):
        """内容或视角变了: 重算屏幕上的文字标注位置, 并请求重画一帧。"""
        self._update_labels()
        facing = (round(self._camera.yaw, 3), round(self._camera.pitch, 3))
        if facing != getattr(self, '_facing', None):
            self._facing = facing
            self.axesChanged.emit()
        self.update()

    @Property('QVariantList', notify=axesChanged)
    def axes(self):
        """世界坐标的 X / Y / Z 轴现在在屏幕上指向哪 → [[右, 下, 远]...] (单位向量在屏幕右、屏幕下、离开眼睛方向上的分量)。"""
        front, right, up = self._camera.basis()
        return [[float(right[index]), float(-up[index]), float(front[index])] for index in range(3)]

    # ---- 主题 / 显示开关 ----
    def _get_dark(self):
        return self._dark

    def _set_dark(self, value):
        if self._dark != bool(value):
            self._dark = bool(value)
            self._set('planes', self._make_planes())
            self._set('drawing', self._make_drawing())
            self.darkChanged.emit()
            self.update()

    dark = Property(bool, _get_dark, _set_dark, notify=darkChanged)

    def _gl_dark(self):
        """视图里的线和字用深色那套还是浅色那套: 换了布景就看布景是深是浅, 不然跟界面主题。"""
        scene = SCENES.get(self._display['scene'])
        return scene[3] if scene else self._dark

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
    def set_model(self, model):
        had_body = bool(self._model.get('has_body'))
        self._model = model or {}
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
                                                                                      self._display['body'])
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
            for identifier in chosen:
                states[owner == identifier] = 2.0
            return states
        selection, hover = self._selection, self._hover
        pointed = hover[1] if hover and hover[0] == 'sketch' else None
        sketches = np.array([2.0 if owner == selection.get('feature') else 1.0 if owner == pointed else 0.0
                             for owner in self._sketch_owner], dtype=np.float32)
        return {'faces': marks(self._vertex_face, selection['faces'], hover[1] if hover and hover[0] == 'face' else None),
                'edges': marks(self._point_edge, selection['edges'], hover[1] if hover and hover[0] == 'edge' else None),
                'sketches': sketches}

    # ---- 基准面 ----
    def plane_half(self):
        """基准面画多大 (半边长): 比零件大一圈, 零件很小或还没有时用固定大小。"""
        if self._model.get('has_body'):
            low, high = np.array(self._model['props']['bbox_min']), np.array(self._model['props']['bbox_max'])
            return max(PLANE_MIN_HALF, float(np.abs(np.concatenate([low, high])).max()) * 1.25)
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
            self.setCursor(Qt.ArrowCursor if self._sketch.tool == 'select' else Qt.CrossCursor)
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
        found = {'faces': [], 'edges': [], 'sketches': []}

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
        found['edges'] = [int(value) for value in lines(geometry['edge_points'], self._point_edge)]
        if len(geometry['verts']):
            screen, depth = self._camera.project(geometry['verts'], width, height)
            inside = picking.in_rect(screen, depth, low, high)
            faces = set(self._vertex_face[inside].tolist()) if crossing else \
                set(self._vertex_face.tolist()) - set(self._vertex_face[~inside].tolist())
            found['faces'] = sorted(int(value) for value in faces)
        if self._sketch_owner:
            names = sorted(set(self._sketch_owner))
            index = {name: number for number, name in enumerate(names)}
            hit = lines(geometry['sketch_points'], [index[name] for name in self._sketch_owner])
            found['sketches'] = [names[number] for number in hit]
        self.boxed.emit(found, additive)

    def _make_drawing(self):
        editor = self._sketch
        if editor is None:
            return EMPTY3, np.zeros(0, dtype=np.float32), np.zeros((0, 7), dtype=np.float32)
        lines, points, _ = editor.drawing()
        ends, states = [], []
        for start, end, state in lines:
            ends += [start, end]
            states += [state, state]
        line_points = planes.to_world(ends, editor.plane, editor.offset) if ends else EMPTY3
        colors = {0: 'draw', 1: 'draw_hover', 2: 'draw_chosen', 3: 'draw_draft'}
        rows = []
        if points:
            world = planes.to_world([position for position, _ in points], editor.plane, editor.offset)
            rows = [(*position, *color_of(colors[state], self._gl_dark()), 1.0) for position, (_, state) in zip(world, points)]
        return (np.asarray(line_points, dtype=np.float32), np.array(states, dtype=np.float32),
                np.array(rows, dtype=np.float32).reshape(-1, 7))

    def _grid_matrix(self):
        """网格摆在哪: 只有编辑草图时画, 摆在草图平面上; 平时没有网格。"""
        if self._sketch is None:
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
            else:
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
        if self._model.get('has_body'):
            return self._model['props']['bbox_min'], self._model['props']['bbox_max']
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

    def _glide_to(self, view, bounds=None):
        """把视角转到 view (None = 方向不变) 并把内容 (或 bounds 这个范围) 放满画面; 平滑转过去, 用户看得出是同一个
        场景转了个角度。第一次取景 (窗口刚出来) 直接到位。"""
        goal = Camera()
        goal.yaw, goal.pitch = self._camera.yaw, self._camera.pitch
        if isinstance(view, tuple):
            goal.yaw, goal.pitch = view
        elif view is not None:
            goal.set_view(view)
        low, high = bounds or self._bounds()
        goal.fit(low, high, self.width() / max(self.height(), 1.0))
        end = (goal.yaw, goal.pitch, np.array(goal.target, dtype=float), goal.distance)
        if not self._fitted or self.width() <= 0:
            self._fitted = self.width() > 0
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
        turn = (end[0] - start[0] + 180.0) % 360.0 - 180.0             # 方位角走近的那一边
        end = (start[0] + turn,) + end[1:]
        self._glide = (time.perf_counter(), start, end)
        self._glide_timer.start()

    def _apply_view(self, state):
        self._camera.yaw = (state[0] + 180.0) % 360.0 - 180.0
        self._camera.pitch, self._camera.target, self._camera.distance = state[1], np.array(state[2]), state[3]
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

    def request_shot(self, path=None):
        """让渲染线程把下一帧存成图片; 存好后发 shotSaved。"""
        if not path:
            path = os.path.join(tempfile.gettempdir(), 'genform_view_%d.png' % int(time.time() * 1000))
        self._shot_path = str(path)
        self.update()
        return self._shot_path

    def geometryChange(self, new, old):
        super().geometryChange(new, old)
        if new.width() > 0 and new.height() > 0:
            if not self._fitted:
                self._glide_to(None)
            else:
                self._update_labels()

    # ---- 拾取 ----
    def _pick(self, x, y):
        width, height = self.width(), self.height()
        hit, depth = picking.pick_depth(self._camera, x, y, width, height, self._model) if self._display['body'] else (None, np.inf)
        if (hit is None or hit[0] == 'face') and self._sketch_owner:
            # 草图线 (和曲线、参考几何体的线): 细, 所以也排在面前面; 被实体挡住的不算
            segment, gap, reach = picking.nearest_segment(self._camera, x, y, width, height, self._data['geometry']['sketch_points'])
            if segment >= 0 and gap <= SKETCH_REACH and reach <= depth * (1 + picking.EDGE_DEPTH_SLACK) + 0.05:
                return 'sketch', self._sketch_owner[segment * 2]
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
        if kind == 'plane':
            return f'{planes.NAMES[identifier]}（单击选中，再点“草图”在它上面画）'
        if kind == 'sketch':
            return f'{self._names.get(identifier, "草图")}（单击选中）'
        table = {entry['id']: entry for entry in self._model.get('edges' if kind == 'edge' else 'faces', ())}
        entry = table.get(identifier)
        if entry is None:
            return ''
        if kind == 'edge':
            names = {'line': '直边', 'circle': '圆弧边', 'curve': '曲线边'}
            extra = f'，半径 {entry["radius"]:.3g} mm' if 'radius' in entry else ''
            return f'{names[entry["type"]]}，长 {entry["length"]:.4g} mm{extra}'
        names = {'plane': '平面', 'cylinder': '圆柱面', 'cone': '圆锥面', 'sphere': '球面', 'torus': '圆环面'}
        extra = f'，半径 {entry["radius"]:.3g} mm' if 'radius' in entry else ''
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
        self._press = [event.button(), point.x(), point.y(), point.x(), point.y(), False, event.modifiers()]
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
        if not dragging and abs(point.x() - x0) + abs(point.y() - y0) > CLICK_SLOP:
            dragging = self._press[5] = True
            if button == Qt.LeftButton and not modifiers & Qt.AltModifier:
                self._band = [x0, y0, point.x(), point.y()]     # 左键拖: 拉选择框
            else:
                self._remember()
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
                self._camera.orbit(dx, dy)
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
        press, self._press = self._press, None
        if press is None:
            return
        if press[0] == Qt.RightButton:
            self._gesture_end()
            return
        point = event.position()
        if self._draws(press[0], press[6]):
            position = self._sketch_point(point.x(), point.y())
            if position is not None:
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
        hit = self._pick(point.x(), point.y())
        if hit != self._hover:
            self._hover = hit
            self._set('states', self._make_states())
            self._set('planes', self._make_planes())
            self.hoverChanged.emit(self._describe(hit))
            self.update()

    def hoverLeaveEvent(self, event):
        if self._hover is not None:
            self._hover = None
            self._set('states', self._make_states())
            self._set('planes', self._make_planes())
            self.hoverChanged.emit('')
            self.update()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        point = event.position()
        width, height = self.width(), self.height()
        origin, direction = self._camera.ray(point.x(), point.y(), width, height)
        triangle, distance = (-1, np.inf)
        if self._model.get('has_body') and self._sketch is None:
            triangle, distance = picking.ray_triangles(origin, direction, self._model['verts'], self._model['tris'])
        # 朝光标指着的那一点缩放: 指着零件就是零件表面那一点, 指着空白处就是目标点所在深度上的那一点
        if triangle < 0:
            front = self._camera.basis()[0]
            distance = self._camera.distance / max(float(direction @ front), 1e-6)
        self._stop_glide()
        if time.perf_counter() - self._wheel_at > 1.0:      # 连着滚的一串算一步
            self._remember()
        self._wheel_at = time.perf_counter()
        self._camera.zoom(0.88 ** steps, origin + direction * distance)
        self._redraw()
        event.accept()
