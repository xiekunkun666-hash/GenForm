from __future__ import annotations

import json
import math
import sys

from mcp_client import Client, DOCUMENT, OUTPUT, feature


def request_edits(client, mode, collect=False):
    state = client.call('get_model')
    steps = []
    for item in state['features']:
        params, name = item['params'], item['name']
        if mode == 'tires' and name.endswith('_tire_section'):
            front = '_front_' in name
            centre_x, centre_y, radius, rim, half = (-1290, 773, 340, 254, 122.5) if front else (1160, 755, 358, 267, 152.5)
            sign = -1 if '_left_' in name else 1
            centre_y *= sign
            points = [(rim - 2, -half + 22), (rim + 12, -half), (radius - 38, -half),
                      (radius - 10, -half + 12), (radius, -half + 36),
                      (radius, half - 36), (radius - 10, half - 12),
                      (radius - 38, half), (rim + 12, half), (rim - 2, half - 22)]
            world = [[centre_x + radial, centre_y + width] for radial, width in points]
            shapes = [{'type': 'polygon', 'points': world}]
            steps.append(feature('edit_feature', name, id=item['id'], params={'shapes': shapes}))
        if mode == 'wheels' and name.endswith('_disc_profile'):
            circle = dict(params['shapes'][0], r=175)
            steps.append(feature('edit_feature', name, id=item['id'], params={'shapes': [circle]}))
        if mode == 'wheels' and name.endswith('_brake_disc'):
            distance = params['distance']
            thickness = 34 if '_front_' in name else 28
            steps.append(feature('edit_feature', name, id=item['id'], params={'distance': math.copysign(thickness, distance)}))
        if mode == 'wheels' and name.endswith('_cap_profile'):
            shapes = [params['shapes'][0]]
            centre_x, centre_z = shapes[0]['cx'], shapes[0]['cy']
            for index in range(5):
                angle = math.radians(index * 72 + 18)
                shapes.append({'type': 'ngon', 'cx': centre_x + 65 * math.cos(angle),
                               'cy': centre_z + 65 * math.sin(angle), 'r': 9.815, 'sides': 6, 'angle': 30})
            steps.append(feature('edit_feature', name, id=item['id'], params={'shapes': shapes}))
    if not steps:
        raise RuntimeError('No matching features')
    if collect:
        return steps
    print(f'START refine {mode}: {len(steps)} parameter edits', flush=True)
    result = client.call('batch', steps=steps)
    client.call('save_document', path=str(DOCUMENT))
    print(json.dumps({'mode': mode, 'body': result['model'].get('body')}, ensure_ascii=False), flush=True)


def glazing(client, collect=False):
    samples = json.loads((OUTPUT / 'surface_samples.json').read_text(encoding='utf-8'))
    state = client.call('get_model')
    features = {item['name']: item for item in state['features']}
    from glazing import shell_shapes
    steps = []
    for key, rows in samples.items():
        screen = key in ('windshield', 'rear_screen')
        for index, row in enumerate(rows):
            values = row['values']
            dimension = 0 if screen else 1
            low, high = values[0][dimension], values[-1][dimension]
            inset = min(20, (high - low) * 0.16)
            samples_at = [low + inset + (high - low - inset * 2) * number / 8 for number in range(9)]
            independent = [point[dimension] for point in values]
            dependent = [point[1 - dimension] for point in values]
            import numpy as np
            interpolated = np.interp(samples_at, independent, dependent)
            points = [[cross, float(height)] if screen else [float(height), cross]
                      for cross, height in zip(samples_at, interpolated)]
            outer = [[point[0], point[1] + 7] if screen else [point[0] + 7, point[1]] for point in points]
            inner = [[point[0], point[1] - 9] if screen else [point[0] - 9, point[1]] for point in points]
            name = f'911_{key}_glass_{index}'
            steps.append(feature('edit_feature', name, id=features[name]['id'], params={'shapes': shell_shapes(outer, inner)}))
    if collect:
        return steps
    print(f'START refine glazing: {len(steps)} parameter edits', flush=True)
    result = client.call('batch', steps=steps)
    client.call('save_document', path=str(DOCUMENT))
    print(json.dumps({'mode': 'glazing', 'body': result['model'].get('body')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    with Client() as client:
        if sys.argv[1] == 'all':
            steps = request_edits(client, 'tires', True) + request_edits(client, 'wheels', True) + glazing(client, True)
            print(f'START combined refinement: {len(steps)} edits', flush=True)
            result = client.call('batch', steps=steps)
            client.call('save_document', path=str(DOCUMENT))
            print(json.dumps({'refined': True, 'body': result['model'].get('body')}), flush=True)
        elif sys.argv[1] == 'glazing':
            glazing(client)
        else:
            request_edits(client, sys.argv[1])
