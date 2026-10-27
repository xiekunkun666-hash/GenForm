"""Changing an imported file must invalidate memory and disk rebuild results."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

from genform.document import Document
from genform.kernel import build, store
from genform.kernel.model import rebuild as rebuilding
from genform.kernel.ops.importing import _FILES


class ImportCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.enterContext(patch.dict(os.environ, {'GENFORM_CACHE': str(self.folder / 'cache')}))
        rebuilding._STEPS.clear()
        rebuilding._SPARE.clear()
        _FILES.clear()
        self.addCleanup(rebuilding._STEPS.clear)
        self.addCleanup(rebuilding._SPARE.clear)
        self.addCleanup(_FILES.clear)
        self.path = self.folder / 'changing.step'
        self.document = Document()
        self.document.add('import_step', {'path': str(self.path), 'op': 'add'}, 'Imported source')

    def write_box(self, length):
        previous = self.path.stat().st_mtime_ns if self.path.exists() else 0
        writer = STEPControl_Writer()
        writer.Transfer(BRepPrimAPI_MakeBox(length, 10, 10).Shape(), STEPControl_AsIs)
        self.assertEqual(writer.Write(str(self.path)), IFSelect_RetDone)
        if self.path.stat().st_mtime_ns <= previous:
            os.utime(self.path, ns=(previous + 1000000, previous + 1000000))

    def length(self):
        shape, sketches, statuses = build.rebuild(self.document.features)
        self.assertEqual(statuses['f1'], 'ok')
        low, high = build.bounds(shape)
        return high[0] - low[0]

    def test_memory_rebuild_reads_updated_source(self):
        self.write_box(10)
        self.assertAlmostEqual(self.length(), 10)
        self.write_box(25)
        self.assertAlmostEqual(self.length(), 25)

    def test_old_disk_result_cannot_hide_source_changes(self):
        self.write_box(10)
        self.length()
        features = self.document.features
        old_key = build._step_keys(features)[-1]
        _, shape, tables, statuses = rebuilding._STEPS[-1]
        store.save(old_key, shape, tables, statuses)
        self.assertTrue(store.has(old_key))
        self.write_box(35)
        rebuilding._STEPS.clear()
        rebuilding._SPARE.clear()
        self.assertNotEqual(build._step_keys(features)[-1], old_key)
        self.assertAlmostEqual(self.length(), 35)

    def test_deleted_source_reports_error_not_cached_success(self):
        self.write_box(10)
        self.length()
        self.path.unlink()
        shape, sketches, statuses = build.rebuild(self.document.features)
        self.assertTrue(statuses['f1'].startswith('error'), statuses)

    def test_only_source_and_downstream_keys_change(self):
        self.write_box(10)
        features = [{'id': 'f0', 'type': 'plane', 'params': {'base': 'XY', 'offset': 0}},
                    *copy.deepcopy(self.document.features),
                    {'id': 'f2', 'type': 'plane', 'params': {'base': 'XY', 'offset': 5}}]
        before = build._step_keys(features)
        self.write_box(20)
        after = build._step_keys(features)
        self.assertEqual(before[0], after[0])
        self.assertNotEqual(before[1], after[1])
        self.assertNotEqual(before[2], after[2])

    def test_display_name_does_not_invalidate_geometry(self):
        self.write_box(10)
        before = build._step_keys(self.document.features)
        self.document.features[0]['name'] = 'Renamed'
        self.assertEqual(build._step_keys(self.document.features), before)


if __name__ == '__main__':
    unittest.main()
