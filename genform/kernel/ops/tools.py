"""造工具体的特征: 旋转、扫描、放样、孔 (各种孔型)、螺柱、螺钉。"""
from __future__ import annotations

import math
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_CompCurve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe, BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_WIRE
from OCP.gp import gp_Ax1, gp_Ax2, gp_Vec

from ..build import FeatureError
from ..occ_compat import _as_wire
from .. import build
from ... import features as table
from .helpers import _axis, _dir, _explore, _need_body, _number, _path, _pnt, _profile, _reach, _run, _sketch, _spots, _volume
from .sweep_geometry import check_closed_sweep_profile, checked_sweep_solid
from .solid_validation import checked_tool_solid
from .importing import import_step


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
    if params.get('reverse'):                               # 反向: 往另一边转
        direction = -np.asarray(direction, dtype=float)
    profile, axis = sketch.profile, gp_Ax1(_pnt(origin), _dir(direction))
    if params.get('symmetric') and abs(angle) < 360.0 - 1e-9:      # 两侧对称: 轮廓先往回转一半
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Trsf
        back = gp_Trsf()
        back.SetRotation(axis, -math.radians(angle) / 2)
        profile = BRepBuilderAPI_Transform(profile, back, True).Shape()
    solid = _run(BRepPrimAPI_MakeRevol(profile, axis, math.radians(angle)), '旋转失败：轮廓不能跨过旋转轴')
    if abs(_volume(solid).Mass()) < 1e-9:
        raise FeatureError('旋转不出实体：轮廓和旋转轴不在同一个平面上，或轮廓就在轴上')
    return checked_tool_solid(solid, '旋转')


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
        adaptor = BRepAdaptor_CompCurve(spine)
    check_closed_sweep_profile(spine, adaptor, sketch)
    if identifier in ctx.helix_axis:               # 沿螺旋线扫: 轮廓的朝向相对轴线保持不变, 不然会越扫越拧
        shell = BRepOffsetAPI_MakePipeShell(spine)
        shell.SetMode(_dir(ctx.helix_axis[identifier]))
        shell.Add(sketch.wires[0])
        _run(shell, '扫描失败：轮廓太大（和相邻的圈碰上了），或轮廓不在螺旋线的起点处')
        if not shell.MakeSolid():
            raise FeatureError('扫描出来的面合不成实体')
        return checked_sweep_solid(shell.Shape())
    from OCP.BRepBuilderAPI import BRepBuilderAPI_RightCorner
    from OCP.GeomAbs import GeomAbs_C0
    trouble = '扫描失败：路径拐得太急（比轮廓还小的弯），或轮廓不在路径的起点处'
    if adaptor.Continuity() != GeomAbs_C0:     # 路径是光顺的: 普通的管道扫描 (轮廓里的孔也带着)
        try:
            solid = _run(BRepOffsetAPI_MakePipe(spine, sketch.profile), trouble)
            return checked_sweep_solid(solid)
        except FeatureError:
            if len(_explore(sketch.profile, TopAbs_WIRE)) != 1:
                raise
    shell = BRepOffsetAPI_MakePipeShell(spine)          # 路径上有尖角: 在拐角处把两段接成直角 (只用轮廓的外圈)
    shell.SetTransitionMode(BRepBuilderAPI_RightCorner)
    shell.Add(sketch.wires[0])
    _run(shell, trouble)
    if not shell.MakeSolid():
        raise FeatureError(trouble)
    return checked_sweep_solid(shell.Shape())


def loft(body, params, ctx):
    identifiers = params.get('sketches') or []
    if len(identifiers) < 2:
        raise FeatureError('放样至少要两个草图轮廓')
    maker = BRepOffsetAPI_ThruSections(True, bool(params.get('ruled')), 1e-6)
    wires = [_profile(ctx, {'sketch': identifier}).wires[0] for identifier in identifiers]
    for wire in wires:
        maker.AddWire(wire)
    # 边数不一样 (矩形 → 圆) 才要 OpenCascade 先把轮廓重新分段对齐; 边数一样时一条对一条就行 —
    # 这一步碰上一串闭合样条 (车身截面) 会算上好几分钟, 不做只要几十毫秒
    counts = {build._indexed(wire, TopAbs_EDGE).Extent() for wire in wires}
    maker.CheckCompatibility(len(counts) > 1)
    solid = _run(maker, '放样失败：这几个轮廓过渡不过去（是不是在同一个平面上，或顺序排错了）')
    try:
        return checked_tool_solid(solid, '放样')
    except FeatureError:
        _blame_profiles(identifiers, wires, ctx)    # 能说出是哪个轮廓的毛病就说出来
        raise


def _blame_profiles(identifiers, wires, ctx):
    """放样出来的实体无效时: 一个个轮廓围成面查一遍, 自交的 (样条的点顺序打了结…) 直接点名。"""
    from OCP.BRepCheck import BRepCheck_Analyzer
    names = {feature['id']: feature.get('name') or feature['id'] for feature in ctx.features}
    for number, (identifier, wire) in enumerate(zip(identifiers, wires), 1):
        maker = BRepBuilderAPI_MakeFace(wire, True)
        if not maker.IsDone() or not BRepCheck_Analyzer(maker.Face()).IsValid():
            raise FeatureError(f'放样失败：第 {number} 个轮廓（{names.get(identifier, identifier)}）自己和自己交叉了，'
                               '围不成一个面——检查样条的点是不是绕一圈的顺序、有没有前后颠倒的点')


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
    if kind in ('counterbore', 'countersink'):
        head, head_depth = _number(params, 'head_diameter', positive=True), _number(params, 'head_depth', positive=True)
    if size in table.HOLE_SIZES:
        diameter, bore, bore_depth, sink = table.HOLE_SIZES[size]
        head, head_depth = (bore, bore_depth) if kind == 'counterbore' else (sink, 0.0)
    if kind == 'tapped':
        if size not in table.TAP_DRILLS:
            raise FeatureError('螺纹底孔要选一个 M 规格')
        diameter = table.TAP_DRILLS[size]
    depth = _reach(body) if params.get('through', True) else _number(params, 'depth', positive=True)
    steps = [(diameter, diameter, depth)]
    if kind in ('counterbore', 'countersink'):
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


def screw(body, params, ctx):
    sketch = _sketch(ctx, params)
    size, head = params.get('size', 'M3'), params.get('head', 'cap')
    if size not in table.SCREW_SIZES or head not in table.SCREW_SIZES[size]:
        raise FeatureError('螺丝的规格或头型不认识')
    diameter = float(size[1:])
    head_diameter, head_height, socket, socket_depth = table.SCREW_SIZES[size][head]
    span = _number(params, 'length', positive=True)
    into = _along(sketch, params)               # 杆伸进去的方向
    tip = min(0.15 * diameter, span * 0.2)      # 杆端的小倒角
    if head == 'flat':
        cone = (head_diameter - diameter) / 2   # 90° 的锥: 高 = 半径差
        if span <= cone + tip:
            raise FeatureError('长度太短：沉头螺丝的长度要比头高长')
        head_steps, top = [(head_diameter, diameter, cone)], 0.0
        shank_from, shank = cone, span - cone
    else:
        low = head_height if head == 'cap' else head_height * 0.45      # 盘头: 下面一圈直的, 上面收成圆顶 (用锥近似)
        head_steps = [(head_diameter, head_diameter, low)]
        if head == 'button':
            head_steps.append((head_diameter, head_diameter * 0.62, head_height - low))
        top, shank_from, shank = head_height, 0.0, span
    x_dir, y_dir = sketch.frame[1], sketch.frame[2]
    made = []
    for spot in _spots(sketch):
        parts = _stack(spot + into * shank_from, into, [(diameter, diameter, shank - tip), (diameter, diameter - 2 * tip, tip)])
        parts += _stack(spot, into if head == 'flat' else -into, head_steps)
        solid = parts[0]
        for part in parts[1:]:
            solid = build._boolean(BRepAlgoAPI_Fuse, solid, part, '做螺丝')
        # 头顶上的内六角: 对边 socket 的六棱柱, 往头里挖 socket_depth
        centre, radius = spot - into * top, socket / math.sqrt(3)
        polygon = BRepBuilderAPI_MakePolygon()
        for corner in range(6):
            angle = math.radians(60 * corner)
            polygon.Add(_pnt(centre + (x_dir * math.cos(angle) + y_dir * math.sin(angle)) * radius - into * 0.01))
        polygon.Close()
        prism = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(polygon.Wire()).Face(), gp_Vec(*(into * (socket_depth + 0.01)))).Shape()
        made.append(build._unify(build._boolean(BRepAlgoAPI_Cut, solid, prism, '做螺丝')))
    return build._compound(made)


MAKERS = {'revolve': revolve, 'sweep': sweep, 'loft': loft, 'boundary': loft, 'hole': hole, 'hole_adv': hole_adv, 'stud': stud,
          'screw': screw, 'import_step': import_step}


DEFAULT_OP = {'hole': 'cut', 'hole_adv': 'cut', 'stud': 'add', 'screw': 'add'}
