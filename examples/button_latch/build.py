from __future__ import annotations

import argparse
import json
import math
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'examples' / 'porsche_911'))
from mcp_client import Client

OUTPUT = ROOT / 'models' / 'button_latch'


def ui(slot, arguments=None):
    with socket.create_connection(('127.0.0.1', 9631), 5) as connection:
        connection.settimeout(20)
        stream = connection.makefile('rwb')
        stream.write((json.dumps({'cmd': 'ui', 'slot': slot, 'args': arguments or []}) + '\n').encode())
        stream.flush()
        answer = json.loads(stream.readline())
        if not answer.get('ok'):
            raise RuntimeError(answer)
        return answer


def feature(command, alias, **arguments):
    return {'cmd': command, 'as': alias, 'args': arguments}


def sketch(alias, plane, offset, shapes):
    return feature('sketch', alias, name=alias, plane=plane, offset=offset, shapes=shapes)


def rectangle(center_x, center_y, width, height):
    return {'type': 'rect', 'cx': center_x, 'cy': center_y, 'w': width, 'h': height}


def circle(center_x, center_y, radius):
    return {'type': 'circle', 'cx': center_x, 'cy': center_y, 'r': radius}


def extrusion(alias, source, distance, operation='add'):
    return feature('extrude', alias, name=alias, sketch='$' + source, distance=distance, op=operation)


def build_part(client, filename, steps, color):
    destination = OUTPUT / filename
    if destination.exists():
        print(f'SKIP existing {filename}', flush=True)
        return
    current = client.call('get_model', brief=True)
    if current.get('unsaved_changes'):
        raise RuntimeError('Current document has unsaved changes; save it before building another part')
    client.call('new_document')
    answer = client.call('batch', steps=steps)
    model = answer.get('model') or client.call('get_model', brief=True)
    failed = [row for row in model.get('features', []) if row.get('status') not in ('ok', None)]
    if failed or not model.get('has_body'):
        raise RuntimeError({'failed': failed, 'model': model})
    client.call('set_appearance', color=color)
    client.call('save_document', path=str(destination))
    print(json.dumps({'saved': filename, 'features': len(model['features']), 'body': model.get('body')}, ensure_ascii=True), flush=True)


def core(client):
    steps = [sketch('housing_blank', 'XY', 0, [rectangle(0, 0, 56, 32)]),
             extrusion('housing_block', 'housing_blank', 17),
             sketch('slider_chamber', 'XY', 3, [rectangle(0, 0, 42, 20)]),
             extrusion('open_top_chamber', 'slider_chamber', 15, 'cut'),
             sketch('bolt_guide', 'YZ', -29, [circle(0, 10, 2.8)]),
             extrusion('coaxial_guide_bores', 'bolt_guide', 58, 'cut'),
             sketch('mount_holes', 'XY', -1, [circle(center_x, center_y, 1.7)
                    for center_x in (-24, 24) for center_y in (-13, 13)]),
             extrusion('four_mounting_holes', 'mount_holes', 19, 'cut'),
             sketch('cover_pilot_holes', 'XY', 11, [circle(center_x, center_y, 1.25)
                    for center_x in (-16, 16) for center_y in (-13, 13)]),
             extrusion('cover_M3_tap_drills', 'cover_pilot_holes', 7, 'cut')]
    build_part(client, 'housing.gform', steps, '#8D99A8')
    steps = [sketch('bolt_shaft', 'YZ', -36, [circle(0, 10, 2.5)]),
             extrusion('five_mm_sliding_bolt', 'bolt_shaft', 62),
             sketch('return_stop', 'YZ', -21, [circle(0, 10, 4.8)]),
             extrusion('spring_reaction_collar', 'return_stop', 3),
             sketch('button_pad', 'YZ', -40, [circle(0, 10, 6.5)]),
             extrusion('push_button', 'button_pad', 4)]
    build_part(client, 'button_bolt.gform', steps, '#2778CE')
    steps = [sketch('keeper_foot', 'XY', 0, [rectangle(35, 0, 10, 32)]),
             extrusion('keeper_mount', 'keeper_foot', 3),
             sketch('keeper_lug', 'XY', 3, [rectangle(33, 0, 6, 18)]),
             extrusion('keeper_body', 'keeper_lug', 14),
             sketch('receiver', 'YZ', 29, [circle(0, 10, 2.9)]),
             extrusion('receiving_bore', 'receiver', 8, 'cut'),
             sketch('keeper_mount_holes', 'XY', -1, [circle(35, center_y, 1.7) for center_y in (-13, 13)]),
             extrusion('two_keeper_mounting_holes', 'keeper_mount_holes', 5, 'cut')]
    build_part(client, 'keeper.gform', steps, '#D3A64A')
    steps = [sketch('lid_outline', 'XY', 17, [rectangle(0, 0, 56, 32)]),
             extrusion('clear_inspection_cover', 'lid_outline', 2),
             sketch('cover_holes', 'XY', 16, [circle(center_x, center_y, 1.7)
                    for center_x in (-16, 16) for center_y in (-13, 13)]),
             extrusion('cover_clearance_holes', 'cover_holes', 4, 'cut'),
             sketch('mounting_access', 'XY', 16, [circle(center_x, center_y, 3.4)
                    for center_x in (-24, 24) for center_y in (-13, 13)]),
             extrusion('mounting_screw_access', 'mounting_access', 4, 'cut')]
    build_part(client, 'cover.gform', steps, '#B5DDE8')
    steps = [sketch('screw_position', 'XY', 19, [{'type': 'point', 'x': 0, 'y': 0}]),
             feature('screw', 'M3x6_cover_screw', sketch='$screw_position', size='M3', head='button', length=6, thread=False)]
    build_part(client, 'cover_screw_M3x6.gform', steps, '#434B56')


def spring(client, pressed):
    start_x = -9.4 if pressed else -17.4
    axial_length = 29.8 if pressed else 37.8
    pitch = axial_length / 9
    steps = [sketch('spring_mean_coil', 'YZ', start_x, [circle(0, 10, 4.1)]),
             feature('curve_helix', 'nine_coil_centerline', sketch='$spring_mean_coil', pitch=pitch, turns=9,
                     taper=0, start=0, clockwise=False),
             feature('plane', 'normal_wire_plane', offset=0, origin=[[start_x, 4.1, 10]], normal=[[pitch / (2 * math.pi), 0, 4.1]]),
             sketch('wire_section', '$normal_wire_plane', 0, [circle(0, 0, 0.6)]),
             feature('sweep', 'return_compression_spring', sketch='$wire_section', path='$nine_coil_centerline')]
    build_part(client, 'spring_pressed.gform' if pressed else 'spring_open.gform', steps, '#BCBFC4')


def assembly(pressed=False, exploded=False):
    shift = 8 if pressed else 0
    parts = [{'name': 'Housing | fixed guide', 'file': 'housing.gform', 'move': [0, 0, 0], 'turn': [0, 0, 0]},
             {'name': 'Button + bolt | stroke 8 mm', 'file': 'button_bolt.gform', 'move': [shift, 0, 0], 'turn': [0, 0, 0]},
             {'name': 'Keeper | separate mating panel', 'file': 'keeper.gform', 'move': [0, 0, 0], 'turn': [0, 0, 0]},
             {'name': 'Return compression spring', 'file': 'spring_pressed.gform' if pressed else 'spring_open.gform',
              'move': [0, 0, 0], 'turn': [0, 0, 0]},
             {'name': 'Inspection cover', 'file': 'cover.gform', 'move': [0, 0, 18 if exploded else 0], 'turn': [0, 0, 0]}]
    parts += [{'name': f'Cover screw M3x6 ({center_x}, {center_y})', 'file': 'cover_screw_M3x6.gform',
               'move': [center_x, center_y, 22 if exploded else 0], 'turn': [0, 0, 0]}
              for center_x in (-16, 16) for center_y in (-13, 13)]
    filename = 'button_latch_exploded.gasm' if exploded else 'button_latch_pressed.gasm' if pressed else 'button_latch_open.gasm'
    destination = OUTPUT / filename
    destination.write_text(json.dumps({'format': 'genform-assembly', 'version': 1, 'parts': parts}, indent=2), encoding='utf-8')
    print(f'SAVED {destination}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('core', 'springs', 'assembly', 'show'))
    arguments = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if arguments.phase == 'assembly':
        assembly()
        assembly(pressed=True)
        assembly(exploded=True)
        return
    if arguments.phase == 'show':
        ui('openDocument', [str(OUTPUT / 'button_latch_exploded.gasm')])
        return
    client = Client()
    try:
        if arguments.phase == 'core':
            core(client)
        else:
            spring(client, False)
            spring(client, True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
