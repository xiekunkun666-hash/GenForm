"""命令层 + 文档 + 会话: 人和 AI 共用的那条路 (不开界面)。"""
import os
import tempfile
import unittest

from genform import commands
from genform.session import Session


class Flow(unittest.TestCase):
    def setUp(self):
        self.session = Session()

    def run_command(self, name, **args):
        replies = []
        self.session.execute(name, args, replies.append)
        self.assertEqual(len(replies), 1, name)
        return replies[0]

    def plate(self):
        sketch = self.run_command('sketch', shapes=[{'type': 'rect', 'w': 40, 'h': 30}])
        self.assertTrue(sketch['ok'], sketch)
        solid = self.run_command('extrude', distance=10)
        self.assertTrue(solid['ok'], solid)
        return sketch['id'], solid['id']

    def test_minimal_loop_sketch_extrude_fillet_edit_export(self):
        sketch, solid = self.plate()
        fillet = self.run_command('fillet', edges='|Z', radius=3)
        self.assertTrue(fillet['ok'], fillet)
        self.assertEqual(fillet['model']['body']['size_mm'], [40, 30, 10])
        edited = self.run_command('edit_feature', id=solid, params={'distance': 25})
        self.assertEqual(edited['model']['body']['size_mm'], [40, 30, 25])
        self.assertEqual([f['status'] for f in edited['model']['features']], ['ok', 'ok', 'ok'])
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'plate.step')
            self.assertTrue(self.run_command('export', path=path)['ok'])
            self.assertGreater(os.path.getsize(path), 500)

    def test_failed_feature_is_reported_with_reason_and_can_be_fixed(self):
        self.plate()
        fillet = self.run_command('fillet', edges='|Z', radius=80)
        self.assertFalse(fillet['ok'])
        self.assertIn('太大', fillet['error'])
        self.assertIn('undo', fillet['hint'])
        fixed = self.run_command('edit_feature', id=fillet['id'], params={'radius': 2})
        self.assertTrue(fixed['ok'], fixed)

    def test_undo_redo_restore_the_model(self):
        self.plate()
        self.run_command('fillet', edges='all', radius=1)
        volume = self.session.model['props']['volume']
        self.assertAlmostEqual(self.run_command('undo')['model']['body']['volume_mm3'], 12000, places=3)
        self.assertAlmostEqual(self.run_command('redo')['model']['body']['volume_mm3'], round(volume, 3), places=3)
        self.run_command('undo'); self.run_command('undo'); self.run_command('undo')
        nothing = self.run_command('undo')
        self.assertFalse(nothing['ok'])
        self.assertIn('没有可撤销', nothing['error'])

    def test_queries_describe_edges_and_faces_for_references(self):
        self.plate()
        edges = self.run_command('list_edges')['edges']
        self.assertEqual(len(edges), 12)
        vertical = [edge for edge in edges if abs(edge['direction'][2]) == 1]
        self.assertEqual(len(vertical), 4)
        picked = self.run_command('chamfer', edges=[{'point': vertical[0]['point']}], distance=2)
        self.assertTrue(picked['ok'], picked)
        faces = self.run_command('list_faces')['faces']
        self.assertEqual(len(faces), 7)
        self.assertTrue(any(face.get('normal') == [0, 0, 1] for face in faces))

    def test_mistakes_get_plain_explanations(self):
        self.assertIn('没有这个命令', self.run_command('extrud')['error'])
        self.assertIn('缺少参数 distance', self.run_command('extrude')['error'])
        self.assertIn('没有参数 depth', self.run_command('extrude', distance=1, depth=2)['error'])
        self.assertIn('还没有草图', self.run_command('extrude', distance=5)['error'])
        self.assertIn('找不到特征', self.run_command('delete_feature', id='f99')['error'])
        self.assertIn('没有打开界面', self.run_command('set_view', view='top')['error'])
        self.assertEqual(self.session.document.features, [])        # 出错的命令不留下半截修改

    def test_save_open_roundtrip_and_rollback(self):
        _, solid = self.plate()
        self.run_command('fillet', edges='|Z', radius=3)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'part.gform')
            self.assertTrue(self.run_command('save_document', path=path)['ok'])
            rolled = self.run_command('rollback', count=2)
            self.assertEqual(rolled['model']['features'][2]['status'], 'skipped')
            self.assertEqual(rolled['model']['body']['faces'], 6)
            self.run_command('new_document')
            self.assertFalse(self.session.model['has_body'])
            opened = self.run_command('open_document', path=path)
            self.assertTrue(opened['ok'], opened)
            self.assertEqual(opened['model']['body']['faces'], 10)
            more = self.run_command('extrude', distance=5, op='add')    # 打开后新特征的 id 不和旧的撞
            self.assertNotIn(more['id'], {'f1', 'f2', 'f3'})

    def test_catalog_is_a_tool_list(self):
        tools = {tool['name']: tool for tool in commands.catalog()}
        self.assertLessEqual({'sketch', 'extrude', 'fillet', 'chamfer', 'edit_feature', 'undo', 'get_model',
                              'list_edges', 'export', 'screenshot'}, set(tools))
        for tool in tools.values():
            self.assertTrue(tool['description'])
            self.assertEqual(tool['input_schema']['type'], 'object')


if __name__ == '__main__':
    unittest.main()
