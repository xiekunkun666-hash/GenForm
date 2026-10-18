"""视图上方那排按钮: 显示样式、布景、剖切、显示哪些东西、外观和材质、视角。"""
from __future__ import annotations

import math
from PySide6.QtCore import Property, Slot

from ..i18n import localized
from .. import features as table, materials, planes
from .common import DISPLAY_STYLES, ORIENTATIONS, SCENE_NAMES, SHOW_ITEMS, SHOW_OF
from .signals import changed, settingsChanged, viewChanged


class ViewBarMixin:
    """视图上方那排按钮 (控制器的一部分)。"""

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
        if self.viewport is not None:           # 单独上了色的特征 (轮胎、玻璃…)
            colors = self.session.document.props.get('feature_colors') or {}
            shown = {key: materials.rgb(value) for key, value in colors.items() if materials.rgb(value)}
            shown.update(self._check_colors())          # 设计检查报错的件: 标红 (关掉检查日志就恢复)
            opacity = dict(self.session.document.props.get('feature_opacity') or {})
            for identifier in self._check_red:
                opacity.pop(identifier, None)           # 标红的玻璃也不透明, 看得清
            self.viewport.set_feature_colors(shown, opacity)

    def _apply_view(self, rebuild=True):
        if self.viewport is None:
            return
        view = self._view
        section = {'plane': view['sectionPlane'], 'offset': view['sectionOffset'], 'flip': view['sectionFlip']} if view['section'] else None
        self.viewport.set_hidden(self._hidden_features(), rebuild)
        self.viewport.set_hidden_faces(self._hidden_faces(), rebuild)
        self.viewport.set_display(style=view['style'], scene=view['scene'], cartoon=view['cartoon'], perspective=view['perspective'],
                                  section=section, color=self._body_color(),
                                  origin=not view['hideAll'] and 'origin' not in self._off, planes_off=view['hideAll'])
        self.viewChanged.emit()

    def _planes_toggled(self):
        self.viewChanged.emit()
        self.changed.emit()

    @Property('QVariantMap', notify=viewChanged)
    def viewState(self):
        props = self.session.document.props
        return dict(self._view, color=props.get('color') or '', saved=len(self._views))

    @Property('QVariantList', notify=settingsChanged)
    @localized
    def displayStyles(self):
        return [{'id': key, 'title': title} for key, title in DISPLAY_STYLES]

    @Property('QVariantList', notify=settingsChanged)
    @localized
    def sceneNames(self):
        return [{'id': key, 'title': title, 'icon': 'scene'} for key, title in SCENE_NAMES]

    @Property('QVariantList', notify=viewChanged)
    @localized
    def orientations(self):
        rows = [{'id': key, 'title': title} for key, title in ORIENTATIONS]
        rows.append({'id': 'save_view', 'title': '新视图（记下现在的视角）', 'line': True})
        rows += [{'id': f'view:{index}', 'title': name, 'icon': 'cube'} for index, (name, _) in enumerate(self._views)]
        return rows

    @Property('QVariantList', notify=viewChanged)
    @localized
    def showItems(self):
        """隐藏/显示项目: [{'id', 'title', 'icon', 'checked'}...]; 第一项是 "隐藏所有类型"。"""
        everything = self._view['hideAll']
        rows = [{'id': 'hide_all', 'title': '隐藏所有类型', 'icon': 'eye_off', 'checked': everything}]
        for index, (key, title) in enumerate(SHOW_ITEMS):
            on = self.viewport.planesVisible if key == 'main_planes' and self.viewport is not None else key not in self._off
            rows.append({'id': key, 'title': title, 'icon': 'show_' + key, 'checked': bool(on) and not everything, 'line': index == 0})
        if self._isolated is not None:
            rows.append({'id': 'isolate_exit', 'title': '退出孤立', 'icon': 'eye', 'line': True})
        if self._hidden_keys:
            rows.append({'id': 'show_bodies', 'title': '显示隐藏的实体', 'icon': 'eye', 'line': self._isolated is None})
        return rows

    @Property('QVariantList', constant=True)
    def appearanceColors(self):
        return list(materials.APPEARANCES)

    @Property('QVariantList', notify=changed)
    @localized
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
        if key == 'isolate_exit':
            self._exit_isolate()
            self.changed.emit()
        elif key == 'show_bodies':
            self._exit_isolate()
            self._hidden_keys = set()
            self.changed.emit()
        elif key == 'hide_all':
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
