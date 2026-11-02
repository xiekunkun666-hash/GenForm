#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QString>
#include <functional>
#include <memory>
#include <optional>

namespace genform::kernel {

class Kernel {
public:
    using Progress = std::function<void(int, int, const QString &)>;
    Kernel();
    ~Kernel();
    Kernel(const Kernel &) = delete;
    Kernel &operator=(const Kernel &) = delete;
    QJsonObject build(const QJsonArray &features, std::optional<int> upto = {}, Progress progress = {});
    QJsonObject query(const QString &what, const QJsonObject &args = {});
    void exportFile(const QString &path);
    QJsonObject preview(const QJsonArray &features, std::optional<int> upto = {});
    static bool available();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}
