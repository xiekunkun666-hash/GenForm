#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QString>
#include <memory>
#include <optional>

namespace genform::assembly {

class Engine {
public:
    Engine();
    ~Engine();
    Engine(const Engine &) = delete;
    Engine &operator=(const Engine &) = delete;
    void setDocument(const QJsonArray &features, std::optional<int> upto = {},
                     const QJsonObject &props = {}, const QString &path = {});
    QJsonObject load(const QString &path);
    QJsonObject setAssembly(const QJsonObject &data, const QString &baseDirectory = {});
    QJsonObject assembly() const;
    QJsonObject query(const QString &what, const QJsonObject &args = {});
    void clearCache();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

QJsonObject resolveAssembly(const QJsonObject &data, const QString &baseDirectory = {});
QJsonObject pose(const QJsonArray &parts, const QJsonArray &joints,
                 std::optional<double> seconds = {});
QJsonObject motionSamples(const QJsonArray &parts, const QJsonArray &joints, int samples = 8);

}
