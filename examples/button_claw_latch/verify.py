from __future__ import annotations

import json
import hashlib

from build import OUTPUT, configuration
from genform.kernel import assembly
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader


def main():
    report = {'parts': {}, 'assemblies': [], 'exports': {}, 'stroke': [], 'spring_seats': [],
              'open_door_path': [], 'closed_blocking_test': None}
    for path in sorted(OUTPUT.glob('*.gform')):
        record = assembly._part_file(str(path))
        valid = BRepCheck_Analyzer(record['shape']).IsValid()
        if not valid:
            raise RuntimeError(f'Invalid solid: {path.name}')
        solids, explorer = 0, TopExp_Explorer(record['shape'], TopAbs_SOLID)
        while explorer.More():
            solids += 1
            explorer.Next()
        if solids != 1:
            raise RuntimeError(f'Expected one connected solid, got {solids}: {path.name}')
        report['parts'][path.name] = {'valid': valid, 'solids': solids}
        print(f'PART {path.name}: valid, one solid', flush=True)
    for angle in (0, 10, 20, 30, 40):
        name = 'closed' if angle == 0 else 'open' if angle == 40 else f'angle_{angle:02d}'
        data = json.loads((OUTPUT / f'claw_latch_{name}.gasm').read_text(encoding='utf-8'))
        parts = [dict(row, path=str(OUTPUT / row['file'])) for row in data['parts']]
        result = assembly.interference([], None, {'parts': parts})
        report['assemblies'].append({'angle': angle, **result})
        if result['clashes']:
            raise RuntimeError({'angle': angle, **result})
        print(f'ASSEMBLY {angle}: {result["pairs"]} pairs, no volume interference', flush=True)
        spring_shape = assembly._part_file(str(OUTPUT / f'spring_{angle:02d}.gform'))['shape']
        config = configuration(angle)
        for name, position in (('moving', -42 + config['shift']), ('fixed', -36)):
            washer = assembly._placed(assembly._part_file(str(OUTPUT / 'spring_seat.gform'))['shape'],
                                      [position, 0, 0], [0, 0, 0])
            distance = BRepExtrema_DistShapeShape(spring_shape, washer)
            if not distance.IsDone() or distance.Value() > 1e-5:
                raise RuntimeError(f'Spring loses {name} seat at angle {angle}')
            report['spring_seats'].append({'angle': angle, 'seat': name, 'gap_mm': distance.Value()})
    for angle in range(0, 41, 2):
        config = configuration(angle)
        parts = [{'name': 'frame', 'path': str(OUTPUT / 'frame.gform')},
                 {'name': 'claw', 'path': str(OUTPUT / 'rotary_claw.gform'), 'turn': [0, 0, angle]},
                 {'name': 'pushrod', 'path': str(OUTPUT / 'pushrod.gform'), 'move': [config['shift'], 0, 0]},
                 {'name': 'link', 'path': str(OUTPUT / 'connecting_link.gform'), 'move': config['link_move'],
                  'turn': [0, 0, config['link_angle']]},
                 {'name': 'striker', 'path': str(OUTPUT / 'door_striker.gform')},
                 {'name': 'rivet_crank', 'path': str(OUTPUT / 'link_rivet.gform'), 'move': [*config['crank'], 0]},
                 {'name': 'rivet_slider', 'path': str(OUTPUT / 'link_rivet.gform'), 'move': [config['slider'], 10, 0]}]
        result = assembly.interference([], None, {'parts': parts})
        report['stroke'].append({'angle': angle, 'button_travel_mm': config['shift'], **result})
        if result['clashes']:
            raise RuntimeError({'stroke_angle': angle, **result})
        if angle % 10 == 0:
            print(f'STROKE {angle}: no rigid interference', flush=True)
    for step in range(37):
        travel = step * 0.5
        parts = [{'name': 'claw', 'path': str(OUTPUT / 'rotary_claw.gform'), 'turn': [0, 0, 40]},
                 {'name': 'striker', 'path': str(OUTPUT / 'door_striker.gform'), 'move': [travel, 0, 0]}]
        result = assembly.interference([], None, {'parts': parts})
        report['open_door_path'].append({'travel_mm': travel, **result})
        if result['clashes']:
            raise RuntimeError({'open_door_travel': travel, **result})
    parts = [{'name': 'claw', 'path': str(OUTPUT / 'rotary_claw.gform')},
             {'name': 'striker', 'path': str(OUTPUT / 'door_striker.gform'), 'move': [0.5, 0, 0]}]
    blocking = assembly.interference([], None, {'parts': parts})
    report['closed_blocking_test'] = {'forced_door_travel_mm': 0.5, 'expected_blocking_collision': blocking['clashes']}
    if not blocking['clashes']:
        raise RuntimeError('Claw does not block the striker when closed')
    for name in ('open', 'closed'):
        path = OUTPUT / f'claw_latch_{name}.step'
        if not path.exists():
            raise RuntimeError(f'Missing STEP export: {path.name}')
        reader = STEPControl_Reader()
        if reader.ReadFile(str(path)) != IFSelect_RetDone:
            raise RuntimeError(f'Cannot read STEP export: {path.name}')
        reader.TransferRoots()
        shape = reader.OneShape()
        solids, explorer = 0, TopExp_Explorer(shape, TopAbs_SOLID)
        while explorer.More():
            solids += 1
            explorer.Next()
        valid = BRepCheck_Analyzer(shape).IsValid()
        if solids != 20 or not valid:
            raise RuntimeError(f'Invalid or incomplete STEP export: {path.name}, solids={solids}')
        report['exports'][path.name] = {'solids': solids, 'valid': valid,
                                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        print(f'STEP {name}: 20 valid solids', flush=True)
    report['limitations'] = ['Discrete checks, not a continuous collision proof.',
                             'Blocking test deliberately forces the door through a stationary closed claw.',
                             'No load, friction, fatigue, spring-force or production-tolerance certification.',
                             'Native design warnings remain available without filtering in design_check_*.json.']
    report['input_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted(OUTPUT.iterdir()) if path.suffix in ('.gform', '.gasm')}
    (OUTPUT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: valid parts, 5 assemblies, 21 rigid stroke samples, 37 release samples, and closed blocking test', flush=True)


if __name__ == '__main__':
    main()
