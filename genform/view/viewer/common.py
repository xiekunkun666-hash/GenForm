"""三维视图共用的常量 (手势、缓动、拾取范围) 和把模型数据变成显卡数组的小工具。"""
from __future__ import annotations

import numpy as np


CLICK_SLOP = 4              # 按下到松开移动不超过这么多像素算单击


GESTURE_START = 8           # 右键按住拖出这么多像素, 手势轮出现


GESTURE_AIM = 22            # 离中心超过这么多像素才算指向了某一格 (中心附近不选任何东西)


GESTURE_FIRE = 62           # 划到离中心这么远 (图标那一圈) 就执行, 不用松手


GESTURE_SECTORS = 8         # 0=右, 逆时针每 45 度一格: 1=右上, 2=上, 3=左上, 4=左, 5=左下, 6=下, 7=右下


PLANE_MIN_HALF = 45.0       # 基准面至少画这么大 (半边长, mm)


VIEW_GLIDE = 0.26           # 切换视角 (点视图按钮、进出草图) 用这么多秒平滑转过去, 不是瞬间跳


HISTORY_LIMIT = 30          # "上一个视图" 最多记这么多步


ORIGIN_PIXELS = 58.0        # 原点坐标系的一根轴在屏幕上画这么长 (像素): 拉近拉远都一样大


SKETCH_REACH = 6.0          # 光标离草图线的屏幕距离在这么多像素内算指着它


EMPTY3 = np.zeros((0, 3), dtype=np.float32)


def _geometry(model, hidden_sketch=None, hidden=(), body=True, colors=None, opacity=None):
    """模型数据 → 要上传到显卡的数组, 以及 "顶点属于哪个面/边/草图" 的对照表。body=False: 实体不画 (被隐藏了)。
    colors: 单独上色的特征 {特征 id: (r, g, b)} → 'tints' 每个顶点的颜色; 没上色的是 -1 (着色器换成零件的颜色)。
    opacity: 半透明的特征 {特征 id: 0~1} (玻璃…): 它的三角面排到 'tris' 的最后, 'glass' = [(从第几个三角面, 几个, 不透明度)...],
    不透明的画完再画它们 (隔着玻璃看得见里面)。阵列 / 镜像自己没设的跟原件, 和颜色一样。"""
    if model.get('has_body') and body:
        verts, normals, tris = model['verts'], model['normals'], model['tris']
        vertex_face = np.full(len(verts), -1, dtype=np.int64)     # -1: 没有三角面用它 (隐藏了的实体块上的)
        vertex_face[tris.ravel()] = np.repeat(model['tri_face'].astype(np.int64), 3)
        faces = model.get('faces') or ()
        face_tint = np.full((len(faces) + 1, 3), -1.0, dtype=np.float32)       # 最后一行给 vertex_face == -1 的
        for face in faces:          # 阵列 / 镜像自己没上色的: 复制出来的面跟着原件的颜色 (见 kernel faces._copy_origins)
            colour = colors and (colors.get(face.get('feature')) or colors.get(face.get('origin')))
            if colour:
                face_tint[face['id']] = colour
        tints = np.ascontiguousarray(face_tint[vertex_face])
        tris, glass = _glass_order(model, faces, opacity)
        edge_points = model['segments'].reshape(-1, 3)
        point_edge = np.repeat(model['segment_edge'].astype(np.int64), 2)
    else:
        verts = normals = edge_points = tints = EMPTY3
        tris, glass = np.zeros((0, 3), dtype=np.uint32), []
        vertex_face = point_edge = np.zeros(0, dtype=np.int64)
    sketch_parts, sketch_owner = [], []
    for identifier, lines in (model.get('sketches') or {}).items():
        if identifier == hidden_sketch or identifier in hidden:     # 正在编辑的草图由编辑器自己画; 用户关掉显示的不画
            continue
        points = np.asarray(lines, dtype=np.float32).reshape(-1, 3)
        sketch_parts.append(points)
        sketch_owner += [identifier] * len(points)
    sketch_points = np.concatenate(sketch_parts) if sketch_parts else EMPTY3
    return ({'verts': verts, 'normals': normals, 'tris': tris, 'edge_points': edge_points, 'tints': tints,
             'sketch_points': sketch_points, 'tinted': bool(colors), 'glass': glass}, vertex_face, point_edge, sketch_owner)


def _glass_order(model, faces, opacity):
    """→ (重排过的三角面, [(从第几个, 几个, 不透明度)...])。没有半透明的: 原样, []。"""
    tris = model['tris']
    if not opacity or not len(tris):
        return tris, []
    face_alpha = np.ones(len(faces) + 1, dtype=np.float32)
    for face in faces:
        value = opacity.get(face.get('feature'), opacity.get(face.get('origin')))
        if value is not None:
            face_alpha[face['id']] = min(1.0, max(0.05, float(value)))
    alpha = face_alpha[model['tri_face'].astype(np.int64)]
    if (alpha >= 0.999).all():
        return tris, []
    order = np.argsort(np.where(alpha >= 0.999, 2.0, alpha), kind='stable')[::-1]      # 不透明的 (记成 2) 在前
    alpha = alpha[order]
    glass, start = [], int((alpha >= 0.999).sum())
    while start < len(alpha):
        end = start + int((alpha[start:] == alpha[start]).sum())
        glass.append((start, end - start, float(alpha[start])))
        start = end
    return np.ascontiguousarray(tris[order]), glass


def _without_faces(model, faces):
    """去掉这些面 (被隐藏的实体块) 的模型: 三角面、只围着它们的边都拿掉, 面和边的编号不变。
    画图、悬停、点选、框选都用它, 被隐藏的东西既看不见也点不着。"""
    if not faces or not model.get('has_body'):
        return model
    faces = np.asarray(sorted(faces), dtype=np.int64)
    kept = ~np.isin(model['tri_face'], faces)
    around = model.get('faces') or ()
    hidden = set(faces.tolist())
    gone = set()
    for face in around:
        if face['id'] in hidden:
            gone.update(face.get('edges', ()))
    for face in around:
        if face['id'] not in hidden:
            gone.difference_update(face.get('edges', ()))
    shown = dict(model, tris=np.ascontiguousarray(model['tris'][kept]), tri_face=np.ascontiguousarray(model['tri_face'][kept]))
    if gone:
        lines = ~np.isin(model['segment_edge'], np.asarray(sorted(gone), dtype=np.int64))
        shown['segments'] = np.ascontiguousarray(model['segments'][lines])
        shown['segment_edge'] = np.ascontiguousarray(model['segment_edge'][lines])
    return shown
