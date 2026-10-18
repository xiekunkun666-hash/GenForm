# -*- coding: utf-8 -*-
"""空心件 (钣金车身、壳体) 的三种方式 — 不用偏移曲面, 空腔就是一块普通的工具体:

- void 挖空腔: 工具体整个在实体里面, 变成实体里的封闭空腔 (外壳 + 反过来的空腔壳, 不做布尔); 和已有的空腔重叠时并成一个。
  外形和内形各放样一次 (内截面往里让一个壁厚), 就是一个 2 mm 的钣金车身。抽壳那样往里偏出来的是偏移曲面,
  后面再开窗、装零件, 布尔碰上偏移曲面常常算坏 (911 车身: 抽壳后第一个车窗就 "拓扑无效")。
- fill 填空腔: 只在空腔里长材料 (空腔减去工具体): 地板、防火墙、隔板天然和车皮连成一体, 也不会伸出车外。
- pocket 钣金凹槽: 在空心件上挖凹槽, 槽壁和槽底自动留一层壁厚 (工具体往外偏一个壁厚填进空腔, 再切掉工具体):
  灯碗、进气口、轮罩。实心件上就是普通的切除。

空腔用实体的内层壳表示; 车窗一类切穿车皮的切除会把空腔和外面连通, 那之后就没有封闭空腔了, 所以这几种方式要在开窗之前做。
"""
from __future__ import annotations

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepLib import BRepLib
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
from OCP.TopAbs import TopAbs_IN, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopoDS import TopoDS

from ..model.base import FeatureError
from .solid_validation import signed_volume

DEFAULT_WALL = 2.0
_as_shell = getattr(TopoDS, 'Shell_s', None) or TopoDS.Shell
_as_solid = getattr(TopoDS, 'Solid_s', None) or TopoDS.Solid
_as_face = getattr(TopoDS, 'Face_s', None) or TopoDS.Face


def _explore(shape, kind):
    from OCP.TopExp import TopExp_Explorer
    found, explorer = [], TopExp_Explorer(shape, kind)
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def parse(operation):
    """'pocket' / 'pocket:1.5' → ('pocket', 1.5); 别的原样 → (operation, None)。"""
    name, _, wall = str(operation).partition(':')
    if name == 'pocket':
        return name, float(wall) if wall else DEFAULT_WALL
    return name, None


def split(body):
    """一块实体 → (外层壳, [每个空腔当成一块正向的实体])。不是一块实体时报错。"""
    solids = _explore(body, TopAbs_SOLID)
    if len(solids) != 1:
        raise FeatureError(f'空腔只能做在一整块实体里 (现在有 {len(solids)} 块)')
    from OCP.BRepClass3d import BRepClass3d
    outer = BRepClass3d.OuterShell_s(_as_solid(solids[0]))
    voids = []
    for shell in _explore(solids[0], TopAbs_SHELL):
        if shell.IsSame(outer):
            continue
        void = BRepBuilderAPI_MakeSolid(_as_shell(shell.Reversed())).Solid()
        if signed_volume(void) < 0:
            void = void.Reversed()
        voids.append(void)
    return outer, voids


def assemble(outer, voids, what):
    """外层壳 + 几个空腔 → 一块空心实体。"""
    maker = BRepBuilderAPI_MakeSolid(_as_shell(outer))
    for void in voids:
        for shell in _explore(void, TopAbs_SHELL):
            maker.Add(_as_shell(shell.Reversed()))
    solid = maker.Solid()
    if not BRepLib.OrientClosedSolid_s(solid) or not BRepCheck_Analyzer(solid).IsValid():
        raise FeatureError(f'{what}失败：拼出来的空心实体无效')
    return solid


def _boolean(operation, base, tool, what):
    from ..model.solids import _boolean as boolean
    return boolean(operation, base, tool, what)


def _sample_points(shape, per_face=3):
    """工具体表面上的一些点: 每张面在参数域里取个小网格, 只留落在面里面的 (裁剪过的面, 参数矩形比面大)。"""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_FACE
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt2d
    points = []
    for face in _explore(shape, TopAbs_FACE):
        face = _as_face(face)
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        surface = BRepAdaptor_Surface(face)
        for i in range(per_face):
            for j in range(per_face):
                u = u0 + (u1 - u0) * (i + 0.5) / per_face
                v = v0 + (v1 - v0) * (j + 0.5) / per_face
                if BRepClass_FaceClassifier(face, gp_Pnt2d(u, v), 1e-7).State() == TopAbs_IN:
                    points.append(surface.Value(u, v))
    return points


def _inside(outer, tool, what):
    """工具体要整个在外壳里面: 表面取点都在里面, 而且和外壳没有交线。"""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.TopAbs import TopAbs_EDGE
    solid = BRepBuilderAPI_MakeSolid(_as_shell(outer)).Solid()
    for point in _sample_points(tool):
        if BRepClass3d_SolidClassifier(solid, point, 1e-6).State() != TopAbs_IN:
            raise FeatureError(f'{what}：空腔要整个在实体里面 (有一部分在外面或贴着外表面)')
    section = BRepAlgoAPI_Section(solid, tool)
    section.Build()
    if section.IsDone() and _explore(section.Shape(), TopAbs_EDGE):
        raise FeatureError(f'{what}：空腔穿出了实体的外表面 (壁太薄的地方内外两层交叉了)')


def void(body, tool, what):
    outer, voids = split(body)
    _inside(outer, tool, what)
    pieces = [piece for piece in _explore(tool, TopAbs_SOLID)] or [tool]
    if voids:
        merged = _boolean(BRepAlgoAPI_Fuse, voids[0], _compound(voids[1:] + pieces), f'{what}：合并空腔')
        voids = _explore(merged, TopAbs_SOLID)
    else:
        voids = pieces
    result = assemble(outer, voids, what)
    _check(body, result, what)
    return result


def fill(body, tool, what):
    outer, voids = split(body)
    if not voids:
        raise FeatureError(f'{what}：实体里没有封闭的空腔可填 (开窗、切穿车皮之后空腔就和外面连通了：填空腔要做在那之前)')
    before = sum(signed_volume(item) for item in voids)
    remaining = _explore(_boolean(BRepAlgoAPI_Cut, _compound(voids), tool, f'{what}：填空腔'), TopAbs_SOLID)
    if not all(BRepCheck_Analyzer(item).IsValid() for item in remaining):
        raise FeatureError(f'{what}：填完的空腔无效 (工具体的面和空腔内壁贴得太近、几乎相切；挪开一点或改小一点)')
    after = sum(signed_volume(item) for item in remaining)
    if before - after < 1e-6 * max(before, 1.0):
        raise FeatureError(f'{what}：工具体碰不到空腔')
    result = assemble(outer, remaining, what)
    _check(body, result, what)
    return result


def pocket(body, tool, wall, what):
    """钣金凹槽: 实心件上直接切; 空心件上先把工具体往外偏 wall 填进空腔 (槽壁、槽底), 再切工具体。"""
    from ..model.solids import combine
    outer, voids = split(body)
    if voids:
        linings = []
        for piece in _explore(tool, TopAbs_SOLID) or [tool]:          # 一张草图里好几个槽: 一块一块往外偏
            maker = BRepOffsetAPI_MakeOffsetShape()
            maker.PerformByJoin(piece, wall, 1e-3)
            if not maker.IsDone() or maker.Shape().IsNull():
                raise FeatureError(f'{what}：凹槽的工具体往外偏 {wall:g} mm 做不出来')
            linings.append(maker.Shape())
        try:
            body = fill(body, linings[0] if len(linings) == 1 else _compound(linings), what)
        except FeatureError as error:
            if '碰不到空腔' not in str(error):
                raise
    return combine(body, tool, 'cut', what)


def _compound(shapes):
    from ..model.sketches import _compound as compound
    return compound(shapes)


def _check(body, result, what):
    """新实体的体积 = 外壳围的体积 - 空腔 (拼的时候没有布尔, 这里是确认空腔壳都朝对了)。"""
    from .solid_validation import volume_error
    outer, voids = split(result)
    shapes = [BRepBuilderAPI_MakeSolid(_as_shell(outer)).Solid()] + voids
    expected = signed_volume(shapes[0], True) - sum(signed_volume(item, True) for item in voids)
    actual = signed_volume(result, True)
    # 车身外形 6×10⁹、车皮只有 5×10⁷: 两个大数相减, 要用自适应积分, 容差按积分自己估的误差给;
    # 要抓的是空腔壳朝反了, 那样会差出两倍的空腔体积
    slack = 2 * (volume_error(result) + sum(volume_error(item) for item in shapes)) + 1e-9 * abs(signed_volume(shapes[0], True)) + 1e-6
    if actual <= 0 or abs(actual - expected) > slack:
        raise FeatureError(f'{what}失败：空心实体的体积对不上 ({actual:.6g} / {expected:.6g})')
