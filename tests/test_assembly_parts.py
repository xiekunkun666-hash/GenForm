# -*- coding: utf-8 -*-
"""装配体: 镜像摆放、同一个文件只算一次、零件自己的颜色 / 半透明、件与件贴着 / 干涉 / 间隙太小 / 悬空、物料清单、
手动指定工艺的价钱, 和界面这一层 (镜像按钮、存取 .gasm、装配体的设计检查进底部日志)。"""
import csv
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from genform import bom
from genform.kernel import assembly, build
from genform.session import Session
from tests.test_features import Part


def ask(session, mode, data):
    replies = []
    session.query(mode, data, lambda result, error: replies.append((result, error)))
    return replies[0]


class Files:
    """临时目录里存几个零件文件。"""

    def __init__(self, case):
        self.case = case
        self.folder = tempfile.TemporaryDirectory()
        case.addCleanup(self.folder.cleanup)

    def block(self, name, cx=0.0, cy=0.0, z=0.0, w=40.0, h=40.0, d=10.0, color=None, opacity=None, name_feature=None, bind=False):
        part = Part(self.case)
        sketch = part.sketch({'type': 'rect', 'cx': cx, 'cy': cy, 'w': w, 'h': h}, offset=z)
        replies = []
        part.session.execute('extrude', {'sketch': sketch, 'distance': d, 'name': name_feature or name}, replies.append)
        self.case.assertTrue(replies[0]['ok'], replies[0].get('error'))
        feature = replies[0]['id']
        if color:
            part.do('set_appearance', color=color)
        if opacity:
            part.do('set_appearance', features=[feature], color='#2A3A48', opacity=opacity)
        if bind:
            self.case.assertTrue(part.run('bind_processes')['ok'])
        path = os.path.join(self.folder.name, f'{name}.gform')
        part.session.document.save(path)
        return path


class Placement(unittest.TestCase):
    def setUp(self):
        self.files = Files(self)
        self.session = Session()

    def test_mirror_flips_y_before_moving(self):
        path = self.files.block('左件', cy=15, w=10, h=10)        # y 10 … 20
        result, error = ask(self.session, 'meshes', {'parts': [{'path': path, 'mirror': True, 'move': [100, 0, 0]}]})
        self.assertIsNone(error)
        mesh = result[0]
        self.assertAlmostEqual(mesh['low'][1], -20, places=3)
        self.assertAlmostEqual(mesh['high'][1], -10, places=3)
        self.assertAlmostEqual(mesh['low'][0], 95, places=3)

    def test_same_file_is_built_and_meshed_once(self):
        path = self.files.block('螺栓', w=5, h=5)
        with patch.object(build, 'tessellate', wraps=build.tessellate) as meshed:
            result, error = ask(self.session, 'meshes', {'parts': [{'path': path, 'move': [x, 0, 0]} for x in (0, 10, 20, 30)]})
        self.assertIsNone(error)
        self.assertEqual(len(result), 4)
        self.assertEqual(meshed.call_count, 1)
        self.assertAlmostEqual(result[3]['low'][0] - result[0]['low'][0], 30, places=3)

    def test_other_files_do_not_wipe_the_open_documents_steps(self):
        path = self.files.block('别的', cx=100)
        part = Part(self)
        part.box()                                  # 现在打开的文档: 重算记着它的中间步
        before = [step[0] for step in build._STEPS]
        ask(part.session, 'meshes', {'parts': [{'path': path}]})
        self.assertEqual([step[0] for step in build._STEPS], before)

    def test_part_colors_and_glass_come_from_the_file(self):
        red = self.files.block('红', color='#FF0000')
        glass = self.files.block('玻璃', opacity=0.3)
        result, _ = ask(self.session, 'meshes', {'parts': [{'path': red}, {'path': glass, 'move': [0, 0, 50]}]})
        self.assertTrue(np.allclose(result[0]['tints'], [1.0, 0.0, 0.0]))
        self.assertEqual(result[0]['alpha'], 1.0)
        self.assertAlmostEqual(result[1]['alpha'], 0.3)

    def test_mirrored_triangles_keep_facing_out(self):
        path = self.files.block('块', cy=30)
        plain, _ = ask(self.session, 'meshes', {'parts': [{'path': path}]})
        flipped, _ = ask(self.session, 'meshes', {'parts': [{'path': path, 'mirror': True}]})
        a, b = plain[0], flipped[0]
        tri = a['tris'][0]
        normal_a = np.cross(a['verts'][tri[1]] - a['verts'][tri[0]], a['verts'][tri[2]] - a['verts'][tri[0]])
        tri = b['tris'][0]
        normal_b = np.cross(b['verts'][tri[1]] - b['verts'][tri[0]], b['verts'][tri[2]] - b['verts'][tri[0]])
        self.assertGreater(float(np.dot(normal_a, a['normals'][a['tris'][0][0]])), 0)       # 绕向和法向一致
        self.assertGreater(float(np.dot(normal_b, b['normals'][b['tris'][0][0]])), 0)


class Contacts(unittest.TestCase):
    """底板 40×40×10 (z 0 … 10); 别的块放在它上面、压进去、隔一点、悬空。"""

    def setUp(self):
        self.files = Files(self)
        self.session = Session()
        self.base = self.files.block('底板')

    def check(self, *others):
        parts = [{'name': '底板', 'path': self.base}] + [{'name': name, 'path': path} for name, path in others]
        result, error = ask(self.session, 'contacts', {'parts': parts, 'rules': {'tolerance': 0.1, 'clearance': 0.5}})
        self.assertIsNone(error)
        return result

    def test_block_sitting_on_the_base_touches(self):
        result = self.check(('上面的块', self.files.block('上面的块', z=10, w=10, h=10)))
        self.assertEqual([pair['kind'] for pair in result['pairs']], ['touch'])
        self.assertEqual(result['floating'], [])

    def test_pressed_in_block_clashes(self):
        result = self.check(('压进去的', self.files.block('压进去的', z=5, w=10, h=10)))
        self.assertEqual(result['pairs'][0]['kind'], 'clash')
        self.assertAlmostEqual(result['pairs'][0]['volume'], 500, delta=1)

    def test_close_but_not_touching_is_a_gap(self):
        result = self.check(('隔一点的', self.files.block('隔一点的', z=10.3, w=10, h=10)))
        self.assertEqual(result['pairs'][0]['kind'], 'gap')
        self.assertAlmostEqual(result['pairs'][0]['distance'], 0.3, places=3)
        self.assertEqual(result['floating'], [1])                       # 没贴上 = 没装在底板上

    def test_floating_through_a_chain(self):
        lower = self.files.block('中间', z=10, w=10, h=10)
        upper = self.files.block('顶上', z=20, w=4, h=4)              # 放在 "中间" 上: 也算装上了
        lost = self.files.block('飘着的', z=60, w=4, h=4)
        result = self.check(('中间', lower), ('顶上', upper), ('飘着的', lost))
        self.assertEqual(result['floating'], [3])

    def test_pin_fitted_in_its_hole_touches(self):
        """销和孔一样粗 (孔是用销的形状切的): 面贴面, 算贴着, 不算干涉。"""
        plate = Part(self)
        plate.box(40, 40, 10)
        plate.do('extrude', sketch=plate.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}, offset=10), distance=10, reverse=True, op='cut')
        path = os.path.join(self.files.folder.name, '带孔的板.gform')
        plate.session.document.save(path)
        pin = Part(self)
        pin.do('extrude', sketch=pin.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}, offset=-5), distance=30)
        pin_path = os.path.join(self.files.folder.name, '销.gform')
        pin.session.document.save(pin_path)
        result, _ = ask(self.session, 'contacts', {'parts': [{'name': '板', 'path': path}, {'name': '销', 'path': pin_path}]})
        self.assertEqual([pair['kind'] for pair in result['pairs']], ['touch'])

    def test_distance_falls_back_to_nearby_faces(self):
        """整个实体求距离失败时 (OCC 对大的空心件会报 NotDone): 一张张面算。"""
        upper = self.files.block('上面的块', z=10, w=10, h=10)
        real = assembly._measure
        calls = []

        def picky(first, second):
            calls.append(first.ShapeType())
            if first.ShapeType() != 4:          # 4 = 面: 只有一张张面才算得出来
                raise RuntimeError('NotDone')
            return real(first, second)
        with patch.object(assembly, '_measure', picky):
            result = self.check(('上面的块', upper))
        self.assertEqual([pair['kind'] for pair in result['pairs']], ['touch'])
        self.assertIn(4, calls)


class Bill(unittest.TestCase):
    def setUp(self):
        self.files = Files(self)

    def test_standard_purchase_and_custom_parts(self):
        bolt = self.files.block('螺栓', w=10, h=10, d=20, name_feature='螺栓', bind=True)
        plate = self.files.block('支架', w=80, h=40, d=3, bind=True)
        part = Part(self)
        feature = part.box()
        self.assertTrue(part.run('set_process', feature=feature, process='purchase', cost=1200, spec='电机')['ok'])
        motor = os.path.join(self.files.folder.name, '电机.gform')
        part.session.document.save(motor)
        rows = bom.bill([{'path': bolt}] * 4 + [{'path': plate}, {'path': plate, 'mirror': True}, {'path': motor}])
        kinds = {row['name']: (row['kind'], row['count']) for row in rows}
        self.assertEqual(kinds['螺栓'], ('standard', 4))
        self.assertEqual(kinds['支架'], ('custom', 1))
        self.assertEqual(kinds['支架（镜像件）'], ('custom', 1))           # 相反方位的件: 另一个料号
        self.assertEqual(kinds['电机'], ('purchase', 1))
        motor_row = next(row for row in rows if row['name'] == '电机')
        self.assertEqual(motor_row['unit'], 1200)
        self.assertEqual(motor_row['spec'], '电机')
        totals = bom.totals(rows)
        self.assertEqual(totals['standard']['count'], 4)
        self.assertEqual(totals['all']['types'], 4)
        path = os.path.join(self.files.folder.name, 'bom.csv')
        bom.write_csv(rows, path)
        with open(path, encoding='utf-8-sig') as handle:
            table = list(csv.reader(handle))
        self.assertEqual(table[0][1], '名称')
        self.assertEqual(len(table), 1 + len(rows))

    def test_unbound_part_is_reported(self):
        rows = bom.bill([{'path': self.files.block('没绑的')}])
        self.assertFalse(rows[0]['bound'])
        self.assertEqual(bom.totals(rows)['unbound'], 1)

    def test_set_process_price_must_not_be_negative(self):
        part = Part(self)
        feature = part.box()
        reply = part.run('set_process', feature=feature, process='purchase', cost=-1)
        self.assertFalse(reply['ok'])


class AssemblyScreen(unittest.TestCase):
    """界面这一层: 镜像按钮、.gasm 存取带 mirror、装配体的设计检查进底部日志 (条目指着零件)。"""

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

    def test_mirror_is_saved_and_read_back(self):
        path = self.files.block('左件', cy=30)
        self.sim.addPart(path)
        self.sim.addPart(path)
        self.sim.mirrorPart(1)
        self.assertTrue(self.sim.state['parts'][1]['mirror'])
        where = os.path.join(self.files.folder.name, 'a.gasm')
        self.sim.saveAssembly(where)
        with open(where, encoding='utf-8') as handle:
            rows = json.load(handle)['parts']
        self.assertNotIn('mirror', rows[0])
        self.assertTrue(rows[1]['mirror'])
        self.sim._parts = []
        self.assertTrue(self.sim.openAssembly(where))
        self.assertEqual([part['mirror'] for part in self.sim._parts], [False, True])

    def test_check_lists_floating_part_and_bill(self):
        base = self.files.block('底板', bind=True)
        self.sim.addPart(base)
        self.sim.addPart(self.files.block('上面的块', z=10, w=10, h=10, bind=True))
        self.sim.addPart(self.files.block('飘着的', z=60, w=4, h=4, bind=True))
        self.controller.runCheck()
        self.assertTrue(self.controller.checkOpen)
        issues = self.controller.checkIssues
        floating = [item for item in issues if item['code'] == 'floating']
        self.assertEqual(len(floating), 1)
        self.assertEqual(floating[0]['features'], ['part:2'])
        self.assertEqual(floating[0]['names'], ['飘着的'])
        self.assertIn(2, self.sim._red)                                # 视图里标红
        self.assertTrue(any(item['code'].startswith('bom_') for item in issues))
        self.controller.closeCheck()
        self.assertEqual(self.sim._red, set())


if __name__ == '__main__':
    unittest.main()
