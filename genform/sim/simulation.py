"""仿真页 (QML 里的 sim): 开和关、问内核、上色; 其余能力在同一个包里的混入类里 (见 genform/simulation.py)。"""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Slot

from .. import i18n
from .analysis import AnalysisMixin
from .assembly import AssemblyMixin
from .livecheck import LiveCheckMixin
from .motion import MotionMixin
from .common import MODES, number, ramp
from .signals import changed, Signals


class Simulation(AnalysisMixin, AssemblyMixin, LiveCheckMixin, MotionMixin, Signals, QObject):

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._mode = ''
        self._running = ''
        self._ticket = 0
        self._static = {'fixed': [], 'loaded': [], 'force': [0.0, 0.0, -100.0], 'quality': 'medium', 'result': None, 'error': '',
                        'material': ''}
        self._drag = {'axis': 'Y', 'speed': 10.0, 'cd': 1.0, 'density': 1.225, 'result': None, 'error': ''}
        self._parts = [self._own_part()]
        self._assembly = {'clashes': None, 'pairs': 0, 'steps': None, 'error': ''}
        self._mesh_ticket = 0
        self._shown = []                # 视图里画着的别的零件: [(装配体里的序号, 网格)...]
        self._red = set()               # 装配检查标红的零件 (序号)
        self._picked = -1               # 设计树 / 视图里选中的零部件 (序号)
        self._hidden_parts = set()      # 隐藏的零部件
        self._alone_part = None         # 孤立着的零部件 (只显示它)
        self._kinds = {}                # 零件文件 → (修改时间, 物料清单里的类别…)
        self.pinned = False             # 现在开着的文档就是一个装配体 (新建 → 装配体): 这个面板关不掉, 也切不到别的仿真
        self.path = ''                  # 装配体存在哪 (.gasm)
        self.dirty = False
        self._live_init()               # 装配体的实时检查 (livecheck.py)
        self._motion_init()             # 运动副和动画 (motion.py)
        app.languageChanged.connect(self.changed)       # 换了界面语言: 面板上的字重新取一遍

    @staticmethod
    def _own_part():
        return {'name': '当前零件', 'path': '', 'move': [0.0, 0.0, 0.0], 'turn': [0.0, 0.0, 0.0], 'mirror': False}

    # ---- 开和关 ----
    @Property(str, notify=changed)
    def mode(self):
        return self._mode

    @Property(str, notify=changed)
    def running(self):
        return self._running

    @Slot(str)
    def open(self, mode):
        """打开一种仿真的面板; 已经开着的再点一次就是关。"""
        if self.pinned:
            return
        if mode == self._mode or mode not in MODES:
            self.close()
            return
        app = self.app
        if not app._leave_modes():
            return
        if mode != 'assembly' and not app.session.model.get('has_body'):
            app.notice.emit('还没有实体可以分析')
            return
        self._leave()
        self._mode = mode
        app._drop_context()
        if mode == 'assembly':
            self._show_parts()
        self._paint()
        self.changed.emit()

    @Slot()
    def close(self):
        if self._mode and not self.pinned:
            self._leave()
            self._mode = ''
            self.changed.emit()

    def pin(self):
        """开始一个装配体文档: 现在打开的零件有实体就是第一个零件, 没有就从空的开始。"""
        self._leave()
        self._picked, self._alone_part = -1, None
        self._hidden_parts = set()
        self._joints_from_file([], 0)
        self._mode, self.pinned, self.path, self.dirty = 'assembly', True, '', False
        self._parts = [self._own_part()] if self.app.session.model.get('has_body') else []
        self._assembly.update(clashes=None, steps=None, error='')
        self._show_parts()
        self.changed.emit()

    def unpin(self):
        if self.pinned:
            self.pinned = False
            self.close()

    def _leave(self):
        """离开现在这种仿真: 视图里它画的东西 (云图、别的零件、标注) 都收掉。"""
        self._live_clear()
        self._ticket += 1
        self._mesh_ticket += 1
        self._running = ''
        viewport = self.app.viewport
        if viewport is not None:
            viewport.set_extras([])
            viewport.set_overlay()

    def model_changed(self):
        """模型变了: 面的编号、算出来的结果都不作数了。"""
        self._static.update(fixed=[], loaded=[], result=None, error='')
        self._drag.update(result=None, error='')
        self._assembly.update(clashes=None, steps=None, error='')
        if self._mode:
            self._ticket += 1
            self._running = ''
            self._paint()
            self.changed.emit()

    def _ask(self, mode, data, done):
        self._ticket += 1
        ticket, self._running = self._ticket, mode
        self.changed.emit()

        def back(result, error):
            if ticket != self._ticket:      # 等结果的时候用户改了东西或关了面板
                return
            self._running = ''
            done(result, error or '')
            self._paint()
            self.changed.emit()
        self.app.session.query(mode, data, back)

    def _paint(self):
        """把现在这种仿真的结果画到视图里。"""
        viewport = self.app.viewport
        if viewport is None:
            return
        if self._mode == 'static':
            result = self._static['result']
            # 正选着面的时候不盖云图: 不然看不见选中了哪个
            if result and not self.app.session.selection.get('faces'):
                mesh = result['mesh']
                viewport.set_extras([{'verts': mesh['verts'], 'normals': mesh['normals'], 'tris': mesh['tris'], 'cover': True,
                                      'tints': ramp(mesh['stress'], result['max_stress']),
                                      'low': mesh['verts'].min(axis=0), 'high': mesh['verts'].max(axis=0)}])
            else:
                viewport.set_extras([])
        points, labels = [], []
        if self._mode == 'assembly':
            for clash in self._assembly['clashes'] or []:
                points.append(tuple(clash['center']))
                labels.append((i18n.tr('干涉') + f' {number(clash["volume"], "mm³")}', tuple(clash['center'])))
            labels += self._live_labels()           # 实时检查查出来的干涉: 红叉
        viewport.set_overlay([], points, labels)
