"""草图编辑器: 用鼠标画、拖、填尺寸 (不开窗口, 直接喂平面坐标)。pixel=0.1 即一个像素 0.1 mm。"""
import unittest

from genform import planes, sketchgeom
from genform.session import Session
from genform.sketcher import SketchEditor, grid_step

PIXEL = 0.1


def click(editor, point):
    editor.move(point, PIXEL)
    editor.press(point, PIXEL)
    editor.release(point, PIXEL)


def drag(editor, start, end):
    editor.move(start, PIXEL)
    editor.press(start, PIXEL)
    editor.move(end, PIXEL)
    editor.release(end, PIXEL)


class DrawingTests(unittest.TestCase):
    def test_rectangle_by_two_clicks_snaps_to_grid(self):
        editor = SketchEditor()
        self.assertEqual(editor.tool, 'rect')
        click(editor, (-20.2, -15.1))
        editor.move((19.8, 15.3), PIXEL)
        self.assertEqual(editor.preview()['w'], 40.0)             # 没点第二下之前已经能看到大小
        click(editor, (19.8, 15.3))
        self.assertEqual(editor.shapes, [{'type': 'rect', 'cx': 0.0, 'cy': 0.0, 'w': 40.0, 'h': 30.0}])
        self.assertEqual(editor.selected, 0)
        self.assertIsNone(editor.draft)

    def test_rectangle_by_press_and_drag(self):
        editor = SketchEditor()
        drag(editor, (0.0, 0.0), (30.0, 10.0))
        self.assertEqual(editor.shapes[0], {'type': 'rect', 'cx': 15.0, 'cy': 5.0, 'w': 30.0, 'h': 10.0})

    def test_circle_and_snap_to_existing_corner(self):
        editor = SketchEditor(shapes=[{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 40.5, 'h': 30.5}])
        editor.set_tool('circle')
        click(editor, (20.4, 15.4))                               # 离角 (20.25, 15.25) 不到 9 像素: 吸到角上而不是格子上
        self.assertTrue(editor.snapped)
        click(editor, (25.25, 15.25))
        self.assertEqual(editor.shapes[1], {'type': 'circle', 'cx': 20.25, 'cy': 15.25, 'r': 5.0})

    def test_line_chain_closes_on_first_point_or_ends_on_enter(self):
        editor = SketchEditor()
        editor.set_tool('line')
        for point in ((0, 0), (30, 0), (30, 20)):
            click(editor, point)
        click(editor, (0.3, 0.2))                                 # 点回起点附近 → 闭合, 这一串结束
        self.assertEqual([shape['type'] for shape in editor.shapes], ['line'] * 3)
        self.assertEqual((editor.shapes[2]['x2'], editor.shapes[2]['y2']), (0.0, 0.0))
        self.assertIsNone(editor.draft)
        self.assertEqual(len(sketchgeom.loops(editor.shapes)[0]), 1)
        for point in ((50, 0), (60, 0), (60, 10)):
            click(editor, point)
        self.assertTrue(editor.key('enter'))                      # 回车: 结束这一串 (开口)
        self.assertEqual(len(editor.shapes), 5)
        self.assertEqual(sketchgeom.loops(editor.shapes)[1], 1)

    def test_escape_cancels_step_by_step(self):
        editor = SketchEditor()
        click(editor, (0, 0))
        self.assertTrue(editor.key('escape'))                     # 先取消正在画的
        self.assertIsNone(editor.draft)
        self.assertTrue(editor.key('escape'))                     # 再退回选择工具
        self.assertEqual(editor.tool, 'select')
        self.assertFalse(editor.key('escape'))                    # 没东西可取消了: 交给外面 (退出草图要另外确认)

    def test_zero_size_shapes_are_not_created(self):
        editor = SketchEditor()
        click(editor, (5, 5))
        click(editor, (5, 20))
        self.assertEqual(editor.shapes, [])

    def test_grid_step_follows_zoom(self):
        self.assertEqual(grid_step(0.01), 0.1)
        self.assertEqual(grid_step(0.1), 1.0)
        self.assertEqual(grid_step(1.0), 10.0)


class EditingTests(unittest.TestCase):
    def setUp(self):
        self.editor = SketchEditor(shapes=[{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 40, 'h': 30},
                                           {'type': 'circle', 'cx': 60, 'cy': 0, 'r': 10}])
        self.assertEqual(self.editor.tool, 'select')

    def test_click_selects_and_empty_click_clears(self):
        click(self.editor, (20.2, 3.0))                           # 矩形右边
        self.assertEqual(self.editor.selected, 0)
        click(self.editor, (60 + 10.3, 0.0))                      # 圆周
        self.assertEqual(self.editor.selected, 1)
        click(self.editor, (0.0, 0.0))                            # 矩形里面是空的 (只有轮廓线能点)
        self.assertIsNone(self.editor.selected)

    def test_drag_outline_moves_the_whole_shape(self):
        drag(self.editor, (20.0, 5.0), (30.0, 12.0))
        self.assertEqual((self.editor.shapes[0]['cx'], self.editor.shapes[0]['cy']), (10.0, 7.0))
        self.assertEqual((self.editor.shapes[0]['w'], self.editor.shapes[0]['h']), (40, 30))

    def test_drag_corner_resizes_and_keeps_the_opposite_corner(self):
        click(self.editor, (20.0, 5.0))
        drag(self.editor, (20.0, 15.0), (30.0, 25.0))             # 右上角
        self.assertEqual(self.editor.shapes[0], {'type': 'rect', 'cx': 5.0, 'cy': 5.0, 'w': 50.0, 'h': 40.0})

    def test_drag_circle_rim_changes_radius(self):
        click(self.editor, (70.0, 0.0))
        drag(self.editor, (70.0, 0.0), (75.0, 0.0))
        self.assertEqual(self.editor.shapes[1]['r'], 15.0)
        self.assertEqual(self.editor.shapes[1]['cx'], 60)

    def test_fields_give_exact_dimensions(self):
        click(self.editor, (70.0, 0.0))
        fields = {field['key']: field['value'] for field in self.editor.fields() if field['type'] == 'number'}
        self.assertEqual(fields, {'offset': 0.0, 'd': 20.0, 'cx': 60.0, 'cy': 0.0})
        self.editor.set_field('d', 12.5)
        self.editor.set_field('cx', 50)
        self.editor.set_field('d', -3)                            # 不成立的值不接受
        self.assertEqual(self.editor.shapes[1], {'type': 'circle', 'cx': 50.0, 'cy': 0, 'r': 6.25})

    def test_delete_removes_the_selected_shape(self):
        click(self.editor, (20.0, 5.0))
        self.assertTrue(self.editor.key('delete'))
        self.assertEqual([shape['type'] for shape in self.editor.shapes], ['circle'])
        self.assertFalse(self.editor.key('delete'))

    def test_drawing_marks_states_and_dimension_label(self):
        click(self.editor, (20.0, 5.0))
        lines, points, labels = self.editor.drawing()
        self.assertEqual(sum(1 for line in lines if line[2] == 2), 4)
        self.assertEqual(len(points), 4)
        self.assertEqual(labels[0][0], '40 × 30')


class ResultTests(unittest.TestCase):
    def test_sketch_drawn_by_mouse_builds_a_solid(self):
        editor = SketchEditor(plane='XZ')
        drag(editor, (-10.0, 0.0), (10.0, 30.0))
        editor.set_tool('circle')
        click(editor, (0.0, 15.0))
        click(editor, (5.0, 15.0))
        session = Session()
        replies = []
        session.execute('sketch', editor.params(), replies.append)
        session.execute('extrude', {'distance': 8}, replies.append)
        self.assertTrue(all(reply['ok'] for reply in replies), replies)
        self.assertEqual(replies[1]['model']['body']['size_mm'], [20, 8, 30])     # 前视基准面: 朝 -Y 拉出 8

    def test_plane_coordinates_round_trip_through_a_ray(self):
        for plane in planes.PLANES:
            world = planes.to_world([(12.0, -7.0)], plane, 5.0)[0]
            _, _, _, normal = planes.frame(plane, 5.0)
            start = world + normal * 50 + (0.3, 0.2, 0.1)
            direction = world - start
            self.assertEqual(tuple(round(v, 9) for v in planes.from_ray(start, direction, plane, 5.0)), (12.0, -7.0))


if __name__ == '__main__':
    unittest.main()
