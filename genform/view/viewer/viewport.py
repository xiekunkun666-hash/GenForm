"""三维视图 (QML 里的 Viewport): 状态、主题、重画; 其余能力在同一个包里的几个混入类里 (见 genform/view/viewport.py)。"""
from __future__ import annotations

from PySide6.QtCore import Property, Qt, QTimer
from PySide6.QtQuick import QQuickFramebufferObject

from ..camera import Camera
from ..scene import SCENES
from ... import planes
from .display import DisplayMixin
from .mouse import MouseMixin
from .overlays import OverlayMixin
from .signals import axesChanged, darkChanged, Signals
from .viewing import ViewingMixin
from .renderer import _Renderer
from .common import _geometry


MOTION_SETTLE = 0.18          # 视角停下来多久算停 (秒), 停了才画装配体零件的边线


class Viewport(DisplayMixin, OverlayMixin, ViewingMixin, MouseMixin, Signals, QQuickFramebufferObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMirrorVertically(True)
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.MiddleButton | Qt.RightButton)
        self.setAcceptHoverEvents(True)
        self._camera = Camera()
        self._pivot = None              # 这次拖动绕着转的点 (None = 画面中心)
        self._wheel_anchor = None       # 这一串滚轮缩放朝着的点: (光标 x, y, 三维点)
        self._dark = True
        self._model = {}                    # 画出来、点得着的模型 (去掉了被隐藏的实体块)
        self._full = {}                     # 会话给的完整模型
        self._hidden_faces = set()          # 被隐藏的实体块上的面 (编号)
        self._feature_colors = {}           # 单独上了色的特征: {特征 id: (r, g, b)} — 它做出来的面用这个颜色
        self._feature_opacity = {}          # 半透明的特征 (玻璃): {特征 id: 0~1}
        self._selection = {'faces': [], 'edges': [], 'feature': None, 'plane': None}
        self._hover = None
        self._plane_shown = set(planes.PLANES)      # 显示着的主要基准面 (每个可以单独开关)
        self._display = {'style': 'shaded_edges', 'scene': 'auto', 'cartoon': False, 'origin': True,
                         'section': None, 'color': None, 'planes_off': False, 'body': True}
        self._names = {}                    # 特征 id → 名称 (状态栏里说光标指着哪个草图)
        self._band = None                   # 建模时左键拖出来的选择框 [x0, y0, x1, y1]
        self._band_points = []              # 现在画着的选择框的四个角 (屏幕像素)
        self.click_at = (0.0, 0.0)          # 最近一次单击的位置 (视图里的像素): 弹出的小工具条摆在它旁边
        self.pick_vertices = False          # 顶点也能点 (测量时开)
        self._handle = None                 # 拉伸的拖动箭头: (起点, 单位方向, 箭头的头离起点多远); None = 没有
        self._handle_drag = False
        self.joint_axis = None              # 装配体: 零部件序号 → 它跟着动的运动副 (类型, 轴上一点, 方向) 或 None (控制器给)
        self._joint_drag = None             # 正按住车门拖: {'index', 'kind', 'origin', 'axis', 'point' 按下的那一点, 'turned'}
        self._overlay = ([], [], [])        # 测量的标注: 线段 [(起点, 终点)...], 点 [...], 文字 [(内容, 位置)...] (都是三维坐标)
        self._hidden = set()                # 不显示的草图 / 曲线 / 参考几何体 (特征 id)
        self._history = []                  # 之前的视角 ("上一个视图")
        self._wheel_at = 0.0
        self._zoom = None                   # 局部放大: None / 'armed' 等用户拖框 / [x0, y0, x1, y1] 正在拖
        self._sketch = None                 # 正在用的草图编辑器 (SketchEditor) 或 None
        self._labels = []
        self._gesture = None                # 手势轮: None 或 [中心 x, 中心 y, 指向的格子 (-1 = 还没指向谁)]
        self._glide = None                  # 视角过渡: (开始时刻, 起点, 终点), 起终点 = (方位, 俯仰, 目标点, 距离)
        self._hover_held = False            # 截图中: 先不按光标找悬停 (mouse.clear_hover)
        self._hover_wait = None             # 视角过渡中光标移到了这里 (视图里的像素): 转完再看它指着什么
        self._glide_timer = QTimer(self)
        self._glide_timer.setInterval(15)
        self._glide_timer.timeout.connect(self._glide_step)
        self._press = None
        self._shot_path = None
        self._fitted = False
        self._data, self._versions = {'extras': []}, {'geometry': 0, 'states': 0, 'planes': 0, 'drawing': 0, 'extras': 0}
        self._data['geometry'], self._vertex_face, self._point_edge, self._sketch_owner = _geometry({})
        self._data['states'] = self._make_states()
        self._data['planes'] = self._make_planes()
        self._data['drawing'] = self._make_drawing()

    def createRenderer(self):
        # 留一个 Python 引用: 渲染器归 Qt 管, 但 Python 这边的包装对象先被回收的话退出时会直接 abort
        self._renderer = _Renderer()
        return self._renderer

    def _note_motion(self):
        """视角在变 (滚轮缩放、拖着转 / 平移、视图定向的动画): 这几帧装配体零件的边线先不画 (边线比面还费显卡),
        停下来 MOTION_SETTLE 秒以后补画一帧带边线的。"""
        camera = self._camera
        seen = (camera.yaw, camera.pitch, camera.distance, tuple(camera.target), camera.perspective, self.width(), self.height())
        if seen == getattr(self, '_motion_seen', None):
            return
        first = getattr(self, '_motion_seen', None) is None
        self._motion_seen = seen
        if first:
            return
        self._moving = True
        timer = getattr(self, '_settle_timer', None)
        if timer is None:
            timer = self._settle_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._settled)
        timer.start(int(MOTION_SETTLE * 1000))

    def _settled(self):
        self._moving = False
        self.update()

    def _set(self, name, value):
        self._data[name] = value
        self._versions[name] += 1

    def _redraw(self):
        """内容或视角变了: 重算屏幕上的文字标注位置, 并请求重画一帧。"""
        self._note_motion()
        self._update_labels()
        facing = (round(self._camera.yaw, 3), round(self._camera.pitch, 3))
        if self._handle is not None and self._sketch is None:
            # 拉伸的箭头: 头的大小按屏幕像素定, 缩放、转视角以后要照新的样子重画 (不然放大了它也跟着变成一大坨)
            seen = (facing, round(self._camera.distance, 6), self.width(), self.height())
            if seen != getattr(self, '_handle_seen', None):
                self._handle_seen = seen
                self._set('drawing', self._make_drawing())
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
