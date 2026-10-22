# -*- coding: utf-8 -*-
"""按特征上色: set_appearance 写了 features 只给那些特征做出来的面上色, 显示数据里逐顶点带颜色。"""
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from genform.kernel import build, store
from genform.kernel.model import faces as face_owners
from genform.kernel.model import rebuild as rebuild_steps
from genform.session import Session
from genform.view.viewer.common import _geometry


def run(session, command, **args):
    replies = []
    session.execute(command, args, replies.append)
    return replies[0]


class FeatureColors(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        run(self.session, 'sketch', shapes=[{'type': 'rect', 'w': 40, 'h': 30}])
        self.plate = run(self.session, 'extrude', distance=10)['id']
        run(self.session, 'sketch', plane='XY', offset=10, shapes=[{'type': 'circle', 'r': 5}])
        self.boss = run(self.session, 'extrude', distance=8)['id']

    def assert_face_tints(self, model, faces, colors, tint):
        geometry, vertex_face, _, _ = _geometry(model, colors=colors)
        selected = np.isin(vertex_face, [face['id'] for face in faces])
        self.assertTrue(selected.any())
        np.testing.assert_allclose(geometry['tints'][selected],
                                   np.broadcast_to(tint, geometry['tints'][selected].shape), atol=1e-6)

    def test_command_stores_and_clears(self):
        self.assertTrue(run(self.session, 'set_appearance', color='#202020', features=[self.boss])['ok'])
        self.assertEqual(self.session.document.props['feature_colors'], {self.boss: '#202020'})
        self.assertFalse(run(self.session, 'set_appearance', color='#202020', features=['f99'])['ok'])
        self.assertEqual(run(self.session, 'get_model')['feature_colors'], {self.boss: '#202020'})
        run(self.session, 'set_appearance', features=[self.boss])           # 写空 = 回到零件的颜色
        self.assertNotIn('feature_colors', self.session.document.props)

    def test_vertices_of_coloured_feature_get_its_tint(self):
        model = self.session.model
        geometry, vertex_face, _, _ = _geometry(model, colors={self.boss: (0.1, 0.2, 0.3)})
        owner = {face['id']: face['feature'] for face in model['faces']}
        used = vertex_face >= 0
        mine = np.array([owner.get(int(face)) == self.boss for face in vertex_face]) & used
        self.assertTrue(mine.any() and (used & ~mine).any())
        np.testing.assert_allclose(geometry['tints'][mine][0], (0.1, 0.2, 0.3), atol=1e-6)
        self.assertTrue((geometry['tints'][used & ~mine] < 0).all())       # 别的面: -1 = 零件的颜色
        self.assertTrue(geometry['tinted'])
        self.assertFalse(_geometry(model)[0]['tinted'])

    def test_fillet_preserves_trimmed_plate_and_boss_owners(self):
        fillet = run(self.session, 'fillet', edges='|Z', radius=2)['id']
        self.assertEqual(set(self.session.model['status'].values()), {'ok'})
        faces = self.session.model['faces']
        self.assertEqual({face['feature'] for face in faces}, {self.plate, self.boss, fillet})
        self.assertEqual(len([face for face in faces if face['feature'] == fillet]), 4)
        boss = [face for face in faces if face['feature'] == self.boss]
        self.assertEqual(sorted(face['type'] for face in boss), ['cylinder', 'plane'])
        plate_top = next(face for face in faces if face['normal'] and face['normal'][2] > 0.9
                         and abs(face['center'][2] - 10) < 1e-6)
        self.assertEqual(plate_top['feature'], self.plate)

    def test_disconnected_coplanar_block_keeps_the_later_feature_owner(self):
        session = Session()
        run(session, 'sketch', shapes=[{'type': 'rect', 'cx': -20, 'cy': 0, 'w': 10, 'h': 10}])
        first = run(session, 'extrude', distance=10)['id']
        run(session, 'sketch', shapes=[{'type': 'rect', 'cx': 20, 'cy': 0, 'w': 10, 'h': 10}])
        second = run(session, 'extrude', distance=10)['id']

        self.assertEqual(set(session.model['status'].values()), {'ok'})
        top = next(face for face in session.model['faces']
                   if face['normal'] and face['normal'][2] > 0.9 and face['center'][0] > 0)
        self.assertEqual(top['feature'], second)
        self.assertNotEqual(top['feature'], first)
        colors = {first: (0.8, 0.1, 0.1), second: (0.1, 0.1, 0.1)}
        for owner, sign in ((first, -1), (second, 1)):
            faces = [face for face in session.model['faces'] if face['center'][0] * sign > 0]
            self.assertEqual(len(faces), 6)
            self.assertEqual({face['feature'] for face in faces}, {owner})
            self.assert_face_tints(session.model, faces, colors, colors[owner])

    def test_disconnected_coaxial_cylinder_keeps_the_later_feature_owner(self):
        session = Session()
        run(session, 'sketch', shapes=[{'type': 'circle', 'r': 8}])
        first = run(session, 'extrude', distance=5)['id']
        run(session, 'sketch', offset=10, shapes=[{'type': 'circle', 'r': 8}])
        second = run(session, 'extrude', distance=5)['id']

        self.assertEqual(set(session.model['status'].values()), {'ok'})
        side = [face for face in session.model['faces'] if face['type'] == 'cylinder']
        self.assertEqual(len(side), 2)
        self.assertEqual(max(side, key=lambda face: face['center'][2])['feature'], second)
        self.assertEqual(min(side, key=lambda face: face['center'][2])['feature'], first)
        colors = {first: (0.8, 0.1, 0.1), second: (0.1, 0.1, 0.1)}
        for owner, high in ((first, False), (second, True)):
            faces = [face for face in session.model['faces'] if (face['center'][2] > 7.5) == high]
            self.assertEqual(len(faces), 3)
            self.assertEqual({face['feature'] for face in faces}, {owner})
            self.assert_face_tints(session.model, faces, colors, colors[owner])

    def test_disconnected_coplanar_faces_with_overlapping_boxes_keep_their_owners(self):
        session = Session()
        run(session, 'sketch', shapes=[{'type': 'circle', 'r': 10}, {'type': 'circle', 'r': 8}])
        ring = run(session, 'extrude', distance=5)['id']
        run(session, 'sketch', shapes=[{'type': 'circle', 'r': 3}])
        disc = run(session, 'extrude', distance=5)['id']

        self.assertEqual(set(session.model['status'].values()), {'ok'})
        caps = [face for face in session.model['faces'] if face['normal'] and face['normal'][2] > 0.9]
        self.assertEqual(len(caps), 2)
        self.assertEqual(min(caps, key=lambda face: face['area'])['feature'], disc)
        self.assertEqual(max(caps, key=lambda face: face['area'])['feature'], ring)
        colors = {ring: (0.8, 0.1, 0.1), disc: (0.1, 0.1, 0.1)}
        for face in caps:
            self.assert_face_tints(session.model, [face], colors, colors[face['feature']])

    def test_spline_loft_cut_keeps_the_outer_loft_owner(self):
        session = Session()
        bottom = run(session, 'sketch', shapes=[{'type': 'spline', 'closed': True,
                                                  'points': [[-30, -20], [-10, -28], [20, -24],
                                                             [32, -8], [28, 18], [5, 28],
                                                             [-25, 22]]}])['id']
        top = run(session, 'sketch', offset=30, shapes=[{'type': 'spline', 'closed': True,
                                                          'points': [[-20, -14], [-8, -20], [14, -17],
                                                                     [22, -5], [19, 13], [3, 20],
                                                                     [-17, 15]]}])['id']
        loft = run(session, 'loft', sketches=[bottom, top])['id']
        outer_before = next(face for face in session.model['faces']
                            if face['type'] == 'surface' and face['center'][0] > 25)
        cutter = run(session, 'sketch', plane='XZ',
                     shapes=[{'type': 'circle', 'cx': 28, 'cy': 10, 'r': 10}])['id']
        cut = run(session, 'extrude', sketch=cutter, distance=100, symmetric=True, op='cut')['id']

        self.assertEqual(set(session.model['status'].values()), {'ok'})
        outer = [face for face in session.model['faces'] if face['type'] == 'surface']
        self.assertGreater(len(outer), 0)
        self.assertEqual({face['feature'] for face in outer}, {loft})
        changed = next(face for face in outer if 22 < face['center'][0] < 25 and face['center'][2] > 20)
        self.assertLess(changed['area'], outer_before['area'] / 2)
        cut_faces = [face for face in session.model['faces'] if face['type'] == 'cylinder']
        self.assertTrue(cut_faces)
        self.assertEqual({face['feature'] for face in cut_faces}, {cut})
        colors = {loft: (0.8, 0.1, 0.1), cut: (0.1, 0.1, 0.1)}
        self.assert_face_tints(session.model, outer, colors, colors[loft])
        self.assert_face_tints(session.model, cut_faces, colors, colors[cut])


class FaceOwnerCache(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {'GENFORM_CACHE': temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        automatic = patch.object(rebuild_steps, 'STORE_AFTER', float('inf'))
        automatic.start()
        self.addCleanup(automatic.stop)
        self.clear_caches()
        self.addCleanup(self.clear_caches)

    @staticmethod
    def clear_caches():
        for cache in (build._STEPS, build._SPARE, build._SHOWN, build._FACE_MESHES, rebuild_steps._MESHED):
            cache.clear()

    @staticmethod
    def separated_features(cylinders=False):
        shapes = ([{'type': 'circle', 'r': 8}], [{'type': 'circle', 'r': 8}]) if cylinders else (
            [{'type': 'rect', 'cx': -20, 'cy': 0, 'w': 10, 'h': 10}],
            [{'type': 'rect', 'cx': 20, 'cy': 0, 'w': 10, 'h': 10}])
        return [
            {'id': 'f1', 'type': 'sketch', 'params': {'plane': 'XY', 'shapes': shapes[0]}},
            {'id': 'f2', 'type': 'extrude', 'params': {'sketch': 'f1', 'distance': 5 if cylinders else 10}},
            {'id': 'f3', 'type': 'sketch', 'params': {'plane': 'XY', 'offset': 10 if cylinders else 0, 'shapes': shapes[1]}},
            {'id': 'f4', 'type': 'extrude', 'params': {'sketch': 'f3', 'distance': 5 if cylinders else 10}}]

    def owner_snapshot(self, model):
        self.assertEqual(set(model['status'].values()), {'ok'})
        return sorted((face['type'], tuple(round(value, 6) for value in face['center']),
                       round(face['area'], 6), face['feature']) for face in model['faces'])

    def assert_split_owners(self, model, cylinders=False):
        axis, threshold = (2, 7.5) if cylinders else (0, 0)
        self.assertEqual(set(model['status'].values()), {'ok'})
        for face in model['faces']:
            self.assertEqual(face['feature'], 'f4' if face['center'][axis] > threshold else 'f2')

    def test_disk_roundtrip_preserves_face_indices_and_owners(self):
        for cylinders in (False, True):
            with self.subTest(cylinders=cylinders):
                self.clear_caches()
                features = self.separated_features(cylinders)
                original = build.build_model(features)
                self.assert_split_owners(original, cylinders)
                build.keep()
                loaded = store.load(build._step_keys(features)[-1])
                self.assertIsNotNone(loaded)
                owners = loaded[1]['owners']
                self.assertEqual(set(owners), set(range(len(original['faces']))))
                self.assertTrue(all(isinstance(index, int) and isinstance(owner, str) for index, owner in owners.items()))
                self.clear_caches()
                with patch.object(rebuild_steps, 'combine', side_effect=AssertionError('unexpected geometry rebuild')) as combine:
                    restored = build.build_model(features)
                    combine.assert_not_called()
                self.assertIs(build._STEPS[0][1], build._MISSING)
                self.assert_split_owners(restored, cylinders)
                self.assertEqual(self.owner_snapshot(restored), self.owner_snapshot(original))

    def test_cut_continues_from_disk_and_matches_a_fresh_rebuild(self):
        for cylinders in (False, True):
            with self.subTest(cylinders=cylinders):
                self.clear_caches()
                features = self.separated_features(cylinders)
                build.build_model(features)
                build.keep()
                self.clear_caches()
                build.build_model(features)
                self.assertIs(build._STEPS[0][1], build._MISSING)
                features += [
                    {'id': 'f5', 'type': 'sketch', 'params': {'plane': 'XY', 'shapes': [{'type': 'rect', 'w': 60, 'h': 2}]}},
                    {'id': 'f6', 'type': 'extrude', 'params': {'sketch': 'f5', 'distance': 15 if cylinders else 10, 'op': 'cut'}}]
                with patch.object(rebuild_steps, 'combine', wraps=rebuild_steps.combine) as combine:
                    continued = build.build_model(features)
                    self.assertEqual(combine.call_count, 1)
                self.assertEqual(set(continued['status'].values()), {'ok'})
                caps = [face for face in continued['faces'] if face['normal'] and abs(face['normal'][2]) > 0.9]
                self.assertEqual(len(caps), 8)
                inherited = caps + ([face for face in continued['faces'] if face['type'] == 'cylinder'] if cylinders else [])
                axis, threshold = (2, 7.5) if cylinders else (0, 0)
                for face in inherited:
                    self.assertEqual(face['feature'], 'f4' if face['center'][axis] > threshold else 'f2')
                cut_faces = [face for face in continued['faces'] if abs(abs(face['center'][1]) - 1) < 1e-6]
                self.assertEqual(len(cut_faces), 4)
                self.assertEqual({face['feature'] for face in cut_faces}, {'f6'})
                self.clear_caches()
                with patch.object(store, 'load', return_value=None):
                    fresh = build.build_model(features)
                self.assertEqual(self.owner_snapshot(continued), self.owner_snapshot(fresh))

    def test_preview_and_rollback_keep_separate_face_owners(self):
        features = self.separated_features()
        original = build.build_model(features)
        changed = copy.deepcopy(features)
        changed[-1]['params']['distance'] = 14
        preview = build.build_model(changed)
        self.assert_split_owners(preview)
        with patch.object(rebuild_steps, 'combine', side_effect=AssertionError('unexpected geometry rebuild')) as combine:
            restored = build.build_model(features)
            self.assertEqual(self.owner_snapshot(restored), self.owner_snapshot(original))
            accepted = build.build_model(changed)
            self.assertEqual(self.owner_snapshot(accepted), self.owner_snapshot(preview))
            combine.assert_not_called()
        rolled = build.build_model(features, upto=2)
        self.assertEqual(len(rolled['faces']), 6)
        self.assertEqual({face['feature'] for face in rolled['faces']}, {'f2'})

    def test_disconnected_candidates_do_not_run_surface_distance_checks(self):
        with patch.object(face_owners, 'BRepExtrema_DistShapeShape') as distance:
            model = build.build_model(self.separated_features())
            self.assert_split_owners(model)
            distance.assert_not_called()

    def test_unchanged_face_identities_skip_surface_matching(self):
        features = self.separated_features()
        original = build.build_model(features)
        features += [
            {'id': 'f5', 'type': 'sketch', 'params': {'plane': 'XY', 'shapes': [{'type': 'circle', 'cx': 100, 'r': 2}]}},
            {'id': 'f6', 'type': 'extrude', 'params': {'sketch': 'f5', 'distance': 10, 'op': 'cut'}}]
        with patch.object(face_owners, '_face_signature') as signature, \
                patch.object(face_owners, 'BRepExtrema_DistShapeShape') as distance:
            unchanged = build.build_model(features)
            # 离得远的切除什么都没切掉: 现在报错 (见 solids._check_changed), 实体保留运算前的样子, 面的归属照旧
            self.assertTrue(unchanged['status'].pop('f6').startswith('error'))
            self.assertEqual(self.owner_snapshot(unchanged), self.owner_snapshot(original))
            signature.assert_not_called()
            distance.assert_not_called()

    def test_spline_loft_cut_and_disk_roundtrip_keep_owners(self):
        profiles = [
            [[-30, -20], [-10, -28], [20, -24], [32, -8], [28, 18], [5, 28], [-25, 22]],
            [[-20, -14], [-8, -20], [14, -17], [22, -5], [19, 13], [3, 20], [-17, 15]]]
        features = [{'id': f'f{index + 1}', 'type': 'sketch',
                     'params': {'plane': 'XY', 'offset': index * 30,
                                'shapes': [{'type': 'spline', 'closed': True, 'points': points}]}}
                    for index, points in enumerate(profiles)]
        features.append({'id': 'f3', 'type': 'loft', 'params': {'sketches': ['f1', 'f2']}})
        self.owner_snapshot(build.build_model(features))
        build.keep()
        self.clear_caches()
        build.build_model(features)
        self.assertIs(build._STEPS[0][1], build._MISSING)
        features += [
            {'id': 'f4', 'type': 'sketch', 'params': {'plane': 'XZ',
                                                   'shapes': [{'type': 'circle', 'cx': 28, 'cy': 10, 'r': 10}]}},
            {'id': 'f5', 'type': 'extrude', 'params': {'sketch': 'f4', 'distance': 100, 'symmetric': True, 'op': 'cut'}}]
        continued = build.build_model(features)
        self.assertEqual(set(continued['status'].values()), {'ok'})
        self.assertEqual({face['feature'] for face in continued['faces'] if face['type'] == 'surface'}, {'f3'})
        self.assertEqual({face['feature'] for face in continued['faces'] if face['type'] == 'cylinder'}, {'f5'})
        build.keep()
        self.clear_caches()
        with patch.object(rebuild_steps, 'combine') as combine:
            restored = build.build_model(features)
            self.assertEqual(self.owner_snapshot(restored), self.owner_snapshot(continued))
            combine.assert_not_called()
        self.clear_caches()
        with patch.object(store, 'load', return_value=None):
            fresh = build.build_model(features)
        self.assertEqual(self.owner_snapshot(fresh), self.owner_snapshot(continued))


if __name__ == '__main__':
    unittest.main()
