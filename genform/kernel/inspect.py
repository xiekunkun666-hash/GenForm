# -*- coding: utf-8 -*-
"""绑定加工工艺、设计检查要的几何数据 (不改文档; 走 query 通道, 界面开着时在内核进程里算):

- tools: 每个造型特征的工具体量出来的指标 — 包围盒、体积、表面积、平均壁厚、各种曲面各有几张 — 拿来判断它像
  一块板、一个回转件还是一块自由曲面, 该用什么工艺做 (见 genform/manufacturing.py);
- bodies: 实体有几块互不相连的, 每块多大、在哪、哪些特征的面在它上面 (一辆车做完应该是一整块, 多出来的就是悬空的零件);
- valid: 整个实体过不过 OpenCascade 的拓扑检查。
"""
from __future__ import annotations

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import (GeomAbs_BSplineSurface, GeomAbs_BezierSurface, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane,
                         GeomAbs_Sphere, GeomAbs_Torus)
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopoDS import TopoDS

from . import build

_SURFACES = {GeomAbs_Plane: 'plane', GeomAbs_Cylinder: 'cylinder', GeomAbs_Cone: 'cone', GeomAbs_Sphere: 'sphere',
             GeomAbs_Torus: 'torus', GeomAbs_BSplineSurface: 'freeform', GeomAbs_BezierSurface: 'freeform'}
_as_face = getattr(TopoDS, 'Face_s', None) or TopoDS.Face
_MAX_TOOL_FACES = 400           # 面多到这个份上 (一串字、几百个孔) 只数前这么多张: 够判断是什么样的东西了


def _parts(shape, kind):
    mapping = build._indexed(shape, kind)
    return [mapping.FindKey(index) for index in range(1, mapping.Extent() + 1)]


def _box(shape):
    low, high = build.bounds(shape)
    return [list(map(float, low)), list(map(float, high))]


def metrics(shape):
    """一块工具体 → {'box', 'size' (从小到大的三个边长), 'volume', 'area', 'thickness' (2·体积/表面积: 板就是板厚),
    'faces': {曲面类型: 张数}, 'solids'}。"""
    props, area = GProp_GProps(), GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    BRepGProp.SurfaceProperties_s(shape, area)
    volume, surface = abs(float(props.Mass())), float(area.Mass())
    faces = {}
    for face in _parts(shape, TopAbs_FACE)[:_MAX_TOOL_FACES]:
        kind = _SURFACES.get(BRepAdaptor_Surface(_as_face(face), False).GetType(), 'other')
        faces[kind] = faces.get(kind, 0) + 1
    box = _box(shape)
    size = sorted(high - low for low, high in zip(*box))
    return {'box': box, 'size': size, 'volume': volume, 'area': surface,
            'thickness': 2 * volume / surface if surface > 1e-12 else 0.0, 'faces': faces,
            'solids': len(_parts(shape, TopAbs_SOLID))}


def _tool_shape(entry):
    """ctx.tools 里的一项: 造型特征是 (工具体, 方式); 阵列 / 镜像是 [(复制体, 方式)...] → (代表的那块, 份数, 方式)。"""
    if isinstance(entry, list):
        if not entry:
            return None, 0, None
        solid, operation = entry[0][0], entry[0][1]
        return solid, len(entry), operation
    solid, operation = entry
    return solid, 1, operation


def inspect(features, upto, data=None):
    body, ctx, status = build._rebuild(features, upto)       # 要 Context (工具体、面的归属), rebuild() 只给草图
    tools = {}
    for identifier, entry in (ctx.tools or {}).items():
        shape, copies, operation = _tool_shape(entry)
        if shape is None or shape.IsNull():
            continue
        try:
            tools[identifier] = dict(metrics(shape), copies=copies, op=str(operation))
        except Exception:               # 量不出来的 (退化的工具体): 工艺按特征类型猜, 不至于整个检查都做不了
            continue
    report = {'tools': tools, 'bodies': [], 'valid': True, 'has_body': not build._is_empty(body), 'status': status}
    if not report['has_body']:
        return report
    report['valid'] = bool(BRepCheck_Analyzer(body).IsValid())
    faces = build._indexed(body, TopAbs_FACE)
    for solid in _parts(body, TopAbs_SOLID):
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(solid, props)
        owners = {}
        for face in _parts(solid, TopAbs_FACE):
            owner = ctx.owners.get(faces.FindIndex(face) - 1)
            if owner:
                owners[owner] = owners.get(owner, 0) + 1
        centre = props.CentreOfMass()
        report['bodies'].append({'volume': abs(float(props.Mass())), 'box': _box(solid),
                                 'center': [centre.X(), centre.Y(), centre.Z()],
                                 'features': sorted(owners, key=lambda key: -owners[key])})
    report['bodies'].sort(key=lambda item: -item['volume'])
    report['voids'] = len(_parts(body, TopAbs_SHELL)) - len(report['bodies'])
    rules = (data or {}).get('rules')
    if rules:
        report['pairs'], report['pairs_checked'] = pairs(ctx, rules)
    if rules and rules.get('proofing'):
        report['proof'] = proof(body)
    return report


def proof(body):
    """CNC 打样要看的整体形状 (genform/proofing.py): 包围盒、按最薄的方向当 Z 放平以后, 最高 / 最低那一层的截面占了外形多少。
    → {'box', 'axis' (哪根轴最薄: 0 / 1 / 2), 'top', 'bottom': 截面在另外两根轴上的 [宽, 长] (切不出来是 None)}。"""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    low, high = _box(body)
    size = [h - l for l, h in zip(low, high)]
    axis = min(range(3), key=lambda index: size[index])
    others = [index for index in range(3) if index != axis]
    out = {'box': [low, high], 'axis': axis}
    for key, level in (('top', high[axis] - min(0.05, size[axis] / 4)), ('bottom', low[axis] + min(0.05, size[axis] / 4))):
        point = [0.0, 0.0, 0.0]
        point[axis] = level
        normal = [0.0, 0.0, 0.0]
        normal[axis] = 1.0
        try:
            section = BRepAlgoAPI_Section(body, gp_Pln(gp_Pnt(*point), gp_Dir(*normal)))
            section.Build()
            shape = section.Shape()
            if shape is None or shape.IsNull() or not _parts(shape, TopAbs_EDGE):      # 截面是一圈边, 没有面
                out[key] = None
                continue
            a, b = _box(shape)
            out[key] = [b[index] - a[index] for index in others]
        except Exception:
            out[key] = None
    out['extent'] = [size[index] for index in others]
    return out


_PART_COPIES = 64           # 一个阵列最多拿前这么多份来比 (轮毂螺栓 5 × 4 个轮子就 20 份)
_BODY_SIZE = 2500.0         # 比这还大的加料工具体 (车身外形放样) 不算 "一个件": 它是整个车皮, 零件都装在它上面


def _pieces(ctx):
    """加料特征的工具体 → [(特征 id, 第几份, 实体, 包围盒)...]: 一张草图里的几块、阵列的每一份都分开。"""
    out = []
    for identifier, entry in (ctx.tools or {}).items():
        copies = entry if isinstance(entry, list) else [entry]
        for number, (solid, operation) in enumerate(copies[:_PART_COPIES]):
            if str(operation) != 'add' or solid is None or solid.IsNull():
                continue
            for part in _parts(solid, TopAbs_SOLID):
                box = _box(part)
                if max(high - low for low, high in zip(*box)) > _BODY_SIZE:
                    continue
                out.append((identifier, number, part, box))
    return out


def _near(a, b, margin):
    return all(a[0][axis] - margin <= b[1][axis] and b[0][axis] - margin <= a[1][axis] for axis in range(3))


def pairs(ctx, rules):
    """件与件的间隙和压入量 (见 genform/rules.py 的 clearance / overlap / tolerance)。
    → ([{'a', 'b' (特征 id), 'kind': 'gap' 间隙太小 / 'shallow' 压得太浅 / 'touch' 只是贴着, 'value' mm, 'point'}...], 比了几对)。"""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    clearance = float(rules.get('clearance', 0.5))
    overlap = float(rules.get('overlap', 0.3))
    tolerance = float(rules.get('tolerance', 0.1))
    gap_limit = max(clearance, tolerance * 2)
    depth_limit = max(overlap, tolerance * 2)
    limit = int(rules.get('pair_limit', 600))
    pieces = _pieces(ctx)
    candidates = []
    for i, (fa, na, sa, ba) in enumerate(pieces):
        for fb, nb, sb, bb in pieces[i + 1:]:
            if fa != fb and _near(ba, bb, gap_limit):
                candidates.append(((fa, na, sa, ba), (fb, nb, sb, bb)))
    found, worst = [], {}
    for (fa, na, sa, ba), (fb, nb, sb, bb) in candidates[:limit]:
        try:
            distance = BRepExtrema_DistShapeShape(sa, sb)
            if not distance.IsDone():
                continue
            gap = float(distance.Value())
            p, q = distance.PointOnShape1(1), distance.PointOnShape2(1)
            point = [(p.X() + q.X()) / 2, (p.Y() + q.Y()) / 2, (p.Z() + q.Z()) / 2]
            if gap > gap_limit:
                continue
            if gap > 1e-6:
                item = {'kind': 'gap', 'value': gap, 'point': point}
            else:
                common = BRepAlgoAPI_Common(sa, sb)
                common.Build()
                shape = common.Shape() if common.IsDone() else None
                if shape is None or shape.IsNull() or not _parts(shape, TopAbs_SOLID):
                    item = {'kind': 'touch', 'value': 0.0, 'point': point}
                else:
                    low, high = _box(shape)
                    depth = min(h - l for l, h in zip(low, high))
                    if depth >= depth_limit:
                        continue
                    item = {'kind': 'shallow', 'value': depth, 'point': [(l + h) / 2 for l, h in zip(low, high)]}
        except Exception:
            continue
        key = tuple(sorted((fa, fb)))
        item.update(a=key[0], b=key[1])
        if key not in worst or item['value'] < worst[key]['value']:       # 同一对特征 (阵列的几份) 只报最差的一处
            worst[key] = item
    found = sorted(worst.values(), key=lambda item: item['value'])
    return found, min(len(candidates), limit)
