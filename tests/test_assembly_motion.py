"""装配体的运动副: 车门绕铰链转 — 内核按转过的位置算 (检查、测量)、视图里的网格跟着转、开着门不算悬空、
存取 .gasm、删零件时序号跟着改、动画放完回到关着、视图里拖。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from genform.kernel import assembly
from genform.session import Session
from genform.sim.motion import rotation
from tests.test_assembly_parts import Files, ask

RULES = {'tolerance': 0.1, 'clearance': 0.5}


class Kernel(unittest.TestCase):
    def setUp(self):
        self.files = Files(self)
        self.session = Session()
        self.base = self.files.block('底板')                            # 40×40×10, z 0 … 10
        self.lid = self.files.block('盖', z=10, w=40, h=40, d=4)        # 盖在上面, z 10 … 14

    def test_swing_turns_the_part_about_the_axis(self):
        swing = {'origin': [-20, 0, 10], 'axis': [0, -1, 0], 'angle': 90}     # 绕左边那条棱往上翻 90°
        result, error = ask(self.session, 'meshes', {'parts': [{'path': self.lid, 'swing': swing}]})
        self.assertIsNone(error)
        low, high = result[0]['low'], result[0]['high']
        self.assertAlmostEqual(low[0], -24, places=3)                   # 立起来了: 厚 4 的那面朝 -X
        self.assertAlmostEqual(high[2], 50, places=3)                   # 40 高

    def test_open_lid_is_not_floating_when_linked(self):
        swing = {'origin': [-20, 0, 14], 'axis': [0, -1, 0], 'angle': 90}     # 绕顶面那条棱翻: 翻开后离底板 4 mm
        parts = [{'name': '底板', 'path': self.base}, {'name': '盖', 'path': self.lid, 'swing': swing}]
        result, _ = ask(self.session, 'contacts', {'parts': parts, 'rules': RULES})
        self.assertEqual(result['floating'], [1])                       # 翻开了, 不贴着底板
        result, _ = ask(self.session, 'contacts', {'parts': parts, 'rules': RULES, 'links': [[0, 1]]})
        self.assertEqual(result['floating'], [])                        # 铰链连着: 不算悬空

    def test_swung_into_the_base_clashes(self):
        swing = {'origin': [-20, 0, 10], 'axis': [0, -1, 0], 'angle': -30}   # 往下翻: 压进底板
        parts = [{'name': '底板', 'path': self.base}, {'name': '盖', 'path': self.lid, 'swing': swing}]
        result, _ = ask(self.session, 'contacts', {'parts': parts, 'rules': RULES})
        self.assertEqual([pair['kind'] for pair in result['pairs']], ['clash'])

    def test_rotation_matrix_matches_the_kernel(self):
        turn = rotation([0, 0, 1], 90)
        self.assertTrue(np.allclose(turn @ [1, 0, 0], [0, 1, 0]))


class Screen(unittest.TestCase):
    def setUp(self):
        self.files = Files(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.dict(os.environ, {'GENFORM_SETTINGS': os.path.join(folder.name, 'settings.json')})
        patcher.start()
        self.addCleanup(patcher.stop)
        from PySide6.QtGui import QGuiApplication
        self.qt = QGuiApplication.instance() or QGuiApplication([])
        from genform.app import AppController
        self.controller = AppController(Session())
        self.controller._set_kind('assembly')
        self.sim = self.controller.sim
        self.sim.pin()
        self.where = os.path.join(self.files.folder.name, 'lid.gasm')
        base, lid = self.files.block('底板', bind=True), self.files.block('盖', z=10, w=40, h=40, d=4, bind=True)
        knob = self.files.block('把手', cx=10, z=14, w=6, h=6, d=4, bind=True)
        rows = [{'name': name, 'file': os.path.basename(path), 'move': [0, 0, 0], 'turn': [0, 0, 0]}
                for name, path in (('底板', base), ('盖', lid), ('把手', knob))]
        joints = [{'name': '盖子', 'kind': 'hinge', 'origin': [-20, 0, 10], 'axis': [0, -1, 0], 'parts': [1, 2], 'base': 0,
                   'min': 0, 'max': 110}]
        with open(self.where, 'w', encoding='utf-8') as handle:
            json.dump({'format': 'genform-assembly', 'version': 1, 'parts': rows, 'joints': joints}, handle, ensure_ascii=False)
        self.assertTrue(self.sim.openAssembly(self.where))

    def mesh(self, low, high):
        from tests.test_assembly_tree import box
        return box(low, high)

    def test_joints_are_read_and_saved(self):
        self.assertEqual([joint['name'] for joint in self.sim.joints], ['盖子'])
        self.assertEqual(self.sim.joints[0]['parts'], ['盖', '把手'])
        self.assertEqual(self.sim.components[2]['joint'], 0)
        self.sim.setJoint(0, 40)
        again = os.path.join(self.files.folder.name, 'again.gasm')
        self.sim.saveAssembly(again)
        with open(again, encoding='utf-8') as handle:
            saved = json.load(handle)['joints'][0]
        self.assertNotIn('value', saved)                                # 只存定义, 不存开到多少
        self.assertEqual(saved['parts'], [1, 2])

    def test_set_joint_clamps_and_poses_the_parts(self):
        self.sim.setJoint(0, 500)
        self.assertEqual(self.sim.joints[0]['value'], 110)
        posed = self.sim._posed_parts()
        self.assertNotIn('swing', posed[0])
        self.assertEqual(posed[1]['swing']['angle'], 110)
        self.assertEqual(posed[2]['swing'], posed[1]['swing'])
        self.assertEqual(self.sim._joint_links(), [[0, 1], [0, 2]])

    def test_view_mesh_turns_with_the_joint(self):
        lid = self.mesh((-20, -20, 10), (20, 20, 14))
        self.assertIs(self.sim._moved_mesh(1, lid), lid)                # 关着: 原样 (视图的缓冲接着用)
        self.sim.setJoint(0, 90)
        moved = self.sim._moved_mesh(1, lid)
        self.assertAlmostEqual(moved['high'][2], 50, places=3)
        self.assertIs(self.sim._moved_mesh(0, lid), lid)                # 底板不跟着动

    def test_removing_a_part_renumbers_the_joint(self):
        self.sim.removePart(1)
        self.assertEqual(self.sim.joints[0]['parts'], ['把手'])
        self.sim.removePart(1)
        self.assertEqual(self.sim.joints, [])                          # 跟着动的都删了: 运动副也没了

    def test_drag_and_actions(self):
        self.assertTrue(self.sim.drag_joint(2, 15.0))                   # 拖把手 = 拖盖子
        self.assertAlmostEqual(self.sim.joints[0]['value'], 15.0)
        self.assertFalse(self.sim.drag_joint(0, 15.0))                  # 底板不跟着谁动
        kind, origin, axis = self.sim.joint_axis(1)
        self.assertEqual((kind, list(axis)), ('hinge', [0, -1, 0]))
        self.assertIsNone(self.sim.joint_axis(0))
        self.sim.jointAction(0, 'open')                                 # 慢慢动过去: 直接放完那一帧
        self.sim._play['clock'].invalidate()
        with patch.object(self.sim._play['clock'], 'elapsed', return_value=5000):
            self.sim._play_frame()
        self.assertAlmostEqual(self.sim.joints[0]['value'], 110)
        self.assertFalse(self.sim.motion['playing'])

    def test_animation_opens_and_closes(self):
        length = self.sim.motion['length']
        self.sim.scrubMotion(length / 2)                                # 中间: 开着
        self.assertAlmostEqual(self.sim.joints[0]['value'], 110)
        self.sim.scrubMotion(length)                                    # 放完: 关上
        self.assertAlmostEqual(self.sim.joints[0]['value'], 0)
        self.sim.playMotion()
        self.assertTrue(self.sim.motion['playing'])
        self.sim.playMotion()
        self.assertFalse(self.sim.motion['playing'])

    def test_spinning_joint_rides_on_another(self):
        self.sim._joints = [dict(self.sim._joints[0], parts=[1], speed=90.0),
                            {'name': '把手', 'kind': 'hinge', 'origin': [10, 0, 0], 'axis': [0, 0, 1], 'parts': [2], 'base': 1,
                             'min': -360, 'max': 360, 'value': 0.0, 'speed': -180.0, 'on': 0}]
        self.assertAlmostEqual(self.sim.motion['length'], 4.0)          # 转得最慢的转一圈
        self.sim.scrubMotion(1.0)                                       # 盖子转 90°, 把手在盖子上再转 -180°
        self.assertEqual([joint['value'] for joint in self.sim.joints], [90.0, -180.0])
        knob = self.mesh((10, 0, 14), (11, 1, 15))
        turn, shift = self.sim._joint_move(self.sim._joints[1])
        moved = self.sim._moved_mesh(2, knob)
        self.assertIs(moved['verts'], knob['verts'])                    # 网格不换, 带摆放矩阵 (视图的缓冲照用)
        np.testing.assert_allclose(moved['matrix'][:3, :3], turn, atol=1e-6)
        np.testing.assert_allclose(moved['matrix'][:3, 3], shift, atol=1e-5)
        swing = self.sim._posed_parts()[2]['swing']
        self.assertEqual((swing['angle'], swing['then']['angle']), (-180.0, 90.0))
        from genform.kernel.assembly import _swing
        motion = _swing(swing)
        np.testing.assert_allclose([[motion.Value(row, column) for column in (1, 2, 3)] for row in (1, 2, 3)], turn, atol=1e-9)
        np.testing.assert_allclose([motion.Value(row, 4) for row in (1, 2, 3)], shift, atol=1e-9)
        again = os.path.join(self.files.folder.name, 'spin.gasm')
        self.sim.saveAssembly(again)
        with open(again, encoding='utf-8') as handle:
            saved = json.load(handle)['joints']
        self.assertEqual((saved[0]['speed'], saved[1]['on']), (90.0, 0))
        self.sim.playMotion()
        self.sim._play['clock'].invalidate()
        with patch.object(self.sim._play['clock'], 'elapsed', return_value=60000):
            self.sim._play_frame()
        self.assertTrue(self.sim.motion['playing'])                     # 一直转: 放不完
        self.sim.playMotion()

    def test_add_and_edit_joint_from_the_panel(self):
        self.sim.addJoint(2)                                            # 把手自己加一个运动副: 从 "盖子" 里拿出来
        self.assertEqual([joint['parts'] for joint in self.sim.joints], [['盖'], ['把手']])
        number = self.sim.pickedJoint
        self.assertEqual(number, 1)
        self.sim.setJointField(number, 'kind', 'spin')
        self.sim.setJointField(number, 'speed', '-90')
        self.sim.setJointField(number, 'axis', 'X')
        self.sim.setJointField(number, 'on', '0')
        self.sim.setJointField(number, 'name', '旋钮')
        row = self.sim.joints[number]
        self.assertEqual((row['spin'], row['speed'], row['axis'], row['on'], row['name']), (True, -90.0, [1.0, 0, 0], 0, '旋钮'))
        self.sim.setJointField(0, 'on', '1')                            # 绕成圈: 不让装
        self.assertEqual(self.sim.joints[0]['on'], -1)
        self.sim.pickJointParts(0)                                      # 点选: 点到的件加进来 / 再点去掉
        self.sim.selectPart(2)
        self.assertEqual(self.sim.joints[0]['parts'], ['盖', '把手'])
        self.sim.selectPart(2)
        self.assertEqual(self.sim.joints[0]['parts'], ['盖'])
        self.sim.pickJointParts(0)
        self.sim.selectPart(2)
        self.assertEqual(self.sim.picked, 2)                            # 结束点选: 点了就是选中
        self.sim.deleteJoint(0)
        self.assertEqual([(joint['name'], joint['on']) for joint in self.sim.joints], [('旋钮', -1)])

    def test_spinning_joints_are_checked_while_turning(self):
        self.sim._joints[0]['speed'] = 90.0                             # 盖子一直转: 转半圈就压进底板
        poses = self.sim._spin_poses()
        self.assertEqual(len(poses), self.sim.SPIN_SAMPLES)
        self.assertEqual(sorted(poses[0]['swings']), ['1', '2'])
        self.assertEqual(self.sim.joints[0]['value'], 0.0)              # 抽完时刻, 运动副照原样
        self.controller.runCheck()
        clashes = [item for item in self.controller.checkIssues if item['code'] == 'motion_clash']
        self.assertTrue(clashes)
        self.assertIn('一直转', clashes[0]['title'])

    def test_rename_part(self):
        self.sim.renamePart(1, '上盖')
        self.assertEqual(self.sim.components[1]['name'], '上盖')
        self.assertIn('rename', [row['id'] for row in self.sim.partMenu(1)])

    def test_live_check_uses_the_open_pose(self):
        self.sim.setJoint(0, 90)
        self.sim.settleJoint()
        if self.sim._live_timer.isActive():
            self.sim._live_timer.stop()
            self.sim._live_start()
        self.assertEqual(self.sim.live['clashes'], 0)
        self.controller.runCheck()
        floating = [item for item in self.controller.checkIssues if item['code'] == 'floating']
        self.assertEqual(floating, [])                                  # 盖子开着, 但铰链连着


if __name__ == '__main__':
    unittest.main()
