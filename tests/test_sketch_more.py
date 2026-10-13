# -*- coding: utf-8 -*-
"""草图页第二批工具: 中心线、各种矩形和槽口、三点圆、样式样条、方程式曲线、延伸、智能尺寸、几何关系、
圆周阵列、捕捉开关; 内核这边的侧影 / 交叉曲线、中心线作旋转轴、3D 草图、曲面上的样条。"""
import math
import unittest

from genform import sketchgeom as geom
from genform.session import Session
from genform.sketcher import SketchEditor

PIXEL = 0.1


def editor(tool, snaps=('end', 'mid', 'center', 'quad', 'int', 'near', 'grid')):
    made = SketchEditor('XY')
    made.snaps = set(snaps)
    made.set_tool(tool)
    return made


def click(made, *points):
    for point in points:
        made.move(point, PIXEL)
        made.press(point, PIXEL)
        made.release(point, PIXEL)


class Drawing(unittest.TestCase):
    def test_centerline_is_construction_and_not_profile(self):
        made = editor('centerline')
        click(made, (0, 0), (0, 40))
        made.key('enter')
        self.assertTrue(made.shapes[0]['construction'])
        made.set_tool('rect')
        click(made, (10, 0), (30, 20))
        loops, _ = geom.loops(made.shapes)
        self.assertEqual(len(loops), 1)

    def test_midline(self):
        made = editor('midline')
        click(made, (10, 10), (30, 10))
        line = made.shapes[0]
        self.assertEqual((line['x1'], line['y1'], line['x2'], line['y2']), (-10, 10, 30, 10))

    def test_center_rect(self):
        made = editor('crect')
        click(made, (10, 10), (30, 20))
        rect = made.shapes[0]
        self.assertEqual((rect['cx'], rect['cy'], rect['w'], rect['h']), (10, 10, 40, 20))

    def test_three_point_rects_and_parallelogram(self):
        made = editor('rect3')
        click(made, (0, 0), (40, 0), (40, 20))
        self.assertAlmostEqual(abs(geom.signed_area([tuple(p) for p in made.shapes[0]['points']])), 800.0)
        made = editor('crect3')
        click(made, (0, 0), (20, 0), (20, 10))
        points = [tuple(p) for p in made.shapes[0]['points']]
        self.assertAlmostEqual(abs(geom.signed_area(points)), 40 * 20)
        self.assertAlmostEqual(sum(p[0] for p in points), 0.0)
        made = editor('pgram')
        click(made, (0, 0), (40, 0), (50, 20))
        points = [tuple(p) for p in made.shapes[0]['points']]
        self.assertEqual(points[3], (10, 20))
        self.assertAlmostEqual(abs(geom.signed_area(points)), 800.0)

    def test_slots(self):
        made = editor('cslot')
        click(made, (0, 0), (20, 0), (20, 5))
        slot = made.shapes[0]
        self.assertEqual((slot['x1'], slot['x2'], slot['w']), (-20, 20, 10))
        made = editor('aslot3')
        click(made, (20, 0), (-20, 0), (0, 20), (0, 25))
        slot = made.shapes[0]
        self.assertEqual(slot['type'], 'arcslot')
        self.assertAlmostEqual(slot['r'], 20.0)
        self.assertAlmostEqual(slot['w'], 10.0)
        loops, _ = geom.loops(made.shapes)
        self.assertEqual(len(loops), 1)
        # 面积 = 弧长 × 槽宽 + 两头的半圆
        self.assertAlmostEqual(abs(geom.signed_area(geom.loop_ring(loops[0], 256))), math.pi * 20 * 10 + math.pi * 25, delta=0.5)
        made = editor('caslot')
        made.move((0, 0), PIXEL); made.press((0, 0), PIXEL); made.release((0, 0), PIXEL)
        made.move((20, 0), PIXEL); made.press((20, 0), PIXEL); made.release((20, 0), PIXEL)
        for degrees in range(5, 91, 5):
            made.move((20 * math.cos(math.radians(degrees)), 20 * math.sin(math.radians(degrees))), PIXEL)
        made.press((0, 20), PIXEL); made.release((0, 20), PIXEL)
        click(made, (0, 24))
        slot = made.shapes[0]
        self.assertEqual(slot['type'], 'arcslot')
        self.assertAlmostEqual(slot['a1'] - slot['a0'], 90.0, places=3)
        self.assertAlmostEqual(slot['w'], 8.0)

    def test_perimeter_circle(self):
        made = editor('circle3')
        click(made, (10, 0), (0, 10), (-10, 0))
        circle = made.shapes[0]
        self.assertAlmostEqual(circle['r'], 10.0)
        self.assertAlmostEqual(circle['cx'], 0.0)

    def test_style_spline_stays_inside_control_polygon(self):
        made = editor('sspline')
        click(made, (0, 0), (10, 20), (30, 20), (40, 0))
        made.key('enter')
        spline = made.shapes[0]
        self.assertTrue(spline['style'])
        line = geom.polylines(spline, 32)[0]
        self.assertAlmostEqual(line[0][0], 0.0)
        self.assertAlmostEqual(line[-1][0], 40.0)
        self.assertLess(max(p[1] for p in line), 20.0)      # 不经过控制点, 只被它们拉过去

    def test_equation_curve(self):
        made = editor('equation')
        click(made, (0, 0))
        shape = made.shapes[0]
        tip = geom.polylines(shape)[-1][-1]
        self.assertAlmostEqual(tip[0], 60.0)
        self.assertAlmostEqual(tip[1], 10 * math.sin(12.0), places=6)
        made.selection = [0]
        made.set_field('fy', 'x**2/10')
        self.assertAlmostEqual(geom.polylines(made.shapes[0])[-1][-1][1], 360.0)
        made.set_field('fy', '__import__("os")')
        self.assertTrue(made.message)
        self.assertEqual(made.shapes[0]['fy'], 'x**2/10')

    def test_extend(self):
        made = editor('extend')
        made.shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 0}, {'type': 'line', 'x1': 30, 'y1': -10, 'x2': 30, 'y2': 10}]
        click(made, (9, 0))
        self.assertAlmostEqual(made.shapes[0]['x2'], 30.0)


class Editing(unittest.TestCase):
    def test_dimension_single_and_distance(self):
        made = editor('dimension')
        made.shapes = [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}, {'type': 'circle', 'cx': 30, 'cy': 0, 'r': 5}]
        click(made, (5, 0))
        panel = made.panel()
        self.assertEqual(panel['title'], '智能尺寸')
        self.assertEqual([f['key'] for f in panel['fields'] if f['type'] == 'number'], ['d'])
        made.set_field('d', 16)
        self.assertAlmostEqual(made.shapes[0]['r'], 8.0)
        click(made, (35, 0))
        self.assertAlmostEqual(made.operation['distance'], 30.0)
        made.set_field('distance', 50)
        made.apply_operation()
        self.assertAlmostEqual(made.shapes[1]['cx'], 50.0)
        self.assertAlmostEqual(made.shapes[0]['cx'], 0.0)

    def test_dimension_line_to_point_uses_perpendicular(self):
        made = editor('dimension')
        made.shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 40, 'y2': 0}, {'type': 'circle', 'cx': 10, 'cy': 12, 'r': 3}]
        click(made, (20, 0))
        click(made, (13, 12))
        self.assertAlmostEqual(made.operation['distance'], 12.0)
        made.set_field('distance', 20)
        made.apply_operation()
        self.assertAlmostEqual(made.shapes[1]['cy'], 20.0)
        self.assertAlmostEqual(made.shapes[1]['cx'], 10.0)

    def test_relations(self):
        made = editor('select')
        made.shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 40, 'y2': 0}, {'type': 'line', 'x1': 0, 'y1': 10, 'x2': 30, 'y2': 14}]
        made.selection = [0, 1]
        made.start_relation()
        keys = [o['value'] for o in made.panel()['fields'][0]['options']]
        self.assertIn('parallel', keys)
        self.assertIn('perpendicular', keys)
        made.set_field('choice', 'parallel')
        made.apply_operation()
        second = made.shapes[1]
        self.assertAlmostEqual(second['y2'] - second['y1'], 0.0)
        self.assertAlmostEqual(math.hypot(second['x2'] - second['x1'], second['y2'] - second['y1']), math.hypot(30, 4))
        made.shapes += [{'type': 'circle', 'cx': 5, 'cy': 5, 'r': 3}, {'type': 'circle', 'cx': 50, 'cy': 9, 'r': 7}]
        made.selection = [2, 3]
        made.start_relation()
        made.set_field('choice', 'concentric')
        made.apply_operation()
        self.assertEqual((made.shapes[3]['cx'], made.shapes[3]['cy'], made.shapes[3]['r']), (5, 5, 7))
        made.selection = [0, 3]
        made.start_relation()
        made.set_field('choice', 'tangent')
        made.apply_operation()
        self.assertAlmostEqual(abs(made.shapes[3]['cy']), 7.0)

    def test_circular_pattern(self):
        made = editor('select')
        made.shapes = [{'type': 'circle', 'cx': 20, 'cy': 0, 'r': 3}]
        made.selection = [0]
        made.start_circular_pattern()
        made.set_field('count', 4)
        made.apply_operation()
        self.assertEqual(len(made.shapes), 4)
        centres = sorted((round(s['cx'], 6), round(s['cy'], 6)) for s in made.shapes)
        self.assertEqual(centres, [(-20.0, 0.0), (0.0, -20.0), (0.0, 20.0), (20.0, 0.0)])
        made.selection = [0]
        made.start_circular_pattern()
        made.set_field('count', 3)
        made.set_field('angle', 90)
        made.apply_operation()
        self.assertEqual(len(made.shapes), 6)       # 0° 是原来的, 加 45° 和 90°

    def test_construction_toggle(self):
        made = editor('select')
        made.shapes = [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}]
        made.selection = [0]
        made.set_field('construction', True)
        self.assertEqual(geom.loops(made.shapes)[0], [])
        self.assertTrue(made.drawing())


class Snapping(unittest.TestCase):
    def shapes(self):
        return [{'type': 'circle', 'cx': 20, 'cy': 20, 'r': 10}, {'type': 'line', 'x1': 0.3, 'y1': 0.4, 'x2': 40.3, 'y2': 0.4}]

    def snap(self, snaps, point):
        made = editor('line', snaps)
        made.shapes = self.shapes()
        return made.snap(point, PIXEL), made.snap_kind

    def test_each_kind_can_be_switched_off(self):
        self.assertEqual(self.snap(('center',), (20.2, 20.1)), ((20.0, 20.0), 'center'))
        self.assertEqual(self.snap((), (20.2, 20.1)), ((20.2, 20.1), ''))
        self.assertEqual(self.snap(('quad',), (30.1, 20.1)), ((30.0, 20.0), 'quad'))
        self.assertEqual(self.snap(('end',), (0.4, 0.5)), ((0.3, 0.4), 'end'))
        point, kind = self.snap(('mid',), (20.4, 0.5))
        self.assertEqual(kind, 'mid')
        self.assertAlmostEqual(point[0], 20.3)
        self.assertEqual(self.snap(('near',), (8.12, 0.5))[1], 'near')
        self.assertEqual(self.snap(('end', 'mid', 'center', 'quad', 'int'), (8.12, 0.5)), ((8.12, 0.5), ''))

    def test_grid(self):
        point, kind = self.snap(('grid',), (33.37, 33.41))
        self.assertEqual(kind, '')
        self.assertAlmostEqual(point[0] / 1.0, round(point[0]))
        self.assertEqual(self.snap((), (33.37, 33.41))[0], (33.37, 33.41))

    def test_hv_alignment(self):
        made = editor('line', ('end', 'hv'))
        made.shapes = self.shapes()
        click(made, (50.0, 30.0))                       # 起点
        point = made.snap((70.3, 30.2), PIXEL)          # 差一点水平: 拉平
        self.assertEqual((point, made.snap_kind), ((70.3, 30.0), 'hv'))
        point = made.snap((0.5, 44.0), PIXEL)           # 和线的端点 (0.3, 0.4) 竖直对齐
        self.assertEqual((point, made.snap_kind), ((0.3, 44.0), 'hv'))
        made.snaps = {'end'}
        self.assertEqual(made.snap((70.3, 30.2), PIXEL), (70.3, 30.2))


class Kernel(unittest.TestCase):
    def run_all(self, session, steps):
        result = {}
        for name, args in steps:
            session.execute(name, args, result.update)
            self.assertTrue(result.get('ok'), (name, result.get('error')))
        return result

    def outline(self, session, mode, plane):
        from genform import planes
        got = {}
        session.outline(mode, planes.frame(plane, 0.0)[:3], lambda lines, error: got.update(lines=lines, error=error))
        self.assertIsNone(got['error'])
        return geom.fit_lines(got['lines'])

    def cylinder(self):
        session = Session()
        self.run_all(session, [('sketch', {'plane': 'XY', 'shapes': [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 10}]}),
                               ('extrude', {'distance': 30})])
        return session

    def test_silhouette_of_cylinder_from_the_side(self):
        shapes = self.outline(self.cylinder(), 'silhouette', 'XZ')
        sides = sorted(round((s['x1'] + s['x2']) / 2, 4) for s in shapes if s['type'] == 'line' and abs(s['x1'] - s['x2']) < 1e-6)
        self.assertIn(-10.0, sides)     # 圆柱转过去的那条侧边: 实体上没有这条边 (另一侧正好是圆柱面的接缝, 本来就是边)
        for shape in shapes:
            if shape['type'] == 'line' and abs(shape['x1'] - shape['x2']) < 1e-6:
                self.assertAlmostEqual(abs(shape['y2'] - shape['y1']), 30.0, places=4)

    def test_section_curves(self):
        session = self.cylinder()
        shapes = self.outline(session, 'section', 'XZ')         # 过轴线竖着切: 一个 20 x 30 的矩形
        self.assertEqual(sorted(s['type'] for s in shapes), ['line'] * 4)
        self.assertAlmostEqual(sum(geom.length(s) for s in shapes), 100.0, places=4)
        from genform import planes
        got = {}
        session.outline('section', planes.frame('XY', 12.0)[:3], lambda lines, error: got.update(lines=lines))
        circles = geom.fit_lines(got['lines'])                  # 横着切: 一个圆 (可能分成两段弧)
        self.assertTrue(all(s['type'] in ('circle', 'arc') for s in circles), circles)
        self.assertAlmostEqual(sum(geom.length(s) for s in circles), 2 * math.pi * 10, delta=0.05)
        self.assertTrue(all(abs(s['r'] - 10.0) < 1e-6 for s in circles))

    def test_revolve_about_centerline(self):
        session = Session()
        self.run_all(session, [
            ('sketch', {'plane': 'XZ', 'shapes': [{'type': 'line', 'x1': 5, 'y1': 0, 'x2': 5, 'y2': 40, 'construction': True},
                                                  {'type': 'rect', 'cx': 20, 'cy': 10, 'w': 10, 'h': 20}]}),
            ('revolve', {'axis': 'CL'})])
        # 矩形离中心线 10..20, 高 20: 体积 = π (20² − 10²) × 20
        self.assertAlmostEqual(session.model['props']['volume'], math.pi * 300 * 20, delta=0.5)

    def test_sketch3d_as_sweep_path(self):
        session = Session()
        self.run_all(session, [
            ('sketch3d', {'points': [[0, 0, 0], [0, 0, 30], [20, 0, 30]]}),
            ('sketch', {'plane': 'XY', 'shapes': [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 2}]}),
            ('sweep', {'sketch': 'f2', 'path': 'f1'})])
        self.assertAlmostEqual(session.model['props']['volume'], math.pi * 4 * 50, delta=8.0)
        self.assertEqual(len(session.model['sketches']['f1']), 2)

    def test_spline_on_surface_stays_on_it(self):
        import numpy as np
        session = self.cylinder()
        side = next(face for face in session.model['faces'] if face['type'] == 'cylinder')
        self.run_all(session, [('curve_surface', {'faces': [{'point': list(side['center'])}],
                                                  'points': [[0.1, 0.1], [0.4, 0.8], [0.9, 0.5]]})])
        points = np.asarray(session.model['sketches']['f3']).reshape(-1, 3)
        self.assertGreater(len(points), 10)
        self.assertLess(float(np.abs(np.hypot(points[:, 0], points[:, 1]) - 10.0).max()), 1e-4)
        self.assertGreater(float(np.ptp(points[:, 2])), 15.0)


if __name__ == '__main__':
    unittest.main()
