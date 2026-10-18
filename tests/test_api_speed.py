# -*- coding: utf-8 -*-
"""AI 接口跑得快、回得少: 修改命令只回精简的特征列表, get_model 能只看一个特征,
MCP 端一直用同一条连接 (断了自己重连), 截图直接把图片附在结果里。"""
import base64
import json
import os
import socket
import tempfile
import threading
import unittest

from genform.api import mcp_server
from genform.session import Session


def run(session, command, **args):
    replies = []
    session.execute(command, args, replies.append)
    return replies[0]


class BriefReplies(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.sketch = run(self.session, 'sketch', shapes=[{'type': 'rect', 'w': 40, 'h': 30}, {'type': 'circle', 'r': 5}])
        self.solid = run(self.session, 'extrude', sketch=self.sketch['id'], distance=10)

    def test_change_reply_lists_features_without_params_except_the_new_one(self):
        rows = {row['id']: row for row in self.solid['model']['features']}
        self.assertNotIn('params', rows[self.sketch['id']])
        self.assertEqual(rows[self.solid['id']]['params']['distance'], 10)
        self.assertNotIn('materials', self.solid['model'])
        self.assertEqual(self.solid['model']['body']['size_mm'], [40, 30, 10])
        renamed = run(self.session, 'rename_feature', id=self.sketch['id'], name='底板')
        sketch_row = renamed['model']['features'][0]
        self.assertEqual(sketch_row['params']['shapes'], '2 个图形')       # 草图的图形不整个回显

    def test_rename_does_not_rebuild(self):
        builds = []
        original = self.session.builder.build
        self.session.builder.build = lambda *args: (builds.append(1), original(*args))
        renamed = run(self.session, 'rename_feature', id=self.solid['id'], name='板')
        self.assertEqual((builds, renamed['ok'], self.session.model_revision), ([], True, self.session.document.revision))
        self.assertEqual(renamed['model']['body']['size_mm'], [40, 30, 10])
        run(self.session, 'edit_feature', id=self.solid['id'], params={'distance': 12})     # 改几何的照样重算
        self.assertEqual(builds, [1])

    def test_get_model_full_brief_and_single(self):
        full = run(self.session, 'get_model')
        self.assertEqual(len(full['features'][0]['params']['shapes']), 2)
        self.assertIn('materials', full)
        self.assertTrue(all('params' not in row for row in run(self.session, 'get_model', brief=True)['features']))
        one = run(self.session, 'get_model', id=self.solid['id'])
        self.assertEqual([row['id'] for row in one['features']], [self.solid['id']])
        self.assertFalse(run(self.session, 'get_model', id='f99')['ok'])

    def test_batch_reply_carries_params_of_its_features(self):
        made = run(self.session, 'batch', steps=[
            {'cmd': 'sketch', 'args': {'plane': 'XY', 'offset': 10, 'shapes': [{'type': 'circle', 'r': 3}]}, 'as': 's'},
            {'cmd': 'extrude', 'args': {'sketch': '$s', 'distance': 4}}])
        rows = {row['id']: row for row in made['model']['features']}
        self.assertTrue(all('params' in rows[i] for i in made['ids']))
        self.assertNotIn('params', rows[self.solid['id']])


class LineServer:
    """假的 GenForm 接口: 每行一个 JSON 请求, 回 {"ok": true, "n": 第几条, "conn": 第几条连接}。"""

    def __init__(self):
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(4)
        self.port, self.connections, self.live = self.socket.getsockname()[1], 0, []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                link, _ = self.socket.accept()
            except OSError:
                return
            self.connections += 1
            self.live.append(link)
            threading.Thread(target=self._serve, args=(link, self.connections), daemon=True).start()

    def _serve(self, link, number):
        count = 0
        try:
            with link.makefile('rwb') as stream:
                for _ in stream:
                    count += 1
                    stream.write(json.dumps({'ok': True, 'n': count, 'conn': number}).encode() + b'\n')
                    stream.flush()
        except (OSError, ValueError):
            pass

    def kick(self):
        """把现有的连接都断掉 (像 GenForm 重开了一样)。"""
        for link in self.live:
            try:
                link.shutdown(socket.SHUT_RDWR)
                link.close()
            except OSError:
                pass
        self.live = []

    def close(self):
        self.kick()
        self.socket.close()


class WindowLink(unittest.TestCase):
    def setUp(self):
        self.server = LineServer()
        self.backend = mcp_server.WindowBackend(self.server.port)

    def tearDown(self):
        self.backend._drop()
        self.server.close()

    def test_calls_share_one_connection_and_reconnect_after_drop(self):
        answers = [self.backend.call('get_model', {}) for _ in range(3)]
        self.assertEqual([answer['n'] for answer in answers], [1, 2, 3])
        self.assertEqual(self.server.connections, 1)
        self.server.kick()
        again = self.backend.call('get_model', {})
        self.assertEqual((again['ok'], again['conn'], again['n']), (True, 2, 1))

    def test_unreachable_says_so(self):
        self.server.close()
        answer = mcp_server.WindowBackend(self.server.port).call('ping', {})
        self.assertFalse(answer['ok'])
        self.assertIn('连不上', answer['error'])


class ScreenshotImage(unittest.TestCase):
    def test_screenshot_result_carries_the_picture(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'shot.png')
            with open(path, 'wb') as handle:
                handle.write(b'\x89PNG fake')
            image = mcp_server._image('screenshot', {'ok': True, 'path': path})
            self.assertEqual(image[0]['mimeType'], 'image/png')
            self.assertEqual(base64.b64decode(image[0]['data']), b'\x89PNG fake')
            self.assertEqual(mcp_server._image('export', {'ok': True, 'path': path}), [])
        self.assertEqual(mcp_server._image('screenshot', {'ok': False, 'error': 'x'}), [])


if __name__ == '__main__':
    unittest.main()
