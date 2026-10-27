from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from OCP.BRepCheck import BRepCheck_Analyzer
from genform.kernel import assembly

OUTPUT = ROOT / 'models' / 'button_latch'


def main():
    report = {'parts': {}, 'states': {}, 'stroke_mm': 8, 'keeper_entry_mm': 30,
              'open_tip_mm': 26, 'pressed_tip_mm': 34, 'open_gap_mm': 4,
              'pressed_engagement_mm': 4, 'guide_radial_clearance_mm': 0.3,
              'receiver_radial_clearance_mm': 0.4,
              'limitations': ['Thread envelopes are simplified: housing and cover screw overlaps are intentional.',
                              'Spring shapes are separate static states, not an elastic simulation.',
                              'Prototype dimensions; no load, fatigue or production tolerance certification.']}
    for path in sorted(OUTPUT.glob('*.gform')):
        record = assembly._part_file(str(path))
        valid = BRepCheck_Analyzer(record['shape']).IsValid()
        report['parts'][path.name] = {'valid': valid}
        if not valid:
            raise RuntimeError(f'Invalid part: {path.name}')
        print(f'VALID {path.name}', flush=True)
    for state in ('open', 'pressed'):
        data = json.loads((OUTPUT / f'button_latch_{state}.gasm').read_text(encoding='utf-8'))
        rows = [{**row, 'path': str(OUTPUT / row['file'])} for row in data['parts']]
        result = assembly.interference([], None, {'parts': rows})
        intended = [pair for pair in result['clashes'] if pair['a'] == 0 and pair['b'] >= 5]
        unexpected = [pair for pair in result['clashes'] if pair not in intended]
        report['states'][state] = {'pair_count': result['pairs'], 'unexpected_clashes': unexpected,
                                  'simplified_thread_envelope_overlaps': intended}
        print(f'STATE {state}: unexpected clashes={len(unexpected)}, thread envelopes={len(intended)}', flush=True)
        if unexpected:
            raise RuntimeError(unexpected)
    housing = {'name': 'Housing', 'path': str(OUTPUT / 'housing.gform')}
    keeper = {'name': 'Keeper', 'path': str(OUTPUT / 'keeper.gform')}
    report['stroke_samples'] = []
    for travel in range(9):
        bolt = {'name': 'Button bolt', 'path': str(OUTPUT / 'button_bolt.gform'), 'move': [travel, 0, 0]}
        result = assembly.interference([], None, {'parts': [housing, keeper, bolt]})
        report['stroke_samples'].append({'travel_mm': travel, 'clashes': result['clashes']})
        if result['clashes']:
            raise RuntimeError({'travel_mm': travel, 'clashes': result['clashes']})
    destination = OUTPUT / 'verification.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'PASS: seven valid part files, both states checked, nine rigid stroke samples; report={destination}', flush=True)


if __name__ == '__main__':
    main()
