"""草图的二维几何: 图形 → 基本曲线、采样、最近点、求交、剪裁、圆角、等距、镜向、找封闭轮廓、检查修复。
纯数学, 不碰界面库也不碰内核 — 草图编辑器 (sketcher.py) 和内核 (kernel/build.py) 共用同一套定义,
所以编辑时看到的和算出来的实体是同一条曲线。

图形 (草图特征 params['shapes'] 里的一项), 坐标是草图平面内的毫米, 角度是度 (逆时针):
    line     x1 y1 x2 y2
    arc      cx cy r a0 a1          从 a0 逆时针到 a1
    circle   cx cy r
    rect     cx cy w h
    polygon  points [[x, y]...]     封闭折线
    ngon     cx cy r sides angle    正多边形: r 是外接圆半径, angle 是第一个顶点的方向
    slot     x1 y1 x2 y2 w          直槽口: 两个圆心和槽宽
    ellipse  cx cy rx ry angle
    arcslot  cx cy r a0 a1 w        圆弧槽口: 中心线是一段圆弧 (从 a0 逆时针到 a1), w 是槽宽
    spline   points closed [style]  过这些点的样条; style=True 是样式样条: 点是控制点, 曲线只过首尾两个
    equation mode fx fy t0 t1 ox oy 方程式驱动的曲线: mode='explicit' 时 y = fy(x), x 从 t0 到 t1;
                                    mode='parametric' 时 x = fx(t), y = fy(t); 整体再平移 (ox, oy)
    point    x y                    只当捕捉和参考用, 不参与围面
    text     x y text height angle font [path flip]   path 是一条曲线图形: 文字沿着它排

任何图形都可以带 construction=True: 构造线 (中心线), 只作参考 — 不围面、不拉伸, 可以当镜向轴和旋转轴。

基本曲线 (prims 的结果, 角度是弧度):
    ('line', a, b)  ('arc', c, r, a0, a1)  ('circle', c, r)  ('ellipse', c, rx, ry, rot)
    ('bezier', p0, p1, …, pn)  ('point', p)        贝塞尔曲线的控制点个数不限 (三次的是 4 个)

实现在 genform/sketchgeo/ 包里 (base / transform / editing / loops / curves / relations /
fitting); 这里把所有名字转出去 (别处写 geom.xxx)。
"""
from .sketchgeo.base import (
    TAU, JOIN, GAP, TINY, CLOSED, NAMES, STYLE_POINTS, EQUATION_STEPS, DEFAULT_FONT, dist, _unit, _polar, _angle,
    _in_sweep, num, _points, is_closed, vertices, _spline_beziers, prims, sample, polylines, length, prim_ends, ends,
    anchor, key_points, signed_area, _oriented, _MATH, evaluate, equation_points)
from .sketchgeo.transform import (
    _nearest_on_segment, nearest_on_prim, nearest, hit, contains, _ring, explode, _mapped, moved, rotated, mirrored)
from .sketchgeo.editing import (
    _line_line, _line_circle, _circle_circle, _on_round, _simple, intersections, _along, _piece, trim, corner_near,
    fillet, signed_distance, offset)
from .sketchgeo.loops import _nodes, loops, loop_ring, chain_of, _open_tips, _same, diagnose, _set_tip, repair
from .sketchgeo.curves import circle3, arc3, extend
from .sketchgeo.relations import RELATIONS, _ROUND, _CENTRED, relations_for, _turned_line, relate, _nearest_on_line
from .sketchgeo.fitting import fit_line, fit_lines, project_edges, text_layout

__all__ = [
    'TAU', 'JOIN', 'GAP', 'TINY', 'CLOSED', 'NAMES', 'STYLE_POINTS', 'EQUATION_STEPS', 'DEFAULT_FONT', 'dist', '_unit',
    '_polar', '_angle', '_in_sweep', 'num', '_points', 'is_closed', 'vertices', '_spline_beziers', 'prims', 'sample',
    'polylines', 'length', 'prim_ends', 'ends', 'anchor', 'key_points', '_nearest_on_segment', 'nearest_on_prim',
    'nearest', 'hit', 'contains', 'signed_area', '_oriented', '_ring', 'explode', '_mapped', 'moved', 'rotated',
    'mirrored', '_line_line', '_line_circle', '_circle_circle', '_on_round', '_simple', 'intersections', '_along',
    '_piece', 'trim', 'corner_near', 'fillet', 'signed_distance', 'offset', '_nodes', 'loops', 'loop_ring', 'chain_of',
    '_open_tips', '_same', 'diagnose', '_set_tip', 'repair', '_MATH', 'evaluate', 'equation_points', 'circle3', 'arc3',
    'extend', 'RELATIONS', '_ROUND', '_CENTRED', 'relations_for', '_turned_line', 'relate', '_nearest_on_line',
    'fit_line', 'fit_lines', 'project_edges', 'text_layout']
