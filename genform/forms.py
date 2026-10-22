# -*- coding: utf-8 -*-
"""参数面板的内容: 新建特征 / 编辑特征时要填哪些项, 以及填完后变成哪条命令。

纯数据进、纯数据出, 不碰界面库 — 界面只管把字段画出来。草图不走这里: 它有自己的编辑模式 (sketcher.py)。
字段: {'key', 'label', 'type': 'number'|'choice'|'multi'|'bool'|'text'|'info', 'value', 'unit', 'options'}。
面板 (form) 里的 'pick' = 这个面板开着时在三维视图里点选的是什么: {'kind': 'edge'|'face', 'key', 'count'}。

拉伸、圆角、倒角是手写的; 其余的特征按特征表 (features.py) 自动生成。
"""
from __future__ import annotations

import copy

from . import features as table
from . import planes

OP_OPTIONS = table.OPS
TITLES = {'extrude': '拉伸凸台', 'cut': '拉伸切除', 'fillet': '圆角', 'chamfer': '倒角'}


def number(key, label, value, unit='mm'):
    return {'key': key, 'label': label, 'type': 'number', 'value': float(value), 'unit': unit}


def choice(key, label, value, options):
    return {'key': key, 'label': label, 'type': 'choice', 'value': value, 'options': options}


def info(key, text):
    return {'key': key, 'label': '', 'type': 'info', 'value': text}


END_OPTIONS = [{'value': 'blind', 'label': '给定深度'}, {'value': 'through', 'label': '完全贯穿'},
               {'value': 'vertex', 'label': '成形到顶点'}, {'value': 'surface', 'label': '成形到面'},
               {'value': 'offset', 'label': '到离指定面指定的距离'}, {'value': 'body', 'label': '成形到实体'},
               {'value': 'mid', 'label': '两侧对称'}]
END_PICKS = {'vertex': ('vertex', '顶点'), 'surface': ('face', '终止面'), 'offset': ('face', '终止面')}


def extrude_fields(params, has_body=True):
    """拉伸面板上 "从哪到哪" 的那几项。哪几项露出来由终止条件定 (arrange)。"""
    end = params.get('end') or ('mid' if params.get('symmetric') else 'blind')
    distance = float(params.get('distance', 10.0))
    reverse = bool(params.get('reverse')) != (distance < 0 and end == 'blind')     # 老写法: 负的距离 = 反向
    return [choice('end', '终止条件', end, END_OPTIONS if has_body else [END_OPTIONS[0], END_OPTIONS[2], END_OPTIONS[6]]),
            number('distance', '深度', abs(distance)),
            info('target', ''),
            number('gap', '离面的距离', params.get('gap', 0.0)),
            {'key': 'reverse', 'label': '反向', 'type': 'bool', 'value': reverse},
            number('distance2', '方向 2 深度', params.get('distance2', 0.0))]


def arrange(form, session):
    """拉伸面板: 按终止条件决定哪几项露出来、视图里该点什么 (form['pick'])。"""
    if form['kind'] != 'extrude':
        return form
    values = values_of(form)
    end = values.get('end', 'blind')
    shown = {'distance': end in ('blind', 'mid'), 'gap': end == 'offset', 'distance2': end == 'blind',
             'reverse': end not in ('mid', 'vertex', 'surface', 'offset'), 'target': end in END_PICKS}
    for field in form['fields']:
        if field['key'] in shown:
            field['hidden'] = not shown[field['key']]
        if field['key'] == 'distance':
            field['label'] = '总厚度' if end == 'mid' else '深度'
    if end in END_PICKS:
        kind, label = END_PICKS[end]
        form['pick'] = {'kind': kind, 'key': 'target', 'count': 1, 'label': label, 'optional': False,
                        'kept': 1 if form.get('kept_end') == end else 0}
        for field in form['fields']:
            if field['key'] == 'target':
                field['value'] = pick_text(form, session)
    else:
        form.pop('pick', None)
    return form


PICKED_AXIS = '视图里点的线'
PICK_HINT = '草图、轴、基准面可以直接在视图里点：点草图 = 选它；点实体的直边、圆边、草图里的直线或基准轴 = 用它当轴'


def picked_axis(value):
    """轴是在视图里点出来的一条线 ("@过点;方向") 时, 选项里多一个代表它的。"""
    return [{'value': value, 'label': PICKED_AXIS}] if str(value).startswith('@') else []


def field_kinds(form):
    """面板上能在视图里点着填的那几项: [(字段名, 种类 sketch / path / axis / plane / sketches / features)...], 按面板上的顺序。"""
    if form['kind'] in table.SPECS:
        wanted = {field['key']: field['kind'] for field in table.SPECS[form['kind']]['fields']}
    else:
        wanted = {'sketch': 'sketch'} if form['kind'] == 'extrude' else {}
    return [(field['key'], wanted[field['key']]) for field in form['fields']
            if wanted.get(field['key']) in ('sketch', 'path', 'axis', 'plane', 'sketches', 'features') and field['type'] in ('choice', 'multi')]


def take(form, accepts, value, label=None):
    """在视图里点了一样东西: 填进面板上收这种东西的那一项 (accepts: 可以收它的字段种类)。
    收它的有好几项时 (线性阵列的方向 1、方向 2): 填 form['active'] 指的那项, 填完轮到下一项。→ 填了哪一项 (没有能收的: None)。"""
    keys = [key for key, kind in field_kinds(form) if kind in accepts]
    if not keys:
        return None
    key = form.get('active') if form.get('active') in keys else keys[0]
    field = next(item for item in form['fields'] if item['key'] == key)
    if field['type'] == 'multi':                # 多选的: 点一下加进去, 再点一下拿掉
        if not any(option['value'] == value for option in field['options']):
            return None
        field['value'] = [item for item in field['value'] if item != value] if value in field['value'] else field['value'] + [value]
    else:
        if not any(option['value'] == value for option in field['options']):
            if label is None:
                return None
            field['options'] = [option for option in field['options'] if option.get('label') != label] + [{'value': value, 'label': label}]
        field['value'] = value
        if len(keys) > 1:
            form['active'] = keys[(keys.index(key) + 1) % len(keys)]
    return key


def edges_text(count):
    return f'已选 {count} 条边' if count else '在三维视图里点选边（再点一次取消）'


def _named(session, kinds):
    return [{'value': f['id'], 'label': f['name']} for f in session.document.features if f['type'] in kinds]


def new_form(kind, session):
    """点工具栏按钮后出现的面板。kind 可以带 _cut 后缀 (旋转切除 = revolve_cut): 同一个特征, 方式默认切除。"""
    base = kind[:-4] if kind.endswith('_cut') else kind
    if base in table.SPECS:
        return spec_form(base, session, cut=kind.endswith('_cut'))
    form = {'kind': kind, 'title': TITLES[kind], 'editing': '', 'accept': '确定', 'cancel': '取消'}
    if kind in ('extrude', 'cut'):
        # 凸台和切除是同一个特征的两种方式 (和 SOLIDWORKS 一样分成两个按钮, 省得每次去选)
        form['kind'] = 'extrude'
        has_body = bool(session.model.get('has_body'))
        sketches = _named(session, ('sketch',))
        selected = session.selection.get('feature')
        default = selected if any(s['value'] == selected for s in sketches) else (sketches[-1]['value'] if sketches else '')
        cutting = kind == 'cut' and has_body
        form['fields'] = [choice('sketch', '草图', default, sketches)] \
            + extrude_fields({'end': 'through' if cutting else 'blind'}, has_body) \
            + [choice('op', '方式', 'cut' if cutting else 'add', OP_OPTIONS if has_body else OP_OPTIONS[:1])]
        if not sketches:
            form['fields'].insert(0, info('note', '还没有草图：先在“草图”页里选一个工具，在基准面上画出轮廓'))
        arrange(form, session)
    else:
        key, label, value = ('radius', '半径', 2.0) if kind == 'fillet' else ('distance', '距离', 1.0)
        form['fields'] = [info('edges', edges_text(len(session.selection.get('edges', ())))), number(key, label, value)]
        form['pick'] = {'kind': 'edge', 'key': 'edges', 'count': None}
    return form


def feature_form(feature, session=None):
    """双击特征后出现的面板: 把它现有的参数摆出来改。"""
    kind, params = feature['type'], feature['params']
    if kind in table.SPECS:
        return spec_form(kind, session, feature)
    form = {'kind': kind, 'title': f'编辑 {feature["name"]}', 'editing': feature['id'], 'accept': '应用', 'cancel': '关闭'}
    if kind == 'extrude':
        form['fields'] = extrude_fields(params) + [choice('op', '方式', params.get('op', 'add'), OP_OPTIONS)]
        form['kept_end'] = params.get('end') if params.get('target') else None     # 原来就选好了终止面 / 顶点: 不重新点就沿用
        if session is not None:
            arrange(form, session)
    elif kind in ('fillet', 'chamfer'):
        edges = params.get('edges')
        text = f'选择器 {edges}' if isinstance(edges, str) else f'{len(edges or ())} 条边'
        key, label = ('radius', '半径') if kind == 'fillet' else ('distance', '距离')
        form['fields'] = [info('edges', f'作用于 {text}'), number(key, label, params.get(key, 1.0))]
    else:
        form['fields'] = []
    return form


# ---------------------------------------------------------------------------
# 特征表里的特征
# ---------------------------------------------------------------------------
def _picked(session, kind):
    """视图里选中的边 / 面 → 存进特征里的引用 [{'point': ...}]。"""
    key, anchor = ('edges', 'mid') if kind == 'edge' else ('faces', 'center')
    known = {item['id']: item for item in session.model.get(key) or ()}
    return [{'point': [round(float(c), 6) for c in known[i][anchor]]} for i in session.selection.get(key, ()) if i in known]


def pick_text(form, session):
    """面板上那行 "已选 N 条边 / 个面"。"""
    pick = form['pick']
    unit, key = {'edge': ('条边', 'edges'), 'face': ('个面', 'faces'), 'vertex': ('个顶点', 'vertices')}[pick['kind']]
    count = len(session.selection.get(key, ()))
    wanted = f'（要 {pick["count"]} 个）' if pick.get('count') else ''
    if count:
        return f'{pick["label"]}：已选 {count} {unit}{wanted}'
    if form['editing']:
        return f'{pick["label"]}：沿用原来选的 {pick.get("kept", 0)} {unit}；在视图里重新点选则换掉'
    return f'{pick["label"]}：在三维视图里点选{unit[1:]}（再点一次取消）{wanted}' + ('，可以不选' if pick.get('optional') else '')


def _prefill(kind, values, session):
    """新建参考几何体时, 用视图里选中的面 / 边把位置先填上。"""
    faces = {item['id']: item for item in session.model.get('faces') or ()}
    edges = {item['id']: item for item in session.model.get('edges') or ()}
    face = next((faces[i] for i in session.selection.get('faces', ()) if i in faces), None)
    edge = next((edges[i] for i in session.selection.get('edges', ()) if i in edges), None)

    def triple(value):
        return [[round(float(c), 6) + 0.0 for c in value]]       # + 0.0: 不要 -0

    if kind == 'plane' and face is not None and face.get('normal') is not None:
        values.update(origin=triple(face['center']), normal=triple(face['normal']), offset=0.0)
        return '已按选中的平面定位（偏移和转角在它的基础上再加）'
    if kind == 'axis' and edge is not None and edge.get('dir') is not None:
        values.update(origin=triple(edge['mid']), direction=triple(edge['dir']))
        return '已按选中的直边定位'
    if kind == 'axis' and edge is not None and edge.get('axis') is not None:
        values.update(origin=triple(edge['center']), direction=triple(edge['axis']))
        return '已按选中圆边的轴线定位'
    if kind in ('point', 'csys') and (face is not None or edge is not None):
        values['position' if kind == 'point' else 'origin'] = triple(face['center'] if face is not None else edge['mid'])
        return '已放在选中的面中心 / 边中点上'
    return ''


def spec_form(kind, session, feature=None, cut=False):
    spec = table.SPECS[kind]
    editing = feature['id'] if feature else ''
    values = copy.deepcopy(feature['params']) if feature else table.default_params(kind)
    form = {'kind': kind, 'editing': editing, 'accept': '应用' if editing else '确定', 'cancel': '关闭' if editing else '取消',
            'title': f'编辑 {feature["name"]}' if feature else (spec.get('cut', spec['title']) if cut else spec['title'])}
    note = '' if feature else _prefill(kind, values, session)
    fields = [info('about', spec['about'] + ('\n' + note if note else ''))]
    document = session.document
    sketches = _named(session, ('sketch',))
    selected = session.selection.get('feature')
    for field in spec['fields']:
        key, label, sort = field['key'], field['label'], field['kind']
        value = values.get(key, field['default'])
        if sort in ('number', 'int') and isinstance(value, str):        # 方程式: 照原样显示, 改也写方程式
            fields.append({'key': key, 'label': label, 'type': 'text', 'value': value})
        elif sort == 'vars':
            fields.append({'key': key, 'label': label, 'type': 'text', 'value': table.variables_text(value)})
        elif sort in ('number', 'int'):
            fields.append(number(key, label, value, field.get('unit', 'mm' if sort == 'number' else '个')))
        elif sort == 'bool':
            fields.append({'key': key, 'label': label, 'type': 'bool', 'value': bool(value)})
        elif sort == 'choice':
            options = field['options']
            if key == 'op':
                if not feature:
                    has_body = bool(session.model.get('has_body'))
                    value = 'cut' if cut and has_body else value
                    options = options if has_body else options[:1]
            fields.append(choice(key, label, value, options))
        elif sort == 'text':
            fields.append({'key': key, 'label': label, 'type': 'text', 'value': str(value)})
        elif sort == 'points':
            fields.append({'key': key, 'label': label, 'type': 'text', 'value': table.points_text(value)})
        elif sort == 'sketch':
            if value is None:       # 新建: 默认用选中的草图, 没选就用还没被别的特征用过的最后一个
                used = {f['params'].get('sketch') for f in document.features if f['type'] != 'sketch'}
                free = [s['value'] for s in sketches if s['value'] not in used]
                picked = [key2 for key2 in (item['key'] for item in spec['fields'] if item['kind'] == 'sketch')]
                value = selected if any(s['value'] == selected for s in sketches) and picked[0] == key \
                    else (free[-1] if free else (sketches[-1]['value'] if sketches else ''))
            fields.append(choice(key, label, value, sketches))
        elif sort == 'path':
            fields.append(choice(key, label, value or '', sketches + _named(session, table.CURVE_KINDS)))
        elif sort == 'plane':
            options = [{'value': name, 'label': planes.NAMES[name]} for name in ('XZ', 'XY', 'YZ')]
            fields.append(choice(key, label, value, options + [o for o in _named(session, ('plane',)) if o['value'] != editing]))
        elif sort == 'axis':
            options = [{'value': 'CL', 'label': '草图里的中心线'}, {'value': 'SX', 'label': '草图 X 轴'},
                       {'value': 'SY', 'label': '草图 Y 轴'}] if field.get('sketch_axes') else []
            options += [{'value': name, 'label': f'{name} 轴'} for name in 'XYZ']
            fields.append(choice(key, label, value, options + _named(session, ('axis',)) + picked_axis(value)))
        elif sort in ('sketches', 'features'):
            kinds = ('sketch',) if sort == 'sketches' else \
                {'point': ('point',), 'path': ('sketch',) + table.CURVE_KINDS}.get(field.get('of'), table.TOOL_KINDS)
            options = _named(session, kinds)
            if not feature and sort == 'features' and not field.get('of') and kind != 'pattern_fill' \
                    and any(o['value'] == selected for o in options):
                value = [selected]              # 选着一个特征点 "阵列": 默认阵列它
            fields.append({'key': key, 'label': label, 'type': 'multi', 'value': list(value or []), 'options': options})
        elif sort in ('edges', 'faces'):
            form['pick'] = {'kind': field['pick'], 'key': key, 'count': field.get('count'), 'label': label,
                            'optional': bool(field.get('optional')), 'kept': len(value) if isinstance(value, list) else 0}
            fields.append(info(key, pick_text(form, session)))
    if not sketches and any(item['kind'] in ('sketch', 'sketches') for item in spec['fields']):
        fields.insert(1, info('note', '还没有草图：先在“草图”页里画一个'))
    form['fields'] = fields
    if any(kind in ('axis', 'sketch', 'path', 'plane', 'sketches') for _, kind in field_kinds(form)):
        fields.append(info('pickhint', PICK_HINT))
    return form


def values_of(form):
    return {field['key']: field['value'] for field in form['fields'] if field['type'] != 'info'}


def to_command(form, session):
    """面板上的值 → (命令名, 参数)。"""
    values, kind = values_of(form), form['kind']
    if kind in table.SPECS:
        args = {}
        for field in table.SPECS[kind]['fields']:
            key = field['key']
            if field['kind'] in ('edges', 'faces'):
                chosen = _picked(session, field['pick'])
                if chosen or not form['editing']:           # 编辑时没重新选 = 沿用原来的
                    if not chosen and not field.get('optional'):
                        raise ValueError(f'先在三维视图里点选{field["label"]}')
                    if field.get('count') and len(chosen) != field['count']:
                        raise ValueError(f'{field["label"]}要正好选 {field["count"]} 个')
                    args[key] = chosen
            elif key in values:
                if field['kind'] in ('sketch', 'path') and not values[key] and not field.get('optional'):
                    raise ValueError(f'还没有可选的{field["label"]}')
                args[key] = table.clean(field, values[key])
        return ('edit_feature', {'id': form['editing'], 'params': args}) if form['editing'] else (kind, args)
    if kind == 'extrude':
        end = values['end']
        args = {'end': end, 'distance': abs(values['distance']), 'op': values['op'], 'symmetric': end == 'mid',
                'reverse': bool(values['reverse']) and end not in ('mid', 'vertex', 'surface', 'offset'),
                'distance2': max(values['distance2'], 0.0) if end == 'blind' else 0.0, 'gap': values['gap'] if end == 'offset' else 0.0}
        if end in ('blind', 'mid') and abs(values['distance']) < 1e-9:
            raise ValueError('深度不能是 0')
        if end in END_PICKS:
            if END_PICKS[end][0] == 'vertex':
                corners = session.model.get('vertices')
                chosen = [{'point': [round(float(c), 6) for c in corners[i]]} for i in session.selection.get('vertices', ())
                          if corners is not None and i < len(corners)]
            else:
                chosen = _picked(session, 'face')
            if chosen:
                args['target'] = chosen[:1]
            elif not (form['editing'] and form.get('kept_end') == end):
                raise ValueError(f'先在三维视图里点一个{END_PICKS[end][1]}')
        if form['editing']:
            return 'edit_feature', {'id': form['editing'], 'params': args}
        if values.get('sketch'):
            args['sketch'] = values['sketch']
        return 'extrude', args
    if form['editing']:
        return 'edit_feature', {'id': form['editing'], 'params': values}
    key = 'radius' if kind == 'fillet' else 'distance'
    return kind, {'edges': _picked(session, 'edge'), key: values[key]}
