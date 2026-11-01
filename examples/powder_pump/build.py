"""PA12 抽粉泵：开式径向叶轮离心抽吸泵 (粉料风机式)，无刷电机直驱。

坐标：Z 朝上 = 电机轴；电机安装面 z=0；泵体 z0–14.5；前盖 z14.5–19.5；进出口软管接头朝 +Z。
叶轮俯视逆时针转，蜗壳为平面阿基米德螺线 (2.5 轴铣)，出口在前盖上与进口平行。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'examples' / 'porsche_911'))
from mcp_client import Client

OUTPUT = ROOT / 'models' / 'powder_pump'

# 主要尺寸
BODY_R = 37.0            # 泵体外圆
BOSS = (30.0, -26.0)     # 出口口位 (蜗壳出口槽末端 = 前盖出口孔)
BOSS_W = 24.0            # 出口凸台宽 (槽口)
FLOOR, CEIL, TOP = 6.0, 14.5, 19.5
IMP_R, IMP_Z0 = 20.0, 6.5
VOLUTE_R0, VOLUTE_GROW, CH_W = 22.0, 8.0, 8.0
COVER_SCREWS = [(33 * math.cos(math.radians(a)), 33 * math.sin(math.radians(a))) for a in (45, 135, 225)] \
    + [(36.5, -20.5), (25.0, -33.0)]
# 电机：Surpass Hobby KK2845 无刷内转子 (标准件)：Ø28×47，轴 Ø3.175×15，前端 M3 孔两对 (孔距 16 / 19)
MOTOR_SCREWS = [(8.0, 0.0), (-8.0, 0.0), (0.0, 9.5), (0.0, -9.5)]
SHAFT_R, SHAFT_TOP, CAN_LEN = 3.175 / 2, 15.0, 47.0
# 真螺纹: OCC 里一个 M3×8 螺纹孔的布尔就要 ~35 s, 一个特征里 5 个会超过 120 s 看门狗。
# False = 螺纹孔画成公称直径的光孔、螺钉画光杆 (干涉检查结果一样)；出图前改 True 重建。
THREADS = False
KEY = 30.0               # D 型轴削平 / 顶丝方向 (°)，在两片叶片 (0°, 60°) 正中


def step(cmd, alias=None, **args):
    row = {'cmd': cmd, 'args': args}
    if alias:
        row['as'] = alias
    return row


def sketch(alias, plane, offset, shapes):
    return step('sketch', alias, name=alias, plane=plane, offset=offset, shapes=shapes)


def circle(x, y, r):
    return {'type': 'circle', 'cx': round(x, 4), 'cy': round(y, 4), 'r': r}


def point(x, y):
    return {'type': 'point', 'x': round(x, 4), 'y': round(y, 4)}


def poly(points):
    return {'type': 'polygon', 'points': [[round(x, 4), round(y, 4)] for x, y in points]}


def cl(x1, y1, x2, y2):
    return {'type': 'line', 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'construction': True}


def extrude(alias, src, distance, op='add'):
    return step('extrude', alias, name=alias, sketch='$' + src, distance=distance, op=op)


def outline(alias, offset):
    """泵体 / 前盖共用外形：Ø74 圆 + 出口凸台槽口。"""
    return [sketch(alias + '_disc', 'XY', offset, [circle(0, 0, BODY_R)]),
            sketch(alias + '_boss', 'XY', offset,
                   [{'type': 'slot', 'x1': 0, 'y1': 0, 'x2': BOSS[0], 'y2': BOSS[1], 'w': BOSS_W}])]


def volute_shapes():
    """蜗壳轮廓：隔舌 (≈4,-22) 起逆时针螺线 r 22→30 (一条样条)，接 +X 方向的出口槽，槽末端是 R4 半圆。"""
    pts = []
    for i in range(0, 36):
        t = -80 + 350 * i / 35          # 隔舌从 -80° 起，避免螺线在起点处跨过出口槽上壁
        r = VOLUTE_R0 + VOLUTE_GROW * (t + 90) / 360
        pts.append([round(r * math.cos(math.radians(t)), 4), round(r * math.sin(math.radians(t)), 4)])
    cx, cy = BOSS
    rr = CH_W / 2
    end, start = pts[-1], pts[0]
    return [{'type': 'spline', 'points': pts},
            {'type': 'line', 'x1': end[0], 'y1': end[1], 'x2': cx, 'y2': cy - rr},
            {'type': 'arc', 'cx': cx, 'cy': cy, 'r': rr, 'a0': -90, 'a1': 90},
            {'type': 'line', 'x1': cx, 'y1': cy + rr, 'x2': start[0], 'y2': start[1]}]


def nipple_profile(x0, z0):
    """软管接头 (内径 10 的抗静电软管)：外径 11，两道倒刺 Ø12，内孔另外切。"""
    prof = [(0, 0), (5.5, 0), (5.5, 4.5), (6.0, 4.5), (5.5, 7.5), (5.5, 8.5), (6.0, 8.5),
            (5.5, 11.5), (5.5, 13.5), (5.0, 14.0), (0, 14.0)]
    return [(x0 + r, z0 + z) for r, z in prof]


def d_bore(r=SHAFT_R, flat=1.0, angle=KEY):
    """D 型孔 / D 型轴截面：Ø3 圆在 angle 方向削平到 flat。"""
    a0 = math.degrees(math.acos(flat / r))
    pts = []
    for i in range(0, 41):
        a = a0 + (360 - 2 * a0) * i / 40
        pts.append((r * math.cos(math.radians(a)), r * math.sin(math.radians(a))))
    rot = math.radians(angle)
    return [(x * math.cos(rot) - y * math.sin(rot), x * math.sin(rot) + y * math.cos(rot)) for x, y in pts]


def flat_cut(flat=1.0, angle=KEY):
    rot = math.radians(angle)
    pts = [(flat, -3), (4, -3), (4, 3), (flat, 3)]
    return [(x * math.cos(rot) - y * math.sin(rot), x * math.sin(rot) + y * math.cos(rot)) for x, y in pts]


def tapped(alias, src, size, depth):
    if THREADS:
        return step('hole', alias, name=alias, sketch='$' + src, kind='tapped', size=size, depth=depth,
                    thread=True, phase=0)
    nominal = float(size[1:])
    return step('hole', alias, name=alias + f' ({size} 螺纹孔, 光孔示意)', sketch='$' + src, kind='simple',
                size='custom', diameter=nominal, depth=depth)


def radial_plane(alias):
    k = math.radians(KEY)
    return step('plane', alias, name=alias, offset=0, origin=[[0, 0, 9.5]], normal=[[math.cos(k), math.sin(k), 0]])


PARTS = {}


def part(filename, name, material, color=None):
    def wrap(fn):
        PARTS[filename] = (name, material, color, fn)
        return fn
    return wrap


@part('pump_body.gform', '泵体 | 6061 导电氧化, 蜗壳 + 电机座', '铝合金 6061', '#b8bec6')
def body():
    s = outline('body', 0)
    s += [extrude('body_disc_x', 'body_disc', CEIL), extrude('body_boss_x', 'body_boss', CEIL),
          sketch('volute', 'XY', CEIL, volute_shapes()),
          extrude('volute_cut', 'volute', -(CEIL - FLOOR), 'cut'),
          sketch('pilot', 'XY', 0, [circle(0, 0, 5.05)]),
          extrude('pilot_cut', 'pilot', 1.2, 'cut'),
          sketch('shaft_hole', 'XY', 0, [circle(0, 0, 2.1)]),
          extrude('shaft_hole_cut', 'shaft_hole', FLOOR, 'cut'),
          sketch('seal_pocket', 'XY', FLOOR, [circle(0, 0, 4.0)]),
          extrude('seal_pocket_cut', 'seal_pocket', -3.0, 'cut'),
          sketch('motor_holes', 'XY', FLOOR, [point(x, y) for x, y in MOTOR_SCREWS]),
          step('hole', 'motor_csk', name='motor_csk', sketch='$motor_holes', kind='countersink', size='M3', through=True),
          sketch('cover_holes', 'XY', CEIL, [point(x, y) for x, y in COVER_SCREWS]),
          tapped('cover_tap', 'cover_holes', 'M3', 8)]
    return s


@part('front_cover.gform', '前盖 | 6061 导电氧化, 进/出口接头', '铝合金 6061', '#c9ced4')
def cover():
    s = outline('cover', CEIL)
    s += [extrude('cover_disc_x', 'cover_disc', TOP - CEIL), extrude('cover_boss_x', 'cover_boss', TOP - CEIL),
          sketch('inlet_nipple', 'XZ', 0, [poly(nipple_profile(0, TOP)), cl(0, 0, 0, 40)]),
          step('revolve', 'inlet_nipple_x', name='inlet_nipple_x', sketch='$inlet_nipple', axis='CL', angle=360),
          sketch('outlet_nipple', 'XZ', -BOSS[1], [poly(nipple_profile(BOSS[0], TOP)), cl(BOSS[0], 0, BOSS[0], 40)]),
          step('revolve', 'outlet_nipple_x', name='outlet_nipple_x', sketch='$outlet_nipple', axis='CL', angle=360),
          sketch('inlet_bore', 'XY', TOP + 14, [circle(0, 0, 4.0)]),
          extrude('inlet_bore_cut', 'inlet_bore', -(14 + TOP - CEIL), 'cut'),
          sketch('eye', 'XZ', 0, [poly([(0, CEIL), (7.0, CEIL), (4.0, CEIL + 3.0), (0, CEIL + 3.0)]),
                                  cl(0, 0, 0, 40)]),
          step('revolve', 'eye_cut', name='eye_cut', sketch='$eye', axis='CL', angle=360, op='cut'),
          sketch('outlet_bore', 'XY', TOP + 14, [circle(BOSS[0], BOSS[1], 4.0)]),
          extrude('outlet_bore_cut', 'outlet_bore', -(14 + TOP - CEIL), 'cut'),
          sketch('cover_holes', 'XY', TOP, [point(x, y) for x, y in COVER_SCREWS]),
          step('hole', 'cover_csk', name='cover_csk', sketch='$cover_holes', kind='countersink', size='M3', through=True)]
    return s


@part('impeller.gform', '叶轮 | 7075, 6 片开式直叶 Ø40, G2.5 动平衡', '铝合金 7075', '#d8a24a')
def impeller():
    blade_len = IMP_R - 2.8
    return [sketch('disc', 'XY', IMP_Z0, [circle(0, 0, IMP_R)]),
            extrude('disc_x', 'disc', 1.5),
            sketch('hub', 'XZ', 0, [poly([(0, IMP_Z0 + 1.5), (3.0, IMP_Z0 + 1.5), (3.0, 13.0), (2.4, 15.6),
                                          (0, 16.6)]), cl(0, 0, 0, 40)]),
            step('revolve', 'hub_x', name='hub_x', sketch='$hub', axis='CL', angle=360),
            sketch('blade', 'XY', IMP_Z0 + 1.5, [{'type': 'rect', 'cx': 2.8 + blade_len / 2, 'cy': 0,
                                                  'w': blade_len, 'h': 1.5}]),
            extrude('blade_x', 'blade', CEIL - 0.5 - IMP_Z0 - 1.5),
            step('pattern_circular', 'blades', name='blades', features=['$blade_x'], axis='Z', count=6, angle=360),
            sketch('bore', 'XY', IMP_Z0, [poly(d_bore())]),
            extrude('bore_cut', 'bore', SHAFT_TOP + 0.1 - IMP_Z0, 'cut'),
            radial_plane('key_plane'),
            sketch('grub_hole', '$key_plane', 3.0, [point(0, 0)]),
            tapped('grub_tap', 'grub_hole', 'M2', 2.0)]


@part('grub_M2x2.gform', '紧定螺钉 M2×2 平端 (DIN 913)', '合金钢', '#30343a')
def grub():
    return [radial_plane('key_plane'),
            sketch('grub_pt', '$key_plane', 1.0, [point(0, 0)]),
            step('stud', 'grub', name='grub', sketch='$grub_pt', diameter=2.0, length=2.0, chamfer=0.2,
                 thread=THREADS, pitch=0.4, phase=0)]


@part('motor_bldc.gform', '无刷电机 Surpass KK2845 3800KV (Ø28×47, 3S)', '合金钢', '#3c4048')
def motor():
    return [sketch('can', 'XY', -CAN_LEN, [circle(0, 0, 14.0)]),
            extrude('can_x', 'can', CAN_LEN),
            step('chamfer', None, name='can_edges', edges='<Z', distance=1.0),
            sketch('shaft_bore', 'XY', 0, [circle(0, 0, SHAFT_R + 0.05)]),
            extrude('shaft_bore_cut', 'shaft_bore', -8.0, 'cut'),
            sketch('mount', 'XY', 0, [point(x, y) for x, y in MOTOR_SCREWS]),
            tapped('mount_tap', 'mount', 'M3', 4.5)]


@part('motor_shaft.gform', '电机轴 Ø3.175×15 (伸出), 磨 D 面 0.6 (随转子转)', '合金钢', '#8a9099')
def motor_shaft():
    return [sketch('shaft', 'XY', -6.8, [circle(0, 0, SHAFT_R)]),
            extrude('shaft_x', 'shaft', SHAFT_TOP + 6.8),
            sketch('dflat', 'XY', SHAFT_TOP, [poly(flat_cut())]),
            extrude('dflat_cut', 'dflat', -(SHAFT_TOP - IMP_Z0 + 0.1), 'cut')]


@part('lip_seal_3x8x3.gform', '骨架油封 3.175×8×3 (PTFE 唇, 防粉进电机)', '橡胶', '#20242a')
def seal():
    return [sketch('ring', 'XY', FLOOR - 3, [circle(0, 0, 4.0), circle(0, 0, SHAFT_R)]),
            extrude('ring_x', 'ring', 3.0)]


@part('screws_motor_M3x10_flat.gform', '沉头螺钉 M3×10 ×4 (电机安装, 拧进电机 4)', '不锈钢 304', '#9aa0a8')
def motor_screws():
    return [sketch('pts', 'XY', FLOOR, [point(x, y) for x, y in MOTOR_SCREWS]),
            step('screw', 's', name='s', sketch='$pts', size='M3', head='flat', length=10, thread=THREADS, phase=0)]


@part('screws_cover_M3x10_flat.gform', '沉头螺钉 M3×10 ×5 (前盖)', '不锈钢 304', '#9aa0a8')
def cover_screws():
    return [sketch('pts', 'XY', TOP, [point(x, y) for x, y in COVER_SCREWS]),
            step('screw', 's', name='s', sketch='$pts', size='M3', head='flat', length=10, thread=THREADS, phase=0)]


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
    spin = [order.index(f) for f in ('impeller.gform', 'grub_M2x2.gform', 'motor_shaft.gform')]
    joints = [{'name': '叶轮转动 (俯视逆时针)', 'kind': 'hinge', 'origin': [0, 0, 0], 'axis': [0, 0, 1],
               'parts': spin, 'base': order.index('pump_body.gform'), 'min': -360, 'max': 360, 'speed': 360}]
    doc = {'format': 'genform-assembly', 'version': 1, 'parts': parts, 'joints': joints}
    (OUTPUT / 'powder_pump.gasm').write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print('saved powder_pump.gasm')


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
