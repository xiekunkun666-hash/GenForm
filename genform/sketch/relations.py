"""几何关系小图标 (量出来的水平 / 竖直 / 重合 / 相切)、属性管理器的内容、选中图形的小工具条。"""
from __future__ import annotations

import math

from ..sketchgeom import dist as _distance
from .. import sketchgeom as geom
from .common import _close, DIMENSIONS, FLAGS, HIT_PIXELS, MARK_NAMES, PROPERTY_TITLES, SPLINE_TOOLS, TOOL_TITLES
from .dimension import _dim_value


def _line_marks(shape):
    """一条直线是水平 / 竖直的 → [(关系键, '', 中点, 往上 (或往右) 让开的方向)]; 都不是是空的。"""
    x1, y1, x2, y2 = (float(shape[key]) for key in ('x1', 'y1', 'x2', 'y2'))
    span = math.hypot(x2 - x1, y2 - y1)
    if span < 1e-9:
        return []
    middle, normal = ((x1 + x2) / 2, (y1 + y2) / 2), (-(y2 - y1) / span, (x2 - x1) / span)
    if normal[1] < 0 or (normal[1] == 0 and normal[0] < 0):
        normal = (-normal[0], -normal[1])
    if abs(y2 - y1) <= 1e-6 * span:
        return [('horizontal', '', middle, normal)]
    if abs(x2 - x1) <= 1e-6 * span:
        return [('vertical', '', middle, normal)]
    return []


def _shape_marks(shape):
    """图形里每段直边的水平 / 竖直图标: 直线本身, 矩形 / 多边形 / 槽口的直边也算 (画矩形时四条边各有一个)。
    封闭图形的图标让到外面 (不挤在框里)。→ [(关系键, '', 中点, 让开方向, 第几条边)...]"""
    if shape.get('type') == 'line':
        return [mark + (0,) for mark in _line_marks(shape)]
    if shape.get('type') in ('text', 'point'):
        return []
    try:
        edges = [prim for prim in geom.prims(shape) if prim[0] == 'line']
    except (KeyError, TypeError, ValueError):
        return []
    if not edges:
        return []
    cx = sum(a[0] + b[0] for _, a, b in edges) / (2 * len(edges))
    cy = sum(a[1] + b[1] for _, a, b in edges) / (2 * len(edges))
    marks = []
    for edge, (_, (x1, y1), (x2, y2)) in enumerate(edges):
        for kind, text, middle, (nx, ny) in _line_marks({'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2}):
            if (middle[0] - cx) * nx + (middle[1] - cy) * ny < 0:
                nx, ny = -nx, -ny
            marks.append((kind, text, middle, (nx, ny), edge))
    return marks


class RelationMixin:
    """几何关系和属性管理器 (草图编辑器的一部分)。"""

    # ---- 选中图形的小工具条和属性栏 ----
    def relations_held(self):
        """选中的图形现在满足哪些几何关系 → [键...]。是量出来的 (照这个关系再摆一次图形不动 = 满足), 不是存着的约束。"""
        held = []
        for kind in (geom.relations_for(self._chosen()) if self.selection else []):
            try:
                after = geom.relate(self.shapes, list(self.selection), kind)
            except ValueError:
                continue
            if all(_close(after[index], self.shapes[index]) for index in self.selection):
                held.append(kind)
        return held

    def relation_marks(self):
        """画在图形旁边的几何关系小图标 (和 SOLIDWORKS 画线时自动加上的那几种一样): 水平 / 竖直的直线和直边 (中点旁边; 矩形、多边形的边也算)、
        重合 (端点或点落在别的图形中间, 或两个图形首尾接在一起)、相切 (直线接圆弧不拐弯)。正在画的那条线也标 (画水平了就出现水平图标)。
        → [(关系键, '', (x, y) 图形上的点, (ux, uy) 往哪边让开, 编号)...] (草图平面坐标; 让开多远由视图按像素定)。
        编号 = "图形序号|键", 点图标选中它、删掉它用 (删掉 = 键记进那个图形的 norel, 不再标); 正在画的那条线的编号是空的。
        是量出来的, 不是存着的约束; "相等" "同心" 这种碰巧一样的不标 (不是画的时候定下来的)。
        图形没变就用上次算的 (转视角时每帧都要)。"""
        if self.operation is not None:
            return []
        drawing = self._preview_shapes() if self.draft is not None else []
        live = [mark[:4] + ('',) for shape in drawing for mark in _shape_marks(shape)]
        signature = repr(self.shapes)
        if getattr(self, '_marks', (None,))[0] == signature:
            return self._marks[1] + live
        marks, shapes = [], self.shapes
        tiny = 1e-6

        def same(a, b):
            return _distance(a, b) <= tiny * max(1.0, abs(a[0]) + abs(a[1]))

        def add(index, kind, tip, way, key):
            if key not in shapes[index].get('norel', ()):
                marks.append((kind, '', tip, way, f'{index}|{key}'))

        for index, shape in enumerate(shapes):
            for kind, _, middle, way, edge in _shape_marks(shape):
                add(index, kind, middle, way, f'{kind}:{edge}')

        # 端点 / 点 落在别的图形中间 = 重合; 直线和圆弧在端点接上而且不拐弯 = 相切
        if len(shapes) <= 200:
            tips = []
            for index, shape in enumerate(shapes):
                if shape['type'] == 'point':
                    tips.append((index, (float(shape['x']), float(shape['y']))))
                else:
                    tips += [(index, tuple(map(float, end))) for end in (geom.ends(shape) or ())]
            seen = set()
            for index, tip in tips:
                for other, shape in enumerate(shapes):
                    if other == index or shape['type'] in ('text', 'point'):
                        continue
                    gap, _ = geom.nearest(shape, tip)
                    if gap > tiny * max(1.0, abs(tip[0]) + abs(tip[1])):
                        continue
                    ends = geom.ends(shape) or ()
                    spot = (round(tip[0], 5), round(tip[1], 5))
                    if any(same(tip, end) for end in ends):
                        mine, theirs = shapes[index], shape
                        pair = {mine['type'], theirs['type']}
                        if pair == {'line', 'arc'} and ('tangent', spot) not in seen:
                            line, arc = (mine, theirs) if mine['type'] == 'line' else (theirs, mine)
                            along = geom._unit(float(line['x2']) - float(line['x1']), float(line['y2']) - float(line['y1']))
                            radial = geom._unit(tip[0] - float(arc.get('cx', 0.0)), tip[1] - float(arc.get('cy', 0.0)))
                            if abs(along[0] * radial[0] + along[1] * radial[1]) < 1e-6:
                                seen.add(('tangent', spot))
                                add(index, 'tangent', tip, radial, f'tangent@{spot[0]:g},{spot[1]:g}')
                                continue
                        if ('tangent', spot) in seen or ('coincident', spot) in seen:
                            continue
                        # 两个图形首尾接在一起 (拐角) 也是重合: 图标让到两条线夹角的外面, 不压在线上
                        away = [0.0, 0.0]
                        for piece in (mine, theirs):
                            far = [end for end in (geom.ends(piece) or ()) if not same(tip, end)]
                            if far:
                                unit = geom._unit(far[0][0] - tip[0], far[0][1] - tip[1])
                                away[0] -= unit[0]
                                away[1] -= unit[1]
                        if math.hypot(*away) < 1e-6:          # 接成一条直线: 往旁边让
                            away = [-0.7071, -0.7071]
                        seen.add(('coincident', spot))
                        add(index, 'coincident', tip, tuple(geom._unit(*away)), f'coincident@{spot[0]:g},{spot[1]:g}')
                        continue
                    if ('coincident', spot) not in seen:
                        seen.add(('coincident', spot))
                        add(index, 'coincident', tip, (-0.7071, -0.7071), f'coincident@{spot[0]:g},{spot[1]:g}')     # 左下: 不和中点上方的水平 / 竖直图标挤在一起
        self._marks = (signature, marks)
        return marks + live

    def finish_tool(self):
        """属性管理器上点了 ✓: 正在画的一串收尾, 回到选择; 本来就在选择 = 放下选中的 (回设计树)。"""
        if self.relation:
            self.relation = None
            return
        if self.tool != 'select':
            if self.draft is not None and self.tool in SPLINE_TOOLS and len(self.draft['points']) >= 2:
                self._commit_spline(closed=False)
            self.set_tool('select')
            return
        self.selection, self.hover = [], None

    def select_relation(self, ident):
        """点了一个几何关系小图标: 选中它 (图形的选中放下), 属性管理器里显示它, Delete 删掉。"""
        known = {mark[4] for mark in self.relation_marks() if mark[4]} | {f'dim:{number}' for number, _ in self._live_dims()}
        self.relation = ident if ident in known else None
        if self.relation:
            self.selection, self.hover, self.operation = [], None, None

    def delete_relation(self, ident=None):
        """删掉一个几何关系小图标: 记进那个图形的 norel, 以后不再标。
        软件没有约束求解, 关系本来就是量出来的: 删掉只是不再标出来, 图形不动 (之后拖成别的样子也不会被拉回来)。"""
        ident = ident or self.relation
        self.relation = None
        if ident and ident.startswith('dim:'):          # 删一个尺寸: 图形不动
            number = int(ident[4:])
            if 0 <= number < len(self.dims):
                self.dims = self.dims[:number] + self.dims[number + 1:]
            return
        if not ident or '|' not in ident:
            return
        number, key = ident.split('|', 1)
        try:
            index = int(number)
        except ValueError:
            return
        if 0 <= index < len(self.shapes):
            shape = dict(self.shapes[index])
            shape['norel'] = sorted(set(shape.get('norel', ())) | {key})
            self.shapes = self.shapes[:index] + [shape] + self.shapes[index + 1:]

    def relate_now(self, kind):
        """给选中的图形加一个几何关系 (照关系摆一次; 第一个选中的不动)。"""
        chosen = list(self.selection)
        movers = chosen if len(chosen) == 1 else chosen[1:]
        if any(self.shapes[index].get('fixed') for index in movers):
            self.message = '固定着的图形不能动：先取消“固定”，或者先选它（第一个选中的不动）'
            return
        self._try(lambda: geom.relate(self.shapes, chosen, kind))
        if not self.message:
            self.selection = chosen

    def toggle_flag(self, key):
        """选中的图形: 固定 / 构造线 / 无限长度 开或关 (都开着就关, 否则都打开)。"""
        chosen = [shape for shape in self._chosen() if key == 'fixed' or shape['type'] not in ('point', 'text')]
        if key == 'infinite':
            chosen = [shape for shape in chosen if shape['type'] == 'line']
        if key not in FLAGS or not chosen:
            return
        turn_on = not all(shape.get(key) for shape in chosen)
        for shape in chosen:
            if turn_on:
                shape[key] = True
                if key == 'infinite':
                    shape['construction'] = True        # 无限长的线只能是构造线: 它围不成轮廓
            else:
                shape.pop(key, None)
                if key == 'construction':
                    shape.pop('infinite', None)

    def select_other(self):
        """刚才点的位置上叠着好几个图形: 换成下一个。"""
        if self._click is None:
            return
        point, pixel = self._click
        hits = [index for index, shape in enumerate(self.shapes) if self._hit(shape, point, HIT_PIXELS * pixel)]
        if len(hits) < 2:
            self.message = '这个位置没有叠着别的图形'
            return
        now = self.selected if self.selected in hits else hits[-1]
        self.selection = [hits[(hits.index(now) + 1) % len(hits)]]

    def dimension_selected(self):
        """对选中的那一个图形用智能尺寸。"""
        index = self.selected
        if index is None:
            self.message = '智能尺寸：先只选一个图形'
            return
        self.set_tool('dimension')
        self._press_dimension((index, None))

    def selection_bounds(self):
        points = [point for shape in self._chosen() for line in self._lines(shape) for point in line]
        points += [(shape['x'], shape['y']) for shape in self._chosen() if shape['type'] in ('point', 'text')]
        if not points:
            return None
        return (min(x for x, _ in points), min(y for _, y in points)), (max(x for x, _ in points), max(y for _, y in points))

    def context_items(self):
        """点中图形后旁边那排小按钮 → [{'id', 'icon', 'title', 'tip'}...]。"""
        chosen = self._chosen()
        if not chosen:
            return []
        rows = []

        def add(action, icon, title, tip):
            rows.append({'id': action, 'icon': icon, 'title': title, 'tip': f'{title}：{tip}'})

        for kind in geom.relations_for(chosen):
            add(f'rel:{kind}', f'rel_{kind}', f'使{geom.RELATIONS[kind]}',
                '把这条线摆成这样' if len(chosen) == 1 else '第一个选中的不动，其余的向它看齐（摆一次，不是保持住的约束）')
        fixed = all(shape.get('fixed') for shape in chosen)
        add('flag:fixed', 'lock', '解除固定' if fixed else '使固定', '固定着的图形拖不动、改不了尺寸')
        lines = [shape for shape in chosen if shape['type'] not in ('point', 'text')]
        if lines:
            add('flag:construction', 'centerline', '构造几何线', '变成构造线（只作参考，不参与拉伸），再点一次变回来')
        if len(chosen) == 1 and chosen[0]['type'] in DIMENSIONS:
            add('dimension', 'dimension', '智能尺寸', '标这个图形的尺寸，改数字图形跟着变')
        if len(chosen) == 1:
            add('select_other', 'select_other', '选择其他', '这个位置叠着别的图形时换成下一个')
        add('zoom', 'zoom_sel', '放大所选范围', '把选中的图形放满画面')
        add('delete', 'trash', '删除', '删掉选中的图形')
        add('exit', 'finish', '退出草图', '保存这个草图并退出')
        return rows

    def properties(self):
        """右边属性栏的内容 → {'title', 'held': 现在满足的关系, 'relations': 能加的关系, 'options': 开关, 'params', 'extra'}
        或 None (没选中东西)。"""
        if self.relation and self.relation.startswith('dim:') and self.operation is None:
            dim = self.dims[int(self.relation[4:])]
            value = _dim_value(dim.get('mode', 'a'), self._dim_points(dim))
            label = {'h': '水平距离', 'v': '竖直距离'}.get(dim.get('mode'), '距离')
            return {'title': '尺寸', 'held': [], 'relations': [], 'options': [], 'extra': [],
                    'params': [{'key': 'dim_value', 'label': label, 'type': 'number', 'value': float(value), 'unit': 'mm'}],
                    'actions': [{'id': 'delete_relation', 'icon': 'delete', 'title': '删除这个尺寸'}],
                    'note': '改数字 = 第二处移动到这个距离（改一次，不是保持住的约束）。删掉尺寸图形不动。'}
        if self.relation and self.operation is None:
            kind = self.relation.split('|', 1)[1].split(':')[0].split('@')[0]
            return {'title': '几何关系', 'held': [MARK_NAMES.get(kind, kind)], 'relations': [], 'options': [], 'params': [], 'extra': [],
                    'actions': [{'id': 'delete_relation', 'icon': 'delete', 'title': '删除这个几何关系'}],
                    'note': '这个关系是按现在的形状量出来的。删掉后不再标出来，图形不动；之后拖成别的样子也不会被拉回来。'}
        if self._edge() is not None and self.operation is None:
            index, side = self._edge()
            rect = self.shapes[index]
            return {'title': '线条属性', 'held': ['水平' if side % 2 == 0 else '竖直'], 'relations': [], 'options': [], 'extra': [],
                    'params': [{'key': 'edge_length', 'label': '长度', 'type': 'number', 'unit': 'mm',
                                'value': float(rect['w'] if side % 2 == 0 else rect['h'])}],
                    'actions': [], 'note': '矩形的一条边：拖它只挪这条边（对边不动）；双击或框选选中整个矩形。Delete 删掉这条边（矩形拆成另外三条线）。'}
        chosen = self._chosen()
        if not chosen and self.operation is None and self.tool in TOOL_TITLES:
            return {'title': TOOL_TITLES[self.tool], 'tool': self.tool, 'held': [], 'relations': [], 'options': [], 'params': [], 'extra': []}
        if not chosen or self.operation is not None:
            return None
        held = [geom.RELATIONS[kind] for kind in self.relations_held()]
        if all(shape.get('fixed') for shape in chosen):
            held.append('固定')
        info = {'title': PROPERTY_TITLES.get(chosen[0]['type'], geom.NAMES[chosen[0]['type']] + '属性') if len(chosen) == 1
                else f'选中了 {len(chosen)} 个图形',
                'held': held,
                'relations': [{'id': f'rel:{kind}', 'icon': f'rel_{kind}', 'title': geom.RELATIONS[kind]}
                              for kind in geom.relations_for(chosen)] + [{'id': 'flag:fixed', 'icon': 'lock', 'title': '固定'}],
                'options': [], 'params': [], 'extra': []}
        lines = [shape for shape in chosen if shape['type'] not in ('point', 'text')]
        if lines:
            info['options'].append({'id': 'flag:construction', 'label': '作为构造线', 'value': all(s.get('construction') for s in lines)})
        if lines and all(shape['type'] == 'line' for shape in lines):
            info['options'].append({'id': 'flag:infinite', 'label': '无限长度', 'value': all(s.get('infinite') for s in lines)})
        if len(chosen) > 1:
            return info
        shape = chosen[0]
        info['params'] = [field for field in self.fields() if field['type'] in ('number', 'text', 'bool', 'choice')
                          and field['key'] not in ('offset', 'construction')]

        def shown(label, value, unit='mm'):
            info['extra'].append({'key': '', 'label': label, 'type': 'number', 'value': float(value), 'unit': unit, 'readonly': True})

        kind = shape['type']
        if kind == 'line':
            info['extra'] += [{'key': 'dx', 'label': 'ΔX', 'type': 'number', 'value': shape['x2'] - shape['x1'], 'unit': 'mm'},
                              {'key': 'dy', 'label': 'ΔY', 'type': 'number', 'value': shape['y2'] - shape['y1'], 'unit': 'mm'}]
            shown('中点 X', (shape['x1'] + shape['x2']) / 2)
            shown('中点 Y', (shape['y1'] + shape['y2']) / 2)
        elif kind == 'circle':
            info['extra'].append({'key': 'r', 'label': '半径', 'type': 'number', 'value': shape['r'], 'unit': 'mm'})
            shown('周长', 2 * math.pi * shape['r'])
            shown('面积', math.pi * shape['r'] ** 2, 'mm²')
        elif kind == 'arc':
            sweep = (shape['a1'] - shape['a0']) % 360 or 360.0
            shown('圆心角', sweep, '°')
            shown('弧长', math.radians(sweep) * shape['r'])
        elif kind == 'rect':
            shown('周长', 2 * (shape['w'] + shape['h']))
            shown('面积', shape['w'] * shape['h'], 'mm²')
        return info
