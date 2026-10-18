# -*- coding: utf-8 -*-
"""装配体的物料清单 (BOM): 每种零件用了几件, 是标准件 (按规格网购)、外购总成, 还是要定制加工的非标件, 估算单价。

零件的类别和价钱从零件文件里各特征绑的工艺来 (评估 → 绑定工艺, 见 manufacturing.py): 全是标准件工艺的是标准件,
最贵的那道工艺是外购的是外购件, 其余都是非标件。同一个文件镜像摆的 (左右一对) 是另一个料号 (相反方位的件),
除非零件本身左右对称 (标准件、外购件按规格买, 不分左右)。
"""
from __future__ import annotations

import csv
import json
import os

KINDS = {'standard': '标准件', 'purchase': '外购件', 'custom': '非标件'}
_NOT_PARTS = {'sketch', 'plane', 'axis', 'point', 'curve', 'helix', 'coordinate'}


def describe(path):
    """零件文件 → {'kind', 'spec', 'process', 'material', 'unit' 每件估价 (元), 'bound' 绑没绑工艺}。读不了的当作非标件。"""
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {'kind': 'custom', 'spec': '', 'process': '', 'material': '', 'unit': 0.0, 'bound': False}
    processes = [feature['process'] for feature in data.get('features') or []
                 if feature.get('type') not in _NOT_PARTS and not feature.get('suppressed') and (feature.get('process') or {}).get('id')]
    material = (data.get('props') or {}).get('material') or ''
    if not processes:
        return {'kind': 'custom', 'spec': '', 'process': '', 'material': material, 'unit': 0.0, 'bound': False}
    main = max(processes, key=lambda process: float(process.get('cost') or 0.0))
    if main.get('id') == 'purchase':
        kind = 'purchase'
    elif all(process.get('standard') for process in processes):
        kind = 'standard'
    else:
        kind = 'custom'
    spec = next((process.get('spec') for process in processes if process.get('spec')), '')
    return {'kind': kind, 'spec': spec or '', 'process': main.get('name') or '', 'material': material,
            'unit': round(sum(float(process.get('cost') or 0.0) for process in processes), 2), 'bound': True}


def bill(parts):
    """装配体里的零件 [{'name', 'path', 'mirror'}...] → 清单的行 [{'name', 'path', 'mirror', 'count', 'kind', 'kind_name', 'spec',
    'process', 'material', 'unit', 'total', 'indices' 在装配体里是哪几个}...], 按类别 (非标 / 外购 / 标准) 再按名字排。"""
    rows, seen, known = [], {}, {}
    for index, part in enumerate(parts):
        path = part.get('path') or ''
        if path not in known:
            known[path] = describe(path) if path else {'kind': 'custom', 'spec': '', 'process': '', 'material': '', 'unit': 0.0,
                                                         'bound': False}
        info = known[path]
        handed = bool(part.get('mirror')) and info['kind'] == 'custom'      # 买来的件不分左右
        key = (os.path.normcase(os.path.abspath(path)) if path else '', handed)
        if key not in seen:
            name = part.get('name') or os.path.splitext(os.path.basename(path))[0]
            seen[key] = dict(info, name=name + ('（镜像件）' if handed else ''), path=path, mirror=handed, count=0, indices=[],
                             kind_name=KINDS[info['kind']])
            rows.append(seen[key])
        seen[key]['count'] += 1
        seen[key]['indices'].append(index)
    for row in rows:
        row['total'] = round(row['unit'] * row['count'], 2)
    order = {'custom': 0, 'purchase': 1, 'standard': 2}
    rows.sort(key=lambda row: (order[row['kind']], row['name']))
    return rows


def totals(rows):
    """→ {类别: {'types' 几种, 'count' 几件, 'cost' 合计}, 'all': ..., 'unbound': 没绑工艺的零件种数}。"""
    result = {kind: {'types': 0, 'count': 0, 'cost': 0.0} for kind in list(KINDS) + ['all']}
    for row in rows:
        for kind in (row['kind'], 'all'):
            result[kind]['types'] += 1
            result[kind]['count'] += row['count']
            result[kind]['cost'] = round(result[kind]['cost'] + row['total'], 2)
    result['unbound'] = sum(1 for row in rows if not row['bound'])
    return result


def write_csv(rows, path):
    """清单存成 CSV (Excel 直接能开: 带 BOM 头的 UTF-8)。"""
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['序号', '名称', '类别', '规格', '工艺', '材质', '数量', '单价 (元)', '小计 (元)', '文件'])
        for number, row in enumerate(rows, 1):
            writer.writerow([number, row['name'], row['kind_name'], row['spec'], row['process'], row['material'], row['count'],
                             f'{row["unit"]:.2f}', f'{row["total"]:.2f}', row['path']])
