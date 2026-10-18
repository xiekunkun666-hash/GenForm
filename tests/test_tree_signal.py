# -*- coding: utf-8 -*-
"""设计树只在内容真的变了时通知 QML (每通知一次, 整棵树的委托都要销毁重建)。"""
import unittest

from PySide6.QtGui import QGuiApplication

from genform.app import AppController
from genform.session import Session

_APP = QGuiApplication.instance() or QGuiApplication([])


class TreeSignal(unittest.TestCase):
    def test_tree_changes_only_when_content_does(self):
        controller = AppController(Session())
        fired = []
        controller.treeChanged.connect(lambda: fired.append(1))
        first = controller.tree
        controller.changed.emit()                       # 什么都没变: 不通知
        self.assertEqual(fired, [])
        self.assertIs(controller.tree, first)
        controller.session.execute('sketch', {'shapes': [{'type': 'rect', 'w': 10, 'h': 10}]})
        self.assertGreaterEqual(len(fired), 1)          # 多了一个草图: 通知
        self.assertTrue(any(row.get('kind') == 'feature' for row in controller.tree))
        count = len(fired)
        controller.changed.emit()
        self.assertEqual(len(fired), count)


if __name__ == '__main__':
    unittest.main()
