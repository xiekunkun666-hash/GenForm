"""工程图和装配体文档: 投影、排版、标尺寸、存取、导出 (不开窗口)。"""
import os
import tempfile
import unittest

from PySide6.QtCore import QObject, Signal

from genform.drawing import Drawing, scale_text
from genform.simulation import Simulation
from tests.test_evaluate import ask
from tests.test_features import Part


class FakeApp(QObject):
    """控制器的替身: 工程图和装配体只用到它的会话、提示和几个信号。"""
    changed = Signal()
    notice = Signal(str)
    languageChanged = Signal()

    def __init__(self, session):
        super().__init__()
        self.session, self.viewport, self.said = session, None, []
        self.notice.connect(self.said.append)

    def _leave_modes(self):
        return True

    def _drop_context(self):
        pass


def plate(case):
    """80 × 50 × 20 的板, 上面一个 Φ12 深 8 的盲孔 (圆心在 10, 5)。"""
    part = Part(case)
    part.box(80, 50, 20)
    part.do('extrude', sketch=part.sketch({'type': 'circle', 'cx': 10, 'cy': 5, 'r': 6}, offset=20), distance=-8, op='cut')
    return part


class ProjectionTest(unittest.TestCase):
    def test_three_views(self):
        result, error = ask(plate(self).session, 'drawing', {'views': ['front', 'top', 'left', 'iso']})
        self.assertIsNone(error)
        self.assertEqual([round(value, 3) for value in result['size']], [80.0, 50.0, 20.0])
        views = result['views']
        self.assertEqual([round(value, 3) for value in views['front']['box']], [-40.0, 0.0, 40.0, 20.0])
        self.assertEqual([round(value, 3) for value in views['top']['box']], [-40.0, -25.0, 40.0, 25.0])
        self.assertEqual([round(value, 3) for value in views['left']['box']], [-25.0, 0.0, 25.0, 20.0])
        self.assertEqual(views['top']['circles'], [[10.0, 5.0, 6.0, True]])
        self.assertTrue(views['front']['hidden'])               # 主视图里盲孔是被挡住的: 虚线
        self.assertFalse(views['iso']['hidden'])                # 轴测图不要虚线


class DrawingTest(unittest.TestCase):
    def setUp(self):
        self.part = plate(self)
        self.app = FakeApp(self.part.session)
        self.drawing = Drawing(self.app)
        self.drawing.begin()

    def texts(self):
        return [item['text'] for item in self.drawing.compose()['texts']]

    def test_layout_and_overall_dimensions(self):
        state = self.drawing.state
        self.assertTrue(state['ready'])
        self.assertEqual(state['scale'], '2:1')                 # A3 上自动挑的比例
        texts = self.texts()
        for value in ('80', '50', '20'):
            self.assertEqual(texts.count(value), 1, value)      # 长宽高各标一次
        placed = self.drawing._placed
        self.assertAlmostEqual(placed['front'][0], placed['top'][0])        # 俯视图在主视图正下方
        self.assertAlmostEqual(placed['front'][1], placed['left'][1])       # 左视图和主视图一样高
        self.assertGreater(placed['top'][1], placed['front'][1])
        self.assertGreater(placed['left'][0], placed['front'][0])
        self.drawing.setScale('0.5')
        self.assertEqual(self.drawing.state['scale'], '1:2')
        self.drawing.toggle('auto')
        self.assertNotIn('80', self.texts())

    def test_smart_dimension(self):
        drawing = self.drawing
        drawing.toggle('auto')
        drawing.compose()
        place = drawing._placed['top']
        drawing.useTool('dimension')
        # 俯视图左下角 → 圆心, 往下拉出去: 水平尺寸 = 50
        drawing.click(*drawing._to_sheet(place, (-40, -25)), 0.2)
        drawing.click(*drawing._to_sheet(place, (10, 5)), 0.2)
        drawing.hover(*drawing._to_sheet(place, (-10, -32)), 0.2)
        drawing.click(*drawing._to_sheet(place, (-10, -32)), 0.2)
        self.assertEqual(drawing._dims[-1]['mode'], 'h')
        self.assertIn('50', self.texts())
        # 同样两个点往左拉: 竖直尺寸 = 30
        drawing.click(*drawing._to_sheet(place, (-40, -25)), 0.2)
        drawing.click(*drawing._to_sheet(place, (10, 5)), 0.2)
        drawing.click(*drawing._to_sheet(place, (-46, -10)), 0.2)
        self.assertEqual(drawing._dims[-1]['mode'], 'v')
        self.assertIn('30', self.texts())
        # 点在圆上: 直径
        drawing.click(*drawing._to_sheet(place, (16, 5)), 0.2)
        drawing.click(*drawing._to_sheet(place, (10, 11)), 0.2)
        self.assertIn('Ø12', self.texts())
        self.assertEqual(len(drawing._dims), 4)
        # 选中再删
        drawing.useTool('dimension')
        drawing.compose()
        _, x, y = drawing._handles[0]
        drawing.click(x, y, 0.2)
        self.assertTrue(drawing.state['selected'])
        drawing.deleteSelected()
        self.assertEqual(len(drawing._dims), 3)
        self.assertNotIn('50', self.texts())

    def test_save_open_and_dxf(self):
        with tempfile.TemporaryDirectory() as folder:
            drawing = self.drawing
            target = os.path.join(folder, 'plate.gdrw')
            drawing.save(target)
            self.assertFalse(os.path.isfile(target))            # 零件还没存成文件: 不让存
            self.part.session.document.save(os.path.join(folder, 'plate.gform'))
            drawing.setSheet('A4')
            drawing.toggleView('iso')
            drawing.setTitle('designer', '张三')
            drawing.save(target)
            self.assertTrue(os.path.isfile(target))
            self.assertFalse(drawing.dirty)
            other = Drawing(FakeApp(Part(self).session))        # 换一个空的会话打开: 零件从文件里读
            self.assertTrue(other.open(target))
            state = other.state
            self.assertEqual((state['sheet'], state['ready']), ('A4', True))
            self.assertEqual([view['on'] for view in state['views']], [True, True, True, False])
            self.assertIn('张三', [item['text'] for item in other.compose()['texts']])
            other.compose()
            dxf = os.path.join(folder, 'plate.dxf')
            other._write_dxf(dxf, other.compose())
            with open(dxf, encoding='utf-8') as handle:
                content = handle.read()
            self.assertIn('HIDDEN', content)
            self.assertTrue(content.rstrip().endswith('EOF'))
            self.assertGreater(content.count('LINE'), 20)

    def test_scale_text(self):
        self.assertEqual([scale_text(value) for value in (2, 1, 0.5, 0.02)], ['2:1', '1:1', '1:2', '1:50'])


class AssemblyDocumentTest(unittest.TestCase):
    def test_open_part_moved_elsewhere_keeps_its_place(self):
        """从装配体里打开一个零件再返回: 这个零件摆在别处的那一项按文件读, 不认成 "当前零件" 画到原点去。"""
        import json
        with tempfile.TemporaryDirectory() as folder:
            part = plate(self)
            first = os.path.join(folder, 'plate.gform')
            part.session.document.save(first)
            target = os.path.join(folder, 'pair.gasm')
            with open(target, 'w', encoding='utf-8') as handle:
                json.dump({'format': 'genform-assembly', 'version': 1, 'parts': [
                    {'name': '原点那块', 'file': 'plate.gform', 'move': [0, 0, 0], 'turn': [0, 0, 0]},
                    {'name': '挪开的', 'file': 'plate.gform', 'move': [40, 0, 0], 'turn': [0, 0, 0]}]}, handle)
            sim = Simulation(FakeApp(part.session))             # 开着的零件就是 plate.gform
            sim.pin()
            self.assertTrue(sim.openAssembly(target))
            self.assertEqual([bool(row['path']) for row in sim._parts], [False, True])
            self.assertEqual(sim._parts[1]['move'][0], 40)
            with open(target, 'w', encoding='utf-8') as handle:       # 只有摆在别处的那一项: 全按文件读
                json.dump({'format': 'genform-assembly', 'version': 1, 'parts': [
                    {'name': '挪开的', 'file': 'plate.gform', 'move': [18, 0, 0], 'turn': [0, 0, 3.75]}]}, handle)
            part.session.document.dirty = False                # 返回装配体前零件已经存过 (backToAssembly 先存)
            again = Simulation(FakeApp(part.session))
            again.app._run = lambda *args, **kwargs: None    # 收掉开着的零件 (new_document): 这里不用真做
            again.pin()
            self.assertTrue(again.openAssembly(target))
            self.assertTrue(again._parts[0]['path'])
            self.assertEqual(again._parts[0]['move'][0], 18)

    def test_pin_save_open_export(self):
        with tempfile.TemporaryDirectory() as folder:
            part = plate(self)
            first = os.path.join(folder, 'plate.gform')
            part.session.document.save(first)
            app = FakeApp(Part(self).session)                   # 空的零件上新建装配体: 从零个零件开始
            sim = Simulation(app)
            sim.pin()
            self.assertEqual(sim.state['parts'], [])
            sim.addPart(first)
            sim.addPart(first)
            sim.placePart(1, 'move', 0, '100')
            self.assertTrue(sim.dirty)
            sim.close()
            self.assertEqual(sim.mode, 'assembly')              # 装配体文档: 这个面板关不掉
            sim.runInterference()
            self.assertEqual(sim._assembly['clashes'], [])
            sim.placePart(1, 'move', 0, '40')
            sim.runInterference()
            self.assertEqual(len(sim._assembly['clashes']), 1)
            target = os.path.join(folder, 'pair.gasm')
            sim.saveAssembly(target)
            self.assertEqual((sim.path, sim.dirty), (target, False))
            step = os.path.join(folder, 'pair.step')
            sim.exportAssembly(step)
            self.assertGreater(os.path.getsize(step), 1000)
            again = Simulation(FakeApp(Part(self).session))
            again.pin()
            self.assertTrue(again.openAssembly(target))
            self.assertEqual([row['move'][0] for row in again.state['parts']], ['0', '40'])
            again.unpin()
            self.assertEqual(again.mode, '')
