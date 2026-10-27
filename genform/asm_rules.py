"""装配体设计检查里 "件与件之间" 以外的几条规则 (纯函数, 输入是检查的结果和零件的资料, 输出是日志条目):
- 电化学腐蚀: 两种金属贴着, 电位差 (阳极指数) 超过 GALVANIC_LIMIT — 铝和不锈钢 / 铜、钢和铜;
- 紧固件没起作用: 标准件 (螺栓、螺丝) 只贴着一个件 — 没把两个件连起来;
- 孤立的标准件: 螺丝、销、堵头大半截埋在别的件的实料里 — 它原来装的孔被删了 / 挪了, 件还留在原处;
- 重复摆放: 同一个零件在同一个位置摆了两次 (复制多了);
- 外购件没报价、标准件没写规格: 物料清单算不准 / 采购不知道买什么;
- 重量和重心: 整套多重、重心在哪, 左右偏得多了提醒;
- 运动干涉: 运动副开到某个角度时跟着动的件撞上别的件。"""
from __future__ import annotations

import json

from . import checks, materials

# 阳极指数 (伏, 越大越容易被腐蚀; 参考 MIL-STD-889 的分组): 两个贴着的金属差超过 0.25 V (户外、潮湿) 就要隔开
ANODIC = {'铝合金 6061': 0.90, '铸造铝合金 A356': 0.90, '普通碳钢': 0.85, '合金钢': 0.85, '铸铁': 0.85,
          '不锈钢 304': 0.50, '黄铜': 0.40, '紫铜': 0.35, '钛合金 Ti-6Al-4V': 0.15}
GALVANIC_LIMIT = 0.25
OFF_CENTRE = 0.02               # 重心偏到总宽的 2% 以外: 左右不平衡


def galvanic(pairs, metal_of, names):
    """贴着 / 压着的金属件, 阳极指数差太大 → 警告 (同一对材料只报一条, 列出是哪几处)。"""
    groups = {}
    for pair in pairs:
        if pair['kind'] not in ('touch', 'clash'):
            continue
        first, second = metal_of(pair['a']), metal_of(pair['b'])
        if first not in ANODIC or second not in ANODIC or first == second:
            continue
        gap = abs(ANODIC[first] - ANODIC[second])
        if gap > GALVANIC_LIMIT:
            key = tuple(sorted((first, second)))
            groups.setdefault(key, (gap, []))[1].append(pair)
    issues = []
    for (first, second), (gap, rows) in sorted(groups.items()):
        where = '、'.join(f'{names[row["a"]]} ↔ {names[row["b"]]}' for row in rows[:4]) + ('…' if len(rows) > 4 else '')
        issues.append(checks._issue('warning', 'galvanic', f'电化学腐蚀：{first} 贴着 {second}',
                                    f'两种金属差 {gap:.2f} V（超过 {GALVANIC_LIMIT} V），潮湿时 {first if ANODIC[first] > ANODIC[second] else second}'
                                    f' 会被腐蚀：中间加绝缘垫片 / 涂层，或换材料。{len(rows)} 处：{where}',
                                    sorted({f'part:{row[key]}' for row in rows for key in ('a', 'b')}), rows[0].get('point')))
    return issues


def fasteners(pairs, kinds, names):
    """标准件 (螺栓、螺丝、销) 只贴着一个件: 它没把两个件连起来 → 警告。"""
    touching = {}
    for pair in pairs:
        if pair['kind'] in ('touch', 'clash'):
            touching.setdefault(pair['a'], set()).add(pair['b'])
            touching.setdefault(pair['b'], set()).add(pair['a'])
    lonely = [index for index, kind in enumerate(kinds) if kind == 'standard' and len(touching.get(index, ())) < 2]
    if not lonely:
        return []
    shown = '、'.join(names[index] for index in lonely[:6]) + ('…' if len(lonely) > 6 else '')
    return [checks._issue('warning', 'fastener', f'{len(lonely)} 个紧固件没起作用',
                          f'{shown}：只贴着一个件（或一个都没贴着），没把两个件连在一起——长度不够、孔没对上，或者放错了地方',
                          [f'part:{index}' for index in lonely])]


ORPHAN_SHARE = 0.25             # 标准件有这么多体积埋在别的件的实料里: 不是配合紧, 是孔没了


def orphans(pairs, kinds, names, props):
    """标准件 (螺丝、销、堵头) 和别的件干涉, 压进去的体积占了它自己的一大块 → 报错: 它装的那个孔已经不在了
    (删了走线孔, 堵孔的钢珠还留着), 单看 "干涉" 两个字想不到是这个原因。props = mass_props 的结果 (每件的体积)。"""
    buried = {}
    for pair in pairs:
        if pair['kind'] != 'clash':
            continue
        for mine, other in ((pair['a'], pair['b']), (pair['b'], pair['a'])):
            if mine < len(kinds) and kinds[mine] == 'standard':
                buried.setdefault(mine, []).append((other, pair['volume'], pair.get('point')))
    issues = []
    for index, rows in sorted(buried.items()):
        own = props[index]['volume'] if index < len(props) and props[index].get('volume') else 0.0
        volume = sum(row[1] for row in rows)
        if own <= 0 or volume < own * ORPHAN_SHARE:
            continue
        hosts = '、'.join(names[row[0]] for row in rows)
        issues.append(checks._issue('error', 'orphan', f'孤立的标准件：{names[index]}',
                                    f'{volume / own:.0%} 的体积埋在 {hosts} 的实料里：它装的孔多半被删了或挪了，件还留在原处——'
                                    f'删掉这个件，或把孔补回来', [f'part:{index}'] + [f'part:{row[0]}' for row in rows], rows[0][2]))
    return issues


def duplicates(parts):
    """同一个零件在同一个位置摆了两次 → 报错 (多半是复制多了; 两个一模一样的件完全重在一起)。"""
    seen, rows = {}, []
    for index, part in enumerate(parts):
        key = json.dumps([part.get('path') or '', [round(float(v), 3) for v in part.get('move', (0, 0, 0))],
                          [round(float(v), 3) for v in part.get('turn', (0, 0, 0))], bool(part.get('mirror'))])
        if key in seen:
            rows.append((seen[key], index))
        else:
            seen[key] = index
    return [checks._issue('error', 'duplicate', f'重复摆放：{parts[second]["name"]}',
                          f'和“{parts[first]["name"]}”是同一个零件、摆在同一个位置，完全重在一起：删掉多的那个',
                          [f'part:{first}', f'part:{second}']) for first, second in rows]


def bill_gaps(rows):
    """物料清单里: 外购件没报价 (价钱是 0)、标准件没写规格。"""
    issues = []
    unpriced = [row for row in rows if row['kind'] == 'purchase' and not row['unit']]
    if unpriced:
        issues.append(checks._issue('warning', 'no_price', f'{len(unpriced)} 种外购件没报价',
                                    '、'.join(row['name'] for row in unpriced[:8]) + '：打开零件给“外购”工艺填上报价，成本才算得准',
                                    [f'part:{row["indices"][0]}' for row in unpriced]))
    nameless = [row for row in rows if row['kind'] == 'standard' and not row['spec']]
    if nameless:
        issues.append(checks._issue('info', 'no_spec', f'{len(nameless)} 种标准件没写规格',
                                    '、'.join(row['name'] for row in nameless[:8]) + '：写上规格（比如 M6×20 GB/T 5783），采购照着买',
                                    [f'part:{row["indices"][0]}' for row in nameless]))
    return issues


def mass(props, material_of, names, size):
    """重量和重心: props = 内核的 mass_props ([{'volume', 'centre'}...]), size = 整套包围盒的长宽高。"""
    total, moment, missing = 0.0, [0.0, 0.0, 0.0], []
    for index, row in enumerate(props):
        density = materials.density(material_of(index))
        if density is None:
            missing.append(names[index])
            continue
        grams = row['volume'] / 1000.0 * density
        total += grams
        moment = [value + grams * axis for value, axis in zip(moment, row['centre'])]
    if total <= 0:
        return []
    centre = [value / total for value in moment]
    detail = f'重心在 X {centre[0]:.0f}　Y {centre[1]:.0f}　Z {centre[2]:.0f} mm'
    if missing:
        detail += f'；{len(missing)} 个零件没定材质，没算进去（{"、".join(missing[:4])}{"…" if len(missing) > 4 else ""}）'
    issues = [checks._issue('info', 'mass', f'整套约 {total / 1000.0:,.1f} kg', detail, [], centre)]
    width = size[1] if len(size) > 1 else 0.0
    if width > 0 and abs(centre[1]) > width * OFF_CENTRE:
        side = '左' if centre[1] < 0 else '右'
        issues.append(checks._issue('warning', 'off_centre', f'重心偏{side} {abs(centre[1]):.0f} mm',
                                    f'超过总宽 {width:.0f} mm 的 {OFF_CENTRE:.0%}：左右重量不平衡，看看是不是少装了对面的件', [], centre))
    return issues


def motion(clashes, joint_names, unit_of):
    """运动副开合的半路上撞上了别的件 → 报错。"""
    return [checks._issue('error', 'motion_clash', f'运动干涉：{joint_names[row["joint"]]} 开到 {row["value"]:g}{unit_of(row["joint"])}',
                          f'{row["names"][0]} 撞上 {row["names"][1]}，压进去 {row["depth"]:.2g} mm：改铰链的位置、开的范围，或者让开',
                          [f'part:{row["a"]}', f'part:{row["b"]}'], row.get('point')) for row in clashes]
