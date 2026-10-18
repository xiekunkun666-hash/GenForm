"""执行命令、撤销重做、新建打开保存导出、特征列表上的操作、键盘 (Esc / 回车 / Delete)。"""
from __future__ import annotations

import copy
import os
from PySide6.QtCore import Property, Slot

from ..document import DocumentError
from .common import _local
from .signals import startChanged

RECENT_KINDS = {'.gform': 'part', '.gasm': 'assembly', '.gdrw': 'drawing'}


class DocumentMixin:
    """执行命令 (控制器的一部分)。"""

    # ---- 开始页 (刚打开软件: 选新建零件 / 装配体 / 工程图, 或者打开最近的文件) ----
    @Property(bool, notify=startChanged)
    def startPage(self):
        return self._start

    @Property('QVariantList', notify=startChanged)
    def recentFiles(self):
        """最近的文件 (还在的): [{path, name, folder, kind, time}...]。"""
        import time
        rows = []
        for file in self.settings.recent:
            kind = RECENT_KINDS.get(os.path.splitext(file)[1].lower())
            if kind is None or not os.path.isfile(file):
                continue
            rows.append({'path': file, 'name': os.path.splitext(os.path.basename(file))[0], 'folder': os.path.dirname(file),
                         'kind': kind, 'time': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(file)))})
        return rows

    def _set_start(self, shown):
        if shown != self._start:
            self._start = shown
            self.startChanged.emit()

    @Slot()
    def closeStart(self):
        self._set_start(False)

    @Slot()
    def showStart(self):
        """点标题栏左上角的标志: 回到开始页 (开着的文档不动, 选了别的才换)。"""
        if self._sketch is None:
            self._set_start(True)

    @Slot(str)
    def forgetRecent(self, path):
        self.settings.forget(_local(path))
        self.startChanged.emit()

    def _remember(self, path):
        if path and os.path.isfile(path):
            self.settings.remember(path)
            self.startChanged.emit()

    # ---- 执行命令 ----
    def _run(self, name, args=None, done=None):
        def reply(result):
            if not result.get('ok'):
                self.notice.emit(result.get('error', '操作失败'))
            if done:
                done(result)
            self.changed.emit()
        self.session.execute(name, args or {}, reply)

    def _leave_modes(self):
        """做别的事之前: 关掉参数面板, 不再等着选基准面。正在编辑草图时不许切走 (返回 False)。"""
        if self._sketch is not None:
            self.notice.emit('正在编辑草图：先点“完成草图”或“放弃”')
            return False
        self._stop_measure()
        self.sim.close()
        self._close_form()
        self._stop_picking_plane()
        return True

    @Slot()
    def undo(self):
        if self._sketch is not None:
            if self._sketch_history:
                self._sketch.shapes = self._sketch_history.pop()
                self._sketch_seen = copy.deepcopy(self._sketch.shapes)
                self._sketch.selected = self._sketch.hover = self._sketch.draft = None
                self._sync_sketch()
            return
        self._close_form()
        self._run('undo')

    @Slot()
    def redo(self):
        if self._sketch is None:
            self._close_form()
            self._run('redo')

    @Slot()
    def newDocument(self):
        if self._leave_modes():
            self._run('new_document')

    @Slot(str)
    def openDocument(self, path):
        """按扩展名打开: .gform 零件 / .gasm 装配体 / .gdrw 工程图 / .step .stp 导入成新零件。"""
        if not self._leave_modes():
            return
        self._set_return('')                    # 打开了别的文档: 不再是 "从装配体过来的" (打开零件那里会再记上)
        self._set_start(False)
        target = _local(path)
        kind = os.path.splitext(target)[1].lower()
        if kind == '.gasm':
            self._set_kind('part')
            self._set_kind('assembly')
            self.sim.pin()
            if self.sim.openAssembly(target):
                self._remember(target)
            else:
                self._set_kind('part')
        elif kind == '.gdrw':
            self._set_kind('drawing')
            if self.drawing.open(target):
                self._remember(target)
            else:
                self._set_kind('part')
        elif kind in ('.step', '.stp'):
            self._set_kind('part')
            self._open_step(target)
        else:
            self._set_kind('part')
            self._run('open_document', {'path': target}, lambda result: result.get('ok') and self._remember(target))

    def _open_step(self, target):
        """别的 CAD 的 STEP: 开一个新零件, 第一个特征是 "导入实体" (文档里只记路径, 可以接着切除、打孔)。"""
        name = os.path.splitext(os.path.basename(target))[0]
        self.notice.emit(f'正在导入 {os.path.basename(target)}，大文件要等几十秒')
        self._run('new_document', {}, lambda result: result.get('ok') and self._run(
            'import_step', {'path': target, 'name': name}, lambda done: done.get('ok') and self._remember(target)))

    @Slot('QVariantList')
    def dropFiles(self, paths):
        """文件拖进窗口 (和 SOLIDWORKS 一样): 有 .gasm / .gdrw 就打开第一个; 装配体里拖的零件 (.gform / .step / .stp)
        一个个插进来当零部件; 零件里拖 .gform 就打开它, 拖 .step 就开一个导入它的新零件。"""
        files = [_local(path.toString() if hasattr(path, 'toString') else path) for path in paths]
        files = [os.path.normpath(path) for path in files if os.path.isfile(path)]
        kinds = [os.path.splitext(path)[1].lower() for path in files]
        documents = [path for path, kind in zip(files, kinds) if kind in ('.gasm', '.gdrw')]
        parts = [path for path, kind in zip(files, kinds) if kind in ('.gform', '.step', '.stp')]
        if documents:
            self.openDocument(documents[0])
        elif self._kind == 'assembly' and parts:
            for path in parts:
                self.sim.addPart(path)
        elif any(path.lower().endswith('.gform') for path in parts):
            self.openDocument(next(path for path in parts if path.lower().endswith('.gform')))
        elif parts:                             # 零件里拖 STEP: 和打开一样, 开一个导入它的新零件
            self.openDocument(parts[0])
        else:
            self.notice.emit('只认 GenForm 文件 (.gform / .gasm / .gdrw) 和 STEP (.step / .stp)')

    @Slot(str)
    def saveDocument(self, path):
        if self._kind == 'assembly':
            self.sim.saveAssembly(_local(path))
            self._remember(self.sim.path)
        elif self._kind == 'drawing':
            self.drawing.save(_local(path))
            self._remember(self.drawing.path)
        else:
            self._run('save_document', {'path': _local(path)} if path else {},
                      lambda result: result.get('ok') and self._remember(result.get('path') or _local(path)))

    @Slot(str)
    def exportModel(self, path):
        target = _local(path)
        if self._kind == 'assembly':
            self.sim.exportAssembly(target)
            return
        if self._kind == 'drawing':
            self.drawing.export(target)
            return
        self._run('export', {'path': target},
                  lambda result: result.get('ok') and self.notice.emit(f'已导出到 {target}'))

    @Slot(str)
    def setView(self, name):
        if self.viewport is not None:
            self.viewport.setView(name)

    @Slot()
    def toggleMaximize(self):
        from ..win32_frame import native_max_toggle
        native_max_toggle(self.window)

    # ---- 特征列表上的操作 ----
    @Slot(str)
    def selectFeature(self, identifier):
        self.session.selection['feature'] = identifier or None
        self._push_selection()

    @Slot(str)
    def deleteFeature(self, identifier):
        if self._leave_modes():
            self._run('delete_feature', {'id': identifier})

    @Slot(str)
    def toggleSuppress(self, identifier):
        try:
            suppressed = bool(self.session.document.find(identifier).get('suppressed'))
        except DocumentError as error:
            self.notice.emit(str(error))
            return
        self._run('suppress_feature', {'id': identifier, 'suppressed': not suppressed})

    @Slot(int)
    def rollbackTo(self, count):
        self._run('rollback', {'count': count} if count >= 0 else {})

    # ---- 键盘 (QML 的快捷键转过来) ----
    @Slot()
    def escape(self):
        if self._kind == 'drawing':
            self.drawing.cancel()
            return
        if self.viewport is not None and self.viewport.cancel_zoom():
            return
        if self._measure is not None:
            self._stop_measure()
            return
        if self.sim.mode:
            self.sim.close()
            return
        if self._sketch is not None:
            if self._sketch.key('escape'):
                self._sync_sketch()
            return                          # 草图里按到头也不退出: 退出草图要点 "完成" 或 "放弃", 免得误触丢东西
        if self._picking_plane:
            self._pending_tool = 'select'       # 快速草图连着画的那一串到此为止
            self._stop_picking_plane()
            return
        if self._form is not None:
            self._close_form()
            return
        self.session.selection.update(faces=[], edges=[], plane=None)
        self._push_selection()

    @Slot()
    def enterKey(self):
        if self._sketch is not None and self._sketch.key('enter'):
            self._sketch_changed()

    @Slot()
    def deleteSelected(self):
        if self._sketch is not None:
            if self._sketch.key('delete'):
                self._sketch_changed()
            return
        identifier = self.session.selection.get('feature')
        if identifier:
            self.deleteFeature(identifier)
