"""给 QML 读的属性: 零件树、文档种类、标题、撤销状态、草图工具和捕捉、手势。"""
from __future__ import annotations

import os
from PySide6.QtCore import Property, Slot

from ..sketcher import ALL_SNAPS, QUICK_SNAPS, SNAP_NAMES as QUICK_SNAP_NAMES
from .. import actions, features as table, i18n, materials, planes, sketchgeom
from ..i18n import localized
from .common import OPERATION_HINTS, STATUS_TEXT, TOOL_HINTS
from .signals import (
    changed, formChanged, hoverTextChanged, kindChanged, progressChanged, settingsChanged, sketchChanged, treeChanged)


def _folder_path(feature):
    """特征所在的文件夹 → ['内饰', '座椅'] (没放进文件夹的是 [])。"""
    return [part for part in str(feature.get('folder') or '').split('/') if part]


class StateMixin:
    """给 QML 读的属性 (控制器的一部分)。"""

    # ---- 给 QML 读的属性 ----
    @Property('QVariantList', notify=treeChanged)
    def tree(self):
        """左侧的零件树 (见 _build_tree)。不跟着 changed 走: 那个信号一次操作要发好几回 (开始重算、算完、选中…),
        每回 QML 都把整棵树的委托 (每行带一排小按钮) 销毁重建, 特征多了一回就要几十毫秒。"""
        if self._tree_rows is None:
            self._tree_rows = self._build_tree()
        return self._tree_rows

    def _refresh_tree(self):
        """changed / sketchChanged 之后: 重新排一遍树 (很快), 内容真的变了才通知 QML。"""
        rows = self._build_tree()
        target = self.session.selection.get('feature')
        if target != getattr(self, '_revealed', None):     # 选中的特征换了 (多半是在视图里点的): 它在收起的文件夹里就展开
            self._revealed = target
            closed = [identifier for identifier in self._folder_chains.get(target, ()) if identifier in self._collapsed]
            if closed:
                self._collapsed.difference_update(closed)
                rows = self._build_tree()
        if rows != self._tree_rows:
            self.treeAboutToChange.emit()
            self._tree_rows = rows
            self.treeChanged.emit()

    def _process_badge(self, feature):
        """设计树里特征名前面的工艺徽标 (绑定工艺之后) 和设计检查标红。"""
        process = feature.get('process') or {}
        why = process.get('why') or ''
        if process.get('alternatives'):
            why += '\n备选：' + '，'.join(f'{item["name"]} ¥{item["cost"]:.0f}' for item in process['alternatives'])
        return {'process': process.get('short') or '', 'processColor': process.get('color') or '',
                'processName': process.get('name') or '', 'processWhy': why, 'processAuto': process.get('auto', True),
                'flagged': feature['id'] in (getattr(self, '_check_red', None) or ())}

    @localized
    def _build_tree(self):
        """左侧的零件树, 一行一个节点 (depth 是缩进层数):
            零件
              前视 / 上视 / 右视基准面、原点
              特征… (草图收在用它的拉伸下面, 和 SOLIDWORKS 一样; 正在画的新草图排在最后)
              文件夹 (kind='folder', 特征的 'folder' = '内饰/座椅' 用 / 分层): 连着的同一文件夹的特征收在它下面;
                  folders = 这一行套在几层文件夹里 (画彩色缩进线用), child = 收在特征下面的草图
              回退线 (kind='rollback'): 它下面的特征暂不计算; 拖到哪两行之间, 用那一行的 before / after (= 只算前几个特征)
        """
        document, selection = self.session.document, self.session.selection
        status = self.session.model.get('status', {})
        editing = self._sketch

        def row(kind, identifier, name, depth, **more):
            base = {'kind': kind, 'id': identifier, 'name': name, 'type': kind, 'depth': depth, 'state': 'ok',
                    'note': '', 'suppressed': False, 'selected': False, 'rolled': False, 'editing': False,
                    'expandable': False, 'expanded': False}
            base.update(more)
            return base

        name = os.path.splitext(os.path.basename(document.path))[0] if document.path else '零件1'
        rows = [row('root', '', name, 0)]
        rows.append(row('material', '', f'材质 <{document.props.get("material") or "未指定"}>', 1))
        for plane in ('XZ', 'XY', 'YZ'):            # 前视、上视、右视: 和 SOLIDWORKS 的顺序一样
            rows.append(row('plane', plane, planes.NAMES[plane], 1, selected=plane == selection.get('plane'),
                            shown=self.viewport is not None and self.viewport.plane_shown(plane),
                            editing=editing is not None and editing.feature is None and editing.plane == plane))
        rows.append(row('origin', '', '原点', 1))

        by_id = {feature['id']: feature for feature in document.features}
        info = self.session.model.get('info') or {}
        absorbed = {}                               # 草图 id → 用它的第一个特征 (拉伸、旋转、孔…)
        for feature in document.features:
            source = feature['params'].get('sketch') if feature['type'] != 'sketch' else None
            if source in by_id and by_id[source]['type'] == 'sketch' and source not in absorbed:
                absorbed[source] = feature['id']
        children = {owner: sketch for sketch, owner in absorbed.items()}

        def feature_row(feature, depth):
            state = status.get(feature['id'], 'pending')
            failed = state.startswith('error: ')
            position = document.features.index(feature)
            spec = table.SPECS.get(feature['type'], {})
            return row('feature', feature['id'], feature['name'], depth, type=feature['type'],
                       mark=spec.get('mark', ''), tint=spec.get('tint', ''),
                       icon='cut' if feature['type'] == 'extrude' and feature['params'].get('op') == 'cut' else feature['type'],
                       state='error' if failed else state,
                       note=state[7:] if failed else (STATUS_TEXT.get(state, '') or info.get(feature['id'], '')),
                       suppressed=bool(feature.get('suppressed')),
                       selected=feature['id'] == selection.get('feature'),
                       rolled=document.upto is not None and position >= document.upto,
                       editing=editing is not None and editing.feature == feature['id'],
                       hidden=self._is_hidden(feature),
                       line=self._is_line_feature(feature),
                       expandable=feature['id'] in children,
                       expanded=feature['id'] in children and feature['id'] not in self._collapsed,
                       **self._process_badge(feature))

        total = len(document.features)
        upto = total if document.upto is None else document.upto
        bar = row('rollback', '', '', 1, count=upto, total=total)
        placed = False
        shown = [feature for feature in document.features if feature['id'] not in absorbed]
        opened = []                                     # 现在套着的文件夹: [(名字, 行)...], 外层在前
        self._folder_chains = {}                        # 特征 id → 它套在哪几层文件夹里 (文件夹行的 id): 选中它时展开用
        for number, feature in enumerate(shown):
            position = document.features.index(feature)
            first = position
            if feature['id'] in children:               # 草图紧挨在它前面: 回退到这一行之前时连草图一起退
                source = document.features.index(by_id[children[feature['id']]])
                first = source if source == position - 1 else position
            if not placed and position >= upto:
                rows.append(bar)
                placed = True
            path = _folder_path(feature)
            keep = 0
            while keep < min(len(path), len(opened)) and opened[keep][0] == path[keep]:
                keep += 1
            del opened[keep:]
            for level in range(keep, len(path)):        # 进新的一层文件夹: 先出它的标题行
                identifier = 'folder:' + '/'.join(path[:level + 1]) + '@' + feature['id']
                count = 0
                for other in shown[number:]:            # 这一段 (连着的) 里有几个特征在它下面
                    if _folder_path(other)[:level + 1] != path[:level + 1]:
                        break
                    count += 1
                header = row('folder', identifier, path[level], 1 + level, note='', count=count, folders=level,
                             expandable=True, expanded=identifier not in self._collapsed, before=first, after=first)
                if not any(item[1]['id'] in self._collapsed for item in opened):
                    rows.append(header)
                opened.append((path[level], header))
            hidden = any(item[1]['id'] in self._collapsed for item in opened)
            self._folder_chains[feature['id']] = [item[1]['id'] for item in opened]
            if feature['id'] in children:
                self._folder_chains[children[feature['id']]] = self._folder_chains[feature['id']] + [feature['id']]     # 草图还收在特征下面
            line = dict(feature_row(feature, 1 + len(path)), before=first, after=position + 1, folders=len(path))
            for _, header in opened:                    # 文件夹里有出错的特征: 文件夹也标红 (收起来也看得见)
                if line['state'] == 'error':
                    header['state'] = 'error'
            if hidden:
                continue
            rows.append(line)
            if feature['id'] in children and feature['id'] not in self._collapsed:
                rows.append(dict(feature_row(by_id[children[feature['id']]], 2 + len(path)), before=-1, after=position + 1,
                                 folders=len(path), child=True))
        if total and not placed:
            rows.append(bar)
        if editing is not None and editing.feature is None:
            rows.append(row('feature', '', editing.name, 1, type='sketch', editing=True))
        return rows

    @Slot(str)
    def toggleExpand(self, identifier):
        self._collapsed.symmetric_difference_update({identifier})
        self.changed.emit()

    @Property(str, notify=sketchChanged)
    def tab(self):
        return self._tab

    # ---- 文档的种类: 零件 / 装配体 / 工程图 ----
    @Property(str, notify=kindChanged)
    def docKind(self):
        return self._kind

    def _set_kind(self, kind):
        if kind == self._kind:
            return
        if self._kind == 'assembly':
            self.sim.unpin()
        if getattr(self, '_check', {}).get('open'):        # 换了文档种类: 上一份检查结果说的不是现在这个了
            self.closeCheck()
        if hasattr(self, '_check'):
            self.clearCheck()
        self._kind = kind
        self._tab = {'part': 'feature', 'assembly': 'assembly', 'drawing': 'drawing'}[kind]
        self._drop_context()
        self.kindChanged.emit()
        self.sketchChanged.emit()
        self.changed.emit()

    @Slot(str)
    def newOf(self, kind):
        """新建: part 零件 / assembly 装配体 / drawing 工程图。
        装配体和工程图是在现在打开的零件上做的: 零件有实体, 它就是装配体的第一个零件 / 工程图画的那个零件。"""
        if kind not in ('part', 'assembly', 'drawing') or not self._leave_modes():
            return
        self._set_return('')
        self._set_start(False)
        if kind == 'part':
            self._set_kind('part')
            self._run('new_document')
        elif kind == 'assembly':
            self._set_kind('part')              # 先回到零件 (要是本来就在一个装配体里, 这一步把它收掉)
            self._set_kind('assembly')
            self.sim.pin()
        else:
            self._set_kind('drawing')
            self.drawing.begin()

    @Slot()
    def backToPart(self):
        """从装配体 / 工程图回到零件 (零件一直开着, 没动过)。从存过的装配体回来的, 零件页上能再返回它。"""
        back = self.sim.path if self._kind == 'assembly' else ''
        self._set_kind('part')
        self._set_return(back)

    def _set_return(self, path):
        if path != self._return:
            self._return = path or ''
            self.changed.emit()

    @Property(str, notify=changed)
    def returnAssembly(self):
        """零件页上 "返回装配体" 回哪个装配体 (只要文件名; 空 = 不是从装配体过来的, 不显示)。"""
        return os.path.splitext(os.path.basename(self._return))[0] if self._return and self._kind == 'part' else ''

    @Slot()
    def backToAssembly(self):
        """回到刚才那个装配体 (和 SOLIDWORKS 里改完零件切回装配体窗口一样): 零件改过就先存, 装配体按文件重新读,
        刚改的零件跟着重算。正在画草图时先要 "完成草图" 或 "放弃"。"""
        path = self._return
        if not path or self._kind != 'part' or not self._leave_modes():
            return
        document = self.session.document
        if document.dirty and document.path:
            self._run('save_document', {}, lambda result: result.get('ok') and self.openDocument(path))
        else:
            self.openDocument(path)

    @Property('QVariantList', notify=changed)
    def layoutSketches(self):
        """装配体的设计树上 "原点" 下面那几个布局草图: [{'id', 'name', 'selected'}...] (装配体里画的草图)。"""
        if self._kind != 'assembly' or not self.sim.layout_mode():
            return []
        chosen = self.session.selection.get('feature')
        return [{'id': feature['id'], 'name': feature['name'], 'selected': feature['id'] == chosen}
                for feature in self.session.document.features if feature['type'] == 'sketch']

    @Property('QVariantList', notify=settingsChanged)
    @localized
    def featureMenus(self):
        """特征页上的下拉菜单: [{'id', 'title', 'items': [{'id', 'title'}...]}...]。"""
        return [{'id': identifier, 'title': title, 'items': [{'id': kind, 'title': table.SPECS[kind]['title']} for kind in kinds]}
                for identifier, title, kinds in table.MENUS]

    @Slot(str)
    def setTab(self, name):
        """翻工具栏的页。只是翻页, 不进也不出草图。"""
        pages = {'part': ('feature', 'sketch', 'evaluate', 'simulate'), 'assembly': ('assembly', 'sketch', 'evaluate')}
        if name in pages.get(self._kind, ()) and name != self._tab:
            self._tab = name
            self.sketchChanged.emit()

    @Property(bool, notify=changed)
    def busy(self):
        return self.session.busy

    @Property('QVariantMap', notify=progressChanged)
    def progress(self):
        """重算做到哪了 (进度条用): {'done' 做完几个特征, 'total' 一共几个, 'name' 正在算的特征, 'fraction' 0~1,
        'loading' 是不是在加载装配体的零件 (那时 done / total 数的是零件)}; 没在算时 total = 0。"""
        state = self.session.progress if self.session.busy else None
        loading = state is None and self.session.query_progress is not None
        if loading:
            state = self.session.query_progress
        live = self.sim._live
        if not state and self.sim._live_waiters and live['running']:     # 工具栏 "设计检查" 在等件与件的检查算完
            total = max(live['total'], 1)
            return {'done': live['done'], 'total': live['total'], 'name': '', 'fraction': live['done'] / total,
                    'loading': True, 'what': 'pairs'}
        if not state:
            return {'done': 0, 'total': 0, 'name': '', 'fraction': 0.0, 'loading': False, 'what': ''}
        index, total, name = state[:3]
        return {'done': index, 'total': total, 'name': name, 'fraction': index / max(total, 1), 'loading': loading,
                'what': (state[3] if len(state) > 3 else 'parts') if loading else ''}

    @Property(bool, notify=changed)
    def canUndo(self):
        if self._kind == 'drawing':
            return False
        return bool(self._sketch_history) if self._sketch is not None else self.session.document.can_undo()

    @Property(bool, notify=changed)
    def canRedo(self):
        return self._kind != 'drawing' and self._sketch is None and self.session.document.can_redo()

    @Property(str, notify=changed)
    @localized
    def title(self):
        if self._kind == 'assembly':            # 布局草图改了也算装配体改了
            dirty = self.sim.dirty or (self.sim.layout_mode() and self.session.document.dirty)
            return (os.path.basename(self.sim.path) if self.sim.path else i18n.tr('未命名装配体')) + (' *' if dirty else '')
        if self._kind == 'drawing':
            return (os.path.basename(self.drawing.path) if self.drawing.path else i18n.tr('未命名工程图')) + (' *' if self.drawing.dirty else '')
        document = self.session.document
        name = os.path.basename(document.path) if document.path else '未命名零件'
        return f'{name}{" *" if document.dirty else ""}'

    @Property(str, notify=changed)
    def documentPath(self):
        return self.session.document.path or ''

    @Property(str, notify=changed)
    @localized
    def bodyText(self):
        model = self.session.model
        if not model.get('has_body'):
            return '还没有实体'
        size, volume = model['props']['size'], model['props']['volume']
        text = f'{size[0]:.4g} × {size[1]:.4g} × {size[2]:.4g} mm\n体积 {volume / 1000:.4g} cm³'
        heavy = materials.density(self.session.document.props.get('material'))
        if heavy:
            mass = volume / 1000 * heavy
            text += f'\n质量 {mass / 1000:.4g} kg' if mass >= 1000 else f'\n质量 {mass:.4g} g'
        return text

    @Property(str, notify=changed)
    @localized
    def selectionText(self):
        selection = self.session.selection
        parts = []
        if selection.get('plane'):
            parts.append(planes.NAMES[selection['plane']])
        if selection['faces']:
            parts.append(f'{len(selection["faces"])} 个面')
        if selection['edges']:
            parts.append(f'{len(selection["edges"])} 条边')
        return '已选 ' + '、'.join(parts) if parts else ''

    @Property(str, notify=hoverTextChanged)
    @localized
    def hoverText(self):
        return self._hover

    @Property('QVariant', notify=formChanged)
    @localized
    def form(self):
        return self._form

    @Property(bool, notify=sketchChanged)
    def sketchActive(self):
        return self._sketch is not None

    @Property(str, notify=sketchChanged)
    def sketchTool(self):
        return self._sketch.tool if self._sketch is not None else ''

    @Property(str, notify=sketchChanged)
    @localized
    def hint(self):
        """视图上方的一句操作提示 (现在该干什么)。"""
        if self._picking_plane:
            if self._rapid:
                return '快速草图：点一个基准面或零件上的平面就在它上面接着画（Esc 结束）'
            return '选一个基准面或零件上的一个平面来画草图（在视图里或左侧列表里点；Esc 取消）'
        if self._sketch is not None:
            if self._sketch.operation is not None:
                return OPERATION_HINTS[self._sketch.operation['kind']]
            if self._sketch.snap_only:
                return f'快速捕捉：下一次点击只吸到“{QUICK_SNAP_NAMES[self._sketch.snap_only]}”'
            return TOOL_HINTS[self._sketch.tool]
        return ''

    @Property(str, notify=sketchChanged)
    def sketchOperation(self):
        """草图里开着面板的操作: pattern / repair / 空。"""
        editor = self._sketch
        return editor.operation['kind'] if editor is not None and editor.operation is not None else ''

    @Property(bool, notify=sketchChanged)
    def rapidSketch(self):
        return self._rapid

    @Slot()
    def toggleRapidSketch(self):
        """快速草图开关。开着时: 进草图不把视角转正 (在当前的立体视角里直接画), 完成一个草图后接着等你点下一个
        基准面, 不用每次再点一遍工具。"""
        self._rapid = not self._rapid
        self.notice.emit('快速草图已打开：进草图不转视角，画完一个接着点下一个基准面' if self._rapid else '快速草图已关闭')
        self.sketchChanged.emit()

    @Property('QVariantList', notify=settingsChanged)
    @localized
    def quickSnaps(self):
        return [{'id': kind, 'text': QUICK_SNAP_NAMES[kind]} for kind in QUICK_SNAPS]

    @Property(str, notify=sketchChanged)
    def quickSnap(self):
        return (self._sketch.snap_only or '') if self._sketch is not None else ''

    @Slot(str)
    def setQuickSnap(self, kind):
        """快速捕捉: 下一次点击只吸到这一种点 (端点 / 中点 / 圆心 / 象限点 / 交点 / 线上), 范围也更大; 点完自动恢复。"""
        if self._sketch is None:
            self.notice.emit('快速捕捉在画草图时用：先进入草图')
            return
        self._sketch.snap_only = kind if kind in QUICK_SNAPS and kind != self._sketch.snap_only else None
        self.sketchChanged.emit()

    @Slot()
    def sketchPattern(self):
        self._sketch_action(lambda editor: editor.start_pattern())

    @Slot()
    def sketchRepair(self):
        self._sketch_action(lambda editor: editor.start_repair())

    @Slot()
    def sketchRelation(self):
        self._sketch_action(lambda editor: editor.start_relation())

    @Slot(str)
    def sketchPick(self, item):
        """草图页下拉菜单里点了一项: 工具名, 或 pattern / cpattern (阵列)、silhouette / section (侧影 / 交叉曲线)。"""
        if item == 'pattern':
            self.sketchPattern()
        elif item == 'relation':
            self.sketchRelation()
        elif item == 'repair':
            self.sketchRepair()
        elif item == 'cpattern':
            self._sketch_action(lambda editor: editor.start_circular_pattern())
        elif item in ('silhouette', 'section'):
            self._sketch_outline(item)
        else:
            self.useSketchTool(item)

    def _sketch_outline(self, mode):
        """侧影实体 / 交叉曲线: 让内核算出实体在草图平面上的轮廓线 / 交线, 像实体的边一样摆出来给用户点着拷进草图。"""
        editor = self._sketch
        if editor is None:
            self.notice.emit('这个功能在画草图时用：先进入草图')
            return
        name = '侧影实体' if mode == 'silhouette' else '交叉曲线'
        if not self.session.model.get('has_body'):
            self.notice.emit(f'还没有实体：{name}是从实体上取线')
            return

        def done(lines, error):
            if self._sketch is not editor:              # 算的时候用户已经退出了这个草图
                return
            if error:
                self.notice.emit(f'{name}没有算出来：{error}')
                return
            found = sketchgeom.fit_lines(lines or [])
            if mode == 'silhouette':                    # 轮廓 = 曲面转过去的那几条线 + 本来就有的边
                edges = sketchgeom.project_edges(self.session.model, editor.plane, editor.offset)
                found += [shape for shape in edges if not any(sketchgeom._same(shape, other) for other in found)]
            if not found:
                self.notice.emit('草图平面没有切到实体' if mode == 'section' else '没有找到轮廓线')
                return
            editor.references = found
            editor.set_tool('convert')
            self._sketch_changed()
            self.notice.emit(f'{name}：蓝色的线就是，点哪条就把哪条拷进草图' if mode == 'silhouette'
                             else '交叉曲线：草图平面切开实体的交线已经标成蓝色，点哪条就把哪条拷进草图')

        frame = planes.frame(editor.plane, editor.offset)
        self.session.outline(mode, [vector.tolist() for vector in frame[:3]], done)

    @Property('QVariantList', notify=sketchChanged)
    @localized
    def snapToggles(self):
        """一直开着的捕捉: [{'id', 'text', 'on'}...] (点捕捉 = 端点, 中心点, 象限点, 交叉点, 最近端, 水平/竖直, 网格…)。"""
        return [{'id': kind, 'text': QUICK_SNAP_NAMES[kind], 'on': kind in self._snaps} for kind in ALL_SNAPS]

    @Slot(str)
    def toggleSnap(self, kind):
        if kind in ALL_SNAPS:
            self._snaps.symmetric_difference_update({kind})     # 草图编辑器拿的是同一个集合, 立刻生效
            self.sketchChanged.emit()
            if kind == 'grid' and self.viewport is not None:
                self.viewport.refresh_sketch()                     # 网格跟着网格捕捉显示 / 隐藏

    def _sketch_action(self, action):
        if self._sketch is None:
            self.notice.emit('这个功能在画草图时用：先进入草图')
            return
        action(self._sketch)
        self._sketch_changed()

    @Property('QVariantList', notify=sketchChanged)
    @localized
    def gestures(self):
        """现在这套手势轮上的 8 格 (图标和文字)。"""
        return self._wheel_rows('sketch' if self._sketch is not None else 'model')

    @Slot(int)
    def runGesture(self, index):
        rows = self.settings.wheel('sketch' if self._sketch is not None else 'model')
        if 0 <= index < len(rows):
            self.runAction(rows[index])

    def _wheel_rows(self, which):
        return [{'id': identifier, 'icon': actions.BY_ID[identifier]['icon'], 'text': actions.short(identifier),
                 'title': actions.BY_ID[identifier]['title']} for identifier in self.settings.wheel(which)]
