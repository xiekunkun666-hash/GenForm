"""Render and verify the assembled and exploded SKYE 2 projects in GenForm."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtQuickControls2 import QQuickStyle

from genform.app import AppController
from genform.session import Session
from genform.view.sheet import SheetView
from genform.view.viewport import Viewport


def main(output, inspect_only=False):
    output = output.resolve()
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    application = QGuiApplication([])
    QQuickStyle.setStyle('Basic')
    qmlRegisterType(Viewport, 'GenForm', 1, 0, 'Viewport')
    qmlRegisterType(SheetView, 'GenForm', 1, 0, 'SheetView')
    controller = AppController(Session())
    controller.sim._live['on'] = False
    engine = QQmlApplicationEngine()
    for name, value in [('app', controller), ('sim', controller.sim), ('drawing', controller.drawing), ('apiText', 'SKYE 2 reference')]:
        engine.rootContext().setContextProperty(name, value)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'qml' / 'Main.qml')))
    if not engine.rootObjects():
        raise RuntimeError('QML failed to load')
    window = engine.rootObjects()[0]
    controller.attach_window(window)
    viewport = window.findChild(Viewport, 'viewport')
    controller.attach_viewport(viewport)
    controller.drawing.attach(window.findChild(SheetView, 'sheetView'))
    frames = [('SKYE2_复现装配.gasm', 'iso', 'SKYE2_整机预览.png'),
              ('SKYE2_复现装配.gasm', 'front', 'SKYE2_侧视.png'),
              ('SKYE2_复现装配.gasm', 'top', 'SKYE2_俯视.png'),
              ('SKYE2_拆分查看.gasm', 'iso', 'SKYE2_拆分预览.png')]
    completed = (output / 'skye2_side_plug.gform').is_file()
    if completed:
        frames += [('SKYE2_复现装配.gasm', 'left', 'SKYE2_前口近景.png'),
                   ('SKYE2_复现装配.gasm', 'bottom', 'SKYE2_安装孔及接口.png'),
                   ('SKYE2_复现装配.gasm', 'front', 'SKYE2_侧圆口近景.png'),
                   ('SKYE2_复现装配.gasm', 'top', 'SKYE2_尾端孔近景.png'),
                   ('SKYE2_复现装配.gasm', 'front', 'SKYE2_孔道剖视.png')]
    if (output / 'SKYE2_拔塞查看.gasm').is_file():
        frames.append(('SKYE2_拔塞查看.gasm', 'iso', 'SKYE2_拔塞露孔.png'))
        frames.append(('SKYE2_拔塞查看.gasm', 'right', 'SKYE2_硅胶塞下开孔剖视.png'))
    state = {'index': 0, 'records': [], 'failure': None}

    def stop(error=None):
        state['failure'] = error
        controller.sim._live_timer.stop()
        window.close()
        application.quit()

    def guarded(action):
        try:
            action()
        except Exception as error:
            stop(str(error))

    def load():
        assembly, view, filename = frames[state['index']]
        path = output / assembly
        if Path(controller.sim.path) != path:
            controller.openDocument(str(path))
        controller.sim._live_timer.stop()
        expected = json.loads(path.read_text(encoding='utf-8'))['parts']
        if Path(controller.sim.path) != path or len(controller.sim._shown) != len(expected) or controller.sim._assembly['error']:
            raise RuntimeError(f'Assembly did not load: {path}; {controller.sim._assembly["error"]}')
        for actual, row in zip(controller.sim._parts, expected):
            if actual['move'] != row['move'] or actual['turn'] != row['turn']:
                raise RuntimeError('Assembly placement mismatch')
        viewport.snap_view(view)
        viewport.set_display(section=None, origin=False)
        if filename == 'SKYE2_前口近景.png':
            viewport._glide_to('left', ((-102, -6.4, 14.1), (-94.0, 5.9, 27)), instant=True)
        elif filename == 'SKYE2_侧圆口近景.png':
            viewport._glide_to('front', ((-21, -5.5, 7), (-5, -3.5, 20)), instant=True)
        elif filename == 'SKYE2_尾端孔近景.png':
            viewport._glide_to('top', ((-6, -3, 8), (0.1, 2.5, 16)), instant=True)
        elif filename == 'SKYE2_孔道剖视.png':
            viewport.set_display(section={'plane': 'XZ', 'offset': 0.25148874334, 'flip': False})
        elif filename == 'SKYE2_拔塞露孔.png':
            viewport._glide_to((-30, 22), ((-23, -23, 5), (-2, 4.8, 24)), instant=True)
        elif filename == 'SKYE2_硅胶塞下开孔剖视.png':
            viewport.set_display(section={'plane': 'YZ', 'offset': -12, 'flip': False})
            viewport._glide_to('right', ((-12.1, -24, 7), (-11.9, 6, 19)), instant=True)
        QTimer.singleShot(650, lambda: guarded(capture))

    def capture():
        assembly, view, filename = frames[state['index']]
        expected_count = len(json.loads((output / assembly).read_text(encoding='utf-8'))['parts'])
        if viewport._glide is not None or len(viewport._data['extras']) != expected_count:
            raise RuntimeError('Viewport not ready')
        image = window.grabWindow()
        if image.isNull():
            raise RuntimeError('Empty screenshot')
        if state['index'] == 0 and not image.save(str(output / 'SKYE2_GenForm界面.png')):
            raise RuntimeError('Screenshot save failed')
        screen = viewport.mapToScene(viewport.boundingRect().topLeft())
        scale = image.devicePixelRatio()
        preview = image.copy(round(screen.x() * scale), round(screen.y() * scale),
                             round(viewport.width() * scale), round(viewport.height() * scale))
        target = output / filename
        if not preview.save(str(target)):
            raise RuntimeError(f'Screenshot save failed: {target}')
        state['records'].append({'assembly': assembly, 'view': view, 'image': filename,
                                  'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                                  'parts': [{'name': part['name'], 'move': part['move'], 'turn': part['turn']}
                                            for part in controller.sim._parts]})
        print(f'Captured {filename}', flush=True)
        state['index'] += 1
        if state['index'] < len(frames):
            QTimer.singleShot(10, lambda: guarded(load))
        else:
            if len({record['sha256'] for record in state['records']}) != len(frames):
                raise RuntimeError('Repeated screenshots')
            (output / 'presentation.json').write_text(json.dumps(state['records'], ensure_ascii=False, indent=2), encoding='utf-8')
            stop()

    def inspect():
        controller.openDocument(str(output / 'SKYE2_复现装配.gasm'))
        controller.sim._live_timer.stop()
        controller.sim._live['running'] = False
        controller.runCheck()
        if controller._check['busy']:
            raise RuntimeError('Inspection did not finish')
        if controller._check['counts'].get('error', 0):
            raise RuntimeError('Inspection contains errors')
        viewport.snap_view('iso')

        def checked_image():
            if not window.grabWindow().save(str(output / 'SKYE2_设计检查界面.png')):
                raise RuntimeError('Inspection screenshot failed')
            print('INSPECTION_READY ' + json.dumps(controller._check['counts']), flush=True)

        QTimer.singleShot(1000, lambda: guarded(checked_image))

    QTimer.singleShot(300, lambda: guarded(inspect if inspect_only else load))
    if not inspect_only:
        QTimer.singleShot(180000, lambda: stop('Presentation timed out'))
    application.exec()
    if state['failure']:
        raise RuntimeError(state['failure'])
    if not inspect_only and len(state['records']) != len(frames):
        raise RuntimeError('Incomplete presentation')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--inspect', action='store_true')
    options = parser.parse_args()
    main(options.output, options.inspect)
