from __future__ import annotations

import math
import sys

from mcp_client import Client, extrude, feature, profile


def lamp(client, side):
    sign = -1 if side == 'left' else 1
    name = '911_headlamp_' + side
    steps = [feature('plane', 'lamp_plane', name=name + '_datum',
                     origin=[[-1940, sign * 662, 724]], normal=[[-0.6, sign * 0.12, 0.791]])]
    for alias, radius_x, radius_y, offset, depth in (
            ('bezel', 143, 170, -12, 36), ('lens', 129, 155, 23, 5)):
        source = alias + '_profile'
        steps += [profile(source, name + '_' + source, '$lamp_plane', offset,
                          [{'type': 'ellipse', 'cx': 0, 'cy': 0, 'rx': radius_x, 'ry': radius_y}]),
                  extrude(alias, name + '_' + alias, source, depth)]
    steps += [profile('led_ring_profile', name + '_led_ring_profile', '$lamp_plane', 29, [
        {'type': 'ellipse', 'cx': 0, 'cy': 0, 'rx': 119, 'ry': 143},
        {'type': 'ellipse', 'cx': 0, 'cy': 0, 'rx': 113, 'ry': 137}]),
        extrude('led_ring', name + '_led_ring', 'led_ring_profile', 3)]
    leds = [{'type': 'circle', 'cx': horizontal, 'cy': vertical, 'r': 17}
            for horizontal in (-51, 51) for vertical in (-58, 58)]
    steps += [profile('leds_profile', name + '_four_leds_profile', '$lamp_plane', 30, leds),
              extrude('leds', name + '_four_led_projectors', 'leds_profile', 5)]
    return client.stage(name, steps, {'bezel': '#111821', 'lens': '#3E5261',
                                     'led_ring': '#EDF5FF', 'leds': '#F7FAFF'})


def bumpers(client):
    grille = [{'type': 'slot', 'x1': -235, 'y1': 348, 'x2': 235, 'y2': 348, 'w': 128},
              {'type': 'slot', 'x1': -616, 'y1': 359, 'x2': -432, 'y2': 359, 'w': 152},
              {'type': 'slot', 'x1': 432, 'y1': 359, 'x2': 616, 'y2': 359, 'w': 152}]
    steps = [profile('front_grilles', '911_front_intake_profiles', 'YZ', -2262, grille),
             extrude('intakes', '911_three_front_intakes', 'front_grilles', 30)]
    running = [{'type': 'slot', 'x1': -638, 'y1': 459, 'x2': -407, 'y2': 459, 'w': 11},
               {'type': 'slot', 'x1': 407, 'y1': 459, 'x2': 638, 'y2': 459, 'w': 11}]
    steps += [profile('drl_profile', '911_front_running_lights_profile', 'YZ', -2266, running),
              extrude('drl', '911_horizontal_daytime_running_lights', 'drl_profile', 7)]
    bars = [{'type': 'rect', 'cx': 0, 'cy': height, 'w': 457, 'h': 4} for height in (311, 337, 363, 389)]
    bars += [{'type': 'rect', 'cx': sign * 525, 'cy': height, 'w': 176, 'h': 4}
             for sign in (-1, 1) for height in (325, 352, 379, 406)]
    steps += [profile('grille_bars_profile', '911_front_grille_bars_profile', 'YZ', -2266, bars),
              extrude('grille_bars', '911_front_grille_horizontal_bars', 'grille_bars_profile', 3)]
    steps += [profile('rear_strip_profile', '911_rear_strip_bezel_profile', 'YZ', 2262, [
        {'type': 'slot', 'x1': -649, 'y1': 668, 'x2': 649, 'y2': 668, 'w': 62}]),
        extrude('rear_bezel', '911_rear_light_black_panel', 'rear_strip_profile', -20),
        profile('rear_led_profile', '911_rear_led_strip_profile', 'YZ', 2266, [
            {'type': 'slot', 'x1': -652, 'y1': 680, 'x2': 652, 'y2': 680, 'w': 13}]),
        extrude('rear_led', '911_continuous_red_light_bar', 'rear_led_profile', -5)]
    steps += [profile('diffuser_profile', '911_rear_diffuser_profile', 'YZ', 2262, [
        {'type': 'polygon', 'points': [[-650, 250], [-550, 205], [550, 205], [650, 250], [600, 355], [-600, 355]]}]),
        extrude('diffuser', '911_black_rear_diffuser', 'diffuser_profile', -40)]
    exhausts = []
    for sign in (-1, 1):
        exhausts += [{'type': 'ellipse', 'cx': sign * 525, 'cy': 294, 'rx': 88, 'ry': 48},
                     {'type': 'ellipse', 'cx': sign * 525, 'cy': 294, 'rx': 74, 'ry': 36}]
    steps += [profile('exhaust_profile', '911_twin_exhaust_profile', 'YZ', 2274, exhausts),
              extrude('exhaust', '911_oval_exhaust_tips', 'exhaust_profile', -72)]
    steps += [profile('exhaust_dark_profile', '911_exhaust_depth_profile', 'YZ', 2250, [
        {'type': 'ellipse', 'cx': sign * 525, 'cy': 294, 'rx': 73, 'ry': 35} for sign in (-1, 1)]),
        extrude('exhaust_dark', '911_exhaust_dark_interiors', 'exhaust_dark_profile', -4)]
    return client.stage('bumpers', steps, {'intakes': '#10161C', 'drl': '#EEF4FC', 'grille_bars': '#3E454E',
                                         'rear_bezel': '#151920', 'rear_led': '#D51930', 'diffuser': '#1B2128',
                                         'exhaust': '#A1ADB7', 'exhaust_dark': '#090C10'})


def mirrors(client):
    steps = []
    for sign, side in ((-1, 'left'), (1, 'right')):
        root = '911_mirror_' + side
        sections = []
        for index, (width, station, height) in enumerate(((40, sign * 823, 843), (55, sign * 921, 875))):
            alias = side + '_stalk_' + str(index)
            steps.append(profile(alias, root + '_stalk_section_' + str(index), 'XZ', -station, [
                {'type': 'ellipse', 'cx': -531, 'cy': height, 'rx': width, 'ry': 16}]))
            sections.append('$' + alias)
        steps.append(feature('loft', 'stalk_' + side, name=root + '_stalk', sketches=sections))
        sections = []
        for index, (station, radius_x, radius_z, centre_x) in enumerate((
                (sign * 903, 90, 43, -542), (sign * 968, 119, 59, -530),
                (sign * 1031, 102, 51, -517), (sign * 1052, 45, 30, -511))):
            alias = side + '_housing_' + str(index)
            steps.append(profile(alias, root + '_housing_section_' + str(index), 'XZ', -station, [
                {'type': 'ellipse', 'cx': centre_x, 'cy': 904, 'rx': radius_x, 'ry': radius_z}]))
            sections.append('$' + alias)
        steps.append(feature('loft', 'housing_' + side, name=root + '_housing', sketches=sections))
        steps += [feature('plane', 'mirror_plane_' + side, name=root + '_glass_datum',
                          origin=[[-437, sign * 975, 906]], normal=[[0.96, sign * 0.28, 0.03]]),
                  profile('mirror_glass_' + side, root + '_glass_profile', '$mirror_plane_' + side, 0, [
                      {'type': 'ellipse', 'cx': 0, 'cy': 0, 'rx': 65, 'ry': 37}]),
                  extrude('glass_' + side, root + '_glass', 'mirror_glass_' + side, 4)]
    return client.stage('mirrors', steps, {'stalk_left': '#222A32', 'stalk_right': '#222A32',
                                         'housing_left': '#9AABB9', 'housing_right': '#9AABB9',
                                         'glass_left': '#5E7587', 'glass_right': '#5E7587'})


if __name__ == '__main__':
    with Client() as client:
        if sys.argv[1] == 'lamp':
            lamp(client, sys.argv[2])
        elif sys.argv[1] == 'bumpers':
            bumpers(client)
        elif sys.argv[1] == 'mirrors':
            mirrors(client)
        else:
            raise SystemExit('Usage: details.py lamp left|right; details.py bumpers|mirrors')
