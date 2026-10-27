# -*- coding: utf-8 -*-
"""以前悄悄出错、检查也看不出来的几处: 草图里共边的矩形被当成孔挖掉、正好等于最小间隙也报 "太近"、
删了孔以后留在原处的标准件只报 "干涉"、自己写的检查脚本和界面上的检查结果对不上。"""
import os
import tempfile
import unittest
from unittest.mock import patch

from genform import asm_rules
from genform.kernel import assembly
from genform.session import Session
from tests.test_assembly_parts import Files, ask
from tests.test_features import Part


class SketchNesting(unittest.TestCase):
    def area(self, *shapes):
        part = Part(self)
        sketch = part.sketch(*shapes)
        part.do('extrude', sketch=sketch, distance=1.0)
        return round(part.volume, 3)

    def test_rects_sharing_an_edge_are_both_solid(self):
        # 轴承的外圈 / 滚珠带 / 内圈画成三个挨着的矩形: 以前第一个点压在共边上, 里外全凭浮点误差, 中间那块被当成孔
        self.assertEqual(self.area({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 10, 'h': 10},
                                   {'type': 'rect', 'cx': 10.0000000001, 'cy': 0, 'w': 10, 'h': 10},
                                   {'type': 'rect', 'cx': 20, 'cy': 0, 'w': 10, 'h': 10}), 300.0)

    def test_rect_touching_the_edge_from_inside_is_a_notch(self):
        for cy in (0.0, -3.0):          # 第一个点压不压在外框上, 结果都一样
            self.assertEqual(self.area({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 10, 'h': 10},
                                       {'type': 'rect', 'cx': 2.5, 'cy': cy, 'w': 5, 'h': 4}), 80.0)

    def test_rings_still_alternate(self):
        self.assertAlmostEqual(self.area({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 10}, {'type': 'circle', 'cx': 0, 'cy': 0, 'r': 6},
                                         {'type': 'circle', 'cx': 0, 'cy': 0, 'r': 3}), 229.336, places=2)


class GapAtTheLimit(unittest.TestCase):
    def test_exactly_the_minimum_clearance_is_not_too_close(self):
        files = Files(self)
        parts = [{'name': '下', 'path': files.block('下')}, {'name': '上', 'path': files.block('上', z=10.5, w=10, h=10)},
                 {'name': '近', 'path': files.block('近', z=10.3, cx=15, w=4, h=4)}]
        with patch.dict(os.environ, {'GENFORM_CACHE': 'off'}):
            result, error = ask(Session(), 'contacts', {'parts': parts, 'rules': {'tolerance': 0.1, 'clearance': 0.5}})
        self.assertIsNone(error)
        gaps = {tuple(pair['names']) for pair in result['pairs'] if pair['kind'] == 'gap'}
        self.assertEqual(gaps, {('下', '近')})


class Orphans(unittest.TestCase):
    def test_buried_standard_part_is_an_error(self):
        pairs = [{'kind': 'clash', 'a': 0, 'b': 1, 'volume': 40.0, 'point': [0, 0, 0]},     # 堵头整个埋在壳体里
                 {'kind': 'clash', 'a': 0, 'b': 2, 'volume': 0.5, 'point': [1, 0, 0]}]      # 销压配: 只压进去一点
        issues = asm_rules.orphans(pairs, ['custom', 'standard', 'standard'], ['壳体', '钢珠堵头', '定位销'],
                                   [{'volume': 9000.0}, {'volume': 50.0}, {'volume': 60.0}])
        self.assertEqual([item['code'] for item in issues], ['orphan'])
        self.assertEqual(issues[0]['features'], ['part:1', 'part:0'])

    def test_custom_parts_are_left_to_the_clash_rule(self):
        pairs = [{'kind': 'clash', 'a': 0, 'b': 1, 'volume': 40.0, 'point': None}]
        self.assertEqual(asm_rules.orphans(pairs, ['custom', 'custom'], ['甲', '乙'], [{'volume': 50.0}, {'volume': 50.0}]), [])


class CommandLine(unittest.TestCase):
    def test_runs_the_same_check_as_the_window(self):
        files = Files(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        base = files.block('底板', bind=True)
        top = files.block('上面的块', z=10, w=10, h=10, bind=True)
        loose = files.block('飘着的', z=60, w=4, h=4, bind=True)
        where = os.path.join(files.folder.name, 'a.gasm')
        import json
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump({'format': 'genform-assembly', 'parts': [{'file': os.path.basename(path), 'move': [0, 0, 0], 'turn': [0, 0, 0]}
                                                               for path in (base, top, loose)]}, handle)
        from genform import check_cli
        with patch.dict(os.environ, {'GENFORM_SETTINGS': os.path.join(folder.name, 'settings.json')}):
            issues = check_cli.run(where)
        floating = [item for item in issues if item['code'] == 'floating']
        self.assertEqual([item['names'] for item in floating], [['飘着的']])
        self.assertTrue(any(item['code'].startswith('bom_') for item in issues))


if __name__ == '__main__':
    unittest.main()
