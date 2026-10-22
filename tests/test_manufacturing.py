# -*- coding: utf-8 -*-
"""加工工艺绑定 (manufacturing.py) 和设计检查 (checks.py, 像 PCB 的 DRC)。"""
import unittest

from genform import manufacturing
from tests.test_features import Part


def bound(part, **args):
    reply = part.run('bind_processes', **args)
    assert reply['ok'], reply
    return {f['name']: (f.get('process') or {}) for f in part.session.document.features}


def named(part, command, label, **args):
    """Part.do 的第一个参数叫 name, 和特征名撞了: 直接交给会话。"""
    replies = []
    part.session.execute(command, dict(args, name=label), replies.append)
    part.case.assertTrue(replies[0]['ok'], replies[0].get('error'))
    return replies[0].get('id')


def plate(part, name='板', w=100, h=60, t=3, offset=0.0):
    sketch = part.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': w, 'h': h}, offset=offset)
    return named(part, 'extrude', name, sketch=sketch, distance=t)


class Binding(unittest.TestCase):
    def test_plate_is_laser_cut_for_one_and_tooled_for_many(self):
        part = Part(self)
        plate(part)
        self.assertEqual(bound(part, batch=1)['板']['id'], 'laser')
        self.assertNotIn(bound(part, batch=200000)['板']['id'], ('laser', 'waterjet'))   # 量大了: 开模 / 冲床更划算

    def test_revolved_part_is_turned(self):
        part = Part(self)
        profile = part.sketch({'type': 'polygon', 'points': [[0, 0], [20, 0], [20, 40], [0, 40]]},
                              {'type': 'line', 'x1': 0, 'y1': -10, 'x2': 0, 'y2': 60, 'construction': True}, plane='XZ')
        named(part, 'revolve', '轴', sketch=profile, axis='CL', angle=360)
        self.assertEqual(bound(part)['轴']['id'], 'turning')

    def test_round_cut_is_drilled_and_mirror_follows_the_seed(self):
        part = Part(self)
        plate(part, t=20)
        hole = named(part, 'extrude', '孔', sketch=part.sketch({'type': 'circle', 'cx': 30, 'cy': 0, 'r': 4}, offset=20),
                     distance=20, reverse=True, op='cut')
        named(part, 'mirror', '孔镜像', features=[hole], plane='YZ')
        result = bound(part)
        self.assertEqual(result['孔']['id'], 'drill')
        self.assertEqual(result['孔镜像']['id'], 'drill')
        self.assertNotIn('process', part.session.document.features[0])         # 草图不绑

    def test_name_hint_makes_fasteners_bought(self):
        part = Part(self)
        plate(part)
        named(part, 'extrude', '螺栓', sketch=part.sketch({'type': 'ngon', 'cx': 0, 'cy': 0, 'r': 6, 'sides': 6, 'angle': 0}, offset=3),
              distance=5)
        result = bound(part)['螺栓']
        self.assertEqual(result['id'], 'standard')        # 螺栓网上按规格买, 不定制
        self.assertTrue(result['standard'])
        self.assertIn('M6', result['spec'])               # 六角对边 10.4 → M6

    def test_hollow_body_skin_is_hand_formed_for_one_car(self):
        part = Part(self)
        plate(part, name='外形', w=600, h=400, t=300)
        inner = part.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 596, 'h': 396}, offset=2)
        named(part, 'extrude', '内形', sketch=inner, distance=296, op='void')
        result = bound(part, batch=1)
        self.assertEqual(result['内形']['id'], 'hand_form')
        self.assertIn('件', result['内形']['why'])

    def test_manual_choice_survives_rebinding(self):
        part = Part(self)
        identifier = plate(part)
        self.assertTrue(part.run('set_process', feature=identifier, process='waterjet')['ok'])
        self.assertEqual(bound(part)['板']['id'], 'waterjet')

    def test_binding_does_not_rebuild(self):
        part = Part(self)
        plate(part)
        revision = part.session.model_revision
        bound(part)
        self.assertEqual(part.session.model_revision, part.session.document.revision)
        self.assertGreater(part.session.model_revision, revision)


class DesignCheck(unittest.TestCase):
    def check(self, part):
        reply = part.run('check_design')
        self.assertTrue(reply['ok'], reply)
        return reply

    def codes(self, reply):
        return [item['code'] for item in reply['issues'] if item['level'] == 'error']

    def test_floating_part_is_an_error_and_red(self):
        part = Part(self)
        plate(part, name='底板')
        lost = plate(part, name='悬空块', w=10, h=10, t=5, offset=50)
        reply = self.check(part)
        self.assertIn('floating', self.codes(reply))
        self.assertIn(lost, reply['red'])

    def test_small_gap_marks_both_parts(self):
        part = Part(self)
        base = plate(part, name='底板')
        top = plate(part, name='盖板', w=20, h=20, t=5, offset=3.2)          # 离底板 0.2 mm (规则 0.5)
        reply = self.check(part)
        self.assertIn('gap', self.codes(reply))
        self.assertTrue({base, top} <= set(reply['red']))

    def test_touching_parts_are_flagged_but_pressed_in_parts_are_fine(self):
        part = Part(self)
        plate(part, name='底板')
        plate(part, name='贴着的块', w=20, h=20, t=5, offset=3.0)
        self.assertIn('touch', self.codes(self.check(part)))
        part = Part(self)
        plate(part, name='底板')
        plate(part, name='压进去的块', w=20, h=20, t=5, offset=2.0)            # 压进去 1 mm
        reply = self.check(part)
        self.assertFalse({'touch', 'shallow', 'gap', 'floating'} & set(self.codes(reply)))

    def test_document_rules_change_the_verdict(self):
        part = Part(self)
        plate(part, name='底板')
        plate(part, name='盖板', w=20, h=20, t=5, offset=3.2)
        self.assertTrue(part.run('set_design_rules', values={'clearance': 0.1, 'tolerance': 0.05})['ok'])
        self.assertNotIn('gap', self.codes(self.check(part)))

    def test_unbound_and_material_warnings_then_cost_summary(self):
        part = Part(self)
        plate(part)
        warnings = [item['code'] for item in self.check(part)['issues']]
        self.assertIn('no_process', warnings)
        self.assertIn('no_material', warnings)
        bound(part)
        infos = [item['code'] for item in self.check(part)['issues']]
        self.assertNotIn('no_process', infos)
        self.assertIn('cost', infos)


class Catalog(unittest.TestCase):
    def test_catalog_has_modern_processes(self):
        names = {item['id'] for item in manufacturing.catalog()}
        for key in ('laser', 'bend', 'stamping', 'hand_form', 'cnc3', 'cnc5', 'turning', 'die_cast', 'injection', 'sls_print', 'slm',
                    'composite', 'vacuum', 'waterjet', 'edm', 'purchase'):
            self.assertIn(key, names)


if __name__ == '__main__':
    unittest.main()


class Proofing(unittest.TestCase):
    """设计规则里打开 proofing: 按铨洲智造 CNC 打样的限制再查一遍 (genform/proofing.py)。"""

    def codes(self, part, material='铝合金 6061'):
        if material:
            named(part, 'set_material', material)
        self.assertTrue(part.run('set_design_rules', values={'proofing': 1})['ok'])
        bound(part)
        reply = part.run('check_design')
        self.assertTrue(reply['ok'], reply)
        return reply['issues']

    def test_plain_plate_passes(self):
        part = Part(self)
        plate(part, w=80, h=50, t=12)
        part.do('extrude', sketch=part.sketch({'type': 'circle', 'cx': 10, 'cy': 5, 'r': 2}, offset=12), distance=-12, op='cut')
        issues = self.codes(part)
        self.assertEqual([item['code'] for item in issues if item['code'].startswith('proof_') and item['level'] != 'info'], [])
        self.assertIn('都过了', next(item['title'] for item in issues if item['code'] == 'proof_summary'))

    def test_material_groove_and_two_sided_boss_are_caught(self):
        part = Part(self)
        plate(part, w=60, h=60, t=10)
        part.do('extrude', sketch=part.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 20, 'h': 20}, offset=10), distance=5)
        part.do('extrude', sketch=part.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 20, 'h': 20}, offset=0), distance=-5)
        groove = part.sketch({'type': 'polygon', 'points': [[22, 3], [25, 3], [25, 6], [22, 6]]}, plane='XZ')
        part.do('revolve', sketch=groove, axis='Z', angle=360, op='cut')
        codes = {item['code'] for item in self.codes(part, material='')}
        self.assertTrue({'proof_material', 'proof_two_sided', 'proof_groove'} <= codes, codes)
