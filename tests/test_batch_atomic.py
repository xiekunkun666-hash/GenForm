"""batch 参数失败时保留完整文档状态，成功时保持逐步历史和一次重算。"""
import copy
import unittest
from unittest.mock import Mock, patch

from genform import commands
from genform.document import DocumentError, UNDO_LIMIT
from genform.session import Session


def sketch_step(**args):
    return {'cmd': 'sketch', 'args': {'shapes': [{'type': 'rect', 'w': 40, 'h': 30}], **args}}


class BatchAtomicTest(unittest.TestCase):
    def setUp(self):
        self.builder = Mock(spec=['build'])
        self.builder.build.side_effect = self.build
        self.session = Session(self.builder)
        self.document = self.session.document
        for number in range(13):
            self.document.add('sketch', {'plane': 'XY', 'shapes': [{'type': 'circle', 'r': number + 1}]})
        self.document.rollback(5)
        self.document.rename('f1', '可重做的名称')
        self.document.undo()
        self.document.set_prop('color', '#123456')
        self.document.set_prop('feature_colors', {'f1': '#ABCDEF'})
        self.document.path = 'unchanged.gform'
        self.document.dirty = False
        self.session.model_revision = self.document.revision
        self.session.selection['feature'] = 'f1'
        self.session.notify = Mock()
        self.session.later = Mock()
        self.session.on_progress = Mock()

    @staticmethod
    def build(features, upto, done):
        done({'status': {feature['id']: 'ok' for feature in features},
              'sketches': {}, 'has_body': False}, None)

    def execute(self, name, **args):
        replies = []
        self.session.execute(name, args, replies.append)
        self.assertEqual(len(replies), 1)
        return replies[0]

    def assert_failed_batch(self, steps, number):
        state = copy.deepcopy(vars(self.document))
        model = self.session.model
        model_revision = self.session.model_revision
        selection = copy.deepcopy(self.session.selection)
        reply = self.execute('batch', steps=steps)
        self.assertFalse(reply['ok'], reply)
        self.assertIn(f'第 {number} 步', reply['error'])
        self.assertIn('整串都没有执行', reply['error'])
        self.assertIs(self.session.document, self.document)
        self.builder.build.assert_not_called()
        self.session.notify.assert_not_called()
        self.session.later.assert_not_called()
        self.session.on_progress.assert_not_called()
        self.assertIs(self.session.model, model)
        self.assertEqual(self.session.model_revision, model_revision)
        self.assertEqual(self.session.selection, selection)
        self.assertFalse(self.session.busy)
        for key, value in state.items():
            with self.subTest(state=key):
                self.assertEqual(vars(self.document).get(key), value)
        self.assertEqual(vars(self.document), state)

    def test_thirteen_steps_rejected_at_appearance_preserve_all_state(self):
        self.assertEqual(self.document._serial, 13)
        self.assertTrue(self.document.can_redo())
        steps = [sketch_step() for number in range(12)]
        steps.append({'cmd': 'set_appearance', 'args': {'color': '#FF0000'}})
        with patch.object(commands.get('set_appearance'), 'handler') as handler:
            self.assert_failed_batch(steps, 13)
            handler.assert_not_called()
        self.assertEqual(self.document.add('sketch', {'shapes': []}), 'f14')

    def test_missing_argument_after_valid_step_preserves_all_state(self):
        self.assert_failed_batch([sketch_step(), {'cmd': 'sketch', 'args': {}}], 2)

    def test_unknown_argument_after_valid_step_preserves_all_state(self):
        self.assert_failed_batch([sketch_step(), {'cmd': 'extrude', 'args': {'distance': 4, 'depth': 2}}], 2)

    def test_invalid_number_after_valid_step_preserves_all_state(self):
        self.assert_failed_batch([sketch_step(), {'cmd': 'extrude', 'args': {'distance': 'invalid'}}], 2)

    def test_invalid_reference_after_valid_step_preserves_all_state(self):
        self.assert_failed_batch([sketch_step(), {'cmd': 'extrude', 'args': {'distance': 4, 'sketch': '$9'}}], 2)

    def test_missing_feature_after_valid_step_preserves_all_state(self):
        self.assert_failed_batch([sketch_step(), {'cmd': 'delete_feature', 'args': {'id': 'f999'}}], 2)

    def test_undo_limit_does_not_discard_original_history_on_failure(self):
        for number in range(UNDO_LIMIT):
            self.document.rename('f1', f'原始历史 {number}')
        self.assertEqual(len(self.document._undo), UNDO_LIMIT)
        self.assert_failed_batch([sketch_step(), {'cmd': 'sketch'}], 2)

    def test_long_failed_batch_restores_features_and_original_history(self):
        self.assert_failed_batch([sketch_step() for number in range(UNDO_LIMIT + 1)]
                                 + [{'cmd': 'sketch'}], UNDO_LIMIT + 2)

    def test_edits_suppression_deletion_and_rollback_are_restored_on_failure(self):
        self.document.dirty = True
        self.assert_failed_batch([
            {'cmd': 'edit_feature', 'args': {'id': 'f1', 'params': {'shapes': [{'type': 'circle', 'r': 99}]}}},
            {'cmd': 'rename_feature', 'args': {'id': 'f2', 'name': '临时名称'}},
            {'cmd': 'suppress_feature', 'args': {'id': 'f3'}},
            {'cmd': 'rollback', 'args': {'count': 2}},
            {'cmd': 'delete_feature', 'args': {'id': 'f1'}},
            sketch_step(),
            {'cmd': 'sketch'}], 7)

    def test_partial_handler_failure_restores_props_and_uncheckpointed_changes(self):
        def fail(session, args):
            session.document.edit(args['id'], {'shapes': []})
            session.document.add('sketch', {'shapes': []})
            session.document.props['feature_colors']['f1'] = '#FFFFFF'
            session.document.set_prop('material', 'temporary')
            session.document.path = 'temporary.gform'
            raise DocumentError('修改中途失败')

        with patch.object(commands.get('edit_feature'), 'handler', side_effect=fail):
            self.assert_failed_batch([
                sketch_step(), {'cmd': 'edit_feature', 'args': {'id': 'f1', 'params': {}}}], 2)

    def test_unexpected_handler_exception_restores_state_before_propagating(self):
        state = copy.deepcopy(vars(self.document))

        def fail(session, args):
            session.document.add('sketch', {'shapes': []})
            session.document.props['feature_colors']['f1'] = '#FFFFFF'
            session.document.transient = True
            raise RuntimeError('unexpected failure')

        with patch.object(commands.get('sketch'), 'handler', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'unexpected failure'):
                commands.get('batch').handler(self.session, {'steps': [sketch_step()]})
        self.assertIs(self.session.document, self.document)
        self.assertEqual(vars(self.document), state)
        self.session.notify.assert_not_called()
        self.builder.build.assert_not_called()

    def test_success_keeps_document_identity_references_and_per_step_history(self):
        state = copy.deepcopy(vars(self.document))
        first = sketch_step()
        first['as'] = 'profile'
        reply = self.execute('batch', steps=[
            first,
            {'cmd': 'extrude', 'args': {'sketch': '$profile', 'distance': 4}},
            {'cmd': 'rename_feature', 'args': {'id': '$2', 'name': '凸台'}},
            {'cmd': 'edit_feature', 'args': {'id': '$2', 'params': {'distance': 8}}}])
        self.assertTrue(reply['ok'], reply)
        self.assertEqual((reply['ids'], reply['count']), (['f14', 'f15', 'f15', 'f15'], 4))
        self.assertIs(self.session.document, self.document)
        self.assertEqual(self.document._serial, 15)
        self.assertEqual(self.document.upto, state['upto'] + 2)
        self.assertEqual(self.document.revision, state['revision'] + 4)
        self.assertTrue(self.document.dirty)
        self.assertEqual(self.document._redo, [])
        self.assertEqual(self.document._undo[:-4], state['_undo'])
        self.assertEqual(self.document.props, state['props'])
        self.assertEqual(self.document.path, state['path'])
        self.assertEqual(self.document.find('f15')['params']['sketch'], 'f14')
        self.assertEqual(self.document.find('f15')['params']['distance'], 8)
        self.builder.build.assert_called_once()
        self.assertEqual(self.session.notify.call_count, 1)
        self.session.later.assert_called_once()
        self.assertEqual(self.builder.build.call_args.args[:2], (self.document.features, self.document.upto))
        self.document.undo()
        self.assertEqual(self.document.find('f15')['params']['distance'], 4)
        self.document.redo()
        self.assertEqual(self.document.find('f15')['params']['distance'], 8)
        for number in range(4):
            self.document.undo()
        self.assertEqual(self.document.features, state['features'])
        self.assertEqual(self.document.upto, state['upto'])

    def test_empty_batch_keeps_existing_no_op_semantics(self):
        state = copy.deepcopy(vars(self.document))
        reply = self.execute('batch', steps=[])
        self.assertEqual(reply, {'ok': True, 'ids': [], 'count': 0})
        self.assertEqual(vars(self.document), state)
        self.builder.build.assert_not_called()
        self.session.notify.assert_not_called()


class BatchGeometryTest(unittest.TestCase):
    def test_geometry_failure_keeps_features_and_builds_only_once(self):
        session = Session()
        document = session.document
        replies = []
        with patch.object(session.builder, 'build', wraps=session.builder.build) as build:
            session.execute('batch', {'steps': [sketch_step(),
                            {'cmd': 'extrude', 'args': {'sketch': '$1', 'distance': 10}},
                            {'cmd': 'fillet', 'args': {'edges': '|Z', 'radius': 80}}]}, replies.append)
            build.assert_called_once()
        self.assertEqual(len(replies), 1)
        reply = replies[0]
        self.assertFalse(reply['ok'], reply)
        self.assertIn('hint', reply)
        self.assertEqual(reply['ids'], ['f1', 'f2', 'f3'])
        self.assertEqual(reply['count'], 3)
        self.assertIs(session.document, document)
        self.assertEqual(len(document.features), 3)
        self.assertEqual(len(document._undo), 3)
        self.assertTrue(session.model['status']['f3'].startswith('error: '))


if __name__ == '__main__':
    unittest.main()
