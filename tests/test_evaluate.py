"""评估和仿真: 测量、静力估算、风阻、装配体的干涉和装配顺序、参数面板的预览、界面语言 (不开窗口)。"""
import json
import math
import os
import tempfile
import unittest

from genform import i18n
from genform.session import Session
from tests.test_features import Part


def ask(session, mode, data):
    replies = []
    session.query(mode, data, lambda result, error: replies.append((result, error)))
    return replies[0]


def face(session, axis, sign, at=None):
    """法向沿 axis (0/1/2) 的 sign 方向的平面 (at: 它在这根轴上的坐标) → 面的 id。"""
    for item in session.model['faces']:
        normal = item.get('normal')
        if normal is not None and normal[axis] * sign > 0.99 and (at is None or abs(item['center'][axis] - at) < 1e-6):
            return item['id']
    raise AssertionError('没有这样的面')


class MeasureTest(unittest.TestCase):
    def setUp(self):
        self.part = Part(self)
        self.part.box(40, 30, 10)

    def test_two_parallel_faces(self):
        session = self.part.session
        result, error = ask(session, 'measure', [{'kind': 'face', 'id': face(session, 0, -1)}, {'kind': 'face', 'id': face(session, 0, 1)}])
        self.assertIsNone(error)
        self.assertAlmostEqual(result['distance'], 40.0, places=6)
        self.assertAlmostEqual(result['angle'] % 180.0, 0.0, places=6)

    def test_two_vertices(self):
        session = self.part.session
        corners = [list(map(float, corner)) for corner in session.model['vertices']]
        far = max(range(len(corners)), key=lambda index: math.dist(corners[index], corners[0]))
        result, _ = ask(session, 'measure', [{'kind': 'vertex', 'id': 0}, {'kind': 'vertex', 'id': far}])
        self.assertAlmostEqual(result['distance'], math.sqrt(40 ** 2 + 30 ** 2 + 10 ** 2), places=6)


class StaticTest(unittest.TestCase):
    def test_cantilever_close_to_beam_theory(self):
        part = Part(self)
        part.box(100, 10, 10)               # 梁沿 X: 左端固定, 右端往下压 100 N
        session = part.session
        result, error = ask(session, 'static', {'fixed': [face(session, 0, -1)], 'loaded': [face(session, 0, 1)], 'force': [0, 0, -100],
                                                'young': 210000, 'poisson': 0.3, 'yield': 235, 'quality': 'medium'})
        self.assertIsNone(error)
        inertia = 10 * 10 ** 3 / 12
        self.assertAlmostEqual(result['max_displacement'], 100 * 100 ** 3 / (3 * 210000 * inertia), delta=0.06)     # 理论 0.19
        self.assertAlmostEqual(result['max_stress'], 100 * 100 * 5 / inertia, delta=15)                             # 理论 60
        self.assertEqual(len(result['mesh']['stress']), len(result['mesh']['verts']))
        self.assertGreater(result['safety'], 2.5)

    def test_needs_fixed_and_loaded_faces(self):
        part = Part(self)
        part.box()
        result, error = ask(part.session, 'static', {'fixed': [], 'loaded': [0], 'force': [0, 0, -1], 'young': 1000})
        self.assertIsNone(result)
        self.assertIn('固定', error)


class DragTest(unittest.TestCase):
    def test_frontal_area_and_force(self):
        part = Part(self)
        part.box(40, 30, 10)
        result, error = ask(part.session, 'drag', {'direction': [0, 1, 0], 'speed': 20, 'density': 1.2, 'cd': 1.0})
        self.assertIsNone(error)
        self.assertAlmostEqual(result['area'], 400.0, delta=6)          # 沿 Y 看过去: 40 × 10
        self.assertAlmostEqual(result['force'], 0.5 * 1.2 * 400 * result['area'] * 1e-6, delta=1e-6)


class AssemblyTest(unittest.TestCase):
    """底座: 40×40×10 的板, 中间一个 Φ10 的通孔。销: Φ10 × 30 的圆柱, 插在孔里。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        pin = Part(self)
        pin.do('extrude', sketch=pin.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}), distance=30)
        self.pin = os.path.join(self.folder.name, 'pin.gform')
        pin.session.document.save(self.pin)
        self.base = Part(self)
        self.base.box(40, 40, 10)
        self.base.do('hole', sketch=self.base.sketch({'type': 'point', 'x': 0, 'y': 0}, offset=10), diameter=10)

    def tearDown(self):
        self.folder.cleanup()

    def parts(self, **place):
        return {'parts': [{'name': '底座'}, dict({'name': '销', 'path': self.pin}, **place)]}

    def test_pin_in_hole_does_not_clash(self):
        result, error = ask(self.base.session, 'interference', self.parts())
        self.assertIsNone(error)
        self.assertEqual(result['clashes'], [])

    def test_shifted_pin_clashes(self):
        result, _ = ask(self.base.session, 'interference', self.parts(move=[12, 0, 0]))
        self.assertEqual(len(result['clashes']), 1)
        self.assertGreater(result['clashes'][0]['volume'], 100)

    def test_pin_goes_in_only_along_the_hole(self):
        result, _ = ask(self.base.session, 'sequence', self.parts())
        step = result['steps'][1]
        self.assertTrue(result['ok'])
        self.assertEqual(sorted(step['directions']), ['+Z', '-Z'])
        self.assertEqual(set(step['blocked'].values()), {'底座'})

    def save(self, part, name):
        path = os.path.join(self.folder.name, name)
        part.session.document.save(path)
        return path

    def test_sequence_finds_its_own_order(self):
        # 带头的销只能从上面插 (头卡在底座上面); 列表里盖板排在销前面, 照列表装不进去, 要自己找出 底座 → 销 → 盖板
        pin = Part(self)
        pin.do('extrude', sketch=pin.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}), distance=10)
        pin.do('extrude', sketch=pin.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 8}, offset=10), distance=2)
        cover = Part(self)
        cover.box(40, 40, 5)
        data = {'parts': [{'name': '底座'}, {'name': '盖板', 'path': self.save(cover, 'cover.gform'), 'move': [0, 0, 12]},
                          {'name': '带头销', 'path': self.save(pin, 'headed.gform')}]}
        result, error = ask(self.base.session, 'sequence', data)
        self.assertIsNone(error)
        self.assertTrue(result['ok'])
        self.assertEqual([step['name'] for step in result['steps']], ['底座', '带头销', '盖板'])
        pin_step = next(step for step in result['steps'] if step['name'] == '带头销')
        self.assertEqual(pin_step['directions'], ['+Z'])

    def test_rivet_with_two_heads_cannot_go_in(self):
        rivet = Part(self)
        rivet.do('extrude', sketch=rivet.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}, offset=-2), distance=14)
        rivet.do('extrude', sketch=rivet.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 8}, offset=10), distance=2)
        rivet.do('extrude', sketch=rivet.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 8}, offset=-2), distance=2)
        data = {'parts': [{'name': '底座'}, {'name': '铆钉', 'path': self.save(rivet, 'rivet.gform')}]}
        result, _ = ask(self.base.session, 'sequence', data)
        self.assertFalse(result['ok'])
        self.assertEqual(result['stuck'], [1])
        step = next(step for step in result['steps'] if step['index'] == 1)
        self.assertFalse(step['ok'])
        self.assertEqual(set(step['blocked'].values()), {'底座'})


class PreviewTest(unittest.TestCase):
    def test_preview_shows_result_without_touching_document(self):
        part = Part(self)
        part.box(40, 30, 10)
        sketch = part.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}, offset=10)
        before = json.dumps(part.session.document.to_data(), sort_keys=True)
        replies = []
        part.session.preview('extrude', {'sketch': sketch, 'distance': 20}, lambda result, error: replies.append((result, error)))
        result, error = replies[0]
        self.assertIsNone(error)
        self.assertEqual(result['errors'], [])
        self.assertAlmostEqual(result['high'][2], 30.0, places=6)
        self.assertEqual(json.dumps(part.session.document.to_data(), sort_keys=True), before)

    def test_preview_reports_bad_parameters(self):
        part = Part(self)
        part.box()
        replies = []
        part.session.preview('extrude', {'sketch': 'nope', 'distance': 5}, lambda result, error: replies.append((result, error)))
        self.assertIsNone(replies[0][0])
        self.assertTrue(replies[0][1])


class ScrewTest(unittest.TestCase):
    def test_cap_screw_size(self):
        part = Part(self)
        part.do('screw', sketch=part.sketch({'type': 'point', 'x': 0, 'y': 0}), size='M4', head='cap', length=12)
        props = part.session.model['props']
        self.assertEqual([round(value, 3) for value in props['size']], [7.0, 7.0, 16.0])       # 头 Φ7 高 4 + 杆 12
        shank, head = math.pi * 2 ** 2 * 12, math.pi * 3.5 ** 2 * 4
        self.assertLess(props['volume'], shank + head)
        self.assertGreater(props['volume'], (shank + head) * 0.9)

    def test_countersunk_head_is_flush(self):
        part = Part(self)
        part.do('screw', sketch=part.sketch({'type': 'point', 'x': 0, 'y': 0}), size='M3', head='flat', length=10)
        props = part.session.model['props']
        self.assertAlmostEqual(props['bbox_max'][2], 0.0, places=6)
        self.assertAlmostEqual(props['bbox_min'][2], -10.0, places=6)

    def test_tapped_hole_uses_tap_drill(self):
        part = Part(self)
        part.box(40, 30, 10)
        part.do('hole', sketch=part.sketch({'type': 'point', 'x': 0, 'y': 0}, offset=10), kind='tapped', size='M4')
        self.assertAlmostEqual(part.volume, 12000 - math.pi * 1.65 ** 2 * 10, delta=1e-3)


class LanguageTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language('zh')

    def test_switching(self):
        self.assertEqual(i18n.tr('静力分析'), '静力分析')
        i18n.set_language('en')
        self.assertEqual(i18n.tr('静力分析'), 'Static Analysis')
        self.assertEqual(i18n.tr('abc'), 'abc')
        self.assertEqual(i18n.localize({'id': '测量', 'title': '测量'}), {'id': '测量', 'title': 'Measure'})

    def test_user_values_are_left_alone(self):
        i18n.set_language('en')
        row = i18n.localize({'key': 'name', 'type': 'text', 'label': '长度', 'value': '长度'})
        self.assertEqual(row['value'], '长度')
        self.assertNotEqual(row['label'], '长度')


if __name__ == '__main__':
    unittest.main()


class IncrementalRebuildTest(unittest.TestCase):
    """内核接着上一次算 (只重算变了的那个特征和它后面的): 结果要和从头算的一样。"""

    def test_edit_in_the_middle_matches_a_fresh_rebuild(self):
        from genform.kernel import build
        part = Part(self)
        part.box(40, 30, 10)
        boss = part.do('extrude', sketch=part.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 6}, offset=10), distance=8)
        part.do('hole', sketch=part.sketch({'type': 'point', 'x': 12, 'y': 0}, offset=10), diameter=4)
        part.do('edit_feature', id=boss, params={'distance': 15})
        kept = part.volume
        self.assertAlmostEqual(kept, 12000 + math.pi * 36 * 15 - math.pi * 4 * 10, delta=1e-3)
        build._STEPS.clear()                # 忘掉记着的, 从头算一遍
        fresh = build.build_model(part.session.document.features, part.session.document.upto)
        self.assertAlmostEqual(fresh['props']['volume'], kept, places=6)

    def test_suppress_and_rollback_are_not_served_stale(self):
        part = Part(self)
        part.box(40, 30, 10)
        boss = part.do('extrude', sketch=part.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 6}, offset=10), distance=8)
        full = part.volume
        part.do('suppress_feature', id=boss, suppressed=True)
        self.assertAlmostEqual(part.volume, 12000, delta=1e-3)
        part.do('suppress_feature', id=boss, suppressed=False)
        self.assertAlmostEqual(part.volume, full, delta=1e-6)
        part.do('rollback', count=2)
        self.assertAlmostEqual(part.volume, 12000, delta=1e-3)
        part.do('rollback')
        self.assertAlmostEqual(part.volume, full, delta=1e-6)


class BatchTest(unittest.TestCase):
    def test_steps_refer_to_earlier_results(self):
        part = Part(self)
        reply = part.run('batch', steps=[
            {'cmd': 'sketch', 'args': {'plane': 'XY', 'shapes': [{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 40, 'h': 30}]}, 'as': 'base'},
            {'cmd': 'extrude', 'args': {'sketch': '$base', 'distance': 10}},
            {'cmd': 'sketch', 'args': {'plane': 'XY', 'offset': 10, 'shapes': [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}]}},
            {'cmd': 'extrude', 'args': {'sketch': '$3', 'distance': -4, 'op': 'cut'}}])
        self.assertTrue(reply['ok'], reply.get('error'))
        self.assertEqual(reply['count'], 4)
        self.assertAlmostEqual(part.volume, 12000 - math.pi * 25 * 4, delta=1e-3)

    def test_a_bad_step_leaves_the_document_alone(self):
        part = Part(self)
        part.box()
        before = json.dumps(part.session.document.features, sort_keys=True)
        reply = part.run('batch', steps=[
            {'cmd': 'sketch', 'args': {'plane': 'XY', 'shapes': [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}]}},
            {'cmd': 'extrude', 'args': {'sketch': '$9', 'distance': 4}}])
        self.assertFalse(reply['ok'])
        self.assertIn('第 2 步', reply['error'])
        self.assertEqual(json.dumps(part.session.document.features, sort_keys=True), before)


class PreviewKeepsCacheTest(unittest.TestCase):
    def test_preview_does_not_throw_away_document_steps(self):
        from genform.kernel import build
        from genform.kernel.model import rebuild as steps     # 进度回调设在这里 (build 只是门面)
        part = Part(self)
        first = part.box(40, 30, 10)
        for index in range(3):
            part.do('extrude', sketch=part.sketch({'type': 'circle', 'cx': -12 + 12 * index, 'cy': 0, 'r': 3}, offset=10), distance=5)
        features = part.session.document.to_data()['features']
        build.rebuild(features)
        changed = json.loads(json.dumps(features))
        next(item for item in changed if item['id'] == first)['params']['distance'] = 12     # 预览: 改第一个特征
        build.preview(changed, None)
        made = []
        steps.on_step = lambda index, total, name: made.append(index)
        try:
            build.rebuild(features)                 # 放弃预览回到文档: 一个特征都不用重算
            self.assertEqual(made, [])
            build.rebuild(changed)                  # 或者点了确定: 预览算过的也还在
            self.assertEqual(made, [])
            next(item for item in features if item['id'] == first)['name'] = '底座'
            build.rebuild(features)                 # 改名不改几何: 也不重算
            self.assertEqual(made, [])
        finally:
            steps.on_step = None
