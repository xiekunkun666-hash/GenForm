# -*- coding: utf-8 -*-
"""查询命令 — AI 靠这些 "看" 模型: 模型描述 (修改命令的回复里也带一份精简的)、边、面、用户的选择。
在 commands 的命令表里登记 (commands.py 末尾导入本模块)。"""
from __future__ import annotations

from . import materials
from .commands import FEATURE_ID, command
from .document import DocumentError


def _params(feature):
    """一个特征的参数; 草图的图形和尺寸不展开 (可能很长, 发命令的人自己知道), 只说有几个。"""
    params = dict(feature['params'])
    if feature['type'] == 'sketch':
        params['shapes'] = f"{len(params.get('shapes') or [])} 个图形"
        if params.get('dims'):
            params['dims'] = f"{len(params['dims'])} 个尺寸"
    return params


def describe(session, brief=False, focus=(), only=None):
    """当前模型的文字描述: 特征树 (含每个特征算没算成) + 实体尺寸。
    brief: 特征只列 id / 类型 / 名称 / 状态 (修改命令的回复用这个: 文档大了以后全列一遍有几十 KB),
    focus 里的特征 (这次新建 / 改的) 才带参数。only: 只要这一个特征, 参数全部展开。"""
    document, model = session.document, session.model
    status = model.get('status', {})
    features = []
    for f in document.features:
        if only is not None and f['id'] != only:
            continue
        row = {'id': f['id'], 'type': f['type'], 'name': f['name'], 'status': status.get(f['id'], 'pending')}
        if not brief or f['id'] in focus:
            row['params'] = _params(f) if brief else f['params']
        features.append(row)
    if only is not None and not features:
        raise DocumentError(f'没有特征 {only}')
    material = document.props.get('material')
    result = {'features': features, 'rollback': document.upto, 'has_body': bool(model.get('has_body')),
              'path': document.path, 'unsaved_changes': document.dirty, 'material': material,
              'busy': session.busy, 'model_stale': session.model_revision != document.revision,
              'progress': session.progress, 'query_progress': session.query_progress}
    if not brief:
        result['materials'] = materials.NAMES
        if document.props.get('feature_colors'):
            result['feature_colors'] = dict(document.props['feature_colors'])
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


@command('get_model', '查看当前模型：特征列表（id、类型、参数、是否计算成功）和实体的尺寸、体积。'
                      '特征多时可以写 brief=true 只列 id / 类型 / 名称 / 状态，或写 id 只看那一个特征的全部参数。',
         {'id': dict(FEATURE_ID, description='只看这一个特征 (参数全部展开，含草图的每个图形)'),
          'brief': {'type': 'boolean', 'description': 'true = 特征不带参数'}})
def _get_model(session, args):
    return describe(session, brief=bool(args.get('brief')), only=args.get('id'))


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
