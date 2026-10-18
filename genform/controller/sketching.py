"""基准面和草图: 选基准面进草图、工具、完成 / 取消、草图里的撤销、属性管理器。"""
from __future__ import annotations

import copy
from PySide6.QtCore import Property, Slot

from ..i18n import localized
from .. import planes, sketchgeom
from .common import DRAW_TOOLS, TOOL_HINTS
from .signals import changed


class SketchingMixin:
    """基准面和草图 (控制器的一部分)。"""

    # ---- 基准面和草图 ----
    @Slot(str)
    def selectPlane(self, name):
        """在左侧列表里点了一个基准面。"""
        if name not in planes.PLANES or self._sketch is not None:
            return
        if self._picking_plane:
            self.sketchOn(name)
            return
        selection = self.session.selection
        selection['plane'] = None if selection.get('plane') == name else name
        selection['faces'], selection['edges'] = [], []
        self._push_selection()

    @Slot()
    def startSketch(self):
        """点了 "草图绘制": 已经选着基准面就直接在它上面画, 不然先让用户选一个。
        已经在草图里再点就是退出草图 (保存), 和 SOLIDWORKS 的同一个按钮一样。"""
        if self._sketch is not None:
            self.finishSketch()
            return
        self._pending_tool = 'select'
        self._begin_sketch()

    @Slot(str)
    def useSketchTool(self, tool):
        """点了草图页里的画图工具。在草图里: 换工具。不在草图里: 先选基准面, 进草图后直接就是这个工具 —
        不用先点 "草图" 再点工具。"""
        if self._sketch is not None:
            self.setSketchTool(tool)
            return
        if tool not in DRAW_TOOLS:
            self.notice.emit('这个工具是改已有图形的：先进入草图')
            return
        self._pending_tool = tool
        self._begin_sketch()

    def _begin_sketch(self):
        self._close_form()
        plane = self.session.selection.get('plane')
        chosen = self.session.selection.get('feature')
        if not plane and any(f['id'] == chosen and f['type'] == 'plane' for f in self.session.document.features):
            plane = chosen                      # 设计树里选着一个基准面特征
        if plane:
            self.sketchOn(plane)
            return
        faces = self.session.selection.get('faces') or []
        if len(faces) == 1 and self._sketch_on_face(faces[0]):     # 选着零件上的一个平面: 直接画在它上面
            return
        self._picking_plane = True
        if self.viewport is not None:
            self._planes_were_visible = self.viewport.planesVisible
            self.viewport.planesVisible = True
        self.sketchChanged.emit()

    @Slot(str)
    def sketchOn(self, name):
        """在基准面 name 上开始画一个新草图。"""
        self._sketch_at(name)

    def _sketch_on_face(self, identifier):
        """在实体的一个平面上开始画草图 → 成没成。正对着坐标轴的面: 用对应的基准面加偏移 (草图的原点还是零件的原点);
        斜的面: 先按它建一个基准面特征, 草图画在那上面。"""
        face = next((item for item in self.session.model.get('faces', ()) if item['id'] == identifier), None)
        if face is None or face.get('normal') is None:
            self.notice.emit('这个面不是平的：草图只能画在平面上')
            return False
        normal, centre = [float(value) for value in face['normal']], [float(value) for value in face['center']]
        for name in planes.PLANES:
            axis = planes.frame(name)[3]
            along = sum(a * b for a, b in zip(normal, axis))
            if abs(abs(along) - 1.0) < 1e-6:
                self._sketch_at(name, sum(a * b for a, b in zip(centre, axis)))
                return True

        def made(result):
            if result.get('ok') and result.get('id'):
                self._sketch_at(result['id'])
        self._stop_picking_plane()
        self._run('plane', {'origin': [centre], 'normal': [normal], 'offset': 0.0, 'angle': 0.0}, made)
        return True

    def _sketch_at(self, name, offset=0.0):
        if self._sketch is not None:
            return
        count = sum(1 for feature in self.session.document.features if feature['type'] == 'sketch') + 1
        try:
            editor = self._sketch_editor(name, name=f'草图{count}', offset=round(float(offset), 6) + 0.0)
        except ValueError as error:
            self.notice.emit(str(error))
            return
        editor.set_tool(self._pending_tool)
        if not self._rapid:                 # 快速草图: 记着工具, 画完这个草图接着用
            self._pending_tool = 'select'
        self._enter_sketch(editor)

    def _stop_picking_plane(self):
        if self._picking_plane:
            self._picking_plane = False
            if self.viewport is not None:
                self.viewport.planesVisible = self._planes_were_visible
            self.sketchChanged.emit()

    def _enter_sketch(self, editor):
        self._close_form()
        self.sim.close()
        self._stop_picking_plane()
        self._sketch, self._sketch_history = editor, []
        self._tab = 'sketch'
        self._sketch_seen = copy.deepcopy(editor.shapes)
        if self._outliner is None:
            from ..textpath import Outliner
            self._outliner = Outliner()
        editor.outliner = self._outliner
        editor.snaps = self._snaps
        # 实体的边投影到草图平面 (转换实体引用用): 进草图时不算, 等真选了那个工具再算 — 边多的零件要算好一会儿
        editor.references = (sketchgeom.project_edges(self.session.model, editor.plane, editor.offset)
                             if editor.tool == 'convert' else [])
        self.session.selection.update(faces=[], edges=[], plane=None)
        if self.viewport is not None:
            self.viewport.set_selection(self.session.selection)
            # 已经有实体了就留在现在的视角 (在零件的面上画, 要看得见零件); 空零件的第一个草图才转到正对着基准面
            self._sketch_turned = not self._rapid and not self.session.model.get('has_body')
            self.viewport.set_sketch(editor, turn=self._sketch_turned)
        self._sketch_form()
        self.sketchChanged.emit()
        self.changed.emit()

    @Slot(str)
    def setSketchTool(self, tool):
        if self._sketch is not None:
            if tool == 'convert':       # 侧影 / 交叉曲线用过这个位置: 换回实体的边
                self._sketch.references = sketchgeom.project_edges(self.session.model, self._sketch.plane, self._sketch.offset)
            self._sketch.set_tool(tool)
            self._sketch_changed()

    @Slot()
    def finishSketch(self):
        self._finish_sketch()

    def _finish_sketch(self, then=None):
        """退出草图并保存。then: 存好之后接着做的事 (在草图里直接点 "拉伸凸台" 时用)。"""
        editor = self._sketch
        if editor is None:
            return
        if not editor.shapes:
            self.notice.emit('草图里还没有图形：先画一个，或点右上角的 ✕ 放弃这个草图')
            return
        again = self._rapid and then is None and self._pending_tool in DRAW_TOOLS
        self._exit_sketch()

        def saved(result):
            identifier = result.get('id') or editor.feature
            if identifier:
                self.selectFeature(identifier)      # 选中刚画的草图: 接着点 "拉伸" 默认拉的就是它
            if then and result.get('ok'):
                then()
            elif again and self._sketch is None:    # 快速草图: 接着等用户点下一个基准面
                self.session.selection['plane'] = None
                self._tab = 'sketch'
                self._begin_sketch()

        if editor.feature:
            self._run('edit_feature', {'id': editor.feature, 'params': editor.params()}, saved)
        else:
            self._run('sketch', editor.params(), saved)

    @Slot()
    def cancelSketch(self):
        if self._sketch is not None:
            self._exit_sketch()

    def _exit_sketch(self):
        self._sketch, self._sketch_history = None, []
        self._form = None
        self._tab = 'feature'           # 画完草图下一步多半是拉伸: 工具栏翻回特征页
        if self.viewport is not None:
            self.viewport.set_sketch(None)
            if not self._rapid and getattr(self, '_sketch_turned', True):
                self.viewport.setView('iso')        # 进草图时转成了正对基准面: 出来转回等轴测。进来时没转 (在零件上画) 的, 出来也不动视角
        self.formChanged.emit()
        self.sketchChanged.emit()
        self.changed.emit()

    def _sketch_form(self):
        """草图里的右侧面板: 选中了一个轮廓才出现 (填它的精确尺寸), 没选中时不占地方。"""
        panel = self._sketch.panel()
        # side: 选中图形的参数 — 在右边的属性栏里 (sketchProps), 左边不再放一份
        self._form = None if panel is None or panel.get('side') else dict(panel, kind='sketch', editing='')
        self.formChanged.emit()

    def _sketch_changed(self):
        """这边 (按钮、面板、快捷键) 改了草图: 记进草图自己的撤销历史, 把编辑器留的话告诉用户, 让视图和面板跟上。"""
        editor = self._sketch
        if editor is None:
            return
        if self._sketch_seen != editor.shapes:
            self._sketch_history.append(self._sketch_seen)
            self._sketch_seen = copy.deepcopy(editor.shapes)
        if editor.message:
            self.notice.emit(editor.message)
            editor.message = ''
        self._sync_sketch()

    def _sync_sketch(self):
        """草图编辑器里的东西被这边改了 (工具、尺寸、撤销): 让视图和面板跟上。"""
        if self.viewport is not None:
            self.viewport.refresh_sketch()
        self._sketch_form()
        self.sketchChanged.emit()
        self.changed.emit()

    def _on_sketch_edited(self):
        """视图里的鼠标操作改了草图 (按下 / 松开时各来一次)。"""
        editor = self._sketch
        if editor is None:
            return
        last = self._sketch_seen
        if last != editor.shapes:
            self._sketch_history.append(last)
        self._sketch_seen = copy.deepcopy(editor.shapes)
        if editor.message:
            self.notice.emit(editor.message)
            editor.message = ''
        self._sketch_form()
        self.sketchChanged.emit()
        self.changed.emit()
        if editor.clicked:                  # 单击选中了图形: 旁边弹出小工具条
            editor.clicked = False
            self._context = {'kind': 'shapes', 'id': '', 'feature': None, 'faces': []}
            self.contextRequested.emit(*self.viewport.click_at)
        elif self._context is not None:
            self._drop_context()

    @Property('QVariant', notify=changed)
    @localized
    def sketchProps(self):
        """草图里选中图形时左栏 PropertyManager 页的内容: 现有几何关系、能加的关系、选项、参数、额外参数; 没选中是 null。"""
        editor = self._sketch
        info = editor.properties() if editor is not None else None
        if info is not None:
            # 换了选中的 / 换了工具 / 点了关系图标就切到属性页 (key 变空回设计树)
            info['key'] = ('rel:' + editor.relation) if editor.relation else ('tool:' + info['tool']) if info.get('tool') \
                else ','.join(str(index) for index in sorted(editor.selection)) + (f':s{editor.edge[1]}' if editor._edge() else '')
            if info.get('tool'):
                info['note'] = TOOL_HINTS.get(info['tool'], '') + '\n' + '点 ✓ 或按 Esc 结束，回到选择。'
            info.setdefault('actions', [])
            info.setdefault('note', '')
        return info

    @Slot(str)
    def selectSketchRelation(self, ident):
        """视图里点了一个几何关系小图标: 选中它, 属性管理器里显示它 (Delete 删掉)。"""
        if self._sketch is None:
            return
        self._sketch.select_relation(ident)
        self._drop_context()
        self._sync_sketch()

    @Slot(str)
    def sketchAction(self, action):
        """草图里的小工具条 / 属性栏上点了一个按钮。"""
        editor = self._sketch
        if editor is None:
            return
        if action == 'exit':
            self._drop_context()
            self.finishSketch()
            return
        if action == 'zoom':
            box = editor.selection_bounds()
            if box is not None and self.viewport is not None:
                corners = planes.to_world([box[0], box[1], (box[0][0], box[1][1]), (box[1][0], box[0][1])], editor.plane, editor.offset)
                self.viewport.zoom_to(corners.min(axis=0), corners.max(axis=0))
            return
        if action == 'ok':
            editor.finish_tool()
        elif action == 'delete_relation':
            editor.delete_relation()
        elif action.startswith('rel:'):
            editor.relate_now(action[4:])
        elif action.startswith('flag:'):
            editor.toggle_flag(action[5:])
        elif action == 'dimension':
            editor.dimension_selected()
        elif action == 'select_other':
            editor.select_other()
        elif action == 'delete':
            editor.key('delete')
        if action not in ('select_other',) and not action.startswith('flag:'):
            self._drop_context()
        self._sketch_changed()
