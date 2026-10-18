# -*- coding: utf-8 -*-
"""草图里光标停在放下的尺寸上: 记下是哪个尺寸 (视图据此换四向箭头光标), 它的线用悬停色画。"""
import unittest

from genform import sketchgeom as geom
from tests.test_sketch_more import PIXEL, editor


def dimensioned():
    made = editor('select')
    made.shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 40, 'y2': 0}, {'type': 'line', 'x1': 0, 'y1': 15, 'x2': 40, 'y2': 15}]
    made.dims = [{'a': 0, 'pa': 'e0', 'b': 1, 'pb': 'e1', 'mode': 'h', 'place': [20, 30], 'ta': 'line', 'tb': 'line'}]
    return made


class DimensionHover(unittest.TestCase):
    def test_hovering_a_dimension_lights_it(self):
        made = dimensioned()
        made.move((20, 30), PIXEL)                      # 停在数字上
        self.assertEqual((made.hover_dim, made.hover), (0, None))
        states = {line[-1] for line in made.drawing()[0]}
        self.assertIn(1, states)
        self.assertNotIn(5, states)                     # 尺寸线全换成悬停色
        made.move((20, 0.2), PIXEL)                     # 移到线上: 尺寸不亮了, 亮的是线
        self.assertIsNone(made.hover_dim)
        self.assertIn(5, {line[-1] for line in made.drawing()[0]})

    def test_dragging_keeps_dimension_hot_and_tool_change_clears(self):
        made = dimensioned()
        made.move((20, 30), PIXEL)
        made.press((20, 30), PIXEL)
        made.move((25, 45), PIXEL)
        self.assertEqual(made.hover_dim, 0)             # 拖着的时候光标一直是四向箭头
        made.release((25, 45), PIXEL)
        made.set_tool('line')
        self.assertIsNone(made.hover_dim)

class SizedColour(unittest.TestCase):
    def test_only_the_dimensioned_rect_side_turns_black(self):
        made = editor('select')
        made.shapes = [{'type': 'rect', 'cx': 20, 'cy': 10, 'w': 40, 'h': 20}, {'type': 'line', 'x1': 0, 'y1': 30, 'x2': 40, 'y2': 30}]
        made.dims = [{'a': 0, 'pa': 's0', 'b': None, 'pb': None, 'mode': 'a', 'place': [20, -8], 'ta': 'rect', 'single': 'len'},
                     {'a': 1, 'pa': None, 'b': None, 'pb': None, 'mode': 'a', 'place': [20, 38], 'ta': 'line', 'single': 'len'}]
        lines = made.drawing()[0]
        black = {(tuple(map(round, a)), tuple(map(round, b))) for a, b, state in lines if state == 4}
        corners = [tuple(map(round, corner)) for corner in geom.vertices(made.shapes[0])]
        self.assertEqual(black, {(corners[0], corners[1]), ((0, 30), (40, 30))})     # 矩形只有标了的那条边, 直线整条
        self.assertTrue(any(state == 0 for *_, state in lines))                # 矩形别的边还是蓝的


if __name__ == '__main__':
    unittest.main()
