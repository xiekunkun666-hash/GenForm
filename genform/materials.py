# -*- coding: utf-8 -*-
"""材质表: 名称 → 密度 (g/cm³) 和显示用的颜色。零件的材质存在文档的 props['material'] 里。

只是一张小表: 够算质量、够让零件看着像那种材料。没有力学参数 (还没有仿真要用它们)。
"""
from __future__ import annotations

MATERIALS = [       # (名称, 密度 g/cm³, 颜色 #RRGGBB)
    ('普通碳钢', 7.85, '#8E97A3'),
    ('合金钢', 7.70, '#7F8894'),
    ('不锈钢 304', 7.93, '#B9C0C8'),
    ('铸铁', 7.20, '#6B6F76'),
    ('铝合金 6061', 2.70, '#C9CED6'),
    ('黄铜', 8.50, '#C9A24A'),
    ('紫铜', 8.90, '#C07A4E'),
    ('钛合金 Ti-6Al-4V', 4.43, '#A8A39A'),
    ('ABS', 1.04, '#E6E1D3'),
    ('尼龙 PA12', 1.01, '#DDDAD2'),
    ('聚碳酸酯 PC', 1.20, '#C7D7E6'),
    ('PLA', 1.24, '#E9E4DA'),
]
NAMES = [name for name, _, _ in MATERIALS]
APPEARANCES = ['#B9C3CF', '#8E97A3', '#E6E1D3', '#4C94FF', '#35A7A0', '#5FC38A', '#E2B43C', '#E98A3C', '#E0605A', '#B685E0',
               '#C9A24A', '#3C4148']     # 编辑外观里给的几个颜色


def density(name):
    return next((value for item, value, _ in MATERIALS if item == name), None)


def color(name):
    return next((value for item, _, value in MATERIALS if item == name), None)


def rgb(text):
    """'#RRGGBB' → (r, g, b) 0~1; 不是这种写法返回 None。"""
    text = str(text or '').lstrip('#')
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[index:index + 2], 16) / 255.0 for index in (0, 2, 4))
    except ValueError:
        return None
