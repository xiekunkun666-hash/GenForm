from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_client import Client, DOCUMENT, OUTPUT, extrude, feature, profile


def sample():
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from genform.kernel import build

    features = json.loads(DOCUMENT.read_text(encoding='utf-8'))['features']
    stop = next(index + 1 for index, item in enumerate(features) if item['id'] == 'f37')
    body, _, status = build.rebuild(features[:stop])
    assert all(value == 'ok' for value in status.values())

    def hit(station, cross, vertical, offset=1.2):
        origin = (station, cross, 2000) if vertical else (station, 1400, cross)
        direction = (0, 0, -1) if vertical else (0, -1, 0)
        probe = BRepIntCurveSurface_Inter()
        probe.Init(body, gp_Lin(gp_Pnt(*origin), gp_Dir(*direction)), 1e-7)
        found = []
        while probe.More():
            point = probe.Pnt()
            found.append(point.Z() if vertical else point.Y())
            probe.Next()
        assert found, (station, cross, vertical)
        value = max(found) + offset
        return [station, cross, value] if vertical else [station, value, cross]

    door = [(-748, 845), (-781, 720), (-787, 530), (-775, 340), (-690, 238),
            (-380, 220), (25, 220), (335, 238), (473, 330), (495, 550),
            (492, 750), (485, 869), (150, 856), (-240, 848)]
    bonnet = [(-2025, 0), (-1980, -270), (-1810, -408), (-1460, -465), (-1090, -505),
              (-925, -487), (-902, -250), (-900, 0), (-902, 250), (-925, 487),
              (-1090, 505), (-1460, 465), (-1810, 408), (-1980, 270)]
    data = {'door': [hit(station, height, False) for station, height in door],
            'bonnet': [hit(station, width, True) for station, width in bonnet],
            'handle': hit(350, 757, False, 3),
            'fuel': hit(-1100, 750, False, 2),
            'vent': []}
    for station in np.linspace(1480, 1780, 11):
        data['vent'].append([hit(float(station), width, True, 2.5) for width in (-480, 0, 480)])
    (OUTPUT / 'trim_samples.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    print('Sampled door, bonnet, fuel cap and engine cover', flush=True)


def seams(client):
    data = json.loads((OUTPUT / 'trim_samples.json').read_text(encoding='utf-8'))
    steps, colors = [], {}
    for key in ('door', 'bonnet'):
        points = data[key]
        tangent = (np.array(points[1]) - points[-1]).tolist()
        steps += [feature('sketch3d', key + '_path', name='911_' + key + '_panel_gap_path',
                          points=points, closed=True, kind='spline'),
                  feature('plane', key + '_plane', name='911_' + key + '_gap_profile_datum',
                          origin=[points[0]], normal=[tangent]),
                  profile(key + '_profile', '911_' + key + '_gap_section', '$' + key + '_plane', 0,
                          [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 2.0}]),
                  feature('sweep', key, name='911_' + key + '_panel_gap',
                          sketch='$' + key + '_profile', path='$' + key + '_path')]
        colors[key] = '#303C47'
        if key == 'door':
            steps.append(feature('mirror', 'door_left', name='911_door_panel_gap_left', plane='XZ', features=['$door']))
            colors['door_left'] = '#303C47'
    return client.stage('panel_seams', steps, colors)


def handles(client):
    data = json.loads((OUTPUT / 'trim_samples.json').read_text(encoding='utf-8'))
    station, width, height = data['handle']
    steps = []
    for side, sign in (('left', -1), ('right', 1)):
        source = side + '_handle_profile'
        steps += [profile(source, '911_' + source, 'XZ', -sign * width, [
            {'type': 'slot', 'x1': station - 60, 'y1': height, 'x2': station + 60, 'y2': height, 'w': 21}]),
            extrude('handle_' + side, '911_flush_door_handle_' + side, source, sign * 10)]
    station, width, height = data['fuel']
    steps += [feature('plane', 'fuel_plane', name='911_fuel_cap_datum', origin=[[station, width, height]], normal=[[0, 0.75, 0.66]]),
              profile('fuel_profile', '911_fuel_cap_profile', '$fuel_plane', 0, [
                  {'type': 'circle', 'cx': 0, 'cy': 0, 'r': 66},
                  {'type': 'circle', 'cx': 0, 'cy': 0, 'r': 63.5}]),
              extrude('fuel', '911_fuel_filler_outline', 'fuel_profile', -8)]
    return client.stage('handles_fuel_cap', steps, {'handle_left': '#748694', 'handle_right': '#748694', 'fuel': '#34414D'})


def vents(client):
    data = json.loads((OUTPUT / 'trim_samples.json').read_text(encoding='utf-8'))
    steps, references = [], []
    for index in (0, 3, 6, 10):
        row = data['vent'][index]
        outer = [[value[1], value[2]] for value in row]
        inner = [[value[1], value[2] - 8] for value in row]
        shapes = [{'type': 'spline', 'points': outer},
                  {'type': 'line', 'x1': outer[-1][0], 'y1': outer[-1][1], 'x2': inner[-1][0], 'y2': inner[-1][1]},
                  {'type': 'spline', 'points': inner[::-1]},
                  {'type': 'line', 'x1': inner[0][0], 'y1': inner[0][1], 'x2': outer[0][0], 'y2': outer[0][1]}]
        alias = 'vent_section_' + str(index)
        steps.append(profile(alias, '911_' + alias, 'YZ', row[0][0], shapes))
        references.append('$' + alias)
    steps.append(feature('loft', 'vent_panel', name='911_engine_cover_black_grille', sketches=references))
    for index, row in enumerate(data['vent'][1:-1]):
        alias = 'louvre_profile_' + str(index)
        points = [[value[1], value[2] + 3] for value in row]
        centre = points[1][1]
        shapes = [{'type': 'polygon', 'points': [[-470, points[0][1]], [0, centre], [470, points[2][1]],
                                                  [470, points[2][1] - 5], [0, centre - 5], [-470, points[0][1] - 5]]}]
        steps += [profile(alias, '911_' + alias, 'YZ', row[0][0], shapes),
                  extrude('louvre_' + str(index), '911_engine_grille_louvre_' + str(index), alias, 8)]
    colors = {'vent_panel': '#121A22'}
    colors.update({'louvre_' + str(index): '#48545F' for index in range(9)})
    return client.stage('engine_cover', steps, colors)


def badges(client):
    steps = [profile('rear_letters', '911_rear_porsche_lettering_profile', 'YZ', 2269, [
        {'type': 'text', 'x': -265, 'y': 579, 'text': 'P O R S C H E', 'height': 57, 'font': 'Arial'}]),
        extrude('letters', '911_rear_porsche_lettering', 'rear_letters', -2.2),
        profile('carrera_script', '911_carrera_script_profile', 'YZ', 2266, [
            {'type': 'text', 'x': -99, 'y': 504, 'text': 'Carrera', 'height': 45, 'font': 'Segoe Script'}]),
        extrude('carrera', '911_carrera_rear_badge', 'carrera_script', -2),
        profile('plate_profile', '911_rear_plate_profile', 'YZ', 2268, [
            {'type': 'rect', 'cx': 0, 'cy': 389, 'w': 440, 'h': 95}]),
        extrude('plate', '911_rear_registration_plate', 'plate_profile', -4),
        profile('plate_letters', '911_rear_plate_letters_profile', 'YZ', 2270, [
            {'type': 'text', 'x': -139, 'y': 365, 'text': '911  CARRERA', 'height': 41, 'font': 'Arial'}]),
        extrude('plate_text', '911_rear_registration_text', 'plate_letters', -1)]
    return client.stage('rear_badges', steps, {'letters': '#CBD2D7', 'carrera': '#BBC8D1',
                                            'plate': '#BEC6CC', 'plate_text': '#18232C'})


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'sample':
        sample()
    else:
        with Client() as client:
            {'seams': seams, 'handles': handles, 'vents': vents, 'badges': badges}[mode](client)
