"""相机换算、拾取、参数面板、MCP 适配 — 都不开窗口。"""
import json
import unittest

import numpy as np

from genform import forms
from genform.api import mcp_server
from genform.session import Session
from genform.view import picking
from genform.view.camera import Camera

W, H = 800, 600


def plate(session):
    session.execute('sketch', {'shapes': [{'type': 'rect', 'w': 40, 'h': 30}]})
    session.execute('extrude', {'distance': 10})


class CameraTests(unittest.TestCase):
    def test_project_and_ray_are_inverse(self):
        camera = Camera()
        camera.fit((-20, -15, 0), (20, 15, 10), W / H)
        point = np.array([12.0, -7.0, 10.0])
        screen, depth = camera.project(point, W, H)
        origin, direction = camera.ray(screen[0, 0], screen[0, 1], W, H)
        reach = (point - origin) @ direction
        np.testing.assert_allclose(origin + direction * reach, point, atol=1e-6)
        self.assertGreater(depth[0], 0)

    def test_fit_keeps_the_box_on_screen(self):
        camera = Camera()
        for view in ('iso', 'top', 'front', 'right'):
            camera.set_view(view)
            camera.fit((-20, -15, 0), (20, 15, 10), W / H)
            corners = np.array([[x, y, z] for x in (-20, 20) for y in (-15, 15) for z in (0, 10)])
            screen, _ = camera.project(corners, W, H)
            self.assertTrue((screen[:, 0] > 0).all() and (screen[:, 0] < W).all(), view)
            self.assertTrue((screen[:, 1] > 0).all() and (screen[:, 1] < H).all(), view)

    def test_right_view_faces_the_right_datum_plane(self):
        camera = Camera()
        camera.set_view('right')                    # 从 +X 往回看: Y 朝右, Z 朝上 (和右视基准面的坐标一致)
        screen, _ = camera.project(np.array([[0, 0, 0], [0, 10, 0], [0, 0, 10]]), W, H)
        self.assertGreater(screen[1, 0], screen[0, 0])
        self.assertLess(screen[2, 1], screen[0, 1])
        self.assertGreater(camera.eye()[0], 0)

    def test_front_view_has_x_right_and_z_up(self):
        camera = Camera()
        camera.set_view('front')
        screen, _ = camera.project(np.array([[0, 0, 0], [10, 0, 0], [0, 0, 10]]), W, H)
        self.assertGreater(screen[1, 0], screen[0, 0])
        self.assertLess(screen[2, 1], screen[0, 1])

    def test_pan_moves_the_scene_with_the_cursor_and_zoom_keeps_the_anchor(self):
        camera = Camera()
        before, _ = camera.project(np.zeros(3), W, H)
        camera.pan(30, -20, H)
        after, _ = camera.project(np.zeros(3), W, H)
        np.testing.assert_allclose(after - before, [[30, -20]], atol=1e-6)
        anchor = np.array([15.0, 5.0, 3.0])
        fixed, _ = camera.project(anchor, W, H)
        camera.zoom(0.5, anchor)
        moved, _ = camera.project(anchor, W, H)
        np.testing.assert_allclose(moved, fixed, atol=1e-6)


class PickingTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        plate(self.session)
        self.model = self.session.model
        self.camera = Camera()
        self.camera.fit(self.model['props']['bbox_min'], self.model['props']['bbox_max'], W / H)

    def at(self, point):
        screen, _ = self.camera.project(np.asarray(point, dtype=float), W, H)
        return picking.pick(self.camera, screen[0, 0], screen[0, 1], W, H, self.model)

    def test_face_under_cursor(self):
        kind, identifier = self.at([3.0, 2.0, 10.0])
        self.assertEqual(kind, 'face')
        face = self.model['faces'][identifier]
        np.testing.assert_allclose(face['normal'], (0, 0, 1), atol=1e-9)

    def test_edge_wins_near_its_line_and_hidden_edges_are_ignored(self):
        kind, identifier = self.at([0.0, -15.0, 10.0])        # 顶面靠前的那条边的中点
        self.assertEqual(kind, 'edge')
        edge = next(edge for edge in self.model['edges'] if edge['id'] == identifier)
        np.testing.assert_allclose(edge['mid'], (0, -15, 10), atol=1e-6)
        hidden = self.at([0.0, 15.0, 0.0])                    # 底面靠后的边被实体挡住: 点到的是挡在前面的面
        self.assertNotEqual(hidden, ('edge', next(e['id'] for e in self.model['edges']
                                                  if np.allclose(e['mid'], (0, 15, 0)))))

    def test_datum_plane_under_cursor_takes_the_nearest(self):
        origin, direction = np.array([10.0, -100.0, 10.0]), np.array([0.0, 1.0, 0.0])
        self.assertEqual(picking.pick_plane(origin, direction, ['XY', 'XZ', 'YZ'], 45.0), 'XZ')
        self.assertIsNone(picking.pick_plane(origin, direction, ['XY', 'YZ'], 45.0))      # 和 XY 平行, 打不到 YZ 的方框
        self.assertIsNone(picking.pick_plane(np.array([80.0, -100.0, 10.0]), direction, ['XZ'], 45.0))

    def test_empty_space(self):
        self.assertIsNone(picking.pick(self.camera, 2, 2, W, H, self.model))
        self.assertIsNone(picking.pick(self.camera, 2, 2, W, H, {}))

    def test_many_segments_match_a_full_scan_in_both_layouts(self):
        # 线段多 (> 4000) 时先用空间包围盒筛: 结果要和把全部线段投影到屏幕上一条条比一样; 草图线是摊平成点给的
        rng = np.random.default_rng(4)
        start = rng.uniform(-20, 20, (6000, 3))
        segments = np.stack([start, start + rng.normal(0, 1.5, (6000, 3))], axis=1).astype(np.float32)
        for perspective in (True, False):
            camera = Camera()
            camera.perspective = perspective
            camera.fit((-20, -20, -20), (20, 20, 20), W / H)
            for _ in range(30):
                camera.yaw += 3.0                   # 每次视角都变
                x, y = rng.uniform(100, 700), rng.uniform(100, 500)
                screen, depth = camera.project(segments.reshape(-1, 3), W, H)
                a, b = screen[0::2], screen[1::2]
                span = b - a
                along = np.clip(np.einsum('ij,ij->i', [x, y] - a, span) / np.einsum('ij,ij->i', span, span), 0, 1)
                gap = np.linalg.norm(a + span * along[:, None] - [x, y], axis=1)
                gap[(depth[0::2] <= 0) | (depth[1::2] <= 0)] = np.inf
                pairs = picking.nearest_segment(camera, x, y, W, H, segments)
                flat = picking.nearest_segment(camera, x, y, W, H, segments.reshape(-1, 3), 'sketches')
                self.assertEqual(flat[:2], pairs[:2])
                if gap.min() <= picking.NEAR_PIXELS:        # 附近有线段: 必须找到真正最近的那条
                    self.assertEqual(pairs[0], int(gap.argmin()))
                    self.assertAlmostEqual(pairs[1], float(gap.min()), places=6)
                else:                                       # 附近没有: 给出的 (如果有) 也够不着
                    self.assertTrue(pairs[0] == -1 or pairs[1] > picking.NEAR_PIXELS)


class HideSolidTests(unittest.TestCase):
    """零件里有好几块不相连的实体时, 点中一块隐藏的只是那一块。"""

    def setUp(self):
        from genform.app import solid_blocks
        from genform.view.viewport import _without_faces
        self.blocks, self.without = solid_blocks, _without_faces
        self.session = Session()
        self.session.execute('sketch', {'shapes': [{'type': 'rect', 'cx': -30, 'cy': 0, 'w': 20, 'h': 20},
                                                    {'type': 'rect', 'cx': 30, 'cy': 0, 'w': 20, 'h': 20}]})
        self.session.execute('extrude', {'distance': 10})           # 两块分开的方块
        self.model = self.session.model
        self.camera = Camera()
        self.camera.fit(self.model['props']['bbox_min'], self.model['props']['bbox_max'], W / H)

    def at(self, model, point):
        screen, _ = self.camera.project(np.asarray(point, dtype=float), W, H)
        return picking.pick(self.camera, screen[0, 0], screen[0, 1], W, H, model)

    def test_separate_solids_are_separate_blocks(self):
        owner, blocks = self.blocks(self.model['faces'])
        self.assertEqual(sorted(len(block) for block in blocks), [6, 6])
        for block in blocks:
            xs = {round(self.model['faces'][index]['center'][0]) > 0 for index in block}
            self.assertEqual(len(xs), 1)                            # 一块里的面都在同一边
        self.assertEqual(self.blocks([{'id': 0}, {'id': 1}])[1], [[0, 1]])      # 没有边的信息: 当成一整块

    def test_hiding_one_block_keeps_the_other_drawn_and_pickable(self):
        _, blocks = self.blocks(self.model['faces'])
        left = next(block for block in blocks if self.model['faces'][block[0]]['center'][0] < 0)
        shown = self.without(self.model, set(left))
        self.assertFalse(np.isin(shown['tri_face'], left).any())
        self.assertGreater(len(shown['tris']), 0)
        kept_edges = set(shown['segment_edge'].tolist())
        left_edges = {edge for index in left for edge in self.model['faces'][index]['edges']}
        self.assertFalse(kept_edges & left_edges)                   # 隐藏那块的边也不画
        self.assertIsNone(self.at(shown, [-30.0, 0.0, 10.0]))       # 点不着隐藏了的那块
        hit = self.at(shown, [30.0, 0.0, 10.0])
        self.assertEqual(hit[0], 'face')
        self.assertNotIn(hit[1], left)
        self.assertIs(self.without(self.model, set()), self.model)

    def test_hide_clicked_part_or_whole_solid(self):
        import types
        from genform.app import AppController
        session = Session()
        plate(session)                                                  # 40×30×10 的板
        session.execute('sketch', {'plane': 'XY', 'offset': 10, 'shapes': [{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 5}]})
        session.execute('extrude', {'distance': 8})                     # 板上长出一个圆柱: 和板连成一块
        faces = session.model['faces']
        fake = types.SimpleNamespace(session=session, _solid_cache=None, _hidden_keys=set())
        for name in ('_solids', '_part_faces', '_solid_faces', '_set_faces_hidden', '_hidden_faces'):
            setattr(fake, name, types.MethodType(getattr(AppController, name), fake))
        fake._face_key = AppController._face_key
        boss = next(face['id'] for face in faces if face['type'] == 'cylinder')
        part = fake._part_faces(boss)
        self.assertEqual({faces[index]['feature'] for index in part}, {faces[boss]['feature']})
        self.assertLess(len(part), len(faces))                          # 只是圆柱那部分
        self.assertEqual(sorted(fake._solid_faces([boss])), list(range(len(faces))))     # 整块实体 = 全部面
        fake._set_faces_hidden(part, True)
        self.assertEqual(fake._hidden_faces(), set(part))
        fake._set_faces_hidden(part, False)
        self.assertEqual(fake._hidden_faces(), set())


class FormTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()

    def test_extrude_form_defaults_to_the_latest_sketch(self):
        self.assertIn('还没有草图', forms.new_form('extrude', self.session)['fields'][0]['value'])
        self.session.execute('sketch', {'shapes': [{'type': 'rect', 'w': 55, 'h': 30}]})
        form = forms.new_form('extrude', self.session)
        self.assertEqual(next(f for f in form['fields'] if f['key'] == 'sketch')['value'], 'f1')
        self.assertEqual([o['value'] for o in next(f for f in form['fields'] if f['key'] == 'op')['options']], ['add'])
        name, args = forms.to_command(form, self.session)
        replies = []
        self.session.execute(name, args, replies.append)
        self.assertTrue(replies[0]['ok'], replies)

    def test_edit_extrude_changes_one_value_and_keeps_the_rest(self):
        plate(self.session)
        form = forms.feature_form(self.session.document.features[1])
        for field in form['fields']:
            if field['key'] == 'distance':
                field['value'] = 25.0
        name, args = forms.to_command(form, self.session)
        replies = []
        self.session.execute(name, args, replies.append)
        self.assertEqual(replies[0]['model']['body']['size_mm'], [40, 30, 25])

    def test_fillet_uses_the_edges_selected_in_the_view(self):
        plate(self.session)
        vertical = [edge['id'] for edge in self.session.model['edges'] if edge['dir'] and abs(edge['dir'][2]) == 1]
        self.session.selection['edges'] = vertical[:2]
        form = forms.new_form('fillet', self.session)
        self.assertIn('已选 2 条边', form['fields'][0]['value'])
        name, args = forms.to_command(form, self.session)
        self.assertEqual((name, len(args['edges']), args['radius']), ('fillet', 2, 2.0))
        replies = []
        self.session.execute(name, args, replies.append)
        self.assertTrue(replies[0]['ok'], replies)


class McpTests(unittest.TestCase):
    def setUp(self):
        self.backend = mcp_server.HeadlessBackend()

    def rpc(self, method, **params):
        return mcp_server.respond(self.backend, {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})

    def test_handshake_and_tool_list(self):
        hello = self.rpc('initialize')['result']
        self.assertIn('tools', hello['capabilities'])
        self.assertIn('草图', hello['instructions'])
        tools = self.rpc('tools/list')['result']['tools']
        self.assertTrue(all({'name', 'description', 'inputSchema'} <= set(tool) for tool in tools))
        self.assertIsNone(mcp_server.respond(self.backend, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}))

    def test_tool_calls_build_a_part(self):
        def tool(name, **arguments):
            answer = self.rpc('tools/call', name=name, arguments=arguments)['result']
            return answer['isError'], json.loads(answer['content'][0]['text'])

        self.assertFalse(tool('sketch', shapes=[{'type': 'circle', 'r': 10}])[0])
        failed, body = tool('extrude', distance=30)
        self.assertFalse(failed)
        self.assertAlmostEqual(body['model']['body']['volume_mm3'], np.pi * 100 * 30, places=2)
        failed, body = tool('fillet', edges='>Z', radius=99)
        self.assertTrue(failed)
        self.assertIn('太大', body['error'])


if __name__ == '__main__':
    unittest.main()
