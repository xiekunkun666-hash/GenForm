from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'models' / 'porsche_911_992'
DOCUMENT = OUTPUT / 'porsche_911_992.gform'


class Client:
    def __init__(self):
        self.identifier = 0
        self.active = None
        self.responses = queue.Queue()
        self.process = subprocess.Popen(
            [sys.executable, '-B', str(ROOT / 'genform_mcp.py')],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8', bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._errors, daemon=True).start()
        self.request('initialize', {'protocolVersion': '2024-11-05',
                                   'capabilities': {}, 'clientInfo': {'name': '911-builder', 'version': '1'}})

    def _read(self):
        try:
            for line in self.process.stdout:
                self.responses.put(json.loads(line))
        except Exception as error:
            self.responses.put(error)
        finally:
            self.responses.put(RuntimeError('MCP process closed its output'))

    def _errors(self):
        for line in self.process.stderr:
            print(line.rstrip(), file=sys.stderr, flush=True)

    def request(self, method, params, timeout=300):
        self.identifier += 1
        identifier = self.identifier
        self.active = identifier
        message = {'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params}
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                try:
                    response = self.responses.get(timeout=min(remaining, 0.1))
                except queue.Empty:
                    continue
                if isinstance(response, Exception):
                    raise response
                if response.get('id') != identifier:
                    continue
                if 'error' in response:
                    raise RuntimeError(response)
                return response['result']
        except queue.Empty:
            self.cancel()
            raise TimeoutError('MCP response timeout; inspect the document before resuming') from None
        except KeyboardInterrupt:
            self.cancel()
            raise
        finally:
            self.active = None

    def cancel(self):
        if self.active is not None and self.process.poll() is None:
            message = {'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                       'params': {'requestId': self.active, 'reason': 'Builder interrupted'}}
            try:
                self.process.stdin.write(json.dumps(message) + '\n')
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass

    def call(self, name, **arguments):
        response = self.request('tools/call', {'name': name, 'arguments': arguments})
        result = json.loads(next(item['text'] for item in response['content'] if item['type'] == 'text'))
        if not result.get('ok'):
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
        return result

    def stage(self, label, steps, colors=None):
        model = self.call('get_model', brief=True)
        existing = {feature['name'] for feature in model['features']}
        planned = [step['args']['name'] for step in steps if 'name' in step.get('args', {})]
        if existing.intersection(planned):
            raise RuntimeError(f'{label}: some geometry already exists; inspect before running again')
        print(f'START {label}: {len(steps)} MCP steps', flush=True)
        result = self.call('batch', steps=steps)
        before_volume = model.get('body', {}).get('volume_mm3', 0)
        after_volume = result.get('model', {}).get('body', {}).get('volume_mm3', 0)
        if before_volume and after_volume < before_volume * 0.98:
            raise RuntimeError(f'{label}: unexpected volume decrease; inspect before continuing')
        for alias, color in (colors or {}).items():
            features = [identifier for identifier, step in zip(result['ids'], steps) if step.get('as') == alias]
            self.call('set_appearance', features=features, color=color)
        self.call('save_document', path=str(DOCUMENT))
        body = result.get('model', {}).get('body', {})
        print(json.dumps({'stage': label, 'ids': result['ids'], 'body': body}, ensure_ascii=False), flush=True)
        return result

    def close(self):
        self.cancel()
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=2)

    def __enter__(self):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


def feature(command, alias, **arguments):
    return {'cmd': command, 'as': alias, 'args': arguments}


def profile(alias, name, plane, offset, shapes):
    return feature('sketch', alias, name=name, plane=plane, offset=offset, shapes=shapes)


def extrude(alias, name, source, distance):
    return feature('extrude', alias, name=name, sketch='$' + source, distance=distance)
