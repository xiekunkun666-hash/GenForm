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
    def __init__(self, name, description, properties, required, mutates, handler, geometry=True):
        self.name, self.description, self.mutates, self.handler = name, description, mutates, handler
        self.geometry = geometry        # False: 改了文档但不动几何 (改名…), 不用重算
        self.schema = {'type': 'object', 'properties': properties, 'required': list(required),
                       'additionalProperties': False}


def command(name, description, properties=None, required=(), mutates=False, geometry=True):
    def register(handler):
        _COMMANDS[name] = Command(name, description, properties or {}, required, mutates, handler, geometry)
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
          'shapes': SHAPES, 'name': NAME,
          'dims': {'type': 'array', 'items': {'type': 'object'},
                   'description': '草图里标着的尺寸 (界面的智能尺寸放下的, 只是标出来; 一般不用写)'}},
         required=('shapes',), mutates=True)
def _sketch(session, args):
    params = {'plane': args.get('plane', 'XY'), 'offset': float(args.get('offset', 0.0)), 'shapes': args['shapes']}
    if args.get('dims'):
        params['dims'] = list(args['dims'])
    try:
        table.plane_frame(params['plane'], session.document.features)
    except ValueError as error:
        raise DocumentError(str(error)) from None
    return {'id': session.document.add('sketch', params, args.get('name'))}


@command('extrude', '拉伸草图成实体：op="add" 加料（没有实体时创建实体），op="cut" 从现有实体切除，op="common" 只留和现有实体重叠的部分；'
                    '空心件 (钣金) 用 void 挖空腔 / fill 填空腔 / pocket 钣金凹槽，见 op 的说明。',
         {'sketch': {'type': 'string', 'description': '草图特征 id；不写则用最近的草图'},
          'distance': {'type': 'number', 'description': '拉伸距离 (mm)，沿草图法向；负数反向。end 是 blind / mid 时要写'},
          'op': {'enum': [option['value'] for option in table.OPS], 'description': '默认 add。' + table.OP_HELP},
          'wall': {'type': 'number', 'description': 'op="pocket" 时槽壁、槽底的壁厚 (mm)，默认 2'},
          'symmetric': {'type': 'boolean', 'description': 'true 则以草图平面为中心两侧各拉一半 (等于 end="mid")'},
          'end': {'enum': ['blind', 'through', 'vertex', 'surface', 'offset', 'body', 'mid'],
                  'description': '拉到哪为止: blind 给定深度 (默认) / mid 两侧对称 / through 完全贯穿 / vertex 成形到顶点 / '
                                 'surface 成形到面 / offset 到离指定面指定的距离 / body 成形到实体'},
          'reverse': {'type': 'boolean', 'description': 'true = 往草图法向的反方向拉'},
          'distance2': {'type': 'number', 'description': 'end="blind" 时反方向再拉这么多 (方向 2)；0 = 不要'},
          'target': {'type': 'array', 'description': 'end 是 vertex 时: [{"point": 顶点坐标}]；surface / offset 时: [{"point": 面中心坐标}]'},
          'gap': {'type': 'number', 'description': 'end="offset" 时离那张面还差多少 (mm)；负数 = 越过它'},
          'name': NAME},
         mutates=True)
def _extrude(session, args):
    end = args.get('end') or ('mid' if args.get('symmetric') else 'blind')
    if end in ('blind', 'mid') and args.get('distance') is None:
        raise DocumentError('命令 extrude 缺少参数 distance')
    source = args.get('sketch') or session.document.last('sketch')
    if source is None:
        raise DocumentError('还没有草图，先用 sketch 画一个')
    if session.document.find(source)['type'] != 'sketch':
        raise DocumentError(f'{source} 不是草图')
    params = {'sketch': source, 'distance': float(args.get('distance') or 10.0), 'op': args.get('op', 'add'),
              'symmetric': end == 'mid', 'end': end, 'reverse': bool(args.get('reverse', False)),
              'distance2': float(args.get('distance2') or 0.0), 'gap': float(args.get('gap') or 0.0),
              'target': list(args.get('target') or [])}
    if params['op'] not in [option['value'] for option in table.OPS]:
        raise DocumentError(f'不认识的方式 {params["op"]!r}')
    if args.get('wall') is not None:
        params['wall'] = float(args['wall'])
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
            elif field['kind'] == 'sketch' and not field.get('optional'):
                params[key] = document.last('sketch')
                if params[key] is None:
                    raise DocumentError('还没有草图，先用 sketch 画一个')
            else:
                params[key] = copy.deepcopy(field['default'])
            wanted = REFERENCE_KINDS.get(field['kind'])
            if wanted and (params[key] or not field.get('optional')) and document.find(params[key])['type'] not in wanted:
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
         required=('id', 'name'), mutates=True, geometry=False)
def _rename(session, args):
    session.document.rename(args['id'], args['name'])
    return {'id': args['id']}


@command('set_folder', '把特征放进设计树的文件夹 (只是归类, 不影响几何, 不重算)：folder 用 / 分层，比如 "内饰/座椅"；'
                       '写空 = 拿出文件夹。同一个文件夹里的特征最好排在一起 (隔开了树上会分成两段)。',
         {'features': {'type': 'array', 'items': {'type': 'string'}, 'description': '特征 id 列表'},
          'folder': {'type': 'string', 'description': '文件夹路径，/ 分层'}},
         required=('features',), mutates=True, geometry=False)
def _set_folder(session, args):
    targets = list(args.get('features') or [])
    if not targets:
        raise DocumentError('要写上特征 id（features）')
    session.document.set_folder(targets, args.get('folder') or '')
    return {'features': targets, 'folder': args.get('folder') or None}


def _design_rules(session):
    from . import rules
    return rules.effective(getattr(session, 'design_rules', None), session.document.props.get('rules'))


def _geometry_unchanged(session, before):
    """只改了工艺这类不影响几何的东西: 现成的模型照用 (和 execute 里 geometry=False 的命令一样)。"""
    if not session.busy and session.model_revision == before:
        session.model_revision = session.document.revision
    session.notify()


@command('list_processes', '列出软件认识的加工工艺：id、名称、类别、最小壁厚、最大尺寸、精度、交期。绑定工艺时按性价比在这些里面挑。')
def _list_processes(session, args):
    from . import manufacturing
    return {'processes': manufacturing.catalog()}


@command('get_design_rules', '查看设计规则 (设计检查按它判断)：公差、件与件最小间隙、连接最小压入量、最小壁厚、孔、内角圆角、字高、生产数量。')
def _get_rules(session, args):
    from . import rules
    return {'rules': _design_rules(session), 'table': rules.table(), 'document': dict(session.document.props.get('rules') or {})}


@command('set_design_rules', '改设计规则：values 写要改的键 (见 get_design_rules)；scope="document" 只对这个零件 (存进文档)，'
                             '"user" 改用户设置里的默认值 (所有零件共用)。',
         {'values': {'type': 'object', 'description': '规则键 → 数值'},
          'scope': {'enum': ['document', 'user'], 'description': '默认 document'}},
         required=('values',))
def _set_rules(session, args):
    from . import rules
    values = rules.clean(args.get('values') or {})
    if not values:
        raise DocumentError('values 里没有认识的规则；可用: ' + '、'.join(rules.DEFAULTS))
    if args.get('scope') == 'user':
        if getattr(session, 'design_rules', None) is None:
            raise DocumentError('没有打开界面，没有用户设置；用 scope="document"')
        session.design_rules.update(values)
        if getattr(session, 'save_rules', None):
            session.save_rules()
    else:
        session.document.set_prop('rules', dict(session.document.props.get('rules') or {}, **values))
    session.notify()
    return {'rules': _design_rules(session)}


@command('bind_processes', '自动给特征绑定现实里能做出来的加工工艺 (激光切割、折弯、冲压、手工钣金、CNC、车削、铸造、注塑、3D 打印、外购…)：'
                           '按生产数量摊模具费，挑每件最便宜的那种；绑好后设计树里特征名前面显示工艺。手动指定过的不动。',
         {'features': {'type': 'array', 'items': {'type': 'string'}, 'description': '只绑这些特征；不写 = 全部'},
          'batch': {'type': 'integer', 'description': '生产数量；不写用设计规则里的'}})
def _bind_processes(session, args):
    from . import manufacturing
    batch = int(args.get('batch') or _design_rules(session)['batch'])
    only = set(args['features']) if args.get('features') else None
    for identifier in only or ():
        session.document.find(identifier)
    material = session.document.props.get('material') or ''

    def run(reply):
        before = session.document.revision

        def done(report, error):
            if error:
                reply({'ok': False, 'error': error})
                return
            bound = manufacturing.bind(session.document.features, report, batch, material, only)
            changed = {identifier: process for identifier, process in bound.items()
                       if session.document.find(identifier).get('process') != process}
            if changed:
                session.document.set_processes(changed)
                _geometry_unchanged(session, before)
            counts = {}
            for process in bound.values():
                label = process.get('name') or '没有合适的工艺'
                counts[label] = counts.get(label, 0) + 1
            reply({'ok': True, 'bound': len(bound), 'batch': batch, 'processes': counts,
                   'features': {identifier: {'process': process.get('id'), 'name': process.get('name'), 'why': process.get('why')}
                                for identifier, process in bound.items()}})
        session.query('inspect', {}, done)
    return run


@command('set_process', '手动给一个特征指定加工工艺 (自动绑定不会再改它)；process 写 list_processes 里的 id，写空 = 解除。'
                        'cost = 每件的价钱 (元，供应商报价；外购总成、标准件写上它物料清单才算得出成本)，spec = 规格型号。',
         {'feature': FEATURE_ID, 'process': {'type': 'string', 'description': '工艺 id'},
          'cost': {'type': 'number', 'minimum': 0, 'description': '每件多少钱 (元)'},
          'spec': {'type': 'string', 'description': '规格型号 (标准件、外购件)'}},
         required=('feature',), mutates=True, geometry=False)
def _set_process(session, args):
    from . import manufacturing
    feature = session.document.find(args['feature'])
    key = args.get('process') or ''
    if not key:
        session.document.set_processes({feature['id']: None})
        return {'feature': feature['id'], 'process': None}
    item = manufacturing.BY_ID.get(key)
    if item is None:
        raise DocumentError(f'没有这种工艺 {key!r}；可用: {"、".join(manufacturing.BY_ID)}')
    process = {'id': item['id'], 'name': item['name'], 'short': item['short'], 'color': item['color'], 'auto': False,
               'kind': (feature.get('process') or {}).get('kind'), 'why': '手动指定', 'alternatives': [],
               'standard': item['id'] in manufacturing.STANDARD}
    if args.get('cost') is not None:
        cost = float(args['cost'])
        if cost < 0:
            raise DocumentError('cost 不能是负数')
        process.update(cost=cost, unit=cost, tooling=0.0, why=f'手动指定：每件 ¥{cost:,.2f}')
    if args.get('spec'):
        process['spec'] = str(args['spec'])
        process['why'] = f'{process["spec"]}。{process["why"]}'
    session.document.set_processes({feature['id']: process})
    return {'feature': feature['id'], 'process': key}


@command('check_design', '设计检查 (像 PCB 的 DRC)：特征出错、实体无效、悬空的零件、件与件间隙太小 / 只贴着 / 压得太浅、没材质、没绑工艺、'
                         '工艺做不了、壁太薄、孔太小太深、铣不出的尖内角、字太小、封闭空腔、成本汇总。按设计规则判断。')
def _check_design(session, args):
    from . import checks

    def run(reply):
        rules = _design_rules(session)

        def done(report, error):
            if error:
                reply({'ok': False, 'error': error})
                return
            issues = checks.run(session.document.features, session.model, report, rules, session.document.props.get('material') or '')
            session.last_check = issues
            if getattr(session, 'on_check', None):
                session.on_check(issues)
            reply({'ok': True, 'counts': checks.summary(issues), 'issues': issues, 'red': checks.red_features(issues)})
        session.query('inspect', {'rules': rules}, done)
    return run


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


@command('set_appearance', '改外观颜色：不写 features = 整个零件 (color 不写或写空 = 跟随材质)；'
                           '写了 features = 只给这些特征做出来的面上色 (轮胎、玻璃、灯…；color 写空 = 回到零件的颜色)。'
                           '阵列 / 镜像复制出来的面没单独上色时跟着原件的颜色。'
                           'opacity (0.05~1) 让这些特征的面半透明 (玻璃、灯罩: 隔着能看见里面)，写 1 = 不透明；只给 opacity 不给 color 时颜色不变。',
         {'color': {'type': 'string', 'description': '颜色，写成 #RRGGBB'},
          'opacity': {'type': 'number', 'minimum': 0.05, 'maximum': 1, 'description': '不透明度，只对写了 features 的有用'},
          'features': {'type': 'array', 'items': {'type': 'string'}, 'description': '特征 id 列表 (见 get_model)'}})
def _set_appearance(session, args):
    from . import materials
    color = args.get('color') or ''
    if color and materials.rgb(color) is None:
        raise DocumentError('颜色要写成 #RRGGBB，比如 #4C94FF')
    targets = list(args.get('features') or [])
    if not targets:
        session.document.set_prop('color', color)
        session.notify()
        return {'color': color or None}
    known = {feature['id'] for feature in session.document.features}
    missing = [identifier for identifier in targets if identifier not in known]
    if missing:
        raise DocumentError(f'没有这些特征: {", ".join(missing)}')
    opacity = args.get('opacity')
    if opacity is not None:
        opacity = float(opacity)
        if not 0.05 <= opacity <= 1.0:
            raise DocumentError('opacity 要在 0.05 到 1 之间')
        shades = dict(session.document.props.get('feature_opacity') or {})
        for identifier in targets:
            if opacity >= 1.0:
                shades.pop(identifier, None)
            else:
                shades[identifier] = round(opacity, 3)
        session.document.set_prop('feature_opacity', shades or None)
        if not color and 'color' not in args:           # 只改透明度: 颜色不动
            session.notify()
            return {'opacity': opacity, 'features': targets}
    colors = dict(session.document.props.get('feature_colors') or {})
    for identifier in targets:
        if color:
            colors[identifier] = color
        else:
            colors.pop(identifier, None)
    session.document.set_prop('feature_colors', colors or None)
    session.notify()
    return {'color': color or None, 'opacity': opacity, 'features': targets}


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
    if hasattr(session.builder, 'keep'):        # 算好的样子也存一份到磁盘缓存: 下次打开不用从头算
        session.builder.keep(copy.deepcopy(session.document.features), session.document.upto)
    session.notify()
    return {'path': session.document.path}


@command('load_layout', '装配体的布局草图：把 .gasm 里存着的草图载入现在这个（没有实体的）文档。界面打开装配体时用。',
         {'data': {'type': 'object', 'description': 'Document.to_data() 的内容'}}, required=('data',), mutates=True)
def _load_layout(session, args):
    session.document.load_data(args['data'])
    return {'features': len(session.document.features)}


@command('open_document', '打开 .gform 文档。', {'path': {'type': 'string'}}, required=('path',), mutates=True)
def _open(session, args):
    session.document.open(args['path'])
    return {'path': session.document.path}


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


# ---------------------------------------------------------------------------
# 一次做一串
# ---------------------------------------------------------------------------
@command('batch', '一次执行一串会改文档的命令，全部做完才重算一次——要连着加很多特征时用它，比一条条发快得多'
                  '（一条条发每条都要等重算、等回复）。steps 里每一项是 {"cmd": 命令名, "args": 参数, "as": 可选的别名}。'
                  '后面的步骤要引用前面步骤新建的特征时，把 id 写成 "$3"（第 3 步的结果，从 1 数）或 "$别名"。'
                  '例如 [{"cmd": "sketch", "args": {...}, "as": "s"}, {"cmd": "extrude", "args": {"sketch": "$s", "distance": 5}}]。'
                  '有一步参数不对就整串都不做（文档保持原样），并说出是第几步、错在哪。几何算不成的特征和单条命令一样留在特征列表里。',
         {'steps': {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'properties': {
             'cmd': {'type': 'string'}, 'args': {'type': 'object'}, 'as': {'type': 'string'}}, 'required': ['cmd']}}},
         required=('steps',), mutates=True)
def _batch(session, args):
    document, made, names = session.document, [], {}
    state = copy.deepcopy(vars(document))

    def fill(value):
        if isinstance(value, str) and value.startswith('$'):
            key = value[1:]
            found = made[int(key) - 1] if key.isdigit() and 0 < int(key) <= len(made) else names.get(key)
            if found is None:
                raise DocumentError(f'{value} 指的那一步还没有做出特征')
            return found
        if isinstance(value, list):
            return [fill(item) for item in value]
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        return value

    try:
        for number, step in enumerate(args['steps'], 1):
            try:
                item = get(str(step.get('cmd')))
                if not item.mutates or item.name in ('batch', 'undo', 'redo', 'new_document', 'open_document'):
                    raise DocumentError(f'batch 里只能放新建和修改特征的命令，{item.name} 请单独发')
                values = fill(dict(step.get('args') or {}))
                check(item, values)
                result = item.handler(session, values)
            except (DocumentError, TypeError, ValueError, KeyError) as error:
                raise DocumentError(f'第 {number} 步 ({step.get("cmd")}) 没做成：{error}。整串都没有执行') from None
            made.append(result.get('id') if isinstance(result, dict) else None)
            if step.get('as'):
                names[str(step['as'])] = made[-1]
    except Exception:
        vars(document).clear()
        vars(document).update(state)
        raise
    return {'ids': made, 'count': len(made)}


from .queries import describe  # noqa: E402,F401  查询命令 (get_model、list_edges…) 在 queries.py 里登记
