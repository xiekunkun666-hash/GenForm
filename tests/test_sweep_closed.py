"""真正闭合的扫描路径: 工具体有效、朝向向外, add 不丢掉原来的料。"""
import math
import os
import unittest
from unittest.mock import patch

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_CompCurve
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.TopAbs import TopAbs_IN, TopAbs_OUT, TopAbs_SHELL, TopAbs_SOLID
from OCP.gp import gp_Pnt, gp_Vec

from genform.kernel import build
from genform.kernel.model import rebuild
from genform.kernel.occ_compat import _as_solid, _as_wire
from genform.kernel.ops import curves, helpers, tools


ROUND_POINTS = [[30 * math.cos(index * math.tau / 8), 30 * math.sin(index * math.tau / 8), 0]
                for index in range(8)]
DOOR_POINTS = [
    [-748, 661.4086278740771, 845], [-781, 853.4443083913277, 720],
    [-787, 902.5054537106241, 530], [-775, 879.9463251896573, 340],
    [-690, 891.0940990354092, 238], [-380, 889.5271228672668, 220],
    [25, 895.7550165885095, 220], [335, 904.0669449671213, 238],
    [473, 897.3529163101185, 330], [495, 920.2412537959358, 550],
    [492, 868.9601907559453, 750], [485, 710.5356722242658, 869],
    [150, 709.647321073028, 856], [-240, 694.8089339538557, 848],
]
BONNET_POINTS = [
    [-2025, 0, 644.5171780113571], [-1980, -270, 673.8657838901806],
    [-1810, -408, 728.6590142861271], [-1460, -465, 777.0252845561508],
    [-1090, -505, 808.5448802833478], [-925, -487, 814.4450469415924],
    [-902, -250, 794.1561619039003], [-900, 0, 794.1516036730222],
    [-902, 250, 794.1561619039003], [-925, 487, 814.4450469415922],
    [-1090, 505, 808.5448802833478], [-1460, 465, 777.0252845561508],
    [-1810, 408, 728.6590142861269], [-1980, 270, 673.8657838901806],
]


def sweep_context(points=ROUND_POINTS, normal=None, section_shapes=None):
    path = {'id': 'path', 'type': 'sketch3d',
            'params': {'points': points, 'closed': True, 'kind': 'spline'}}
    ctx = build.Context([path])
    spine = curves.sketch3d(None, path['params'], ctx, 'path')
    ctx.curves['path'] = spine
    adaptor = BRepAdaptor_CompCurve(spine)
    spot, derivative = gp_Pnt(), gp_Vec()
    adaptor.D1(adaptor.FirstParameter(), spot, derivative)
    if normal is None:
        normal = [derivative.X(), derivative.Y(), derivative.Z()]
    datum = {'id': 'datum', 'type': 'plane',
             'params': {'origin': [[spot.X(), spot.Y(), spot.Z()]], 'normal': [list(normal)]}}
    section = {'id': 'section', 'type': 'sketch',
               'params': {'plane': 'datum', 'shapes': section_shapes or [{'type': 'circle', 'r': 2}]}}
    ctx.features.extend([datum, section])
    ctx.sketches['section'] = build.build_sketch(section['params'], ctx.features)
    return ctx


class ClosedSweepTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'GENFORM_CACHE': 'off'}))

    def assert_finite_solid(self, shape):
        self.assertTrue(BRepCheck_Analyzer(shape).IsValid())
        solids = helpers._explore(shape, TopAbs_SOLID)
        self.assertTrue(solids)
        for solid in solids:
            shells = helpers._explore(solid, TopAbs_SHELL)
            self.assertTrue(shells)
            self.assertTrue(all(BRep_Tool.IsClosed_s(shell) for shell in shells))
            volume = helpers._volume(solid).Mass()
            self.assertTrue(math.isfinite(volume))
            self.assertGreater(volume, 0)
            classifier = BRepClass3d_SolidClassifier(solid)
            classifier.PerformInfinitePoint(1e-7)
            self.assertEqual(classifier.State(), TopAbs_OUT)
        return helpers._volume(shape).Mass()

    def assert_add_keeps_body(self, ctx):
        body = BRepPrimAPI_MakeBox(gp_Pnt(-20, -40, -5), 40, 80, 10).Shape()
        before = helpers._volume(body).Mass()
        tool = ctx.make('sweep', {'sketch': 'section', 'path': 'path', 'op': 'add'}, body)
        tool_volume = self.assert_finite_solid(tool)
        combined = build.combine(body, tool, 'add')
        after = self.assert_finite_solid(combined)
        self.assertGreater(after, before + 100)
        self.assertLessEqual(after, before + tool_volume + 0.1)
        self.assertAlmostEqual(helpers._volume(body).Mass(), before, places=7)
        return tool_volume

    def test_closed_spline_add_in_both_path_and_normal_directions(self):
        for reverse_path in (False, True):
            points = [ROUND_POINTS[0], *ROUND_POINTS[:0:-1]] if reverse_path else ROUND_POINTS
            for reverse_normal in (False, True):
                with self.subTest(reverse_path=reverse_path, reverse_normal=reverse_normal):
                    ctx = sweep_context(points)
                    if reverse_normal:
                        normal = -ctx.sketches['section'].frame[3]
                        ctx = sweep_context(points, normal=normal)
                    volume = self.assert_add_keeps_body(ctx)
                    length = GCPnts_AbscissaPoint.Length_s(BRepAdaptor_CompCurve(ctx.curves['path']))
                    self.assertAlmostEqual(volume, math.pi * 4 * length, delta=volume * 0.005)

    def test_reversed_section_topology(self):
        ctx = sweep_context()
        section = ctx.sketches['section']
        section.profile = section.profile.Reversed()
        section.wires = [_as_wire(wire.Reversed()) for wire in section.wires]
        self.assert_add_keeps_body(ctx)

    def test_reversed_wire_topology(self):
        ctx = sweep_context()
        ctx.curves['path'] = _as_wire(ctx.curves['path'].Reversed())
        self.assert_add_keeps_body(ctx)

    def test_closed_sweep_preserves_section_hole_or_reports_invalid_tool(self):
        ctx = sweep_context(section_shapes=[{'type': 'circle', 'r': 2}, {'type': 'circle', 'r': 1}])
        try:
            tool = tools.sweep(None, {'sketch': 'section', 'path': 'path'}, ctx)
        except build.FeatureError as error:
            self.assertIn('扫描', str(error))
        else:
            volume = self.assert_finite_solid(tool)
            length = GCPnts_AbscissaPoint.Length_s(BRepAdaptor_CompCurve(ctx.curves['path']))
            self.assertAlmostEqual(volume, math.pi * 3 * length, delta=volume * 0.005)

    def test_non_perpendicular_section_reports_actual_tangent(self):
        ctx = sweep_context(normal=[0, 1, 1])
        with self.assertRaisesRegex(build.FeatureError, '截面.*垂直.*切向') as raised:
            tools.sweep(None, {'sketch': 'section', 'path': 'path'}, ctx)
        self.assertIn('normal', str(raised.exception))

    def test_closed_sketch_wire_is_checked_without_closed_parameter(self):
        ctx = sweep_context(normal=[0, 0, 1])
        del ctx.curves['path']
        path = {'id': 'path', 'type': 'sketch', 'params': {'shapes': [{'type': 'circle', 'r': 30}]}}
        ctx.features[0] = path
        ctx.sketches['path'] = build.build_sketch(path['params'])
        with self.assertRaisesRegex(build.FeatureError, '截面.*垂直.*切向'):
            tools.sweep(None, {'sketch': 'section', 'path': 'path'}, ctx)

    def test_actual_seams_reject_sample_chord_as_profile_normal(self):
        for name, points in [('door', DOOR_POINTS), ('bonnet', BONNET_POINTS)]:
            with self.subTest(seam=name):
                ctx = sweep_context(points, normal=np.array(points[1]) - points[-1])
                with self.assertRaisesRegex(build.FeatureError, '截面.*垂直.*切向'):
                    tools.sweep(None, {'sketch': 'section', 'path': 'path'}, ctx)

    def test_actual_seams_with_exact_tangent_never_return_open_solid(self):
        for name, points in [('door', DOOR_POINTS), ('bonnet', BONNET_POINTS)]:
            with self.subTest(seam=name):
                ctx = sweep_context(points)
                body = BRepPrimAPI_MakeBox(gp_Pnt(-900, 680, 200), 1600, 240, 700).Shape()
                before = helpers._volume(body).Mass()
                try:
                    tool = tools.sweep(body, {'sketch': 'section', 'path': 'path'}, ctx)
                except build.FeatureError as error:
                    self.assertIn('扫描', str(error))
                else:
                    self.assert_finite_solid(tool)
                    result = build.combine(body, tool, 'add')
                    self.assertGreaterEqual(self.assert_finite_solid(result), before - 0.1)
                self.assertAlmostEqual(helpers._volume(body).Mass(), before, places=5)

    def test_invalid_seam_stops_before_combine_and_preserves_prefix(self):
        ctx = sweep_context(DOOR_POINTS, normal=np.array(DOOR_POINTS[1]) - DOOR_POINTS[-1])
        features = [
            {'id': 'base_section', 'type': 'sketch',
             'params': {'offset': 200, 'shapes': [{'type': 'rect', 'cx': -100, 'cy': 800, 'w': 1600, 'h': 240}]}},
            {'id': 'base', 'type': 'extrude', 'params': {'sketch': 'base_section', 'distance': 700}},
            *ctx.features,
            {'id': 'seam', 'type': 'sweep', 'params': {'sketch': 'section', 'path': 'path', 'op': 'add'}},
            {'id': 'after', 'type': 'extrude', 'params': {'sketch': 'section', 'distance': 1}},
        ]
        with patch.object(rebuild, '_STEPS', []), patch.object(rebuild, '_SPARE', []), \
                patch.object(rebuild, 'combine', wraps=build.combine) as combine:
            body, result_ctx, status = rebuild._rebuild(features)
        self.assertEqual(combine.call_count, 1)
        self.assertEqual(status['base'], 'ok')
        self.assertTrue(status['seam'].startswith('error:'), status)
        self.assertEqual(status['after'], 'skipped')
        self.assertNotIn('seam', result_ctx.tools)
        self.assertAlmostEqual(self.assert_finite_solid(body), 268800000, delta=0.01)

    def test_exact_tangent_seam_is_validated_before_combine(self):
        from genform.kernel.ops.sweep_geometry import checked_sweep_solid
        ctx = sweep_context(DOOR_POINTS)
        features = [
            {'id': 'base_section', 'type': 'sketch',
             'params': {'offset': 200, 'shapes': [{'type': 'rect', 'cx': -100, 'cy': 800, 'w': 1600, 'h': 240}]}},
            {'id': 'base', 'type': 'extrude', 'params': {'sketch': 'base_section', 'distance': 700}},
            *ctx.features,
            {'id': 'seam', 'type': 'sweep', 'params': {'sketch': 'section', 'path': 'path', 'op': 'add'}},
            {'id': 'after', 'type': 'extrude', 'params': {'sketch': 'section', 'distance': 1}},
        ]
        with patch.object(rebuild, '_STEPS', []), patch.object(rebuild, '_SPARE', []), \
                patch.object(rebuild, 'combine', wraps=build.combine) as combine, \
                patch.object(tools, 'checked_sweep_solid', wraps=checked_sweep_solid) as check:
            body, result_ctx, status = rebuild._rebuild(features)
        self.assertGreaterEqual(check.call_count, 1)
        volume = self.assert_finite_solid(body)
        if status['seam'].startswith('error:'):
            self.assertEqual(combine.call_count, 1)
            self.assertEqual(status['after'], 'skipped')
            self.assertNotIn('seam', result_ctx.tools)
            self.assertAlmostEqual(volume, 268800000, delta=0.01)
        else:
            self.assertEqual(status['seam'], 'ok')
            self.assertGreaterEqual(volume, 268800000 - 0.1)
            self.assert_finite_solid(result_ctx.tools['seam'][0])

    def test_inverted_solids_are_oriented_individually_without_mutating_input(self):
        from genform.kernel.ops.sweep_geometry import checked_sweep_solid
        ctx = sweep_context()
        pipe = helpers._run(BRepOffsetAPI_MakePipe(ctx.curves['path'], ctx.sketches['section'].profile), 'pipe')
        solid = _as_solid(helpers._explore(pipe, TopAbs_SOLID)[0])
        volume = helpers._volume(solid).Mass()
        inverted = helpers._moved(solid.Reversed(), helpers._translation([100, 0, 0]))
        self.assertLess(helpers._volume(inverted).Mass(), 0)
        classifier = BRepClass3d_SolidClassifier(inverted)
        classifier.PerformInfinitePoint(1e-7)
        self.assertEqual(classifier.State(), TopAbs_IN)
        normalized = checked_sweep_solid(build._compound([solid, inverted]))
        self.assertAlmostEqual(self.assert_finite_solid(normalized), volume * 2, delta=0.01)
        self.assertAlmostEqual(helpers._volume(inverted).Mass(), -volume, delta=0.01)

    def test_surface_only_and_mixed_results_are_rejected(self):
        from genform.kernel.ops.sweep_geometry import checked_sweep_solid
        ctx = sweep_context()
        section = ctx.sketches['section']
        shell = helpers._run(BRepOffsetAPI_MakePipe(ctx.curves['path'], section.wires[0]), 'pipe')
        solid = helpers._run(BRepOffsetAPI_MakePipe(ctx.curves['path'], section.profile), 'pipe')
        for shape in (shell, build._compound([solid, section.profile]), build._compound([])):
            with self.subTest(shape=shape.ShapeType()), self.assertRaises(build.FeatureError):
                checked_sweep_solid(shape)


if __name__ == '__main__':
    unittest.main()
