"""直接改实体的特征: 螺纹、筋、拔模、抽壳、包覆、分割。"""
from __future__ import annotations

import math
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_CompCurve, BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeWire
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle, BRepOffsetAPI_MakeOffsetShape, BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_MakeThickSolid
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRep import BRep_Tool
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pln

from ..build import FeatureError
from .. import build
from . import threads
from ... import sketchgeom
from .helpers import (
    _centroid, _dir, _explore, _faces, _frame, _moved, _need_body, _number, _pnt, _profile, _reach, _run, _shape_list,
    _sketch, _spline, _translation, _vec, _volume, _wire, _xyz)


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
    if 0.6134 * pitch >= radius:
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
    # 60° 普通螺纹牙型, 相位按 threads 里的约定 (从这条边所在的平面量起): 同规格的螺丝和孔牙嵌得上
    major = 2 * radius if outward > 0 else 2 * radius + 1.082532 * pitch      # 孔按小径 (底孔) 打的, 大径往外推
    tool = threads.groove(centre, along, major, pitch, -pitch * 0.5, span, outward < 0, float(params.get('phase') or 0.0))
    return build.combine(body, tool, 'cut', '切螺纹')


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


def _inner_skin(body, thickness):
    """实体往里偏 thickness 的那一层。先用拼接偏移 (棱角处按交线接好); 它在样条放样上常常做不成 (911 车身: 拼接偏移
    返回空, 换个公差要算 19 秒还是失败), 就退到简单偏移 — 每张面各自沿法向挪, 光顺的曲面上又快又准 (同一个车身 0.2 秒)。"""
    from OCP.BRepCheck import BRepCheck_Analyzer
    maker = BRepOffsetAPI_MakeOffsetShape()
    try:
        maker.PerformByJoin(body, -thickness, 1e-3)
        if maker.IsDone() and not maker.Shape().IsNull() and BRepCheck_Analyzer(maker.Shape()).IsValid():
            return maker.Shape()
    except Exception:
        pass
    simple = BRepOffsetAPI_MakeOffsetShape()
    try:
        simple.PerformBySimple(body, -thickness)
    except Exception:
        raise FeatureError(f'抽壳失败：壁厚 {thickness:g} mm 对这个实体来说太大') from None
    inner = _run(simple, f'抽壳失败：壁厚 {thickness:g} mm 对这个实体来说太大')
    if not BRepCheck_Analyzer(inner).IsValid():
        raise FeatureError(f'抽壳失败：往里偏 {thickness:g} mm 后面自己交叉了 (有比壁厚还小的圆角或尖角)')
    if not _fits_inside(body, inner, thickness):        # 各面各挪各的: 壁厚比零件还厚时面会互相穿过去, 偏出一个翻过来的形状
        raise FeatureError(f'抽壳失败：壁厚 {thickness:g} mm 对这个实体来说太大')
    return inner


def _fits_inside(body, inner, thickness):
    """简单偏移出来的内表面靠不靠谱: 朝向和外面一样 (体积为正)、比外面小, 挖掉的体积约等于 表面积 × 壁厚
    (凸的地方略少、凹的地方略多)。面互相穿过去时会翻出体积为负、或者大小对不上的形状。包围盒不能用: 样条面的粗包围盒按控制点算, 能大出几百毫米。"""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from .solid_validation import signed_volume
    outer, rest = signed_volume(body), signed_volume(inner)
    if not 0 < rest < outer:
        return False
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(body, props)
    expected = props.Mass() * thickness
    return 0.5 * expected <= outer - rest <= 1.3 * expected


def shell(body, params, ctx):
    _need_body(body, '抽壳')
    thickness = _number(params, 'thickness', positive=True)
    removed = _faces(body, params.get('faces'), '抽壳')
    if removed:
        maker = BRepOffsetAPI_MakeThickSolid()
        maker.MakeThickSolidByJoin(body, _shape_list(removed), -thickness, 1e-3)
        return _run(maker, f'抽壳失败：壁厚 {thickness:g} mm 对这个实体来说太大，或有的面往里偏不动')
    inner = _inner_skin(body, thickness)
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
    if params.get('walls'):
        inner = _partitioned(body, inner, ctx, params, thickness)
    hollow = _with_void(body, inner)
    if hollow is not None:
        return hollow
    return build.combine(body, inner, 'cut', '掏空')


def _partitioned(body, inner, ctx, params, thickness):
    """隔板: 草图里每一段直线沿草图法向贯穿实体、在草图面里加厚成一块板 (默认和壁厚一样), 从空腔里切掉 —
    空腔被分成几格, 隔板天然和外壳长成一体, 不会伸出外面 (车身的地板、防火墙、后隔板就是这样)。"""
    from OCP.GeomAbs import GeomAbs_Line
    sketch = _sketch(ctx, params, 'walls')
    origin, x_dir, y_dir, normal = sketch.frame
    wall = float(params.get('wall_thickness') or thickness)
    if wall <= 0:
        raise FeatureError('隔板厚度要大于 0')
    reach = _reach(body)
    slabs = []
    for edge in _explore(sketch.curves, TopAbs_EDGE):
        curve = BRepAdaptor_Curve((getattr(TopoDS, 'Edge_s', None) or TopoDS.Edge)(edge))
        if curve.GetType() != GeomAbs_Line:
            raise FeatureError('隔板草图里只能画直线 (每一段直线是一块平板隔板)')
        first, last = _xyz(curve.Value(curve.FirstParameter())), _xyz(curve.Value(curve.LastParameter()))
        chord = last - first
        if np.linalg.norm(chord) < 1e-6:
            continue
        across = np.cross(normal, chord / np.linalg.norm(chord))
        start = first - across * wall / 2 - normal * reach
        face = BRepBuilderAPI_MakePolygon(_pnt(start), _pnt(start + chord), _pnt(start + chord + across * wall), _pnt(start + across * wall), True)
        slabs.append(BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(face.Wire()).Face(), _vec(normal * reach * 2)).Shape())
    if not slabs:
        raise FeatureError('隔板草图里没有直线')
    pieces = build._boolean(BRepAlgoAPI_Cut, inner, build._compound(slabs), '空腔和隔板求差')    # 复合体工具会拆开一块块放进去, 隔板之间可以交叉
    if not _explore(pieces, TopAbs_SOLID):
        raise FeatureError('隔板把空腔全占满了')
    return pieces


def _with_void(body, inner):
    """一块实体 + 往里偏出来的内表面 → 外壳 + 反过来的内壳拼成的一个空心实体 (B-rep 里空腔的标准写法), 不做布尔:
    两层贴得这么近的大样条面拿去求差, 布尔常常算坏 (911 车身: 结果朝向错、体积反而变大)。不是一块实体时返回 None。"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepLib import BRepLib
    from OCP.TopAbs import TopAbs_SHELL
    from ..ops.solid_validation import check_boolean_volume
    solids = _explore(body, TopAbs_SOLID)
    voids = _explore(inner, TopAbs_SOLID) or [inner]
    inner_shells = [shell for void in voids for shell in _explore(void, TopAbs_SHELL)]
    if len(solids) != 1 or len(inner_shells) != len(voids):      # 一格空腔一层壳 (隔板把它分成了几格)
        return None
    outer_shells = _explore(solids[0], TopAbs_SHELL)
    if len(outer_shells) != 1:
        return None
    as_shell = getattr(TopoDS, 'Shell_s', None) or TopoDS.Shell
    maker = BRepBuilderAPI_MakeSolid(as_shell(outer_shells[0]))
    for void in inner_shells:
        maker.Add(as_shell(void.Reversed()))
    hollow = maker.Solid()
    if not BRepLib.OrientClosedSolid_s(hollow) or not BRepCheck_Analyzer(hollow).IsValid():
        return None
    check_boolean_volume(body, inner, hollow, 'cut', '抽壳')
    return hollow


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
    outward = -1.0 if face.Orientation() == TopAbs_REVERSED else 1.0     # 圆柱面的自然法向朝外; 孔壁是反的
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
