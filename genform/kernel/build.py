"""几何内核: 把特征列表 (纯数据) 重算成实体, 再给出显示用的三角网格、边线和拓扑信息。

只有这个模块碰 OpenCascade (OCP)。它不知道界面、文档、撤销 — 输入是特征列表, 输出是纯数据,
所以可以放在独立进程里跑 (见 worker.py), 也可以在测试里直接调。

特征 = {'id', 'type', 'name', 'params', 'suppressed'}; 目前的 type:
    sketch   草图: 基准面上的一组图形 (直线、圆弧、矩形、样条、文本… 见 sketchgeom.py); 封闭的和首尾相接成圈的
             是轮廓, 套在里面的轮廓算孔
    extrude  拉伸一个草图: 加料 (add) 或切除 (cut)
    fillet   圆角; chamfer 倒角 — 作用在选中的边上
单位: 毫米、度。

实现在 genform/kernel/model/ 包里 (base / sketches / solids / rebuild / display);
这里把所有名字转出去 (别处写 build.xxx)。重算的进度回调要设在 model.rebuild.on_step 上。
"""
from .model.base import AXES, LINEAR_DEFLECTION, ANGULAR_DEFLECTION, CURVE_SEGMENTS, SELECT_TOLERANCE, FeatureError
from .model.sketches import (
    plane_frame, Sketch, Context, _prim_edge, _loop_wire, _FONTS, _text_faces, build_sketch, _compound)
from .model.solids import (
    _boolean, _unify, _is_empty, EXTRUDE_ENDS, _prism, extrude_solid, combine, _indexed, _model_size, bounds,
    edge_table, resolve_edges, apply_blend)
from .model.rebuild import (
    rebuild, on_step, _STEPS, _SPARE, _usable, _KEPT, _MISSING, STORE_AFTER, _step_keys, _rebuild, keep, _restore)
from .model.display import (
    _SHOWN, tessellate, _FACE_MESHES, _face_mesh, _sample_edge, edge_lines, sketch_lines, properties, build_model,
    preview, query, outline, export)
from .model.faces import _surface_name, _faces_of, _face_signature

__all__ = [
    'AXES', 'LINEAR_DEFLECTION', 'ANGULAR_DEFLECTION', 'CURVE_SEGMENTS', 'SELECT_TOLERANCE', 'FeatureError',
    'plane_frame', 'Sketch', 'Context', '_prim_edge', '_loop_wire', '_FONTS', '_text_faces', 'build_sketch',
    '_compound', '_boolean', '_unify', '_is_empty', 'EXTRUDE_ENDS', '_prism', 'extrude_solid', 'combine', '_indexed',
    '_model_size', 'bounds', 'edge_table', 'resolve_edges', 'apply_blend', 'rebuild', 'on_step', '_SHOWN', '_STEPS',
    '_SPARE', '_usable', '_KEPT', '_MISSING', 'STORE_AFTER', '_step_keys', '_rebuild', 'keep', '_restore',
    '_surface_name', '_faces_of', '_face_signature', 'tessellate', '_FACE_MESHES', '_face_mesh', '_sample_edge',
    'edge_lines', 'sketch_lines', 'properties', 'build_model', 'preview', 'query', 'outline', 'export']
