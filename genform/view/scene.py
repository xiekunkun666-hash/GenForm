# -*- coding: utf-8 -*-
"""三维视图的绘制 (只在渲染线程里用): 背景、地面网格和坐标轴、实体的面、边线、草图线。

面和边各带一个逐顶点的 "状态" 值 (0 普通 / 1 光标悬停 / 2 选中): 选择变了只重传这一小段数据,
不用重传几何。
"""
from __future__ import annotations

import ctypes
import math

import numpy as np
from OpenGL.GL import *

from .shader_program import ShaderProgram
from .shaders import _BACK_VS, _BACK_FS, _FLAT_VS, _FLAT_FS, _MESH_VS, _MESH_FS, _LINE_VS, _LINE_GS, _LINE_FS

EMPTY_TINTS = np.zeros((0, 3), dtype=np.float32)      # 没有实体时的逐顶点颜色
GRID_HALF = 200.0           # 草图平面上的网格从原点往每个方向画多远 (mm)
GRID_MINOR, GRID_MAJOR = 10.0, 50.0

# 配色: (深色主题, 浅色主题)
PALETTE = {
    'back_top': ((0.215, 0.218, 0.228), (0.93, 0.955, 0.985)),
    'back_bottom': ((0.105, 0.107, 0.115), (0.78, 0.835, 0.905)),
    'grid_minor': ((1.0, 1.0, 1.0, 0.06), (0.05, 0.15, 0.35, 0.07)),
    'grid_major': ((1.0, 1.0, 1.0, 0.14), (0.05, 0.15, 0.35, 0.15)),
    'face': ((0.84, 0.84, 0.85), (0.76, 0.81, 0.88)),
    'face_hover': ((0.74, 0.85, 1.00), (0.66, 0.80, 0.94)),
    'face_chosen': ((0.45, 0.69, 1.00), (0.20, 0.50, 0.96)),
    'edge': ((0.02, 0.02, 0.03), (0.16, 0.19, 0.23)),
    'edge_wire': ((1.0, 1.0, 1.0), (0.10, 0.13, 0.18)),      # 不上色的显示样式里的边线: 要和背景分得开
    'edge_hover': ((0.70, 0.84, 1.00), (0.10, 0.50, 0.95)),
    'edge_chosen': ((0.40, 0.67, 1.00), (0.95, 0.50, 0.05)),
    'sketch': ((0.55, 0.75, 1.00), (0.14, 0.41, 0.95)),
    'sketch_chosen': ((1.0, 1.0, 1.0), (0.95, 0.50, 0.05)),
    # 草图编辑时: 已画好的轮廓 / 光标悬停 / 选中 / 正在画的
    # 草图: 没标尺寸的深蓝 (不发黑), 选中的浅蓝, 悬停橙色, 标过尺寸的和尺寸线是黑的 (深色界面上用白, 黑的看不见)
    'draw': ((0.26, 0.48, 0.96), (0.09, 0.26, 0.66)),
    'draw_hover': ((1.00, 0.66, 0.26), (0.96, 0.50, 0.06)),
    'draw_chosen': ((0.62, 0.86, 1.00), (0.36, 0.68, 1.00)),
    'draw_draft': ((0.55, 0.77, 1.00), (0.05, 0.62, 0.35)),
    'draw_defined': ((0.94, 0.95, 0.97), (0.06, 0.07, 0.09)),
    'plane': ((0.55, 0.75, 1.00), (0.14, 0.41, 0.95)),
}


# 布景: 名称 → (上面的颜色, 下面的颜色, 是不是聚光, 算不算深色 — 决定线和字用哪一套颜色)。'auto' = 跟着界面主题
SCENES = {
    'fade': ((0.56, 0.66, 0.80), (0.94, 0.96, 0.98), False, False),        # 三点渐褪
    'white': ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0), False, False),              # 单白色
    'gray': ((0.66, 0.67, 0.69), (0.40, 0.41, 0.43), False, True),          # 带顶光源的灰色
    'spot': ((0.42, 0.42, 0.45), (0.05, 0.05, 0.06), True, True),           # 柔光聚光灯
}
STYLES = ('shaded_edges', 'shaded', 'hlr', 'hlv', 'wire')


def color_of(name, dark):
    return PALETTE[name][0 if dark else 1]


def _grid_vertices(dark):
    index = 0 if dark else 1
    minor, major = PALETTE['grid_minor'][index], PALETTE['grid_major'][index]
    rows = []
    steps = int(GRID_HALF / GRID_MINOR)
    for step in range(-steps, steps + 1):
        value = step * GRID_MINOR
        if step == 0:
            continue                        # 原点的两条线由坐标轴代替
        color = major if step % int(GRID_MAJOR / GRID_MINOR) == 0 else minor
        rows += [(value, -GRID_HALF, 0, *color), (value, GRID_HALF, 0, *color),
                 (-GRID_HALF, value, 0, *color), (GRID_HALF, value, 0, *color)]
    rows += [(-GRID_HALF, 0, 0, *major), (0, 0, 0, *major), (0, -GRID_HALF, 0, *major), (0, 0, 0, *major)]
    return np.array(rows, dtype=np.float32)


AXIS_TINTS = (((0.94, 0.46, 0.42), (0.85, 0.26, 0.23)),        # X 红 / Y 绿 / Z 蓝: (深色主题, 浅色主题), 和左下角的坐标系一个颜色
              ((0.42, 0.80, 0.58), (0.18, 0.62, 0.38)),
              ((0.35, 0.64, 1.00), (0.14, 0.41, 0.95)))
AXIS_SHAFT = 0.76           # 原点坐标系: 轴长算 1, 杆画到这里, 再往外是箭头
AXIS_HEAD = 0.085           # 箭头底面的半径


def _axis_lines():
    """原点的三根轴杆: 端点 (6,3) 和逐点的状态 (0 / 1 / 2 = X / Y / Z, 画的时候当成三种颜色)。"""
    points, states = [], []
    for axis in range(3):
        tip = [0.0, 0.0, 0.0]
        tip[axis] = AXIS_SHAFT
        points += [(0.0, 0.0, 0.0), tuple(tip)]
        states += [float(axis), float(axis)]
    return np.array(points, dtype=np.float32), np.array(states, dtype=np.float32)


def _axis_solids(dark):
    """三个箭头 (圆锥) 和原点的小球: 三角形顶点, 每行 xyz + rgba。没有光照, 靠每一瓣深浅不同显出立体感。"""
    index = 0 if dark else 1
    rows = []
    slices = 18
    for axis in range(3):
        tint = np.array(AXIS_TINTS[axis][index])
        u, v = (axis + 1) % 3, (axis + 2) % 3

        def at(along, radius, angle):
            point = [0.0, 0.0, 0.0]
            point[axis], point[u], point[v] = along, radius * math.cos(angle), radius * math.sin(angle)
            return point

        for step in range(slices):
            a0, a1 = 2 * math.pi * step / slices, 2 * math.pi * (step + 1) / slices
            shade = 0.72 + 0.28 * (0.5 + 0.5 * math.cos((a0 + a1) / 2 - 0.9))
            side, cap = (*(tint * shade), 1.0), (*(tint * 0.58), 1.0)
            rows += [(*at(1.0, 0.0, 0.0), *side), (*at(AXIS_SHAFT, AXIS_HEAD, a0), *side), (*at(AXIS_SHAFT, AXIS_HEAD, a1), *side)]
            rows += [(*at(AXIS_SHAFT, 0.0, 0.0), *cap), (*at(AXIS_SHAFT, AXIS_HEAD, a1), *cap), (*at(AXIS_SHAFT, AXIS_HEAD, a0), *cap)]
    ball, bands = 0.062, 8
    core = np.array((0.93, 0.95, 0.98) if dark else (0.30, 0.34, 0.40))

    def on_ball(lat, lon):
        return (ball * math.cos(lat) * math.cos(lon), ball * math.cos(lat) * math.sin(lon), ball * math.sin(lat))

    for band in range(bands):
        lat0, lat1 = -math.pi / 2 + math.pi * band / bands, -math.pi / 2 + math.pi * (band + 1) / bands
        for step in range(slices):
            lon0, lon1 = 2 * math.pi * step / slices, 2 * math.pi * (step + 1) / slices
            shade = 0.70 + 0.30 * (0.5 + 0.5 * math.sin((lat0 + lat1) / 2))
            tint = (*(core * shade), 1.0)
            corners = [on_ball(lat0, lon0), on_ball(lat0, lon1), on_ball(lat1, lon1), on_ball(lat1, lon0)]
            rows += [(*corners[0], *tint), (*corners[1], *tint), (*corners[2], *tint),
                     (*corners[0], *tint), (*corners[2], *tint), (*corners[3], *tint)]
    return np.array(rows, dtype=np.float32)

_EYE4 = np.eye(4, dtype=np.float32)    # 没有摆放矩阵的网格: 原样画


class _Buffer:
    """一个顶点数组对象 + 它的几个缓冲。"""

    def __init__(self):
        self.vao = glGenVertexArrays(1)
        self.buffers = {}
        self.count = 0

    def attribute(self, location, data, size, dynamic=False):
        data = np.ascontiguousarray(data, dtype=np.float32)
        glBindVertexArray(self.vao)
        if location not in self.buffers:
            self.buffers[location] = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.buffers[location])
        glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_DYNAMIC_DRAW if dynamic else GL_STATIC_DRAW)
        glEnableVertexAttribArray(location)
        glVertexAttribPointer(location, size, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
        glBindVertexArray(0)

    def interleaved(self, data, sizes):
        data = np.ascontiguousarray(data, dtype=np.float32)
        glBindVertexArray(self.vao)
        if 'all' not in self.buffers:
            self.buffers['all'] = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.buffers['all'])
        glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
        stride, offset = data.shape[1] * 4, 0
        for location, size in enumerate(sizes):
            glEnableVertexAttribArray(location)
            glVertexAttribPointer(location, size, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(offset))
            offset += size * 4
        glBindVertexArray(0)
        self.count = len(data)

    def elements(self, indices):
        indices = np.ascontiguousarray(indices, dtype=np.uint32)
        glBindVertexArray(self.vao)
        if 'index' not in self.buffers:
            self.buffers['index'] = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.buffers['index'])
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        glBindVertexArray(0)
        self.count = indices.size


class Scene:
    def __init__(self):
        self._ready = False
        self._grid_dark = None

    def _init(self):
        self._back = ShaderProgram(_BACK_VS, _BACK_FS)
        self._flat = ShaderProgram(_FLAT_VS, _FLAT_FS)
        self._mesh = ShaderProgram(_MESH_VS, _MESH_FS)
        self._line = ShaderProgram(_LINE_VS, _LINE_FS, _LINE_GS)
        self._empty = glGenVertexArrays(1)
        self._grid, self._axes, self._axis_solid = _Buffer(), _Buffer(), _Buffer()
        points, states = _axis_lines()
        self._axes.attribute(0, points, 3)
        self._axes.attribute(1, states, 1)
        self._axes.count = len(points)
        self._faces, self._edges, self._sketches = _Buffer(), _Buffer(), _Buffer()
        self._plane_fill, self._plane_edge = _Buffer(), _Buffer()
        self._draw_lines, self._draw_points = _Buffer(), _Buffer()
        self._extras = []               # 另外画的网格 (装配体里别的零件、应力云图): [(缓冲, 颜色, 有没有逐顶点的颜色, 不透明度)...]
        self._extra_edges = []          # 装配体里零件的边线: [(线段缓冲, 摆放矩阵)...]
        self._extra_hover = None        # 光标指着的零件的那条边
        self._covered = False           # 有一个盖在实体上的网格 (云图): 实体自己的面不画
        self._tinted = False            # 实体有单独上了色的特征 (逐顶点颜色, 见 set_geometry)
        self._glass = []                # 实体里半透明的三角面段, 不透明的画完再画
        self._ready = True

    # ---- 数据 (渲染线程在同步阶段调用) ----
    def set_geometry(self, geometry):
        """geometry: {'verts','normals','tris','edge_points','sketch_points'} (都可以是空数组)。"""
        if not self._ready:
            self._init()
        self._faces.attribute(0, geometry['verts'], 3)
        self._faces.attribute(1, geometry['normals'], 3)
        self._faces.attribute(3, geometry.get('tints', EMPTY_TINTS), 3)       # 单独上色的特征的面 (-1 = 零件的颜色)
        self._tinted = bool(geometry.get('tinted'))
        self._glass = list(geometry.get('glass') or ())     # 半透明的三角面段 (排在最后): [(从第几个, 几个, 不透明度)...]
        self._faces.elements(geometry['tris'])
        self._edges.attribute(0, geometry['edge_points'], 3)
        self._edges.count = len(geometry['edge_points'])
        self._sketches.attribute(0, geometry['sketch_points'], 3)
        self._sketches.count = len(geometry['sketch_points'])

    def set_extras(self, parts):
        """另外画的网格: [{'verts', 'normals', 'tris', 'color'}...]。只画, 不参与拾取。
        带 'tints' (每个顶点的颜色) 的按它着色; 带 'cover': True 的是盖在实体上的 (云图), 有它的时候实体自己的面不画。"""
        if not self._ready:
            self._init()
        # 同一批数组 (装配体里没动的零件) 的缓冲照用, 只上传新的 (车门开着动画时每一帧只有门的网格是新的)。
        # 缓存里连数组一起留着: 数组活着, 它的 id 就不会被别的新数组占去, 不会认错
        cached, kept = getattr(self, '_extra_buffers', {}), {}
        self._extras, self._extra_edges = [], []
        if getattr(self, '_extra_hover', None) is None:
            self._extra_hover = _Buffer()
        self._extra_hover.count = 0
        for part in parts:
            tints = part.get('tints')
            key = (id(part['verts']), id(part['normals']), id(part['tris']), id(tints) if tints is not None else None)
            entry = cached.pop(key, None) or kept.get(key)
            if entry is None:
                buffer = _Buffer()
                buffer.attribute(0, part['verts'], 3)
                buffer.attribute(1, part['normals'], 3)
                buffer.attribute(2, np.zeros(len(part['verts']), dtype=np.float32), 1)
                if tints is not None:
                    buffer.attribute(3, tints, 3)
                buffer.elements(part['tris'])
                entry = (buffer, (part['verts'], part['normals'], part['tris'], tints))
            kept[key] = entry
            model = part.get('matrix')          # 运动副动着的件: 网格不变, 只给一个摆放矩阵 (缓冲照用, 动画不卡)
            model = _EYE4 if model is None else np.ascontiguousarray(model, dtype=np.float32)
            self._extras.append((entry[0], tuple(part.get('color') or (0.7, 0.7, 0.7)), tints is not None,
                                 float(part.get('alpha', 1.0)), model))       # 装配体里的玻璃: 半透明, 最后画
            segments = part.get('segments')
            if segments is not None and len(segments):     # 零件的边线: 按显示样式画 (带边线上色 / 消除隐藏线 / 线架图…)
                key = ('edges', id(segments))
                line = cached.pop(key, None) or kept.get(key)
                if line is None:
                    buffer = _Buffer()
                    buffer.attribute(0, np.asarray(segments, dtype=np.float32).reshape(-1, 3), 3)
                    buffer.count = len(segments) * 2
                    line = (buffer, (segments,))
                kept[key] = line
                self._extra_edges.append((line[0], model))
            if part.get('hover_points') is not None:        # 光标指着的那条边: 亮出来 (每次重新上传, 只有几十个点)
                self._extra_hover.attribute(0, part['hover_points'], 3)
                self._extra_hover.attribute(1, np.ones(len(part['hover_points']), dtype=np.float32), 1)
                self._extra_hover.count = len(part['hover_points'])
                self._extra_hover_model = model
        for buffer, _ in cached.values():       # 这次没用上的: 删掉
            glDeleteBuffers(len(buffer.buffers), list(buffer.buffers.values()))
            glDeleteVertexArrays(1, [buffer.vao])
        self._extra_buffers = kept
        self._covered = any(part.get('cover') for part in parts)
        self._ghost = any(part.get('ghost') for part in parts)      # 有预览体: 草图的线画在它上面 (不然被它盖住, 看不见也点不着)

    def set_states(self, states):
        """states: {'faces','edges','sketches'} 各是逐顶点的状态值。"""
        self._faces.attribute(2, states['faces'], 1, dynamic=True)
        self._edges.attribute(1, states['edges'], 1, dynamic=True)
        self._sketches.attribute(1, states['sketches'], 1, dynamic=True)

    def set_planes(self, fill, edge):
        """基准面: 半透明的面 (三角形顶点, 每行 xyz + rgba) 和边框线 (同样的格式)。空数组 = 不显示。"""
        if not self._ready:
            self._init()
        self._plane_fill.interleaved(np.asarray(fill, dtype=np.float32).reshape(-1, 7), (3, 4))
        self._plane_edge.interleaved(np.asarray(edge, dtype=np.float32).reshape(-1, 7), (3, 4))

    def set_drawing(self, line_points, line_states, points):
        """正在编辑的草图: 线段端点 (K,3) + 逐点状态, 以及控制点 (每行 xyz + rgba)。"""
        if not self._ready:
            self._init()
        self._draw_lines.attribute(0, np.asarray(line_points, dtype=np.float32).reshape(-1, 3), 3, dynamic=True)
        self._draw_lines.attribute(1, np.asarray(line_states, dtype=np.float32).reshape(-1), 1, dynamic=True)
        self._draw_lines.count = len(line_points)
        self._draw_points.interleaved(np.asarray(points, dtype=np.float32).reshape(-1, 7), (3, 4))

    # ---- 画一帧 ----
    def render(self, width, height, mvp, eye, dark, grid_matrix=None, options=None):
        """grid_matrix: 网格摆在哪个平面上 (草图编辑时是草图平面); None = 不画网格。
        options: {'style' 显示样式, 'scene' 布景, 'face' 实体颜色或 None, 'clip' 剖切面 (a, b, c, d: ax+by+cz+d >= 0 的留下) 或 None,
                  'cartoon', 'origin' 原点坐标系的一根轴有多长 (mm; 视图按屏幕上一样大算好给过来), 0 = 不画}。"""
        if not self._ready:
            self._init()
        options = options or {}
        style = options.get('style', 'shaded_edges')
        index = 0 if dark else 1
        top, bottom, spot = PALETTE['back_top'][index], PALETTE['back_bottom'][index], False
        if options.get('scene') in SCENES:
            top, bottom, spot, _ = SCENES[options['scene']]
        clip = options.get('clip') or (0.0, 0.0, 0.0, 1.0)
        matrix = np.ascontiguousarray(mvp, dtype=np.float32)
        grid = matrix if grid_matrix is None else np.ascontiguousarray(mvp @ grid_matrix, dtype=np.float32)
        glViewport(0, 0, width, height)
        glDisable(GL_SCISSOR_TEST)
        glDisable(GL_STENCIL_TEST)
        glDisable(GL_CULL_FACE)
        glDepthMask(GL_TRUE)
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glDisable(GL_DEPTH_TEST)
        glDisable(GL_BLEND)
        with self._back:
            glUniform3f(self._back.loc('top'), *top)
            glUniform3f(self._back.loc('bottom'), *bottom)
            glUniform1f(self._back.loc('spot'), 1.0 if spot else 0.0)
            glBindVertexArray(self._empty)
            glDrawArrays(GL_TRIANGLES, 0, 3)

        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glEnable(GL_CLIP_DISTANCE0)
        # 面往后让一点: 贴在面上的边线和草图线不会和面抢深度 (闪烁)
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(1.0, 1.0)
        flat = style in ('hlr', 'hlv')
        if self._faces.count and style != 'wire' and not self._covered:
            base = options.get('face') or PALETTE['face'][index]
            if flat:                    # 面和背景一个颜色: 只留下边线, 像一张线图
                base = tuple((a + b) / 2 for a, b in zip(top, bottom))
            with self._mesh:
                glUniformMatrix4fv(self._mesh.loc('mvp'), 1, GL_TRUE, matrix)
                glUniformMatrix4fv(self._mesh.loc('model'), 1, GL_TRUE, _EYE4)
                glUniform4f(self._mesh.loc('clip'), *clip)
                glUniform3f(self._mesh.loc('eye'), *eye)
                glUniform3f(self._mesh.loc('base'), *base)
                glUniform3f(self._mesh.loc('hover'), *PALETTE['face_hover'][index])
                glUniform3f(self._mesh.loc('chosen'), *PALETTE['face_chosen'][index])
                glUniform1f(self._mesh.loc('flatShade'), 1.0 if flat else 0.0)
                glUniform1f(self._mesh.loc('toon'), 1.0 if options.get('cartoon') else 0.0)
                glUniform1f(self._mesh.loc('useTint'), 2.0 if self._tinted else 0.0)
                glUniform1f(self._mesh.loc('alpha'), 1.0)
                glBindVertexArray(self._faces.vao)
                solid = self._glass[0][0] * 3 if self._glass else self._faces.count
                glDrawElements(GL_TRIANGLES, solid, GL_UNSIGNED_INT, None)
        if self._extras and style != 'wire':          # 线架图: 零件的面不画, 只画边线
            paper = tuple((a + b) / 2 for a, b in zip(top, bottom))
            with self._mesh:
                glUniformMatrix4fv(self._mesh.loc('mvp'), 1, GL_TRUE, matrix)
                glUniform4f(self._mesh.loc('clip'), *clip)
                glUniform3f(self._mesh.loc('eye'), *eye)
                glUniform1f(self._mesh.loc('flatShade'), 1.0 if flat else 0.0)
                glUniform1f(self._mesh.loc('toon'), 0.0)
                glUniform1f(self._mesh.loc('alpha'), 1.0)
                for buffer, color, tinted, alpha, model in sorted(self._extras, key=lambda extra: extra[3] < 1.0):
                    if alpha < 1.0:         # 半透明的 (玻璃) 排在后面: 不透明的都画完了才混合着画, 不写深度
                        glEnable(GL_BLEND)
                        glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
                        glDepthMask(GL_FALSE)
                    glUniform1f(self._mesh.loc('alpha'), alpha)
                    glUniform1f(self._mesh.loc('useTint'), 1.0 if tinted and not flat else 0.0)
                    glUniform3f(self._mesh.loc('base'), *(paper if flat else color))     # 消除隐藏线 / 隐藏线可见: 面和背景一个颜色
                    glUniformMatrix4fv(self._mesh.loc('model'), 1, GL_TRUE, model)
                    glBindVertexArray(buffer.vao)
                    glDrawElements(GL_TRIANGLES, buffer.count, GL_UNSIGNED_INT, None)
                glUniform1f(self._mesh.loc('alpha'), 1.0)
                glUniformMatrix4fv(self._mesh.loc('model'), 1, GL_TRUE, _EYE4)
                glDepthMask(GL_TRUE)
                glDisable(GL_BLEND)
        if self._glass and self._faces.count and style != 'wire' and not self._covered:
            # 半透明的面 (玻璃): 不透明的都画完了才画, 混合、不写深度 — 隔着它看得见后面的内饰
            glEnable(GL_BLEND)
            glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
            glDepthMask(GL_FALSE)
            with self._mesh:
                glBindVertexArray(self._faces.vao)
                for start, count, alpha in self._glass:
                    glUniform1f(self._mesh.loc('alpha'), alpha)
                    glDrawElements(GL_TRIANGLES, count * 3, GL_UNSIGNED_INT, ctypes.c_void_p(start * 3 * 4))
                glUniform1f(self._mesh.loc('alpha'), 1.0)
            glDepthMask(GL_TRUE)
            glDisable(GL_BLEND)
        glDisable(GL_POLYGON_OFFSET_FILL)
        glDisable(GL_CLIP_DISTANCE0)

        glEnable(GL_BLEND)
        glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)
        if self._grid_dark != dark:
            self._grid.interleaved(_grid_vertices(dark), (3, 4))
            self._axis_solid.interleaved(_axis_solids(dark), (3, 4))
            self._grid_dark = dark
        reach = float(options.get('origin') or 0.0)
        axes = np.ascontiguousarray(mvp @ np.diag([reach, reach, reach, 1.0]), dtype=np.float32)
        with self._flat:
            # 平时不画地面网格 (用户不要地板), 只留原点的三根短轴; 编辑草图时在草图平面上画网格当作画图的参照
            if grid_matrix is not None:
                glUniformMatrix4fv(self._flat.loc('mvp'), 1, GL_TRUE, grid)
                glUniform1f(self._flat.loc('fade'), GRID_HALF)
                glBindVertexArray(self._grid.vao)
                glDrawArrays(GL_LINES, 0, self._grid.count)
            glUniformMatrix4fv(self._flat.loc('mvp'), 1, GL_TRUE, matrix)
            glUniform1f(self._flat.loc('fade'), 0.0)
            if self._plane_fill.count:
                glBindVertexArray(self._plane_fill.vao)
                glDrawArrays(GL_TRIANGLES, 0, self._plane_fill.count)
                glBindVertexArray(self._plane_edge.vao)
                glDrawArrays(GL_LINES, 0, self._plane_edge.count)
        glDepthMask(GL_TRUE)
        if reach > 0:                   # 原点坐标系的箭头和小球 (实心的, 要写深度)
            with self._flat:
                glUniformMatrix4fv(self._flat.loc('mvp'), 1, GL_TRUE, axes)
                glUniform1f(self._flat.loc('fade'), 0.0)
                glBindVertexArray(self._axis_solid.vao)
                glDrawArrays(GL_TRIANGLES, 0, self._axis_solid.count)

        with self._line:
            glUniform2f(self._line.loc('viewport'), float(width), float(height))
            glUniform4f(self._line.loc('clip'), 0.0, 0.0, 0.0, 1.0)
            if reach > 0:               # 三根轴杆: 状态 0 / 1 / 2 借来当 X / Y / Z 三种颜色
                glUniformMatrix4fv(self._line.loc('mvp'), 1, GL_TRUE, axes)
                glUniform3f(self._line.loc('base'), *AXIS_TINTS[0][index])
                glUniform3f(self._line.loc('hover'), *AXIS_TINTS[1][index])
                glUniform3f(self._line.loc('chosen'), *AXIS_TINTS[2][index])
                glUniform1f(self._line.loc('alpha'), 1.0)
                glUniform1f(self._line.loc('width'), 2.6)
                glUniform1f(self._line.loc('widthActive'), 2.6)
                glBindVertexArray(self._axes.vao)
                glDrawArrays(GL_LINES, 0, self._axes.count)
            glUniformMatrix4fv(self._line.loc('mvp'), 1, GL_TRUE, matrix)

            def strokes(buffer, base, hover, chosen, width_px, alpha):
                glUniform3f(self._line.loc('base'), *PALETTE[base][index])
                glUniform3f(self._line.loc('hover'), *PALETTE[hover][index])
                glUniform3f(self._line.loc('chosen'), *PALETTE[chosen][index])
                glUniform1f(self._line.loc('alpha'), alpha)
                glUniform1f(self._line.loc('width'), width_px)
                glUniform1f(self._line.loc('widthActive'), 2.6)
                glBindVertexArray(buffer.vao)
                glDrawArrays(GL_LINES, 0, buffer.count)

            if self._sketches.count:
                if getattr(self, '_ghost', False):
                    glDisable(GL_DEPTH_TEST)
                strokes(self._sketches, 'sketch', 'sketch_chosen', 'sketch_chosen', 1.6 if getattr(self, '_ghost', False) else 1.3, 0.85)
                glEnable(GL_DEPTH_TEST)
            if self._edges.count:
                # 实体的边线, 按显示样式: 带边线上色 = 深色细线; 上色 = 不画 (悬停、选中的那条还是亮出来);
                # 消除隐藏线 / 线架图 = 和背景分得开的线; 隐藏线可见 = 被挡住的线也淡淡地画出来
                glEnable(GL_CLIP_DISTANCE0)
                glUniform4f(self._line.loc('clip'), *clip)
                tint = 'edge' if style in ('shaded_edges', 'shaded') else 'edge_wire'
                if style == 'hlv':
                    glDepthFunc(GL_GREATER)
                    glDepthMask(GL_FALSE)
                    strokes(self._edges, tint, 'edge_hover', 'edge_chosen', 1.0, 0.28)
                    glDepthMask(GL_TRUE)
                    glDepthFunc(GL_LEQUAL)
                strokes(self._edges, tint, 'edge_hover', 'edge_chosen', 1.4, 0.0 if style == 'shaded' else 0.90)
                glDisable(GL_CLIP_DISTANCE0)
                glUniform4f(self._line.loc('clip'), 0.0, 0.0, 0.0, 1.0)
            if self._extra_edges and style != 'shaded' and not (options.get('moving') and style == 'shaded_edges'):
                # 转视角、缩放的时候 (moving) 带边线上色先不画零件边线, 停下来再补; 消除隐藏线 / 隐藏线可见 / 线架图靠线看形状, 照画
                # 装配体里零件的边线: 和实体的边一样按显示样式 (上色 = 不画)
                tint = 'edge' if style == 'shaded_edges' else 'edge_wire'
                for buffer, model in self._extra_edges:
                    glUniformMatrix4fv(self._line.loc('mvp'), 1, GL_TRUE, np.ascontiguousarray(mvp @ model, dtype=np.float32))
                    if style == 'hlv':
                        glDepthFunc(GL_GREATER)
                        glDepthMask(GL_FALSE)
                        strokes(buffer, tint, 'edge_hover', 'edge_chosen', 1.0, 0.28)
                        glDepthMask(GL_TRUE)
                        glDepthFunc(GL_LEQUAL)
                    strokes(buffer, tint, 'edge_hover', 'edge_chosen', 1.2, 0.85)
                glUniformMatrix4fv(self._line.loc('mvp'), 1, GL_TRUE, matrix)
            if self._extra_hover is not None and self._extra_hover.count:
                model = getattr(self, '_extra_hover_model', _EYE4)
                glUniformMatrix4fv(self._line.loc('mvp'), 1, GL_TRUE, np.ascontiguousarray(mvp @ model, dtype=np.float32))
                strokes(self._extra_hover, 'edge', 'edge_hover', 'edge_chosen', 2.6, 1.0)
                glUniformMatrix4fv(self._line.loc('mvp'), 1, GL_TRUE, matrix)
            # 正在编辑的草图画在最上面 (不做深度测试): 画在实体里面或背面的轮廓也要看得见
            if self._draw_lines.count:
                glDisable(GL_DEPTH_TEST)
                glUniform3f(self._line.loc('base'), *PALETTE['draw'][index])
                glUniform3f(self._line.loc('hover'), *PALETTE['draw_hover'][index])
                glUniform3f(self._line.loc('chosen'), *PALETTE['draw_chosen'][index])
                glUniform3f(self._line.loc('draft'), *PALETTE['draw_draft'][index])
                glUniform3f(self._line.loc('defined'), *PALETTE['draw_defined'][index])
                glUniform1f(self._line.loc('alpha'), 1.0)
                glUniform1f(self._line.loc('width'), 1.8)
                glUniform1f(self._line.loc('widthActive'), 2.4)
                glBindVertexArray(self._draw_lines.vao)
                glDrawArrays(GL_LINES, 0, self._draw_lines.count)
        if self._draw_points.count:
            glDisable(GL_DEPTH_TEST)
            glEnable(GL_PROGRAM_POINT_SIZE)
            with self._flat:
                glUniformMatrix4fv(self._flat.loc('mvp'), 1, GL_TRUE, matrix)
                glUniform1f(self._flat.loc('fade'), 0.0)
                glUniform1f(self._flat.loc('pointSize'), 8.0)
                glBindVertexArray(self._draw_points.vao)
                glDrawArrays(GL_POINTS, 0, self._draw_points.count)
        glBindVertexArray(0)
        glDisable(GL_BLEND)
        glDisable(GL_DEPTH_TEST)
