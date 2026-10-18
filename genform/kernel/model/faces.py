"""认面: 曲面种类、实体的面、面的签名 (改了模型以后靠它认出还是不是那张面)。"""
from __future__ import annotations

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus
from OCP.TopAbs import TopAbs_FACE

from ..occ_compat import _as_face
from .solids import bounds, _indexed


# ---------------------------------------------------------------------------
# 显示数据
# ---------------------------------------------------------------------------
def _surface_name(kind):
    return {GeomAbs_Plane: 'plane', GeomAbs_Cylinder: 'cylinder', GeomAbs_Cone: 'cone',
            GeomAbs_Sphere: 'sphere', GeomAbs_Torus: 'torus'}.get(kind, 'surface')


def _faces_of(shape):
    mapping = _indexed(shape, TopAbs_FACE)
    return [_as_face(mapping.FindKey(index)) for index in range(1, mapping.Extent() + 1)]


def _inherit_owners(before, body, owners, identifier, cache):
    """面序号 → 特征。未变的面按 identity 继承, 裁过的面只匹配同曲面上实际接触的旧面。"""
    current = _faces_of(body)
    if before is None or before.IsNull():
        return dict.fromkeys(range(len(current)), identifier)
    previous = _faces_of(before)
    identities = {}
    for index, face in enumerate(previous):
        identities.setdefault(hash(face), []).append((face, owners.get(index)))
    inherited, pending = {}, []
    for index, face in enumerate(current):
        owner = next((owner for other, owner in identities.get(hash(face), ()) if face.IsSame(other)), None)
        if owner is not None:
            inherited[index] = owner
        else:
            record = _face_record(face, cache)
            pending.append((index, record, _record_signature(record)))
    if not pending:
        return inherited
    needed = {signature for _, _, signature in pending}
    candidates = {}
    for index, face in enumerate(previous):
        owner = owners.get(index)
        if owner is None:
            continue
        record = _face_record(face, cache)
        signature = _record_signature(record)
        if signature in needed:
            candidates.setdefault(signature, []).append((record, owner))
    for index, record, signature in pending:
        inherited[index] = next((owner for other, owner in candidates.get(signature, ())
                                 if _faces_touch(record, other)), identifier)
    return inherited


def _copy_origins(body, paired, fresh, copies, origins, cache):
    """阵列 / 镜像刚做出来的面 (paired 里值还是 fresh 的): 认出它是哪一份复制体上的 (原样留下的同一张面, 或者
    同一张曲面上碰得着的), 记上那一份的原件特征 → paired[序号] = (阵列, 原件)。轮子阵列到后面, 轮胎还是轮胎的颜色。"""
    current = _faces_of(body)
    waiting = [index for index, value in paired.items() if value == fresh]
    if not waiting:
        return
    candidates = {}
    for (solid, _), origin in zip(copies, origins):
        if origin is None:
            continue
        for face in _faces_of(solid):
            record = _face_record(face, cache)
            candidates.setdefault(_record_signature(record), []).append((record, origin))
    for index in waiting:
        face = current[index]
        record = _face_record(face, cache)
        found = next((origin for other, origin in candidates.get(_record_signature(record), ())
                      if face.IsSame(other['face']) or _faces_touch(record, other)), None)
        if found:
            paired[index] = (fresh[0], found)


def _face_record(face, cache):
    bucket = cache.setdefault(hash(face), [])
    record = next((record for record in bucket if face.IsSame(record['face'])), None)
    if record is None:
        record = {'face': face}
        bucket.append(record)
    return record


def _record_signature(record):
    if 'signature' not in record:
        record['signature'] = _face_signature(record['face'])
    return record['signature']


def _faces_touch(first, second):
    """两张面 (同一张底层曲面上的, 指纹相同才会来比) 碰不碰得着。先比包围盒; 再看一张面的顶点、边中点有没有落在
    另一张面里或边上 (反过来也看) — 同一张曲面上这就够了, 每个点一毫秒左右; 都没落进去时才精确求两张面的距离。
    (原来直接求距离: 911 车身上两张大样条面之间一次要 3 秒, 一个特征十几次, 光认面就花了将近 50 秒。)"""
    for record in (first, second):
        if 'box' not in record:
            record['box'] = bounds(record['face'])
    tolerance = 1e-6
    low, high = first['box']
    other_low, other_high = second['box']
    if any(high[axis] < other_low[axis] - tolerance or other_high[axis] < low[axis] - tolerance
           for axis in range(3)):
        return False
    if _lands_on(first, second) or _lands_on(second, first):
        return True
    distance = BRepExtrema_DistShapeShape(first['face'], second['face'])
    return distance.IsDone() and distance.Value() <= tolerance


def _probes(record):
    """一张面边界上用来试探的点: 每个顶点 + 每条边的中点 (记在 record 里, 一轮重算里反复用)。"""
    if 'probes' not in record:
        from OCP.BRep import BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_VERTEX
        from ..occ_compat import _as_edge
        from OCP.TopoDS import TopoDS
        points = []
        for vertex in _indexed_list(record['face'], TopAbs_VERTEX):
            points.append(BRep_Tool.Pnt_s(TopoDS.Vertex(vertex)))
        for edge in _indexed_list(record['face'], TopAbs_EDGE):
            try:
                curve = BRepAdaptor_Curve(_as_edge(edge))
                points.append(curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2))
            except Exception:
                continue
        record['probes'] = points
    return record['probes']


def _lands_on(source, target):
    """source 的试探点里有没有落在 target 这张面里或它的边上的。"""
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    for point in _probes(source):
        try:
            state = BRepClass_FaceClassifier(target['face'], point, 1e-6).State()
        except Exception:
            continue
        if state in (TopAbs_IN, TopAbs_ON):
            return True
    return False


def _indexed_list(shape, kind):
    mapping = _indexed(shape, kind)
    return [mapping.FindKey(index) for index in range(1, mapping.Extent() + 1)]


def _face_signature(face):
    """曲面的匹配键 (不是面的唯一标识): 平面 = 法向 + 到原点的距离; 圆柱 = 轴线 + 半径; 别的曲面 = 底层曲面在
    固定参数上的几个点。裁剪不改变这个键; 归属还要匹配旧面的 identity 或空间接触, 避免分离的共面 / 同轴零件串色。
    不用面积 + 形心: 车身样条面被轮拱裁短后, 仍然需要匹配原 loft 的曲面。"""
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
    points = _surface_samples(face)
    if points is not None:
        return ('surface', int(kind), points)
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    centre = props.CentreOfMass()
    return ('surface', int(kind), round(float(props.Mass()), 3),
            tuple(round(value, 3) + 0.0 for value in (centre.X(), centre.Y(), centre.Z())))


_FAR = 1e50                         # 参数范围超过这个就当是无限的 (拉伸面、圆锥的母线方向…)


def _surface_samples(face):
    """面底下那张 (没裁过的) 曲面在固定参数上的 3×3 个点: 参数有界就在范围里均匀取, 无界就取 0、10、100。
    同一张曲面不管被裁成什么样都一样; 挪过、镜像过的就不一样。取不到 (没有曲面) 返回 None。"""
    from OCP.BRep import BRep_Tool
    try:
        surface = BRep_Tool.Surface_s(face)
        u1, u2, v1, v2 = surface.Bounds()
    except Exception:
        return None

    def spread(low, high):
        if abs(low) < _FAR and abs(high) < _FAR:
            return [low + (high - low) * share for share in (0.1, 0.5, 0.9)]
        return [0.0, 10.0, 100.0]
    points = []
    for u in spread(u1, u2):
        for v in spread(v1, v2):
            point = surface.Value(u, v)
            points.append(tuple(round(value, 3) + 0.0 for value in (point.X(), point.Y(), point.Z())))
    return tuple(points)
