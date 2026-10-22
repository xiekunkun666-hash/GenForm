# -*- coding: utf-8 -*-
"""尺寸链 / 高度分配: 沿一根轴 (默认 Z) 把装配体在每个零件的上下端切开, 一段段列出多高、里面主要是哪几个零件 —
"怎么这么高" 一眼看出高度都花在哪了。

做法: 每个零件摆好以后的包围盒沿这根轴的范围; 所有零件的上下端排好就是分段点; 每一段里横截面 (包围盒在另外两个方向上的面积)
最大的几个零件是 "主角"; 相邻两段主角一样的合成一段 (不然几十个零件切出一百多段)。只用包围盒, 不求交 — 很快,
但转子杯这种空心件按它整个外形算 (它占着那一段的高度, 不管中间是不是空的)。
"""
from __future__ import annotations

import numpy as np

AXES = {'X': 0, 'Y': 1, 'Z': 2}
MAIN = 2                        # 每段按横截面取前几个当主角 (合并相邻段时比它们)
SHOWN = 4                       # 每段最多列几个零件名
TINY = 0.05                     # 比这还薄的段并进相邻的段 (mm)
SLENDER = 3.0                   # 横截面最窄处比它还细的 (线、棒): 排主角时往后放


def stack(features, upto, data):
    """内核里算 (要读零件文件): data = {'parts', 'axis'}。界面里已经有每个零件的网格包围盒时直接用 layers(), 不用走内核。"""
    from .assembly import _placed_box, _record
    rows = []
    for number, part in enumerate(data.get('parts') or []):
        low, high = _placed_box(_record(part, features, upto), part)
        rows.append({'index': number, 'name': part.get('name') or f'零件{number + 1}', 'low': low, 'high': high})
    return layers(rows, data.get('axis', 'Z'))


def layers(rows, axis='Z'):
    """rows: [{'index', 'name', 'low', 'high' 摆好以后的包围盒}...] →
       {'axis', 'low', 'high', 'total', 'segments': [{'from', 'to', 'height', 'parts': [名字...], 'indices'}...] 从低到高,
        'parts': [{'index', 'name', 'from', 'to', 'height'}...]}。"""
    axis = AXES.get(str(axis).upper(), 2)
    others = [index for index in range(3) if index != axis]
    table = []
    for row in rows:
        low, high = np.asarray(row['low'], float), np.asarray(row['high'], float)
        size = high - low
        across = (float(size[others[0]]), float(size[others[1]]))
        weight = across[0] * across[1] * (1.0 if min(across) >= SLENDER else 0.01)     # 细长的线、棒往后排
        table.append({'index': row['index'], 'name': row['name'], 'from': float(low[axis]), 'to': float(high[axis]),
                      'height': float(size[axis]), 'area': weight})
    rows = table
    if not rows:
        return {'axis': 'XYZ'[axis], 'low': 0.0, 'high': 0.0, 'total': 0.0, 'segments': [], 'parts': []}
    cuts = sorted({round(value, 3) for row in rows for value in (row['from'], row['to'])})
    segments = []
    for bottom, top in zip(cuts[:-1], cuts[1:]):
        if top - bottom <= 1e-9:
            continue
        middle = (bottom + top) / 2
        inside = sorted((row for row in rows if row['from'] <= middle <= row['to']), key=lambda row: -row['area'])
        segments.append({'from': bottom, 'to': top, 'inside': inside})
    merged = []
    for segment in segments:
        main = tuple(row['index'] for row in segment['inside'][:MAIN])
        if merged and (merged[-1]['main'] == main or segment['to'] - segment['from'] < TINY or
                       merged[-1]['to'] - merged[-1]['from'] < TINY):
            last = merged[-1]
            last['to'] = segment['to']
            known = {row['index'] for row in last['inside']}
            last['inside'] += [row for row in segment['inside'] if row['index'] not in known]
            if segment['to'] - segment['from'] >= last.get('longest', 0.0):
                last['main'], last['longest'] = main, segment['to'] - segment['from']
            continue
        merged.append(dict(segment, main=main, longest=segment['to'] - segment['from']))
    out = []
    for segment in merged:
        names, seen = [], set()
        for row in sorted(segment['inside'], key=lambda row: -row['area']):
            base = row['name'].split(' #')[0]           # 同一种件 (螺丝 #1~#6) 只列一次
            if base not in seen:
                seen.add(base)
                names.append(base)
        out.append({'from': segment['from'], 'to': segment['to'], 'height': segment['to'] - segment['from'], 'parts': names[:SHOWN],
                    'indices': [row['index'] for row in segment['inside']]})
    low, high = min(row['from'] for row in rows), max(row['to'] for row in rows)
    return {'axis': 'XYZ'[axis], 'low': low, 'high': high, 'total': high - low, 'segments': out,
            'parts': [{key: row[key] for key in ('index', 'name', 'from', 'to', 'height')} for row in rows]}
