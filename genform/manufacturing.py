# -*- coding: utf-8 -*-
"""加工工艺: 工艺库 + 给每个特征挑性价比最好的那种。

做法: 先看特征做出来的是什么样的东西 (一块板、一个回转件、一块自由曲面、一个孔、一串字、空心件的车皮…, 由内核量出来的
工具体指标 + 特征类型 + 名字里的提示判断), 列出能做它的工艺, 每种按 "模具 / 工装费 ÷ 生产数量 + 单件费用" 算出摊到每件
的价钱, 挑最便宜的; 做不了的 (太大、壁太薄、材料不对) 不参加比较。所以同一个零件, 做 1 台和做 1 万台绑的工艺不一样:
车皮做 1 台是手工钣金成形, 做 10 万台才轮到开冲压模。

价钱都是按国内加工厂常见报价的量级估的 (人民币), 只用来给工艺排先后、看大头花在哪, 不是报价。
"""
from __future__ import annotations

import math
import re

from . import materials

DEFAULT_BATCH = 1
SKIN_GUESS = 2.0            # 车皮按多厚的板算料 (外形放样是实心的, 看不出板厚)

# 材质 → (大类, 每公斤价钱): 大类决定哪些工艺能用 (压铸只做铝锌镁、注塑只做塑料…)
_STOCK = {'普通碳钢': ('steel', 7.0), '合金钢': ('steel', 12.0), '不锈钢 304': ('steel', 22.0), '铸铁': ('iron', 6.0),
          '铝合金 6061': ('light', 28.0), '黄铜': ('copper', 55.0), '紫铜': ('copper', 75.0), '钛合金 Ti-6Al-4V': ('titanium', 380.0),
          'ABS': ('plastic', 22.0), '尼龙 PA12': ('plastic', 60.0), '聚碳酸酯 PC': ('plastic', 30.0), 'PLA': ('plastic', 25.0),
          '聚丙烯 PP': ('plastic', 14.0), 'PMMA 亚克力': ('plastic', 35.0), '铸造铝合金 A356': ('light', 24.0),
          '钢化玻璃': ('glass', 12.0), '橡胶': ('rubber', 30.0), '皮革 + 海绵': ('soft', 160.0)}
_METALS = {'steel', 'iron', 'light', 'copper', 'titanium'}
_DEFAULT_MATERIAL = '普通碳钢'


def _process(key, name, short, color, family, about, tooling, unit, kinds, metals=None, wall=0.0, size=1e9, tolerance=0.1, days=7):
    """tooling(m) / unit(m): 一次性的模具工装费、每件的费用 (m 是 _Measure); kinds: 能做哪几类形状;
    metals: 能用的材料大类 (None = 不限); wall: 能做的最小壁厚; size: 能做的最大边长。"""
    return dict(id=key, name=name, short=short, color=color, family=family, about=about, tooling=tooling, unit=unit,
                kinds=set(kinds), metals=None if metals is None else set(metals), wall=wall, size=size, tolerance=tolerance, days=days)


def _hours(hours, rate, setup=0.0):
    """(加工工时 + 准备工时 setup) × 每小时费率。"""
    return (setup + hours) * rate


# ---- 工艺库: 几种费用公式用到的量见 _Measure ----
PROCESSES = [
    # 板材下料
    _process('laser', '激光切割', '激光', '#E0605A', '板材', '光纤激光切平板: 不用模具, 开图就能切, 钢 0.5~25 mm、铝 ≤ 12 mm',
             lambda m: 0.0, lambda m: m.material(1.25) + _hours(m.cut_length / (9000.0 / (1 + m.t)) / 60, 300, 0.08),
             {'plate', 'letters'}, wall=0.5, size=3000, tolerance=0.1, days=3),
    _process('waterjet', '水刀切割', '水刀', '#4C94FF', '板材', '高压水加砂切: 什么材料都能切 (玻璃、石材、厚板), 没有热影响, 比激光慢',
             lambda m: 0.0, lambda m: m.material(1.3) + _hours(m.cut_length / (1500.0 / (1 + m.t / 5)) / 60, 260, 0.12),
             {'plate', 'letters', 'glass'}, metals=None, wall=0.5, size=3000, tolerance=0.2, days=4),
    _process('plasma', '等离子切割', '等离', '#B685E0', '板材', '厚钢板粗下料: 6~50 mm 便宜又快, 切口粗, 要再加工',
             lambda m: 0.0, lambda m: m.material(1.3) + _hours(m.cut_length / 3000.0 / 60, 180, 0.08),
             {'plate'}, metals={'steel', 'iron'}, wall=6, size=6000, tolerance=0.8, days=2),
    _process('bend', '激光切割 + 折弯 + 焊接', '折弯', '#E98A3C', '板材', '平板件下料后用折弯机折边, 再焊到车身上: 地板、隔板、支架',
             lambda m: 500.0, lambda m: m.material(1.3) + _hours(m.cut_length / 6000.0 / 60 + 0.4, 260, 0.15),
             {'plate', 'partition'}, metals=_METALS, wall=0.5, size=4000, tolerance=0.3, days=5),
    _process('punch', '数控冲床', '冲床', '#D9A441', '板材', '转塔冲床用通用模冲孔、冲百叶窗: 孔多的板件比激光快',
             lambda m: 2000.0, lambda m: m.material(1.2) + 3.0 + 0.4 * m.features_count,
             {'plate', 'hole_sheet'}, metals=_METALS, wall=0.5, size=2500, tolerance=0.15, days=4),
    # 板材成形 (曲面钣金)
    _process('stamping', '冲压 (开钢模)', '冲压', '#C0392B', '钣金成形', '拉延 + 修边 + 冲孔 + 翻边几套钢模: 一件几秒钟、几块钱, 模具费几十万到上千万',
             lambda m: 80000.0 + 22.0 * m.sheet_cm2, lambda m: m.material(1.6) + 1.5 + 0.004 * m.sheet_cm2,
             {'skin', 'pocket', 'plate', 'partition'}, metals=_METALS, wall=0.5, size=4500, tolerance=0.3, days=120),
    _process('hand_form', '手工钣金成形 (英式滚轮 + 锤形)', '手工', '#8E9AAF', '钣金成形', '按木制型架手工滚压、锤打成双曲面再焊起来: 不开模, 一台车几百工时, 老爷车、样车、限量车都这么做',
             lambda m: 3000.0 + 0.6 * m.sheet_cm2, lambda m: m.material(1.5) + _hours(m.sheet_cm2 / 900.0, 180, 4),
             {'skin', 'pocket'}, metals={'steel', 'light'}, wall=0.6, size=6000, tolerance=1.0, days=45),
    _process('hydroform', '液压成形 (软模)', '液压', '#35A7A0', '钣金成形', '只做一半钢模, 另一边用橡胶垫 / 液体压: 模具费是冲压的几分之一, 适合几百到几千件',
             lambda m: 30000.0 + 5.0 * m.sheet_cm2, lambda m: m.material(1.5) + 60.0 + 0.02 * m.sheet_cm2,
             {'skin', 'pocket', 'partition'}, metals=_METALS, wall=0.5, size=3000, tolerance=0.4, days=50),
    _process('composite', '碳纤维 / 玻纤铺层 (树脂模)', '碳纤', '#3C4148', '复合材料', '在树脂或铝模上铺预浸料、真空袋加热固化: 模具便宜, 件轻, 每件人工多',
             lambda m: 15000.0 + 2.5 * m.sheet_cm2, lambda m: _hours(m.sheet_cm2 / 1500.0, 160, 2) + 0.25 * m.sheet_cm2,
             {'skin', 'pocket', 'freeform'}, metals=None, wall=1.0, size=6000, tolerance=0.5, days=30),
    _process('vacuum', '真空吸塑', '吸塑', '#5FC38A', '塑料成形', '加热塑料板吸到木模或树脂模上: 内饰板、灯罩、护板, 模具几千块',
             lambda m: 3000.0 + 0.4 * m.sheet_cm2, lambda m: m.material(1.8) + 10.0 + 0.01 * m.sheet_cm2,
             {'skin', 'pocket', 'freeform'}, metals={'plastic'}, wall=1.0, size=2500, tolerance=0.5, days=10),
    # 切削
    _process('cnc3', '三轴 CNC 铣', '三轴', '#4C94FF', '切削', '从整块料铣出来: 平面、型腔、孔都能做, 不用模具; 内角要留刀具半径',
             lambda m: 300.0, lambda m: m.stock(1.0) + _hours(m.removed_cm3 / (60.0 * m.mrr) + m.area_cm2 / 6000.0, 220, 0.5),
             {'prism', 'profile', 'pocket_cut', 'hole', 'revolved', 'letters', 'freeform_small'}, wall=0.5, size=2000, tolerance=0.02, days=5),
    _process('cnc5', '五轴 CNC 铣', '五轴', '#2E6FD8', '切削', '刀能从各个方向够到: 自由曲面、叶轮、模具一类的整体件',
             lambda m: 800.0, lambda m: m.stock(1.0) + _hours(m.removed_cm3 / (60.0 * m.mrr) + m.area_cm2 / 2500.0, 480, 1.0),
             {'prism', 'pocket_cut', 'hole', 'revolved', 'freeform', 'freeform_small'}, wall=0.5, size=1500, tolerance=0.02, days=8),
    _process('turning', '数控车削', '车削', '#35A7A0', '切削', '工件转、车刀走: 轴、盘、套、轮毂这类回转件最便宜',
             lambda m: 200.0, lambda m: m.stock(0.85) + _hours(m.removed_cm3 / (60.0 * m.mrr * 1.6) + m.area_cm2 / 9000.0, 150, 0.3),
             {'revolved'}, wall=0.5, size=900, tolerance=0.01, days=4),
    _process('millturn', '车铣复合', '车铣', '#6FA8DC', '切削', '车完不下机直接铣: 带孔、带平面的回转件一次装夹做完',
             lambda m: 500.0, lambda m: m.stock(0.9) + _hours(m.removed_cm3 / (60.0 * m.mrr * 1.3) + m.area_cm2 / 5000.0, 320, 0.5),
             {'revolved'}, wall=0.5, size=700, tolerance=0.01, days=6),
    _process('drill', '钻孔 / 攻丝', '钻孔', '#9A9EA3', '切削', '钻床或加工中心上钻、铰、攻螺纹: 按孔算钱',
             lambda m: 0.0, lambda m: 2.0 + 3.0 * m.copies + m.depth / 30.0,
             {'hole', 'hole_sheet'}, wall=0.0, size=3000, tolerance=0.02, days=1),
    _process('edm', '慢走丝线切割', '线切', '#8E97A3', '切削', '金属丝放电切: 窄缝、尖内角、淬硬钢都能切, 慢',
             lambda m: 300.0, lambda m: m.material(1.2) + _hours(m.cut_length * max(m.t, 5.0) / 9000.0, 140, 0.5),
             {'plate', 'pocket_cut', 'letters'}, metals=_METALS, wall=0.1, size=600, tolerance=0.005, days=6),
    # 铸、锻、挤
    _process('sand_cast', '砂型铸造 + 机加工', '砂铸', '#A8A39A', '铸锻', '木模或 3D 打印砂型: 模具便宜, 大件、壳体、刹车盘这类; 壁要 ≥ 4 mm, 配合面再加工',
             lambda m: 6000.0 + 0.8 * m.bbox_cm3 ** 0.66 * 40, lambda m: m.material(1.15) * 1.6 + 120.0 + m.area_cm2 * 0.03,
             {'revolved', 'prism', 'freeform', 'freeform_small'}, metals={'steel', 'iron', 'light', 'copper'}, wall=4.0, size=3000, tolerance=1.0, days=25),
    _process('investment', '熔模精密铸造', '精铸', '#C9A24A', '铸锻', '蜡模 + 型壳: 复杂小件的近净形, 不太需要再加工',
             lambda m: 6000.0, lambda m: m.material(1.1) * 3.0 + 80.0 + m.volume_cm3 * 0.3,
             {'freeform_small', 'prism', 'revolved'}, metals=_METALS, wall=1.5, size=600, tolerance=0.2, days=30),
    _process('die_cast', '高压压铸 (开钢模)', '压铸', '#7F8894', '铸铁', '铝 / 锌 / 镁合金高压打进钢模: 一件几十秒, 模具几十万到上百万',
             lambda m: 250000.0 + 8.0 * m.bbox_cm3 ** 0.66 * 40, lambda m: m.material(1.1) * 1.3 + 8.0,
             {'prism', 'freeform', 'freeform_small', 'revolved'}, metals={'light', 'copper'}, wall=1.5, size=1500, tolerance=0.1, days=90),
    _process('forging', '模锻 + 机加工', '锻造', '#5E6268', '铸锻', '加热后在锻模里压成形: 强度最好, 轮毂、摆臂、连杆; 模具十几万',
             lambda m: 120000.0, lambda m: m.material(1.3) * 1.5 + 60.0 + m.area_cm2 * 0.05,
             {'revolved', 'prism', 'freeform_small'}, metals={'steel', 'light', 'titanium'}, wall=3.0, size=1200, tolerance=0.5, days=60),
    _process('extrusion', '型材挤压', '挤压', '#B9C0C8', '铸锻', '铝或塑料从模口挤出来, 再按长度切: 截面不变的长件, 挤压模一万上下',
             lambda m: 10000.0, lambda m: m.material(1.1) * 1.4 + 10.0,
             {'profile'}, metals={'light', 'plastic', 'copper'}, wall=1.0, size=12000, tolerance=0.2, days=20),
    _process('tube_bend', '管材弯管', '弯管', '#9DA3A8', '铸锻', '成品管用数控弯管机弯: 排气管、防滚架、扶手',
             lambda m: 1500.0, lambda m: m.material(1.2) + 30.0,
             {'tube'}, metals=_METALS, wall=0.8, size=6000, tolerance=0.5, days=7),
    # 塑料
    _process('injection', '注塑 (开钢模)', '注塑', '#4C94FF', '塑料成形', '塑料打进钢模: 一件几十秒、几块钱; 模具几万到几十万, 壁厚 0.8~4 mm 最好',
             lambda m: 40000.0 + 3.0 * m.bbox_cm3 ** 0.66 * 40, lambda m: m.material(1.1) + 2.0,
             {'freeform_small', 'prism', 'revolved', 'lens', 'letters'}, metals={'plastic'}, wall=0.8, size=1200, tolerance=0.05, days=45),
    # 3D 打印
    _process('fdm', 'FDM 熔融挤出打印', 'FDM', '#E2B43C', '3D 打印', '桌面 / 工业 FDM: 最便宜, 层纹明显, 适合样件、治具',
             lambda m: 0.0, lambda m: 15.0 + m.volume_cm3 * 0.4,
             {'freeform_small', 'prism', 'revolved', 'letters', 'lens'}, metals={'plastic'}, wall=0.8, size=400, tolerance=0.3, days=2),
    _process('sls_print', '尼龙 SLS / MJF 打印', 'SLS', '#E9E4DA', '3D 打印', '粉末床烧结尼龙: 不要支撑, 结构件能直接用',
             lambda m: 0.0, lambda m: 30.0 + m.volume_cm3 * 1.2,
             {'freeform', 'freeform_small', 'prism', 'revolved', 'letters', 'lens'}, metals={'plastic'}, wall=0.7, size=380, tolerance=0.2, days=4),
    _process('sla', 'SLA 光固化打印', 'SLA', '#C7D7E6', '3D 打印', '光敏树脂: 表面光、细节好, 灯罩样件、外观件',
             lambda m: 0.0, lambda m: 30.0 + m.volume_cm3 * 1.8,
             {'freeform_small', 'prism', 'revolved', 'letters', 'lens'}, metals={'plastic'}, wall=0.5, size=600, tolerance=0.1, days=3),
    _process('slm', '金属 SLM 打印', 'SLM', '#A8A39A', '3D 打印', '激光熔化金属粉: 铸不出来、铣不到的复杂金属小件 (镂空、随形流道)',
             lambda m: 0.0, lambda m: 300.0 + m.volume_cm3 * 25.0,
             {'freeform_small', 'prism', 'revolved'}, metals={'steel', 'light', 'titanium'}, wall=0.4, size=400, tolerance=0.1, days=10),
    # 表面
    _process('engrave', '激光雕刻 / 打标', '雕刻', '#C9A227', '表面', '激光在表面刻字、刻标: 深 0.05~1 mm, 按面积算钱',
             lambda m: 0.0, lambda m: 5.0 + m.area_cm2 * 0.05,
             {'engraving'}, wall=0.0, size=1500, tolerance=0.05, days=1),
    # 外协 / 外购
    _process('glass', '钢化 / 热弯玻璃 (外协)', '玻璃', '#2A3A48', '外协', '玻璃厂切割、磨边、热弯钢化: 曲面玻璃要一套热弯模',
             lambda m: 0.0 if m.flat else 8000.0, lambda m: 60.0 + m.sheet_cm2 * 0.06,
             {'glass'}, wall=3.0, size=3200, tolerance=0.5, days=15),
    _process('upholstery', '软包 (发泡 + 皮革缝制)', '软包', '#7A4A2C', '外协', '座椅、扶手: 发泡块切出形状, 蒙皮缝好包上去',
             lambda m: 2000.0, lambda m: 150.0 + m.area_cm2 * 0.15,
             {'soft'}, wall=0.0, size=2000, tolerance=3.0, days=20),
    _process('standard', '标准件 (按规格网购)', '标准', '#3FB97F', '标准件', '国标 / 通用规格的件, 网上、五金店按规格直接买: 螺栓、螺母、垫圈、螺钉、轮胎、气门嘴',
             lambda m: 0.0, lambda m: m.purchase_price,
             {'fastener', 'tyre', 'standard'}, wall=0.0, size=1e9, tolerance=0.0, days=2),
    _process('purchase', '外购总成', '外购', '#5E6268', '标准件', '成熟的总成找供应商买, 不自己做: 减振器、弹簧、轴承、点火线圈、涡轮、发动机、变速箱',
             lambda m: 0.0, lambda m: m.purchase_price,
             {'bought'}, wall=0.0, size=1e9, tolerance=0.0, days=10),
    # 成形后的车皮上开孔、修边
    _process('laser5', '五轴激光修边 / 开孔', '修边', '#E0605A', '板材', '冲压 / 手工成形以后, 在曲面车皮上用五轴激光切窗洞、格栅、修边: 要一个仿形夹具',
             lambda m: 3000.0, lambda m: _hours(m.cut_length / 4000.0 / 60, 450, 0.3),
             {'trim'}, metals=None, wall=0.3, size=6000, tolerance=0.1, days=5),
    _process('hand_trim', '划线手工修边', '手修', '#8E9AAF', '板材', '按样板划线, 用气动剪 / 角磨机切开再打磨: 不要夹具, 一件慢、精度一般',
             lambda m: 0.0, lambda m: _hours(m.cut_length / 400.0 / 60, 160, 0.2),
             {'trim'}, metals=None, wall=0.3, size=1e9, tolerance=1.0, days=2),
]
BY_ID = {item['id']: item for item in PROCESSES}

# 名字里的提示: 特征叫什么, 多半就是什么零件 (正则, 按顺序第一个对上的算)
_HINTS = [
    (r'玻璃|挡风|窗玻', 'glass'), (r'轮胎', 'tyre'), (r'螺栓|螺丝|螺钉|螺母|垫圈|气门嘴|铆钉', 'fastener'),
    (r'减振器|弹簧(?!座)|轴承|点火线圈|涡轮|发动机总成|变速箱|卡钳|刹车盘', 'bought'), (r'坐垫|靠背|包边|头枕|扶手|座椅$', 'soft'),
    (r'灯罩|透镜|镜片', 'lens'),
    (r'排气尾管|排气管|管路', 'tube')]
_PRICE = {'tyre': 1800.0, 'fastener': 1.5, 'bought': 600.0, 'standard': 20.0}     # 外购件一个多少钱 (量级)
STANDARD = {'standard', 'purchase'}         # 这两种工艺的件不用定制: 标准件 / 外购总成
_SHEET_FAMILIES = ('板材', '钣金成形')       # 板件超过设备行程: 分几段做再焊起来
_SHEET_KINDS = ('plate', 'partition', 'skin')
_FOLLOW_SKIN = ('skin', 'pocket')           # 车皮的内形、凹槽: 和车皮一起成形, 费用算在外形里
_NO_PROCESS = {'sketch', 'plane', 'axis', 'point', 'helix', 'curve3d', 'composite_curve', 'projected_curve', 'split'}


class _Measure:
    """工艺费用公式用到的量 (都由内核量的工具体指标算出来, mm → cm 换算在这里做)。"""

    def __init__(self, metrics, material, hint=None, params=None, copies=1):
        metrics = metrics or {}
        size = metrics.get('size') or [0.0, 0.0, 0.0]
        self.size = [float(value) for value in size]
        self.length = max(self.size) if self.size else 0.0
        self.volume = float(metrics.get('volume') or 0.0)
        self.area = float(metrics.get('area') or 0.0)
        self.t = float(metrics.get('thickness') or 0.0)
        if self.size and self.size[0] > 0:
            self.t = min(self.t, self.size[0]) if self.t else self.size[0]
        self.faces = metrics.get('faces') or {}
        self.copies = max(int(copies or 1), 1)
        self.material_name = material or _DEFAULT_MATERIAL
        self.family, self.price = _STOCK.get(self.material_name, ('steel', 7.0))
        self.density = materials.density(self.material_name) or 7.85
        self.hint = hint
        self.params = params or {}
        self.features_count = 1
        if hint == 'skin':                  # 车皮: 外形 (或内形) 的表面积 × 板厚
            self.t = SKIN_GUESS
            self.volume = self.area * SKIN_GUESS

    # ---- 几种派生量 ----
    @property
    def volume_cm3(self):
        return self.volume / 1000.0

    @property
    def area_cm2(self):
        return self.area / 100.0

    @property
    def sheet_cm2(self):
        """板件的展开面积 (cm²): 两面加几条边, 取一半。"""
        return self.area / 200.0

    @property
    def bbox_cm3(self):
        return max(self.size[0] * self.size[1] * self.size[2], self.volume) / 1000.0 if len(self.size) == 3 else self.volume_cm3

    @property
    def removed_cm3(self):
        return max(self.bbox_cm3 * 1.15 - self.volume_cm3, 0.0)

    @property
    def cut_length(self):
        """板件的切割长度 (mm): 外轮廓 + 孔, 按展开面积估 (近似正方形的周长再乘 1.6)。"""
        plate = max(self.area / 2.0, 1.0)
        return 4.0 * math.sqrt(plate) * 1.6

    @property
    def depth(self):
        return float(self.params.get('distance') or self.length or 0.0)

    @property
    def mrr(self):
        """材料去除率 cm³/分钟: 铝和塑料快, 钢慢, 钛更慢。"""
        return {'light': 40.0, 'plastic': 60.0, 'copper': 25.0, 'steel': 12.0, 'iron': 15.0, 'titanium': 5.0}.get(self.family, 12.0)

    @property
    def flat(self):
        return not self.faces.get('freeform') and not self.faces.get('cylinder')

    @property
    def purchase_price(self):
        return _PRICE.get(self.hint, 50.0)

    def material(self, waste=1.2):
        """净重 × 损耗 × 单价 (元)。"""
        return self.volume_cm3 * self.density / 1000.0 * self.price * waste

    def stock(self, waste=1.0):
        """切削用的整块料 (包围盒大一圈) 的钱。"""
        return self.bbox_cm3 * 1.15 * self.density / 1000.0 * self.price * waste


def _sketch_shapes(feature, by_id):
    sketch = by_id.get(feature.get('params', {}).get('sketch'))
    return (sketch or {}).get('params', {}).get('shapes') or []


def _hollow_document(features):
    return any(f.get('params', {}).get('op') == 'void' or f.get('type') == 'shell' for f in features if not f.get('suppressed'))


def shape_kind(feature, metrics, by_id, hollow):
    """特征做出来的东西属于哪一类 (决定哪些工艺能参加比较); 返回 (类别, 一句为什么)。None = 不用工艺 (草图、基准面…)。"""
    kind, params = feature.get('type'), feature.get('params') or {}
    if kind in _NO_PROCESS or kind not in by_id.get('__solid_kinds__', ()):
        return None, ''
    name = feature.get('name') or ''
    op = params.get('op', 'add')
    for pattern, hint in _HINTS:
        if op != 'cut' and re.search(pattern, name):     # 切除不看名字: "螺栓孔"、"减振器让位孔" 是孔, 不是买来的螺栓、减振器
            return hint, f'名字是 “{name}”'
    m = metrics or {}
    size = m.get('size') or [0.0, 0.0, 0.0]
    thin = size[0] if size else 0.0
    faces = m.get('faces') or {}
    shapes = _sketch_shapes(feature, by_id)
    text = any(shape.get('type') == 'text' for shape in shapes)
    if op == 'void' or kind == 'shell':
        return 'skin', '空心件的内形: 外形和内形之间就是一层车皮'
    if op == 'fill':
        return 'partition', '只长在空腔里的板: 地板、隔板这类焊在车皮上的平板'
    if op == 'pocket':
        return 'pocket', '空心件上的凹槽: 和车皮一起成形'
    if text:
        if op == 'cut' or thin <= 1.5:
            return 'engraving', '刻在表面上的字'
        return 'letters', '凸起的字: 一个个切出来贴上去'
    if op == 'cut':
        circles = shapes and all(shape.get('type') == 'circle' for shape in shapes if not shape.get('construction'))
        if kind == 'hole' or circles and kind == 'extrude':
            return 'hole', '圆孔'
        if hollow and max(size or [0]) > 200:
            return 'trim', '在成形好的车皮上开的窗洞、格栅'
        return 'pocket_cut', '切出来的槽、窗、缺口'
    if kind in ('hole', 'thread'):
        return 'hole', '孔 / 螺纹'
    if kind in ('revolve',):
        return 'revolved', '旋转出来的回转体'
    round_bar = shapes and all(shape.get('type') == 'circle' for shape in shapes if not shape.get('construction'))
    if kind == 'extrude' and round_bar and not faces.get('freeform') and thin > 12:
        return 'revolved', '圆柱 (棒料车出来)'
    if kind in ('loft', 'sweep', 'boundary') and hollow and max(size or [0]) > 800:
        return 'skin', '空心件的外形曲面: 做出来是一层车皮'
    if kind in ('loft', 'sweep', 'boundary', 'wrap') or faces.get('freeform'):
        return ('freeform_small' if max(size or [0]) <= 400 else 'freeform'), '自由曲面'
    if kind == 'extrude' and thin <= 12 and not faces.get('freeform'):
        return 'plate', f'厚 {thin:.3g} mm 的平板'
    if kind == 'extrude' and len(size) == 3 and size[2] > 5 * max(size[1], 1e-9) and size[1] <= 200 and size[2] > 300:
        return 'profile', '截面不变的长条'
    if kind in ('extrude', 'rib', 'draft', 'emboss'):
        return 'prism', '有厚度的块'
    return 'prism', '实体'


def _feasible(process, m, kind):
    """这种工艺做不做得了: → (能不能, 不能的原因)。"""
    if kind not in process['kinds']:
        return False, '形状不对'
    family = 'glass' if kind == 'glass' else m.family
    if process['metals'] is not None and family not in process['metals'] and kind not in ('glass', 'soft', 'tyre', 'fastener', 'bought'):
        return False, f'不能用{m.material_name}'
    if m.length > process['size'] and not (kind in _SHEET_KINDS and process['family'] in _SHEET_FAMILIES):
        return False, f'零件长 {m.length:.0f} mm, 超过这种工艺的 {process["size"]:.0f} mm'
    if kind in ('plate', 'skin', 'pocket', 'partition', 'freeform', 'freeform_small', 'prism', 'revolved') and 0 < m.t < process['wall']:
        return False, f'壁厚 {m.t:.2g} mm 比这种工艺的下限 {process["wall"]:g} mm 薄'
    return True, ''


def segments(process, m, kind):
    """板件比设备行程长时分几段做 (1 = 不用分)。"""
    if kind in _SHEET_KINDS and process['family'] in _SHEET_FAMILIES and m.length > process['size']:
        return math.ceil(m.length / process['size'])
    return 1


def rank(feature, metrics, by_id, batch=DEFAULT_BATCH, material='', hollow=False, copies=1):
    """→ (类别, 为什么, [(每件价钱, 工艺, 模具费, 单件费)... 从便宜到贵], [(工艺, 做不了的原因)...])。"""
    kind, why = shape_kind(feature, metrics, by_id, hollow)
    if kind is None:
        return None, '', [], []
    hint = kind if kind in _PRICE or kind == 'skin' else None
    if kind == 'lens':
        material = '聚碳酸酯 PC'
    copies = max(int(copies or 1), int((metrics or {}).get('solids') or 1))     # 一张草图里好几块 (左右两个灯): 按单件量, 乘件数
    m = _Measure(metrics, material, hint, feature.get('params'), copies)
    batch = max(int(batch or 1), 1)
    options, refused = [], []
    for process in PROCESSES:
        ok, reason = _feasible(process, m, kind)
        if not ok:
            if reason != '形状不对':
                refused.append((process, reason))
            continue
        tooling, unit = float(process['tooling'](m)), float(process['unit'](m)) * m.copies
        pieces = segments(process, m, kind)
        if pieces > 1:                      # 分 n 段做: 模具 / 夹具按段数, 每条焊缝另算
            tooling *= pieces
            unit += 300.0 * (pieces - 1) * m.copies
        options.append((tooling / batch + unit, process, tooling, unit))
    options.sort(key=lambda item: (round(item[0], 2), item[1]['tolerance']))
    return kind, why, options, refused


def _money(value):
    if value >= 1e8:
        return f'{value / 1e8:.2f} 亿'
    if value >= 1e4:
        return f'{value / 1e4:.1f} 万'
    return f'{value:.0f}' if value >= 10 else f'{value:.2f}'


def choose(feature, metrics, by_id, batch=DEFAULT_BATCH, material='', hollow=False, copies=1):
    """给一个特征挑工艺 → 存进 feature['process'] 的字典; 不用工艺的返回 None。"""
    kind, why, options, refused = rank(feature, metrics, by_id, batch, material, hollow, copies)
    if kind is None:
        return None
    if not options:
        reasons = '；'.join(f'{process["name"]}：{reason}' for process, reason in refused[:4]) or '没有能做这种形状的工艺'
        return {'id': '', 'name': '没有合适的工艺', 'short': '?', 'color': '#E0605A', 'kind': kind, 'auto': True, 'batch': batch,
                'why': f'{why}。{reasons}', 'alternatives': []}
    cost, process, tooling, unit = options[0]
    m = _Measure(metrics, material, kind if kind in _PRICE or kind == 'skin' else None, feature.get('params'), copies)
    pieces = segments(process, m, kind)
    note = f'{why} → {process["name"]}：做 {batch} 件, 每件约 ¥{_money(cost)}'
    if pieces > 1:
        note += f' (长 {m.length:.0f} mm 超过设备的 {process["size"]:.0f} mm: 分 {pieces} 段做再焊起来)'
    if tooling > 0:
        note += f' (模具 / 工装 ¥{_money(tooling)} 摊下来 ¥{_money(tooling / batch)} + 单件 ¥{_money(unit)})'
    if len(options) > 1:
        runner = options[1]
        note += f'；第二是 {runner[1]["name"]} ¥{_money(runner[0])}'
        break_even = _break_even(options[0], options[1:])
        if break_even:
            note += f'；做到 {break_even[0]} 件以上换成 {break_even[1]} 更划算'
    standard = process['id'] in STANDARD
    spec = standard_spec(feature, metrics, by_id, kind) if standard else ''
    if spec:
        note = f'{spec}。' + note
    return {'id': process['id'], 'name': process['name'], 'short': process['short'], 'color': process['color'], 'kind': kind,
            'auto': True, 'batch': batch, 'cost': round(cost, 2), 'tooling': round(tooling, 2), 'unit': round(unit, 2),
            'standard': standard, 'spec': spec, 'why': note, 'alternatives': [{'id': item[1]['id'], 'name': item[1]['name'], 'cost': round(item[0], 2)}
                                          for item in options[1:4]]}


def _break_even(best, others):
    """模具费高、单件便宜的工艺: 做到多少件以上比现在这个便宜 → (件数, 工艺名); 没有就 None。"""
    _, process, tooling, unit = best
    found = None
    for _, other, other_tooling, other_unit in others:
        if other_unit < unit and other_tooling > tooling:
            count = math.ceil((other_tooling - tooling) / (unit - other_unit))
            if found is None or count < found[0]:
                found = (count, other['name'])
    return found


# 六角头螺栓 / 螺母: 螺纹规格 → 对边宽度 s (GB/T 5782 / GB/T 6170); 平垫圈外径 (GB/T 97.1); 盘头螺钉头部直径 (GB/T 818)
BOLT_FLATS = {'M5': 8, 'M6': 10, 'M8': 13, 'M10': 16, 'M12': 18, 'M14': 21, 'M16': 24, 'M20': 30, 'M24': 36}
WASHER_OD = {'M5': 10, 'M6': 12, 'M8': 16, 'M10': 20, 'M12': 24, 'M14': 28, 'M16': 30, 'M20': 37, 'M24': 44}
PAN_HEAD = {'M3': 5.6, 'M4': 8.0, 'M5': 9.5, 'M6': 12.0, 'M8': 16.0, 'M10': 20.0}


def _nearest(table, value):
    """→ (规格, 表里的值, 差多少)。"""
    size, close = min(table.items(), key=lambda item: abs(item[1] - value))
    return size, close, value - close


def standard_spec(feature, metrics, by_id, kind=None):
    """标准件的规格 (能拿去网上搜的写法); 尺寸对不上标准的, 后面写上该改成多少。"""
    name = feature.get('name') or ''
    shapes = [shape for shape in _sketch_shapes(feature, by_id) if not shape.get('construction')]
    size = (metrics or {}).get('size') or [0.0, 0.0, 0.0]
    length = float((feature.get('params') or {}).get('distance') or 0.0)
    hexes = [shape for shape in shapes if shape.get('type') == 'ngon' and int(shape.get('sides') or 0) == 6]
    circles = [shape for shape in shapes if shape.get('type') == 'circle']
    if hexes:
        flats = float(hexes[0].get('r') or 0) * math.sqrt(3)
        thread, close, off = _nearest(BOLT_FLATS, flats)
        nut = '螺母' in name
        text = f'GB/T 6170 {thread} 六角螺母' if nut else f'GB/T 5782 {thread}×{max(round(length * 2), 10)} 六角头螺栓'
        if abs(off) > 0.5:
            text += f' (现在对边 {flats:.1f} mm, 标准是 {close} mm: 改成 {close} mm 才买得到)'
        return text
    if circles and '垫圈' in name:
        diameter = 2 * float(circles[0].get('r') or 0)
        thread, close, off = _nearest(WASHER_OD, diameter)
        text = f'GB/T 97.1 {thread} 平垫圈'
        if abs(off) > 0.5:
            text += f' (现在外径 {diameter:.1f} mm, 标准是 {close} mm)'
        return text
    if circles and re.search(r'螺丝|螺钉', name):
        diameter = 2 * float(circles[0].get('r') or 0)
        thread, close, off = _nearest(PAN_HEAD, diameter)
        text = f'GB/T 818 {thread} 十字盘头螺钉'
        if abs(off) > 0.8:
            text += f' (现在头部 {diameter:.1f} mm, 标准是 {close} mm)'
        return text
    if '气门嘴' in name:
        return 'TR414 无内胎气门嘴'
    if kind == 'tyre' and size and size[2] > 0:
        outer, width = size[2], size[0]
        rim = None
        for inch in range(13, 24):
            sidewall = (outer - inch * 25.4) / 2
            if width > 0 and 0.25 <= sidewall / width <= 0.8:
                rim = inch if rim is None or abs(sidewall / width - 0.4) < abs((outer - rim * 25.4) / 2 / width - 0.4) else rim
        if rim:
            section = int(round(width / 5.0) * 5)
            aspect = int(round((outer - rim * 25.4) / 2 / width * 20) * 5)
            return f'{section}/{aspect} R{rim} 轮胎'
        return '轮胎 (按外径 / 断面宽选规格)'
    return name


def solid_kinds():
    from . import features as table
    return {'extrude', 'fillet', 'chamfer', 'hole'} | set(table.SPECS)


def bind(features, report, batch=DEFAULT_BATCH, material='', only=None):
    """给特征表里的造型特征绑工艺 → {特征 id: 工艺字典}。阵列、镜像跟原件走; 圆角、倒角跟着它前面最近的那个造型特征。
    手动指定过的 (auto=False) 不动。only: 只绑这些 id。"""
    by_id = {feature['id']: feature for feature in features}
    by_id['__solid_kinds__'] = solid_kinds()
    tools = (report or {}).get('tools') or {}
    hollow = _hollow_document(features)
    bound, last, skin, skin_name = {}, None, None, ''
    for feature in features:
        if feature.get('suppressed'):
            continue
        identifier, kind = feature['id'], feature.get('type')
        current = feature.get('process')
        params = feature.get('params') or {}
        if only is not None and identifier not in only:
            if current:
                last = current
            continue
        if current and not current.get('auto', True):
            bound[identifier] = current
            last = current
            continue
        if kind in ('pattern_linear', 'pattern_circular', 'mirror', 'pattern_curve', 'pattern_sketch', 'pattern_table',
                    'pattern_fill', 'pattern_variable'):
            seeds = [bound.get(seed) or (by_id.get(seed) or {}).get('process') for seed in params.get('features') or []]
            seeds = [seed for seed in seeds if seed and seed.get('id')]
            if seeds:
                copy = dict(seeds[0], why=f'复制原件 → 和原件一样用{seeds[0]["name"]}', auto=True)
                copy['alternatives'] = list(seeds[0].get('alternatives') or [])
                bound[identifier] = copy
            continue
        if kind in ('fillet', 'chamfer'):
            if last and last.get('id'):
                bound[identifier] = dict(last, why=f'{"圆角" if kind == "fillet" else "倒角"}在{last["name"]}的时候一起做出来', auto=True)
            continue
        metrics = tools.get(identifier)
        choice = choose(feature, metrics, by_id, batch, material, hollow, 1)
        if choice is not None and choice.get('kind') in _FOLLOW_SKIN and skin is not None and choice is not skin:
            choice = dict(skin, cost=0.0, tooling=0.0, unit=0.0, auto=True, alternatives=[],
                          why=f'和车皮一起成形 → {skin["name"]} (费用算在 “{skin_name}” 里)')
        if choice is not None:
            bound[identifier] = choice
            if choice.get('id'):
                last = choice
            if choice.get('kind') == 'skin' and skin is None and choice.get('id'):
                skin, skin_name = choice, feature.get('name') or identifier
    return bound


def catalog():
    """给 AI 接口和界面看的工艺表 (不含费用公式)。"""
    return [{key: item[key] for key in ('id', 'name', 'short', 'color', 'family', 'about', 'wall', 'size', 'tolerance', 'days')}
            for item in PROCESSES]
