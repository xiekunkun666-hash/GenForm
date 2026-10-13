# -*- coding: utf-8 -*-
"""命令层: 软件能做的每一件事都是这里的一条命令。

界面上的按钮和 AI 的工具调用走的是同一张表 — 所以 AI 能做的和人能做的永远一致, 撤销也只有一套。
每条命令带名称、说明和参数格式 (JSON Schema), catalog() 直接就是给 AI 的工具清单。

命令函数签名: handler(session, args) → 结果字典。会改文档的命令 (mutates=True) 由 Session 在重算完成后
把特征状态和实体尺寸补进结果再回复。
"""
from __future__ import annotations

import copy

from . import features as table
from .document import DocumentError

_COMMANDS = {}


class Command:
    def __init__(self, name, description, properties, required, mutates, handler):
        self.name, self.description, self.mutates, self.handler = name, description, mutates, handler
        self.schema = {'type': 'object', 'properties': properties, 'required': list(required),
                       'additionalProperties': False}


def command(name, description, properties=None, required=(), mutates=False):
    def register(handler):
        _COMMANDS[name] = Command(name, description, properties or {}, required, mutates, handler)
        return handler
    return register


def get(name):
    if name not in _COMMANDS:
        raise DocumentError(f'没有这个命令: {name!r}。可用命令: {", ".join(sorted(_COMMANDS))}')
    return _COMMANDS[name]


def catalog():
    """给 AI 的工具清单: [{'name', 'description', 'input_schema'}...]。"""
    return [{'name': item.name, 'description': item.description, 'input_schema': item.schema}
            for item in _COMMANDS.values()]


def check(item, args):
    """调用前的基本检查: 缺必填参数、写了不认识的参数名 — 这两种是 AI 最常犯的, 要说清楚。"""
    if not isinstance(args, dict):
        raise DocumentError('命令参数要写成对象')
    known = item.schema['properties']
    unknown = [key for key in args if key not in known]
    if unknown:
        raise DocumentError(f'命令 {item.name} 没有参数 {", ".join(unknown)}；可用参数: {", ".join(known) or "无"}')
    missing = [key for key in item.schema['required'] if key not in args]
    if missing:
        raise DocumentError(f'命令 {item.name} 缺少参数 {", ".join(missing)}')


# ---------------------------------------------------------------------------
# 参数格式里反复用到的片段
# ---------------------------------------------------------------------------
NUMBER = {'type': 'number'}
NAME = {'type': 'string', 'description': '特征名称，不写则自动命名'}
FEATURE_ID = {'type': 'string', 'description': '特征 id，如 "f3"（见 get_model）'}
POINT_LIST = {'type': 'array', 'items': {'type': 'array', 'items': NUMBER, 'minItems': 2, 'maxItems': 2}}
SHAPES = {
    'type': 'array', 'minItems': 1,
    'description': ('草图里的图形，坐标是草图平面内的二维坐标 (mm)，角度是度 (逆时针为正)。每种 type 要写的参数：'
                    'line: x1 y1 x2 y2；arc: cx cy r a0 a1 (从 a0 逆时针到 a1)；circle: cx cy r；rect: cx cy w h；'
                    'polygon: points (封闭折线)；ngon 正多边形: cx cy r sides angle (r 是外接圆半径)；'
                    'slot 直槽口: x1 y1 x2 y2 w (两个圆心和槽宽)；ellipse: cx cy rx ry angle；'
                    'arcslot 圆弧槽口: cx cy r a0 a1 w (中心线圆弧 + 槽宽)；'
                    'spline: points closed (过这些点的样条；style=true 时 points 是控制点，最多 12 个)；point: x y (只作参考)；'
                    'equation 方程式曲线: mode="explicit" 时 fy 是 y=f(x) 的式子、t0 t1 是 x 的范围；mode="parametric" 时 fx fy 是 x(t) y(t)、'
                    't0 t1 是 t 的范围；ox oy 整体平移；式子里能用 x t pi e 和 sin cos tan asin acos atan sqrt abs exp log；'
                    '任何图形都可以加 construction=true 变成构造线 (中心线): 只作参考和旋转轴，不参与拉伸；'
                    'text: x y text height angle (height 是字高)，或给 path (一个 line/arc/circle/spline/ellipse 图形) 让字沿它排。'
                    '封闭的图形、以及端点首尾相接 (坐标完全一样) 围成一圈的 line/arc/spline 是轮廓，可以拉伸；'
                    '套在另一个轮廓里面的轮廓是孔。没围成圈的线只显示，不参与拉伸。'),
    'items': {'type': 'object', 'properties': {
        'type': {'enum': ['line', 'arc', 'circle', 'rect', 'polygon', 'ngon', 'slot', 'arcslot', 'ellipse', 'spline', 'equation',
                          'point', 'text']},
        'construction': {'type': 'boolean', 'description': 'true = 构造线 (中心线)'},
        'style': {'type': 'boolean', 'description': 'spline: true = 样式样条 (points 是控制点)'},
        'mode': {'enum': ['explicit', 'parametric']}, 'fx': {'type': 'string'}, 'fy': {'type': 'string'},
        't0': NUMBER, 't1': NUMBER, 'ox': NUMBER, 'oy': NUMBER,
        'cx': NUMBER, 'cy': NUMBER, 'x': NUMBER, 'y': NUMBER,
        'x1': NUMBER, 'y1': NUMBER, 'x2': NUMBER, 'y2': NUMBER,
        'w': {'type': 'number', 'description': 'rect 的宽 (平面 X 方向)；slot / arcslot 的槽宽'},
        'h': {'type': 'number', 'description': 'rect 的高 (平面 Y 方向)'},
        'r': {'type': 'number', 'description': 'circle / arc 的半径；ngon 的外接圆半径'},
        'rx': NUMBER, 'ry': NUMBER,
        'a0': {'type': 'number', 'description': 'arc 的起始角 (度)'},
        'a1': {'type': 'number', 'description': 'arc 的终止角 (度)，从 a0 逆时针转到 a1'},
        'angle': {'type': 'number', 'description': 'ellipse 长轴 / ngon 第一个顶点 / text 基线 的方向 (度)'},
        'sides': {'type': 'integer', 'description': 'ngon 的边数，3 到 100'},
        'points': dict(POINT_LIST, description='polygon 的顶点或 spline 经过的点 [[x, y], ...]'),
        'closed': {'type': 'boolean', 'description': 'spline 是否封闭'},
        'text': {'type': 'string'}, 'height': NUMBER,
        'font': {'type': 'string', 'description': '字体名，默认 Microsoft YaHei'},
        'path': {'type': 'object', 'description': 'text 沿着排的曲线 (一个图形)'},
        'flip': {'type': 'boolean', 'description': 'text 沿 path 排时反过来走'},
    }, 'required': ['type']},
}
EDGES = {
    'description': ('要处理的边。可以是选择器字符串: "all" 全部边, "|Z" 平行于 Z 轴的直边 (X/Y 同理), '
                    '">Z" 最高处的一圈边, "<Z" 最低处的一圈边 (X/Y 同理)；'
                    '也可以是边的列表 [{"point": [x, y, z]}, ...]，point 是边中点坐标 (用 list_edges 查)。'),
    'anyOf': [{'type': 'string'},
              {'type': 'array', 'items': {'type': 'object', 'properties': {
                  'point': {'type': 'array', 'items': NUMBER, 'minItems': 3, 'maxItems': 3}},
                  'required': ['point']}}],
}


# ---------------------------------------------------------------------------
# 建模
# ---------------------------------------------------------------------------
@command('sketch', '新建草图：在基准面上画一组图形（直线、圆弧、矩形、槽口、样条、文本…），围成封闭轮廓的部分供 extrude 使用。',
         {'plane': {'type': 'string', 'description': 'XY=上视(法向+Z)，XZ=前视(法向-Y)，YZ=右视(法向+X)；或基准面特征 (plane) 的 id'},
          'offset': {'type': 'number', 'description': '沿基准面法向偏移 (mm)，默认 0'},
          'shapes': SHAPES, 'name': NAME},
         required=('shapes',), mutates=True)
def _sketch(session, args):
    params = {'plane': args.get('plane', 'XY'), 'offset': float(args.get('offset', 0.0)), 'shapes': args['shapes']}
    try:
        table.plane_frame(params['plane'], session.document.features)
    except ValueError as error:
        raise DocumentError(str(error)) from None
    return {'id': session.document.add('sketch', params, args.get('name'))}


@command('extrude', '拉伸草图成实体：op="add" 加料（没有实体时创建实体），op="cut" 从现有实体切除，op="common" 只留和现有实体重叠的部分。',
         {'sketch': {'type': 'string', 'description': '草图特征 id；不写则用最近的草图'},
          'distance': {'type': 'number', 'description': '拉伸距离 (mm)，沿草图法向；负数反向'},
          'op': {'enum': ['add', 'cut', 'common'], 'description': '默认 add'},
          'symmetric': {'type': 'boolean', 'description': 'true 则以草图平面为中心两侧各拉一半'},
          'name': NAME},
         required=('distance',), mutates=True)
def _extrude(session, args):
    source = args.get('sketch') or session.document.last('sketch')
    if source is None:
        raise DocumentError('还没有草图，先用 sketch 画一个')
    if session.document.find(source)['type'] != 'sketch':
        raise DocumentError(f'{source} 不是草图')
    params = {'sketch': source, 'distance': float(args['distance']), 'op': args.get('op', 'add'),
              'symmetric': bool(args.get('symmetric', False))}
    return {'id': session.document.add('extrude', params, args.get('name'))}


@command('fillet', '给实体的边倒圆角。', {'edges': EDGES, 'radius': {'type': 'number', 'description': '半径 (mm)'},
                                 'name': NAME},
         required=('edges', 'radius'), mutates=True)
def _fillet(session, args):
    params = {'edges': args['edges'], 'radius': float(args['radius'])}
    return {'id': session.document.add('fillet', params, args.get('name'))}


@command('chamfer', '给实体的边倒斜角。', {'edges': EDGES, 'distance': {'type': 'number', 'description': '倒角距离 (mm)'},
                                  'name': NAME},
         required=('edges', 'distance'), mutates=True)
def _chamfer(session, args):
    params = {'edges': args['edges'], 'distance': float(args['distance'])}
    return {'id': session.document.add('chamfer', params, args.get('name'))}


# ---- 特征表 (features.py) 里登记的特征: 每种一条命令, 参数格式从表里生成 ----
FACES = {'type': 'array', 'description': '面的列表 [{"point": [x, y, z]}, ...]，point 是面中心坐标 (用 list_faces 查)',
         'items': {'type': 'object', 'properties': {'point': {'type': 'array', 'items': NUMBER, 'minItems': 3, 'maxItems': 3}},
                   'required': ['point']}}
REFERENCE_KINDS = {'sketch': ('sketch',), 'path': ('sketch',) + table.CURVE_KINDS}


def _field_schema(field):
    kind, text = field['kind'], field['label'] + ('。' + field['help'] if field.get('help') else '')
    if kind == 'number':
        return {'type': 'number', 'description': text + (f' ({field["unit"]})' if field.get('unit') else '')}
    if kind == 'int':
        return {'type': 'integer', 'description': text}
    if kind == 'bool':
        return {'type': 'boolean', 'description': text}
    if kind == 'choice':
        labels = '，'.join(f'{option["value"]}={option["label"]}' for option in field['options'])
        return {'enum': [option['value'] for option in field['options']], 'description': f'{text}：{labels}'}
    if kind == 'points':
        return {'type': 'array', 'description': text, 'items': {'type': 'array', 'items': NUMBER}}
    if kind in ('sketches', 'features'):
        return {'type': 'array', 'description': text, 'items': {'type': 'string'}}
    if kind == 'edges':
        return dict(EDGES, description=text + '。' + EDGES['description'])
    if kind == 'faces':
        return dict(FACES, description=text + '。' + FACES['description'])
    hints = {'sketch': '草图特征的 id；不写则用最近的草图', 'path': '草图或曲线特征的 id',
             'plane': 'XY / XZ / YZ 或基准面特征的 id', 'axis': ''}
    return {'type': 'string', 'description': text + ('。' + hints[kind] if hints.get(kind) and not field.get('help') else '')}


def _register_feature(kind, spec):
    fields = spec['fields']
    properties = {field['key']: _field_schema(field) for field in fields}
    properties['name'] = NAME
    required = [field['key'] for field in fields
                if field['default'] in (None, []) and field['kind'] not in ('sketch', 'features') and not field.get('optional')]

    def handler(session, args):
        document, params = session.document, {}
        for field in fields:
            key = field['key']
            if key in args:
                params[key] = table.clean(field, args[key])
            elif field['kind'] == 'sketch':
                params[key] = document.last('sketch')
                if params[key] is None:
                    raise DocumentError('还没有草图，先用 sketch 画一个')
            else:
                params[key] = copy.deepcopy(field['default'])
            wanted = REFERENCE_KINDS.get(field['kind'])
            if wanted and document.find(params[key])['type'] not in wanted:
                raise DocumentError(f'参数 {key}: {params[key]} 不是{"草图" if field["kind"] == "sketch" else "草图或曲线"}')
            if field['kind'] in ('sketches', 'features'):
                for identifier in params[key]:
                    document.find(identifier)
        return {'id': document.add(kind, params, args.get('name'))}

    _COMMANDS[kind] = Command(kind, f'{spec["title"]}：{spec["about"]}', properties, required, True, handler)


for _kind, _spec in table.SPECS.items():
    _register_feature(_kind, _spec)


# ---------------------------------------------------------------------------
# 特征历史
# ---------------------------------------------------------------------------
@command('edit_feature', '修改已有特征的参数（只写要改的键），之后的特征自动重算。例如把拉伸距离改成 20: '
                         '{"id": "f2", "params": {"distance": 20}}。',
         {'id': FEATURE_ID, 'params': {'type': 'object', 'description': '要覆盖的参数'}},
         required=('id', 'params'), mutates=True)
def _edit(session, args):
    session.document.edit(args['id'], args['params'])
    return {'id': args['id']}


@command('delete_feature', '删除一个特征。', {'id': FEATURE_ID}, required=('id',), mutates=True)
def _delete(session, args):
    session.document.delete(args['id'])
    return {}


@command('suppress_feature', '抑制 / 恢复一个特征（抑制 = 暂时当它不存在，参数保留）。',
         {'id': FEATURE_ID, 'suppressed': {'type': 'boolean', 'description': '默认 true'}},
         required=('id',), mutates=True)
def _suppress(session, args):
    session.document.suppress(args['id'], args.get('suppressed', True))
    return {'id': args['id']}


@command('rename_feature', '给特征改名。', {'id': FEATURE_ID, 'name': {'type': 'string'}},
         required=('id', 'name'), mutates=True)
def _rename(session, args):
    session.document.rename(args['id'], args['name'])
    return {'id': args['id']}


@command('rollback', '把特征历史回滚到第 count 个特征之后（之后的特征暂不计算）；不写 count 则取消回滚。',
         {'count': {'type': 'integer', 'minimum': 0}}, mutates=True)
def _rollback(session, args):
    session.document.rollback(args.get('count'))
    return {}


@command('set_material', '给零件指定材质（用来算质量，零件的颜色也跟着变）；name 不写或写空 = 不指定。',
         {'name': {'type': 'string', 'description': '材质名，见 get_model 结果里的 materials'}})
def _set_material(session, args):
    from . import materials
    name = args.get('name') or ''
    if name and name not in materials.NAMES:
        raise DocumentError(f'没有这种材质 {name!r}；可用: {"、".join(materials.NAMES)}')
    session.document.set_prop('material', name)
    session.notify()
    return {'material': name or None}


@command('set_appearance', '改零件的外观颜色；color 不写或写空 = 跟随材质。',
         {'color': {'type': 'string', 'description': '颜色，写成 #RRGGBB'}})
def _set_appearance(session, args):
    from . import materials
    color = args.get('color') or ''
    if color and materials.rgb(color) is None:
        raise DocumentError('颜色要写成 #RRGGBB，比如 #4C94FF')
    session.document.set_prop('color', color)
    session.notify()
    return {'color': color or None}


@command('undo', '撤销上一步操作。', mutates=True)
def _undo(session, args):
    session.document.undo()
    return {}


@command('redo', '重做刚撤销的操作。', mutates=True)
def _redo(session, args):
    session.document.redo()
    return {}


# ---------------------------------------------------------------------------
# 文档
# ---------------------------------------------------------------------------
@command('new_document', '清空当前文档，开始一个新零件（没保存的修改会丢失）。', mutates=True)
def _new(session, args):
    session.document.clear()
    return {}


@command('save_document', '保存文档（.gform，记录的是特征历史，可以继续编辑）。',
         {'path': {'type': 'string', 'description': '保存路径；已保存过可以不写'}})
def _save(session, args):
    session.document.save(args.get('path'))
    session.notify()
    return {'path': session.document.path}


@command('open_document', '打开 .gform 文档。', {'path': {'type': 'string'}}, required=('path',), mutates=True)
def _open(session, args):
    session.document.open(args['path'])
    return {'path': session.document.path}


# ---------------------------------------------------------------------------
# 查询 — AI 靠这些 "看" 模型
# ---------------------------------------------------------------------------
def describe(session):
    """当前模型的文字描述: 特征树 (含每个特征算没算成) + 实体尺寸。"""
    document, model = session.document, session.model
    status = model.get('status', {})
    features = [{'id': f['id'], 'type': f['type'], 'name': f['name'], 'params': f['params'],
                 'status': status.get(f['id'], 'pending')} for f in document.features]
    from . import materials
    material = document.props.get('material')
    result = {'features': features, 'rollback': document.upto, 'has_body': bool(model.get('has_body')),
              'path': document.path, 'unsaved_changes': document.dirty,
              'material': material, 'materials': materials.NAMES}
    if model.get('has_body') and materials.density(material):
        result['mass_g'] = round(model['props']['volume'] / 1000.0 * materials.density(material), 3)
    if model.get('has_body'):
        props = model['props']
        result['body'] = {'size_mm': _round(props['size']), 'bbox_min': _round(props['bbox_min']),
                          'bbox_max': _round(props['bbox_max']), 'volume_mm3': round(props['volume'], 3),
                          'area_mm2': round(props['area'], 3), 'faces': len(model['faces']),
                          'edges': len(model['edges'])}
    return result


def _round(values, digits=4):
    return [round(float(value), digits) for value in values]


@command('get_model', '查看当前模型：特征列表（id、类型、参数、是否计算成功）和实体的尺寸、体积。')
def _get_model(session, args):
    return describe(session)


@command('list_edges', '列出实体的边：类型、中点坐标、长度、方向。fillet / chamfer 用中点坐标引用边。',
         {'type': {'enum': ['line', 'circle', 'curve'], 'description': '只列这种类型'}})
def _list_edges(session, args):
    edges = session.model.get('edges') or []
    wanted = args.get('type')
    rows = []
    for edge in edges:
        if wanted and edge['type'] != wanted:
            continue
        row = {'type': edge['type'], 'point': _round(edge['mid']), 'length': round(edge['length'], 4)}
        if edge.get('dir') is not None:
            row['direction'] = _round(edge['dir'])
        if 'radius' in edge:
            row['radius'] = round(edge['radius'], 4)
        rows.append(row)
    return {'edges': rows}


@command('list_faces', '列出实体的面：类型、中心坐标、面积，平面带法向，圆柱面带半径。')
def _list_faces(session, args):
    rows = []
    for face in session.model.get('faces') or []:
        row = {'type': face['type'], 'center': _round(face['center']), 'area': round(face['area'], 4)}
        if face.get('normal') is not None:
            row['normal'] = _round(face['normal'])
        if 'radius' in face:
            row['radius'] = round(face['radius'], 4)
        rows.append(row)
    return {'faces': rows}


@command('get_selection', '查看用户在三维视图里选中了什么（面、边、基准面）。用户说 "这条边" "这个面" 时用它。')
def _get_selection(session, args):
    model, selection = session.model, session.selection
    edges = {edge['id']: edge for edge in model.get('edges') or []}
    faces = {face['id']: face for face in model.get('faces') or []}
    return {'edges': [{'type': edges[i]['type'], 'point': _round(edges[i]['mid'])}
                      for i in selection.get('edges', ()) if i in edges],
            'faces': [{'type': faces[i]['type'], 'center': _round(faces[i]['center'])}
                      for i in selection.get('faces', ()) if i in faces],
            'feature': selection.get('feature'), 'plane': selection.get('plane')}


# ---------------------------------------------------------------------------
# 导出 / 视图 (由 Session 接到内核和界面上)
# ---------------------------------------------------------------------------
@command('export', '导出实体：.step / .stp 是精确几何（给其他 CAD），.stl 是三角网格（给切片软件）。',
         {'path': {'type': 'string'}}, required=('path',))
def _export(session, args):
    return session.export(args['path'])


@command('set_view', '切换三维视图方向。',
         {'view': {'enum': ['iso', 'top', 'bottom', 'front', 'back', 'left', 'right', 'fit']}}, required=('view',))
def _set_view(session, args):
    return session.view_call('set_view', args['view'])


@command('screenshot', '把三维视图当前画面存成 PNG，返回文件路径 — AI 用它看模型长什么样。',
         {'path': {'type': 'string', 'description': '保存路径；不写则存到临时目录'},
          'view': {'enum': ['iso', 'top', 'bottom', 'front', 'back', 'left', 'right'],
                   'description': '先切到这个方向再截图'}})
def _screenshot(session, args):
    return session.view_call('screenshot', args.get('path'), args.get('view'))
