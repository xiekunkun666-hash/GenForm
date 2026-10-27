import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'examples' / 'button_latch' / 'present.py'


class PresentationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name)
        backend = types.ModuleType('build')
        backend.Client = Mock()
        backend.OUTPUT = self.output
        backend.ui = Mock()
        spec = importlib.util.spec_from_file_location('button_latch_presentation_test', SOURCE)
        self.presentation = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'build': backend}):
            spec.loader.exec_module(self.presentation)
        self.ui = backend.ui
        rows = [{'file': 'housing.gform', 'move': [0, 0, 0]},
                {'file': 'button_bolt.gform', 'move': [8, 0, 0]}]
        self.destination = self.output / 'button_latch_pressed.gasm'
        self.destination.write_text(json.dumps({'parts': rows}), encoding='utf-8')
        self.components = [{'path': str(self.output / row['file']), 'move': row['move'], 'turn': [0, 0, 0]}
                           for row in rows]

    def response(self, slot, arguments=None):
        if slot == 'sim.path':
            return {'value': str(self.destination)}
        if slot == 'sim.components':
            return {'value': self.components}
        if slot == 'sim._assembly':
            return {'value': {'error': ''}}
        raise AssertionError(slot)

    def test_waits_until_viewport_matches_requested_placement(self):
        frames = iter([{'extras': [{'pick': 1, 'low': [-40, -6.5, 3.5], 'high': [26, 6.5, 16.5]},
                                   {'pick': 3, 'low': [-17.995, -4.7, 5.3]}]},
                       {'extras': [{'pick': 1, 'low': [-32, -6.5, 3.5], 'high': [34, 6.5, 16.5]},
                                   {'pick': 3, 'low': [-9.995, -4.7, 5.3]}]}])
        self.ui.side_effect = lambda slot, arguments=None: (
            {'value': next(frames)} if slot == 'viewport._data' else self.response(slot, arguments))
        with patch.object(self.presentation.time, 'sleep') as pause:
            observed = self.presentation.wait_for_state('pressed')
        self.assertEqual(observed['bolt_high'][0], 34)
        pause.assert_called_once_with(0.2)

    def test_correct_bolt_with_stale_spring_is_not_ready(self):
        self.ui.side_effect = lambda slot, arguments=None: (
            {'value': {'extras': [{'pick': 1, 'low': [-32, -6.5, 3.5], 'high': [34, 6.5, 16.5]},
                                 {'pick': 3, 'low': [-17.995, -4.7, 5.3]}]}}
            if slot == 'viewport._data' else self.response(slot, arguments))
        with patch.object(self.presentation.time, 'monotonic', side_effect=[0, 0, 21]), \
                patch.object(self.presentation.time, 'sleep'):
            with self.assertRaisesRegex(TimeoutError, 'did not reach'):
                self.presentation.wait_for_state('pressed')

    def test_unchanged_old_export_is_rejected(self):
        destination = self.output / 'model.step'
        destination.write_text('old export', encoding='utf-8')
        previous = destination.stat().st_mtime_ns, destination.stat().st_size
        self.ui.side_effect = lambda slot: {'value': '' if slot == 'sim._running' else {'error': ''}}
        with self.assertRaises(RuntimeError):
            self.presentation.wait_for_export(destination, previous)

    def test_export_failure_is_not_reported_as_success(self):
        self.ui.side_effect = lambda slot: {'value': '' if slot == 'sim._running' else {'error': 'export failed'}}
        with self.assertRaisesRegex(RuntimeError, 'export failed'):
            self.presentation.wait_for_export(self.output / 'missing.step', None)

    def test_new_export_is_accepted(self):
        destination = self.output / 'model.step'
        destination.write_text('new export', encoding='utf-8')
        self.ui.side_effect = lambda slot: {'value': '' if slot == 'sim._running' else {'error': ''}}
        self.presentation.wait_for_export(destination, None)


if __name__ == '__main__':
    unittest.main()
