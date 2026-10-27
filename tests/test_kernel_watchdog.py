# -*- coding: utf-8 -*-
"""内核工作进程的看门狗: 一个特征算太久就停掉进程、换新的, 回复说清楚是卡住了; 之后照常能算。"""
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from genform.kernel import client
from genform.operations import Operation, operation_scope

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
    def test_cancel_stops_only_owned_job_and_next_build_works(self):
        builder = client.ProcessBuilder()
        self.addCleanup(builder.close)
        owner, unrelated = Operation('owned'), Operation('other')
        cancelled = []
        with operation_scope(owner):
            builder.build(PLATE, None, lambda model, error: cancelled.append((model, error)))
        old_process = builder._process
        self.assertFalse(builder.cancel(unrelated))
        self.assertIs(builder._process, old_process)
        owner.cancel()
        self.assertTrue(builder.cancel(owner))
        old_process.join(1)
        self.assertFalse(old_process.is_alive())
        self.assertEqual(len(cancelled), 1)
        self.assertIsNone(cancelled[0][0])
        self.assertIn('取消', cancelled[0][1])
        model, error = wait_for(builder, PLATE)
        self.assertIsNone(error)
        self.assertTrue(model['has_body'])

    def test_total_deadline_is_not_reset_by_progress(self):
        builder = client.ProcessBuilder()
        self.addCleanup(builder.close)
        with patch.object(client, 'TASK_TIMEOUT', 30):
            builder.build(PLATE, None, lambda model, error: None)
            remaining = builder._deadline.remainingTime()
            builder._on_arrived(builder._generation, ('progress', builder._flight[0], (1, 2, '草图')))
            self.assertLessEqual(builder._deadline.remainingTime(), remaining)
            box, loop = [], QEventLoop()
            builder._flight[2].append(lambda model, error: (box.append(error), loop.quit()))
            QTimer.singleShot(1000, loop.quit)
            loop.exec()
        self.assertTrue(box)
        self.assertIn('总时限', box[0])

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
