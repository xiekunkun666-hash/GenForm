# -*- coding: utf-8 -*-
"""草图编辑器: 在基准面上用鼠标画图形、拖动修改、填精确尺寸。纯数据和几何 (见 sketchgeom.py), 不碰界面库。

坐标都是草图平面内的二维坐标 (mm)。视图把鼠标位置换算成平面坐标再喂进来, pixel 是当前一个屏幕像素
对应多少毫米 — 捕捉和 "点没点中" 的容差都按屏幕像素算, 所以放大缩小后手感一样。

画图工具 (画完一个工具不变, 可以接着画; 刚画的处于选中状态, 面板里可以直接改成精确尺寸):
    line     连续点出一段段直线, 点回起点闭合; 回车 / 双击 / Esc 结束这一串 (centerline: 同样画法, 画出来的是构造线)
    midline  中点 → 一端 (另一端对称)      crect    中心 + 一个角
    rect3    一条边的两端 → 对边            crect3   中心 → 一边的中点 → 一个角        pgram  三个角
    cslot    中心 → 一个圆心 → 槽宽         circle3  圆周上三个点
    aslot3   弧的起点 → 终点 → 弧上一点 → 槽宽     caslot  圆心 → 起点 → 终点 → 槽宽
    sspline  样式样条: 点的是控制点          equation 点一下放一条方程式曲线, 式子在面板里改
    rect     两个对角 (或按住拖出)          circle   圆心 + 圆周上一点 (或按住拖出)
    arc      圆心 → 起点 → 终点             slot     两个圆心 → 槽宽
    ngon     中心 + 一个顶点 (边数在面板里)   ellipse  中心 → 长轴端点 → 短轴
    spline   连续点出经过的点, 回车 / 双击结束, 点回起点闭合
    point    点一下放一个点                 text     点一下放一行字; 先选中一条曲线再点工具 = 沿这条曲线排
修改工具:
    select   点选 (Ctrl 加选), 空白处拖出方框框选, 拖图形移动, 拖控制点改形状, 双击选中首尾相接的一串
    fillet   点两条直线相交的尖角            trim     点要剪掉的那一段        extend  点要延长的那一头
    dimension 智能尺寸: 点一个图形改它的主尺寸; 再点另一个图形 = 改它们之间的距离 (改一次, 不是保持住的约束)
    offset   点一个图形, 再点一下定距离和方向  convert  点实体的边 (投影到草图平面上的) 把它拷进草图
    mirror   先选图形, 再点两点定镜向轴       move     先选图形, 再点起点和终点
带面板的操作 (operation): pattern 线性阵列, cpattern 圆周阵列, relation 几何关系 (摆一次), repair 检查修复。

这里没有约束求解: 图形之间互不关联, 尺寸就是图形自己的参数。
"""
from __future__ import annotations

import copy
import math

from . import sketchgeom as geom
from .sketchgeom import dist as _distance

SNAP_PIXELS = 9.0           # 离特征点这么多像素以内就吸过去
QUICK_PIXELS = 28.0         # 指定了只捕捉某一种点时, 吸附范围放大到这么多
HIT_PIXELS = 7.0            # 离线这么多像素以内算点中
DRAG_PIXELS = 4.0           # 按下后移动超过这么多像素算拖动 (不然是单击)
GRID_STEPS = (0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0)
GRID_MIN_PIXELS = 7.0       # 捕捉格子在屏幕上至少这么大, 不然换下一档
TOOLS = ('select', 'line', 'centerline', 'midline', 'rect', 'crect', 'rect3', 'crect3', 'pgram', 'circle', 'circle3', 'arc',
         'slot', 'cslot', 'aslot3', 'caslot', 'ngon', 'ellipse', 'spline', 'sspline', 'equation', 'point', 'text',
         'dimension', 'fillet', 'trim', 'extend', 'offset', 'mirror', 'move', 'convert')
STEPS = {'rect': 2, 'crect': 2, 'midline': 2, 'circle': 2, 'ngon': 2, 'arc': 3, 'slot': 3, 'cslot': 3, 'ellipse': 3, 'rect3': 3,
         'crect3': 3, 'pgram': 3, 'circle3': 3, 'aslot3': 4, 'caslot': 4, 'mirror': 2, 'move': 2}   # 要点几下
DRAG_TOOLS = ('rect', 'crect', 'midline', 'circle', 'ngon')    # 可以按住拖出来的
CHAIN_TOOLS = ('line', 'centerline')                # 连着画一串直线的
SPLINE_TOOLS = ('spline', 'sspline')
SNAP_NAMES = {'end': '端点', 'mid': '中点', 'center': '中心点', 'quad': '象限点', 'int': '交叉点', 'near': '最近端（线上）',
              'hv': '水平/竖直', 'grid': '网格', 'origin': '原点'}
QUICK_SNAPS = ('end', 'mid', 'center', 'quad', 'int', 'near')
ALIGN_PIXELS = 5                    # 离水平 / 竖直对齐线这么近就对齐上去
ALL_SNAPS = QUICK_SNAPS + ('hv', 'grid')            # 可以单独开关的捕捉
DIMENSIONS = {'line': ('len',), 'circle': ('d',), 'arc': ('r',), 'rect': ('w', 'h'), 'slot': ('len', 'w'), 'ngon': ('r',),
              'ellipse': ('rx', 'ry'), 'arcslot': ('r', 'w')}     # 智能尺寸点一个图形时改的是它的哪几个尺寸
SNAP_ORDER = ('end', 'int', 'center', 'quad', 'mid', 'origin')
TEXT_PATHS = ('line', 'arc', 'circle', 'ellipse', 'spline')


def grid_step(pixel):
    for step in GRID_STEPS:
        if step / max(pixel, 1e-9) >= GRID_MIN_PIXELS:
            return step
    return GRID_STEPS[-1]


def _line_distance(point, first, second):
    """点到过 first、second 的整条直线的距离。"""
    span = _distance(first, second)
    if span == 0:
        return _distance(point, first)
    return abs((second[0] - first[0]) * (point[1] - first[1]) - (second[1] - first[1]) * (point[0] - first[0])) / span


def _degrees(first, second):
    return math.degrees(math.atan2(second[1] - first[1], second[0] - first[0]))


def handles(shape):
    """可以拖的控制点 → [(名称, (x, y))...]。"""
    kind = shape['type']
    if kind == 'rect':
        return [(f'corner{index}', point) for index, point in enumerate(geom.vertices(shape))]
    if kind in ('polygon', 'spline'):
        return [(f'vertex{index}', tuple(point)) for index, point in enumerate(shape['points'])]
    if kind == 'line':
        return [('p1', (shape['x1'], shape['y1'])), ('p2', (shape['x2'], shape['y2']))]
    if kind in ('point', 'text'):
        return [('at', (shape['x'], shape['y']))]
    centre = (shape.get('cx', 0.0), shape.get('cy', 0.0))
    if kind == 'circle':
        return [('center', centre), ('rim', (centre[0] + shape['r'], centre[1]))]
    if kind == 'arc':
        prim = geom.prims(shape)[0]
        start, end = geom.prim_ends(prim)
        middle = (prim[3] + prim[4]) / 2
        return [('center', centre), ('start', start), ('end', end),
                ('rim', (centre[0] + shape['r'] * math.cos(middle), centre[1] + shape['r'] * math.sin(middle)))]
    if kind == 'ngon':
        return [('center', centre), ('vertex', geom.vertices(shape)[0])]
    if kind == 'ellipse':
        turn = math.radians(shape.get('angle', 0.0))
        return [('center', centre),
                ('major', (centre[0] + shape['rx'] * math.cos(turn), centre[1] + shape['rx'] * math.sin(turn))),
                ('minor', (centre[0] - shape['ry'] * math.sin(turn), centre[1] + shape['ry'] * math.cos(turn)))]
    if kind == 'arcslot':
        return [('center', centre)]
    if kind == 'equation':
        return [('at', geom.anchor(shape))]
    if kind == 'slot':
        first, second = (shape['x1'], shape['y1']), (shape['x2'], shape['y2'])
        span = _distance(first, second) or 1.0
        side = (-(second[1] - first[1]) / span * shape['w'] / 2, (second[0] - first[0]) / span * shape['w'] / 2)
        return [('p1', first), ('p2', second),
                ('width', ((first[0] + second[0]) / 2 + side[0], (first[1] + second[1]) / 2 + side[1]))]
    return []


def _dashes(line, dash, gap):
    """折线 → 一段段虚线 [(起, 止)...]。"""
    pieces, period, travelled = [], dash + gap, 0.0
    if period <= 0:
        return list(zip(line, line[1:]))
    for a, b in zip(line, line[1:]):
        span = _distance(a, b)
        position = 0.0
        while span > 0 and position < span - 1e-12:
            phase = (travelled + position) % period
            run = min((dash - phase) if phase < dash else (period - phase), span - position)
            if phase < dash:
                pieces.append(((a[0] + (b[0] - a[0]) * position / span, a[1] + (b[1] - a[1]) * position / span),
                               (a[0] + (b[0] - a[0]) * (position + run) / span, a[1] + (b[1] - a[1]) * (position + run) / span)))
            position += max(run, 1e-9)
        travelled += span
    return pieces


def describe(shape):
    """图形的尺寸文字 (画的时候跟在光标旁边)。"""
    kind = shape['type']
    if kind == 'rect':
        return f'{shape["w"]:.4g} × {shape["h"]:.4g}'
    if kind == 'circle':
        return f'R {shape["r"]:.4g}　Ø {shape["r"] * 2:.4g}'
    if kind == 'line':
        first, second = (shape['x1'], shape['y1']), (shape['x2'], shape['y2'])
        return f'{_distance(first, second):.4g}　{_degrees(first, second) % 360:.4g}°'
    if kind == 'arc':
        return f'R {shape["r"]:.4g}　{(shape["a1"] - shape["a0"]) % 360 or 360:.4g}°'
    if kind == 'slot':
        return f'{_distance((shape["x1"], shape["y1"]), (shape["x2"], shape["y2"])):.4g} × {shape["w"]:.4g}'
    if kind == 'ngon':
        return f'{int(shape.get("sides", 6))} 边　R {shape["r"]:.4g}'
    if kind == 'arcslot':
        return f'R {shape["r"]:.4g}　宽 {shape["w"]:.4g}'
    if kind == 'equation':
        return 'y = ' + str(shape.get('fy', '')) if shape.get('mode', 'explicit') == 'explicit' else '参数方程'
    if kind == 'ellipse':
        return f'{shape["rx"] * 2:.4g} × {shape["ry"] * 2:.4g}'
    if kind == 'text':
        return f'字高 {shape.get("height", 10):.4g}'
    if kind == 'point':
        return f'{shape["x"]:.4g}, {shape["y"]:.4g}'
    return f'{len(shape["points"])} 个点'


class SketchEditor:
    def __init__(self, plane='XY', offset=0.0, shapes=(), feature=None, name=''):
        self.plane, self.offset = plane, float(offset)
        self.plane_ref = None           # 画在基准面特征上时是它的 id (这时 plane 是算好的坐标系)
        self.shapes = copy.deepcopy(list(shapes))
        self.feature = feature          # 正在编辑的草图特征 id; None = 新草图
        self.name = name
        self.tool = 'select' if self.shapes else 'rect'
        self.selection = []             # 选中的图形序号
        self.hover = None               # 光标下的图形序号
        self.draft = None               # 正在画的: {'points': [已经点下的点...], 'cursor': (x, y), ...}
        self.cursor = None              # 捕捉后的光标位置
        self.snapped = False            # 光标是不是吸在了某个点上 (画个记号提示用户)
        self.snap_kind = ''             # 吸在了哪种点上 (SNAP_NAMES 的键)
        self.snap_only = None           # 快速捕捉: 下一次点击只吸这一种点
        self.snaps = set(ALL_SNAPS)     # 开着的捕捉 (ALL_SNAPS 里的键)
        self.options = {'radius': 5.0, 'sides': 6}      # 工具的参数: 圆角半径、多边形边数
        self.operation = None           # 开着面板的操作: {'kind': 'pattern' | 'repair', ...}
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

    # ---- 捕捉 ----
    def snap(self, point, pixel, skip=(), loose=True):
        """光标位置 → 捕捉后的位置。先吸特征点 (端点、中点、中心点、象限点、交叉点) 和原点, 再吸到线上, 再和已有的点
        对齐成水平 / 竖直, 最后吸格子 — 每一种都可以单独关掉 (self.snaps)。
        skip: 不参与的图形序号 (正在拖的那些); loose=False 时只吸特征点和格子 (拖动图形时用)。"""
        skipped = {skip} if isinstance(skip, int) else set(skip or ())
        only = self.snap_only
        on = {only} if only else self.snaps
        reach = (QUICK_PIXELS if only else SNAP_PIXELS) * pixel
        others = [shape for index, shape in enumerate(self.shapes) if index not in skipped]
        candidates = [('origin', (0.0, 0.0))] if 'end' in on and not only else []
        for shape in others:
            candidates += [item for item in geom.key_points(shape) if item[0] in on]
        if self.draft and self.tool in SPLINE_TOOLS and len(self.draft['points']) >= 3 and 'end' in on:
            candidates.append(('end', self.draft['points'][0]))
        close = [shape for shape in others if shape['type'] not in ('point', 'text') and geom.hit(shape, point, reach)] \
            if loose and ('int' in on or 'near' in on) else []
        if 'int' in on:
            for first in range(len(close)):
                for second in range(first + 1, len(close)):
                    for a in geom.prims(close[first]):
                        for b in geom.prims(close[second]):
                            candidates += [('int', crossing) for crossing in geom.intersections(a, b)]
        if candidates:
            # 两种点落在同一个位置 (比如交点正好在中点上) 时, 报更 "硬" 的那一种
            kind, best = min(candidates, key=lambda item: (round(_distance(item[1], point), 7), SNAP_ORDER.index(item[0])))
            if _distance(best, point) <= reach:
                self.snapped, self.snap_kind = True, kind
                return float(best[0]), float(best[1])
        if close and 'near' in on:
            gap, spot = min((geom.nearest(shape, point) for shape in close), key=lambda item: item[0])
            if gap <= (reach if only else HIT_PIXELS * pixel):
                self.snapped, self.snap_kind = True, 'near'
                return float(spot[0]), float(spot[1])
        self.snapped, self.snap_kind = False, ''
        step = grid_step(pixel)
        x, y = (round(point[0] / step) * step, round(point[1] / step) * step) if 'grid' in on else (float(point[0]), float(point[1]))
        if 'hv' in on and loose and not only:
            # 和已有的点对齐成水平 / 竖直: 只改对齐的那个坐标, 另一个坐标照常走格子。不算 "吸在点上": 半径这类长度还是按格子取整。
            # 正在画的这一串自己的点 (上一个点、起点) 优先; 别的图形只看端点和中心点, 而且要比格子更近才让它赢 —
            # 不然光标明明压在格子上, 却被远处某个点拉走一点点
            own = [self.draft['points'][-1], self.draft['points'][0]] if self.draft and self.draft.get('points') else []
            far = [(0.0, 0.0)] + [spot for shape in others for kind, spot in geom.key_points(shape) if kind in ('end', 'center')]
            tolerance, landed = ALIGN_PIXELS * pixel, [x, y]
            for axis in (0, 1):
                raw = point[axis]
                best = min((spot[axis] for spot in own), key=lambda value: abs(value - raw), default=None)
                if best is None or abs(best - raw) > tolerance:
                    best = min((spot[axis] for spot in far), key=lambda value: abs(value - raw), default=None)
                    if best is None or abs(best - raw) > tolerance or ('grid' in on and abs(best - raw) >= abs(landed[axis] - raw)):
                        continue
                if abs(best - landed[axis]) > 1e-12:
                    landed[axis], self.snap_kind = float(best), 'hv'
            x, y = landed
        return x, y

    def _round(self, value):
        """一个长度: 光标吸在某个点上就用原值 (过那个点); 否则取整到捕捉格子 — 用户要的是 5 而不是 4.757。"""
        if self.snapped:
            return value
        step = grid_step(self._pixel)
        return round(value / step) * step

    def _radius(self, centre, pixel=None):
        return _distance(centre, self.cursor) if self.snapped else self._round(_distance(centre, self._raw))

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
        self.operation, self._reference_hover = None, None

    def _try(self, action):
        """做一个可能不成立的修改 (剪裁、圆角…); 不成立时把原因留在 message 里。"""
        try:
            self.shapes = action()
            self.selection, self.hover = [], None
        except ValueError as error:
            self.message = str(error)

    # ---- 鼠标 ----
    def press(self, point, pixel, additive=False):
        self._press = point
        self._raw, self._pixel = point, pixel
        tool = self.tool
        if tool == 'select':
            self._press_select(point, pixel, additive)
            return
        if tool in ('trim', 'extend'):
            index = self._shape_at(point, pixel)
            if index is not None:
                self._try(lambda: (geom.trim if tool == 'trim' else geom.extend)(self.shapes, index, point))
            return
        if tool == 'dimension':
            self._press_dimension(self._shape_at(point, pixel))
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
            self._move_drag(point, pixel)
            return
        if self._box is not None:
            self._box[1] = point
            return
        tool = self.tool
        if tool in ('select', 'trim', 'extend', 'dimension', 'fillet', 'convert') or (tool == 'offset' and self.draft is None):
            self.cursor, self.snapped, self.snap_kind = None, False, ''
            self.hover = self._shape_at(point, pixel) if tool != 'convert' else None
            self._reference_hover = self._reference_at(point, pixel) if tool == 'convert' else None
            if tool == 'fillet':
                self.cursor = geom.corner_near(self.shapes, point, SNAP_PIXELS * 2 * pixel)
                self.snapped = self.cursor is not None
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
        if self._drag is not None:
            self._drag = None
            return
        if self._box is not None:
            (x0, y0), (x1, y1) = self._box[0], point        # 用松开的位置: 最后一段移动不一定单独送到过
            self._box = None
            if max(abs(x1 - x0), abs(y1 - y0)) > DRAG_PIXELS * pixel:
                low, high = (min(x0, x1), min(y0, y1)), (max(x0, x1), max(y0, y1))
                self.selection = [index for index, shape in enumerate(self.shapes)
                                  if all(low[0] <= x <= high[0] and low[1] <= y <= high[1]
                                         for line in self._lines(shape) for x, y in line)]
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
            self.selection = geom.chain_of(self.shapes, self.hover)

    def key(self, name):
        """→ 这个按键有没有被草图用掉。"""
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
        if name == 'delete' and self.selection:
            self.shapes = [shape for index, shape in enumerate(self.shapes) if index not in set(self.selection)]
            self.selection, self.hover = [], None
            return True
        return False

    # ---- 完成一个图形 ----
    def _add(self, shape):
        self.shapes.append(shape)
        self.selection = [len(self.shapes) - 1]

    def _commit(self, last):
        tool, points = self.tool, self.draft['points'] + [last]
        self._track_sweep()
        made = self._preview_shapes()
        chosen = list(self.selection)
        self.draft = None
        if tool == 'mirror':
            copies = made[:-1]                              # 最后一条是镜向轴
            self.shapes += copies
            self.selection = list(range(len(self.shapes) - len(copies), len(self.shapes)))
            self.tool = 'select'
        elif tool == 'move':
            for index, shape in zip(chosen, made):
                self.shapes[index] = shape
            self.tool = 'select'
        elif made and len(points) == STEPS[tool]:
            self._add(made[0])

    def _commit_spline(self, closed):
        points = self.draft['points']
        self.draft = None
        if self.tool == 'sspline' and len(points) > geom.STYLE_POINTS:
            self.message = f'样式样条最多 {geom.STYLE_POINTS} 个控制点，多出来的没有用上'
            points = points[:geom.STYLE_POINTS]
        if len(points) >= (3 if closed else 2):
            self._add({'type': 'spline', 'points': [[x, y] for x, y in points], 'closed': closed,
                       **({'style': True} if self.tool == 'sspline' else {})})

    def _track_sweep(self):
        """画圆弧时记着光标绕圆心转过了多少: 往哪边转弧就往哪边画, 转过半圈也不会突然翻到另一边。"""
        draft = self.draft
        if self.tool not in ('arc', 'caslot') or draft is None or len(draft['points']) != 2:
            return
        centre, start = draft['points']
        if _distance(centre, draft['cursor']) < 1e-9:
            return
        raw = math.atan2(draft['cursor'][1] - centre[1], draft['cursor'][0] - centre[0]) \
            - math.atan2(start[1] - centre[1], start[0] - centre[0])
        best = min((raw + turn * geom.TAU for turn in (-2, -1, 0, 1, 2)), key=lambda value: abs(value - draft['sweep']))
        draft['sweep'] = max(-geom.TAU, min(geom.TAU, best))

    def _swept_arc(self, centre, start):
        """圆心 + 起点 + 记下来的转角 → 圆弧图形。"""
        begin, sweep = _degrees(centre, start), math.degrees(self.draft['sweep']) if self.draft else 0.0
        if abs(sweep) < 1e-6:
            return None
        low, high = (begin, begin + sweep) if sweep > 0 else (begin + sweep, begin)
        return {'type': 'arc', 'cx': centre[0], 'cy': centre[1], 'r': _distance(centre, start), 'a0': low, 'a1': high}

    def _build(self, tool, points):
        """已经点下的点 + 光标 → 现在这个图形的样子; 点得还不够时给一条示意线。"""
        first, last = points[0], points[-1]
        if tool in ('rect', 'crect'):
            width, height = abs(last[0] - first[0]), abs(last[1] - first[1])
            if width < 1e-9 or height < 1e-9:
                return None
            if tool == 'crect':                         # 中心矩形: 第一个点是中心
                return {'type': 'rect', 'cx': first[0], 'cy': first[1], 'w': width * 2, 'h': height * 2}
            return {'type': 'rect', 'cx': (first[0] + last[0]) / 2, 'cy': (first[1] + last[1]) / 2, 'w': width, 'h': height}
        if tool == 'midline':
            return self._line((2 * first[0] - last[0], 2 * first[1] - last[1]), last) if _distance(first, last) > 1e-9 else None
        if tool == 'circle':
            radius = self._radius(first)
            return {'type': 'circle', 'cx': first[0], 'cy': first[1], 'r': radius} if radius > 1e-9 else None
        if tool == 'ngon':
            radius = self._radius(first)
            if radius <= 1e-9:
                return None
            return {'type': 'ngon', 'cx': first[0], 'cy': first[1], 'r': radius, 'sides': int(self.options['sides']),
                    'angle': _degrees(first, last) if _distance(first, last) > 1e-9 else 0.0}
        second = points[1]
        if _distance(first, second) < 1e-9:
            return None
        if len(points) == 2:
            return self._line(first, second)
        third = points[2]
        if tool == 'circle3':
            found = geom.circle3(first, second, third)
            return {'type': 'circle', 'cx': found[0][0], 'cy': found[0][1], 'r': found[1]} if found else None
        if tool == 'pgram':
            corners = [first, second, third, (first[0] + third[0] - second[0], first[1] + third[1] - second[1])]
            return {'type': 'polygon', 'points': [list(corner) for corner in corners]} if abs(geom.signed_area(corners)) > 1e-9 else None
        if tool in ('rect3', 'crect3'):
            ux, uy = (second[0] - first[0]) / _distance(first, second), (second[1] - first[1]) / _distance(first, second)
            rise = (third[0] - first[0]) * -uy + (third[1] - first[1]) * ux      # 第三个点离第一条线多远 (带方向)
            if abs(rise) < 1e-9:
                return None
            side = (-uy * rise, ux * rise)
            if tool == 'rect3':
                corners = [first, second, (second[0] + side[0], second[1] + side[1]), (first[0] + side[0], first[1] + side[1])]
            else:                                       # 第一个点是中心, 第二个点是一条边的中点
                back = (2 * first[0] - second[0], 2 * first[1] - second[1])
                corners = [(second[0] + side[0], second[1] + side[1]), (second[0] - side[0], second[1] - side[1]),
                           (back[0] - side[0], back[1] - side[1]), (back[0] + side[0], back[1] + side[1])]
            return {'type': 'polygon', 'points': [list(corner) for corner in corners]}
        if tool == 'arc':
            return self._swept_arc(first, second)
        if tool in ('aslot3', 'caslot'):
            spine = geom.arc3(first, second, third) if tool == 'aslot3' else self._swept_arc(first, second)
            if spine is None or len(points) == 3:
                return spine
            centre = (spine['cx'], spine['cy'])
            width = self._round(2 * abs(_distance(centre, last if self.snapped else self._raw) - spine['r']))
            if not 1e-9 < width < 2 * spine['r']:
                return None
            return dict(spine, type='arcslot', w=width)
        side = _line_distance(last if self.snapped else self._raw, first, second)
        if tool in ('slot', 'cslot'):
            width = self._round(side * 2)
            if width <= 1e-9:
                return None
            start = first if tool == 'slot' else (2 * first[0] - second[0], 2 * first[1] - second[1])
            return {'type': 'slot', 'x1': start[0], 'y1': start[1], 'x2': second[0], 'y2': second[1], 'w': width}
        if tool == 'ellipse':
            minor = self._round(side)
            if minor <= 1e-9:
                return None
            return {'type': 'ellipse', 'cx': first[0], 'cy': first[1], 'rx': _distance(first, second), 'ry': minor,
                    'angle': _degrees(first, second)}
        return None

    def _preview_shapes(self):
        """正在画 / 正在做的操作现在会得到什么 → 图形列表 (还没定下来)。"""
        operation = self.operation
        if operation and operation['kind'] == 'pattern':
            return [geom.moved(shape, operation['dx'] * column, operation['dy'] * row)
                    for row in range(int(operation['ny'])) for column in range(int(operation['nx']))
                    if row or column for shape in self._chosen()]
        if operation and operation['kind'] == 'cpattern':
            count, total = int(operation['count']), float(operation['angle'])
            step = total / count if abs(abs(total) - 360.0) < 1e-9 else total / max(count - 1, 1)
            return [geom.rotated(shape, (operation['cx'], operation['cy']), step * turn)
                    for turn in range(1, count) for shape in self._chosen()]
        if operation and operation['kind'] == 'dimension' and operation['b'] is not None:
            pair = self._pair(operation['a'], operation['b'])
            return [self._line(*pair)] if pair and _distance(*pair) > 1e-9 else []
        draft, tool = self.draft, self.tool
        if draft is None:
            return []
        points = draft['points'] + [draft['cursor']]
        if tool in CHAIN_TOOLS:
            return [self._line(points[0], points[1], tool == 'centerline')] if _distance(points[0], points[1]) > 1e-9 else []
        if tool in SPLINE_TOOLS:
            if _distance(points[-1], points[-2]) <= 1e-9:
                points = points[:-1]
            points = points[:geom.STYLE_POINTS] if tool == 'sspline' else points
            return [{'type': 'spline', 'points': [list(p) for p in points], 'closed': False,
                     **({'style': True} if tool == 'sspline' else {})}] if len(points) >= 2 else []
        if tool == 'offset':
            source = self.shapes[draft['source']]
            gap = geom.signed_distance(source, draft['cursor'])
            step = grid_step(self._pixel)
            made = geom.offset(source, round(gap / step) * step)
            return [made] if made is not None and round(gap / step) != 0 else []
        if tool == 'mirror':
            if _distance(points[0], points[1]) <= 1e-9:
                return []
            return [geom.mirrored(shape, points[0], points[1]) for shape in self._chosen()] + [self._line(points[0], points[1])]
        if tool == 'move':
            return [geom.moved(shape, points[1][0] - points[0][0], points[1][1] - points[0][1]) for shape in self._chosen()]
        shape = self._build(tool, points)
        return [shape] if shape is not None else []

    @staticmethod
    def _line(first, second, construction=False):
        line = {'type': 'line', 'x1': first[0], 'y1': first[1], 'x2': second[0], 'y2': second[1]}
        if construction:
            line['construction'] = True
        return line

    # ---- 智能尺寸 ----
    def _press_dimension(self, index):
        if index is None:
            return
        operation = self.operation
        if operation and operation['kind'] == 'dimension' and operation['b'] is None and index != operation['a']:
            pair = self._pair(operation['a'], index)        # 点了第二个图形: 标它们之间的距离
            if pair is None or _distance(*pair) < 1e-9:
                self.message = '这两个图形的参考点重合，标不了距离'
                return
            operation.update(b=index, distance=round(_distance(*pair), 6))
            self.selection = [operation['a'], index]
            return
        self.selection = [index]
        self.operation = {'kind': 'dimension', 'a': index, 'b': None}

    def _pair(self, first, second):
        """两个图形之间量距离的两个点: 圆和点用圆心 / 点本身, 直线用另一个图形在它上面的垂足。"""
        if max(first, second) >= len(self.shapes):
            return None
        a, b = self.shapes[first], self.shapes[second]

        def spot(shape):
            if shape['type'] == 'line':
                return (shape['x1'] + shape['x2']) / 2, (shape['y1'] + shape['y2']) / 2
            return geom.anchor(shape)

        def foot(line, point):
            return geom._nearest_on_line(point, (line['x1'], line['y1']), (line['x2'], line['y2']))

        if a['type'] == 'line':
            return foot(a, spot(b)), spot(b)
        if b['type'] == 'line':
            return spot(a), foot(b, spot(a))
        return spot(a), spot(b)

    def preview(self):
        """正在画的图形现在的样子 → 图形字典或 None。"""
        made = self._preview_shapes() if self.draft is not None else []
        return made[0] if made else None

    # ---- 选择和拖动 ----
    def _lines(self, shape):
        """图形 → 要画的折线。文本是字的轮廓 (界面给; 没有就画个占位框)。"""
        if shape['type'] == 'point':
            return []
        if shape['type'] != 'text':
            return geom.polylines(shape)
        if self.outliner is not None:
            return self.outliner(shape)
        height = float(shape.get('height', 10.0))
        wide = height * 0.9 * max(len(str(shape.get('text', ''))), 1)
        turn = math.radians(shape.get('angle', 0.0))
        cos, sin = math.cos(turn), math.sin(turn)
        box = [(0, 0), (wide, 0), (wide, height), (0, height), (0, 0)]
        return [[(shape['x'] + x * cos - y * sin, shape['y'] + x * sin + y * cos) for x, y in box]]

    def _hit(self, shape, point, tolerance):
        if shape['type'] != 'text':
            return geom.hit(shape, point, tolerance)
        spots = [spot for line in self._lines(shape) for spot in line] or [(shape['x'], shape['y'])]
        return min(x for x, _ in spots) - tolerance <= point[0] <= max(x for x, _ in spots) + tolerance \
            and min(y for _, y in spots) - tolerance <= point[1] <= max(y for _, y in spots) + tolerance

    def _shape_at(self, point, pixel):
        tolerance = HIT_PIXELS * pixel
        for index in self.selection:
            if self._hit(self.shapes[index], point, tolerance):
                return index
        for index in range(len(self.shapes) - 1, -1, -1):
            if self._hit(self.shapes[index], point, tolerance * (1.6 if self.shapes[index]['type'] == 'point' else 1.0)):
                return index
        return None

    def _reference_at(self, point, pixel):
        best = min(range(len(self.references)), key=lambda index: geom.nearest(self.references[index], point)[0], default=None)
        if best is not None and geom.nearest(self.references[best], point)[0] <= HIT_PIXELS * pixel:
            return best
        return None

    def _press_select(self, point, pixel, additive):
        if self.selected is not None and not additive:
            for name, position in handles(self.shapes[self.selected]):
                if _distance(position, point) <= SNAP_PIXELS * pixel:
                    self._drag = {'handle': name, 'origin': point, 'base': self.selected,
                                  'shapes': {self.selected: copy.deepcopy(self.shapes[self.selected])}}
                    return
        index = self._shape_at(point, pixel)
        if additive:
            if index is not None:
                self.selection = [item for item in self.selection if item != index] if index in self.selection \
                    else self.selection + [index]
            return
        if index is None:
            self.selection, self._box = [], [point, point]
            return
        if index not in self.selection:
            self.selection = [index]
        self._drag = {'handle': None, 'origin': point, 'base': index,
                      'shapes': {item: copy.deepcopy(self.shapes[item]) for item in self.selection}}

    def _move_drag(self, point, pixel):
        drag, handle = self._drag, self._drag['handle']
        before = drag['shapes'][drag['base']]
        if handle is None:
            # 整体移动: 让按住的那个图形的基准点落在捕捉位置上, 选中的其余图形跟着平移
            base = geom.anchor(before)
            wanted = (base[0] + point[0] - drag['origin'][0], base[1] + point[1] - drag['origin'][1])
            target = self.snap(wanted, pixel, skip=self.selection, loose=False)
            for index, original in drag['shapes'].items():
                self.shapes[index] = geom.moved(original, target[0] - base[0], target[1] - base[1])
            self.cursor = target
            return
        shape = self.shapes[drag['base']]
        target = self.snap(point, pixel, skip=drag['base'], loose=False)
        self.cursor = target
        kind = shape['type']
        centre = (before.get('cx', 0.0), before.get('cy', 0.0))
        if handle.startswith('corner'):
            opposite = geom.vertices(before)[(int(handle[6:]) + 2) % 4]
            width, height = abs(target[0] - opposite[0]), abs(target[1] - opposite[1])
            if width > 1e-9 and height > 1e-9:
                shape.update(cx=(target[0] + opposite[0]) / 2, cy=(target[1] + opposite[1]) / 2, w=width, h=height)
        elif handle == 'center':
            shape['cx'], shape['cy'] = target
        elif handle == 'rim':
            radius = self._radius(centre)
            if radius > 1e-9:
                shape['r'] = radius
        elif handle.startswith('vertex') and kind in ('polygon', 'spline'):
            shape['points'][int(handle[6:])] = [target[0], target[1]]
        elif handle == 'vertex':                            # 正多边形的顶点: 改大小和朝向
            radius = self._radius(centre)
            if radius > 1e-9:
                shape['r'], shape['angle'] = radius, _degrees(centre, target)
        elif handle in ('p1', 'p2'):
            other = (before['x2'], before['y2']) if handle == 'p1' else (before['x1'], before['y1'])
            if _distance(other, target) > 1e-9:
                shape['x' + handle[1]], shape['y' + handle[1]] = target
        elif handle == 'at':
            shape['x'], shape['y'] = target
        elif handle in ('start', 'end') and _distance(centre, target) > 1e-9:
            shape['a0' if handle == 'start' else 'a1'] = _degrees(centre, target)
        elif handle == 'major' and _distance(centre, target) > 1e-9:
            shape['rx'], shape['angle'] = _distance(centre, target), _degrees(centre, target)
        elif handle == 'minor' and self._round(_distance(centre, self._raw)) > 1e-9:
            shape['ry'] = self._round(_distance(centre, self._raw))
        elif handle == 'width':
            width = self._round(2 * _line_distance(self._raw, (before['x1'], before['y1']), (before['x2'], before['y2'])))
            if width > 1e-9:
                shape['w'] = width

    # ---- 带面板的操作 ----
    def start_pattern(self):
        if not self.selection:
            self.message = '先选中要阵列的图形（点选，Ctrl 加选，或拖方框框选）'
            return
        self.set_tool('select') if self.tool != 'select' else None
        self.operation = {'kind': 'pattern', 'nx': 2, 'dx': 20.0, 'ny': 1, 'dy': 20.0}

    def start_circular_pattern(self):
        if not self.selection:
            self.message = '先选中要阵列的图形（点选，Ctrl 加选，或拖方框框选）'
            return
        selection = self.selection
        self.set_tool('select')
        self.selection = selection
        self.operation = {'kind': 'cpattern', 'count': 6, 'angle': 360.0, 'cx': 0.0, 'cy': 0.0}

    def start_relation(self):
        options = geom.relations_for(self._chosen()) if self.selection else []
        if not options:
            self.message = '先选中要加关系的图形：一条或几条直线、两个圆、一条线和一个圆…（第一个选中的不动，其余的向它看齐）'
            return
        selection = self.selection
        self.set_tool('select')
        self.selection = selection
        self.operation = {'kind': 'relation', 'choice': options[0]}

    def start_repair(self):
        selection = self.selection
        self.set_tool('select')
        self.selection = selection
        self.issues = geom.diagnose(self.shapes)
        self.operation = {'kind': 'repair'}

    def apply_operation(self):
        operation, self.operation = self.operation, None
        if operation is None:
            return
        if operation['kind'] in ('pattern', 'cpattern'):
            self.operation = operation
            copies = self._preview_shapes()
            self.operation = None
            self.shapes += copies
        elif operation['kind'] == 'relation':
            chosen = list(self.selection)
            self._try(lambda: geom.relate(self.shapes, chosen, operation['choice']))
            self.selection = chosen if not self.message else self.selection
        elif operation['kind'] == 'dimension':
            if operation['b'] is not None:
                pair = self._pair(operation['a'], operation['b'])
                wanted = float(operation['distance'])
                if pair and _distance(*pair) > 1e-9 and wanted >= 0:
                    scale = (wanted - _distance(*pair)) / _distance(*pair)
                    self.shapes[operation['b']] = geom.moved(self.shapes[operation['b']], (pair[1][0] - pair[0][0]) * scale,
                                                             (pair[1][1] - pair[0][1]) * scale)
            self.selection = []
        elif operation['kind'] == 'repair':
            if any(issue['fixable'] for issue in self.issues):
                self.shapes, fixed = geom.repair(self.shapes)
                left = len(geom.diagnose(self.shapes))
                self.message = f'修了 {fixed} 处' + (f'，还有 {left} 处要自己改（见“修复草图”）' if left else '，草图没有问题了')
                self.selection, self.hover = [], None
            self.issues = []

    def cancel_operation(self):
        self.operation, self.issues = None, []

    # ---- 面板: 选中图形的精确尺寸、工具的参数、操作的参数 ----
    def panel(self):
        """现在该显示的面板 → {'title', 'fields', 'accept', 'cancel'} 或 None (不占地方)。"""
        operation = self.operation
        if operation and operation['kind'] == 'pattern':
            def count(key, label):
                return {'key': key, 'label': label, 'type': 'number', 'value': float(operation[key]), 'unit': '个'}

            def gap(key, label):
                return {'key': key, 'label': label, 'type': 'number', 'value': float(operation[key]), 'unit': 'mm'}
            return {'title': '线性草图阵列', 'accept': '确定', 'cancel': '取消',
                    'fields': [count('nx', 'X 方向数量'), gap('dx', 'X 方向间距'), count('ny', 'Y 方向数量'), gap('dy', 'Y 方向间距'),
                               {'key': 'hint', 'label': '', 'type': 'info', 'value': f'阵列选中的 {len(self.selection)} 个图形；数量包含原来的那个'}]}
        if operation and operation['kind'] == 'cpattern':
            def entry(key, label, unit):
                return {'key': key, 'label': label, 'type': 'number', 'value': float(operation[key]), 'unit': unit}
            return {'title': '圆周草图阵列', 'accept': '确定', 'cancel': '取消',
                    'fields': [entry('count', '数量', '个'), entry('angle', '总角度', '°'), entry('cx', '中心 X', 'mm'), entry('cy', '中心 Y', 'mm'),
                               {'key': 'hint', 'label': '', 'type': 'info',
                                'value': f'绕中心转着复制选中的 {len(self.selection)} 个图形；数量包含原来的那个，360° = 均布一圈'}]}
        if operation and operation['kind'] == 'relation':
            options = [{'value': key, 'label': geom.RELATIONS[key]} for key in geom.relations_for(self._chosen())]
            return {'title': '添加几何关系', 'accept': '添加', 'cancel': '取消',
                    'fields': [{'key': 'choice', 'label': '关系', 'type': 'choice', 'value': operation['choice'], 'options': options},
                               {'key': 'hint', 'label': '', 'type': 'info',
                                'value': '第一个选中的图形不动，其余的向它看齐。\n这是照关系摆一次：软件还没有约束求解，之后再拖动不会自动保持。'}]}
        if operation and operation['kind'] == 'dimension':
            if operation['b'] is not None:
                return {'title': '智能尺寸', 'accept': '确定', 'cancel': '取消',
                        'fields': [{'key': 'distance', 'label': '距离', 'type': 'number', 'value': float(operation['distance']), 'unit': 'mm'},
                                   {'key': 'hint', 'label': '', 'type': 'info', 'value': '确定后第二个图形沿这条连线移动到这个距离（改一次，不是保持住的约束）'}]}
            if operation['a'] < len(self.shapes) and self.selected == operation['a']:
                wanted = DIMENSIONS.get(self.shapes[operation['a']]['type'], ())
                rows = [field for field in self.fields() if field['key'] in wanted]
                tip = '改数字后图形立刻跟着变。再点另一个图形 = 标它们之间的距离。' if rows \
                    else '这种图形没有单个的主尺寸；再点另一个图形可以标它们之间的距离。'
                return {'title': '智能尺寸', 'accept': '好', 'cancel': '',
                        'fields': rows + [{'key': 'hint', 'label': '', 'type': 'info', 'value': tip}]}
        if operation and operation['kind'] == 'repair':
            if not self.issues:
                text = '没有发现问题：没有废线、重复的线和没接上的端点。'
            else:
                counts = {}
                for issue in self.issues:               # 同一种问题合成一行, 不然八个线头就是八行一样的字
                    counts[issue['text']] = counts.get(issue['text'], 0) + 1
                shown = [f'· {text}' + (f'　× {count}' if count > 1 else '') for text, count in counts.items()]
                text = f'发现 {len(self.issues)} 处（视图里用点标出来了）：\n' + '\n'.join(shown)
            fixable = any(issue['fixable'] for issue in self.issues)
            return {'title': '修复草图', 'accept': '修复' if fixable else '好', 'cancel': '关闭' if fixable else '',
                    'fields': [{'key': 'hint', 'label': '', 'type': 'info', 'value': text}]}
        if self.selected is not None:
            return {'title': geom.NAMES[self.shapes[self.selected]['type']], 'accept': '', 'cancel': '', 'fields': self.fields()}
        if self.tool == 'fillet':
            return {'title': '绘制圆角', 'accept': '', 'cancel': '',
                    'fields': [{'key': 'opt_radius', 'label': '圆角半径', 'type': 'number', 'value': float(self.options['radius']), 'unit': 'mm'}]}
        if self.tool == 'ngon':
            return {'title': '多边形', 'accept': '', 'cancel': '',
                    'fields': [{'key': 'opt_sides', 'label': '边数', 'type': 'number', 'value': float(self.options['sides']), 'unit': '边'}]}
        if len(self.selection) > 1:
            return {'title': f'选中了 {len(self.selection)} 个图形', 'accept': '', 'cancel': '',
                    'fields': [{'key': 'hint', 'label': '', 'type': 'info',
                                'value': '拖动可以一起移动；Delete 删除；草图页里的镜向、阵列、移动对它们生效。'}]}
        return None

    def fields(self):
        """选中图形的尺寸 → 面板字段 (和 forms.py 的格式一样)。"""
        rows = [{'key': 'offset', 'label': '基准面偏移', 'type': 'number', 'value': self.offset, 'unit': 'mm'}]
        if self.selected is None:
            text = '用上方的工具在视图里画图形；点选一个后可以在这里填精确尺寸。' if not self.shapes \
                else f'共 {len(self.shapes)} 个图形。点选一个可以改尺寸，拖动可以移动。'
            return rows + [{'key': 'hint', 'label': '', 'type': 'info', 'value': text}]
        shape = self.shapes[self.selected]
        kind = shape['type']

        def number(key, label, value, unit='mm'):
            return {'key': key, 'label': label, 'type': 'number', 'value': float(value), 'unit': unit}

        centre = [number('cx', '中心 X', shape.get('cx', 0.0)), number('cy', '中心 Y', shape.get('cy', 0.0))]
        if kind == 'rect':
            rows += [number('w', '宽度', shape['w']), number('h', '高度', shape['h'])] + centre
        elif kind == 'circle':
            rows += [number('d', '直径', shape['r'] * 2), number('cx', '圆心 X', shape.get('cx', 0.0)),
                     number('cy', '圆心 Y', shape.get('cy', 0.0))]
        elif kind == 'line':
            first, second = (shape['x1'], shape['y1']), (shape['x2'], shape['y2'])
            rows += [number('len', '长度', _distance(first, second)), number('dir', '角度', _degrees(first, second), '°'),
                     number('x1', '起点 X', first[0]), number('y1', '起点 Y', first[1]),
                     number('x2', '终点 X', second[0]), number('y2', '终点 Y', second[1])]
        elif kind == 'arc':
            rows += [number('r', '半径', shape['r']), number('a0', '起始角', shape['a0'], '°'), number('a1', '终止角', shape['a1'], '°'),
                     number('cx', '圆心 X', shape['cx']), number('cy', '圆心 Y', shape['cy'])]
        elif kind == 'slot':
            first, second = (shape['x1'], shape['y1']), (shape['x2'], shape['y2'])
            rows += [number('len', '圆心距', _distance(first, second)), number('w', '槽宽', shape['w']),
                     number('dir', '角度', _degrees(first, second), '°'),
                     number('x1', '圆心 1 X', first[0]), number('y1', '圆心 1 Y', first[1])]
        elif kind == 'arcslot':
            rows += [number('r', '中心线半径', shape['r']), number('w', '槽宽', shape['w']), number('a0', '起始角', shape['a0'], '°'),
                     number('a1', '终止角', shape['a1'], '°'), number('cx', '圆心 X', shape['cx']), number('cy', '圆心 Y', shape['cy'])]
        elif kind == 'equation':
            explicit = shape.get('mode', 'explicit') == 'explicit'
            rows += [{'key': 'mode', 'label': '类型', 'type': 'choice', 'value': shape.get('mode', 'explicit'),
                      'options': [{'value': 'explicit', 'label': '显性 y=f(x)'}, {'value': 'parametric', 'label': '参数 x(t), y(t)'}]}]
            if not explicit:
                rows.append({'key': 'fx', 'label': 'x(t) =', 'type': 'text', 'value': str(shape.get('fx', 't'))})
            rows += [{'key': 'fy', 'label': 'y =' if explicit else 'y(t) =', 'type': 'text', 'value': str(shape.get('fy', '0'))},
                     number('t0', '从 x =' if explicit else '从 t =', shape.get('t0', 0.0), ''),
                     number('t1', '到 x =' if explicit else '到 t =', shape.get('t1', 1.0), ''),
                     number('ox', '平移 X', shape.get('ox', 0.0)), number('oy', '平移 Y', shape.get('oy', 0.0))]
        elif kind == 'ngon':
            rows += [number('sides', '边数', shape.get('sides', 6), '边'), number('r', '外接圆半径', shape['r']),
                     number('angle', '转角', shape.get('angle', 0.0), '°')] + centre
        elif kind == 'ellipse':
            rows += [number('rx', '长半轴', shape['rx']), number('ry', '短半轴', shape['ry']),
                     number('angle', '转角', shape.get('angle', 0.0), '°')] + centre
        elif kind == 'point':
            rows += [number('x', 'X', shape['x']), number('y', 'Y', shape['y'])]
        elif kind == 'text':
            rows += [{'key': 'text', 'label': '文字', 'type': 'text', 'value': str(shape.get('text', ''))},
                     number('height', '字高', shape.get('height', 10.0))]
            if shape.get('path'):
                rows += [{'key': 'flip', 'label': '换一侧 / 反向', 'type': 'bool', 'value': bool(shape.get('flip'))},
                         {'key': 'hint', 'label': '', 'type': 'info', 'value': f'沿一条{geom.NAMES[shape["path"]["type"]]}排列'}]
            else:
                rows += [number('angle', '转角', shape.get('angle', 0.0), '°'),
                         number('x', '位置 X', shape['x']), number('y', '位置 Y', shape['y'])]
        else:
            if kind == 'spline':
                rows.append({'key': 'closed', 'label': '封闭', 'type': 'bool', 'value': bool(shape.get('closed'))})
            for index, (x, y) in enumerate(shape['points']):
                rows += [number(f'p{index}x', f'点 {index + 1} X', x), number(f'p{index}y', f'点 {index + 1} Y', y)]
        if kind not in ('point', 'text'):
            rows.append({'key': 'construction', 'label': '构造线（只作参考，不参与拉伸）', 'type': 'bool', 'value': bool(shape.get('construction'))})
        return rows

    def set_field(self, key, value):
        operation = self.operation
        if operation and key == 'choice' and 'choice' in operation:
            operation['choice'] = str(value)
            return
        if operation and key in operation:
            try:
                value = float(value)
            except (TypeError, ValueError):
                return
            if key in ('nx', 'ny', 'count'):
                if 1 <= round(value) <= 100:
                    operation[key] = int(round(value))
            elif math.isfinite(value):
                operation[key] = value
            return
        shape = self.shapes[self.selected] if self.selected is not None else None
        if key == 'text' and shape is not None and shape['type'] == 'text':
            shape['text'] = str(value)
            return
        if key in ('flip', 'closed', 'construction') and shape is not None:
            if key == 'closed' and value and len(shape['points']) < 3:
                self.message = '封闭的样条至少要 3 个点'
                return
            shape[key] = bool(value)
            return
        if key in ('fx', 'fy', 'mode') and shape is not None and shape['type'] == 'equation':
            trial = dict(shape, **{key: str(value)})
            try:
                geom.equation_points(trial)             # 式子写错了就不收, 把原因告诉用户
            except ValueError as error:
                self.message = str(error)
                return
            shape[key] = str(value)
            return
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(value):
            return
        if key == 'offset':
            self.offset = value
        elif key == 'opt_radius':
            if value > 0:
                self.options['radius'] = value
        elif key == 'opt_sides':
            if 3 <= round(value) <= 100:
                self.options['sides'] = int(round(value))
        elif shape is None:
            return
        elif key in ('w', 'h', 'r', 'rx', 'ry', 'height'):
            if value > 0:
                shape[key] = value
        elif key == 'd':
            if value > 0:
                shape['r'] = value / 2
        elif key == 'sides':
            if 3 <= round(value) <= 100:
                shape['sides'] = int(round(value))
        elif key in ('len', 'dir') and shape['type'] in ('line', 'slot'):
            first, second = (shape['x1'], shape['y1']), (shape['x2'], shape['y2'])
            span = value if key == 'len' else _distance(first, second)
            turn = math.radians(value if key == 'dir' else _degrees(first, second))
            if span > 0:
                shape['x2'], shape['y2'] = first[0] + span * math.cos(turn), first[1] + span * math.sin(turn)
        elif key.startswith('p') and key[-1] in 'xy' and key[1:-1].isdigit() and 'points' in shape:
            shape['points'][int(key[1:-1])][0 if key.endswith('x') else 1] = value
        elif key in ('t0', 't1') and shape['type'] == 'equation':
            if abs(value - float(shape['t1' if key == 't0' else 't0'])) > 1e-12:
                shape[key] = value
        elif key in ('cx', 'cy', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'a0', 'a1', 'angle', 'ox', 'oy') and (key in shape or key in ('cx', 'cy', 'angle')):
            shape[key] = value

    # ---- 结果 ----
    def params(self):
        return {'plane': self.plane_ref or self.plane, 'offset': self.offset, 'shapes': copy.deepcopy(self.shapes)}

    # ---- 给视图画的东西 ----
    def drawing(self):
        """→ (线段 [((x0,y0),(x1,y1), 状态)...], 点 [((x,y), 状态)...], 标注 [(文字, (x,y))...])。
        状态: 0 普通 / 1 悬停 / 2 选中 / 3 正在画。"""
        lines, points, labels = [], [], []

        def stroke(shape, state):
            for line in self._lines(shape):
                if shape.get('construction'):           # 构造线画成虚线
                    lines.extend((a, b, state) for a, b in _dashes(line, 7.0 * self._pixel, 4.0 * self._pixel))
                else:
                    lines.extend((a, b, state) for a, b in zip(line, line[1:]))
            if shape['type'] == 'point':
                points.append(((shape['x'], shape['y']), state))

        chosen = set(self.selection)
        for index, shape in enumerate(self.shapes):
            stroke(shape, 2 if index in chosen else 1 if index == self.hover else 0)
        if self.selected is not None:
            shape = self.shapes[self.selected]
            points += [(position, 2) for _, position in handles(shape)]
            if shape['type'] not in ('text', 'point'):      # 这两种的标注会正好压在它自己上面
                labels.append((describe(shape), self._label_anchor(shape)))
        if self.tool == 'dimension':                     # 智能尺寸: 每个图形的尺寸都标出来, 点哪个改哪个
            labels += [(describe(shape), self._label_anchor(shape)) for index, shape in enumerate(self.shapes)
                       if shape['type'] in DIMENSIONS and index != self.selected]
            pair = self._pair(self.operation['a'], self.operation['b']) \
                if self.operation and self.operation['kind'] == 'dimension' and self.operation['b'] is not None else None
            if pair:
                labels.append((f'{_distance(*pair):.4g}', ((pair[0][0] + pair[1][0]) / 2, (pair[0][1] + pair[1][1]) / 2)))
        if self.selected is not None and self.shapes[self.selected].get('style'):
            poles = [tuple(point) for point in self.shapes[self.selected]['points']]       # 样式样条: 把控制多边形画出来
            lines += [(a, b, 1) for a, b in _dashes(poles, 4.0 * self._pixel, 4.0 * self._pixel)]
        if self.tool == 'convert':
            for index, shape in enumerate(self.references):
                stroke(shape, 3 if index == self._reference_hover else 1)
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
        if self.cursor is not None and self.tool != 'select':
            points.append((self.cursor, 1 if self.snapped else 3))
            if self.snap_kind and not (made and draft is not None):
                labels.append((SNAP_NAMES[self.snap_kind], self.cursor))
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
