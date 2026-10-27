import json
import queue
import unittest
from io import StringIO
from unittest.mock import Mock

from examples.porsche_911.mcp_client import Client


class ClientCancellation(unittest.TestCase):
    def setUp(self):
        self.client = Client.__new__(Client)
        self.client.identifier = 0
        self.client.active = None
        self.client.responses = queue.Queue()
        self.client.process = Mock()
        self.client.process.poll.return_value = None
        self.client.process.stdin = StringIO()

    def messages(self):
        return [json.loads(line) for line in self.client.process.stdin.getvalue().splitlines()]

    def test_timeout_sends_cancel_notification(self):
        with self.assertRaises(TimeoutError):
            self.client.request('tools/call', {'name': 'extrude'}, timeout=0.02)
        self.assertEqual(self.messages()[-1]['method'], 'notifications/cancelled')
        self.assertEqual(self.messages()[-1]['params']['requestId'], 1)
        self.assertIsNone(self.client.active)

    def test_late_cancelled_response_does_not_break_next_request(self):
        self.client.identifier = 1
        self.client.responses.put({'id': 1, 'error': {'code': -32800}})
        self.client.responses.put({'id': 2, 'result': {'ok': True}})
        self.assertEqual(self.client.request('tools/list', {}, timeout=0.2), {'ok': True})

    def test_keyboard_interrupt_sends_cancel_notification(self):
        self.client.responses = Mock()
        self.client.responses.get.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.client.request('tools/call', {'name': 'extrude'})
        self.assertEqual(self.messages()[-1]['method'], 'notifications/cancelled')


if __name__ == '__main__':
    unittest.main()
