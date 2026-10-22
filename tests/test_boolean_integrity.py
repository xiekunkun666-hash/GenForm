"""工具体、布尔结果与体积界限的真实几何回归, 不依赖存档或 GUI。"""
import math
import os
import unittest
from unittest.mock import patch

from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopoDS import TopoDS_Solid
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from genform.kernel import build
from genform.kernel.model import rebuild, solids
from genform.kernel.ops import helpers, solid_validation, tools


BODY_SECTIONS = [
    (-2259.5, [[0, 500], [230, 505], [445, 515], [630, 515], [730, 470], [730, 300], [620, 210], [0, 195]]),
    (-2100, [[0, 610], [260, 625], [510, 655], [710, 655], [825, 545], [835, 315], [755, 170], [0, 150]]),
    (-1800, [[0, 700], [280, 712], [550, 752], [760, 782], [885, 640], [887, 340], [805, 170], [0, 145]]),
    (-1290, [[0, 740], [290, 755], [565, 805], [785, 812], [915, 650], [900, 345], [820, 165], [0, 145]]),
    (-730, [[0, 810], [285, 810], [550, 820], [755, 795], [890, 640], [878, 345], [805, 160], [0, 145]]),
    (-250, [[0, 825], [285, 825], [550, 820], [748, 790], [882, 630], [875, 340], [805, 160], [0, 145]]),
    (400, [[0, 835], [295, 835], [570, 840], [775, 822], [905, 650], [895, 340], [815, 160], [0, 145]]),
    (850, [[0, 850], [300, 850], [590, 865], [800, 865], [925, 675], [908, 345], [830, 165], [0, 145]]),
    (1160, [[0, 850], [300, 853], [590, 875], [800, 870], [925, 680], [910, 350], [835, 170], [0, 150]]),
    (1600, [[0, 850], [295, 855], [570, 858], [780, 820], [903, 660], [900, 350], [820, 180], [0, 155]]),
    (2050, [[0, 820], [280, 825], [545, 815], [745, 750], [855, 615], [850, 355], [780, 195], [0, 175]]),
    (2259.5, [[0, 735], [265, 738], [510, 725], [680, 675], [780, 560], [775, 360], [700, 235], [0, 215]]),
]
BONNET_EDGE = [
    [-1980, 270, 673.8657838901806], [-1810, 408, 728.6590142861269],
    [-1460, 465, 777.0252845561508], [-1090, 505, 808.5448802833478],
    [-925, 487, 814.4450469415922], [-902, 250, 794.1561619039003],
]


def box(width=10, height=10, depth=10, origin=(0, 0, 0)):
    return BRepPrimAPI_MakeBox(gp_Pnt(*origin), width, height, depth).Shape()


def loft_sections(ctx, sections, prefix):
    identifiers = []
    for index, params in enumerate(sections):
        identifier = prefix + str(index)
        identifiers.append(identifier)
        ctx.sketches[identifier] = build.build_sketch(params)
    return tools.loft(None, {'sketches': identifiers}, ctx)


def panel_fixture():
    ctx = build.Context([])
    sections = []
    for station, right in BODY_SECTIONS:
        points = right + [[-width, height] for width, height in right[-2:0:-1]]
        sections.append({'plane': 'YZ', 'offset': station,
                         'shapes': [{'type': 'spline', 'closed': True, 'points': points}]})
    body = loft_sections(ctx, sections, 'body')
    sections = [{'plane': 'YZ', 'offset': station,
                 'shapes': [{'type': 'rect', 'cx': width, 'cy': height - 1.8, 'w': 3, 'h': 6.4}]}
                for station, width, height in BONNET_EDGE]
    return body, loft_sections(ctx, sections, 'bonnet')


def open_solid():
    faces = helpers._explore(box(), TopAbs_FACE)
    from OCP.TopoDS import TopoDS_Shell
    builder, shell, solid = BRep_Builder(), TopoDS_Shell(), TopoDS_Solid()
    builder.MakeShell(shell)
    for face in faces[:-1]:
        builder.Add(shell, face)
    builder.MakeSolid(solid)
    builder.Add(solid, shell)
    return solid


class BooleanIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'GENFORM_CACHE': 'off'}))
        self.enterContext(patch.object(solid_validation, '_TOOLS', []))
        self.enterContext(patch.object(solid_validation, '_VOLUMES', []))

    def test_actual_panel_loft_is_valid_but_bad_fuse_is_rejected(self):
        body, tool = panel_fixture()
        self.assertTrue(BRepCheck_Analyzer(body).IsValid())
        self.assertTrue(BRepCheck_Analyzer(tool).IsValid())
        self.assertAlmostEqual(helpers._volume(tool).Mass(), 20697.6, delta=0.01)
        before = helpers._volume(body).Mass()
        raw = solids._boolean(BRepAlgoAPI_Fuse, body, tool, '现场复现')
        with patch.object(solids, '_boolean', return_value=raw):
            if not BRepCheck_Analyzer(raw).IsValid() or helpers._volume(raw).Mass() < before - 0.1:
                with self.assertRaises(build.FeatureError):
                    solids.combine(body, tool, 'add')
            else:
                result = solids.combine(body, tool, 'add')
                self.assertTrue(BRepCheck_Analyzer(result).IsValid())
                self.assertGreaterEqual(helpers._volume(result).Mass(), before - 0.1)
        self.assertAlmostEqual(helpers._volume(body).Mass(), before, places=4)
        self.assertTrue(BRepCheck_Analyzer(body).IsValid())

    def test_actual_panel_tool_and_mirror_add_to_box(self):
        _, tool = panel_fixture()
        transform = gp_Trsf()
        transform.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, -1, 0)))
        body = box(1600, 1200, 300, (-2200, -600, 600))
        for shape in (tool, helpers._moved(tool, transform)):
            before = helpers._volume(body).Mass()
            body = solids.combine(body, shape, 'add')
            self.assertTrue(BRepCheck_Analyzer(body).IsValid())
            self.assertGreaterEqual(helpers._volume(body).Mass(), before - 0.01)

    def test_cut_that_removes_nothing_is_an_error(self):
        body = box(10, 10, 10, (0, 0, 0))
        with self.assertRaisesRegex(build.FeatureError, '没碰到'):
            solids.combine(body, box(2, 2, 2, (50, 50, 50)), 'cut')            # 离得远远的
        with self.assertRaisesRegex(build.FeatureError, '什么都没切掉'):
            solids.combine(body, box(2, 2, 2, (4, 4, 10)), 'cut')              # 只贴着顶面
        self.assertGreater(helpers._volume(body).Mass(), helpers._volume(solids.combine(body, box(2, 2, 2, (4, 4, 9)), 'cut')).Mass())

    def test_open_and_surface_tools_never_reach_boolean(self):
        body = box()
        invalid = open_solid()
        self.assertFalse(BRepCheck_Analyzer(invalid).IsValid())
        for operation in ('add', 'cut', 'common'):
            for tool in (invalid, helpers._explore(body, TopAbs_FACE)[0]):
                with self.subTest(operation=operation), patch.object(solids, '_boolean') as boolean:
                    with self.assertRaises(build.FeatureError):
                        solids.combine(body, tool, operation)
                    boolean.assert_not_called()
        with self.assertRaises(build.FeatureError):
            solids.combine(None, invalid, 'add')

    def test_self_intersecting_extrude_is_rejected(self):
        polygon = BRepBuilderAPI_MakePolygon()
        for point in [(0, 0, 0), (10, 8, 0), (0, 8, 0), (8, 0, 0)]:
            polygon.Add(gp_Pnt(*point))
        polygon.Close()
        face = BRepBuilderAPI_MakeFace(polygon.Wire()).Face()
        invalid = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, 10)).Shape()
        self.assertFalse(BRepCheck_Analyzer(invalid).IsValid())
        with self.assertRaises(build.FeatureError):
            solids.combine(box(), invalid, 'add')

    def test_flat_loft_and_invalid_revolve_are_rejected(self):
        ctx = build.Context([])
        for identifier, offset in [('first', 0), ('second', 0)]:
            ctx.sketches[identifier] = build.build_sketch({'offset': offset,
                'shapes': [{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 10, 'h': 8}]})
        with self.assertRaises(build.FeatureError):
            tools.loft(None, {'sketches': ['first', 'second']}, ctx)
        ctx.sketches['first'] = build.build_sketch({'plane': 'XZ',
            'shapes': [{'type': 'rect', 'cx': 15, 'cy': 10, 'w': 10, 'h': 20}]})
        with patch.object(tools, '_run', return_value=open_solid()), self.assertRaises(build.FeatureError):
            tools.revolve(None, {'sketch': 'first', 'axis': 'SY', 'angle': 360}, ctx)

    def test_inverted_tool_normalizes_without_mutating_source(self):
        inverted = box(5, 5, 5, (8, 0, 0)).Reversed()
        before = helpers._volume(inverted).Mass()
        result = solids.combine(box(), inverted, 'add')
        self.assertTrue(BRepCheck_Analyzer(result).IsValid())
        self.assertAlmostEqual(helpers._volume(result).Mass(), 1075, places=6)
        self.assertEqual(helpers._volume(inverted).Mass(), before)

    def test_plausible_but_invalid_boolean_result_is_rejected(self):
        body, tool = box(), box(3, 3, 3, (9, 0, 0))
        invalid = build._compound([body, open_solid()])
        with patch.object(solids, '_boolean', return_value=invalid), self.assertRaises(build.FeatureError):
            solids.combine(body, tool, 'add')

    def test_mixed_boolean_solid_orientations_cannot_cancel_volume(self):
        body, tool = box(), box(10, 10, 10, (8, 0, 0))
        mixed = build._compound([box(20, 10, 10), box(5, 10, 10, (30, 0, 0)).Reversed()])
        self.assertAlmostEqual(helpers._volume(mixed).Mass(), 1500, places=6)
        with patch.object(solids, '_boolean', return_value=mixed), \
                patch.object(solids, '_unify', side_effect=lambda shape: shape), \
                self.assertRaisesRegex(build.FeatureError, '朝向错误'):
            solids.combine(body, tool, 'add')

    def test_valid_shaped_volume_loss_and_unify_damage_are_rejected(self):
        body, tool = box(), box(5, 5, 5, (9, 0, 0))
        smaller = box(9, 10, 10)
        self.assertTrue(BRepCheck_Analyzer(smaller).IsValid())
        with patch.object(solids, '_boolean', return_value=smaller), self.assertRaisesRegex(build.FeatureError, '体积异常'):
            solids.combine(body, tool, 'add')
        with patch.object(solids, '_unify', return_value=smaller), self.assertRaises(build.FeatureError):
            solids.combine(body, tool, 'add')

    def test_cut_and_common_keep_valid_volume_semantics(self):
        body, tool = box(), box(5, 10, 10, (8, 0, 0))
        expected = {'add': 1300, 'cut': 800, 'common': 200}
        for operation, volume in expected.items():
            with self.subTest(operation=operation):
                result = solids.combine(body, tool, operation)
                self.assertTrue(BRepCheck_Analyzer(result).IsValid())
                self.assertAlmostEqual(helpers._volume(result).Mass(), volume, places=6)
        for operation in ('cut', 'common'):
            with patch.object(solids, '_boolean', return_value=box(20, 10, 10)), \
                    self.assertRaisesRegex(build.FeatureError, '体积异常'):
                solids.combine(body, tool, operation)
        with self.assertRaisesRegex(build.FeatureError, '完全切掉'):
            solids.combine(body, body, 'cut')
        with self.assertRaisesRegex(build.FeatureError, '没有重叠'):
            solids.combine(body, box(origin=(30, 0, 0)), 'common')

    def test_overlapping_compound_tools_do_not_inflate_add_lower_bound(self):
        first, second = box(), box(origin=(5, 0, 0))
        tool = build._compound([first, second])
        body = box(2, 2, 2, (1, 1, 1))
        union = BRepAlgoAPI_Fuse(first, second).Shape()
        with patch.object(solids, '_boolean', return_value=union):
            result = solids.combine(body, tool, 'add')
        self.assertTrue(BRepCheck_Analyzer(result).IsValid())
        self.assertAlmostEqual(helpers._volume(result).Mass(), 1500, places=6)

    def test_tangent_extrude_cannot_silently_remove_base_material(self):
        body = box(40, 30, 10, (-20, -15, 0))
        ctx = build.Context([{'id': 'datum', 'type': 'plane',
                             'params': {'base': 'XY', 'offset': 10, 'angle': 90, 'about': 'x'}}])
        ctx.sketches['profile'] = build.build_sketch({'plane': 'datum',
            'shapes': [{'type': 'circle', 'cx': 0, 'cy': 15, 'r': 5}]}, ctx.features)
        tool = build.extrude_solid({'sketch': 'profile', 'distance': 8}, ctx)
        raw = solids._boolean(BRepAlgoAPI_Fuse, body, tool, '相切加料')
        with patch.object(solids, '_boolean', return_value=raw):
            result = solids.combine(body, tool, 'add')
        self.assertTrue(BRepCheck_Analyzer(result).IsValid())
        self.assertAlmostEqual(helpers._volume(result).Mass(), 12000 + math.pi * 25 * 8, places=6)
        self.assertEqual(solids.bounds(result), ((-20, -18, 0), (20, 15, 20)))
        self.assertTrue(all(BRepCheck_Analyzer(part).IsValid() for part in helpers._explore(result, TopAbs_SOLID)))
        self.assertAlmostEqual(helpers._volume(body).Mass(), 12000, places=6)

    def test_failed_fuse_of_edge_or_point_contact_can_keep_compound(self):
        body = box()
        for origin in [(10, 10, 0), (10, 10, 10), (10, 0, 0)]:
            tool = box(origin=origin)
            with self.subTest(origin=origin), patch.object(solids, '_boolean', side_effect=build.FeatureError('Fuse failed')):
                result = solids.combine(body, tool, 'add')
            self.assertTrue(BRepCheck_Analyzer(result).IsValid())
            self.assertEqual(len(helpers._explore(result, TopAbs_SOLID)), 2)
            self.assertAlmostEqual(helpers._volume(result).Mass(), 2000, places=6)
            low, high = solids.bounds(result)
            self.assertEqual(low, (0, 0, 0))
            self.assertEqual(high, tuple(value + 10 for value in origin))

    def test_separation_fallback_cannot_hide_small_positive_overlap(self):
        body = box()
        for overlap in (1, 1e-5, 1e-8):
            tool = box(origin=(10 - overlap, 0, 0))
            with self.subTest(overlap=overlap), \
                    patch.object(solids, '_boolean', side_effect=build.FeatureError('Fuse failed')), \
                    self.assertRaisesRegex(build.FeatureError, 'Fuse failed'):
                solids.combine(body, tool, 'add')

    def test_separation_fallback_refuses_overlapping_compound_members(self):
        tool = build._compound([box(origin=(20, 0, 0)), box(origin=(25, 0, 0))])
        with patch.object(solids, '_boolean', side_effect=build.FeatureError('Fuse failed')), \
                self.assertRaisesRegex(build.FeatureError, 'Fuse failed'):
            solids.combine(box(), tool, 'add')

    def test_separation_fallback_is_bounded(self):
        tool = build._compound([box(origin=(20 * index, 0, 0)) for index in range(1, 13)])
        with patch.object(solids, '_boolean', side_effect=build.FeatureError('Fuse failed')), \
                self.assertRaisesRegex(build.FeatureError, 'Fuse failed'):
            solids.combine(box(), tool, 'add')

    def test_new_face_validation_accepts_thin_glass_and_real_text(self):
        cases = [
            ('glass', {'type': 'ellipse', 'cx': 3, 'cy': 0, 'rx': 9, 'ry': 5, 'angle': 17}, 0.08),
            ('text', {'type': 'text', 'x': -9, 'y': -2, 'text': 'B O 911', 'height': 3, 'font': 'Arial'}, 0.05),
        ]
        for name, shape, depth in cases:
            with self.subTest(kind=name):
                ctx = build.Context([])
                ctx.sketches['profile'] = build.build_sketch({'offset': 9.98, 'shapes': [shape]})
                tool = build.extrude_solid({'sketch': 'profile', 'distance': depth}, ctx)
                body = box(40, 30, 10, (-20, -15, 0))
                analyzer = solid_validation.BRepCheck_Analyzer
                with patch.object(solids, '_separated_add', wraps=solids._separated_add) as fallback, \
                        patch.object(solid_validation, 'BRepCheck_Analyzer', wraps=analyzer) as checks:
                    result = solids.combine(body, tool, 'add')
                fallback.assert_not_called()
                geometric_compounds = [call.args[0] for call in checks.call_args_list
                                       if len(call.args) == 1 and call.args[0].ShapeType() != TopAbs_SOLID]
                self.assertTrue(geometric_compounds)
                self.assertTrue(BRepCheck_Analyzer(result).IsValid())
                self.assertGreater(helpers._volume(result).Mass(), 12000)
                self.assertLessEqual(helpers._volume(result).Mass(), 12000 + helpers._volume(tool).Mass() + 1e-6)
                low, high = solids.bounds(result)
                self.assertAlmostEqual(high[2], 9.98 + depth, delta=1e-6)
                for actual, expected in zip((*low, *high[:2]), (-20, -15, 0, 20, 15)):
                    self.assertAlmostEqual(actual, expected, delta=1e-6)

    def test_unify_volume_change_inside_boolean_bounds_is_rejected(self):
        body, tool = box(), box(5, 10, 10, (8, 0, 0))
        for operation, damaged in [('add', box(11, 10, 10)), ('cut', box(7, 10, 10)),
                                   ('common', box(1, 10, 10))]:
            with self.subTest(operation=operation), patch.object(solids, '_unify', return_value=damaged):
                with self.assertRaisesRegex(build.FeatureError, '合并同面改变了体积'):
                    solids.combine(body, tool, operation)

    def test_surface_boolean_for_sketch_holes_is_still_supported(self):
        sketch = build.build_sketch({'shapes': [{'type': 'circle', 'r': 5}, {'type': 'circle', 'r': 2}]})
        ctx = build.Context([])
        ctx.sketches['ring'] = sketch
        tool = build.extrude_solid({'sketch': 'ring', 'distance': 3}, ctx)
        result = solids.combine(None, tool, 'add')
        self.assertAlmostEqual(helpers._volume(result).Mass(), math.pi * 21 * 3, places=6)

    def test_boolean_reports_errors_and_checks_warned_results(self):
        body, tool = box(), box(2, 2, 2, (9, 0, 0))
        for warning, error, result, rejected in [(True, False, body, False),
                                                 (True, False, open_solid(), True),
                                                 (False, True, body, True)]:
            with self.subTest(warning=warning, error=error, rejected=rejected):
                from unittest.mock import Mock
                maker = Mock()
                maker.IsDone.return_value = True
                maker.Shape.return_value = result
                maker.HasWarnings.return_value = warning
                maker.HasErrors.return_value = error
                if rejected:
                    with self.assertRaises(build.FeatureError):
                        solids._boolean(lambda: maker, body, tool, '布尔诊断')
                else:
                    self.assertTrue(solids._boolean(lambda: maker, body, tool, '布尔诊断').IsEqual(body))
                maker.SetNonDestructive.assert_called_once_with(True)

    def test_rebuild_keeps_prefix_and_skips_later_features_on_boolean_loss(self):
        features = [
            {'id': 'profile', 'type': 'sketch', 'params': {'shapes': [{'type': 'rect', 'w': 10, 'h': 10}]}},
            {'id': 'base', 'type': 'extrude', 'params': {'sketch': 'profile', 'distance': 10}},
            {'id': 'boss', 'type': 'extrude', 'params': {'sketch': 'profile', 'distance': 12}},
            {'id': 'after', 'type': 'extrude', 'params': {'sketch': 'profile', 'distance': 15}},
        ]
        with patch.object(rebuild, '_STEPS', []), patch.object(rebuild, '_SPARE', []), \
                patch.object(solids, '_boolean', return_value=box(9, 10, 10)):
            body, ctx, status = rebuild._rebuild(features)
        self.assertEqual(status['base'], 'ok')
        self.assertTrue(status['boss'].startswith('error:'), status)
        self.assertEqual(status['after'], 'skipped')
        self.assertNotIn('boss', ctx.tools)
        self.assertAlmostEqual(helpers._volume(body).Mass(), 1000, places=6)

    def test_large_base_is_not_geometrically_checked_again(self):
        body, tool = box(100, 100, 100), box(2, 2, 2, (99, 10, 10))
        original = solid_validation.BRepCheck_Analyzer
        with patch.object(solid_validation, 'BRepCheck_Analyzer', wraps=original) as analyzer:
            result = solids.combine(body, tool, 'add')
        for call in analyzer.call_args_list:
            if len(call.args) < 2 or call.args[1]:
                self.assertFalse(call.args[0].IsSame(body))
                self.assertFalse(call.args[0].IsSame(result))
        self.assertLessEqual(len(solid_validation._TOOLS), 16)
        self.assertLessEqual(len(solid_validation._VOLUMES), solid_validation._KEEP_VOLUMES)


if __name__ == '__main__':
    unittest.main()
