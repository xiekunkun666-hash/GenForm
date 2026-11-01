"""PA12 吸粉器 (风扇版)：台达 12 cm 4 线 PWM 风扇 + 切向进气旋风分离 + 滤网，粉不过风扇。

坐标：Z 朝上。集粉锥斗 z-33.4–100 (透明 PC, 60° 锥底, Ø22 出粉口 + 配重翻板阀)；旋风头 z80–165 (插口伸进杯里 20, O 形圈径向密封, 推上去即可, 负压吸住)；
旋风腔顶 z145 隔板 3 厚，上面 Ø104×17 匀风腔；滤网 z165–166 边缘夹在旋风头和滤网框之间；滤网框 z165–180 (格栅托住滤网)；风扇 120×120×38 z180–218，往上排风。
进气口：Ø32 切向管 (吸尘器标准 32 mm 配件直接套上)，中心 z125，y=36，朝 +X。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'examples' / 'porsche_911'))
sys.path.insert(0, str(ROOT / 'examples' / 'powder_pump'))
from mcp_client import Client
from build import step, sketch, circle, point, cl, extrude   # 叶轮泵脚本里的通用小函数

OUTPUT = ROOT / 'models' / 'powder_pump_fan'

FAN, FAN_T, FAN_HOLE = 120.0, 38.0, 52.5        # 台达 12 cm：孔距 105，厚 38 (25 厚的换短螺钉)
CUP_TOP, SEP, HEAD_TOP, FRAME_TOP = 100.0, 145.0, 165.0, 180.0   # SEP = 旋风腔顶 / 3 厚隔板底; 隔板上是 Ø104×17 匀风腔
FAN_TOP = FRAME_TOP + FAN_T
INLET_Y, INLET_Z = 36.0, 125.0                  # 切向：管内壁外缘 y=50 与旋风筒内壁相切
FRAME_SCREWS = [(x, y) for x in (-45, 45) for y in (-45, 45)]
FAN_SCREWS = [(x, y) for x in (-FAN_HOLE, FAN_HOLE) for y in (-FAN_HOLE, FAN_HOLE)]


def rect(cx, cy, w, h):
    return {'type': 'rect', 'cx': cx, 'cy': cy, 'w': w, 'h': h}


def simple_hole(alias, src, d, depth=None):
    args = dict(name=alias, sketch='$' + src, kind='simple', size='custom', diameter=d)
    args.update(through=True) if depth is None else args.update(depth=depth)
    return step('hole', alias, **args)


PARTS = {}


def part(filename, name, material, color=None):
    def wrap(fn):
        PARTS[filename] = (name, material, color, fn)
        return fn
    return wrap


# 锥斗 + 翻板阀：内锥半角 30° (60° 锥)，r50.5@z45 → 出粉口 Ø22@z-23.4，出粉短管到 z-33.4 (底面 = 阀座)
SEAT_Z = -33.4
HINGE = (22.0, -37.0)          # 翻板铰轴 (x, z)，轴线沿 Y
CW_X = 32.0                    # 配重螺钉位置


def radial_plane(alias, z, sign):
    return step('plane', alias, name=alias, offset=0, origin=[[0, 0, z]], normal=[[0, sign, 0]])


@part('collection_cup.gform', '集粉锥斗 | 透明 PC 车削, 60° 锥底, Ø22 出粉口', '聚碳酸酯 PC', '#cfe3ef')
def cup():
    prof = [(50.5, CUP_TOP), (55, CUP_TOP), (55, 46.8), (15, -22.5), (15, SEAT_Z), (11, SEAT_Z),
            (11, -23.4), (50.5, 45)]
    return [sketch('wall', 'XZ', 0, [{'type': 'polygon', 'points': [list(p) for p in prof]}, cl(0, -100, 0, 200)]),
            step('revolve', 'wall_x', name='wall_x', sketch='$wall', axis='CL', angle=360),
            sketch('valve_screw_holes', 'XZ', 20, [point(0, -28)]),
            simple_hole('valve_tap', 'valve_screw_holes', 3.0)]          # M3 螺纹孔，两侧对穿


@part('valve_body.gform', '翻板阀座 | PA12 打印, 套在出粉短管上, 带铰耳', '尼龙 PA12', '#4a525b')
def valve_body():
    hx, hz = HINGE
    return [sketch('sleeve', 'XY', SEAT_Z, [circle(0, 0, 19), circle(0, 0, 15)]),
            extrude('sleeve_x', 'sleeve', 10.4),
            sketch('ear_a', 'XZ', -5, [rect(21, -33, 10, 18)]),
            step('extrude', 'ear_a_x', name='ear_a_x', sketch='$ear_a', distance=3, symmetric=True),
            sketch('ear_b', 'XZ', 5, [rect(21, -33, 10, 18)]),
            step('extrude', 'ear_b_x', name='ear_b_x', sketch='$ear_b', distance=3, symmetric=True),
            sketch('pin_hole', 'XZ', 0, [circle(hx, hz, 1.5)]),
            step('extrude', 'pin_hole_cut', name='pin_hole_cut', sketch='$pin_hole', distance=20, symmetric=True,
                 op='cut'),
            sketch('screw_holes', 'XZ', 20, [point(0, -28)]),
            simple_hole('screw_clear', 'screw_holes', 3.4)]


@part('flap.gform', '翻板 | PA12 打印 (轻), 关闭位', '尼龙 PA12', '#e07b39')
def flap():
    hx, hz = HINGE
    return [sketch('disc', 'XY', SEAT_Z - 3.5, [circle(0, 0, 14)]),
            extrude('disc_x', 'disc', 2),
            sketch('arm', 'XY', SEAT_Z - 3.5, [rect(23, 0, 26, 6)]),
            extrude('arm_x', 'arm', 2),
            sketch('boss', 'XZ', 0, [circle(hx, hz, 3)]),
            step('extrude', 'boss_x', name='boss_x', sketch='$boss', distance=6, symmetric=True),
            sketch('bore', 'XZ', 0, [circle(hx, hz, 1.6)]),
            step('extrude', 'bore_cut', name='bore_cut', sketch='$bore', distance=8, symmetric=True, op='cut'),
            sketch('cw_hole', 'XY', SEAT_Z - 1.5, [circle(CW_X, 0, 1.7)]),
            extrude('cw_hole_cut', 'cw_hole', -2, 'cut')]


@part('flap_seal.gform', '翻板密封垫 Ø28×1.5 (硅胶)', '橡胶', '#c43c3c')
def flap_seal():
    return [sketch('pad', 'XY', SEAT_Z - 1.5, [circle(0, 0, 14)]),
            extrude('pad_x', 'pad', 1.5)]


@part('counterweight.gform', '配重块 6×10×20 黄铜 ≈10 g (加减垫片调)', '黄铜', '#c9a227')
def counterweight():
    return [sketch('block', 'XY', SEAT_Z - 3.5, [rect(CW_X, 0, 10, 6)]),
            extrude('block_x', 'block', -20),
            sketch('tap', 'XY', SEAT_Z - 3.5, [point(CW_X, 0)]),
            simple_hole('cw_tap', 'tap', 3.0, 8.0)]


@part('hinge_pin_3x14.gform', '圆柱销 Ø3×14 (GB/T 119, 压在铰耳里)', '不锈钢 304', '#9aa0a8')
def hinge_pin():
    hx, hz = HINGE
    return [sketch('pin', 'XZ', 0, [circle(hx, hz, 1.5)]),
            step('extrude', 'pin_x', name='pin_x', sketch='$pin', distance=14, symmetric=True)]


@part('screws_valve_M3x8.gform', '盘头螺钉 M3×8 ×2 (阀座→锥斗短管) + M3×8 ×1 (配重)', '不锈钢 304', '#9aa0a8')
def valve_screws():
    return [radial_plane('pa', -28, 1), sketch('sa', '$pa', 19, [point(0, 0)]),
            step('screw', 's1', name='s1', sketch='$sa', size='M3', head='button', length=8, thread=False),
            radial_plane('pb', -28, -1), sketch('sb', '$pb', 19, [point(0, 0)]),
            step('screw', 's2', name='s2', sketch='$sb', size='M3', head='button', length=8, thread=False),
            sketch('sc', 'XY', SEAT_Z - 1.5, [point(CW_X, 0)]),
            step('screw', 's3', name='s3', sketch='$sc', size='M3', head='button', length=8, thread=False)]


@part('cyclone_head.gform', '旋风头 | PA12 打印 (SLS/MJF), 切向进气 Ø32', '尼龙 PA12', '#5d6670')
def head():
    return [sketch('flange', 'XY', HEAD_TOP - 5, [rect(0, 0, FAN, FAN)]),
            extrude('flange_x', 'flange', 5),
            sketch('barrel', 'XY', CUP_TOP, [circle(0, 0, 55)]),
            extrude('barrel_x', 'barrel', HEAD_TOP - 5 - CUP_TOP),
            sketch('spigot', 'XY', CUP_TOP - 20, [circle(0, 0, 50.3)]),
            extrude('spigot_x', 'spigot', 20),
            sketch('inlet', 'YZ', 0, [circle(INLET_Y, INLET_Z, 16)]),
            extrude('inlet_x', 'inlet', 90),
            sketch('chamber', 'XY', CUP_TOP - 20, [circle(0, 0, 50)]),
            extrude('chamber_cut', 'chamber', SEP - (CUP_TOP - 20), 'cut'),
            sketch('finder', 'XY', SEP, [circle(0, 0, 22), circle(0, 0, 20)]),
            extrude('finder_x', 'finder', -40),
            sketch('plenum', 'XY', HEAD_TOP, [circle(0, 0, 52)]),
            extrude('plenum_cut', 'plenum', -(HEAD_TOP - SEP - 3), 'cut'),
            sketch('finder_exit', 'XY', SEP + 3, [circle(0, 0, 20)]),
            extrude('finder_exit_cut', 'finder_exit', -3, 'cut'),
            sketch('inlet_bore', 'YZ', 30, [circle(INLET_Y, INLET_Z, 14)]),
            extrude('inlet_bore_cut', 'inlet_bore', 60, 'cut'),
            sketch('oring_groove', 'XZ', 0, [rect(49.4, 89.3, 1.8, 3.0), cl(0, 0, 0, 200)]),
            step('revolve', 'groove_cut', name='groove_cut', sketch='$oring_groove', axis='CL', angle=360, op='cut'),
            sketch('frame_holes', 'XY', HEAD_TOP, [point(x, y) for x, y in FRAME_SCREWS]),
            simple_hole('frame_tap', 'frame_holes', 4.0, 5.0)]     # M4 螺纹孔 (打印件建议压 M4 铜螺母或热熔螺母)


@part('oring_97x2.gform', 'O 形圈 ID97×2 (NBR, 杯口径向密封)', '橡胶', '#1d1f22')
def oring():
    return [sketch('section', 'XZ', 0, [circle(49.5, 89.3, 1.0), cl(0, 0, 0, 200)]),
            step('revolve', 'ring', name='ring', sketch='$section', axis='CL', angle=360)]


@part('filter_disc.gform', '滤网 Ø116 (H13 HEPA / PTFE 覆膜毡) 边缘夹紧兼作密封垫', '聚丙烯 PP', '#f2f2ec')
def filt():
    return [sketch('disc', 'XY', HEAD_TOP, [circle(0, 0, 58)]),
            extrude('disc_x', 'disc', 1.0)]


@part('filter_frame.gform', '滤网框 + 格栅 | PA12 打印, 风扇座', '尼龙 PA12', '#4a525b')
def frame():
    bars = [-27.5, 0.0, 27.5]
    return [sketch('block', 'XY', HEAD_TOP, [rect(0, 0, FAN, FAN)]),
            extrude('block_x', 'block', FRAME_TOP - HEAD_TOP),
            sketch('opening', 'XY', FRAME_TOP, [circle(0, 0, 52)]),
            extrude('opening_cut', 'opening', -(FRAME_TOP - HEAD_TOP), 'cut'),
            sketch('recess', 'XY', HEAD_TOP, [circle(0, 0, 58.1)]),
            extrude('recess_cut', 'recess', 1, 'cut'),            # 滤网边 r52–58 被旋风头顶面和这里夹住
            sketch('bars_x', 'XY', HEAD_TOP + 1, [rect(0, y, 116, 2) for y in bars]),
            extrude('bars_x_x', 'bars_x', 4),
            sketch('bars_y', 'XY', HEAD_TOP + 1, [rect(x, 0, 2, 116) for x in bars]),
            extrude('bars_y_x', 'bars_y', 4),
            sketch('frame_holes', 'XY', FRAME_TOP, [point(x, y) for x, y in FRAME_SCREWS]),
            step('hole', 'frame_csk', name='frame_csk', sketch='$frame_holes', kind='countersink', size='M4',
                 through=True),
            sketch('fan_holes', 'XY', FRAME_TOP, [point(x, y) for x, y in FAN_SCREWS]),
            simple_hole('fan_tap', 'fan_holes', 4.0, 13.0)]


@part('delta_fan_120x38.gform', '台达 12 cm 风扇 120×120×38 4 线 PWM (外购, 占位)', '聚碳酸酯 PC', '#202226')
def fan():
    return [sketch('frame', 'XY', FRAME_TOP, [rect(0, 0, FAN, FAN)]),
            extrude('frame_x', 'frame', FAN_T),
            step('fillet', None, name='corners', edges='|Z', radius=5),
            sketch('bore', 'XY', FAN_TOP, [circle(0, 0, 58)]),
            extrude('bore_cut', 'bore', -FAN_T, 'cut'),
            sketch('hub', 'XY', FRAME_TOP + 2, [circle(0, 0, 22)]),
            extrude('hub_x', 'hub', FAN_T - 2),
            sketch('struts', 'XY', FAN_TOP - 4, [rect(0, 0, 118, 4)]),
            extrude('struts_x', 'struts', 4),
            sketch('struts2', 'XY', FAN_TOP - 4, [rect(0, 0, 4, 118)]),
            extrude('struts2_x', 'struts2', 4),
            sketch('blade', 'XY', FRAME_TOP + 6, [rect(39.5, 0, 35, 1.5)]),
            extrude('blade_x', 'blade', 24),
            step('pattern_circular', 'blades', name='blades', features=['$blade_x'], axis='Z', count=7, angle=360),
            sketch('holes', 'XY', FAN_TOP, [point(x, y) for x, y in FAN_SCREWS]),
            simple_hole('fan_holes', 'holes', 4.3)]


@part('screws_frame_M4x20_flat.gform', '沉头螺钉 M4×20 ×4 (滤网框→旋风头)', '不锈钢 304', '#9aa0a8')
def frame_screws():
    return [sketch('pts', 'XY', FRAME_TOP, [point(x, y) for x, y in FRAME_SCREWS]),
            step('screw', 's', name='s', sketch='$pts', size='M4', head='flat', length=20, thread=False)]


@part('screws_fan_M4x50.gform', '内六角螺钉 M4×50 ×4 (风扇→滤网框)', '不锈钢 304', '#9aa0a8')
def fan_screws():
    return [sketch('pts', 'XY', FAN_TOP, [point(x, y) for x, y in FAN_SCREWS]),
            step('screw', 's', name='s', sketch='$pts', size='M4', head='cap', length=50, thread=False)]


def build(client, filename, force):
    name, material, color, fn = PARTS[filename]
    dest = OUTPUT / filename
    if dest.exists() and not force:
        print('SKIP', filename, flush=True)
        return
    client.call('new_document')
    answer = client.call('batch', steps=fn())
    model = answer.get('model') or client.call('get_model', brief=True)
    failed = [r for r in model.get('features', []) if r.get('status') not in ('ok', None)]
    if failed or not model.get('has_body'):
        print(json.dumps({'file': filename, 'failed': failed, 'answer': answer}, ensure_ascii=False)[:3000])
        raise SystemExit(1)
    client.request('tools/call', {'name': 'set_material', 'arguments': {'name': material}})
    if color:
        client.call('set_appearance', color=color)
    client.call('save_document', path=str(dest))
    print(json.dumps({'saved': filename, 'body': model.get('body')}, ensure_ascii=False), flush=True)


def assembly():
    order = list(PARTS)
    parts = [{'name': PARTS[f][0], 'file': f, 'move': [0, 0, 0], 'turn': [0, 0, 0]} for f in order]
    moving = [order.index(f) for f in ('flap.gform', 'flap_seal.gform', 'counterweight.gform')]
    joints = [{'name': '翻板阀 (负 = 打开卸粉)', 'kind': 'hinge', 'origin': [HINGE[0], 0, HINGE[1]],
               'axis': [0, 1, 0], 'parts': moving, 'base': order.index('valve_body.gform'), 'min': -60, 'max': 0}]
    doc = {'format': 'genform-assembly', 'version': 1, 'parts': parts, 'joints': joints}
    (OUTPUT / 'powder_pump_fan.gasm').write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print('saved powder_pump_fan.gasm')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('parts', nargs='*')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    client = Client()
    try:
        for f in a.parts or list(PARTS):
            build(client, f, a.force)
    finally:
        client.close()
    assembly()


if __name__ == '__main__':
    main()
