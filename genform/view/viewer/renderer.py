"""渲染线程这边: 把视图的数据同步进 Scene, 在帧缓冲上画, 顺手截图。"""
from __future__ import annotations

from PySide6.QtQuick import QQuickFramebufferObject


class _Renderer(QQuickFramebufferObject.Renderer):
    def __init__(self):
        super().__init__()
        from ..scene import Scene
        self._scene = Scene()
        self._pending = {}
        self._versions = {}
        self._frame = None
        self._shot = None
        self._item = None

    def createFramebufferObject(self, size):
        from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        fmt.setSamples(8)               # 边线细, 不开多重采样全是锯齿
        self._fbo = QOpenGLFramebufferObject(size, fmt)     # 留一个引用: 生命周期归 Qt 管, 但不能被 Python 先回收
        return self._fbo

    def synchronize(self, item):
        """界面线程此刻被挂起: 把这一帧要用的东西拷过来 (之后渲染线程不再碰控件)。"""
        self._item = item
        if item._shot_path is not None:
            self._shot, item._shot_path = item._shot_path, None
        try:
            for name in ('geometry', 'states', 'planes', 'drawing', 'extras'):
                version = item._versions[name]
                if self._versions.get(name) != version:
                    self._pending[name] = item._data[name]
                    self._versions[name] = version
            if 'geometry' in self._pending:
                self._pending['states'] = item._data['states']      # 几何换了, 状态数组长度也跟着变
            width, height = max(int(item.width()), 1), max(int(item.height()), 1)
            self._frame = (item._camera.matrix(width, height), tuple(item._camera.eye()), item._gl_dark(), item._grid_matrix(),
                           item._render_options())
        except Exception as error:
            self._frame = None
            self._finish_shot(error=f'截图同步失败: {type(error).__name__}: {error}')

    def _finish_shot(self, saved=False, error=''):
        shot, self._shot = self._shot, None
        if not shot or self._item is None:
            return
        try:
            if shot.finish(saved, error):
                self._item.shotSaved.emit(shot.path if saved else '')
        except RuntimeError:
            pass

    def render(self):
        from OpenGL.GL import glGetError, GL_NO_ERROR
        from PySide6.QtQuick import QQuickOpenGLUtils
        target = None
        saved, error = False, ''
        try:
            for _ in range(8):              # 清掉场景图留下的旧错误标志, 免得算到我们头上
                if glGetError() == GL_NO_ERROR:
                    break
            if self._frame is None:
                raise RuntimeError('三维视图还没准备好')
            target = self.framebufferObject()
            if target is None or not target.isValid() or target.width() <= 0 or target.height() <= 0:
                raise RuntimeError('三维视图帧缓冲还没准备好')
            for name in ('geometry', 'states', 'planes', 'drawing', 'extras'):
                if name not in self._pending:
                    continue
                value = self._pending[name]
                setter = getattr(self._scene, 'set_' + name)
                if name in ('planes', 'drawing'):
                    setter(*value)
                else:
                    setter(value)
                del self._pending[name]
            matrix, eye, dark, grid, options = self._frame
            self._scene.render(target.width(), target.height(), matrix, eye, dark, grid, options)
            if self._shot is not None and not self._shot.cancelled:
                image = target.toImage()
                if not self._shot.cancelled:
                    saved = bool(image.save(self._shot.path))
        except Exception as failure:
            error = f'截图渲染失败: {type(failure).__name__}: {failure}'
        finally:
            if target is not None:
                try:
                    if not target.bind():
                        raise RuntimeError('帧缓冲绑定失败')
                except Exception as failure:
                    saved, error = False, f'截图清理失败: {type(failure).__name__}: {failure}'
            try:
                QQuickOpenGLUtils.resetOpenGLState()
            except Exception as failure:
                saved, error = False, f'OpenGL 状态重置失败: {type(failure).__name__}: {failure}'
            self._finish_shot(saved, error)
