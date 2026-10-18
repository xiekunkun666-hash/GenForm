"""开始一张图 / 换零件 / 投影, 以及面板上改的: 图纸、比例、视图、标题栏、工具。"""
from __future__ import annotations

import numpy as np
import os
from PySide6.QtGui import QPainterPath, QPolygonF
from PySide6.QtCore import QPointF, Slot

from .. import i18n
from .common import _local, SHEETS, VIEWS


class PanelMixin:
    """开始和面板 (工程图的一部分)。"""

    # ---- 开始 / 零件 ----
    def begin(self):
        """新建一张工程图: 现在打开的零件有实体就画它, 没有就等用户选零件文件。"""
        self._ticket += 1
        self._reset()
        document = self.app.session.document
        if document.path:
            self._title['name'] = os.path.splitext(os.path.basename(document.path))[0]
        self._title['material'] = i18n.tr(document.props.get('material') or '')
        if self.app.session.model.get('has_body'):
            self.project()
        if self.view is not None:
            self.view.fit()
        self._refresh()

    @Slot(str)
    def setPart(self, where):
        path = _local(where)
        if not os.path.isfile(path) or not path.lower().endswith(('.gform', '.step', '.stp')):
            self.app.notice.emit('零件文件只认 .gform / .step / .stp')
            return
        self._source = path
        self._title['name'] = os.path.splitext(os.path.basename(path))[0]
        self._dims, self._offsets, self._selected = [], {}, -1
        self.project()
        self._touch()

    @Slot()
    def project(self):
        """让内核重新投影 (零件换了、改了以后)。"""
        self._ticket += 1
        ticket = self._ticket
        self._running, self._error = True, ''
        self.changed.emit()

        def done(result, error):
            if ticket != self._ticket:
                return
            self._running = False
            self._error = error or ''
            if result:
                self._take(result)
            self._refresh()
        self.app.session.query('drawing', {'part': {'path': self._source, 'name': self._title['name'] or '零件'},
                                           'views': [name for name, _ in VIEWS], 'hidden': True}, done)

    def _take(self, data):
        self._data = data
        self._paths, self._snaps = {}, {}
        for name, view in data['views'].items():
            paths = []
            for lines in (view['visible'], view['hidden']):
                path = QPainterPath()
                for line in lines:
                    path.addPolygon(QPolygonF([QPointF(x, -y) for x, y in line]))
                paths.append(path)
            self._paths[name] = tuple(paths)
            ends = [point for line in view['visible'] if line[0] != line[-1] for point in (line[0], line[-1])]     # 整圆的接缝不算端点
            ends += [(x, y) for x, y, _, _ in view['circles']]
            self._snaps[name] = np.asarray(ends, dtype=float).reshape(-1, 2)

    # ---- 面板上改的 ----
    @Slot(str)
    def setSheet(self, name):
        if name in SHEETS and name != self._sheet:
            self._sheet = name
            self._offsets = {}
            if self.view is not None:
                self.view.fit()
            self._touch()

    @Slot(str)
    def setScale(self, text):
        """'auto' 或一个数 (0.5 = 1:2)。"""
        try:
            value = 0.0 if text == 'auto' else float(text)
        except ValueError:
            return
        if value >= 0 and value != self._scale:
            self._scale = value
            self._offsets = {}
            self._touch()

    @Slot(str)
    def toggleView(self, name):
        if name in dict(VIEWS):
            if name in self._views:
                self._views.remove(name)
                self._dims = [dim for dim in self._dims if dim['view'] != name]
            else:
                self._views.append(name)
            self._selected, self._draft = -1, None
            self._touch()

    @Slot(str)
    def toggle(self, what):
        if what == 'hidden':
            self._hidden = not self._hidden
        elif what == 'auto':
            self._auto = not self._auto
        elif what == 'centers':
            self._centers = not self._centers
        else:
            return
        self._touch()

    @Slot(str, str)
    def setTitle(self, key, text):
        if key in self._title and self._title[key] != text:
            self._title[key] = text
            self._touch()

    @Slot(str)
    def useTool(self, name):
        self._tool = '' if name == self._tool or name != 'dimension' else name
        self._draft, self._mark = None, None
        self._refresh()

    @Slot()
    def fit(self):
        if self.view is not None:
            self.view.fit()

    @Slot()
    def resetLayout(self):
        if self._offsets:
            self._offsets = {}
            self._touch()
