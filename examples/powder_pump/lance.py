"""吸料枪 (给抽粉泵进口用)：插进料桶的粉里，内管走粉 + 气，内外管之间的环隙从枪头补进空气，
粉一直是"粉 + 空气"的混合流，不会把软管吸成一根实心粉柱堵死。上面的调节环转一下改变补气孔开度，调粉气比。

坐标：Z 朝上，外管下端 (枪尖) z=0；内管比外管缩进 5 mm；枪头 z195–235，软管接头 z235–249 (接 ID10 软管到泵进口)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'examples' / 'porsche_911'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_client import Client
from build import step, sketch, circle, point, poly, cl, extrude, nipple_profile

OUTPUT = ROOT / 'models' / 'powder_pump'

SLEEVE_TOP, HEAD_Z0, HEAD_TOP = 205.0, 195.0, 235.0
AIR_Z = 210.0                  # 补气孔高度
TIP_RECESS = 5.0


def ring(alias, z, r_out, r_in, h):
    return [sketch(alias, 'XY', z, [circle(0, 0, r_out), circle(0, 0, r_in)]), extrude(alias + '_x', alias, h)]


def radial_holes(alias, z, d, r_start):
    """X、Y 两个方向各一个对穿孔 = 4 个径向孔 (0/90/180/270°)。"""
    rows = []
    for k, n in (('x', [1, 0, 0]), ('y', [0, 1, 0])):
        rows += [step('plane', f'{alias}_p{k}', name=f'{alias}_p{k}', offset=0, origin=[[0, 0, z]], normal=[n]),
                 sketch(f'{alias}_s{k}', f'${alias}_p{k}', r_start, [point(0, 0)]),
                 step('hole', f'{alias}_{k}', name=f'{alias}_{k}', sketch=f'${alias}_s{k}', kind='simple',
                      size='custom', diameter=d, through=True)]
    return rows


PARTS = {}


def part(filename, name, material, color=None):
    def wrap(fn):
        PARTS[filename] = (name, material, color, fn)
        return fn
    return wrap


@part('lance_inner_tube.gform', '吸料枪内管 Ø12×1 (304 不锈钢管), 走粉', '不锈钢 304', '#b9bec4')
def inner_tube():
    return ring('tube', TIP_RECESS, 6.0, 5.0, HEAD_TOP - 5 - TIP_RECESS)        # 顶端插到枪头 z230


@part('lance_outer_sleeve.gform', '吸料枪外管 Ø20×2 (304 不锈钢管), 补气环隙', '不锈钢 304', '#9da3aa')
def outer_sleeve():
    return ring('sleeve', 0, 10.0, 8.0, SLEEVE_TOP)


@part('lance_spacer.gform', '内管定位撑 (PTFE, 3 爪, 留补气通道)', '聚丙烯 PP', '#f2f2ec')
def spacer():
    rows = ring('ring', 20, 8.0, 6.0, 6)
    rows += [sketch('gap', 'XY', 26, [poly([(0, 0), (10.39, 6.0), (10.39, -6.0)])]),
             extrude('gap_cut', 'gap', -6, 'cut'),
             step('pattern_circular', 'gaps', name='gaps', features=['$gap_cut'], axis='Z', count=3, angle=360)]
    return rows


@part('lance_head.gform', '吸料枪头 | 6061 车削, 补气腔 + 软管接头', '铝合金 6061', '#c9ced4')
def head():
    return [sketch('shoulder', 'XY', HEAD_Z0, [circle(0, 0, 18)]),
            extrude('shoulder_x', 'shoulder', 10),
            sketch('body', 'XY', HEAD_Z0 + 10, [circle(0, 0, 15)]),
            extrude('body_x', 'body', HEAD_TOP - HEAD_Z0 - 10),
            sketch('nipple', 'XZ', 0, [poly(nipple_profile(0, HEAD_TOP)), cl(0, 0, 0, 400)]),
            step('revolve', 'nipple_x', name='nipple_x', sketch='$nipple', axis='CL', angle=360),
            sketch('socket', 'XY', HEAD_Z0, [circle(0, 0, 10)]),                # 外管插口
            extrude('socket_cut', 'socket', SLEEVE_TOP - HEAD_Z0, 'cut'),
            sketch('air', 'XY', SLEEVE_TOP, [circle(0, 0, 10)]),                # 补气腔 → 通环隙
            extrude('air_cut', 'air', 10, 'cut'),
            sketch('tube_bore', 'XY', SLEEVE_TOP + 10, [circle(0, 0, 6)]),      # 内管插口
            extrude('tube_bore_cut', 'tube_bore', HEAD_TOP - 5 - SLEEVE_TOP - 10, 'cut'),
            sketch('flow', 'XY', HEAD_TOP + 14, [circle(0, 0, 4)]),
            extrude('flow_cut', 'flow', -(14 + 5), 'cut'),
            sketch('clip_groove', 'XZ', 0, [{'type': 'rect', 'cx': 14.75, 'cy': 215.5, 'w': 0.5, 'h': 1.0},
                                            cl(0, 0, 0, 400)]),
            step('revolve', 'clip_groove_cut', name='clip_groove_cut', sketch='$clip_groove', axis='CL', angle=360,
                 op='cut')] + radial_holes('air_hole', AIR_Z, 4.0, 20)


@part('lance_air_collar.gform', '补气调节环 | 6061, 转 45° 关闭补气孔', '铝合金 6061', '#d8a24a')
def collar():
    rows = ring('collar', HEAD_Z0 + 10, 18.0, 15.0, 10)
    rows += [step('fillet', None, name='knurl_edge', edges='>Z', radius=0.5)]
    return rows + radial_holes('collar_hole', AIR_Z, 5.0, 20)


@part('lance_circlip.gform', '轴用挡圈 Ø30 (GB/T 894, 挡住调节环)', '合金钢', '#30343a')
def circlip():
    return ring('clip', 215.0, 17.0, 14.5, 1.0)


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
    joints = [{'name': '补气调节环 (0 = 全开, 45° = 全关)', 'kind': 'hinge', 'origin': [0, 0, 0], 'axis': [0, 0, 1],
               'parts': [order.index('lance_air_collar.gform')], 'base': order.index('lance_head.gform'),
               'min': 0, 'max': 45}]
    doc = {'format': 'genform-assembly', 'version': 1, 'parts': parts, 'joints': joints}
    (OUTPUT / 'suction_lance.gasm').write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print('saved suction_lance.gasm')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('parts', nargs='*')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    client = Client()
    try:
        for f in a.parts or list(PARTS):
            build(client, f, a.force)
    finally:
        client.close()
    assembly()


if __name__ == '__main__':
    main()
