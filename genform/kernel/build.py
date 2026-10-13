# -*- coding: utf-8 -*-
"""几何内核: 把特征列表 (纯数据) 重算成实体, 再给出显示用的三角网格、边线和拓扑信息。

只有这个模块碰 OpenCascade (OCP)。它不知道界面、文档、撤销 — 输入是特征列表, 输出是纯数据,
所以可以放在独立进程里跑 (见 worker.py), 也可以在测试里直接调。

特征 = {'id', 'type', 'name', 'params', 'suppressed'}; 目前的 type:
    sketch   草图: 基准面上的一组图形 (直线、圆弧、矩形、样条、文本… 见 sketchgeom.py); 封闭的和首尾相接成圈的
             是轮廓, 套在里面的轮廓算孔
    extrude  拉伸一个草图: 加料 (add) 或切除 (cut)
    fillet   圆角; chamfer 倒角 — 作用在选中的边上
单位: 毫米、度。
"""
from __future__ import annotations

import math

import numpy as np

from .. import planes, sketchgeom
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace,
                                BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeWire)
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.Bnd import Bnd_Box
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import (GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Line,
                         GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus)
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
from OCP.TopLoc import TopLoc_Location
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.Geom import Geom_BezierCurve
from OCP.gp import gp_Ax1, gp_Ax2, gp_Circ, gp_Dir, gp_Elips, gp_Pnt, gp_Vec

try:                                    # OCP 7.x
    from OCP.TopTools import TopTools_IndexedMapOfShape
except ImportError:                     # OCP 8: 集合类搬到了 OCP.collections, 静态转换函数去掉了 _s 后缀
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape
try:
    from OCP.TColgp import TColgp_Array1OfPnt as _PointArray
except ImportError:
    from OCP.collections import Array1_gp_Pnt as _PointArray
_as_edge = getattr(TopoDS, 'Edge_s', None) or TopoDS.Edge
_as_face = getattr(TopoDS, 'Face_s', None) or TopoDS.Face

AXES = {'X': (1.0, 0.0, 0.0), 'Y': (0.0, 1.0, 0.0), 'Z': (0.0, 0.0, 1.0)}
LINEAR_DEFLECTION = 0.05        # 显示网格离真实曲面最多差这么多 (mm)
ANGULAR_DEFLECTION = 0.3        # 弧度
CURVE_SEGMENTS = 48             # 一条曲线边画成多少段
SELECT_TOLERANCE = 1e-4         # 选择器里 "同一高度/平行" 的容差 (相对模型尺寸)


class FeatureError(Exception):
    """某个特征算不出来; 文字直接给用户和 AI 看。"""


# ---------------------------------------------------------------------------
# 草图
# ---------------------------------------------------------------------------
def plane_frame(params, features=()):
    """草图所在的坐标系 → (原点, X 方向, Y 方向, 法向), 都是 numpy 向量。plane 可以是 XY / XZ / YZ 或基准面特征的 id。"""
    from .. import features as table
    try:
        return planes.frame(table.plane_frame(params.get('plane', 'XY'), features), params.get('offset', 0.0))
    except ValueError as error:
        raise FeatureError(str(error)) from None


class Sketch:
    """一个草图算出来的东西。profile: 能拉伸的面 (没有封闭轮廓时是 None); frame: 坐标系; curves: 全部曲线 (显示、
    作路径用); shapes: 原始的图形参数; wires: 最外层的封闭轮廓 (放样、沿螺旋线扫描用)。"""

    def __init__(self, profile, frame, curves, shapes, wires):
        self.profile, self.frame, self.curves, self.shapes, self.wires = profile, frame, curves, shapes, wires


class Context:
    """重算到现在为止攒下来的东西, 后面的特征会引用。"""

    def __init__(self, features):
        self.features = features        # 全部特征 (纯数据): 查基准面、基准轴、参考点的参数用
        self.sketches = {}              # 草图 id → Sketch
        self.curves = {}                # 曲线特征 id → 一条线 (Wire)
        self.tools = {}                 # 造型特征 id → (工具体, 方式): 阵列和镜像复制的就是它
        self.display = {}               # 曲线 / 参考几何体 id → 显示用的线
        self.info = {}                  # 特征 id → 算出来的一句话 (质心坐标、边界框尺寸)
        self.helix_axis = {}            # 螺旋线 id → 轴的方向

    def make(self, kind, params, body):
        """按参数造一个工具体 (变量阵列: 同一个特征换几个尺寸再造一遍)。"""
        from . import features as more
        if kind == 'extrude':
            return extrude_solid(params, self)
        return more.MAKERS[kind](body, params, self)


def _prim_edge(prim, frame):
    """草图里的一条基本曲线 (见 sketchgeom) → 三维的边。"""
    origin, x_dir, y_dir, normal = frame

    def to_point(point):
        return gp_Pnt(*(origin + x_dir * point[0] + y_dir * point[1]))

    kind = prim[0]
    if kind == 'line':
        return BRepBuilderAPI_MakeEdge(to_point(prim[1]), to_point(prim[2])).Edge()
    if kind in ('arc', 'circle'):
        circle = gp_Circ(gp_Ax2(to_point(prim[1]), gp_Dir(*normal), gp_Dir(*x_dir)), prim[2])
        if kind == 'circle':
            return BRepBuilderAPI_MakeEdge(circle).Edge()
        return BRepBuilderAPI_MakeEdge(circle, prim[3], prim[4]).Edge()
    if kind == 'ellipse':
        major, minor, turn = prim[2], prim[3], prim[4]
        if minor > major:                   # 内核要求长轴在前
            major, minor, turn = minor, major, turn + math.pi / 2
        along = x_dir * math.cos(turn) + y_dir * math.sin(turn)
        return BRepBuilderAPI_MakeEdge(gp_Elips(gp_Ax2(to_point(prim[1]), gp_Dir(*normal), gp_Dir(*along)), major, minor)).Edge()
    if kind == 'bezier':
        poles = _PointArray(1, len(prim) - 1)
        for index in range(len(prim) - 1):
            poles.SetValue(index + 1, to_point(prim[index + 1]))
        return BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles)).Edge()
    raise FeatureError(f'内核不认识的草图曲线 {kind!r}')


def _loop_wire(loop, frame):
    maker = BRepBuilderAPI_MakeWire()
    for prim, _ in loop:
        maker.Add(_prim_edge(prim, frame))
        if not maker.IsDone():
            raise FeatureError('轮廓的线没有首尾相接（或有重合的线）')
    return maker.Wire()


_FONTS = {}


def _text_faces(shape, frame):
    """文本 → 每个字的面 (已经摆到草图平面上)。字形来自系统字体, 排版和界面预览用同一个 text_layout。"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.Font import Font_FontAspect
    from OCP.StdPrs import StdPrs_BRepFont
    from OCP.TCollection import TCollection_AsciiString
    from OCP.gp import gp_Ax3, gp_Trsf
    text = str(shape.get('text', ''))
    height = sketchgeom.num(shape, 'height', 10.0, positive=True)
    name = str(shape.get('font') or sketchgeom.DEFAULT_FONT)
    font = _FONTS.get((name, height))
    if font is None:
        font = StdPrs_BRepFont()
        if not font.FindAndInit(TCollection_AsciiString(name), Font_FontAspect.Font_FontAspect_Regular, height):
            raise FeatureError(f'找不到字体 {name!r}')
        _FONTS[(name, height)] = font
    origin, x_dir, y_dir, normal = frame
    to_plane = gp_Trsf()
    to_plane.SetTransformation(gp_Ax3(gp_Pnt(*origin), gp_Dir(*normal), gp_Dir(*x_dir)), gp_Ax3())
    faces = []
    spots = sketchgeom.text_layout(shape, [float(font.AdvanceX(letter)) for letter in text])
    for letter, (x, y, turn) in zip(text, spots):
        glyph = font.RenderGlyph(letter)
        if glyph.IsNull():                  # 空格
            continue
        place = gp_Trsf()
        place.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), turn)
        shift = gp_Trsf()
        shift.SetTranslation(gp_Vec(x, y, 0))
        faces.append(BRepBuilderAPI_Transform(glyph, to_plane * shift * place, True).Shape())
    return faces


def build_sketch(params, features=()):
    """草图 → Sketch。
    封闭图形和首尾相接成圈的线是轮廓: 套在偶数层里的是实心, 奇数层是孔。没围成圈的线、点只显示, 不参与拉伸。"""
    frame = plane_frame(params, features)
    shapes = list(params.get('shapes', ()))
    if not shapes:
        raise FeatureError('草图里没有轮廓')
    try:
        loops, _ = sketchgeom.loops(shapes)
        rings = [sketchgeom.loop_ring(loop) for loop in loops]
        curves = [_prim_edge(prim, frame) for shape in shapes if not shape.get('construction')    # 构造线只在编辑草图时看得见
                  for prim in sketchgeom.prims(shape) if prim[0] != 'point']
    except ValueError as error:
        raise FeatureError(str(error)) from None
    areas = [abs(sketchgeom.signed_area(ring)) for ring in rings]
    depths = [sum(1 for other in range(len(rings))
                  if other != index and areas[other] > areas[index] and sketchgeom.contains(rings[other], rings[index][0]))
              for index in range(len(rings))]
    faces, outer = [], []
    for index, loop in enumerate(loops):
        if depths[index] % 2:
            continue
        wire = _loop_wire(loop, frame)
        if depths[index] == 0:
            outer.append(wire)
        maker = BRepBuilderAPI_MakeFace(wire, True)
        if not maker.IsDone():
            raise FeatureError('轮廓围不成面')
        face = maker.Shape()
        for hole in range(len(loops)):
            if depths[hole] == depths[index] + 1 and sketchgeom.contains(rings[index], rings[hole][0]):
                hole_face = BRepBuilderAPI_MakeFace(_loop_wire(loops[hole], frame), True).Shape()
                face = _boolean(BRepAlgoAPI_Cut, face, hole_face, '草图挖孔')
        faces.append(face)
    for shape in shapes:
        if shape.get('type') == 'text':
            letters = _text_faces(shape, frame)
            faces += letters
            curves += letters
    return Sketch(_compound(faces) if faces else None, frame, _compound(curves), shapes, outer)


def _compound(shapes):
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    return compound


# ---------------------------------------------------------------------------
# 实体操作
# ---------------------------------------------------------------------------
def _boolean(operation, base, tool, what):
    result = operation(base, tool)
    result.Build()
    if not result.IsDone() or result.Shape().IsNull():
        raise FeatureError(f'{what}失败')
    return result.Shape()


def _unify(shape):
    """合并布尔运算留下的共面碎面、共线碎边: 不然一个平面会被分成好几块, 选面选边都别扭。"""
    unify = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    unify.Build()
    return unify.Shape()


def _is_empty(shape):
    return shape is None or shape.IsNull() or _indexed(shape, TopAbs_FACE).Extent() == 0


def extrude_solid(params, ctx):
    """拉伸出来的那块料 (还没和实体合并)。"""
    sketch_id = params.get('sketch')
    if sketch_id not in ctx.sketches:
        raise FeatureError(f'找不到草图 {sketch_id!r}（可能被删除、抑制或出错了）')
    sketch = ctx.sketches[sketch_id]
    profile, normal = sketch.profile, sketch.frame[3]
    if profile is None:
        raise FeatureError('这个草图里没有封闭轮廓：线要首尾相接围成一圈才能拉伸（草图页的“修复草图”能找出没接上的地方）')
    try:
        distance = float(params.get('distance'))
    except (TypeError, ValueError):
        raise FeatureError('拉伸距离不是数字') from None
    if not math.isfinite(distance) or abs(distance) < 1e-9:
        raise FeatureError('拉伸距离不能为 0')
    if params.get('symmetric'):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Trsf
        move = gp_Trsf()
        move.SetTranslation(gp_Vec(*(-normal * distance / 2)))
        profile = BRepBuilderAPI_Transform(profile, move, True).Shape()
    return BRepPrimAPI_MakePrism(profile, gp_Vec(*(normal * distance))).Shape()


def combine(body, solid, operation, what='特征'):
    """把一块工具体并进实体: add 加料 / cut 切除 / common 相交 (只留重叠的部分)。"""
    operation = str(operation)
    if operation == 'add':
        return solid if _is_empty(body) else _unify(_boolean(BRepAlgoAPI_Fuse, body, solid, '合并实体'))
    if operation in ('cut', 'common'):
        if _is_empty(body):
            raise FeatureError(f'还没有实体，无法{"切除" if operation == "cut" else "求交"}')
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
        result = _unify(_boolean(BRepAlgoAPI_Cut if operation == 'cut' else BRepAlgoAPI_Common, body, solid,
                                 '切除' if operation == 'cut' else '求交'))
        if _is_empty(result):
            raise FeatureError('切除后实体被完全切掉了' if operation == 'cut' else '和现有实体没有重叠的部分')
        return result
    raise FeatureError(f'不认识的方式 {operation!r}，可用 add / cut / common')


def _indexed(shape, kind):
    mapping = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, mapping)
    return mapping


def _model_size(shape):
    low, high = bounds(shape)
    return float(np.linalg.norm(np.array(high) - np.array(low))) or 1.0


def bounds(shape):
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)   # 按精确几何算: 按显示网格算的话, 圆弧的最外点会差一点
    low, high = box.CornerMin(), box.CornerMax()       # box.Get() 在 OCP 8 里返回不了 Python 值
    gap = box.GetGap()                                  # 包围盒自带的余量, 去掉才是真实尺寸
    return ((low.X() + gap, low.Y() + gap, low.Z() + gap), (high.X() - gap, high.Y() - gap, high.Z() - gap))


def edge_table(shape):
    """实体的每条边 → [{'id', 'type', 'mid', 'length', 'dir'}...], id 就是在这张表里的序号。
    序号在特征重算后可能变, 所以存进特征里的引用用的是中点坐标, 不是序号。"""
    table = []
    mapping = _indexed(shape, TopAbs_EDGE)
    for index in range(1, mapping.Extent() + 1):
        edge = _as_edge(mapping.FindKey(index))
        if BRep_Tool.Degenerated_s(edge):
            table.append(None)
            continue
        curve = BRepAdaptor_Curve(edge)
        first, last = curve.FirstParameter(), curve.LastParameter()
        mid = curve.Value((first + last) / 2)
        kind = curve.GetType()
        entry = {'id': index - 1, 'mid': (mid.X(), mid.Y(), mid.Z()),
                 'length': float(GCPnts_AbscissaPoint.Length_s(curve)),
                 'type': 'line' if kind == GeomAbs_Line else 'circle' if kind == GeomAbs_Circle else 'curve',
                 'dir': None}
        if kind == GeomAbs_Line:
            start, end = curve.Value(first), curve.Value(last)
            vector = np.array([end.X() - start.X(), end.Y() - start.Y(), end.Z() - start.Z()])
            length = np.linalg.norm(vector)
            entry['dir'] = tuple(vector / length) if length > 0 else None
        elif kind == GeomAbs_Circle:
            circle = curve.Circle()
            centre, axis = circle.Location(), circle.Axis().Direction()
            entry['radius'] = float(circle.Radius())
            entry['center'] = (centre.X(), centre.Y(), centre.Z())
            entry['axis'] = (axis.X(), axis.Y(), axis.Z())
        entry['_edge'] = edge
        table.append(entry)
    return table


def resolve_edges(shape, selection):
    """特征里写的边选择 → 实体上的边。selection 可以是:
        'all'                全部边
        '|Z'  (或 |X |Y)     平行于该轴的直边
        '>Z'  '<Z' (X Y 同)  中点在该方向最靠外的那一圈边
        [{'point': [x, y, z]}, ...]   中点离这些坐标最近的边 (界面点选和 AI 查询后都用这种)
    """
    table = [entry for entry in edge_table(shape) if entry]
    if not table:
        raise FeatureError('实体上没有边')
    size = _model_size(shape)
    if isinstance(selection, str):
        text = selection.strip()
        if text.lower() == 'all':
            return [entry['_edge'] for entry in table]
        if len(text) == 2 and text[0] in '|<>' and text[1].upper() in AXES:
            axis = np.array(AXES[text[1].upper()])
            if text[0] == '|':
                chosen = [entry for entry in table
                          if entry['dir'] is not None and abs(abs(np.dot(entry['dir'], axis)) - 1) < 1e-6]
            else:
                heights = [float(np.dot(entry['mid'], axis)) for entry in table]
                extreme = max(heights) if text[0] == '>' else min(heights)
                chosen = [entry for entry, height in zip(table, heights)
                          if abs(height - extreme) <= SELECT_TOLERANCE * size]
            if not chosen:
                raise FeatureError(f'选择器 {text!r} 没有选中任何边')
            return [entry['_edge'] for entry in chosen]
        raise FeatureError(f'看不懂的边选择器 {selection!r}')
    chosen, used = [], set()
    mids = np.array([entry['mid'] for entry in table])
    for reference in selection or ():
        point = reference.get('point') if isinstance(reference, dict) else None
        if point is None or len(point) != 3:
            raise FeatureError('边的引用要写成 {"point": [x, y, z]}（边中点坐标）')
        distance = np.linalg.norm(mids - np.array(point, dtype=float), axis=1)
        nearest = int(distance.argmin())
        # 引用存的是当时的中点。前面的尺寸改了以后边会移动, 离得太远就说明这条边已经不是原来那条了
        if distance[nearest] > 0.25 * size:
            raise FeatureError('引用的边找不到了（前面的特征改动后这条边可能已经消失），请重新选择边')
        if nearest not in used:
            used.add(nearest)
            chosen.append(table[nearest]['_edge'])
    if not chosen:
        raise FeatureError('没有选择任何边')
    return chosen


def apply_blend(body, params, rounded):
    what = '圆角' if rounded else '倒角'
    if _is_empty(body):
        raise FeatureError(f'还没有实体，无法{what}')
    key = 'radius' if rounded else 'distance'
    try:
        size = float(params.get(key))
    except (TypeError, ValueError):
        raise FeatureError(f'{what}尺寸不是数字') from None
    if not math.isfinite(size) or size <= 0:
        raise FeatureError(f'{what}尺寸必须是正数')
    edges = resolve_edges(body, params.get('edges'))
    maker = BRepFilletAPI_MakeFillet(body) if rounded else BRepFilletAPI_MakeChamfer(body)
    for edge in edges:
        maker.Add(size, edge)
    try:
        maker.Build()
        done = maker.IsDone()
        result = maker.Shape() if done else None
    except Exception:                       # OCC 在尺寸放不下时直接抛 StdFail_NotDone
        result = None
    if _is_empty(result):
        raise FeatureError(f'{what}失败：{size:g} mm 对选中的边来说太大，或这些边不能做{what}')
    return result


# ---------------------------------------------------------------------------
# 重算
# ---------------------------------------------------------------------------
def rebuild(features, upto=None):
    """按顺序重算特征 → (实体或 None, {草图 id: Sketch}, {特征 id: 状态})。"""
    body, ctx, status = _rebuild(features, upto)
    return body, ctx.sketches, status


def _rebuild(features, upto=None):
    """按顺序重算特征 → (实体或 None, Context, {特征 id: 状态})。
    状态: 'ok' / 'suppressed' / 'skipped' (在回滚线之后, 或前面有特征出错) / 'error: 原因'。
    一个特征出错后保留它之前的实体, 后面的特征不再算: 在坏掉的基础上继续算只会给出一串误导的错误。"""
    from . import features as more
    body, ctx, status = None, Context(features), {}
    ctx.owners = {}                     # 面的 "指纹" → 做出这张面的特征 (点面找特征用)
    failed = False
    for index, feature in enumerate(features):
        before = body
        identifier = feature['id']
        if failed or (upto is not None and index >= upto):
            status[identifier] = 'skipped'
            continue
        if feature.get('suppressed'):
            status[identifier] = 'suppressed'
            continue
        kind, params = feature.get('type'), feature.get('params') or {}
        try:
            if kind == 'sketch':
                ctx.sketches[identifier] = build_sketch(params, features)
            elif kind == 'extrude' or kind in more.MAKERS:
                solid = ctx.make(kind, params, body)
                operation = params.get('op', more.DEFAULT_OP.get(kind, 'add'))
                body = combine(body, solid, operation)
                ctx.tools[identifier] = (solid, operation)
            elif kind == 'fillet':
                body = apply_blend(body, params, True)
            elif kind == 'chamfer':
                body = apply_blend(body, params, False)
            elif kind in more.MODIFIERS:
                body = more.MODIFIERS[kind](body, params, ctx)
            elif kind in more.CURVES:
                ctx.curves[identifier] = more.CURVES[kind](body, params, ctx, identifier)
                ctx.display.setdefault(identifier, ctx.curves[identifier])
            elif kind in more.REFERENCES:
                ctx.display[identifier] = more.reference(kind, body, params, ctx, identifier)
            else:
                raise FeatureError(f'不认识的特征类型 {kind!r}')
            status[identifier] = 'ok'
            if body is not before and not _is_empty(body):
                for face in _faces_of(body):
                    ctx.owners.setdefault(_face_signature(face), identifier)
        except FeatureError as error:
            status[identifier] = f'error: {error}'
            failed = True
        except Exception as error:          # 内核自己抛的异常: 也只让这一个特征失败
            status[identifier] = f'error: 内核错误 {type(error).__name__}: {error}'
            failed = True
    return body, ctx, status


# ---------------------------------------------------------------------------
# 显示数据
# ---------------------------------------------------------------------------
def _surface_name(kind):
    return {GeomAbs_Plane: 'plane', GeomAbs_Cylinder: 'cylinder', GeomAbs_Cone: 'cone',
            GeomAbs_Sphere: 'sphere', GeomAbs_Torus: 'torus'}.get(kind, 'surface')


def _faces_of(shape):
    mapping = _indexed(shape, TopAbs_FACE)
    return [_as_face(mapping.FindKey(index)) for index in range(1, mapping.Extent() + 1)]


def _face_signature(face):
    """一张面的 "指纹": 它躺在哪张曲面上 (平面 = 法向 + 到原点的距离; 圆柱 = 轴线 + 半径), 和面被裁成什么样无关。
    所以后面的特征在这张面上开了孔、切掉一角, 它还是算最早做出它的那个特征的。别的曲面没有这么简单的说法, 用面积 + 形心。"""
    def canon(vector):                  # 方向正反算同一个: 让第一个不为零的分量是正的
        vector = [round(float(value), 5) + 0.0 for value in vector]
        lead = next((value for value in vector if abs(value) > 1e-5), 1.0)
        return tuple(-value + 0.0 for value in vector) if lead < 0 else tuple(vector)

    surface = BRepAdaptor_Surface(face)
    kind = surface.GetType()
    if kind == GeomAbs_Plane:
        plane = surface.Plane()
        point, axis = plane.Location(), plane.Axis().Direction()
        normal = canon((axis.X(), axis.Y(), axis.Z()))
        return ('plane', normal, round(normal[0] * point.X() + normal[1] * point.Y() + normal[2] * point.Z(), 4) + 0.0)
    if kind == GeomAbs_Cylinder:
        cylinder = surface.Cylinder()
        point, axis = cylinder.Location(), cylinder.Axis().Direction()
        along = canon((axis.X(), axis.Y(), axis.Z()))
        place = np.array([point.X(), point.Y(), point.Z()])
        foot = place - (place @ np.array(along)) * np.array(along)      # 轴线上离原点最近的那一点: 轴线怎么表示都一样
        return ('cylinder', along, tuple(round(float(value), 4) + 0.0 for value in foot), round(float(cylinder.Radius()), 4))
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    centre = props.CentreOfMass()
    return ('surface', int(kind), round(float(props.Mass()), 3),
            tuple(round(value, 3) + 0.0 for value in (centre.X(), centre.Y(), centre.Z())))


def tessellate(shape, owners=None):
    """实体 → 显示用三角网格。每个面单独一段顶点 (面之间不共用), 所以可以按面着色和拾取。
    返回 verts (N,3) float32, normals (N,3) float32, tris (M,3) uint32, tri_face (M,) uint32, faces [信息]。
    owners: _rebuild 记下的 面指纹 → 特征; 给了的话每张面的信息里带 'feature' (做出它的特征) 和 'edges' (围着它的边)。"""
    BRepMesh_IncrementalMesh(shape, LINEAR_DEFLECTION, False, ANGULAR_DEFLECTION, True)
    mapping = _indexed(shape, TopAbs_FACE)
    edge_map = _indexed(shape, TopAbs_EDGE)
    all_verts, all_normals, all_tris, all_owner, infos = [], [], [], [], []
    base = 0
    for index in range(1, mapping.Extent() + 1):
        face = _as_face(mapping.FindKey(index))
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        surface = BRepAdaptor_Surface(face)
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        centre = props.CentreOfMass()
        info = {'id': index - 1, 'type': _surface_name(surface.GetType()),
                'center': (centre.X(), centre.Y(), centre.Z()), 'area': float(props.Mass()), 'normal': None}
        reverse = face.Orientation() == TopAbs_REVERSED
        if surface.GetType() == GeomAbs_Plane:
            direction = surface.Plane().Axis().Direction()
            sign = -1.0 if reverse else 1.0
            info['normal'] = (direction.X() * sign, direction.Y() * sign, direction.Z() * sign)
        elif surface.GetType() == GeomAbs_Cylinder:
            info['radius'] = float(surface.Cylinder().Radius())
        if owners is not None:
            info['feature'] = owners.get(_face_signature(face))
            around = _indexed(face, TopAbs_EDGE)
            info['edges'] = sorted({edge_map.FindIndex(around.FindKey(number)) - 1 for number in range(1, around.Extent() + 1)
                                    if not BRep_Tool.Degenerated_s(_as_edge(around.FindKey(number)))})
        infos.append(info)
        if triangulation is None:
            continue
        transform = location.Transformation()
        count = triangulation.NbNodes()
        verts = np.empty((count, 3), dtype=np.float64)
        for node in range(1, count + 1):
            point = triangulation.Node(node).Transformed(transform)
            verts[node - 1] = (point.X(), point.Y(), point.Z())
        tris = np.empty((triangulation.NbTriangles(), 3), dtype=np.int64)
        for number in range(1, triangulation.NbTriangles() + 1):
            tris[number - 1] = triangulation.Triangle(number).Get()
        tris -= 1
        if reverse:
            tris = tris[:, ::-1]
        # 顶点法线 = 用到它的三角面法线之和: 面内 (圆柱等) 是平滑的, 面与面之间因为不共用顶点保持棱线
        corners = verts[tris]
        flat = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
        normals = np.zeros_like(verts)
        for corner in range(3):
            np.add.at(normals, tris[:, corner], flat)
        length = np.linalg.norm(normals, axis=1, keepdims=True)
        normals /= np.where(length > 0, length, 1.0)
        all_verts.append(verts)
        all_normals.append(normals)
        all_tris.append(tris + base)
        all_owner.append(np.full(len(tris), index - 1, dtype=np.uint32))
        base += count
    if not all_verts:
        empty = np.zeros((0, 3), dtype=np.float32)
        return empty, empty, np.zeros((0, 3), dtype=np.uint32), np.zeros(0, dtype=np.uint32), infos
    return (np.concatenate(all_verts).astype(np.float32), np.concatenate(all_normals).astype(np.float32),
            np.concatenate(all_tris).astype(np.uint32), np.concatenate(all_owner), infos)


def _sample_edge(edge):
    curve = BRepAdaptor_Curve(edge)
    first, last = curve.FirstParameter(), curve.LastParameter()
    count = 1 if curve.GetType() == GeomAbs_Line else CURVE_SEGMENTS
    points = []
    for step in range(count + 1):
        point = curve.Value(first + (last - first) * step / count)
        points.append((point.X(), point.Y(), point.Z()))
    return np.array(points, dtype=np.float32)


def edge_lines(shape):
    """实体的边 → 线段 (K,2,3) float32, 每条线段属于哪条边 (K,) uint32, 边信息表。"""
    table = edge_table(shape)
    segments, owner, infos = [], [], []
    for entry in table:
        if entry is None:
            continue
        points = _sample_edge(entry.pop('_edge'))
        segments.append(np.stack([points[:-1], points[1:]], axis=1))
        owner.append(np.full(len(points) - 1, entry['id'], dtype=np.uint32))
        infos.append(entry)
    if not segments:
        return np.zeros((0, 2, 3), dtype=np.float32), np.zeros(0, dtype=np.uint32), infos
    return np.concatenate(segments), np.concatenate(owner), infos


def sketch_lines(ctx):
    """每个草图、曲线、参考几何体要画的线 → {特征 id: 线段 (K,2,3)}。"""
    shown = {identifier: sketch.curves for identifier, sketch in ctx.sketches.items()}
    shown.update(ctx.display)
    lines = {}
    for identifier, curves in shown.items():
        mapping = _indexed(curves, TopAbs_EDGE)
        parts = []
        for index in range(1, mapping.Extent() + 1):
            points = _sample_edge(_as_edge(mapping.FindKey(index)))
            parts.append(np.stack([points[:-1], points[1:]], axis=1))
        lines[identifier] = np.concatenate(parts) if parts else np.zeros((0, 2, 3), dtype=np.float32)
    return lines


def properties(shape):
    volume, area = GProp_GProps(), GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, volume)
    BRepGProp.SurfaceProperties_s(shape, area)
    low, high = bounds(shape)
    centre = volume.CentreOfMass()
    return {'volume': float(volume.Mass()), 'area': float(area.Mass()),
            'bbox_min': low, 'bbox_max': high,
            'size': tuple(h - l for l, h in zip(low, high)),
            'center_of_mass': (centre.X(), centre.Y(), centre.Z())}


def build_model(features, upto=None):
    """特征列表 → 界面和接口要的全部数据 (纯 Python / numpy, 可以跨进程传)。"""
    body, ctx, status = _rebuild(features, upto)
    model = {'status': status, 'sketches': sketch_lines(ctx), 'info': ctx.info, 'has_body': not _is_empty(body)}
    if model['has_body']:
        verts, normals, tris, tri_face, faces = tessellate(body, ctx.owners)
        segments, segment_edge, edges = edge_lines(body)
        model.update(verts=verts, normals=normals, tris=tris, tri_face=tri_face, faces=faces,
                     segments=segments, segment_edge=segment_edge, edges=edges, props=properties(body))
    return model


def outline(features, upto, mode, frame):
    """草图平面上看到的实体的线 → 草图平面里的折线 [[(x, y)...]...]。frame = (原点, X 方向, Y 方向)。
    mode: 'silhouette' 顺着草图法向看过去, 曲面 "转过去" 的那条轮廓线 (圆柱的两条侧边、球的外圈 — 它们不是实体的边);
          'section'    草图平面把实体切开的那一圈交线。"""
    body, _, _ = rebuild(features, upto)
    if _is_empty(body):
        raise FeatureError('还没有实体')
    origin, x_dir, y_dir = (np.asarray(vector, dtype=float) for vector in frame)
    normal = np.cross(x_dir, y_dir)
    ax2 = gp_Ax2(gp_Pnt(*origin.tolist()), gp_Dir(*normal.tolist()), gp_Dir(*x_dir.tolist()))
    if mode == 'section':
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
        from OCP.gp import gp_Ax3, gp_Pln
        maker = BRepAlgoAPI_Section(body, gp_Pln(gp_Ax3(ax2)))
        maker.Build()
        if not maker.IsDone():
            raise FeatureError('求不出交线')
        shape = maker.Shape()

        def flat(point):
            local = np.array([point.X(), point.Y(), point.Z()]) - origin
            return float(local @ x_dir), float(local @ y_dir)
    else:
        from OCP.BRepLib import BRepLib
        from OCP.HLRAlgo import HLRAlgo_Projector
        from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
        algo = HLRBRep_Algo()
        algo.Add(body)
        algo.Projector(HLRAlgo_Projector(ax2))
        algo.Update()
        algo.Hide()
        shape = HLRBRep_HLRToShape(algo).OutLineVCompound()     # 结果已经在投影平面的坐标里: (x, y, 0)
        if shape is not None and not shape.IsNull():
            BRepLib.BuildCurves3d_s(shape)

        def flat(point):
            return float(point.X()), float(point.Y())
    lines = []
    if shape is None or shape.IsNull():
        return lines
    mapping = _indexed(shape, TopAbs_EDGE)
    for index in range(1, mapping.Extent() + 1):
        edge = _as_edge(mapping.FindKey(index))
        if BRep_Tool.Degenerated_s(edge):
            continue
        curve = BRepAdaptor_Curve(edge)
        first, last = curve.FirstParameter(), curve.LastParameter()
        count = 1 if curve.GetType() == GeomAbs_Line else CURVE_SEGMENTS
        lines.append([flat(curve.Value(first + (last - first) * step / count)) for step in range(count + 1)])
    return lines


def export(features, path, upto=None):
    """导出当前实体: .step / .stp 是精确几何, .stl 是三角网格。"""
    body, _, status = rebuild(features, upto)
    if _is_empty(body):
        raise FeatureError('没有可导出的实体')
    lower = str(path).lower()
    if lower.endswith(('.step', '.stp')):
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
        writer = STEPControl_Writer()
        writer.Transfer(body, STEPControl_AsIs)
        if writer.Write(str(path)) != IFSelect_RetDone:
            raise FeatureError('写 STEP 文件失败')
    elif lower.endswith('.stl'):
        from OCP.StlAPI import StlAPI_Writer
        BRepMesh_IncrementalMesh(body, LINEAR_DEFLECTION, False, ANGULAR_DEFLECTION, True)
        writer = StlAPI_Writer()
        writer.ASCIIMode = False
        if not writer.Write(body, str(path)):
            raise FeatureError('写 STL 文件失败')
    else:
        raise FeatureError('只能导出 .step / .stp / .stl')
    return status
