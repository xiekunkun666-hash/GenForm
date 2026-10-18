"""实体操作: 布尔、合并同面、拉伸 (各种终止条件)、按选择器找边、圆角倒角。"""
from __future__ import annotations

import math
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.Bnd import Bnd_Box
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line, GeomAbs_Plane
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS_Compound
from OCP.gp import gp_Dir, gp_Pnt, gp_Vec

from ..occ_compat import _as_edge, _ShapeList, TopTools_IndexedMapOfShape
from .base import AXES, FeatureError, SELECT_TOLERANCE
from ..ops.solid_validation import checked_tool_solid, check_boolean_shape, check_boolean_volume, check_unify_volume, signed_volume


# ---------------------------------------------------------------------------
# 实体操作
# ---------------------------------------------------------------------------
def _boolean(operation, base, tool, what):
    result = operation()
    first, second = _ShapeList(), _ShapeList()
    first.Append(base)
    # 工具是好几块拼成的 (阵列 / 镜像的一堆复制体、一串字): 一块一块分开给。它们之间可以重叠 (座椅的坐垫和靠背、挨得紧的字),
    # 塞在一个复合体里当一个参数, 这个参数就 "自己和自己相交", 布尔会算错 (911 镜像后排座椅: 结果只剩座椅, 车身没了)
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_SOLID
    pieces = _indexed(tool, TopAbs_SOLID) if not tool.IsNull() and tool.ShapeType() == TopAbs_COMPOUND else None
    if pieces is not None and pieces.Extent() > 1:
        for index in range(1, pieces.Extent() + 1):
            second.Append(pieces.FindKey(index))
    else:
        second.Append(tool)
    result.SetArguments(first)
    result.SetTools(second)
    result.SetNonDestructive(True)
    result.SetRunParallel(True)         # 面和面的求交分到几个核上算
    result.SetUseOBB(True)              # 先用贴身的包围盒筛掉碰不到的面: 实体的面多了以后省得多
    result.Build()
    if not result.IsDone() or result.Shape().IsNull():
        raise FeatureError(f'{what}失败')
    if getattr(result, 'HasErrors', lambda: False)():
        raise FeatureError(f'{what}失败：布尔算法报告错误')
    if getattr(result, 'HasWarnings', lambda: False)():
        from OCP.BRepCheck import BRepCheck_Analyzer
        if not BRepCheck_Analyzer(result.Shape()).IsValid():
            raise FeatureError(f'{what}失败：布尔算法报告警告且结果无效')
    return result.Shape()


def _unify(shape):
    """合并布尔运算留下的共面碎面、共线碎边: 不然一个平面会被分成好几块, 选面选边都别扭。"""
    unify = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    unify.Build()
    return unify.Shape()


def _is_empty(shape):
    return shape is None or shape.IsNull() or _indexed(shape, TopAbs_FACE).Extent() == 0


EXTRUDE_ENDS = ('blind', 'through', 'vertex', 'surface', 'offset', 'body', 'mid')


def _prism(profile, normal, start, stop):
    """轮廓沿草图法向从 start 拉到 stop (都是离草图平面的距离, 可正可负)。"""
    if abs(stop - start) < 1e-9:
        raise FeatureError('拉伸出来的厚度是 0')
    if abs(start) > 1e-12:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Trsf
        move = gp_Trsf()
        move.SetTranslation(gp_Vec(*(normal * start)))
        profile = BRepBuilderAPI_Transform(profile, move, True).Shape()
    return BRepPrimAPI_MakePrism(profile, gp_Vec(*(normal * (stop - start)))).Shape()


def extrude_solid(params, ctx, body=None):
    """拉伸出来的那块料 (还没和实体合并)。拉到哪为止看 params['end']:
        blind   给定深度 (distance; distance2 > 0 时反方向再拉这么多)      mid     两侧对称 (distance 是总厚度)
        through 完全贯穿 (穿过整个实体)                                  vertex  成形到顶点 (target 那个点所在的高度)
        surface 成形到面 (target 那张面)                                 offset  到离指定面指定的距离 (gap: 正 = 还差这么多没到)
        body    成形到实体 (一直拉到碰上现有的实体)
    reverse = 反向。老文档里没有 end: symmetric 为真就是 mid, 否则 blind。"""
    sketch_id = params.get('sketch')
    if sketch_id not in ctx.sketches:
        raise FeatureError(f'找不到草图 {sketch_id!r}（可能被删除、抑制或出错了）')
    sketch = ctx.sketches[sketch_id]
    profile, origin, normal = sketch.profile, sketch.frame[0], sketch.frame[3]
    if profile is None:
        raise FeatureError('这个草图里没有封闭轮廓：线要首尾相接围成一圈才能拉伸（草图页的“修复草图”能找出没接上的地方）')
    end = str(params.get('end') or ('mid' if params.get('symmetric') else 'blind'))
    if end not in EXTRUDE_ENDS:
        raise FeatureError(f'不认识的终止条件 {end!r}')
    sign = -1.0 if params.get('reverse') else 1.0

    def number(key, zero=False):
        try:
            value = float(params.get(key) or 0.0)
        except (TypeError, ValueError):
            raise FeatureError('拉伸距离不是数字') from None
        if not math.isfinite(value) or (not zero and abs(value) < 1e-9):
            raise FeatureError('拉伸距离不能为 0')
        return value

    if end == 'blind':
        second = number('distance2', zero=True)
        return _prism(profile, normal, -sign * second if second > 0 else 0.0, sign * number('distance'))
    if end == 'mid':
        distance = abs(number('distance'))
        return _prism(profile, normal, -distance / 2, distance / 2)
    target = params.get('target') or []
    point = target[0].get('point') if target and isinstance(target[0], dict) else None
    if end == 'vertex':
        if point is None or len(point) != 3:
            raise FeatureError('成形到顶点：先点一个顶点')
        reach = float((np.asarray(point, dtype=float) - origin) @ normal)
        if abs(reach) < 1e-6:
            raise FeatureError('这个顶点就在草图平面上：拉不出厚度')
        return _prism(profile, normal, 0.0, reach)
    if _is_empty(body):
        raise FeatureError('完全贯穿 / 成形到面 / 成形到实体：要先有实体')
    low, high = bounds(body)
    corners = np.array([(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])])
    heights = (corners - origin) @ normal
    edge = float(heights.max()) if sign > 0 else float(heights.min())       # 这个方向上实体最远到哪
    if edge * sign <= 1e-6:
        raise FeatureError('这个方向上没有实体：勾上“反向”试试')
    far = edge + sign * 1.0                                                 # 多出 1 mm, 保证穿透
    if end == 'through':
        return _prism(profile, normal, 0.0, far)
    if end in ('surface', 'offset'):
        from .. import features as more
        face = more._faces(body, target, '终止面', 1)[0] if target else None
        if face is None:
            raise FeatureError('先点一张面：拉到它为止')
        surface = BRepAdaptor_Surface(face)
        gap = number('gap', zero=True) if end == 'offset' else 0.0
        if surface.GetType() == GeomAbs_Plane:
            plane = surface.Plane()
            spot = np.array([plane.Location().X(), plane.Location().Y(), plane.Location().Z()])
            facing = np.array([plane.Axis().Direction().X(), plane.Axis().Direction().Y(), plane.Axis().Direction().Z()])
            slope = float(facing @ normal)
            if abs(slope) < 1e-6:
                raise FeatureError('这张面和拉伸方向平行：拉不到它')
            centre = GProp_GProps()
            BRepGProp.SurfaceProperties_s(profile, centre)
            middle = np.array([centre.CentreOfMass().X(), centre.CentreOfMass().Y(), centre.CentreOfMass().Z()])
            reach = float((spot - middle) @ facing) / slope             # 轮廓中心沿法向走多远碰到这张面
            if abs(reach) < 1e-6:
                raise FeatureError('这张面就在草图平面上：拉不出厚度')
            toward = 1.0 if reach > 0 else -1.0
            if abs(slope) > 1 - 1e-9:                                   # 和草图平面平行: 直接拉到那个高度
                return _prism(profile, normal, 0.0, reach - toward * gap)
            # 斜的面: 先拉过头, 再把面那一边的削掉
            from OCP.BRepPrimAPI import BRepPrimAPI_MakeHalfSpace
            from OCP.gp import gp_Pln
            shifted = spot - normal * toward * gap                         # 面沿拉伸方向退回 gap
            wall = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*shifted.tolist()), gp_Dir(*facing.tolist()))).Face()
            beyond = shifted + normal * toward * 1.0
            long = _prism(profile, normal, 0.0, toward * (abs(reach) + 2.0 * _model_size(body) + 10.0))
            rest = _boolean(BRepAlgoAPI_Cut, long, BRepPrimAPI_MakeHalfSpace(wall, gp_Pnt(*beyond.tolist())).Solid(), '成形到面')
            if _is_empty(rest):
                raise FeatureError('成形到面：削完什么都没剩下')
            return rest
        if end == 'offset':
            raise FeatureError('到离指定面指定的距离：目前只支持平面')
        # 曲面: 按 "拉到碰上实体为止" 做 (这张面是实体的一部分)
    if str(params.get('op', 'add')) != 'add':
        raise FeatureError('成形到实体 / 成形到曲面只能用在加料上；切除请用“完全贯穿”或“成形到面”（平面）')
    from OCP.TopAbs import TopAbs_SOLID
    pieces = _boolean(BRepAlgoAPI_Cut, _prism(profile, normal, 0.0, far), body, '成形到实体')
    mapping = _indexed(pieces, TopAbs_SOLID)
    near = []
    for index in range(1, mapping.Extent() + 1):                    # 被实体截成几段: 只要贴着草图平面的那些
        piece = mapping.FindKey(index)
        piece_low, piece_high = bounds(piece)
        spread = (np.array([(x, y, z) for x in (piece_low[0], piece_high[0]) for y in (piece_low[1], piece_high[1])
                            for z in (piece_low[2], piece_high[2])]) - origin) @ normal
        if float(np.abs(spread).min()) < 1e-4 or spread.min() * spread.max() < 0:
            near.append(piece)
    if not near:
        raise FeatureError('成形到实体：草图就在实体里面，往这个方向拉不出东西')
    if len(near) == 1:
        return near[0]
    builder, whole = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(whole)
    for piece in near:
        builder.Add(whole, piece)
    return whole


def combine(body, solid, operation, what='特征'):
    """把一块工具体并进实体: add 加料 / cut 切除 / common 相交 (只留重叠的部分)。"""
    operation = str(operation)
    from ..ops import hollow
    kind, wall = hollow.parse(operation)
    if kind in ('void', 'fill', 'pocket'):            # 空心件的三种方式, 见 ops/hollow.py
        if _is_empty(body):
            raise FeatureError('还没有实体，无法做空腔')
        solid = checked_tool_solid(solid, what)
        if kind == 'void':
            return hollow.void(body, solid, what)
        if kind == 'fill':
            return hollow.fill(body, solid, what)
        return hollow.pocket(body, solid, wall, what)
    if operation not in ('add', 'cut', 'common'):
        raise FeatureError(f'不认识的方式 {operation!r}，可用 add / cut / common / void / fill / pocket')
    if operation != 'add' and _is_empty(body):
        raise FeatureError(f'还没有实体，无法{"切除" if operation == "cut" else "求交"}')
    solid = checked_tool_solid(solid, what)
    if _is_empty(body):
        return solid
    try:
        return _combine_checked(body, solid, operation, what)
    except FeatureError:
        if operation == 'add':
            separated = _separated_add(body, solid, what)
            if separated is not None:
                return separated
        else:
            each = _each_solid(body, solid, operation, what)
            if each is not None:
                return each
        raise


def _raw_boolean(body, solid, operation):
    if operation == 'add':
        return _boolean(BRepAlgoAPI_Fuse, body, solid, '合并实体')
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    return _boolean(BRepAlgoAPI_Cut if operation == 'cut' else BRepAlgoAPI_Common, body, solid,
                    '切除' if operation == 'cut' else '求交')


def _combine_checked(body, solid, operation, what):
    raw = _raw_boolean(body, solid, operation)
    if _is_empty(raw):
        raise FeatureError('切除后实体被完全切掉了' if operation == 'cut' else
                           '和现有实体没有重叠的部分' if operation == 'common' else '加料后实体丢失')
    return _checked_result(body, solid, raw, operation, what)


def _checked_result(body, solid, raw, operation, what):
    check_boolean_volume(body, solid, raw, operation, what)
    result = _unify(raw)
    check_boolean_shape(result, body, what)
    check_boolean_volume(body, solid, result, operation, what)
    check_unify_volume(raw, result, what)
    return result


def _each_solid(body, solid, operation, what):
    """切除 / 求交整块做不成, 而实体是好几块互相贴着、套着的 (导入的 STEP 零件: 螺丝插在孔里、轴承压在座里):
    块和块之间的面会互相干扰, 布尔结果无效。改成一块一块分别做, 碰不到工具的块原样留着 (切除) 或扔掉 (求交)。"""
    mapping = _indexed(body, TopAbs_SOLID)
    parts = [mapping.FindKey(index) for index in range(1, mapping.Extent() + 1)]
    if len(parts) < 2:
        return None
    low, high = _rough_bounds(solid)
    kept = []
    for part in parts:
        part_low, part_high = _rough_bounds(part)
        if any(part_high[axis] < low[axis] or high[axis] < part_low[axis] for axis in range(3)):
            if operation == 'cut':
                kept.append(part)
            continue
        raw = _raw_boolean(part, solid, operation)
        if _is_empty(raw):                      # 这一块被整个切掉了 / 和工具不重叠
            continue
        result = _checked_result(part, solid, raw, operation, what)
        mapping = _indexed(result, TopAbs_SOLID)
        kept += [mapping.FindKey(index) for index in range(1, mapping.Extent() + 1)]
    if not kept:
        raise FeatureError('切除后实体被完全切掉了' if operation == 'cut' else '和现有实体没有重叠的部分')
    builder, result = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(result)
    for part in kept:
        builder.Add(result, part)
    return result


def _rough_bounds(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)      # 只用来筛碰不碰得到: 粗的就行 (精确的每张面要一毫秒, 导入件几千张面)
    low, high = box.CornerMin(), box.CornerMax()
    return (low.X(), low.Y(), low.Z()), (high.X(), high.Y(), high.Z())


def _separated_add(body, solid, what):
    mapping = _indexed(body, TopAbs_SOLID)
    parts = [mapping.FindKey(index) for index in range(1, mapping.Extent() + 1)]
    mapping = _indexed(solid, TopAbs_SOLID)
    parts += [mapping.FindKey(index) for index in range(1, mapping.Extent() + 1)]
    if not parts or len(parts) * (len(parts) - 1) // 2 > 64:
        return None
    boxes = [bounds(part) for part in parts]
    if not all(math.isfinite(value) for low, high in boxes for value in (*low, *high)):
        return None
    for index, (low, high) in enumerate(boxes):
        for other_low, other_high in boxes[:index]:
            if not any(high[axis] <= other_low[axis] or other_high[axis] <= low[axis] for axis in range(3)):
                return None
    validated_base = checked_tool_solid(body, what)
    builder, result = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(result)
    builder.Add(result, validated_base)
    builder.Add(result, solid)
    check_boolean_shape(result, validated_base, what)
    check_boolean_volume(validated_base, solid, result, 'add', what)
    expected_volume = math.fsum((signed_volume(validated_base), signed_volume(solid)))
    if abs(signed_volume(result) - expected_volume) > max(1e-6, abs(expected_volume) * 1e-8):
        raise FeatureError(f'{what}失败：分离实体的体积总和异常')
    expected_low = tuple(min(low[axis] for low, _ in boxes) for axis in range(3))
    expected_high = tuple(max(high[axis] for _, high in boxes) for axis in range(3))
    actual_low, actual_high = bounds(result)
    if any(abs(actual - expected) > 1e-7 for actual, expected in
           zip((*actual_low, *actual_high), (*expected_low, *expected_high))):
        raise FeatureError(f'{what}失败：分离实体的包围盒异常')
    return result


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
