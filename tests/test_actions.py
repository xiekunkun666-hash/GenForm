# -*- coding: utf-8 -*-
"""动作表、用户设置 (快捷键 / 手势轮)、面归哪个特征、框选用的几何判断。"""
import json
import os
import tempfile
import unittest

import numpy as np

from genform import actions
from genform.kernel import build
from genform.settings import Settings
from genform.view import picking


class ActionTable(unittest.TestCase):
    def test_ids_unique_and_default_keys_do_not_clash(self):
        ids = [row['id'] for row in actions.ACTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        keys = [row['default'].lower() for row in actions.ACTIONS if row['default']]
        self.assertEqual(len(keys), len(set(keys)))

    def test_default_wheels_use_known_actions(self):
        for rows in actions.GESTURES.values():
            self.assertEqual(len(rows), 8)
            for identifier in rows:
                self.assertIn(identifier, actions.BY_ID)
                self.assertLessEqual(len(actions.short(identifier)), 5)


class UserSettings(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.file = os.path.join(self.folder.name, 'deep', 'settings.json')

    def tearDown(self):
        self.folder.cleanup()

    def test_taking_a_used_key_clears_the_other_action(self):
        settings = Settings(self.file)
        self.assertEqual(settings.key('cmd:extrude'), 'E')
        self.assertEqual(settings.set_key('cmd:revolve', 'e'), ['cmd:extrude'])
        self.assertEqual(settings.key('cmd:extrude'), '')
        again = Settings(self.file)                 # 存下来了, 重新打开还在
        self.assertEqual(again.key('cmd:revolve'), 'e')
        self.assertEqual(again.key('cmd:extrude'), '')
        again.reset_keys()
        self.assertEqual(Settings(self.file).key('cmd:extrude'), 'E')

    def test_back_to_default_is_not_stored(self):
        settings = Settings(self.file)
        settings.set_key('cmd:revolve', 'Q')
        settings.set_key('cmd:revolve', '')
        settings.set_wheel('model', 7, 'cmd:fillet')
        settings.set_wheel('model', 7, actions.GESTURES['model'][7])
        with open(self.file, encoding='utf-8') as handle:
            self.assertEqual(json.load(handle), {'shortcuts': {}, 'gestures': {}})

    def test_broken_file_falls_back_to_defaults(self):
        os.makedirs(os.path.dirname(self.file))
        with open(self.file, 'w', encoding='utf-8') as handle:
            handle.write('{"shortcuts": {"no.such": "X", "cmd:cut": 5}, "gestures": {"model": ["view:top"]}')
        self.assertEqual(Settings(self.file).wheel('model'), actions.GESTURES['model'])
        with open(self.file, 'w', encoding='utf-8') as handle:
            json.dump({'shortcuts': {'no.such': 'X', 'cmd:cut': 'K'}, 'gestures': {'model': ['view:top']}}, handle)
        settings = Settings(self.file)
        self.assertEqual(settings.keys, {'cmd:cut': 'K'})
        self.assertEqual(settings.wheel('model'), actions.GESTURES['model'])


class FaceOwners(unittest.TestCase):
    def test_faces_know_their_feature_and_edges(self):
        features = [
            {'id': 'f1', 'type': 'sketch', 'params': {'plane': 'XY', 'shapes': [{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 80, 'h': 50}]}},
            {'id': 'f2', 'type': 'extrude', 'params': {'sketch': 'f1', 'distance': 20}},
            {'id': 'f3', 'type': 'sketch', 'params': {'plane': 'XY', 'offset': 20, 'shapes': [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 12}]}},
            {'id': 'f4', 'type': 'extrude', 'params': {'sketch': 'f3', 'distance': 15}},
            {'id': 'f5', 'type': 'fillet', 'params': {'edges': '|Z', 'radius': 4}},
        ]
        model = build.build_model(features)
        owners = {}
        for face in model['faces']:
            owners.setdefault(face['feature'], []).append(face)
        self.assertEqual(set(owners), {'f2', 'f4', 'f5'})
        self.assertEqual(len(owners['f5']), 4)                      # 四个圆角面
        self.assertEqual(sorted(face['type'] for face in owners['f4']), ['cylinder', 'plane'])
        # 底板的顶面被凸台占了一块、四角被圆角削了, 还是算底板的
        top = next(face for face in owners['f2'] if face['normal'] and face['normal'][2] > 0.5)
        self.assertAlmostEqual(top['center'][2], 20.0)
        known = {edge['id'] for edge in model['edges']}
        for face in model['faces']:
            self.assertTrue(face['edges'])
            self.assertTrue(set(face['edges']) <= known)


class BoxSelection(unittest.TestCase):
    def test_segments_touching_rect(self):
        start = np.array([[0.0, 5.0], [-5.0, -5.0], [20.0, 0.0], [2.0, 2.0]])
        end = np.array([[20.0, 5.0], [-1.0, -1.0], [20.0, 20.0], [3.0, 3.0]])
        hit = picking.segments_touch_rect(start, end, (1.0, 1.0), (10.0, 10.0))
        self.assertEqual(hit.tolist(), [True, False, False, True])     # 穿过去的也算; 整条在外面的不算

    def test_points_in_rect(self):
        screen = np.array([[5.0, 5.0], [11.0, 5.0], [5.0, 5.0]])
        inside = picking.in_rect(screen, np.array([1.0, 1.0, -1.0]), (1.0, 1.0), (10.0, 10.0))
        self.assertEqual(inside.tolist(), [True, False, False])


if __name__ == '__main__':
    unittest.main()


class RayBoxedTest(unittest.TestCase):
    def test_same_answer_as_testing_every_triangle(self):
        import numpy as np
        from genform.view import picking
        rng = np.random.default_rng(1)
        centers = rng.uniform(-100, 100, (6000, 3))
        verts = (centers[:, None, :] + rng.uniform(-4, 4, (6000, 3, 3))).reshape(-1, 3).astype(np.float32)
        tris = np.arange(len(verts), dtype=np.uint32).reshape(-1, 3)
        model = {'verts': verts, 'tris': tris}
        for _ in range(25):
            origin = rng.uniform(-80, 80, 3)
            origin[2] = 300
            direction = rng.normal(size=3)
            direction[2] = -5
            direction /= np.linalg.norm(direction)
            plain, boxed = picking.ray_triangles(origin, direction, verts, tris), picking.ray_boxed(origin, direction, model)
            self.assertEqual(plain[0], boxed[0])
            self.assertAlmostEqual(plain[1], boxed[1])
