"""装配体的 草图 / 评估 两页: 布局草图跟着 .gasm 存取、设计树上列出来; 评估 → 测量点零部件; 状态栏的日志按钮。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from genform.session import Session
from tests.test_assembly_parts import Files


class Pages(unittest.TestCase):
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
        self.sim.addPart(self.files.block('底板', bind=True))
        self.sim.addPart(self.files.block('块', z=30, w=10, h=10, bind=True))      # 隔 20 mm

    def run_command(self, name, **args):
        replies = []
        self.controller.session.execute(name, args, replies.append)
        self.assertTrue(replies[0]['ok'], replies[0].get('error'))
        return replies[0]

    def test_assembly_has_sketch_and_evaluate_pages(self):
        for page in ('sketch', 'evaluate', 'assembly'):
            self.controller.setTab(page)
            self.assertEqual(self.controller.tab, page)
        self.controller.setTab('feature')                              # 装配体里没有特征页
        self.assertEqual(self.controller.tab, 'assembly')

    def test_layout_sketch_is_saved_with_the_assembly(self):
        self.assertTrue(self.sim.layout_mode())
        self.run_command('sketch', shapes=[{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 100, 'y2': 0}], plane='XY', offset=0.0)
        sketches = self.controller.layoutSketches
        self.assertEqual(len(sketches), 1)
        self.assertTrue(self.controller.title.endswith(' *'))         # 画了布局草图: 装配体算改过
        where = os.path.join(self.files.folder.name, 'layout.gasm')
        self.sim.saveAssembly(where)
        with open(where, encoding='utf-8') as handle:
            saved = json.load(handle)
        self.assertEqual([feature['type'] for feature in saved['layout']['features']], ['sketch'])
        self.assertFalse(self.controller.title.endswith(' *'))
        self.controller.backToPart()
        self.controller.newOf('part')                                   # 换掉底下的文档
        self.controller.openDocument(where)
        self.assertEqual(self.controller.docKind, 'assembly')
        self.assertEqual([row['name'] for row in self.controller.layoutSketches], [sketches[0]['name']])
        self.assertEqual(len(self.sim._parts), 2)

    def test_measure_two_parts(self):
        self.controller.setTab('evaluate')
        self.controller.toggleMeasure()
        self.assertTrue(self.controller.measuring)
        self.controller._on_picked('component', 0, False)
        rows = {row['label']: row['value'] for row in self.controller.measure['rows']}
        self.assertEqual(rows['长 (X)'], '40 mm')
        self.assertIn('体积', rows)
        self.controller._on_picked('component', 1, False)
        rows = {row['label']: row['value'] for row in self.controller.measure['rows']}
        self.assertEqual(rows['最短距离'], '20 mm')
        self.assertEqual(rows['ΔZ'], '20 mm')
        self.assertEqual(self.sim._measured, {0, 1})
        self.controller.toggleMeasure()
        self.assertFalse(self.controller.measuring)
        self.assertEqual(self.sim._measured, set())

    def test_log_button_runs_then_toggles(self):
        self.assertFalse(self.controller.checkOpen)
        self.controller.toggleCheckLog()                                # 还没查过: 查一遍, 日志拉出来
        self.assertTrue(self.controller.checkOpen)
        self.assertTrue(self.controller.checkIssues)
        self.controller.toggleCheckLog()
        self.assertFalse(self.controller.checkOpen)
        self.controller.toggleCheckLog()                                # 有结果: 直接拉出来
        self.assertTrue(self.controller.checkOpen)
        self.controller._set_kind('part')                               # 换了文档种类: 旧结果清掉
        self.assertEqual(self.controller.checkIssues, [])


if __name__ == '__main__':
    unittest.main()
