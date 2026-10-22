"""真实螺纹牙: 60° 普通螺纹的基本牙型, 内外螺纹各让出 CLEAR 的轴向间隙, 相位有定义 — 同规格的螺丝拧进螺纹孔,
牙正好嵌在一起, 干涉检查不报。

相位: 从起点平面 (螺丝头、孔口、螺柱根部) 沿螺纹前进方向 along 走 s, 外螺纹的牙槽中心在 side 方向绕 along (右手) 转
θ = 2π (s - 偏移) / p 的地方 (右旋螺纹); 内螺纹的牙槽再错开半个螺距, 正好对着外螺纹的牙。
side = 世界 X 在垂直于轴的平面上的投影 (轴和 X 平行时用 Y)。两件拧在一起: 起点平面沿轴相距螺距的整数倍就正好对上,
不是整数倍用 phase (度) 补: phase = 360 × (外螺纹起点 - 内螺纹起点) / p。"""
from __future__ import annotations

import math

import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell

from ..build import FeatureError
from .. import build
from .helpers import _dir, _pnt, _run, _spline

PITCHES = {'M2': 0.4, 'M2.5': 0.45, 'M3': 0.5, 'M4': 0.7, 'M5': 0.8, 'M6': 1.0, 'M8': 1.25, 'M10': 1.5, 'M12': 1.75}   # 粗牙螺距
CLEAR = 0.01            # 内外螺纹每个牙侧各让出的轴向间隙 (mm): 合在一起总共 0.04, 牙不会碰上
STEPS = 36              # 螺旋线每圈取几个点
SEGMENT = 3             # 螺旋每段扫几圈


def coarse_pitch(diameter):
    """按直径查粗牙螺距 (表里没有就按 0.15 × 直径估一个)。"""
    for name, pitch in PITCHES.items():
        if abs(float(name[1:]) - diameter) < 1e-6:
            return pitch
    return round(0.15 * diameter, 2)


def minor_hole(major, pitch):
    """螺纹孔的底孔直径 (内螺纹小径 D1 = D - 1.0825 p)。"""
    return major - 1.082532 * pitch


def cut(solid, tool, what):
    """从 solid 上切掉牙槽, 切完体积没变就报错 (螺旋面的布尔偶尔算出 "什么都没切", 不能让光杆冒充带牙的)。"""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    def volume(shape):
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        return props.Mass()
    before = volume(solid)
    result = build._boolean(BRepAlgoAPI_Cut, solid, tool, what)
    if volume(result) > before - 1e-4:
        raise FeatureError(f'{what}失败：螺纹牙没切上')
    return result


def tip_trimmer(spot, along, diameter, length, chamfer):
    """把加长的螺杆截回 length 并倒角的切除体: 端面以外的一大块 + 倒角那一圈 (光杆加长切完牙再截, 牙槽不碰端面, 布尔才稳)。"""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2
    spot, along = np.asarray(spot, float), np.asarray(along, float) / np.linalg.norm(along)
    big = diameter
    beyond = BRepPrimAPI_MakeCylinder(gp_Ax2(_pnt(spot + along * length), _dir(along)), big, diameter * 3).Shape()
    if chamfer <= 0:
        return beyond
    ring = BRepPrimAPI_MakeCylinder(gp_Ax2(_pnt(spot + along * (length - chamfer)), _dir(along)), big, chamfer).Shape()
    cone = BRepPrimAPI_MakeCone(gp_Ax2(_pnt(spot + along * (length - chamfer)), _dir(along)), diameter / 2, diameter / 2 - chamfer, chamfer).Shape()
    ring = build._boolean(BRepAlgoAPI_Cut, ring, cone, '螺杆倒角')
    return build._boolean(BRepAlgoAPI_Fuse, beyond, ring, '螺杆倒角')


def side_of(along):
    along = np.asarray(along, float) / np.linalg.norm(along)
    ref = np.array([1.0, 0, 0]) if abs(along[0]) < 0.9 else np.array([0, 1.0, 0])
    side = ref - along * float(np.dot(ref, along))
    return side / np.linalg.norm(side)


def groove(spot, along, major, pitch, start, end, internal, phase=0.0):
    """牙槽实体 (拿去从零件上切掉): 螺纹轴过 spot、朝 along, 公称大径 major, 螺距 pitch;
    牙槽沿轴从 s = start 切到 s = end (s 从 spot 量起)。internal = 内螺纹 (孔壁上), 否则外螺纹 (轴上)。"""
    spot, along = np.asarray(spot, float), np.asarray(along, float) / np.linalg.norm(along)
    if pitch <= 0 or end <= start:
        raise FeatureError('螺纹的螺距和长度要是正数')
    height = 0.866025 * pitch                   # 60° 基本三角形高 H
    crest, root = major / 2 + height / 8, major / 2 - 7 * height / 8    # 基本牙型尖顶 / 尖底所在半径
    widen = 2 * CLEAR * height / pitch          # 牙侧让 CLEAR 后, 槽尖往外 (内螺纹) / 往里 (外螺纹) 挪的量
    if internal:
        tip, base = crest + widen, minor_hole(major, pitch) / 2 - 0.02
        half = (pitch * (crest - base) / height + 2 * CLEAR) / 2
    else:
        tip, base = root - widen, major / 2 + 0.02
        half = (pitch * (base - root) / height + 2 * CLEAR) / 2
    if min(tip, base) <= 0 or half >= pitch / 2:
        raise FeatureError('螺距相对这个直径太大')
    side = side_of(along)
    shift = pitch * ((phase / 360.0) % 1.0) + (pitch / 2 if internal else 0.0)    # 牙槽中心在 θ = 0 时的 s
    # 一根扫很多圈的螺旋, 布尔会算不出来 (切了等于没切): 每 SEGMENT 圈一段, 一段段的实体拼成复合体
    cuts, edges = [], [start]
    while end - edges[-1] > SEGMENT * pitch * 1.5:
        edges.append(edges[-1] + SEGMENT * pitch)
    edges.append(end)
    for first, last in zip(edges, edges[1:]):
        cuts.append(_segment(spot, along, side, pitch, first, last, shift, tip, base, half))
    return cuts[0] if len(cuts) == 1 else build._compound(cuts)


def _segment(spot, along, side, pitch, start, end, shift, tip, base, half):
    cross = np.cross(along, side)
    angle = math.tau * (start - shift) / pitch                                     # 起点处牙槽中心转到的角度
    turns = (end - start) / pitch
    count = max(int(math.ceil(turns * STEPS)), 4)
    middle = (tip + base) / 2

    def radial(theta):
        return side * math.cos(theta) + cross * math.sin(theta)
    points = [spot + along * (start + pitch * turns * k / count) + radial(angle + math.tau * turns * k / count) * middle
              for k in range(count + 1)]
    spine = _spline(points)
    at, out = spot + along * start, radial(angle)
    polygon = BRepBuilderAPI_MakePolygon(_pnt(at + out * base - along * half), _pnt(at + out * base + along * half), _pnt(at + out * tip), True)
    shell = BRepOffsetAPI_MakePipeShell(spine)
    shell.SetMode(_dir(along))
    shell.Add(polygon.Wire())
    _run(shell, '螺纹扫不出来')
    if not shell.MakeSolid():
        raise FeatureError('螺纹牙合不成实体')
    return shell.Shape()
