# -*- coding: utf-8 -*-
"""空心件的三种方式 (ops/hollow.py): void 挖空腔、fill 填空腔、pocket 钣金凹槽; 做完以后普通的切除、加料照常能做。"""
import math
import unittest

from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.TopAbs import TopAbs_IN, TopAbs_SHELL
from OCP.gp import gp_Pnt

from genform.kernel.model import rebuild
from genform.kernel.ops import modify
from tests.test_features import Part

OUTER = 100 * 60 * 40
CAVITY = 96 * 56 * 36


def hollow_box(case):
    part = Part(case)
    part.box(100, 60, 40)                                                   # x -50..50, y -30..30, z 0..40
    inner = part.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 96, 'h': 56}, offset=2)
    part.do('extrude', sketch=inner, distance=36, op='void')
    return part


def body_of(part):
    return [step for step in rebuild._STEPS if step[1] is not rebuild._MISSING][-1][1]


def inside(part, *point):
    return BRepClass3d_SolidClassifier(body_of(part), gp_Pnt(*point), 1e-6).State() == TopAbs_IN


class Void(unittest.TestCase):
    def test_void_leaves_a_two_millimetre_skin(self):
        part = hollow_box(self)
        self.assertAlmostEqual(part.volume, OUTER - CAVITY, delta=1e-3)
        self.assertEqual(len(modify._explore(body_of(part), TopAbs_SHELL)), 2)
        self.assertTrue(inside(part, 0, 0, 1) and not inside(part, 0, 0, 20))

    def test_overlapping_voids_merge(self):
        part = hollow_box(self)
        more = part.sketch({'type': 'rect', 'cx': 30, 'cy': 0, 'w': 20, 'h': 20}, offset=10)
        part.do('extrude', sketch=more, distance=10, op='void')               # 整个在原来的空腔里: 体积不变
        self.assertAlmostEqual(part.volume, OUTER - CAVITY, delta=1e-3)
        self.assertEqual(len(modify._explore(body_of(part), TopAbs_SHELL)), 2)

    def test_void_poking_out_is_an_error(self):
        part = Part(self)
        part.box(100, 60, 40)
        inner = part.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 120, 'h': 56}, offset=2)
        self.assertFalse(part.run('extrude', sketch=inner, distance=36, op='void')['ok'])


class Fill(unittest.TestCase):
    def test_floor_splits_the_cavity_and_stays_inside(self):
        part = hollow_box(self)
        floor = part.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 300, 'h': 300}, offset=19)    # 比车身大得多
        part.do('extrude', sketch=floor, distance=2, op='fill')
        self.assertAlmostEqual(part.volume, OUTER - CAVITY + 96 * 56 * 2, delta=1e-3)
        self.assertEqual(part.size, [100, 60, 40])                          # 没有伸出去
        self.assertEqual(len(modify._explore(body_of(part), TopAbs_SHELL)), 3)  # 上下两格

    def test_fill_needs_a_cavity(self):
        part = Part(self)
        part.box(100, 60, 40)
        slab = part.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 20, 'h': 20}, offset=19)
        reply = part.run('extrude', sketch=slab, distance=2, op='fill')
        self.assertFalse(reply['ok'])
        self.assertIn('空腔', reply['error'])


class Pocket(unittest.TestCase):
    def test_pocket_in_a_hollow_part_gets_a_wall_and_a_bottom(self):
        part = hollow_box(self)
        hole = part.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 10}, offset=40)
        part.do('extrude', sketch=hole, distance=15, reverse=True, op='pocket')     # 槽底在 z=25
        self.assertFalse(inside(part, 0, 0, 30))                            # 槽里是空的
        self.assertTrue(inside(part, 11, 0, 30))                            # 槽壁 (r 10..12)
        self.assertTrue(inside(part, 0, 0, 24))                             # 槽底 (z 23..25)
        self.assertFalse(inside(part, 30, 0, 30))                           # 别处还是空腔
        self.assertEqual(part.session.model['props']['bodies'], 1)
        removed = OUTER - CAVITY - part.volume                              # 顶上的车皮切掉一个圆, 加了槽壁和槽底
        self.assertLess(removed, 0)

    def test_pocket_wall_follows_the_wall_parameter(self):
        part = hollow_box(self)
        hole = part.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 10}, offset=40)
        part.do('extrude', sketch=hole, distance=15, reverse=True, op='pocket', wall=4)
        self.assertTrue(inside(part, 13.5, 0, 30))
        self.assertFalse(inside(part, 14.5, 0, 30))

    def test_several_pockets_in_one_sketch(self):
        part = hollow_box(self)
        holes = part.sketch({'type': 'circle', 'cx': -25, 'cy': 0, 'r': 8}, {'type': 'circle', 'cx': 25, 'cy': 0, 'r': 8}, offset=40)
        part.do('extrude', sketch=holes, distance=15, reverse=True, op='pocket')
        for x in (-25, 25):
            self.assertFalse(inside(part, x, 0, 30))
            self.assertTrue(inside(part, x + 9, 0, 30))

    def test_pocket_on_a_solid_part_is_a_plain_cut(self):
        part = Part(self)
        part.box(100, 60, 40)
        hole = part.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 10}, offset=40)
        part.do('extrude', sketch=hole, distance=15, reverse=True, op='pocket')
        self.assertAlmostEqual(part.volume, OUTER - math.pi * 100 * 15, delta=1e-2)


class AfterHollowing(unittest.TestCase):
    def test_window_cut_and_parts_still_work(self):
        part = hollow_box(self)
        window = part.sketch({'type': 'rect', 'cx': 20, 'cy': 0, 'w': 30, 'h': 20}, offset=40)
        part.do('extrude', sketch=window, distance=5, reverse=True, op='cut')    # 切穿顶上的车皮
        self.assertAlmostEqual(part.volume, OUTER - CAVITY - 30 * 20 * 2, delta=1e-3)
        seat = part.sketch({'type': 'rect', 'cx': -20, 'cy': 0, 'w': 20, 'h': 20}, offset=1)
        part.do('extrude', sketch=seat, distance=10)                         # 压在底板上的零件
        self.assertAlmostEqual(part.volume, OUTER - CAVITY - 30 * 20 * 2 + 20 * 20 * 9, delta=1e-3)
        self.assertEqual(part.session.model['props']['bodies'], 1)

    def test_mirror_copies_a_pocket_with_its_wall(self):
        part = hollow_box(self)
        hole = part.sketch({'type': 'circle', 'cx': 25, 'cy': 0, 'r': 8}, offset=40)
        pocket = part.do('extrude', sketch=hole, distance=15, reverse=True, op='pocket', wall=3)
        part.do('mirror', features=[pocket], plane='YZ')
        self.assertFalse(inside(part, -25, 0, 30))
        self.assertTrue(inside(part, -25 - 10, 0, 30))                       # 镜像过去的槽壁也是 3 mm (r 8..11)


if __name__ == '__main__':
    unittest.main()
