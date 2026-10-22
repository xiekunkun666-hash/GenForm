"""全局变量: 零件里的变量特征 + "=表达式" 参数; 装配体的全局变量写回零件文件、位置表达式、配合 (同轴 / 距离)。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from genform.kernel.model import rebuild
from genform.kernel.model.variables import resolve
from genform.session import Session
from tests.test_assembly_parts import Files


def block(height, values=None):
    """一个 20×20 的方块, 高 = height (可以是 "=表达式")。"""
    features = []
    if values is not None:
        features.append({'id': 'f0', 'type': 'variables', 'name': '变量', 'suppressed': False, 'params': {'values': values}})
    features += [{'id': 'f1', 'type': 'sketch', 'name': 's', 'suppressed': False,
                  'params': {'plane': 'XY', 'offset': 0.0, 'shapes': [{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 20, 'h': 20}]}},
                 {'id': 'f2', 'type': 'extrude', 'name': 'e', 'suppressed': False,
                  'params': {'sketch': 'f1', 'distance': height, 'op': 'add', 'symmetric': False, 'end': 'blind', 'reverse': False,
                             'distance2': 0.0, 'gap': 0.0, 'target': []}}]
    return features


def height_of(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    return box.CornerMax().Z() - box.CornerMin().Z()


class VariablesTest(unittest.TestCase):
    def test_formula_parameter(self):
        shape, _, status = rebuild._rebuild(block('=H/2 + 1', {'H': 20, 'W': '=H*2'}))
        self.assertEqual(status['f0'], 'ok')
        self.assertAlmostEqual(height_of(shape), 11.0, places=6)

    def test_bad_formula_is_a_feature_error(self):
        _, _, status = rebuild._rebuild(block('=Q+1', {'H': 20}))
        self.assertTrue(status['f2'].startswith('error'), status)
        _, _, status = rebuild._rebuild(block(5, {'H': '=K*2'}))
        self.assertTrue(status['f0'].startswith('error'), status)

    def test_untouched_features_are_the_same_objects(self):
        features = block(5.0)
        resolved, errors = resolve(features)
        self.assertEqual(errors, {})
        self.assertTrue(all(a is b for a, b in zip(features, resolved)))

    def test_form_text_round_trip(self):
        from genform import features as table
        values = table.parse_variables('D = 112; H = D/2')
        self.assertEqual(values, {'D': 112.0, 'H': '=D/2'})
        self.assertEqual(table.variables_text(values), 'D = 112; H = D/2')
        field = {'kind': 'number', 'label': '距离'}
        self.assertEqual(table.clean(field, '=H-3'), '=H-3')


class AssemblyParamsTest(unittest.TestCase):
    def setUp(self):
        self.files = Files(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        patcher = patch.dict(os.environ, {'GENFORM_SETTINGS': os.path.join(folder.name, 'settings.json')})
        patcher.start()
        self.addCleanup(patcher.stop)
        from PySide6.QtGui import QGuiApplication
        self.qt = QGuiApplication.instance() or QGuiApplication([])
        from genform.app import AppController
        self.controller = AppController(Session())
        self.controller._set_kind('assembly')
        self.sim = self.controller.sim
        self.sim.pin()
        self.part = os.path.join(self.folder, 'part.gform')
        with open(self.part, 'w', encoding='utf-8') as handle:
            json.dump({'format': 'genform-document', 'version': 1, 'serial': 2, 'upto': None, 'props': {},
                       'features': block('=H', {'H': 10.0})}, handle)
        self.sim.addPart(self.part)
        self.sim.addPart(self.part)

    def test_param_is_pushed_into_part_files(self):
        self.sim.setParam('H', '24')
        with open(self.part, encoding='utf-8') as handle:
            values = json.load(handle)['features'][0]['params']['values']
        self.assertEqual(values['H'], 24.0)
        self.assertEqual(self.sim.params[0]['value'], '24')

    def test_position_formula_and_mates(self):
        self.sim.setParam('H', '10')
        self.sim.setParam('GAP', '=H/2')
        self.sim.placePart(1, 'move', 0, '30')
        self.sim.placePart(1, 'move', 1, '7')
        self.sim.placePart(1, 'move', 2, '=H + GAP')
        self.assertEqual(self.sim._parts[1]['move'], [30.0, 7.0, 15.0])
        self.sim.setParam('H', '20')
        self.assertEqual(self.sim._parts[1]['move'][2], 30.0)
        self.sim.addMate(1, 0, 'coaxial', 'Z')
        self.assertEqual(self.sim._parts[1]['move'][:2], [0.0, 0.0])
        self.sim.addMate(1, 0, 'offset', 'Z')                   # 先按现在差多少: 不动
        self.assertEqual(self.sim._parts[1]['move'][2], 30.0)
        self.sim.setMateField(1, 'value', '=GAP*3')
        self.assertEqual(self.sim._parts[1]['move'][2], 30.0)   # GAP = 10 → 30
        self.sim.setMateField(1, 'value', '5')
        self.assertEqual(self.sim._parts[1]['move'][2], 5.0)
        self.sim.placePart(1, 'move', 0, '50')                  # 配合定的方向不让改
        self.assertEqual(self.sim._parts[1]['move'][0], 0.0)
        path = os.path.join(self.folder, 'a.gasm')
        self.sim.saveAssembly(path)
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        self.assertEqual(data['params'], {'H': 20.0, 'GAP': '=H/2'})
        self.assertEqual(len(data['mates']), 2)
        self.assertEqual(data['parts'][1]['move'][2], '=H + GAP')
        self.sim._params_init()
        self.sim.openAssembly(path)
        self.assertEqual(self.sim._parts[1]['move'], [0.0, 0.0, 5.0])
        self.assertEqual(len(self.sim.mates), 2)
        self.sim.removePart(0)                                  # 删了被配合的件: 配合跟着没了
        self.assertEqual(self.sim.mates, [])


if __name__ == '__main__':
    unittest.main()
