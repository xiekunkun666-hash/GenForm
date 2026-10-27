"""装配体: 加 / 删 / 挪零件、镜像、存取和导出装配体、干涉检查、装配顺序、装配体的设计检查 (贴着 / 干涉 / 悬空) 和物料清单。"""
from __future__ import annotations

import json
import os
import re

import numpy as np
from PySide6.QtCore import Property, QUrl, Slot

from .. import asm_rules, bom, checks, i18n, rules as design_rules
from .signals import changed

RED = (1.0, 0.18, 0.16)
PICKED = np.array([0.30, 0.58, 1.0], dtype=np.float32)      # 选中的零部件: 颜色大半换成蓝 (红车身调一半会变紫, 看不出是选中)
KIND_LOOK = {'standard': ('标准', '#3FB97F'), 'purchase': ('外购', '#8A94A6'), 'custom': ('非标', '#E98A3C')}


class AssemblyMixin:
    """装配体 (仿真页的一部分)。"""

    # ---- 装配体 ----
    @Slot(str)
    def addPart(self, where):
        self.addParts([where])

    @Slot('QVariantList')
    def addParts(self, paths):
        if getattr(self.app, '_sketch', None) is not None:
            self.app.notice.emit('正在编辑草图：先点“完成草图”或“放弃”')
            return
        added, rejected = [], []
        for where in paths:
            text = where.toString() if hasattr(where, 'toString') else str(where)
            path = QUrl(text).toLocalFile() if '://' in text else text
            path = os.path.abspath(path)
            if not os.path.isfile(path) or not path.lower().endswith(('.gform', '.step', '.stp', '.stl')):
                rejected.append(os.path.basename(path))
                continue
            added.append({'name': os.path.splitext(os.path.basename(path))[0], 'path': path, 'move': [0.0, 0.0, 0.0],
                          'turn': [0.0, 0.0, 0.0], 'mirror': False})
        if added:
            self._parts.extend(added)
            self._parts_changed()
        if rejected:
            self.app.notice.emit('已跳过不支持或不存在的文件：' + '、'.join(rejected))

    @Property('QVariantList', constant=True)
    def standardCatalog(self):
        """标准件库的目录 (类别 → 系列 → 规格, 要长度的给常用长度), 见 standard_parts.py。"""
        from .. import standard_parts
        return standard_parts.catalog()

    @Slot(str, str, str, str)
    def addStandardPart(self, kind, series, size, length):
        """插一个标准件: 按规格生成零件文件, 放在装配体旁边的 standard/ 文件夹里 (已经有了就直接用), 再加进装配体。"""
        from .. import standard_parts
        own = self.path or self.app.session.document.path
        if not own:
            self.app.notice.emit('先把装配体保存成文件：标准件的零件文件放在它旁边的 standard/ 里')
            return
        try:
            name, doc = standard_parts.make(kind, size, float(length) if str(length).strip() else None, series)
        except (KeyError, ValueError) as error:
            self.app.notice.emit(f'生成不了这个标准件：{error}')
            return
        folder = os.path.join(os.path.dirname(os.path.abspath(own)), 'standard')
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            try:
                os.makedirs(folder, exist_ok=True)
                with open(path, 'w', encoding='utf-8') as handle:
                    json.dump(doc, handle, ensure_ascii=False, indent=1)
            except OSError as error:
                self.app.notice.emit(f'存不了：{error}')
                return
        self.addPart(path)
        self._parts[-1]['name'] = doc['props']['standard']['spec']
        self.changed.emit()
        self.app.notice.emit(f"插入了 {doc['props']['standard']['spec']}（文件在 standard/{name}）")

    @Slot(int)
    def removePart(self, index):
        if 0 <= index < len(self._parts) and self._parts[index]['path']:
            del self._parts[index]
            mapping = {old: old - (old > index) for old in range(len(self._parts) + 1) if old != index}
            self._joints_renumber(mapping)
            self._mates_renumber(mapping)
            self._parts_changed()

    @Slot(int, int)
    def shiftPart(self, index, step):
        """在装配顺序里往前 (-1) / 往后 (+1) 挪一位。"""
        target = index + step
        if 0 <= index < len(self._parts) and 0 <= target < len(self._parts):
            self._parts[index], self._parts[target] = self._parts[target], self._parts[index]
            mapping = {old: old for old in range(len(self._parts))}
            mapping.update({index: target, target: index})
            self._joints_renumber(mapping)
            self._mates_renumber(mapping)
            self._parts_changed(meshes=False)

    @Slot(int, str, int, str)
    def placePart(self, index, field, axis, text):
        """改一个零件的位置 (field: move 平移 mm / turn 转角 度)。"""
        if not (0 <= index < len(self._parts)) or field not in ('move', 'turn') or not (0 <= axis < 3):
            return
        part = self._parts[index]
        if field == 'move' and axis in self._mated_axes(index):
            self.app.notice.emit('这个方向是配合定的：改配合，或者先删掉配合')
            self.changed.emit()
            return
        text = str(text).strip()
        formulas = part.setdefault('formula', {}).setdefault(field, [None, None, None])
        if text.startswith('='):                # 用全局变量的表达式: 变量改了跟着变
            formulas[axis] = text
            self._parts_changed()
            return
        try:
            value = float(text)
        except ValueError:
            self.app.notice.emit('这里要填数字，或者 =表达式（用全局变量）')
            self.changed.emit()
            return
        if part[field][axis] != value or formulas[axis]:
            formulas[axis] = None
            part[field][axis] = value
            self._parts_changed()

    @Slot(int)
    def mirrorPart(self, index):
        """镜像 / 不镜像这个零件 (对它自己的 XZ 面: 左边的件 → 右边的件)。"""
        if 0 <= index < len(self._parts) and self._parts[index]['path']:
            self._parts[index]['mirror'] = not self._parts[index].get('mirror')
            self._parts_changed()

    @Slot(str)
    def saveAssembly(self, where):
        """把装配体存成 .gasm: 零件文件的位置 (相对这个文件)、各自的位置和转角, 顺序就是装配顺序。"""
        path = (QUrl(where).toLocalFile() if '://' in where else where) or self.path
        if not path:
            return
        if not path.lower().endswith('.gasm'):
            path += '.gasm'
        own = self.app.session.document.path
        if not own and any(not part['path'] for part in self._parts):
            self.app.notice.emit('先把当前零件保存成文件：装配体里记的是零件文件在哪')
            return
        folder = os.path.dirname(os.path.abspath(path))

        def relative(target):
            try:
                return os.path.relpath(target, folder).replace(os.sep, '/')
            except ValueError:              # 不在同一个盘上: 只能记完整路径
                return os.path.abspath(target).replace(os.sep, '/')
        rows = [dict({'name': part['name'], 'file': relative(part['path'] or own), 'move': self._place_to_row(part, 'move'),
                      'turn': self._place_to_row(part, 'turn')},
                     **({'mirror': True} if part.get('mirror') else {}))
                for part in self._parts]
        data = {'format': 'genform-assembly', 'version': 1, 'parts': rows}
        if self._joints:                        # 运动副 (车门的铰链…): 存定义, 不存开到多少
            data['joints'] = self._joints_to_file()
        self._params_to_file(data)              # 全局变量和配合
        layout = self.layout_mode() and self.app.session.document.features
        if layout:                              # 装配体里画的布局草图: 存在装配体文件里
            data['layout'] = self.app.session.document.to_data()
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
        except OSError as error:
            self.app.notice.emit(f'存不了：{error}')
            return
        if self.layout_mode():
            self.app.session.document.dirty = False
        self.path, self.dirty = path, False
        self.app.changed.emit()
        self.app.notice.emit(f'装配体已保存到 {path}')

    @Slot(str)
    def exportAssembly(self, where):
        """整个装配体导出成一个 STEP 文件: 每个零件一个实体, 都在摆好的位置上。"""
        path = QUrl(where).toLocalFile() if '://' in where else where
        if not self._parts:
            self.app.notice.emit('装配体里还没有零件')
            return
        if not path.lower().endswith(('.step', '.stp')):
            path += '.step'

        def done(result, error):
            self._assembly['error'] = error
            if result:
                self.app.notice.emit(f'已导出到 {path}')
        self._ask('assembly_step', {'parts': self._posed_parts(), 'path': path}, done)    # 门开着就导出开着的样子

    @Slot(str)
    def openAssembly(self, where):
        """打开 .gasm。里面指着现在打开的这个零件的那一项就是 "当前零件"; 都不是的话当前零件排在最前面。"""
        path = QUrl(where).toLocalFile() if '://' in where else where
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
            if data.get('format') != 'genform-assembly':
                raise ValueError('不是 GenForm 装配体文件')
            folder, parts = os.path.dirname(os.path.abspath(path)), []
            own = os.path.normcase(os.path.abspath(self.app.session.document.path)) if self.app.session.document.path else None
            moving = {index for joint in data.get('joints') or [] for index in joint.get('parts') or []}
            for number, row in enumerate(data['parts']):
                target = os.path.normpath(os.path.join(folder, row['file']))
                (move, move_formula), (turn, turn_formula) = self._place_from_row(row, 'move'), self._place_from_row(row, 'turn')
                # 开着的零件就是 "当前零件" (视图里直接画它的文档, 不挪): 只认摆在原点、没转、没镜像、不在运动副里的那一项。
                # 摆在别处的 (从装配体里打开一个零件再返回: 行星轮在 (18, 0, 0)) 按文件读, 不然它会跑到原点去
                mine = (own is not None and os.path.normcase(target) == own and not any(not part['path'] for part in parts)
                        and not any(float(value) for value in move + turn) and not any(move_formula + turn_formula)
                        and not row.get('mirror') and number not in moving)
                parts.append({'name': '当前零件' if mine else str(row.get('name') or os.path.splitext(os.path.basename(target))[0]),
                              'path': '' if mine else target, 'move': move, 'turn': turn, 'mirror': bool(row.get('mirror'))})
                if any(move_formula) or any(turn_formula):          # 位置写成 "=表达式" 的 (用全局变量)
                    parts[-1]['formula'] = {'move': move_formula, 'turn': turn_formula}
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.app.notice.emit(f'打不开这个装配体：{error}')
            return False
        missing = [part['name'] for part in parts if part['path'] and not os.path.isfile(part['path'])]
        if missing:
            self.app.notice.emit('找不到这些零件的文件：' + '、'.join(missing))
        if self.pinned and all(part['path'] for part in parts) and self.app.session.document.features:
            # 开着的零件不在这个装配体里: 把它收掉 (不然它的实体还画在视图里); 有没保存的修改就先不打开
            if self.app.session.document.dirty:
                self.app.notice.emit('当前零件有没保存的修改：先保存，再打开这个装配体')
                return False
            self.app._run('new_document')
        if self.pinned and all(part['path'] for part in parts) and isinstance(data.get('layout'), dict):
            self.app._run('load_layout', {'data': data['layout']})     # 布局草图
        inserted = all(part['path'] for part in parts) and not self.pinned
        if inserted:
            parts.insert(0, self._own_part())       # 仿真页里的装配检查: 现在打开的零件总在里面
        self._joints_from_file(data.get('joints') if self.pinned else None, len(parts))
        self._params_from_file(data, len(parts) - inserted)
        if inserted:
            self._mates_renumber({number: number + 1 for number in range(len(parts))})
        self._parts = parts
        self._parts_changed()
        self.path, self.dirty = path, False
        self.app.changed.emit()
        self.changed.emit()                     # 设计树顶上的装配体名字
        return True

    def _parts_changed(self, meshes=True):
        self._apply_layout()                    # 位置里的表达式、配合 (params.py)
        self.dirty = True
        self.app.changed.emit()             # 标题上的 * 号
        self._assembly.update(clashes=None, steps=None, fasteners=None, stack=None, error='')
        self._red = set()
        self._hidden_parts = {index for index in self._hidden_parts if index < len(self._parts)}
        if self._picked >= len(self._parts):
            self._picked = -1
        self._ticket += 1
        self._running = ''
        self._live_schedule()                   # 实时检查: 过一会儿把变了的几对重新查
        if meshes:
            self._show_parts()
        self._paint()
        self.changed.emit()

    def _show_parts(self):
        """视图里把装配体里别的零件也画出来 (现在打开的这个零件本来就在画)。"""
        self._mesh_ticket += 1
        ticket = self._mesh_ticket
        others = [(number, part) for number, part in enumerate(self._parts) if part['path']]
        viewport = self.app.viewport
        if viewport is None:
            return
        if not others:
            viewport.set_extras([])
            return

        def done(result, error):
            if ticket != self._mesh_ticket or self._mode != 'assembly':
                return
            if error:
                self._assembly['error'] = error
                self._shown = []
                viewport.set_extras([])
            else:
                failures = [mesh['error'] for mesh in result if mesh.get('error')]
                self._assembly['error'] = '\n'.join(failures)
                self._shown = [(number, mesh) for (number, _), mesh in zip(others, result) if not mesh.get('error')]
                self._push_parts()
                viewport.fit()              # 别的零件可能摆在画面外面
                if failures:
                    self.app.notice.emit(f'{len(failures)} 个文件加载失败：' + '；'.join(failures))
            self.changed.emit()
        self.app.session.query('meshes', {'parts': [part for _, part in others], 'allow_partial': True}, done)

    def _push_parts(self):
        """把算好的零件网格送给视图: 零件自己的颜色 (每个顶点); 装配检查报错的零件整个标红、不透明; 选中的往蓝里调;
        隐藏的不送 (孤立时只送那一个)。每一项带 'pick' = 它在装配体里的序号: 视图里点它就选中这个零部件。"""
        viewport = self.app.viewport
        if viewport is None:
            return
        shown, labels = [], self._labels()
        selected = self._selected_part_indices() if hasattr(self, '_selected_part_indices') else {self._picked}
        for number, mesh in self._shown:
            mesh = self._moved_mesh(number, mesh)       # 运动副动过的: 门开着
            if number in self._hidden_parts or (self._alone_part is not None and number != self._alone_part):
                continue
            if number in self._red:
                mesh = dict(mesh, color=RED, tints=None, alpha=1.0)
            elif number in selected or number in getattr(self, '_measured', ()):
                mesh = dict(mesh, tints=self._picked_tints(mesh['tints']))
            part = self._parts[number] if number < len(self._parts) else {}
            info = self._kind_of(part['path']) if part.get('path') else None
            about = '　'.join(text for text in ((info or {}).get('spec') or '', (info or {}).get('material') or '') if text)
            shown.append(dict(mesh, pick=number, label=labels[number] if number < len(labels) else '', about=about))
        viewport.set_extras(shown)

    def _picked_tints(self, tints):
        """选中的件往蓝里调的颜色: 同一份数组只算一次 (放动画时每帧都要, 新数组视图就得重新上传)。"""
        cache = self.__dict__.setdefault('_tint_cache', {})
        key = id(tints)
        if key not in cache or cache[key][0] is not tints:
            if len(cache) > 64:
                cache.clear()
            cache[key] = (tints, (np.asarray(tints) * 0.2 + PICKED * 0.8).astype(np.float32))
        return cache[key][1]

    # ---- 设计树 (和 SOLIDWORKS 的 FeatureManager 一样: 装配体 → 基准面 / 原点 → 零部件<n>) ----
    def _labels(self):
        """每个零部件在树上的名字: 零件名<第几个>, 同一个文件数自己的。"""
        counts, labels = {}, []
        for part in self._parts:
            key = os.path.normcase(part['path']) if part['path'] else ''
            counts[key] = counts.get(key, 0) + 1
            base = re.sub(r'\s*\d+$', '', part['name']) or part['name']
            labels.append(f'{base}<{counts[key]}>')
        return labels

    def _kind_of(self, path):
        """零件文件是标准件 / 外购件 / 非标件 (按它各特征绑的工艺; 文件改了重新看)。"""
        try:
            stamp = os.stat(path).st_mtime_ns
        except OSError:
            return None
        cached = self._kinds.get(path)
        if cached is None or cached[0] != stamp:
            cached = (stamp, bom.describe(path))
            self._kinds[path] = cached
        return cached[1]

    @Property('QVariantList', notify=changed)
    def components(self):
        """树上的零部件: [{'index', 'label', 'name', 'path', 'fixed' 第一个 (固定), 'mirror', 'hidden', 'selected', 'bad',
        'kind' 标准/外购/非标, 'kindColor', 'spec', 'process', 'material', 'unit'}...]。"""
        rows, clashing = [], self._live_clash_parts()
        selected = self._selected_part_indices() if hasattr(self, '_selected_part_indices') else {self._picked}
        for index, (part, label) in enumerate(zip(self._parts, self._labels())):
            info = self._kind_of(part['path']) if part['path'] else None
            short, color = KIND_LOOK.get((info or {}).get('kind'), ('', ''))
            rows.append({'index': index, 'label': label if part['path'] else i18n.tr(part['name']), 'name': part['name'],
                         'path': part['path'], 'file': os.path.basename(part['path']) if part['path'] else '',
                         'fixed': index == 0, 'mirror': bool(part.get('mirror')), 'hidden': index in self._hidden_parts,
                         'selected': index in selected, 'bad': index in self._red,
                         'kind': i18n.tr(short) if (info or {}).get('bound') else '', 'kindColor': color,
                         'spec': (info or {}).get('spec') or '', 'process': (info or {}).get('process') or '',
                         'material': (info or {}).get('material') or '', 'unit': (info or {}).get('unit') or 0.0,
                         'move': [float(value) for value in part['move']], 'turn': [float(value) for value in part['turn']],
                         'formula': {field: [value or '' for value in ((part.get('formula') or {}).get(field) or [None] * 3)]
                                     for field in ('move', 'turn')},
                         'mated': sorted(self._mated_axes(index)),
                         'clash': [self._parts[other]['name'] for other in clashing.get(index, ())],
                         'joint': self._joint_of(index)})
        return rows

    @Property(int, notify=changed)
    def picked(self):
        return self._picked

    @Property(str, notify=changed)
    def assemblyName(self):
        return os.path.splitext(os.path.basename(self.path))[0] if self.path else i18n.tr('装配体')

    @Slot(int)
    def selectPart(self, index):
        """选中一个零部件 (树上点的、视图里点的; -1 = 不选): 视图里它变蓝, 树滚到它。"""
        index = index if 0 <= index < len(self._parts) else -1
        if index >= 0 and 0 <= self._joint_adding < len(self._joints):     # 正在点选运动副跟着动的件
            self._toggle_joint_part(index)
            return
        if index >= 0:
            self._joint_picked = -1             # 选了零部件: 不再是设计树上点的那个运动副 (它跟着动的那个照样显示)
        if index != self._picked:
            self._picked = index
            self._push_parts()
            self.changed.emit()

    @Slot(int, result='QVariantList')
    def partMenu(self, index):
        """树上 / 视图里右键一个零部件出来的菜单 (-1 = 装配体本身)。"""
        tr = i18n.tr
        if not (0 <= index < len(self._parts)):
            return [{'id': 'fit', 'icon': 'fit', 'title': tr('整屏显示全图')},
                    {'id': 'show_all', 'icon': 'eye', 'title': tr('显示所有零部件'), 'line': True},
                    {'id': 'hide_all', 'icon': 'eye_off', 'title': tr('隐藏所有零部件')}]
        part = self._parts[index]
        rows = []
        if part['path']:
            rows.append({'id': 'open', 'icon': 'open', 'title': tr('打开零件')})
        rows.append({'id': 'edit', 'icon': 'move', 'title': tr('编辑位置'), 'line': bool(part['path'])})
        rows.append({'id': 'rename', 'icon': 'edit', 'title': tr('重命名')})
        if part['path']:
            rows.append({'id': 'mirror', 'icon': 'mirror', 'title': tr('取消镜像') if part.get('mirror') else tr('镜像 (相反方位的件)')})
        rows.append({'id': 'hide', 'icon': 'eye', 'title': tr('显示') if index in self._hidden_parts else tr('隐藏'), 'line': True})
        rows.append({'id': 'isolate', 'icon': 'isolate', 'title': tr('退出孤立') if self._alone_part == index else tr('孤立')})
        rows.append({'id': 'up', 'icon': 'up', 'title': tr('往前挪 (早一步装)'), 'line': True})
        rows.append({'id': 'down', 'icon': 'down', 'title': tr('往后挪 (晚一步装)')})
        if part['path']:
            rows.append({'id': 'delete', 'icon': 'trash', 'title': tr('删除'), 'line': True})
        return rows

    @Slot(int, result='QVariantList')
    def partContext(self, index):
        """单击零部件 (视图里或设计树上) 弹出来的小工具条 (和 SOLIDWORKS 装配体的关联工具栏一样): 一排图标按钮。
        index = -1: 设计树上点了装配体本身 → 显示全部 / 隐藏全部 / 整屏显示。"""
        tr, rows = i18n.tr, []

        def add(action, icon, title, tip):
            rows.append({'id': action, 'icon': icon, 'title': tr(title), 'tip': f'{tr(title)}：{tr(tip)}'})
        if index == -1 and self._parts:
            add('show_all', 'eye', '显示', '显示所有零部件（也退出孤立）')
            add('hide_all', 'eye_off', '隐藏', '隐藏所有零部件')
            add('fit', 'fit', '整屏显示全图', '把整个装配体放满画面')
            return rows
        if not (0 <= index < len(self._parts)):
            return []
        part = self._parts[index]

        if part['path']:
            add('open', 'open', '打开零件', '离开装配体去改这个零件（改完点“返回装配体”回来）')
        add('edit', 'move', '编辑位置', '在属性管理器里改它的平移、转角')
        if part['path']:
            add('mirror', 'mirror', '取消镜像' if part.get('mirror') else '镜像', '换成左右相反方位的那个件')
        add('hide', 'eye' if index in self._hidden_parts else 'eye_off', '显示' if index in self._hidden_parts else '隐藏', '在视图里不画它（还在装配体里）')
        add('isolate', 'isolate', '退出孤立' if self._alone_part == index else '孤立', '只显示它一个')
        add('zoom', 'zoom_sel', '放大所选范围', '把它放满画面')
        return rows

    @Slot(int, str)
    def partAction(self, index, action):
        if action == 'zoom':
            mesh = next((mesh for number, mesh in self._shown if number == index), None)
            if mesh is not None and self.app.viewport is not None:
                self.app.viewport.zoom_to(mesh['low'], mesh['high'])
            return
        if action == 'fit':
            if self.app.viewport is not None:
                self.app.viewport.fit()
            return
        if action == 'show_all':
            self._hidden_parts.clear()
            self._alone_part = None
        elif action == 'hide_all':
            self._hidden_parts = set(range(len(self._parts)))
            self._alone_part = None
        elif not (0 <= index < len(self._parts)):
            return
        elif action == 'open':
            self.openPart(index)
            return
        elif action == 'mirror':
            self.mirrorPart(index)
            return
        elif action == 'hide':
            self._hidden_parts.symmetric_difference_update({index})
        elif action == 'isolate':
            self._alone_part = None if self._alone_part == index else index
        elif action in ('up', 'down'):
            self.shiftPart(index, -1 if action == 'up' else 1)
            self.selectPart(index + (-1 if action == 'up' else 1))
            return
        elif action == 'delete':
            self.removePart(index)
            return
        elif action == 'edit':
            self.selectPart(index)
            self.editRequested.emit(index)
            return
        self._push_parts()
        self.changed.emit()

    @Slot(int, str)
    def renamePart(self, index, name):
        """设计树上重命名一个零部件 (只改它在装配体里的名字, 零件文件不动)。"""
        name = str(name).strip()
        if 0 <= index < len(self._parts) and name and name != self._parts[index]['name']:
            self._parts[index]['name'] = name
            self.dirty = True
            self.app.changed.emit()
            self.changed.emit()

    @Slot(int)
    def openPart(self, index):
        """打开这个零部件的零件文件 (离开装配体): 装配体有没保存的修改就先提示。"""
        if not (0 <= index < len(self._parts)) or not self._parts[index]['path']:
            return
        if self.dirty or (self.layout_mode() and self.app.session.document.dirty):
            self.app.notice.emit('装配体有没保存的修改：先保存装配体，再打开零件')
            return
        back = self.path
        self.app.openDocument(self._parts[index]['path'])
        if self.app.docKind == 'part':
            self.app._set_return(back)            # 零件页上出 "返回装配体"


    def layout_mode(self):
        """开着的装配体里每个零件都是文件 (没有 "当前零件"): 底下那个零件文档就是装配体的布局草图, 跟着 .gasm 存取。"""
        return self.pinned and all(part['path'] for part in self._parts)

    def markMeasured(self, indices):
        """测量点着的零部件: 和选中一样变蓝 (可以两个)。"""
        self._measured = set(indices)
        self._push_parts()

    def mark(self, indices):
        """视图里标红这些零件 (装配体里的序号); 空 = 都恢复。"""
        self._red = set(indices)
        self._push_parts()

    # ---- 装配体的设计检查 + 物料清单 ----
    def bill(self):
        return bom.bill([part for part in self._parts if part['path']])

    def check(self, done):
        """装配体的设计检查 → done(issues): 件与件干涉 (压进去了)、间隙比规则小但没贴上、悬空的零件 (和第一个零件连不上)、
        零件文件没绑工艺; 最后是物料清单的汇总。issues 的 'features' 写的是 'part:序号'。"""
        if not self._parts:
            done([checks._issue('error', 'no_parts', '装配体里还没有零件')])
            return
        rules = design_rules.effective(getattr(self.app.session, 'design_rules', None) or {})
        names = [part['name'] for part in self._parts]

        def back(result, error):
            if error:
                done([checks._issue('error', 'check_failed', '检查没做完', error)])
                return
            issues = []
            for pair in result['pairs']:
                tags = [f'part:{pair["a"]}', f'part:{pair["b"]}']
                both = f'{names[pair["a"]]} ↔ {names[pair["b"]]}'
                if pair['kind'] == 'clash':
                    issues.append(checks._issue('error', 'clash', f'干涉：{both}',
                                                f'两个件压进去了 {pair["depth"]:.2g} mm 深、{pair["volume"]:.3g} mm³：装不上，改尺寸或让开', tags, pair['point']))
                elif pair['kind'] == 'gap':
                    issues.append(checks._issue('warning', 'gap', f'间隙太小：{both}',
                                                f'只隔 {pair["distance"]:.2f} mm (设计规则：不贴着的件至少隔 {rules["clearance"]:g} mm)，'
                                                f'加工误差一叠就碰上了', tags, pair['point']))
            for index in result['floating']:
                issues.append(checks._issue('error', 'floating', f'悬空：{names[index]}',
                                            f'没贴在任何装到“{names[0]}”上的零件上：装上去没有东西托着它', [f'part:{index}']))
            touches = sum(1 for pair in result['pairs'] if pair['kind'] == 'touch')
            rows = self.bill()
            unbound = [row['name'] for row in rows if not row['bound']]
            if unbound:
                issues.append(checks._issue('warning', 'no_process', f'{len(unbound)} 种零件还没绑工艺',
                                            '、'.join(unbound[:8]) + ('…' if len(unbound) > 8 else '') + '：打开零件，评估 → 绑定工艺',
                                            [f'part:{row["indices"][0]}' for row in rows if not row['bound']]))
            sums = bom.totals(rows)
            issues.append(checks._issue('info', 'contacts', f'{touches} 处装配面',
                                        f'查了 {result["checked"]} 对挨得近的零件：贴着的 {touches} 处，靠它们一个托一个地装在“{names[0]}”上'))
            for kind in ('custom', 'purchase', 'standard'):
                part = sums[kind]
                if part['types']:
                    issues.append(checks._issue('info', 'bom_' + kind, f'{bom.KINDS[kind]} {part["types"]} 种 {part["count"]} 件',
                                                f'估算 ¥{part["cost"]:,.0f}' + ('：网上按规格买' if kind == 'standard' else '')))
            issues.append(checks._issue('info', 'cost', f'整套估算 ¥{sums["all"]["cost"]:,.0f}',
                                        f'{sums["all"]["types"]} 种零件 {sums["all"]["count"]} 件，按各零件绑的工艺和设计规则里的生产数量'))
            self._check_more(result, rows, issues, rules, done)
        self._live_need(back)

    def _check_more(self, result, rows, issues, rules, done):
        """设计检查的后半: 重复摆放、电化学腐蚀、紧固件、外购件报价 / 标准件规格 (马上有), 再问内核要重量重心,
        有运动副的再扫一遍运动干涉 (每个运动副开到 1/4、1/2、3/4、到头), 最后按 报错 → 警告 → 提示 排好交给 done。"""
        names = [part['name'] for part in self._parts]
        info = [self._kind_of(part['path']) or {} if part['path'] else {} for part in self._parts]
        material_of = lambda index: info[index].get('material') or (self.app.session.document.props.get('material') if not self._parts[index]['path'] else '')
        issues = asm_rules.duplicates(self._parts) + issues
        issues += asm_rules.galvanic(result['pairs'], material_of, names)
        kinds = [row.get('kind') if row.get('bound') else '' for row in info]
        issues += asm_rules.fasteners(result['pairs'], kinds, names)
        issues += asm_rules.bill_gaps(rows)
        posed = self._posed_parts()
        corners = [mesh for _, mesh in self._shown]
        size = (np.max([mesh['high'] for mesh in corners], axis=0) - np.min([mesh['low'] for mesh in corners], axis=0)).tolist() if corners else []

        def finish(extra):
            order = {'error': 0, 'warning': 1, 'info': 2}
            done(sorted(issues + extra, key=lambda item: order.get(item['level'], 3)))

        def weighed(props, error):
            extra = asm_rules.mass(props, material_of, names, size) + asm_rules.orphans(result['pairs'], kinds, names, props)                 if props and not error else []
            if not self._joints:
                finish(extra)
                return
            joints = [dict(joint, values=[] if joint.get('speed') else      # 一直转的 (齿轮咬着一起转): 单独转一个查不了, 下面一起查
                           [self._closed(joint) + (float(joint['max']) - self._closed(joint)) * share
                            for share in (0.25, 0.5, 0.75, 1.0)]) for joint in self._joints]
            if self._spinning():
                joints.append({'name': '一直转的运动副', 'parts': [], 'origin': [0, 0, 0], 'axis': [0, 0, 1], 'poses': self._spin_poses()})
            closed = [dict(part) for part in self._parts]

            def swept(clashes, error):
                if error:
                    extra.append(checks._issue('warning', 'motion_failed', '运动干涉没查完', error))
                else:
                    extra.extend(asm_rules.motion(clashes, [joint['name'] for joint in self._joints] + ['一直转的运动副转'],
                                                  lambda number: 's' if number >= len(self._joints) else
                                                  'mm' if self._joints[number]['kind'] == 'slide' else '°'))
                finish(extra)
            self.app.session.query('sweep', {'parts': closed, 'joints': joints, 'rules': rules}, swept)
        self.app.session.query('mass_props', {'parts': posed}, weighed)                   # 和实时检查用同一份结果 (刚查过就不用再算)

    @Slot(str)
    def exportBill(self, where):
        """物料清单存成 CSV。"""
        path = QUrl(where).toLocalFile() if '://' in where else where
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        try:
            bom.write_csv(self.bill(), path)
        except OSError as error:
            self.app.notice.emit(f'存不了：{error}')
            return
        self.app.notice.emit(f'物料清单已保存到 {path}')

    def _check_parts(self):
        if len(self._parts) < 2:
            self.app.notice.emit('装配体里至少要有两个零件：先点“插入零件”')
            return False
        if not self.app.session.model.get('has_body') and any(not part['path'] for part in self._parts):
            self.app.notice.emit('当前零件里还没有实体')
            return False
        return True

    @Slot()
    def runInterference(self):
        if not self._check_parts():
            return
        state = self._assembly
        state.update(clashes=None, error='')

        def done(result, error):
            state.update(clashes=result['clashes'] if result else None, pairs=result['pairs'] if result else 0, error=error)
        self._ask('interference', {'parts': self._posed_parts()}, done)

    @Slot()
    def runSequence(self):
        if not self._check_parts():
            return
        state = self._assembly
        state.update(steps=None, error='')

        def done(result, error):
            state.update(steps=result['steps'] if result else None, error=error)
        self._ask('sequence', {'parts': self._posed_parts()}, done)

    @Slot()
    def runFasteners(self):
        """螺纹检查: 螺丝和螺纹孔自动配对, 查拧入长度、顶不顶孔底、螺纹相位 (见 kernel/fasteners.py)。"""
        if not self._check_parts():
            return
        state = self._assembly
        state.update(fasteners=None, error='')

        def done(result, error):
            state.update(fasteners=result, error=error)
        self._ask('fasteners', {'parts': self._posed_parts()}, done)

    @Slot(str)
    def runStack(self, axis='Z'):
        """尺寸链 / 高度分配: 用视图里已经有的网格包围盒直接算 (不走内核, 一下就好), 见 kernel/stack.py。"""
        from ..kernel import stack
        rows = []
        for number, mesh in self._shown:
            mesh = self._moved_mesh(number, mesh)
            if number in self._hidden_parts:
                continue
            rows.append({'index': number, 'name': self._parts[number]['name'] if number < len(self._parts) else f'零件{number + 1}',
                         'low': mesh['low'], 'high': mesh['high']})
        if not rows:
            self.app.notice.emit('零件还在加载，等视图里画出来再点')
            return
        self._assembly.update(stack=stack.layers(rows, axis or 'Z'), error='')
        self.changed.emit()

    @Slot()
    def alignThreads(self):
        """把螺纹检查算出来的相位写进螺纹孔特征 (零件文件), 再重新画: 螺丝和孔的牙对上。"""
        result = self._assembly.get('fasteners')
        if not result:
            self.app.notice.emit('先点“螺纹检查”')
            return
        changed = 0
        for item in result.get('fix') or []:
            if item.get('phase') is None or not 0 <= item['part'] < len(self._parts):
                continue
            path = self._parts[item['part']].get('path')
            if not path or not str(path).lower().endswith('.gform'):
                continue
            try:
                with open(path, encoding='utf-8') as handle:
                    doc = json.load(handle)
                for feature in doc.get('features') or []:
                    params = feature.get('params') or {}
                    if feature.get('id') == item['feature'] and abs(float(params.get('phase') or 0.0) - item['phase']) > 1e-3:
                        params['phase'] = round(float(item['phase']), 3)
                        changed += 1
                with open(path, 'w', encoding='utf-8') as handle:
                    json.dump(doc, handle, ensure_ascii=False, indent=1)
            except (OSError, ValueError) as error:
                self.app.notice.emit(f'改不了 {path}：{error}')
        self.app.notice.emit(f'对齐了 {changed} 个螺纹孔的相位' if changed else '螺纹相位本来就是对的')
        if changed:
            self._show_parts()
            self.runFasteners()
