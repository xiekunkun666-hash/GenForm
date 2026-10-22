"""装配体的运动副 (和 SOLIDWORKS 的铰链配合 + 运动算例一样): 车门绕前边的铰链转、车盖绕后边的铰链抬、抽屉沿导轨滑。

一个运动副: {'name', 'kind': 'hinge' 绕轴转 (度) / 'slide' 沿轴滑 (mm), 'origin' 轴上一点, 'axis' 轴的方向 (右手定则),
            'parts': [跟着动的零部件序号...] (车门 + 侧窗玻璃 + 后视镜), 'base': 装在哪个件上 (车身),
            'min', 'max' 能动的范围, 'value' 现在动到多少} — 存在 .gasm 的 'joints' 里。
一直转的 (电机、齿轮): 再加 'speed' 每秒转几度, 'on' 装在哪个运动副上 (行星轮绕自己的轴转, 又跟着行星架绕中心转);
有一直转的运动副, "播放动画" 就是一直转下去, 再点停下。
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
        self._joint_adding = -1         # 正等着点零部件加进 / 去掉的运动副 (属性管理器 "点选跟着动的件")
        self._play = {'on': False, 'time': 0.0, 'from': [], 'clock': QElapsedTimer(), 'start': 0.0}
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(FRAME_MS)
        self._play_timer.timeout.connect(self._play_frame)

    # ---- 运动副作用到零件上 ----
    def _spinning(self):
        return any(joint.get('speed') for joint in self._joints)

    def _length(self):
        """时间轴多长: 打开 + 停 + 关上; 一直转的是转得最慢的那个转一圈。"""
        speeds = [abs(float(joint['speed'])) for joint in self._joints if joint.get('speed')]
        return 360.0 / min(speeds) if speeds else OPEN_S + HOLD_S + CLOSE_S

    SPIN_SAMPLES = 8            # 设计检查查运动干涉: 一直转的转一圈里抽几个时刻 (错开整数, 不和齿的周期正好对上)

    def _spin_poses(self):
        """一直转的运动副一起转, 一圈里抽几个时刻 → [{'value' 第几秒, 'swings' {零部件序号: 它的 swing}}...] (内核 sweep 用)。"""
        length, saved, poses = self._length(), [joint.get('value') for joint in self._joints], []
        try:
            for step in range(self.SPIN_SAMPLES):
                seconds = length * (step + 0.37) / self.SPIN_SAMPLES
                for joint, value in zip(self._joints, self._pose_at(seconds)):
                    joint['value'] = value if joint.get('speed') else 0.0
                swings = {}
                for joint in self._joints:
                    swing = self._swing_of(joint) if joint.get('speed') else None
                    for index in joint['parts']:
                        if swing is not None:
                            swings[str(index)] = swing
                poses.append({'value': round(seconds, 3), 'swings': swings})
        finally:
            for joint, value in zip(self._joints, saved):
                joint['value'] = value
        return poses

    def _parent(self, joint):
        number = int(joint.get('on', -1))
        return self._joints[number] if 0 <= number < len(self._joints) and self._joints[number] is not joint else None

    def _joint_of(self, index):
        return next((number for number, joint in enumerate(self._joints) if index in joint['parts']), -1)

    def _swing_of(self, joint, depth=0):
        """运动副现在的动作; 装在别的运动副上的, 'then' 是那个运动副接着带它动的。"""
        parent = self._parent(joint)
        parent = self._swing_of(parent, depth + 1) if parent is not None and depth < 8 else None
        value = float(joint.get('value') or 0.0)
        if abs(value) < 1e-9:
            return parent
        swing = {'origin': [float(v) for v in joint['origin']], 'axis': [float(v) for v in joint['axis']]}
        swing['slide' if joint['kind'] == 'slide' else 'angle'] = value
        if parent is not None:
            swing['then'] = parent
        return swing

    def _joint_move(self, joint, depth=0):
        """运动副 (连着它装在上面的那些) 把点挪到哪: (3×3 转动, 平移), 点 p → turn @ p + shift; 没动是 None。"""
        parent = self._parent(joint)
        parent = self._joint_move(parent, depth + 1) if parent is not None and depth < 8 else None
        value = float(joint.get('value') or 0.0)
        if abs(value) < 1e-9:
            return parent
        if joint['kind'] == 'slide':
            axis = np.asarray(joint['axis'], float)
            turn, shift = np.eye(3), axis / max(np.linalg.norm(axis), 1e-12) * value
        else:
            turn = rotation(joint['axis'], value)
            origin = np.asarray(joint['origin'], float)
            shift = origin - turn @ origin
        if parent is None:
            return turn, shift
        return parent[0] @ turn, parent[0] @ shift + parent[1]

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
        move = self._joint_move(self._joints[number])
        if move is None:
            return mesh
        # 网格数组原样留着 (视图的缓冲照用), 只带一个摆放矩阵; 包围盒按八个角挪过去 (拾取、整屏显示用)
        matrix = np.eye(4, dtype=np.float32)
        matrix[:3, :3], matrix[:3, 3] = move[0], move[1]
        low, high = np.asarray(mesh['low'], float), np.asarray(mesh['high'], float)
        corners = np.array([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]) @ move[0].T + move[1]
        return dict(mesh, matrix=matrix, low=corners.min(axis=0).tolist(), high=corners.max(axis=0).tolist())

    def _joints_moved(self, check=True):
        """运动副动了: 视图更新; check = 停下来了 (松手 / 动画放完), 实时检查按新的位置查。
        放动画时视图每帧都更新, 界面 (设计树、时间轴) 一秒只刷十次 — 每帧都刷, 设计树几十行重算一遍, 动画就一顿一顿的。"""
        self._push_parts()
        if check:
            self._live_schedule()
        clock = self._play.setdefault('ui', QElapsedTimer())
        if check or not self._play['on'] or not clock.isValid() or clock.elapsed() >= 100:
            clock.start()
            self.changed.emit()

    # ---- 给界面的 ----
    @Property('QVariantList', notify=changed)
    def joints(self):
        """设计树上 "运动副" 下面的行、属性管理器里的滑块: [{'index', 'name', 'kind', 'value', 'min', 'max', 'unit',
        'parts': 跟着动的件的名字, 'base': 装在哪个件上, 'selected'}...]。"""
        names = [part['name'] for part in self._parts]
        return [{'index': number, 'name': i18n.tr(joint['name']), 'kind': joint['kind'], 'value': float(joint.get('value') or 0.0),
                 'min': float(joint['min']), 'max': float(joint['max']), 'unit': 'mm' if joint['kind'] == 'slide' else '°',
                 'parts': [names[index] for index in joint['parts'] if index < len(names)], 'partIndices': list(joint['parts']),
                 'base': names[joint['base']] if 0 <= joint.get('base', -1) < len(names) else '', 'baseIndex': joint.get('base', -1),
                 'spin': bool(joint.get('speed')), 'speed': float(joint.get('speed') or 0.0),
                 'on': int(joint.get('on', -1)), 'onName': self._parent(joint)['name'] if self._parent(joint) is not None else '',
                 'origin': [float(value) for value in joint['origin']], 'axis': [float(value) for value in joint['axis']],
                 'adding': number == self._joint_adding, 'selected': number == self._joint_picked}
                for number, joint in enumerate(self._joints)]

    # ---- 自己加 / 改运动副 (属性管理器) ----
    def _joints_edited(self, number=None):
        self._stop_play()
        if number is not None:
            self._joint_picked = number
        self.dirty = True
        self.app.changed.emit()
        self._joints_moved()

    def _part_centre(self, index):
        mesh = next((mesh for number, mesh in self._shown if number == index), None)
        if mesh is None:
            return [0.0, 0.0, 0.0]
        return [round((float(low) + float(high)) / 2, 3) for low, high in zip(mesh['low'], mesh['high'])]

    @Slot(int)
    def addJoint(self, index):
        """给选中的零部件加一个运动副: 先是绕过它中心的 Z 轴转 0~90° 的铰链, 装在第一个件上; 再在属性管理器里改。"""
        if not (0 <= index < len(self._parts)):
            return
        for joint in self._joints:                  # 一个件只跟着一个运动副动
            joint['parts'] = [number for number in joint['parts'] if number != index]
        self._joints = [joint for joint in self._joints if joint['parts']]
        names = {joint['name'] for joint in self._joints}
        name = next(f'运动副{count}' for count in range(1, 999) if f'运动副{count}' not in names)
        self._joints.append({'name': name, 'kind': 'hinge', 'origin': self._part_centre(index), 'axis': [0.0, 0.0, 1.0],
                             'parts': [index], 'base': 0 if index != 0 else min(1, len(self._parts) - 1),
                             'min': 0.0, 'max': 90.0, 'value': 0.0})
        self._joints_edited(len(self._joints) - 1)

    @Slot(int)
    def deleteJoint(self, number):
        if not (0 <= number < len(self._joints)):
            return
        del self._joints[number]
        for joint in self._joints:
            on = int(joint.get('on', -1))
            joint['on'] = -1 if on == number else on - (on > number)
        self._joint_adding = -1
        self._joint_picked = -1
        self._play['time'] = 0.0
        self._joints_edited()

    @Slot(int, str, str)
    def setJointField(self, number, key, text):
        """改运动副的一项: name 名字 / kind hinge 铰链 · slide 滑动 · spin 一直转 / axis X·Y·Z 或 "x,y,z" /
        origin0~2 轴上一点 / min / max 范围 / speed 每秒转几度 / base 装在哪个件 (序号) / on 装在哪个运动副上 (序号, -1 = 不装)。"""
        if not (0 <= number < len(self._joints)):
            return
        joint, text = self._joints[number], str(text).strip()
        try:
            if key == 'name' and text:
                joint['name'] = text
            elif key == 'kind':
                joint['kind'] = 'slide' if text == 'slide' else 'hinge'
                if text == 'spin':
                    joint['speed'] = joint.get('speed') or 36.0
                    joint['min'], joint['max'] = -360.0, 360.0
                else:
                    joint.pop('speed', None)
                    joint.pop('on', None)
                    joint['min'], joint['max'] = (0.0, 100.0) if text == 'slide' else (0.0, 90.0)
                joint['value'] = 0.0
            elif key == 'axis':
                axis = {'X': [1.0, 0, 0], 'Y': [0, 1.0, 0], 'Z': [0, 0, 1.0]}.get(text.upper()) or [float(v) for v in text.split(',')]
                if len(axis) != 3 or np.linalg.norm(axis) < 1e-9:
                    return
                joint['axis'] = [float(v) for v in axis]
            elif key.startswith('origin'):
                joint['origin'][int(key[-1])] = float(text)
            elif key in ('min', 'max'):
                joint[key] = float(text)
                if joint['min'] > joint['max']:
                    joint['min'], joint['max'] = joint['max'], joint['min']
            elif key == 'speed':
                joint['speed'] = float(text) or 1.0
            elif key == 'base':
                joint['base'] = int(text)
            elif key == 'on':
                on = int(text)
                parent, depth = (self._joints[on] if 0 <= on < len(self._joints) else None), 0
                while parent is not None and depth < 9:     # 不能装在自己 (或自己带着的) 运动副上: 会绕成圈
                    if parent is joint:
                        self.app.notice.emit('不能装在它自己带着的运动副上')
                        return
                    parent, depth = self._parent(parent), depth + 1
                joint['on'] = on if 0 <= on < len(self._joints) else -1
            else:
                return
        except (TypeError, ValueError, IndexError):
            return
        self._joints_edited(number)

    @Slot(int)
    def jointCentre(self, number):
        """运动副的轴挪到选中零部件的中心 (行星轮绕自己的轴转: 选中它, 点这个)。"""
        if 0 <= number < len(self._joints) and 0 <= self._picked < len(self._parts):
            self._joints[number]['origin'] = self._part_centre(self._picked)
            self._joints_edited(number)

    @Slot(int)
    def pickJointParts(self, number):
        """开始 / 结束点选跟着动的件: 开着的时候在视图或设计树里点零部件 = 加进这个运动副, 再点一次 = 去掉。"""
        self._joint_adding = number if 0 <= number < len(self._joints) and number != self._joint_adding else -1
        if self._joint_adding >= 0:
            self._joint_picked = number
        self.changed.emit()

    def _toggle_joint_part(self, index):
        """点选模式下点了零部件 index: 在这个运动副里就去掉, 不在就加进来 (从别的运动副里拿出来)。"""
        joint = self._joints[self._joint_adding]
        if index in joint['parts']:
            if len(joint['parts']) > 1:
                joint['parts'].remove(index)
        elif index != joint.get('base'):
            for other in self._joints:
                if other is not joint and index in other['parts'] and len(other['parts']) > 1:
                    other['parts'].remove(index)
            joint['parts'].append(index)
        self._joints_edited(self._joint_adding)

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
        length = self._length()
        time = self._play['time'] % length if self._spinning() else self._play['time']
        return {'playing': self._play['on'], 'time': time, 'length': length, 'count': len(self._joints)}

    def _pose_at(self, seconds):
        """动画放到第 seconds 秒时每个运动副的值: 一起打开 → 开着停一会 → 一起关上; 一直转的按 speed 转下去。"""
        if self._spinning():
            return [math.fmod(float(joint.get('speed') or 0.0) * seconds, 360.0) for joint in self._joints]
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
            self.app.notice.emit('装配体里还没有运动副：选中一个零部件，在属性管理器里点“给它加运动副”')
            return
        if self._play['on']:
            self._stop_play()
            self._joints_moved()
            return
        length = self._length()
        if not self._spinning() and self._play['time'] >= length - 1e-6:
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
        self._play['time'] = min(max(float(seconds), 0.0), self._length())
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
        spinning, length = self._spinning(), self._length()
        self._play['time'] = self._play['start'] + elapsed if spinning else min(self._play['start'] + elapsed, length)
        for joint, value in zip(self._joints, self._pose_at(self._play['time'])):
            joint['value'] = value
        if not spinning and self._play['time'] >= length:
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
        return [dict({key: joint[key] for key in ('name', 'kind', 'origin', 'axis', 'parts', 'base', 'min', 'max')},
                     **({'speed': joint['speed']} if joint.get('speed') else {}),
                     **({'on': joint['on']} if int(joint.get('on', -1)) >= 0 else {}))
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
                if row.get('speed'):
                    joint['speed'] = float(row['speed'])
                if int(row.get('on', -1)) >= 0:
                    joint['on'] = int(row['on'])
            except (KeyError, TypeError, ValueError):
                continue
            if parts and len(joint['origin']) == 3 and len(joint['axis']) == 3:
                joints.append(joint)
        self._stop_play()
        self._joints, self._joint_picked, self._joint_adding = joints, -1, -1
        self._play['time'] = 0.0

    def _joints_renumber(self, mapping):
        """零部件删了 / 挪了顺序: 运动副里的序号跟着换 (mapping: 旧序号 → 新序号, 删掉的不在里面)。"""
        for joint in self._joints:
            joint['parts'] = [mapping[index] for index in joint['parts'] if index in mapping]
            joint['base'] = mapping.get(joint.get('base', 0), -1)
        kept = [number for number, joint in enumerate(self._joints) if joint['parts']]
        for joint in self._joints:
            if int(joint.get('on', -1)) >= 0:
                joint['on'] = kept.index(joint['on']) if joint['on'] in kept else -1
        self._joints = [self._joints[number] for number in kept]
        if self._joint_picked >= len(self._joints):
            self._joint_picked = -1
