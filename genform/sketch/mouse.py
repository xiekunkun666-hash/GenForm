"""鼠标和按键: 按下 / 移动 / 松开 / 双击 / 按键分给各个工具。"""
from __future__ import annotations

import copy

from ..sketchgeom import dist as _distance
from .. import sketchgeom as geom
from .common import CHAIN_TOOLS, DRAG_PIXELS, DRAG_TOOLS, handles, SNAP_PIXELS, SPLINE_TOOLS, STEPS


class MouseMixin:
    """鼠标和按键 (草图编辑器的一部分)。"""

    # ---- 鼠标 ----
    def press(self, point, pixel, additive=False):
        self._press = point
        self.relation = None
        self._raw, self._pixel = point, pixel
        tool = self.tool
        busy = self.operation is not None and self.operation['kind'] == 'dimension'
        if tool in ('select', 'dimension') and not busy and not additive:
            number = self._dim_at(point, pixel)
            if number is not None:                  # 按住一个放下的尺寸: 选中它, 拖 = 换个地方放 (量法和数不变)
                self.relation, self.selection, self.edge, self.hover_dim = f'dim:{number}', [], None, number
                self._drag = {'dim': number, 'base': None, 'handle': None}
                return
        if tool == 'select':
            self._press_select(point, pixel, additive)
            return
        if tool in ('trim', 'extend'):
            index = self._shape_at(point, pixel)
            if index is not None:
                self._try(lambda: (geom.trim if tool == 'trim' else geom.extend)(self.shapes, index, point))
            return
        if tool == 'dimension':
            operation = self.operation
            pick = self._dimension_pick(point, pixel)
            if operation and operation['kind'] == 'dimension' and not operation.get('placed') \
                    and (operation.get('b') is not None or (operation.get('single') and pick is None)):
                self._dim_follow(point)                     # 放在这里: 存进草图, 属性管理器里改数
                self._place_dimension()
                return
            self._press_dimension(pick)
            return
        if tool == 'fillet':
            self._try(lambda: geom.fillet(self.shapes, point, float(self.options['radius']), SNAP_PIXELS * 2 * pixel))
            return
        if tool == 'convert':
            index = self._reference_at(point, pixel)
            if index is not None:
                shape = copy.deepcopy(self.references[index])
                if any(geom._same(shape, other) for other in self.shapes):
                    self.message = '这条边已经在草图里了'
                else:
                    self.shapes.append(shape)
                    self.selection = [len(self.shapes) - 1]
            return
        if tool == 'offset':
            if self.draft is None:
                index = self._shape_at(point, pixel)
                if index is not None and self.shapes[index]['type'] not in ('point', 'text'):
                    self.draft = {'points': [point], 'cursor': point, 'source': index}
                    self.selection = []
            else:
                self.draft['cursor'] = point
                made = self._preview_shapes()
                self.draft = None
                if made:
                    self.shapes.append(made[0])
                    self.selection = [len(self.shapes) - 1]
            return
        target = self.snap(point, pixel)
        self.cursor, self.snap_only = target, None
        if tool == 'point':
            self._add({'type': 'point', 'x': target[0], 'y': target[1]})
        elif tool == 'text':
            self._add({'type': 'text', 'x': target[0], 'y': target[1], 'text': '文本', 'height': 10.0, 'angle': 0.0})
        elif tool == 'equation':
            self._add({'type': 'equation', 'mode': 'explicit', 'fx': 't', 'fy': '10*sin(x/5)', 't0': 0.0, 't1': 60.0,
                       'ox': target[0], 'oy': target[1]})
        elif self.draft is None:
            self.draft = {'points': [target], 'cursor': target, 'start': target, 'count': 0, 'sweep': 0.0}
            if tool not in ('mirror', 'move'):
                self.selection = []
        elif tool in CHAIN_TOOLS:
            last = self.draft['points'][-1]
            if _distance(target, last) > 1e-9:
                self.shapes.append(self._line(last, target, tool == 'centerline'))
                self.draft['points'], self.draft['count'] = [target], self.draft['count'] + 1
                if self.draft['count'] >= 2 and _distance(target, self.draft['start']) <= 1e-9:
                    self.draft = None                           # 点回了起点: 这一串闭合了
        elif tool in SPLINE_TOOLS:
            points = self.draft['points']
            if len(points) >= 3 and _distance(target, points[0]) <= 1e-9 and tool == 'spline':
                self._commit_spline(closed=True)
            elif _distance(target, points[-1]) > 1e-9:
                points.append(target)
        else:
            self.draft['cursor'] = target
            if len(self.draft['points']) + 1 >= STEPS[tool]:
                self._commit(target)
            elif _distance(target, self.draft['points'][-1]) > 1e-9:
                self.draft['points'].append(target)

    def box(self):
        """正在拖的选择框 → (起点, 现在的角), 没在拖是 None。框由界面画。"""
        return None if self._box is None else (tuple(self._box[0]), tuple(self._box[1]))

    def move(self, point, pixel):
        self._raw, self._pixel = point, pixel
        if self._drag is not None:
            if 'dim' in self._drag:
                self.move_dimension(self._drag['dim'], point)
            else:
                self._move_drag(point, pixel)
            return
        if self._box is not None:
            self._box[1] = point
            return
        tool = self.tool
        if tool in ('select', 'trim', 'extend', 'dimension', 'fillet', 'convert') or (tool == 'offset' and self.draft is None):
            self.cursor, self.snapped, self.snap_kind = None, False, ''
            self.hover = self._shape_at(point, pixel) if tool != 'convert' else None
            self.hover_edge = (self.hover, self._side_at(self.hover, point)) \
                if tool == 'select' and self.hover is not None and self.shapes[self.hover]['type'] == 'rect' else None
            found = self._point_at(point, pixel) if tool == 'select' else None
            self.hover_point = dict(handles(self.shapes[found[0]]))[found[1]] if found else None     # 选择时停在端点上: 那个点亮
            busy = self.operation is not None and self.operation['kind'] == 'dimension'
            self.hover_dim = self._dim_at(point, pixel) if tool in ('select', 'dimension') and not busy else None
            if self.hover_dim is not None:          # 停在放下的尺寸上: 只亮这个尺寸 (光标变成四向箭头, 能拖)
                self.hover, self.hover_edge, self.hover_point = None, None, None
            self._reference_hover = self._reference_at(point, pixel) if tool == 'convert' else None
            if tool == 'fillet':
                self.cursor = geom.corner_near(self.shapes, point, SNAP_PIXELS * 2 * pixel)
                self.snapped = self.cursor is not None
            if tool == 'dimension':
                self._dim_follow(point)
                pick = self._dim_hover = self._dimension_pick(point, pixel)     # 停在端点 / 圆心上: 亮出那个点, 表示点下去选的是点
                if pick is not None and (pick[1] is not None or self.shapes[pick[0]]['type'] == 'point'):
                    self.cursor, self.snapped = self._dim_spot(*pick), True
            return
        if tool == 'offset':
            self.draft['cursor'] = point
            return
        self.cursor = self.snap(point, pixel)
        if self.draft is not None:
            self.draft['cursor'] = self.cursor
            self._track_sweep()

    def release(self, point, pixel):
        press, self._press = self._press, None
        self._click = (point, pixel)
        # 选择工具下原地点了一下 (没拖动) 并且有东西选中着: 界面在旁边弹出小工具条
        self.clicked = bool(self.tool == 'select' and self.operation is None and press is not None and self.selection
                            and _distance(point, press) <= DRAG_PIXELS * pixel)
        if self._drag is not None:
            drag, self._drag = self._drag, None
            base = drag['base']
            # 整个矩形选中着时在它的边上单击 (没拖动): 改成只选这条边
            if drag['handle'] is None and press is not None and _distance(point, press) <= DRAG_PIXELS * pixel \
                    and self.selection == [base] and self.shapes[base]['type'] == 'rect':
                self.edge = (base, self._side_at(base, point))
            return
        if self._box is not None:
            (x0, y0), (x1, y1) = self._box[0], point        # 用松开的位置: 最后一段移动不一定单独送到过
            self._box = None
            if max(abs(x1 - x0), abs(y1 - y0)) > DRAG_PIXELS * pixel:
                low, high = (min(x0, x1), min(y0, y1)), (max(x0, x1), max(y0, y1))
                def spots(shape):       # 点和文本没有线: 看它自己的位置 (不然 "全都在框里" 对它们永远成立)
                    return [(shape['x'], shape['y'])] if shape['type'] == 'point' \
                        else [spot for line in self._lines(shape) for spot in line] or [(shape.get('x', 0.0), shape.get('y', 0.0))]
                self.selection = [index for index, shape in enumerate(self.shapes)
                                  if all(low[0] <= x <= high[0] and low[1] <= y <= high[1] for x, y in spots(shape))]
            return
        # 按住拖出矩形 / 圆 / 多边形: 松开时离起点够远就直接完成 (不用再点第二下)
        if self.tool in DRAG_TOOLS and self.draft is not None and press is not None \
                and _distance(point, press) > DRAG_PIXELS * pixel:
            self._raw, self._pixel = point, pixel
            self.cursor = self.snap(point, pixel)
            self.draft['cursor'] = self.cursor
            self._commit(self.cursor)

    def double_click(self):
        if self.tool in CHAIN_TOOLS:
            self.draft = None
        elif self.tool in SPLINE_TOOLS and self.draft is not None:
            self._commit_spline(closed=False)
        elif self.tool == 'select' and self.hover is not None:
            self.selection, self.edge = geom.chain_of(self.shapes, self.hover), None       # 双击矩形的边 = 选整个矩形

    def key(self, name):
        """→ 这个按键有没有被草图用掉。"""
        if self.relation and name in ('delete', 'escape'):     # 点中了一个几何关系小图标: Delete 删它, Esc 放开它
            if name == 'delete':
                self.delete_relation()
            self.relation = None
            return True
        if name == 'escape':
            if self.operation is not None:
                self.cancel_operation()
                return True
            if self.draft is not None:
                self.draft = None
                return True
            if self.tool != 'select':
                self.set_tool('select')
                return True
            if self.selection:
                self.selection = []
                return True
            return False
        if name == 'enter' and self.draft is not None and self.tool in CHAIN_TOOLS + SPLINE_TOOLS:
            if self.tool in SPLINE_TOOLS:
                self._commit_spline(closed=False)
            self.draft = None
            return True
        if name == 'delete' and self._edge() is not None:
            index, side = self._edge()
            rect = self.shapes[index]
            corners = geom.vertices(rect)
            rest = [self._line(corners[number], corners[(number + 1) % 4], bool(rect.get('construction')))
                    for number in range(4) if number != side]
            self.shapes = [shape for number, shape in enumerate(self.shapes) if number != index] + rest
            self._forget_shapes([index])
            self.selection, self.hover, self.edge = [], None, None
            return True
        if name == 'delete' and self.selection:
            self._forget_shapes(self.selection)
            self.shapes = [shape for index, shape in enumerate(self.shapes) if index not in set(self.selection)]
            self.selection, self.hover = [], None
            return True
        return False
