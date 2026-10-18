"""读别的 CAD 的 STEP 文件, 整理成实体: 零件里的 "导入实体" 特征和装配体里的 STEP 零部件都用它。

STEP 里不一定是实体: SOLIDWORKS 按曲面模型导出 (SHELL_BASED_SURFACE_MODEL) 时全是一个个壳, 有的封闭标记没设上,
有的真缺了面。整理的做法:
    1. 本来就是实体的直接用;
    2. 不在实体里的壳和散面放在一起缝合, 缝完封闭的壳 → 实体;
    3. 还有缺口的壳: 缺口是平面上的环就补一张平面 (同一平面里套在大环里的小环是这张面上的孔), 补完再缝一次;
    4. 补不上的, 和体积几乎为零、过不了实体检查的碎块一起略过, 只报个数。
同一个文件没改过就用上次读的 (_FILES, 按修改时间和大小认): 读一个二十多兆的 STEP 要十来秒。
"""
from __future__ import annotations

import os

from OCP.BRep import BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import GeomAbs_Plane
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Solid
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_IN, TopAbs_ON, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound

from ..model.base import FeatureError
from ..occ_compat import _as_face, _as_wire
from .solid_validation import checked_tool_solid, trust_tool_solid

_as_shell = getattr(TopoDS, 'Shell_s', None) or TopoDS.Shell
_as_vertex = getattr(TopoDS, 'Vertex_s', None) or TopoDS.Vertex
SEW_TOLERANCES = (0.01, 0.1)    # mm: 先细后粗; SOLIDWORKS 导出的接缝一般在 0.01 以内
_FILES = {}                     # 规范化的完整路径 → ((修改时间, 大小), (实体, 说明))


def _parts(shape, kind, avoid=None):
    explorer = TopExp_Explorer(shape, kind) if avoid is None else TopExp_Explorer(shape, kind, avoid)
    found = []
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def _compound(parts):
    builder, result = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(result)
    for part in parts:
        builder.Add(result, part)
    return result


def _area(face):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return abs(props.Mass())


def _gaps(shell, tolerance):
    """壳上的缺口 → (闭合的边界环, 有没有不闭合的边界)。"""
    bounds = ShapeAnalysis_FreeBounds(shell, tolerance, False, False)
    return _parts(bounds.GetClosedWires(), TopAbs_WIRE), bool(_parts(bounds.GetOpenWires(), TopAbs_WIRE))


def _inside(loop, outer, tolerance):
    """环 loop 是不是在平面 outer 上、并且在它的范围里 (= outer 上的一个孔)。"""
    plane = BRepAdaptor_Surface(outer).Plane()
    from OCP.BRep import BRep_Tool
    for vertex in _parts(loop, TopAbs_VERTEX):
        point = BRep_Tool.Pnt_s(_as_vertex(vertex))
        if plane.Distance(point) > tolerance:
            return False
        if BRepClass_FaceClassifier(outer, point, tolerance).State() not in (TopAbs_IN, TopAbs_ON):
            return False
    return True


def _patches(loops, tolerance):
    """缺口的环 → 补上的平面; 有一个环不在平面上就补不了 (None)。大环先当外轮廓, 套在里面的小环当它的孔。"""
    faces = []
    for loop in loops:
        maker = BRepBuilderAPI_MakeFace(_as_wire(loop), True)
        if not maker.IsDone() or BRepAdaptor_Surface(maker.Face()).GetType() != GeomAbs_Plane:
            return None
        faces.append((maker.Face(), loop))
    faces.sort(key=lambda item: -_area(item[0]))
    groups = []                                 # [外轮廓的面, [孔的环...]]
    for face, loop in faces:
        owner = next((group for group in groups if _inside(loop, group[0], tolerance)), None)
        if owner is None:
            groups.append([face, []])
        else:
            owner[1].append(loop)
    patched = []
    for outer, holes in groups:
        maker = BRepBuilderAPI_MakeFace(outer)
        for hole in holes:
            maker.Add(_as_wire(hole))
        fix = ShapeFix_Face(maker.Face())
        fix.FixOrientation()                    # 孔的环朝向反了也没关系: 修成和外轮廓相反
        fix.Perform()
        patched.append(fix.Face())
    return patched


def _sew(shapes, tolerance):
    sewing = BRepBuilderAPI_Sewing(tolerance)
    for shape in shapes:
        sewing.Add(shape)
    sewing.Perform()
    return _parts(sewing.SewedShape(), TopAbs_SHELL)


def _close(shell, tolerance):
    """一个壳 → 封闭的壳; 补不上: None。"""
    loops, broken = _gaps(shell, tolerance)
    if not loops and not broken:
        return shell
    if broken:
        return None
    patches = _patches(loops, tolerance)
    if not patches:
        return None
    for result in _sew([shell] + patches, tolerance):
        loops, broken = _gaps(result, tolerance)
        if len(_parts(result, TopAbs_FACE)) > len(patches) and not loops and not broken:
            return result
    return None


def _checked(solid, kept):
    try:
        kept.append(checked_tool_solid(solid, '导入'))
        return True
    except FeatureError:
        return False


def solidify(shape):
    """STEP 读出来的形状 → (所有实体拼成的一块, 一句说明: 修了什么、略过了什么)。一块实体也拼不出来: FeatureError。"""
    kept, dropped = [], 0
    for solid in _parts(shape, TopAbs_SOLID):
        dropped += not _checked(solid, kept)
    loose = _parts(shape, TopAbs_SHELL, TopAbs_SOLID) + _parts(shape, TopAbs_FACE, TopAbs_SHELL)
    repaired = 0
    if loose:
        tolerance = SEW_TOLERANCES[0]
        pending = []
        for shell in _sew(loose, tolerance):
            closed = _close(shell, tolerance)
            if closed is None:
                pending.append(shell)
                continue
            repaired += closed is not shell
            dropped += not _checked(ShapeFix_Solid().SolidFromShell(_as_shell(closed)), kept)
        for tolerance in SEW_TOLERANCES[1:]:    # 细的公差缝不上的: 放粗再试一次
            if not pending:
                break
            shells, pending = _sew(pending, tolerance), []
            for shell in shells:
                closed = _close(shell, tolerance)
                if closed is None:
                    pending.append(shell)
                    continue
                repaired += closed is not shell
                dropped += not _checked(ShapeFix_Solid().SolidFromShell(_as_shell(closed)), kept)
        dropped += sum(1 for shell in pending if len(_parts(shell, TopAbs_FACE)) > 1)
    if not kept:
        raise FeatureError('STEP 文件里没有能变成实体的东西（只有开口的曲面或线）')
    notes = [f'{len(kept)} 个实体']
    if loose:
        notes.append('由曲面缝合而成')
    if repaired:
        notes.append(f'补了 {repaired} 处缺面')
    if dropped:
        notes.append(f'略过 {dropped} 个封不住的曲面 / 碎块')
    return (kept[0] if len(kept) == 1 else trust_tool_solid(_compound(kept))), '，'.join(notes)


def read_step(path):
    """STEP 文件 → (实体, 说明)。同一个文件没改过就用上次读的。"""
    full = os.path.abspath(str(path))
    try:
        stat = os.stat(full)
    except OSError as error:
        raise FeatureError(f'打不开 {path}：{error.strerror or error}') from None
    if not os.path.isfile(full):
        raise FeatureError(f'{path} 不是文件')
    key, stamp = os.path.normcase(full), (stat.st_mtime_ns, stat.st_size)
    cached = _FILES.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    reader = STEPControl_Reader()
    if reader.ReadFile(full) != IFSelect_RetDone:
        raise FeatureError(f'读不了 STEP 文件 {path}')
    if not reader.TransferRoots():
        raise FeatureError(f'STEP 文件 {path} 里没有几何')
    result = solidify(reader.OneShape())
    _FILES.clear()                              # 只记最近的一个: 一个二十多兆的 STEP 读出来就占好几百兆内存
    _FILES[key] = (stamp, result)
    return result


def import_step(body, params, ctx):
    """导入实体特征: 读 params['path'] 的 STEP 文件, 当作工具体 (按 op 并进实体)。"""
    path = str(params.get('path') or '').strip().strip('"')
    if not path:
        raise FeatureError('还没选 STEP 文件')
    if not path.lower().endswith(('.step', '.stp')):
        raise FeatureError('导入实体只认 .step / .stp 文件')
    solid, note = read_step(path)
    if ctx.current:
        ctx.info[ctx.current] = note
    return solid
