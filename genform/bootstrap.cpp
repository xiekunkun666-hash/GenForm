#include "genform/bootstrap.hpp"
#include "genform/api/server.hpp"
#include "genform/api/wire.hpp"
#include "genform/controller/controller.hpp"
#include "genform/platform/window_frame.hpp"
#include "genform/view/viewport.hpp"
#include "genform/view/sheet.hpp"
#include <QApplication>
#include <QDir>
#include <QFileInfo>
#include <QIcon>
#include <QMessageBox>
#include <QQmlApplicationEngine>
#include <QQmlAbstractUrlInterceptor>
#include <QQmlContext>
#include <QQmlExpression>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QTimer>
#include <QJsonDocument>
#include <QTextStream>
#include <QTemporaryDir>
#include <QUrl>

namespace genform {
namespace {
class AssetInterceptor final : public QQmlAbstractUrlInterceptor {
public:
    QUrl intercept(const QUrl &url,DataType type) override {
        if (type!=UrlString || !url.path().contains("/genform/assets/")) return url;
        const auto path=controller::assetPath(QFileInfo(url.path()).fileName());
        if (path.isEmpty()) return url;
        return path.startsWith(':')?QUrl("qrc"+path):QUrl::fromLocalFile(path);
    }
};
}
int run(int argc,char **argv) {
    QApplication application(argc,argv);
    const bool smoke=application.arguments().contains("--gui-smoke-test");
    QTemporaryDir smokeSettings;
    if (smoke) { if (!smokeSettings.isValid()) return 2; qputenv("GENFORM_SETTINGS",smokeSettings.filePath("settings.json").toUtf8()); }
    application.setApplicationName(QStringLiteral("GenForm"));
    application.setOrganizationName(QStringLiteral("GenForm"));
    QQuickStyle::setStyle(QStringLiteral("Basic"));
    const QString source=QString::fromUtf8(GENFORM_SOURCE_DIR);
    QString qmlDirectory;
    const QStringList candidates{qEnvironmentVariable("GENFORM_QML_DIR"),QStringLiteral(":/genform/qml"),QStringLiteral(":/qml"),QCoreApplication::applicationDirPath()+"/qml",
        QCoreApplication::applicationDirPath()+"/../share/genform/qml",source+"/qml"};
    for (const auto &candidate : candidates) if (!candidate.isEmpty() && QFileInfo::exists(candidate+"/Main.qml")) { qmlDirectory=candidate.startsWith(':')?candidate:QDir(candidate).absolutePath(); break; }
    if (qmlDirectory.isEmpty()) { QMessageBox::critical(nullptr,QStringLiteral("GenForm"),QStringLiteral("找不到 qml/Main.qml，请设置 GENFORM_QML_DIR。")); return 1; }
    application.setWindowIcon(QIcon(controller::assetPath("genform.png")));
    Session session;
    controller::AppController controller(&session);
    std::unique_ptr<api::ApiServer> server;
    QString apiText=QStringLiteral("AI 接口未启动");
    try {
        const auto port=smoke?quint16(0):api::configuredPort();
        if (port) { server=std::make_unique<api::ApiServer>(&session,port); controller.setApiPort(server->port()); apiText=QStringLiteral("AI 接口 127.0.0.1:%1").arg(server->port()); }
    } catch (const std::exception &exception) { apiText=QStringLiteral("AI 接口启动失败：%1").arg(QString::fromUtf8(exception.what())); }
    qmlRegisterType<view::Viewport>("GenForm",1,0,"Viewport");
    qmlRegisterType<view::SheetView>("GenForm",1,0,"SheetView");
    AssetInterceptor assets;
    QQmlApplicationEngine engine;
    engine.addUrlInterceptor(&assets);
    QStringList warnings;
    QObject::connect(&engine,&QQmlApplicationEngine::warnings,&application,[&warnings](const QList<QQmlError> &errors) { for (const auto &error : errors) warnings.append(error.toString()); });
    engine.rootContext()->setContextProperty("app",&controller);
    engine.rootContext()->setContextProperty("sim",controller.simulation());
    engine.rootContext()->setContextProperty("drawing",controller.drawing());
    engine.rootContext()->setContextProperty("apiText",apiText);
    QObject::connect(&controller,&controller::AppController::languageChanged,&engine,&QQmlApplicationEngine::retranslate);
    engine.load(qmlDirectory.startsWith(':')?QUrl("qrc"+qmlDirectory+"/Main.qml"):QUrl::fromLocalFile(qmlDirectory+"/Main.qml"));
    if (engine.rootObjects().isEmpty()) return 1;
    auto *root=engine.rootObjects().front();
    auto *window=qobject_cast<QWindow *>(root);
    auto *viewport=root->findChild<view::Viewport *>(QStringLiteral("viewport"));
    auto *sheet=root->findChild<view::SheetView *>(QStringLiteral("sheetView"));
    controller.attach(window,viewport,sheet);
    platform::enableNativeWindowFrame(window);
    QQmlExpression themeExpression(QQmlEngine::contextForObject(root),root,QStringLiteral("Theme"));
    const auto theme=themeExpression.evaluate(); controller.attachTheme(qvariant_cast<QObject *>(theme));
    if (smoke) {
        QTimer::singleShot(300,&application,[&] {
            auto result=controller.smokeTest(viewport);
            QTimer::singleShot(100,&application,[&,result]() mutable {
                result["qmlWarnings"]=QJsonArray::fromStringList(warnings);
                if (!warnings.isEmpty()) { result["ok"]=false; if (!result.contains("error")) result["error"]=QStringLiteral("原 QML 界面存在运行警告。 "); }
                QTextStream(stdout)<<QJsonDocument(result).toJson(QJsonDocument::Compact)<<Qt::endl; application.exit(result.value("ok").toBool()?0:2);
            });
        });
        return application.exec();
    }
    if (application.arguments().size()>1) {
        const auto path=application.arguments().at(1);
        if (QFileInfo(path).isFile()) QTimer::singleShot(0,&controller,[&controller,path] { controller.openDocument(path); });
    }
    return application.exec();
}
}
