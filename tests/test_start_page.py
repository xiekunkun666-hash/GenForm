"""开始页: 刚打开软件先显示 (选新建哪一种 / 打开文件), 选了就收起; 最近文件记在设置里; AI 接口改模型时收起。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from genform.settings import RECENT, Settings
from genform.session import Session
from tests.test_assembly_parts import Files


class Recent(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        self.file = os.path.join(self.folder, 'settings.json')

    def test_remember_moves_to_front_and_survives_reload(self):
        settings = Settings(self.file)
        first, second = os.path.join(self.folder, 'a.gform'), os.path.join(self.folder, 'b.gasm')
        settings.remember(first)
        settings.remember(second)
        settings.remember(first.upper() if os.name == 'nt' else first)      # 同一个文件 (Windows 不分大小写): 只留一条
        again = Settings(self.file)
        self.assertEqual(len(again.recent), 2)
        self.assertEqual(os.path.normcase(again.recent[0]), os.path.normcase(first))
        again.forget(first)
        self.assertEqual(Settings(self.file).recent, [os.path.normpath(second)])

    def test_list_is_capped(self):
        settings = Settings(self.file)
        for number in range(RECENT + 5):
            settings.remember(os.path.join(self.folder, f'{number}.gform'))
        self.assertEqual(len(settings.recent), RECENT)
        self.assertTrue(settings.recent[0].endswith(f'{RECENT + 4}.gform'))

    def test_bad_entries_are_dropped(self):
        with open(self.file, 'w', encoding='utf-8') as handle:
            json.dump({'recent': ['x.gform', 3, '', None]}, handle)
        self.assertEqual(Settings(self.file).recent, ['x.gform'])


class Screen(unittest.TestCase):
    def setUp(self):
        self.files = Files(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.dict(os.environ, {'GENFORM_SETTINGS': os.path.join(folder.name, 'settings.json')})
        patcher.start()
        self.addCleanup(patcher.stop)
        from PySide6.QtGui import QGuiApplication
        self.qt = QGuiApplication.instance() or QGuiApplication([])
        from genform.app import AppController
        self.controller = AppController(Session())

    def test_starts_on_the_start_page_and_new_closes_it(self):
        self.assertTrue(self.controller.startPage)
        self.controller.newOf('assembly')
        self.assertFalse(self.controller.startPage)
        self.assertEqual(self.controller.docKind, 'assembly')
        self.controller.showStart()
        self.assertTrue(self.controller.startPage)
        self.controller.newOf('part')
        self.assertFalse(self.controller.startPage)
        self.assertEqual(self.controller.docKind, 'part')

    def test_opening_a_file_closes_it_and_lists_the_file(self):
        part = self.files.block('底板', bind=True)
        self.controller.openDocument(part)
        self.assertFalse(self.controller.startPage)
        rows = self.controller.recentFiles
        self.assertEqual([(row['name'], row['kind']) for row in rows], [('底板', 'part')])
        where = os.path.join(self.files.folder.name, 'one.gasm')
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump({'format': 'genform-assembly', 'version': 1,
                       'parts': [{'name': '底板', 'file': '底板.gform', 'move': [0, 0, 0], 'turn': [0, 0, 0]}]}, handle, ensure_ascii=False)
        self.controller.showStart()
        self.controller.dropFiles([where])                              # 拖进来的也一样
        self.assertFalse(self.controller.startPage)
        self.assertEqual([row['kind'] for row in self.controller.recentFiles], ['assembly', 'part'])
        os.remove(where)                                                # 文件没了: 列表里不显示
        self.assertEqual([row['kind'] for row in self.controller.recentFiles], ['part'])
        self.controller.forgetRecent(part)
        self.assertEqual(self.controller.recentFiles, [])

    def test_api_commands_that_change_the_model_close_it(self):
        from genform.api.server import ApiServer
        server = ApiServer(Session(), port=0)
        self.addCleanup(server.close)
        server.controller = self.controller
        replies = []
        server._handle({'cmd': 'get_model'}, replies.append)
        self.assertTrue(self.controller.startPage)                      # 只看不改: 开始页留着
        server._handle({'cmd': 'new_document'}, replies.append)
        self.assertFalse(self.controller.startPage)


if __name__ == '__main__':
    unittest.main()
