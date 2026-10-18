"""界面控制器: 状态、窗口和视图接进来; 其余能力在同一个包里的几个混入类里 (见 genform/app.py 的说明)。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer

from ..sketcher import ALL_SNAPS
from ..settings import Settings
from .. import i18n
from .context import ContextMixin
from .documents import DocumentMixin
from .formpick import FormPickMixin
from .manufacture import ManufactureMixin
from .measuring import MeasureMixin
from .preview import PreviewMixin
from .selection import SelectionMixin
from .shortcuts import ShortcutMixin
from .signals import Signals
from .sketching import SketchingMixin
from .solids import SolidMixin
from .state import StateMixin
from .viewbar import ViewBarMixin
from .common import _ViewAdapter


class AppController(ViewBarMixin, StateMixin, ShortcutMixin, SolidMixin, ContextMixin, DocumentMixin, SketchingMixin,
                    ManufactureMixin, MeasureMixin, FormPickMixin, PreviewMixin, SelectionMixin, Signals, QObject):
    """QML 里的 app: 界面读的属性、按钮调的槽都在这里 (分在各个混入类里), 改模型交给 session。"""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.viewport = None
        self.window = None
        self._form = None
        self._hover = ''
        self._shown_revision = None
        self._tree_rows = None          # 设计树上一次给 QML 的样子 (见 StateMixin.tree)
        self._folder_chains = {}        # 特征 id → 它在哪几层文件夹里 (见 _build_tree)
        self._revealed = None           # 上一次替它展开过文件夹的选中特征
        self._sketch = None             # 正在编辑的草图 (SketchEditor)
        self._sketch_history = []       # 草图里每一步之前的轮廓 (草图内的撤销)
        self._sketch_seen = []          # 上一次看到的轮廓: 和现在不一样就说明刚才那一下改了东西
        self._picking_plane = False     # 点了 "草图" 但还没选基准面
        self._planes_were_visible = True    # 为了让用户选基准面临时把它们显示出来之前, 原来是不是显示着
        self._pending_tool = 'select'   # 选好基准面进草图后直接拿起哪个工具
        self._tab = 'feature'           # 工具栏现在翻在哪一页: feature / sketch
        self._collapsed = set()         # 零件树里被用户收起来的特征 (它下面的草图不显示)
        self._rapid = False             # 快速草图: 进草图不转视角, 画完一个接着选下一个基准面
        self._snaps = set(ALL_SNAPS) - {'grid'}     # 开着的草图捕捉 (所有草图共用); 网格默认关 (关着时也不画网格)
        self._outliner = None           # 草图文本的字形 (第一次用到时才建)
        self._view = {'style': 'shaded_edges', 'scene': 'auto', 'perspective': True, 'cartoon': False, 'hideAll': False,
                      'section': False, 'sectionPlane': 'XZ', 'sectionOffset': 0.0, 'sectionFlip': False}
        self._off = set()               # "隐藏/显示项目" 里关掉的 (SHOW_ITEMS 的键)
        self._views = []                # 用户存下来的视角: [(名称, 视角)...] (只在这次打开期间)
        self.settings = Settings()      # 快捷键、手势轮 (存在用户目录里, 和零件无关)
        self.api_port = 0               # AI 接口开在哪个端口 (0 = 没开); 启动时填
        i18n.set_language(self.settings.language)
        self._hidden_ids = set()        # 用户单独隐藏的草图 / 曲线 / 参考几何体 (特征 id; 只在这次打开期间)
        self._hidden_keys = set()       # 用户隐藏的面: 各张面的 _face_key (改了模型以后靠它认出还是不是那张面)
        self._isolated = None           # 孤立中: {'name': 特征名, 'keys': 原来隐藏的面, 'ids': 原来隐藏的线} (退出时恢复)
        self._solid_cache = None
        self._context = None            # 视图里刚点中的东西: {'kind', 'id', 'feature', 'faces' 这个位置一路穿过的面}
        self._measure = None            # 正在测量: {'items': [最多两个对象], 'result': 内核算出来的, 'error': ''}
        self._preview_ticket = 0        # 参数面板的预览: 第几次试算 (回来的结果不是最新这次的就不要)
        self._preview_note = ''         # 预览试算没成的原因 (面板上显示)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(160)        # 连着打字时等停下来再算
        self._preview_timer.timeout.connect(self._run_preview)
        from ..simulation import Simulation
        self.sim = Simulation(self)     # 仿真页 (静力、风阻、装配体); 界面上叫 sim
        from ..drawing import Drawing
        self.drawing = Drawing(self)    # 工程图; 界面上叫 drawing
        self._init_manufacture()        # 绑定工艺、设计检查、设计规则
        self._kind = 'part'             # 现在开着的是哪种文档: part 零件 / assembly 装配体 / drawing 工程图
        self._start = True              # 开着开始页: 刚打开软件还没选新建 / 打开哪个文档 (带文件启动、拖进文件、AI 接口改模型时收起)
        self._return = ''               # 从哪个装配体过来的 (打开零件 / 回到零件以后, 零件页上 "返回装配体" 回这个文件)
        session.on_progress = self.progressChanged.emit
        session.view = _ViewAdapter(self)
        session.listen(self._on_session)
        session.later = lambda milliseconds, function: QTimer.singleShot(milliseconds, function)
        self.changed.connect(self._refresh_tree)       # 设计树: 内容真变了才让 QML 重建
        self.sketchChanged.connect(self._refresh_tree)

    # ---- 窗口和三维视图接进来 ----
    def attach_window(self, window):
        """无边框窗口: 装上系统级的最大化 / 贴边 / 阴影行为。"""
        self.window = window
        from ..win32_frame import enable_native_frame, round_corners
        enable_native_frame(window)
        round_corners(window)

    def attach_viewport(self, viewport):
        self.viewport = viewport
        viewport.picked.connect(self._on_picked)
        viewport.boxed.connect(self._on_boxed)
        viewport.hoverChanged.connect(self._on_hover)
        viewport.sketchEdited.connect(self._on_sketch_edited)
        viewport.gestureTriggered.connect(self.runGesture)
        viewport.menuRequested.connect(self._on_view_menu)
        viewport.planesVisibleChanged.connect(self._planes_toggled)
        viewport.handleDragged.connect(self._on_handle)
        viewport.joint_axis = lambda index: self.sim.joint_axis(index) if self._kind == 'assembly' else None
        viewport.jointDragged.connect(lambda index, step: self.sim.drag_joint(index, step))
        viewport.jointReleased.connect(self.sim.settleJoint)
        self._apply_view(rebuild=False)
        viewport.set_model(self.session.model)

    def _on_session(self):
        if self.viewport is not None and self._shown_revision != (self.session.model_revision, id(self.session.model)):
            self._shown_revision = (self.session.model_revision, id(self.session.model))
            self.viewport.set_hidden(self._hidden_features(), rebuild=False)
            self.viewport.set_hidden_faces(self._hidden_faces(), rebuild=False)
            self.viewport.set_names({feature['id']: feature['name'] for feature in self.session.document.features})
            self.viewport.set_model(self.session.model)
            self._drop_context()
            if self._measure is not None:           # 模型变了: 原来选的面和边的编号不作数了
                self._measure.update(items=[], result=None, error='')
                self._show_measure()
            self.sim.model_changed()
            self._check_model_changed()
            if self._form is not None and self._sketch is None:
                self._preview()             # 面板还开着 (编辑特征时点了确定): 预览跟着新的模型重算
                self._show_handle()
            self.viewport.set_selection(self.session.selection)
            self._refresh_form_info()
        self._push_appearance()
        self.changed.emit()
