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
    from PySide6.QtGui import QGuiApplication, QIcon, QSurfaceFormat
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

    if sys.platform == 'win32':
        # 任务栏上算一个独立的程序 (用自己的图标、自己一组), 不然会被归到 python 名下、显示 python 的图标
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('GenForm.GenForm')
        except (AttributeError, OSError):
            pass
    application = QGuiApplication(argv)
    application.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'genform.png')))
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
            controller.api_port = server.port
            api_text = f'AI 接口 127.0.0.1:{server.port}'
        except OSError:
            api_text = f'AI 接口没开起来（端口 {port} 被占用）'

    # 界面语言: QML 里的 qsTr("中文") 都来问这个翻译器, 它去查 i18n 的对照表; 换语言时让引擎把文字重新取一遍
    from PySide6.QtCore import QTranslator
    from . import i18n

    class Translator(QTranslator):
        def isEmpty(self):
            return False

        def translate(self, context, source, disambiguation=None, n=-1):
            return i18n.tr(source)

    translator = Translator(application)
    application.installTranslator(translator)

    from PySide6.QtQuickControls2 import QQuickStyle
    QQuickStyle.setStyle('Basic')       # 系统原生样式不让改控件外观 (输入框背景等)
    qmlRegisterType(Viewport, 'GenForm', 1, 0, 'Viewport')
    from .view.sheet import SheetView
    qmlRegisterType(SheetView, 'GenForm', 1, 0, 'SheetView')
    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    context.setContextProperty('app', controller)
    context.setContextProperty('sim', controller.sim)
    context.setContextProperty('drawing', controller.drawing)
    context.setContextProperty('apiText', api_text)
    qml_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'qml')
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, 'Main.qml')))
    if not engine.rootObjects():
        builder.close()
        return 1
    controller.languageChanged.connect(engine.retranslate)
    window = engine.rootObjects()[0]
    controller.attach_window(window)
    controller.attach_viewport(window.findChild(Viewport, 'viewport'))
    controller.drawing.attach(window.findChild(SheetView, 'sheetView'))

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
