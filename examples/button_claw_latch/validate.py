from __future__ import annotations

import argparse
import json
import time

from build import Client, OUTPUT, assembly as make_assembly, configuration, ui


def wait_for_assembly(path, angle):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        parts = ui('sim.components')['value']
        meshes = dict(ui('sim._shown')['value'])
        current = ui('sim.path')['value']
        shift = configuration(angle)['shift']
        bolt = meshes.get(2, {})
        spring = meshes.get(8, {})
        low = bolt.get('low')
        spring_low = spring.get('low')
        if (current == str(path) and len(parts) == 20 and len(meshes) == 20
                and parts[1]['turn'] == [0, 0, angle] and low and spring_low
                and abs(low[0] - (-64 + shift)) < 0.02
                and abs(spring_low[0] - (-41.5 + shift)) < 0.02):
            return
        error = ui('sim._assembly')['value'].get('error')
        if error:
            raise RuntimeError(error)
        time.sleep(0.2)
    raise TimeoutError(f'Assembly still loading: {path.name}; no duplicate open sent')


def native_check(angle, name):
    path = make_assembly(angle)
    ui('openDocument', [str(path)])
    wait_for_assembly(path, angle)
    ui('runCheck')
    deadline = time.monotonic() + 20
    while ui('checkBusy')['value']:
        if time.monotonic() >= deadline:
            raise TimeoutError('Native design check still running; inspect before retrying')
        time.sleep(0.2)
    report = {'state': name, 'angle_degrees': angle, 'counts': ui('checkCounts')['value'],
              'issues': ui('checkIssues')['value'], 'stale': ui('checkStale')['value']}
    destination = OUTPUT / f'design_check_{name}.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'state': name, 'counts': report['counts'], 'issues': [
        {'level': issue['level'], 'code': issue['code'], 'title': issue['title'], 'detail': issue['detail']}
        for issue in report['issues'] if issue['level'] != 'info']}, ensure_ascii=True), flush=True)
    if report['stale'] or report['counts'].get('error'):
        raise RuntimeError(f'Native check failed: {destination}')
    return report


def show(client, angle, name):
    native_check(angle, name)
    ui('setDisplayStyle', ['shaded'])
    for part in ui('sim.components')['value']:
        if (part['index'] == 9 or part['index'] >= 12) and not part['hidden']:
            ui('sim.partAction', [part['index'], 'hide'])
    answer = client.call('screenshot', path=str(OUTPUT / f'claw_latch_{name}.png'), view='iso')
    print(json.dumps({'screenshot': answer['path']}), flush=True)


def export_step(name):
    path = OUTPUT / f'claw_latch_{name}.step'
    previous = path.stat().st_mtime_ns if path.exists() else None
    ui('exportModel', [str(path)])
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = ui('sim._assembly')['value']
        if state.get('error'):
            raise RuntimeError(state['error'])
        if not ui('sim._running')['value'] and path.exists() and path.stat().st_size > 1000:
            if path.stat().st_mtime_ns != previous:
                print(json.dumps({'step': str(path), 'bytes': path.stat().st_size}), flush=True)
                return
        time.sleep(0.1)
    raise TimeoutError('STEP export not confirmed; inspect before retrying')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('state', choices=('closed', 'middle', 'open'))
    parser.add_argument('--export', action='store_true')
    args = parser.parse_args()
    client = Client()
    try:
        show(client, {'closed': 0, 'middle': 20, 'open': 40}[args.state], args.state)
        if args.export:
            export_step(args.state)
    finally:
        client.close()


if __name__ == '__main__':
    main()
