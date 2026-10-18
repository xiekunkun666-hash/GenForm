# -*- coding: utf-8 -*-
"""软件里能点的每个功能登记成一条 "动作": 快捷键设置、右键手势轮都从这张表里挑。

动作 id 的写法:
    file.new / file.open …    文件
    edit.undo …               编辑
    cmd:<特征>                特征页上的命令 (cmd:extrude、cmd:revolve_cut …)
    sketch.start …            进出草图
    tool:<工具>               草图工具 (tool:line …), 以及 sketch.pattern 这类带面板的操作
    view:<视角或取景>         view:front、view:fit …
    style:<显示样式>          style:wire …
真正执行在 app.runAction。
"""
from __future__ import annotations

from . import features as table


def _a(identifier, title, group, icon, key=''):
    return {'id': identifier, 'title': title, 'group': group, 'icon': icon, 'default': key}


_FEATURES = [('extrude', '拉伸凸台/基体', 'extrude', 'E'), ('revolve', '旋转凸台/基体', 'revolve', ''), ('sweep', '扫描', 'sweep', ''),
             ('loft', '放样凸台/基体', 'loft', ''), ('boundary', '边界凸台/基体', 'boundary', ''), ('cut', '拉伸切除', 'cut', ''),
             ('revolve_cut', '旋转切除', 'revolve', ''), ('sweep_cut', '扫描切除', 'sweep', ''), ('loft_cut', '放样切除', 'loft', ''),
             ('fillet', '圆角', 'fillet', 'F'), ('chamfer', '倒角', 'chamfer', '')]
_TOOLS = [('select', '选择', ''), ('dimension', '智能尺寸', 'D'), ('line', '直线', 'L'), ('centerline', '中心线', ''), ('midline', '中点线', ''),
          ('rect', '边角矩形', 'R'), ('crect', '中心矩形', ''), ('rect3', '3 点边角矩形', ''), ('crect3', '3 点中心矩形', ''),
          ('pgram', '平行四边形', ''), ('ngon', '多边形', ''), ('slot', '直槽口', ''), ('cslot', '中心点直槽口', ''),
          ('aslot3', '三点圆弧槽口', ''), ('caslot', '中心点圆弧槽口', ''), ('circle', '圆', 'C'), ('circle3', '周边圆', ''),
          ('ellipse', '椭圆', ''), ('arc', '圆心/起/终点画弧', 'A'), ('spline', '样条曲线', ''), ('sspline', '样式样条曲线', ''),
          ('equation', '方程式驱动的曲线', ''), ('point', '点', ''), ('text', '文本', ''), ('fillet', '绘制圆角', ''),
          ('trim', '剪裁实体', 'T'), ('extend', '延伸实体', ''), ('offset', '等距实体', 'O'), ('mirror', '镜向实体', ''),
          ('move', '移动实体', 'M'), ('convert', '转换实体引用', '')]
_VIEWS = [('fit', '整屏显示全图', 'fit', 'Z'), ('zoom_box', '局部放大', 'zoom_box', ''), ('previous', '上一个视图', 'previous', 'Ctrl+Shift+Z'),
          ('front', '前视', 'front', 'Ctrl+1'), ('back', '后视', 'back', 'Ctrl+2'), ('left', '左视', 'left', 'Ctrl+3'),
          ('right', '右视', 'right', 'Ctrl+4'), ('top', '上视', 'top', 'Ctrl+5'), ('bottom', '下视', 'bottom', 'Ctrl+6'),
          ('iso', '等轴测', 'cube', 'Ctrl+7'), ('normal', '正视于', 'normal', 'Ctrl+8')]
_STYLES = [('shaded_edges', '带边线上色'), ('shaded', '上色'), ('hlr', '消除隐藏线'), ('hlv', '隐藏线可见'), ('wire', '线架图')]


def _build():
    rows = [_a('file.new', '新建', '文件', 'new', 'Ctrl+N'), _a('file.open', '打开', '文件', 'open', 'Ctrl+O'),
            _a('file.save', '保存', '文件', 'save', 'Ctrl+S'), _a('file.export', '导出 STEP / STL', '文件', 'export', ''),
            _a('app.settings', '设置', '文件', 'gear', 'Ctrl+,'),
            _a('edit.undo', '撤销', '编辑', 'undo', 'Ctrl+Z'), _a('edit.redo', '重做', '编辑', 'redo', 'Ctrl+Y'),
            _a('edit.delete', '删除选中的', '编辑', 'cancel', 'Del')]
    rows += [_a(f'cmd:{kind}', title, '特征', icon, key) for kind, title, icon, key in _FEATURES]
    listed = {kind for kind, _, _, _ in _FEATURES}
    rows += [_a(f'cmd:{kind}', spec['title'], '特征', kind, '') for kind, spec in table.SPECS.items() if kind not in listed]
    rows += [_a('sketch.start', '草图绘制', '草图', 'sketch', 'S'), _a('sketch.finish', '完成草图', '草图', 'finish', ''),
             _a('sketch.cancel', '放弃草图', '草图', 'cancel', '')]
    rows += [_a(f'tool:{tool}', title, '草图', 'fillet' if tool == 'fillet' else tool, key) for tool, title, key in _TOOLS]
    rows += [_a('sketch.pattern', '线性草图阵列', '草图', 'pattern'), _a('sketch.cpattern', '圆周草图阵列', '草图', 'cpattern'),
             _a('sketch.relation', '添加几何关系', '草图', 'relation'), _a('sketch.repair', '修复草图', '草图', 'repair'),
             _a('sketch.silhouette', '侧影实体', '草图', 'silhouette'), _a('sketch.section', '交叉曲线', '草图', 'section'),
             _a('sketch.rapid', '快速草图', '草图', 'rapid')]
    rows += [_a('eval.measure', '测量', '评估', 'measure', 'Ctrl+M'), _a('eval.process', '绑定工艺', '评估', 'process'),
             _a('eval.check', '设计检查', '评估', 'drc', 'F8')]
    rows += [_a('sim.static', '静力分析', '仿真', 'stress'), _a('sim.drag', '风阻估算', '仿真', 'wind'),
             _a('sim.assembly', '装配检查', '仿真', 'assembly')]
    rows += [_a(f'view:{name}', title, '视图', icon, key) for name, title, icon, key in _VIEWS]
    rows += [_a(f'style:{name}', title, '视图', name, '') for name, title in _STYLES]
    rows += [_a('view.section', '剖切视图 开/关', '视图', 'section', ''), _a('view.perspective', '透视图 开/关', '视图', 'perspective', ''),
             _a('view.planes', '主要基准面 显示/隐藏', '视图', 'plane', '')]
    return rows


ACTIONS = _build()
BY_ID = {row['id']: row for row in ACTIONS}
_SHORT = {'view:fit': '适应', 'view:zoom_box': '局部放大', 'view:previous': '上一视图', 'sketch.start': '草图', 'tool:rect': '矩形',
          'tool:arc': '圆弧', 'tool:dimension': '尺寸', 'tool:trim': '剪裁', 'tool:extend': '延伸', 'tool:offset': '等距',
          'tool:mirror': '镜向', 'tool:move': '移动', 'tool:convert': '转换引用', 'tool:fillet': '草图圆角', 'tool:spline': '样条',
          'edit.delete': '删除', 'file.export': '导出', 'view.section': '剖切', 'view.perspective': '透视', 'view.planes': '基准面',
          'sketch.pattern': '线性阵列', 'sketch.cpattern': '圆周阵列', 'sketch.relation': '几何关系', 'tool:equation': '方程曲线'}


def short(identifier):
    """手势轮的格子里写的名字: 地方小, 最多五个字。"""
    return _SHORT.get(identifier) or BY_ID[identifier]['title'].split('/')[0].split(' ')[0][:5]
GROUPS = ['文件', '编辑', '特征', '草图', '评估', '仿真', '视图']

# 右键手势轮: 8 格, 从 "右" 开始逆时针 (右, 右上, 上, 左上, 左, 左下, 下, 右下)。
# 四个正方向和 SOLIDWORKS 的默认一致 (建模: 视图方向; 草图: 画图工具), 斜向放最常用的几个命令。
GESTURES = {
    'model': ['view:right', 'view:iso', 'view:top', 'view:front', 'view:left', 'sketch.start', 'view:bottom', 'cmd:extrude'],
    'sketch': ['tool:line', 'sketch.finish', 'tool:select', 'edit.undo', 'tool:rect', 'view:fit', 'tool:circle', 'view:normal'],
}
