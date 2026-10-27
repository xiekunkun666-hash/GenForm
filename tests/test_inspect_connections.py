import unittest
from types import SimpleNamespace

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt

from genform.kernel.inspect import pairs


def box(origin, size):
    return BRepPrimAPI_MakeBox(gp_Pnt(*origin), *size).Shape()


class InspectConnectionsTest(unittest.TestCase):
    def check_pairs(self, shapes, **rules):
        context = SimpleNamespace(tools={name: (shape, 'add') for name, shape in shapes.items()})
        return pairs(context, rules)[0]

    def test_gap_between_robustly_connected_features_is_not_a_separate_part_gap(self):
        shapes = {'left': box((0, 0, 0), (4, 4, 4)),
                  'right': box((4.2, 0, 0), (4, 4, 4)),
                  'bridge': box((2, 2, 0), (4, 2, 4))}
        self.assertEqual(self.check_pairs(shapes), [])

    def test_disconnected_gap_still_fails(self):
        shapes = {'left': box((0, 0, 0), (4, 4, 4)),
                  'right': box((4.2, 0, 0), (4, 4, 4))}
        self.assertEqual([item['kind'] for item in self.check_pairs(shapes)], ['gap'])

    def test_face_only_contact_still_fails_even_with_another_connection(self):
        shapes = {'left': box((0, 0, 0), (4, 4, 4)),
                  'right': box((4, 0, 0), (4, 4, 4)),
                  'bridge': box((2, 2, 0), (4, 2, 4))}
        self.assertEqual([item['kind'] for item in self.check_pairs(shapes)], ['touch'])

    def test_shallow_overlap_still_fails(self):
        shapes = {'left': box((0, 0, 0), (4, 4, 4)),
                  'right': box((3.9, 0, 0), (4, 4, 4))}
        self.assertEqual([item['kind'] for item in self.check_pairs(shapes)], ['shallow'])

    def test_unchecked_bridge_does_not_hide_a_gap(self):
        shapes = {'left': box((0, 0, 0), (4, 4, 4)),
                  'right': box((4.2, 0, 0), (4, 4, 4)),
                  'bridge': box((2, 2, 0), (4, 2, 4))}
        self.assertEqual([item['kind'] for item in self.check_pairs(shapes, pair_limit=1)], ['gap'])


if __name__ == '__main__':
    unittest.main()
