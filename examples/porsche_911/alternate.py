"""Plan offline; --execute --new-document builds method B through single-send MCP.

Save A in GenForm first. Runtime checks the live A against its complete saved JSON.
Resume with --resume; --open-checkpoint explicitly permits replacing a saved window
document with the last owned checkpoint. An ambiguous action is never resent.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from alternate_runtime import Client, Journal, atomic_json, digest, load_json, same_features
from genform import commands
from genform.document import Document
from genform.sketchgeo.base import _spline_beziers, prims, sample

SOURCE = ROOT / 'models/porsche_911_992/porsche_911_992.gform'
HALVES = {'911_连续曲面车身': 7, '911_经典弧顶与后溜背': 5}
AUXILIARY = {'sketch', 'axis', 'plane', 'point', 'csys', 'sketch3d', 'bbox', 'com'}


def read_source(path):
    data = load_json(path)
    document = Document()
    document.load_data(data)
    if document.upto is not None:
        raise ValueError('A must have no rollback before building B')
    if set(document.props) - {'material', 'color', 'feature_colors'}:
        raise ValueError('Unknown props cannot be represented by the current MCP API')
    features = document.features
    if len({item['name'] for item in features}) != len(features):
        raise ValueError('A feature names must be unique')
    if len({item['id'] for item in features}) != len(features):
        raise ValueError('A feature IDs must be unique')
    return data


def live_matches_source(model, data):
    if not same_features(model, data):
        return False
    props = data.get('props', {})
    return model.get('material') == props.get('material') and \
        model.get('feature_colors', {}) == props.get('feature_colors', {})


def paired_left(name, names):
    if not re.search(r'(^|_)right(_|$)', name):
        return None
    if any(token in name.lower() for token in ('window', 'glass', 'mirror_right')):
        return None
    candidate = re.sub(r'(^|_)right(_|$)', r'\1left\2', name, count=1)
    return candidate if candidate in names else None


def half_shapes(params, count):
    shapes = params['shapes']
    if params.get('plane') != 'YZ' or len(shapes) != 1:
        raise ValueError('Expected one closed YZ Catmull section')
    shape = shapes[0]
    points = shape.get('points', [])
    if shape['type'] != 'spline' or not shape.get('closed') or shape.get('style') or len(points) != count * 2:
        raise ValueError('Unexpected Catmull section topology')
    if points[0][0] != 0 or points[count][0] != 0 or points[0][1] <= points[count][1]:
        raise ValueError('Section must start at top Y=0 and reach bottom Y=0')
    if any(point[0] <= 0 for point in points[1:count]):
        raise ValueError('First half must be positive Y')
    for index in range(1, count):
        if points[-index] != [-points[index][0], points[index][1]]:
            raise ValueError('Section is not symmetric; refusing to discard A coordinates')
    curves = _spline_beziers(points, True)[:count]
    result = [{'type': 'spline', 'style': True, 'closed': False,
               'points': [list(point) for point in curve[1:]]} for curve in curves]
    result.append({'type': 'line', 'x1': points[count][0], 'y1': points[count][1],
                   'x2': points[0][0], 'y2': points[0][1]})
    return result


class Plan:
    def __init__(self, data):
        self.source, self.document = data, Document()
        self.mapping, self.rows = {}, []
        features = data['features']
        by_id = {item['id']: item for item in features}
        by_name = {item['name']: item for item in features}
        sections = {}
        for name, count in HALVES.items():
            loft = by_name[name]
            if loft['type'] != 'loft' or loft['params'].get('op', 'add') != 'add':
                raise ValueError(f'{name}: expected additive loft')
            for identifier in loft['params']['sketches']:
                sections[by_id[identifier]['name']] = count
        names = {item['name'] for item in features}
        for source in features:
            name, kind, identifier = source['name'], source['type'], source['id']
            left_name = paired_left(name, names)
            params = self.remap(source['params']) if left_name is None else {}
            if name in sections:
                params['shapes'] = half_shapes(source['params'], sections[name])
                made = [self.add(kind, params, name, source)]
                strategy = 'exact-positive-Y-Bezier-section'
            elif name in HALVES:
                seed = self.add('loft', params, name + '__B_positiveY', source)
                reflected = self.add('mirror', {'plane': 'XZ', 'offset': 0, 'features': [seed]}, name, source)
                made, strategy = [seed, reflected], 'half-YZ-loft-plus-feature-mirror-XZ'
            elif left_name:
                seed_name = left_name
                seed_source = by_name[seed_name]
                if source.get('suppressed') != seed_source.get('suppressed'):
                    raise ValueError(f'Asymmetric suppression: {name}')
                if kind in AUXILIARY or kind.startswith('curve_'):
                    made, strategy = [], 'omitted-right-auxiliary; original retained in manifest'
                else:
                    if kind not in ('extrude', 'revolve', 'loft', 'sweep', 'mirror', 'stud', 'hole', 'screw'):
                        raise ValueError(f'Cannot feature-mirror paired {kind}: {name}')
                    seeds = self.mapping[seed_source['id']]['features']
                    made = [self.add('mirror', {'plane': 'XZ', 'offset': 0, 'features': seeds}, name, source)]
                    strategy = 'left-seed-feature-mirror-XZ'
            else:
                made = [self.add(kind, params, name, source)]
                strategy = 'unchanged-source-replay'
            self.mapping[identifier] = {'name': name, 'primary': made[-1] if made else None,
                                        'features': made, 'strategy': strategy}
        colors = data.get('props', {}).get('feature_colors', {})
        self.colors = {new: color for old, color in colors.items()
                       for new in self.mapping.get(old, {}).get('features', [])}
        self.orphans = {old: color for old, color in colors.items() if old not in by_id}
        self.validate_references()

    def remap(self, value, field=None):
        if isinstance(value, str) and re.fullmatch(r'f\d+', value):
            if value not in self.mapping or not self.mapping[value]['primary']:
                raise ValueError(f'Unresolved/omitted source reference {value} in {field}')
            return self.mapping[value]['primary']
        if isinstance(value, list):
            if field == 'features':
                result = []
                for old in value:
                    mapped = self.mapping[old]['features']
                    if not mapped:
                        raise ValueError(f'Feature reference {old} was intentionally omitted')
                    result.extend(mapped)
                return result
            return [self.remap(item, field) for item in value]
        if isinstance(value, dict):
            return {key: self.remap(item, key) for key, item in value.items()}
        return copy.deepcopy(value)

    def add(self, kind, params, name, source):
        arguments = dict(copy.deepcopy(params), name=name)
        command = commands.get(kind)
        commands.check(command, arguments)
        identifier = command.handler(SimpleNamespace(document=self.document), arguments)['id']
        if source.get('suppressed'):
            self.document.suppress(identifier, True)
        self.rows.append({'cmd': kind, 'args': arguments, 'id': identifier,
                          'source_id': source['id'], 'suppressed': bool(source.get('suppressed')),
                          'feature': copy.deepcopy(self.document.find(identifier))})
        return identifier

    def validate_references(self):
        for old, entry in self.mapping.items():
            if not entry['features'] and old in self.source.get('props', {}).get('feature_colors', {}):
                raise ValueError(f'Colored right auxiliary cannot be preserved: {entry["name"]}')

    def batches(self, size):
        batch, solids = [], 0
        for row in self.rows:
            batch.append(row)
            solids += row['cmd'] not in AUXILIARY and not row['cmd'].startswith('curve_')
            if solids >= size or len(batch) >= 16:
                yield batch
                batch, solids = [], 0
        if batch:
            yield batch

    def manifest(self):
        return {'strategy_version': 1, 'source_parameter_sha256': digest(self.source),
                'source_feature_sha256': {item['id']: digest(item) for item in self.source['features']},
                'source_props': self.source.get('props', {}), 'old_to_new': self.mapping,
                'mapped_feature_colors': self.colors, 'orphan_source_colors': self.orphans,
                'source_features': self.source['features'], 'planned_B_features': self.document.features,
                'strategy': {'body_roof': 'closed Catmull -> exact cubic Bezier positive Y halves; loft; XZ mirror',
                             'wheels_headlamps': 'left seeds; per-feature right mirrors',
                             'arches_and_later_details': 'all remaining source features replayed in source order',
                             'side_glass': 'existing feature mirrors replayed'},
                'limits': ['Curve segments preserve controls; loft equivalence must be measured by compare.py.',
                           'Unreferenced orphan colors are recorded, not assigned to unrelated B IDs.']}


def aliasize(value, aliases):
    if isinstance(value, str) and value in aliases:
        return '$' + value
    if isinstance(value, list):
        return [aliasize(item, aliases) for item in value]
    if isinstance(value, dict):
        return {key: aliasize(item, aliases) for key, item in value.items()}
    return copy.deepcopy(value)


def actions(plan, size, output):
    expected = Document()
    yield 'new', 'new_document', {}, expected.to_data()
    props = plan.source.get('props', {})
    if props.get('material'):
        expected.set_prop('material', props['material'])
        yield 'material', 'set_material', {'name': props['material']}, expected.to_data()
    if props.get('color'):
        expected.set_prop('color', props['color'])
        yield 'color', 'set_appearance', {'color': props['color']}, expected.to_data()
    for number, batch in enumerate(plan.batches(size), 1):
        steps = []
        aliases = set()
        for row in batch:
            steps.append({'cmd': row['cmd'], 'as': row['id'],
                          'args': aliasize(row['args'], aliases)})
            aliases.add(row['id'])
            expected.features.append(copy.deepcopy(row['feature']))
            expected._serial = int(row['id'][1:])
            if row['suppressed']:
                steps.append({'cmd': 'suppress_feature', 'args': {'id': '$' + row['id'], 'suppressed': True}})
        yield f'batch-{number:04}', 'batch', {'steps': steps}, expected.to_data()
        grouped = {}
        for row in batch:
            if row['id'] in plan.colors:
                grouped.setdefault(plan.colors[row['id']], []).append(row['id'])
        for index, (color, identifiers) in enumerate(grouped.items()):
            expected.props.setdefault('feature_colors', {}).update(dict.fromkeys(identifiers, color))
            yield f'paint-{number:04}-{index}', 'set_appearance', {'color': color, 'features': identifiers}, expected.to_data()
    yield 'final', 'save_document', {'path': str(output)}, expected.to_data()


def runtime(options, source, output, folder):
    progress = folder / 'progress.json'
    if options.resume:
        state = load_json(progress)
        if state['source'] != str(source) or state['output'] != str(output):
            raise RuntimeError('Resume paths differ from the journal')
        if options.batch_size != state['batch_size']:
            raise RuntimeError('Resume requires the original --batch-size')
    else:
        if not options.new_document:
            raise RuntimeError('--execute requires explicit --new-document')
        if progress.exists() or output.exists():
            raise RuntimeError('B/progress already exists; use --resume or a fresh --state-dir')
        state = {'source': str(source), 'output': str(output), 'batch_size': options.batch_size,
                 'done': [], 'pending': None}
    client = Client(options.port, options.timeout)
    try:
        model = client.call('get_model', brief=False)
        data = read_source(source)
        if options.resume:
            if state['source_sha256'] != digest(data):
                raise RuntimeError('A changed since this run; resume would mix parameter revisions')
        elif Path(model.get('path') or '').resolve() != source or model.get('unsaved_changes'):
            raise RuntimeError('Save the current A at its source path before --new-document')
        elif not live_matches_source(model, data):
            raise RuntimeError('Live A differs from saved A')
        plan = Plan(data)
        manifest = plan.manifest()
        if options.resume and state['plan_sha256'] != digest(manifest):
            raise RuntimeError('Strategy changed since checkpoint')
        state.update(source_sha256=digest(data), plan_sha256=digest(manifest))
        journal = Journal(folder, client, state)
        atomic_json(folder / 'strategy.json', manifest)
        if options.resume:
            pending = state.get('pending')
            checkpoint = state.get('checkpoint')
            saved = None
            if checkpoint and Path(checkpoint).exists():
                try:
                    saved = load_json(checkpoint)
                except (OSError, ValueError):
                    if not pending:
                        raise RuntimeError('Owned checkpoint is corrupt; inspect before resuming') from None
            if saved and digest(saved) != state['checkpoint_sha256']:
                raise RuntimeError('Checkpoint integrity failure')
            if pending:
                journal.reconcile()
            elif saved:
                if options.open_checkpoint:
                    if model.get('unsaved_changes'):
                        raise RuntimeError('Refusing to replace a modified window document')
                    journal.perform(f'restore-{len(state["done"]):04}', 'open_document',
                                    {'path': checkpoint}, saved)
                elif not same_features(model, saved) or Path(model.get('path') or '').resolve() != Path(checkpoint):
                    raise RuntimeError('Open the last checkpoint, or use --resume --open-checkpoint')
            elif state['done']:
                raise RuntimeError('Missing owned checkpoint')
            elif Path(model.get('path') or '').resolve() != source or model.get('unsaved_changes') or not live_matches_source(model, data):
                raise RuntimeError('Unstarted resume still requires the saved A in the window')
            observed = client.call('get_model', brief=False)
            if any(item['status'] not in ('ok', 'suppressed') for item in observed['features']):
                raise RuntimeError('Checkpoint contains a geometry failure; inspect it before proceeding')
        else:
            journal.record('start', source_sha256=state['source_sha256'], planned_features=len(plan.rows))
        atomic_json(folder / 'source_map.json', {'source_sha256': state['source_sha256'],
                    'old_to_new': plan.mapping, 'verified_ids': [],
                    'last_action': state['done'][-1] if state['done'] else None,
                    'checkpoint': state.get('checkpoint')})
        for key, command, arguments, expected in actions(plan, options.batch_size, output):
            if key in state['done']:
                continue
            if digest(read_source(source)) != state['source_sha256']:
                raise RuntimeError('A changed during the build; stopped at the last checkpoint')
            journal.perform(key, command, arguments, expected)
            atomic_json(folder / 'source_map.json', {'source_sha256': state['source_sha256'],
                        'old_to_new': plan.mapping, 'verified_ids': [item['id'] for item in expected['features']],
                        'last_action': key, 'checkpoint': state.get('checkpoint')})
        print(json.dumps({'complete': True, 'output': str(output), 'source_sha256': digest(data)}), flush=True)
    finally:
        client.close()


def self_test(source):
    import tempfile
    import unittest
    from genform.kernel import store
    from genform.kernel.model import rebuild as rebuild_module
    from genform.kernel.model.rebuild import rebuild
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    class SmallTests(unittest.TestCase):
        def test_atomic_json_sharing_retry(self):
            from unittest.mock import patch
            import alternate_runtime
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'progress.json'
                original_replace = os.replace
                calls = []
                def replace_once_locked(temporary, destination):
                    calls.append(destination)
                    if len(calls) == 1:
                        raise PermissionError(13, 'sharing violation', None, 32)
                    return original_replace(temporary, destination)
                with patch.object(alternate_runtime.os, 'replace', side_effect=replace_once_locked), \
                        patch.object(alternate_runtime.time, 'sleep') as pause:
                    atomic_json(target, {'done': ['batch-0029']})
                self.assertEqual(load_json(target), {'done': ['batch-0029']})
                self.assertEqual(len(calls), 2)
                pause.assert_called_once_with(0.05)

        def test_sections(self):
            data = read_source(source)
            plan = Plan(data)
            by_id = {item['id']: item for item in data['features']}
            errors = []
            for loft in data['features']:
                if loft['name'] not in HALVES:
                    continue
                count = HALVES[loft['name']]
                for identifier in loft['params']['sketches']:
                    params = by_id[identifier]['params']
                    converted = half_shapes(params, count)
                    original = _spline_beziers(params['shapes'][0]['points'], True)
                    for first, second in zip(original[:count], converted[:-1]):
                        self.assertEqual([tuple(point) for point in first[1:]], [tuple(point) for point in second['points']])
                        errors.extend(abs(left - right) for point_a, point_b in zip(sample(first, 100), sample(prims(second)[0], 100))
                                      for left, right in zip(point_a, point_b))
                    from genform.kernel.model.sketches import build_sketch
                    profile = build_sketch(dict(params, shapes=converted)).profile
                    self.assertTrue(BRepCheck_Analyzer(profile).IsValid())
            self.assertEqual(max(errors), 0)
            self.assertEqual(len(plan.mapping), len(data['features']))
            for row in plan.rows:
                if paired_left(row['args']['name'], {item['name'] for item in plan.source['features']}):
                    self.assertEqual(row['cmd'], 'mirror')
                    self.assertTrue(row['args']['features'])
            print(json.dumps({'section_coordinate_max_error_mm': max(errors), 'section_samples': len(errors) // 2,
                              'source_features': len(data['features']), 'B_planned_features': len(plan.rows)}))

        def test_circle_seed_mirror(self):
            rows = [{'id': 'f1', 'type': 'sketch', 'name': 'left', 'params': {
                'plane': 'XZ', 'offset': 20, 'shapes': [{'type': 'circle', 'cx': 3, 'cy': 4, 'r': 10}]}},
                {'id': 'f2', 'type': 'extrude', 'name': 'seed', 'params': {'sketch': 'f1', 'distance': -5}},
                {'id': 'f3', 'type': 'mirror', 'name': 'right', 'params': {'plane': 'XZ', 'features': ['f2']}}]
            body, _, status = rebuild(rows)
            self.assertTrue(all(value == 'ok' for value in status.values()), status)
            self.assertTrue(BRepCheck_Analyzer(body).IsValid())
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(body, props)
            import math
            self.assertAlmostEqual(props.Mass(), 2 * math.pi * 100 * 5, places=7)
            self.assertAlmostEqual(props.CentreOfMass().Y(), 0, places=9)

        def test_single_send_recovery(self):
            expected = Document().to_data()
            class Fake:
                def __init__(self):
                    self.calls = []
                    self.path = None
                def call(self, name, **arguments):
                    self.calls.append(name)
                    if name == 'new_document':
                        raise TimeoutError('applied; reply lost')
                    if name == 'get_model':
                        return {'features': [], 'rollback': None, 'path': self.path,
                                'unsaved_changes': False}
                    atomic_json(arguments['path'], expected)
                    self.path = arguments['path']
                    return {'ok': True}
            with tempfile.TemporaryDirectory() as folder:
                client = Fake()
                state = {'done': [], 'pending': None}
                journal = Journal(folder, client, state)
                journal.perform('new', 'new_document', {}, expected)
                journal.perform('new', 'new_document', {}, expected)
                self.assertEqual(client.calls.count('new_document'), 1)
                self.assertLess(client.calls.index('get_model'), client.calls.index('save_document'))
                self.assertEqual(client.path, state['checkpoint'])
                output = str(Path(folder) / 'final.gform')
                journal.perform('final', 'save_document', {'path': output}, expected)
                self.assertEqual(client.path, output)
                self.assertEqual(state['done'], ['new', 'final'])
                state['pending'] = {'key': 'bad', 'command': 'batch', 'arguments': {},
                                    'expected': dict(expected, features=[{'id': 'f1'}]), 'phase': 'command'}
                with self.assertRaises(RuntimeError):
                    journal.reconcile()
                self.assertNotIn('batch', client.calls)

    original_folder = store.folder
    store.folder = lambda: None
    try:
        success = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SmallTests)).wasSuccessful()
    finally:
        store.folder = original_folder
        rebuild_module._STEPS.clear()
        rebuild_module._SPARE.clear()
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--state-dir', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--resume', action='store_true')
    mode.add_argument('--self-test', action='store_true')
    parser.add_argument('--new-document', action='store_true')
    parser.add_argument('--open-checkpoint', action='store_true')
    parser.add_argument('--batch-size', type=int, default=3, choices=range(2, 7))
    parser.add_argument('--timeout', type=float, default=295)
    parser.add_argument('--port', type=int, default=int(os.environ.get('GENFORM_PORT', '9631')))
    options = parser.parse_args()
    if not 2 <= options.timeout <= 295:
        parser.error('--timeout must be between 2 and 295 seconds')
    if options.new_document and not options.execute or options.open_checkpoint and not options.resume:
        parser.error('--new-document needs --execute; --open-checkpoint needs --resume')
    source = options.source.resolve()
    output = source.with_name('porsche_911_992_method_b.gform')
    if source == output:
        parser.error('A and B must differ')
    folder = (options.state_dir or output.with_suffix('.run')).resolve()
    if options.self_test:
        return self_test(source)
    if options.execute or options.resume:
        runtime(options, source, output, folder)
    else:
        plan = Plan(read_source(source))
        manifest = plan.manifest()
        print(json.dumps({'offline_preview': True, 'source_parameter_sha256': digest(plan.source),
                          'manifest_sha256': digest(manifest),
                          'source_features': len(plan.source['features']), 'B_features': len(plan.rows),
                          'batches': len(list(plan.batches(options.batch_size))), 'output': str(output),
                          'orphan_colors': plan.orphans, 'strategies': manifest['strategy']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f'STOP: {error}', file=sys.stderr, flush=True)
        raise SystemExit(1)
