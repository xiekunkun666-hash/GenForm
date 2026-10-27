import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'build' / 'smoke_interactions'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        environment = dict(os.environ, GENFORM_PORT=str(port), GENFORM_SETTINGS=str(Path(folder) / 'settings.json'),
                           PYTHONIOENCODING='utf-8')
        log = (OUTPUT / 'gui.log').open('w', encoding='utf-8')
        process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'main.py')], cwd=ROOT,
                                   env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        status = {'port': port, 'launcher_pid': process.pid, 'checks': []}
        (OUTPUT / 'running.json').write_text(json.dumps(status), encoding='utf-8')

        def ask(request):
            with socket.create_connection(('127.0.0.1', port), timeout=1) as connection:
                connection.settimeout(8)
                request.setdefault('timeout_s', 7)
                connection.sendall((json.dumps(request) + '\n').encode('utf-8'))
                with connection.makefile('rb') as stream:
                    result = json.loads(stream.readline())
            if not result.get('ok'):
                raise RuntimeError(result)
            return result

        def command(name, **args):
            return ask({'cmd': name, 'args': args})

        def ui(slot, *args):
            return ask({'cmd': 'ui', 'slot': slot, 'args': list(args)}).get('value')

        def wait(predicate, message, seconds=8):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if predicate():
                    return
                time.sleep(0.05)
            raise TimeoutError(message)

        def passed(name):
            status['checks'].append(name)
            print('PASS ' + name, flush=True)

        try:
            def started():
                try:
                    status['pid'] = command('ping')['pid']
                    return True
                except OSError:
                    return False

            wait(started, 'GUI startup', 12)
            print(json.dumps({'pid': status['pid'], 'port': port}), flush=True)
            command('batch', steps=[{'cmd': 'sketch', 'args': {'shapes': [{'type': 'rect', 'w': 20, 'h': 20}]}},
                                    {'cmd': 'extrude', 'args': {'distance': 10}}])
            part = Path(folder) / 'cube.gform'
            command('save_document', path=str(part))
            command('new_document')
            assembly = Path(folder) / 'test.gasm'
            assembly.write_text(json.dumps({'format': 'genform-assembly', 'version': 1, 'parts': [
                {'name': 'base', 'file': 'cube.gform', 'move': [0, 0, 0], 'turn': [0, 0, 0]},
                {'name': 'overlap', 'file': 'cube.gform', 'move': [8, 0, 0], 'turn': [0, 0, 0]}]}), encoding='utf-8')
            ui('openDocument', str(assembly))
            wait(lambda: len(ui('sim._shown')) == 2, 'assembly meshes')
            time.sleep(0.6)
            assert not ui('sim.live')['running']
            assert ui('sim.live')['clashes'] == 0
            assert ui('checkIssues') == []
            passed('no automatic check on opening assembly')
            ui('runCheck')
            wait(lambda: not ui('checkBusy'), 'manual check')
            assert ui('checkCounts')['error'] > 0
            assert ui('viewport.labels')
            passed('explicit design check finds overlap')
            command('screenshot', path=str(OUTPUT / 'checked.png'), view='iso')
            ui('clearCheck')
            assert ui('checkIssues') == []
            assert ui('checkCounts') == {}
            assert not any(row['bad'] or row['clash'] for row in ui('sim.components'))
            assert not any(row['kind'] == 'clash' for row in ui('viewport.labels'))
            ui('sim.placePart', 1, 'move', 0, '9')
            time.sleep(0.45)
            assert not ui('sim.live')['running']
            assert ui('checkIssues') == []
            ui('closeCheck')
            ui('toggleCheckLog')
            assert ui('checkIssues') == []
            ui('closeCheck')
            passed('clear removes scene errors and modelling does not restore them')
            ui('sim.partAction', 1, 'isolate')
            assert ui('sim.isolatedName') == 'overlap'
            assert len(ui('viewport._data')['extras']) == 1
            command('screenshot', path=str(OUTPUT / 'isolated.png'), view='iso')
            ui('sim.exitIsolation')
            assert ui('sim.isolatedName') == ''
            assert len(ui('viewport._data')['extras']) == 2
            passed('assembly isolation exits and restores components')
            ui('setDisplayStyle', 'shaded_edges')
            ui('viewport.fit')
            time.sleep(0.4)
            for kind, x, y in (('press', 0.02, 0.02), ('move', 0.98, 0.98), ('release', 0.98, 0.98)):
                ui('_debug_mouse', kind, x, y)
            assert sum(row['selected'] for row in ui('sim.components')) == 2
            passed('actual mouse box selects two assembly components')
            style = ui('viewport._display')['style']
            ui('_debug_mouse', 'press', 0.5, 0.5, 'middle')
            ui('_debug_mouse', 'move', 0.57, 0.55, 'middle')
            ui('_debug_mouse', 'release', 0.57, 0.55, 'middle')
            assert ui('viewport._display')['style'] == style
            passed('mouse orbit preserves selected display style')
            ui('runCheck')
            wait(lambda: not ui('checkBusy'), 'second manual check')
            assert ui('checkCounts')['error'] > 0
            passed('explicit recheck restores findings after clear')
            ui('clearCheck')
            command('screenshot', path=str(OUTPUT / 'cleared.png'), view='iso')
            status['ok'] = True
        except Exception as error:
            status['ok'], status['error'] = False, repr(error)
            raise
        finally:
            (OUTPUT / 'result.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
            try:
                command('quit')
            except (OSError, RuntimeError):
                pass
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.terminate()
            log.close()


if __name__ == '__main__':
    main()
