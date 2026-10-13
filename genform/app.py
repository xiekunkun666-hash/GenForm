# -*- coding: utf-8 -*-
"""界面控制器: QML 和会话之间的桥。

QML 只读这里的属性、调这里的槽; 这里把每个操作变成一条命令交给会话 (和 AI 接口同一条路),
再把会话的变化 (特征列表、模型、忙碌状态) 报给 QML 和三维视图。

草图编辑是这里唯一的 "模式": 进入后左键交给草图编辑器, 画的东西先只在编辑器里, 点 "完成草图" 才变成
一条 sketch / edit_feature 命令 — 所以放弃草图不会在历史里留下任何东西。
"""
from __future__ import annotations

import copy
import math
import os

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from . import actions
from . import features as table
from . import forms, materials, planes, sketchgeom
from .settings import Settings
from .document import DocumentError
from .sketcher import ALL_SNAPS, QUICK_SNAPS, SNAP_NAMES as QUICK_SNAP_NAMES, SketchEditor

STATUS_TEXT = {'ok': '', 'suppressed': '已抑制', 'skipped': '未计算', 'pending': '计算中'}
TOOL_HINTS = {
    'select': '点选图形（Ctrl 加选，空白处拖出方框框选）；拖动移动；拖控制点改形状；双击选一整串；Delete 删除',
    'line': '连续点出直线，点回起点闭合；回车、双击或 Esc 结束这一串',
    'centerline': '中心线：和直线一样画，画出来的是构造线（虚线）——只作参考和旋转轴，不参与拉伸',
    'midline': '中点线：点中点，再点一端（另一端对称着出来）',
    'rect': '点两个对角，或按住拖出矩形',
    'crect': '中心矩形：点中心，再点一个角',
    'rect3': '3 点边角矩形：点一条边的两端，再拉出另一边的长度',
    'crect3': '3 点中心矩形：点中心 → 点一条边的中点 → 拉出这条边的半长',
    'pgram': '平行四边形：依次点三个角，第四个角自动补上',
    'circle3': '周边圆：点圆周上的三个点',
    'cslot': '中心点直槽口：点槽的中心 → 点一头的圆心 → 拉出槽宽再点',
    'aslot3': '三点圆弧槽口：点中心线圆弧的起点 → 终点 → 弧上一点 → 拉出槽宽再点',
    'caslot': '中心点圆弧槽口：点圆心 → 点起点 → 顺着要画的方向转到终点再点 → 拉出槽宽再点',
    'sspline': '样式样条曲线：依次点控制点（曲线被它们拉过去，不经过中间的点），回车或双击结束；最多 12 个',
    'equation': '方程式驱动的曲线：点一下放置，再在左上角的面板里改式子和范围',
    'dimension': '智能尺寸：点一个图形改它的尺寸；接着点另一个图形 = 改它们之间的距离',
    'extend': '延伸实体：点直线或圆弧要延长的那一头，延到碰上别的线为止',
    'circle': '点圆心，再点圆周上一点',
    'arc': '圆心/起/终点画弧：点圆心 → 点起点 → 顺着要画的方向转到终点再点',
    'slot': '直槽口：点第一个圆心 → 点第二个圆心 → 拉出槽宽再点',
    'ngon': '多边形：点中心，再点一个顶点（边数在左上角的面板里改）',
    'ellipse': '椭圆：点中心 → 点长轴端点 → 拉出短轴再点',
    'spline': '样条曲线：依次点经过的点，回车或双击结束，点回起点闭合',
    'point': '点：单击放置一个点（可以被别的图形捕捉）',
    'text': '文本：单击放置，再在左上角的面板里改文字和字高（先选中一条曲线再点“文本”= 沿这条曲线排）',
    'fillet': '绘制圆角：点两条直线相交的尖角（半径在左上角的面板里改）',
    'trim': '剪裁实体：点要剪掉的那一段，剪到它和别的线相交的地方',
    'offset': '等距实体：点一个图形，再往要偏的那一侧移动，到合适的距离再点',
    'mirror': '镜向实体：点两个点定出镜向轴（原来的图形保留）',
    'move': '移动实体：点起点，再点终点',
    'convert': '转换实体引用：点实体的边（蓝色的线），把它拷进草图',
}
OPERATION_HINTS = {'pattern': '线性草图阵列：在左上角的面板里填数量和间距，确定', 'repair': '修复草图：问题在视图里用点标出来了',
                   'cpattern': '圆周草图阵列：在左上角的面板里填数量、总角度和中心，确定',
                   'relation': '添加几何关系：在左上角的面板里选一种关系，点“添加”',
                   'dimension': '智能尺寸：在左上角的面板里改数字；再点另一个图形 = 改它们之间的距离'}
# 视图上方那排按钮用的几张表
DISPLAY_STYLES = [('shaded_edges', '带边线上色'), ('shaded', '上色'), ('hlr', '消除隐藏线'), ('hlv', '隐藏线可见'), ('wire', '线架图')]
SCENE_NAMES = [('auto', '跟随界面主题'), ('fade', '三点渐褪'), ('white', '单白色'), ('gray', '带顶光源的灰色'), ('spot', '柔光聚光灯')]
ORIENTATIONS = [('front', '前视'), ('back', '后视'), ('left', '左视'), ('right', '右视'), ('top', '上视'), ('bottom', '下视'),
                ('iso', '等轴测'), ('normal', '正视于')]
SHOW_ITEMS = [('main_planes', '主要基准面'), ('planes', '基准面'), ('axes', '基准轴'), ('csys', '坐标系'), ('points', '点'),
              ('origin', '原点'), ('curves', '曲线'), ('sketches', '草图'), ('sketch3d', '3D 草图'), ('com', '质心'), ('bbox', '边界框')]
SHOW_OF = {'plane': 'planes', 'axis': 'axes', 'csys': 'csys', 'point': 'points', 'com': 'com', 'bbox': 'bbox',
           'sketch': 'sketches', 'sketch3d': 'sketch3d'}       # 特征类型 → 归哪一项管 (其余的曲线特征都归 curves)
HOLE_KINDS = ('hole', 'hole_adv', 'stud')       # 位置由一个草图定的孔 / 螺柱: 有 "编辑孔草图"
RESERVED_KEYS = ('esc', 'escape', 'return', 'enter')    # 取消和确认: 不让改派给别的功能
DRAW_TOOLS = ('line', 'centerline', 'midline', 'rect', 'crect', 'rect3', 'crect3', 'pgram', 'circle', 'circle3', 'arc', 'slot',
              'cslot', 'aslot3', 'caslot', 'ngon', 'ellipse', 'spline', 'sspline', 'equation', 'point', 'text')


def _local(path):
    """QML 文件对话框给的是 file:/// 地址。"""
    text = str(path)
    return QUrl(text).toLocalFile() if text.startswith('file:') else text


class _ViewAdapter:
    """会话的视图命令 (set_view / screenshot) 落到三维视图控件上。"""

    def __init__(self, controller):
        self._controller = controller

    def set_view(self, name):
        viewport = self._controller.viewport
        if viewport is None:
            raise DocumentError('三维视图还没准备好')
        viewport.setView(name)
        return {'view': name}

    def screenshot(self, path, view):
        viewport = self._controller.viewport
        if viewport is None:
            raise DocumentError('三维视图还没准备好')
        if view:
            viewport.setView(view)

        def later(reply):
            def saved(result):
                viewport.shotSaved.disconnect(saved)
                reply({'ok': True, 'path': result} if result else {'ok': False, 'error': '截图保存失败'})
            viewport.shotSaved.connect(saved)
            viewport.request_shot(path)
        return later


class AppController(QObject):
    changed = Signal()              # 特征列表 / 忙碌 / 撤销状态 / 标题 / 选择
    formChanged = Signal()
    sketchChanged = Signal()        # 进入或退出草图、换工具、等着选基准面
    hoverTextChanged = Signal()
    notice = Signal(str)            # 要让用户看到的一句话 (出错原因等)
    viewChanged = Signal()          # 显示样式 / 布景 / 剖切 / 显示哪些东西 / 存下来的视角
    settingsChanged = Signal()      # 快捷键 / 手势轮改了
    dialogRequested = Signal(str)   # 要界面打开一个对话框: open / save / export / settings
    contextRequested = Signal(float, float)     # 在视图里点中了东西: 在这个位置 (视图里的像素) 弹出小工具条; 负数 = 收起来
    appearanceRequested = Signal()  # 打开 "编辑外观"

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.viewport = None
        self.window = None
        self._form = None
        self._hover = ''
        self._shown_revision = None
        self._sketch = None             # 正在编辑的草图 (SketchEditor)
        self._sketch_history = []       # 草图里每一步之前的轮廓 (草图内的撤销)
        self._sketch_seen = []          # 上一次看到的轮廓: 和现在不一样就说明刚才那一下改了东西
        self._picking_plane = False     # 点了 "草图" 但还没选基准面
        self._planes_were_visible = True    # 为了让用户选基准面临时把它们显示出来之前, 原来是不是显示着
        self._pending_tool = 'select'   # 选好基准面进草图后直接拿起哪个工具
        self._tab = 'feature'           # 工具栏现在翻在哪一页: feature / sketch
        self._collapsed = set()         # 零件树里被用户收起来的特征 (它下面的草图不显示)
        self._rapid = False             # 快速草图: 进草图不转视角, 画完一个接着选下一个基准面
        self._snaps = set(ALL_SNAPS)        # 开着的草图捕捉 (所有草图共用)
        self._outliner = None           # 草图文本的字形 (第一次用到时才建)
        self._view = {'style': 'shaded_edges', 'scene': 'auto', 'perspective': True, 'cartoon': False, 'hideAll': False,
                      'section': False, 'sectionPlane': 'XZ', 'sectionOffset': 0.0, 'sectionFlip': False}
        self._off = set()               # "隐藏/显示项目" 里关掉的 (SHOW_ITEMS 的键)
        self._views = []                # 用户存下来的视角: [(名称, 视角)...] (只在这次打开期间)
        self.settings = Settings()      # 快捷键、手势轮 (存在用户目录里, 和零件无关)
        self._hidden_ids = set()        # 用户单独隐藏的草图 / 曲线 / 参考几何体 (特征 id; 只在这次打开期间)
        self._body_hidden = False       # 实体被隐藏了
        self._context = None            # 视图里刚点中的东西: {'kind', 'id', 'feature', 'faces' 这个位置一路穿过的面}
        session.view = _ViewAdapter(self)
        session.listen(self._on_session)

    # ---- 窗口和三维视图接进来 ----
    def attach_window(self, window):
        """无边框窗口: 装上系统级的最大化 / 贴边 / 阴影行为。"""
        self.window = window
        from .win32_frame import enable_native_frame, round_corners
        enable_native_frame(window)
        round_corners(window)

    def attach_viewport(self, viewport):
        self.viewport = viewport
        viewport.picked.connect(self._on_picked)
        viewport.boxed.connect(self._on_boxed)
        viewport.hoverChanged.connect(self._on_hover)
        viewport.sketchEdited.connect(self._on_sketch_edited)
        viewport.gestureTriggered.connect(self.runGesture)
        viewport.planesVisibleChanged.connect(self._planes_toggled)
        self._apply_view(rebuild=False)
        viewport.set_model(self.session.model)

    def _on_session(self):
        if self.viewport is not None and self._shown_revision != (self.session.model_revision, id(self.session.model)):
            self._shown_revision = (self.session.model_revision, id(self.session.model))
            self.viewport.set_hidden(self._hidden_features(), rebuild=False)
            self.viewport.set_names({feature['id']: feature['name'] for feature in self.session.document.features})
            self.viewport.set_model(self.session.model)
            self._drop_context()
            self.viewport.set_selection(self.session.selection)
            self._refresh_form_info()
        self._push_appearance()
        self.changed.emit()

    # ---- 视图上方那排按钮: 显示样式、布景、剖切、显示哪些东西、视角 ----
    def _hidden_features(self):
        off = {key for key, _ in SHOW_ITEMS} if self._view['hideAll'] else self._off
        return {feature['id'] for feature in self.session.document.features
                if (SHOW_OF.get(feature['type']) or ('curves' if feature['type'] in table.CURVE_KINDS else None)) in off
                or feature['id'] in self._hidden_ids}

    def _body_color(self):
        props = self.session.document.props
        return materials.rgb(props.get('color')) or materials.rgb(materials.color(props.get('material')))

    def _push_appearance(self):
        if self.viewport is not None and self.viewport._display['color'] != self._body_color():
            self.viewport.set_display(color=self._body_color())

    def _apply_view(self, rebuild=True):
        if self.viewport is None:
            return
        view = self._view
        section = {'plane': view['sectionPlane'], 'offset': view['sectionOffset'], 'flip': view['sectionFlip']} if view['section'] else None
        self.viewport.set_hidden(self._hidden_features(), rebuild)
        self.viewport.set_display(style=view['style'], scene=view['scene'], cartoon=view['cartoon'], perspective=view['perspective'],
                                  section=section, color=self._body_color(),
                                  origin=not view['hideAll'] and 'origin' not in self._off, planes_off=view['hideAll'],
                                  body=not self._body_hidden)
        self.viewChanged.emit()

    def _planes_toggled(self):
        self.viewChanged.emit()
        self.changed.emit()

    @Property('QVariantMap', notify=viewChanged)
    def viewState(self):
        props = self.session.document.props
        return dict(self._view, color=props.get('color') or '', saved=len(self._views))

    @Property('QVariantList', constant=True)
    def displayStyles(self):
        return [{'id': key, 'title': title} for key, title in DISPLAY_STYLES]

    @Property('QVariantList', constant=True)
    def sceneNames(self):
        return [{'id': key, 'title': title, 'icon': 'scene'} for key, title in SCENE_NAMES]

    @Property('QVariantList', notify=viewChanged)
    def orientations(self):
        rows = [{'id': key, 'title': title} for key, title in ORIENTATIONS]
        rows.append({'id': 'save_view', 'title': '新视图（记下现在的视角）', 'line': True})
        rows += [{'id': f'view:{index}', 'title': name, 'icon': 'cube'} for index, (name, _) in enumerate(self._views)]
        return rows

    @Property('QVariantList', notify=viewChanged)
    def showItems(self):
        """隐藏/显示项目: [{'id', 'title', 'icon', 'checked'}...]; 第一项是 "隐藏所有类型"。"""
        everything = self._view['hideAll']
        rows = [{'id': 'hide_all', 'title': '隐藏所有类型', 'icon': 'eye_off', 'checked': everything}]
        for index, (key, title) in enumerate(SHOW_ITEMS):
            on = self.viewport.planesVisible if key == 'main_planes' and self.viewport is not None else key not in self._off
            rows.append({'id': key, 'title': title, 'icon': 'show_' + key, 'checked': bool(on) and not everything, 'line': index == 0})
        return rows

    @Property('QVariantList', constant=True)
    def appearanceColors(self):
        return list(materials.APPEARANCES)

    @Property('QVariantList', notify=changed)
    def materialList(self):
        chosen = self.session.document.props.get('material') or ''
        rows = [{'id': '', 'title': '未指定', 'icon': 'material', 'checked': chosen == ''}]
        return rows + [{'id': name, 'title': f'{name}　{value:g} g/cm³', 'icon': 'material', 'checked': chosen == name}
                       for name, value, _ in materials.MATERIALS]

    @Slot(str)
    def setMaterial(self, name):
        self._run('set_material', {'name': name})

    @Slot(str)
    def setAppearance(self, color):
        self._run('set_appearance', {'color': color}, lambda result: self.viewChanged.emit())

    @Slot(str)
    def setDisplayStyle(self, style):
        if style in dict(DISPLAY_STYLES):
            self._view['style'] = style
            self._apply_view(rebuild=False)

    @Slot(str)
    def setScene(self, name):
        if name in dict(SCENE_NAMES):
            self._view['scene'] = name
            self._apply_view(rebuild=False)
            self._sync_sketch() if self._sketch is not None else None

    @Slot(str)
    def toggleViewSetting(self, key):
        if key in ('perspective', 'cartoon', 'section', 'sectionFlip'):
            self._view[key] = not self._view[key]
            self._apply_view(rebuild=False)

    @Slot(str, float)
    def setSection(self, plane, offset):
        """剖切视图: 用哪个基准面切、沿法向偏多少。"""
        if plane in planes.PLANES and math.isfinite(offset):
            self._view.update(section=True, sectionPlane=plane, sectionOffset=float(offset))
            self._apply_view(rebuild=False)

    @Slot(str)
    def toggleShow(self, key):
        if key == 'hide_all':
            self._view['hideAll'] = not self._view['hideAll']
        elif key == 'main_planes':
            self._view['hideAll'] = False
            if self.viewport is not None:
                self.viewport.planesVisible = not self.viewport.planesVisible
        elif key in dict(SHOW_ITEMS):
            self._view['hideAll'] = False
            self._off.symmetric_difference_update({key})
        self._apply_view()

    @Slot(str)
    def viewAction(self, name):
        """视图上方的按钮和 "视图定向" 菜单: fit / zoom_box / previous / front… / normal / save_view / view:序号。"""
        viewport = self.viewport
        if viewport is None:
            return
        if name == 'zoom_box':
            viewport.zoomBox()
            if viewport.zoomArmed:
                self.notice.emit('局部放大：按住左键拖一个框，框里的内容放满画面（Esc 取消）')
        elif name == 'previous':
            viewport.previousView()
        elif name == 'normal':
            plane = self._sketch.plane if self._sketch is not None else self.session.selection.get('plane')
            if plane:
                viewport.look_at_plane(plane)
            else:
                self.notice.emit('正视于：先在设计树或视图里选中一个基准面')
        elif name == 'save_view':
            self._views.append((f'视图 {len(self._views) + 1}', viewport.view_state()))
            self.notice.emit(f'已记下现在的视角：视图 {len(self._views)}（在“视图定向”里点它回来；关掉软件后不保留）')
            self.viewChanged.emit()
        elif name.startswith('view:') and name[5:].isdigit() and int(name[5:]) < len(self._views):
            viewport.go_to(self._views[int(name[5:])][1])
        else:
            viewport.setView(name)

    @Slot(str, str)
    def planeAction(self, name, action):
        """设计树里点基准面弹出来的那排小按钮: sketch 草图绘制 / toggle 显示隐藏 / zoom 放大所选范围 / normal 正视于。"""
        if name not in planes.PLANES or self.viewport is None:
            return
        if action == 'sketch':
            self._pending_tool = 'select'
            self._close_form()
            self.sketchOn(name)
        elif action == 'toggle':
            self.viewport.toggle_plane(name)
        elif action == 'zoom':
            self.viewport.zoom_to_plane(name)
        elif action == 'normal':
            self.viewport.look_at_plane(name)

    # ---- 给 QML 读的属性 ----
    @Property('QVariantList', notify=changed)
    def tree(self):
        """左侧的零件树, 一行一个节点 (depth 是缩进层数):
            零件
              前视 / 上视 / 右视基准面、原点
              特征… (草图收在用它的拉伸下面, 和 SOLIDWORKS 一样; 正在画的新草图排在最后)
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
                       state='error' if failed else state,
                       note=state[7:] if failed else (STATUS_TEXT.get(state, '') or info.get(feature['id'], '')),
                       suppressed=bool(feature.get('suppressed')),
                       selected=feature['id'] == selection.get('feature'),
                       rolled=document.upto is not None and position >= document.upto,
                       editing=editing is not None and editing.feature == feature['id'],
                       hidden=self._is_hidden(feature),
                       expandable=feature['id'] in children,
                       expanded=feature['id'] in children and feature['id'] not in self._collapsed)

        total = len(document.features)
        upto = total if document.upto is None else document.upto
        bar = row('rollback', '', '', 1, count=upto, total=total)
        placed = False
        for feature in document.features:
            if feature['id'] in absorbed:
                continue
            position = document.features.index(feature)
            first = position
            if feature['id'] in children:               # 草图紧挨在它前面: 回退到这一行之前时连草图一起退
                source = document.features.index(by_id[children[feature['id']]])
                first = source if source == position - 1 else position
            if not placed and position >= upto:
                rows.append(bar)
                placed = True
            rows.append(dict(feature_row(feature, 1), before=first, after=position + 1))
            if feature['id'] in children and feature['id'] not in self._collapsed:
                rows.append(dict(feature_row(by_id[children[feature['id']]], 2), before=-1, after=position + 1))
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

    @Property('QVariantList', constant=True)
    def featureMenus(self):
        """特征页上的下拉菜单: [{'id', 'title', 'items': [{'id', 'title'}...]}...]。"""
        return [{'id': identifier, 'title': title, 'items': [{'id': kind, 'title': table.SPECS[kind]['title']} for kind in kinds]}
                for identifier, title, kinds in table.MENUS]

    @Slot(str)
    def setTab(self, name):
        """翻工具栏的页。只是翻页, 不进也不出草图。"""
        if name in ('feature', 'sketch') and name != self._tab:
            self._tab = name
            self.sketchChanged.emit()

    @Property(bool, notify=changed)
    def busy(self):
        return self.session.busy

    @Property(bool, notify=changed)
    def canUndo(self):
        return bool(self._sketch_history) if self._sketch is not None else self.session.document.can_undo()

    @Property(bool, notify=changed)
    def canRedo(self):
        return self._sketch is None and self.session.document.can_redo()

    @Property(str, notify=changed)
    def title(self):
        document = self.session.document
        name = os.path.basename(document.path) if document.path else '未命名零件'
        return f'{name}{" *" if document.dirty else ""}'

    @Property(str, notify=changed)
    def documentPath(self):
        return self.session.document.path or ''

    @Property(str, notify=changed)
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
    def hoverText(self):
        return self._hover

    @Property('QVariant', notify=formChanged)
    def form(self):
        return self._form

    @Property(bool, notify=sketchChanged)
    def sketchActive(self):
        return self._sketch is not None

    @Property(str, notify=sketchChanged)
    def sketchTool(self):
        return self._sketch.tool if self._sketch is not None else ''

    @Property(str, notify=sketchChanged)
    def hint(self):
        """视图上方的一句操作提示 (现在该干什么)。"""
        if self._picking_plane:
            if self._rapid:
                return '快速草图：点一个基准面就在它上面接着画（Esc 结束）'
            return '选择一个基准面来画草图（在视图里或左侧列表里点；Esc 取消）'
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

    @Property('QVariantList', constant=True)
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
    def snapToggles(self):
        """一直开着的捕捉: [{'id', 'text', 'on'}...] (点捕捉 = 端点, 中心点, 象限点, 交叉点, 最近端, 水平/竖直, 网格…)。"""
        return [{'id': kind, 'text': QUICK_SNAP_NAMES[kind], 'on': kind in self._snaps} for kind in ALL_SNAPS]

    @Slot(str)
    def toggleSnap(self, kind):
        if kind in ALL_SNAPS:
            self._snaps.symmetric_difference_update({kind})     # 草图编辑器拿的是同一个集合, 立刻生效
            self.sketchChanged.emit()

    def _sketch_action(self, action):
        if self._sketch is None:
            self.notice.emit('这个功能在画草图时用：先进入草图')
            return
        action(self._sketch)
        self._sketch_changed()

    @Property('QVariantList', notify=sketchChanged)
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

    # ---- 动作表: 快捷键和手势轮都从这里走 ----
    @Slot(str)
    def runAction(self, identifier):
        """执行动作表 (actions.py) 里的一个动作。"""
        if identifier not in actions.BY_ID:
            return
        head, _, name = identifier.partition(':')
        if head == 'cmd':
            self.startCommand(name)
        elif head == 'tool':
            self.useSketchTool(name)
        elif head == 'view':
            self.viewAction(name)
        elif head == 'style':
            self.setDisplayStyle(name)
        elif identifier == 'sketch.start':
            if self._sketch is None:            # 已经在草图里: 不做事 (免得一个字母键把草图退出去)
                self.startSketch()
        elif identifier == 'file.save':
            self.saveDocument('') if self.session.document.path else self.dialogRequested.emit('save')
        elif identifier in ('file.open', 'file.export', 'app.settings'):
            self.dialogRequested.emit(identifier.partition('.')[2])
        elif identifier.startswith('sketch.') and identifier[7:] in ('pattern', 'cpattern', 'relation', 'repair', 'silhouette', 'section'):
            self.sketchPick(identifier[7:])
        else:
            {'file.new': self.newDocument, 'edit.undo': self.undo, 'edit.redo': self.redo, 'edit.delete': self.deleteSelected,
             'sketch.finish': self.finishSketch, 'sketch.cancel': self.cancelSketch, 'sketch.rapid': self.toggleRapidSketch,
             'view.section': lambda: self.toggleViewSetting('section'),
             'view.perspective': lambda: self.toggleViewSetting('perspective'),
             'view.planes': lambda: self.toggleShow('main_planes')}[identifier]()

    @Property('QVariantList', notify=settingsChanged)
    def shortcuts(self):
        """现在生效的快捷键: [{'id', 'key'}...] (没有键的不在里面)。"""
        return [{'id': row['id'], 'key': self.settings.key(row['id'])} for row in actions.ACTIONS if self.settings.key(row['id'])]

    @Property('QVariantMap', notify=settingsChanged)
    def keyMap(self):
        """动作 id → 快捷键 (按钮的悬停说明里显示)。"""
        return {row['id']: self.settings.key(row['id']) for row in actions.ACTIONS}

    @Property('QVariantList', notify=settingsChanged)
    def actionTable(self):
        """设置页里的那张表: 每个功能一行。"""
        return [dict(row, key=self.settings.key(row['id']), changed=self.settings.key(row['id']) != row['default'])
                for row in actions.ACTIONS]

    @Property('QVariantList', constant=True)
    def actionGroups(self):
        return list(actions.GROUPS)

    @Slot(int, int, result=str)
    def keyText(self, key, modifiers):
        """按下的键 → 快捷键的写法 ("Ctrl+Shift+Z")。只按了 Ctrl / Shift 这类修饰键时是空的。"""
        from PySide6.QtCore import QKeyCombination, Qt
        from PySide6.QtGui import QKeySequence
        if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr, Qt.Key_CapsLock, Qt.Key_NumLock, Qt.Key_unknown, 0):
            return ''
        try:
            held = Qt.KeyboardModifier(modifiers) & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
            return QKeySequence(QKeyCombination(held, Qt.Key(key))).toString()
        except (ValueError, TypeError):
            return ''

    @Slot(str, str)
    def setShortcut(self, identifier, key):
        """给一个功能定快捷键 (key 为空 = 不要快捷键)。这个键原来给了别的功能的, 那边自动让出来。"""
        if identifier not in actions.BY_ID:
            return
        if key.lower() in RESERVED_KEYS:
            self.notice.emit('Esc 和回车固定用来取消和确认，不能改派给别的功能')
            return
        taken = self.settings.set_key(identifier, key)
        if taken:
            names = '、'.join(f'“{actions.BY_ID[other]["title"]}”' for other in taken)
            self.notice.emit(f'{key} 原来是{names}的快捷键，现在改给“{actions.BY_ID[identifier]["title"]}”了')
        self.settingsChanged.emit()

    @Slot(str)
    def resetShortcut(self, identifier):
        if identifier in actions.BY_ID:
            self.setShortcut(identifier, actions.BY_ID[identifier]['default'])

    @Slot()
    def resetShortcuts(self):
        self.settings.reset_keys()
        self.settingsChanged.emit()

    @Property('QVariantMap', notify=settingsChanged)
    def gestureWheels(self):
        """两套手势轮现在的 8 格: {'model': [...], 'sketch': [...]}。"""
        return {which: self._wheel_rows(which) for which in actions.GESTURES}

    @Slot(str, int, str)
    def setGesture(self, which, index, identifier):
        if which in actions.GESTURES and 0 <= index < 8 and identifier in actions.BY_ID:
            self.settings.set_wheel(which, index, identifier)
            self.settingsChanged.emit()
            self.sketchChanged.emit()

    @Slot()
    def resetGestures(self):
        self.settings.reset_wheels()
        self.settingsChanged.emit()
        self.sketchChanged.emit()

    @Property(str, constant=True)
    def settingsPath(self):
        return self.settings.file

    # ---- 点特征 / 草图弹出来的小工具条 ----
    def _find(self, identifier):
        return next((feature for feature in self.session.document.features if feature['id'] == identifier), None)

    def _is_line_feature(self, feature):
        """画出来是线的特征 (草图、曲线、参考几何体): 可以单独隐藏。别的特征都长在同一个实体上。"""
        return feature['type'] == 'sketch' or feature['type'] in SHOW_OF or feature['type'] in table.CURVE_KINDS

    def _is_hidden(self, feature):
        return feature['id'] in self._hidden_ids if self._is_line_feature(feature) else self._body_hidden

    def _source_sketch(self, feature):
        """这个特征用的草图 (没有就是 None)。"""
        source = self._find(feature['params'].get('sketch')) if feature['type'] != 'sketch' else None
        return source if source is not None and source['type'] == 'sketch' else None

    def _context_items(self, identifier, scene=None):
        """小工具条上的按钮: [{'id', 'icon', 'title', 'tip'}...]。scene: 在视图里点出来的 (多几项和面 / 边有关的)。"""
        rows = []

        def add(action, icon, title, tip):
            rows.append({'id': action, 'icon': icon, 'title': title, 'tip': f'{title}：{tip}'})

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
            if self._is_hidden(feature):
                add('toggle', 'eye', '显示', '重新显示出来')
            elif self._is_line_feature(feature):
                add('toggle', 'eye_off', '隐藏', '在视图里不画它（特征还在）')
            else:
                add('toggle', 'eye_off', '隐藏', '在视图里不画实体（这个零件只有一个实体，隐藏的是整个实体）')
        add('zoom', 'zoom_sel', '放大所选范围', '把它放满画面')
        add('normal', 'normal', '正视于', '把视角转到正对着它')
        if feature is None or not self._is_line_feature(feature):
            add('appearance', 'appearance', '外观', '给零件换个颜色')
        if feature is not None and hole:
            add('hole_sketch', 'hole', '编辑孔草图', '改孔的位置（进入定位置的那个草图）')
            if scene is not None:
                add('hole_spec', 'settings', '修改孔规格', '改孔的类型、规格和深度')
        if scene is not None and scene['kind'] in ('face', 'edge'):
            add('select_other', 'select_other', '选择其他', '换成这个位置后面被挡住的下一个面')
            add('fillet', 'fillet', '圆角', '给选中的边倒圆角（选的是面就是它的一圈边）')
            add('chamfer', 'chamfer', '倒角', '给选中的边倒斜角（选的是面就是它的一圈边）')
        if scene is not None and scene['kind'] == 'face':
            add('same_faces', 'same_faces', '选择相同面', '把和它同样大小、同样形状的面都选上')
            add('back_face', 'back_face', '选择背面', '选这个位置最后面的那个面（零件背面）')
        return rows

    @Slot(str, result='QVariantList')
    def featureContext(self, identifier):
        """设计树里点一个特征弹出来的按钮。"""
        if self._sketch is not None or self._picking_plane or self._form is not None:
            return []
        return self._context_items(identifier)

    @Property('QVariantList', notify=changed)
    def sceneContext(self):
        """视图里点中面 / 边 / 草图线弹出来的按钮。"""
        return self._context_items(self._context['feature'], self._context) if self._context else []

    @Property(str, notify=changed)
    def sceneTarget(self):
        return (self._context.get('feature') or '') if self._context else ''

    def _drop_context(self):
        if self._context is not None:
            self._context = None
            self.contextRequested.emit(-1.0, -1.0)

    @Slot(str, result='QVariantList')
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
        feature, scene, viewport = self._find(identifier), self._context, self.viewport
        selection, model = self.session.selection, self.session.model
        faces = {face['id']: face for face in model.get('faces', ())}
        face = faces.get(scene['id']) if scene and scene['kind'] == 'face' else None
        if viewport is None:
            return
        if action in ('edit', 'hole_spec') and feature is not None:
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
        elif action == 'toggle' and feature is not None:
            if self._is_line_feature(feature):
                self._hidden_ids.symmetric_difference_update({identifier})
            else:
                self._body_hidden = not self._body_hidden
                if self._body_hidden:
                    self.notice.emit('实体已隐藏（这个零件只有一个实体，隐藏的是整个实体）。在设计树里点任何一个特征，再点“显示”就回来')
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
        if self._leave_modes():
            self._run('open_document', {'path': _local(path)})

    @Slot(str)
    def saveDocument(self, path):
        self._run('save_document', {'path': _local(path)} if path else {})

    @Slot(str)
    def exportModel(self, path):
        target = _local(path)
        self._run('export', {'path': target},
                  lambda result: result.get('ok') and self.notice.emit(f'已导出到 {target}'))

    @Slot(str)
    def setView(self, name):
        if self.viewport is not None:
            self.viewport.setView(name)

    @Slot()
    def toggleMaximize(self):
        from .win32_frame import native_max_toggle
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
        self._picking_plane = True
        if self.viewport is not None:
            self._planes_were_visible = self.viewport.planesVisible
            self.viewport.planesVisible = True
        self.sketchChanged.emit()

    @Slot(str)
    def sketchOn(self, name):
        """在基准面 name 上开始画一个新草图。"""
        if self._sketch is not None:
            return
        count = sum(1 for feature in self.session.document.features if feature['type'] == 'sketch') + 1
        try:
            editor = self._sketch_editor(name, name=f'草图{count}')
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
        self._stop_picking_plane()
        self._sketch, self._sketch_history = editor, []
        self._tab = 'sketch'
        self._sketch_seen = copy.deepcopy(editor.shapes)
        if self._outliner is None:
            from .textpath import Outliner
            self._outliner = Outliner()
        editor.outliner = self._outliner
        editor.snaps = self._snaps
        editor.references = sketchgeom.project_edges(self.session.model, editor.plane, editor.offset)
        self.session.selection.update(faces=[], edges=[], plane=None)
        if self.viewport is not None:
            self.viewport.set_selection(self.session.selection)
            self.viewport.set_sketch(editor, turn=not self._rapid)
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
            if not self._rapid:
                self.viewport.setView('iso')
        self.formChanged.emit()
        self.sketchChanged.emit()
        self.changed.emit()

    def _sketch_form(self):
        """草图里的右侧面板: 选中了一个轮廓才出现 (填它的精确尺寸), 没选中时不占地方。"""
        panel = self._sketch.panel()
        self._form = None if panel is None else dict(panel, kind='sketch', editing='')
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

    # ---- 键盘 (QML 的快捷键转过来) ----
    @Slot()
    def escape(self):
        if self.viewport is not None and self.viewport.cancel_zoom():
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

    # ---- 参数面板 ----
    @Slot(str)
    def startCommand(self, kind):
        """点了特征页里的命令。正在画草图时点拉伸: 先把草图存了, 接着就拉它 (不用先退出草图再回来点)。"""
        base = kind[:-4] if kind.endswith('_cut') else kind
        spec = table.SPECS.get(base)
        if self._sketch is not None:
            if kind in ('extrude', 'cut') or (spec and any(field['kind'] == 'sketch' for field in spec['fields'])):
                self._finish_sketch(lambda: self.startCommand(kind))     # 用草图的特征: 先存草图, 接着就做它
            else:
                self.notice.emit('正在编辑草图：先点右上角的 ✓ 完成草图')
            return
        self._close_form()
        self._stop_picking_plane()
        if (kind == 'cut' or kind.endswith('_cut')) and not self.session.model.get('has_body'):
            self.notice.emit('还没有实体可以切：先用“拉伸凸台”做出实体')
            return
        if spec is not None and not spec['fields']:      # 质心、边界框: 没有要填的, 直接加上
            self._run(base)
            return
        self._form = forms.new_form(kind, self.session)
        self.formChanged.emit()

    @Slot(str)
    def editFeature(self, identifier):
        """双击特征: 草图进入草图编辑, 其他特征打开参数面板。"""
        if not self._leave_modes():
            return
        try:
            feature = self.session.document.find(identifier)
        except DocumentError as error:
            self.notice.emit(str(error))
            return
        self.session.selection['feature'] = identifier
        self._push_selection()
        if feature['type'] == 'sketch':
            params = feature['params']
            try:
                self._enter_sketch(self._sketch_editor(params.get('plane', 'XY'), offset=params.get('offset', 0.0),
                                                       shapes=params.get('shapes', ()), feature=identifier, name=feature['name']))
            except ValueError as error:
                self.notice.emit(str(error))
            return
        self._form = forms.feature_form(feature, self.session)
        self.formChanged.emit()

    @Slot(str, 'QVariant')
    def setField(self, key, value):
        """面板上改了一项。草图的尺寸立刻生效 (看得见); 其他特征等点 "确定"。"""
        if self._form is None:
            return
        if self._sketch is not None:
            editor = self._sketch
            editor.set_field(key, value)
            if self._sketch_seen != editor.shapes:
                self._sketch_history.append(self._sketch_seen)
                self._sketch_seen = copy.deepcopy(editor.shapes)
            if editor.message:
                self.notice.emit(editor.message)
                editor.message = ''
            # 只让视图跟上, 不重建面板: 重建会让正在用 Tab 逐项填尺寸的输入框丢掉焦点
            if self.viewport is not None:
                self.viewport.refresh_sketch()
            self.changed.emit()
            return
        for field in self._form['fields']:
            if field['key'] == key:
                field['value'] = float(value) if field['type'] == 'number' else value

    @Slot()
    def acceptForm(self):
        form = self._form
        if form is None:
            return
        if self._sketch is not None:            # 草图里带 "确定" 的面板: 阵列、修复
            self._sketch.apply_operation()
            self._sketch_changed()
            return
        try:
            name, args = forms.to_command(form, self.session)
        except (DocumentError, KeyError, ValueError) as error:
            self.notice.emit(f'参数不对: {error}')
            return
        if name in ('fillet', 'chamfer') and not args['edges']:
            self.notice.emit('先在三维视图里点选要处理的边')
            return

        def done(result):
            # 新建的特征算失败了: 面板换成它的编辑面板, 改个数就能再试, 不用重新来一遍
            if not form['editing'] and result.get('id') and not result.get('ok'):
                self.editFeature(result['id'])
            elif not form['editing']:
                self._close_form()

        self._run(name, args, done)

    @Slot()
    def cancelForm(self):
        if self._sketch is not None:
            self._sketch.cancel_operation()
            self._sketch_changed()
            return
        self._close_form()

    def _close_form(self):
        if self._form is not None and self._sketch is None:
            self._form = None
            self.formChanged.emit()

    def _refresh_form_info(self):
        """选边变了: 圆角 / 倒角面板上的 "已选 N 条边" 跟着变。"""
        form = self._form
        if not form or not form.get('pick'):
            return
        if form['kind'] in table.SPECS:
            text = forms.pick_text(form, self.session)
        else:
            text = forms.edges_text(len(self.session.selection['edges']))
        for field in form['fields']:
            if field['key'] == form['pick']['key'] and field['type'] == 'info' and field['value'] != text:
                field['value'] = text
                self._form = dict(form)
                self.formChanged.emit()

    # ---- 三维视图里的选择 ----
    def _on_picked(self, kind, identifier, additive):
        selection = self.session.selection
        self._drop_context()
        if self._picking_plane:
            if kind == 'plane':
                self.sketchOn(identifier)
            return
        if kind == 'sketch':                    # 点中了草图 (或曲线、参考几何体) 的线: 选中这个特征
            if self._form is not None and self._form.get('pick'):
                return
            selection.update(faces=[], edges=[], plane=None, feature=identifier)
            self._push_selection()
            if self._form is None:
                self._context = {'kind': 'sketch', 'id': identifier, 'feature': identifier, 'faces': []}
                self.changed.emit()
                self.contextRequested.emit(*self.viewport.click_at)
            return
        # 圆角 / 倒角面板开着时, 点边就是往里加 (再点一次去掉), 不用一直按着 Ctrl
        # 面板开着并且要选边 / 面时, 点一下就是往里加 (再点一次去掉), 不用一直按着 Ctrl; 只要一个的, 点新的就换掉
        pick = self._form.get('pick') if self._form else None
        if pick:
            if kind != pick['kind']:
                return
            additive = pick.get('count') != 1
        if not additive:
            selection.update(faces=[], edges=[], plane=None)
            if not pick:
                selection['feature'] = None
        if kind == 'plane':
            selection['plane'] = None if (additive and selection.get('plane') == identifier) else identifier
        elif kind:
            key = 'edges' if kind == 'edge' else 'faces'
            if identifier in selection[key]:
                selection[key].remove(identifier)
            else:
                selection[key].append(identifier)
        if kind in ('face', 'edge') and not additive and self._form is None:
            # 单点了一个面 / 一条边: 设计树里把做出它的特征也标出来, 旁边弹出小工具条
            owner = self._owner_of(kind, identifier)
            selection['feature'] = owner
            self._context = {'kind': kind, 'id': identifier, 'feature': owner, 'faces': self.viewport.faces_at(*self.viewport.click_at)}
        self._push_selection()
        self._refresh_form_info()
        if self._context is not None:
            self.contextRequested.emit(*self.viewport.click_at)

    def _owner_of(self, kind, identifier):
        """面 / 边是哪个特征做出来的 (边: 挨着它的面里最晚的那个特征)。认不出来是 None。"""
        faces = self.session.model.get('faces', ())
        if kind == 'face':
            return next((face.get('feature') for face in faces if face['id'] == identifier), None)
        order = {feature['id']: number for number, feature in enumerate(self.session.document.features)}
        owners = [face.get('feature') for face in faces if identifier in face.get('edges', ()) and face.get('feature') in order]
        return max(owners, key=order.get) if owners else None

    def _on_boxed(self, found, additive):
        """视图里拉了一个选择框。平时框的是边 (倒圆角最常用); 面板正等着选面时框的是面。一条边都没框到但框住了草图: 选中那个草图。"""
        if self._sketch is not None or self._picking_plane:
            return
        self._drop_context()
        selection = self.session.selection
        pick = self._form.get('pick') if self._form else None
        key = 'faces' if pick and pick['kind'] == 'face' else 'edges'
        if not additive and not pick:
            selection.update(faces=[], edges=[], plane=None, feature=None)
        merged = selection[key] + [number for number in found[key] if number not in selection[key]]
        selection[key] = merged[-1:] if pick and pick.get('count') == 1 else merged
        if not pick and not found['edges'] and found['sketches']:
            selection['feature'] = found['sketches'][0]
        self._push_selection()
        self._refresh_form_info()

    def _push_selection(self):
        if self.viewport is not None:
            self.viewport.set_selection(self.session.selection)
        self.changed.emit()

    def _on_hover(self, text):
        self._hover = text
        self.hoverTextChanged.emit()

    # ---- 自动化测试用 ----
    def _debug_mouse(self, kind, fx, fy, button='left'):
        """往三维视图里送一个鼠标事件 (kind: press / move / release; 位置是视图宽高的比例 0~1)。
        事件发给窗口, 走的是和真鼠标一样的分发路径。只给 tests/smoke_ui.py 通过接口的 'ui' 命令调。"""
        from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        which = {'left': Qt.LeftButton, 'middle': Qt.MiddleButton, 'right': Qt.RightButton}[button]
        kinds = {'press': QEvent.MouseButtonPress, 'move': QEvent.MouseMove, 'release': QEvent.MouseButtonRelease}
        local = QPointF(fx * self.viewport.width(), fy * self.viewport.height())
        scene = self.viewport.mapToScene(local)
        held = Qt.NoButton if kind == 'release' else which
        event = QMouseEvent(kinds[kind], scene, self.window.mapToGlobal(scene.toPoint()),
                            Qt.NoButton if kind == 'move' else which, held, Qt.NoModifier)
        QCoreApplication.sendEvent(self.window, event)
