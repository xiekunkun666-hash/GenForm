"""装配体的设计树和视图里点零部件: 名字<n>、选中变蓝、隐藏 / 孤立、右键菜单、射线点中零部件、基准面跟着装配体变大。"""
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from genform.session import Session
from genform.view import picking
from tests.test_assembly_parts import Files


def box(low, high):
    """一个长方体的网格 (12 个三角形), 和装配体送给视图的一项一样。"""
    low, high = np.asarray(low, float), np.asarray(high, float)
    corners = np.array([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])], np.float32)
    tris = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
                     [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]], np.int32)
    return {'verts': corners, 'normals': np.zeros_like(corners), 'tris': tris, 'color': (0.6, 0.6, 0.6),
            'tints': np.full((len(corners), 3), 0.6, np.float32), 'alpha': 1.0, 'low': low, 'high': high}


class FakeViewport:
    def __init__(self):
        self.extras, self.fits, self.click_at = [], 0, (0.0, 0.0)

    def set_extras(self, parts):
        self.extras = list(parts)

    def fit(self):
        self.fits += 1

    def __getattr__(self, name):                # 别的视图方法 (标注、覆盖层…): 这里不关心
        return lambda *args, **kwargs: None


class Tree(unittest.TestCase):
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
        self.view = FakeViewport()
        self.controller.viewport = self.view

    def add_three(self):
        base = self.files.block('底板', bind=True)
        self.sim.addPart(base)
        self.sim.addPart(self.files.block('块', z=10, w=10, h=10))
        self.sim.addPart(base)
        self.sim._shown = [(number, box((0, 0, number * 20), (10, 10, number * 20 + 10))) for number in range(3)]

    def test_labels_count_each_file_and_first_is_fixed(self):
        self.add_three()
        rows = self.sim.components
        self.assertEqual([row['label'] for row in rows], ['底板<1>', '块<1>', '底板<2>'])
        self.assertEqual([row['fixed'] for row in rows], [True, False, False])
        self.assertEqual(rows[0]['kind'], '非标')               # 绑了工艺的普通块
        self.assertEqual(rows[1]['kind'], '')                   # 没绑工艺: 不标

    def test_select_turns_blue_and_carries_pick_numbers(self):
        self.add_three()
        self.sim.selectPart(1)
        self.assertEqual(self.sim.picked, 1)
        self.assertEqual([part['pick'] for part in self.view.extras], [0, 1, 2])
        self.assertGreater(self.view.extras[1]['tints'][0][2], self.view.extras[0]['tints'][0][2])
        self.assertTrue(self.sim.components[1]['selected'])
        self.sim.selectPart(9)                                   # 超出范围 = 不选
        self.assertEqual(self.sim.picked, -1)

    def test_hide_isolate_and_show_all(self):
        self.add_three()
        self.sim.partAction(1, 'hide')
        self.assertEqual([part['pick'] for part in self.view.extras], [0, 2])
        self.assertTrue(self.sim.components[1]['hidden'])
        self.sim.partAction(2, 'isolate')
        self.assertEqual([part['pick'] for part in self.view.extras], [2])
        self.assertIn('show_all', [row['id'] for row in self.sim.partMenu(-1)])
        self.sim.partAction(-1, 'show_all')
        self.assertEqual(len(self.view.extras), 3)
        fits = self.view.fits
        self.sim.partAction(-1, 'fit')
        self.assertEqual(self.view.fits, fits + 1)

    def test_root_shows_and_hides_everything(self):
        self.add_three()
        bar = [row['id'] for row in self.sim.partContext(-1)]
        self.assertEqual(bar[:2], ['show_all', 'hide_all'])
        self.assertIn('hide_all', [row['id'] for row in self.sim.partMenu(-1)])
        self.sim.partAction(-1, 'hide_all')
        self.assertEqual(self.view.extras, [])
        self.assertTrue(all(part['hidden'] for part in self.sim.components))
        self.sim.partAction(-1, 'show_all')
        self.assertEqual(len(self.view.extras), 3)

    def test_hover_describes_component(self):
        self.add_three()
        self.sim._push_parts()
        self.assertEqual([part['label'] for part in self.view.extras], ['底板<1>', '块<1>', '底板<2>'])
        from genform.view.viewer.mouse import MouseMixin
        fake = type('V', (), {'_data': {'extras': self.view.extras}})()
        text = MouseMixin._describe(fake, ('component', 1))
        self.assertTrue(text.startswith('块<1>'))

    def test_hover_describes_part_edge_sizes(self):
        from genform.kernel import assembly
        self.add_three()
        real = assembly.meshes([], None, {'parts': [{'path': self.sim._parts[1]['path'], 'move': [0, 0, 5]}]})[0]
        self.sim._shown[1] = (1, real)
        self.sim._push_parts()
        part = self.view.extras[1]
        self.assertGreater(len(part['segments']), 0)            # 零件的边线跟着网格一起来, 装配体里能按显示样式画
        self.assertEqual(len(part['segment_edge']), len(part['segments']))
        from genform.view.viewer.mouse import MouseMixin, _edge_text
        fake = type('V', (), {'_data': {'extras': self.view.extras}})()
        line = int(np.flatnonzero(part['edge_kind'] == 0)[0])
        text = MouseMixin._describe(fake, ('part_edge', (1, line)))
        self.assertTrue(text.startswith('块<1>') and '直边，长' in text)
        circle = _edge_text({'type': 'circle', 'length': 2 * np.pi * 5, 'radius': 5.0})
        self.assertIn('直径 10 mm', circle)
        self.assertIn('周长 31.42 mm', circle)
        self.assertIn('弧长', _edge_text({'type': 'circle', 'length': np.pi * 5, 'radius': 5.0}))

    def test_orbit_turns_about_the_assembly_not_the_screen_centre(self):
        from genform.view.camera import Camera
        from genform.view.viewer.mouse import MouseMixin
        self.add_three()
        self.sim._push_parts()
        camera = Camera()
        camera.target = np.array([300.0, 0.0, 0.0])             # 画面中心离装配体很远
        fake = type('V', (), {'_camera': camera, '_data': {'extras': self.view.extras}, '_model': {}, '_display': {'body': True},
                              'width': lambda self: 800, 'height': lambda self: 600})()
        centre = MouseMixin._orbit_pivot(fake, 0, 0)            # 指着空白: 绕整个装配体的中心
        low = np.min([part['low'] for part in self.view.extras], axis=0)
        high = np.max([part['high'] for part in self.view.extras], axis=0)
        np.testing.assert_allclose(centre, (low + high) / 2)
        camera.target = np.array([5.0, 5.0, 25.0])
        screen, _ = camera.project(np.array([[5.0, 5.0, 25.0]]), 800, 600)
        hit = MouseMixin._orbit_pivot(fake, float(screen[0, 0]), float(screen[0, 1]))     # 指着零部件也一样: 场景在原地转
        np.testing.assert_allclose(hit, (low + high) / 2)

    def test_drag_direction_is_fixed_for_one_drag(self):
        from genform.view.camera import Camera
        camera = Camera()
        camera.yaw, camera.pitch = 0.0, 80.0
        camera.orbit(0, 30, None, flip=False)                   # 拖过头顶 (pitch 110°): 这次拖动左右还是原来的方向
        before = camera.yaw
        camera.orbit(10, 0, None, flip=False)
        self.assertAlmostEqual(camera.yaw - before, 4.0)

    def test_menu_and_edit_request(self):
        self.add_three()
        ids = [row['id'] for row in self.sim.partMenu(1)]
        for wanted in ('open', 'edit', 'mirror', 'hide', 'isolate', 'up', 'down', 'delete'):
            self.assertIn(wanted, ids)
        asked = []
        self.sim.editRequested.connect(asked.append)
        self.sim.partAction(2, 'edit')
        self.assertEqual((asked, self.sim.picked), ([2], 2))

    def test_view_click_selects_component(self):
        self.add_three()
        self.controller._on_picked('component', 2, False)
        self.assertEqual(self.sim.picked, 2)
        self.controller._on_picked('face', 5, False)            # 装配体里点了别的 = 不选
        self.assertEqual(self.sim.picked, -1)

    def test_drop_files(self):
        from PySide6.QtCore import QUrl
        part = self.files.block('拖进来的')
        self.controller.dropFiles([QUrl.fromLocalFile(part)])         # 装配体里拖零件: 插入
        self.assertEqual([item['path'] for item in self.sim._parts][-1], part)
        where = os.path.join(self.files.folder.name, 'a.gasm')
        self.sim.saveAssembly(where)
        self.sim._parts = []
        self.controller.dropFiles([QUrl.fromLocalFile(part), QUrl.fromLocalFile(where)])   # 有装配体: 打开它
        self.assertEqual(self.controller.docKind, 'assembly')
        self.assertEqual(len(self.sim._parts), 1)
        notices = []
        self.controller.notice.connect(notices.append)
        self.controller._set_kind('part')
        self.controller.viewport = None                                # 换文档要整套视图, 这里只看换成了什么
        step = os.path.join(self.files.folder.name, 'x.step')
        open(step, 'w').close()
        self.controller.dropFiles([QUrl.fromLocalFile(step)])         # 零件里拖 STEP: 开一个导入它的新零件
        self.assertEqual(self.controller.docKind, 'part')
        self.assertTrue(any('正在导入' in text for text in notices))
        features = self.controller.session.document.features
        self.assertEqual([(feature['type'], feature['params']['path']) for feature in features], [('import_step', step)])

    def test_click_component_pops_context_bar(self):
        self.add_three()
        self.controller.viewport.click_at = (100.0, 80.0)
        popped = []
        self.controller.contextRequested.connect(lambda x, y: popped.append((x, y)))
        self.controller._on_picked('component', 1, False)
        self.assertEqual(popped[-1], (100.0, 80.0))
        self.assertEqual(self.controller.sceneTarget, 'part:1')
        ids = [row['id'] for row in self.controller.sceneContext]
        self.assertEqual(ids[:2], ['open', 'edit'])
        self.assertIn('zoom', ids)
        self.controller.contextAction('part:1', 'hide')
        self.assertTrue(self.sim.components[1]['hidden'])
        self.assertEqual(popped[-1], (-1.0, -1.0))                     # 点了按钮: 小工具条收起来
        self.controller._on_picked('face', 0, False)
        self.assertEqual(self.controller.sceneContext, [])

    def test_open_part_then_back_to_assembly(self):
        self.add_three()
        where = os.path.join(self.files.folder.name, 'car.gasm')
        self.sim.saveAssembly(where)
        self.controller.viewport = None                                # 换文档要整套视图, 这里只看切换
        self.sim.openPart(1)
        self.assertEqual(self.controller.docKind, 'part')
        self.assertEqual(self.controller.returnAssembly, 'car')
        self.controller.backToAssembly()
        self.assertEqual(self.controller.docKind, 'assembly')
        self.assertEqual(self.controller.returnAssembly, '')
        self.assertEqual(len(self.sim._parts), 3)
        self.controller.backToPart()                                   # 回到零件也能再回来
        self.assertEqual(self.controller.returnAssembly, 'car')
        self.controller.newOf('part')
        self.assertEqual(self.controller.returnAssembly, '')

    def test_loading_progress_shows_on_the_card(self):
        session = self.controller.session
        session._on_query_progress(3, 44, '车身 · 外形放样')
        progress = self.controller.progress
        self.assertTrue(progress['loading'])
        self.assertEqual((progress['done'], progress['total'], progress['name']), (3, 44, '车身 · 外形放样'))
        session.query('meshes', {'parts': []}, lambda result, error: None)   # 查询算完: 加载条收起来
        self.assertFalse(self.controller.progress['loading'])


class Loading(unittest.TestCase):
    def test_meshes_report_each_part(self):
        from genform.kernel import assembly
        from genform.kernel.model import rebuild as steps
        files = Files(self)
        first, second = files.block('甲'), files.block('乙', z=10)
        assembly._FILES.clear()                                         # 不用内存里算好的: 要它真重算一遍
        steps._STEPS.clear(), steps._SPARE.clear()
        calls = []
        steps.on_step = lambda *args: calls.append(args)
        try:
            assembly.meshes([], None, {'parts': [{'path': first, 'name': '甲'}, {'path': second, 'name': '乙'}]})
        finally:
            steps.on_step = None
        marked = [call for call in calls if call[-1] == 'parts']
        self.assertEqual(len(marked), len(calls))                       # 零件文件里的特征进度也换成了 "第几个零件"
        self.assertEqual([call[:2] for call in marked if '·' not in call[2]], [(0, 2), (1, 2)])
        self.assertTrue(any(call[2].startswith('乙 · ') for call in marked))


class Picking(unittest.TestCase):
    def test_ray_hits_nearest_component(self):
        extras = [dict(box((0, 0, 0), (10, 10, 10)), pick=0), dict(box((0, 0, 30), (10, 10, 40)), pick=1), box((0, 0, 60), (10, 10, 70))]
        origin, down = np.array([5.0, 5.0, 100.0]), np.array([0.0, 0.0, -1.0])
        number, distance = picking.pick_extras(origin, down, extras)
        self.assertEqual(number, 1)                              # 最上面那个没 'pick', 点不着
        self.assertAlmostEqual(distance, 60.0, places=4)
        self.assertEqual(picking.pick_extras(np.array([50.0, 50.0, 100.0]), down, extras)[0], None)

    def test_ray_hits_part_moved_by_matrix(self):
        part = dict(box((0, 0, 0), (10, 10, 10)), pick=0)
        part['matrix'] = np.eye(4, dtype=np.float32)
        part['matrix'][:3, 3] = (50, 0, 0)                      # 动着的件: 网格没变, 摆放矩阵挪到 x 50
        part['low'], part['high'] = (50, 0, 0), (60, 10, 10)
        down = np.array([0.0, 0.0, -1.0])
        self.assertEqual(picking.pick_extras(np.array([55.0, 5.0, 100.0]), down, [part])[0], 0)
        self.assertIsNone(picking.pick_extras(np.array([5.0, 5.0, 100.0]), down, [part])[0])

    def test_ray_box(self):
        self.assertAlmostEqual(picking.ray_box(np.zeros(3), np.array([1.0, 0, 0]), (5, -1, -1), (6, 1, 1)), 5.0)
        self.assertEqual(picking.ray_box(np.zeros(3), np.array([-1.0, 0, 0]), (5, -1, -1), (6, 1, 1)), np.inf)


class Planes(unittest.TestCase):
    def test_planes_fold_and_grow_with_assembly(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        from genform.view.viewer.viewport import Viewport
        from genform.view.viewer.display import PLANE_MIN_HALF
        viewport = Viewport()
        viewport.planesVisible = True
        viewport.set_extras([dict(box((0, -900, 0), (4500, 900, 1300)), pick=0)])
        self.assertFalse(viewport.planesVisible)                 # 零部件一出来, 基准面就收起来
        self.assertAlmostEqual(viewport.plane_half(), 4500 * 1.25)
        viewport.set_extras([])
        self.assertEqual(viewport.plane_half(), PLANE_MIN_HALF)


if __name__ == '__main__':
    unittest.main()
