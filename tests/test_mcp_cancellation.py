import socket
import threading
import time
import unittest
from unittest.mock import Mock, patch

from genform.api import mcp_server
from genform.api.mcp_runtime import StdioRuntime


class HangingBackend:
    def __init__(self):
        self.started = threading.Event()
        self.released = threading.Event()
        self.cancelled = threading.Event()
        self.calls = []

    def call(self, name, arguments):
        self.calls.append(name)
        self.started.set()
        self.released.wait(3)
        return {'ok': True}

    def cancel(self, operation):
        self.cancelled.set()
        self.released.set()


def request(identifier, name='get_model'):
    return {'jsonrpc': '2.0', 'id': identifier, 'method': 'tools/call',
            'params': {'name': name, 'arguments': {}}}


class StdioCancellation(unittest.TestCase):
    def setUp(self):
        self.backend = HangingBackend()
        self.answers = []
        self.ready = threading.Event()
        self.runtime = StdioRuntime(self.backend, mcp_server.respond, self.output)
        self.addCleanup(self.runtime.close)
        self.addCleanup(self.backend.released.set)

    def output(self, response):
        self.answers.append(response)
        self.ready.set()

    def test_cancel_is_read_while_tool_is_blocked_and_late_result_is_ignored(self):
        self.runtime.submit(request(1))
        self.assertTrue(self.backend.started.wait(1))
        self.runtime.submit({'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                             'params': {'requestId': 1}})
        self.assertTrue(self.ready.wait(1))
        self.assertEqual(self.answers[0]['error']['code'], -32800)
        self.assertTrue(self.backend.cancelled.wait(1))
        self.backend.released.wait(0.2)
        self.assertEqual(len(self.answers), 1)
        self.runtime.submit(request(2))
        deadline = time.monotonic() + 1
        while len(self.answers) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(self.answers[1]['id'], 2)
        self.assertIn('result', self.answers[1])

    def test_deadline_cancels_instead_of_only_abandoning_wait(self):
        self.runtime.timeout = 0.05
        self.runtime.submit(request(3))
        self.assertTrue(self.ready.wait(1))
        self.assertEqual(self.answers[0]['error']['data']['code'], 'timeout')
        self.assertTrue(self.backend.cancelled.wait(1))

    def test_cancelled_queued_command_never_runs(self):
        self.runtime.submit(request(1))
        self.assertTrue(self.backend.started.wait(1))
        self.runtime.submit(request(2, 'extrude'))
        self.runtime.cancel(2)
        self.backend.released.set()
        deadline = time.monotonic() + 1
        while len(self.answers) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(self.backend.calls, ['get_model'])

    def test_eof_cancels_running_request_without_waiting_for_tool(self):
        self.runtime.submit(request(1))
        self.assertTrue(self.backend.started.wait(1))
        started = time.monotonic()
        self.runtime.close()
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(self.backend.cancelled.wait(1))
        self.assertEqual(self.answers, [])


class NoReplay(unittest.TestCase):
    def test_timed_out_query_is_not_retried_on_reused_connection(self):
        backend = mcp_server.WindowBackend(1)
        backend._link = Mock()
        with patch.object(backend, '_send', side_effect=TimeoutError('timeout')) as send:
            answer = backend.call('get_model', {})
        self.assertEqual(send.call_count, 1)
        self.assertEqual(answer['code'], 'timeout')

    def test_disconnected_mutation_is_not_retried(self):
        backend = mcp_server.WindowBackend(1)
        backend._link = Mock()
        with patch.object(backend, '_send', side_effect=ConnectionError('lost')) as send:
            answer = backend.call('extrude', {'distance': 5})
        self.assertEqual(send.call_count, 1)
        self.assertFalse(answer['ok'])
        self.assertIn('不要直接重发', answer['error'])

    def test_cancel_shutdown_unblocks_socket_read(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(2)
        self.addCleanup(listener.close)
        accepted = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def serve():
            connection, _ = listener.accept()
            with connection:
                connection.recv(4096)
                accepted.set()
                release.wait(3)

        threading.Thread(target=serve, daemon=True).start()
        backend = mcp_server.WindowBackend(listener.getsockname()[1])
        self.addCleanup(backend._drop)
        answers = []
        runtime = StdioRuntime(backend, mcp_server.respond, answers.append)
        self.addCleanup(runtime.close)
        runtime.submit(request(1, 'extrude'))
        self.assertTrue(accepted.wait(1))
        runtime.cancel(1)
        deadline = time.monotonic() + 1
        while backend._owner is not None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertIsNone(backend._owner)
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0]['error']['code'], -32800)


if __name__ == '__main__':
    unittest.main()
