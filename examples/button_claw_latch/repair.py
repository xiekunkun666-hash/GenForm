from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from build import Client, OUTPUT, rectangle


PATCHES = {
    'frame': {'link_sweep_relief': {'shapes': [{'type': 'slot', 'x1': -34.5, 'y1': 5.5,
                                              'x2': -34.5, 'y2': 14.5, 'w': 3}]},
              'rivet_head_relief': {'shapes': [{'type': 'slot', 'x1': -33.5, 'y1': 7,
                                              'x2': -33.5, 'y2': 13, 'w': 2}]}},
    'pushrod': {'slider_shaft': {'shapes': [rectangle(-42.25, 10, 36.5, 6)]}},
    'door_striker': {'striker_pin': {'offset': 5.5}, 'six_mm_striker': {'distance': 10.5},
                     'striker_head': {'offset': 15.5}, 'striker_retention_head': {'distance': 2}},
    'link_rivet': {'rivet_shank': {'offset': 7.5}, 'three_mm_joint_pin': {'distance': 8}},
}


def check(client, path):
    report = client.call('check_design')
    target = OUTPUT / f'part_check_{path.stem}.json'
    if target.exists() and not target.with_name(target.stem + '_before.json').exists():
        target.with_name(target.stem + '_before.json').write_bytes(target.read_bytes())
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'part': path.name, 'counts': report['counts'], 'issues': [
        {'level': row['level'], 'code': row['code'], 'title': row['title']}
        for row in report['issues'] if row['level'] != 'info']}, ensure_ascii=True), flush=True)
    if report['counts'].get('error'):
        raise RuntimeError(f'Native part check failed: {path.name}')


def repair(client, name):
    path = OUTPUT / f'{name}.gform'
    stored = json.loads(path.read_text(encoding='utf-8'))
    current = client.call('get_model', brief=True)
    if current.get('unsaved_changes'):
        raise RuntimeError('Save the current document before repairing another part')
    client.call('open_document', path=str(path))
    model = client.call('get_model')
    by_name = {row['name']: row for row in model['features']}
    steps = []
    for feature_name, params in PATCHES[name].items():
        feature = by_name[feature_name]
        if any(feature['params'].get(key) != value for key, value in params.items()):
            steps.append({'cmd': 'edit_feature', 'args': {'id': feature['id'], 'params': copy.deepcopy(params)}})
    if steps:
        client.call('batch', steps=steps)
        client.call('save_document', path=str(path))
        saved = json.loads(path.read_text(encoding='utf-8'))
        for before, after in zip(stored['features'], saved['features']):
            if before.get('process') != after.get('process'):
                raise RuntimeError(f'Process metadata changed: {name}/{before["id"]}')
    check(client, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('part', choices=(*PATCHES, 'check_all'))
    args = parser.parse_args()
    with Client() as client:
        if args.part == 'check_all':
            current = client.call('get_model', brief=True)
            if current.get('unsaved_changes'):
                raise RuntimeError('Unsaved document; refusing to replace it')
            for path in sorted(OUTPUT.glob('*.gform')):
                client.call('open_document', path=str(path))
                check(client, path)
        else:
            repair(client, args.part)


if __name__ == '__main__':
    main()
