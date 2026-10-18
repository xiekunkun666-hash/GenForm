"""新工具体校验与布尔结果的有界完整性检查。"""
from __future__ import annotations

import math
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepGProp import BRepGProp_Domain, BRepGProp_Face, BRepGProp_Vinert
from OCP.BRepLib import BRepLib
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_FACE, TopAbs_OUT, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS_Compound, TopoDS_Iterator

from ..model.base import FeatureError
from ..occ_compat import _as_face, _as_solid, TopTools_IndexedMapOfShape


_TOOLS = []
_VOLUMES = []
_KEEP_VOLUMES = 128              # 按块记: 一个阵列一步里几十块, 还要留着上一步的实体给下一步当 "原体积"
_FACES = {}                      # 每张面的积分: hash → [(面, 方式, 参考点, 体积, 误差, 一阶矩)...] (见 _face_integral)
_KEEP_FACES = 40000
_FACE_COUNT = [0]                # _FACES 里一共记了几条 (每积一张面都去数一遍: 六千多张面的导入件光数就要十几秒)


def _parts(shape, kind):
    explorer, parts = TopExp_Explorer(shape, kind), []
    while explorer.More():
        parts.append(explorer.Current())
        explorer.Next()
    return parts


def _compound(parts):
    builder, result = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(result)
    for part in parts:
        builder.Add(result, part)
    return result


def _solids(shape, what):
    pending, solids = [shape], []
    while pending:
        part = pending.pop()
        if part is None or part.IsNull():
            raise FeatureError(f'{what}失败：没有生成实体')
        if part.ShapeType() == TopAbs_SOLID:
            solids.append(part)
        elif part.ShapeType() in (TopAbs_COMPOUND, TopAbs_COMPSOLID):
            iterator = TopoDS_Iterator(part)
            while iterator.More():
                pending.append(iterator.Value())
                iterator.Next()
        else:
            raise FeatureError(f'{what}失败：结果含有未成实体的面或线')
    if not solids:
        raise FeatureError(f'{what}失败：没有生成实体')
    return solids


def signed_volume(shape, precise=False):
    """形状的体积。由几块实体拼成的 (阵列、镜像出来的一堆复制体…) 按块分别算再加起来: 每块记在 _VOLUMES 里,
    拼进新结果的老实体不用再积一遍分 (911 后轮阵列一步原来光体积就积了 60 多次、10 秒)。
    precise=True 时用自适应积分 (相对误差 1e-6), 误差估计见 volume_error。"""
    return _volume(shape, precise)[0]


def volume_error(shape):
    """precise 体积的绝对误差上限 (积分自己估出来的)。"""
    return _volume(shape, True)[1]


def mass(shape):
    """(体积, 质心): 显示用的质量属性也从这里拿, 积分方式和布尔校验先用的那种一样 (见 _tiers) — 校验刚积过分的
    实体直接用记着的。解析曲面不能一律用自适应积分: 椭圆柱上它反而差到 2e-5, 普通积分是准的。"""
    volume, _, moment = _volume(shape, _tiers(shape)[0])
    if not volume:
        return 0.0, (0.0, 0.0, 0.0)
    return volume, tuple(value / volume for value in moment)


def _volume(shape, precise):
    """→ (体积, 误差, 一阶矩 (体积 × 质心))。"""
    if shape is not None and not shape.IsNull() and shape.ShapeType() in (TopAbs_COMPOUND, TopAbs_COMPSOLID):
        solids = _parts(shape, TopAbs_SOLID)
        if len(solids) > 1:
            pieces = [_solid_volume(solid, precise) for solid in solids]
            return (math.fsum(piece[0] for piece in pieces), math.fsum(piece[1] for piece in pieces),
                    tuple(math.fsum(piece[2][axis] for piece in pieces) for axis in range(3)))
    return _solid_volume(shape, precise)


def _solid_volume(shape, precise):
    for saved, accurate, volume, error, moment in _VOLUMES:
        if accurate == precise and saved.IsEqual(shape):
            return volume, error, moment
    # 一张面一张面积分再加起来 (OpenCascade 的 VolumeProperties 里面也是这么做的), 参考点取整个形状的一个粗略的整点:
    # 布尔前后没变的面 (绝大多数) 参考点一样, 积分直接用记着的 — 每一步只积新面。911 车身两千多张面, 原来每一步整个
    # 积两遍要三秒多。没变的面两边的值一模一样, 前后体积之差只来自新面, 比整个重积分一遍更准。
    origin = _reference_point(shape)
    volume, error, moment = 0.0, 0.0, [0.0, 0.0, 0.0]
    for face in _parts(shape, TopAbs_FACE):
        part_volume, part_error, part_moment = _face_integral(face, precise, origin)
        volume += part_volume
        error += part_error
        for axis in range(3):
            moment[axis] += part_moment[axis]
    moment = tuple(moment)
    _VOLUMES.append((shape, precise, volume, error, moment))
    del _VOLUMES[:-_KEEP_VOLUMES]
    return volume, error, moment


def _reference_point(shape):
    """积分的参考点: 包围盒中心取到粗一档的整数 (零件 5 米就取到整米)。离零件近, 数值上准; 取整了以后布尔前后
    (包围盒差不多) 还是同一个点, 面的积分才能接着用。"""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)      # 粗略的就行 (精确的 AddOptimal 在两千张样条面上要零点几秒)
    if box.IsVoid():
        return (0.0, 0.0, 0.0)
    corner, other = box.CornerMin(), box.CornerMax()
    low, high = (corner.X(), corner.Y(), corner.Z()), (other.X(), other.Y(), other.Z())
    size = max(max(h - l for l, h in zip(low, high)), 1e-9)
    step = 10.0 ** math.floor(math.log10(size))
    return tuple(round((l + h) / 2 / step) * step + 0.0 for l, h in zip(low, high))


def _face_integral(face, precise, origin):
    """一张面对体积的贡献 (散度定理: 以 origin 为顶点、以这张面为底的锥体) → (体积, 误差, 一阶矩)。"""
    key = hash(face)
    for saved, accurate, where, volume, error, moment in _FACES.get(key, ()):
        if accurate == precise and where == origin and saved.IsEqual(face):
            return volume, error, moment
    from OCP.gp import gp_Pnt
    face = _as_face(face)
    point = gp_Pnt(*origin)
    surface = BRepGProp_Face(face)
    if TopoDS_Iterator(face).More():            # 有边界 (绝大多数): 按边界裁出来的那块积分
        domain = BRepGProp_Domain(face)
        integral = BRepGProp_Vinert(surface, domain, point, 1e-6) if precise else BRepGProp_Vinert(surface, domain, point)
    else:                                       # 没边界的整张曲面 (球面…)
        integral = BRepGProp_Vinert(surface, point, 1e-6) if precise else BRepGProp_Vinert(surface, point)
    volume = integral.Mass()
    error = abs(volume) * abs(integral.GetEpsilon()) if precise else 0.0
    if not math.isfinite(error):
        error = abs(volume)
    centre = integral.CentreOfMass() if volume else None
    moment = (volume * centre.X(), volume * centre.Y(), volume * centre.Z()) if centre is not None else (0.0, 0.0, 0.0)
    if _FACE_COUNT[0] >= _KEEP_FACES:
        _FACES.clear()
        _FACE_COUNT[0] = 0
    _FACES.setdefault(key, []).append((face, precise, origin, volume, error, moment))
    _FACE_COUNT[0] += 1
    return volume, error, moment


def _tiers(*shapes):
    """先用哪种积分: 全是平面、圆柱这类解析曲面的, 普通积分就准到 1e-8, 先试它; 带样条面的普通积分到不了,
    直接用自适应的 (911 车身上每一步都白积一遍, 一步一秒多)。"""
    return (True,) if any(_freeform(shape) for shape in shapes) else (False, True)


def _freeform(shape):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_BezierSurface, GeomAbs_BSplineSurface, GeomAbs_OffsetSurface, GeomAbs_OtherSurface
    kinds = (GeomAbs_BezierSurface, GeomAbs_BSplineSurface, GeomAbs_OffsetSurface, GeomAbs_OtherSurface)
    for face in _parts(shape, TopAbs_FACE):
        if BRepAdaptor_Surface(_as_face(face), False).GetType() in kinds:
            return True
    return False


def checked_tool_solid(shape, what='特征'):
    for saved, checked in _TOOLS:
        if shape is not None and saved.IsEqual(shape):
            return checked
    checked = []
    for part in _solids(shape, what):
        shells = _parts(part, TopAbs_SHELL)
        if not shells or not all(BRep_Tool.IsClosed_s(shell) for shell in shells):
            raise FeatureError(f'{what}失败：实体壳未封闭，请检查闭环接缝或轮廓，或改用分段建模')
        solid = _as_solid(BRepBuilderAPI_Copy(part, False, False).Shape())
        if not BRepLib.OrientClosedSolid_s(solid):
            raise FeatureError(f'{what}失败：实体的朝向不一致')
        if not BRepCheck_Analyzer(solid).IsValid():
            raise FeatureError(f'{what}失败：工具体无效，请检查轮廓、自交或闭环接缝')
        classifier = BRepClass3d_SolidClassifier(solid)
        classifier.PerformInfinitePoint(1e-7)
        if classifier.State() != TopAbs_OUT:
            raise FeatureError(f'{what}失败：实体不能确定有限的内外区域')
        volume = signed_volume(solid)
        if not math.isfinite(volume) or volume <= 1e-9:
            raise FeatureError(f'{what}失败：实体没有有限的正体积')
        checked.append(solid)
    result = checked[0] if len(checked) == 1 else _compound(checked)
    _TOOLS.extend([(shape, result), (result, result)])
    del _TOOLS[:-16]
    return result


def trust_tool_solid(shape):
    """shape 是一块块过了 checked_tool_solid 的实体拼成的: 记下来, 合并进实体时不用再整个查一遍 (导入的几十个零件要好几秒)。"""
    _TOOLS.append((shape, shape))
    del _TOOLS[:-16]
    return shape


def check_boolean_shape(shape, base, what):
    old_solids = _parts(base, TopAbs_SOLID)
    for solid in _solids(shape, what):
        if any(solid.IsEqual(old) for old in old_solids):
            continue
        shells = _parts(solid, TopAbs_SHELL)
        if not shells or not all(BRep_Tool.IsClosed_s(shell) for shell in shells):
            raise FeatureError(f'{what}失败：布尔结果壳未封闭，已保留运算前实体')
        classifier = BRepClass3d_SolidClassifier(solid)
        classifier.PerformInfinitePoint(1e-7)
        if classifier.State() != TopAbs_OUT:
            raise FeatureError(f'{what}失败：布尔结果实体朝向错误，已保留运算前实体')
    if not BRepCheck_Analyzer(shape, False).IsValid():
        raise FeatureError(f'{what}失败：布尔结果拓扑无效，已保留运算前实体')
    old_faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(base, TopAbs_FACE, old_faces)
    new_faces = [face for face in _parts(shape, TopAbs_FACE) if not old_faces.Contains(face)]
    if new_faces and not BRepCheck_Analyzer(_compound(new_faces)).IsValid():
        raise FeatureError(f'{what}失败：布尔结果的新面无效，已保留运算前实体')


def check_boolean_volume(base, tool, result, operation, what):
    for precise in _tiers(base, tool, result):
        before, added, after = [signed_volume(shape, precise) for shape in (base, tool, result)]
        if not all(math.isfinite(volume) and volume > 0 for volume in (before, added, after)):
            raise FeatureError(f'{what}失败：布尔结果或输入体积不是有限正数')
        tolerance = max(1e-6, max(before, added, after) * 1e-8)
        if precise:     # 样条实体普通积分到不了 1e-8, 自适应积分把自己的误差估计带上
            tolerance += 2 * sum(volume_error(shape) for shape in (base, tool, result))
        if operation == 'add':
            tool_floor = max(signed_volume(part, precise) for part in _solids(tool, what))
            low, high = max(before, tool_floor), before + added
        elif operation == 'cut':
            low, high = max(0.0, before - added), before
        else:
            low, high = 0.0, min(before, added)
        if low - tolerance <= after <= high + tolerance:
            return
    raise FeatureError(f'{what}失败：{operation} 布尔体积异常（原体积 {before:.12g}，'
                       f'工具 {added:.12g}，结果 {after:.12g}），已保留运算前实体')


def check_unify_volume(raw, result, what):
    if raw.IsEqual(result):
        return
    for precise in _tiers(raw, result):
        before, after = signed_volume(raw, precise), signed_volume(result, precise)
        tolerance = max(1e-6, abs(before) * 1e-8)
        if precise:
            tolerance += 2 * (volume_error(raw) + volume_error(result))
        if math.isfinite(after) and abs(before - after) <= tolerance:
            return
    raise FeatureError(f'{what}失败：合并同面改变了体积（{before:.12g} → {after:.12g}），已保留运算前实体')
