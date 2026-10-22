"""显示数据: 实体 → 三角网格、边线、草图线, 属性、查询、轮廓, 导出。"""
from __future__ import annotations

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.BRep import BRep_Tool
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
from OCP.TopLoc import TopLoc_Location
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from ..occ_compat import _as_edge, _as_face
from .base import ANGULAR_DEFLECTION, CURVE_SEGMENTS, FeatureError, LINEAR_DEFLECTION, display_deflection
from .faces import _face_signature, _surface_name
from .solids import bounds, edge_table, _indexed, _is_empty
from . import rebuild as rebuild_steps
from .rebuild import _rebuild, rebuild


_SHOWN = []         # [实体, 它的显示数据]: 上一次 build_model 给出去的 (实体没变就不用再网格化)


def tessellate(shape, owners=None, origins=None):
    """实体 → 显示用三角网格。每个面单独一段顶点 (面之间不共用), 所以可以按面着色和拾取。
    返回 verts (N,3) float32, normals (N,3) float32, tris (M,3) uint32, tri_face (M,) uint32, faces [信息]。
    owners: _rebuild 记下的 面序号 → 特征; 给了的话每张面的信息里带 'feature' (做出它的特征) 和 'edges' (围着它的边)。
    origins: 面序号 → 原件特征 (阵列、镜像复制出来的面), 有的话信息里带 'origin' (上色时阵列自己没颜色就跟原件)。"""
    BRepMesh_IncrementalMesh(shape, display_deflection(shape), False, ANGULAR_DEFLECTION, True)
    mapping = _indexed(shape, TopAbs_FACE)
    edge_map = _indexed(shape, TopAbs_EDGE)
    all_verts, all_normals, all_tris, all_owner, infos = [], [], [], [], []
    base = 0
    used = {}
    for index in range(1, mapping.Extent() + 1):
        face = _as_face(mapping.FindKey(index))
        # 这张面上一次算过 (加一个特征, 绝大多数面没变): 网格、面积、形心直接用记着的, 只有编号和归属要重新填
        key = (hash(face), face.Orientation())
        record = next((entry for entry in _FACE_MESHES.get(key, ()) if entry[0].IsEqual(face)), None)
        if record is None:
            record = (face,) + _face_mesh(face)
        used.setdefault(key, []).append(record)
        _, info, verts, normals, tris = record
        info = dict(info, id=index - 1)
        if owners is not None:
            info['feature'] = owners.get(index - 1, owners.get(info['signature']))
            if origins and origins.get(index - 1):
                info['origin'] = origins[index - 1]
            around = _indexed(face, TopAbs_EDGE)
            info['edges'] = sorted({edge_map.FindIndex(around.FindKey(number)) - 1 for number in range(1, around.Extent() + 1)
                                    if not BRep_Tool.Degenerated_s(_as_edge(around.FindKey(number)))})
        infos.append(info)
        if verts is None:
            continue
        all_verts.append(verts)
        all_normals.append(normals)
        all_tris.append(tris + base)
        all_owner.append(np.full(len(tris), index - 1, dtype=np.uint32))
        base += len(verts)
    _FACE_MESHES.clear()
    _FACE_MESHES.update(used)           # 只留现在这个实体上的面: 不会越攒越多
    if not all_verts:
        empty = np.zeros((0, 3), dtype=np.float32)
        return empty, empty, np.zeros((0, 3), dtype=np.uint32), np.zeros(0, dtype=np.uint32), infos
    return (np.concatenate(all_verts).astype(np.float32), np.concatenate(all_normals).astype(np.float32),
            np.concatenate(all_tris).astype(np.uint32), np.concatenate(all_owner), infos)


_FACE_MESHES = {}       # (面的散列, 朝向) → [(面, 信息, 顶点, 法线, 三角形)...]: 上一次网格化时每张面算出来的东西


def _face_mesh(face):
    """一张面自己的东西 (和它在实体里排第几无关) → (信息, 顶点, 法线, 三角形); 没有网格的面后三个是 None。"""
    location = TopLoc_Location()
    triangulation = BRep_Tool.Triangulation_s(face, location)
    surface = BRepAdaptor_Surface(face)
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    centre = props.CentreOfMass()
    info = {'id': -1, 'type': _surface_name(surface.GetType()),
            'center': (centre.X(), centre.Y(), centre.Z()), 'area': float(props.Mass()), 'normal': None}
    reverse = face.Orientation() == TopAbs_REVERSED
    if surface.GetType() == GeomAbs_Plane:
        direction = surface.Plane().Axis().Direction()
        sign = -1.0 if reverse else 1.0
        info['normal'] = (direction.X() * sign, direction.Y() * sign, direction.Z() * sign)
    elif surface.GetType() == GeomAbs_Cylinder:
        info['radius'] = float(surface.Cylinder().Radius())
    info['signature'] = _face_signature(face)
    info['box'] = bounds(face)
    if triangulation is None:
        return info, None, None, None
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
    return info, verts, normals, tris


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


def properties(shape, faces=None):
    """faces: 网格化时每张面的信息 — 给了的话包围盒和表面积用它们拼 (每张面的已经算过了, 整个实体再精确算一遍很慢)。"""
    from ..ops.solid_validation import mass
    volume, centre = mass(shape)            # 布尔校验刚算过的直接拿 (同一个实体不再积一遍分)
    if faces:
        low = tuple(min(face['box'][0][axis] for face in faces) for axis in range(3))
        high = tuple(max(face['box'][1][axis] for face in faces) for axis in range(3))
        surface = float(sum(face['area'] for face in faces))
    else:
        area = GProp_GProps()
        BRepGProp.SurfaceProperties_s(shape, area)
        (low, high), surface = bounds(shape), float(area.Mass())
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    explorer, bodies = TopExp_Explorer(shape, TopAbs_SOLID), 0
    while explorer.More():
        bodies += 1
        explorer.Next()
    return {'volume': float(volume), 'area': surface, 'bodies': bodies,      # bodies: 互不相连的实体有几块 (零件悬空就会多出来)
            'bbox_min': low, 'bbox_max': high,
            'size': tuple(h - l for l, h in zip(low, high)),
            'center_of_mass': tuple(float(value) for value in centre)}


def _drop_stale_meshes(body):
    """布尔运算做出来的实体上挂着之前的旧网格: 新面上是原来那张面的, 没变的面的边也被切分过, 和网格对不上了。
    OpenCascade 碰上这种要一张张检查、修补, 一个实体网格化能从零点几秒拖到二十几秒 (911 车身上加日行灯: 27 秒)。
    整个扔掉重新网格化反而快得多 (同一个车身 0.4 秒)。"""
    BRepTools.Clean_s(body)


def build_model(features, upto=None):
    """特征列表 → 界面和接口要的全部数据 (纯 Python / numpy, 可以跨进程传)。"""
    body, ctx, status = _rebuild(features, upto)
    model = {'status': status, 'sketches': sketch_lines(ctx), 'info': ctx.info, 'has_body': not _is_empty(body)}
    if model['has_body']:
        if _SHOWN and _SHOWN[0] is body:        # 实体和上一次是同一个 (只加了草图、基准面…): 网格和属性原样用
            model.update(_SHOWN[1])
            return model
        if not rebuild_steps.meshed(body):       # 磁盘缓存读回来的、刚存盘时网格化好的: 网格是干净的, 不要扔
            _drop_stale_meshes(body)
        verts, normals, tris, tri_face, faces = tessellate(body, ctx.owners, ctx.origins)
        props = properties(body, faces)
        for face in faces:                      # 只在内核里用的两项, 不往外送
            del face['signature'], face['box']
        segments, segment_edge, edges = edge_lines(body)
        from .. import measure
        shown = dict(verts=verts, normals=normals, tris=tris, tri_face=tri_face, faces=faces,
                     segments=segments, segment_edge=segment_edge, edges=edges, props=props, vertices=measure.vertices(body))
        _SHOWN[:] = [body, shown]
        model.update(shown)
    return model


def preview(features, upto):
    """试算: 这份特征表算出来的实体 → {'verts', 'normals', 'tris', 'low', 'high', 'errors': [哪个特征为什么没算成...]}。
    参数面板开着的时候拿它在视图里画预览 (features 是 "假如点了确定" 的那份, 文档本身没动)。"""
    body, _, status = rebuild(features, upto)
    names = {feature['id']: feature.get('name', feature['id']) for feature in features}
    errors = [f'{names.get(identifier, identifier)}：{text[7:]}' for identifier, text in status.items() if text.startswith('error: ')]
    if _is_empty(body):
        return {'verts': None, 'errors': errors}
    verts, normals, tris, _, _ = tessellate(body)
    low, high = bounds(body)
    return {'verts': verts, 'normals': normals, 'tris': tris, 'low': list(low), 'high': list(high), 'errors': errors}


def query(features, upto, mode, data):
    """不改文档的计算 (测量等): 和 outline 走同一条通道, mode 说要算什么。"""
    if mode == 'measure':
        from .. import measure
        return measure.measure(features, upto, data)
    if mode == 'preview':
        return preview(features, upto)
    if mode in ('static', 'drag'):
        from .. import simulate
        return getattr(simulate, mode)(features, upto, data)
    if mode in ('interference', 'sequence', 'meshes', 'contacts', 'measure_parts', 'mass_props', 'sweep'):
        from .. import assembly
        return getattr(assembly, mode)(features, upto, data)
    if mode == 'fasteners':
        from .. import fasteners
        return fasteners.fasteners(features, upto, data)
    if mode == 'stack':
        from .. import stack
        return stack.stack(features, upto, data)
    if mode == 'assembly_step':
        from .. import assembly
        return assembly.export(features, upto, data)
    if mode == 'drawing':
        from .. import drawing
        return drawing.views(features, upto, data)
    if mode == 'inspect':               # 绑定工艺、设计检查要的几何数据
        from .. import inspect
        return inspect.inspect(features, upto, data)
    raise FeatureError(f'不认识的计算 {mode!r}')


def outline(features, upto, mode, frame):
    if mode not in ('silhouette', 'section'):
        return query(features, upto, mode, frame)
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
