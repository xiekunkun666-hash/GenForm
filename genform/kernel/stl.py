"""STL 三角网格读取; 不创建 BRep 面或把网格当作精确实体。长度沿用装配体的 mm。"""
from __future__ import annotations

import io
import math
import os
import re
import struct

import numpy as np
from OCP.RWStl import RWStl

from .model.base import FeatureError

_NUMBER = rb'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
_VECTOR = _NUMBER + rb'\s+' + _NUMBER + rb'\s+' + _NUMBER
_FACET = re.compile(rb'facet\s+normal\s+' + _VECTOR + rb'\s+outer\s+loop\s+'
                    + rb'\s+'.join([rb'vertex\s+(' + _VECTOR + rb')'] * 3) + rb'\s+endloop\s+endfacet\b')
_BOUNDARY = re.compile(rb'(endsolid|solid)\b[^\r\n]*')
_DISPLAY_LIMIT = float(np.finfo(np.float32).max)


def _ascii(data):
    data = data.removeprefix(b'\xef\xbb\xbf')
    position, opened, count = 0, False, 0
    stream = io.BytesIO()
    stream.write(b'solid mesh\n')
    while position < len(data):
        if data[position:position + 1].isspace():
            position += 1
            continue
        boundary = _BOUNDARY.match(data, position)
        if boundary is not None:
            opening = boundary[1] == b'solid'
            if opening == opened:
                raise ValueError('solid / endsolid 不配对')
            opened, position = opening, boundary.end()
            continue
        facet = _FACET.match(data, position) if opened else None
        if facet is None:
            raise ValueError('ASCII 三角面格式错误或文件不完整')
        coordinates = [float(value) for vertex in facet.groups() for value in vertex.split()]
        if not all(math.isfinite(value) and abs(value) <= _DISPLAY_LIMIT for value in coordinates):
            raise ValueError('顶点坐标不是有限数或超出显示范围')
        stream.write(facet[0])
        stream.write(b'\n')
        count += 1
        position = facet.end()
    if opened:
        raise ValueError('缺少 endsolid，文件不完整')
    stream.write(b'endsolid mesh\n')
    stream.seek(0)
    return stream, count


def read_stl(path):
    """ASCII / binary STL → 顶点、平面法向和三角形索引; 空、截断或无效几何报 FeatureError。"""
    full = os.path.abspath(str(path))
    try:
        with open(full, 'rb') as handle:
            data = handle.read()
    except OSError as error:
        raise FeatureError(f'打不开 STL 文件 {path}：{error.strerror or error}') from None
    try:
        if not data or not data.strip():
            raise ValueError('文件为空，没有三角网格')
        count = struct.unpack_from('<I', data, 80)[0] if len(data) >= 84 else None
        if count is not None and len(data) == 84 + 50 * count:
            facets = np.frombuffer(data, dtype=np.dtype([('normal', '<f4', (3,)), ('verts', '<f4', (3, 3)), ('attribute', '<u2')]),
                                   count=count, offset=84)
            if not np.isfinite(facets['verts']).all():
                raise ValueError('顶点坐标不是有限数')
            stream = io.BytesIO(data)
            reader = RWStl.ReadBinaryStream_s
        elif data.removeprefix(b'\xef\xbb\xbf').lstrip().startswith(b'solid'):
            stream, count = _ascii(data)
            reader = RWStl.ReadAsciiStream_s
        else:
            raise ValueError('二进制三角面数量与文件长度不符，或文件不是有效 STL')
        if not count:
            raise ValueError('没有三角网格')
        triangulation = reader(stream, 0.0)
        if triangulation is None or triangulation.NbTriangles() != count:
            raise ValueError('三角网格损坏或含退化三角面')
        verts = np.empty((triangulation.NbNodes(), 3), dtype=np.float64)
        for index in range(len(verts)):
            point = triangulation.Node(index + 1)
            verts[index] = point.X(), point.Y(), point.Z()
        tris = np.empty((count, 3), dtype=np.uint32)
        for index in range(count):
            tris[index] = triangulation.Triangle(index + 1).Get()
        tris -= 1
        if not np.isfinite(verts).all() or np.any(np.abs(verts) > _DISPLAY_LIMIT):
            raise ValueError('顶点坐标不是有限数或超出显示范围')
        corners = verts[tris]
        normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
        lengths = np.linalg.norm(normals, axis=1)
        if not np.isfinite(lengths).all() or np.any(lengths == 0):
            raise ValueError('含退化三角面或无效坐标')
        normals /= lengths[:, None]
        verts = corners.reshape(-1, 3)
        normals = np.repeat(normals, 3, axis=0)
        tris = np.arange(len(verts), dtype=np.uint32).reshape(-1, 3)
        return {'verts': verts, 'normals': normals, 'tris': tris}
    except Exception as error:
        raise FeatureError(f'读不了 STL 文件 {path}：{error}') from None
