"""特征表里的特征: 每种都走一遍命令 → 内核, 核对算出来的实体 (不开窗口)。"""
import math
import unittest

from genform import commands, features, forms
from genform.session import Session


class Part:
    """一个会话 + 简短的调用写法; 每条命令都要求成功, 返回新特征的 id。"""

    def __init__(self, case):
        self.session, self.case = Session(), case

    def run(self, name, **args):
        replies = []
        self.session.execute(name, args, replies.append)
        return replies[0]

    def do(self, name, **args):
        reply = self.run(name, **args)
        self.case.assertTrue(reply['ok'], (name, reply.get('error')))
        return reply.get('id')

    def sketch(self, *shapes, plane='XY', offset=0.0):
        return self.do('sketch', shapes=list(shapes), plane=plane, offset=offset)

    def box(self, w=40.0, h=30.0, d=10.0):
        sketch = self.sketch({'type': 'rect', 'cx': 0, 'cy': 0, 'w': w, 'h': h})
        return self.do('extrude', sketch=sketch, distance=d)

    @property
    def volume(self):
        return self.session.model['props']['volume']

    @property
    def size(self):
        return [round(value, 3) for value in self.session.model['props']['size']]

    @property
    def faces(self):
        return self.session.model['faces']

    def face(self, **near):
        """按法向或类型找一个面 → 引用。"""
        for face in self.faces:
            if 'normal' in near and face.get('normal') is not None and \
                    all(abs(a - b) < 1e-6 for a, b in zip(face['normal'], near['normal'])):
                return {'point': list(face['center'])}
            if 'type' in near and face['type'] == near['type']:
                return {'point': list(face['center'])}
        raise AssertionError(f'没有这样的面 {near}')

    def edge(self, kind, where=None):
        edges = [edge for edge in self.session.model['edges'] if edge['type'] == kind]
        if where:
            edges.sort(key=lambda edge: -sum(a * b for a, b in zip(edge['mid'], where)))
        return {'point': list(edges[0]['mid'])}


def rect(w, h, cx=0.0, cy=0.0):
    return {'type': 'rect', 'cx': cx, 'cy': cy, 'w': w, 'h': h}


def circle(r, cx=0.0, cy=0.0):
    return {'type': 'circle', 'cx': cx, 'cy': cy, 'r': r}


def line(x1, y1, x2, y2):
    return {'type': 'line', 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2}


def point(x, y):
    return {'type': 'point', 'x': x, 'y': y}


class BossAndCutTests(unittest.TestCase):
    def test_revolve_full_and_partial_and_cut(self):
        part = Part(self)
        profile = part.sketch(rect(10, 20, cx=15, cy=10), plane='XZ')
        part.do('revolve', sketch=profile, axis='SY', angle=360)
        self.assertAlmostEqual(part.volume, math.pi * (20 ** 2 - 10 ** 2) * 20, delta=1e-3)
        part.do('edit_feature', id='f2', params={'angle': 90})
        self.assertAlmostEqual(part.volume, math.pi * 300 * 20 / 4, delta=1e-3)
        part.do('edit_feature', id='f2', params={'angle': 360})
        groove = part.sketch(rect(4, 4, cx=20, cy=10), plane='XZ')
        part.do('revolve', sketch=groove, axis='Z', op='cut')            # 外圆上车一道槽; Z 轴 = 这个草图的 Y 轴
        self.assertAlmostEqual(part.volume, math.pi * 300 * 20 - math.pi * (20 ** 2 - 18 ** 2) * 4, delta=1e-3)
        reply = part.run('revolve', sketch=part.sketch(rect(10, 10), plane='XZ'), axis='SY')
        self.assertFalse(reply['ok'])                                   # 轮廓跨过了旋转轴

    def test_sweep_along_sketch_path_and_cut(self):
        part = Part(self)
        path = part.sketch(line(0, 0, 0, 30), {'type': 'arc', 'cx': 10, 'cy': 30, 'r': 10, 'a0': 90, 'a1': 180},
                           line(10, 40, 40, 40), plane='XZ')
        profile = part.sketch(circle(3))
        part.do('sweep', sketch=profile, path=path)
        length = 30 + math.pi * 10 / 2 + 30
        self.assertAlmostEqual(part.volume, math.pi * 9 * length, delta=0.05)
        bore = part.sketch(circle(1.5))
        part.do('sweep', sketch=bore, path=path, op='cut')              # 扫描切除: 掏成管子
        self.assertAlmostEqual(part.volume, math.pi * (9 - 2.25) * length, delta=0.05)

    def test_loft_boundary_and_loft_cut(self):
        part = Part(self)
        bottom, top = part.sketch(rect(40, 40)), part.sketch(rect(20, 20), offset=30)
        part.do('loft', sketches=[bottom, top])
        self.assertAlmostEqual(part.volume, 30 / 3 * (1600 + 400 + 800), delta=1e-3)     # 棱台
        self.assertEqual(part.size, [40, 40, 30])
        part.do('loft', sketches=[part.sketch(circle(5)), part.sketch(circle(2), offset=30)], op='cut')
        self.assertAlmostEqual(part.volume, 28000 - math.pi * 30 / 3 * (25 + 4 + 10), delta=0.5)
        other = Part(self)
        other.do('boundary', sketches=[other.sketch(circle(10)), other.sketch(circle(6), offset=10), other.sketch(circle(10), offset=20)])
        self.assertEqual(other.size[2], 20)
        self.assertLess(other.volume, math.pi * 100 * 20)
        self.assertFalse(other.run('loft', sketches=['f1'])['ok'])

    def test_extrude_common_keeps_the_overlap(self):
        part = Part(self)
        part.box(40, 30, 10)
        part.do('extrude', sketch=part.sketch(circle(10)), distance=50, op='common')
        self.assertAlmostEqual(part.volume, math.pi * 100 * 10, delta=1e-3)


class HoleTests(unittest.TestCase):
    def setUp(self):
        self.part = Part(self)
        self.part.box(60, 40, 10)
        self.spots = self.part.sketch(point(-20, 0), point(20, 0), offset=10)

    def test_simple_through_and_blind(self):
        self.part.do('hole', sketch=self.spots, diameter=6)
        self.assertAlmostEqual(self.part.volume, 24000 - 2 * math.pi * 9 * 10, delta=1e-3)
        self.part.do('edit_feature', id='f4', params={'through': False, 'depth': 4})
        self.assertAlmostEqual(self.part.volume, 24000 - 2 * math.pi * 9 * 4, delta=1e-3)

    def test_counterbore_by_size_and_countersink(self):
        self.part.do('hole', sketch=self.spots, kind='counterbore', size='M5')
        through, head, head_depth, _ = features.HOLE_SIZES['M5']
        one = math.pi * (head / 2) ** 2 * head_depth + math.pi * (through / 2) ** 2 * (10 - head_depth)
        self.assertAlmostEqual(self.part.volume, 24000 - 2 * one, delta=1e-3)
        self.part.do('edit_feature', id='f4', params={'kind': 'countersink', 'size': 'custom', 'diameter': 4, 'head_diameter': 8})
        cone = math.pi * 2 / 3 * (16 + 4 + 8)
        self.assertAlmostEqual(self.part.volume, 24000 - 2 * (cone + math.pi * 4 * 8), delta=1e-3)

    def test_advanced_hole_and_stud(self):
        self.part.do('hole_adv', sketch=self.spots, steps=[[10, 2], [6, 3], [3, 0]])
        one = math.pi * (25 * 2 + 9 * 3 + 2.25 * 5)
        self.assertAlmostEqual(self.part.volume, 24000 - 2 * one, delta=1e-3)
        self.part.do('stud', sketch=self.part.sketch(point(0, 10), offset=10), diameter=6, length=15, chamfer=1)
        self.assertEqual(self.part.size, [60, 40, 25])

    def test_thread_on_a_stud_and_in_a_hole(self):
        self.part.do('stud', sketch=self.part.sketch(point(0, 0), offset=10), diameter=8, length=12, chamfer=0)
        before = self.part.volume
        self.part.do('thread', edges=[self.part.edge('circle', where=(0, 0, 1))], pitch=1.25, length=8)
        self.assertLess(self.part.volume, before - 5)                   # 切掉了牙槽
        self.assertGreater(self.part.volume, before - math.pi * 8 * 0.8 * 8)
        self.part.do('hole', sketch=self.spots, diameter=6)
        before = self.part.volume
        rim = min((edge for edge in self.part.session.model['edges'] if edge['type'] == 'circle' and abs(edge['radius'] - 3) < 1e-6),
                  key=lambda edge: -edge['mid'][2])
        self.part.do('thread', edges=[{'point': list(rim['mid'])}], pitch=1.0, length=6)
        self.assertLess(self.part.volume, before - 2)                   # 内螺纹: 往孔壁里切


class ModifyTests(unittest.TestCase):
    def test_shell_open_and_closed(self):
        part = Part(self)
        part.box(40, 30, 20)
        part.do('shell', faces=[part.face(normal=(0, 0, 1))], thickness=2)
        self.assertAlmostEqual(part.volume, 24000 - 36 * 26 * 18, delta=1e-3)
        part.do('edit_feature', id='f3', params={'faces': []})
        self.assertAlmostEqual(part.volume, 24000 - 36 * 26 * 16, delta=1e-3)
        self.assertFalse(part.run('edit_feature', id='f3', params={'thickness': 40})['ok'])

    def test_draft_tilts_the_side_faces(self):
        part = Part(self)
        part.box(40, 30, 20)
        part.do('draft', faces=[part.face(normal=(1, 0, 0)), part.face(normal=(-1, 0, 0))], plane='XY', angle=5)
        lean = 20 * math.tan(math.radians(5))                           # 顶上每边收进去这么多 (中性面在底面)
        self.assertAlmostEqual(part.volume, 20 * 30 * (40 + 40 - 2 * lean) / 2, delta=1e-3)
        self.assertEqual(part.size, [40, 30, 20])
        part.do('edit_feature', id='f3', params={'flip': True})         # 反向: 顶上往外张
        self.assertAlmostEqual(part.size[0], 40 + 2 * lean, delta=1e-3)

    def test_rib_fills_the_corner_of_an_L(self):
        part = Part(self)
        part.do('extrude', sketch=part.sketch({'type': 'polygon', 'points': [[0, 0], [40, 0], [40, 5], [5, 5], [5, 30], [0, 30]]}, plane='XZ'),
                distance=20, symmetric=True)
        before = part.volume
        part.do('rib', sketch=part.sketch(line(5, 25, 30, 5), plane='XZ'), thickness=4)
        self.assertAlmostEqual(part.volume, before + 25 * 20 / 2 * 4, delta=1e-3)
        self.assertEqual(part.size, [40, 20, 30])

    def test_split_line_divides_a_face(self):
        part = Part(self)
        part.box(40, 30, 10)
        count = len(part.faces)
        part.do('split', sketch=part.sketch(line(0, -30, 0, 30), offset=20))
        self.assertEqual(len(part.faces), count + 4)                    # 竖着切过去: 上下前后四个面各分成两块
        self.assertAlmostEqual(part.volume, 12000, delta=1e-6)

    def test_wrap_emboss_and_deboss_on_a_cylinder(self):
        part = Part(self)
        part.do('extrude', sketch=part.sketch(circle(20)), distance=40)
        base = part.volume
        label = part.sketch(rect(10, 8, cy=20), plane='XZ', offset=20)        # 贴在圆柱前面的切平面上
        part.do('wrap', sketch=label, faces=[part.face(type='cylinder')], depth=1)
        swept = 10 / 20                                                 # 展开长 10 → 圆心角
        self.assertAlmostEqual(part.volume - base, swept / 2 * (21 ** 2 - 20 ** 2) * 8, delta=0.05)
        part.do('edit_feature', id='f4', params={'mode': 'deboss'})
        self.assertAlmostEqual(base - part.volume, swept / 2 * (20 ** 2 - 19 ** 2) * 8, delta=0.05)


class PatternTests(unittest.TestCase):
    def setUp(self):
        self.part = Part(self)
        self.part.box(100, 60, 10)                                      # f1 f2
        self.hole = self.part.do('extrude', sketch=self.part.sketch(circle(3, cx=-40, cy=-20)), distance=10, op='cut')   # f3 f4
        self.one = math.pi * 9 * 10

    def holes(self):
        return round((60000 - self.part.volume) / self.one, 3)

    def test_linear_in_two_directions(self):
        self.part.do('pattern_linear', features=[self.hole], axis1='X', count1=4, spacing1=20, axis2='Y', count2=2, spacing2=40)
        self.assertEqual(self.holes(), 8)

    def test_circular_and_mirror(self):
        self.part.do('pattern_circular', features=[self.hole], axis='Z', count=2, angle=360)
        self.assertEqual(self.holes(), 2)
        self.part.do('mirror', features=[self.hole], plane='YZ')
        self.assertEqual(self.holes(), 3)
        self.part.do('mirror', plane='XY')                              # 不写对象: 整个实体镜像后合在一起
        self.assertEqual(self.part.size, [100, 60, 20])

    def test_pattern_of_a_pattern(self):
        ring = self.part.do('mirror', features=[self.hole], plane='XZ')                  # 孔 (-40, -20) 照到 (-40, 20)
        row = self.part.do('pattern_linear', features=[self.hole, ring], axis1='X', count1=2, spacing1=20, count2=1)
        self.assertEqual(self.holes(), 4)                               # 镜像出来的也跟着阵列: x = -40, -20 各两个
        self.part.do('mirror', features=[self.hole, ring, row], plane='YZ')       # 阵列出来的也跟着照过去
        self.assertEqual(self.holes(), 8)
        self.assertFalse(self.part.run('pattern_variable', features=[ring], rows='0,0,0')['ok'])

    def test_whole_body_pattern_and_boss_pattern(self):
        boss = self.part.do('extrude', sketch=self.part.sketch(circle(4, cx=40, cy=0), offset=10), distance=5)
        self.part.do('pattern_linear', features=[boss], axis1='X', count1=3, spacing1=-15, count2=1)
        self.assertAlmostEqual(self.part.volume, 60000 - self.one + 3 * math.pi * 16 * 5, delta=1e-3)
        self.assertFalse(self.part.run('pattern_linear', features=['f1'])['ok'])       # 草图不是造型特征

    def test_curve_sketch_table_driven(self):
        path = self.part.sketch(line(-40, -20, 40, -20), {'type': 'arc', 'cx': 40, 'cy': 0, 'r': 20, 'a0': -90, 'a1': 0})
        self.part.do('pattern_curve', features=[self.hole], path=path, count=5, spacing=20)
        self.assertEqual(self.holes(), 5)
        self.part.do('pattern_sketch', features=[self.hole], sketch=self.part.sketch(point(-40, 20), point(0, 20)))
        self.assertEqual(self.holes(), 7)
        self.part.do('pattern_table', features=[self.hole], points=[[20, 20], [40, 20]])
        self.assertEqual(self.holes(), 9)

    def test_fill_with_holes_and_with_a_seed(self):
        area = self.part.sketch(rect(40, 30, cx=20, cy=5))
        self.part.do('pattern_fill', sketch=area, spacing=10, margin=3, diameter=4)
        self.assertAlmostEqual(self.part.volume, 60000 - self.one - 9 * math.pi * 4 * 10, delta=1e-3)    # 3 × 3 个
        self.part.do('edit_feature', id='f6', params={'features': [self.hole], 'layout': 'hex'})
        self.assertGreater(self.holes(), 8)

    def test_variable_pattern_changes_a_dimension_per_instance(self):
        boss = self.part.do('extrude', sketch=self.part.sketch(circle(4, cx=-40, cy=20), offset=10), distance=5)
        self.part.do('pattern_variable', features=[boss], rows='20,0,0,distance=10; 40,0,0,distance=15')
        self.assertEqual(self.part.size[2], 25)
        self.assertAlmostEqual(self.part.volume, 60000 - self.one + math.pi * 16 * (5 + 10 + 15), delta=1e-3)
        self.assertIn('没有参数', self.part.run('pattern_variable', features=[boss], rows='1,0,0,radius=3')['error'])


class ReferenceAndCurveTests(unittest.TestCase):
    def test_plane_axis_point_csys_com_bbox(self):
        part = Part(self)
        part.box(40, 30, 10)
        tilted = part.do('plane', base='XY', offset=10, angle=90, about='x')        # 转 90 度: 变成和前视面平行
        frame = features.plane_frame(tilted, part.session.document.features)
        self.assertEqual([round(v, 9) for v in frame['y']], [0.0, 0.0, 1.0])
        boss = part.do('extrude', sketch=part.sketch(circle(5, cy=15), plane=tilted), distance=8)   # 在新基准面上画草图
        self.assertEqual(part.session.model['status'][boss], 'ok')
        self.assertGreater(part.size[1], 30)
        axis = part.do('axis', origin=[[30, 0, 0]], direction=[[0, 0, 1]])
        part.do('pattern_circular', features=[boss], axis=axis, count=2)
        for name in ('point', 'csys', 'com', 'bbox'):
            identifier = part.do(name)
            self.assertGreater(len(part.session.model['sketches'][identifier]), 2, name)
        info = part.session.model['info']
        self.assertTrue(any(text.startswith('边界框') for text in info.values()))
        self.assertTrue(any(text.startswith('质心') for text in info.values()))
        self.assertFalse(part.run('sketch', shapes=[circle(1)], plane='f999')['ok'])

    def test_helix_sweeps_into_a_spring(self):
        part = Part(self)
        helix = part.do('curve_helix', sketch=part.sketch(circle(10)), pitch=5, turns=4)
        self.assertEqual(part.session.model['status'][helix], 'ok')
        wire = part.sketch(circle(1, cx=10), plane='XZ')
        part.do('sweep', sketch=wire, path=helix)
        length = 4 * math.hypot(2 * math.pi * 10, 5)
        self.assertAlmostEqual(part.volume, math.pi * length, delta=length * 0.02)
        self.assertAlmostEqual(part.size[2], 22, delta=0.1)
        spiral = part.do('curve_helix', sketch='f1', kind='spiral', pitch=5, turns=2)
        points = part.session.model['sketches'][spiral].reshape(-1, 3)
        self.assertAlmostEqual(float(abs(points[:, 2]).max()), 0, places=6)
        self.assertAlmostEqual(float(points[:, 0].max()), 20, delta=0.01)

    def test_xyz_reference_point_projected_and_composite_curves(self):
        part = Part(self)
        part.box(40, 30, 10)
        curve = part.do('curve_xyz', points=[[0, 0, 10], [10, 5, 15], [20, 0, 20]])
        self.assertAlmostEqual(float(part.session.model['sketches'][curve].reshape(-1, 3)[:, 2].max()), 20, places=6)
        spots = [part.do('point', position=[[x, y, 12]]) for x, y in ((0, 0), (10, 10), (20, 0))]
        through = part.do('curve_points', points=spots, closed=True)
        self.assertEqual(part.session.model['status'][through], 'ok')
        projected = part.do('curve_project', sketch=part.sketch(line(-10, 0, 10, 0), offset=50))
        heights = part.session.model['sketches'][projected].reshape(-1, 3)[:, 2]
        self.assertEqual(sorted(set(round(float(z), 6) for z in heights)), [0.0, 10.0])     # 上下两个面上各一条
        top = [edge for edge in part.session.model['edges'] if edge['type'] == 'line' and abs(edge['mid'][2] - 10) < 1e-6]
        two = [edge for edge in top if abs(edge['mid'][0] - 20) < 1e-6 or abs(edge['mid'][1] - 15) < 1e-6]
        composite = part.do('curve_composite', edges=[{'point': list(edge['mid'])} for edge in two])
        part.do('sweep', sketch=part.sketch(circle(2, cx=20, cy=10), plane='XZ', offset=15), path=composite)
        self.assertGreater(part.volume, 12000 + 100)


class TableTests(unittest.TestCase):
    def test_every_spec_has_a_command_a_maker_and_a_form(self):
        from genform.kernel import features as kernel
        names = {item['name'] for item in commands.catalog()}
        session = Session()
        for kind, spec in features.SPECS.items():
            self.assertIn(kind, names)
            self.assertTrue(kind in kernel.MAKERS or kind in kernel.MODIFIERS or kind in kernel.CURVES or kind in kernel.REFERENCES, kind)
            form = forms.new_form(kind, session)
            self.assertEqual(form['title'], spec['title'])
            self.assertEqual({f['key'] for f in form['fields'] if f['type'] != 'info'},
                             {f['key'] for f in spec['fields'] if f['kind'] not in ('edges', 'faces')}, kind)
        self.assertEqual(forms.new_form('revolve_cut', session)['title'], '旋转切除')

    def test_form_round_trip_creates_and_edits(self):
        part = Part(self)
        part.box(40, 30, 10)
        session = part.session
        session.selection['faces'] = [next(face['id'] for face in part.faces if face.get('normal') and face['normal'][2] > 0.9)]
        form = forms.new_form('shell', session)
        self.assertEqual(form['pick']['kind'], 'face')
        name, args = forms.to_command(form, session)
        identifier = part.do(name, **args)
        self.assertAlmostEqual(part.volume, 12000 - 36 * 26 * 8, delta=1e-3)
        edit = forms.feature_form(session.document.find(identifier), session)
        next(field for field in edit['fields'] if field['key'] == 'thickness')['value'] = 1.0
        name, args = forms.to_command(edit, session)
        self.assertEqual((name, args['params']), ('edit_feature', {'thickness': 1.0, 'walls': '', 'wall_thickness': 0.0}))  # 没重新选面: 不动原来的
        table = forms.new_form('pattern_table', session)
        next(field for field in table['fields'] if field['key'] == 'points')['value'] = '5,5; 10,5,3'
        self.assertEqual(forms.to_command(table, session)[1]['points'], [[5.0, 5.0], [10.0, 5.0, 3.0]])
        session.selection['faces'] = [next(face['id'] for face in session.model['faces'] if face.get('normal') and face['normal'][0] > 0.9)]
        plane = forms.new_form('plane', session)
        values = forms.values_of(plane)
        self.assertEqual(values['normal'], '1,0,0')


if __name__ == '__main__':
    unittest.main()
