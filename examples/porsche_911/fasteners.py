from __future__ import annotations

import math

from mcp_client import Client, extrude, feature, profile


def make(client):
    steps, colors = [], {}
    for axle in ('front', 'rear'):
        for side in ('left', 'right'):
            front = axle == 'front'
            station, height, width, half = (-1290, 340, 773, 122.5) if front else (1160, 358, 755, 152.5)
            sign = -1 if side == 'left' else 1
            face = sign * (width + half - 12)
            name = f'911_{axle}_{side}'
            bolts = []
            washers = []
            for index in range(5):
                angle = math.radians(index * 72 + 18)
                horizontal, vertical = station + 65 * math.cos(angle), height + 65 * math.sin(angle)
                bolts.append({'type': 'circle', 'cx': horizontal, 'cy': vertical, 'r': 7})
                washers += [{'type': 'circle', 'cx': horizontal, 'cy': vertical, 'r': 11.5},
                            {'type': 'ngon', 'cx': horizontal, 'cy': vertical, 'r': 9.9, 'sides': 6, 'angle': 30}]
            source = name + '_M14_shank_profile'
            steps += [profile(source, source, 'XZ', -(face + sign * 4), bolts),
                      extrude(name + '_shanks', name + '_five_M14_bolt_shanks', source, sign * 40)]
            source = name + '_bolt_seats_profile'
            steps += [profile(source, source, 'XZ', -(face + sign * 5.5), washers),
                      extrude(name + '_seats', name + '_five_bolt_head_seats', source, sign * 1.0)]
            source = name + '_crest_profile'
            crest = [[station - 13, height + 18], [station + 13, height + 18],
                     [station + 11, height - 9], [station, height - 21], [station - 11, height - 9]]
            steps += [profile(source, source, 'XZ', -(face + sign * 10.3), [{'type': 'polygon', 'points': crest}]),
                      extrude(name + '_crest', name + '_hub_crest', source, sign * 1)]
            colors.update({name + '_shanks': '#7E8994', name + '_seats': '#48535F', name + '_crest': '#BD9B4B'})
    steps += [feature('plane', 'plate_fastener_plane', name='911_plate_fastener_datum',
                      origin=[[2270, 0, 389]], normal=[[1, 0, 0]], offset=0),
              profile('plate_screw_positions', '911_plate_M4_screw_positions', '$plate_fastener_plane', 0,
                      [{'type': 'point', 'x': width, 'y': height} for width in (-182, 182) for height in (-29, 29)]),
              feature('screw', 'plate_screws', name='911_four_plate_M4_socket_screws', sketch='$plate_screw_positions',
                      size='M4', head='button', length=12)]
    colors['plate_screws'] = '#84939E'
    return client.stage('visible_fasteners', steps, colors)


if __name__ == '__main__':
    with Client() as client:
        make(client)
