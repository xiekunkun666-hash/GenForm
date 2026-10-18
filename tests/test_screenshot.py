"""截图生命周期、重试和 GL 清理：mock 场景/帧缓冲，不创建窗口或 GL 上下文。"""
import threading
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, Signal, QTimer

from genform.controller.common import _ViewAdapter
from genform.document import DocumentError
from genform.session import Session
from genform.view.camera import Camera, VIEWS
from genform.view.viewer.renderer import _Renderer
from genform.view.viewer.screenshot import ScreenshotRequest
from genform.view.viewer.viewing import ViewingMixin
from genform.view.viewer import offscreen

_APP = QCoreApplication.instance() or QCoreApplication([])


def drain_events():
    _APP.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class FakeViewport(QObject, ViewingMixin):
    shotSaved = Signal(str)

    def __init__(self):
        super().__init__()
        self.width = Mock(return_value=800)
        self.height = Mock(return_value=600)
        self.isVisible = Mock(return_value=True)
        self.window_object = Mock()
        for name in ('isVisible', 'isExposed', 'isSceneGraphInitialized'):
            getattr(self.window_object, name).return_value = True
        self.window = Mock(return_value=self.window_object)
        self.window_object.devicePixelRatio.return_value = 1.0
        self._renderer = object()
        self._shot_path = None
        self._camera = Camera()
        self._sketch = None
        self._model = {}
        self._data = {'geometry': {'sketch_points': np.zeros((0, 3))}, 'states': {},
                      'planes': ([], []), 'drawing': ([], [], []), 'extras': []}
        self._gl_dark = Mock(return_value=True)
        self._grid_matrix = Mock(return_value=None)
        self._render_options = Mock(return_value={'style': 'shaded_edges', 'face': (0.2, 0.4, 0.8)})
        self._fitted = False
        self._glide = None
        self._history = []
        self.update = Mock()
        self._redraw = Mock()
        self._glide_timer = Mock()
        self.clear_hover = Mock()
        self.release_hover = Mock()


class ScreenshotAdapterTests(unittest.TestCase):
    def setUp(self):
        self.viewport = FakeViewport()
        self.controller = types.SimpleNamespace(viewport=self.viewport)
        self.adapter = _ViewAdapter(self.controller)
        self.session = Session()
        self.session.view = self.adapter

    def tearDown(self):
        drain_events()

    def start(self, path='capture.png', view=None):
        replies = []
        args = {'path': path}
        if view is not None:
            args['view'] = view
        self.session.execute('screenshot', args, replies.append)
        return replies

    def test_unready_view_fails_before_snap_or_request(self):
        scenarios = [
            (self.viewport.width, 0), (self.viewport.height, 0),
        ]
        with patch.object(self.viewport, 'snap_view') as snap:
            for getter, value in scenarios:
                with self.subTest(getter=getter, value=value):
                    original = getter.return_value
                    getter.return_value = value
                    replies = self.start(view='iso')
                    self.assertEqual(len(replies), 1)
                    self.assertFalse(replies[0]['ok'])
                    self.assertIn('还没准备好', replies[0]['error'])
                    getter.return_value = original
            with patch.dict(self.viewport._data, {}, clear=True):
                self.assertFalse(self.start()[0]['ok'])
            self.controller.viewport = None
            self.assertFalse(self.start()[0]['ok'])
        snap.assert_not_called()
        self.viewport.update.assert_not_called()
        self.assertIsNone(self.adapter._shot_state)

    def test_background_or_uninitialized_scene_uses_offscreen_without_frame_wait(self):
        getters = (self.viewport.isVisible, self.viewport.window_object.isVisible,
                   self.viewport.window_object.isExposed, self.viewport.window_object.isSceneGraphInitialized)
        with patch.object(offscreen, 'start_offscreen') as start:
            for getter in getters:
                getter.return_value = False
                replies = self.start(view='iso')
                request = start.call_args.args[1]
                self.assertIsNone(self.viewport._shot_path)
                request.finish(True)
                self.assertTrue(replies[0]['ok'])
                getter.return_value = True
            self.assertEqual(start.call_count, len(getters))

    def test_offscreen_submit_failure_replies_and_releases_single_flight(self):
        self.viewport.window_object.isExposed.return_value = False
        with patch.object(offscreen, 'start_offscreen', side_effect=RuntimeError('offscreen unavailable')):
            replies = self.start()
        self.assertIn('offscreen unavailable', replies[0]['error'])
        self.assertIsNone(self.adapter._shot_state)
        self.assertIsNone(self.viewport._shot_request)

    def test_empty_model_iso_can_snap_and_reply(self):
        replies = self.start(view='iso')
        request = self.viewport._shot_path
        self.assertEqual(self.viewport._camera.yaw, VIEWS['iso'][0])
        self.assertTrue(self.viewport._fitted)
        self.assertTrue(np.isfinite(self.viewport._camera.distance))
        request.finish(True)
        request.finish(False)
        self.assertEqual(replies, [{'ok': True, 'path': 'capture.png'}])
        self.assertIsNone(self.viewport._shot_request)
        self.assertIsNone(self.adapter._shot_state)
        self.viewport.clear_hover.assert_called_once_with(hold=True)     # 截图里不带用户鼠标停着的悬停高亮
        self.viewport.release_hover.assert_called_once_with()            # 截完放开

    def test_second_request_is_rejected_without_overwriting_first(self):
        first = self.start('a.png')
        request = self.viewport._shot_path
        second = self.start('b.png')
        self.assertFalse(second[0]['ok'])
        self.assertIn('已有截图', second[0]['error'])
        self.assertIs(self.viewport._shot_path, request)
        self.viewport.shotSaved.emit('b.png')
        self.assertEqual(first, [])
        request.finish(True)
        self.assertEqual(first, [{'ok': True, 'path': 'a.png'}])

    def test_deferred_starters_are_also_single_flight(self):
        first = self.adapter.screenshot('a.png', None)
        second = self.adapter.screenshot('b.png', None)
        first_replies, second_replies = [], []
        first(first_replies.append)
        second(second_replies.append)
        self.assertFalse(second_replies[0]['ok'])
        self.viewport._shot_path.finish(True)
        self.assertEqual(first_replies, [{'ok': True, 'path': 'a.png'}])

    def test_timeout_uses_fifteen_seconds_and_old_callbacks_cannot_finish_retry(self):
        replies = self.start('same.png')
        old = self.viewport._shot_path
        timer = old.findChild(QTimer)
        self.assertEqual(timer.interval(), 15000)
        timer.timeout.emit()
        self.assertEqual(len(replies), 1)
        self.assertFalse(replies[0]['ok'])
        self.assertIn('超时', replies[0]['error'])
        self.assertTrue(old.cancelled)
        self.assertFalse(timer.isActive())
        self.assertIsNone(self.viewport._shot_path)
        retry = self.start('same.png')
        current = self.viewport._shot_path
        old.finish(False)
        old.finished.emit('same.png')
        self.viewport.shotSaved.emit('')
        self.assertEqual(retry, [])
        current.finish(True)
        self.assertEqual(retry, [{'ok': True, 'path': 'same.png'}])
        timer.timeout.emit()
        self.assertEqual(len(replies), 1)

    def test_real_timer_fires_without_a_render_frame(self):
        replies, loop = [], QEventLoop()
        with patch.object(self.adapter, 'SCREENSHOT_TIMEOUT_MS', 5):
            self.adapter.screenshot('slow.png', None)(lambda result: (replies.append(result), loop.quit()))
            QTimer.singleShot(200, loop.quit)
            loop.exec()
        self.assertEqual(len(replies), 1)
        self.assertIn('超时', replies[0]['error'])

    def test_snap_update_and_deferred_readiness_exceptions_cleanup(self):
        for method in ('snap_view', 'update'):
            with self.subTest(method=method), patch.object(self.viewport, method, side_effect=RuntimeError('broken')):
                replies = self.start(view='iso')
                self.assertEqual(len(replies), 1)
                self.assertIn('broken', replies[0]['error'])
                self.assertIsNone(self.adapter._shot_state)
                self.assertIsNone(self.viewport._shot_path)
        later = self.adapter.screenshot('later.png', None)
        self.viewport.height.return_value = 0
        replies = []
        later(replies.append)
        self.assertIn('还没准备好', replies[0]['error'])
        self.assertIsNone(self.adapter._shot_state)

    def test_request_initialization_errors_reply_without_leaving_busy_state(self):
        for path in (1, ['invalid.png']):
            with self.subTest(path=path):
                replies = self.start(path)
                self.assertEqual(len(replies), 1)
                self.assertFalse(replies[0]['ok'])
                self.assertIn('TypeError', replies[0]['error'])
                self.assertIsNone(self.adapter._shot_state)
        with patch('genform.view.viewer.screenshot.tempfile.gettempdir', side_effect=OSError('no temp directory')):
            replies = self.start(None)
        self.assertEqual(len(replies), 1)
        self.assertIn('no temp directory', replies[0]['error'])
        self.assertIsNone(self.adapter._shot_state)
        self.viewport.update.assert_not_called()
        retry = self.start()
        self.viewport._shot_path.finish(True)
        self.assertEqual(retry, [{'ok': True, 'path': 'capture.png'}])

    def test_view_destruction_finishes_and_disconnects(self):
        replies = self.start()
        self.viewport.deleteLater()
        drain_events()
        self.assertEqual(len(replies), 1)
        self.assertIn('已销毁', replies[0]['error'])
        self.assertIsNone(self.adapter._shot_state)

    def test_render_thread_completion_is_delivered_on_gui_thread(self):
        replies, loop = [], QEventLoop()
        gui_thread = threading.get_ident()
        self.adapter.screenshot('thread.png', None)(
            lambda result: (replies.append((result, threading.get_ident())), loop.quit()))
        request = self.viewport._shot_path
        worker = threading.Thread(target=lambda: request.finish(True))
        worker.start()
        worker.join(1)
        QTimer.singleShot(200, loop.quit)
        loop.exec()
        self.assertEqual(replies, [({'ok': True, 'path': 'thread.png'}, gui_thread)])


class CameraScreenshotTests(unittest.TestCase):
    def test_invalid_aspects_stay_finite_in_both_projections(self):
        for perspective in (True, False):
            camera = Camera()
            camera.perspective = perspective
            for aspect in (0, -1, float('inf'), float('nan')):
                with self.subTest(perspective=perspective, aspect=aspect):
                    camera.fit((-60, -60, 0), (60, 60, 40), aspect)
                    self.assertGreater(camera.distance, 0)
                    self.assertTrue(np.isfinite(camera.distance))
                    self.assertTrue(np.isfinite(camera.projection(aspect)).all())
            for width, height in ((0, 0), (0, 600), (800, 0)):
                self.assertTrue(np.isfinite(camera.matrix(width, height)).all())

    def test_zero_size_skips_fit_without_changing_camera(self):
        viewport = FakeViewport()
        state = viewport.view_state()
        for width, height in ((0, 600), (800, 0), (0, 0)):
            viewport.width.return_value, viewport.height.return_value = width, height
            with patch.object(Camera, 'fit') as fit:
                self.assertFalse(viewport._glide_to('iso'))
                fit.assert_not_called()
            with self.assertRaisesRegex(DocumentError, '还没准备好'):
                viewport.snap_view('iso')
            self.assertFalse(viewport._fitted)
            self.assertEqual(viewport._camera.distance, state[3])
        viewport.width.return_value, viewport.height.return_value = 800, 600
        viewport.snap_view('iso')
        self.assertTrue(viewport._fitted)

class FakeItem(FakeViewport):
    def __init__(self, request=None):
        super().__init__()
        self._versions = dict.fromkeys(('geometry', 'states', 'planes', 'drawing', 'extras'), 1)
        self._data = {'geometry': {'sketch_points': np.zeros((0, 3))}, 'states': {},
                      'planes': ([], []), 'drawing': ([], [], []), 'extras': []}
        self._shot_path = self._shot_request = request


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.scene = Mock()
        with patch('genform.view.scene.Scene', return_value=self.scene):
            self.renderer = _Renderer()
        self.target = Mock()
        self.target.width.return_value, self.target.height.return_value = 800, 600
        self.target.isValid.return_value = True
        self.target.bind.return_value = True
        self.target.toImage.return_value.save.return_value = True
        self.renderer.framebufferObject = Mock(return_value=self.target)
        self.gl = patch('OpenGL.GL.glGetError', return_value=0).start()
        self.reset = patch('PySide6.QtQuick.QQuickOpenGLUtils.resetOpenGLState').start()
        self.addCleanup(patch.stopall)

    def attach(self):
        request = ScreenshotRequest('capture.png')
        self.results, self.legacy = [], []
        request.finished.connect(self.results.append)
        item = FakeItem(request)
        item.shotSaved.connect(self.legacy.append)
        self.renderer.synchronize(item)
        return item, request

    def assert_finished(self, success):
        self.assertEqual(self.results, ['capture.png' if success else ''])
        self.assertEqual(self.legacy, self.results)
        self.assertIsNone(self.renderer._shot)
        self.reset.assert_called_once()

    def test_empty_synchronize_keeps_request_until_success(self):
        item, request = self.attach()
        self.renderer.synchronize(item)
        self.assertIs(self.renderer._shot, request)
        events = []
        self.target.toImage.side_effect = lambda: (events.append('read'), Mock(save=Mock(return_value=True)))[1]
        self.target.bind.side_effect = lambda: events.append('bind') or True
        self.reset.side_effect = lambda: events.append('reset')
        request.finished.connect(lambda result: events.append('reply'))
        self.renderer.render()
        self.assert_finished(True)
        self.assertEqual(events, ['read', 'bind', 'reset', 'reply'])

    def test_each_failed_upload_is_retained_and_retries_after_sync(self):
        names = ('geometry', 'states', 'planes', 'drawing', 'extras')
        for index, name in enumerate(names):
            with self.subTest(name=name):
                self.renderer._versions = {}
                self.renderer._pending = {}
                self.reset.reset_mock()
                item, request = self.attach()
                setter = getattr(self.scene, 'set_' + name)
                setter.reset_mock()
                setter.side_effect = RuntimeError('upload failed')
                self.renderer.render()
                self.assert_finished(False)
                self.assertIn('upload failed', request.error)
                self.assertEqual(set(self.renderer._pending), set(names[index:]))
                setter.side_effect = None
                retry = ScreenshotRequest('retry.png')
                item._shot_path = retry
                self.renderer.synchronize(item)
                self.renderer.render()
                self.assertEqual(self.renderer._pending, {})
                self.assertEqual(setter.call_count, 2)
                self.assertTrue(retry.done)
                self.assertFalse(retry.error)

    def test_render_readback_save_bind_reset_errors_always_reply_and_cleanup(self):
        for stage in ('render', 'readback', 'save', 'bind', 'reset', 'gl_error'):
            with self.subTest(stage=stage):
                for mock in (self.scene, self.target, self.reset, self.gl):
                    mock.reset_mock(side_effect=True)
                item, request = self.attach()
                failing = {'render': self.scene.render, 'readback': self.target.toImage,
                           'save': self.target.toImage.return_value.save, 'bind': self.target.bind,
                           'reset': self.reset, 'gl_error': self.gl}[stage]
                failing.side_effect = RuntimeError(stage)
                self.renderer.render()
                self.assert_finished(False)
                self.assertIn(stage, request.error)
                if stage != 'gl_error':
                    self.target.bind.assert_called_once()

    def test_false_save_or_bind_result_is_failure(self):
        for stage in ('save', 'bind'):
            with self.subTest(stage=stage):
                self.reset.reset_mock()
                self.target.bind.return_value = stage != 'bind'
                self.target.toImage.return_value.save.return_value = stage != 'save'
                self.attach()
                self.renderer.render()
                self.assert_finished(False)

    def test_missing_frame_or_invalid_fbo_finishes_without_readback(self):
        for stage in ('frame', 'missing_fbo', 'invalid_fbo', 'zero_size'):
            with self.subTest(stage=stage):
                self.reset.reset_mock()
                self.target.toImage.reset_mock()
                self.target.isValid.return_value = stage != 'invalid_fbo'
                self.target.width.return_value = 0 if stage == 'zero_size' else 800
                self.renderer.framebufferObject.return_value = None if stage == 'missing_fbo' else self.target
                self.attach()
                if stage == 'frame':
                    self.renderer._frame = None
                self.renderer.render()
                self.assert_finished(False)
                self.target.toImage.assert_not_called()

    def test_sync_error_finishes_and_does_not_use_previous_frame(self):
        item, request = self.attach()
        item._camera.matrix = Mock(side_effect=RuntimeError('matrix failed'))
        self.renderer.synchronize(item)
        self.assertIsNone(self.renderer._frame)
        self.assertIsNone(self.renderer._shot)
        self.assertEqual(self.results, [''])
        self.assertIn('matrix failed', request.error)

    def test_cancelled_request_is_never_saved_or_acknowledged(self):
        item, request = self.attach()
        request.cancel()
        self.renderer.render()
        self.assertEqual(self.results, [])
        self.assertEqual(self.legacy, [])
        self.target.toImage.assert_not_called()
        self.assertIsNone(self.renderer._shot)
        self.reset.assert_called_once()


class OffscreenTests(unittest.TestCase):
    def test_snapshot_uses_current_camera_options_and_device_pixels(self):
        viewport = FakeViewport()
        viewport.window_object.devicePixelRatio.return_value = 1.5
        viewport._camera.set_view('front')
        state = offscreen.snapshot(viewport)
        self.assertEqual((state.width, state.height), (1200, 900))
        np.testing.assert_allclose(state.frame[0], viewport._camera.matrix(1200, 900))
        self.assertEqual(state.frame[-1]['face'], (0.2, 0.4, 0.8))
        self.assertIs(state.data['geometry']['sketch_points'], viewport._data['geometry']['sketch_points'])

    def test_context_cleanup_restores_previous_on_success_and_failure(self):
        state = offscreen.snapshot(FakeViewport())
        for stage in ('success', 'create', 'current', 'upload', 'render', 'read', 'cleanup'):
            with self.subTest(stage=stage), patch.object(offscreen, 'QOpenGLContext') as contexts, \
                    patch.object(offscreen, 'QOpenGLFramebufferObject') as targets, \
                    patch.object(offscreen, 'QOpenGLFramebufferObjectFormat'), \
                    patch.object(offscreen.contextdata, 'getContext', return_value=123), \
                    patch.object(offscreen.contextdata, 'cleanupContext') as cleanup, \
                    patch.object(offscreen, 'Scene') as scenes, patch.object(offscreen.shiboken6, 'delete') as delete:
                previous, context, target = contexts.currentContext.return_value, contexts.return_value, targets.return_value
                context.create.return_value = stage != 'create'
                context.makeCurrent.return_value = stage != 'current'
                target.toImage.return_value.isNull.return_value = False
                if stage in ('upload', 'render', 'read', 'cleanup'):
                    failing = {'upload': scenes.return_value.set_geometry, 'render': scenes.return_value.render,
                               'read': target.toImage, 'cleanup': target.release}[stage]
                    failing.side_effect = RuntimeError(stage)
                if stage == 'success':
                    offscreen.render_image(state, Mock(), lambda: None)
                    self.assertEqual(scenes.return_value.set_drawing.call_args.args, ([], [], []))
                else:
                    with self.assertRaises(RuntimeError):
                        offscreen.render_image(state, Mock(), lambda: None)
                previous.makeCurrent.assert_called_once_with(previous.surface.return_value)
                self.assertIn(context, [call.args[0] for call in delete.call_args_list])
                context.setShareContext.assert_not_called()
                if stage not in ('create', 'current'):
                    cleanup.assert_called_once_with(123)

    def test_png_cancel_never_commits_and_cleans_temporary_output(self):
        with patch.object(offscreen, 'QSaveFile') as output:
            image = Mock()
            check = Mock(side_effect=[None, TimeoutError('cancelled')])
            with self.assertRaises(TimeoutError):
                offscreen.save_png(image, 'old.png', check)
            output.return_value.commit.assert_not_called()
            output.return_value.cancelWriting.assert_called_once()

    def test_submit_rejects_slow_snapshot_and_overlapping_worker(self):
        app = type('Application', (), {})()
        app.thread, app.aboutToQuit = Mock(return_value=1), Mock()
        type(app).instance = staticmethod(lambda: app)
        with patch.object(offscreen, 'QGuiApplication', type(app)), \
                patch.object(offscreen.QThread, 'currentThread', return_value=1), \
                patch.object(offscreen, '_Job') as jobs, patch.object(offscreen, '_active', None):
            with patch.object(offscreen.time, 'monotonic', side_effect=[0, 1]):
                with self.assertRaisesRegex(TimeoutError, '同步时间'):
                    offscreen.start_offscreen(FakeViewport(), Mock(deadline=20))
            jobs.return_value.deleteLater.assert_called_once()
            with patch.object(offscreen, '_active', object()):
                with self.assertRaisesRegex(DocumentError, '仍在清理'):
                    offscreen.start_offscreen(FakeViewport(), Mock())

    def test_timeout_kills_child_process_without_publishing(self):
        with patch.object(offscreen.subprocess, 'Popen') as launch, patch.object(offscreen, 'QSaveFile') as output:
            launch.return_value.poll.return_value = None
            check = Mock(side_effect=[None, None, TimeoutError('deadline')])
            with self.assertRaises(TimeoutError):
                offscreen.run_process(offscreen.snapshot(FakeViewport()), 'never.png', 1, threading.Event(), check)
            launch.return_value.kill.assert_called_once()
            launch.return_value.communicate.assert_called_once()
            output.assert_not_called()

    def test_cancelled_completion_drops_prepared_png_without_replacing_original(self):
        request = ScreenshotRequest('original.png')
        request.cancel()
        job = types.SimpleNamespace(disposed=False, prepared='prepared.png', request=request,
                                    _shutdown=Mock(), legacy=Mock(), deleteLater=Mock())
        with patch.object(offscreen, 'QGuiApplication'), patch.object(offscreen.os, 'replace') as replace, \
                patch.object(offscreen, 'Path') as path:
            offscreen._Job._complete(job, '')
            replace.assert_not_called()
            path.return_value.unlink.assert_called_once_with(missing_ok=True)
            job.legacy.assert_not_called()


if __name__ == '__main__':
    unittest.main()
