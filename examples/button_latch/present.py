from __future__ import annotations

import json
import hashlib
import os
import time
from pathlib import Path

from build import Client, OUTPUT, ui


def wait_for_export(path, previous):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        running = ui('sim._running').get('value')
        if not running:
            state = ui('sim._assembly')['value']
            stamp = (path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else None
            if state.get('error') or stamp is None or stamp[1] == 0 or stamp == previous:
                raise RuntimeError({'state': state, 'path': str(path)})
            return
        time.sleep(0.2)
    raise TimeoutError('Export is still pending; inspect status before retrying')


def wait_for_state(state, timeout=20):
    destination = OUTPUT / f'button_latch_{state}.gasm'
    expected = json.loads(destination.read_text(encoding='utf-8'))['parts']
    shift = expected[1]['move'][0]
    deadline = time.monotonic() + timeout
    observed = None
    while time.monotonic() < deadline:
        current = ui('sim.path')['value']
        components = ui('sim.components')['value']
        data = ui('viewport._data')['value']
        extras = {part.get('pick'): part for part in data.get('extras', [])}
        bolt = extras.get(1, {})
        spring = extras.get(3, {})
        observed = {'path': current, 'part_count': len(components), 'bolt_low': bolt.get('low'),
                    'bolt_high': bolt.get('high'), 'spring_low': spring.get('low')}
        placements_match = len(components) == len(expected) and all(
            os.path.normcase(Path(actual['path']).resolve()) == os.path.normcase((OUTPUT / target['file']).resolve())
            and actual['move'] == target.get('move', [0, 0, 0])
            and actual['turn'] == target.get('turn', [0, 0, 0])
            for actual, target in zip(components, expected))
        low, high = bolt.get('low'), bolt.get('high')
        spring_low = spring.get('low')
        if (current and os.path.normcase(Path(current).resolve()) == os.path.normcase(destination.resolve())
                and placements_match and low and high and spring_low
                and abs(low[0] - (-40 + shift)) < 0.05 and abs(high[0] - (26 + shift)) < 0.05
                and abs(spring_low[0] - (-17.995 + shift)) < 0.05):
            return observed
        error = ui('sim._assembly')['value'].get('error')
        if error:
            raise RuntimeError(error)
        time.sleep(0.2)
    raise TimeoutError(f'Assembly meshes did not reach requested {state} state: {observed}')


def show_state(client, state):
    ui('openDocument', [str(OUTPUT / f'button_latch_{state}.gasm')])
    observed = wait_for_state(state)
    ui('setDisplayStyle', ['shaded'])
    for part in ui('sim.components')['value']:
        if part['index'] >= 4 and not part['hidden']:
            ui('sim.partAction', [part['index'], 'hide'])
    screenshot = client.call('screenshot', path=str(OUTPUT / f'button_latch_{state}.png'), view='iso')
    destination = OUTPUT / f'button_latch_{state}.step'
    previous = (destination.stat().st_mtime_ns, destination.stat().st_size) if destination.exists() else None
    ui('sim.exportAssembly', [str(destination)])
    wait_for_export(destination, previous)
    record = {'state': state, 'screenshot': screenshot['path'], 'step': str(destination),
              'step_bytes': destination.stat().st_size, 'observed': observed,
              'screenshot_sha256': hashlib.sha256(Path(screenshot['path']).read_bytes()).hexdigest()}
    print(json.dumps(record), flush=True)
    return record


def main():
    client = Client()
    try:
        pressed = show_state(client, 'pressed')
        opened = show_state(client, 'open')
        if pressed['screenshot_sha256'] == opened['screenshot_sha256']:
            raise RuntimeError('Open and pressed screenshots are identical; inspect rendering before continuing')
        (OUTPUT / 'presentation.json').write_text(json.dumps({'states': [opened, pressed]}, indent=2), encoding='utf-8')
        print('Displayed default-open configuration with cover hidden', flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
