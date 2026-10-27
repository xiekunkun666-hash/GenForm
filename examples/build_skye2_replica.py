"""Build an exact SKYE 2 reference assembly from supplied STEP parts."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID

from genform.document import Document
from genform.kernel import build
from genform.kernel.ops.importing import _parts, read_step


PARTS = [('主体', 'body', '#414850'), ('底盖', 'cover', '#303740'), ('探头', 'probe', '#C2CAD2')]


def properties(shape):
    low, high = build.bounds(shape)
    mass = GProp_GProps()
    accuracy = BRepGProp.VolumeProperties_s(shape, mass, 1e-8, True, False)
    return {'bbox_min': low, 'bbox_max': high, 'size_mm': [upper - lower for lower, upper in zip(low, high)],
            'volume_mm3': mass.Mass(), 'integration_relative_error': accuracy,
            'solids': len(_parts(shape, TopAbs_SOLID)), 'faces': len(_parts(shape, TopAbs_FACE)),
            'valid': BRepCheck_Analyzer(shape).IsValid()}


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def generate(source, output):
    source, output = source.resolve(), output.resolve()
    source_files = [source / f'SKYE2_{name}_R20.step' for name, _, _ in PARTS]
    source_files.append(source / 'SKYE2_整机_R20.step')
    for path in source_files:
        if not path.is_file():
            raise FileNotFoundError(path)
    output.mkdir(parents=True, exist_ok=True)
    copies = output / 'source'
    copies.mkdir(exist_ok=True)
    for path in source_files:
        destination = copies / path.name
        if not destination.exists():
            shutil.copyfile(path, destination)
        if checksum(path) != checksum(destination):
            raise ValueError(f'Existing source copy differs: {destination}')

    rows, records, shapes = [], [], []
    whole_document = Document()
    for name, stem, color in PARTS:
        path = copies / f'SKYE2_{name}_R20.step'
        shape, note = read_step(str(path))
        reference = properties(shape)
        if not reference['valid'] or reference['solids'] != 1:
            raise ValueError(f'Invalid source solid: {name}')
        document = Document()
        document.add('import_step', {'path': str(path), 'op': 'add'}, f'SKYE 2 {name} · 原尺寸实体')
        document.props.update(color=color, reference={'product': 'CUAV SKYE 2', 'source_sha256': checksum(path),
                                                     'method': 'STEP exact geometry import', 'units': 'mm'})
        target = output / f'skye2_{stem}.gform'
        document.save(str(target))
        built, context, statuses = build.rebuild(document.features)
        measured = properties(built)
        if measured['faces'] != reference['faces'] or abs(measured['volume_mm3'] - reference['volume_mm3']) > 1e-5:
            raise ValueError(f'Imported geometry differs: {name}')
        rows.append({'name': f'SKYE 2 · {name}', 'file': target.name, 'move': [0, 0, 0], 'turn': [0, 0, 0]})
        records.append({'name': name, 'file': target.name, 'source': path.name, 'sha256': checksum(path),
                        'geometry': measured, 'note': note, 'statuses': statuses})
        shapes.append(built)
        identifier = whole_document.add('import_step', {'path': str(path), 'op': 'add'}, f'SKYE 2 {name}')
        whole_document.props.setdefault('feature_colors', {})[identifier] = color
        print(f'Built {name}: {measured["solids"]} solid, {measured["faces"]} faces', flush=True)

    assembly = {'format': 'genform-assembly', 'version': 1, 'parts': rows}
    write_json(output / 'SKYE2_复现装配.gasm', assembly)
    exploded = json.loads(json.dumps(assembly))
    exploded['parts'][1]['move'] = [0, 0, -25]
    exploded['parts'][2]['move'] = [-30, 0, 8]
    write_json(output / 'SKYE2_拆分查看.gasm', exploded)
    whole_document.save(str(output / 'SKYE2_整机复现.gform'))

    combined = build._compound(shapes)
    measured = properties(combined)
    reference, _ = read_step(str(copies / 'SKYE2_整机_R20.step'))
    reference_props = properties(reference)
    size_error = max(abs(first - second) for first, second in zip(measured['size_mm'], reference_props['size_mm']))
    volume_error = abs(measured['volume_mm3'] - reference_props['volume_mm3'])
    if size_error > 1e-5 or measured['faces'] != reference_props['faces'] or measured['solids'] != 3:
        raise ValueError('Assembly geometry does not match the reference structure')
    reference_solids = sorted((properties(solid) for solid in _parts(reference, TopAbs_SOLID)), key=lambda item: item['faces'])
    replica_solids = sorted((record['geometry'] for record in records), key=lambda item: item['faces'])
    comparisons = []
    for expected, actual in zip(reference_solids, replica_solids):
        boundary_error = max(abs(first - second) for key in ('bbox_min', 'bbox_max') for first, second in zip(expected[key], actual[key]))
        relative_volume_error = abs(expected['volume_mm3'] - actual['volume_mm3']) / expected['volume_mm3']
        comparisons.append({'faces': actual['faces'], 'bbox_max_error_mm': boundary_error,
                            'relative_volume_error': relative_volume_error})
        if boundary_error > 1e-5 or relative_volume_error > 1e-5:
            raise ValueError(f'Assembly source and separate parts differ: {comparisons[-1]}')
    for suffix in ('step', 'stl'):
        target = output / f'SKYE2_整机复现.{suffix}'
        with tempfile.TemporaryDirectory(prefix='skye2-export-') as folder:
            temporary = Path(folder) / f'skye2.{suffix}'
            build.export(whole_document.features, str(temporary))
            shutil.copyfile(temporary, target)
        if not target.is_file() or target.stat().st_size == 0:
            raise ValueError(f'Export failed: {target}')
        print(f'Exported {target.name}', flush=True)
    report = {'product': 'CUAV SKYE 2', 'website': 'https://www.cuav.net/skye-2/',
              'method': 'Exact STEP import, original component coordinates; original feature history unavailable',
              'official_size_mm': [101.9, 28.2, 29.9], 'parts': records, 'replica': measured,
              'reference': reference_props, 'size_max_error_mm': size_error, 'volume_difference_mm3': volume_error,
              'component_comparisons': comparisons, 'materials': 'Not assigned; display colors only',
              'limitations': ['No electronics, firmware or calibration reconstruction',
                              'Supplied CAD is not proof of manufacturing tolerances or physical performance']}
    write_json(output / 'verification.json', report)
    readme = f'''# SKYE 2 原尺寸复现工程

依据用户提供的雷迅 CUAV SKYE 2 R20 主体、底盖、探头及整机 STEP 建立。
官网：https://www.cuav.net/skye-2/

## 打开文件

- `SKYE2_复现装配.gasm`：默认整机，三个独立零件，可分别选中、移动、隐藏和打开修改。
- `SKYE2_拆分查看.gasm`：底盖下移 25 mm，探头前移 30 mm、上移 8 mm，便于观察接口；仅为展示位置。
- `SKYE2_整机复现.gform`：三个导入特征组成的单文档，可继续添加切除、孔等特征。
- `skye2_body.gform`、`skye2_cover.gform`、`skye2_probe.gform`：独立零件。
- `SKYE2_整机复现.step`：精确几何交换文件。
- `SKYE2_整机复现.stl`：网格交换文件，单位按毫米。
- `verification.json`：几何检查与输入文件 SHA-256。

## 核验

整机尺寸：{measured['size_mm'][0]:.4f} × {measured['size_mm'][1]:.4f} × {measured['size_mm'][2]:.4f} mm。
三个实体、{measured['faces']} 张面，与整机 STEP 的零件边界及曲面数量核对一致。
最大外形尺寸差：{size_error:.9g} mm。所有分件通过 OpenCascade 实体有效性检查。
保留原始坐标，不自动对齐或缩放。颜色仅用于区分外壳与金属探头，未推定实际材料。

## 建模范围

这是原始 STEP 精确几何导入形成的复现工程，不是恢复了原厂的草图、拉伸、放样等历史。
复杂曲面、原有孔位和细节来自提供的 STEP，可在导入实体之后继续建模。
源文件仅有三个机械实体，未虚构 PCB、传感器、加热器、电路、固件或标定结果。

`source/` 是原始输入的独立副本，原目录四份文件未修改。装配引用零件文件的相对路径；
零件内的导入特征引用本工程 `source/` 的绝对路径。若移动工程，运行项目中的
`examples/build_skye2_replica.py --source <原始STEP目录> --output <新工程目录>` 重新生成引用。
'''
    (output / 'README.md').write_text(readme, encoding='utf-8')
    print(json.dumps({'output': str(output), 'size_mm': measured['size_mm'], 'component_comparisons': comparisons}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    generate(options.source, options.output)
