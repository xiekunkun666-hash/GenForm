# -*- coding: utf-8 -*-
"""启动装配: 建会话、内核进程、AI 接口、窗口, 把它们接到一起。

环境变量:
    GENFORM_PORT   AI 接口端口 (默认 9631); 设成 0 则不开接口
"""
from __future__ import annotations

import os
import sys


def run(argv):
    from PySide6.QtCore import QUrl, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication, QSurfaceFormat
    from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

    # 三维视图用 OpenGL 3.3 核心模式画; 界面的场景图也走 OpenGL, 两边共用一个上下文体系
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)

    def qt_message(mode, context, message):
        # Qt 自己的警告和致命错误默认进调试器输出, 看不见: 接到标准错误上, 出问题时日志里有原因
        if sys.stderr is not None:          # 用 pythonw (桌面快捷方式) 启动时没有标准错误
            sys.stderr.write(f'[Qt] {message}\n')
            sys.stderr.flush()
    qInstallMessageHandler(qt_message)

    application = QGuiApplication(argv)
    application.setApplicationName('GenForm')
    application.setOrganizationName('GenForm')

    from .api.wire import DEFAULT_PORT
    from .app import AppController
    from .kernel.client import ProcessBuilder
    from .session import Session
    from .view.viewport import Viewport

    builder = ProcessBuilder()
    session = Session(builder)
    controller = AppController(session)

    api_text = 'AI 接口未开启'
    server = None
    port = int(os.environ.get('GENFORM_PORT', DEFAULT_PORT))
    if port:
        from .api.server import ApiServer
        try:
            server = ApiServer(session, port)
            server.controller = controller
            api_text = f'AI 接口 127.0.0.1:{server.port}'
        except OSError:
            api_text = f'AI 接口没开起来（端口 {port} 被占用）'

    from PySide6.QtQuickControls2 import QQuickStyle
    QQuickStyle.setStyle('Basic')       # 系统原生样式不让改控件外观 (输入框背景等)
    qmlRegisterType(Viewport, 'GenForm', 1, 0, 'Viewport')
    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    context.setContextProperty('app', controller)
    context.setContextProperty('apiText', api_text)
    qml_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'qml')
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, 'Main.qml')))
    if not engine.rootObjects():
        builder.close()
        return 1
    window = engine.rootObjects()[0]
    controller.attach_window(window)
    controller.attach_viewport(window.findChild(Viewport, 'viewport'))

    if len(argv) > 1 and os.path.isfile(argv[1]):
        controller.openDocument(argv[1])

    code = application.exec()
    # 收尾保险: 窗口关了以后要是 8 秒还没退干净 (卡在某个销毁顺序上), 把各线程的调用栈写进日志并强制结束,
    # 不留一个看不见的进程占着文档和端口
    import faulthandler
    if sys.stderr is not None:
        faulthandler.dump_traceback_later(8, exit=True)
    else:
        import threading
        threading.Timer(8, lambda: os._exit(code)).start()
    if server is not None:
        server.close()
    session.close()
    return code
