"""三维视图里的选择 (点选、框选、悬停) 和给自动化测试用的入口。"""
from __future__ import annotations



class SelectionMixin:
    """三维视图里的选择 (点选 (控制器的一部分)。"""

    # ---- 三维视图里的选择 ----
    def _on_picked(self, kind, identifier, additive):
        if self._kind == 'assembly' and self._measure is not None:          # 评估 → 测量: 点零部件, 或点零部件的一条边
            hover = getattr(self.viewport, '_hover', None) if self.viewport is not None else None
            if kind == 'component' and hover and hover[0] == 'part_edge' and hover[1][0] == identifier:
                self._measure_edge(*hover[1])
                return
            self._measure_part(identifier if kind == 'component' else -1)
            return
        if self._kind == 'assembly' and kind == 'sketch' and self._sketch is None:
            pass                                # 点中了布局草图的线: 和零件里一样选中这个草图
        elif self._kind == 'assembly' and self._sketch is None and not self._picking_plane:
            # 装配体: 点的是零部件 (视图里画的别的零件), 点空白处 = 不选
            self.sim.selectPart(identifier if kind == 'component' else -1)
            if kind == 'component':             # 旁边弹出它的小工具条 (和零件里点一个面一样)
                self._context = {'kind': 'component', 'id': identifier, 'feature': f'part:{identifier}', 'faces': []}
                self.changed.emit()
                self.contextRequested.emit(*self.viewport.click_at)
            else:
                self._drop_context()
            return
        if self._kind == 'assembly':
            self.sim.selectPart(-1)
        selection = self.session.selection
        self._drop_context()
        if self._measure is not None:
            self._measure_pick(kind, identifier)
            return
        if kind == 'vertex':                    # 拉伸 "成形到顶点" 正等着点顶点
            pick = self._form.get('pick') if self._form else None
            corners = self.session.model.get('vertices')
            if pick and pick['kind'] == 'vertex' and corners is not None and identifier < len(corners):
                selection['vertices'] = [identifier]
                self.viewport.set_overlay(points=[[float(value) for value in corners[identifier]]])
                self._refresh_form_info()
            return
        if self._picking_plane:
            if kind == 'plane':
                self.sketchOn(identifier)
            elif kind == 'face':                # 零件上的平面也可以
                self._sketch_on_face(identifier)
            return
        if kind in ('face', 'edge', '') and self._form is not None and (self._form.get('pick') or {}).get('kind') != kind                 and self._form_take_line_under_click():
            return                              # 点到的是面或边, 但那个位置正好压着草图里的一条直线 (中心线): 先认它当轴
        if kind == 'sketch' and self._form is not None:     # 面板开着: 点中的草图 / 曲线 / 基准轴 / 基准面 填进面板
            self._form_take_feature(identifier)
            return
        if kind == 'plane' and self._form is not None and self._form_take(('plane',), identifier):
            return
        if kind == 'edge' and self._form is not None and (self._form.get('pick') or {}).get('kind') != 'edge' \
                and self._form_take_edge(identifier):
            return
        if kind == 'sketch':                    # 点中了草图 (或曲线、参考几何体) 的线: 选中这个特征
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
        if kind in ('face', 'edge') and not additive and self._form is None and not self.sim.mode:
            # 单点了一个面 / 一条边: 设计树里把做出它的特征也标出来, 旁边弹出小工具条
            owner = self._owner_of(kind, identifier)
            selection['feature'] = owner
            self._context = {'kind': kind, 'id': identifier, 'feature': owner, 'faces': self.viewport.faces_at(*self.viewport.click_at)}
        if kind == 'plane' and not additive and self._form is None and not self.sim.mode and selection.get('plane'):
            self._context = {'kind': 'plane', 'id': identifier, 'feature': None, 'faces': []}
        self._push_selection()
        self._refresh_form_info()
        if self._context is not None:
            self.contextRequested.emit(*self.viewport.click_at)

    def _on_view_menu(self, kind, identifier):
        """视图里右键单击: 右键点着的是已经选中的面 / 边就不动选择, 不然先像左键一样选上它; 然后在那里弹出它所属特征的
        右键菜单 (和设计树里右键那个特征一样)。点在空白处: 零件的菜单。"""
        if self._kind == 'assembly' and self._sketch is None and kind != 'sketch' and self._measure is None:
            # 装配体: 零部件的菜单 ('part:序号'); 空白处 = 装配体的菜单 ('part:-1')
            index = identifier if kind == 'component' else -1
            if index >= 0:
                self.sim.selectPart(index)
            x, y = self.viewport.click_at
            self.viewMenuRequested.emit(f'part:{index}', float(x), float(y))
            return
        if self._measure is not None or self._picking_plane or self._form is not None:
            return
        selection = self.session.selection
        key = 'edges' if kind == 'edge' else 'faces'
        if kind in ('face', 'edge') and identifier in selection.get(key, ()):
            owner = self._owner_of(kind, identifier)
        elif kind == 'sketch':
            owner = identifier
            self._on_picked(kind, identifier, False)
        elif kind in ('face', 'edge'):
            self._on_picked(kind, identifier, False)
            owner = self._owner_of(kind, identifier)
        else:
            owner = selection.get('feature') if kind == '' and selection.get('feature') else ''
        self._drop_context()                    # 小工具条收起来: 菜单里有一样的东西
        x, y = self.viewport.click_at
        self.viewMenuRequested.emit(owner or '', float(x), float(y))

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
        if self._sketch is not None or self._picking_plane or self._measure is not None:
            return
        self._drop_context()
        selection = self.session.selection
        pick = self._form.get('pick') if self._form else None
        key = 'faces' if pick and pick['kind'] == 'face' else 'edges'
        if not additive and not pick:
            selection.update(faces=[], edges=[], plane=None, feature=None)
        already = set(selection[key])
        merged = selection[key] + [number for number in found[key] if number not in already]
        selection[key] = merged[-1:] if pick and pick.get('count') == 1 else merged
        if not pick and not found['edges'] and found['sketches']:
            selection['feature'] = found['sketches'][0]
        self._push_selection()
        self._refresh_form_info()

    def _push_selection(self):
        if self.viewport is not None:
            self.viewport.set_selection(self.session.selection)
            if self.sim.mode == 'static':       # 云图盖着实体: 选了面要让出来
                self.sim._paint()
        self.changed.emit()

    def _on_hover(self, text):
        self._hover = text
        self.hoverTextChanged.emit()

    # ---- 自动化测试用 ----
    def _debug_wheel(self, fx, fy, delta):
        """在三维视图的 (fx, fy) 处滚一下滚轮 (delta: 正 = 放大; 一格是 120)。只给界面冒烟测试用。"""
        from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        scene = self.viewport.mapToScene(QPointF(fx * self.viewport.width(), fy * self.viewport.height()))
        QCoreApplication.sendEvent(self.window, QWheelEvent(scene, QPointF(self.window.mapToGlobal(scene.toPoint())), QPoint(0, 0),
                                                            QPoint(0, int(delta)), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))

    def _debug_click_world(self, x, y, z):
        """在三维里这个点落在屏幕上的位置单击一下 (走真鼠标的路径)。只给界面冒烟测试用。"""
        view = self.viewport
        spots, _ = view._camera.project([[x, y, z]], view.width(), view.height())
        for kind in ('press', 'release'):
            self._debug_mouse(kind, spots[0][0] / view.width(), spots[0][1] / view.height())

    def _debug_profile(self, target, kind, fx, fy, button='left'):
        """给一个鼠标事件的处理过程做性能剖析, 结果写到 target。只给界面冒烟测试用。"""
        import cProfile
        import pstats
        profile = cProfile.Profile()
        profile.enable()
        self._debug_mouse(kind, fx, fy, button)
        profile.disable()
        with open(target, 'w', encoding='utf-8') as handle:
            pstats.Stats(profile, stream=handle).sort_stats('cumulative').print_stats(28)

    def _debug_profile_command(self, target, name, args=None):
        """给一条命令在界面线程上的处理过程 (从执行到回复、再到界面刷新完) 做性能剖析, 结果写到 target。
        只给界面冒烟测试用 (测 AI 接口每一步的固定开销)。"""
        import cProfile
        import pstats
        import time
        from PySide6.QtCore import QTimer
        profile, began = cProfile.Profile(), time.perf_counter()

        def replied(result):
            def finish():                   # 回复之后排在队列里的界面刷新也算进去
                profile.disable()
                with open(target, 'w', encoding='utf-8') as handle:
                    handle.write(f'总共 {time.perf_counter() - began:.3f} s  ok={result.get("ok")}\n')
                    pstats.Stats(profile, stream=handle).sort_stats('cumulative').print_stats(45)
            QTimer.singleShot(50, finish)
        profile.enable()
        self.session.execute(name, args or {}, replied)

    def _debug_frames(self, target, view, seconds=1.0):
        """转到 view 这个视角, 把之后 seconds 秒里每一帧开始画、画完的时刻 (秒) 写到 target (json)。只给界面冒烟测试用。"""
        import json
        import time
        from PySide6.QtCore import QTimer
        frames, window = [], self.window

        def began():
            frames.append([time.perf_counter(), None])

        def ended():
            if frames and frames[-1][1] is None:
                frames[-1][1] = time.perf_counter()

        window.beforeRendering.connect(began)
        window.afterRendering.connect(ended)
        start = time.perf_counter()
        self.setView(view)

        def done():
            window.beforeRendering.disconnect(began)
            window.afterRendering.disconnect(ended)
            with open(target, 'w', encoding='utf-8') as handle:
                json.dump({'start': start, 'frames': frames}, handle)
        QTimer.singleShot(int(seconds * 1000), done)

    def _debug_handle(self, reach):
        """用鼠标把拉伸的箭头拖到 reach 处 (走真鼠标的路径)。只给界面冒烟测试用。"""
        view = self.viewport
        if view is None or view._handle is None:
            return False
        origin, direction, _ = view._handle
        _, head = view._handle_lines()
        spots, _ = view._camera.project([head, origin + direction * float(reach)], view.width(), view.height())
        self._debug_mouse('press', spots[0][0] / view.width(), spots[0][1] / view.height())
        self._debug_mouse('move', spots[1][0] / view.width(), spots[1][1] / view.height())
        self._debug_mouse('release', spots[1][0] / view.width(), spots[1][1] / view.height())
        return True

    def _debug_mouse(self, kind, fx, fy, button='left'):
        """往三维视图里送一个鼠标事件 (kind: press / move / release / hover 不按键移动; 位置是视图宽高的比例 0~1)。
        事件发给窗口, 走的是和真鼠标一样的分发路径。只给 tests/smoke_ui.py 通过接口的 'ui' 命令调。"""
        from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        which = {'left': Qt.LeftButton, 'middle': Qt.MiddleButton, 'right': Qt.RightButton}[button]
        kinds = {'press': QEvent.MouseButtonPress, 'move': QEvent.MouseMove, 'hover': QEvent.MouseMove,
                 'release': QEvent.MouseButtonRelease}
        local = QPointF(fx * self.viewport.width(), fy * self.viewport.height())
        scene = self.viewport.mapToScene(local)
        held = Qt.NoButton if kind in ('release', 'hover') else which
        event = QMouseEvent(kinds[kind], scene, self.window.mapToGlobal(scene.toPoint()),
                            Qt.NoButton if kind in ('move', 'hover') else which, held, Qt.NoModifier)
        QCoreApplication.sendEvent(self.window, event)
