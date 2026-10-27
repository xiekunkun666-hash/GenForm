# -*- coding: utf-8 -*-
"""评估页的 绑定工艺 / 设计检查 (界面这一层): 树上的工艺徽标、检查日志、报错的件标红、设计规则存进用户设置。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtGui import QGuiApplication

from genform.session import Session

_APP = QGuiApplication.instance() or QGuiApplication([])


def run(session, command, **args):
    replies = []
    session.execute(command, args, replies.append)
    return replies[0]


class CheckPanel(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.settings_file = os.path.join(folder.name, 'settings.json')
        patcher = patch.dict(os.environ, {'GENFORM_SETTINGS': self.settings_file})     # 不碰用户自己的设置
        patcher.start()
        self.addCleanup(patcher.stop)
        from genform.app import AppController
        self.controller = AppController(Session())
        session = self.session = self.controller.session
        run(session, 'sketch', shapes=[{'type': 'rect', 'w': 100, 'h': 60}])
        self.plate = run(session, 'extrude', distance=3)['id']
        run(session, 'sketch', plane='XY', offset=40, shapes=[{'type': 'rect', 'w': 10, 'h': 10}])
        self.lost = run(session, 'extrude', distance=5)['id']              # 悬空的块

    def row(self, identifier):
        return next(row for row in self.controller.tree if row['kind'] == 'feature' and row['id'] == identifier)

    def test_bound_process_shows_in_the_tree(self):
        self.assertEqual(self.row(self.plate)['process'], '')
        self.controller.bindProcesses()
        row = self.row(self.plate)
        self.assertEqual(row['process'], '激光')
        self.assertIn('激光切割', row['processName'])
        self.assertIn('件', row['processWhy'])

    def test_check_opens_the_log_and_marks_the_floating_part_red(self):
        self.controller.runCheck()
        self.assertTrue(self.controller.checkOpen)
        codes = [item['code'] for item in self.controller.checkIssues]
        self.assertIn('floating', codes)
        self.assertGreater(self.controller.checkCounts['error'], 0)
        self.assertIn(self.lost, self.controller._check_colors())          # 视图里标红
        self.assertTrue(self.row(self.lost)['flagged'])                     # 树上也标
        self.controller.closeCheck()
        self.assertNotIn(self.lost, self.controller._check_colors())       # 关掉就恢复
        self.assertFalse(self.row(self.lost)['flagged'])

    def test_rules_are_saved_in_user_settings_and_used_by_commands(self):
        self.controller.setRule('clearance', '1.5')
        with open(self.settings_file, encoding='utf-8') as handle:
            self.assertEqual(json.load(handle)['rules']['clearance'], 1.5)
        self.assertEqual(run(self.session, 'get_design_rules')['rules']['clearance'], 1.5)
        row = next(item for item in self.controller.designRules if item['key'] == 'clearance')
        self.assertTrue(row['changed'])
        self.controller.resetRules()
        self.assertEqual(run(self.session, 'get_design_rules')['rules']['clearance'], 0.5)

    def test_opening_log_does_not_start_a_check(self):
        with patch.object(self.session, 'execute') as execute:
            self.controller.toggleCheckLog()
        execute.assert_not_called()
        self.assertTrue(self.controller.checkOpen)
        self.assertFalse(self.controller.checkCompleted)

    def test_clear_removes_log_and_scene_marks_until_explicit_check(self):
        self.controller.runCheck()
        self.assertIn(self.lost, self.controller._check_colors())
        self.controller.clearCheck()
        self.assertEqual(self.controller.checkIssues, [])
        self.assertEqual(self.controller.checkCounts, {})
        self.assertEqual(self.controller._check_colors(), {})
        self.assertFalse(self.row(self.lost)['flagged'])
        run(self.session, 'rename_feature', id=self.plate, name='继续建模')
        self.assertEqual(self.controller.checkIssues, [])
        self.controller.closeCheck()
        self.controller.toggleCheckLog()
        self.assertEqual(self.controller.checkIssues, [])
        self.controller.runCheck()
        self.assertIn(self.lost, self.controller._check_colors())

    def test_clear_ignores_result_that_arrives_afterwards(self):
        replies = []
        with patch.object(self.session, 'execute', side_effect=lambda name, args, done: replies.append(done)):
            self.controller.runCheck()
            self.assertTrue(self.controller.checkBusy)
            self.controller.clearCheck()
            replies[0]({'ok': True, 'issues': [{'level': 'error', 'code': 'floating', 'title': '迟到',
                                              'detail': '', 'features': [self.lost], 'point': None}],
                        'counts': {'error': 1}})
        self.assertEqual(self.controller.checkIssues, [])
        self.assertEqual(self.controller._check_red, [])
        self.assertFalse(self.controller.checkBusy)

    def test_modelling_marks_result_stale_and_removes_scene_highlight(self):
        self.controller.runCheck()
        run(self.session, 'rename_feature', id=self.plate, name='新名称')
        self.assertTrue(self.controller.checkStale)
        self.assertEqual(self.controller._check_colors(), {})
        self.controller.closeCheck()
        self.controller.toggleCheckLog()
        self.assertEqual(self.controller._check_colors(), {})

    def test_switching_document_kind_discards_pending_check(self):
        replies = []
        with patch.object(self.session, 'execute', side_effect=lambda name, args, done: replies.append(done)):
            self.controller.runCheck()
            self.controller._set_kind('drawing')
            replies[0]({'ok': True, 'issues': [], 'counts': {'error': 0}})
        self.assertFalse(self.controller.checkOpen)
        self.assertFalse(self.controller.checkCompleted)
        self.assertFalse(self.controller.checkBusy)


if __name__ == '__main__':
    unittest.main()
