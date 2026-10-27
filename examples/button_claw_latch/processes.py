from __future__ import annotations

import json

from build import Client, OUTPUT, circle, extrusion, rectangle, sketch


def main():
    proposals = {
        'frame.gform': ('cnc3', '概念样机：底板、导向块和支柱的等效整体件；需拆件后出加工图'),
        'cover.gform': ('laser', '2 mm检修上盖，孔位按模型'),
        'door_striker.gform': ('millturn', '演示门板与扣销等效件；实际需独立扣销安装图'),
        'rotary_claw.gform': ('laser', '4 mm锁爪坯，转轴孔需后续精加工'),
        'pushrod.gform': ('millturn', '矩形推杆、按钮与轴肩等效整体件'),
        'connecting_link.gform': ('laser', '3 mm传动连杆，中心距24 mm'),
        'pivot_dowel.gform': ('turning', '直径4 长15 主转轴，按模型配合确认'),
        'link_rivet.gform': ('turning', '直径3阶梯铆钉，两端铆成头；装配工序未仿真'),
        'spring_seat.gform': ('laser', '0.5 mm弹簧支承垫圈'),
        'cover_bolt.gform': ('standard', 'M3x25盘头内六角，螺纹仅包络；供应商报价待定'),
        'cover_nut.gform': ('standard', 'M3六角螺母，螺纹仅包络；供应商报价待定'),
    }
    client = Client()
    try:
        client.call('open_document', path=str(OUTPUT / 'frame.gform'))
        current = client.call('get_model', brief=True)
        if not any(row['name'] == 'rivet_head_relief' for row in current['features']):
            client.call('batch', steps=[sketch('rivet_head_relief', 'XY', 6.5, [rectangle(-33.5, 10, 1, 6)]),
                                       extrusion('guide_front_clearance', 'rivet_head_relief', 11.6, 'cut')])
            client.call('save_document', path=str(OUTPUT / 'frame.gform'))
        for path in sorted(OUTPUT.glob('*.gform')):
            process, specification = proposals.get(path.name, ('purchase', '压缩弹簧按几何定制；刚度、预压、材料和报价待定'))
            client.call('open_document', path=str(path))
            model = client.call('get_model', brief=True)
            steps = [{'cmd': 'set_process', 'args': {'feature': row['id'], 'process': process, 'spec': specification}}
                     for row in model['features'] if row['type'] in ('extrude', 'sweep', 'screw')]
            client.call('batch', steps=steps)
            client.call('save_document', path=str(path))
            print(json.dumps({'part': path.name, 'proposed_process': process, 'price': 'not provided'}, ensure_ascii=True), flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
