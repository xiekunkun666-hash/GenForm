"""交互期间保持用户选择的显示样式, 不创建窗口或 OpenGL 上下文。"""
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import numpy as np
from PySide6.QtCore import Qt

from genform.view import scene
from genform.view.camera import Camera
from genform.view.viewer.display import DisplayMixin
from genform.view.viewer.mouse import MouseMixin


def renderer():
    made = scene.Scene()
    made._ready = True
    made._empty = 1
    for name in ('back', 'flat', 'mesh', 'line'):
        shader = MagicMock()
        shader.loc.side_effect = lambda uniform, prefix=name: f'{prefix}.{uniform}'
        setattr(made, f'_{name}', shader)
    for index, name in enumerate(('grid', 'axes', 'axis_solid', 'faces', 'edges', 'sketches',
                                 'plane_fill', 'plane_edge', 'draw_lines', 'draw_points'), 2):
        setattr(made, f'_{name}', SimpleNamespace(vao=index, count=0))
    made._faces.count, made._edges.count = 6, 4
    made._covered, made._tinted = False, True
    made._glass = [(1, 1, 0.4)]
    transform = np.eye(4, dtype=np.float32)
    transform[:3, 3] = (20, -10, 5)
    made._extras = [(SimpleNamespace(vao=20, count=6), (0.2, 0.4, 0.6), True, 1.0, transform),
                    (SimpleNamespace(vao=21, count=3), (0.6, 0.5, 0.4), False, 0.3, transform)]
    made._extra_edges = [(SimpleNamespace(vao=22, count=4), transform),
                         (SimpleNamespace(vao=23, count=2), transform)]
    made._extra_hover = SimpleNamespace(vao=24, count=2)
    made._extra_hover_model = transform
    return made


def render_calls(made, options, dark=True):
    calls = Mock()
    replacements = {name: getattr(calls, name) for name, value in vars(scene).items()
                    if name.startswith('gl') and callable(value)}
    made._grid_dark = dark
    with patch.dict(vars(scene), replacements):
        made.render(800, 600, np.eye(4), (100, 80, 60), dark, options=options)
    return [(entry[0], tuple(argument.tolist() if isinstance(argument, np.ndarray)
                            else argument.value if isinstance(argument, ctypes.c_void_p)
                            else argument for argument in entry[1])) for entry in calls.mock_calls]


def draws_for(calls, vao):
    bound, alpha, depth = None, None, None
    draws = []
    for name, arguments in calls:
        if name == 'glBindVertexArray':
            bound = arguments[0]
        elif name == 'glUniform1f' and arguments[0] == 'line.alpha':
            alpha = arguments[1]
        elif name == 'glDepthFunc':
            depth = arguments[0]
        elif name in ('glDrawArrays', 'glDrawElements') and bound == vao:
            draws.append((name, alpha, depth))
    return draws


class DisplayStabilityTests(unittest.TestCase):
    def test_motion_keeps_all_render_passes_unchanged(self):
        for style in scene.STYLES:
            for dark in (True, False):
                with self.subTest(style=style, dark=dark):
                    made = renderer()
                    options = {'style': style, 'origin': 0.0, 'cartoon': True,
                               'clip': (0.0, 0.0, 1.0, -2.0), 'face': (0.4, 0.5, 0.6)}
                    idle = render_calls(made, {**options, 'moving': False}, dark)
                    moving = render_calls(made, {**options, 'moving': True}, dark)
                    self.assertEqual(idle, moving)
                    self.assertEqual(idle, render_calls(made, options, dark))

    def test_each_style_keeps_its_face_and_edge_policy(self):
        for style in scene.STYLES:
            for moving in (False, True):
                with self.subTest(style=style, moving=moving):
                    made = renderer()
                    calls = render_calls(made, {'style': style, 'moving': moving, 'origin': 0.0})
                    for vao in (22, 23):
                        expected = [] if style == 'shaded' else [('glDrawArrays', 0.85, scene.GL_LEQUAL)]
                        if style == 'hlv':
                            expected.insert(0, ('glDrawArrays', 0.28, scene.GL_GREATER))
                        self.assertEqual(draws_for(calls, vao), expected)
                    own_edges = [('glDrawArrays', 0.0 if style == 'shaded' else 0.9, scene.GL_LEQUAL)]
                    if style == 'hlv':
                        own_edges.insert(0, ('glDrawArrays', 0.28, scene.GL_GREATER))
                    self.assertEqual(draws_for(calls, made._edges.vao), own_edges)
                    for vao in (made._faces.vao, 20, 21):
                        self.assertEqual(bool(draws_for(calls, vao)), style != 'wire')
                    self.assertEqual(draws_for(calls, 24), [('glDrawArrays', 1.0, scene.GL_LEQUAL)])

    def test_mouse_interactions_keep_camera_controls_and_selected_style(self):
        for style in scene.STYLES:
            for operation in ('orbit', 'pan', 'zoom', 'box'):
                with self.subTest(style=style, operation=operation):
                    display = {'style': style, 'scene': 'auto', 'cartoon': True, 'origin': False,
                               'color': (0.3, 0.5, 0.7), 'section': None}
                    viewer = SimpleNamespace(
                        _display=display.copy(), _camera=Camera(), _sketch=None, _moving=True,
                        _zoom=None, _handle_drag=False, _press=None, _joint_drag=None,
                        _band=None, _pivot=None, _wheel_anchor=None, _wheel_at=0.0,
                        _model={}, _draws=lambda *args: False, _stop_glide=Mock(),
                        _redraw=Mock(), _remember=Mock(), _sync_band=Mock(),
                        width=lambda: 800, height=lambda: 600)
                    point = SimpleNamespace(x=lambda: 430.0, y=lambda: 320.0)
                    event = SimpleNamespace(position=lambda: point, accept=Mock(),
                                            angleDelta=lambda: SimpleNamespace(y=lambda: 120))
                    camera_before = self.camera_state(viewer._camera)
                    if operation == 'zoom':
                        MouseMixin.wheelEvent(viewer, event)
                    else:
                        button = Qt.LeftButton if operation == 'box' else Qt.MiddleButton
                        modifiers = Qt.ControlModifier if operation == 'pan' else Qt.NoModifier
                        viewer._press = [button, 400.0, 300.0, 400.0, 300.0, True, modifiers]
                        if operation == 'box':
                            viewer._band = [400.0, 300.0, 410.0, 310.0]
                        MouseMixin.mouseMoveEvent(viewer, event)
                    if operation == 'box':
                        self.assertEqual(self.camera_state(viewer._camera), camera_before)
                        self.assertEqual(viewer._band, [400.0, 300.0, 430.0, 320.0])
                        viewer._sync_band.assert_called_once_with()
                    else:
                        self.assertNotEqual(self.camera_state(viewer._camera), camera_before)
                        viewer._redraw.assert_called_once_with()
                    self.assertEqual(viewer._display, display)
                    options = DisplayMixin._render_options(viewer)
                    self.assertEqual(options['style'], style)
                    self.assertTrue(options['moving'])
                    made = renderer()
                    self.assertEqual(render_calls(made, options),
                                     render_calls(made, {**options, 'moving': False}))

    @staticmethod
    def camera_state(camera):
        return camera.yaw, camera.pitch, camera.distance, tuple(camera.target)


if __name__ == '__main__':
    unittest.main()
