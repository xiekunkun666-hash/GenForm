"""矩形框选的纯投影、控制器分发与装配体多选，不创建真实窗口。"""
import unittest
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QObject

from genform.controller.selection import SelectionMixin
from genform.sim.assembly import AssemblyMixin
from genform.sim.part_selection import PartSelectionMixin
from genform.sim.signals import Signals
from genform.view import picking
from genform.view.viewer.overlays import OverlayMixin


class Recorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class ScreenCamera:
    def project(self, points, width, height):
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        return points[:, :2], points[:, 2]


def triangle(points, pick=0, matrix=None):
    verts = np.asarray(points, dtype=float)
    return {'verts': verts, 'tris': np.array([[0, 1, 2]]), 'pick': pick,
            'low': verts.min(axis=0), 'high': verts.max(axis=0), 'matrix': matrix,
            'tints': np.full((3, 3), 0.5)}


class BandHarness(OverlayMixin):
    def __init__(self, meshes=(), geometry=None, vertex_face=(), point_edge=(), sketches=()):
        empty = np.zeros((0, 3))
        self._data = {'extras': list(meshes), 'geometry': geometry or {
            'verts': empty, 'tris': np.zeros((0, 3), dtype=int), 'edge_points': empty, 'sketch_points': empty}}
        self._camera = ScreenCamera()
        self._vertex_face = np.asarray(vertex_face)
        self._point_edge = np.asarray(point_edge)
        self._sketch_owner = list(sketches)
        self._sketch, self._band_points = None, []
        self.bandChanged, self.boxed = Recorder(), Recorder()

    def width(self):
        return 100

    def height(self):
        return 100

    def finish(self, rect, additive=False):
        self._band = rect
        self._finish_band(additive)
        return self.boxed.calls[-1]


class SelectionHarness(PartSelectionMixin, AssemblyMixin, Signals, QObject):
    def __init__(self):
        super().__init__()
        self._parts = [{'name': str(index), 'path': '', 'move': [0, 0, 0], 'turn': [0, 0, 0]}
                       for index in range(3)]
        self._picked, self._joint_picked, self._joint_adding = -1, -1, -1
        self._joints, self._hidden_parts, self._red = [], set(), set()
        self._alone_part, self.mode = None, ''
        self._shown = [(index, triangle([[1, 1, 1], [3, 1, 1], [1, 3, 1]], index)) for index in range(3)]
        self.app = SimpleNamespace(viewport=SimpleNamespace(set_extras=self._record_extras))
        self.extras, self.toggled = [], []

    def _record_extras(self, parts):
        self.extras = parts

    def _moved_mesh(self, index, mesh):
        return mesh

    def _live_clash_parts(self):
        return {}

    def _mated_axes(self, index):
        return ()

    def _joint_of(self, index):
        return -1

    def _toggle_joint_part(self, index):
        self.toggled.append(index)


class ControllerHarness(SelectionMixin):
    def __init__(self, kind='assembly'):
        self._kind, self._sketch, self._picking_plane = kind, None, False
        self._measure, self._form = None, None
        self.sim = SelectionHarness()
        self.session = SimpleNamespace(selection={'faces': [], 'edges': [], 'plane': None, 'feature': None})
        self.viewport = SimpleNamespace(click_at=(10, 20), set_selection=lambda selection: None)
        self.changed, self.contextRequested = Recorder(), Recorder()
        self._context, self.refreshes = {}, 0

    def _drop_context(self):
        self._context = {}

    def _refresh_form_info(self):
        self.refreshes += 1


class MeshBoxSelection(unittest.TestCase):
    def test_direction_changes_containment_to_crossing(self):
        mesh = triangle([[-2, 3, 1], [12, 3, 1], [5, 12, 1]], pick=2)
        view = BandHarness([mesh])
        self.assertEqual(view.finish((0, 0, 10, 10))[0]['components'], [])
        self.assertEqual(view.finish((10, 0, 0, 10), True),
                         ({'faces': [], 'edges': [], 'sketches': [], 'components': [2]}, True))

    def test_window_contains_whole_mesh_including_boundary(self):
        mesh = triangle([[0, 0, 1], [10, 0, 1], [0, 10, 1]])
        view = BandHarness([mesh])
        self.assertEqual(view.finish((0, 0, 10, 10))[0]['components'], [0])
        self.assertIsNone(view._band)
        self.assertEqual(view._band_points, [])

    def test_crossing_hits_face_interior_without_any_vertex_or_edge(self):
        mesh = triangle([[-100, -100, 1], [100, -100, 1], [0, 100, 1]])
        self.assertEqual(BandHarness([mesh]).finish((1, -1, -1, 1))[0]['components'], [0])

    def test_bbox_overlap_without_mesh_overlap_is_not_selected(self):
        mesh = triangle([[0, 0, 1], [10, 0, 1], [0, 10, 1]])
        self.assertEqual(BandHarness([mesh]).finish((10, 8, 8, 10))[0]['components'], [])

    def test_dynamic_matrix_applies_rotation_translation_and_reflection(self):
        matrix = np.eye(4)
        matrix[:3, :3] = [[0, -1, 0], [-1, 0, 0], [0, 0, 1]]
        matrix[:3, 3] = [50, 60, 0]
        mesh = triangle([[1, 1, 1], [3, 1, 1], [1, 3, 1]], matrix=matrix)
        view = BandHarness([mesh])
        self.assertEqual(view.finish((0, 0, 5, 5))[0]['components'], [])
        self.assertEqual(view.finish((46, 56, 50, 60))[0]['components'], [0])
        np.testing.assert_array_equal(mesh['verts'], [[1, 1, 1], [3, 1, 1], [1, 3, 1]])

    def test_unpickable_empty_and_behind_camera_meshes_are_ignored(self):
        meshes = [triangle([[1, 1, -1], [3, 1, -1], [1, 3, -1]]),
                  triangle([[1, 1, 1], [3, 1, 1], [1, 3, 1]], pick=None),
                  {'pick': 1, 'verts': [], 'tris': []}]
        self.assertEqual(BandHarness(meshes).finish((10, 0, 0, 10))[0]['components'], [])

    def test_duplicate_pick_ids_are_only_emitted_once(self):
        mesh = triangle([[1, 1, 1], [3, 1, 1], [1, 3, 1]], pick=2)
        self.assertEqual(BandHarness([mesh, mesh]).finish((0, 0, 10, 10))[0]['components'], [2])

    def test_near_plane_crossing_is_clipped_before_intersection(self):
        class PerspectiveCamera:
            def project(self, points, width, height):
                points = np.asarray(points, dtype=float)
                return points[:, :2] / points[:, 2, None], points[:, 2]

        mesh = triangle([[-10, -10, 2], [10, -10, 2], [0, 10, -1]])
        self.assertTrue(picking.mesh_in_rect(PerspectiveCamera(), 100, 100, mesh, (-1, -1), (1, 1), True))
        self.assertFalse(picking.mesh_in_rect(PerspectiveCamera(), 100, 100, mesh, (-100, -100), (100, 100), False))

    def test_part_geometry_edges_faces_and_sketches_still_work(self):
        geometry = {'verts': np.array([[1, 1, 1], [3, 1, 1], [1, 3, 1]]),
                    'tris': np.array([[0, 1, 2]]),
                    'edge_points': np.array([[1, 1, 1], [3, 1, 1]]),
                    'sketch_points': np.array([[1, 2, 1], [3, 2, 1]])}
        view = BandHarness(geometry=geometry, vertex_face=[4, 4, 4], point_edge=[7, 7], sketches=['s1', 's1'])
        self.assertEqual(view.finish((0, 0, 10, 10))[0],
                         {'faces': [4], 'edges': [7], 'sketches': ['s1'], 'components': [], 'body': True})

    def test_current_body_requires_full_mesh_containment_for_window_selection(self):
        geometry = {'verts': np.array([[1, 1, 1], [3, 1, 1], [1, 3, 1],
                                       [11, 1, 1], [13, 1, 1], [11, 3, 1]]),
                    'tris': np.array([[0, 1, 2], [3, 4, 5]]),
                    'edge_points': np.zeros((0, 3)), 'sketch_points': np.zeros((0, 3))}
        view = BandHarness(geometry=geometry, vertex_face=[0, 0, 0, 1, 1, 1])
        self.assertNotIn('body', view.finish((0, 0, 10, 10))[0])
        self.assertTrue(view.finish((10, 0, 0, 10))[0]['body'])


class AssemblyMultiSelection(unittest.TestCase):
    def setUp(self):
        self.sim = SelectionHarness()

    def selected(self):
        return [row['index'] for row in self.sim.components if row['selected']]

    def test_box_selects_multiple_tree_rows_and_highlights(self):
        self.sim.selectParts([0, 2])
        self.assertEqual(self.selected(), [0, 2])
        self.assertEqual(self.sim.picked, 2)
        self.assertGreater(self.sim.extras[0]['tints'][0, 2], self.sim.extras[1]['tints'][0, 2])
        self.assertGreater(self.sim.extras[2]['tints'][0, 2], self.sim.extras[1]['tints'][0, 2])

    def test_ctrl_box_and_click_accumulate_and_normal_click_replaces(self):
        self.sim.selectPart(0)
        self.sim.selectParts([1], True)
        self.sim.selectPart(2, True)
        self.assertEqual(self.selected(), [0, 1, 2])
        self.sim.selectPart(2)
        self.assertEqual(self.selected(), [2])
        self.sim.selectPart(-1)
        self.assertEqual((self.selected(), self.sim.picked), ([], -1))

    def test_empty_ctrl_box_preserves_and_empty_box_clears(self):
        self.sim.selectParts([0, 1])
        self.sim.selectParts([], True)
        self.assertEqual((self.selected(), self.sim.picked), ([0, 1], 1))
        self.sim.selectParts([])
        self.assertEqual((self.selected(), self.sim.picked), ([], -1))

    def test_box_ignores_hidden_and_isolated_out_parts(self):
        self.sim._hidden_parts = {1}
        self.sim.selectParts([0, 1, 2])
        self.assertEqual(self.selected(), [0, 2])
        self.sim._alone_part = 2
        self.sim.selectParts([0, 1, 2], True)
        self.assertEqual(self.selected(), [2])
        self.assertEqual([part['pick'] for part in self.sim.extras], [2])

    def test_hidden_primary_falls_back_to_a_visible_selected_component(self):
        self.sim.selectParts([0, 1])
        self.sim._hidden_parts = {1}
        self.sim.selectParts([], True)
        self.assertEqual((self.selected(), self.sim.picked), ([0], 0))

    def test_legacy_primary_reset_and_reordered_parts_do_not_resurrect_multiselect(self):
        self.sim.selectParts([0, 1])
        self.sim._picked = -1
        self.assertEqual(self.selected(), [])
        self.sim.selectParts([0, 1])
        self.sim._parts.reverse()
        self.assertEqual(self.selected(), [1])

    def test_joint_assignment_click_keeps_existing_semantics(self):
        self.sim._joints, self.sim._joint_adding = [{}], 0
        self.sim.selectPart(1, True)
        self.assertEqual(self.sim.toggled, [1])
        self.assertEqual(self.selected(), [])

    def test_tree_slot_still_accepts_one_argument_and_hidden_part(self):
        self.sim._hidden_parts = {1}
        self.sim.selectPart(1)
        self.assertEqual(self.selected(), [1])

    def test_invalid_ids_and_duplicates_are_ignored(self):
        self.sim.selectParts([-1, 0, 0, 100, '1'])
        self.assertEqual((self.selected(), self.sim.picked), ([0], 0))


class ControllerDispatch(unittest.TestCase):
    def test_assembly_layout_sketch_can_still_be_box_selected(self):
        app = ControllerHarness()
        app.sim.selectParts([0, 1])
        app._on_boxed({'faces': [], 'edges': [], 'sketches': ['layout1'], 'components': []}, False)
        self.assertEqual(app.sim._selected_part_indices(), set())
        self.assertEqual(app.session.selection['feature'], 'layout1')

    def test_current_document_body_maps_to_own_component_and_respects_hidden(self):
        app = ControllerHarness()
        app.sim._parts[1]['path'] = 'other.gform'
        app.sim._parts[2]['path'] = 'third.gform'
        app._on_boxed({'body': True, 'components': [1]}, False)
        self.assertEqual(app.sim._selected_part_indices(), {0, 1})
        app.sim._hidden_parts = {0}
        app._on_boxed({'body': True}, False)
        self.assertEqual(app.sim._selected_part_indices(), set())

    def test_assembly_box_dispatches_to_sim_and_preserves_part_selection(self):
        app = ControllerHarness()
        app.session.selection['edges'] = [99]
        app._on_boxed({'components': [0, 2]}, False)
        self.assertEqual(app.sim._selected_part_indices(), {0, 2})
        self.assertEqual(app.session.selection['edges'], [99])
        app._on_boxed({'components': [1]}, True)
        self.assertEqual(app.sim._selected_part_indices(), {0, 1, 2})

    def test_component_ctrl_click_accumulates_and_plain_click_replaces(self):
        app = ControllerHarness()
        app._on_picked('component', 0, False)
        app._on_picked('component', 2, True)
        self.assertEqual(app.sim._selected_part_indices(), {0, 2})
        app._on_picked('component', 2, False)
        self.assertEqual(app.sim._selected_part_indices(), {2})
        app._on_picked('', -1, True)
        self.assertEqual(app.sim._selected_part_indices(), {2})
        app._on_picked('', -1, False)
        self.assertEqual(app.sim._selected_part_indices(), set())

    def test_part_box_still_merges_edges_and_single_face_form(self):
        app = ControllerHarness('part')
        app._on_boxed({'faces': [2], 'edges': [3], 'sketches': []}, False)
        app._on_boxed({'faces': [], 'edges': [4], 'sketches': []}, True)
        self.assertEqual(app.session.selection['edges'], [3, 4])
        app._form = {'pick': {'kind': 'face', 'count': 1}}
        app._on_boxed({'faces': [5, 6], 'edges': [], 'sketches': []}, False)
        self.assertEqual(app.session.selection['faces'], [6])

    def test_sketch_edit_plane_and_measure_modes_ignore_assembly_box(self):
        for field in ('_sketch', '_picking_plane', '_measure'):
            app = ControllerHarness()
            setattr(app, field, True)
            app._on_boxed({'components': [1]}, False)
            self.assertEqual(app.sim._selected_part_indices(), set())


if __name__ == '__main__':
    unittest.main()
