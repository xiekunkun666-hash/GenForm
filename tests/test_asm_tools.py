"""装配体的工具: 螺丝 ↔ 螺纹孔配对 (拧入长度、顶底、螺纹相位)、尺寸链 / 高度分配 (不开窗口)。"""
import json
import os
import tempfile
import unittest

from genform.kernel import stack
from tests.test_evaluate import ask
from tests.test_features import Part


class FastenerTest(unittest.TestCase):
    """底板 30×30×10 (铝), 顶面中间一个 M3 螺纹孔 (真实牙, 深 8 → 孔底 z2); 一颗 M3 圆柱头螺丝 (真实牙) 从上面拧进去。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.base = Part(self)
        self.base.box(30, 30, 10)
        self.base.do('hole', sketch=self.base.sketch({'type': 'point', 'x': 0, 'y': 0}, offset=10), kind='tapped', size='M3',
                     diameter=2.5, through=False, depth=8.0, thread=True, phase=0.0)
        self.plate = os.path.join(self.folder.name, 'plate.gform')
        self.base.session.document.save(self.plate)

    def tearDown(self):
        self.folder.cleanup()

    def screw(self, length, name='screw.gform'):
        part = Part(self)
        part.do('screw', sketch=part.sketch({'type': 'point', 'x': 0, 'y': 0}), size='M3', head='cap', length=length, thread=True)
        path = os.path.join(self.folder.name, name)
        part.session.document.save(path)
        return path

    def check(self, length, head_z=10.0):
        data = {'parts': [{'name': '底板', 'path': self.plate}, {'name': '螺丝', 'path': self.screw(length), 'move': [0, 0, head_z]}]}
        result, error = ask(self.base.session, 'fasteners', data)
        self.assertIsNone(error)
        self.assertEqual(len(result['pairs']), 1)
        return result, result['pairs'][0]

    def test_good_screw(self):
        _, pair = self.check(6)
        self.assertEqual((pair['screw'], pair['hole_part'], pair['size']), (1, 0, 'M3'))
        self.assertAlmostEqual(pair['engaged'], 6.0, delta=0.15)
        self.assertAlmostEqual(pair['need'], 4.5)                 # 不知道材质: 按铝 1.5d
        self.assertAlmostEqual(pair['bottom'], 2.0, delta=0.1)
        self.assertTrue(pair['phase_ok'])
        self.assertEqual(pair['problems'], [])

    def test_short_screw_and_bottoming(self):
        _, short = self.check(3)
        self.assertTrue(any('拧进去只有' in problem for problem in short['problems']))
        _, deep = self.check(7.8)
        self.assertTrue(any('孔底' in problem for problem in deep['problems']))

    def test_phase_is_computed_and_applied(self):
        # 螺丝头抬高 0.2 (垫了一片 0.2 的垫片): 牙要错开 360 × 0.2 / 0.5 = 144°, 孔的相位要填 360 - 144 = 216
        result, pair = self.check(6, head_z=10.2)
        self.assertAlmostEqual(pair['phase_need'], 216.0, delta=0.5)
        self.assertFalse(pair['phase_ok'])
        self.assertEqual(result['fix'], [{'part': 0, 'feature': pair['feature'], 'phase': pair['phase_need']}])
        from genform.kernel import fasteners
        self.assertEqual(fasteners.apply_phases([(self.plate, pair['feature'], pair['phase_need'])]), 1)
        with open(self.plate, encoding='utf-8') as handle:
            hole = next(f for f in json.load(handle)['features'] if f['id'] == pair['feature'])
        self.assertAlmostEqual(hole['params']['phase'], 216.0, delta=0.5)
        _, again = self.check(6, head_z=10.2)
        self.assertTrue(again['phase_ok'])


class StackTest(unittest.TestCase):
    def test_layers_merge_and_order(self):
        rows = [{'index': 0, 'name': '底板', 'low': [-50, -50, 0], 'high': [50, 50, 5]},
                {'index': 1, 'name': '外壳', 'low': [-50, -50, 5], 'high': [50, 50, 40]},
                {'index': 2, 'name': '定子', 'low': [-40, -40, 10], 'high': [40, 40, 30]},
                {'index': 3, 'name': '螺丝 #1', 'low': [40, 0, 2], 'high': [44, 4, 12]},
                {'index': 4, 'name': '螺丝 #2', 'low': [-44, 0, 2], 'high': [-40, 4, 12]},
                {'index': 5, 'name': '相线', 'low': [0, 0, 0], 'high': [40, 1, 35]}]
        result = stack.layers(rows, 'Z')
        self.assertEqual((result['low'], result['high'], result['total']), (0.0, 40.0, 40.0))
        heights = sum(segment['height'] for segment in result['segments'])
        self.assertAlmostEqual(heights, 40.0)
        self.assertEqual(result['segments'][0]['parts'][0], '底板')
        middle = next(segment for segment in result['segments'] if segment['from'] <= 20 <= segment['to'])
        self.assertEqual(middle['parts'][:2], ['外壳', '定子'])
        self.assertNotIn('螺丝 #2', middle['parts'])               # 同一种件只列一次 (名字去掉 #n)
        self.assertNotEqual(middle['parts'][0], '相线')            # 细长的线排在后面


class EdgeMeasureTest(unittest.TestCase):
    def circle(self, radius, z, centre=(0.0, 0.0), count=48):
        import numpy as np
        angles = np.linspace(0, 2 * np.pi, count + 1)
        return np.stack([centre[0] + radius * np.cos(angles), centre[1] + radius * np.sin(angles), np.full_like(angles, z)], axis=1)

    def test_circle_and_coaxial(self):
        import math
        import numpy as np
        from genform import edge_measure
        hole = edge_measure.describe(self.circle(5, 0), 'circle', 2 * math.pi * 5, 5)
        self.assertTrue(hole['whole'])
        self.assertAlmostEqual(hole['diameter'], 10)
        np.testing.assert_allclose(hole['center'], [0, 0, 0], atol=1e-9)
        self.assertAlmostEqual(abs(hole['axis'][2]), 1.0)
        shaft = edge_measure.describe(self.circle(4, 12), 'circle', 2 * math.pi * 4, 4)
        out = edge_measure.compare(hole, shaft)
        self.assertAlmostEqual(out['center_distance'], 12)
        self.assertAlmostEqual(out['axis_offset'], 0, places=6)
        self.assertAlmostEqual(out['angle'], 0, places=4)
        off = edge_measure.describe(self.circle(4, 12, centre=(0.3, 0.4)), 'circle', 2 * math.pi * 4, 4)
        self.assertAlmostEqual(edge_measure.compare(hole, off)['axis_offset'], 0.5, places=6)
        arc = edge_measure.describe(self.circle(5, 0)[:13], 'circle', math.pi * 5 / 2, 5)
        self.assertFalse(arc['whole'])

    def test_two_lines(self):
        from genform import edge_measure
        first = edge_measure.describe([[0, 0, 0], [10, 0, 0]], 'line', 10)
        second = edge_measure.describe([[5, 3, 2], [5, 3, 12]], 'line', 10)
        out = edge_measure.compare(first, second)
        self.assertAlmostEqual(out['angle'], 90)
        self.assertAlmostEqual(out['distance'], (3 ** 2 + 2 ** 2) ** 0.5)


class StandardPartsTest(unittest.TestCase):
    """标准件库: 目录里的东西都能生成, 尺寸对得上规格。"""

    def build(self, kind, size, length=None, series=''):
        from genform import standard_parts
        from genform.kernel.model import rebuild
        name, doc = standard_parts.make(kind, size, length, series)
        shape, _, status = rebuild._rebuild(doc['features'], None)
        self.assertFalse([v for v in status.values() if str(v).startswith('error')], name)
        process = next(f['process'] for f in doc['features'] if 'process' in f)
        self.assertEqual(process['id'], 'standard')
        return name, doc, None, shape

    def size_of(self, shape):
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
        box = Bnd_Box()
        BRepBndLib.Add_s(shape, box)
        (x0, y0, z0), (x1, y1, z1) = box.CornerMin().Coord(), box.CornerMax().Coord()
        return x1 - x0, y1 - y0, z1 - z0

    def test_catalog_has_every_kind(self):
        from genform import standard_parts
        kinds = {row['id'] for row in standard_parts.catalog()}
        self.assertEqual(kinds, {'bearing', 'needle', 'dowel', 'screw', 'nut', 'washer', 'standoff', 'shaft_clip', 'hole_clip', 'ball'})

    def test_bearing_dowel_washer_sizes(self):
        name, doc, _, shape = self.build('bearing', '6709')
        self.assertEqual(name, 'std_6709.gform')
        dx, dy, dz = self.size_of(shape)
        self.assertAlmostEqual(dx, 55, delta=0.05)
        self.assertAlmostEqual(dz, 6, delta=0.05)
        from OCP.TopAbs import TopAbs_SOLID
        from OCP.TopExp import TopExp_Explorer
        solids = TopExp_Explorer(shape, TopAbs_SOLID)
        count = 0
        while solids.More():
            count, _ = count + 1, solids.Next()
        self.assertEqual(count, 1)                  # 一整块: 没有悬空的滚珠圈 / 密封圈
        _, _, _, shape = self.build('dowel', '3', 12)
        dx, _, dz = self.size_of(shape)
        self.assertAlmostEqual(dx, 3, delta=0.05)
        self.assertAlmostEqual(dz, 12, delta=0.05)
        _, _, _, shape = self.build('washer', 'M3')
        dx, _, dz = self.size_of(shape)
        self.assertAlmostEqual(dx, 7, delta=0.05)
        self.assertAlmostEqual(dz, 0.5, delta=0.02)

    def test_threaded_parts_build(self):
        _, doc, _, shape = self.build('standoff', 'M3', 8)
        self.assertEqual(doc['props']['material'], '黄铜')
        self.assertAlmostEqual(self.size_of(shape)[2], 8, delta=0.05)
        self.build('nut', 'M3')
        _, _, _, shape = self.build('screw', 'M3', 10, 'cap')
        self.assertGreater(self.size_of(shape)[2], 10)
        self.build('shaft_clip', '10')
        self.build('ball', '2')


class FlexibleTest(unittest.TestCase):
    """装配顺序里的线缆: 只用细圆截面扫出来的零件算软的, 不挡别的件。"""

    def doc(self, folder, name, radius, extra=()):
        features = [{'id': 'f1', 'type': 'sketch', 'params': {'plane': 'XY', 'shapes': [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 0, 'y2': 9}]}},
                    {'id': 'f2', 'type': 'sketch', 'params': {'plane': 'XZ', 'shapes': [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': radius}]}},
                    {'id': 'f3', 'type': 'sweep', 'params': {'sketch': 'f2', 'path': 'f1'}}] + list(extra)
        path = os.path.join(folder, name)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'features': features, 'props': {}}, handle)
        return {'path': path}

    def test_detect_wires(self):
        from genform.kernel import assembly
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(assembly._flexible(self.doc(folder, 'wire.gform', 0.8)))
            self.assertFalse(assembly._flexible(self.doc(folder, 'rod.gform', 5.0)))
            self.assertFalse(assembly._flexible(self.doc(folder, 'mixed.gform', 0.8, [{'id': 'f4', 'type': 'extrude', 'params': {}}])))


if __name__ == '__main__':
    unittest.main()
