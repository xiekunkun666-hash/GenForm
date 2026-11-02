#pragma once

#include "engine.hpp"
#include "../kernel/native.hpp"
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QSet>
#include <array>
#include <cmath>
#include <vector>

namespace genform::assembly::detail {

using Vector = std::array<double, 3>;
using Matrix = std::array<std::array<double, 4>, 4>;
using kernel::native::fail;
using kernel::native::number;
double scalar(const QJsonValue &value, double fallback = 0);
Vector coordinates(const QJsonValue &value, Vector fallback = {0, 0, 0});
QJsonArray json(const Vector &value);
Matrix identity();
Matrix multiply(const Matrix &first, const Matrix &second);
Vector apply(const Matrix &matrix, const Vector &value, bool direction = false);
Matrix swingMatrix(const QJsonObject &swing, int depth = 0);
Matrix placement(const QJsonObject &part);
QJsonArray json(const Matrix &value);
QJsonObject readObject(const QString &path);
QString absolutePath(const QString &path, const QString &baseDirectory);
QMap<QString, double> parameterValues(const QJsonObject &params);
QJsonObject bom(const QJsonArray &parts, const QJsonArray &documents);
double density(const QString &material);

#ifdef GENFORM_HAS_OCCT
struct Part {
    QJsonObject definition;
    QJsonObject document;
    QJsonObject model;
    QJsonArray buildFeatures;
    TopoDS_Shape shape;
    Vector low{}, high{};
    QString key;
    bool exact = true;
};
void requireExact(const std::vector<Part> &parts);
void updateBounds(Part &part);
QJsonObject mesh(const Part &part);
QJsonObject interference(const std::vector<Part> &parts, const QJsonObject &args);
QJsonObject contacts(const std::vector<Part> &parts, const QJsonObject &args,
                     QMap<QString, QJsonObject> &cache);
QJsonObject measureParts(const std::vector<Part> &parts);
QJsonObject massProperties(const std::vector<Part> &parts);
QJsonObject sequence(const std::vector<Part> &parts, const QJsonObject &args);
QJsonObject stack(const std::vector<Part> &parts, const QJsonObject &args);
QJsonObject drawing(const Part &part, const QJsonObject &args);
QJsonObject drag(const std::vector<Part> &parts, const QJsonObject &args);
QJsonObject staticAnalysis(const Part &part, const QJsonObject &args);
QJsonObject fasteners(const std::vector<Part> &parts);
QJsonObject relationship(const Part &first, const Part &second, double tolerance, double clearance);
#endif

}
