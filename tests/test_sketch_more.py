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

    def test_dimension_two_points_dragged_out(self):
        made = editor('dimension')
        made.shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 30, 'y2': 10}, {'type': 'line', 'x1': 50, 'y1': 40, 'x2': 80, 'y2': 40}]
        click(made, (0, 0), (50, 40))                   # 两个起点
        made.move((25, 60), PIXEL)                      # 往上拉: 水平距离
        self.assertEqual((made.operation['mode'], made.operation['distance']), ('h', 50.0))
        made.move((-20, 20), PIXEL)                     # 往左拉: 竖直距离
        self.assertEqual((made.operation['mode'], made.operation['distance']), ('v', 40.0))
        click(made, (25, 60))                           # 放下: 存进草图, 选中它
        self.assertIsNone(made.operation)
        self.assertEqual((made.dims[-1]['mode'], made.relation), ('h', 'dim:0'))
        made.set_field('dim_value', 60)                 # 属性管理器里改数
        self.assertEqual(made.shapes[1], {'type': 'line', 'x1': 60.0, 'y1': 40.0, 'x2': 80, 'y2': 40})
        self.assertEqual(made.params()['dims'][0]['mode'], 'h')

    def test_dimension_single_shape_pulled_out(self):
        made = editor('dimension')
        made.shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 30, 'y2': 40}, {'type': 'circle', 'cx': 100, 'cy': 0, 'r': 10},
                       {'type': 'arc', 'cx': 150, 'cy': 0, 'r': 8, 'a0': 0, 'a1': 180}, {'type': 'point', 'x': 0, 'y': 80}]
        click(made, (15, 20))                           # 一条斜线: 尺寸跟着鼠标
        for place, mode, value in (((15, 60), 'h', 30.0), ((60, 20), 'v', 40.0), ((40, 10), 'a', 50.0)):
            made.move(place, PIXEL)
            self.assertEqual((made.operation['mode'], made.operation['distance']), (mode, value))
        click(made, (40, 10))                           # 点空白处放下
        made.set_field('dim_value', 100)
        self.assertAlmostEqual(math.hypot(made.shapes[0]['x2'], made.shapes[0]['y2']), 100.0)
        click(made, (110, 0), (120, 20))                # 圆: 直径
        self.assertTrue(made.dim_labels()[-1][0].startswith('Ø20'))
        made.set_field('dim_value', 30)
        self.assertEqual(made.shapes[1]['r'], 15.0)
        click(made, (150, 8), (160, 15))                # 圆弧: 半径
        made.set_field('dim_value', 5)
        self.assertEqual(made.shapes[2]['r'], 5.0)
        click(made, (0, 80))                            # 一个点: 不拉, 等第二处
        self.assertIsNone(made.operation['single'])
        self.assertEqual(len(made.dims), 3)

    def test_dimension_between_parallel_lines(self):
        made = editor('dimension')
        made.shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 40, 'y2': 0}, {'type': 'line', 'x1': 10, 'y1': 15, 'x2': 30, 'y2': 15}]
        click(made, (20, 0), (20, 15))
        self.assertAlmostEqual(made.operation['distance'], 15.0)
        made.set_field('distance', 25)
        made.apply_operation()
        self.assertEqual((made.shapes[1]['y1'], made.shapes[1]['y2']), (25.0, 25.0))

    def test_dimension_rect_edges_and_corners(self):
        made = editor('dimension')
        made.shapes = [{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 40, 'h': 20}, {'type': 'point', 'x': 50, 'y': 30}]
        click(made, (0, -10), (0, 10))                  # 下边 → 上边: 高
        self.assertEqual((made.operation['pa'], made.operation['pb'], made.operation['distance']), ('s0', 's2', 20.0))
        made.set_field('distance', 30)
        made.apply_operation()
        self.assertEqual(made.shapes[0], {'type': 'rect', 'cx': 0.0, 'cy': 5.0, 'w': 40.0, 'h': 30.0})
        click(made, (50, 30), (20, 20))                 # 点 → 右上角, 往上拉: 水平距离, 改了只挪那个角
        made.move((35, 50), PIXEL)
        self.assertEqual((made.operation['pb'], made.operation['mode'], made.operation['distance']), ('v2', 'h', 30.0))
        made.set_field('distance', 40)
        made.apply_operation()
        self.assertEqual(made.shapes[0], {'type': 'rect', 'cx': -5.0, 'cy': 5.0, 'w': 30.0, 'h': 30.0})

    def test_select_grabs_a_corner_without_selecting_first(self):
        made = editor('select')
        made.shapes = [{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 40, 'h': 20}]
        made.move((20, 10), PIXEL)
        self.assertEqual(made.hover_point, (20.0, 10.0))
        made.press((20, 10), PIXEL)
        made.move((30, 15), PIXEL)
        made.release((30, 15), PIXEL)
        self.assertEqual(made.shapes[0], {'type': 'rect', 'cx': 5.0, 'cy': 2.5, 'w': 50.0, 'h': 25.0})

    def test_relation_mark_can_be_picked_and_deleted(self):
        made = editor('select')
        made.shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 0}]
        ident = made.relation_marks()[0][4]
        made.select_relation(ident)
        self.assertEqual(made.properties()['held'], ['水平'])
        self.assertTrue(made.key('delete'))
        self.assertEqual(made.relation_marks(), [])
        self.assertEqual(made.shapes[0]['y2'], 0)       # 图形不动

    def test_tool_page_and_ok(self):
        made = editor('line')
        self.assertEqual(made.properties()['tool'], 'line')
        made.finish_tool()
        self.assertEqual((made.tool, made.properties()), ('select', None))

    def test_placed_dimension_can_be_dragged_again(self):
        made = editor('select')
        made.shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 40, 'y2': 0}, {'type': 'line', 'x1': 0, 'y1': 15, 'x2': 40, 'y2': 15}]
        made.dims = [{'a': 0, 'pa': 'e0', 'b': 1, 'pb': 'e1', 'mode': 'h', 'place': [20, 30], 'ta': 'line', 'tb': 'line'}]
        for start, end in (((20, 30), (25, 50)), ((10, 50), (10, 40))):     # 按住数字拖, 再按住尺寸线拖
            made.move(start, PIXEL)
            made.press(start, PIXEL)
            made.move(end, PIXEL)
            made.release(end, PIXEL)
            self.assertEqual(made.dims[0]['place'], [float(end[0]), float(end[1])])
        self.assertEqual((made.dims[0]['mode'], made.dim_labels()[0][0], made.relation), ('h', '40', 'dim:0'))
        click(made, (0.3, 0.5))                         # 尺寸界线旁边压着图形: 还是选中图形
        self.assertEqual(made.selection, [0])

    def test_line_ends_get_dots(self):
        made = editor('select')
        made.shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 0}, {'type': 'line', 'x1': 10, 'y1': 0, 'x2': 10, 'y2': 8}]
        self.assertEqual(sorted(spot for spot, _ in made.drawing()[1]), [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0)])

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


class SelectionToolsTest(unittest.TestCase):
    """选中图形后的小工具条和属性栏: 关系、固定、构造线、无限长度。"""

    def setUp(self):
        from genform.sketcher import SketchEditor
        self.editor = SketchEditor(shapes=[{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 4},
                                           {'type': 'line', 'x1': 0, 'y1': 10, 'x2': 10, 'y2': 10},
                                           {'type': 'point', 'x': 50, 'y': 50}])
        self.editor.set_tool('select')

    def test_relation_applied_and_then_reported_as_held(self):
        editor = self.editor
        editor.selection = [0]
        self.assertNotIn('horizontal', editor.relations_held())
        editor.relate_now('horizontal')
        self.assertAlmostEqual(editor.shapes[0]['y1'], editor.shapes[0]['y2'])
        self.assertIn('horizontal', editor.relations_held())
        self.assertIn('水平', editor.properties()['held'])

    def test_fixed_shape_cannot_be_dragged_edited_or_moved_by_a_relation(self):
        editor = self.editor
        editor.selection = [0]
        editor.toggle_flag('fixed')
        before = dict(editor.shapes[0])
        editor.press((5, 2), 0.1)
        editor.move((30, 30), 0.1)
        editor.release((30, 30), 0.1)
        editor.selection = [0]
        editor.set_field('len', 99)
        editor.relate_now('vertical')
        self.assertEqual(editor.shapes[0], before)
        self.assertTrue(editor.message)

    def test_infinite_line_becomes_construction(self):
        editor = self.editor
        editor.selection = [1]
        editor.toggle_flag('infinite')
        self.assertTrue(editor.shapes[1]['infinite'] and editor.shapes[1]['construction'])
        lines, _, _ = editor.drawing()
        self.assertTrue(any(abs(a[0]) > 100 for a, _, _ in lines))        # 画出去了
        self.assertEqual(editor.bounds()[1][0], 50)                        # 范围不跟着变大

    def test_click_sets_clicked_and_box_does_not_swallow_points(self):
        editor = self.editor
        editor.press((5, 10), 0.1)
        editor.release((5, 10), 0.1)
        self.assertTrue(editor.clicked)
        self.assertEqual(editor.selection, [1])
        self.assertIn('rel:horizontal', [row['id'] for row in editor.context_items()])
        editor.press((-5, -5), 0.1)
        editor.move((20, 20), 0.1)
        editor.release((20, 20), 0.1)
        self.assertFalse(editor.clicked)
        self.assertEqual(sorted(editor.selection), [0, 1])                 # 远处的点不在框里

    def test_two_lines_offer_pair_relations(self):
        editor = self.editor
        editor.selection = [1, 0]
        ids = [row['id'] for row in editor.context_items()]
        for wanted in ('rel:parallel', 'rel:perpendicular', 'rel:equal', 'rel:collinear'):
            self.assertIn(wanted, ids)
        editor.relate_now('parallel')
        self.assertAlmostEqual(editor.shapes[0]['y1'], editor.shapes[0]['y2'])
