# -*- coding: utf-8 -*-
"""装配体里的螺丝 ↔ 螺纹孔: 自动配对, 查拧进去多长、会不会顶到孔底, 算螺纹相位 (两边的牙对上)。

配对: 螺丝 (零件文件里的 screw 特征) 的轴和别的零件上螺纹孔 (hole 特征, kind = tapped) 的轴同一条线、规格一样。
拧入长度: 沿螺丝的轴, 在牙的半径上取点 — 同时在螺丝杆里、又在对面零件的料里的那一段 (通孔、沉孔、台阶孔都对)。
    够不够: 铝、塑料至少 1.5d (塑料 2d), 钢、铜至少 1d。
顶底: 螺丝尖再往前 MIN_BOTTOM 毫米之内就碰到孔底的料 → 报 (钻头尖、攻丝的不完整牙都在孔底)。
相位: 牙槽的约定见 ops/threads.py — 螺旋从 spot 沿 along 量 s, 角度从 side_of(along) (零件自己坐标里) 绕 along 量,
    s = p·θ/2π + p·phase/360。把两边都换到世界坐标、沿螺丝的方向 a 比:
        φ孔 = sign · (φ螺丝 + 360·(m − f)/p + (α孔 − α螺丝))       (mod 360)
    m、f = 螺丝 / 孔的起点在 a 上的位置; α = 各自的角度起点 (side) 绕 a 量的角; sign = 孔的钻向和 a 同向 +1, 反向 -1。
"""
from __future__ import annotations

import copy
import json
import math
import os

import numpy as np

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

from . import build
from .model.base import FeatureError

MIN_BOTTOM = 0.5                # 螺丝尖离盲孔底至少留这么多 (mm)
AXIS_GAP = 0.1                  # 两根轴相距不超过这么多算同一条 (mm)
ENGAGE = {'铝': 1.5, '塑料': 2.0, '尼龙': 2.0, 'ABS': 2.0, 'PLA': 2.0, '钢': 1.0, '铜': 1.0, '铁': 1.0, '钛': 1.0}
SAMPLE = 0.1                    # 量拧入长度时沿轴取点的间距 (mm)


def _engage_factor(material):
    for key, factor in ENGAGE.items():
        if key in (material or ''):
            return factor
    return 1.5                  # 不知道材质: 按铝算, 宁可严一点


def _features(path):
    if not str(path or '').lower().endswith('.gform'):
        return None
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _threads_in(part):
    """一个零件里的螺丝和螺纹孔 (零件自己的坐标) → (螺丝 [...], 螺纹孔 [...])。"""
    from .assembly import _alone
    from .ops import threads
    from .ops.helpers import _spots
    from .ops.tools import _along
    doc = _features(part.get('path'))
    if doc is None:
        return [], []
    features = doc.get('features') or []
    wanted = [feature for feature in features if not feature.get('suppressed') and
              (feature.get('type') == 'screw' or (feature.get('type') == 'hole' and (feature.get('params') or {}).get('kind') == 'tapped'))]
    if not wanted:
        return [], []
    _, ctx, status = _alone(features, doc.get('upto'))
    screws, holes = [], []
    from .. import features as table
    for feature in wanted:
        params = feature.get('params') or {}
        if not str(status.get(feature['id'], 'ok')).startswith('ok'):
            continue
        sketch = ctx.sketches.get(params.get('sketch'))
        if sketch is None:
            continue
        size = params.get('size', 'M3')
        if size not in threads.PITCHES:
            continue
        along = np.asarray(_along(sketch, params), float)
        along = along / np.linalg.norm(along)
        common = {'feature': feature['id'], 'name': feature.get('name') or feature['id'], 'size': size, 'pitch': threads.PITCHES[size],
                  'along': along, 'side': threads.side_of(along), 'phase': float(params.get('phase') or 0.0),
                  'thread': bool(params.get('thread'))}
        for spot in _spots(sketch):
            if feature['type'] == 'screw':
                head = params.get('head', 'cap')
                diameter = float(size[1:])
                head_diameter = table.SCREW_SIZES[size][head][0]
                start = (head_diameter - diameter) / 2 if head == 'flat' else 0.0       # 杆从哪里开始 (沉头: 锥面下面)
                screws.append(dict(common, spot=np.asarray(spot, float), start=start, length=float(params.get('length') or 10.0)))
            else:
                depth = None if params.get('through', True) else float(params.get('depth') or 0.0)
                holes.append(dict(common, spot=np.asarray(spot, float), depth=depth))
    return screws, holes


def _placed(item, rotation, offset):
    item = dict(item)
    item['spot'] = rotation @ item['spot'] + offset
    item['along'] = rotation @ item['along']
    item['side'] = rotation @ item['side']
    return item


def _angle_about(axis, vector):
    reference = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    reference = reference - axis * float(reference @ axis)
    reference /= np.linalg.norm(reference)
    return math.degrees(math.atan2(float(axis @ np.cross(reference, vector)), float(reference @ vector)))


def needed_phase(screw, hole):
    """螺纹孔要填的相位 (度, 0~360), 让它的牙和螺丝的牙对上。两边的 spot / along / side 都是世界坐标。"""
    axis = screw['along']
    sign = 1.0 if float(hole['along'] @ axis) > 0 else -1.0
    m, f = float(screw['spot'] @ axis), float(hole['spot'] @ axis)
    alpha_screw, alpha_hole = _angle_about(axis, screw['side']), _angle_about(axis, hole['side'] * 1.0)
    value = sign * (screw['phase'] + 360.0 * (m - f) / screw['pitch'] + (alpha_hole - alpha_screw))
    return value % 360.0


def _cylinder(base, axis, radius, height):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    frame = gp_Ax2(gp_Pnt(*(float(value) for value in base)), gp_Dir(*(float(value) for value in axis)))
    return BRepPrimAPI_MakeCylinder(frame, float(radius), float(height)).Shape()


def _common_shape(first, second):
    from .assembly import _common
    try:
        maker = _common(first, second)
        if not maker.IsDone() or build._is_empty(maker.Shape()):
            return None
        return maker.Shape()
    except Exception:
        return None


def _inside(shape):
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt
    classifier = BRepClass3d_SolidClassifier(shape)

    def test(point):
        classifier.Perform(gp_Pnt(*(float(value) for value in point)), 1e-4)
        return classifier.State() == TopAbs_IN
    return test


def fasteners(features, upto, data):
    """→ {'pairs': [{'screw', 'hole_part' 零部件序号, 'screw_name', 'hole_name', 'feature', 'size', 'engaged' 拧进去多长 (mm),
                     'need' 至少要多长, 'bottom' 离孔底多远 (通孔 / 没碰到是 None), 'phase', 'phase_need', 'phase_ok',
                     'problems': [...]}...],
          'loose': [{'screw', 'name', 'size'}] 没找到螺纹孔的螺丝 (配螺母的、或者孔没画成螺纹孔的), 'fix': {(零部件, 特征) → 相位}}。"""
    from .assembly import _matrix, _where, _placed as place_shape, _record
    parts = data.get('parts') or []
    found = []
    for number, part in enumerate(parts):
        rotation, offset = _matrix(*_where(part))
        screws, holes = _threads_in(part)
        found.append(([_placed(item, rotation, offset) for item in screws], [_placed(item, rotation, offset) for item in holes]))
    shapes = {}

    def shape_of(number):
        if number not in shapes:
            shapes[number] = place_shape(_record(parts[number], features, upto)['shape'], *_where(parts[number]))
        return shapes[number]
    pairs, loose, wanted = [], [], {}
    for number, (screws, _) in enumerate(found):
        for screw in screws:
            axis, match = screw['along'], None
            for other, (_, holes) in enumerate(found):
                if other == number:
                    continue
                for hole in holes:
                    if hole['size'] != screw['size'] or abs(float(hole['along'] @ axis)) < 0.999:
                        continue
                    apart = hole['spot'] - screw['spot']
                    if np.linalg.norm(apart - axis * float(apart @ axis)) > AXIS_GAP:
                        continue
                    # 孔沿轴的那一段要和螺丝杆 (起点 ~ 尖) 有重叠
                    reach, depth = float(apart @ axis), hole['depth'] if hole['depth'] is not None else 1e6
                    low, high = (reach, reach + depth) if float(hole['along'] @ axis) > 0 else (reach - depth, reach)
                    if min(high, screw['length']) - max(low, screw['start']) <= 0:
                        continue
                    match = (other, hole)
                    break
                if match:
                    break
            if match is None:
                loose.append({'screw': number, 'name': parts[number].get('name') or f'零件{number + 1}', 'size': screw['size']})
                continue
            other, hole = match
            pairs.append(_judge(number, screw, other, hole, parts, shape_of, wanted))
    fix = {}
    for key, values in wanted.items():
        spread = max(min(abs(a - b), 360 - abs(a - b)) for a in values for b in values)
        fix[key] = values[0] if spread < 1.0 else None          # 同一个孔特征上几颗螺丝要的相位不一样: 没法一个数都对上
    for pair in pairs:
        key = (pair['hole_part'], pair['feature'])
        if fix.get(key) is None and key in fix and not pair['phase_ok']:
            pair['problems'].append('这个孔特征上的几颗螺丝要的相位不一样 (螺丝头不在螺距整数倍的平面上): 拆成几个孔特征或改螺丝长度')
    return {'pairs': pairs, 'loose': loose, 'fix': [{'part': key[0], 'feature': key[1], 'phase': value} for key, value in fix.items()]}


def _judge(number, screw, other, hole, parts, shape_of, wanted):
    axis, diameter = screw['along'], float(screw['size'][1:])
    material = ((_features(parts[other].get('path')) or {}).get('props') or {}).get('material', '')
    need = _engage_factor(material) * diameter
    # 拧入长度: 大径外面一点点套一圈 0.05 厚的薄管 (杆的起点 ~ 尖), 和对面零件求交: 交出来的体积 ÷ 薄管截面 = 咬住的长度。
    # 那一圈在螺纹孔的孔壁里全是料 (内螺纹的牙槽只挖到大径 + 1/8 牙高), 在光孔 (过孔比大径大 0.4 以上)、沉孔里全是空的
    from .assembly import _overlap
    target = shape_of(other)
    inner = diameter / 2 + 0.10
    outer = inner + 0.05
    span = screw['length'] - screw['start']
    base = screw['spot'] + axis * screw['start']
    tube = build._boolean(BRepAlgoAPI_Cut, _cylinder(base, axis, outer, span), _cylinder(base - axis * 0.01, axis, inner, span + 0.02), '量拧入长度')
    volume, _ = _overlap(tube, target)
    engaged = volume / (math.pi * (outer * outer - inner * inner))
    # 顶底: 尖往前 6·MIN_BOTTOM 放一根细棒和对面零件求交, 交出来那块离尖最近的地方就是孔底 (更远的不报)
    tip = screw['spot'] + axis * screw['length']
    rod = _cylinder(tip, axis, 0.3, MIN_BOTTOM * 6)
    bottom = None
    maker = _common_shape(rod, target)
    if maker is not None:
        low, high = build.bounds(maker)
        corners = np.array([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])])
        bottom = max(float(((corners - tip) @ axis).min()), 0.0)
    phase_need = needed_phase(screw, hole)
    gap = min(abs(phase_need - hole['phase']), 360 - abs(phase_need - hole['phase']))
    problems = []
    if engaged + 1e-6 < need:
        problems.append(f'拧进去只有 {engaged:.1f} mm, {material or "这种材质"}里至少要 {need:.1f} mm ({need / diameter:g}d)')
    if bottom is not None and bottom < MIN_BOTTOM - 1e-3:
        problems.append(f'螺丝尖离孔底只有 {bottom:.2f} mm (至少留 {MIN_BOTTOM} mm): 换短一号的螺丝或把孔打深')
    if screw['thread'] and hole['thread'] and gap > 3.0:
        problems.append(f'螺纹相位对不上: 孔现在 {hole["phase"]:.0f}°, 要 {phase_need:.0f}° (点“对齐螺纹相位”)')
    wanted.setdefault((other, hole['feature']), []).append(phase_need)
    return {'screw': number, 'hole_part': other, 'screw_name': parts[number].get('name') or f'零件{number + 1}',
            'hole_name': parts[other].get('name') or f'零件{other + 1}', 'feature': hole['feature'], 'feature_name': hole['name'],
            'size': screw['size'], 'engaged': engaged, 'need': need, 'bottom': bottom, 'phase': hole['phase'], 'phase_need': phase_need,
            'phase_ok': gap <= 3.0 or not (screw['thread'] and hole['thread']), 'problems': problems}


def apply_phases(paths_and_fixes):
    """把算出来的相位写回零件文件: [(文件, 特征 id, 相位)...] → 改了几个特征。"""
    changed = 0
    for path, feature_id, phase in paths_and_fixes:
        doc = _features(path)
        if doc is None:
            continue
        for feature in doc.get('features') or []:
            if feature.get('id') == feature_id:
                feature.setdefault('params', {})['phase'] = round(float(phase), 3)
                changed += 1
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=1)
    return changed
