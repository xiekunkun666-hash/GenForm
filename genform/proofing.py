# -*- coding: utf-8 -*-
"""铨洲智造平台 "CNC 智能制造打样" 的限制 (设计建议 8.14 版, 2026-08): 设计规则里打开 proofing 以后, 设计检查再按它查一遍。

打样是全自动报价 + 自动编程, 模型不合规矩就被系统 NG, 所以这里能从模型里看出来的都先查掉:
  proof_material    材质只开放 铝合金 6061 / 7075、45# 钢 (车铣打样只有 303 / 304 不锈钢)
  proof_size        外形 10×10×1 ~ 650×440×30 (按最薄的方向当厚度放平)
  proof_two_sided   双面凸台: 最大外形既不在最高面也不在最低面上 → 系统 NG
  proof_hole        孔 < Φ1.2、深 > 8 倍径 (> 5 倍径改用钻头, 精度低)
  proof_thread      螺纹底孔不是表里的直径 / 有效螺纹 > 5 倍径
  proof_slot        内槽 < 1.25 宽, 或比刀具 5 倍径还深
  proof_groove      环槽、T 槽、内孔退刀槽 (旋转切除不通到端面): 打样不支持
  proof_corner      尖内角: 平台按 深度 / 5 自动加 R (提示)
  proof_chamfer     倒角 > C0.5: 双面都有可能 NG, 能不画就不画
  proof_silk        模型里的丝印 / 很薄的凸字: 不是加工特征, 导出打样前要压掉
  proof_text        刻字太小: 刻字最小间隙 1.25
  proof_fit         销钉孔、精孔: 建模时放大 0.02 ~ 0.03
  proof_lathe       车铣打样: 303 / 304, Φ ≤ 17.9, 长 ≤ 3 倍径, 只车外圆
最后一条 info: 自动查的项都过了 / 没过几项。实际能不能做以平台仿真为准。
"""
from __future__ import annotations

from . import manufacturing

MILL_MATERIALS = ('铝合金 6061', '铝合金 7075', '45# 钢')
LATHE_MATERIALS = ('不锈钢 304',)
MIN_SIZE, MAX_SIZE = (1.0, 10.0, 10.0), (30.0, 440.0, 650.0)       # 从小到大的三个边长
MIN_HOLE, MAX_HOLE_RATIO, DRILL_RATIO = 1.2, 8.0, 5.0
MIN_SLOT, TOOL_DEPTH_RATIO = 1.25, 5.0
MAX_CHAMFER = 0.5
SILK = 0.5                  # 比这还薄的凸起 (丝印、0.03 厚的白字): 不是加工出来的
THREAD_RATIO = 5.0
LATHE_DIAMETER, LATHE_RATIO = 17.9, 3.0
_PLANE_AXIS = {'XY': 2, 'XZ': 1, 'YZ': 0}
_AXIS = {'X': 0, 'Y': 1, 'Z': 2}
_LATHE = {'turning', 'millturn'}


def _issue(level, code, title, detail='', features=()):
    from .checks import _issue as make
    return make(level, code, title, detail, features)


def _main_process(features):
    for feature in features:
        process = feature.get('process') or {}
        if process.get('id') and not feature.get('suppressed'):
            return process.get('id')
    return ''


def _shapes(feature, by_id):
    sketch = by_id.get((feature.get('params') or {}).get('sketch')) or {}
    return [shape for shape in (sketch.get('params') or {}).get('shapes') or [] if not shape.get('construction')]


def _plane_axis(feature, by_id):
    sketch = by_id.get((feature.get('params') or {}).get('sketch')) or {}
    return _PLANE_AXIS.get((sketch.get('params') or {}).get('plane'))


def _tool_extent(tools, identifier, axis, body=None):
    """工具体沿 axis 的长度; 给了零件的包围盒 body 就只算在零件里的那段 (贯穿孔的工具体会伸出零件很远)。"""
    metrics = tools.get(identifier) or {}
    box = metrics.get('box')
    if not box or axis is None:
        return None
    low, high = box[0][axis], box[1][axis]
    if body:
        low, high = max(low, body[0][axis]), min(high, body[1][axis])
    return max(high - low, 0.0)


def run(features, report, material='', rules=None):
    """→ 问题列表 (和 checks.run 的格式一样)。report: 内核 inspect 的结果 (要带 'proof', 见 kernel/inspect.proof)。"""
    report = report or {}
    if not report.get('has_body'):
        return []
    by_id = {feature['id']: feature for feature in features}
    main = _main_process(features)
    if main in manufacturing.STANDARD:
        return [_issue('info', 'proof_skip', '标准件 / 外购件：不走打样', '按规格直接买')]
    if main in _LATHE:
        return _lathe(features, report, material, by_id)
    issues = []
    tools = report.get('tools') or {}
    proof = report.get('proof') or {}

    # ---- 材质、外形 ----
    if material not in MILL_MATERIALS:
        issues.append(_issue('error', 'proof_material', f'材质不在打样范围：{material or "没指定"}',
                             'CNC 打样只开放 铝合金 6061、铝合金 7075、45# 钢 (7075 和 45# 只开放部分尺寸)'))
    box = proof.get('box')
    if box:
        size = sorted(high - low for low, high in zip(*box))
        names = ('厚', '宽', '长')
        for value, low, high, name in zip(size, MIN_SIZE, MAX_SIZE, names):
            if value > high + 1e-6 or value < low - 1e-6:
                issues.append(_issue('error', 'proof_size', f'外形超出打样范围：{name} {value:.1f} mm',
                                     f'打样外形 {MIN_SIZE[1]:g}×{MIN_SIZE[2]:g}×{MIN_SIZE[0]:g} ~ {MAX_SIZE[2]:g}×{MAX_SIZE[1]:g}×{MAX_SIZE[0]:g} mm '
                                     f'(现在 {size[2]:.1f}×{size[1]:.1f}×{size[0]:.1f})'))
                break
    extent, top, bottom = proof.get('extent'), proof.get('top'), proof.get('bottom')
    if extent and min(extent) > 0:
        def cover(section):
            return min(section[0] / extent[0], section[1] / extent[1]) if section else 0.0
        if max(cover(top), cover(bottom)) < 0.98:
            issues.append(_issue('error', 'proof_two_sided', '双面凸台：最大外形不在最高面也不在最低面上',
                                 '打样要求至少有一面的最大外形在零件最高 (或最低) 那一层：把最高面延伸到整个外形; '
                                 '别用薄片凑外形, 平台算违规'))

    # ---- 逐个特征 ----
    for feature in features:
        if feature.get('suppressed'):
            continue
        kind, params = feature.get('type'), feature.get('params') or {}
        identifier, name = feature['id'], feature.get('name') or feature['id']
        op = params.get('op', 'add')
        shapes = _shapes(feature, by_id)
        axis = _plane_axis(feature, by_id)
        if kind == 'hole':
            _hole(feature, params, shapes, tools, axis, issues, proof.get('box'))
            continue
        if kind == 'chamfer' and float(params.get('distance') or params.get('size') or 0) > MAX_CHAMFER:
            issues.append(_issue('warning', 'proof_chamfer', f'倒角大于 C0.5：{name}',
                                 '打样默认按 C0.1~0.5 去毛刺; 双面都有大于 C0.5 的倒角可能 NG: 能不画就不画', [identifier]))
        if kind == 'revolve' and op == 'cut':
            _groove(feature, params, tools, proof, issues)
            continue
        if kind != 'extrude':
            continue
        depth = abs(float(params.get('distance') or 0.0))
        texts = [shape for shape in shapes if shape.get('type') == 'text']
        if texts:
            if op == 'add' and depth < SILK:
                issues.append(_issue('warning', 'proof_silk', f'丝印 / 薄凸字不是加工特征：{name}',
                                     f'只凸起 {depth:g} mm: 导出 STEP 打样前把这个特征压掉, 丝印另外做 (移印 / 激光打标)', [identifier]))
            elif op == 'cut' and min(float(shape.get('height') or 0) for shape in texts) < 2.0:
                issues.append(_issue('warning', 'proof_text', f'刻字可能太小：{name}',
                                     '打样刻字的最小间隙是 1.25 mm (最小刀 Φ1): 字高 2 mm 以下笔画间隙多半不够', [identifier]))
            continue
        if op != 'cut':
            continue
        circles = [shape for shape in shapes if shape.get('type') == 'circle']
        if circles and len(circles) == len(shapes):
            extent_ = _tool_extent(tools, identifier, axis, proof.get('box')) or depth
            for shape in circles:
                _check_round(identifier, name, 2 * float(shape.get('r') or 0), extent_, issues)
                break
            _fit(identifier, name, [2 * float(shape.get('r') or 0) for shape in circles], issues)
            continue
        widths = []
        for shape in shapes:
            if shape.get('type') in ('slot', 'arcslot'):
                widths.append(float(shape.get('w') or 0))
            elif shape.get('type') == 'rect':
                widths.append(min(float(shape.get('w') or 0), float(shape.get('h') or 0)))
        narrow = min(widths) if widths else 0.0
        if widths and narrow < MIN_SLOT:
            issues.append(_issue('error', 'proof_slot', f'槽太窄：{name}',
                                 f'最窄 {narrow:.2f} mm, 打样最小刀 Φ1, 内槽要 ≥ {MIN_SLOT:g} mm', [identifier]))
        elif widths:
            tool = max(1.0, narrow - 0.25)
            if depth > TOOL_DEPTH_RATIO * tool + 1e-6:
                issues.append(_issue('warning', 'proof_slot', f'槽太深：{name}',
                                     f'宽 {narrow:.2f} mm 要用约 Φ{tool:.2g} 的刀, 槽深最多 {TOOL_DEPTH_RATIO * tool:.1f} mm (现在 {depth:.2f})', [identifier]))
        corners = sum(4 for shape in shapes if shape.get('type') == 'rect' and not float(shape.get('r') or 0)) + \
            sum(len(shape.get('points') or []) for shape in shapes if shape.get('type') == 'polygon')
        if corners and depth > 0:
            issues.append(_issue('info', 'proof_corner', f'尖内角会自动加 R：{name}',
                                 f'深 {depth:.2g} mm → 平台按 深度/5 加工成 R{max(depth / 5, 0.5):.2g} 左右的圆角; 要清根就画避空 (Φ1.2 / 1.7 / 2.2 / 3.2 / 4.2)',
                                 [identifier]))
    bad = [item for item in issues if item['level'] in ('error', 'warning')]
    if bad:
        issues.append(_issue('info', 'proof_summary', f'铨洲 CNC 打样：{len(bad)} 项要改',
                             '上面 proof_ 开头的几条; 改完以平台上传后的仿真为准'))
    else:
        issues.append(_issue('info', 'proof_summary', '铨洲 CNC 打样：自动能查的项都过了',
                             '侧孔要有平面支撑、薄壁 / 悬空细长结构、孔底和螺纹侧壁余量这几条看不出来, 上传后以平台仿真为准'))
    return issues


def _check_round(identifier, name, diameter, depth, issues):
    if diameter <= 0:
        return
    if diameter < MIN_HOLE:
        issues.append(_issue('error', 'proof_hole', f'孔太小：{name}', f'Φ{diameter:.2f}, 打样孔要 ≥ Φ{MIN_HOLE:g}', [identifier]))
    elif depth and depth / diameter > MAX_HOLE_RATIO:
        issues.append(_issue('error', 'proof_hole', f'孔太深：{name}',
                             f'深 {depth:.3g} / Φ{diameter:.3g} = {depth / diameter:.2g} 倍径, 打样最多 {MAX_HOLE_RATIO:g} 倍', [identifier]))
    elif depth and depth / diameter > DRILL_RATIO:
        issues.append(_issue('warning', 'proof_hole', f'孔偏深：{name}',
                             f'{depth / diameter:.2g} 倍径: 超过 {DRILL_RATIO:g} 倍改用钻头, 精度比铣的低', [identifier]))


def _hole(feature, params, shapes, tools, axis, issues, body=None):
    from .features import TAP_DRILLS
    identifier, name = feature['id'], feature.get('name') or feature['id']
    diameter = float(params.get('diameter') or 0.0) or (2 * float(shapes[0].get('r') or 0) if shapes else 0.0)
    if params.get('kind') == 'tapped' and params.get('size') in TAP_DRILLS:
        diameter = TAP_DRILLS[params['size']]           # 内核按规格打底孔, 参数里的 diameter 不用 (见 kernel/ops/tools.py)
    depth = _tool_extent(tools, identifier, axis, body) if params.get('through', True) else float(params.get('depth') or 0.0)
    _check_round(identifier, name, diameter, depth, issues)
    if params.get('kind') == 'tapped':
        size = params.get('size') or ''
        if params.get('thread'):
            issues.append(_issue('warning', 'proof_thread', f'导出前关掉真实牙：{name}',
                                 f'真实牙的底孔是螺纹小径, 平台认不出来: 关掉 "真实螺纹" 再导出, 孔就是 Φ{TAP_DRILLS.get(size, diameter):g} 光孔, '
                                 f'下单时按 {size} 选攻丝', [identifier]))
        nominal = float(size[1:]) if size[1:].replace('.', '', 1).isdigit() else 0.0
        if nominal and depth and depth > THREAD_RATIO * nominal + 1e-6:
            issues.append(_issue('warning', 'proof_thread', f'螺纹太深：{name}',
                                 f'{size} 有效螺纹最多 {THREAD_RATIO * nominal:g} mm (5 倍径), 现在孔深 {depth:g}; 拧紧长度 1~2 倍径就够', [identifier]))
    elif params.get('kind') == 'simple':
        _fit(identifier, name, [diameter], issues)


def _fit(identifier, name, diameters, issues):
    if not any(word in name for word in ('销', 'H7', '精孔')):
        return
    nominal = [value for value in diameters if value > 0 and abs(value * 2 - round(value * 2)) < 1e-6]
    if nominal:
        issues.append(_issue('info', 'proof_fit', f'精孔建模放大一点：{name}',
                             f'打样孔做到 0~+0.02: 销钉孔 Φ{nominal[0]:g} 建模画成 Φ{nominal[0] + 0.02:g} ~ Φ{nominal[0] + 0.03:g}', [identifier]))


def _groove(feature, params, tools, proof, issues):
    """旋转切除: 切的那一圈两头都没通到零件端面 → 环槽 / 内孔退刀槽, 三轴从上往下铣不出来。"""
    metrics = tools.get(feature['id']) or {}
    box, whole = metrics.get('box'), proof.get('box')
    axis = _AXIS.get(str(params.get('axis') or 'Z').upper()[-1:], 2)
    if not box or not whole:
        return
    inside = box[0][axis] > whole[0][axis] + 0.05 and box[1][axis] < whole[1][axis] - 0.05
    if inside:
        name = feature.get('name') or feature['id']
        issues.append(_issue('error', 'proof_groove', f'环槽 / T 槽：{name}',
                             '旋转切除的这一圈两头都没通到端面 (内孔环槽、退刀槽): 打样不支持, 改成从端面铣得到的形状', [feature['id']]))


def _lathe(features, report, material, by_id):
    """车铣打样: 303 / 304 不锈钢, Φ ≤ 17.9, 长 ≤ 3 倍径, 只车外圆 (不做端面、孔、铣)。"""
    issues = []
    box = (report.get('proof') or {}).get('box')
    reasons = []
    if material not in LATHE_MATERIALS:
        reasons.append(f'材质 {material or "没指定"} (车铣打样只有 303 / 304 不锈钢)')
    if box:
        size = sorted(high - low for low, high in zip(*box))
        diameter, length = size[1], size[2]
        if diameter > LATHE_DIAMETER:
            reasons.append(f'直径 {diameter:.1f} > {LATHE_DIAMETER:g}')
        elif length > LATHE_RATIO * diameter:
            reasons.append(f'长 {length:.1f} > 3 倍径 {LATHE_RATIO * diameter:.1f}')
    cuts = [feature.get('name') or feature['id'] for feature in features
            if not feature.get('suppressed') and (feature.get('type') == 'hole' or (feature.get('params') or {}).get('op') == 'cut')
            and feature.get('type') != 'revolve']
    if cuts:
        reasons.append('有孔 / 铣的特征 (车铣打样只车外圆): ' + '、'.join(cuts[:3]))
    if reasons:
        issues.append(_issue('warning', 'proof_lathe', '车削件不在车铣打样范围', '；'.join(reasons) + '：走普通报价'))
    else:
        issues.append(_issue('info', 'proof_lathe', '车削件符合车铣打样', '外螺纹画大径 (M3 → D2.9)、要画退刀槽和 C 角 (≥ 螺距)'))
    return issues
