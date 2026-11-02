#pragma once

#include <QByteArray>
#include <QJsonObject>
#include <QString>

namespace genform {
class Session;
}

namespace genform::api {

inline constexpr quint16 DefaultPort = 9631;
inline constexpr double ReplyTimeout = 300.0;
inline constexpr qsizetype MaximumLineSize = 16 * 1024 * 1024;

quint16 configuredPort(quint16 fallback = DefaultPort);
QByteArray encode(const QJsonObject &object);
QJsonObject failure(const QString &message, const QString &code = {});
QJsonObject interrupted(const QString &reason, const QString &code, bool started);
QJsonObject execute(Session *session, const QJsonObject &request);

}
