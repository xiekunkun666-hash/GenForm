"""批量打开、拖入和装配体网格加载，不启动窗口。"""
import os
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication

from genform.app import AppController
from genform.session import Session
from tests.test_assembly_parts import Files
from tests.test_assembly_tree import FakeViewport


class BatchImport(unittest.TestCase):
    def setUp(self):
        self.files = Files(self)
        self.settings = tempfile.TemporaryDirectory()
        self.addCleanup(self.settings.cleanup)
        self.environment = patch.dict(os.environ, {'GENFORM_SETTINGS': os.path.join(self.settings.name, 'settings.json')})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.qt = QGuiApplication.instance() or QGuiApplication([])
        self.controller = AppController(Session())
        self.controller.viewport = FakeViewport()
        self.addCleanup(self.controller.sim._live_timer.stop)
        self.notices = []
        self.controller.notice.connect(self.notices.append)

    def stl(self, name='网格.STL'):
        target = os.path.join(self.files.folder.name, name)
        with open(target, 'w', encoding='ascii') as handle:
            handle.write('solid mesh\nfacet normal 0 0 1\nouter loop\n'
                         'vertex 0 0 0\nvertex 10 0 0\nvertex 0 20 0\n'
                         'endloop\nendfacet\nendsolid mesh\n')
        return target

    def step(self):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
        target = os.path.join(self.files.folder.name, '底板.STEP')
        writer = STEPControl_Writer()
        writer.Transfer(BRepPrimAPI_MakeBox(10, 20, 3).Shape(), STEPControl_AsIs)
        self.assertEqual(writer.Write(target), IFSelect_RetDone)
        return target

    def test_mixed_drop_creates_independent_components_and_one_mesh_query(self):
        paths = [self.step(), self.stl(), self.files.block('零件')]
        with patch.object(self.controller.session, 'query', wraps=self.controller.session.query) as query:
            self.controller.dropFiles([QUrl.fromLocalFile(path) for path in paths])
        meshes = [call for call in query.call_args_list if call.args[0] == 'meshes']
        self.assertEqual(len(meshes), 1)
        self.assertEqual(self.controller.docKind, 'assembly')
        self.assertFalse(self.controller.startPage)
        self.assertEqual([part['path'] for part in self.controller.sim._parts], paths)
        self.assertEqual([part['move'] for part in self.controller.sim._parts], [[0, 0, 0]] * 3)
        self.assertEqual(len(self.controller.viewport.extras), 3)
        self.assertEqual(self.controller.viewport.extras[1]['geometry'], 'mesh')

    def test_append_keeps_existing_components_and_duplicate_files(self):
        first, second = self.files.block('甲'), self.stl()
        self.controller.openFiles([first, second])
        self.controller.dropFiles([first, second])
        self.assertEqual([part['path'] for part in self.controller.sim._parts], [first, second, first, second])
        self.assertEqual(len(self.controller.viewport.extras), 4)

    def test_single_stl_can_be_opened_and_remembered(self):
        target = self.stl()
        self.controller.openDocument(target)
        self.assertEqual(self.controller.docKind, 'assembly')
        self.assertEqual(len(self.controller.viewport.extras), 1)
        self.assertEqual(self.controller.recentFiles[0]['kind'], 'stl')

    def test_failed_file_keeps_other_meshes_and_component_indices(self):
        target = os.path.join(self.files.folder.name, '坏.step')
        with open(target, 'w', encoding='ascii') as handle:
            handle.write('invalid step')
        self.controller.dropFiles([self.stl(), target, self.files.block('好的')])
        self.assertEqual([number for number, mesh in self.controller.sim._shown], [0, 2])
        self.assertEqual([mesh['pick'] for mesh in self.controller.viewport.extras], [0, 2])
        self.assertIn('坏', self.controller.sim._assembly['error'])
        self.assertTrue(any('加载失败' in notice for notice in self.notices))

    def test_save_reopen_preserves_mesh_placement(self):
        self.controller.openFiles([self.files.block('底座'), self.stl()])
        self.controller.sim.placePart(1, 'move', 0, '35')
        self.controller.sim.placePart(1, 'turn', 2, '90')
        target = os.path.join(self.files.folder.name, 'pair.gasm')
        self.controller.saveDocument(target)
        self.controller.openDocument(target)
        self.assertEqual(self.controller.sim._parts[1]['move'], [35, 0, 0])
        self.assertEqual(self.controller.sim._parts[1]['turn'], [0, 0, 90])
        self.assertEqual(len(self.controller.viewport.extras), 2)

    def test_current_part_is_preserved(self):
        first = self.files.block('当前')
        viewport = self.controller.viewport
        self.controller.viewport = None
        self.controller.openDocument(first)
        self.controller.viewport = viewport
        document = self.controller.session.document
        self.controller.openFiles([self.stl(), self.files.block('另一个')])
        self.assertIs(self.controller.session.document, document)
        self.assertEqual(self.controller.sim._parts[0]['path'], '')
        self.assertEqual(len(self.controller.sim._parts), 3)

    def test_invalid_paths_and_formats_are_skipped(self):
        unsupported = os.path.join(self.files.folder.name, 'note.txt')
        with open(unsupported, 'w', encoding='ascii') as handle:
            handle.write('ignored')
        self.controller.openFiles([self.stl(), unsupported, os.path.join(self.files.folder.name, 'missing.stl')])
        self.assertEqual(len(self.controller.sim._parts), 1)
        self.assertTrue(any('跳过 2' in notice for notice in self.notices))

    def test_sketch_edit_blocks_batch_open_and_insert(self):
        self.controller._sketch = object()
        target = self.stl()
        self.controller.dropFiles([target, target])
        self.controller.sim.addParts([target, target])
        self.assertEqual(self.controller.docKind, 'part')
        self.assertFalse(any(part['path'] for part in self.controller.sim._parts))
        self.assertEqual(len(self.notices), 2)


if __name__ == '__main__':
    unittest.main()
