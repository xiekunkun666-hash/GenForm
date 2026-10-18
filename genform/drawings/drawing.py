"""工程图 (QML 里的 drawing): 状态和刷新; 其余能力在同一个包里的几个混入类里 (见 genform/drawing.py)。"""
from __future__ import annotations

import datetime
from PySide6.QtCore import QObject

from .files import FileMixin
from .layout import LayoutMixin
from .mouse import MouseMixin
from .panel import PanelMixin
from .signals import Signals
from .common import TITLE_FIELDS


class Drawing(PanelMixin, LayoutMixin, MouseMixin, FileMixin, Signals, QObject):

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.view = None                    # 界面上的图纸 (view/sheet.SheetView)
        self._ticket = 0
        self._reset()
        app.languageChanged.connect(self._refresh)

    def _reset(self):
        self.path = ''                      # 这张工程图存在哪 (.gdrw)
        self.dirty = False
        self._source = ''                   # 零件文件; '' = 现在打开的那个零件
        self._sheet = 'A3'
        self._scale = 0.0                   # 0 = 自动
        self._views = ['front', 'top', 'left', 'iso']
        self._offsets = {}                  # 视图名 → [dx, dy] (mm): 用户把它拖开了多少
        self._hidden = True
        self._auto = True                   # 自动标长宽高
        self._centers = True                # 圆的中心线
        self._dims = []                     # 手标的尺寸
        self._title = {key: '' for key, _ in TITLE_FIELDS}
        self._title['date'] = datetime.date.today().isoformat()
        self._data = None                   # 内核算回来的投影
        self._paths = {}                    # 视图名 → (看得见的线, 被挡住的线) 拼好的路径 (视图自己的坐标, y 已经翻成向下)
        self._snaps = {}                    # 视图名 → 可以吸住的点 (N×2)
        self._error = ''
        self._running = False
        self._tool = ''                     # 'dimension' = 正在标尺寸
        self._draft = None                  # 标到一半的尺寸: {'view', 'a', 'b'?, 'at'?}
        self._mark = None                   # 鼠标现在吸住的点 (图纸坐标)
        self._selected = -1                 # 选中的那个手标尺寸
        self._placed = {}                   # 上一次 compose 排出来的各视图: 名 → (中心 x, y, 比例, 盒子中心 bx, by)
        self._handles = []                  # 上一次 compose 里各个手标尺寸的数字在哪: [(第几个, x, y)]
        self._composed = None

    def attach(self, view):
        self.view = view
        if view is not None:
            view.owner = self

    def _refresh(self):
        self._composed = None
        if self.view is not None:
            self.view.update()
        self.changed.emit()

    def _touch(self):
        self.dirty = True
        self._refresh()
        self.app.changed.emit()             # 标题上的 * 号
