"""Single-send MCP transport and checkpointed write-ahead execution for method B."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(6):
        try:
            os.replace(temporary, path)
            break
        except PermissionError as error:
            if error.winerror not in (5, 32, 33) or attempt == 5:
                raise
            time.sleep(0.05 * 2 ** attempt)


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def same_features(model, expected):
    actual = model.get('features', [])
    return model.get('rollback') == expected.get('upto') and len(actual) == len(expected['features']) and all(
        all(found.get(key) == wanted.get(key) for key in ('id', 'type', 'name', 'params'))
        and (found.get('status') == 'suppressed') == bool(wanted.get('suppressed'))
        for found, wanted in zip(actual, expected['features']))


class Client:
    """No reconnect/replay. Late JSON-RPC responses are routed by request ID."""

    def __init__(self, port, timeout=295):
        self.timeout, self.identifier = timeout, 0
        self.responses = queue.Queue()
        self.process = subprocess.Popen(
            [sys.executable, '-B', str(Path(__file__).resolve()), '--mcp', str(port), str(timeout - 1)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
            text=True, encoding='utf-8', bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        self.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                    'clientInfo': {'name': '911-method-b', 'version': '1'}})

    def _read(self):
        try:
            for line in self.process.stdout:
                self.responses.put(json.loads(line))
        except Exception as error:
            self.responses.put(error)
        finally:
            self.responses.put(RuntimeError('MCP adapter closed'))

    def request(self, method, params):
        import time
        self.identifier += 1
        identifier = self.identifier
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': identifier,
                                             'method': method, 'params': params}) + '\n')
        self.process.stdin.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                response = self.responses.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise TimeoutError(f'Request {identifier} timed out; never resend it') from None
            if isinstance(response, Exception):
                raise response
            if response.get('id') != identifier:
                continue
            if 'error' in response:
                raise RuntimeError(response['error'])
            return response['result']

    def call(self, name, **arguments):
        response = self.request('tools/call', {'name': name, 'arguments': arguments})
        result = json.loads(next(item['text'] for item in response['content'] if item['type'] == 'text'))
        if not result.get('ok'):
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
        return result

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()


class Journal:
    """An uncertain mutation is reconciled, never issued a second time."""

    def __init__(self, folder, client, state):
        self.folder, self.client, self.state = Path(folder), client, state
        self.folder.mkdir(parents=True, exist_ok=True)

    def record(self, event, **values):
        with (self.folder / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'event': event, **values}, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        atomic_json(self.folder / 'progress.json', self.state)
        print(json.dumps({'event': event, **values}, ensure_ascii=False), flush=True)

    def perform(self, key, command, arguments, expected):
        if key in self.state['done']:
            return
        pending = self.state.get('pending')
        if pending is None:
            if self.state.get('checkpoint') and command != 'open_document':
                owned = load_json(self.state['checkpoint'])
                live = self.client.call('get_model', brief=False)
                if digest(owned) != self.state['checkpoint_sha256'] or not same_features(live, owned):
                    raise RuntimeError('Live document diverged from the owned checkpoint')
                if live.get('unsaved_changes') or Path(live.get('path') or '').resolve() != Path(self.state['checkpoint']):
                    raise RuntimeError('Live document changed since the checkpoint')
            checkpoint = arguments['path'] if command in ('save_document', 'open_document') else str(
                self.folder / 'checkpoints' / (key + '.gform'))
            owned_open = command == 'open_document' and self.state.get('checkpoint') and \
                Path(checkpoint).resolve() == Path(self.state['checkpoint']).resolve()
            if Path(checkpoint).exists() and not owned_open:
                raise RuntimeError(f'Unowned checkpoint already exists: {checkpoint}')
            Path(checkpoint).parent.mkdir(parents=True, exist_ok=True)
            save_path = None if command == 'open_document' else checkpoint
            pending = {'key': key, 'command': command, 'arguments': arguments,
                       'expected': expected, 'checkpoint': checkpoint, 'save_path': save_path,
                       'phase': 'command'}
            self.state['pending'] = pending
            self.record('intent', key=key, command=command, arguments_sha256=digest(arguments))
            try:
                call_arguments = dict(arguments)
                if command == 'save_document':
                    call_arguments['path'] = save_path
                self.client.call(command, **call_arguments)
            except Exception as error:
                self.record('uncertain', key=key, error=str(error))
        elif pending['key'] != key:
            raise RuntimeError(f"Reconcile pending action {pending['key']} before {key}")
        self.reconcile()

    def reconcile(self):
        pending = self.state.get('pending')
        if pending is None:
            return
        model = self.client.call('get_model', brief=False)
        self.record('observed', key=pending['key'], features=len(model['features']),
                    body=model.get('body'))
        expected = pending['expected']
        if not same_features(model, expected):
            raise RuntimeError('Pending action absent/partial/diverged; stopped without resending')
        checkpoint = Path(pending['checkpoint'])
        save_path = Path(pending['save_path']) if pending.get('save_path') else None
        if pending['phase'] == 'command' and checkpoint.exists():
            pending['phase'] = 'saving'
            self.record('checkpoint_found', key=pending['key'])
        if pending['phase'] == 'command' and pending['command'] not in ('save_document', 'open_document'):
            pending['phase'] = 'saving'
            self.record('checkpoint_intent', key=pending['key'], path=str(checkpoint))
            try:
                self.client.call('save_document', path=str(save_path))
            except Exception as error:
                self.record('checkpoint_uncertain', key=pending['key'], error=str(error))
                model = self.client.call('get_model', brief=False)
                if not same_features(model, expected):
                    raise RuntimeError('Model changed while saving checkpoint') from error
        saved_path = save_path if save_path is not None and save_path.exists() else checkpoint
        if saved_path is None or not saved_path.exists():
            if save_path is None:
                raise RuntimeError('Checkpoint save is incomplete; inspect before resuming')
            atomic_json(save_path, expected)
            saved_path = save_path
        try:
            saved = load_json(saved_path)
        except (OSError, ValueError):
            if save_path is None:
                raise RuntimeError('Owned checkpoint is corrupt; inspect before resuming') from None
            atomic_json(save_path, expected)
            saved_path, saved = save_path, load_json(save_path)
        if model.get('feature_colors', {}) != saved.get('props', {}).get('feature_colors', {}):
            raise RuntimeError('Live feature colors differ from checkpoint')
        if model.get('material') != saved.get('props', {}).get('material'):
            raise RuntimeError('Live material differs from checkpoint')
        if any(saved.get(field) != expected.get(field) for field in ('features', 'props', 'upto')):
            raise RuntimeError('Checkpoint differs from expected parameters/props; no action was replayed')
        if saved_path.resolve() != checkpoint.resolve():
            os.replace(save_path, checkpoint)
        self.state['done'].append(pending['key'])
        self.state['checkpoint'] = str(checkpoint)
        self.state['checkpoint_sha256'] = digest(saved)
        self.state['pending'] = None
        self.record('commit', key=pending['key'], checkpoint=str(checkpoint),
                    checkpoint_sha256=digest(saved))
        bad = {item['id']: item['status'] for item in model['features']
               if item['status'] not in ('ok', 'suppressed')}
        if bad:
            raise RuntimeError(f'Geometry failed; checkpoint retained: {bad}')


def adapter(port, timeout):
    sys.path.insert(0, str(ROOT))
    from genform.api.mcp_server import respond

    class Backend:
        def tools(self):
            from genform.commands import catalog
            return catalog()

        def call(self, name, arguments):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=min(5, timeout)) as link:
                    link.settimeout(timeout)
                    with link.makefile('rwb') as stream:
                        stream.write((json.dumps({'cmd': name, 'args': arguments}) + '\n').encode())
                        stream.flush()
                        return json.loads(stream.readline().decode('utf-8'))
            except Exception as error:
                return {'ok': False, 'error': f'Single-send transport: {type(error).__name__}: {error}'}

    backend = Backend()
    for line in sys.stdin:
        response = respond(backend, json.loads(line))
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--mcp':
        raise SystemExit('Internal single-send MCP adapter; run alternate.py instead')
    adapter(int(sys.argv[2]), float(sys.argv[3]))
