# -*- coding: utf-8 -*-
"""轨道相机 + 屏幕和三维之间的换算 (纯 numpy, 不碰 OpenGL)。

坐标: Z 朝上。矩阵按 "列向量" 约定: 裁剪坐标 = proj @ view @ 点。
屏幕坐标: 像素, 原点在视图左上角, y 朝下。
"""
from __future__ import annotations

import math

import numpy as np

FOV = 32.0                      # 竖直视角 (度): 比常见的 45 小, 透视变形轻, 零件看着更 "正"
VIEWS = {                       # 名称 → (方位角, 俯仰角)。方位角 0 = 从 -Y 往 +Y 看 (前视)
    'iso': (-35.0, 28.0), 'front': (0.0, 0.0), 'back': (180.0, 0.0),
    'right': (-90.0, 0.0), 'left': (90.0, 0.0), 'top': (0.0, 89.9), 'bottom': (0.0, -89.9),
}


class Camera:
    def __init__(self):
        self.target = np.zeros(3)
        self.yaw, self.pitch = VIEWS['iso']
        self.distance = 260.0
        self.perspective = True         # False = 平行投影 (远近一样大)

    def copy(self):
        twin = Camera()
        twin.target, twin.yaw, twin.pitch = np.array(self.target, dtype=float), self.yaw, self.pitch
        twin.distance, twin.perspective = self.distance, self.perspective
        return twin

    # ---- 位置和朝向 ----
    def basis(self):
        """→ (front 看的方向, right 屏幕右, up 屏幕上), 单位向量。"""
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        front = np.array([math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), -math.sin(pitch)])
        right = np.cross(front, (0.0, 0.0, 1.0))
        right /= np.linalg.norm(right)
        return front, right, np.cross(right, front)

    def eye(self):
        return self.target - self.basis()[0] * self.distance

    def view(self):
        front, right, up = self.basis()
        matrix = np.eye(4)
        matrix[0, :3], matrix[1, :3], matrix[2, :3] = right, up, -front
        matrix[:3, 3] = -matrix[:3, :3] @ self.eye()
        return matrix

    def projection(self, aspect):
        near, far = max(self.distance * 0.02, 0.05), self.distance * 40.0 + 2000.0
        scale = 1.0 / math.tan(math.radians(FOV) / 2)
        matrix = np.zeros((4, 4))
        if not self.perspective:
            # 平行投影: 画面的高 = 透视时目标点那个深度上看到的高, 两种投影切换时零件大小不跳
            half = self.distance / scale
            near = -far                 # 眼睛 "后面" 的东西也照样画: 平行投影没有眼睛的位置
            matrix[0, 0], matrix[1, 1] = 1.0 / (half * aspect), 1.0 / half
            matrix[2, 2], matrix[2, 3] = -2.0 / (far - near), -(far + near) / (far - near)
            matrix[3, 3] = 1.0
            return matrix
        matrix[0, 0], matrix[1, 1] = scale / aspect, scale
        matrix[2, 2], matrix[2, 3] = (far + near) / (near - far), 2 * far * near / (near - far)
        matrix[3, 2] = -1.0
        return matrix

    def matrix(self, width, height):
        return self.projection(width / max(height, 1)) @ self.view()

    # ---- 操作 ----
    def orbit(self, dx, dy):
        self.yaw = (self.yaw + dx * 0.4 + 180.0) % 360.0 - 180.0
        self.pitch = max(-89.9, min(89.9, self.pitch + dy * 0.4))

    def pixel_size(self, height):
        """目标点所在深度上, 一个像素对应多少毫米。"""
        return 2 * self.distance * math.tan(math.radians(FOV) / 2) / max(height, 1)

    def pan(self, dx, dy, height):
        _, right, up = self.basis()
        self.target = self.target + (-dx * right + dy * up) * self.pixel_size(height)

    def zoom(self, factor, anchor=None):
        """缩放; anchor 是光标指着的三维点 — 给了就朝它缩放 (它在屏幕上不动), 不然朝画面中心。"""
        distance = min(max(self.distance * factor, 0.5), 1e5)
        actual = distance / self.distance
        if anchor is not None:
            self.target = np.asarray(anchor, dtype=float) + (self.target - anchor) * actual
        self.distance = distance

    def set_view(self, name):
        self.yaw, self.pitch = VIEWS[name]

    def fit(self, low, high, aspect=1.0):
        """把包围盒放进画面 (留边)。"""
        low, high = np.asarray(low, dtype=float), np.asarray(high, dtype=float)
        self.target = (low + high) / 2
        radius = max(float(np.linalg.norm(high - low)) / 2, 1.0)
        half = math.radians(FOV) / 2
        if aspect < 1:
            half = math.atan(math.tan(half) * aspect)
        self.distance = radius / math.sin(half) * 1.15

    # ---- 屏幕 ↔ 三维 ----
    def ray(self, x, y, width, height):
        """屏幕上一点 → 射线 (起点, 单位方向)。"""
        front, right, up = self.basis()
        half = math.tan(math.radians(FOV) / 2)
        horizontal = (2 * x / max(width, 1) - 1) * half * width / max(height, 1)
        vertical = (1 - 2 * y / max(height, 1)) * half
        if not self.perspective:
            return self.eye() + (right * horizontal + up * vertical) * self.distance, front
        direction = front + right * horizontal + up * vertical
        return self.eye(), direction / np.linalg.norm(direction)

    def project(self, points, width, height):
        """三维点 (N,3) → 屏幕像素 (N,2) 和到相机平面的深度 (N,)。深度 <= 0 的点在相机后面。"""
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        clip = (self.matrix(width, height) @ np.c_[points, np.ones(len(points))].T).T
        depth = (points - self.eye()) @ self.basis()[0]         # 沿视线方向到眼睛的距离 (透视时就是 clip 的 w)
        if not self.perspective:
            depth = np.maximum(depth, 1e-6)                     # 平行投影没有 "相机后面"
        scale = clip[:, 3]
        safe = np.where(np.abs(scale) > 1e-9, scale, 1e-9)
        screen = np.empty((len(points), 2))
        screen[:, 0] = (clip[:, 0] / safe * 0.5 + 0.5) * width
        screen[:, 1] = (0.5 - clip[:, 1] / safe * 0.5) * height
        return screen, depth
