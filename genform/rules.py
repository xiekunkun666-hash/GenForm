# -*- coding: utf-8 -*-
"""设计规则 (像 PCB 的 DRC 规则): 设计检查按它们判断加工、装配会不会出问题。

默认值存在用户设置里 (设置 → 设计规则), 所有零件共用; 某个零件要不一样的, 存在它自己的文档属性 props['rules'] 里,
优先用零件自己的。
"""
from __future__ import annotations

# (键, 名称, 单位, 默认值, 最小, 最大, 说明)
RULES = [
    ('tolerance', '加工公差 (±)', 'mm', 0.1, 0.001, 5.0,
     '零件按这个公差做出来: 两个件之间的间隙、压入量都要比它大, 不然做出来可能撞上或者连不上'),
    ('clearance', '件与件最小间隙', 'mm', 0.5, 0.0, 50.0,
     '两个不该碰的件之间至少留这么多; 间隙大于 0 又小于它的, 两个件都标红'),
    ('overlap', '连接最小压入量', 'mm', 0.3, 0.0, 50.0,
     '两个要连在一起的件 (焊、粘、压装) 至少要压进去这么多; 只贴着或压得比它浅的, 两个件都标红'),
    ('min_wall', '最小壁厚', 'mm', 1.0, 0.05, 50.0, '比它薄的板、壁报警告 (各工艺自己还有下限, 见工艺表)'),
    ('min_hole', '最小孔径', 'mm', 1.0, 0.05, 50.0, '比它小的孔报警告: 钻头太细容易断'),
    ('hole_ratio', '孔最大深径比', '', 10.0, 1.0, 100.0, '孔深 ÷ 孔径超过它的报警告: 普通钻头排屑困难, 要枪钻或改成两头钻'),
    ('corner_radius', '铣削内角最小圆角', 'mm', 1.0, 0.0, 50.0,
     '铣出来的槽、窗内角至少要有铣刀半径大的圆角; 画成尖角又绑了 CNC 的, 报警告'),
    ('min_text', '最小字高', 'mm', 2.0, 0.1, 100.0, '比它矮的字刻不清楚、铸不出来'),
    ('batch', '生产数量', '件', 1, 1, 10000000, '绑定工艺时按这个数量摊模具费: 做 1 件和做 10 万件, 性价比最好的工艺不一样'),
    ('pair_limit', '间隙检查最多比较的件数', '件', 600, 10, 5000, '零件很多时, 只比较离得近的前这么多对 (太多会算很久)'),
]
DEFAULTS = {key: default for key, _, _, default, _, _, _ in RULES}
_LIMITS = {key: (low, high) for key, _, _, _, low, high, _ in RULES}


def clean(values):
    """规则字典 → 只留认识的键、数字夹在范围里。"""
    out = {}
    for key, value in (values or {}).items():
        if key not in DEFAULTS:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        low, high = _LIMITS[key]
        number = min(max(number, low), high)
        out[key] = int(round(number)) if isinstance(DEFAULTS[key], int) else number
    return out


def effective(settings_rules=None, document_rules=None):
    """默认值 ← 用户设置 ← 零件自己的。"""
    rules = dict(DEFAULTS)
    rules.update(clean(settings_rules))
    rules.update(clean(document_rules))
    return rules


def table():
    return [{'key': key, 'label': label, 'unit': unit, 'default': default, 'min': low, 'max': high, 'help': text}
            for key, label, unit, default, low, high, text in RULES]
