#pragma once
#include <QJsonArray>
#include <QJsonObject>
#include <QString>
#include <QStringList>

namespace genform::features {
QJsonObject specs();
QJsonObject spec(const QString &kind);
QJsonObject defaultParams(const QString &kind);
QJsonValue clean(const QJsonObject &field, const QJsonValue &value);
QJsonArray catalog();
QString title(const QString &kind);
QStringList curveKinds();
QStringList toolKinds();
QJsonObject planeFrame(const QJsonValue &reference, const QJsonArray &features, double offset = 0, int depth = 0);
QJsonObject axisOf(const QString &reference, const QJsonArray &features, const QJsonObject &sketchFrame = {});
QJsonObject csysAxes(const QJsonObject &params);
}
