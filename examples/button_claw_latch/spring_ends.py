from __future__ import annotations

import argparse
import json

from build import Client, OUTPUT, circle, configuration, extrusion, feature, sketch
from repair import check


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('angles', nargs='+', type=int, choices=(0, 10, 20, 30, 40))
    arguments = parser.parse_args()
    with Client() as client:
        current = client.call('get_model', brief=True)
        if current.get('unsaved_changes'):
            raise RuntimeError('Save current document before modifying springs')
        for angle in arguments.angles:
            path = OUTPUT / f'spring_{angle:02d}.gform'
            client.call('open_document', path=str(path))
            model = client.call('get_model', brief=True)
            if not any(row['name'] == 'rear_ground_seat' for row in model['features']):
                rear = -42 + configuration(angle)['shift']
                front = -35.5
                result = client.call('batch', steps=[
                    sketch('rear_closed_end', 'YZ', rear + 0.5, [circle(10, 10, 5.25), circle(10, 10, 4.15)]),
                    extrusion('rear_ground_seat', 'rear_closed_end', 1),
                    sketch('front_closed_end', 'YZ', front - 1.5, [circle(10, 10, 5.25), circle(10, 10, 4.15)]),
                    extrusion('front_ground_seat', 'front_closed_end', 1)])
                print(json.dumps({'spring_angle': angle, 'body': result['model']['body']}, ensure_ascii=True), flush=True)
            model = client.call('get_model', brief=True)
            specification = '定制压簧几何包络：线径1、平均径9.4、四圈及闭口磨平端；弹力与寿命未校核，报价待定'
            steps = [feature('set_process', 'spring_process_' + row['id'], feature=row['id'],
                             process='purchase', spec=specification)
                     for row in model['features'] if row['type'] in ('extrude', 'sweep', 'curve_helix')]
            client.call('batch', steps=steps)
            client.call('save_document', path=str(path))
            check(client, path)


if __name__ == '__main__':
    main()
