import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

from genform.api.server import ApiServer
from genform.kernel.client import ProcessBuilder
from genform.operations import CURRENT_OPERATION
from genform.session import Session


_APP = QCoreApplication.instance() or QCoreApplication([])


def pump_until(condition, timeout=1.5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        _APP.processEvents()
        time.sleep(0.002)
    return condition()


class DeferredBuilder:
    def __init__(self):
        self.jobs = []
        self.cancelled = []

    def build(self, features, upto, done):
        self.jobs.append((CURRENT_OPERATION.get(), done))

    def cancel(self, owner, reason):
        self.cancelled.append(owner)
        retained = []
        for job_owner, done in self.jobs:
            if job_owner is owner:
                done(None, reason)
            else:
                retained.append((job_owner, done))
        self.jobs = retained


class ApiCancellation(unittest.TestCase):
    def setUp(self):
        self.builder = DeferredBuilder()
        self.session = Session(self.builder)
        self.server = ApiServer(self.session, port=0)
        self.addCleanup(self.server.close)
        self.answers = []
        self.failures = []
        self.connections = []
        self.threads = []
        self.addCleanup(self.finish_threads)

    def finish_threads(self):
        for connection in self.connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
                connection.close()
            except OSError:
                pass
        for thread in self.threads:
            thread.join(0.2)

    def call(self, request, read=True):
        connection = socket.create_connection(('127.0.0.1', self.server.port), timeout=1)
        connection.settimeout(2)
        self.connections.append(connection)

        def exchange():
            try:
                connection.sendall((json.dumps(request) + '\n').encode())
                if read:
                    with connection.makefile('rb') as stream:
                        self.answers.append(json.loads(stream.readline()))
            except Exception as error:
                self.failures.append(error)

        thread = threading.Thread(target=exchange, daemon=True)
        self.threads.append(thread)
        thread.start()
        return connection

    def start_build(self, **extra):
        return self.call({'cmd': 'sketch', 'request_id': 'build', 'timeout_s': 1,
                          'args': {'shapes': [{'type': 'rect', 'w': 10, 'h': 10}]}, **extra})

    def test_control_connection_cancels_active_job_and_keeps_document(self):
        self.start_build()
        self.assertTrue(pump_until(lambda: bool(self.builder.jobs)))
        self.call({'cmd': 'cancel_request', 'request_id': 'build'})
        self.assertTrue(pump_until(lambda: len(self.answers) == 2 and bool(self.builder.cancelled)))
        failure = next(answer for answer in self.answers if not answer['ok'])
        self.assertEqual(failure['code'], 'cancelled')
        self.assertFalse(self.session.busy)
        self.assertEqual(len(self.session.document.features), 1)
        self.call({'cmd': 'get_model', 'args': {'brief': True}})
        self.assertTrue(pump_until(lambda: len(self.answers) == 3))
        self.assertTrue(self.answers[-1]['model_stale'])
        self.assertEqual(self.failures, [])

    def test_disconnect_cancels_active_job(self):
        connection = self.start_build()
        self.assertTrue(pump_until(lambda: bool(self.builder.jobs)))
        connection.shutdown(socket.SHUT_RDWR)
        self.assertTrue(pump_until(lambda: bool(self.builder.cancelled)))
        self.assertFalse(self.session.busy)

    def test_timeout_cancels_job_instead_of_leaving_it_running(self):
        self.start_build(timeout_s=0.08)
        self.assertTrue(pump_until(lambda: bool(self.answers) and bool(self.builder.cancelled)))
        self.assertEqual(self.answers[0]['code'], 'timeout')
        self.assertFalse(self.session.busy)
        self.assertEqual(len(self.session.document.features), 1)

    def test_cancel_before_ui_dispatch_does_not_modify_document(self):
        self.start_build()
        deadline = time.monotonic() + 1
        while 'build' not in self.server._pending and time.monotonic() < deadline:
            time.sleep(0.005)
        self.call({'cmd': 'cancel_request', 'request_id': 'build'})
        deadline = time.monotonic() + 1
        while len(self.answers) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        _APP.processEvents()
        self.assertEqual(len(self.answers), 2)
        self.assertEqual(self.session.document.features, [])
        self.assertEqual(self.builder.jobs, [])

    def test_handler_exception_returns_error_not_a_five_minute_wait(self):
        with patch.object(self.session, 'execute', side_effect=RuntimeError('test failure')):
            self.call({'cmd': 'get_model'})
            self.assertTrue(pump_until(lambda: bool(self.answers)))
        self.assertFalse(self.answers[0]['ok'])
        self.assertIn('test failure', self.answers[0]['error'])

    def start_mcp(self):
        root = Path(__file__).resolve().parents[1]
        process = subprocess.Popen([sys.executable, '-B', str(root / 'genform_mcp.py')], cwd=root,
                                   env=dict(os.environ, GENFORM_PORT=str(self.server.port)),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8')
        answers = queue.Queue()

        def reader():
            for line in process.stdout:
                answers.put(json.loads(line))

        threading.Thread(target=reader, daemon=True).start()

        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

        self.addCleanup(cleanup)
        return process, answers

    @staticmethod
    def send(process, message):
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()

    def test_real_stdio_cancel_reaches_gui_and_next_request_succeeds(self):
        process, answers = self.start_mcp()
        self.send(process, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                            'params': {'name': 'sketch', 'arguments': {
                                'shapes': [{'type': 'rect', 'w': 10, 'h': 10}]}}})
        self.assertTrue(pump_until(lambda: bool(self.builder.jobs), timeout=3))
        started = time.monotonic()
        self.send(process, {'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                            'params': {'requestId': 1}})
        self.assertTrue(pump_until(lambda: bool(self.builder.cancelled) and not answers.empty()))
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(answers.get_nowait()['error']['code'], -32800)
        self.assertFalse(self.session.busy)
        self.send(process, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                            'params': {'name': 'get_model', 'arguments': {'brief': True}}})
        self.assertTrue(pump_until(lambda: not answers.empty()))
        reply = answers.get_nowait()
        self.assertEqual(reply['id'], 2)
        model = json.loads(reply['result']['content'][0]['text'])
        self.assertEqual(len(model['features']), 1)
        self.assertFalse(model['busy'])
        self.assertTrue(model['model_stale'])

    def test_real_stdio_eof_exits_without_closing_gui(self):
        process, answers = self.start_mcp()
        self.send(process, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                            'params': {'name': 'sketch', 'arguments': {
                                'shapes': [{'type': 'rect', 'w': 10, 'h': 10}]}}})
        self.assertTrue(pump_until(lambda: bool(self.builder.jobs), timeout=3))
        process.stdin.close()
        self.assertTrue(pump_until(lambda: process.poll() is not None and bool(self.builder.cancelled)))
        self.assertFalse(self.session.busy)
        self.call({'cmd': 'ping'})
        self.assertTrue(pump_until(lambda: bool(self.answers)))
        self.assertTrue(self.answers[-1]['ok'])

    def test_stdio_cancel_terminates_owned_kernel_process_and_retains_features(self):
        builder = ProcessBuilder()
        self.addCleanup(builder.close)
        self.session.builder = builder
        process, answers = self.start_mcp()
        flight = []

        def cancel_when_build_starts():
            if self.session.busy and not flight:
                flight.append(builder._process)
                self.send(process, {'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                                    'params': {'requestId': 1}})

        self.session.listen(cancel_when_build_starts)
        self.send(process, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                            'params': {'name': 'sketch', 'arguments': {
                                'shapes': [{'type': 'rect', 'w': 10, 'h': 10}]}}})
        self.assertTrue(pump_until(lambda: bool(flight) and not self.session.busy and not answers.empty(), 3))
        self.assertEqual(answers.get_nowait()['error']['code'], -32800)
        flight[0].join(1)
        self.assertFalse(flight[0].is_alive())
        self.assertEqual(len(self.session.document.features), 1)
        self.send(process, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                            'params': {'name': 'get_model', 'arguments': {'brief': True}}})
        self.assertTrue(pump_until(lambda: not answers.empty()))
        self.assertFalse(answers.get_nowait()['result']['isError'])


if __name__ == '__main__':
    unittest.main()
