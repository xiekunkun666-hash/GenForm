"""Offline, finite boundary comparison; status describes execution, never equivalence.

Run with python -B compare.py [A.gform B.gform] --report result.json.
Only a cache miss rebuilds JSON features. --self-test uses temporary tiny cylinders.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import OCP
from OCP.BinTools import BinTools
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.Extrema import Extrema_ExtFlag_MIN
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_ON, TopAbs_OUT, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shape
from OCP.gp import gp_Pnt, gp_Pnt2d
from genform.kernel.occ_compat import TopTools_IndexedMapOfShape, _as_edge, _as_face, _as_solid


def static(owner, name):
    return getattr(owner, name + '_s', None) or getattr(owner, name)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def engine_stamp():
    sources = [ROOT / 'genform' / name for name in
               ('kernel', 'sketchgeo', 'sketchgeom.py', 'planes.py', 'features.py', 'textpath.py')]
    files = sorted({file for source in sources for file in
                    (source.rglob('*.py') if source.is_dir() else [source])})
    stamp = hashlib.sha256()
    for file in files:
        stamp.update(encoded([file.relative_to(ROOT).as_posix(), digest(file.read_bytes())]))
    return {'ocp_version': OCP.__version__, 'kernel_stamp': stamp.hexdigest(),
            'script_sha256': digest(Path(__file__).read_bytes()), 'cache_schema': 1}


def parts(shape, kind):
    explorer = TopExp_Explorer(shape, kind)
    indexed = TopTools_IndexedMapOfShape()
    while explorer.More():
        indexed.Add(explorer.Current())
        explorer.Next()
    return [indexed.FindKey(index) for index in range(1, indexed.Extent() + 1)]


def compound(shapes):
    result, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result


def xyz(point):
    coordinates = [point.X(), point.Y(), point.Z()]
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError('Non-finite sample coordinates')
    return coordinates


def measures(shape):
    box, volume, area = Bnd_Box(), GProp_GProps(), GProp_GProps()
    static(BRepBndLib, 'AddOptimal')(shape, box, False, False)
    if box.IsVoid() or box.IsOpen():
        raise ValueError('Empty or unbounded geometry')
    static(BRepGProp, 'VolumeProperties')(shape, volume, 1e-8, True, False)
    static(BRepGProp, 'SurfaceProperties')(shape, area, 1e-8, False)
    bounds = xyz(box.CornerMin()) + xyz(box.CornerMax())
    result = {'bounds': {'min': bounds[:3], 'max': bounds[3:]}, 'volume': volume.Mass(),
              'area': area.Mass(), 'valid': bool(BRepCheck_Analyzer(shape).IsValid()),
              'solid_count': len(parts(shape, TopAbs_SOLID)), 'face_count': len(parts(shape, TopAbs_FACE))}
    encoded(result)
    return result


def rebuild_json(document, cache):
    previous = {name: os.environ.get(name) for name in ('GENFORM_CACHE', 'GENFORM_SETTINGS')}
    os.environ.update(GENFORM_CACHE='off', GENFORM_SETTINGS=str(cache / 'settings.json'))
    module, callback = None, None
    try:
        from genform.kernel.build import rebuild
        module = importlib.import_module('genform.kernel.model.rebuild')
        callback = module.on_step
        module.on_step = lambda index, total, name: print(f'  rebuild {index + 1}/{total}: {name}', flush=True)
        shape, _, status = rebuild(document['features'], upto=document.get('upto'))
        return shape, status
    finally:
        if module is not None:
            module.on_step = callback
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def load_input(path, cache, engine, factory=None):
    began = time.perf_counter()
    record = {'path': str(path), 'source_sha256': None, 'cache_hit': False, 'errors': []}
    shape = None
    try:
        source = path.read_bytes()
        record['source_sha256'] = digest(source)
        document = json.loads(source.decode('utf-8-sig'))
        features = document['features']
        identifiers = [feature['id'] for feature in features]
        if not features or len(set(identifiers)) != len(identifiers):
            raise ValueError('Expected nonempty features with unique IDs')
        identity = {'source_sha256': record['source_sha256'], **engine}
        key = digest(encoded(identity))
        geometry, manifest = cache / (key + '.brep'), cache / (key + '.json')
        record['cache_key'] = key
        try:
            envelope = json.loads(manifest.read_bytes())
            payload = envelope['payload']
            if digest(encoded(payload)) != envelope['sha256'] or payload['identity'] != identity:
                raise ValueError('Metadata hash/identity mismatch')
            binary = geometry.read_bytes()
            if digest(binary) != payload['brep_sha256']:
                raise ValueError('BRep content hash mismatch')
            if binary:
                shape = TopoDS_Shape()
                static(BinTools, 'Read')(shape, io.BytesIO(binary))
                if shape.IsNull():
                    raise ValueError('Cached BRep is null')
            record['cache_hit'] = True
            print(f'{path.name}: cache hit', flush=True)
        except Exception as error:
            record['cache_miss_reason'] = f'{type(error).__name__}: {error}'
            print(f'{path.name}: cache miss; rebuilding', flush=True)
            shape, status = factory(document, cache) if factory else rebuild_json(document, cache)
            payload = {'identity': identity, 'status': status, 'metrics': None, 'errors': []}
            stream = io.BytesIO()
            if shape is not None and not shape.IsNull():
                try:
                    payload['metrics'] = measures(shape)
                except Exception as error:
                    payload['errors'].append(f'Measurement failed: {type(error).__name__}: {error}')
                static(BinTools, 'Write')(shape, stream)
            else:
                payload['errors'].append('Rebuild produced no geometry')
            binary = stream.getvalue()
            payload['brep_sha256'] = digest(binary)
            atomic(geometry, binary)
            atomic(manifest, encoded({'payload': payload, 'sha256': digest(encoded(payload))}))
        record.update(status=payload['status'], metrics=payload['metrics'], brep_sha256=payload['brep_sha256'])
        record['errors'].extend(payload['errors'])
        for identifier in identifiers:
            if record['status'].get(identifier) not in ('ok', 'suppressed'):
                record['errors'].append(f'{identifier}: {record["status"].get(identifier, "missing status")}')
        metrics = record['metrics']
        if metrics and (not metrics['valid'] or not metrics['solid_count'] or not metrics['face_count']):
            record['errors'].append('Invalid BRep or missing solids/faces')
        if path.read_bytes() != source:
            record['errors'].append('Source changed during processing')
    except Exception as error:
        record['errors'].append(f'{type(error).__name__}: {error}')
    record['runtime_seconds'] = time.perf_counter() - began
    return shape, record


def sample_faces(shape, grid, tolerance):
    samples, coverage = [], []
    faces = parts(shape, TopAbs_FACE)
    for face_index, raw_face in enumerate(faces, 1):
        face, seen = _as_face(raw_face), set()
        detail = {'face': face_index, 'uv_accepted': 0, 'uv_rejected': 0,
                  'vertex_samples': 0, 'edge_samples': 0, 'errors': []}
        def add(point, kind):
            coordinates = xyz(point)
            key = tuple(coordinates)
            if key not in seen:
                samples.append({'point': coordinates, 'face': face_index, 'kind': kind})
                seen.add(key)
                detail[kind] += 1
        try:
            umin, umax, vmin, vmax = static(BRepTools, 'UVBounds')(face)
            if not all(math.isfinite(value) and abs(value) < 1e100 for value in (umin, umax, vmin, vmax)):
                raise ValueError('Non-finite UV domain')
            surface = BRepAdaptor_Surface(face, True)
            for uindex in range(grid[0]):
                for vindex in range(grid[1]):
                    upos = umin + (umax - umin) * (uindex + 0.5) / grid[0]
                    vpos = vmin + (vmax - vmin) * (vindex + 0.5) / grid[1]
                    state = BRepClass_FaceClassifier(face, gp_Pnt2d(upos, vpos), tolerance).State()
                    if state in (TopAbs_IN, TopAbs_ON):
                        add(surface.Value(upos, vpos), 'uv_accepted')
                    else:
                        detail['uv_rejected'] += 1
        except Exception as error:
            detail['errors'].append(f'UV: {type(error).__name__}: {error}')
        try:
            for vertex in parts(face, TopAbs_VERTEX):
                add(static(BRep_Tool, 'Pnt')(static(TopoDS, 'Vertex')(vertex)), 'vertex_samples')
            if not detail['uv_accepted']:
                for edge in parts(face, TopAbs_EDGE):
                    curve = BRepAdaptor_Curve(_as_edge(edge))
                    parameter = (curve.FirstParameter() + curve.LastParameter()) / 2
                    if math.isfinite(parameter):
                        add(curve.Value(parameter), 'edge_samples')
        except Exception as error:
            detail['errors'].append(f'Boundary: {type(error).__name__}: {error}')
        detail['samples'] = len(seen)
        coverage.append(detail)
        if face_index % max(1, len(faces) // 10) == 0:
            print(f'  sampling faces {face_index}/{len(faces)}', flush=True)
    return samples, {'face_count': len(faces), 'covered_faces': sum(bool(row['samples']) for row in coverage),
                     'failed_faces': [row['face'] for row in coverage if not row['samples']],
                     'failed_face_count': sum(not row['samples'] for row in coverage),
                     'boundary_only_faces': [row['face'] for row in coverage if not row['uv_accepted']],
                     'evaluation_error_count': sum(len(row['errors']) for row in coverage),
                     'sample_count': len(samples), 'per_face': coverage}


def classifier_state(classifiers, point, tolerance):
    states = []
    for classifier in classifiers:
        classifier.Perform(point, tolerance)
        states.append(classifier.State())
    if TopAbs_IN in states:
        return 'inside'
    if TopAbs_ON in states:
        return 'on'
    return 'outside' if states and all(state == TopAbs_OUT for state in states) else 'unknown'


def direction(samples, target, tolerance, classify, label):
    solver = BRepExtrema_DistShapeShape()
    solver.SetFlag(Extrema_ExtFlag_MIN)
    solver.SetDeflection(tolerance)
    solver.LoadS2(compound(parts(target, TopAbs_FACE)))
    classifiers = [BRepClass3d_SolidClassifier(_as_solid(solid)) for solid in parts(target, TopAbs_SOLID)] if classify else []
    values, worst, errors = [], None, []
    states = dict.fromkeys(('inside', 'outside', 'on', 'unknown'), 0) if classify else None
    for index, sample in enumerate(samples, 1):
        try:
            point = gp_Pnt(*sample['point'])
            solver.LoadS1(BRepBuilderAPI_MakeVertex(point).Vertex())
            solver.Perform()
            if not solver.IsDone() or solver.NbSolution() < 1:
                raise ValueError('Distance solver did not finish')
            value = solver.Value()
            if not math.isfinite(value) or value < 0:
                raise ValueError('Invalid distance')
            nearest = xyz(solver.PointOnShape2(1))
            if classify:
                states[classifier_state(classifiers, point, tolerance)] += 1
            values.append(value)
            if worst is None or value > worst['distance']:
                worst = {**sample, 'distance': value, 'target_point': nearest}
        except Exception as error:
            errors.append({'sample': index, **sample, 'error': f'{type(error).__name__}: {error}'})
        if index % max(100, len(samples) // 10) == 0 or index == len(samples):
            print(f'  {label}: distances {index}/{len(samples)}', flush=True)
    ordered = sorted(values)
    result = {'attempted': len(samples), 'successful': len(values), 'failed': len(errors),
              'errors': errors, 'classification': states, 'worst': worst, 'statistics': None}
    if ordered:
        position = (len(ordered) - 1) * 0.95
        lower = math.floor(position)
        percentile = ordered[lower] + (ordered[math.ceil(position)] - ordered[lower]) * (position - lower)
        result['statistics'] = {'min': ordered[0], 'mean': math.fsum(values) / len(values),
                                'rms': math.sqrt(math.fsum(value * value for value in values) / len(values)),
                                'p95': percentile, 'max': ordered[-1]}
    return result


def execute(args, factory=None):
    began = time.perf_counter()
    paths, report = [Path(args.first).resolve(), Path(args.second).resolve()], Path(args.report).resolve()
    cache = Path(args.cache_dir).resolve() if args.cache_dir else report.parent / (report.stem + '.cache')
    if any(report == source or report.is_relative_to(source.parent) or cache.is_relative_to(source.parent) for source in paths):
        raise ValueError('Report/cache must be outside the source directories')
    if report == cache or report.is_relative_to(cache):
        raise ValueError('Report must be outside its cache directory')
    grid = args.uv_grid or (math.ceil(math.sqrt(args.samples_per_face)),
                            math.ceil(args.samples_per_face / math.ceil(math.sqrt(args.samples_per_face))))
    result = {'ok': False, 'status': 'failed', 'equivalence': 'not_asserted', 'units': 'mm, mm^2, mm^3',
              'parameters': {'uv_grid': list(grid), 'tolerance': args.tolerance, 'classify': args.classify,
                             'cache_dir': str(cache), 'distance_target': 'compound of all target faces; MIN'},
              'inputs': [], 'sampling': {}, 'distances': {}, 'errors': [],
              'limitations': ['Finite UV samples plus boundary points are not a strict Hausdorff distance.',
                              'No assertion of exact geometric equivalence, even when all sampled distances are zero.',
                              'UV spacing is not area-uniform; small trims/interior differences may be missed.',
                              'Boundary-only faces have no confirmed interior UV coverage; numerical tolerances apply.',
                              'All BRep faces, including cavity/internal component faces, form the distance target.']}
    try:
        result['engine'] = engine_stamp()
        loaded = [load_input(path, cache, result['engine'], factory) for path in paths]
        result['inputs'] = [record for _, record in loaded]
        for index, (_, record) in enumerate(loaded):
            result['errors'].extend(f'input {index + 1}: {error}' for error in record['errors'])
        if all(shape is not None and not shape.IsNull() and record.get('metrics') for shape, record in loaded):
            first, second = [record['metrics'] for _, record in loaded]
            result['delta_b_minus_a'] = {'bounds': {side: [right - left for left, right in zip(first['bounds'][side], second['bounds'][side])]
                                                  for side in ('min', 'max')},
                                         'volume': second['volume'] - first['volume'], 'area': second['area'] - first['area'],
                                         'relative_volume': (second['volume'] - first['volume']) / first['volume'] if first['volume'] else None,
                                         'relative_volume_definition': '(B.volume - A.volume) / A.volume; null if A.volume is zero'}
            for index, label in enumerate(('a_to_b', 'b_to_a')):
                print(f'{label}: sampling and boundary distances', flush=True)
                samples, coverage = sample_faces(loaded[index][0], grid, args.tolerance)
                result['sampling'][label] = coverage
                result['distances'][label] = direction(samples, loaded[1 - index][0], args.tolerance, args.classify, label)
                if coverage['failed_faces'] or coverage['evaluation_error_count'] or not samples or result['distances'][label]['failed']:
                    result['errors'].append(f'{label}: sampling/distance failure; inspect coverage and errors')
        else:
            result['errors'].append('Comparison unavailable: missing geometry/metrics')
        for path, record in zip(paths, result['inputs']):
            if record['source_sha256'] and digest(path.read_bytes()) != record['source_sha256']:
                result['errors'].append(f'Source changed during comparison: {path}')
    except Exception as error:
        result['errors'].append(f'{type(error).__name__}: {error}')
    result.update(ok=not result['errors'], status='completed' if not result['errors'] else 'failed',
                  runtime_seconds=time.perf_counter() - began)
    atomic(report, json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8'))
    print(f'{result["status"]}: {report} ({result["runtime_seconds"]:.3f}s)', flush=True)
    return result


def self_test():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Trsf, gp_Vec
    def tiny(document, cache):
        seed = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(3, 0, 0), gp_Dir(0, 0, 1)), 1, 2).Shape()
        mirror = gp_Trsf()
        mirror.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)))
        wheels = compound([seed, BRepBuilderAPI_Transform(seed, mirror, True).Shape()])
        shift = gp_Trsf()
        shift.SetTranslation(gp_Vec(document['features'][0]['params']['dx'], 0, 0))
        return BRepBuilderAPI_Transform(wheels, shift, True).Shape(), {'seed': 'ok'}
    with tempfile.TemporaryDirectory(prefix='genform-compare-') as temporary:
        directory = Path(temporary)
        source = directory / 'sources'
        source.mkdir()
        first, second = source / 'a.gform', source / 'b.gform'
        document = {'features': [{'id': 'seed', 'type': 'self_test_cylinders', 'params': {'dx': 0}}]}
        first.write_bytes(encoded(document))
        second.write_bytes(encoded(document))
        args = parser().parse_args([str(first), str(second), '--report', str(directory / 'report.json'), '--uv-grid', '4', '4', '--classify'])
        same = execute(args, tiny)
        assert same['ok'] and [row['cache_hit'] for row in same['inputs']] == [False, True]
        assert all(row['statistics']['max'] < 1e-6 for row in same['distances'].values())
        assert all(row['metrics']['solid_count'] == 2 and row['metrics']['valid'] for row in same['inputs'])
        assert all(row['sample_count'] > 0 and not row['failed_faces'] for row in same['sampling'].values())
        assert all(sum(face['uv_rejected'] for face in row['per_face']) > 0 for row in same['sampling'].values())
        command = [sys.executable, '-B', str(Path(__file__).resolve()), str(first), str(second), '--report', args.report, '--uv-grid', '4', '4', '--classify']
        restarted = subprocess.run(command, capture_output=True, text=True, timeout=60)
        print(restarted.stdout, end='', flush=True)
        assert restarted.returncode == 0, restarted.stderr
        assert all(row['cache_hit'] for row in json.loads(Path(args.report).read_bytes())['inputs'])
        document['features'][0]['params']['dx'] = 0.5
        second.write_bytes(encoded(document))
        shifted = execute(args, tiny)
        assert shifted['ok'] and [row['cache_hit'] for row in shifted['inputs']] == [True, False]
        assert all(row['statistics']['max'] > 0.1 for row in shifted['distances'].values())
        assert abs(shifted['delta_b_minus_a']['bounds']['min'][0] - 0.5) < 1e-6
        shape, _ = tiny(json.loads(first.read_bytes()), directory)
        interior = direction([{'point': [3, 0, 1], 'face': 0, 'kind': 'regression'}], shape, 1e-7, True, 'interior')
        assert abs(interior['statistics']['min'] - 1) < 1e-6 and interior['classification']['inside'] == 1
        cache = directory / 'report.cache'
        altered = {**same['engine'], 'kernel_stamp': 'changed'}
        assert not load_input(first, cache, altered, tiny)[1]['cache_hit']
        altered = {**same['engine'], 'ocp_version': 'changed'}
        assert not load_input(first, cache, altered, tiny)[1]['cache_hit']
        key = shifted['inputs'][1]['cache_key']
        (cache / (key + '.brep')).write_bytes(b'partial')
        repaired = execute(args, tiny)
        assert repaired['ok'] and not repaired['inputs'][1]['cache_hit']
        assert 'hash mismatch' in repaired['inputs'][1]['cache_miss_reason']
        (cache / (key + '.json')).write_bytes(b'{')
        assert not execute(args, tiny)['inputs'][1]['cache_hit']
        manifest = cache / (key + '.json')
        tampered = json.loads(manifest.read_bytes())
        tampered['payload']['metrics']['volume'] += 1
        manifest.write_bytes(encoded(tampered))
        assert 'Metadata hash' in execute(args, tiny)['inputs'][1]['cache_miss_reason']
        second.write_bytes(b'{')
        failed = execute(args, tiny)
        assert not failed['ok'] and failed['errors'] and json.loads(Path(args.report).read_bytes())['status'] == 'failed'
        rejected = subprocess.run(command, capture_output=True, text=True, timeout=60)
        print(rejected.stdout, end='', flush=True)
        assert rejected.returncode == 1 and not json.loads(Path(args.report).read_bytes())['ok']
    print('SELF-TEST PASSED: mirrored cylinders, identity/translation, interior boundary, restart cache, source/kernel/OCP invalidation, corruption, failure JSON', flush=True)


def positive(value):
    number = int(value)
    if not 1 <= number <= 1000000:
        raise argparse.ArgumentTypeError('Expected integer in [1, 1000000]')
    return number


def parser():
    command = argparse.ArgumentParser(description=__doc__)
    models = ROOT / 'models' / 'porsche_911_992'
    command.add_argument('first', nargs='?', default=str(models / 'porsche_911_992.gform'))
    command.add_argument('second', nargs='?', default=str(models / 'porsche_911_992_method_b.gform'))
    command.add_argument('--report', default='porsche_911_comparison.json')
    command.add_argument('--cache-dir', help='Dedicated cache; default: <report parent>/<report stem>.cache')
    sampling = command.add_mutually_exclusive_group()
    sampling.add_argument('--samples-per-face', type=positive, default=36, help='UV budget rounded up to a rectangular grid (default: 36)')
    sampling.add_argument('--uv-grid', nargs=2, type=positive, metavar=('U', 'V'))
    command.add_argument('--tolerance', type=float, default=1e-7, help='Classifier and distance numerical tolerance in mm')
    command.add_argument('--classify', action='store_true', help='Classify samples against target solids: inside/outside/on/unknown')
    command.add_argument('--self-test', action='store_true', help='Only tiny geometry in TemporaryDirectory; no model rebuild')
    return command


def main():
    command = parser()
    args = command.parse_args()
    if not math.isfinite(args.tolerance) or args.tolerance <= 0:
        command.error('--tolerance must be finite and positive')
    try:
        if args.self_test:
            self_test()
            return 0
        return 0 if execute(args)['ok'] else 1
    except Exception as error:
        print(f'FAILED: {type(error).__name__}: {error}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
