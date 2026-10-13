# -*- coding: utf-8 -*-
"""草图文本在编辑时的样子: 文本图形 → 字的轮廓折线 (界面进程用 Qt 的字体取字形)。

内核那边 (kernel/build.py 的 _text_faces) 用 OpenCascade 从同一个系统字体取字形, 排版两边都走
sketchgeom.text_layout — 同一个字体文件、同一套排版, 所以编辑时看到的字和拉伸出来的字是对得上的。
"""
from __future__ import annotations

import math

from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath

from . import sketchgeom

EM = 200.0          # 取字形时用的字号 (像素); 取出来再缩成 1 个单位高


class Outliner:
    def __init__(self):
        self._glyphs = {}           # (字体, 字) → (前进宽度, [折线...]), 都按字高 1 算

    def _glyph(self, font_name, letter):
        key = (font_name, letter)
        if key not in self._glyphs:
            font = QFont(font_name)
            font.setPixelSize(int(EM))
            font.setHintingPreference(QFont.PreferNoHinting)
            path = QPainterPath()
            path.addText(0, 0, font, letter)
            outlines = [[(point.x() / EM, -point.y() / EM) for point in polygon] for polygon in path.toSubpathPolygons()]
            self._glyphs[key] = (QFontMetricsF(font).horizontalAdvance(letter) / EM, outlines)
        return self._glyphs[key]

    def __call__(self, shape):
        text, height = str(shape.get('text', '')), float(shape.get('height', 10.0))
        font_name = str(shape.get('font') or sketchgeom.DEFAULT_FONT)
        glyphs = [self._glyph(font_name, letter) for letter in text]
        spots = sketchgeom.text_layout(shape, [advance * height for advance, _ in glyphs])
        lines = []
        for (_, outlines), (x, y, turn) in zip(glyphs, spots):
            cos, sin = math.cos(turn) * height, math.sin(turn) * height
            lines += [[(x + px * cos - py * sin, y + px * sin + py * cos) for px, py in outline] for outline in outlines]
        if not lines:               # 空文本: 留一小段基线, 不然点不中也看不见
            lines.append([(shape['x'], shape['y']), (shape['x'] + height, shape['y'])])
        return lines
