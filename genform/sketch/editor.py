"""草图编辑器: 状态、工具切换、出参数、给视图画的东西; 其余能力在同一个包里的几个混入类里 (见 genform/sketcher.py 的说明)。"""
from __future__ import annotations

import copy

from ..sketchgeom import dist as _distance
from .. import sketchgeom as geom
from .common import ALL_SNAPS, _dashes, describe, DIMENSIONS, FAR, handles, SNAP_NAMES, TEXT_PATHS, TOOLS
from .building import BuildMixin
from .dimension import DimensionMixin
from .mouse import MouseMixin
from .panels import PanelMixin
from .relations import RelationMixin
from .selecting import SelectMixin
from .snapping import SnapMixin


class SketchEditor(SnapMixin, MouseMixin, BuildMixin, DimensionMixin, SelectMixin, PanelMixin, RelationMixin):

    def __init__(self, plane='XY', offset=0.0, shapes=(), feature=None, name='', dims=()):
        self.plane, self.offset = plane, float(offset)
        self.plane_ref = None           # 画在基准面特征上时是它的 id (这时 plane 是算好的坐标系)
        self.shapes = copy.deepcopy(list(shapes))
        self.feature = feature          # 正在编辑的草图特征 id; None = 新草图
        self.name = name
        self.tool = 'select' if self.shapes else 'rect'
        self.selection = []             # 选中的图形序号
        self.clicked = False            # 刚才那一下是不是 "单击选中了东西" (界面据此弹小工具条)
        self._click = None              # 最近一次松开鼠标的位置和像素大小 ("选择其他" 用)
        self.hover = None               # 光标下的图形序号
        self.draft = None               # 正在画的: {'points': [已经点下的点...], 'cursor': (x, y), ...}
        self.cursor = None              # 捕捉后的光标位置
        self.snapped = False            # 光标是不是吸在了某个点上 (画个记号提示用户)
        self.snap_kind = ''             # 吸在了哪种点上 (SNAP_NAMES 的键)
        self.snap_only = None           # 快速捕捉: 下一次点击只吸这一种点
        self.snaps = set(ALL_SNAPS)     # 开着的捕捉 (ALL_SNAPS 里的键)
        self.options = {'radius': 5.0, 'sides': 6}      # 工具的参数: 圆角半径、多边形边数
        self.operation = None           # 开着面板的操作: {'kind': 'pattern' | 'repair', ...}
        self.hover_point = None         # 选择工具下光标停着的端点 / 角 (画亮一点, 表示能点住拖)
        self.hover_dim = None           # 光标停着的放下的尺寸 (序号): 它亮, 光标变成四向箭头
        self.edge = None                # 选中的是矩形的哪条边: (图形序号, 边号 0 下 1 右 2 上 3 左); 选中整个矩形是 None
        self.hover_edge = None          # 光标下的矩形的边 (只亮这一条, 不亮整个矩形)
        self.dims = [dict(dim) for dim in dims]     # 放下的智能尺寸: {'a', 'pa', 'b', 'pb', 'mode', 'place', 'ta', 'tb'}; 只是标出来, 数是现量的
        self.relation = None            # 点中的几何关系小图标的编号 (relation_marks 给的), Delete 删掉它
        self.issues = []                # 检查草图找出来的问题 (见 sketchgeom.diagnose)
        self.references = []            # 实体的边投影到草图平面上的样子 (转换实体引用用)
        self.message = ''               # 要告诉用户的一句话 (刚才那一下为什么没成); 外面读走后清掉
        self.outliner = None            # 文本 → 字的轮廓折线 (界面提供; 没有就画一个占位框)
        self._raw = (0.0, 0.0)          # 没捕捉过的光标位置
        self._pixel = 1.0               # 最近一次鼠标事件时一个像素多少毫米
        self._drag = None               # 正在拖的: {'handle'|None, 'origin', 'shapes' 拖之前的副本, 'base'}
        self._box = None                # 正在拖的选择框: [起点, 现在的角]
        self._press = None
        self._reference_hover = None

    # ---- 选中 ----
    @property
    def selected(self):
        """只选中了一个图形时是它的序号, 否则 None。"""
        return self.selection[0] if len(self.selection) == 1 else None

    @selected.setter
    def selected(self, index):
        self.selection = [] if index is None else [index]

    def _chosen(self):
        return [self.shapes[index] for index in self.selection]

    # ---- 工具 ----
    def set_tool(self, tool):
        if tool not in TOOLS:
            raise ValueError(f'没有这个草图工具: {tool}')
        if tool in ('mirror', 'move') and not self.selection:
            self.message = f'先选中要{"镜向" if tool == "mirror" else "移动"}的图形（点选，Ctrl 加选，或拖方框框选）'
            tool = 'select'
        if tool == 'convert' and not self.references:
            self.message = '还没有实体：转换实体引用是把实体的边拷到草图里'
            tool = 'select'
        if tool == 'text' and self.selected is not None and self.shapes[self.selected]['type'] in TEXT_PATHS:
            path = copy.deepcopy(self.shapes[self.selected])            # 选着一条曲线点 "文本": 字沿着它排
            spot = geom.anchor(path)
            self.shapes.append({'type': 'text', 'x': spot[0], 'y': spot[1], 'text': '文本', 'height': 10.0,
                                'angle': 0.0, 'path': path, 'flip': False})
            self.selection = [len(self.shapes) - 1]
            tool = 'select'
        if tool not in ('select', 'mirror', 'move'):        # 拿起画图 / 修改工具: 之前选中的放下, 面板让给工具
            self.selection = []
        self.tool, self.draft, self._drag, self._box, self.hover = tool, None, None, None, None
        self.operation, self._reference_hover, self.relation = None, None, None
        self._dim_hover, self.edge, self.hover_edge, self.hover_dim = None, None, None, None

    def _sized(self, dims):
        """标过尺寸的: (整个图形的序号集合, 矩形 / 多边形被标的边 {(序号, 第几条边)})。直线、圆、圆弧被标了整个算;
        矩形、多边形只算被标的那条边 (标它的角或中心不算哪条边)。"""
        whole, sides = set(), set()
        for _, dim in dims:
            for key, spec_key in (('a', 'pa'), ('b', 'pb')):
                index, spec = dim.get(key), dim.get(spec_key)
                if index is None or index >= len(self.shapes):
                    continue
                if self.shapes[index]['type'] in ('rect', 'polygon', 'ngon'):
                    if spec and spec[0] == 's':
                        sides.add((index, int(spec[1:]) % len(geom.vertices(self.shapes[index]))))
                else:
                    whole.add(index)
        return whole, sides

    def _try(self, action):
        """做一个可能不成立的修改 (剪裁、圆角…); 不成立时把原因留在 message 里。"""
        try:
            self.shapes = action()
            self.selection, self.hover = [], None
        except ValueError as error:
            self.message = str(error)

    # ---- 结果 ----
    def params(self):
        params = {'plane': self.plane_ref or self.plane, 'offset': self.offset, 'shapes': copy.deepcopy(self.shapes)}
        dims = self._live_dims()
        if dims:
            params['dims'] = [copy.deepcopy(dim) for _, dim in dims]
        return params

    # ---- 给视图画的东西 ----
    def drawing(self):
        """→ (线段 [((x0,y0),(x1,y1), 状态)...], 点 [((x,y), 状态)...], 标注 [(文字, (x,y))...])。
        状态: 0 普通 / 1 悬停 / 2 选中 / 3 正在画 / 4 标过尺寸的 / 5 尺寸线 (尺寸的数字见 dim_labels)。"""
        lines, points, labels = [], [], []
        tips = {}

        def stroke(shape, state, ends_too=True):
            # 线段的起点终点 (圆弧、开口样条的两头, 矩形 / 多边形的角) 默认画个点; 首尾相接的拐角只画一个, 亮的那个算数
            if ends_too and not shape.get('infinite') and shape['type'] not in ('text', 'point'):
                ends = list(geom.ends(shape) or ())
                if shape['type'] in ('rect', 'polygon', 'ngon'):
                    ends = [prim[1] for prim in geom.prims(shape) if prim[0] == 'line']
                for end in ends:
                    key = (round(float(end[0]), 6), round(float(end[1]), 6))
                    if key not in tips or tips[key][1] < state:
                        tips[key] = ((float(end[0]), float(end[1])), state)
            for line in self._lines(shape):
                if shape['type'] == 'line' and shape.get('infinite'):      # 无限长的构造线: 两头一直画出去
                    (x1, y1), (x2, y2) = line[0], line[-1]
                    span = max(_distance((x1, y1), (x2, y2)), 1e-9)
                    ux, uy = (x2 - x1) / span, (y2 - y1) / span
                    line = [(x1 - ux * FAR, y1 - uy * FAR), (x2 + ux * FAR, y2 + uy * FAR)]
                    lines.extend((a, b, state) for a, b in _dashes(line, 12.0 * self._pixel, 6.0 * self._pixel)
                                 if _distance(a, (x1, y1)) < 400 * 12.0 * self._pixel)      # 只画看得见的这一段, 不然虚线段数太多
                    continue
                if shape.get('construction'):           # 构造线画成虚线
                    lines.extend((a, b, state) for a, b in _dashes(line, 7.0 * self._pixel, 4.0 * self._pixel))
                else:
                    lines.extend((a, b, state) for a, b in zip(line, line[1:]))
            if shape['type'] == 'point':
                points.append(((shape['x'], shape['y']), state))

        chosen, edge, dims = set(self.selection), self._edge(), self._live_dims()
        sized, sized_sides = self._sized(dims)
        hover_edge = self.hover_edge if self.tool == 'select' else None
        for index, shape in enumerate(self.shapes):
            rest = 4 if index in sized else 0
            sides = [side for number, side in sized_sides if number == index]
            # 矩形 / 多边形标过尺寸的那几条边: 黑 (别的边照常; 画在整个图形上面, 光标下 / 选中的边再画在它上面)
            ring = geom.vertices(shape) if sides else []
            black = [(ring[side], ring[(side + 1) % len(ring)], 4) for side in sides]
            if shape['type'] == 'rect' and ((edge and edge[0] == index) or (hover_edge and hover_edge[0] == index)
                                            or (self.tool == 'select' and index == self.hover and index not in chosen)):
                # 矩形一条边一条边地上状态: 只亮光标下 / 选中的那条
                corners = geom.vertices(shape)
                whole = 2 if index in chosen and not edge else rest
                stroke(dict(shape, type='polygon', points=[list(corner) for corner in corners]), whole)
                lines += black if whole != 2 else []
                for side in range(4):
                    state = 2 if edge == (index, side) else 1 if hover_edge == (index, side) else None
                    if state is not None:
                        lines.append((corners[side], corners[(side + 1) % 4], state))
                continue
            whole = 2 if index in chosen else 1 if index == self.hover else rest
            stroke(shape, whole)
            lines += black if whole == 0 else []
        for number, dim in dims:                     # 尺寸: 光标停着的悬停色, 选中的选中色, 别的是尺寸线 (黑 / 白, 细)
            state = 1 if number == self.hover_dim else 2 if self.relation == f'dim:{number}' else 5
            lines += [(a, b, state) for a, b in self._dim_graphics(dim)[0]]
        if self.selected is not None and edge is None:
            shape = self.shapes[self.selected]
            points += [(position, 2) for _, position in handles(shape)]
            if shape['type'] not in ('text', 'point'):      # 这两种的标注会正好压在它自己上面
                labels.append((describe(shape), self._label_anchor(shape)))
        if self.tool == 'dimension':                     # 智能尺寸: 鼠标下的和选了的边 / 角单独亮出来 (不然只看得到整个矩形)
            operation = self.operation if self.operation and self.operation['kind'] == 'dimension' else {}
            picks = [getattr(self, '_dim_hover', None), (operation.get('a'), operation.get('pa')), (operation.get('b'), operation.get('pb'))]
            for pick in picks:
                if pick is None or pick[0] is None or pick[1] is None or pick[0] >= len(self.shapes):
                    continue
                line = self._dim_line(*pick)
                if line is not None:
                    lines.append((line[0], line[1], 3))
                else:
                    spot = self._dim_spot(*pick)
                    if spot is not None:
                        points.append((spot, 3))
        if self.tool == 'dimension':                     # 智能尺寸: 每个图形的尺寸都标出来, 点哪个改哪个
            labels += [(describe(shape), self._label_anchor(shape)) for index, shape in enumerate(self.shapes)
                       if shape['type'] in DIMENSIONS and index != self.selected]
            operation = self.operation
            if operation and operation['kind'] == 'dimension' and (operation.get('b') is not None or operation.get('single')):
                lines += [(a, b, 5) for a, b in self._dim_graphics(operation)[0]]     # 数字在 dim_labels
        if self.selected is not None and self.shapes[self.selected].get('style'):
            poles = [tuple(point) for point in self.shapes[self.selected]['points']]       # 样式样条: 把控制多边形画出来
            lines += [(a, b, 1) for a, b in _dashes(poles, 4.0 * self._pixel, 4.0 * self._pixel)]
        if self.tool == 'convert':
            for index, shape in enumerate(self.references):
                stroke(shape, 3 if index == self._reference_hover else 1, ends_too=False)
        made = self._preview_shapes()
        for shape in made:
            stroke(shape, 3)
        draft = self.draft
        if draft is not None:
            points += [(position, 3) for position in draft['points']]
            if made and self.tool not in ('mirror', 'move'):
                labels.append((describe(made[0]), draft['cursor']))
            elif self.tool == 'move':
                labels.append((f'{_distance(draft["points"][0], draft["cursor"]):.4g}', draft['cursor']))
        if self.operation and self.operation['kind'] == 'repair':
            points += [(issue['point'], 1) for issue in self.issues]
        if self.tool == 'select' and self.hover_point is not None and self._drag is None:
            points.append((self.hover_point, 1))
        if self.cursor is not None and self.tool != 'select':
            points.append((self.cursor, 1 if self.snapped else 3))
            if self.snap_kind and not (made and draft is not None):
                labels.append((SNAP_NAMES[self.snap_kind], self.cursor))
        taken = {(round(float(x), 6), round(float(y), 6)) for (x, y), _ in points}
        points[:0] = [tip for key, tip in tips.items() if key not in taken]     # 端点垫在最下面; 已经有控制点的地方不重复画
        return lines, points, labels

    @staticmethod
    def _label_anchor(shape):
        kind = shape['type']
        if kind == 'rect':
            return shape.get('cx', 0.0) + shape['w'] / 2, shape.get('cy', 0.0) + shape['h'] / 2
        if kind in ('circle', 'ngon'):
            return shape.get('cx', 0.0) + shape['r'] * 0.7071, shape.get('cy', 0.0) + shape['r'] * 0.7071
        if kind in ('line', 'slot'):
            return (shape['x1'] + shape['x2']) / 2, (shape['y1'] + shape['y2']) / 2
        return geom.anchor(shape)

    def bounds(self):
        """全部图形的范围 → ((xmin, ymin), (xmax, ymax)); 没有图形返回 None。"""
        points = [point for shape in self.shapes for line in self._lines(shape) for point in line]
        points += [(shape['x'], shape['y']) for shape in self.shapes if shape['type'] in ('point', 'text')]
        if not points:
            return None
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return (min(xs), min(ys)), (max(xs), max(ys))
