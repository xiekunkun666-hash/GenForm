#pragma once

#include "genform/session.hpp"
#include <QDir>
#include <QJsonArray>
#include <QJsonObject>
#include <QStringList>
#include <functional>

namespace examples {

QJsonObject loadObject(const QString &path);
void saveObject(const QString &path, const QJsonObject &value);
QString sha256(const QString &path);
void require(bool condition, const QString &message);
QJsonObject call(genform::Session &session, const QString &command, const QJsonObject &arguments = {});
QJsonObject ui(const QString &slot, const QJsonArray &arguments = {}, quint16 port = 9631);
QJsonObject rpc(const QString &command, const QJsonObject &arguments = {}, quint16 port = 9631);
QJsonObject configuration(double angle);
QString sourceRoot();

struct Options {
    QString name;
    QStringList positional;
    QJsonObject values;
    QString output;
    bool force = false;
};

int run(const Options &options);
int audit();
int selfTest();
int verify(const Options &options);
int skye(const Options &options);
int alternate(const Options &options);

}
