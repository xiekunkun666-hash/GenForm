# -*- coding: utf-8 -*-
"""设计树的文件夹: set_folder 归类 (不重算), 树上按层出文件夹行, 收起来里面的行不出, 出错的特征让文件夹标红。"""
import unittest

from PySide6.QtGui import QGuiApplication

from genform.app import AppController
from genform.kernel.model import rebuild
from genform.session import Session

_APP = QGuiApplication.instance() or QGuiApplication([])


def run(session, command, **args):
    replies = []
    session.execute(command, args, replies.append)
    return replies[0]


class TreeFolders(unittest.TestCase):
    def setUp(self):
        self.controller = AppController(Session())
        session = self.session = self.controller.session
        run(session, 'sketch', shapes=[{'type': 'rect', 'w': 40, 'h': 30}])
        self.plate = run(session, 'extrude', distance=10)['id']
        run(session, 'sketch', plane='XY', offset=10, shapes=[{'type': 'circle', 'r': 5}])
        self.boss = run(session, 'extrude', distance=8)['id']
        run(session, 'sketch', plane='XY', offset=18, shapes=[{'type': 'circle', 'r': 2}])
        self.pin = run(session, 'extrude', distance=4)['id']

    def kinds(self):
        return [(row['kind'], row['name'] if row['kind'] == 'folder' else row['id'], row['depth'])
                for row in self.controller.tree if row['kind'] in ('folder', 'feature') and not row.get('child')]

    def test_nested_folders_make_levels(self):
        steps = len(rebuild._STEPS)
        reply = run(self.session, 'set_folder', features=[self.boss, self.pin], folder='凸台')
        self.assertTrue(reply['ok'], reply)
        run(self.session, 'set_folder', features=[self.pin], folder='凸台/销子')
        self.assertEqual(len(rebuild._STEPS), steps)                  # 只是归类: 没有重算
        self.assertEqual(self.kinds(), [('feature', self.plate, 1), ('folder', '凸台', 1), ('feature', self.boss, 2),
                                        ('folder', '销子', 2), ('feature', self.pin, 3)])
        rows = {row['name']: row for row in self.controller.tree if row['kind'] == 'folder'}
        self.assertEqual((rows['凸台']['count'], rows['销子']['count']), (2, 1))
        self.assertEqual(rows['销子']['folders'], 1)
        pin = next(row for row in self.controller.tree if row['id'] == self.pin)
        self.assertEqual(pin['folders'], 2)

    def test_collapsed_folder_hides_its_rows(self):
        run(self.session, 'set_folder', features=[self.boss, self.pin], folder='凸台')
        folder = next(row for row in self.controller.tree if row['kind'] == 'folder')
        self.controller.toggleExpand(folder['id'])
        self.assertEqual(self.kinds(), [('feature', self.plate, 1), ('folder', '凸台', 1)])
        self.assertFalse(next(row for row in self.controller.tree if row['kind'] == 'folder')['expanded'])

    def test_empty_folder_takes_feature_out_and_undo_restores(self):
        run(self.session, 'set_folder', features=[self.boss], folder='凸台')
        run(self.session, 'set_folder', features=[self.boss], folder='')
        self.assertNotIn('folder', self.session.document.find(self.boss))
        run(self.session, 'undo')
        self.assertEqual(self.session.document.find(self.boss)['folder'], '凸台')

    def test_failed_feature_marks_its_folder(self):
        bad = run(self.session, 'fillet', edges='|Z', radius=100)['id']           # 圆角比零件还大: 失败
        self.assertTrue(self.session.model['status'][bad].startswith('error'))
        run(self.session, 'set_folder', features=[bad], folder='坏的')
        folder = next(row for row in self.controller.tree if row['kind'] == 'folder')
        self.assertEqual(folder['state'], 'error')


if __name__ == '__main__':
    unittest.main()
