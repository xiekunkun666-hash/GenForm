"""装配体的运动副 (和 SOLIDWORKS 的铰链配合 + 运动算例一样): 车门绕前边的铰链转、车盖绕后边的铰链抬、抽屉沿导轨滑。

一个运动副: {'name', 'kind': 'hinge' 绕轴转 (度) / 'slide' 沿轴滑 (mm), 'origin' 轴上一点, 'axis' 轴的方向 (右手定则),
            'parts': [跟着动的零部件序号...] (车门 + 侧窗玻璃 + 后视镜), 'base': 装在哪个件上 (车身),
            'min', 'max' 能动的范围, 'value' 现在动到多少} — 存在 .gasm 的 'joints' 里。
怎么动它: 设计树 "运动副" 下面那几行 → 属性管理器里的滑块; 视图里按住跟着动的件拖 (照着鼠标绕轴转);
"播放动画" 让所有运动副一起 打开 → 停一下 → 关上 (视图下面一条时间轴, 可以拖着看)。
动的时候视图里只把跟着动的那几件的网格变一下 (不问内核, 一帧几毫秒); 松手 / 停下以后实时检查按新的位置查干涉。"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Property, QElapsedTimer, QTimer, Slot

from .. import i18n
from .signals import changed

FRAME_MS = 16                   # 动画一帧 (60 帧每秒)
OPEN_S, HOLD_S, CLOSE_S = 1.6, 0.8, 1.6     # 播放动画: 打开用多久、开着停多久、关上用多久


def _ease(t):
    """慢起慢停 (0 → 1)。"""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def rotation(axis, degrees):
    """绕单位轴 axis 转 degrees 度的 3×3 矩阵 (罗德里格斯公式)。"""
    axis = np.asarray(axis, float)
    axis = axis / max(np.linalg.norm(axis), 1e-12)
    x, y, z = axis
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) * cos + sin * cross + (1 - cos) * np.outer(axis, axis)


class MotionMixin:
    """运动副和动画 (仿真页的一部分; 用在装配体文档里)。"""

    def _motion_init(self):
        self._joints = []
        self._joint_picked = -1
        self._play = {'on': False, 'time': 0.0, 'from': [], 'clock': QElapsedTimer(), 'start': 0.0}
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(FRAME_MS)
        self._play_timer.timeout.connect(self._play_frame)

    # ---- 运动副作用到零件上 ----
    def _joint_of(self, index):
        return next((number for number, joint in enumerate(self._joints) if index in joint['parts']), -1)

    @staticmethod
    def _swing_of(joint):
        value = float(joint.get('value') or 0.0)
        if abs(value) < 1e-9:
            return None
        swing = {'origin': [float(v) for v in joint['origin']], 'axis': [float(v) for v in joint['axis']]}
        swing['slide' if joint['kind'] == 'slide' else 'angle'] = value
        return swing

    def _posed_parts(self):
        """零部件 + 运动副现在让它动了多少 ('swing'): 给内核算检查、测量、导出用。"""
        parts = [dict(part) for part in self._parts]
        for joint in self._joints:
            swing = self._swing_of(joint)
            for index in joint['parts']:
                if swing is not None and 0 <= index < len(parts):
                    parts[index]['swing'] = swing
        return parts

    def _joint_links(self):
        """运动副连着的两件 (跟着动的每一件 ↔ 它装在上面的那件): 设计检查里算连上。"""
        return [[joint['base'], index] for joint in self._joints for index in joint['parts']
                if 0 <= joint.get('base', -1) < len(self._parts) and index < len(self._parts)]

    def _moved_mesh(self, index, mesh):
        """视图里的网格跟着运动副动 (没动就原样给回去, 数组不换 — 视图那边的缓冲接着用)。"""
        number = self._joint_of(index)
        if number < 0:
            return mesh
        joint = self._joints[number]
        value = float(joint.get('value') or 0.0)
        if abs(value) < 1e-9:
            return mesh
        if joint['kind'] == 'slide':
            axis = np.asarray(joint['axis'], float)
            shift = (axis / max(np.linalg.norm(axis), 1e-12) * value).astype(np.float32)
            return dict(mesh, verts=(mesh['verts'] + shift).astype(np.float32), low=list(np.asarray(mesh['low']) + shift),
                        high=list(np.asarray(mesh['high']) + shift))
        turn = rotation(joint['axis'], value).astype(np.float32)
        origin = np.asarray(joint['origin'], np.float32)
        verts = ((np.asarray(mesh['verts'], np.float32) - origin) @ turn.T + origin).astype(np.float32)
        return dict(mesh, verts=verts, normals=(np.asarray(mesh['normals'], np.float32) @ turn.T).astype(np.float32),
                    low=verts.min(axis=0).tolist(), high=verts.max(axis=0).tolist())

    def _joints_moved(self, check=True):
        """运动副动了: 视图更新; check = 停下来了 (松手 / 动画放完), 实时检查按新的位置查。"""
        self._push_parts()
        if check:
            self._live_schedule()
        self.changed.emit()

    # ---- 给界面的 ----
    @Property('QVariantList', notify=changed)
    def joints(self):
        """设计树上 "运动副" 下面的行、属性管理器里的滑块: [{'index', 'name', 'kind', 'value', 'min', 'max', 'unit',
        'parts': 跟着动的件的名字, 'base': 装在哪个件上, 'selected'}...]。"""
        names = [part['name'] for part in self._parts]
        return [{'index': number, 'name': i18n.tr(joint['name']), 'kind': joint['kind'], 'value': float(joint.get('value') or 0.0),
                 'min': float(joint['min']), 'max': float(joint['max']), 'unit': 'mm' if joint['kind'] == 'slide' else '°',
                 'parts': [names[index] for index in joint['parts'] if index < len(names)],
                 'base': names[joint['base']] if 0 <= joint.get('base', -1) < len(names) else '',
                 'selected': number == self._joint_picked}
                for number, joint in enumerate(self._joints)]

    @Property(int, notify=changed)
    def pickedJoint(self):
        return self._joint_picked

    @Property(int, notify=changed)
    def partJoint(self):
        """选中的零部件跟着哪个运动副动 (属性管理器里给它一个滑块); 不跟着动是 -1。"""
        return self._joint_of(self._picked) if self._picked >= 0 else -1

    @Slot(int)
    def selectJoint(self, number):
        number = number if 0 <= number < len(self._joints) else -1
        if number != self._joint_picked:
            self._joint_picked = number
            if number >= 0:
                self._picked = -1
                self._push_parts()
            self.changed.emit()

    @Slot(int, float)
    def setJoint(self, number, value):
        """属性管理器的滑块拖到了 value (拖着的时候一直叫; 松手叫 settleJoint)。"""
        if 0 <= number < len(self._joints):
            joint = self._joints[number]
            value = min(max(float(value), float(joint['min'])), float(joint['max']))
            if abs(value - float(joint.get('value') or 0.0)) > 1e-9:
                joint['value'] = value
                self._stop_play()
                self._joints_moved(check=False)

    @Slot()
    def settleJoint(self):
        """松手了: 按现在的位置查一遍干涉。"""
        self._live_schedule()
        self.changed.emit()

    @Slot(int, str)
    def jointAction(self, number, action):
        """open 开到头 / close 关上 / half 开一半 (属性管理器的按钮)。"""
        if not (0 <= number < len(self._joints)):
            return
        joint = self._joints[number]
        target = {'open': joint['max'], 'close': self._closed(joint),
                  'half': (joint['min'] + joint['max']) / 2}.get(action)
        if target is not None:
            self._animate_to({number: float(target)})

    def drag_joint(self, index, degrees):
        """视图里按住一个跟着动的件拖: 运动副跟着转 degrees 度 (滑的是 mm)。拖不动 (这个件不跟着谁动) 返回 False。"""
        number = self._joint_of(index)
        if number < 0:
            return False
        joint = self._joints[number]
        self._joint_picked = number
        self.setJoint(number, float(joint.get('value') or 0.0) + degrees)
        return True

    def joint_axis(self, index):
        """这个件跟着动的那个运动副的轴 → (类型, 轴上一点, 方向); 不跟着动是 None。视图里拖的时候用。"""
        number = self._joint_of(index)
        if number < 0:
            return None
        joint = self._joints[number]
        return joint['kind'], np.asarray(joint['origin'], float), np.asarray(joint['axis'], float)

    # ---- 播放动画 ----
    @Property('QVariantMap', notify=changed)
    def motion(self):
        """动画的样子: {'playing', 'time' 放到第几秒, 'length' 一共几秒, 'count' 几个运动副}。"""
        return {'playing': self._play['on'], 'time': self._play['time'], 'length': OPEN_S + HOLD_S + CLOSE_S, 'count': len(self._joints)}

    def _pose_at(self, seconds):
        """动画放到第 seconds 秒时每个运动副的值: 一起打开 → 开着停一会 → 一起关上。"""
        if seconds <= OPEN_S:
            share = _ease(seconds / OPEN_S)
        elif seconds <= OPEN_S + HOLD_S:
            share = 1.0
        else:
            share = 1.0 - _ease((seconds - OPEN_S - HOLD_S) / CLOSE_S)
        return [self._closed(joint) + (float(joint['max']) - self._closed(joint)) * share for joint in self._joints]

    @staticmethod
    def _closed(joint):
        """关着的时候是多少: 0 (不在范围里就是 min)。"""
        return 0.0 if float(joint['min']) <= 0.0 <= float(joint['max']) else float(joint['min'])

    @Slot()
    def playMotion(self):
        """播放 / 暂停。放完了再点从头放。"""
        if not self._joints:
            self.app.notice.emit('装配体里还没有运动副：车门、车盖这些要先定好绕哪根轴转')
            return
        if self._play['on']:
            self._stop_play()
            self._joints_moved()
            return
        length = OPEN_S + HOLD_S + CLOSE_S
        if self._play['time'] >= length - 1e-6:
            self._play['time'] = 0.0
        self._play.update(on=True, start=self._play['time'], target=None)
        self._play['clock'].start()
        self._play_timer.start()
        self.changed.emit()

    @Slot(float)
    def scrubMotion(self, seconds):
        """时间轴拖到第 seconds 秒。"""
        if not self._joints:
            return
        self._stop_play()
        self._play['time'] = min(max(float(seconds), 0.0), OPEN_S + HOLD_S + CLOSE_S)
        for joint, value in zip(self._joints, self._pose_at(self._play['time'])):
            joint['value'] = value
        self._joints_moved(check=False)

    def _animate_to(self, targets):
        """几个运动副慢慢动到 targets ({序号: 值}) — 属性管理器的 打开 / 关上 按钮。"""
        self._stop_play()
        self._play.update(on=True, target={number: (float(self._joints[number].get('value') or 0.0), value)
                                           for number, value in targets.items()})
        self._play['clock'].start()
        self._play_timer.start()
        self.changed.emit()

    def _play_frame(self):
        elapsed = self._play['clock'].elapsed() / 1000.0
        target = self._play.get('target')
        if target is not None:                  # 打开 / 关上 按钮: 一秒钟动过去
            share = _ease(elapsed / 1.0)
            for number, (start, end) in target.items():
                if number < len(self._joints):
                    self._joints[number]['value'] = start + (end - start) * share
            if share >= 1.0:
                self._stop_play()
                self._joints_moved()
                return
            self._joints_moved(check=False)
            return
        length = OPEN_S + HOLD_S + CLOSE_S
        self._play['time'] = min(self._play['start'] + elapsed, length)
        for joint, value in zip(self._joints, self._pose_at(self._play['time'])):
            joint['value'] = value
        if self._play['time'] >= length:
            self._stop_play()
            self._joints_moved()
            return
        self._joints_moved(check=False)

    def _stop_play(self):
        if self._play['on']:
            self._play['on'] = False
            self._play['target'] = None
            self._play_timer.stop()

    # ---- 存取 / 零部件增删时跟着改序号 ----
    def _joints_to_file(self):
        return [{key: joint[key] for key in ('name', 'kind', 'origin', 'axis', 'parts', 'base', 'min', 'max')}
                for joint in self._joints]

    def _joints_from_file(self, rows, count):
        joints = []
        for row in rows or ():
            try:
                parts = [int(index) for index in row['parts'] if 0 <= int(index) < count]
                joint = {'name': str(row.get('name') or '运动副'), 'kind': 'slide' if row.get('kind') == 'slide' else 'hinge',
                         'origin': [float(value) for value in row['origin']][:3], 'axis': [float(value) for value in row['axis']][:3],
                         'parts': parts, 'base': int(row.get('base', 0)), 'min': float(row.get('min', 0.0)),
                         'max': float(row.get('max', 90.0)), 'value': 0.0}
            except (KeyError, TypeError, ValueError):
                continue
            if parts and len(joint['origin']) == 3 and len(joint['axis']) == 3:
                joints.append(joint)
        self._stop_play()
        self._joints, self._joint_picked = joints, -1
        self._play['time'] = 0.0

    def _joints_renumber(self, mapping):
        """零部件删了 / 挪了顺序: 运动副里的序号跟着换 (mapping: 旧序号 → 新序号, 删掉的不在里面)。"""
        for joint in self._joints:
            joint['parts'] = [mapping[index] for index in joint['parts'] if index in mapping]
            joint['base'] = mapping.get(joint.get('base', 0), -1)
        self._joints = [joint for joint in self._joints if joint['parts']]
        if self._joint_picked >= len(self._joints):
            self._joint_picked = -1
