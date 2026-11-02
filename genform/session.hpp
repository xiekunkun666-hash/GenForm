#pragma once

#include "genform/document.hpp"
#include "genform/kernel/kernel.hpp"
#include "genform/assembly/engine.hpp"
#include <QObject>
#include <functional>

namespace genform {

class Session : public QObject {
    Q_OBJECT
public:
    explicit Session(QObject *parent = nullptr);
    Document document;
    kernel::Kernel builder;
    QJsonObject model;
    QJsonObject selection;
    bool busy = false;
    std::function<QJsonObject(const QString &, const QJsonObject &)> viewCommand;
    QJsonObject execute(const QString &command, const QJsonObject &arguments = {});
    QJsonObject rebuild();
    QJsonObject state(const QString &identifier = {}) const;
    static QJsonArray tools();

signals:
    void changed();
    void progress(int index, int total, const QString &name);

private:
    assembly::Engine assembly_;
    quint64 modelRevision_ = static_cast<quint64>(-1);
    QJsonObject dispatch(const QString &command, QJsonObject arguments);
    QJsonObject query(const QString &what, QJsonObject arguments);
    QJsonObject afterChange(QJsonObject result) const;
};

}
