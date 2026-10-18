# -*- coding: utf-8 -*-
"""重算结果的磁盘缓存: 一份特征表算到头的样子 (实体连同它的网格、各张表) 存成一个文件, 下次遇到一模一样的特征表直接读。

为什么要它: 特征多的零件打开就是从头重算一遍, 上百个布尔运算要一两分钟; 读回来只要几秒。
文件名就是特征表的钥匙 (build._step_keys 的最后一把) 加上内核自己的印记 — 内核的源码或 OpenCascade 的版本变了,
旧文件自然对不上号, 不会拿旧算法的结果冒充。只存 "算到头" 的那一个样子, 中间每一步的不存: 改前面的特征还是要从头算。

放在哪: 环境变量 GENFORM_CACHE 指的目录; 没设就是 %LOCALAPPDATA%/GenForm/cache。GENFORM_CACHE=off 关掉。
"""
from __future__ import annotations

import hashlib
import io
import os
import pickle

from OCP.BinTools import BinTools
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_WIRE
from OCP.TopoDS import TopoDS, TopoDS_Shape

KEEP_FILES = 40             # 目录里最多留这么多份 (最近用过的; 大零件除了最后一步还有几个中间检查点, 见 rebuild.keep)
_CASTS = {TopAbs_EDGE: TopoDS.Edge, TopAbs_WIRE: TopoDS.Wire, TopAbs_FACE: TopoDS.Face, TopAbs_SOLID: TopoDS.Solid}
_stamp = []


def folder():
    """缓存目录 (没有就建); 关掉了或建不了返回 None。"""
    chosen = os.environ.get('GENFORM_CACHE', '')
    if chosen.lower() in ('off', '0', 'no'):
        return None
    if not chosen:
        chosen = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), '.cache'), 'GenForm', 'cache')
    try:
        os.makedirs(chosen, exist_ok=True)
    except OSError:
        return None
    return chosen


# 算几何要用到的源码: 内核整个包 (含 model/、ops/ 子包) + 草图几何包 + 这几个文件。哪个变了旧缓存都作废
_SOURCES = ('.', '../sketchgeo', '../sketchgeom.py', '../planes.py', '../features.py', '../textpath.py')


def _source_files():
    here = os.path.dirname(os.path.abspath(__file__))
    for entry in _SOURCES:
        path = os.path.normpath(os.path.join(here, entry))
        if os.path.isfile(path):
            yield entry, path
            continue
        for root, folders, names in os.walk(path):
            folders[:] = sorted(name for name in folders if name != '__pycache__')
            for name in sorted(names):
                if name.endswith('.py'):
                    full = os.path.join(root, name)
                    yield os.path.relpath(full, here).replace(os.sep, '/'), full


def stamp():
    """内核的印记: OpenCascade 的版本 + 算几何的源文件的大小和修改时间。"""
    if not _stamp:
        import OCP
        digest = hashlib.sha1(str(getattr(OCP, '__version__', '')).encode())
        for name, path in _source_files():
            try:
                info = os.stat(path)
                digest.update(f'{name}:{info.st_size}:{info.st_mtime_ns}'.encode())
            except OSError:
                digest.update(name.encode())
        _stamp.append(digest.hexdigest()[:16])
    return _stamp[0]


def _path(key):
    where = folder()
    return os.path.join(where, f'{key[:40]}-{stamp()}.gfcache') if where else None


def _shape(data):
    shape = TopoDS_Shape()
    if data:
        BinTools.Read_s(shape, io.BytesIO(data))
        cast = _CASTS.get(shape.ShapeType())
        if cast is not None:            # 读回来的是不带具体类型的形状: 边、线、面这些要变回原来的类型, 后面的运算才认
            shape = cast(shape)
    return shape


class _Pickler(pickle.Pickler):
    def reducer_override(self, value):
        if isinstance(value, TopoDS_Shape):
            data = io.BytesIO()
            if not value.IsNull():
                BinTools.Write_s(value, data)       # 连网格一起写: 读回来不用再网格化
            return _shape, (data.getvalue(),)
        return NotImplemented


def save(key, body, tables, status):
    """存一份; 存不了 (盘满、没权限) 就算了。"""
    target = _path(key)
    if target is None:
        return
    try:
        with open(target + '.part', 'wb') as handle:
            _Pickler(handle, protocol=pickle.HIGHEST_PROTOCOL).dump({'body': body, 'tables': tables, 'status': status})
        os.replace(target + '.part', target)
        kept = sorted((os.path.join(os.path.dirname(target), name) for name in os.listdir(os.path.dirname(target))
                       if name.endswith('.gfcache')), key=os.path.getmtime, reverse=True)
        for old in kept[KEEP_FILES:]:
            os.remove(old)
    except Exception:
        try:
            os.remove(target + '.part')
        except OSError:
            pass


def has(key):
    """磁盘上有没有这一份 (只看文件在不在, 不读)。"""
    target = _path(key)
    return target is not None and os.path.isfile(target)


def load(key):
    """→ (实体, 各张表, 状态) 或 None (没有这一份, 或者读不出来)。"""
    target = _path(key)
    if target is None or not os.path.isfile(target):
        return None
    try:
        with open(target, 'rb') as handle:
            data = pickle.load(handle)
        os.utime(target)                # 刚用过: 清理时排在后面
        return data['body'], data['tables'], data['status']
    except Exception:
        return None
