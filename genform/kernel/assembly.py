# -*- coding: utf-8 -*-
"""装配体上的检查 (只读): 把几个零件按各自的位置摆到一起, 查干涉, 查按给定的顺序能不能一个个装进去,
查件与件是贴着装上的还是悬空的 (装配体的设计检查)。

零件的写法 (data['parts'] 里的每一项, 顺序就是装配顺序):
    {'name': 名称, 'path': .gform / .step / .stp 文件; 没有 path = 现在打开的这个零件,
     'move': [x, y, z] 平移 (mm), 'turn': [rx, ry, rz] 绕 X、Y、Z 依次转的角度 (度),
     'mirror': True = 先对零件自己的 XZ 面镜像 (y → -y): 左右对称的一对件 (左边的车灯 → 右边的), 再转、再挪,
     'swing': 运动副让它动了多少 (摆好以后再动): {'origin': 轴上一点, 'axis': 轴的方向, 'angle': 绕轴转的度数 (右手定则)
              或 'slide': 沿轴滑的距离 mm} — 车门开到 40°、车盖抬起来}
同一个文件在装配体里摆好几处 (四个车轮、二十颗螺栓): 文件只读、只算、只三角化一次 (_FILES, 按文件的修改时间认)。

装配顺序检查的做法: 第 k 个零件装的时候, 前 k-1 个已经在位。让它沿 ±X ±Y ±Z 六个方向从外面直线推进到最终位置,
一路上和已经装好的零件不相撞, 这个方向就算能装。六个方向都撞 = 按这个顺序装不进去。
没管的: 要斜着、转着才能装进去的; 螺丝刀、手伸不伸得进去; 零件有弹性可以掰开的卡扣。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time

import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepExtrema import BRepExtrema_DistShapeShape, BRepExtrema_ShapeProximity
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from . import build, store
from .occ_compat import _ShapeList
from .. import materials

DIRECTIONS = [('+X', (1, 0, 0)), ('-X', (-1, 0, 0)), ('+Y', (0, 1, 0)), ('-Y', (0, -1, 0)), ('+Z', (0, 0, 1)), ('-Z', (0, 0, -1))]
CLASH_VOLUME = 0.01             # 重叠体积超过这么多 (mm³) 才算干涉: 面贴面的接触算出来是零点零几
PATH_STEPS = (10, 36)           # 推进路径上最少 / 最多查多少个位置
PLAIN = (0.72, 0.74, 0.77)      # 零件没颜色也没材质时的颜色

_FILES = {}                     # 零件文件 (规范化的完整路径) → ((修改时间, 大小), {'shape', 'owners', 'origins', 'props', 'mesh'})
NEAR_MESH = 0.3                 # 设计检查粗筛用的网格精度 (mm): 网格离真的表面最多差这么多, 粗筛的范围各放宽两倍
_PLACED = {}                    # 零件的钥匙 (文件版本 + 摆放) → {'shape' 摆好的实体, 'box', 'meshed', 'faces' 有几张面}
_PAIRS = {}                     # 一对零件的钥匙 → 这一对的检查结果 (None = 离得远, 不用管); 也存在磁盘上 (_PAIRS_FILE)
_PAIRS_FILE = []                # [磁盘上那份的路径] (读过一次以后); 关了缓存是 [None]
KEEP_PAIRS = 20000              # 磁盘上最多记这么多对 (最近算的)


def _alone(features, upto):
    """算另一个零件文件的特征表, 不动现在打开的这个文档记着的中间步 (_STEPS / _SPARE): 不然回到文档又要从头算。
    磁盘缓存照用 (算过的零件第二次打开很快)。"""
    from .model import rebuild as model
    steps, spare = list(model._STEPS), list(model._SPARE)
    try:
        return model._rebuild(features, upto)
    finally:
        model._STEPS[:], model._SPARE[:] = steps, spare


def _part_file(path):
    """零件文件 → {'shape', 'owners', 'origins', 'props', 'mesh'}; 同一个文件没改过就用上次读的。"""
    full = os.path.abspath(str(path))
    try:
        stat = os.stat(full)
    except OSError as error:
        raise build.FeatureError(f'打不开 {path}：{error}') from None
    key, stamp = os.path.normcase(full), (stat.st_mtime_ns, stat.st_size)
    cached = _FILES.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    lower = full.lower()
    if lower.endswith('.gform'):
        try:
            with open(full, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError) as error:
            raise build.FeatureError(f'打不开 {path}：{error}') from None
        shape, ctx, _ = _alone(data.get('features') or [], data.get('upto'))
        record = {'shape': shape, 'owners': dict(ctx.owners), 'origins': dict(ctx.origins), 'props': data.get('props') or {}}
    elif lower.endswith(('.step', '.stp')):
        from .ops.importing import read_step       # 只有曲面的 STEP 也缝成实体 (和零件里的导入实体一样)
        shape, _ = read_step(full)
        record = {'shape': shape, 'owners': None, 'origins': None, 'props': {}}
    else:
        raise build.FeatureError('零件文件只认 .gform / .step / .stp')
    record['mesh'] = None
    _FILES[key] = (stamp, record)
    return record


def _record(part, features, upto):
    path = part.get('path')
    if path:
        record = _part_file(path)
    else:                               # 现在打开的这个零件
        shape, ctx, _ = build._rebuild(features, upto)
        record = {'shape': shape, 'owners': dict(ctx.owners), 'origins': dict(ctx.origins), 'props': part.get('props') or {},
                  'mesh': None}
    if record['shape'] is None or build._is_empty(record['shape']):
        raise build.FeatureError(f'“{part.get("name", path or "当前零件")}”里没有实体')
    return record


def _load(part, features, upto):
    return _record(part, features, upto)['shape']


def _transform(move=(0, 0, 0), turn=(0, 0, 0), mirror=False, swing=None):
    """先镜像 (对零件自己的 XZ 面), 再绕 X、Y、Z 依次转, 再平移; 最后是运动副的动作 (swing: 绕轴转 / 沿轴滑)。"""
    transform = gp_Trsf()
    if mirror:
        transform.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0)))
    for angle, axis in zip(turn, ((1, 0, 0), (0, 1, 0), (0, 0, 1))):
        if abs(float(angle)) > 1e-12:
            step = gp_Trsf()
            step.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*axis)), math.radians(float(angle)))
            transform = step.Multiplied(transform)
    shift = gp_Trsf()
    shift.SetTranslation(gp_Vec(*(float(value) for value in move)))
    transform = shift.Multiplied(transform)
    motion = _swing(swing)
    return motion.Multiplied(transform) if motion is not None else transform


def _swing(swing):
    """运动副的动作 → gp_Trsf (没动是 None)。"""
    if not swing:
        return None
    origin, axis = [float(value) for value in swing['origin']], np.asarray(swing['axis'], float)
    if np.linalg.norm(axis) < 1e-12:
        return None
    motion = gp_Trsf()
    if swing.get('slide') is not None:
        if abs(float(swing['slide'])) < 1e-12:
            return None
        motion.SetTranslation(gp_Vec(*(axis / np.linalg.norm(axis) * float(swing['slide']))))
    else:
        if abs(float(swing.get('angle') or 0.0)) < 1e-12:
            return None
        motion.SetRotation(gp_Ax1(gp_Pnt(*origin), gp_Dir(*axis)), math.radians(float(swing['angle'])))
    return motion


def _where(part):
    return part.get('move', (0, 0, 0)), part.get('turn', (0, 0, 0)), bool(part.get('mirror')), part.get('swing') or None


def _placed(shape, move=(0, 0, 0), turn=(0, 0, 0), mirror=False, swing=None):
    return BRepBuilderAPI_Transform(shape, _transform(move, turn, mirror, swing), True).Shape()


def _matrix(move=(0, 0, 0), turn=(0, 0, 0), mirror=False, swing=None):
    """和 _transform 一样的变换 → (3×3 矩阵, 平移), 给网格的顶点用。"""
    transform = _transform(move, turn, mirror, swing)
    rows = np.array([[transform.Value(row, column) for column in range(1, 5)] for row in range(1, 4)])
    return rows[:, :3], rows[:, 3]


def _mesh(record):
    """零件文件的显示网格 (只算一次): 顶点、法向、三角形、每个顶点的颜色 (特征单独上的色 > 零件的颜色 > 材质的颜色), 透明度。"""
    if record['mesh'] is not None:
        return record['mesh']
    verts, normals, tris, tri_face, faces = build.tessellate(record['shape'], record['owners'], record['origins'])
    props = record['props']
    base = materials.rgb(props.get('color')) or materials.rgb(materials.color(props.get('material'))) or PLAIN
    painted = {key: materials.rgb(value) for key, value in (props.get('feature_colors') or {}).items() if materials.rgb(value)}
    shades = props.get('feature_opacity') or {}
    colors, alphas = [], []
    for info in faces:
        owner, origin = info.get('feature'), info.get('origin')
        colors.append(painted.get(owner) or painted.get(origin) or base)
        alphas.append(float(shades.get(owner, shades.get(origin, 1.0))))
    tints = np.tile(np.array(base, dtype=np.float32), (len(verts), 1))
    if len(tris) and colors:
        tints[np.asarray(tris).reshape(-1)] = np.repeat(np.array(colors, dtype=np.float32)[np.asarray(tri_face)], 3, axis=0)
    alpha = min(alphas) if alphas and max(alphas) < 1.0 else 1.0       # 整个零件都是半透明的 (玻璃): 画成半透明
    record['mesh'] = {'verts': np.asarray(verts, dtype=np.float64), 'normals': np.asarray(normals, dtype=np.float64),
                      'tris': np.asarray(tris), 'tints': tints, 'alpha': alpha}
    return record['mesh']


def _shift(shape, offset):
    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(*(float(value) for value in offset)))
    return BRepBuilderAPI_Transform(shape, transform, False).Shape()     # 只挪位置, 不拷几何: 一路上要挪很多次


def _parts(features, upto, data, least=2):
    parts = data.get('parts') or []
    if len(parts) < least:
        raise build.FeatureError('装配体里至少要有两个零件')
    shapes = [_placed(_load(part, features, upto), *_where(part)) for part in parts]
    names = [part.get('name') or f'零件{number + 1}' for number, part in enumerate(parts)]
    boxes = [tuple(np.array(corner) for corner in build.bounds(shape)) for shape in shapes]
    return shapes, names, boxes


def _boxes_touch(first, second, gap=0.0):
    return bool(np.all(first[0] <= second[1] + gap) and np.all(second[0] <= first[1] + gap))


def _common(first, second):
    """两个实体的布尔求交: 面和面的求交分到几个核上算 (整车的设计检查快五六倍), 不改动传进来的实体。"""
    maker = BRepAlgoAPI_Common()
    arguments, tools = _ShapeList(), _ShapeList()
    arguments.Append(first)
    tools.Append(second)
    maker.SetArguments(arguments)
    maker.SetTools(tools)
    maker.SetNonDestructive(True)
    maker.SetRunParallel(True)
    maker.Build()
    return maker


def _overlap(first, second, depth=False):
    """两个实体重叠的体积 (mm³) 和重叠部分的中心; 布尔运算失败时当作不重叠。
    depth=True 再给压进去多深: 重叠那块的平均厚度 2·体积/表面积 (薄板就是板厚), 和包围盒最薄的方向取小的。
    面贴面的接触 (玻璃嵌在窗框里、螺栓在孔里) 算出来的重叠是一层几乎没有厚度的薄壳, 体积可能有零点几, 但厚度是零;
    包围盒对弯的薄壳 (圆孔里那一圈) 不管用, 所以要看平均厚度。"""
    try:
        maker = _common(first, second)
        if not maker.IsDone() or build._is_empty(maker.Shape()):
            return (0.0, None, 0.0) if depth else (0.0, None)
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(maker.Shape(), props)
        centre = props.CentreOfMass()
        volume, middle = abs(float(props.Mass())), [centre.X(), centre.Y(), centre.Z()]
        if not depth:
            return volume, middle
        low, high = build.bounds(maker.Shape())
        surface = GProp_GProps()
        BRepGProp.SurfaceProperties_s(maker.Shape(), surface)
        thickness = 2.0 * volume / surface.Mass() if surface.Mass() > 1e-12 else 0.0
        return volume, middle, min(float(np.min(np.asarray(high) - np.asarray(low))), thickness)
    except Exception:
        return (0.0, None, 0.0) if depth else (0.0, None)


def _measure(first, second):
    meter = BRepExtrema_DistShapeShape()
    meter.SetMultiThread(True)          # 几个核一起算 (大灯对车身这种几十张曲面的: 快三四倍)
    meter.LoadS1(first)
    meter.LoadS2(second)
    meter.Perform()
    if not meter.IsDone() or meter.NbSolution() == 0:
        return None, None
    point = meter.PointOnShape1(1)
    return float(meter.Value()), [point.X(), point.Y(), point.Z()]


def _near_faces(shape, low, high, reach):
    """shape 上包围盒挨着 [low, high] (各边放宽 reach) 的面。"""
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    box = (np.asarray(low, float) - reach, np.asarray(high, float) + reach)
    explorer, found = TopExp_Explorer(shape, TopAbs_FACE), []
    while explorer.More():
        face = explorer.Current()
        corners = tuple(np.asarray(corner, float) for corner in build.bounds(face))
        if _boxes_touch(corners, box):
            found.append(face)
        explorer.Next()
    return found


def _distance(first, second, reach=1.0):
    """两个实体表面之间最近的距离和那一点 (第一个实体上的); 算不出来是 (None, None)。
    整个算失败的 (OCC 对大的空心车身有时直接报 NotDone): 只拿 first 上挨着 second 的那些面一张张算, 取最近的。"""
    try:
        return _measure(first, second)
    except Exception:
        pass
    low, high = build.bounds(second)
    best = (None, None)
    for face in _near_faces(first, low, high, reach):
        try:
            found = _measure(face, second)
        except Exception:
            continue
        if found[0] is not None and (best[0] is None or found[0] < best[0]):
            best = found
    return best


def meshes(features, upto, data):
    """每个零件摆好以后的显示网格 → [{'name', 'verts', 'normals', 'tris', 'tints' 每个顶点的颜色, 'alpha', 'low', 'high'}...]。
    同一个文件只三角化一次, 摆在别处的只变换顶点; 镜像的翻一下三角形的绕向。
    一个个零件报进度 (界面的加载条: 第几个零件、它正在算哪个特征), 重算零件文件时的特征进度也转成这个。"""
    from .model import rebuild as steps
    result, outer = [], steps.on_step
    parts = data.get('parts') or []
    for number, part in enumerate(parts):
        name = part.get('name') or f'零件{number + 1}'
        if outer is not None:
            outer(number, len(parts), name, 'parts')
            steps.on_step = lambda index, total, feature, number=number, name=name: outer(number, len(parts), f'{name} · {feature}', 'parts')
        try:
            mesh = _mesh(_record(part, features, upto))
        finally:
            steps.on_step = outer
        rotation, offset = _matrix(*_where(part))
        verts = (mesh['verts'] @ rotation.T + offset).astype(np.float32)
        normals = (mesh['normals'] @ rotation.T).astype(np.float32)
        tris = mesh['tris'] if np.linalg.det(rotation) > 0 else np.ascontiguousarray(mesh['tris'][:, ::-1])
        low = verts.min(axis=0).tolist() if len(verts) else [0.0] * 3
        high = verts.max(axis=0).tolist() if len(verts) else [0.0] * 3
        result.append({'name': part.get('name') or f'零件{number + 1}', 'verts': verts, 'normals': normals, 'tris': tris,
                       'tints': mesh['tints'], 'alpha': mesh['alpha'], 'low': low, 'high': high})
    return result


def export(features, upto, data):
    """把摆好的各个零件写成一个 STEP 文件 (data['path']): 一个零件一个实体, 位置就是装配体里的位置。"""
    from OCP.BRep import BRep_Builder
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.TopoDS import TopoDS_Compound
    parts = data.get('parts') or []
    if not parts:
        raise build.FeatureError('装配体里还没有零件')
    builder, whole = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(whole)
    for part in parts:
        builder.Add(whole, _placed(_load(part, features, upto), *_where(part)))
    writer = STEPControl_Writer()
    writer.Transfer(whole, STEPControl_AsIs)
    if writer.Write(str(data['path'])) != IFSelect_RetDone:
        raise build.FeatureError('写 STEP 文件失败')
    return {'parts': len(parts)}


def interference(features, upto, data):
    """干涉检查: 两两求重叠 → {'clashes': [{'a', 'b' 零件序号, 'names', 'volume' mm³, 'center'}...], 'pairs': 查了多少对}。"""
    shapes, names, boxes = _parts(features, upto, data)
    clashes, pairs = [], 0
    for first in range(len(shapes)):
        for second in range(first + 1, len(shapes)):
            pairs += 1
            if not _boxes_touch(boxes[first], boxes[second]):
                continue
            volume, centre = _overlap(shapes[first], shapes[second])
            if volume > CLASH_VOLUME:
                clashes.append({'a': first, 'b': second, 'names': [names[first], names[second]], 'volume': volume, 'center': centre})
    return {'clashes': clashes, 'pairs': pairs}


# ---- 装配体的设计检查 ----
def _part_key(part, features, upto):
    """零件在装配体里的钥匙: 哪个文件的哪一版 (路径、修改时间、大小; 现在打开的零件看它的特征表) + 摆在哪。
    钥匙一样 = 摆好的实体一样, 和别的零件的检查结果可以照用。文件打不开是 None (不缓存)。"""
    move, turn, mirror, swing = _where(part)
    place = ([round(float(value), 6) for value in move], [round(float(value), 6) for value in turn], bool(mirror))
    motion = _swing(swing)
    if motion is not None:              # 运动副动过: 钥匙里带上它 (开着门和关着门是两种摆法)
        place += ([round(motion.Value(row, column), 9) for row in range(1, 4) for column in range(1, 5)],)
    where = part.get('path')
    if where:
        full = os.path.normcase(os.path.abspath(str(where)))
        try:
            info = os.stat(full)
        except OSError:
            return None
        source = [full, info.st_mtime_ns, info.st_size]
    else:
        source = ['', hashlib.sha1(json.dumps([features, upto], sort_keys=True, default=str).encode()).hexdigest()]
    return json.dumps([source, place])


def _placed_part(part, key, features, upto):
    """摆好的零件 (同一个钥匙只摆一次, 网格也只三角化一次): {'shape', 'box', 'meshed', 'faces'}。"""
    item = _PLACED.get(key) if key is not None else None
    if item is None:
        shape = _placed(_load(part, features, upto), *_where(part))
        item = {'shape': shape, 'box': tuple(np.array(corner) for corner in build.bounds(shape)), 'meshed': False, 'faces': None}
        if key is not None:
            _PLACED[key] = item
    return item


def _meshed(item):
    """粗筛要网格: 摆好的实体三角化一次; 有张面没网格 (三角化失败) 就记 'faces' = -1, 这个零件不粗筛, 直接精确算。"""
    if item['meshed']:
        return item
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from .occ_compat import _as_face
    BRepMesh_IncrementalMesh(item['shape'], NEAR_MESH, False, 0.3, True)
    explorer, count, bare = TopExp_Explorer(item['shape'], TopAbs_FACE), 0, False
    while explorer.More():
        count += 1
        if BRep_Tool.Triangulation_s(_as_face(explorer.Current()), TopLoc_Location()) is None:
            bare = True
        explorer.Next()
    item['meshed'], item['faces'] = True, -1 if bare else count
    return item


def _gather(found, get, count):
    """粗筛结果里挨着的那几张面 → 一个复合体 (没有是 None)。"""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    builder, whole, any_face = BRep_Builder(), TopoDS_Compound(), False
    builder.MakeCompound(whole)
    for index in range(count):
        if found.IsBound(index):
            builder.Add(whole, get(index))
            any_face = True
    return whole if any_face else None


def _pair_result(first, second, filters, tolerance, clearance):
    """一对零件 (包围盒挨着的) 是什么关系 → {'kind': 'clash' / 'touch' / 'gap', 'distance', 'volume', 'depth', 'point'};
    离得比最小间隙还远是 None。先在网格上粗筛 (几毫秒): 网格上都隔得远, 真的表面也远, 不用精确算 —
    车身的包围盒套着刹车盘、轮辋、方向盘, 原来每一对都要精确算十几秒。挨得近的只拿挨着的那几张面去精确求距离。"""
    reach = clearance + 2 * NEAR_MESH + 0.1
    shapes = (first['shape'], second['shape'])
    if _meshed(first)['faces'] > 0 and _meshed(second)['faces'] > 0:
        probe = filters.get(id(first))
        if probe is None:               # 第一个零件的网格树建一次, 和后面的一个个比
            probe = filters[id(first)] = BRepExtrema_ShapeProximity(reach)
            probe.LoadShape1(first['shape'])
        probe.LoadShape2(second['shape'])
        probe.Perform()
        if not probe.IsDone():          # 两边的网格树连最外面的包围盒都不挨着 (IsDone 只说算没算完, 不说挨没挨着)
            return None
        exact = BRepExtrema_ShapeProximity(reach)       # 挨着的面: 新开一个 (复用的那个会把以前挨着的面也攒着)
        exact.LoadShape1(first['shape'])
        exact.LoadShape2(second['shape'])
        exact.Perform()
        near = (_gather(exact.OverlapSubShapes1(), exact.GetSubShape1, first['faces']),
                _gather(exact.OverlapSubShapes2(), exact.GetSubShape2, second['faces'])) if exact.IsDone() else (None, None)
        if near[0] is None or near[1] is None:          # 网格上没有一对三角形挨着: 真的表面也隔得远
            return None
        shapes = near
    distance, point = _distance(shapes[0], shapes[1], clearance + 1.0)
    if distance is None or distance > clearance:
        return None
    if distance <= tolerance:
        volume, centre, depth = _overlap(first['shape'], second['shape'], depth=True)
        kind = 'clash' if volume > CLASH_VOLUME and depth > tolerance else 'touch'
        return {'kind': kind, 'distance': distance, 'volume': volume, 'depth': depth,
                'point': centre if kind == 'clash' and centre else point}
    return {'kind': 'gap', 'distance': distance, 'volume': 0.0, 'depth': 0.0, 'point': point}


def _pair_key(first, second, tolerance, clearance):
    if first is None or second is None:
        return None
    first, second = sorted((first, second))     # 和先后无关: 挪了装配顺序不用重算
    return hashlib.sha1(f'{first}|{second}|{tolerance:g}|{clearance:g}'.encode()).hexdigest()


def _pairs_file():
    """磁盘上记着的各对检查结果: 第一次用时读进来; 文件名带内核的印记 (算法改了旧结果自然不用)。"""
    if not _PAIRS_FILE:
        folder = store.folder()
        where = os.path.join(folder, f'contacts-{store.stamp()}.json') if folder else None
        _PAIRS_FILE.append(where)
        if where and os.path.isfile(where):
            try:
                with open(where, 'r', encoding='utf-8') as handle:
                    saved = json.load(handle)
                for key, value in saved.items():
                    _PAIRS.setdefault(key, value)
            except (OSError, ValueError):
                pass
    return _PAIRS_FILE[0]


def _save_pairs():
    where = _pairs_file()
    if not where:
        return
    rows = list(_PAIRS.items())[-KEEP_PAIRS:]
    try:
        with open(where + '.tmp', 'w', encoding='utf-8') as handle:
            json.dump(dict(rows), handle, separators=(',', ':'))
        os.replace(where + '.tmp', where)
    except OSError:
        pass


def contacts(features, upto, data):
    """装配体的设计检查: 件与件之间是什么关系, 哪些零件没装在任何东西上。
    data['rules']: 'tolerance' (多近算贴上, mm)、'clearance' (不贴着的两个件最少要隔开多少)。
    data['budget']: 这一趟最多算几秒 (界面分段算, 中间让别的活插进来; 不给 = 一口气算完)。
    data['links']: [[a, b]...] 运动副连着的两件 (车门和车身): 算连上 — 门开着、铰链那面不贴了也不算悬空。
    每一对的结果按两个零件的钥匙 (文件版本 + 摆放) 记着 (内存和磁盘): 再查一遍、挪了一个零件以后只算变了的那几对。
    → {'pairs': [{'a', 'b', 'kind': 'clash' 压进去了 (重叠的体积和深度都超过公差) / 'touch' 贴着 (装配面) /
                  'gap' 没贴上但比最小间隙近, 'distance', 'volume', 'depth' 压进去多深, 'point'}...],
       'floating': [零件序号...] 和第一个零件 (底座、车身) 连不上的: 贴着 / 压着算连上, 一个挨一个地传过去,
       'checked': 查了多少对, 'partial': 这一趟没算完 (到了 budget; 'done' / 'total' 对), 'fresh': 这一趟新算了几对}"""
    from .model import rebuild as steps
    rules = data.get('rules') or {}
    tolerance = float(rules.get('tolerance', 0.1))
    clearance = max(float(rules.get('clearance', 0.5)), tolerance)
    budget = data.get('budget')
    parts = data.get('parts') or []
    if not parts:
        raise build.FeatureError('装配体里至少要有两个零件')
    began = time.perf_counter()
    _pairs_file()
    keys = [_part_key(part, features, upto) for part in parts]
    items = [_placed_part(part, key, features, upto) for part, key in zip(parts, keys)]
    for key in [key for key in _PLACED if key not in set(keys)]:     # 不在这个装配体里的: 不白占内存
        del _PLACED[key]
    names = [part.get('name') or f'零件{number + 1}' for number, part in enumerate(parts)]
    candidates = [(first, second) for first in range(len(items)) for second in range(first + 1, len(items))
                  if _boxes_touch(items[first]['box'], items[second]['box'], clearance)]
    pairs, filters, fresh, done = [], {}, 0, len(candidates)
    linked = {index: set() for index in range(len(items))}
    for first, second in data.get('links') or ():
        if 0 <= first < len(items) and 0 <= second < len(items):
            linked[first].add(second)
            linked[second].add(first)
    for number, (first, second) in enumerate(candidates):
        key = _pair_key(keys[first], keys[second], tolerance, clearance)
        if key is not None and key in _PAIRS:
            found = _PAIRS[key]
        else:
            if budget is not None and fresh and time.perf_counter() - began > float(budget):
                done = number
                break
            if steps.on_step is not None:       # 报进度: 让看门狗知道还在算 (不然两分钟就当卡死了); 不带 'parts', 不弹加载条
                steps.on_step(number, len(candidates), f'{names[first]} ↔ {names[second]}')   # (查到哪了界面看每段的回话)
            found = _pair_result(items[first], items[second], filters, tolerance, clearance)
            fresh += 1
            if key is not None:
                _PAIRS[key] = found
        if found is None:
            continue
        if found['kind'] in ('clash', 'touch'):
            linked[first].add(second)
            linked[second].add(first)
        pairs.append(dict(found, a=first, b=second, names=[names[first], names[second]]))
    if fresh:
        _save_pairs()
    reached, waiting = {0}, [0]
    while waiting:
        for other in linked[waiting.pop()]:
            if other not in reached:
                reached.add(other)
                waiting.append(other)
    return {'pairs': pairs, 'floating': [index for index in range(len(items)) if index not in reached], 'checked': len(candidates),
            'partial': done < len(candidates), 'done': done, 'total': len(candidates), 'fresh': fresh}


def measure_parts(features, upto, data):
    """装配体里的测量 (评估页 → 测量, 点零部件): 一个 → {'size' 包围盒的长宽高, 'low', 'high', 'volume' mm³, 'area' mm²};
    两个 → 再加 {'distance' 两个零件表面之间最短的距离, 'points' 两个最近点, 'delta' 这两点在 X / Y / Z 上各差多少}。"""
    parts = data.get('parts') or []
    if not 1 <= len(parts) <= 2:
        raise build.FeatureError('测量要点一个或两个零部件')
    items = [_placed_part(part, _part_key(part, features, upto), features, upto) for part in parts]
    rows = []
    for item in items:
        volume, surface = GProp_GProps(), GProp_GProps()
        BRepGProp.VolumeProperties_s(item['shape'], volume)
        BRepGProp.SurfaceProperties_s(item['shape'], surface)
        low, high = (np.asarray(corner, float) for corner in item['box'])
        rows.append({'size': (high - low).tolist(), 'low': low.tolist(), 'high': high.tolist(),
                     'volume': abs(float(volume.Mass())), 'area': float(surface.Mass())})
    result = {'items': rows}
    if len(items) == 2:
        meter = BRepExtrema_DistShapeShape()
        meter.SetMultiThread(True)
        meter.LoadS1(items[0]['shape'])
        meter.LoadS2(items[1]['shape'])
        meter.Perform()
        if not meter.IsDone() or meter.NbSolution() == 0:
            raise build.FeatureError('这两个零件之间的距离算不出来')
        first, second = meter.PointOnShape1(1), meter.PointOnShape2(1)
        points = [[first.X(), first.Y(), first.Z()], [second.X(), second.Y(), second.Z()]]
        result.update(distance=float(meter.Value()), points=points, delta=[b - a for a, b in zip(*points)])
    return result


def sweep(features, upto, data):
    """运动干涉 (设计检查): 每个运动副从关着开到头, 在 data['joints'][k]['values'] 这几个位置上, 查跟着动的件撞不撞别的件。
    data: {'parts' (关着的样子), 'joints': [{'parts', 'origin', 'axis', 'kind', 'values'}...], 'rules'}。
    → [{'joint', 'value', 'a' 动的件, 'b' 被撞的件, 'names', 'depth', 'volume', 'point'}...] (每个运动副和每个被撞的件只报
    最先撞上的那个位置)。每一对的结果和设计检查共用一份缓存。"""
    from .model import rebuild as steps
    rules = data.get('rules') or {}
    tolerance = float(rules.get('tolerance', 0.1))
    clearance = max(float(rules.get('clearance', 0.5)), tolerance)
    parts = data.get('parts') or []
    names = [part.get('name') or f'零件{number + 1}' for number, part in enumerate(parts)]
    _pairs_file()
    base_keys = [_part_key(part, features, upto) for part in parts]
    base = [_placed_part(part, key, features, upto) for part, key in zip(parts, base_keys)]
    jobs = [(number, joint, value) for number, joint in enumerate(data.get('joints') or []) for value in joint.get('values') or ()]
    found, fresh, seen = [], 0, set()
    for step, (number, joint, value) in enumerate(jobs):
        if steps.on_step is not None:
            steps.on_step(step, len(jobs), f'{joint.get("name") or "运动副"} {value:g}', 'motion')
        swing = {'origin': joint['origin'], 'axis': joint['axis'], ('slide' if joint.get('kind') == 'slide' else 'angle'): float(value)}
        moving = [index for index in joint['parts'] if 0 <= index < len(parts)]
        keys, items = list(base_keys), list(base)
        for index in moving:
            posed = dict(parts[index], swing=swing)
            keys[index] = _part_key(posed, features, upto)
            items[index] = _placed_part(posed, keys[index], features, upto)
        filters = {}
        for first in moving:
            for second in range(len(parts)):
                if second in moving or (number, second) in seen:
                    continue
                if not _boxes_touch(items[first]['box'], items[second]['box'], clearance):
                    continue
                key = _pair_key(keys[first], keys[second], tolerance, clearance)
                if key is not None and key in _PAIRS:
                    result = _PAIRS[key]
                else:
                    result = _pair_result(items[first], items[second], filters, tolerance, clearance)
                    fresh += 1
                    if key is not None:
                        _PAIRS[key] = result
                if result and result['kind'] == 'clash':
                    seen.add((number, second))
                    found.append({'joint': number, 'value': float(value), 'a': first, 'b': second, 'names': [names[first], names[second]],
                                  'depth': result['depth'], 'volume': result['volume'], 'point': result['point']})
    if fresh:
        _save_pairs()
    for key in [key for key in _PLACED if key not in set(base_keys)]:      # 转过去的那些摆法不留着占内存
        del _PLACED[key]
    return found


def mass_props(features, upto, data):
    """各零件摆好以后的体积和重心 → [{'volume' mm³, 'centre' [x, y, z]}...] (算重量: 乘材质的密度; 整车的重心、前后配重)。
    按零件的钥匙记着 (摆法没变不重算)。"""
    rows = []
    for part in data.get('parts') or []:
        key = _part_key(part, features, upto)
        item = _placed_part(part, key, features, upto)
        if item.get('mass') is None:
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(item['shape'], props)
            centre = props.CentreOfMass()
            item['mass'] = {'volume': abs(float(props.Mass())), 'centre': [centre.X(), centre.Y(), centre.Z()]}
        rows.append(dict(item['mass']))
    return rows


def sequence(features, upto, data):
    """装配顺序检查 → {'steps': [{'index', 'name', 'ok', 'directions': 能装进去的方向, 'blocked': {方向: 挡路的零件名},
                                  'clash': 最终位置上和谁干涉 (没有是 None)}...], 'ok': 是不是全都装得进去}。"""
    shapes, names, boxes = _parts(features, upto, data)
    steps = [{'index': 0, 'name': names[0], 'ok': True, 'directions': [label for label, _ in DIRECTIONS], 'blocked': {}, 'clash': None}]
    for index in range(1, len(shapes)):
        part, box = shapes[index], boxes[index]
        step = {'index': index, 'name': names[index], 'ok': False, 'directions': [], 'blocked': {}, 'clash': None}
        steps.append(step)
        for other in range(index):                      # 先看最终位置: 本来就干涉的, 谈不上装
            if _boxes_touch(box, boxes[other]) and _overlap(part, shapes[other])[0] > CLASH_VOLUME:
                step['clash'] = names[other]
                break
        if step['clash']:
            continue
        low = np.min([boxes[other][0] for other in range(index)], axis=0)
        high = np.max([boxes[other][1] for other in range(index)], axis=0)
        finest = max(float(np.min(box[1] - box[0])), 1.0) / 2       # 每一步挪半个零件最薄的尺寸: 不会跨过去漏掉
        for label, direction in DIRECTIONS:
            direction = np.array(direction, dtype=float)
            # 沿这个方向退出去, 退到整个零件都在已装好的零件外面
            if direction.sum() > 0:
                travel = float(((high - box[0]) * direction).sum())
            else:
                travel = float(((low - box[1]) * direction).sum())
            if travel <= 0:
                step['directions'].append(label)
                continue
            travel += 1.0
            count = int(min(PATH_STEPS[1], max(PATH_STEPS[0], math.ceil(travel / finest))))
            blocker = None
            for number in range(1, count + 1):
                offset = direction * travel * number / count
                moved = _shift(part, offset)
                moved_box = (box[0] + offset, box[1] + offset)
                for other in range(index):
                    if _boxes_touch(moved_box, boxes[other]) and _overlap(moved, shapes[other])[0] > CLASH_VOLUME:
                        blocker = names[other]
                        break
                if blocker:
                    break
            if blocker:
                step['blocked'][label] = blocker
            else:
                step['directions'].append(label)
        step['ok'] = bool(step['directions'])
    return {'steps': steps, 'ok': all(step['ok'] for step in steps)}
