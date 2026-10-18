"""小工具条和右键菜单: 特征 / 设计树各行 / 视图里点中的东西能做什么, 孤立, 换草图平面。"""
from __future__ import annotations

from PySide6.QtCore import Property, Slot

from ..sketcher import SketchEditor
from ..i18n import localized
from .. import features as table, planes
from .common import HOLE_KINDS
from .signals import changed, sketchChanged


class ContextMixin:
    """小工具条和右键菜单 (控制器的一部分)。"""

    def _context_items(self, identifier, scene=None):
        """小工具条上的按钮: [{'id', 'icon', 'title', 'tip'}...]。scene: 在视图里点出来的 (多几项和面 / 边有关的)。"""
        rows = []

        def add(action, icon, title, tip):
            rows.append({'id': action, 'icon': icon, 'title': title, 'tip': f'{title}：{tip}'})

        if scene is not None and scene['kind'] == 'plane':
            add('plane_sketch', 'sketch', '草图绘制', '在这个基准面上画草图')
            add('normal', 'normal', '正视于', '把视角转到正对着它')
            add('plane_hide', 'eye_off', '隐藏', '不显示三个主要基准面（视图上方“隐藏/显示项目”里可以再打开）')
            return rows
        feature = self._find(identifier)
        document = self.session.document
        if feature is not None:
            kind = feature['type']
            hole = kind in HOLE_KINDS and self._source_sketch(feature) is not None
            if kind == 'sketch':
                add('edit_sketch', 'sketch', '编辑草图', '进入这个草图接着画')
                add('sketch_plane', 'plane', '编辑草图平面', '把这个草图换到另一个基准面上')
            else:
                add('edit', 'edit', '编辑特征', '改这个特征的参数')
                if self._source_sketch(feature) is not None and not hole:
                    add('edit_sketch', 'sketch', '编辑草图', '进入这个特征用的草图')
            if feature.get('suppressed'):
                add('suppress', 'unsuppress', '解除压缩', '重新启用这个特征')
            else:
                add('suppress', 'suppress', '压缩', '暂时当这个特征不存在（参数保留）')
            position = document.features.index(feature)
            if document.upto is not None and position >= document.upto:
                add('roll_end', 'roll_end', '退回到尾', '把回退线放回最后，所有特征都算上')
            else:
                add('rollback', 'rollback', '退回', '把回退线放到这个特征前面：它和它后面的特征暂不计算')
            if scene is not None and scene['kind'] in ('face', 'edge'):
                add('toggle', 'eye_off', '隐藏', '在视图里不画点中的这一部分（做出它的那个特征做出来的面；别的照常显示）')
            elif self._is_hidden(feature):
                add('toggle', 'eye', '显示', '重新显示出来')
            elif self._is_line_feature(feature):
                add('toggle', 'eye_off', '隐藏', '在视图里不画它（特征还在）')
            else:
                add('toggle', 'eye_off', '隐藏', '在视图里不画这个特征做出来的那部分（特征还在，别的照常显示）')
        elif scene is not None and scene['kind'] in ('face', 'edge'):
            add('toggle', 'eye_off', '隐藏', '在视图里不画点中的这一整块实体（别的实体照常显示）')
        if scene is not None and scene['kind'] in ('face', 'edge'):
            add('hide_solid', 'eye_off', '隐藏实体', '在视图里不画点中的这一整块相连的实体')
        add('zoom', 'zoom_sel', '放大所选范围', '把它放满画面')
        add('normal', 'normal', '正视于', '把视角转到正对着它')
        if feature is None or not self._is_line_feature(feature):
            add('appearance', 'appearance', '外观', '给零件换个颜色')
        if feature is not None and hole:
            add('hole_sketch', 'hole', '编辑孔草图', '改孔的位置（进入定位置的那个草图）')
            if scene is not None:
                add('hole_spec', 'settings', '修改孔规格', '改孔的类型、规格和深度')
        if scene is not None and scene['kind'] == 'face' and self._face_is_flat(scene['id']):
            rows.insert(0, {'id': 'face_sketch', 'icon': 'sketch', 'title': '草图绘制', 'tip': '草图绘制：在这个面上画草图'})
        if scene is not None and scene['kind'] in ('face', 'edge'):
            add('select_other', 'select_other', '选择其他', '换成这个位置后面被挡住的下一个面')
            add('fillet', 'fillet', '圆角', '给选中的边倒圆角（选的是面就是它的一圈边）')
            add('chamfer', 'chamfer', '倒角', '给选中的边倒斜角（选的是面就是它的一圈边）')
        if scene is not None and scene['kind'] == 'face':
            add('same_faces', 'same_faces', '选择相同面', '把和它同样大小、同样形状的面都选上')
            add('back_face', 'back_face', '选择背面', '选这个位置最后面的那个面（零件背面）')
        return rows

    @Slot(str, result='QVariantList')
    @localized
    def featureMenu(self, identifier):
        """设计树里右键一个特征出来的菜单: 重命名 + 小工具条上的那些 + 删除。"""
        if self._sketch is not None or self._find(identifier) is None:
            return []
        rows = [{'id': 'rename', 'icon': 'edit', 'title': '重命名'}]
        rows += [{'id': row['id'], 'icon': row['icon'], 'title': row['title']} for row in self._context_items(identifier)
                 if row['id'] != 'sketch_plane']
        rows[1]['line'] = True
        rows.append({'id': 'isolate', 'icon': 'isolate', 'title': '孤立', 'line': True})
        if self._isolated is not None:
            rows.append({'id': 'isolate_exit', 'icon': 'eye', 'title': '退出孤立'})
        return rows + [{'id': 'delete', 'icon': 'trash', 'title': '删除', 'line': True}]

    @Slot(str, str, result='QVariantList')
    @localized
    def treeMenu(self, kind, identifier):
        """设计树里右键零件 (第一行)、材质、基准面、原点出来的菜单。"""
        if self._sketch is not None:
            return []
        rows = []

        def add(action, icon, title, line=False):
            rows.append({'id': action, 'icon': icon, 'title': title, 'line': line})

        if kind == 'root':
            add('fit', 'fit', '整屏显示全图')
            add('appearance', 'appearance', '外观')
            add('material', 'material', '编辑材质')
            if self._isolated is not None:
                add('isolate_exit', 'eye', '退出孤立', True)
            if self._hidden_keys or self._hidden_ids:
                add('show_all', 'eye', '显示所有隐藏的', self._isolated is None)
            if any(row.get('expandable') for row in self.tree):
                add('expand_all', 'tree_expand', '全部展开', True)
                add('collapse_all', 'tree_collapse', '全部收起')
        elif kind == 'material':
            add('material', 'material', '编辑材质')
        elif kind == 'plane' and identifier in planes.PLANES:
            shown = self.viewport is not None and self.viewport.plane_shown(identifier)
            add('sketch', 'sketch', '草图绘制')
            add('toggle', 'eye_off' if shown else 'eye', '隐藏' if shown else '显示', True)
            add('zoom', 'zoom_sel', '放大所选范围')
            add('normal', 'normal', '正视于')
        elif kind == 'origin':
            on = not self._view['hideAll'] and 'origin' not in self._off
            add('origin', 'eye_off' if on else 'eye', '隐藏原点' if on else '显示原点')
        return rows

    @Slot(str, str, str)
    def treeAction(self, kind, identifier, action):
        """treeMenu 里点了一项 (编辑材质由界面自己弹材质列表)。"""
        if kind == 'plane':
            self.planeAction(identifier, action)
        elif action == 'fit':
            self.viewAction('fit')
        elif action == 'appearance':
            self.appearanceRequested.emit()
        elif action == 'isolate_exit':
            self.toggleShow('isolate_exit')
        elif action == 'show_all':
            self._exit_isolate()
            self._hidden_keys, self._hidden_ids = set(), set()
            self._apply_view()
            self.changed.emit()
        elif action == 'origin':
            self.toggleShow('origin')
        elif action in ('expand_all', 'collapse_all'):
            self._collapsed = set() if action == 'expand_all' else {row['id'] for row in self.tree if row.get('expandable')}
            self.changed.emit()

    def _isolate(self, identifier):
        """孤立: 只显示这个特征做出来的东西 (它的面, 或它这条线), 别的先藏起来; 退出时恢复原来的隐藏状态。"""
        feature = self._find(identifier)
        if feature is None:
            return
        faces = self.session.model.get('faces') or []
        if not self._is_line_feature(feature) and not any(face.get('feature') == identifier for face in faces):
            self.notice.emit('孤立：这个特征现在没有留在实体上的面，没有可以单独显示的东西')
            return
        if self._isolated is None:
            self._isolated = {'keys': set(self._hidden_keys), 'ids': set(self._hidden_ids)}
        self._isolated['name'] = feature['name']
        self._hidden_keys = {self._face_key(face) for face in faces if face.get('feature') != identifier}
        self._hidden_ids = {other['id'] for other in self.session.document.features
                            if other['id'] != identifier and self._is_line_feature(other)}
        self.notice.emit(f'已孤立“{feature["name"]}”：只显示它。点视图上方的“退出孤立”回到原来的样子')

    def _exit_isolate(self):
        if self._isolated is not None:
            self._hidden_keys, self._hidden_ids = self._isolated['keys'], self._isolated['ids']
            self._isolated = None

    @Property(str, notify=changed)
    def isolatedName(self):
        """正在孤立的特征名; 没在孤立是空的。"""
        return self._isolated['name'] if self._isolated is not None else ''

    @Slot(str, result=str)
    def featureName(self, identifier):
        feature = self._find(identifier)
        return feature['name'] if feature is not None else ''

    @Slot(str, str)
    def renameFeature(self, identifier, name):
        name = name.strip()
        if name and name != self.featureName(identifier):
            self._run('rename_feature', {'id': identifier, 'name': name})

    @Slot(str, result='QVariantList')
    @localized
    def featureContext(self, identifier):
        """设计树里点一个特征弹出来的按钮。"""
        if self._sketch is not None or self._picking_plane or self._form is not None:
            return []
        return self._context_items(identifier)

    @Property('QVariantList', notify=changed)
    @localized
    def sceneContext(self):
        """视图里点中面 / 边 / 草图线弹出来的按钮。"""
        if self._context and self._context['kind'] == 'component':
            return self.sim.partContext(self._context['id'])
        if self._context and self._context['kind'] == 'shapes':
            return self._sketch.context_items() if self._sketch is not None else []
        return self._context_items(self._context['feature'], self._context) if self._context else []

    @Property(str, notify=changed)
    def sceneTarget(self):
        return (self._context.get('feature') or '') if self._context else ''

    def _face_is_flat(self, identifier):
        return any(face['id'] == identifier and face.get('normal') is not None for face in self.session.model.get('faces', ()))

    def _drop_context(self):
        if self._context is not None:
            self._context = None
            self.contextRequested.emit(-1.0, -1.0)

    @Slot(str, result='QVariantList')
    @localized
    def planeChoices(self, identifier):
        """这个草图可以换到哪些基准面上: 三个主要基准面 + 排在它前面的基准面特征。"""
        feature = self._find(identifier)
        if feature is None:
            return []
        now = feature['params'].get('plane', 'XY')
        rows = [{'id': name, 'title': planes.NAMES[name], 'icon': 'plane', 'checked': now == name} for name in ('XZ', 'XY', 'YZ')]
        before = self.session.document.features[:self.session.document.features.index(feature)]
        rows += [{'id': other['id'], 'title': other['name'], 'icon': 'plane', 'checked': now == other['id']}
                 for other in before if other['type'] == 'plane']
        return rows

    @Slot(str, str)
    def setSketchPlane(self, identifier, plane):
        if self._leave_modes():
            self._run('edit_feature', {'id': identifier, 'params': {'plane': plane}})

    def _feature_frame(self, feature):
        """特征的草图平面 (基准面名, 或基准面特征算出来的坐标系); 没有草图的特征是 None。"""
        sketch = feature if feature['type'] == 'sketch' else self._source_sketch(feature)
        if sketch is None:
            return None
        ref = sketch['params'].get('plane', 'XY')
        try:
            return ref if ref in planes.PLANES else table.plane_frame(ref, self.session.document.features)
        except (ValueError, KeyError):
            return None

    def _feature_bounds(self, feature):
        """一个特征在视图里占的范围 → (最小角, 最大角) 或 None。"""
        lines = (self.session.model.get('sketches') or {}).get(feature['id'])
        if lines is not None and len(lines):
            import numpy as np
            points = np.asarray(lines, dtype=float).reshape(-1, 3)
            return points.min(axis=0), points.max(axis=0)
        faces = [face['id'] for face in self.session.model.get('faces', ()) if face.get('feature') == feature['id']]
        return self.viewport.face_bounds(faces) if faces else None

    @Slot(str, str)
    def contextAction(self, identifier, action):
        """小工具条上点了一个按钮。identifier: 特征 id (在视图里点了不属于任何特征的面时是空的)。"""
        if self._sketch is not None:
            self.sketchAction(action)
            return
        if identifier.startswith('part:'):      # 装配体的零部件 (视图里 / 设计树上点出来的)
            if action != 'zoom':
                self._drop_context()
            self.sim.partAction(int(identifier[5:]), action)
            return
        feature, scene, viewport = self._find(identifier), self._context, self.viewport
        selection, model = self.session.selection, self.session.model
        faces = {face['id']: face for face in model.get('faces', ())}
        face = faces.get(scene['id']) if scene and scene['kind'] == 'face' else None
        if viewport is None:
            return
        if scene is not None and scene['kind'] == 'plane':
            name = scene['id']
            self._drop_context()
            if action == 'plane_sketch':
                self._pending_tool = 'select'
                self.sketchOn(name)
            elif action == 'normal':
                viewport.look_at_plane(name)
            elif action == 'plane_hide':
                selection['plane'] = None
                self._push_selection()
                viewport.planesVisible = False
                self._apply_view()
        elif action == 'face_sketch' and scene is not None:
            target = scene['id']
            self._drop_context()
            self._pending_tool = 'select'
            self._sketch_on_face(target)
        elif action in ('edit', 'hole_spec') and feature is not None:
            self.editFeature(identifier)
        elif action in ('edit_sketch', 'hole_sketch') and feature is not None:
            sketch = feature if feature['type'] == 'sketch' else self._source_sketch(feature)
            if sketch is not None:
                self.editFeature(sketch['id'])
        elif action == 'suppress' and feature is not None:
            self.toggleSuppress(identifier)
        elif action == 'rollback' and feature is not None:
            position = self.session.document.features.index(feature)
            source = self._source_sketch(feature)
            if source is not None and self.session.document.features.index(source) == position - 1:
                position -= 1                   # 草图紧挨在它前面: 连草图一起退 (和设计树里拖回退线一样)
            self.rollbackTo(position)
        elif action == 'roll_end':
            self.rollbackTo(-1)
        elif action in ('isolate', 'isolate_exit'):
            if action == 'isolate' and feature is not None:
                self._isolate(identifier)
            else:
                self._exit_isolate()
            self._drop_context()
            self._apply_view()
            self.changed.emit()
        elif action in ('toggle', 'hide_solid') and scene is not None and scene['kind'] in ('face', 'edge'):
            touched = self._scene_faces(scene)
            if action == 'hide_solid':
                self._set_faces_hidden(self._solid_faces(touched), True)
            else:
                self._set_faces_hidden([index for face_id in touched for index in self._part_faces(face_id)], True)
            self.notice.emit('已隐藏。要显示回来：视图上方“隐藏/显示项目”里点“显示隐藏的实体”，或在设计树里点做出它的特征再点“显示”')
            self._drop_context()
            self._apply_view()
            self.changed.emit()
        elif action == 'toggle' and feature is not None:
            if self._is_line_feature(feature):
                self._hidden_ids.symmetric_difference_update({identifier})
            else:
                mine = [item['id'] for item in model.get('faces', ()) if item.get('feature') == identifier]
                if mine:
                    self._set_faces_hidden(mine, not self._is_hidden(feature))
                else:
                    self.notice.emit('这个特征现在没有留在实体上的面，没有可以隐藏的东西')
            self._drop_context()
            self._apply_view()
            self.changed.emit()
        elif action == 'zoom':
            box = viewport.face_bounds([face['id']]) if face else (self._feature_bounds(feature) if feature else None)
            if box is None:
                self.notice.emit('放大所选范围：它现在没有显示出来的图形')
            else:
                viewport.zoom_to(*box)
        elif action == 'normal':
            frame = self._feature_frame(feature) if feature is not None else None
            if face is not None and face.get('normal'):
                viewport.look_along(face['normal'])
            elif frame is not None:
                viewport.look_at_plane(frame)
            else:
                self.notice.emit('正视于：要一个平面才知道朝哪边看——点一个平的面，或者一个有草图的特征')
        elif action == 'appearance':
            self.appearanceRequested.emit()
        elif action == 'select_other' and scene is not None:
            along = scene.get('faces') or []
            here = scene['id'] if scene['kind'] == 'face' else None
            behind = [number for number in along if number != here]
            if not behind:
                self.notice.emit('选择其他：这个位置后面没有别的面了')
                return
            following = along[(along.index(here) + 1) % len(along)] if here in along else behind[0]
            self._select_face(following, along)
        elif action == 'back_face' and scene is not None:
            along = scene.get('faces') or []
            if len(along) < 2 or along[-1] == scene['id']:
                self.notice.emit('选择背面：这个位置后面没有别的面了')
                return
            self._select_face(along[-1], along)
        elif action == 'same_faces' and face is not None:
            def alike(other):
                return other['type'] == face['type'] and abs(other['area'] - face['area']) <= 1e-4 * max(face['area'], 1.0) \
                    and abs(other.get('radius', 0.0) - face.get('radius', 0.0)) <= 1e-6
            selection.update(faces=[number for number, other in faces.items() if alike(other)], edges=[], plane=None)
            self._push_selection()
            self.notice.emit(f'选中了 {len(selection["faces"])} 个相同的面')
        elif action in ('fillet', 'chamfer'):
            if not selection['edges'] and selection['faces']:      # 选的是面: 就是它的一圈边
                known = {edge['id'] for edge in model.get('edges', ())}
                around = [number for chosen in selection['faces'] for number in faces.get(chosen, {}).get('edges', ()) if number in known]
                selection.update(edges=list(dict.fromkeys(around)), faces=[])
                self._push_selection()
            self._drop_context()
            self.startCommand(action)

    def _select_face(self, number, along):
        """换成选这个面 (选择其他 / 选择背面), 小工具条跟着换成它的。"""
        faces = {face['id']: face for face in self.session.model.get('faces', ())}
        owner = faces.get(number, {}).get('feature')
        self.session.selection.update(faces=[number], edges=[], plane=None, feature=owner)
        self._context = {'kind': 'face', 'id': number, 'feature': owner, 'faces': along}
        self._push_selection()
        self.contextRequested.emit(*self.viewport.click_at)

    @Property(str, notify=sketchChanged)
    @localized
    def sketchTitle(self):
        if self._sketch is None:
            return ''
        return f'{self._sketch.name} · {self._plane_name(self._sketch.plane_ref or self._sketch.plane)}'

    def _plane_name(self, ref):
        if ref in planes.NAMES:
            return planes.NAMES[ref]
        return next((feature['name'] for feature in self.session.document.features if feature['id'] == ref), str(ref))

    def _sketch_editor(self, ref, **more):
        """在基准面 ref (XY / XZ / YZ 或基准面特征的 id) 上的草图编辑器。"""
        if ref in planes.PLANES:
            return SketchEditor(plane=ref, **more)
        editor = SketchEditor(plane=table.plane_frame(ref, self.session.document.features), **more)
        editor.plane_ref = ref
        return editor
