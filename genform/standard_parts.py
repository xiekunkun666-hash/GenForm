# -*- coding: utf-8 -*-
"""标准件库: 按国标 / 样本尺寸生成零件文件 (.gform 特征表), 绑好 "标准件" 工艺和规格 — 装配体里点一下就插进来。

类别 → 系列 → 规格 (有的再要一个长度): CATALOG。make(类别, 规格, 长度) → (文件名, 文档)。
尺寸都是公称尺寸 (轴承 d×D×B、销 d×l…); 模型画的是外形 (轴承带两面密封圈、螺母和铜柱带真实螺纹), 不是厂家的精确模型。
挡圈 (卡簧) 的径向宽度是按样本取的近似值。
"""
from __future__ import annotations

import math

# ---- 深沟球轴承 d × D × B (密封型 2RS 的宽度; 68x 微型开式更窄, 这里给的是带密封的) ----
BEARINGS = {
    '6700 薄壁': {'6700': (10, 15, 4), '6701': (12, 18, 4), '6702': (15, 21, 4), '6703': (17, 23, 4), '6704': (20, 27, 4),
                 '6705': (25, 32, 4), '6706': (30, 37, 4), '6707': (35, 44, 5), '6708': (40, 50, 6), '6709': (45, 55, 6),
                 '6710': (50, 62, 6)},
    '6800 / 61800': {'6800': (10, 19, 5), '6801': (12, 21, 5), '6802': (15, 24, 5), '6803': (17, 26, 5), '6804': (20, 32, 7),
                     '6805': (25, 37, 7), '6806': (30, 42, 7), '6807': (35, 47, 7), '6808': (40, 52, 7), '6809': (45, 58, 7),
                     '6810': (50, 65, 7), '61811': (55, 72, 9), '61812': (60, 78, 10)},
    '6900': {'6900': (10, 22, 6), '6901': (12, 24, 6), '6902': (15, 28, 7), '6903': (17, 30, 7), '6904': (20, 37, 9),
             '6905': (25, 42, 9), '6906': (30, 47, 9), '6907': (35, 55, 10), '6908': (40, 62, 12), '6909': (45, 68, 12),
             '6910': (50, 72, 12)},
    '6000': {'6000': (10, 26, 8), '6001': (12, 28, 8), '6002': (15, 32, 9), '6003': (17, 35, 10), '6004': (20, 42, 12),
             '6005': (25, 47, 12), '6006': (30, 55, 13), '6007': (35, 62, 14), '6008': (40, 68, 15), '6009': (45, 75, 16),
             '6010': (50, 80, 16)},
    '6200': {'6200': (10, 30, 9), '6201': (12, 32, 10), '6202': (15, 35, 11), '6203': (17, 40, 12), '6204': (20, 47, 14),
             '6205': (25, 52, 15), '6206': (30, 62, 16), '6207': (35, 72, 17), '6208': (40, 80, 18)},
    '微型 68x / 69x': {'683': (3, 7, 3), '684': (4, 9, 4), '685': (5, 11, 5), '686': (6, 13, 5), '687': (7, 14, 5), '688': (8, 16, 5),
                      '689': (9, 17, 5), '693': (3, 8, 4), '694': (4, 11, 4), '695': (5, 13, 4), '696': (6, 15, 5), '697': (7, 17, 5),
                      '698': (8, 19, 6), '699': (9, 20, 6)},
    '微型 62x': {'623': (3, 10, 4), '624': (4, 13, 5), '625': (5, 16, 5), '626': (6, 19, 6), '627': (7, 22, 7), '628': (8, 24, 8),
                '629': (9, 26, 8)},
    '微型 MR': {'MR52': (2, 5, 2.5), 'MR63': (3, 6, 2.5), 'MR74': (4, 7, 2.5), 'MR85': (5, 8, 2.5), 'MR95': (5, 9, 3),
               'MR105': (5, 10, 4), 'MR106': (6, 10, 3), 'MR115': (5, 11, 4), 'MR117': (7, 11, 3), 'MR126': (6, 12, 4),
               'MR128': (8, 12, 3.5), 'MR137': (7, 13, 4), 'MR148': (8, 14, 4)},
}
# ---- 冲压外圈滚针轴承 HK: 内切圆 Fw × 外径 D × 宽 C ----
NEEDLES = {'HK0306': (3, 6.5, 6), 'HK0408': (4, 8, 8), 'HK0509': (5, 9, 9), 'HK0606': (6, 10, 6), 'HK0608': (6, 10, 8),
           'HK0609': (6, 10, 9), 'HK0612': (6, 10, 12), 'HK0810': (8, 12, 10), 'HK0812': (8, 12, 12), 'HK1010': (10, 14, 10),
           'HK1012': (10, 14, 12), 'HK1210': (12, 18, 10), 'HK1212': (12, 18, 12), 'HK1512': (15, 21, 12), 'HK1612': (16, 22, 12),
           'HK2010': (20, 26, 10), 'HK2012': (20, 26, 12)}
# ---- 圆柱销 GB/T 119.2 (淬硬, m6): 直径 → 常用长度 ----
DOWELS = {1: (3, 4, 5, 6, 8, 10), 1.5: (4, 5, 6, 8, 10, 12, 16), 2: (4, 5, 6, 8, 10, 12, 16, 20), 2.5: (6, 8, 10, 12, 16, 20, 24),
          3: (6, 8, 10, 12, 16, 20, 24, 30), 4: (8, 10, 12, 16, 20, 24, 30, 40), 5: (10, 12, 16, 20, 24, 30, 40, 50),
          6: (12, 16, 20, 24, 30, 40, 50, 60), 8: (16, 20, 24, 30, 40, 50, 60, 80), 10: (20, 24, 30, 40, 50, 60, 80, 100)}
# ---- 挡圈: 轴用 GB/T 894 (公称轴径 → 槽径, 厚度, 径向宽 ≈) / 孔用 GB/T 893 (公称孔径 → 槽径, 厚度, 径向宽 ≈) ----
SHAFT_CLIPS = {3: (2.8, 0.4, 0.8), 4: (3.8, 0.4, 0.9), 5: (4.8, 0.6, 1.1), 6: (5.7, 0.7, 1.3), 8: (7.6, 0.8, 1.5), 10: (9.6, 1.0, 1.8),
               12: (11.5, 1.0, 1.9), 15: (14.3, 1.0, 2.2), 17: (16.2, 1.0, 2.3), 20: (19.0, 1.2, 2.6), 25: (23.9, 1.2, 3.0),
               30: (28.6, 1.5, 3.5), 35: (33.0, 1.5, 3.9), 40: (37.5, 1.75, 4.3), 45: (42.5, 1.75, 4.6), 50: (47.0, 2.0, 5.0)}
HOLE_CLIPS = {8: (8.4, 0.8, 1.3), 10: (10.4, 1.0, 1.5), 12: (12.5, 1.0, 1.7), 15: (15.7, 1.0, 2.0), 16: (16.8, 1.0, 2.0),
              19: (20.0, 1.0, 2.2), 22: (23.0, 1.0, 2.5), 24: (25.2, 1.2, 2.6), 26: (27.2, 1.2, 2.7), 28: (29.4, 1.2, 2.9),
              30: (31.4, 1.2, 3.0), 32: (33.7, 1.2, 3.2), 35: (37.0, 1.5, 3.4), 37: (39.0, 1.5, 3.6), 40: (42.5, 1.75, 3.9),
              42: (44.5, 1.75, 4.1), 47: (49.5, 1.75, 4.4), 52: (55.0, 2.0, 4.7), 55: (58.0, 2.0, 5.0), 58: (61.0, 2.0, 5.0),
              62: (65.0, 2.0, 5.2)}
# ---- 钢球 GB/T 308 (直径) ----
BALLS = (1, 1.5, 2, 2.5, 3, 3.175, 3.5, 4, 4.5, 5, 6, 6.35, 7, 8, 10)
# ---- 六角螺母 GB/T 6170: 对边 s, 厚 m ----
NUTS = {'M2': (4, 1.6), 'M2.5': (5, 2.0), 'M3': (5.5, 2.4), 'M4': (7, 3.2), 'M5': (8, 4.7), 'M6': (10, 5.2), 'M8': (13, 6.8),
        'M10': (16, 8.4), 'M12': (18, 10.8)}
# ---- 平垫圈 GB/T 97.1: 内径, 外径, 厚 ----
WASHERS = {'M2': (2.2, 5, 0.3), 'M2.5': (2.7, 6, 0.5), 'M3': (3.2, 7, 0.5), 'M4': (4.3, 9, 0.8), 'M5': (5.3, 10, 1.0),
           'M6': (6.4, 12, 1.6), 'M8': (8.4, 16, 1.6), 'M10': (10.5, 20, 2.0), 'M12': (13, 24, 2.5)}
# ---- 六角铜柱 (双通 F-F): 对边; 常用长度 ----
STANDOFFS = {'M2': 4.0, 'M2.5': 5.0, 'M3': 5.0, 'M4': 7.0}
STANDOFF_LENGTHS = (3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30)
# ---- 内六角螺丝: 头型 → 标准名; 常用长度 ----
SCREW_HEADS = {'cap': ('内六角圆柱头', 'GB/T 70.1'), 'button': ('内六角圆头 (盘头)', 'ISO 7380'), 'flat': ('内六角沉头', 'GB/T 70.3')}
SCREW_SIZES = ('M2', 'M2.5', 'M3', 'M4', 'M5', 'M6', 'M8')
SCREW_LENGTHS = (3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 25, 30, 35, 40)

PROCESS = {'id': 'standard', 'name': '标准件 (按规格网购)', 'short': '标准', 'color': '#3FB97F', 'standard': True}


def _number(value):
    return f'{value:g}'


def screw_lengths(size):
    """这个规格常用的长度: 不短于 d (沉头的头要埋得下), 不长于 12d。"""
    d = float(size[1:])
    return [length for length in SCREW_LENGTHS if d <= length <= 12 * d]


def catalog():
    """给界面的目录: [{'id', 'title', 'series': [{'id', 'title', 'sizes': [{'id', 'title'}]}], 'lengths': {规格: [长度...]} 或 None}...]。"""
    out = []
    out.append({'id': 'bearing', 'title': '深沟球轴承', 'lengths': None, 'series': [
        {'id': series, 'title': series, 'sizes': [{'id': name, 'title': f'{name}　{_number(d)}×{_number(D)}×{_number(B)}'}
                                                  for name, (d, D, B) in table.items()]} for series, table in BEARINGS.items()]})
    out.append({'id': 'needle', 'title': '滚针轴承 HK (冲压外圈)', 'lengths': None, 'series': [
        {'id': 'HK', 'title': 'HK', 'sizes': [{'id': name, 'title': f'{name}　{_number(fw)}×{_number(D)}×{_number(C)}'}
                                              for name, (fw, D, C) in NEEDLES.items()]}]})
    out.append({'id': 'dowel', 'title': '圆柱销 GB/T 119.2', 'series': [
        {'id': 'dowel', 'title': '淬硬 m6', 'sizes': [{'id': _number(d), 'title': f'Ø{_number(d)}'} for d in DOWELS]}],
        'lengths': {_number(d): list(lengths) for d, lengths in DOWELS.items()}})
    out.append({'id': 'screw', 'title': '内六角螺丝', 'series': [
        {'id': head, 'title': f'{title} {code}', 'sizes': [{'id': size, 'title': size} for size in SCREW_SIZES]}
        for head, (title, code) in SCREW_HEADS.items()], 'lengths': {size: screw_lengths(size) for size in SCREW_SIZES}})
    out.append({'id': 'nut', 'title': '六角螺母 GB/T 6170', 'lengths': None, 'series': [
        {'id': 'nut', 'title': '1 型', 'sizes': [{'id': size, 'title': f'{size}　对边 {_number(s)} 厚 {_number(m)}'}
                                                 for size, (s, m) in NUTS.items()]}]})
    out.append({'id': 'washer', 'title': '平垫圈 GB/T 97.1', 'lengths': None, 'series': [
        {'id': 'washer', 'title': 'A 级', 'sizes': [{'id': size, 'title': f'{size}　{_number(a)}×{_number(b)}×{_number(t)}'}
                                                   for size, (a, b, t) in WASHERS.items()]}]})
    out.append({'id': 'standoff', 'title': '六角铜柱 (双通)', 'series': [
        {'id': 'ff', 'title': 'F-F', 'sizes': [{'id': size, 'title': f'{size}　对边 {_number(s)}'} for size, s in STANDOFFS.items()]}],
        'lengths': {size: list(STANDOFF_LENGTHS) for size in STANDOFFS}})
    out.append({'id': 'shaft_clip', 'title': '轴用挡圈 GB/T 894', 'lengths': None, 'series': [
        {'id': 'shaft', 'title': 'A 型', 'sizes': [{'id': _number(d), 'title': f'轴 Ø{_number(d)}　厚 {_number(s)}'}
                                                  for d, (_, s, _) in SHAFT_CLIPS.items()]}]})
    out.append({'id': 'hole_clip', 'title': '孔用挡圈 GB/T 893', 'lengths': None, 'series': [
        {'id': 'hole', 'title': 'A 型', 'sizes': [{'id': _number(d), 'title': f'孔 Ø{_number(d)}　厚 {_number(s)}'}
                                                 for d, (_, s, _) in HOLE_CLIPS.items()]}]})
    out.append({'id': 'ball', 'title': '钢球 GB/T 308', 'lengths': None, 'series': [
        {'id': 'ball', 'title': 'G10', 'sizes': [{'id': _number(d), 'title': f'Ø{_number(d)}'} for d in BALLS]}]})
    return out


# ---- 特征表的小工具 ----
def _sketch(fid, name, shapes, plane='XY', offset=0.0):
    return {'id': fid, 'type': 'sketch', 'name': name, 'suppressed': False, 'params': {'plane': plane, 'offset': offset, 'shapes': shapes}}


def _extrude(fid, name, sketch, distance, op='add'):
    return {'id': fid, 'type': 'extrude', 'name': name, 'suppressed': False,
            'params': {'sketch': sketch, 'distance': distance, 'op': op, 'symmetric': False, 'end': 'blind', 'reverse': False,
                       'distance2': 0.0, 'gap': 0.0, 'target': []}}


def _revolve(fid, name, sketch, axis='Z'):
    return {'id': fid, 'type': 'revolve', 'name': name, 'suppressed': False,
            'params': {'sketch': sketch, 'axis': axis, 'angle': 360.0, 'reverse': False, 'symmetric': False, 'op': 'add'}}


def _rect(x0, x1, z0, z1):
    return {'type': 'rect', 'cx': round((x0 + x1) / 2, 4), 'cy': round((z0 + z1) / 2, 4), 'w': round(x1 - x0, 4), 'h': round(z1 - z0, 4)}


def _circle(r, cx=0.0, cy=0.0):
    return {'type': 'circle', 'cx': cx, 'cy': cy, 'r': r}


def _hexagon(across):
    radius = across / math.sqrt(3)
    return {'type': 'polygon', 'points': [[round(radius * math.cos(math.radians(30 + 60 * k)), 4),
                                           round(radius * math.sin(math.radians(30 + 60 * k)), 4)] for k in range(6)]}


def _doc(features, spec, material='合金钢', name=''):
    """文档 + 标准件工艺 (绑在第一个出实体的特征上)。"""
    for feature in features:
        if feature['type'] in ('extrude', 'revolve', 'screw'):
            feature['process'] = dict(PROCESS, spec=spec, why=spec + '。标准件库生成')
            break
    serial = max(int(feature['id'][1:]) for feature in features)
    return {'format': 'genform-document', 'version': 1, 'serial': serial, 'upto': None,
            'props': {'material': material, 'standard': {'spec': spec, 'name': name}}, 'features': features}


def _tapped(fid, name, sketch, size, flip=False):
    return {'id': fid, 'type': 'hole', 'name': name, 'suppressed': False,
            'params': {'sketch': sketch, 'kind': 'tapped', 'size': size, 'diameter': 2.5, 'through': True, 'depth': 10.0,
                       'head_diameter': 6.0, 'head_depth': 1.0, 'flip': flip, 'thread': True, 'phase': 0.0}}


# ---- 各类别的模型 (坐标: 零件的轴是 Z, 从 z = 0 往上; 螺丝头在 z = 0、杆朝 -Z, 和螺丝特征一样) ----
def _bearing(name, d, D, B, ring=None):
    """深沟球轴承 (2RS): 一整块实体 (外购件整体买, 分成内圈 / 滚珠 / 外圈几块就成了悬空的块),
    两个端面在内圈、密封圈、外圈的分界处各车一道浅缝, 看上去还是三圈。"""
    ri, ro = d / 2, D / 2
    ring = ring or max(0.3 * (ro - ri), 0.4)                      # 内外圈的径向厚度
    slit, deep = min(0.15, 0.05 * (ro - ri)), min(0.3, 0.06 * B)
    grooves = [_rect(r - slit / 2, r + slit / 2, z0, z0 + deep) for r in (ri + ring, ro - ring) for z0 in (0, B - deep)]
    spec = f'{name}-2RS {_number(d)}×{_number(D)}×{_number(B)}'
    cut = _revolve('f4', '内外圈和密封圈的分界缝', 'f3')
    cut['params']['op'] = 'cut'
    return _doc([_sketch('f1', '截面', [_rect(ri, ro, 0, B)], plane='XZ'), _revolve('f2', spec, 'f1'),
                 _sketch('f3', '分界缝', grooves, plane='XZ'), cut], spec, name=name)


def make(kind, size, length=None, series=''):
    """→ (建议的文件名, 文档)。kind: catalog() 里的类别 id; size: 规格 id; length: 销、螺丝、铜柱的长度; series: 螺丝的头型。"""
    if kind == 'bearing':
        for table in BEARINGS.values():
            if size in table:
                d, D, B = table[size]
                return f'std_{size}.gform', _bearing(size, d, D, B)
        raise ValueError(f'没有这个轴承 {size}')
    if kind == 'needle':
        fw, D, C = NEEDLES[size]
        shell = (D - fw) / 2
        shapes = [_rect(D / 2 - shell * 0.25, D / 2, 0, C), _rect(fw / 2, D / 2 - shell * 0.25, C * 0.1, C * 0.9),
                  _rect(fw / 2 + shell * 0.2, D / 2, 0, C * 0.1), _rect(fw / 2 + shell * 0.2, D / 2, C * 0.9, C)]
        spec = f'{size} 冲压外圈滚针轴承 {_number(fw)}×{_number(D)}×{_number(C)}'
        return f'std_{size}.gform', _doc([_sketch('f1', '截面', shapes, plane='XZ'), _revolve('f2', spec, 'f1')], spec, name=size)
    if kind == 'dowel':
        d, l = float(size), float(length or DOWELS[float(size) if float(size) % 1 else int(float(size))][2])
        chamfer = min(0.1 * d, 0.3)
        spec = f'GB/T 119.2 圆柱销 Ø{_number(d)}×{_number(l)} m6 淬硬'
        shapes = [{'type': 'polygon', 'points': [[0, 0], [d / 2 - chamfer, 0], [d / 2, chamfer], [d / 2, l - chamfer],
                                                 [d / 2 - chamfer, l], [0, l]]}]
        return f'std_dowel_{_number(d)}x{_number(l)}.gform', _doc([_sketch('f1', '截面', shapes, plane='XZ'), _revolve('f2', spec, 'f1')], spec)
    if kind == 'screw':
        head = series or 'cap'
        l = float(length or 10)
        title, code = SCREW_HEADS[head]
        spec = f'{code} M{size[1:]}×{_number(l)} {title}'
        features = [_sketch('f1', '位置', [{'type': 'point', 'x': 0, 'y': 0}]),
                    {'id': 'f2', 'type': 'screw', 'name': f'{size}×{_number(l)} {title} (真实牙)', 'suppressed': False,
                     'params': {'sketch': 'f1', 'size': size, 'head': head, 'length': l, 'flip': False, 'thread': True, 'phase': 0.0}}]
        return f'std_screw_{size}x{_number(l)}_{head}.gform', _doc(features, spec)
    if kind == 'nut':
        s, m = NUTS[size]
        spec = f'GB/T 6170 {size} 六角螺母'
        features = [_sketch('f1', '六角', [_hexagon(s)]), _extrude('f2', spec, 'f1', m),
                    _sketch('f3', '螺纹孔', [{'type': 'point', 'x': 0, 'y': 0}], offset=m), _tapped('f4', f'{size} 螺纹 (真实牙)', 'f3', size)]
        return f'std_nut_{size}.gform', _doc(features, spec)
    if kind == 'washer':
        inner, outer, thick = WASHERS[size]
        spec = f'GB/T 97.1 {size} 平垫圈 {_number(inner)}×{_number(outer)}×{_number(thick)}'
        return f'std_washer_{size}.gform', _doc([_sketch('f1', '垫圈', [_circle(outer / 2), _circle(inner / 2)]), _extrude('f2', spec, 'f1', thick)], spec)
    if kind == 'standoff':
        s, l = STANDOFFS[size], float(length or 6)
        spec = f'{size}×{_number(l)} 双通六角铜柱 (F-F) 对边 {_number(s)}'
        features = [_sketch('f1', '六角', [_hexagon(s)]), _extrude('f2', spec, 'f1', l),
                    _sketch('f3', '螺纹孔', [{'type': 'point', 'x': 0, 'y': 0}], offset=l), _tapped('f4', f'{size} 通孔螺纹 (真实牙)', 'f3', size)]
        return f'std_standoff_{size}x{_number(l)}.gform', _doc(features, spec, material='黄铜')
    if kind in ('shaft_clip', 'hole_clip'):
        d = float(size)
        table = SHAFT_CLIPS if kind == 'shaft_clip' else HOLE_CLIPS
        groove, thick, band = table[d if d % 1 else int(d)]
        inner, outer = (groove / 2, groove / 2 + band) if kind == 'shaft_clip' else (groove / 2 - band, groove / 2)
        code = 'GB/T 894 轴用' if kind == 'shaft_clip' else 'GB/T 893 孔用'
        spec = f'{code}挡圈 {_number(d)} (厚 {_number(thick)})'
        gap = max(band * 0.8, 0.6)
        shapes = [_circle(outer), _circle(inner)]
        features = [_sketch('f1', '挡圈', shapes), _extrude('f2', spec, 'f1', thick),
                    _sketch('f3', '开口', [_rect(-gap / 2, gap / 2, inner - 0.5, outer + 0.5)]), _extrude('f4', '开口', 'f3', thick, 'cut')]
        return f'std_{kind}_{_number(d)}.gform', _doc(features, spec, material='弹簧钢')
    if kind == 'ball':
        d = float(size)
        spec = f'GB/T 308 钢球 Ø{_number(d)} G10'
        shapes = [{'type': 'arc', 'cx': 0, 'cy': d / 2, 'r': d / 2, 'a0': -90.0, 'a1': 90.0},
                  {'type': 'line', 'x1': 0, 'y1': d, 'x2': 0, 'y2': 0}]
        return f'std_ball_{_number(d)}.gform', _doc([_sketch('f1', '截面', shapes, plane='XZ'), _revolve('f2', spec, 'f1')], spec)
    raise ValueError(f'不认识的标准件类别 {kind}')
