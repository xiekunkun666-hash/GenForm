# -*- coding: utf-8 -*-
"""设计检查 (像 PCB 的 DRC): 做完一个零件点一下, 把加工、装配前能查出来的问题都查一遍, 免得零件做回来装的时候才发现。

查的东西 (每条一个 code, 界面按 level 上色: error 红 / warning 黄 / info 灰):
  feature_error    特征算不出来 / 被跳过
  invalid_body     实体过不了拓扑检查 (导出给加工厂会出问题)
  floating         实体分成了几块互不相连的: 多出来的那几块是悬空的零件
  gap / touch / shallow   件与件: 间隙比规则小 / 只贴着 / 压得比规则浅 (两个件都标红)
  no_material      没指定材质 (算不了重量, 工艺按碳钢估)
  no_process / process_none / process_infeasible   没绑工艺 / 没有能做它的工艺 / 绑的工艺现在做不了 (改了尺寸以后)
  thin_wall        板、壁比规则薄
  small_hole / deep_hole   孔比规则小 / 深径比太大
  sharp_corner     绑了 CNC 的切除, 轮廓有尖的内角 (铣刀铣不出来)
  small_text       字比规则矮
  closed_cavity    空心件里有封闭空腔: 电泳、喷涂、防锈都要开排液孔
  cost             按绑的工艺汇总的成本 (info)
"""
from __future__ import annotations

from . import manufacturing, rules as design_rules

LEVELS = ('error', 'warning', 'info')
_CNC = {'cnc3', 'cnc5', 'millturn'}


def _issue(level, code, title, detail='', features=(), point=None):
    return {'level': level, 'code': code, 'title': title, 'detail': detail, 'features': [item for item in features if item],
            'point': point}


def _name(by_id, identifier):
    feature = by_id.get(identifier)
    return (feature or {}).get('name') or identifier


def _sketch_of(feature, by_id):
    return by_id.get((feature.get('params') or {}).get('sketch')) or {}


def _concave_corners(shape):
    """草图图形里尖的内角数: 矩形、多边形的直角 / 尖角 (圆、槽口、样条没有)。切除时它们是型腔的内角。"""
    kind = shape.get('type')
    if kind == 'rect':
        return 0 if float(shape.get('r') or shape.get('radius') or 0) > 0 else 4
    if kind in ('polygon', 'ngon'):
        return int(shape.get('sides') or len(shape.get('points') or []))
    return 0


def run(features, model, report, rules=None, material=''):
    """→ 问题列表 (从严重到不严重)。features: 文档的特征表 (带绑定的工艺); model: session.model; report: 内核的 inspect。"""
    rules = dict(design_rules.DEFAULTS, **(rules or {}))
    by_id = {feature['id']: feature for feature in features}
    issues = []
    status = (model or {}).get('status') or {}
    report = report or {}

    # ---- 特征本身 ----
    for feature in features:
        state = status.get(feature['id'], '')
        if state.startswith('error'):
            issues.append(_issue('error', 'feature_error', f'特征出错：{feature.get("name")}', state[7:], [feature['id']]))
    skipped = [feature['id'] for feature in features if status.get(feature['id']) == 'skipped']
    if skipped:
        issues.append(_issue('warning', 'feature_error', f'{len(skipped)} 个特征被跳过 (前面有特征出错)', '', skipped[:20]))

    # ---- 实体 ----
    if report.get('has_body'):
        if not report.get('valid', True):
            issues.append(_issue('error', 'invalid_body', '实体过不了拓扑检查', '导出 STEP 给加工厂时可能打不开或缺面：撤销最近几步，找出把实体弄坏的那个特征'))
        bodies = report.get('bodies') or []
        if len(bodies) > 1:
            main = bodies[0]
            for number, body in enumerate(bodies[1:], 2):
                names = '、'.join(_name(by_id, item) for item in body['features'][:4]) or '未知特征'
                centre = '，'.join(f'{value:.0f}' for value in body['center'])
                issues.append(_issue('error', 'floating', f'悬空的零件：{names}',
                                     f'第 {number} 块实体 (体积 {body["volume"] / 1000:.4g} cm³，在 ({centre})) 和主体 '
                                     f'({main["volume"] / 1000:.4g} cm³) 不相连：装配时没有东西托着它。让它和相邻的件压进去一点 (≥ {rules["overlap"]:g} mm)',
                                     body['features'][:6], body['center']))
        if report.get('voids'):
            issues.append(_issue('info', 'closed_cavity', f'有 {report["voids"]} 个封闭空腔',
                                 '空心件的封闭空腔在电泳、喷涂、防锈时要开排液 / 排气孔，焊接前也要留工艺孔'))

    # ---- 件与件 (间隙、压入量) ----
    for pair in report.get('pairs') or []:
        a, b = _name(by_id, pair['a']), _name(by_id, pair['b'])
        if pair['kind'] == 'gap':
            issues.append(_issue('error', 'gap', f'间隙太小：{a} ↔ {b}',
                                 f'只隔 {pair["value"]:.3g} mm，规则要 ≥ {rules["clearance"]:g} mm (公差 ±{rules["tolerance"]:g})：'
                                 '按公差做出来可能撞上；要么拉开，要么让它们压在一起连成一体', [pair['a'], pair['b']], pair['point']))
        elif pair['kind'] == 'touch':
            issues.append(_issue('error', 'touch', f'只贴着没压进去：{a} ↔ {b}',
                                 f'两个件的面正好贴在一起：按公差 ±{rules["tolerance"]:g} mm 做出来可能有缝、连不上；'
                                 f'压进去 ≥ {rules["overlap"]:g} mm', [pair['a'], pair['b']], pair['point']))
        else:
            issues.append(_issue('error', 'shallow', f'压得太浅：{a} ↔ {b}',
                                 f'只重叠 {pair["value"]:.3g} mm，规则要 ≥ {rules["overlap"]:g} mm', [pair['a'], pair['b']], pair['point']))
    if report.get('pairs') is not None and report.get('pairs_checked') is not None:
        issues.append(_issue('info', 'pairs', f'比较了 {report["pairs_checked"]} 对离得近的件'))

    # ---- 材质、工艺 ----
    if not material:
        issues.append(_issue('warning', 'no_material', '没有指定材质', '重量算不出来，工艺按普通碳钢估价：在设计树的 “材质” 上右键指定'))
    tools = report.get('tools') or {}
    solid_kinds = manufacturing.solid_kinds()
    unbound, total, tooling, by_process = [], 0.0, 0.0, {}
    hollow = manufacturing._hollow_document(features)
    lookup = dict(by_id, __solid_kinds__=solid_kinds)
    for feature in features:
        if feature.get('suppressed') or feature.get('type') not in solid_kinds or not status.get(feature['id'], '').startswith('ok'):
            continue
        process = feature.get('process')
        kind, _ = manufacturing.shape_kind(feature, tools.get(feature['id']), lookup, hollow)
        if kind is None:
            continue
        if not process:
            unbound.append(feature['id'])
            continue
        if not process.get('id'):
            issues.append(_issue('error', 'process_none', f'没有能做它的工艺：{feature.get("name")}', process.get('why', ''), [feature['id']]))
            continue
        chosen = manufacturing.BY_ID.get(process['id'])
        metrics = tools.get(feature['id'])
        if chosen is not None and metrics is not None and kind == process.get('kind', kind):
            m = manufacturing._Measure(metrics, material)
            ok, reason = manufacturing._feasible(chosen, m, kind)
            if not ok and reason != '形状不对':
                issues.append(_issue('error', 'process_infeasible', f'{chosen["name"]}做不了：{feature.get("name")}',
                                     f'{reason}：重新绑定工艺，或者改设计', [feature['id']]))
        total += float(process.get('cost') or 0.0)
        tooling += float(process.get('tooling') or 0.0) if not feature.get('type', '').startswith(('pattern', 'mirror')) else 0.0
        by_process[process.get('name', '?')] = by_process.get(process.get('name', '?'), 0.0) + float(process.get('cost') or 0.0)
        _check_rules(feature, process, metrics, by_id, rules, issues)
    if unbound:
        issues.append(_issue('warning', 'no_process', f'{len(unbound)} 个特征还没绑加工工艺',
                             '评估 → 绑定工艺：按性价比自动给每个特征挑工艺', unbound[:30]))
    if total:
        top = sorted(by_process.items(), key=lambda item: -item[1])[:5]
        issues.append(_issue('info', 'cost', f'估算成本：每件约 ¥{manufacturing._money(total)} (模具 / 工装合计 ¥{manufacturing._money(tooling)})',
                             '大头：' + '，'.join(f'{name} ¥{manufacturing._money(value)}' for name, value in top)))
    order = {level: index for index, level in enumerate(LEVELS)}
    issues.sort(key=lambda item: order[item['level']])
    return issues


def _check_rules(feature, process, metrics, by_id, rules, issues):
    """单个特征上的几条规则: 壁厚、孔、内角、字高。"""
    kind = process.get('kind')
    identifier, name = feature['id'], feature.get('name') or feature['id']
    params = feature.get('params') or {}
    if metrics and kind in ('plate', 'partition', 'prism', 'freeform', 'freeform_small', 'revolved'):
        wall = min(metrics.get('thickness') or 1e9, (metrics.get('size') or [1e9])[0])
        if 0 < wall < rules['min_wall']:
            issues.append(_issue('warning', 'thin_wall', f'壁太薄：{name}', f'约 {wall:.3g} mm，规则 ≥ {rules["min_wall"]:g} mm', [identifier]))
    shapes = (_sketch_of(feature, by_id).get('params') or {}).get('shapes') or []
    if kind == 'hole':
        depth = float(params.get('distance') or params.get('depth') or 0.0)
        for shape in shapes:
            if shape.get('type') != 'circle' or shape.get('construction'):
                continue
            diameter = 2 * float(shape.get('r') or 0.0)
            if 0 < diameter < rules['min_hole']:
                issues.append(_issue('warning', 'small_hole', f'孔太小：{name}', f'直径 {diameter:.3g} mm，规则 ≥ {rules["min_hole"]:g} mm', [identifier]))
                break
            if diameter > 0 and depth / diameter > rules['hole_ratio']:
                issues.append(_issue('warning', 'deep_hole', f'孔太深：{name}',
                                     f'深 {depth:.3g} / 直径 {diameter:.3g} = {depth / diameter:.3g}，规则 ≤ {rules["hole_ratio"]:g}', [identifier]))
                break
    if process.get('id') in _CNC and params.get('op') in ('cut', 'pocket') and rules['corner_radius'] > 0:
        corners = sum(_concave_corners(shape) for shape in shapes if not shape.get('construction'))
        if corners:
            issues.append(_issue('warning', 'sharp_corner', f'铣不出的尖内角：{name}',
                                 f'轮廓里有 {corners} 个尖角，铣刀是圆的：内角加 R ≥ {rules["corner_radius"]:g} mm 的圆角，或改线切割 / 激光', [identifier]))
    for shape in shapes:
        if shape.get('type') == 'text' and float(shape.get('height') or 0) < rules['min_text']:
            issues.append(_issue('warning', 'small_text', f'字太小：{name}',
                                 f'字高 {float(shape.get("height") or 0):.3g} mm，规则 ≥ {rules["min_text"]:g} mm', [identifier]))
            break


def summary(issues):
    counts = {level: sum(1 for item in issues if item['level'] == level) for level in LEVELS}
    return counts


def red_features(issues):
    """要在视图里标红的特征: 报错的 (悬空、间隙、工艺做不了…) 里提到的。"""
    marked = []
    for item in issues:
        if item['level'] == 'error' and item['code'] != 'feature_error':
            for identifier in item['features']:
                if identifier not in marked:
                    marked.append(identifier)
    return marked
