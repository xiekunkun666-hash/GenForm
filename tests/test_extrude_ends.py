"""拉伸的终止条件 (给定深度、方向 2、完全贯穿、成形到顶点 / 面 / 实体、离面的距离)、反向, 旋转的反向和两侧对称, 以及拉伸面板。"""
import math
import unittest

from genform import forms
from tests.test_features import Part

BOX = 40 * 30 * 10


def circle(part, x=0.0, y=0.0, r=5.0, offset=10.0):
    return part.sketch({'type': 'circle', 'cx': x, 'cy': y, 'r': r}, offset=offset)


class ExtrudeEndTest(unittest.TestCase):
    def setUp(self):
        self.part = Part(self)
        self.part.box(40, 30, 10)               # z 从 0 到 10

    def test_reverse_and_second_direction(self):
        part = self.part
        part.do('extrude', sketch=circle(part), distance=4, reverse=True, op='cut')         # 从顶面往下切 4
        self.assertAlmostEqual(part.volume, BOX - math.pi * 25 * 4, delta=0.5)
        part.do('extrude', sketch=circle(part, x=-12, r=3), distance=6, distance2=2)        # 往上 6, 往下 2 (下面那段在实体里)
        self.assertAlmostEqual(part.volume, BOX - math.pi * 25 * 4 + math.pi * 9 * 6, delta=0.5)
        self.assertEqual(part.size, [40.0, 30.0, 16.0])

    def test_through(self):
        part = self.part
        reply = part.run('extrude', sketch=circle(part), end='through', op='cut')
        self.assertFalse(reply['ok'])           # 顶面的法向朝上: 这个方向上没有实体
        self.assertIn('反向', reply['error'])
        part.do('edit_feature', id=reply['id'], params={'reverse': True})
        self.assertAlmostEqual(part.volume, BOX - math.pi * 25 * 10, delta=0.5)

    def test_up_to_vertex(self):
        part = self.part
        part.do('extrude', sketch=circle(part), end='vertex', target=[{'point': [20, 15, 25]}])
        self.assertEqual(part.size, [40.0, 30.0, 25.0])

    def test_up_to_face_and_offset(self):
        part = self.part
        part.do('extrude', sketch=circle(part, x=-10), distance=20)                # 一根柱子, 顶在 z = 30
        before = part.volume
        top = [{'point': [-10, 0, 30]}]
        part.do('extrude', sketch=circle(part, x=10, r=3), end='surface', target=top)
        self.assertAlmostEqual(part.volume - before, math.pi * 9 * 20, delta=0.5)
        before = part.volume
        part.do('extrude', sketch=circle(part, x=10, y=10, r=2), end='offset', target=top, gap=5)
        self.assertAlmostEqual(part.volume - before, math.pi * 4 * 15, delta=0.5)
        self.assertEqual(part.size, [40.0, 30.0, 30.0])

    def test_up_to_inclined_face(self):
        part = self.part
        edge = next(item for item in part.session.model['edges']
                    if abs(item['mid'][0] - 20) < 1e-6 and abs(item['mid'][2] - 10) < 1e-6)
        part.do('chamfer', edges=[{'point': list(edge['mid'])}], distance=5)
        slope = next(item for item in part.session.model['faces']
                     if item.get('normal') is not None and abs(item['normal'][0]) > 0.5 and abs(item['normal'][2]) > 0.5)
        before = part.volume
        # 从下面 z = -20 往上拉到斜面: 实体外面多出来的只有 z < 0 的那一段
        part.do('extrude', sketch=circle(part, x=17.5, r=1.0, offset=-20), end='surface', target=[{'point': list(slope['center'])}])
        self.assertAlmostEqual(part.volume - before, math.pi * 1 * 20, delta=0.3)
        self.assertEqual(part.size, [40.0, 30.0, 30.0])

    def test_up_to_body(self):
        part = self.part
        part.do('extrude', sketch=circle(part, x=10, r=3, offset=40), end='body', reverse=True)    # 从 z = 40 往下拉到碰上实体
        self.assertAlmostEqual(part.volume, BOX + math.pi * 9 * 30, delta=0.5)
        self.assertEqual(part.size, [40.0, 30.0, 40.0])
        reply = part.run('extrude', sketch=circle(part, x=-10, r=3, offset=40), end='body', reverse=True, op='cut')
        self.assertFalse(reply['ok'])

    def test_old_documents_still_work(self):
        part = Part(self)
        sketch = part.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': 10, 'h': 10})
        part.session.document.add('extrude', {'sketch': sketch, 'distance': -6, 'op': 'add', 'symmetric': False})    # 老写法: 没有 end
        part.session.rebuild() if hasattr(part.session, 'rebuild') else part.do('edit_feature', id=part.session.document.features[-1]['id'], params={})
        self.assertEqual(part.size, [10.0, 10.0, 6.0])


class RevolveTest(unittest.TestCase):
    def test_reverse_and_symmetric(self):
        volumes = []
        for more in ({}, {'reverse': True}, {'symmetric': True}):
            part = Part(self)
            sketch = part.sketch({'type': 'rect', 'cx': 10, 'cy': 0, 'w': 4, 'h': 4})
            part.do('revolve', sketch=sketch, axis='SY', angle=90, **more)
            volumes.append(part.volume)
            if more.get('symmetric'):
                self.assertAlmostEqual(part.size[2], 2 * 12 * math.sin(math.radians(45)), delta=0.01)
        self.assertAlmostEqual(volumes[0], volumes[1], delta=0.01)
        self.assertAlmostEqual(volumes[0], volumes[2], delta=0.01)


class ExtrudeFormTest(unittest.TestCase):
    def setUp(self):
        self.part = Part(self)
        self.part.box(40, 30, 10)
        self.sketch = circle(self.part)
        self.session = self.part.session

    def shown(self, form):
        return [field['key'] for field in form['fields'] if not field.get('hidden')]

    def set(self, form, key, value):
        next(field for field in form['fields'] if field['key'] == key)['value'] = value
        return forms.arrange(form, self.session)

    def test_fields_follow_end_condition(self):
        form = forms.new_form('extrude', self.session)
        self.assertEqual(self.shown(form), ['sketch', 'end', 'distance', 'reverse', 'distance2', 'op'])
        self.assertNotIn('pick', form)
        self.set(form, 'end', 'offset')
        self.assertEqual(self.shown(form), ['sketch', 'end', 'target', 'gap', 'op'])
        self.assertEqual(form['pick']['kind'], 'face')
        with self.assertRaises(ValueError):
            forms.to_command(form, self.session)            # 还没点终止面
        self.set(form, 'end', 'vertex')
        self.assertEqual(form['pick']['kind'], 'vertex')
        self.session.selection['vertices'] = [0]
        name, args = forms.to_command(form, self.session)
        self.assertEqual((name, args['end'], len(args['target'][0]['point'])), ('extrude', 'vertex', 3))
        self.set(form, 'end', 'mid')
        self.assertEqual(self.shown(form), ['sketch', 'end', 'distance', 'op'])
        self.assertEqual(forms.new_form('cut', self.session)['fields'][1]['value'], 'through')     # 切除默认完全贯穿

    def test_edit_keeps_target(self):
        feature = self.part.do('extrude', sketch=self.sketch, end='vertex', target=[{'point': [0, 0, 18]}])
        form = forms.feature_form(self.session.document.find(feature), self.session)
        name, args = forms.to_command(form, self.session)
        self.assertEqual(name, 'edit_feature')
        self.assertNotIn('target', args['params'])           # 没重新点: 原来的顶点留着
        self.assertEqual(args['params']['end'], 'vertex')


class PickIntoFormTest(unittest.TestCase):
    def setUp(self):
        self.part = Part(self)
        self.part.box(40, 30, 10)
        self.profile = self.part.sketch({'type': 'rect', 'cx': 30, 'cy': 0, 'w': 4, 'h': 4}, offset=10)
        self.session = self.part.session

    def value(self, form, key):
        return next(field['value'] for field in form['fields'] if field['key'] == key)

    def test_axis_from_a_picked_line(self):
        form = forms.new_form('revolve', self.session)
        self.assertEqual([kind for _, kind in forms.field_kinds(form)], ['sketch', 'axis'])
        token = '@20,0,10;0,1,0'                # 顶面右边那条直边
        self.assertEqual(forms.take(form, ('axis',), token, forms.PICKED_AXIS), 'axis')
        self.assertEqual(self.value(form, 'axis'), token)
        name, args = forms.to_command(form, self.session)
        before = self.part.volume
        self.part.do(name, **dict(args, angle=90))
        self.assertAlmostEqual(self.part.volume - before, math.pi / 2 * 10 * 16, delta=0.5)     # 4×4 的方块绕离它中心 10 的轴转四分之一圈
        again = forms.feature_form(self.session.document.features[-1], self.session)
        self.assertIn(forms.PICKED_AXIS, [option['label'] for field in again['fields'] if field['key'] == 'axis' for option in field['options']])

    def test_pick_sketch_and_two_axes(self):
        form = forms.new_form('revolve', self.session)
        other = self.part.sketch({'type': 'circle', 'cx': 0, 'cy': 0, 'r': 2}, offset=10)
        form = forms.new_form('revolve', self.session)
        self.assertEqual(forms.take(form, ('sketch', 'path', 'sketches'), self.profile), 'sketch')
        self.assertEqual(self.value(form, 'sketch'), self.profile)
        self.assertIsNone(forms.take(form, ('plane',), 'XY'))                   # 旋转的面板上没有收基准面的项
        loft = forms.new_form('loft', self.session)
        forms.take(loft, ('sketch', 'path', 'sketches'), other)
        forms.take(loft, ('sketch', 'path', 'sketches'), self.profile)
        self.assertEqual(self.value(loft, 'sketches'), [other, self.profile])
        forms.take(loft, ('sketch', 'path', 'sketches'), other)                 # 再点一次: 拿掉
        self.assertEqual(self.value(loft, 'sketches'), [self.profile])
        pattern = forms.new_form('pattern_linear', self.session)
        forms.take(pattern, ('axis',), 'Z')
        forms.take(pattern, ('axis',), '@0,0,0;1,1,0', forms.PICKED_AXIS)       # 第二下轮到方向 2
        self.assertEqual((self.value(pattern, 'axis1'), self.value(pattern, 'axis2')), ('Z', '@0,0,0;1,1,0'))
