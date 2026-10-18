"""导入实体: 别的 CAD 的 STEP 读进来当实体 (实体的、只有曲面的、几块贴在一起的), 再接着切除 (不开窗口)。"""
import math
import os
import tempfile
import unittest

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_ShellBasedSurfaceModel, STEPControl_Writer
from OCP.TopAbs import TopAbs_FACE
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from genform.kernel.ops import importing
from genform.kernel.model.sketches import _compound
from genform.session import Session

PLATE = 40.0 * 30.0 * 10.0
HOLE = math.pi * 3.0 ** 2 * 10.0


def _plate_with_hole():
    box = BRepPrimAPI_MakeBox(gp_Pnt(-20, -15, 0), 40, 30, 10).Shape()
    pin = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 3, 10).Shape()
    return BRepAlgoAPI_Cut(box, pin).Shape(), pin


def _write(shape, path, mode=STEPControl_AsIs):
    writer = STEPControl_Writer()
    writer.Transfer(shape, mode)
    assert writer.Write(path) == IFSelect_RetDone


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.session = Session()
        importing._FILES.clear()

    def tearDown(self):
        self.folder.cleanup()

    def path(self, name):
        return os.path.join(self.folder.name, name)

    def run_command(self, name, **args):
        replies = []
        self.session.execute(name, args, replies.append)
        return replies[0]

    def imported(self, path):
        reply = self.run_command('import_step', path=path)
        self.assertTrue(reply['ok'], reply.get('error'))
        self.assertEqual(reply['model']['features'][0]['status'], 'ok')
        return reply

    def cut_through(self):
        sketch = self.run_command('sketch', shapes=[{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 2, 'h': 40}])
        cut = self.run_command('extrude', sketch=sketch['id'], distance=10, op='cut')
        self.assertTrue(cut['ok'], cut.get('error'))
        self.assertEqual([feature['status'] for feature in cut['model']['features']], ['ok'] * 3)

    def test_solid_step_becomes_the_body_and_can_be_cut(self):
        plate, _ = _plate_with_hole()
        _write(plate, self.path('plate.step'))
        self.imported(self.path('plate.step'))
        self.assertAlmostEqual(self.session.model['props']['volume'], PLATE - HOLE, delta=1e-3)
        self.assertEqual(self.session.model['info']['f1'], '1 个实体')
        self.cut_through()
        self.assertLess(self.session.model['props']['volume'], PLATE - HOLE - 1.0)

    def test_surface_model_with_a_missing_planar_face_is_sewn_and_patched(self):
        plate, _ = _plate_with_hole()
        faces = importing._parts(plate, TopAbs_FACE)
        top = max(faces, key=_top_z)
        sewing = BRepBuilderAPI_Sewing(1e-6)
        for face in faces:
            if not face.IsSame(top):               # 顶面 (带孔的那张平面) 拿掉: SOLIDWORKS 曲面导出常见的缺面
                sewing.Add(face)
        sewing.Perform()
        _write(sewing.SewedShape(), self.path('open.step'), STEPControl_ShellBasedSurfaceModel)
        self.imported(self.path('open.step'))
        self.assertAlmostEqual(self.session.model['props']['volume'], PLATE - HOLE, delta=1e-2)
        self.assertIn('补了 1 处缺面', self.session.model['info']['f1'])

    def test_touching_parts_are_cut_one_by_one(self):
        plate, pin = _plate_with_hole()                     # 销子正好插在孔里: 两块实体的面贴在一起
        _write(_compound([plate, pin]), self.path('pair.step'))
        self.imported(self.path('pair.step'))
        self.assertAlmostEqual(self.session.model['props']['volume'], PLATE, delta=1e-3)
        self.cut_through()
        self.assertAlmostEqual(self.session.model['props']['volume'], PLATE - 2 * 30 * 10, delta=1e-2)

    def test_missing_file_and_wrong_extension_are_reported(self):
        missing = self.run_command('import_step', path=self.path('nothing.step'))
        self.assertIn('打不开', missing['model']['features'][0]['status'])
        self.run_command('delete_feature', id='f1')
        with open(self.path('note.txt'), 'w') as handle:
            handle.write('x')
        wrong = self.run_command('import_step', path=self.path('note.txt'))
        self.assertIn('.step', wrong['model']['features'][0]['status'])


def _top_z(face):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.CentreOfMass().Z()


if __name__ == '__main__':
    unittest.main()
