#include "genform/api/wire.hpp"
#include "genform/session.hpp"
#include <QCoreApplication>
#include <QJsonDocument>
#include <QMetaObject>
#include <stdexcept>

namespace genform::api {

quint16 configuredPort(quint16 fallback)
{
    if (!qEnvironmentVariableIsSet("GENFORM_PORT"))
        return fallback;
    bool valid = false;
    const int port = qEnvironmentVariable("GENFORM_PORT").toInt(&valid);
    if (!valid || port < 0 || port > 65535)
        throw std::invalid_argument("GENFORM_PORT must be an integer between 0 and 65535");
    return static_cast<quint16>(port);
}

QByteArray encode(const QJsonObject &object)
{
    return QJsonDocument(object).toJson(QJsonDocument::Compact);
}

QJsonObject failure(const QString &message, const QString &code)
{
    QJsonObject result{{"ok", false}, {"error", message}};
    if (!code.isEmpty())
        result.insert("code", code);
    return result;
}

QJsonObject interrupted(const QString &reason, const QString &code, bool started)
{
    auto result = failure(reason, code);
    result.insert("started", started);
    result.insert("hint", QStringLiteral("文档修改可能已经发生，请先检查模型，不要直接重发。"));
    return result;
}

QJsonObject execute(Session *session, const QJsonObject &request)
{
    try {
        const auto name = request.value("cmd").toString();
        if (name == "tools")
            return {{"ok", true}, {"tools", Session::tools()}};
        if (name == "ping")
            return {{"ok", true}, {"app", "GenForm"}, {"pid", QCoreApplication::applicationPid()}};
        if (!session)
            return failure(QStringLiteral("GenForm 会话已关闭"), "closed");
        if (name == "quit") {
            QMetaObject::invokeMethod(QCoreApplication::instance(), "quit", Qt::QueuedConnection);
            return {{"ok", true}};
        }
        if (name == "ui")
            return failure(QStringLiteral("原生接口不提供 Python 界面控制器槽访问"), "unsupported");
        return session->execute(name, request.value("args").toObject());
    } catch (const std::exception &error) {
        return failure(QStringLiteral("命令执行失败: %1").arg(QString::fromUtf8(error.what())));
    } catch (...) {
        return failure(QStringLiteral("命令执行失败: 未知异常"));
    }
}

}
