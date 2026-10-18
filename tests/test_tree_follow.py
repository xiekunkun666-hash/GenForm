# -*- coding: utf-8 -*-
"""设计树跟着视图走: 视图里点了 (选中了) 一个特征, 它在收起的文件夹里就展开; 视图里右键单击弹出所属特征的菜单。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtGui import QGuiApplication

from genform.session import Session

_APP = QGuiApplication.instance() or QGuiApplication([])


def run(session, command, **args):
    replies = []
    session.execute(command, args, replies.append)
    return replies[0]


class TreeFollow(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.dict(os.environ, {'GENFORM_SETTINGS': os.path.join(folder.name, 'settings.json')})     # 不碰用户设置
        patcher.start()
        self.addCleanup(patcher.stop)
        from genform.app import AppController
        self.controller = AppController(Session())
        session = self.session = self.controller.session
        run(session, 'sketch', shapes=[{'type': 'rect', 'w': 100, 'h': 60}])
        self.plate = run(session, 'extrude', distance=3)['id']
        run(session, 'sketch', plane='XY', offset=3, shapes=[{'type': 'rect', 'w': 10, 'h': 10}])
        self.boss = run(session, 'extrude', distance=5)['id']
        run(session, 'set_folder', features=[self.boss], folder='外饰/凸台')

    def rows(self, kind, **match):
        return [row for row in self.controller.tree if row['kind'] == kind and all(row.get(k) == v for k, v in match.items())]

    def collapse_all_folders(self):
        for row in self.rows('folder'):
            if row['expanded']:
                self.controller.toggleExpand(row['id'])

    def test_selecting_a_feature_opens_the_folders_around_it(self):
        self.collapse_all_folders()
        self.assertEqual(self.rows('feature', id=self.boss), [])            # 收起来了: 树上看不到
        self.controller.selectFeature(self.boss)                           # 视图里点中它 (选择一样走这里)
        self.assertTrue(self.rows('feature', id=self.boss)[0]['selected'])
        self.assertTrue(all(row['expanded'] for row in self.rows('folder')))

    def test_selecting_a_folded_sketch_opens_the_feature_it_sits_under(self):
        sketch = self.session.document.find(self.boss)['params']['sketch']
        self.controller.treeAction('root', '', 'collapse_all')
        self.assertEqual(self.rows('feature', id=sketch), [])
        self.controller.selectFeature(sketch)
        self.assertTrue(self.rows('feature', id=sketch)[0]['selected'])
        self.assertTrue(self.rows('feature', id=self.boss)[0]['expanded'])

    def test_folder_closed_by_hand_stays_closed_while_selection_is_unchanged(self):
        self.controller.selectFeature(self.boss)
        self.collapse_all_folders()                                        # 选着它, 用户自己收起来
        self.assertEqual(self.rows('feature', id=self.boss), [])
        self.controller.selectFeature(self.plate)
        self.assertEqual(self.rows('feature', id=self.boss), [])            # 选别的: 不去动它的文件夹

    def test_right_click_on_a_selected_face_asks_for_its_feature_menu(self):
        face = next(face['id'] for face in self.session.model['faces'] if face.get('feature') == self.boss)
        self.session.selection['faces'] = [face]
        self.controller.viewport = MagicMock(click_at=(40.0, 25.0))
        asked = []
        self.controller.viewMenuRequested.connect(lambda *args: asked.append(args))
        self.controller._on_view_menu('face', face)
        self.assertEqual(asked, [(self.boss, 40.0, 25.0)])
        self.assertEqual(self.session.selection['faces'], [face])          # 选中的不变
        self.assertTrue(self.controller.featureMenu(self.boss))           # 菜单有东西

    def test_right_click_on_empty_space_asks_for_the_part_menu(self):
        self.session.selection['feature'] = None
        self.controller.viewport = MagicMock(click_at=(5.0, 6.0))
        asked = []
        self.controller.viewMenuRequested.connect(lambda *args: asked.append(args))
        self.controller._on_view_menu('', -1)
        self.assertEqual(asked, [('', 5.0, 6.0)])


if __name__ == '__main__':
    unittest.main()
