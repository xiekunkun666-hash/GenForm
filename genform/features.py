# -*- coding: utf-8 -*-
"""特征表: 除草图、拉伸、圆角、倒角以外的每种特征在这里登记一行 — 名称、要填哪些参数。

命令 (commands.py, 也就是给 AI 的工具)、参数面板 (forms.py)、设计树上的名称和图标都从这张表生成,
所以加一种特征 = 在这里加一行 + 在 kernel/features.py 里写怎么算。纯数据, 不碰界面库也不碰内核。

参数的种类 (kind):
    number / int / bool / text    普通的值
    choice                        从 options 里选一个
    points                        一串坐标 [[x, y, z]...] (面板里写成 "x,y,z; x,y,z")
    sketch / sketches             引用一个 / 多个草图 (特征 id)
    path                          引用一条路径: 草图或曲线特征
    features                      引用多个造型特征 (阵列、镜像的对象); 空 = 整个实体
    plane                         基准面: XY / XZ / YZ 或基准面特征的 id
    axis                          轴: X / Y / Z, 草图的 SX / SY (只在 sketch_axes 时), 或基准轴特征的 id
    edges / faces                 实体上的边 / 面, 存成 [{'point': [x, y, z]}...] (边中点 / 面中心)
"""
from __future__ import annotations

import math

import numpy as np

from . import planes

OPS = [{'value': 'add', 'label': '加料'}, {'value': 'cut', 'label': '切除'}, {'value': 'common', 'label': '相交'},
       {'value': 'void', 'label': '挖空腔'}, {'value': 'fill', 'label': '填空腔'}, {'value': 'pocket', 'label': '钣金凹槽'}]
HOLE_SIZES = {      # 螺纹规格 → (通孔直径, 沉头孔直径, 沉头孔深, 90° 锥形沉头的大端直径)。常用的中等配合值, 要紧的地方以所用标准为准
    'M2': (2.4, 4.3, 2.2, 4.0), 'M2.5': (2.9, 5.5, 2.8, 5.0), 'M3': (3.4, 6.5, 3.4, 6.72), 'M4': (4.5, 8.0, 4.6, 8.96), 'M5': (5.5, 10.0, 5.7, 11.2), 'M6': (6.6, 11.0, 6.8, 13.44),
    'M8': (9.0, 15.0, 9.0, 17.92), 'M10': (11.0, 18.0, 11.0, 22.4), 'M12': (13.5, 20.0, 13.0, 26.88),
}


TAP_DRILLS = {'M2': 1.6, 'M2.5': 2.05, 'M3': 2.5, 'M4': 3.3, 'M5': 4.2, 'M6': 5.0, 'M8': 6.8, 'M10': 8.5, 'M12': 10.2}     # 粗牙螺纹攻丝前的底孔直径
SCREW_SIZES = {     # 螺丝规格 → 头型 → (头直径, 头高, 内六角对边, 内六角深); 杆的直径就是规格的数。
    # cap 内六角圆柱头 (ISO 4762)、button 内六角盘头 (ISO 7380)、flat 内六角沉头 (ISO 10642, 头直径是理论值), 都取标称尺寸
    'M2': {'cap': (3.8, 2.0, 1.5, 1.0), 'button': (3.5, 1.1, 1.3, 0.7), 'flat': (4.0, 1.0, 1.3, 0.6)},
    'M2.5': {'cap': (4.5, 2.5, 2.0, 1.1), 'button': (4.7, 1.35, 1.5, 0.9), 'flat': (5.0, 1.25, 1.5, 0.8)},
    'M3': {'cap': (5.5, 3.0, 2.5, 1.3), 'button': (5.7, 1.65, 2.0, 1.04), 'flat': (6.72, 1.86, 2.0, 1.1)},
    'M4': {'cap': (7.0, 4.0, 3.0, 2.0), 'button': (7.6, 2.2, 2.5, 1.3), 'flat': (8.96, 2.48, 2.5, 1.5)},
    'M5': {'cap': (8.5, 5.0, 4.0, 2.5), 'button': (9.5, 2.75, 3.0, 1.56), 'flat': (11.2, 3.1, 3.0, 1.9)},
    'M6': {'cap': (10.0, 6.0, 5.0, 3.0), 'button': (10.5, 3.3, 4.0, 2.08), 'flat': (13.44, 3.72, 4.0, 2.2)},
    'M8': {'cap': (13.0, 8.0, 6.0, 4.0), 'button': (14.0, 4.4, 5.0, 2.6), 'flat': (17.92, 4.96, 5.0, 3.0)},
}


def F(key, kind, label, default=None, **more):
    return dict(key=key, kind=kind, label=label, default=default, **more)


OP_HELP = ('add 加料 / cut 切除 / common 相交 (只留和现有实体重叠的部分) / void 挖空腔 (整个在实体里面, 变成封闭的空腔: '
           '外形、内形各做一次就是钣金壳) / fill 填空腔 (只在空腔里长材料: 地板、隔板) / pocket 钣金凹槽 (空心件上挖槽, 槽壁留一层壁厚)')


def _op(default='add'):
    return F('op', 'choice', '方式', default, options=OPS, help=OP_HELP)


def _options(*pairs):
    return [{'value': value, 'label': label} for value, label in pairs]


FEATURES_FIELD = F('features', 'features', '对象', [], help='要复制的造型特征 id 列表；不写 = 整个实体')
AXIS_XYZ = dict(help='X / Y / Z (过原点的坐标轴) 或基准轴特征的 id')

SPECS = {
    # ---- 凸台 / 切除 ----
    'revolve': dict(title='旋转凸台/基体', short='旋转', mark='转', tint='#57B894', tool=True, cut='旋转切除',
                    about='把草图绕一根轴旋转成实体。',
                    fields=[F('sketch', 'sketch', '草图'),
                            F('axis', 'axis', '旋转轴', 'SY', sketch_axes=True,
                              help='CL = 草图里的第一条中心线 (构造线)；SX / SY = 草图平面的 X / Y 轴 (过草图原点)；X / Y / Z = 坐标轴；或基准轴特征的 id'),
                            F('angle', 'number', '角度', 360.0, unit='°'),
                            F('reverse', 'bool', '反向', False), F('symmetric', 'bool', '两侧对称', False), _op()]),
    'sweep': dict(title='扫描', short='扫描', mark='扫', tint='#57B894', tool=True, cut='扫描切除',
                  about='让轮廓草图沿一条路径扫过去。轮廓要画在路径的起点处，并且大致垂直于路径。',
                  fields=[F('sketch', 'sketch', '轮廓'), F('path', 'path', '路径', help='草图 (首尾相接的一条线) 或曲线特征的 id'), _op()]),
    'loft': dict(title='放样凸台/基体', short='放样', mark='放', tint='#57B894', tool=True, cut='放样切除',
                 about='在几个草图轮廓之间过渡成实体 (按给的顺序)。每个草图用它的第一个封闭轮廓。',
                 fields=[F('sketches', 'sketches', '轮廓', [], help='至少两个草图 id，按过渡的顺序'),
                         F('ruled', 'bool', '直纹 (轮廓之间走直线)', False), _op()]),
    'boundary': dict(title='边界凸台/基体', short='边界', mark='界', tint='#57B894', tool=True,
                     about='在几个草图轮廓之间做光顺过渡的实体。目前只支持方向 1 的轮廓，没有方向 2 的引导线。',
                     fields=[F('sketches', 'sketches', '方向 1 轮廓', [], help='至少两个草图 id，按顺序'), _op()]),
    'import_step': dict(title='导入实体', short='导入', mark='导', tint='#57B894', tool=True,
                        about='把别的 CAD 导出的 STEP 文件 (.step / .stp) 读进来当作实体，后面可以接着切除、打孔、倒圆角。'
                              '文档里只记文件路径，每次重算从文件读；文件改了重算就跟着变。只有曲面的 STEP (SOLIDWORKS '
                              '按曲面导出的) 会先缝合成实体，平面上缺的面自动补上。',
                        fields=[F('path', 'text', 'STEP 文件', '', help='STEP 文件的完整路径'), _op()]),
    # ---- 孔和螺纹 ----
    'hole': dict(title='异形孔向导', short='孔', mark='孔', tint='#E07A5F', tool=True,
                 about='在草图的每个点 (和圆心) 处打孔，方向垂直于草图平面、朝草图法向的反方向。',
                 fields=[F('sketch', 'sketch', '位置草图', help='孔打在这个草图的点和圆心上'),
                         F('kind', 'choice', '类型', 'simple', options=_options(('simple', '简单孔'), ('counterbore', '柱形沉头孔'), ('countersink', '锥形沉头孔'), ('tapped', '螺纹底孔')),
                           help='螺纹底孔：按规格打攻丝前的底孔 (M3 是 2.5、M4 是 3.3)，螺纹牙要另外攻或用“螺纹线”'),
                         F('size', 'choice', '规格', 'custom', options=_options(('custom', '自定义'), *((name, name) for name in HOLE_SIZES)),
                           help='选了 M 规格就用它的通孔 (螺纹底孔类型时是底孔) 和沉头尺寸，下面的直径不起作用'),
                         F('diameter', 'number', '孔直径', 5.0), F('through', 'bool', '完全贯穿', True), F('depth', 'number', '孔深', 10.0),
                         F('head_diameter', 'number', '沉头直径', 10.0), F('head_depth', 'number', '沉头深度', 5.0),
                         F('flip', 'bool', '反向', False),
                         F('thread', 'bool', '切出螺纹牙', False, help='螺纹底孔类型才有效：按内螺纹小径打底孔并切出真实的 60° 牙 (粗牙螺距)，同规格带牙螺丝拧进去不干涉'),
                         F('phase', 'number', '螺纹相位', 0.0, unit='°', help='牙的起始角度。两件拧在一起: 起点平面相距螺距的整数倍时都填 0 就对上; 不是整数倍时内螺纹填 360 × (外螺纹起点 − 内螺纹起点) / 螺距')]),
    'hole_adv': dict(title='高级孔', short='高级孔', mark='孔', tint='#E07A5F', tool=True,
                     about='自己定义一串孔段：从草图平面往里，一段接一段。',
                     fields=[F('sketch', 'sketch', '位置草图'),
                             F('steps', 'points', '孔段 直径,深度', [[10.0, 3.0], [5.0, 12.0]], width=2,
                               help='[[直径, 深度], ...]，从入口往里依次排；最后一段深度写 0 = 贯穿'),
                             F('flip', 'bool', '反向', False)]),
    'thread': dict(title='螺纹线', short='螺纹', mark='纹', tint='#E07A5F',
                   about='沿一条圆形边切出真实的螺纹牙 (60° 三角牙)。轴上是外螺纹，孔里是内螺纹，自动判断。牙多了会比较慢。',
                   fields=[F('edges', 'edges', '圆形边', [], pick='edge', count=1, help='螺纹起始处的一条圆形边'),
                           F('pitch', 'number', '螺距', 1.5), F('length', 'number', '螺纹长度', 10.0), F('phase', 'number', '螺纹相位', 0.0, unit='°', help='牙的起始角度。两件拧在一起: 起点平面相距螺距的整数倍时都填 0 就对上; 不是整数倍时内螺纹填 360 × (外螺纹起点 − 内螺纹起点) / 螺距')]),
    'stud': dict(title='螺柱向导', short='螺柱', mark='柱', tint='#E07A5F', tool=True,
                 about='在草图的每个点处立一根圆柱螺柱 (朝草图法向)，端部带倒角。勾上“切出螺纹牙”切真实的外螺纹。',
                 fields=[F('sketch', 'sketch', '位置草图'), F('diameter', 'number', '直径', 6.0), F('length', 'number', '长度', 15.0),
                         F('chamfer', 'number', '端部倒角', 0.5), F('flip', 'bool', '反向', False),
                         F('thread', 'bool', '切出螺纹牙', False, help='在螺柱上切真实的 60° 外螺纹 (根部留一个螺距)'),
                         F('pitch', 'number', '螺距', 0.0, help='0 = 按直径取粗牙螺距'), F('phase', 'number', '螺纹相位', 0.0, unit='°', help='牙的起始角度。两件拧在一起: 起点平面相距螺距的整数倍时都填 0 就对上; 不是整数倍时内螺纹填 360 × (外螺纹起点 − 内螺纹起点) / 螺距')]),
    'screw': dict(title='螺丝', short='螺丝', mark='钉', tint='#E07A5F', tool=True,
                  about='在草图的每个点处放一颗内六角螺丝：头在草图平面上 (沉头的头埋在平面里)，杆朝草图法向的反方向伸进去。勾上“切出螺纹牙”杆上切真实的牙，不勾是光杆。',
                  fields=[F('sketch', 'sketch', '位置草图', help='螺丝放在这个草图的点和圆心上'),
                          F('size', 'choice', '规格', 'M3', options=_options(*((name, name) for name in SCREW_SIZES))),
                          F('head', 'choice', '头型', 'cap', options=_options(('cap', '圆柱头'), ('button', '盘头'), ('flat', '沉头'))),
                          F('length', 'number', '长度', 10.0, help='圆柱头和盘头：头下面的杆长；沉头：连头一起的总长'),
                          F('flip', 'bool', '反向', False),
                          F('thread', 'bool', '切出螺纹牙', False, help='杆上切真实的 60° 粗牙外螺纹，相位从头的平面量起'), F('phase', 'number', '螺纹相位', 0.0, unit='°', help='牙的起始角度。两件拧在一起: 起点平面相距螺距的整数倍时都填 0 就对上; 不是整数倍时内螺纹填 360 × (外螺纹起点 − 内螺纹起点) / 螺距')]),
    # ---- 修改实体 ----
    'rib': dict(title='筋', short='筋', mark='筋', tint='#D9A441',
                about='用一条开口的草图线做加强筋：在草图平面内朝实体延伸到碰上实体为止，厚度沿草图法向两侧各一半。',
                fields=[F('sketch', 'sketch', '草图'), F('thickness', 'number', '厚度', 3.0), F('flip', 'bool', '朝另一侧延伸', False)]),
    'draft': dict(title='拔模', short='拔模', mark='拔', tint='#D9A441',
                  about='把选中的面相对中性面倾斜一个角度 (开模方向 = 中性面的法向)。',
                  fields=[F('faces', 'faces', '拔模面', [], pick='face'), F('plane', 'plane', '中性面', 'XY'),
                          F('offset', 'number', '中性面偏移', 0.0), F('angle', 'number', '角度', 3.0, unit='°'), F('flip', 'bool', '反向', False)]),
    'shell': dict(title='抽壳', short='抽壳', mark='壳', tint='#D9A441',
                  about='把实体掏空成等厚的壳；选中的面被拿掉成为开口 (不选 = 封闭的空腔)。封闭抽壳可以留隔板: '
                        '隔板草图里每段直线沿草图法向贯穿实体, 成为一块和外壳连在一起的平板 (地板、防火墙)。',
                  fields=[F('faces', 'faces', '开口的面', [], pick='face', optional=True), F('thickness', 'number', '壁厚', 2.0),
                          F('walls', 'sketch', '隔板草图', '', optional=True), F('wall_thickness', 'number', '隔板厚度', 0.0)]),
    'wrap': dict(title='包裹', short='包裹', mark='裹', tint='#D9A441',
                 about='把草图轮廓贴到一个圆柱面上，凸起或凹进去。草图的 X/Y 被展开成沿圆周 / 沿轴线的长度。',
                 fields=[F('sketch', 'sketch', '草图'), F('faces', 'faces', '圆柱面', [], pick='face', count=1),
                         F('depth', 'number', '厚度', 1.0),
                         F('mode', 'choice', '类型', 'emboss', options=_options(('emboss', '浮雕 (凸起)'), ('deboss', '蚀雕 (凹进)')))]),
    'split': dict(title='分割线', short='分割线', mark='分', tint='#8E9AAF',
                  about='把草图沿它的法向投到实体上，在面上刻出分割线 (面被分成几块，可以分别选来拔模等)。',
                  fields=[F('sketch', 'sketch', '草图')]),
    # ---- 阵列 / 镜像 ----
    'pattern_linear': dict(title='线性阵列', short='线性阵列', mark='阵', tint='#6FA8DC',
                           about='沿一个或两个方向等距复制特征。数量包含原来的那个。',
                           fields=[FEATURES_FIELD, F('axis1', 'axis', '方向 1', 'X', **AXIS_XYZ), F('count1', 'int', '数量 1', 3), F('spacing1', 'number', '间距 1', 20.0),
                                   F('axis2', 'axis', '方向 2', 'Y', **AXIS_XYZ), F('count2', 'int', '数量 2', 1), F('spacing2', 'number', '间距 2', 20.0)]),
    'pattern_circular': dict(title='圆周阵列', short='圆周阵列', mark='阵', tint='#6FA8DC',
                             about='绕一根轴等角度复制特征。数量包含原来的那个；总角度 360 = 均布一圈。',
                             fields=[FEATURES_FIELD, F('axis', 'axis', '阵列轴', 'Z', **AXIS_XYZ), F('count', 'int', '数量', 6),
                                     F('angle', 'number', '总角度', 360.0, unit='°')]),
    'mirror': dict(title='镜像', short='镜像', mark='镜', tint='#6FA8DC',
                   about='关于一个基准面镜像特征 (不选对象 = 镜像整个实体并合在一起)。',
                   fields=[FEATURES_FIELD, F('plane', 'plane', '镜像面', 'YZ'), F('offset', 'number', '镜像面偏移', 0.0)]),
    'pattern_curve': dict(title='曲线驱动的阵列', short='曲线阵列', mark='阵', tint='#6FA8DC',
                          about='沿一条路径复制特征：实例按路径上的位置平移 (相对路径起点)。',
                          fields=[FEATURES_FIELD, F('path', 'path', '路径'), F('count', 'int', '数量', 5),
                                  F('spacing', 'number', '间距 (0=均布)', 0.0, help='0 = 沿路径全长均布'), F('align', 'bool', '跟着路径转向', False)]),
    'pattern_sketch': dict(title='草图驱动的阵列', short='草图阵列', mark='阵', tint='#6FA8DC',
                           about='在草图的每个点处放一个实例：把对象的质心 (沿草图平面) 移到那个点上。',
                           fields=[FEATURES_FIELD, F('sketch', 'sketch', '位置草图')]),
    'pattern_table': dict(title='表格驱动的阵列', short='表格阵列', mark='阵', tint='#6FA8DC',
                          about='按一张坐标表放实例：把对象的质心移到每个坐标上 (只写 x,y 时 z 不动)。',
                          fields=[FEATURES_FIELD, F('points', 'points', '坐标表', [[20.0, 0.0], [40.0, 0.0]], help='[[x, y], ...] 或 [[x, y, z], ...]')]),
    'pattern_fill': dict(title='填充阵列', short='填充阵列', mark='阵', tint='#6FA8DC',
                         about='在一个草图轮廓围出的区域里铺满实例。不选对象时铺的是圆孔 (贯穿切除)。',
                         fields=[F('features', 'features', '对象', [], help='造型特征 id 列表；不写 = 铺圆孔'), F('sketch', 'sketch', '边界草图'),
                                 F('spacing', 'number', '间距', 10.0),
                                 F('layout', 'choice', '排布', 'square', options=_options(('square', '方形'), ('hex', '交错 (蜂窝)'))),
                                 F('margin', 'number', '离边界', 3.0), F('angle', 'number', '排布转角', 0.0, unit='°'),
                                 F('diameter', 'number', '圆孔直径', 4.0, help='不选对象时铺的圆孔的直径')]),
    'pattern_variable': dict(title='变量阵列', short='变量阵列', mark='阵', tint='#6FA8DC',
                             about='每个实例各自平移并改几个尺寸：实例表每行 "dx,dy,dz,参数=值,…"，参数是对象特征自己的参数名 (如 distance、angle)。',
                             fields=[F('features', 'features', '对象', [], help='造型特征 id 列表 (不能为空)'),
                                     F('rows', 'text', '实例表', '20,0,0,distance=15; 40,0,0,distance=20',
                                       help='用分号隔开每个实例："dx,dy,dz,参数=值,…"')]),
    # ---- 参考几何体 ----
    'plane': dict(title='基准面', short='基准面', mark='面', tint='#4C9BE8', reference=True,
                  about='新的基准面：从一个基准面偏移、再绕它的 X 或 Y 轴转一个角度。可以在它上面画草图。',
                  fields=[F('base', 'plane', '参考面', 'XY'), F('offset', 'number', '偏移', 10.0), F('angle', 'number', '转角', 0.0, unit='°'),
                          F('about', 'choice', '绕', 'x', options=_options(('x', '参考面的 X 轴'), ('y', '参考面的 Y 轴'))),
                          F('origin', 'points', '过点', [], width=3, optional=True, help='[[x, y, z]]: 给了就用这个点和 normal 定面，不用参考面'),
                          F('normal', 'points', '法向', [], width=3, optional=True)]),
    'axis': dict(title='基准轴', short='基准轴', mark='轴', tint='#4C9BE8', reference=True,
                 about='一根基准轴：过一个点、沿一个方向。可以作旋转轴和阵列轴。',
                 fields=[F('origin', 'points', '过点', [[0.0, 0.0, 0.0]], width=3), F('direction', 'points', '方向', [[0.0, 0.0, 1.0]], width=3)]),
    'csys': dict(title='坐标系', short='坐标系', mark='系', tint='#4C9BE8', reference=True,
                 about='一个参考坐标系：原点 + 依次绕 X、Y、Z 轴的转角。',
                 fields=[F('origin', 'points', '原点', [[0.0, 0.0, 0.0]], width=3), F('rx', 'number', '绕 X', 0.0, unit='°'),
                         F('ry', 'number', '绕 Y', 0.0, unit='°'), F('rz', 'number', '绕 Z', 0.0, unit='°')]),
    'point': dict(title='点', short='点', mark='点', tint='#4C9BE8', reference=True,
                  about='一个参考点。',
                  fields=[F('position', 'points', '坐标', [[0.0, 0.0, 0.0]], width=3)]),
    'com': dict(title='质心', short='质心', mark='心', tint='#4C9BE8', reference=True,
                about='在实体的质心处放一个标记 (跟着实体变)。', fields=[]),
    'bbox': dict(title='边界框', short='边界框', mark='框', tint='#4C9BE8', reference=True,
                 about='画出刚好包住实体的长方体框 (跟着实体变)。', fields=[]),
    'variables': dict(title='全局变量', short='变量', mark='变', tint='#4C9BE8', reference=True,
                      about='定义几个变量 (方程式)：后面任何特征的数值参数都可以写成 =表达式，比如 =D/2-3。'
                            '变量的值也能写表达式，只能用前面定义过的变量。装配体的全局变量会改掉同名的值。',
                      fields=[F('values', 'vars', '变量', {'D': 100.0}, help='写成 名字 = 值，用分号隔开：D = 112; H = D/2')]),
    # ---- 曲线 ----
    'curve_helix': dict(title='螺旋线/涡状线', short='螺旋线', mark='旋', tint='#B388EB', curve=True,
                        about='以草图里的一个圆为底画螺旋线 (沿草图法向上升) 或涡状线 (在草图平面内一圈圈往外)。',
                        fields=[F('sketch', 'sketch', '底圆草图', help='用这个草图里的第一个圆'),
                                F('kind', 'choice', '类型', 'helix', options=_options(('helix', '螺旋线'), ('spiral', '涡状线'))),
                                F('pitch', 'number', '螺距', 5.0), F('turns', 'number', '圈数', 5.0, unit='圈'),
                                F('taper', 'number', '每圈半径增量', 0.0, help='螺旋线的锥度: 每转一圈半径变化多少 (负数 = 越来越细)'), F('start', 'number', '起始角', 0.0, unit='°'),
                                F('clockwise', 'bool', '顺时针', False)]),
    'sketch3d': dict(title='3D 草图', short='3D草图', mark='线', tint='#B388EB', curve=True,
                     about='不在一个平面上的草图: 按顺序连起这些空间坐标点 (直线段或样条)，可以作扫描路径。',
                     fields=[F('points', 'points', '坐标点', [[0.0, 0.0, 0.0], [30.0, 0.0, 0.0], [30.0, 20.0, 0.0], [30.0, 20.0, 25.0]], width=3),
                             F('kind', 'choice', '连法', 'line', options=_options(('line', '直线段'), ('spline', '样条曲线'))),
                             F('closed', 'bool', '闭合', False)]),
    'curve_surface': dict(title='曲面上的样条曲线', short='面上样条', mark='线', tint='#B388EB', curve=True,
                          about='贴在一张面上的样条曲线: 每个点写成它在这张面上的位置 (U、V 都是 0 到 1)，曲线始终在面上。',
                          fields=[F('faces', 'faces', '所在的面', [], pick='face', count=1),
                                  F('points', 'points', '面上的点 U,V', [[0.1, 0.1], [0.5, 0.7], [0.9, 0.9]], width=2,
                                    help='每个点 = [U, V]，是它在这张面上的位置，0 到 1')]),
    'curve_xyz': dict(title='通过 XYZ 点的曲线', short='XYZ 曲线', mark='线', tint='#B388EB', curve=True,
                      about='一条光顺地穿过这些坐标点的空间曲线。',
                      fields=[F('points', 'points', '坐标点', [[0.0, 0.0, 0.0], [10.0, 10.0, 5.0], [20.0, 0.0, 10.0]], width=3)]),
    'curve_points': dict(title='通过参考点的曲线', short='参考点曲线', mark='线', tint='#B388EB', curve=True,
                         about='一条光顺地穿过几个参考点 (点特征) 的空间曲线。',
                         fields=[F('points', 'features', '参考点', [], of='point', help='点特征的 id 列表，按顺序'),
                                 F('closed', 'bool', '闭合', False)]),
    'curve_project': dict(title='投影曲线', short='投影曲线', mark='线', tint='#B388EB', curve=True,
                          about='把草图沿它的法向 (两个方向都算) 投到实体的面上，得到贴在面上的空间曲线。',
                          fields=[F('sketch', 'sketch', '草图')]),
    'curve_composite': dict(title='组合曲线', short='组合曲线', mark='线', tint='#B388EB', curve=True,
                            about='把几条首尾相接的实体边 (和草图、曲线) 合成一条曲线，可以作扫描路径。',
                            fields=[F('edges', 'edges', '实体的边', [], pick='edge', optional=True),
                                    F('curves', 'features', '草图 / 曲线', [], of='path', help='草图或曲线特征的 id 列表')]),
}
TOOL_KINDS = ('extrude',) + tuple(kind for kind, spec in SPECS.items() if spec.get('tool'))    # 留得下 "工具体" 的特征: 能被阵列和镜像
CURVE_KINDS = tuple(kind for kind, spec in SPECS.items() if spec.get('curve'))
MENUS = [       # 工具栏上的下拉菜单
    ('hole', '异形孔向导', ['hole', 'hole_adv', 'thread', 'stud', 'screw']),
    ('pattern', '线性阵列', ['pattern_linear', 'pattern_circular', 'mirror', 'pattern_curve', 'pattern_sketch', 'pattern_table',
                         'pattern_fill', 'pattern_variable']),
    ('reference', '参考几何体', ['plane', 'axis', 'csys', 'point', 'com', 'bbox', 'variables']),
    ('curve', '曲线', ['split', 'curve_project', 'curve_composite', 'curve_xyz', 'curve_points', 'curve_helix']),
    ('sketch3d', '3D 草图', ['sketch3d', 'curve_surface']),
]


# ---------------------------------------------------------------------------
# 值的整理 (命令进来的参数 → 存进特征里的参数)
# ---------------------------------------------------------------------------
def parse_points(value, width=None):
    """坐标表: 可以是 [[x, y, z]...], 也可以是面板里写的 "x,y,z; x,y,z" → [[float...]...]。"""
    if isinstance(value, str):
        rows = [[part for part in row.replace('，', ',').replace(' ', ',').split(',') if part]
                for row in value.replace('；', ';').replace('\n', ';').split(';')]
        value = [row for row in rows if row]
    if value and not isinstance(value[0], (list, tuple)):
        value = [value]
    points = [[float(item) for item in row] for row in (value or [])]
    if width and any(len(row) != width for row in points):
        raise ValueError(f'每组要正好 {width} 个数，用逗号隔开；多组之间用分号')
    return points


def points_text(points):
    return '; '.join(','.join(f'{value:g}' for value in row) for row in points or ())


def parse_variables(value):
    """变量表: {'D': 112, 'H': '=D/2'} 或面板里写的 "D = 112; H = D/2" → {名字: 数 或 "=表达式"} (按写的先后)。"""
    if isinstance(value, dict):
        rows = list(value.items())
    else:
        rows = []
        for row in str(value or '').replace('；', ';').replace('\n', ';').split(';'):
            if row.strip():
                if '=' not in row:
                    raise ValueError(f'变量要写成 名字 = 值：{row.strip()!r}')
                name, text = row.split('=', 1)
                rows.append((name, text))
    out = {}
    for name, text in rows:
        name = str(name).strip()
        if not name.isidentifier():
            raise ValueError(f'变量名 {name!r} 不行：只能用字母、数字、下划线，不能数字开头')
        text = text.strip() if isinstance(text, str) else text
        try:
            out[name] = float(text[1:] if isinstance(text, str) and text.startswith('=') else text)
        except (TypeError, ValueError):
            out[name] = text if isinstance(text, str) and text.startswith('=') else f'={text}'
    return out


def variables_text(values):
    return '; '.join(f'{name} = {str(text).lstrip("=") if isinstance(text, str) else f"{text:g}"}' for name, text in (values or {}).items())


def clean(field, value):
    kind = field['kind']
    if kind in ('number', 'int') and isinstance(value, str) and value.strip().startswith('='):
        return value.strip()                        # 方程式 (用变量特征里的变量): 重算时才换成数
    if kind == 'vars':
        return parse_variables(value)
    if kind == 'number':
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f'{field["label"]}不是有效的数')
        return value
    if kind == 'int':
        return int(round(float(value)))
    if kind == 'bool':
        return bool(value)
    if kind == 'points':
        return parse_points(value, field.get('width'))
    if kind == 'choice':
        allowed = [option['value'] for option in field['options']]
        if value not in allowed:
            raise ValueError(f'{field["label"]}只能是 {" / ".join(allowed)}')
        return value
    if kind in ('sketches', 'features'):
        return [str(item) for item in ([value] if isinstance(value, str) else (value or []))]
    if kind in ('edges', 'faces'):
        return value if isinstance(value, str) else list(value or [])
    return str(value)


def default_params(kind):
    import copy
    return {field['key']: copy.deepcopy(field['default']) for field in SPECS[kind]['fields']}


# ---------------------------------------------------------------------------
# 参考几何体: 都能只凭参数算出来 (界面画草图、内核重算用的是同一个结果)
# ---------------------------------------------------------------------------
def _unit(vector):
    vector = np.asarray(vector, dtype=float)
    size = float(np.linalg.norm(vector))
    if size < 1e-12:
        raise ValueError('方向不能是零向量')
    return vector / size


def plane_frame(ref, features, offset=0.0, _depth=0):
    """基准面的引用 (XY / XZ / YZ 或基准面特征 id) → planes.frame 认识的坐标系字典 {'origin', 'x', 'y'}。"""
    if isinstance(ref, dict):
        frame = ref
    elif str(ref).upper() in planes.PLANES:
        origin, x_dir, y_dir, _ = planes.frame(str(ref).upper())
        frame = {'origin': origin.tolist(), 'x': x_dir.tolist(), 'y': y_dir.tolist()}
    else:
        feature = next((item for item in features if item['id'] == ref and item['type'] == 'plane'), None)
        if feature is None or _depth > 50:
            raise ValueError(f'找不到基准面 {ref!r}（可用 XY / XZ / YZ 或基准面特征的 id）')
        frame = _plane_of(feature['params'], features, _depth)
    if not offset:
        return frame
    origin, x_dir, y_dir, normal = planes.frame(frame, offset)
    return {'origin': origin.tolist(), 'x': x_dir.tolist(), 'y': y_dir.tolist()}


def _plane_of(params, features, depth):
    if params.get('origin') and params.get('normal'):          # 从选中的平面抓来的: 过一个点、给定法向
        normal = _unit(params['normal'][0])
        helper = np.array([0.0, 0.0, 1.0]) if abs(normal[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        x_dir = _unit(np.cross(helper, normal))
        base = {'origin': list(map(float, params['origin'][0])), 'x': x_dir.tolist(), 'y': np.cross(normal, x_dir).tolist()}
    else:
        base = plane_frame(params.get('base', 'XY'), features, _depth=depth + 1)
    origin, x_dir, y_dir, normal = planes.frame(base)
    turn = math.radians(float(params.get('angle', 0.0)))
    if turn:
        cos, sin = math.cos(turn), math.sin(turn)
        if params.get('about', 'x') == 'x':
            y_dir = y_dir * cos + normal * sin
        else:
            x_dir = x_dir * cos - normal * sin
        normal = np.cross(x_dir, y_dir)
    origin = origin + normal * float(params.get('offset', 0.0))
    return {'origin': origin.tolist(), 'x': x_dir.tolist(), 'y': y_dir.tolist()}


def axis_of(ref, features, sketch_frame=None):
    """轴的引用 → (过点, 方向), numpy 向量。"""
    name = str(ref)
    if name.startswith('@'):            # 在视图里点出来的一条线 (实体的直边、圆边的轴线、草图里的直线): "@过点;方向"
        try:
            origin, direction = ([float(value) for value in part.split(',')] for part in name[1:].split(';'))
            if len(origin) != 3 or len(direction) != 3:
                raise ValueError
        except ValueError:
            raise ValueError(f'轴 {ref!r} 写得不对（要写成 "@x,y,z;dx,dy,dz"）') from None
        return np.asarray(origin, dtype=float), _unit(direction)
    if name.upper() in ('X', 'Y', 'Z'):
        return np.zeros(3), np.eye(3)['XYZ'.index(name.upper())]
    if name.upper() in ('SX', 'SY') and sketch_frame is not None:
        origin, x_dir, y_dir, _ = sketch_frame
        return np.asarray(origin, dtype=float), np.asarray(x_dir if name.upper() == 'SX' else y_dir, dtype=float)
    feature = next((item for item in features if item['id'] == ref and item['type'] == 'axis'), None)
    if feature is None:
        raise ValueError(f'找不到轴 {ref!r}（可用 X / Y / Z 或基准轴特征的 id）')
    return np.asarray(feature['params']['origin'][0], dtype=float), _unit(feature['params']['direction'][0])


def csys_axes(params):
    """坐标系特征 → (原点, 3x3 矩阵: 每列是一根轴)。"""
    matrix = np.eye(3)
    for index, key in enumerate(('rx', 'ry', 'rz')):
        turn = math.radians(float(params.get(key, 0.0)))
        cos, sin = math.cos(turn), math.sin(turn)
        a, b = (index + 1) % 3, (index + 2) % 3
        rotation = np.eye(3)
        rotation[a, a], rotation[a, b], rotation[b, a], rotation[b, b] = cos, -sin, sin, cos
        matrix = rotation @ matrix
    return np.asarray(params['origin'][0], dtype=float), matrix
