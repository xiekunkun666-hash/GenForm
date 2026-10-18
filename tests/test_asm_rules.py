"""装配体设计检查的新规则: 电化学腐蚀、紧固件、重复摆放、外购件报价 / 标准件规格、重量重心、运动干涉。"""
import unittest

from genform import asm_rules
from genform.session import Session
from tests.test_assembly_parts import Files, ask

NAMES = ['车身', '支架', '螺栓', '盖板']


def pair(a, b, kind='touch'):
    return {'a': a, 'b': b, 'kind': kind, 'point': [0, 0, 0]}


class Rules(unittest.TestCase):
    def test_galvanic_pairs(self):
        metals = {0: '普通碳钢', 1: '铝合金 6061', 2: '不锈钢 304', 3: '紫铜'}
        issues = asm_rules.galvanic([pair(0, 1), pair(1, 2), pair(0, 3), pair(2, 3, 'gap')], metals.get, NAMES)
        titles = sorted(item['title'] for item in issues)
        self.assertEqual(len(issues), 2)                               # 钢 ↔ 铝 差 0.05 不算; 隔开的 (gap) 不算
        self.assertTrue(any('不锈钢 304' in title and '铝合金 6061' in title for title in titles))
        self.assertTrue(any('普通碳钢' in title and '紫铜' in title for title in titles))
        self.assertEqual(issues[0]['level'], 'warning')

    def test_lonely_fastener(self):
        kinds = ['custom', 'custom', 'standard', 'standard']
        issues = asm_rules.fasteners([pair(0, 2), pair(1, 2), pair(0, 3)], kinds, NAMES)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['features'], ['part:3'])            # 螺栓 (2) 连着两个件, 盖板 (3) 这个标准件只贴着一个

    def test_duplicates(self):
        parts = [{'name': '轮 1', 'path': 'w.gform', 'move': [0, 0, 0]}, {'name': '轮 2', 'path': 'w.gform', 'move': [100, 0, 0]},
                 {'name': '轮 3', 'path': 'w.gform', 'move': [0.0004, 0, 0]}]
        issues = asm_rules.duplicates(parts)
        self.assertEqual([item['features'] for item in issues], [['part:0', 'part:2']])
        self.assertEqual(issues[0]['level'], 'error')

    def test_bill_gaps(self):
        rows = [{'name': '大灯', 'kind': 'purchase', 'unit': 0.0, 'spec': '', 'indices': [3]},
                {'name': '螺栓', 'kind': 'standard', 'unit': 2.0, 'spec': '', 'indices': [5]},
                {'name': '尾灯', 'kind': 'purchase', 'unit': 900.0, 'spec': 'LED', 'indices': [7]}]
        codes = {item['code']: item for item in asm_rules.bill_gaps(rows)}
        self.assertEqual(codes['no_price']['features'], ['part:3'])
        self.assertEqual(codes['no_spec']['features'], ['part:5'])

    def test_mass_and_balance(self):
        props = [{'volume': 1_000_000.0, 'centre': [0, 0, 0]}, {'volume': 1_000_000.0, 'centre': [0, 300, 0]},
                 {'volume': 5.0, 'centre': [0, 0, 0]}]
        material = {0: '普通碳钢', 1: '普通碳钢', 2: ''}.get
        issues = asm_rules.mass(props, material, ['甲', '乙', '没材质的'], [1000, 1000, 500])
        codes = {item['code']: item for item in issues}
        self.assertIn('15.7 kg', codes['mass']['title'])               # 两块 1 L 钢: 7.85 kg × 2
        self.assertIn('没定材质', codes['mass']['detail'])
        self.assertIn('偏右 150', codes['off_centre']['title'])

    def test_motion_issue(self):
        rows = [{'joint': 0, 'value': 32.5, 'a': 1, 'b': 0, 'names': ['车门', '车身'], 'depth': 3.0, 'volume': 80.0, 'point': [1, 2, 3]}]
        issues = asm_rules.motion(rows, ['左车门'], lambda number: '°')
        self.assertEqual(issues[0]['title'], '运动干涉：左车门 开到 32.5°')
        self.assertEqual(issues[0]['features'], ['part:1', 'part:0'])


class Sweep(unittest.TestCase):
    def test_lid_swung_down_hits_the_wall(self):
        files = Files(self)
        session = Session()
        base = files.block('底板')                                     # 40×40×10
        wall = files.block('挡块', cx=40, z=10, w=10, h=40, d=30)      # 盖子右边立着一块 (x 35 … 45, 高到 z 40)
        lid = files.block('盖', z=10, w=40, h=40, d=4)                 # z 10 … 14, x -20 … 20
        parts = [{'name': '底板', 'path': base}, {'name': '挡块', 'path': wall}, {'name': '盖', 'path': lid}]
        joint = {'name': '盖子', 'parts': [2], 'origin': [-20, 0, 14], 'axis': [0, 1, 0], 'kind': 'hinge', 'values': [10, 20]}
        result, error = ask(session, 'sweep', {'parts': parts, 'joints': [joint], 'rules': {'tolerance': 0.1, 'clearance': 0.5}})
        self.assertIsNone(error)
        self.assertEqual([(row['value'], row['names']) for row in result], [(10.0, ['盖', '底板'])])   # 往下翻: 先撞上底板


if __name__ == '__main__':
    unittest.main()
