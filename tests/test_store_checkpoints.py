# -*- coding: utf-8 -*-
"""磁盘缓存的中间检查点: 存盘时除了最后一步, 每算了一阵子存一份; 打开后改了后面的特征, 从最近的检查点接着算。"""
import os
import tempfile
import unittest
from unittest.mock import patch

from genform.kernel import build, store
from genform.kernel.model import rebuild as rebuild_steps


def features():
    rows = []
    for number in range(4):
        rows.append({'id': f's{number}', 'type': 'sketch', 'name': f's{number}',
                     'params': {'plane': 'XY', 'offset': 10.0 * number, 'shapes': [{'type': 'rect', 'w': 40 - 5 * number, 'h': 30}]}})
        rows.append({'id': f'e{number}', 'type': 'extrude', 'name': f'e{number}', 'params': {'sketch': f's{number}', 'distance': 10.0}})
    return rows


class Checkpoints(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for patcher in (patch.dict(os.environ, {'GENFORM_CACHE': temporary.name}),
                        patch.object(rebuild_steps, 'STORE_AFTER', float('inf')),
                        patch.object(rebuild_steps, 'CHECKPOINT_EVERY', 0.0)):     # 每一步都算 "算了一阵子"
            patcher.start()
            self.addCleanup(patcher.stop)
        self.clear()

    @staticmethod
    def clear():
        for cache in (build._STEPS, build._SPARE, build._SHOWN, build._FACE_MESHES, rebuild_steps._MESHED):
            cache.clear()

    def test_edit_after_reopen_continues_from_checkpoint(self):
        rows = features()
        whole = build.build_model(rows)
        build.keep()
        keys = build._step_keys(rows)
        self.assertTrue(store.has(keys[-1]) and store.has(keys[3]))         # 最后一步 + 中间的检查点
        self.clear()                                                        # 像重新打开软件
        rows[-1]['params']['distance'] = 20.0                               # 改最后一个特征
        calls = []
        original = rebuild_steps.combine
        with patch.object(rebuild_steps, 'combine', side_effect=lambda *a, **k: calls.append(1) or original(*a, **k)):
            edited = build.build_model(rows)
        self.assertEqual(len(calls), 1)                                     # 只重算了改的那一个
        self.assertIs(build._STEPS[0][1], build._MISSING)
        self.assertGreater(edited['props']['volume'], whole['props']['volume'])
        self.assertEqual(set(edited['status'].values()), {'ok'})

    def test_no_checkpoints_when_rebuild_was_quick(self):
        with patch.object(rebuild_steps, 'CHECKPOINT_EVERY', float('inf')):
            rows = features()
            build.build_model(rows)
            build.keep()
        keys = build._step_keys(rows)
        self.assertTrue(store.has(keys[-1]))
        self.assertFalse(any(store.has(key) for key in keys[:-1]))


if __name__ == '__main__':
    unittest.main()
