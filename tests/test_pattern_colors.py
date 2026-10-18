# -*- coding: utf-8 -*-
"""半透明的特征排到最后画; 阵列 / 镜像复制出来的面记得原件 ('origin'), 阵列自己没上色时跟着原件的颜色; 放样轮廓自交时点名。"""
import unittest

import numpy as np

from genform.session import Session
from genform.view.viewer.common import _geometry


def run(session, command, **args):
    replies = []
    session.execute(command, args, replies.append)
    return replies[0]


class PatternOrigins(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        run(self.session, 'sketch', shapes=[{'type': 'rect', 'cx': 30, 'w': 100, 'h': 30}])
        self.plate = run(self.session, 'extrude', distance=10)['id']
        run(self.session, 'sketch', plane='XY', offset=10, shapes=[{'type': 'circle', 'cx': 0, 'cy': 6, 'r': 4}])
        self.boss = run(self.session, 'extrude', distance=8)['id']
        run(self.session, 'sketch', plane='XY', offset=10, shapes=[{'type': 'rect', 'cx': 0, 'cy': -12.5, 'w': 6, 'h': 3}])
        self.pocket = run(self.session, 'extrude', distance=3, reverse=True, op='cut')['id']
        self.row = run(self.session, 'pattern_linear', features=[self.boss, self.pocket], axis1='X', count1=3,
                       spacing1=30, count2=1)['id']

    def faces_of(self, identifier):
        return [face for face in self.session.model['faces'] if face.get('feature') == identifier]

    def test_copied_faces_remember_their_seed(self):
        copies = self.faces_of(self.row)
        self.assertTrue(copies)
        self.assertEqual({face.get('origin') for face in copies}, {self.boss, self.pocket})
        cylinders = [face for face in copies if face['type'] == 'cylinder']
        self.assertEqual({face['origin'] for face in cylinders}, {self.boss})

    def test_mirror_of_pattern_traces_back_to_first_seed(self):
        flipped = run(self.session, 'mirror', features=[self.boss, self.pocket, self.row], plane='XZ')['id']
        self.assertEqual(set(self.session.model['status'].values()), {'ok'})
        self.assertEqual({face.get('origin') for face in self.faces_of(flipped)}, {self.boss, self.pocket})

    def test_uncoloured_pattern_follows_seed_colour(self):
        model = self.session.model
        colors = {self.boss: (0.1, 0.2, 0.3)}
        geometry, vertex_face, _, _ = _geometry(model, colors=colors)
        copied = [face['id'] for face in self.faces_of(self.row) if face.get('origin') == self.boss]
        mine = np.isin(vertex_face, copied)
        self.assertTrue(mine.any())
        np.testing.assert_allclose(geometry['tints'][mine], np.broadcast_to((0.1, 0.2, 0.3), geometry['tints'][mine].shape),
                                   atol=1e-6)
        colors[self.row] = (0.9, 0.0, 0.0)              # 阵列自己上了色: 用它自己的
        geometry, vertex_face, _, _ = _geometry(model, colors=colors)
        np.testing.assert_allclose(geometry['tints'][np.isin(vertex_face, copied)][0], (0.9, 0.0, 0.0), atol=1e-6)


class GlassFaces(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        run(self.session, 'sketch', shapes=[{'type': 'rect', 'w': 40, 'h': 30}])
        self.plate = run(self.session, 'extrude', distance=10)['id']
        run(self.session, 'sketch', plane='XY', offset=10, shapes=[{'type': 'circle', 'r': 5}])
        self.boss = run(self.session, 'extrude', distance=8)['id']

    def test_opacity_command_keeps_colour_and_one_clears(self):
        run(self.session, 'set_appearance', color='#203040', features=[self.boss])
        self.assertTrue(run(self.session, 'set_appearance', opacity=0.3, features=[self.boss])['ok'])
        props = self.session.document.props
        self.assertEqual((props['feature_colors'], props['feature_opacity']), ({self.boss: '#203040'}, {self.boss: 0.3}))
        self.assertFalse(run(self.session, 'set_appearance', opacity=0.0, features=[self.boss])['ok'])
        run(self.session, 'set_appearance', opacity=1, features=[self.boss])
        self.assertNotIn('feature_opacity', self.session.document.props)

    def test_translucent_triangles_go_last_in_one_run(self):
        model = self.session.model
        geometry = _geometry(model, opacity={self.boss: 0.4})[0]
        self.assertEqual(len(geometry['glass']), 1)
        start, count, alpha = geometry['glass'][0]
        self.assertAlmostEqual(alpha, 0.4, places=6)
        self.assertEqual(start + count, len(model['tris']))
        owner = {face['id']: face['feature'] for face in model['faces']}
        tri_owner = {tuple(tri): owner[int(face)] for tri, face in zip(model['tris'], model['tri_face'])}
        self.assertEqual({tri_owner[tuple(tri)] for tri in geometry['tris'][start:]}, {self.boss})
        self.assertEqual({tri_owner[tuple(tri)] for tri in geometry['tris'][:start]}, {self.plate})
        self.assertEqual(sorted(map(tuple, geometry['tris'])), sorted(map(tuple, model['tris'])))
        self.assertEqual(_geometry(model)[0]['glass'], [])


class LoftBlame(unittest.TestCase):
    def test_self_crossing_profile_is_named(self):
        session = Session()
        square = [[-20, -20], [20, -20], [20, 20], [-20, 20]]
        bowtie = [[-20, -20], [20, 20], [20, -20], [-20, 20]]          # 点的顺序打了结
        first = run(session, 'sketch', plane='XY', offset=0, name='底', shapes=[{'type': 'spline', 'points': square, 'closed': True}])
        second = run(session, 'sketch', plane='XY', offset=40, name='打结的',
                     shapes=[{'type': 'spline', 'points': bowtie, 'closed': True}])
        reply = run(session, 'loft', sketches=[first['id'], second['id']])
        status = session.model['status'][reply['id']]
        self.assertTrue(status.startswith('error'))
        self.assertIn('打结的', status)


if __name__ == '__main__':
    unittest.main()
