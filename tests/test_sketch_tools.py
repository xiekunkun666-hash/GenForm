"""草图的新工具: 圆弧、槽口、多边形、椭圆、样条、点、文本; 圆角、剪裁、等距、镜向、阵列、移动、转换引用、修复、快速捕捉。"""
import math
import unittest

from genform import sketchgeom as geom
from genform.session import Session
from genform.sketcher import SketchEditor

PIXEL = 0.1


def click(editor, point, additive=False):
    editor.move(point, PIXEL)
    editor.press(point, PIXEL, additive)
    editor.release(point, PIXEL)


def build(shapes, distance=5, plane='XY'):
    session, replies = Session(), []
    session.execute('sketch', {'plane': plane, 'shapes': shapes}, replies.append)
    session.execute('extrude', {'distance': distance}, replies.append)
    return session, replies


def box(*lines):
    return [{'type': 'line', 'x1': a, 'y1': b, 'x2': c, 'y2': d} for a, b, c, d in lines]


SQUARE = box((0, 0, 40, 0), (40, 0, 40, 30), (40, 30, 0, 30), (0, 30, 0, 0))


class DrawToolTests(unittest.TestCase):
    def test_arc_follows_the_direction_the_cursor_turns(self):
        editor = SketchEditor()
        editor.set_tool('arc')
        click(editor, (0, 0))
        click(editor, (10, 0))
        for point in ((7, 7), (0, 10), (-7, 7)):                  # 逆时针转过去
            editor.move(point, PIXEL)
        click(editor, (-10, 0))
        self.assertEqual(editor.shapes[0], {'type': 'arc', 'cx': 0, 'cy': 0, 'r': 10.0, 'a0': 0.0, 'a1': 180.0})
        click(editor, (50, 0))
        click(editor, (60, 0))
        for point in ((57, -7), (50, -10)):                       # 顺时针
            editor.move(point, PIXEL)
        click(editor, (40, 0))
        self.assertEqual((editor.shapes[1]['a0'], editor.shapes[1]['a1']), (-180.0, 0.0))

    def test_slot_polygon_ellipse_spline_point(self):
        editor = SketchEditor()
        editor.set_tool('slot')
        for point in ((0, 0), (30, 0), (20, 5)):
            click(editor, point)
        self.assertEqual(editor.shapes[-1], {'type': 'slot', 'x1': 0, 'y1': 0, 'x2': 30, 'y2': 0, 'w': 10.0})
        editor.set_tool('ngon')
        editor.options['sides'] = 5
        click(editor, (100, 0))
        click(editor, (100, 20))
        self.assertEqual(editor.shapes[-1], {'type': 'ngon', 'cx': 100, 'cy': 0, 'r': 20.0, 'sides': 5, 'angle': 90.0})
        editor.set_tool('ellipse')
        for point in ((0, 100), (30, 100), (10, 110)):
            click(editor, point)
        self.assertEqual((editor.shapes[-1]['rx'], editor.shapes[-1]['ry'], editor.shapes[-1]['angle']), (30.0, 10.0, 0.0))
        editor.set_tool('spline')
        for point in ((200, 0), (210, 10), (220, 0), (230, 10)):
            click(editor, point)
        self.assertTrue(editor.key('enter'))
        self.assertEqual((len(editor.shapes[-1]['points']), editor.shapes[-1]['closed']), (4, False))
        editor.set_tool('point')
        click(editor, (300, 300))
        self.assertEqual(editor.shapes[-1], {'type': 'point', 'x': 300, 'y': 300})

    def test_new_closed_shapes_extrude(self):
        shapes = [{'type': 'slot', 'x1': 0, 'y1': 0, 'x2': 30, 'y2': 0, 'w': 10},
                  {'type': 'ngon', 'cx': 100, 'cy': 0, 'r': 20, 'sides': 6, 'angle': 0},
                  {'type': 'ellipse', 'cx': 0, 'cy': 100, 'rx': 30, 'ry': 10, 'angle': 0},
                  {'type': 'spline', 'points': [[200, 0], [220, 0], [220, 20], [200, 20]], 'closed': True}]
        for shape in shapes:
            session, replies = build([shape])
            self.assertTrue(all(reply['ok'] for reply in replies), (shape['type'], replies))
        session, replies = build([shapes[0]])
        self.assertEqual(replies[1]['model']['body']['size_mm'], [40, 10, 5])
        volume = session.model['props']['volume']
        self.assertAlmostEqual(volume, (30 * 10 + math.pi * 25) * 5, places=3)
        session, replies = build([shapes[2]])
        self.assertAlmostEqual(session.model['props']['volume'], math.pi * 30 * 10 * 5, places=3)

    def test_lines_and_arcs_joined_end_to_end_make_a_profile_and_a_hole(self):
        outline = box((0, 0, 40, 0), (40, 0, 40, 20), (0, 20, 0, 0)) + \
            [{'type': 'arc', 'cx': 20, 'cy': 20, 'r': 20, 'a0': 0, 'a1': 180}]
        session, replies = build(outline + [{'type': 'circle', 'cx': 20, 'cy': 15, 'r': 5}], distance=10)
        self.assertTrue(replies[1]['ok'], replies)
        self.assertAlmostEqual(session.model['props']['volume'], (40 * 20 + math.pi * 200 - math.pi * 25) * 10, places=3)

    def test_open_sketch_is_kept_but_cannot_be_extruded(self):
        session, replies = build(SQUARE[:3])
        self.assertTrue(replies[0]['ok'])
        self.assertFalse(replies[1]['ok'])
        self.assertIn('没有封闭轮廓', str(replies[1]))
        self.assertEqual(len(session.model['sketches'][replies[0]['id']]), 3)       # 三条线照样显示

    def test_text_becomes_faces(self):
        session, replies = build([{'type': 'text', 'x': 0, 'y': 0, 'text': 'HI', 'height': 10, 'angle': 0}], distance=2)
        self.assertTrue(replies[1]['ok'], replies)
        size = replies[1]['model']['body']['size_mm']
        self.assertAlmostEqual(size[1], 7.56, places=1)           # 大写字母的高度约是字高的 0.756
        self.assertEqual(size[2], 2)
        along = {'type': 'text', 'x': 0, 'y': 0, 'text': 'ABC', 'height': 5,
                 'path': {'type': 'arc', 'cx': 0, 'cy': 0, 'r': 30, 'a0': 0, 'a1': 180}}
        spots = geom.text_layout(along, [4.0, 4.0, 4.0])
        self.assertLess(spots[0][0], spots[2][0])                 # 沿圆弧顺时针排: 从左往右读
        self.assertTrue(build([along])[1][1]['ok'])


class ModifyToolTests(unittest.TestCase):
    def test_fillet_rounds_a_rectangle_corner(self):
        editor = SketchEditor(shapes=[{'type': 'rect', 'cx': 20, 'cy': 15, 'w': 40, 'h': 30}])
        editor.set_tool('fillet')
        editor.options['radius'] = 5.0
        click(editor, (40.3, 30.2))
        self.assertEqual(sorted(shape['type'] for shape in editor.shapes), ['arc'] + ['line'] * 4)
        arc = next(shape for shape in editor.shapes if shape['type'] == 'arc')
        self.assertEqual((round(arc['cx'], 9), round(arc['cy'], 9), arc['r']), (35.0, 25.0, 5.0))
        self.assertEqual(len(geom.loops(editor.shapes)[0]), 1)    # 还是一个封闭轮廓
        session, replies = build(editor.shapes, distance=1)
        self.assertAlmostEqual(session.model['props']['volume'], 1200 - 25 + math.pi * 25 / 4, places=4)
        editor.options['radius'] = 500.0
        click(editor, (0.0, 0.0))
        self.assertIn('太大', editor.message)

    def test_trim_cuts_at_the_intersections(self):
        cross = box((0, 0, 40, 0), (20, -10, 20, 10))
        trimmed = geom.trim(cross, 0, (30, 0))                    # 剪掉右半截
        self.assertEqual(trimmed[0], {'type': 'line', 'x1': 0.0, 'y1': 0.0, 'x2': 20.0, 'y2': 0.0})
        self.assertEqual(len(geom.trim(cross, 1, (20, 5))), 2)
        self.assertEqual(len(geom.trim(box((0, 0, 40, 0)), 0, (5, 0))), 0)       # 没有交点: 整条删掉
        circle = [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 10}] + box((-20, 0, 20, 0))
        arc = geom.trim(circle, 0, (0, 10))[0]                    # 剪掉上半圆
        self.assertEqual((arc['type'], round(arc['a0'] % 360, 6), round(arc['a1'] % 360, 6)), ('arc', 180.0, 0.0))
        with self.assertRaises(ValueError):
            geom.trim([{'type': 'ellipse', 'cx': 0, 'cy': 0, 'rx': 9, 'ry': 4}], 0, (9, 0))

    def test_offset_by_two_clicks(self):
        editor = SketchEditor(shapes=[{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 40, 'h': 30}, {'type': 'circle', 'cx': 100, 'cy': 0, 'r': 10}])
        editor.set_tool('offset')
        click(editor, (20.0, 3.0))
        click(editor, (25.0, 3.0))                                # 往外 5
        self.assertEqual(editor.shapes[-1], {'type': 'rect', 'cx': 0, 'cy': 0, 'w': 50.0, 'h': 40.0})
        click(editor, (110.0, 0.0))
        click(editor, (107.0, 0.0))                               # 往里 3
        self.assertEqual(editor.shapes[-1]['r'], 7.0)
        self.assertEqual(geom.offset({'type': 'line', 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 0}, 2)['y1'], 2)
        triangle = {'type': 'polygon', 'points': [[0, 0], [30, 0], [0, 30]]}
        self.assertIsNone(geom.offset(triangle, -20))             # 往里缩没了
        self.assertEqual([round(value, 9) for value in geom.offset(triangle, 1)['points'][0]], [-1.0, -1.0])

    def test_mirror_keeps_the_originals_and_move_does_not(self):
        editor = SketchEditor(shapes=[{'type': 'circle', 'cx': 10, 'cy': 5, 'r': 3},
                                      {'type': 'arc', 'cx': 20, 'cy': 0, 'r': 5, 'a0': 0, 'a1': 90}])
        editor.set_tool('mirror')
        self.assertEqual(editor.tool, 'select')                   # 没选东西: 提示先选
        self.assertTrue(editor.message)
        editor.selection = [0, 1]
        editor.set_tool('mirror')
        click(editor, (0, -50))
        click(editor, (0, 50))                                    # 关于 Y 轴
        self.assertEqual(len(editor.shapes), 4)
        self.assertEqual(editor.shapes[2]['cx'], -10)
        self.assertEqual((editor.shapes[3]['cx'], editor.shapes[3]['a0'] % 360, editor.shapes[3]['a1'] % 360), (-20, 90, 180))
        editor.selection = [0]
        editor.set_tool('move')
        click(editor, (10, 5))
        click(editor, (30, 25))
        self.assertEqual((editor.shapes[0]['cx'], editor.shapes[0]['cy'], len(editor.shapes)), (30, 25, 4))

    def test_linear_pattern(self):
        editor = SketchEditor(shapes=[{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 3}])
        editor.start_pattern()
        self.assertIsNone(editor.operation)                       # 没选东西
        editor.selection = [0]
        editor.start_pattern()
        for key, value in (('nx', 3), ('dx', 10), ('ny', 2), ('dy', 15)):
            editor.set_field(key, value)
        self.assertEqual(len(editor.drawing()[0]), 64 * 6)        # 预览里已经能看到 5 个拷贝
        editor.apply_operation()
        self.assertEqual(sorted((shape['cx'], shape['cy']) for shape in editor.shapes),
                         [(0, 0), (0, 15), (10, 0), (10, 15), (20, 0), (20, 15)])

    def test_convert_entities_copies_projected_model_edges(self):
        session, replies = build([{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 40, 'h': 30}, {'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}], 10)
        references = geom.project_edges(session.model, 'XY', 10.0)
        self.assertEqual(sorted(shape['type'] for shape in references), ['circle'] + ['line'] * 4)   # 上下两圈重合的只留一份
        side = geom.project_edges(session.model, 'XZ', 0.0)
        self.assertTrue(all(shape['type'] == 'line' for shape in side))            # 侧着看圆是一条线
        editor = SketchEditor(plane='XY', offset=10.0)
        editor.references = references
        editor.set_tool('convert')
        click(editor, (5.0, 0.2))
        self.assertEqual(editor.shapes, [{'type': 'circle', 'cx': 0.0, 'cy': 0.0, 'r': 5.0}])
        click(editor, (5.0, 0.2))
        self.assertEqual(len(editor.shapes), 1)                   # 同一条边不拷两次

    def test_repair_finds_and_closes_small_gaps(self):
        broken = box((0, 0, 40, 0), (40.03, 0, 40, 30), (40, 30, 0, 30), (0, 30, 0, 0), (0, 0, 40, 0), (5, 5, 5, 5.0001))
        kinds = sorted(issue['kind'] for issue in geom.diagnose(broken))
        self.assertEqual(kinds, ['duplicate', 'gap', 'tiny'])
        self.assertEqual(len(geom.loops(broken)[0]), 0)
        editor = SketchEditor(shapes=broken)
        editor.start_repair()
        self.assertEqual(editor.panel()['accept'], '修复')
        editor.apply_operation()
        self.assertEqual(len(editor.shapes), 4)
        self.assertEqual(len(geom.loops(editor.shapes)[0]), 1)
        self.assertEqual(geom.diagnose(editor.shapes), [])
        self.assertEqual([issue['kind'] for issue in geom.diagnose(SQUARE[:3])], ['open', 'open'])

    def test_snaps_and_quick_snap_filter(self):
        editor = SketchEditor(shapes=box((0, 0, 40, 0), (20, -10, 20, 10)) + [{'type': 'circle', 'cx': 100, 'cy': 0, 'r': 10}])
        editor.set_tool('line')
        for point, kind, expected in (((20.3, 0.2), 'int', (20.0, 0.0)), ((40.2, 0.3), 'end', (40.0, 0.0)),
                                      ((100.2, 10.3), 'quad', (100.0, 10.0)), ((100.3, 0.2), 'center', (100.0, 0.0)),
                                      ((7.3, 0.4), 'near', (7.3, 0.0))):
            editor.move(point, PIXEL)
            self.assertEqual((editor.snap_kind, editor.cursor), (kind, expected))
        editor.snap_only = 'mid'
        editor.move((12.0, 1.5), PIXEL)                           # 离中点 (20, 0) 八十多个像素: 太远, 不吸
        self.assertFalse(editor.snapped)
        editor.move((18.0, 0.5), PIXEL)                           # 二十个像素: 平时吸不到, 指定了只吸中点就吸过去
        self.assertEqual((editor.snap_kind, editor.cursor), ('mid', (20.0, 0.0)))
        click(editor, (18.0, 0.5))
        self.assertIsNone(editor.snap_only)                       # 只管一次

    def test_multi_select_box_select_and_chain(self):
        editor = SketchEditor(shapes=SQUARE + [{'type': 'circle', 'cx': 100, 'cy': 0, 'r': 10}])
        click(editor, (20.0, 0.0))
        click(editor, (110.0, 0.0), additive=True)
        self.assertEqual(editor.selection, [0, 4])
        self.assertIsNone(editor.selected)
        editor.move((80.0, -20.0), PIXEL)
        editor.press((80.0, -20.0), PIXEL)
        editor.move((120.0, 20.0), PIXEL)
        editor.release((120.0, 20.0), PIXEL)
        self.assertEqual(editor.selection, [4])                   # 整个在框里的才选中
        editor.move((20.0, 0.0), PIXEL)
        editor.double_click()
        self.assertEqual(editor.selection, [0, 1, 2, 3])
        editor.move((20.0, 0.0), PIXEL)                           # 拖其中一条: 选中的一起走
        editor.press((20.0, 0.0), PIXEL)
        editor.move((20.0, 10.0), PIXEL)
        editor.release((20.0, 10.0), PIXEL)
        self.assertEqual((editor.shapes[2]['y1'], editor.shapes[4]['cy']), (40, 0))
        self.assertTrue(editor.key('delete'))
        self.assertEqual(len(editor.shapes), 1)

    def test_every_shape_has_fields_handles_and_survives_transforms(self):
        shapes = [{'type': 'line', 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 0}, {'type': 'arc', 'cx': 0, 'cy': 0, 'r': 5, 'a0': 10, 'a1': 80},
                  {'type': 'slot', 'x1': 0, 'y1': 0, 'x2': 30, 'y2': 0, 'w': 10}, {'type': 'ngon', 'cx': 0, 'cy': 0, 'r': 20, 'sides': 6, 'angle': 0},
                  {'type': 'ellipse', 'cx': 0, 'cy': 0, 'rx': 30, 'ry': 10, 'angle': 30}, {'type': 'point', 'x': 1, 'y': 2},
                  {'type': 'spline', 'points': [[0, 0], [10, 10], [20, 0]], 'closed': False},
                  {'type': 'text', 'x': 0, 'y': 0, 'text': '文本', 'height': 10, 'angle': 0},
                  {'type': 'rect', 'cx': 0, 'cy': 0, 'w': 4, 'h': 2}, {'type': 'polygon', 'points': [[0, 0], [5, 0], [0, 5]]}]
        from genform.sketcher import handles
        for index, shape in enumerate(shapes):
            editor = SketchEditor(shapes=shapes)
            editor.selected = index
            self.assertTrue(editor.panel()['fields'], shape['type'])
            self.assertTrue(handles(shape), shape['type'])
            editor.drawing()
            shifted = geom.moved(shape, 3, 4)
            flipped = geom.mirrored(geom.mirrored(shifted, (0, 0), (1, 2)), (0, 0), (1, 2))
            if shape['type'] not in ('rect', 'text'):
                self.assertAlmostEqual(geom.length(flipped), geom.length(shape), places=6, msg=shape['type'])
        line = SketchEditor(shapes=shapes)
        line.selected = 0
        line.set_field('len', 25)
        line.set_field('dir', 90)
        self.assertEqual((round(line.shapes[0]['x2'], 9), line.shapes[0]['y2']), (0.0, 25.0))


if __name__ == '__main__':
    unittest.main()
