from __future__ import annotations

import json

from mcp_client import Client, OUTPUT, feature, profile


def line_sections(steps, name, points, across):
    references = []
    for index, point in enumerate(points):
        station, width, height = point
        alias = name + '_' + str(index)
        if across == 'yz':
            shape = {'type': 'rect', 'cx': width - 1.8, 'cy': height, 'w': 6.4, 'h': 3.0}
            plane, offset = 'YZ', station
        else:
            shape = {'type': 'rect', 'cx': station, 'cy': height, 'w': 3.0, 'h': 4.5}
            plane, offset = 'XZ', -width
        steps.append(profile(alias, '911_' + alias, plane, offset, [shape]))
        references.append('$' + alias)
    steps.append(feature('loft', name, name='911_' + name, sketches=references, ruled=False))


def make(client):
    data = json.loads((OUTPUT / 'trim_samples.json').read_text(encoding='utf-8'))
    steps, colors = [], {}
    door = data['door']
    paths = {'door_front_seam': sorted(door[0:5], key=lambda point: point[2]),
             'door_sill_seam': door[4:9],
             'door_rear_seam': door[8:12]}
    for name, points in paths.items():
        if name.endswith('sill_seam'):
            line_sections(steps, name, points, 'yz')
        else:
            references = []
            for index, (station, width, height) in enumerate(points):
                alias = name + '_' + str(index)
                steps.append(profile(alias, '911_' + alias, 'XY', height, [
                    {'type': 'rect', 'cx': station, 'cy': width - 1.8, 'w': 3.0, 'h': 6.4}]))
                references.append('$' + alias)
            steps.append(feature('loft', name, name='911_' + name, sketches=references, ruled=False))
        colors[name] = '#34414C'
        steps.append(feature('mirror', name + '_left', name='911_' + name + '_left', plane='XZ', features=['$' + name]))
        colors[name + '_left'] = '#34414C'
    bonnet = data['bonnet']
    right = sorted([point for point in bonnet if point[1] >= 250], key=lambda point: point[0])
    references = []
    for index, (station, width, height) in enumerate(right):
        alias = 'bonnet_edge_' + str(index)
        steps.append(profile(alias, '911_' + alias, 'YZ', station, [
            {'type': 'rect', 'cx': width, 'cy': height - 1.8, 'w': 3.0, 'h': 6.4}]))
        references.append('$' + alias)
    steps.append(feature('loft', 'bonnet_seam', name='911_bonnet_edge_seam', sketches=references))
    steps.append(feature('mirror', 'bonnet_seam_left', name='911_bonnet_edge_seam_left', plane='XZ', features=['$bonnet_seam']))
    colors.update(bonnet_seam='#34414C', bonnet_seam_left='#34414C')
    return client.stage('safe_panel_lines', steps, colors)


if __name__ == '__main__':
    with Client() as client:
        make(client)
