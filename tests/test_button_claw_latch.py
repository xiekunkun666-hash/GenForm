import importlib.util
import math
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from examples.button_claw_latch.build import configuration


class Kinematics(unittest.TestCase):
    def test_link_length_is_constant_for_entire_sampled_stroke(self):
        for angle in range(41):
            config = configuration(angle)
            self.assertAlmostEqual(math.hypot(config['crank'][0] - config['slider'],
                                             config['crank'][1] - 10), 24)

    def test_button_travel_is_monotonic_with_known_endpoints(self):
        shifts = [configuration(angle)['shift'] for angle in range(41)]
        self.assertAlmostEqual(shifts[0], 0)
        self.assertAlmostEqual(shifts[-1], -6.31357222952861)
        self.assertTrue(all(first > second for first, second in zip(shifts, shifts[1:])))


class Presentation(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.output = Path(folder.name)
        backend = types.ModuleType('build')
        backend.Client = Mock()
        backend.OUTPUT = self.output
        backend.assembly = Mock()
        backend.configuration = configuration
        backend.ui = Mock()
        source = Path(__file__).resolve().parents[1] / 'examples' / 'button_claw_latch' / 'validate.py'
        spec = importlib.util.spec_from_file_location('claw_validation_test', source)
        self.validation = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'build': backend}):
            spec.loader.exec_module(self.validation)
        self.ui = backend.ui

    def test_stale_export_is_not_reported_as_success(self):
        path = self.output / 'claw_latch_open.step'
        path.write_bytes(b'x' * 2000)
        self.ui.side_effect = lambda slot, arguments=None: {'value': '' if slot == 'sim._running' else {}}
        with patch.object(self.validation.time, 'monotonic', side_effect=[0, 0, 16]), \
                patch.object(self.validation.time, 'sleep'):
            with self.assertRaises(TimeoutError):
                self.validation.export_step('open')

    def test_export_error_is_not_hidden(self):
        self.ui.side_effect = lambda slot, arguments=None: {'value': {'error': 'STEP failed'}}
        with self.assertRaisesRegex(RuntimeError, 'STEP failed'):
            self.validation.export_step('closed')

    def test_native_check_preserves_warnings(self):
        path = self.output / 'claw_latch_open.gasm'
        self.validation.make_assembly.return_value = path
        warning = {'level': 'warning', 'code': 'gap', 'title': 'small clearance', 'detail': '0.2 mm'}
        values = {'checkBusy': False, 'checkCounts': {'error': 0, 'warning': 1},
                  'checkIssues': [warning], 'checkStale': False}
        self.ui.side_effect = lambda slot, arguments=None: {'value': values.get(slot)}
        with patch.object(self.validation, 'wait_for_assembly'):
            report = self.validation.native_check(40, 'open')
        self.assertEqual(report['issues'], [warning])
        self.assertEqual(report['counts']['warning'], 1)


if __name__ == '__main__':
    unittest.main()
