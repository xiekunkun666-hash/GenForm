"""Verify exported holes, evidence coverage and native design-check reports."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_IN
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from complete_skye2_reference import MOUNTS, PROBE_DIRECTION, PROBE_MOUTH
from genform.kernel.ops.importing import read_step
from genform.kernel.stl import read_stl


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def intersection_volume(shape, start, direction, radius, length):
    tool = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*map(float, start)), gp_Dir(*map(float, direction))), radius, length).Shape()
    common = BRepAlgoAPI_Common(shape, tool)
    common.SetNonDestructive(True)
    common.Build()
    if not common.IsDone():
        raise RuntimeError('Hole intersection verification did not complete')
    measure = GProp_GProps()
    BRepGProp.VolumeProperties_s(common.Shape(), measure)
    return abs(measure.Mass())


def main(folder):
    folder = folder.resolve()
    silicone_plug = json.loads((folder / 'skye2_side_plug.gform').read_text(encoding='utf-8')).get('props', {}).get('material') == '硅胶'
    shape, note = read_step(str(folder / 'SKYE2_整机复现.step'))
    if not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError('Exported STEP is invalid')
    classifier = BRepClass3d_SolidClassifier(shape)

    def occupied(point):
        classifier.Perform(gp_Pnt(*map(float, point)), 1e-6)
        return classifier.State() == TopAbs_IN

    sample_count, voids = 0, []
    for center_x, center_y in MOUNTS:
        for altitude in np.linspace(-3.7, 3, 9):
            for angle in np.linspace(0, 2 * math.pi, 12, endpoint=False):
                point = [center_x + 1.95 * math.cos(angle), center_y + 1.95 * math.sin(angle), altitude]
                if occupied(point):
                    raise ValueError(f'Exported mounting hole blocked: {point}')
                sample_count += 1
        volume = intersection_volume(shape, [center_x, center_y, -4], [0, 0, 1], 1.95, 7.2)
        if volume > 1e-5:
            raise ValueError(f'Mounting hole contains material: {volume}')
        voids.append({'feature': 'mount', 'center_xy': [center_x, center_y], 'test_radius_mm': 1.95,
                      'length_mm': 7.2, 'intersecting_material_mm3': volume})
    sideways = np.array([0, 1, 0])
    upward = np.cross(PROBE_DIRECTION, sideways)
    for distance in np.linspace(1.1, 70, 80):
        for angle in np.linspace(0, 2 * math.pi, 8, endpoint=False):
            point = PROBE_MOUTH + distance * PROBE_DIRECTION + 1.9 * (sideways * math.cos(angle) + upward * math.sin(angle))
            if occupied(point):
                raise ValueError(f'Exported reference bore blocked: {point}')
            sample_count += 1
    bore_volume = intersection_volume(shape, PROBE_MOUTH + 1.1 * PROBE_DIRECTION, PROBE_DIRECTION, 1.9, 68.9)
    if bore_volume > 1e-5:
        raise ValueError(f'Reference bore contains material: {bore_volume}')
    voids.append({'feature': 'reference_bore_not_manufacturer_verified', 'test_radius_mm': 1.9,
                  'length_mm': 68.9, 'intersecting_material_mm3': bore_volume})
    if silicone_plug:
        body_shape, _ = read_step(str(folder / 'geometry' / 'body.step'))
        plug_shape, _ = read_step(str(folder / 'geometry' / 'side_plug.step'))
        open_hole_volume = intersection_volume(body_shape, [-12, -5.2, 12.7], [0, 1, 0], 2.1, 3.2)
        if open_hole_volume > 1e-5:
            raise ValueError(f'Silicone plug removed but access opening is still blocked: {open_hole_volume}')
        body_classifier = BRepClass3d_SolidClassifier(body_shape)
        plug_classifier = BRepClass3d_SolidClassifier(plug_shape)
        for position in np.linspace(-4.9, -2.1, 15):
            body_classifier.Perform(gp_Pnt(-12, float(position), 12.7), 1e-6)
            if body_classifier.State() == TopAbs_IN:
                raise ValueError('Body access hole has a residual floor')
        body_classifier.Perform(gp_Pnt(-12, 4.0, 12.7), 1e-6)
        if body_classifier.State() != TopAbs_IN:
            raise ValueError('Access cut unexpectedly removed opposite shell wall')
        plug_classifier.Perform(gp_Pnt(-12, -3.2, 12.7), 1e-6)
        if plug_classifier.State() != TopAbs_IN:
            raise ValueError('Silicone insertion stem missing')
        voids.append({'feature': 'silicone_plug_removed_access_hole', 'test_radius_mm': 2.1,
                      'length_mm': 3.2, 'intersecting_material_mm3': open_hole_volume,
                      'opposite_wall_preserved': True, 'plug_stem_present': True})

    local_tests = [
        ('near_tip_positive_y', [-99.3887170887, 3.7, 20.809276715806], False),
        ('near_tip_negative_y', [-99.3887170887, -4.2, 20.809276715806], False),
        ('near_tip_blind_hole_partition_positive', [-99.3887170887, 3.0, 20.809276715806], True),
        ('near_tip_blind_hole_partition_negative', [-99.3887170887, -3.5, 20.809276715806], True),
        ('existing_top_hole', [-18.9, -0.25148874334, 24.8], False),
        ('new_tail_hole', [-1.8, -0.25148874334, 10.5], False),
        ('single_side_window', [-46.5, -4.3, 20.46], False),
        ('side_plug_slot', [-12, -4.8, 12.7], False),
        ('side_plug_slot_floor', [-12, -4.3, 12.7], True)]
    holes = []
    for label, point, expected in local_tests:
        actual = occupied(point)
        if actual != expected:
            raise ValueError(f'Local hole verification failed: {label}, expected material {expected}, actual {actual}')
        holes.append({'feature': label, 'point_mm': point, 'contains_material': actual})
    mesh = read_stl(folder / 'SKYE2_整机复现.stl')
    size = mesh['verts'].max(axis=0) - mesh['verts'].min(axis=0)
    if max(abs(actual - expected) for actual, expected in zip(size, [101.9, 28.2, 29.9])) > 0.001:
        raise ValueError('STL size differs')
    assembly = json.loads((folder / 'design_check_assembly.json').read_text(encoding='utf-8'))
    summary = json.loads((folder / 'design_check_summary.json').read_text(encoding='utf-8'))
    if assembly['counts'].get('error', 0) or any(row['counts'].get('error', 0) for row in summary['parts']):
        raise ValueError('Native design checks still contain errors')
    report = {'exported_step_valid': True, 'solid_note': note, 'exported_geometry_hole_samples': sample_count,
              'void_intersection_tests': voids, 'visible_hole_point_tests': holes,
              'stl_triangles': len(mesh['tris']), 'stl_size_mm': size.tolist(),
              'native_assembly_errors': assembly['counts'].get('error', 0),
              'native_assembly_warnings': assembly['counts'].get('warning', 0),
              'native_part_errors': sum(row['counts'].get('error', 0) for row in summary['parts']),
              'manufacturer_identity_verified': False,
              'limitations': ['Public pictures do not specify all hole depths, exact locations or internal pressure channels',
                              'A zero-error native geometry check is not proof of identical manufacture or working airspeed sensing']}
    save(folder / 'export_verification.json', report)
    audit = '''# 官网可见孔位核对及设计检查

## 已核对的孔口

| 部位 | 当前模型处理 | 可靠程度 |
| --- | --- | --- |
| 四个安装孔 | 主体、底盖贯穿，Ø4；逐孔做整段圆柱与实体求交，孔内无实料 | 数量孔径为官网标注，中心沿用源STEP |
| 探头正面入口 | 保留源入口尺寸，补参考阶梯孔道及壳腔，检查到壳内70mm无实料阻塞 | 外部孔口由官网确认，内部结构推定 |
| 近鼻两侧小孔 | 保留两个源盲凹孔及与轴向孔道之间的隔壁 | 存在由官网确认；孔径沿用源STEP，深度未核实 |
| 壳顶中间小孔 | 保留源孔，并检查入口为空 | 存在由官网确认；深度未核实 |
| 壳顶尾端小孔 | 已补；入口及孔内点检查为空 | 存在由官网俯视图确认；尺寸、位置、深度估算 |
| 单侧方形凹窗及中心小孔 | 已补，不镜像另一侧 | 存在由官网确认；尺寸及深度估算 |
| 侧面圆凹区、横槽塞件 | 已补圆凹区及独立塞件；槽内为空、槽底有材料 | 官网外观确认，不能错误地当整壳横向通孔；尺寸估算 |
| 底部矩形接口 | 保留源开口，补四针插座及有实际支承的肩台 | 4针及接口存在由官网确认；具体连接器尺寸及固定方式推定 |
| 底盖周边圆凹位/螺钉外观 | 保留原STEP形状，不把紧固件头部一律切穿 | 官网照片可见，未有完整紧固件机械图 |

## 原生设计检查

未放宽默认公差、间隙或其他检查规则。第一次检查发现连接器及4触点共5个悬空错误。
新增推定固定肩台，并按底盖精确扣除交叠后重新检查，装配体0错误，9个分件0错误。
装配体仍有1项未绑定工艺警告；每个分件仍有未指定材质、未绑定工艺警告。
未虚构材质、报价，不把软件显示的未定价零元当实际成本。

报告：`design_check_assembly.json`、`design_check_skye2_*.json`、`design_check_summary.json`、`export_verification.json`。
`*_before_support.json` 是修正前的记录，不是最终检查结果。

## 尚不能验收为“一模一样”

官网只提供部分尺寸与外观图；未公开孔深、各小孔精确坐标、壁厚、实际内气路和完整连接器公差。
未精确恢复丝印、内部电子结构与厂家紧固件规格。本工程是有标注假设的机械参考模型，
不是已证实与原厂完全相同的可生产图。若要求逐孔及内部完全相同，需要完整厂家机械图或实物测量。
零几何错误不代表性能、防水、加热或飞行使用验证完成。
'''
    if silicone_plug:
        audit = audit.replace('| 侧面圆凹区、横槽塞件 | 已补圆凹区及独立塞件；槽内为空、槽底有材料 | 官网外观确认，不能错误地当整壳横向通孔；尺寸估算 |',
                              '| 硅胶塞及塞下开孔 | 独立硅胶塞含帽部、止挡肩和插入段；拔塞后壳壁孔连通内腔，对侧壁保留 | 用户确认材质与结构；孔径、配合及硬度等未确认 |')
        audit = audit.replace('装配体仍有1项未绑定工艺警告；每个分件仍有未指定材质、未绑定工艺警告。',
                              '装配体仍有未绑定工艺警告；其他分件仍有未指定材质等警告。硅胶塞材质由用户确认，密度、硬度及牌号未知。')
        audit += '\n## 本次硅胶塞修正\n\n打开 `SKYE2_拔塞查看.gasm` 查看拔塞配置。孔腔用圆柱求交验证无残料，塞子插入段存在，对侧壳壁未切穿。\n硅胶的弹性压缩、过盈及密封没有验证，参考配合尺寸不可当作厂家生产尺寸。\n'
    (folder / '孔位核对与检查结果.md').write_text(audit, encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    arguments = parser.parse_args()
    main(arguments.folder)
