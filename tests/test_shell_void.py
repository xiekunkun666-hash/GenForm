# -*- coding: utf-8 -*-
"""封闭抽壳: 外壳 + 反过来的内壳拼成一块空心实体 (不做布尔); 拼接偏移做不成时退到简单偏移; 壁厚太大要报错。"""
import unittest
from unittest.mock import patch

from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeSphere
from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID

from genform.kernel.build import FeatureError
from genform.kernel.ops import modify
from genform.kernel.ops.solid_validation import signed_volume
from tests.test_features import Part


class JoinFails:
    """偏移器的替身: 拼接偏移直接失败 (像在样条车身上那样), 简单偏移照常交给 OCC。"""
    def __init__(self):
        self.real = BRepOffsetAPI_MakeOffsetShape()

    def PerformByJoin(self, *args):
        raise RuntimeError('join')

    def __getattr__(self, name):
        return getattr(self.real, name)


def join_fails():
    return patch.object(modify, 'BRepOffsetAPI_MakeOffsetShape', JoinFails)


def count(shape, kind):
    return len(modify._explore(shape, kind))


class ClosedShell(unittest.TestCase):
    def test_box_becomes_one_solid_with_a_void(self):
        box = BRepPrimAPI_MakeBox(40.0, 30.0, 20.0).Shape()
        hollow = modify.shell(box, {'thickness': 2.0}, None)
        self.assertEqual(count(hollow, TopAbs_SOLID), 1)
        self.assertEqual(count(hollow, TopAbs_SHELL), 2)                     # 外面一层、空腔一层
        self.assertAlmostEqual(signed_volume(hollow), 24000 - 36 * 26 * 16, delta=1e-3)

    def test_falls_back_to_simple_offset_when_join_fails(self):
        ball = BRepPrimAPI_MakeSphere(20.0).Shape()
        with join_fails():
            hollow = modify.shell(ball, {'thickness': 3.0}, None)
        expected = 4 / 3 * 3.141592653589793 * (20 ** 3 - 17 ** 3)
        self.assertAlmostEqual(signed_volume(hollow), expected, delta=expected * 1e-4)
        self.assertEqual(count(hollow, TopAbs_SHELL), 2)

    def test_too_thick_wall_is_an_error_not_an_inverted_solid(self):
        box = BRepPrimAPI_MakeBox(40.0, 30.0, 20.0).Shape()
        with join_fails():
            with self.assertRaises(FeatureError):
                modify.shell(box, {'thickness': 12.0}, None)



class Walls(unittest.TestCase):
    def test_wall_sketch_splits_the_void(self):
        part = Part(self)
        part.box(100, 60, 40)                                               # x -50..50, y -30..30, z 0..40
        walls = part.sketch({'type': 'line', 'x1': 0, 'y1': -10, 'x2': 0, 'y2': 50},       # 竖着一整道
                            {'type': 'line', 'x1': 0, 'y1': 20, 'x2': 60, 'y2': 20}, plane='XZ')   # 右半边再横着一道
        part.do('shell', thickness=2, walls=walls)
        inside = 96 * 56 * 36 - 2 * 56 * 36 - 47 * 56 * 2                  # 横的那道在空腔里只有 x 1..48 那一段
        self.assertAlmostEqual(part.volume, 100 * 60 * 40 - inside, delta=1e-2)
        self.assertEqual(part.session.model['props']['bodies'], 1)

    def test_plain_shell_does_not_pick_up_the_last_sketch(self):
        part = Part(self)
        part.box(40, 30, 20)
        part.sketch({'type': 'line', 'x1': 0, 'y1': -5, 'x2': 0, 'y2': 25}, plane='XZ')
        part.do('shell', thickness=2)
        self.assertAlmostEqual(part.volume, 24000 - 36 * 26 * 16, delta=1e-3)

    def test_floating_part_counts_as_a_second_body(self):
        part = Part(self)
        part.box(40, 30, 20)
        self.assertEqual(part.session.model['props']['bodies'], 1)
        part.do('extrude', sketch=part.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 5, 'h': 5}, offset=50), distance=5)
        self.assertEqual(part.session.model['props']['bodies'], 2)

    def test_curved_wall_is_refused(self):
        part = Part(self)
        part.box(40, 30, 20)
        walls = part.sketch({'type': 'circle', 'cx': 0, 'cy': 10, 'r': 5}, plane='XZ')
        self.assertFalse(part.run('shell', thickness=2, walls=walls)['ok'])


if __name__ == '__main__':
    unittest.main()
