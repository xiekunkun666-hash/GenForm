import tempfile
import unittest
from pathlib import Path

from genform.document import Document
from genform.kernel.model.variables import resolve


class DocumentMetadataTest(unittest.TestCase):
    def test_saved_process_and_folder_survive_reopening(self):
        document = Document()
        identifier = document.add('extrude', {'distance': 4})
        process = {'id': 'laser', 'kind': 'plate', 'spec': '4 mm blank',
                   'alternatives': [{'id': 'cnc3'}]}
        document.set_processes({identifier: process})
        document.set_folder([identifier], 'Lock/Claw')
        with tempfile.TemporaryDirectory() as directory:
            target = str(Path(directory) / 'claw.gform')
            document.save(target)
            reopened = Document()
            reopened.open(target)
            self.assertEqual(reopened.find(identifier)['process'], process)
            self.assertEqual(reopened.find(identifier)['folder'], 'Lock/Claw')
            reopened.save()
            final = Document()
            final.open(target)
            self.assertEqual(final.to_data()['features'], document.to_data()['features'])

    def test_loaded_metadata_is_not_shared_with_source(self):
        document = Document()
        identifier = document.add('extrude', {'distance': 4})
        document.set_processes({identifier: {'id': 'laser', 'alternatives': []}})
        source = document.to_data()
        loaded = Document()
        loaded.load_data(source)
        source['features'][0]['process']['alternatives'].append({'id': 'cnc3'})
        self.assertEqual(loaded.find(identifier)['process']['alternatives'], [])

    def test_expression_resolution_preserves_loaded_process(self):
        document = Document()
        document.add('variables', {'values': {'thickness': 4}})
        identifier = document.add('extrude', {'distance': '=thickness'})
        document.set_processes({identifier: {'id': 'laser'}})
        loaded = Document()
        loaded.load_data(document.to_data())
        features, errors = resolve(loaded.features)
        self.assertFalse(errors)
        self.assertEqual(features[-1]['params']['distance'], 4)
        self.assertEqual(features[-1]['process']['id'], 'laser')

    def test_legacy_documents_do_not_gain_optional_fields(self):
        document = Document()
        document.add('extrude', {'distance': 4})
        loaded = Document()
        loaded.load_data(document.to_data())
        self.assertNotIn('process', loaded.features[0])
        self.assertNotIn('folder', loaded.features[0])


if __name__ == '__main__':
    unittest.main()
