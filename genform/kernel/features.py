# -*- coding: utf-8 -*-
"""features.py (特征表) 里登记的每种特征怎么算。和 build.py 一样只在内核这边用, 输入输出都是 OpenCascade 的形体。

四类:
    MAKERS     造一个 "工具体", 再按 op 和现有实体合并 / 切除 / 求交 (旋转、扫描、放样、孔…) — 工具体留着, 阵列和镜像复制的就是它
    MODIFIERS  直接改现有实体 (筋、拔模、抽壳、包裹、分割线、螺纹线、各种阵列)
    CURVES     得到一条空间曲线, 可以作扫描路径
    REFERENCES 参考几何体: 只产生显示用的线, 不改实体
"""
from __future__ import annotations

import math

import numpy as np

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_CompCurve, BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon,
                                BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform)
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import (BRepOffsetAPI_DraftAngle, BRepOffsetAPI_MakeOffsetShape, BRepOffsetAPI_MakePipe,
                               BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_MakeThickSolid, BRepOffsetAPI_ThruSections)
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GProp import GProp_GProps
from OCP.GeomAPI import GeomAPI_Interpolate
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_SOLID, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec

from .. import features as table
from .. import planes, sketchgeom
from . import build
from .build import FeatureError

try:
    from OCP.TopTools import TopTools_ListOfShape as _ShapeList
    from OCP.TColgp import TColgp_HArray1OfPnt as _PointHandleArray
except ImportError:                     # OCP 8
    from OCP.collections import HArray1_gp_Pnt as _PointHandleArray
    from OCP.collections import List_TopoDS_Shape as _ShapeList
_as_wire = getattr(TopoDS, 'Wire_s', None) or TopoDS.Wire
_as_solid = getattr(TopoDS, 'Solid_s', None) or TopoDS.Solid


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _pnt(point):
    return gp_Pnt(float(point[0]), float(point[1]), float(point[2]))


def _dir(vector):
    return gp_Dir(float(vector[0]), float(vector[1]), float(vector[2]))


def _vec(vector):
    return gp_Vec(float(vector[0]), float(vector[1]), float(vector[2]))


def _xyz(point):
    return np.array([point.X(), point.Y(), point.Z()])


def _number(params, key, positive=False, least=None):
    try:
        value = float(params.get(key))
    except (TypeError, ValueError):
        raise FeatureError(f'参数 {key} 不是数字') from None
    if not math.isfinite(value) or (positive and value <= 0) or (least is not None and value < least):
        raise FeatureError(f'参数 {key} 必须{"是正数" if positive else f"不小于 {least:g}"}，现在是 {value:g}')
    return value


def _shape_list(shapes):
    items = _ShapeList()
    for shape in shapes:
        items.Append(shape)
    return items


def _explore(shape, kind):
    found, explorer = [], TopExp_Explorer(shape, kind)
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def _moved(shape, transform):
    return BRepBuilderAPI_Transform(shape, transform, True).Shape()


def _translation(vector):
    transform = gp_Trsf()
    transform.SetTranslation(_vec(vector))
    return transform


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props


def _centroid(shape):
    return _xyz(_volume(shape).CentreOfMass())


def _reach(body):
    """足够长的一段: 比实体的对角线长, 用来做 "贯穿"。"""
    return (build._model_size(body) if not build._is_empty(body) else 100.0) * 2 + 10.0


def _need_body(body, what):
    if build._is_empty(body):
        raise FeatureError(f'还没有实体，无法{what}')


def _sketch(ctx, params, key='sketch'):
    identifier = params.get(key)
    if identifier not in ctx.sketches:
        raise FeatureError(f'找不到草图 {identifier!r}（可能被删除、抑制或出错了；参数 {key} 要写草图特征的 id）')
    return ctx.sketches[identifier]


def _profile(ctx, params, key='sketch'):
    sketch = _sketch(ctx, params, key)
    if sketch.profile is None:
        raise FeatureError('这个草图里没有封闭轮廓：线要首尾相接围成一圈（草图页的“修复草图”能找出没接上的地方）')
    return sketch


def _wire(edges, what='路径'):
    maker = BRepBuilderAPI_MakeWire()
    maker.Add(_shape_list(edges))
    if not edges or not maker.IsDone():
        raise FeatureError(f'{what}的线要首尾相接连成一条（不能断开或分叉）')
    return maker.Wire()


def _path(ctx, identifier, what='路径'):
    if identifier in ctx.curves:
        return ctx.curves[identifier]
    if identifier in ctx.sketches:
        return _wire(_explore(ctx.sketches[identifier].curves, TopAbs_EDGE), what)
    raise FeatureError(f'找不到{what} {identifier!r}（要写草图或曲线特征的 id）')


def _axis(ctx, ref, sketch_frame=None):
    try:
        return table.axis_of(ref, ctx.features, sketch_frame)
    except ValueError as error:
        raise FeatureError(str(error)) from None


def _frame(ctx, ref, offset=0.0):
    try:
        return planes.frame(table.plane_frame(ref, ctx.features), offset)
    except ValueError as error:
        raise FeatureError(str(error)) from None


def _spots(sketch):
    """草图里的点和圆心 → 三维坐标。"""
    origin, x_dir, y_dir, _ = sketch.frame
    found = []
    for shape in sketch.shapes:
        if shape.get('type') == 'point':
            found.append(origin + x_dir * float(shape['x']) + y_dir * float(shape['y']))
        elif shape.get('type') in ('circle', 'arc'):
            found.append(origin + x_dir * float(shape.get('cx', 0.0)) + y_dir * float(shape.get('cy', 0.0)))
    if not found:
        raise FeatureError('位置草图里没有点：用草图页的“点”工具放几个点（圆的圆心也算）')
    return found


def _faces(body, refs, what, count=None):
    """特征里写的面引用 [{'point': 面中心}...] → 实体上的面。"""
    mapping = build._indexed(body, TopAbs_FACE)
    centres, faces = [], []
    for index in range(1, mapping.Extent() + 1):
        face = build._as_face(mapping.FindKey(index))
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        centres.append(_xyz(props.CentreOfMass()))
        faces.append(face)
    chosen = []
    for ref in refs or ():
        point = ref.get('point') if isinstance(ref, dict) else None
        if point is None or len(point) != 3:
            raise FeatureError('面的引用要写成 {"point": [x, y, z]}（面中心坐标，用 list_faces 查）')
        gaps = np.linalg.norm(np.array(centres) - np.array(point, dtype=float), axis=1)
        nearest = int(gaps.argmin())
        if gaps[nearest] > 0.25 * build._model_size(body):
            raise FeatureError('引用的面找不到了（前面的特征改动后这个面可能已经消失），请重新选择面')
        if not any(faces[nearest].IsSame(face) for face in chosen):
            chosen.append(faces[nearest])
    if count is not None and len(chosen) != count:
        raise FeatureError(f'{what}要正好选 {count} 个面，现在是 {len(chosen)} 个')
    return chosen


def _spline(points, closed=False):
    if len(points) < 2:
        raise FeatureError('曲线至少要 2 个点')
    array = _PointHandleArray(1, len(points))
    for index, point in enumerate(points):
        array.SetValue(index + 1, _pnt(point))
    maker = GeomAPI_Interpolate(array, bool(closed), 1e-6)
    maker.Perform()
    if not maker.IsDone():
        raise FeatureError('这些点连不成光顺的曲线（有重合的点？）')
    return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(maker.Curve()).Edge()).Wire()


def _run(maker, what):
    """跑一个 OpenCascade 的造型算法; 它做不出来时给一句人话。"""
    try:
        maker.Build()
        shape = maker.Shape() if maker.IsDone() else None
    except Exception:
        shape = None
    if shape is None or shape.IsNull():
        raise FeatureError(what)
    return shape


# ---------------------------------------------------------------------------
# 造工具体的特征
# ---------------------------------------------------------------------------
def revolve(body, params, ctx):
    sketch = _profile(ctx, params)
    if str(params.get('axis', 'SY')).upper() == 'CL':       # 草图里的第一条中心线 (构造线)
        line = next((shape for shape in sketch.shapes if shape.get('type') == 'line' and shape.get('construction')), None)
        if line is None:
            raise FeatureError('这个草图里没有中心线：用草图页的“中心线”画一条作旋转轴，或把旋转轴改成草图 X / Y 轴')
        start, x_dir, y_dir, _ = sketch.frame
        origin = start + x_dir * float(line['x1']) + y_dir * float(line['y1'])
        direction = x_dir * (float(line['x2']) - float(line['x1'])) + y_dir * (float(line['y2']) - float(line['y1']))
        if np.linalg.norm(direction) < 1e-9:
            raise FeatureError('中心线太短，定不出旋转轴')
    else:
        origin, direction = _axis(ctx, params.get('axis', 'SY'), sketch.frame)
    angle = _number(params, 'angle')
    if not 1e-6 < abs(angle) <= 360.0 + 1e-9:
        raise FeatureError('旋转角度要在 0 到 360 度之间（不含 0）')
    solid = _run(BRepPrimAPI_MakeRevol(sketch.profile, gp_Ax1(_pnt(origin), _dir(direction)), math.radians(angle)),
                 '旋转失败：轮廓不能跨过旋转轴')
    if abs(_volume(solid).Mass()) < 1e-9:
        raise FeatureError('旋转不出实体：轮廓和旋转轴不在同一个平面上，或轮廓就在轴上')
    return solid


def sweep(body, params, ctx):
    sketch = _profile(ctx, params)
    identifier = params.get('path')
    spine = _path(ctx, identifier)
    # 轮廓画在路径的哪一头, 就从哪一头开始扫 (路径是几条线拼起来的, 它自己的走向不一定对)
    adaptor = BRepAdaptor_CompCurve(spine)
    surface = GProp_GProps()
    BRepGProp.SurfaceProperties_s(sketch.profile, surface)
    if adaptor.Value(adaptor.LastParameter()).Distance(surface.CentreOfMass()) \
            < adaptor.Value(adaptor.FirstParameter()).Distance(surface.CentreOfMass()) - 1e-9:
        spine = _as_wire(spine.Reversed())
    if identifier in ctx.helix_axis:               # 沿螺旋线扫: 轮廓的朝向相对轴线保持不变, 不然会越扫越拧
        shell = BRepOffsetAPI_MakePipeShell(spine)
        shell.SetMode(_dir(ctx.helix_axis[identifier]))
        shell.Add(sketch.wires[0])
        _run(shell, '扫描失败：轮廓太大（和相邻的圈碰上了），或轮廓不在螺旋线的起点处')
        if not shell.MakeSolid():
            raise FeatureError('扫描出来的面合不成实体')
        return shell.Shape()
    from OCP.BRepBuilderAPI import BRepBuilderAPI_RightCorner
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GeomAbs import GeomAbs_C0
    trouble = '扫描失败：路径拐得太急（比轮廓还小的弯），或轮廓不在路径的起点处'
    if BRepAdaptor_CompCurve(spine).Continuity() != GeomAbs_C0:     # 路径是光顺的: 普通的管道扫描 (轮廓里的孔也带着)
        try:
            solid = _run(BRepOffsetAPI_MakePipe(spine, sketch.profile), trouble)
            if BRepCheck_Analyzer(solid).IsValid():
                return solid
        except FeatureError:
            pass
    shell = BRepOffsetAPI_MakePipeShell(spine)          # 路径上有尖角: 在拐角处把两段接成直角 (只用轮廓的外圈)
    shell.SetTransitionMode(BRepBuilderAPI_RightCorner)
    shell.Add(sketch.wires[0])
    _run(shell, trouble)
    if not shell.MakeSolid():
        raise FeatureError(trouble)
    return shell.Shape()


def loft(body, params, ctx):
    identifiers = params.get('sketches') or []
    if len(identifiers) < 2:
        raise FeatureError('放样至少要两个草图轮廓')
    maker = BRepOffsetAPI_ThruSections(True, bool(params.get('ruled')), 1e-6)
    for identifier in identifiers:
        maker.AddWire(_profile(ctx, {'sketch': identifier}).wires[0])
    maker.CheckCompatibility(True)
    return _run(maker, '放样失败：这几个轮廓过渡不过去（是不是在同一个平面上，或顺序排错了）')


def _stack(spot, direction, steps):
    """一个孔 (或螺柱): 沿 direction 一段接一段的圆柱 / 圆锥。steps = [(起始直径, 结束直径, 长度)...]。"""
    solids, depth = [], 0.0
    for start, end, span in steps:
        if min(start, end) < 0 or max(start, end) <= 0 or span <= 0:
            raise FeatureError('直径和深度都要是正数')
        axis = gp_Ax2(_pnt(spot + direction * depth), _dir(direction))
        if abs(start - end) < 1e-9:
            solids.append(BRepPrimAPI_MakeCylinder(axis, start / 2, span).Shape())
        else:
            solids.append(BRepPrimAPI_MakeCone(axis, start / 2, end / 2, span).Shape())
        depth += span
    return solids


def _along(sketch, params):
    normal = sketch.frame[3]
    return normal if params.get('flip') else -normal


def hole(body, params, ctx):
    _need_body(body, '打孔')
    sketch = _sketch(ctx, params)
    kind, size = params.get('kind', 'simple'), params.get('size', 'custom')
    diameter, head, head_depth = _number(params, 'diameter', positive=True), 0.0, 0.0
    if kind != 'simple':
        head, head_depth = _number(params, 'head_diameter', positive=True), _number(params, 'head_depth', positive=True)
    if size in table.HOLE_SIZES:
        diameter, bore, bore_depth, sink = table.HOLE_SIZES[size]
        head, head_depth = (bore, bore_depth) if kind == 'counterbore' else (sink, 0.0)
    depth = _reach(body) if params.get('through', True) else _number(params, 'depth', positive=True)
    steps = [(diameter, diameter, depth)]
    if kind != 'simple':
        if head <= diameter:
            raise FeatureError('沉头直径要比孔直径大')
        if kind == 'countersink':
            head_depth = (head - diameter) / 2          # 90° 锥形沉头
        steps = [(head, head if kind == 'counterbore' else diameter, head_depth), (diameter, diameter, max(depth - head_depth, 1e-3))]
    direction = _along(sketch, params)
    return build._compound([solid for spot in _spots(sketch) for solid in _stack(spot, direction, steps)])


def hole_adv(body, params, ctx):
    _need_body(body, '打孔')
    sketch = _sketch(ctx, params)
    rows = params.get('steps') or []
    if not rows:
        raise FeatureError('高级孔至少要一段：[[直径, 深度], ...]')
    steps = [(float(row[0]), float(row[0]), float(row[1]) if float(row[1]) > 0 else _reach(body)) for row in rows]
    direction = _along(sketch, params)
    return build._compound([solid for spot in _spots(sketch) for solid in _stack(spot, direction, steps)])


def stud(body, params, ctx):
    sketch = _sketch(ctx, params)
    diameter, span = _number(params, 'diameter', positive=True), _number(params, 'length', positive=True)
    bevel = _number(params, 'chamfer', least=0.0)
    if bevel * 2 >= diameter or bevel >= span:
        raise FeatureError('端部倒角太大')
    steps = [(diameter, diameter, span - bevel)] + ([(diameter, diameter - 2 * bevel, bevel)] if bevel > 0 else [])
    direction = -_along(sketch, params)
    return build._compound([solid for spot in _spots(sketch) for solid in _stack(spot, direction, steps)])


MAKERS = {'revolve': revolve, 'sweep': sweep, 'loft': loft, 'boundary': loft, 'hole': hole, 'hole_adv': hole_adv, 'stud': stud}
DEFAULT_OP = {'hole': 'cut', 'hole_adv': 'cut', 'stud': 'add'}


# ---------------------------------------------------------------------------
# 直接改实体的特征
# ---------------------------------------------------------------------------
def thread(body, params, ctx):
    _need_body(body, '切螺纹')
    edges = build.resolve_edges(body, params.get('edges'))
    curve = BRepAdaptor_Curve(edges[0])
    if len(edges) != 1 or curve.GetType() != GeomAbs_Circle:
        raise FeatureError('螺纹线要选一条圆形边（轴的端边或孔口的边）')
    circle = curve.Circle()
    centre, axis, radius = _xyz(circle.Location()), _xyz(circle.Axis().Direction()), circle.Radius()
    side = _xyz(circle.XAxis().Direction())
    pitch, span = _number(params, 'pitch', positive=True), _number(params, 'length', positive=True)
    height = 0.6134 * pitch
    if height >= radius:
        raise FeatureError('螺距相对这个直径太大')

    def inside(point):
        return BRepClass3d_SolidClassifier(body, _pnt(point), 1e-6).State() == TopAbs_IN

    probe = min(radius, pitch) * 0.3
    external = [sign for sign in (1, -1) if inside(centre + axis * sign * probe)]
    internal = [sign for sign in (1, -1) if inside(centre + axis * sign * probe + side * (radius + probe))]
    if len(external) == 1:
        along, outward = axis * external[0], 1.0
    elif not external and len(internal) == 1:
        along, outward = axis * internal[0], -1.0
    else:
        raise FeatureError('判断不出螺纹往哪边走：这条边要在轴的端面或孔口上')
    turns = span / pitch + 0.5
    start = centre - along * pitch * 0.5            # 从端面外半圈开始切, 牙从端面上自然露出来
    count = max(int(turns * 24), 2)
    points = [start + along * pitch * turns * k / count
              + (side * math.cos(math.tau * turns * k / count) + np.cross(along, side) * math.sin(math.tau * turns * k / count)) * radius
              for k in range(count + 1)]
    spine = _spline(points)
    base, tip = start + side * (radius + outward * pitch * 0.05), start + side * (radius - outward * height)
    polygon = BRepBuilderAPI_MakePolygon(_pnt(base - along * pitch * 0.45), _pnt(base + along * pitch * 0.45), _pnt(tip), True)
    shell = BRepOffsetAPI_MakePipeShell(spine)
    shell.SetMode(_dir(along))
    shell.Add(polygon.Wire())
    _run(shell, '螺纹扫不出来')
    if not shell.MakeSolid():
        raise FeatureError('螺纹牙合不成实体')
    return build.combine(body, shell.Shape(), 'cut', '切螺纹')


def rib(body, params, ctx):
    _need_body(body, '加筋')
    sketch = _sketch(ctx, params)
    spine = _wire(_explore(sketch.curves, TopAbs_EDGE), '筋的草图')
    thickness = _number(params, 'thickness', positive=True)
    origin, x_dir, y_dir, normal = sketch.frame
    adaptor = BRepAdaptor_CompCurve(spine)
    first, last = _xyz(adaptor.Value(adaptor.FirstParameter())), _xyz(adaptor.Value(adaptor.LastParameter()))
    middle = _xyz(adaptor.Value((adaptor.FirstParameter() + adaptor.LastParameter()) / 2))
    chord = last - first
    if np.linalg.norm(chord) < 1e-9:
        raise FeatureError('筋的草图要是一条开口的线')
    toward = np.cross(normal, chord / np.linalg.norm(chord))
    if np.dot(_centroid(body) - middle, toward) < 0:        # 默认朝实体那一侧延伸
        toward = -toward
    if params.get('flip'):
        toward = -toward
    reach = _reach(body)
    sheet = BRepPrimAPI_MakePrism(_moved(spine, _translation(-normal * thickness / 2)), _vec(toward * reach)).Shape()
    slab = BRepPrimAPI_MakePrism(sheet, _vec(normal * thickness)).Shape()
    pieces = _explore(build._boolean(BRepAlgoAPI_Cut, slab, body, '筋和实体求差'), TopAbs_SOLID)
    probe = middle + toward * 1e-4
    mine = [piece for piece in pieces if BRepClass3d_SolidClassifier(piece, _pnt(probe), 1e-5).State() == TopAbs_IN]
    if not mine:
        raise FeatureError('筋的草图线在实体里面：把它画在实体外面、要加筋的空档里')
    low, high = build.bounds(mine[0])
    span = max(abs(float(np.dot(np.array(corner) - middle, toward))) for corner in
               [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])])
    if span > reach * 0.9:
        raise FeatureError('筋朝这个方向碰不到实体：勾上“朝另一侧延伸”试试')
    return build.combine(body, mine[0], 'add', '合并筋')


def draft(body, params, ctx):
    _need_body(body, '拔模')
    faces = _faces(body, params.get('faces'), '拔模')
    if not faces:
        raise FeatureError('没有选择要拔模的面')
    origin, _, _, normal = _frame(ctx, params.get('plane', 'XY'), float(params.get('offset', 0.0)))
    angle = _number(params, 'angle')
    if not 1e-6 < abs(angle) < 89:
        raise FeatureError('拔模角度要在 0 到 89 度之间')
    pull = -normal if params.get('flip') else normal
    maker = BRepOffsetAPI_DraftAngle(body)
    for face in faces:
        maker.Add(face, _dir(pull), math.radians(angle), gp_Pln(_pnt(origin), _dir(normal)))
        if not maker.AddDone():
            raise FeatureError('这个面不能拔模：拔模面要和中性面相交或相邻，且不能平行于中性面')
    return _run(maker, '拔模失败：角度太大，或这些面拔模后接不上')


def shell(body, params, ctx):
    _need_body(body, '抽壳')
    thickness = _number(params, 'thickness', positive=True)
    removed = _faces(body, params.get('faces'), '抽壳')
    if removed:
        maker = BRepOffsetAPI_MakeThickSolid()
        maker.MakeThickSolidByJoin(body, _shape_list(removed), -thickness, 1e-3)
        return _run(maker, f'抽壳失败：壁厚 {thickness:g} mm 对这个实体来说太大，或有的面往里偏不动')
    maker = BRepOffsetAPI_MakeOffsetShape()
    maker.PerformByJoin(body, -thickness, 1e-3)
    inner = _run(maker, f'抽壳失败：壁厚 {thickness:g} mm 对这个实体来说太大')
    if not _explore(inner, TopAbs_SOLID):               # 往里偏出来的是一层壳: 合成实体才能拿去切
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
        from OCP.TopAbs import TopAbs_SHELL
        shells = _explore(inner, TopAbs_SHELL)
        if not shells:
            raise FeatureError(f'抽壳失败：壁厚 {thickness:g} mm 对这个实体来说太大')
        inner = BRepBuilderAPI_MakeSolid((getattr(TopoDS, 'Shell_s', None) or TopoDS.Shell)(shells[0])).Solid()
    if _volume(inner).Mass() < 0:
        inner = inner.Reversed()
    if abs(_volume(inner).Mass()) < 1e-9:
        raise FeatureError(f'抽壳失败：壁厚 {thickness:g} mm 对这个实体来说太大')
    return build.combine(body, inner, 'cut', '掏空')


def wrap(body, params, ctx):
    from OCP.BRepLib import BRepLib
    from OCP.BRepOffset import BRepOffset_MakeOffset, BRepOffset_Skin
    from OCP.Geom2d import Geom2d_Line, Geom2d_TrimmedCurve
    from OCP.Geom2dAPI import Geom2dAPI_PointsToBSpline
    from OCP.gp import gp_Dir2d
    from OCP.GeomAbs import GeomAbs_Arc
    from OCP.ShapeAnalysis import ShapeAnalysis_Surface
    from OCP.collections import Array1_gp_Pnt2d
    from OCP.gp import gp_Pnt2d
    _need_body(body, '包裹')
    sketch = _profile(ctx, params)
    face = _faces(body, params.get('faces'), '包裹', count=1)[0]
    adaptor = BRepAdaptor_Surface(face)
    if adaptor.GetType() != GeomAbs_Cylinder:
        raise FeatureError('包裹目前只能贴到圆柱面上')
    depth = _number(params, 'depth', positive=True)
    cylinder = adaptor.Cylinder()
    radius, axis = cylinder.Radius(), _xyz(cylinder.Axis().Direction())
    surface = BRep_Tool.Surface_s(face)
    origin, x_dir, y_dir, normal = sketch.frame
    start = ShapeAnalysis_Surface(surface).ValueOfUV(_pnt(origin), 1e-6)       # 草图原点落在圆柱面上的位置
    around = np.cross(axis, _xyz(surface.Value(start.X(), start.Y())) - _xyz(cylinder.Location()))
    around /= np.linalg.norm(around)
    # 草图的 (x, y) → 圆柱面的 (转角, 轴向): 草图平面在这一点 "摊开" 贴上去
    to_u = np.array([np.dot(x_dir, around), np.dot(y_dir, around)]) / radius
    to_v = np.array([np.dot(x_dir, axis), np.dot(y_dir, axis)])

    def on_surface(point):
        return gp_Pnt2d(start.X() + float(to_u @ point), start.Y() + float(to_v @ point))

    loops, _ = sketchgeom.loops(sketch.shapes)
    stickers = []
    for loop in loops:
        maker = BRepBuilderAPI_MakeWire()
        for prim, _ in loop:
            if prim[0] == 'line':
                first, second = on_surface(prim[1]), on_surface(prim[2])
                curve = Geom2d_TrimmedCurve(Geom2d_Line(first, gp_Dir2d(second.X() - first.X(), second.Y() - first.Y())),
                                            0.0, first.Distance(second))
            else:
                line = sketchgeom.sample(prim, 48)
                array = Array1_gp_Pnt2d(1, len(line))
                for index, point in enumerate(line):
                    array.SetValue(index + 1, on_surface(point))
                curve = Geom2dAPI_PointsToBSpline(array).Curve()
            edge = BRepBuilderAPI_MakeEdge(curve, surface).Edge()
            BRepLib.BuildCurves3d_s(edge)
            maker.Add(edge)
        if not maker.IsDone():
            raise FeatureError('包裹的轮廓贴到圆柱面上后接不上')
        patch = BRepBuilderAPI_MakeFace(surface, maker.Wire(), True)
        if not patch.IsDone():
            raise FeatureError('包裹的轮廓在圆柱面上围不成面（是不是绕了超过一圈）')
        stickers.append(patch.Face())
    emboss = params.get('mode', 'emboss') == 'emboss'
    outward = -1.0 if face.Orientation() == build.TopAbs_REVERSED else 1.0     # 圆柱面的自然法向朝外; 孔壁是反的
    for sticker in stickers:
        thick = BRepOffset_MakeOffset()
        thick.Initialize(sticker, depth * outward * (1.0 if emboss else -1.0), 1e-4, BRepOffset_Skin, False, False,
                         GeomAbs_Arc, True)
        try:
            thick.MakeOffsetShape()
            solid = thick.Shape() if thick.IsDone() else None
        except Exception:
            solid = None
        if solid is None or solid.IsNull() or abs(_volume(solid).Mass()) < 1e-9:
            raise FeatureError('包裹失败：这个轮廓在圆柱面上加不出厚度')
        body = build.combine(body, solid, 'add' if emboss else 'cut', '包裹')
    return body


def split(body, params, ctx):
    _need_body(body, '分割')
    sketch = _sketch(ctx, params)
    normal, reach = sketch.frame[3], _reach(body)
    blades = [BRepPrimAPI_MakePrism(_moved(edge, _translation(-normal * reach)), _vec(normal * reach * 2)).Shape()
              for edge in _explore(sketch.curves, TopAbs_EDGE)]
    if not blades:
        raise FeatureError('分割线的草图里没有线')
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.BRepFeat import BRepFeat_SplitShape
    from OCP.collections import Sequence_TopoDS_Shape
    traces = Sequence_TopoDS_Shape()                    # 每把 "刀" 和实体表面的交线
    for blade in blades:
        for edge in _explore(_run(BRepAlgoAPI_Section(body, blade), '分割失败'), TopAbs_EDGE):
            traces.Append(edge)
    maker = BRepFeat_SplitShape(body)                   # 只在面上刻线: 实体还是一整块
    if traces.Length() == 0 or not maker.Add(traces):
        raise FeatureError('草图投到实体上没有把任何面分开：线要横穿过一个面')
    result = _run(maker, '分割失败')
    if build._indexed(result, TopAbs_FACE).Extent() == build._indexed(body, TopAbs_FACE).Extent():
        raise FeatureError('草图投到实体上没有把任何面分开：线要横穿过一个面')
    return result


# ---- 阵列 ----
def _seeds(body, params, ctx, need=False):
    """要复制的东西 → [(工具体, 方式, 造它的特征或 None)...]。不写对象 = 整个实体。"""
    identifiers = params.get('features') or []
    if not identifiers:
        if need:
            raise FeatureError('要选对象：写上造型特征的 id（features）')
        _need_body(body, '阵列')
        return [(body, 'add', None)]
    seeds = []
    for identifier in identifiers:
        if identifier not in ctx.tools:
            raise FeatureError(f'{identifier} 不能被阵列或镜像：只有拉伸、旋转、扫描、放样、孔、螺柱这类特征可以（并且要算成功了）')
        seeds.append((*ctx.tools[identifier], next(item for item in ctx.features if item['id'] == identifier)))
    return seeds


def _replicate(body, seeds, transforms):
    """把每个工具体按每个变换复制一份, 用它原来的方式并进实体。切除的攒到一起一次切 (孔多的时候快得多)。"""
    cuts = []
    for transform in transforms:
        for solid, op, _ in seeds:
            copy = _moved(solid, transform)
            if op == 'cut':
                cuts.append(copy)
            else:
                body = build.combine(body, copy, op, '阵列')
    if cuts:
        body = build.combine(body, build._compound(cuts), 'cut', '阵列')
    return body


def _count(params, key):
    count = int(round(_number(params, key)))
    if not 1 <= count <= 500:
        raise FeatureError('数量要在 1 到 500 之间')
    return count


def pattern_linear(body, params, ctx):
    seeds = _seeds(body, params, ctx)
    first, second = _axis(ctx, params.get('axis1', 'X'))[1], _axis(ctx, params.get('axis2', 'Y'))[1]
    count1, count2 = _count(params, 'count1'), _count(params, 'count2')
    step1, step2 = _number(params, 'spacing1'), _number(params, 'spacing2')
    moves = [_translation(first * step1 * i + second * step2 * j) for j in range(count2) for i in range(count1) if i or j]
    return _replicate(body, seeds, moves)


def pattern_circular(body, params, ctx):
    seeds = _seeds(body, params, ctx)
    origin, direction = _axis(ctx, params.get('axis', 'Z'))
    count, total = _count(params, 'count'), _number(params, 'angle')
    if count < 2:
        return body
    step = total / count if abs(abs(total) - 360.0) < 1e-9 else total / (count - 1)
    moves = []
    for index in range(1, count):
        turn = gp_Trsf()
        turn.SetRotation(gp_Ax1(_pnt(origin), _dir(direction)), math.radians(step * index))
        moves.append(turn)
    return _replicate(body, seeds, moves)


def mirror(body, params, ctx):
    seeds = _seeds(body, params, ctx)
    origin, _, _, normal = _frame(ctx, params.get('plane', 'YZ'), float(params.get('offset', 0.0)))
    flip = gp_Trsf()
    flip.SetMirror(gp_Ax2(_pnt(origin), _dir(normal)))
    return _replicate(body, seeds, [flip])


def pattern_curve(body, params, ctx):
    seeds = _seeds(body, params, ctx)
    adaptor = BRepAdaptor_CompCurve(_path(ctx, params.get('path')))
    count, spacing = _count(params, 'count'), _number(params, 'spacing', least=0.0)
    total = GCPnts_AbscissaPoint.Length_s(adaptor)
    closed = adaptor.Value(adaptor.FirstParameter()).Distance(adaptor.Value(adaptor.LastParameter())) < 1e-6
    if spacing <= 0:
        spacing = total / (count if closed else max(count - 1, 1))
    if spacing * (count - 1) > total + 1e-6:
        raise FeatureError(f'路径不够长：全长 {total:.4g} mm，放不下 {count} 个间距 {spacing:.4g} mm 的实例')

    def at(distance):
        parameter = GCPnts_AbscissaPoint(adaptor, distance, adaptor.FirstParameter()).Parameter()
        point, tangent = gp_Pnt(), gp_Vec()
        adaptor.D1(parameter, point, tangent)
        return point, tangent

    start, heading = at(0.0)
    moves = []
    for index in range(1, count):
        point, tangent = at(min(spacing * index, total))
        move = _translation(_xyz(point) - _xyz(start))
        if params.get('align') and heading.Magnitude() > 1e-9 and tangent.Magnitude() > 1e-9:
            pivot = heading.Crossed(tangent)
            if pivot.Magnitude() > 1e-9:
                turn = gp_Trsf()
                turn.SetRotation(gp_Ax1(start, gp_Dir(pivot)), heading.Angle(tangent))
                move = move.Multiplied(turn)
        moves.append(move)
    return _replicate(body, seeds, moves)


def _to_spots(body, seeds, spots, normal=None):
    """把对象的质心挪到每个位置上 (normal: 只在垂直于它的平面里挪)。"""
    centre = _centroid(seeds[0][0])
    moves = []
    for spot in spots:
        shift = np.asarray(spot, dtype=float) - centre
        if normal is not None:
            shift = shift - normal * float(np.dot(shift, normal))
        if np.linalg.norm(shift) > 1e-9:
            moves.append(_translation(shift))
    return _replicate(body, seeds, moves)


def pattern_sketch(body, params, ctx):
    sketch = _sketch(ctx, params)
    return _to_spots(body, _seeds(body, params, ctx), _spots(sketch), sketch.frame[3])


def pattern_table(body, params, ctx):
    seeds = _seeds(body, params, ctx)
    centre = _centroid(seeds[0][0])
    rows = params.get('points') or []
    if not rows:
        raise FeatureError('坐标表是空的')
    return _to_spots(body, seeds, [list(row[:2]) + [row[2] if len(row) > 2 else centre[2]] for row in rows])


def pattern_fill(body, params, ctx):
    _need_body(body, '填充阵列')
    sketch = _profile(ctx, params)
    spacing, margin = _number(params, 'spacing', positive=True), _number(params, 'margin', least=0.0)
    loops, _ = sketchgeom.loops(sketch.shapes)
    ring = max((sketchgeom.loop_ring(loop) for loop in loops), key=lambda item: abs(sketchgeom.signed_area(item)))
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    centre = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    half = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / 2 + spacing
    turn = math.radians(float(params.get('angle', 0.0)))
    cos, sin = math.cos(turn), math.sin(turn)
    hexagonal = params.get('layout') == 'hex'
    row_step = spacing * (math.sqrt(3) / 2 if hexagonal else 1.0)
    rows, spots = int(half / row_step) + 1, []
    if (2 * rows + 1) * (2 * int(half / spacing) + 3) > 20000:
        raise FeatureError('间距相对边界太小，实例太多')
    for row in range(-rows, rows + 1):
        shift = spacing / 2 if hexagonal and row % 2 else 0.0
        for column in range(-int(half / spacing) - 1, int(half / spacing) + 2):
            x, y = column * spacing + shift, row * row_step
            point = (centre[0] + x * cos - y * sin, centre[1] + x * sin + y * cos)
            if sketchgeom.contains(ring, point) and \
                    min(sketchgeom.dist(point, sketchgeom._nearest_on_segment(point, a, b)) for a, b in zip(ring, ring[1:] + ring[:1])) >= margin:
                spots.append(point)
    if not spots:
        raise FeatureError('边界里一个实例也放不下：间距或离边界的距离太大')
    origin, x_dir, y_dir, normal = sketch.frame
    world = [origin + x_dir * x + y_dir * y for x, y in spots]
    if params.get('features'):
        return _to_spots(body, _seeds(body, params, ctx), world, normal)
    diameter, reach = _number(params, 'diameter', positive=True), _reach(body)
    holes = [BRepPrimAPI_MakeCylinder(gp_Ax2(_pnt(spot - normal * reach), _dir(normal)), diameter / 2, reach * 2).Shape() for spot in world]
    return build.combine(body, build._compound(holes), 'cut', '填充阵列')


def pattern_variable(body, params, ctx):
    seeds = _seeds(body, params, ctx, need=True)
    rows = [row.strip() for row in str(params.get('rows', '')).replace('；', ';').replace('\n', ';').split(';') if row.strip()]
    if not rows:
        raise FeatureError('实例表是空的：每行写 "dx,dy,dz,参数=值,…"，行之间用分号')
    for row in rows:
        parts = [part.strip() for part in row.replace('，', ',').split(',') if part.strip()]
        try:
            shift = [float(part) for part in parts if '=' not in part]
            changes = {part.split('=')[0].strip(): float(part.split('=')[1]) for part in parts if '=' in part}
        except ValueError:
            raise FeatureError(f'实例表这一行看不懂: {row!r}') from None
        if len(shift) != 3:
            raise FeatureError(f'实例表每行开头要有 dx,dy,dz 三个数: {row!r}')
        for _, op, feature in seeds:
            unknown = [key for key in changes if key not in feature['params']]
            if unknown:
                raise FeatureError(f'{feature["name"]} 没有参数 {", ".join(unknown)}；它有: {", ".join(feature["params"])}')
            solid = ctx.make(feature['type'], dict(feature['params'], **changes), body)
            body = build.combine(body, _moved(solid, _translation(shift)), op, '变量阵列')
    return body


MODIFIERS = {'thread': thread, 'rib': rib, 'draft': draft, 'shell': shell, 'wrap': wrap, 'split': split,
             'pattern_linear': pattern_linear, 'pattern_circular': pattern_circular, 'mirror': mirror,
             'pattern_curve': pattern_curve, 'pattern_sketch': pattern_sketch, 'pattern_table': pattern_table,
             'pattern_fill': pattern_fill, 'pattern_variable': pattern_variable}


# ---------------------------------------------------------------------------
# 曲线
# ---------------------------------------------------------------------------
def curve_helix(body, params, ctx, identifier):
    sketch = _sketch(ctx, params)
    circle = next((shape for shape in sketch.shapes if shape.get('type') == 'circle'), None)
    if circle is None:
        raise FeatureError('螺旋线的草图里要有一个圆（它定出起始直径和位置）')
    origin, x_dir, y_dir, normal = sketch.frame
    centre = origin + x_dir * float(circle.get('cx', 0.0)) + y_dir * float(circle.get('cy', 0.0))
    radius, pitch = float(circle['r']), _number(params, 'pitch', positive=True)
    turns, taper = _number(params, 'turns', positive=True), _number(params, 'taper')
    spiral = params.get('kind') == 'spiral'
    sense = -1.0 if params.get('clockwise') else 1.0
    start = math.radians(float(params.get('start', 0.0)))
    count = max(int(turns * 24), 4)
    if count > 20000:
        raise FeatureError('圈数太多')
    points = []
    for index in range(count + 1):
        turn = turns * index / count
        reach = radius + (pitch if spiral else taper) * turn
        if reach <= 1e-6:
            raise FeatureError('锥度太大：半径缩到 0 了')
        angle = start + sense * math.tau * turn
        points.append(centre + (x_dir * math.cos(angle) + y_dir * math.sin(angle)) * reach + normal * (0.0 if spiral else pitch * turn))
    if not spiral:
        ctx.helix_axis[identifier] = normal
    return _spline(points)


def sketch3d(body, params, ctx, identifier):
    points = [np.array(row, dtype=float) for row in params.get('points') or []]
    closed = bool(params.get('closed'))
    if len(points) < (3 if closed else 2):
        raise FeatureError('3D 草图至少要 2 个点（闭合的要 3 个）')
    if params.get('kind') == 'spline':
        return _spline(points, closed)
    if any(np.linalg.norm(b - a) < 1e-9 for a, b in zip(points, points[1:])):
        raise FeatureError('相邻的两个点重合了')
    maker = BRepBuilderAPI_MakePolygon()
    for point in points:
        maker.Add(_pnt(point))
    if closed:
        maker.Close()
    return maker.Wire()


def curve_surface(body, params, ctx, identifier):
    from OCP.BRepLib import BRepLib
    from OCP.Geom2d import Geom2d_Line, Geom2d_TrimmedCurve
    from OCP.Geom2dAPI import Geom2dAPI_Interpolate
    from OCP.collections import HArray1_gp_Pnt2d
    from OCP.gp import gp_Dir2d, gp_Pnt2d
    _need_body(body, '在面上画样条')
    face = _faces(body, params.get('faces'), '曲面上的样条曲线', count=1)[0]
    adaptor = BRepAdaptor_Surface(face)                     # 这张面在自己曲面上占的那一块 (U, V 范围)
    low_u, high_u, low_v, high_v = (adaptor.FirstUParameter(), adaptor.LastUParameter(),
                                    adaptor.FirstVParameter(), adaptor.LastVParameter())
    rows = params.get('points') or []
    if len(rows) < 2:
        raise FeatureError('面上的样条至少要 2 个点')
    if any(not (0.0 <= float(value) <= 1.0) for row in rows for value in row):
        raise FeatureError('面上的点要写成 U,V，两个数都在 0 到 1 之间（它在这张面上的位置）')
    spots = [gp_Pnt2d(low_u + (high_u - low_u) * float(u), low_v + (high_v - low_v) * float(v)) for u, v in rows]
    if any(a.Distance(b) < 1e-12 for a, b in zip(spots, spots[1:])):
        raise FeatureError('相邻的两个点重合了')
    if len(spots) == 2:
        first, second = spots
        curve = Geom2d_TrimmedCurve(Geom2d_Line(first, gp_Dir2d(second.X() - first.X(), second.Y() - first.Y())),
                                    0.0, first.Distance(second))
    else:
        array = HArray1_gp_Pnt2d(1, len(spots))
        for index, spot in enumerate(spots):
            array.SetValue(index + 1, spot)
        maker = Geom2dAPI_Interpolate(array, False, 1e-9)
        maker.Perform()
        if not maker.IsDone():
            raise FeatureError('这些点连不成光顺的曲线')
        curve = maker.Curve()
    edge = BRepBuilderAPI_MakeEdge(curve, BRep_Tool.Surface_s(face)).Edge()
    BRepLib.BuildCurves3d_s(edge)
    return BRepBuilderAPI_MakeWire(edge).Wire()


def curve_xyz(body, params, ctx, identifier):
    return _spline([row for row in params.get('points') or []])


def curve_points(body, params, ctx, identifier):
    spots = []
    for ref in params.get('points') or []:
        feature = next((item for item in ctx.features if item['id'] == ref and item['type'] == 'point'), None)
        if feature is None:
            raise FeatureError(f'{ref} 不是参考点（要写“点”特征的 id）')
        spots.append(feature['params']['position'][0])
    return _spline(spots, params.get('closed'))


def curve_project(body, params, ctx, identifier):
    from OCP.BRepProj import BRepProj_Projection
    _need_body(body, '投影曲线')
    sketch = _sketch(ctx, params)
    spine = _wire(_explore(sketch.curves, TopAbs_EDGE), '要投影的草图')
    projection = BRepProj_Projection(spine, body, _dir(sketch.frame[3]))
    wires = _explore(projection.Shape(), TopAbs_WIRE) if projection.IsDone() else []
    if not wires:
        raise FeatureError('草图沿法向投不到实体上')
    ctx.display[identifier] = projection.Shape()
    return _as_wire(wires[0])


def curve_composite(body, params, ctx, identifier):
    edges = list(build.resolve_edges(body, params['edges'])) if params.get('edges') else []
    for ref in params.get('curves') or []:
        edges += _explore(_path(ctx, ref, '曲线'), TopAbs_EDGE)
    return _wire(edges, '组合曲线')


CURVES = {'sketch3d': sketch3d, 'curve_surface': curve_surface, 'curve_helix': curve_helix, 'curve_xyz': curve_xyz, 'curve_points': curve_points,
          'curve_project': curve_project, 'curve_composite': curve_composite}


# ---------------------------------------------------------------------------
# 参考几何体: 只出显示用的线
# ---------------------------------------------------------------------------
def _segments(pairs):
    return build._compound([BRepBuilderAPI_MakeEdge(_pnt(a), _pnt(b)).Edge() for a, b in pairs])


def _cross(centre, size):
    return [(centre - axis * size, centre + axis * size) for axis in np.eye(3)]


def reference(kind, body, params, ctx, identifier):
    scale = build._model_size(body) if not build._is_empty(body) else 100.0
    if kind == 'plane':
        origin, x_dir, y_dir, _ = _frame(ctx, identifier)
        half = max(scale * 0.4, 20.0)
        corners = [origin + x_dir * a * half + y_dir * b * half for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        return _segments(zip(corners, corners[1:] + corners[:1]))
    if kind == 'axis':
        origin, direction = _axis(ctx, identifier)
        return _segments([(origin - direction * scale * 0.6, origin + direction * scale * 0.6)])
    if kind == 'csys':
        try:
            origin, matrix = table.csys_axes(params)
        except (KeyError, IndexError, ValueError):
            raise FeatureError('坐标系的原点要写成 [[x, y, z]]') from None
        size = max(scale * 0.15, 8.0)
        return _segments([(origin, origin + matrix[:, index] * size * (1.0, 0.75, 0.5)[index]) for index in range(3)])
    if kind == 'point':
        try:
            spot = np.asarray(params['position'][0], dtype=float)
        except (KeyError, IndexError, ValueError):
            raise FeatureError('点的坐标要写成 [[x, y, z]]') from None
        return _segments(_cross(spot, max(scale * 0.02, 1.5)))
    _need_body(body, '算这个')
    if kind == 'com':
        centre = _centroid(body)
        ctx.info[identifier] = f'质心 ({centre[0]:.4g}, {centre[1]:.4g}, {centre[2]:.4g})'
        return _segments(_cross(centre, max(scale * 0.05, 3.0)))
    low, high = (np.array(corner) for corner in build.bounds(body))
    ctx.info[identifier] = '边界框 {:.4g} × {:.4g} × {:.4g} mm'.format(*(high - low))
    pairs = []
    for axis in range(3):
        for a in (low, high):
            for b in (low, high):
                start = np.array([a[i] if i == (axis + 1) % 3 else b[i] if i == (axis + 2) % 3 else low[i] for i in range(3)])
                end = start.copy()
                end[axis] = high[axis]
                pairs.append((start, end))
    return _segments(pairs)


REFERENCES = ('plane', 'axis', 'csys', 'point', 'com', 'bbox')
