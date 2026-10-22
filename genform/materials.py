# -*- coding: utf-8 -*-
"""材质表: 名称 → 密度 (g/cm³) 和显示用的颜色。零件的材质存在文档的 props['material'] 里。

只是一张小表: 够算质量、够让零件看着像那种材料; 力学参数 (静力分析用) 在下面的 MECHANICS 里, 都是手册上的典型值。
"""
from __future__ import annotations

MATERIALS = [       # (名称, 密度 g/cm³, 颜色 #RRGGBB)
    ('普通碳钢', 7.85, '#8E97A3'),
    ('合金钢', 7.70, '#7F8894'),
    ('不锈钢 304', 7.93, '#B9C0C8'),
    ('铸铁', 7.20, '#6B6F76'),
    ('铝合金 6061', 2.70, '#C9CED6'),
    ('铝合金 7075', 2.81, '#C4CAD2'),
    ('45# 钢', 7.85, '#858C96'),
    ('黄铜', 8.50, '#C9A24A'),
    ('紫铜', 8.90, '#C07A4E'),
    ('钛合金 Ti-6Al-4V', 4.43, '#A8A39A'),
    ('ABS', 1.04, '#E6E1D3'),
    ('尼龙 PA12', 1.01, '#DDDAD2'),
    ('聚碳酸酯 PC', 1.20, '#C7D7E6'),
    ('PLA', 1.24, '#E9E4DA'),
    ('聚丙烯 PP', 0.91, '#2F3135'),
    ('PMMA 亚克力', 1.19, '#D9E4EC'),
    ('铸造铝合金 A356', 2.68, '#B8BDC4'),
    ('钢化玻璃', 2.50, '#2A3A48'),
    ('橡胶', 1.15, '#1E1F21'),
    ('皮革 + 海绵', 0.35, '#7A4A2C'),
]
NAMES = [name for name, _, _ in MATERIALS]
MECHANICS = {       # 名称 → (弹性模量 MPa, 泊松比, 屈服强度 MPa; 铸铁没有明显的屈服, 给的是抗拉强度)
    '普通碳钢': (210000, 0.29, 235), '合金钢': (210000, 0.28, 620), '不锈钢 304': (193000, 0.29, 215), '铸铁': (110000, 0.26, 200),
    '铝合金 6061': (68900, 0.33, 276), '铝合金 7075': (71700, 0.33, 503), '45# 钢': (209000, 0.29, 355), '黄铜': (100000, 0.34, 200), '紫铜': (117000, 0.34, 70),
    '钛合金 Ti-6Al-4V': (113800, 0.34, 880), 'ABS': (2200, 0.35, 40), '尼龙 PA12': (1700, 0.39, 48),
    '聚碳酸酯 PC': (2300, 0.37, 62), 'PLA': (3500, 0.36, 60), '聚丙烯 PP': (1500, 0.42, 30), 'PMMA 亚克力': (3000, 0.37, 70),
    '铸造铝合金 A356': (72400, 0.33, 165), '钢化玻璃': (70000, 0.22, 120), '橡胶': (5, 0.49, 15),
}
DEFAULT_MECHANICS = '普通碳钢'      # 没指定材质的零件做静力分析时按它算
APPEARANCES = ['#B9C3CF', '#8E97A3', '#E6E1D3', '#4C94FF', '#35A7A0', '#5FC38A', '#E2B43C', '#E98A3C', '#E0605A', '#B685E0',
               '#C9A24A', '#3C4148']     # 编辑外观里给的几个颜色


def density(name):
    return next((value for item, value, _ in MATERIALS if item == name), None)


def mechanics(name):
    """(弹性模量 MPa, 泊松比, 屈服强度 MPa); 表里没有的返回 None。"""
    return MECHANICS.get(name)


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
