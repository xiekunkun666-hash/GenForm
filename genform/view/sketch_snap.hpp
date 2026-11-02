#pragma once

#include <QJsonArray>
#include <QSet>
#include <QString>
#include <QVector2D>

namespace genform::view {

struct SketchSnap {
    QVector2D point;
    QString kind;
};

double sketchGridStep(double pixelsPerUnit);
SketchSnap snapSketch(const QJsonArray &shapes,const QVector2D &point,double pixelsPerUnit,
    const QSet<QString> &enabled,const QString &only={},const QVector<int> &skip={},const QVector<QVector2D> &draft={});

}
