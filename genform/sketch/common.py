"""草图编辑器共用的常量和小工具: 容差、工具表、捕捉名字、控制点、虚线、图形的说明文字。"""
from __future__ import annotations

import math

from ..sketchgeom import dist as _distance
from .. import sketchgeom as geom


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


def _rect_from(corners):
    """横平竖直的四个角 → 矩形的中心和宽高。"""
    xs, ys = [x for x, _ in corners], [y for _, y in corners]
    return {'cx': (min(xs) + max(xs)) / 2, 'cy': (min(ys) + max(ys)) / 2, 'w': max(xs) - min(xs), 'h': max(ys) - min(ys)}


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


def _close(first, second, tolerance=1e-6):
    """两份图形参数是不是一样 (数字允许差一点点)。"""
    if isinstance(first, dict) and isinstance(second, dict):
        return first.keys() == second.keys() and all(_close(first[key], second[key], tolerance) for key in first)
    if isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)):
        return len(first) == len(second) and all(_close(a, b, tolerance) for a, b in zip(first, second))
    if isinstance(first, bool) or isinstance(second, bool) or not isinstance(first, (int, float)) or not isinstance(second, (int, float)):
        return first == second
    return abs(first - second) <= tolerance


FLAGS = {'fixed': '固定', 'construction': '构造线', 'infinite': '无限长度'}


TOOL_TITLES = {'line': '直线', 'centerline': '中心线', 'midline': '中点线', 'rect': '边角矩形', 'crect': '中心矩形',
               'rect3': '3 点边角矩形', 'crect3': '3 点中心矩形', 'pgram': '平行四边形', 'circle': '圆', 'circle3': '周边圆',
               'arc': '圆心/起/终点画弧', 'slot': '直槽口', 'cslot': '中心点直槽口', 'aslot3': '三点圆弧槽口', 'caslot': '中心点圆弧槽口',
               'ngon': '多边形', 'ellipse': '椭圆', 'spline': '样条曲线', 'sspline': '样式样条曲线', 'equation': '方程式驱动的曲线',
               'point': '点', 'text': '文本', 'dimension': '智能尺寸', 'fillet': '绘制圆角', 'trim': '剪裁实体', 'extend': '延伸实体',
               'offset': '等距实体', 'mirror': '镜向实体', 'move': '移动实体', 'convert': '转换实体引用'}   # 属性管理器里工具页的标题


MARK_NAMES = {'horizontal': '水平', 'vertical': '竖直', 'coincident': '重合', 'tangent': '相切'}     # 几何关系小图标的名字


PROPERTY_TITLES = {'line': '线条属性', 'circle': '圆属性', 'arc': '圆弧属性', 'point': '点属性', 'rect': '矩形属性', 'text': '文本属性'}


FAR = 1.0e4                 # "无限长" 的构造线画到这么远 (mm)


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
