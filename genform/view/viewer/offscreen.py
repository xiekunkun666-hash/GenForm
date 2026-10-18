"""后台截图：GUI 线程取快照，独立子进程创建 surface 和不共享的 GL 上下文。"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
import threading
import time

from OpenGL import contextdata
from PySide6.QtCore import QIODevice, QObject, QSaveFile, QSize, QThread, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
import shiboken6

from ...document import DocumentError
from ..scene import Scene

MAX_PIXELS = 16777216
PREPARE_SECONDS = 0.25
_active = None


@dataclass(frozen=True)
class Snapshot:
    width: int
    height: int
    data: dict
    frame: tuple


def surface_format():
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.OpenGL)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    return fmt


def snapshot(viewport):
    window = viewport.window()
    ratio = float(window.devicePixelRatio()) if window is not None else 1.0
    width, height = round(viewport.width() * ratio), round(viewport.height() * ratio)
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise DocumentError('离屏截图尺寸无效或超过像素上限')
    data = {name: viewport._data[name] for name in ('geometry', 'states', 'planes', 'drawing', 'extras')}
    data['geometry'], data['states'] = dict(data['geometry']), dict(data['states'])
    data['extras'] = [dict(part) for part in data['extras']]
    camera = viewport._camera.copy()
    frame = (camera.matrix(width, height), tuple(camera.eye()), viewport._gl_dark(), viewport._grid_matrix(),
             dict(viewport._render_options()))
    return Snapshot(width, height, data, frame)


def render_image(state, surface, check):
    """只创建自己的上下文；退出时销毁整个非共享资源组，并恢复本线程先前的上下文。"""
    previous = QOpenGLContext.currentContext()
    previous_surface = previous.surface() if previous is not None else None
    context, target, current, native_context = None, None, False, None
    try:
        check()
        context = QOpenGLContext()
        context.setFormat(surface.format())
        if not context.create():
            raise RuntimeError('无法创建离屏 OpenGL 上下文')
        if not context.makeCurrent(surface):
            raise RuntimeError('无法启用离屏 OpenGL 上下文')
        current = True
        native_context = contextdata.getContext()
        check()
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        fmt.setSamples(8)
        target = QOpenGLFramebufferObject(QSize(state.width, state.height), fmt)
        if not target.isValid() or not target.bind():
            raise RuntimeError('无法创建或绑定离屏帧缓冲')
        scene = Scene()
        for name in ('geometry', 'states', 'planes', 'drawing', 'extras'):
            check()
            setter, value = getattr(scene, 'set_' + name), state.data[name]
            setter(*value) if name in ('planes', 'drawing') else setter(value)
        check()
        scene.render(state.width, state.height, *state.frame)
        check()
        image = target.toImage()
        if image.isNull():
            raise RuntimeError('离屏帧缓冲没有返回图像')
        check()
        return image
    finally:
        failure = sys.exc_info()[1]
        errors = []

        def cleanup(action):
            try:
                action()
            except Exception as error:
                errors.append(str(error))

        if target is not None:
            cleanup(target.release)
            cleanup(lambda: shiboken6.delete(target))
        if context is not None:
            if current:
                cleanup(context.doneCurrent)
            cleanup(lambda: shiboken6.delete(context))
            if native_context is not None:
                cleanup(lambda: contextdata.cleanupContext(native_context))
        if previous is not None:
            try:
                if not previous.makeCurrent(previous_surface):
                    raise RuntimeError('无法恢复先前的 OpenGL 上下文')
            except Exception as error:
                errors.append(str(error))
        if errors:
            message = '离屏 GL 清理失败: ' + '；'.join(errors)
            if failure is None:
                raise RuntimeError(message)
            failure.add_note(message)


def save_png(image, path, check):
    output = QSaveFile(path)
    committed = False
    try:
        check()
        if not output.open(QIODevice.WriteOnly):
            raise OSError(output.errorString())
        if not image.save(output, 'PNG'):
            raise OSError('离屏截图 PNG 编码失败')
        check()
        if not output.commit():
            raise OSError(output.errorString())
        committed = True
    finally:
        if not committed:
            output.cancelWriting()


class _Job(QObject):
    completed = Signal(str)

    def __init__(self, state, request, legacy):
        super().__init__()
        self.state, self.request, self.legacy = state, request, legacy
        self.completed.connect(self._complete, Qt.QueuedConnection)
        self.worker = None
        self.prepared = None
        self.disposed = False
        QGuiApplication.instance().aboutToQuit.connect(self._shutdown)

    def run(self):
        stopped, deadline, path = self.request.stopped, self.request.deadline, self.request.path

        def check():
            if stopped.is_set() or time.monotonic() >= deadline:
                raise TimeoutError('离屏截图已取消或超时')

        error = ''
        try:
            self.prepared = run_process(self.state, path, deadline, stopped, check)
        except Exception as failure:
            error = f'离屏截图失败: {type(failure).__name__}: {failure}'
        self.completed.emit(error)

    @Slot(str)
    def _complete(self, error):
        global _active
        if self.disposed:
            return
        self.disposed = True
        QGuiApplication.instance().aboutToQuit.disconnect(self._shutdown)
        if _active is self:
            _active = None
        try:
            if self.prepared is not None and not error and not self.request.cancelled:
                if time.monotonic() >= self.request.deadline:
                    raise TimeoutError('离屏截图已超时，未发布文件')
                os.replace(self.prepared, self.request.path)
                self.prepared = None
        except Exception as failure:
            error = f'离屏截图保存失败: {type(failure).__name__}: {failure}'
        finally:
            if self.prepared is not None:
                Path(self.prepared).unlink(missing_ok=True)
                self.prepared = None
        try:
            if self.request.finish(not error, error):
                self.legacy(self.request.path if not error else '')
        except RuntimeError:
            pass
        finally:
            self.deleteLater()

    @Slot()
    def _shutdown(self):
        self.request.cancel()
        if self.worker is not None:
            self.worker.join(PREPARE_SECONDS)
            if not self.worker.is_alive():
                self._complete('离屏截图因退出取消')


def start_offscreen(viewport, request):
    global _active
    app = QGuiApplication.instance()
    if not isinstance(app, QGuiApplication) or QThread.currentThread() != app.thread():
        raise DocumentError('离屏截图必须在 GUI 线程提交')
    if _active is not None:
        raise DocumentError('上一张离屏截图仍在清理，请稍后重试')
    began = time.monotonic()
    state = snapshot(viewport)
    job = _Job(state, request, viewport.shotSaved.emit)
    try:
        if time.monotonic() - began > PREPARE_SECONDS or time.monotonic() >= request.deadline:
            raise TimeoutError('离屏截图准备超过同步时间限制')
        _active = job
        job.worker = threading.Thread(target=job.run, name='genform-screenshot', daemon=False)
        job.worker.start()
    except Exception:
        _active = None
        app.aboutToQuit.disconnect(job._shutdown)
        job.deleteLater()
        raise


def run_process(state, path, deadline, stopped, check):
    with tempfile.TemporaryDirectory(prefix='genform_shot_') as directory:
        source, target = Path(directory) / 'scene.pickle', Path(directory) / 'view.png'
        check()
        with source.open('wb') as stream:
            pickle.dump((state.width, state.height, state.data, state.frame), stream, pickle.HIGHEST_PROTOCOL)
        check()
        command = [sys.executable, '-B', '-m', 'genform.view.viewer.offscreen', str(source), str(target), str(deadline)]
        process = subprocess.Popen(command, cwd=str(Path(__file__).resolve().parents[3]),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while process.poll() is None:
                check()
                stopped.wait(0.02)
            output, error = process.communicate(timeout=1)
            if process.returncode:
                raise RuntimeError((output + error).decode('utf-8', errors='replace')[-2000:] or
                                   f'离屏进程退出码 {process.returncode}')
            check()
            descriptor, prepared = tempfile.mkstemp(prefix='.genform_shot_', suffix='.png', dir=str(Path(path).absolute().parent))
            try:
                with os.fdopen(descriptor, 'wb') as destination, target.open('rb') as stream:
                    while chunk := stream.read(1024 * 1024):
                        check()
                        destination.write(chunk)
                    destination.flush()
                    os.fsync(destination.fileno())
                check()
                return prepared
            except BaseException:
                Path(prepared).unlink(missing_ok=True)
                raise
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=1)


def _worker(source, target, deadline):
    app = QGuiApplication([])
    surface = QOffscreenSurface()
    surface.setFormat(surface_format())

    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError('离屏渲染超时')

    try:
        check()
        surface.create()
        if not surface.isValid():
            raise RuntimeError('无法创建离屏 OpenGL surface')
        with open(source, 'rb') as stream:
            state = Snapshot(*pickle.load(stream))
        image = render_image(state, surface, check)
        save_png(image, target, check)
        return 0
    except Exception as error:
        print(json.dumps({'error': f'{type(error).__name__}: {error}'}, ensure_ascii=True), flush=True)
        return 1
    finally:
        surface.destroy()


if __name__ == '__main__':
    raise SystemExit(_worker(sys.argv[1], sys.argv[2], float(sys.argv[3])))
