from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_client import Client, DOCUMENT, OUTPUT, feature, profile


def shell_shapes(outer, inner):
    return [{'type': 'spline', 'points': outer},
            {'type': 'line', 'x1': outer[-1][0], 'y1': outer[-1][1], 'x2': inner[-1][0], 'y2': inner[-1][1]},
            {'type': 'spline', 'points': inner[::-1]},
            {'type': 'line', 'x1': inner[0][0], 'y1': inner[0][1], 'x2': outer[0][0], 'y2': outer[0][1]}]


def sample():
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from genform.kernel import build

    document = json.loads(DOCUMENT.read_text(encoding='utf-8'))
    features = document['features']
    end = next(index + 1 for index, item in enumerate(features) if item['id'] == 'f37')
    body, _, status = build.rebuild(features[:end])
    assert all(value == 'ok' for value in status.values()), status

    def hit(station, cross, vertical):
        origin = (station, cross, 2000) if vertical else (station, 1400, cross)
        direction = (0, 0, -1) if vertical else (0, -1, 0)
        intersector = BRepIntCurveSurface_Inter()
        intersector.Init(body, gp_Lin(gp_Pnt(*origin), gp_Dir(*direction)), 1e-7)
        coordinates = []
        while intersector.More():
            point = intersector.Pnt()
            coordinates.append(point.Z() if vertical else point.Y())
            intersector.Next()
        if not coordinates:
            raise RuntimeError(f'No body surface at {station}, {cross}, vertical={vertical}')
        return max(coordinates)

    result = {}
    screens = {
        'windshield': [(-815, 565), (-745, 560), (-650, 551), (-540, 535), (-430, 516), (-330, 496), (-245, 480)],
        'rear_screen': [(720, 482), (820, 507), (940, 536), (1060, 554), (1180, 572), (1300, 574), (1380, 558)]}
    for name, stations in screens.items():
        result[name] = []
        for station, width in stations:
            values = [[round(value, 5), round(hit(station, value, True), 5)]
                      for value in np.linspace(-width, width, 9)]
            result[name].append({'station': station, 'values': values})
    side_stations = {
        'door_window': [(-650, 865, 885), (-540, 864, 997), (-390, 865, 1096),
                        (-220, 869, 1172), (0, 876, 1210), (235, 883, 1209), (460, 891, 1192)],
        'quarter_window': [(535, 894, 1172), (665, 897, 1122), (820, 900, 1046),
                           (960, 900, 967), (1070, 900, 910)]}
    for name, stations in side_stations.items():
        result[name] = []
        for station, low, high in stations:
            values = [[round(hit(station, value, False), 5), round(value, 5)]
                      for value in np.linspace(low, high, 9)]
            result[name].append({'station': station, 'values': values})
    destination = OUTPUT / 'surface_samples.json'
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f'Sampled {sum(len(rows) for rows in result.values())} body stations: {destination}', flush=True)


def make(client, name):
    data = json.loads((OUTPUT / 'surface_samples.json').read_text(encoding='utf-8'))[name]
    screen = name in ('windshield', 'rear_screen')
    steps, colors = [], {}
    for layer, height, inset in (('frame', 4.0, 0), ('glass', 7.0, 20)):
        references = []
        for index, row in enumerate(data):
            values = row['values']
            if inset:
                values = values[1:-1]
            outer = [[value[0], value[1] + height] if screen else [value[0] + height, value[1]] for value in values]
            inner = [[value[0], value[1] - 9] if screen else [value[0] - 9, value[1]] for value in values]
            alias = f'{name}_{layer}_{index}'
            station = row['station']
            if inset and index in (0, len(data) - 1):
                station += inset if index == 0 else -inset
            steps.append(profile(alias, '911_' + alias, 'YZ', station, shell_shapes(outer, inner)))
            references.append('$' + alias)
        alias = name + '_' + layer
        steps.append(feature('loft', alias, name='911_' + alias, sketches=references, ruled=False))
        colors[alias] = '#141B23' if layer == 'frame' else '#263F50'
        if not screen:
            mirrored = alias + '_left'
            steps.append(feature('mirror', mirrored, name='911_' + mirrored, plane='XZ', features=['$' + alias]))
            colors[mirrored] = colors[alias]
    return client.stage('glazing_' + name, steps, colors)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: glazing.py sample|windshield|rear_screen|door_window|quarter_window')
    if sys.argv[1] == 'sample':
        sample()
    else:
        with Client() as client:
            make(client, sys.argv[1])
