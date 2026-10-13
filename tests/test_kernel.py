"""几何内核: 草图 → 拉伸 → 圆角/倒角 → 改尺寸重算 → 导出。"""
import math
import os
import tempfile
import unittest

import numpy as np

from genform.kernel import build


def sketch(identifier, shapes, plane='XY', offset=0.0):
    return {'id': identifier, 'type': 'sketch', 'params': {'plane': plane, 'offset': offset, 'shapes': shapes}}


def extrude(identifier, source, distance, op='add', **more):
    return {'id': identifier, 'type': 'extrude', 'params': dict(sketch=source, distance=distance, op=op, **more)}


def block(w=40.0, h=30.0, depth=10.0):
    return [sketch('s1', [{'type': 'rect', 'cx': 0, 'cy': 0, 'w': w, 'h': h}]), extrude('e1', 's1', depth)]


class SolidTests(unittest.TestCase):
    def test_rectangle_extrude_gives_a_box(self):
        model = build.build_model(block())
        self.assertEqual(model['status'], {'s1': 'ok', 'e1': 'ok'})
        self.assertAlmostEqual(model['props']['volume'], 40 * 30 * 10, places=6)
        np.testing.assert_allclose(model['props']['size'], (40, 30, 10), atol=1e-6)
        self.assertEqual(len(model['faces']), 6)
        self.assertEqual(len(model['edges']), 12)
        self.assertEqual(len(model['tris']), len(model['tri_face']))
        self.assertEqual(model['tris'].max(), len(model['verts']) - 1)

    def test_nested_outline_is_a_hole(self):
        features = [sketch('s1', [{'type': 'rect', 'w': 40, 'h': 30}, {'type': 'circle', 'r': 5}]),
                    extrude('e1', 's1', 10)]
        model = build.build_model(features)
        self.assertAlmostEqual(model['props']['volume'], (40 * 30 - math.pi * 25) * 10, places=4)

    def test_cut_removes_material_and_planes_follow_cad_views(self):
        features = block() + [sketch('s2', [{'type': 'circle', 'r': 4}], plane='XZ', offset=20),
                              extrude('e2', 's2', -40, op='cut')]
        model = build.build_model(features)
        self.assertEqual(model['status']['e2'], 'ok')
        # XZ 面 (前视) 的法向是 -Y, 朝着看图的人: 偏移 20 在 y=-20, 反向拉伸 40 穿过整块板。圆心在 z=0, 只有上半个圆落在板子里 → 切掉半个圆柱 (贯穿 30 厚)
        self.assertAlmostEqual(model['props']['volume'], 12000 - math.pi * 16 / 2 * 30, places=3)

    def test_symmetric_extrude_is_centred_on_the_sketch_plane(self):
        model = build.build_model([sketch('s1', [{'type': 'rect', 'w': 10, 'h': 10}]),
                                   extrude('e1', 's1', 8, symmetric=True)])
        self.assertAlmostEqual(model['props']['bbox_min'][2], -4, places=6)
        self.assertAlmostEqual(model['props']['bbox_max'][2], 4, places=6)

    def test_merged_faces_after_union(self):
        features = block() + [sketch('s2', [{'type': 'rect', 'cx': 40, 'w': 40, 'h': 30}]), extrude('e2', 's2', 10)]
        model = build.build_model(features)
        self.assertEqual(len(model['faces']), 6)          # 两块拼成一块长方体, 共面的碎面要合并
        self.assertAlmostEqual(model['props']['volume'], 80 * 30 * 10, places=5)


class BlendTests(unittest.TestCase):
    def fillet(self, edges, radius=2.0):
        return block() + [{'id': 'f1', 'type': 'fillet', 'params': {'edges': edges, 'radius': radius}}]

    def test_fillet_vertical_edges_by_selector(self):
        model = build.build_model(self.fillet('|Z', 3.0))
        self.assertEqual(model['status']['f1'], 'ok')
        self.assertAlmostEqual(model['props']['volume'], 12000 - (4 - math.pi) * 9 * 10, places=4)
        self.assertEqual(sum(face['type'] == 'cylinder' for face in model['faces']), 4)

    def test_fillet_edge_picked_by_midpoint(self):
        model = build.build_model(self.fillet([{'point': [20, 15, 5]}], 3.0))
        self.assertAlmostEqual(model['props']['volume'], 12000 - (4 - math.pi) / 4 * 9 * 10, places=4)

    def test_top_ring_selector_and_chamfer(self):
        features = block() + [{'id': 'c1', 'type': 'chamfer', 'params': {'edges': '>Z', 'distance': 1.0}}]
        model = build.build_model(features)
        self.assertEqual(model['status']['c1'], 'ok')
        self.assertLess(model['props']['volume'], 12000)
        self.assertAlmostEqual(model['props']['size'][2], 10, places=6)

    def test_oversized_fillet_reports_error_and_keeps_previous_body(self):
        model = build.build_model(self.fillet('|Z', 50.0))
        self.assertTrue(model['status']['f1'].startswith('error'), model['status'])
        self.assertIn('太大', model['status']['f1'])
        self.assertAlmostEqual(model['props']['volume'], 12000, places=6)

    def test_picked_edge_follows_a_dimension_change(self):
        features = self.fillet([{'point': [20, 15, 5]}], 3.0)
        features[0]['params']['shapes'][0]['w'] = 44          # 边从 x=20 移到 x=22, 仍是同一条
        model = build.build_model(features)
        self.assertEqual(model['status']['f1'], 'ok')
        self.assertAlmostEqual(model['props']['volume'], 44 * 30 * 10 - (4 - math.pi) / 4 * 90, places=4)


class RebuildTests(unittest.TestCase):
    def test_error_stops_later_features(self):
        features = block() + [extrude('e2', 'missing', 5), {'id': 'f1', 'type': 'fillet',
                                                            'params': {'edges': 'all', 'radius': 1}}]
        model = build.build_model(features)
        self.assertTrue(model['status']['e2'].startswith('error'))
        self.assertEqual(model['status']['f1'], 'skipped')
        self.assertAlmostEqual(model['props']['volume'], 12000, places=6)

    def test_suppressed_and_rollback(self):
        features = block() + [{'id': 'f1', 'type': 'fillet', 'params': {'edges': '|Z', 'radius': 3}, 'suppressed': True}]
        self.assertEqual(build.build_model(features)['status']['f1'], 'suppressed')
        rolled = build.build_model(block(), upto=1)
        self.assertFalse(rolled['has_body'])
        self.assertEqual(rolled['status'], {'s1': 'ok', 'e1': 'skipped'})
        self.assertEqual(len(rolled['sketches']['s1']), 4)

    def test_bad_parameters_are_explained(self):
        model = build.build_model([sketch('s1', [{'type': 'rect', 'w': -1, 'h': 2}])])
        self.assertIn('正数', model['status']['s1'])
        model = build.build_model([sketch('s1', [{'type': 'rect', 'w': 4, 'h': 2}]), extrude('e1', 's1', 0)])
        self.assertIn('不能为 0', model['status']['e1'])

    def test_export_step_and_stl(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('part.step', 'part.stl'):
                path = os.path.join(folder, name)
                build.export(block(), path)
                self.assertGreater(os.path.getsize(path), 500)
            with self.assertRaises(build.FeatureError):
                build.export([], os.path.join(folder, 'empty.step'))


if __name__ == '__main__':
    unittest.main()
