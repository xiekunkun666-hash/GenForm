# -*- coding: utf-8 -*-
"""内核工作进程的看门狗: 一个特征算太久就停掉进程、换新的, 回复说清楚是卡住了; 之后照常能算。"""
import unittest

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from genform.kernel import client

_APP = QCoreApplication.instance() or QCoreApplication([])
PLATE = [{'id': 'f1', 'type': 'sketch', 'name': '草图1', 'params': {'plane': 'XY', 'offset': 0.0,
                                                                   'shapes': [{'type': 'rect', 'w': 10, 'h': 10}]}},
         {'id': 'f2', 'type': 'extrude', 'name': '拉伸1', 'params': {'sketch': 'f1', 'distance': 5}}]


def wait_for(builder, features, seconds=60):
    box, loop = [], QEventLoop()
    builder.build(features, None, lambda model, error: (box.append((model, error)), loop.quit()))
    QTimer.singleShot(seconds * 1000, loop.quit)
    loop.exec()
    return box[0] if box else (None, '没等到')


class Watchdog(unittest.TestCase):
    def test_stuck_build_is_stopped_and_next_one_works(self):
        saved = client.STUCK_AFTER
        builder = client.ProcessBuilder()
        try:
            client.STUCK_AFTER = 1                  # 1 毫秒: 新进程连内核都还没加载完, 一定 "卡住"
            model, error = wait_for(builder, PLATE)
            self.assertIsNone(model)
            self.assertIn('卡住', error)
            client.STUCK_AFTER = saved
            model, error = wait_for(builder, PLATE)
            self.assertIsNone(error)
            self.assertTrue(model['has_body'])
        finally:
            client.STUCK_AFTER = saved
            builder.close()


if __name__ == '__main__':
    unittest.main()
