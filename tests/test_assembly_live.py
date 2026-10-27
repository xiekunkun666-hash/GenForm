"""装配体设计检查的提速和实时检查: 每一对的结果按 (文件版本, 摆放) 记着, 挪一个零件只算变了的几对;
分段算 (budget); 磁盘上记着下次打开还能用; 界面这一层: 零件一变就在后台查, 干涉的两件画红叉、设计树上打叉。"""
import os
import tempfile
import unittest
from unittest.mock import patch

from genform.kernel import assembly
from genform.session import Session
from tests.test_assembly_parts import Files, ask

RULES = {'tolerance': 0.1, 'clearance': 0.5}


class Cache(unittest.TestCase):
    def setUp(self):
        self.files = Files(self)
        self.session = Session()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.where = os.path.join(folder.name, 'contacts.json')
        for name, value in (('_PAIRS_FILE', [self.where]), ('_PAIRS', {}), ('_PLACED', {})):
            patcher = patch.object(assembly, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        base, block = self.files.block('底板'), self.files.block('块', z=10, w=10, h=10)
        self.parts = [{'name': '底板', 'path': base}, {'name': '块', 'path': block}, {'name': '另一块', 'path': block, 'move': [20, 20, 0]}]

    def check(self, parts=None, **extra):
        result, error = ask(self.session, 'contacts', dict({'parts': parts or self.parts, 'rules': RULES}, **extra))
        self.assertIsNone(error)
        return result

    def test_second_check_uses_the_remembered_pairs(self):
        first = self.check()
        self.assertGreater(first['fresh'], 0)
        again = self.check()
        self.assertEqual(again['fresh'], 0)
        self.assertEqual([(pair['a'], pair['b'], pair['kind']) for pair in again['pairs']],
                         [(pair['a'], pair['b'], pair['kind']) for pair in first['pairs']])
        self.assertTrue(os.path.isfile(self.where))                     # 磁盘上也记着

    def test_moving_one_part_only_redoes_its_pairs(self):
        self.check()
        moved = [dict(part) for part in self.parts]
        moved[1]['move'] = [0, 0, -3]                                   # 压进底板 3 mm
        result = self.check(moved)
        self.assertEqual(result['fresh'], 1)                            # 只有 底板 ↔ 块 这一对 (另一块离得远, 包围盒都不挨)
        self.assertEqual([pair['kind'] for pair in result['pairs'] if pair['b'] == 1], ['clash'])

    def test_order_does_not_matter(self):
        self.check()
        result = self.check(list(reversed(self.parts)))
        self.assertEqual(result['fresh'], 0)

    def test_budget_splits_the_work(self):
        result = self.check(budget=0.0)
        self.assertTrue(result['partial'])
        self.assertEqual(result['fresh'], 1)                            # 到点了也至少算一对, 不会原地打转
        while result['partial']:
            result = self.check(budget=0.0)
        self.assertEqual(result['done'], result['total'])
        self.assertEqual(result['floating'], [])

    def test_saved_pairs_are_read_back(self):
        self.check()
        assembly._PAIRS.clear()
        assembly._PAIRS_FILE[:] = []
        with patch.object(assembly.store, 'folder', lambda: os.path.dirname(self.where)), \
                patch.object(assembly.store, 'stamp', lambda: 'x'):
            os.replace(self.where, os.path.join(os.path.dirname(self.where), 'contacts-x.json'))
            self.assertEqual(self.check()['fresh'], 0)

    def test_far_apart_pair_is_skipped_by_the_mesh_filter(self):
        calls = []
        real = assembly._distance

        def counted(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)
        bar = self.files.block('长条', w=200, h=10, d=10)                # 转 45° 以后包围盒是个大方块, 套住角上的小块
        far = self.files.block('角上的小块', cx=60, cy=-60, w=4, h=4, d=4)   # 离长条的表面八十多毫米
        with patch.object(assembly, '_distance', counted):
            result = self.check([{'name': '长条', 'path': bar, 'turn': [0, 0, 45]}, {'name': '远', 'path': far}])
        self.assertEqual(result['checked'], 1)
        self.assertEqual(result['pairs'], [])
        self.assertEqual(calls, [])                                     # 网格上就隔得远: 没精确算


class Live(unittest.TestCase):
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

    def settle(self):
        """不等 350 毫秒: 排着的那一趟马上算 (测试里内核是同步的)。"""
        if self.sim._live_timer.isActive():
            self.sim._live_timer.stop()
            self.sim._live_start()

    def test_moving_a_part_into_another_shows_a_clash(self):
        self.sim.addPart(self.files.block('底板', bind=True))
        self.sim.addPart(self.files.block('块', z=10, w=10, h=10, bind=True))
        self.assertFalse(self.sim.live['running'])
        self.assertFalse(self.sim._live_timer.isActive())
        self.settle()
        self.assertEqual((self.sim.live['running'], self.sim.live['clashes']), (False, 0))
        self.sim.placePart(1, 'move', 2, '-4')                          # 压进去 4 mm
        self.settle()
        self.assertEqual(self.sim.live['clashes'], 0)
        self.controller.runCheck()
        self.assertEqual(self.sim.live['clashes'], 1)
        self.assertEqual(self.sim.components[1]['clash'], ['底板'])
        labels = self.sim._live_labels()
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0][2], 'clash')
        self.assertIn('底板 ↔ 块', labels[0][0])
        self.sim.placePart(1, 'move', 2, '0')                           # 挪回去: 叉没了
        self.settle()
        self.assertEqual(self.sim.live['clashes'], 0)
        self.assertEqual(self.sim._live_labels(), [])

    def test_turning_live_off_clears_and_check_still_works(self):
        self.sim.addPart(self.files.block('底板', bind=True))
        self.sim.addPart(self.files.block('块', z=6, w=10, h=10, bind=True))
        self.assertFalse(self.sim.live['on'])
        self.assertFalse(self.sim._live_timer.isActive())
        self.controller.runCheck()                                      # 关着也能手动查: 现算一趟
        self.assertIn('clash', [item['code'] for item in self.controller.checkIssues])

    def test_check_reuses_the_live_result(self):
        self.sim.addPart(self.files.block('底板', bind=True))
        self.sim.addPart(self.files.block('块', z=10, w=10, h=10, bind=True))
        self.controller.runCheck()
        asked = []
        real = self.controller.session.query

        def counted(mode, data, done):
            asked.append(mode)
            return real(mode, data, done)
        with patch.object(self.controller.session, 'query', counted):
            self.controller.runCheck()
        self.assertIn('contacts', asked)
        self.assertTrue(self.controller.checkOpen)

    def test_clear_removes_assembly_crosses_and_tree_flags(self):
        self.sim.addPart(self.files.block('底板', bind=True))
        self.sim.addPart(self.files.block('块', z=6, w=10, h=10, bind=True))
        self.controller.runCheck()
        self.assertTrue(self.sim._live_labels())
        self.assertTrue(any(part['clash'] for part in self.sim.components))
        self.controller.clearCheck()
        self.assertFalse(self.sim._live_labels())
        self.assertFalse(any(part['clash'] or part['bad'] for part in self.sim.components))
        self.sim.placePart(1, 'move', 0, '1')
        self.settle()
        self.assertFalse(self.sim.live['running'])
        self.assertFalse(self.sim._live_labels())
        self.assertEqual(self.controller.checkIssues, [])
        self.controller.runCheck()
        self.assertTrue(self.sim._live_labels())

    def test_assembly_isolation_can_exit_without_changing_hidden_parts(self):
        self.sim.addPart(self.files.block('底板', bind=True))
        self.sim.addPart(self.files.block('块', z=10, bind=True))
        self.sim._hidden_parts = {0}
        self.sim.partAction(1, 'isolate')
        self.assertEqual(self.sim.isolatedName, '块')
        self.sim.exitIsolation()
        self.assertEqual(self.sim.isolatedName, '')
        self.assertEqual(self.sim._hidden_parts, {0})


if __name__ == '__main__':
    unittest.main()
