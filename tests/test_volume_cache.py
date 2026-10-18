# -*- coding: utf-8 -*-
"""体积积分: 解析曲面先用普通积分, 带样条面的直接用自适应积分; 拼起来的形状按块记; 显示的质量属性复用校验积过的。"""
import math
import unittest
from unittest.mock import patch

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt

from genform.kernel.model import display
from genform.kernel.ops import solid_validation
from genform.session import Session


def run(session, command, **args):
    replies = []
    session.execute(command, args, replies.append)
    return replies[0]


def box(size, corner=(0, 0, 0)):
    return BRepPrimAPI_MakeBox(gp_Pnt(*corner), size, size, size).Shape()


class VolumeTiers(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(solid_validation, '_VOLUMES', []))

    def test_analytic_shape_tries_plain_integration_first(self):
        self.assertEqual(solid_validation._tiers(box(10)), (False, True))

    def test_spline_shape_goes_straight_to_adaptive(self):
        session = Session()
        square = [[-20, -20], [20, -20], [20, 20], [-20, 20]]
        first = run(session, 'sketch', plane='XY', offset=0, shapes=[{'type': 'spline', 'points': square, 'closed': True}])
        second = run(session, 'sketch', plane='XY', offset=30, shapes=[{'type': 'circle', 'r': 12}])
        run(session, 'loft', sketches=[first['id'], second['id']])
        from genform.kernel.model import rebuild
        self.assertEqual(solid_validation._tiers(rebuild._STEPS[-1][1]), (True,))

    def test_compound_volume_is_sum_of_its_solids(self):
        parts = solid_validation._compound([box(10), box(5, (20, 0, 0))])
        self.assertAlmostEqual(solid_validation.signed_volume(parts), 1125.0, places=6)
        volume, centre = solid_validation.mass(parts)
        self.assertAlmostEqual(centre[0], (1000 * 5 + 125 * 22.5) / 1125, places=6)

    def test_display_properties_reuse_cached_integral(self):
        shape = box(10)
        solid_validation.signed_volume(shape)
        with patch.object(solid_validation, '_face_integral') as integrate:
            props = display.properties(shape)
        integrate.assert_not_called()
        self.assertAlmostEqual(props['volume'], 1000.0, places=6)
        for axis in range(3):
            self.assertAlmostEqual(props['center_of_mass'][axis], 5.0, places=6)

    def test_unchanged_faces_are_not_integrated_again(self):
        from genform.kernel.model import solids
        body = box(10)
        solid_validation.signed_volume(body, True)
        calls = []
        original = solid_validation._face_integral
        with patch.object(solid_validation, '_face_integral', side_effect=lambda *a: calls.append(a) or original(*a)):
            result = solids.combine(body, box(4, (10, 3, 3)), 'add')            # 贴在一个面上的小方块
            solid_validation.signed_volume(result, True)
        self.assertLess(len(calls), 40)                                    # 新面 + 小方块的面, 不是每次全部重积
        self.assertAlmostEqual(solid_validation.signed_volume(result), 1064.0, places=6)


class OverlappingTools(unittest.TestCase):
    def test_overlapping_pieces_of_one_tool_fuse_correctly(self):
        from genform.kernel.model import solids
        body = box(10)
        tool = solid_validation._compound([box(10, (20, 0, 0)), box(10, (25, 0, 0))])     # 两块互相重叠
        result = solids.combine(body, tool, 'add')
        self.assertAlmostEqual(solid_validation.signed_volume(result), 1000 + 1500, places=4)
        cut = solids.combine(box(40, (0, -15, -15)), tool, 'cut')
        self.assertAlmostEqual(solid_validation.signed_volume(cut), 64000 - 1500, places=3)


if __name__ == '__main__':
    unittest.main()
