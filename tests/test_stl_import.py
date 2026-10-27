"""STL 组件仅网格导入、装配显示与精确实体查询边界 (无需 GUI)。"""
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.gp import gp_Pnt

from genform.kernel import assembly, build, stl


POINTS = ((0, 0, 0), (2, 0, 0), (0, 3, 0))


def ascii_stl(points=POINTS, name='mesh'):
    vertices = '\n'.join('vertex ' + ' '.join(str(value) for value in point) for point in points)
    return f'solid {name}\nfacet normal 0 0 0\nouter loop\n{vertices}\nendloop\nendfacet\nendsolid {name}\n'.encode()


def binary_stl(points=POINTS, header=b'mesh', normal=(0, 0, 0)):
    return header.ljust(80, b' ') + struct.pack('<I12fH', 1, *normal, *(value for point in points for value in point), 0)


class StlImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        assembly._FILES.clear()
        assembly._PLACED.clear()

    def tearDown(self):
        assembly._FILES.clear()
        assembly._PLACED.clear()
        self.folder.cleanup()

    def write(self, data, name='mesh.stl'):
        path = self.root / name
        path.write_bytes(data)
        return path

    def display(self, parts):
        return assembly.meshes([], None, {'parts': parts})

    def test_ascii_and_binary_on_unicode_paths(self):
        for name, data in [('齿轮 ASCII.STL', ascii_stl()), ('二进制.stl', binary_stl()),
                           ('solid-header.stl', binary_stl(header=b'solid binary mesh'))]:
            with self.subTest(name=name):
                path = self.write(data, name)
                mesh = self.display([{'name': '网格组件', 'path': str(path)}])[0]
                np.testing.assert_allclose(mesh['verts'], POINTS)
                np.testing.assert_allclose(mesh['normals'], [[0, 0, 1]] * 3)
                np.testing.assert_array_equal(mesh['tris'], [[0, 1, 2]])
                self.assertEqual(mesh['geometry'], 'mesh')
                self.assertEqual(mesh['name'], '网格组件')
                self.assertEqual(mesh['verts'].dtype, np.float32)
                self.assertEqual(mesh['tris'].dtype, np.uint32)
                self.assertEqual(mesh['tints'].shape, (3, 3))
                self.assertEqual(mesh['segments'].shape, (0, 2, 3))
                for key in assembly.EDGE_KEYS[1:]:
                    self.assertEqual(mesh[key].size, 0)

    def test_ascii_bom_whitespace_and_multiple_solids_keep_all_facets(self):
        second = np.asarray(POINTS) + [0, 0, 5]
        data = b'\xef\xbb\xbf\r\n\t' + ascii_stl() + ascii_stl(second, 'second')
        path = self.write(data.replace(b'\n', b'\r\n'))
        mesh = stl.read_stl(path)
        self.assertEqual(mesh['tris'].shape, (2, 3))
        np.testing.assert_allclose(mesh['verts'], np.vstack([POINTS, second]))

    def test_supplied_normal_does_not_override_triangle_geometry(self):
        path = self.write(binary_stl(normal=(1, 0, 0)))
        np.testing.assert_allclose(stl.read_stl(path)['normals'], [[0, 0, 1]] * 3)

    def test_multiple_distinct_stl_files_preserve_order_and_placement(self):
        ascii_path = self.write(ascii_stl(), 'first.stl')
        binary_path = self.write(binary_stl(points=np.asarray(POINTS) + [0, 0, 4]), 'second.stl')
        meshes = self.display([{'name': 'ASCII', 'path': str(ascii_path)},
                               {'name': 'binary', 'path': str(binary_path), 'move': [10, 0, 0]}])
        self.assertEqual([mesh['name'] for mesh in meshes], ['ASCII', 'binary'])
        np.testing.assert_allclose(meshes[0]['low'], [0, 0, 0])
        np.testing.assert_allclose(meshes[1]['low'], [10, 0, 4])
        self.assertEqual(len(assembly._FILES), 2)

    def test_record_is_mesh_only_and_cached_without_brep_tessellation(self):
        path = self.write(binary_stl())
        with patch.object(stl, 'read_stl', wraps=stl.read_stl) as reader, \
                patch.object(build, 'tessellate', side_effect=AssertionError('STL must not be tessellated')), \
                patch.object(assembly, '_edge_data', side_effect=AssertionError('STL has no BRep edges')):
            record = assembly._record({'path': str(path)}, [], None)
            self.assertIsNone(record['shape'])
            self.assertEqual(record['geometry'], 'mesh')
            self.assertIs(assembly._part_file(path), record)
            self.assertIs(assembly._step_mesh({'path': path})[0], record['mesh'])
            self.display([{'path': str(path)}, {'path': str(path), 'move': [5, 0, 0]}])
            self.assertEqual(reader.call_count, 1)
            np.testing.assert_allclose(assembly._placed_box(record, {}), [[0, 0, 0], [2, 3, 0]])

    def test_cache_invalidation_reloads_changed_geometry(self):
        path = self.write(binary_stl())
        first = assembly._part_file(path)
        stamp = path.stat().st_mtime_ns
        path.write_bytes(binary_stl(points=np.asarray(POINTS) + [0, 0, 7]))
        os.utime(path, ns=(stamp + 10000000, stamp + 10000000))
        second = assembly._part_file(path)
        self.assertIsNot(first, second)
        np.testing.assert_allclose(second['box'], [[0, 0, 7], [2, 3, 7]])

    def test_translation_rotation_mirror_and_nested_motion(self):
        path = self.write(binary_stl())
        base = assembly._part_file(path)['mesh']['verts'].copy()
        placements = [{}, {'move': [10, 20, 30]}, {'turn': [15, 25, 35]}, {'mirror': True},
                      {'mirror': True, 'move': [2, 4, 6], 'turn': [0, 0, 90],
                       'swing': {'origin': [1, 0, 0], 'axis': [0, 1, 0], 'angle': 30,
                                 'then': {'origin': [0, 0, 0], 'axis': [1, 0, 0], 'slide': 5}}}]
        for placement in placements:
            with self.subTest(placement=placement):
                mesh = self.display([dict(placement, path=str(path))])[0]
                transform = assembly._transform(*assembly._where(placement))
                expected = [gp_Pnt(*point).Transformed(transform) for point in POINTS]
                np.testing.assert_allclose(mesh['verts'], [[point.X(), point.Y(), point.Z()] for point in expected], atol=1e-6)
                np.testing.assert_allclose(mesh['low'], mesh['verts'].min(axis=0))
                np.testing.assert_allclose(mesh['high'], mesh['verts'].max(axis=0))
                corners = mesh['verts'][mesh['tris']][0]
                normal = np.cross(corners[1] - corners[0], corners[2] - corners[0])
                normal /= np.linalg.norm(normal)
                np.testing.assert_allclose(mesh['normals'], np.tile(normal, (3, 1)), atol=1e-6)
        np.testing.assert_array_equal(assembly._part_file(path)['mesh']['verts'], base)

    def test_mixed_step_stl_assembly(self):
        path = self.write(ascii_stl())
        step = self.root / 'box.step'
        writer = STEPControl_Writer()
        writer.Transfer(BRepPrimAPI_MakeBox(2, 3, 4).Shape(), STEPControl_AsIs)
        self.assertEqual(writer.Write(str(step)), IFSelect_RetDone)
        with patch.object(assembly.store, 'folder', return_value=None):
            meshes = self.display([{'path': str(step)}, {'path': str(path), 'move': [10, 0, 0]}])
        self.assertEqual(len(meshes), 2)
        self.assertEqual([mesh['geometry'] for mesh in meshes], ['brep', 'mesh'])
        np.testing.assert_allclose(meshes[1]['low'], [10, 0, 0])
        np.testing.assert_allclose(meshes[0]['high'], [2, 3, 4], atol=1e-6)

    def test_empty_corrupt_truncated_and_nonfinite_files_fail_clearly(self):
        bad = [b'', b' \r\n', b'solid empty\nendsolid empty\n', b'not an stl',
               b'\0' * 84, binary_stl()[:-1], binary_stl() + b'junk',
               binary_stl(points=((float('nan'), 0, 0), *POINTS[1:])),
               binary_stl(points=((float('inf'), 0, 0), *POINTS[1:])),
               binary_stl(points=((0, 0, 0), (0, 0, 0), (0, 1, 0))),
               ascii_stl().replace(b'endsolid mesh\n', b''),
               ascii_stl().replace(b'endloop', b'garbage'),
               ascii_stl() + b'garbage', ascii_stl().replace(b'vertex 2', b'vertex 1e999'),
               ascii_stl() + b'solid broken\nfacet normal 0 0 1\n']
        for number, data in enumerate(bad):
            with self.subTest(number=number):
                path = self.write(data)
                with self.assertRaisesRegex(build.FeatureError, 'STL') as raised:
                    self.display([{'path': str(path)}])
                self.assertIn(str(path), str(raised.exception))
                self.assertNotIn(os.path.normcase(str(path)), assembly._FILES)

    def test_missing_file_and_directory_report_paths(self):
        for path in [self.root / 'missing.stl', self.root / 'directory.stl']:
            with self.subTest(path=path):
                if path.name == 'directory.stl':
                    path.mkdir()
                with self.assertRaisesRegex(build.FeatureError, '打不开') as raised:
                    self.display([{'path': str(path)}])
                self.assertIn(str(path), str(raised.exception))

    def test_exact_geometry_queries_and_step_export_reject_mesh_only_components(self):
        path = self.write(ascii_stl())
        part = {'path': str(path)}
        operations = [assembly.interference, assembly.contacts, assembly.measure_parts, assembly.mass_props,
                      assembly.sequence, assembly.sweep, assembly.export]
        with patch.object(assembly.store, 'folder', return_value=None), patch.object(assembly, '_PAIRS_FILE', []):
            for operation in operations:
                with self.subTest(operation=operation.__name__):
                    with self.assertRaisesRegex(build.FeatureError, 'STL.*三角网格.*精确实体'):
                        operation([], None, {'parts': [part, part], 'path': str(self.root / 'out.step')})
            with self.assertRaisesRegex(build.FeatureError, 'STL.*三角网格'):
                assembly._load(part, [], None)
        self.assertFalse((self.root / 'out.step').exists())

    def test_large_binary_mesh_uses_no_brep_faces(self):
        count = 10000
        facet = binary_stl()[84:]
        path = self.write(b'large mesh'.ljust(80, b' ') + struct.pack('<I', count) + facet * count)
        with patch.object(build, 'tessellate', side_effect=AssertionError('No BRep tessellation')):
            mesh = self.display([{'path': str(path)}])[0]
        self.assertEqual(mesh['tris'].shape, (count, 3))
        self.assertEqual(mesh['verts'].shape, (count * 3, 3))
        self.assertIsNone(assembly._part_file(path)['shape'])


if __name__ == '__main__':
    unittest.main()
