"""Complete visible SKYE 2 mechanical details with explicit evidence levels."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.TopAbs import TopAbs_IN, TopAbs_OUT
from OCP.gp import gp_Pnt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build_skye2_replica import checksum, properties, write_json
from genform.document import Document
from genform.kernel import build
from genform.kernel.ops.importing import read_step


MOUNTS = [(-13.6, -12.15148874334), (-22.63, -12.15148874334),
          (-13.6, 11.64851125666), (-22.63, 11.64851125666)]
PROBE_DIRECTION = np.array([0.9999294285856908, 0, -0.011880145129336328])
PROBE_MOUTH = np.array([-101.8214276355, -0.269278046942, 20.787740084594])
MOUTH_RADIUS = 2.926999600466


def plane(document, origin, normal, name):
    return document.add('plane', {'origin': [list(origin)], 'normal': [list(normal)], 'offset': 0}, name)


def profile(document, origin, normal, shapes, distance, name, operation='cut'):
    support = plane(document, origin, normal, name + ' · 基准面')
    sketch = document.add('sketch', {'plane': support, 'shapes': shapes}, name + ' · 轮廓')
    return document.add('extrude', {'sketch': sketch, 'distance': distance, 'op': operation}, name)


def circle(document, origin, normal, radius, depth, name, operation='cut'):
    return profile(document, origin, normal, [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': radius}], depth, name, operation)


def rectangle(document, origin, normal, width, height, depth, name, operation='cut'):
    if abs(normal[2]) > 0.9:
        width, height = height, width
    return profile(document, origin, normal, [{'type': 'rect', 'cx': 0, 'cy': 0, 'w': width, 'h': height}], depth, name, operation)


def at(shape, point):
    return BRepClass3d_SolidClassifier(shape, gp_Pnt(*map(float, point)), 1e-6).State()


def check_mounts(shapes):
    classifiers = [BRepClass3d_SolidClassifier(shape) for shape in shapes]
    count = 0
    for center_x, center_y in MOUNTS:
        for altitude in np.linspace(-3.7, 3.0, 8):
            for radius in (0, 1.3, 1.9):
                for angle in np.linspace(0, 2 * math.pi, 8, endpoint=False):
                    point = [center_x + radius * math.cos(angle), center_y + radius * math.sin(angle), altitude]
                    for classifier in classifiers:
                        classifier.Perform(gp_Pnt(*map(float, point)), 1e-6)
                        if classifier.State() == TopAbs_IN:
                            raise ValueError(f'Mounting hole obstructed: {point}')
                    count += 1
    return count


def generate(source, output, reference):
    source, output, reference = source.resolve(), output.resolve(), reference.resolve()
    output.mkdir(parents=True, exist_ok=True)
    copies = output / 'source'
    copies.mkdir(exist_ok=True)
    for name in ('主体', '底盖', '探头', '整机'):
        original = source / f'SKYE2_{name}_R20.step'
        target = copies / original.name
        if not target.exists():
            shutil.copyfile(original, target)
        if checksum(original) != checksum(target):
            raise ValueError(f'Source mismatch: {target}')
    references = output / 'reference'
    references.mkdir(exist_ok=True)
    for path in reference.glob('*'):
        if path.is_file():
            shutil.copyfile(path, references / path.name)

    documents = {}
    for name, stem in [('主体', 'body'), ('底盖', 'cover'), ('探头', 'probe')]:
        document = Document()
        document.add('import_step', {'path': str(copies / f'SKYE2_{name}_R20.step'), 'op': 'add'}, f'R20 {name} · 不完整外形基体')
        document.props.update(color='#51585F', reference={'method': 'Source STEP plus editable mechanical details',
                                                        'website': 'https://www.cuav.net/skye-2/', 'units': 'mm'})
        documents[stem] = document

    for stem in ('body', 'cover'):
        document = documents[stem]
        sketch = document.add('sketch', {'plane': 'XY', 'offset': -4.1, 'shapes': [{'type': 'circle', 'cx': x, 'cy': y, 'r': 2}
                                                                   for x, y in MOUNTS]}, '官网 4×Ø4 · 四孔轮廓')
        document.add('extrude', {'sketch': sketch, 'distance': 7.4, 'op': 'cut'}, '官网 Ø4 安装通孔 · 全厚切除')

    body = documents['body']
    circle(body, [-12, -5.153858539, 12.7], [0, 1, 0], 3.2, 1.4, '照片补建 · 侧圆凹区 Ø6.4 深1.3（估算）')
    probe = documents['probe']
    circle(probe, PROBE_MOUTH - 0.1 * PROBE_DIRECTION, PROBE_DIRECTION, 2.3, 63.1,
           '前口阶梯孔道 · 内径Ø4.6延伸至后端（推定）')
    rectangle(body, [-46.5, -5.207298, 20.46], [0, 1, 0], 2.6, 2.6, 1.0,
              '照片补建 · 单侧方窗2.6×2.6（估算）')
    circle(body, [-46.5, -5.207298, 20.46], [0, 1, 0], 0.38, 1.5,
           '照片补建 · 方窗中心小凹孔Ø0.76（估算）')

    circle(body, PROBE_MOUTH + 50 * PROBE_DIRECTION, PROBE_DIRECTION, 2.3, 22,
           '对接孔道 · 内径Ø4.6与参考壳腔连通（推定）')
    cavity = body.add('sketch', {'plane': 'XZ', 'offset': -2.75, 'shapes': [
        {'type': 'polygon', 'points': [[-36, 3.2], [-4, 3.2], [-4, 8], [-10, 15.5],
                                      [-18, 20], [-34.2, 21.8], [-36, 21.5]]}]},
        '壳内参考腔 · 截面及壁厚为推定')
    body.add('extrude', {'sketch': cavity, 'distance': 6, 'op': 'cut'}, '壳内参考腔 · 宽6mm（推定）')
    circle(body, [-1.8, -0.25148874334, 14], [0, 0, -1], 0.5, 5,
           '官网俯视尾端小孔 · Ø1深至Z9（位置与深度估算）')
    circle(body, [-12, -3.853858539, 12.7], [0, 1, 0], 2.2, 1.3,
           '硅胶塞下真实开孔 · 连通内腔Ø4.4（用户确认结构，孔径估算）')

    plug = Document()
    circle(plug, [-12, -4.953858539, 12.7], [0, 1, 0], 2.82, 1.2,
           '硅胶塞帽 · Ø5.64止挡肩（外形估算）', 'add')
    circle(plug, [-12, -4.153858539, 12.7], [0, 1, 0], 2.18, 1.3,
           '硅胶塞插入段 · Ø4.36（参考配合，非密封认证）', 'add')
    rectangle(plug, [-12, -5.0, 12.7], [0, 1, 0], 4.2, 0.85, 0.6,
              '照片补建 · 横向一字凹槽（估算）')
    plug.props['color'] = '#252A30'
    plug.props['material'] = '硅胶'
    plug.props['reference'] = {'material_source': '用户确认：带一字槽的硅胶塞，下面有孔',
                               'density_hardness_grade': '未确认，不使用通用橡胶密度代替',
                               'hole_diameter_mm': 4.4, 'stem_diameter_mm': 4.36,
                               'fit_status': '参考几何配合；未模拟弹性压缩或验证密封'}
    documents['side_plug'] = plug

    connector = Document()
    rectangle(connector, [-23.35, -0.17, -3.5], [0, 0, 1], 9.4, 5.8, 4.7,
              '底部四针连接器 · 参考包络9.4×5.8（估算）', 'add')
    rectangle(connector, [-23.35, -0.17, -3.6], [0, 0, 1], 7.6, 3.6, 3.3,
              '连接器插口 · 外观参考（估算）')
    flange = connector.add('sketch', {'plane': 'XY', 'offset': -1.8, 'shapes': [
        {'type': 'rect', 'cx': -23.35, 'cy': -0.17, 'w': 12.6, 'h': 8.6},
        {'type': 'rect', 'cx': -23.35, 'cy': -0.17, 'w': 7.6, 'h': 3.6}]},
        '连接器固定肩台 · 示意轮廓（推定）')
    connector.add('extrude', {'sketch': flange, 'distance': 0.9, 'op': 'add'},
                  '连接器固定肩台 · 承托于底盖（推定）')
    connector.add('import_step', {'path': str(output / 'geometry' / 'cover.step'), 'op': 'cut'},
                  '固定肩台避让底盖 · 精确扣除交叠')
    connector.props['color'] = '#C8CAC4'
    documents['connector'] = connector
    for index in range(4):
        contact = Document()
        rectangle(contact, [-25.15 + index * 1.2, -0.17, -2.8], [0, 0, 1], 0.35, 0.6, 2.5,
                  f'4针触点 {index + 1} · 间距1.2（估算）', 'add')
        contact.props['color'] = '#C5AB72'
        documents[f'contact_{index + 1}'] = contact

    names = {'body': '主体 · 安装通孔、侧凹区及方窗', 'cover': '底盖 · 安装通孔', 'probe': '探头 · 前口深腔',
             'side_plug': '可拆硅胶塞 · 用户确认结构', 'connector': '底部连接器 · 外观估算'}
    rows, records, built_shapes, export_features = [], [], {}, []
    generated = output / 'geometry'
    generated.mkdir(exist_ok=True)
    whole = Document()
    for stem, document in documents.items():
        shape, context, statuses = build.rebuild(document.features)
        for identifier, status in statuses.items():
            if status != 'ok':
                raise ValueError(f'{stem}: {identifier}: {status}')
        measured = properties(shape)
        if not measured['valid'] or measured['solids'] != 1:
            raise ValueError(f'Invalid completed component: {stem}')
        built_shapes[stem] = shape
        target = output / f'skye2_{stem}.gform'
        document.save(str(target))
        label = names.get(stem, stem.replace('contact_', '触点 '))
        rows.append({'name': label, 'file': target.name, 'move': [0, 0, 0], 'turn': [0, 0, 0]})
        exported = generated / f'{stem}.step'
        with tempfile.TemporaryDirectory(prefix='skye2-detail-') as folder:
            temporary = Path(folder) / 'part.step'
            build.export(document.features, str(temporary))
            shutil.copyfile(temporary, exported)
        identifier = whole.add('import_step', {'path': str(exported), 'op': 'add'}, label)
        whole.props.setdefault('feature_colors', {})[identifier] = document.props['color']
        records.append({'name': label, 'file': target.name, 'geometry': measured, 'features': len(document.features),
                        'statuses': statuses})
        print(f'Built {stem}: {len(document.features)} features', flush=True)

    test_count = check_mounts([built_shapes['body'], built_shapes['cover']])
    forward_checks = []
    for distance in (2, 5, 10, 18, 30, 45, 51, 54, 60, 65, 70):
        point = PROBE_MOUTH + distance * PROBE_DIRECTION
        if any(at(built_shapes[stem], point) == TopAbs_IN for stem in ('probe', 'body')):
            raise ValueError(f'Front cavity blocked: {distance}')
        forward_checks.append({'distance_from_mouth_mm': distance, 'state': 'outside'})
    assembly_shape = build._compound([built_shapes[stem] for stem in documents])
    measured = properties(assembly_shape)
    if max(abs(actual - expected) for actual, expected in zip(measured['size_mm'], [101.9, 28.2, 29.9])) > 0.001:
        raise ValueError('Outer envelope changed')
    assembly = {'format': 'genform-assembly', 'version': 1, 'parts': rows}
    write_json(output / 'SKYE2_复现装配.gasm', assembly)
    exploded = json.loads(json.dumps(assembly))
    exploded['parts'][1]['move'] = [0, 0, -25]
    exploded['parts'][2]['move'] = [-30, 0, 8]
    exploded['parts'][3]['move'] = [0, -17, 0]
    for row in exploded['parts'][4:]:
        row['move'] = [0, 0, -38]
    write_json(output / 'SKYE2_拆分查看.gasm', exploded)
    unplugged = json.loads(json.dumps(assembly))
    unplugged['parts'][3]['move'] = [0, -17, 0]
    write_json(output / 'SKYE2_拔塞查看.gasm', unplugged)
    whole.save(str(output / 'SKYE2_整机复现.gform'))
    for suffix in ('step', 'stl'):
        with tempfile.TemporaryDirectory(prefix='skye2-complete-') as folder:
            temporary = Path(folder) / f'completed.{suffix}'
            build.export(whole.features, str(temporary))
            shutil.copyfile(temporary, output / f'SKYE2_整机复现.{suffix}')

    changes = [
        {'feature': '四个安装通孔', 'evidence': '官网尺寸图4×Ø4 mm；孔中心沿用源STEP', 'diameter_mm': 4,
         'centers_xy_mm': MOUNTS, 'verified_sample_count': test_count},
        {'feature': '探头前口及延伸孔道', 'evidence': '官网确认前端开口；口部Ø5.854沿用源STEP；内部Ø4.6孔道及壳内参考腔均为推定',
         'mouth_diameter_mm': 2 * MOUTH_RADIUS, 'reference_bore_diameter_mm': 4.6,
         'probe_cut_length_mm': 63.1, 'axis': PROBE_DIRECTION.tolist(), 'samples': forward_checks},
        {'feature': '侧面硅胶塞及塞下开孔', 'evidence': '用户确认是硅胶塞，下面有洞；壳壁开孔连内腔，未贯穿对侧壳壁；尺寸为参考估算',
         'center_xz_mm': [-12, 12.7], 'recess_diameter_mm': 6.4, 'recess_depth_mm': 1.3,
         'hole_diameter_mm': 4.4, 'stem_diameter_mm': 4.36, 'material': '硅胶',
         'material_grade_hardness_density': '未确认'},
        {'feature': '单侧方窗', 'evidence': '官网SKYE2字样一侧可见；2.6mm边长及位置为外观估算',
         'center_xz_mm': [-46.5, 20.46], 'size_mm': [2.6, 2.6]},
        {'feature': '底部连接器与四针', 'evidence': '官网底视及说明书确认4针；外形尺寸为示意估算，未确认厂家规格'},
        {'feature': '连接器固定肩台', 'evidence': '用于解决原生检查的悬空问题；按底盖几何避让，结构为推定，不代表厂家固定方式'},
        {'feature': '尾端顶部小孔', 'evidence': '官网俯视尺寸图有可见孔口；源STEP缺失；Ø1及X=-1.8、深至Z9为参考估算'},
        {'feature': '近鼻两侧小孔、顶部小孔及底盖接口开口', 'evidence': '原STEP中已存在；保留，不把照片中的凹孔一律改通'}]
    write_json(output / 'verification.json', {'method': 'Officially dimensioned mounting holes plus estimated visible details',
                                             'assembly': measured, 'parts': records, 'changes': changes,
                                             'not_verified': ['厂家实际孔深、壁厚、配合与内部气路', '连接器准确型号和针距',
                                                              '防水、加热、空速测量及电子功能']})
    lines = ['# SKYE 2 硅胶塞修正版（含明确标注的估算结构）', '',
             '上一版只复现了不完整本地STEP，不能当作完整SKYE2模型。本版对照官网尺寸图、四面产品图和中文说明书补建。', '',
             '打开 `SKYE2_复现装配.gasm` 查看整机；`SKYE2_拆分查看.gasm` 查看分件。',
             '打开 `SKYE2_拔塞查看.gasm` 查看硅胶塞拔出后露出的壳壁通孔；孔通向内腔，不横穿对侧壳壁。',
             '各 `skye2_*.gform` 包含可编辑的草图、基准面和切除特征；`SKYE2_整机复现.gform` 引用本版最终分件几何。',
             '已附STEP、STL及预览。原始输入未修改，上一版工程保留。', '', '## 已核对及补建', '']
    for change in changes:
        lines.append(f'- {change["feature"]}：{change["evidence"]}。')
    lines += ['', '整机外形保持101.9×28.2×29.9 mm。安装孔采用4×Ø4，9.03×23.8mm孔距来自源STEP，官网未标注孔距。',
              f'安装通孔检查：{test_count} 个点，检查覆盖主体及底盖的整个厚度、孔内不同半径；未发现堵孔。',
              '前口保留源Ø5.854入口，新增Ø4.6延伸孔道并对接壳内参考腔；从入口到壳内70mm范围的多个轴向点无实料封堵。', '',
              '## 尺寸来源和限制', '',
              'reference/ 保存本次实际读取的官网尺寸图、产品图及说明书。',
              '官网现行尺寸图为101.9×28.2×29.9mm；中文说明书为102×28.2×30.5mm，二者存在差异，本版按现行官网外形。',
              '用户确认侧面带一字槽的是硅胶塞，下面是开孔，已修正上一版误建盲凹区的错误。',
              '塞子独立可拆，含塞帽、止挡肩和插入段；硅胶牌号、硬度及密度未知，未模拟弹性密封。',
              '参考孔Ø4.4、插入段Ø4.36不属于原厂尺寸，不能据此宣称密封或实际插拔性能。方窗不镜像到另一侧。',
              '连接器固定肩台是补建的推定支承，已扣除与底盖交叠的材料；不能冒充厂家内部固定方式。',
              '官网未公开的孔深、凹区尺寸、塞件及连接器细节均为外观参考估算，特征名已标出。',
              '本模型用于外观和安装布局参考，未完成厂家制造图还原，不代表内部气路、电子或标定功能已复现。',
              '近鼻侧孔与轴向延伸孔道保持隔离；内部孔道及参考腔仅用于几何展示，没有依据声称复现实际压力、排水或加热结构。',
              '导入特征记录绝对路径；移动本工程后需重新运行生成脚本修正引用。', '',
              '来源：https://www.cuav.net/skye-2/；https://manual.cuav.net/skye2/skye2_use_manual_cn.pdf']
    (output / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'size_mm': measured['size_mm'], 'mounting_hole_samples': test_count}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, default=ROOT / 'build' / 'skye2-reference')
    options = parser.parse_args()
    generate(options.source, options.output, options.reference)
