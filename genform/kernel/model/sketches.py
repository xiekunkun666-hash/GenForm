"""草图 → OCC 的线框和面: 基本曲线 → 边、闭合环 → 线框、文字 → 面。"""
from __future__ import annotations

import math
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
from OCP.BRep import BRep_Builder
from OCP.Geom import Geom_BezierCurve
from OCP.TopoDS import TopoDS_Compound
from OCP.gp import gp_Ax1, gp_Ax2, gp_Circ, gp_Dir, gp_Elips, gp_Pnt, gp_Vec

from ..occ_compat import _PointArray
from ... import planes, sketchgeom
from .base import FeatureError
from .solids import _boolean, extrude_solid


# ---------------------------------------------------------------------------
# 草图
# ---------------------------------------------------------------------------
def plane_frame(params, features=()):
    """草图所在的坐标系 → (原点, X 方向, Y 方向, 法向), 都是 numpy 向量。plane 可以是 XY / XZ / YZ 或基准面特征的 id。"""
    from ... import features as table
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
        self.tools = {}                 # 造型特征 id → (工具体, 方式): 阵列和镜像复制的就是它; 阵列 / 镜像 → [(工具体, 方式)...]
        self.copied = None              # 正在算的阵列 / 镜像复制出来的 [(工具体, 方式)...] (见 ops/patterns.py)
        self.seen_faces = {}            # 本轮面几何缓存 (hash → [记录...]), 见 faces._face_record
        self.sources = {}               # 阵列 / 镜像 id → 和 tools 里一份份复制体对应的 "原件特征 id" 列表
        self.origins = {}               # 当前实体的面序号 → 这张面是从哪个特征复制来的 (只有阵列、镜像做出的面有)
        self.display = {}               # 曲线 / 参考几何体 id → 显示用的线
        self.info = {}                  # 特征 id → 算出来的一句话 (质心坐标、边界框尺寸)
        self.helix_axis = {}            # 螺旋线 id → 轴的方向
        self.current = None             # 正在算的特征 id (造工具体的函数要往 info 里写一句时用)

    def make(self, kind, params, body):
        """按参数造一个工具体 (变量阵列: 同一个特征换几个尺寸再造一遍)。"""
        from .. import features as more
        if kind == 'extrude':
            return extrude_solid(params, self, body)
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
    faces, glyphs = [], []
    for letter in text:
        # 先渲染再取宽度: AdvanceX(字) 给的其实是 "刚加载的那个字形" 的宽度 — 新字体上全是 0 (字全叠在一起,
        # 拉伸出来的工具体自己和自己重叠, 布尔把实体算没了), 渲染过别的字后全是最后那个字的宽度
        glyph = font.RenderGlyph(letter)
        glyphs.append((glyph, float(font.AdvanceX(letter))))
    spots = sketchgeom.text_layout(shape, [advance for _, advance in glyphs])
    for (glyph, _), (x, y, turn) in zip(glyphs, spots):
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
