"""features.py (特征表) 里登记的每种特征怎么算。和 build.py 一样只在内核这边用, 输入输出都是 OpenCascade 的形体。

四类:
    MAKERS     造一个 "工具体", 再按 op 和现有实体合并 / 切除 / 求交 (旋转、扫描、放样、孔…) — 工具体留着, 阵列和镜像复制的就是它
    MODIFIERS  直接改现有实体 (筋、拔模、抽壳、包裹、分割线、螺纹线、各种阵列)
    CURVES     得到一条空间曲线, 可以作扫描路径
    REFERENCES 参考几何体: 只产生显示用的线, 不改实体

实现在 genform/kernel/ops/ 包里 (helpers / tools / modify / patterns / curves / references);
这里把所有名字转出去 (别处写 more.xxx)。
"""
from .ops.helpers import (
    _pnt, _dir, _vec, _xyz, _number, _shape_list, _explore, _moved, _translation, _volume, _centroid, _reach,
    _need_body, _sketch, _profile, _wire, _path, _axis, _frame, _spots, _faces, _spline, _run)
from .ops.tools import revolve, sweep, loft, _stack, _along, hole, hole_adv, stud, screw, MAKERS, DEFAULT_OP
from .ops.modify import thread, rib, draft, shell, wrap, split
from .ops.patterns import (
    _seeds, _replicate, _count, pattern_linear, pattern_circular, mirror, pattern_curve, _to_spots, pattern_sketch,
    pattern_table, pattern_fill, pattern_variable, MODIFIERS)
from .ops.curves import (
    curve_helix, sketch3d, curve_surface, curve_xyz, curve_points, curve_project, curve_composite, CURVES)
from .ops.references import _segments, _cross, reference, REFERENCES

__all__ = [
    '_pnt', '_dir', '_vec', '_xyz', '_number', '_shape_list', '_explore', '_moved', '_translation', '_volume',
    '_centroid', '_reach', '_need_body', '_sketch', '_profile', '_wire', '_path', '_axis', '_frame', '_spots',
    '_faces', '_spline', '_run', 'revolve', 'sweep', 'loft', '_stack', '_along', 'hole', 'hole_adv', 'stud', 'screw',
    'MAKERS', 'DEFAULT_OP', 'thread', 'rib', 'draft', 'shell', 'wrap', 'split', '_seeds', '_replicate', '_count',
    'pattern_linear', 'pattern_circular', 'mirror', 'pattern_curve', '_to_spots', 'pattern_sketch', 'pattern_table',
    'pattern_fill', 'pattern_variable', 'MODIFIERS', 'curve_helix', 'sketch3d', 'curve_surface', 'curve_xyz',
    'curve_points', 'curve_project', 'curve_composite', 'CURVES', '_segments', '_cross', 'reference', 'REFERENCES']
