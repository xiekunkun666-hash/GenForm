from __future__ import annotations

import math
import sys

from mcp_client import Client, extrude, feature, profile


def polar(center, radius, angle):
    radians = math.radians(angle)
    return [round(center[0] + radius * math.cos(radians), 5),
            round(center[1] + radius * math.sin(radians), 5)]


def wheel(client, axle, side):
    front = axle == 'front'
    centre_x, centre_z, centre_y = (-1290, 340, 773) if front else (1160, 358, 755)
    radius, rim, half = (340, 254, 122.5) if front else (358, 267, 152.5)
    sign = -1 if side == 'left' else 1
    centre_y *= sign
    face_y = centre_y + sign * (half - 12)
    name = f'911_{axle}_{side}'
    axis = name + '_axis'
    section = name + '_tire_section'
    tire_points = [(rim - 2, -half + 22), (rim + 12, -half), (radius - 38, -half),
                   (radius - 10, -half + 12), (radius, -half + 36),
                   (radius, half - 36), (radius - 10, half - 12),
                   (radius - 38, half), (rim + 12, half), (rim - 2, half - 22)]
    steps = [feature('axis', axis, name=axis, origin=[[centre_x, 0, centre_z]], direction=[[0, 1, 0]]),
             profile(section, section, 'XY', centre_z, [{'type': 'spline', 'closed': True,
                 'points': [[centre_x + radial, centre_y + width] for radial, width in tire_points]}]),
             feature('revolve', 'tire', name=name + '_tire', sketch='$' + section, axis='$' + axis, angle=360)]
    ring = name + '_rim_profile'
    steps += [profile(ring, ring, 'XZ', -face_y, [
        {'type': 'circle', 'cx': centre_x, 'cy': centre_z, 'r': rim},
        {'type': 'circle', 'cx': centre_x, 'cy': centre_z, 'r': rim - 16}]),
        extrude('rim', name + '_alloy_rim', ring, sign * 165)]
    disc = name + '_disc_profile'
    steps += [profile(disc, disc, 'XZ', -(face_y - sign * 46), [
        {'type': 'circle', 'cx': centre_x, 'cy': centre_z, 'r': rim - 40}]),
        extrude('disc', name + '_brake_disc', disc, sign * 12)]
    spokes = []
    for index in range(5):
        for fork in (-9, 9):
            angle = index * 72 + fork + 8
            points = [polar((centre_x, centre_z), 68, angle - 9),
                      polar((centre_x, centre_z), rim - 9, angle + 0.5),
                      polar((centre_x, centre_z), rim - 9, angle + 5),
                      polar((centre_x, centre_z), 68, angle + 9)]
            spokes.append({'type': 'polygon', 'points': points})
    spoke_profile = name + '_spoke_profile'
    steps += [profile(spoke_profile, spoke_profile, 'XZ', -(face_y + sign * 2), spokes),
              extrude('spokes', name + '_ten_alloy_spokes', spoke_profile, sign * 34)]
    hub = name + '_hub_profile'
    steps += [profile(hub, hub, 'XZ', -(face_y + sign * 5), [
        {'type': 'circle', 'cx': centre_x, 'cy': centre_z, 'r': 77}]),
        extrude('hub', name + '_hub', hub, sign * 37)]
    cap = name + '_cap_profile'
    bolts = [{'type': 'circle', 'cx': centre_x, 'cy': centre_z, 'r': 29}]
    bolts += [{'type': 'circle', 'cx': point[0], 'cy': point[1], 'r': 7}
              for point in (polar((centre_x, centre_z), 49, index * 72 + 18) for index in range(5))]
    steps += [profile(cap, cap, 'XZ', -(face_y + sign * 9), bolts),
              extrude('cap', name + '_centre_cap_and_lugs', cap, sign * 7)]
    caliper = name + '_caliper_profile'
    steps += [profile(caliper, caliper, 'XZ', -(face_y - sign * 35), [
        {'type': 'ellipse', 'cx': centre_x + 155, 'cy': centre_z + 70, 'rx': 34, 'ry': 88, 'angle': -18}]),
        extrude('caliper', name + '_red_caliper', caliper, sign * 28)]
    return client.stage(name, steps, {'tire': '#181B20', 'rim': '#BFC6CF', 'spokes': '#CAD1D9',
                                     'hub': '#AAB1BC', 'disc': '#555C65', 'cap': '#39414A', 'caliper': '#B71D27'})


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] not in ('front', 'rear') or sys.argv[2] not in ('left', 'right'):
        raise SystemExit('Usage: wheels.py front|rear left|right')
    with Client() as client:
        wheel(client, *sys.argv[1:])
