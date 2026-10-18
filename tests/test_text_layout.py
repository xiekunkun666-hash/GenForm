# -*- coding: utf-8 -*-
"""内核排字: 每个字按它自己的宽度往后排 (OCC 的 AdvanceX 只认刚加载的字形, 先取宽度会全是 0, 字叠成一团)。"""
import unittest

from genform.kernel.model import sketches
from genform.kernel.model.solids import bounds

FRAME = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
SHAPE = {'type': 'text', 'x': 0, 'y': 0, 'text': 'WIW', 'height': 20, 'font': 'Arial'}


def spans(faces):
    return [(bounds(face)[0][0], bounds(face)[1][0]) for face in faces]


class TextLayout(unittest.TestCase):
    def setUp(self):
        sketches._FONTS.clear()             # 新字体对象: 原来的写法在这里排出来全叠在 x=0

    def test_letters_follow_each_other_without_overlap(self):
        letters = spans(sketches._text_faces(SHAPE, FRAME))
        self.assertEqual(len(letters), 3)
        for (_, right), (left, _) in zip(letters, letters[1:]):
            self.assertLessEqual(right, left + 0.5)
        self.assertGreater(letters[2][0] - letters[1][0], 2.0)        # 窄的 I 之后紧跟着下一个 W
        self.assertGreater(letters[1][0] - letters[0][0], letters[2][0] - letters[1][0])   # W 比 I 宽

    def test_fresh_and_cached_font_lay_out_the_same(self):
        first = spans(sketches._text_faces(SHAPE, FRAME))
        sketches._text_faces(dict(SHAPE, text='EEE'), FRAME)            # 字体里最后加载的换成了别的字
        again = spans(sketches._text_faces(SHAPE, FRAME))
        for (a, b), (c, d) in zip(first, again):
            self.assertAlmostEqual(a, c, places=6)
            self.assertAlmostEqual(b, d, places=6)


if __name__ == '__main__':
    unittest.main()
