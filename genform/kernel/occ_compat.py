"""OCP 7.x / 8 的差别收在这里: 集合类在 8 里搬到了 OCP.collections, TopoDS 的静态转换函数去掉了 _s 后缀。"""
from __future__ import annotations

from OCP.TopoDS import TopoDS

try:                                    # OCP 7.x
    from OCP.TopTools import TopTools_IndexedMapOfShape
except ImportError:                     # OCP 8: 集合类搬到了 OCP.collections, 静态转换函数去掉了 _s 后缀
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape
try:
    from OCP.TColgp import TColgp_Array1OfPnt as _PointArray
except ImportError:
    from OCP.collections import Array1_gp_Pnt as _PointArray
try:
    from OCP.TopTools import TopTools_ListOfShape as _ShapeList
    from OCP.TColgp import TColgp_HArray1OfPnt as _PointHandleArray
except ImportError:                     # OCP 8
    from OCP.collections import HArray1_gp_Pnt as _PointHandleArray
    from OCP.collections import List_TopoDS_Shape as _ShapeList

_as_edge = getattr(TopoDS, 'Edge_s', None) or TopoDS.Edge
_as_face = getattr(TopoDS, 'Face_s', None) or TopoDS.Face
_as_wire = getattr(TopoDS, 'Wire_s', None) or TopoDS.Wire
_as_solid = getattr(TopoDS, 'Solid_s', None) or TopoDS.Solid

__all__ = ['TopTools_IndexedMapOfShape', '_PointArray', '_ShapeList', '_PointHandleArray',
           '_as_edge', '_as_face', '_as_wire', '_as_solid']
