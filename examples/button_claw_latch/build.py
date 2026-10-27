from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from examples.button_latch.build import Client, circle, extrusion, feature, rectangle, sketch, ui

OUTPUT = ROOT / 'models' / 'button_claw_latch'
POSTS = [(-56, -16), (-56, 30), (8, -16), (8, 30)]


def configuration(angle):
    radians = math.radians(angle)
    crank = [-10 * math.sin(radians), 10 * math.cos(radians)]
    slider = crank[0] - math.sqrt(24 ** 2 - (crank[1] - 10) ** 2)
    link_angle = math.degrees(math.atan2(crank[1] - 10, crank[0] - slider))
    link_radians = math.radians(link_angle)
    translation = [slider + 24 * math.cos(link_radians) + 10 * math.sin(link_radians),
                   10 + 24 * math.sin(link_radians) - 10 * math.cos(link_radians), 0]
    return {'angle': angle, 'slider': slider, 'crank': crank, 'shift': slider + 24,
            'link_angle': link_angle, 'link_move': translation}


def part(client, filename, steps, color):
    destination = OUTPUT / filename
    if destination.exists():
        print(f'EXISTS {filename}', flush=True)
        return
    current = client.call('get_model', brief=True)
    if current.get('unsaved_changes'):
        raise RuntimeError('Unsaved document: inspect before changing it')
    client.call('new_document')
    answer = client.call('batch', steps=steps)
    model = answer.get('model') or client.call('get_model', brief=True)
    failed = [row for row in model['features'] if row.get('status') != 'ok']
    if failed or not model.get('has_body'):
        raise RuntimeError({'part': filename, 'failed': failed})
    client.call('set_appearance', color=color)
    client.call('save_document', path=str(destination))
    print(json.dumps({'saved': filename, 'body': model['body']}, ensure_ascii=True), flush=True)


def frame(client):
    steps = [sketch('demo_base', 'XY', 0, [rectangle(-2, 7, 148, 62)]),
             extrusion('frame_plate', 'demo_base', 4),
             sketch('cover_posts', 'XY', 3.5, [circle(center_x, center_y, 4) for center_x, center_y in POSTS]),
             extrusion('four_cover_spacers', 'cover_posts', 14.5),
             sketch('pivot_boss', 'XY', 3.5, [circle(0, 0, 6)]),
             extrusion('rotary_claw_support', 'pivot_boss', 4.5),
             sketch('pivot_seat', 'XY', 3, [circle(0, 0, 2.2)]),
             extrusion('blind_dowel_seat', 'pivot_seat', 6, 'cut')]
    for position, thickness in ((-60, 4), (-35.5, 2), (-53.314, 2)):
        alias = f'guide_{abs(position)}'
        steps += [sketch(alias, 'YZ', position, [rectangle(10, 10.75, 18, 14.5), rectangle(10, 10, 6.4, 4.4)]),
                  extrusion(alias + '_block', alias, thickness)]
    steps += [sketch('through_bolt_clearances', 'XY', -1, [circle(center_x, center_y, 1.7) for center_x, center_y in POSTS]),
              extrusion('M3_clearance_not_tap_drills', 'through_bolt_clearances', 20, 'cut'),
              sketch('link_sweep_relief', 'XY', 11.3, [{'type': 'slot', 'x1': -34.5, 'y1': 5.5,
                                                     'x2': -34.5, 'y2': 14.5, 'w': 3}]),
              extrusion('guide_top_open_for_link', 'link_sweep_relief', 8, 'cut'),
              sketch('rivet_head_relief', 'XY', 6.5, [{'type': 'slot', 'x1': -33.5, 'y1': 7,
                                                    'x2': -33.5, 'y2': 13, 'w': 2}]),
              extrusion('guide_front_clearance', 'rivet_head_relief', 11.6, 'cut'),
              sketch('fixture_mounting', 'XY', -1, [circle(center_x, center_y, 2.7)
                      for center_x in (-70, 66) for center_y in (-18, 32)]),
              extrusion('base_mount_holes', 'fixture_mounting', 6, 'cut')]
    part(client, 'frame.gform', steps, '#748495')
    steps = [sketch('cover_outline', 'XY', 18, [rectangle(-24, 7, 80, 54)]),
             extrusion('removable_cover', 'cover_outline', 2),
             sketch('lid_clearances', 'XY', 17, [circle(center_x, center_y, 1.7) for center_x, center_y in POSTS]),
             extrusion('four_through_holes', 'lid_clearances', 4, 'cut')]
    part(client, 'cover.gform', steps, '#B5DDE8')
    steps = [sketch('door_sample', 'XY', 4, [rectangle(36, 0, 28, 36)]),
             extrusion('sliding_door_coupon', 'door_sample', 2),
             sketch('striker_pin', 'XY', 5.5, [circle(26, 0, 3)]),
             extrusion('six_mm_striker', 'striker_pin', 10.5),
             sketch('striker_head', 'XY', 15.5, [circle(26, 0, 4.5)]),
             extrusion('striker_retention_head', 'striker_head', 2)]
    part(client, 'door_striker.gform', steps, '#D5A13B')
    steps = [sketch('dowel', 'XY', 3, [circle(0, 0, 2)]),
             extrusion('captured_pivot_dowel', 'dowel', 15)]
    part(client, 'pivot_dowel.gform', steps, '#444F5E')


def mechanism(client):
    outline = [[-4, -5], [17, -4], [20, -7], [34, -7], [34, 7], [18, 7], [14, 5], [-4, 5]]
    mouth = [[22.6, 0], [18, -12], [35, -12], [29.4, 0]]
    steps = [sketch('hook_outline', 'XY', 8, [{'type': 'polygon', 'points': outline}]),
             extrusion('load_bearing_claw', 'hook_outline', 4),
             sketch('pivot_eye', 'XY', 8, [circle(0, 0, 6)]),
             extrusion('pivot_hub', 'pivot_eye', 4),
             sketch('crank_arm', 'XY', 8, [rectangle(0, 5, 7, 10)]),
             extrusion('button_link_drive_arm', 'crank_arm', 4),
             sketch('crank_eye', 'XY', 8, [circle(0, 10, 4.5)]),
             extrusion('crank_pin_boss', 'crank_eye', 4),
             sketch('striker_clearance', 'XY', 7, [circle(26, 0, 3.4)]),
             extrusion('round_striker_pocket', 'striker_clearance', 6, 'cut'),
             sketch('release_mouth', 'XY', 7, [{'type': 'polygon', 'points': mouth}]),
             extrusion('flared_entry_and_release', 'release_mouth', 6, 'cut'),
             sketch('hinge_bores', 'XY', 7, [circle(0, 0, 2.2), circle(0, 10, 1.7)]),
             extrusion('pivot_and_crank_holes', 'hinge_bores', 6, 'cut')]
    part(client, 'rotary_claw.gform', steps, '#D66A38')
    steps = [sketch('slider_shaft', 'XY', 8, [rectangle(-42.25, 10, 36.5, 6)]),
             extrusion('rectangular_pushrod', 'slider_shaft', 4),
             sketch('slider_eye', 'XY', 8, [circle(-24, 10, 3)]),
             extrusion('link_attachment_eye', 'slider_eye', 4),
             sketch('eye_hole', 'XY', 7, [circle(-24, 10, 1.7)]),
             extrusion('slider_link_bore', 'eye_hole', 6, 'cut'),
             sketch('button_head', 'YZ', -64, [circle(10, 10, 6)]),
             extrusion('push_button', 'button_head', 4),
             sketch('spring_stop', 'YZ', -45, [circle(10, 10, 5.5)]),
             extrusion('moving_spring_collar', 'spring_stop', 3)]
    part(client, 'pushrod.gform', steps, '#247FCC')
    steps = [sketch('link_profile', 'XY', 12, [{'type': 'slot', 'x1': -24, 'y1': 10, 'x2': 0, 'y2': 10, 'w': 6}]),
             extrusion('rigid_24mm_link', 'link_profile', 3),
             sketch('link_eyes', 'XY', 11, [circle(-24, 10, 1.7), circle(0, 10, 1.7)]),
             extrusion('two_link_bores', 'link_eyes', 5, 'cut')]
    part(client, 'connecting_link.gform', steps, '#56AA92')
    steps = [sketch('rivet_shank', 'XY', 7.5, [circle(0, 0, 1.5)]),
             extrusion('three_mm_joint_pin', 'rivet_shank', 8),
             sketch('upper_head', 'XY', 15, [circle(0, 0, 2.7)]),
             extrusion('formed_upper_head', 'upper_head', 1.2),
             sketch('lower_head', 'XY', 7, [circle(0, 0, 2.7)]),
             extrusion('peened_lower_head', 'lower_head', 1)]
    part(client, 'link_rivet.gform', steps, '#46505C')


def hardware(client):
    steps = [sketch('bolt_position', 'XY', 20, [{'type': 'point', 'x': 0, 'y': 0}]),
             feature('screw', 'M3x25_through_screw', sketch='$bolt_position', size='M3', head='button', length=25, thread=False)]
    part(client, 'cover_bolt.gform', steps, '#434D5B')
    steps = [sketch('hex_nut', 'XY', -2.4, [{'type': 'ngon', 'cx': 0, 'cy': 0, 'r': 5.5 / math.sqrt(3), 'sides': 6,
                                           'angle': 0}, circle(0, 0, 1.6)]),
             extrusion('M3_nut_clearance_envelope', 'hex_nut', 2.4)]
    part(client, 'cover_nut.gform', steps, '#434D5B')
    steps = [sketch('spring_seat', 'YZ', 0, [circle(10, 10, 5.5), circle(10, 10, 4.2)]),
             extrusion('thin_spring_seat_washer', 'spring_seat', 0.5)]
    part(client, 'spring_seat.gform', steps, '#9BA6B5')


def spring(client, angle):
    shift = configuration(angle)['shift']
    rear, front = -42 + shift, -35.5
    pitch = (front - rear - 2) / 4
    steps = [sketch('coil_mean_circle', 'YZ', rear + 1, [circle(10, 10, 4.7)]),
             feature('curve_helix', 'four_turn_return_spring', sketch='$coil_mean_circle', pitch=pitch, turns=4,
                     taper=0, start=0, clockwise=False),
             feature('plane', 'wire_normal', offset=0, origin=[[rear + 1, 14.7, 10]],
                     normal=[[pitch / (2 * math.pi), 0, 4.7]]),
             sketch('wire_section', '$wire_normal', 0, [circle(0, 0, 0.5)]),
             feature('sweep', 'spring_wire', sketch='$wire_section', path='$four_turn_return_spring'),
             sketch('rear_closed_end', 'YZ', rear + 0.5, [circle(10, 10, 5.25), circle(10, 10, 4.15)]),
             extrusion('rear_ground_seat', 'rear_closed_end', 1),
             sketch('front_closed_end', 'YZ', front - 1.5, [circle(10, 10, 5.25), circle(10, 10, 4.15)]),
             extrusion('front_ground_seat', 'front_closed_end', 1)]
    part(client, f'spring_{angle:02d}.gform', steps, '#BDC4CD')


def assembly(angle, exploded=False, door_shift=0):
    config = configuration(angle)

    def row(name, filename, move=(0, 0, 0), turn=0):
        return {'name': name, 'file': filename, 'move': list(move), 'turn': [0, 0, turn]}

    parts = [row('固定框架与导向座', 'frame.gform'),
             row('橙色旋转锁爪', 'rotary_claw.gform', turn=angle),
             row('蓝色按钮推杆', 'pushrod.gform', [config['shift'], 0, 0]),
             row('绿色传动连杆', 'connecting_link.gform', config['link_move'], config['link_angle']),
             row('门板试片与扣销', 'door_striker.gform', [door_shift, 0, 0]),
             row('主转轴', 'pivot_dowel.gform'),
             row('锁爪连杆铆钉', 'link_rivet.gform', [*config['crank'], 0]),
             row('按钮连杆铆钉', 'link_rivet.gform', [config['slider'], 10, 0]),
             row('压簧', f'spring_{angle:02d}.gform'),
             row('检修上盖', 'cover.gform', [0, 0, 22 if exploded else 0]),
             row('移动弹簧支承垫圈', 'spring_seat.gform', [-42 + config['shift'], 0, 0]),
             row('固定弹簧支承垫圈', 'spring_seat.gform', [-36, 0, 0])]
    for center_x, center_y in POSTS:
        parts.append(row('上盖穿透螺栓 M3x25', 'cover_bolt.gform', [center_x, center_y, 25 if exploded else 0]))
        parts.append(row('上盖配套六角螺母 M3', 'cover_nut.gform', [center_x, center_y, -6 if exploded else 0]))
    name = 'exploded' if exploded else 'released' if door_shift else 'open' if angle == 40 else 'closed' if angle == 0 else f'angle_{angle:02d}'
    destination = OUTPUT / f'claw_latch_{name}.gasm'
    destination.write_text(json.dumps({'format': 'genform-assembly', 'version': 1, 'parts': parts}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'SAVED {destination.name}', flush=True)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('frame', 'mechanism', 'hardware', 'springs', 'assembly', 'show'))
    parser.add_argument('--angle', type=int, default=40)
    arguments = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if arguments.phase == 'assembly':
        for angle in (40, 30, 20, 10, 0):
            assembly(angle)
        assembly(40, exploded=True)
        assembly(40, door_shift=18)
        return
    if arguments.phase == 'show':
        ui('openDocument', [str(OUTPUT / ('claw_latch_open.gasm' if arguments.angle == 40 else 'claw_latch_closed.gasm'))])
        return
    client = Client()
    try:
        if arguments.phase == 'springs':
            spring(client, arguments.angle)
        else:
            {'frame': frame, 'mechanism': mechanism, 'hardware': hardware}[arguments.phase](client)
    finally:
        client.close()


if __name__ == '__main__':
    main()
