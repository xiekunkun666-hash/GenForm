#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QString>
#include <QStringList>
#include <QVector>
#include <optional>
#include <stdexcept>

namespace genform {

class Error : public std::runtime_error {
public:
    explicit Error(const QString &message) : std::runtime_error(message.toUtf8().constData()) {}
};

class Document {
public:
    QJsonArray features;
    std::optional<int> upto;
    QJsonObject props;
    QString path;
    bool dirty = false;
    quint64 revision = 0;

    QJsonObject find(const QString &identifier) const;
    int index(const QString &identifier) const;
    QString last(const QString &kind) const;
    QString add(const QString &kind, const QJsonObject &params, const QString &name = {});
    void edit(const QString &identifier, const QJsonObject &params);
    void rename(const QString &identifier, const QString &name);
    void setFolder(const QStringList &identifiers, const QString &folder);
    void setProcesses(const QJsonObject &bound);
    void suppress(const QString &identifier, bool suppressed = true);
    void remove(const QString &identifier);
    void rollback(std::optional<int> count);
    void setProp(const QString &key, const QJsonValue &value);
    bool canUndo() const;
    bool canRedo() const;
    void undo();
    void redo();
    QJsonObject toData() const;
    void loadData(const QJsonObject &data);
    void save(const QString &filePath = {});
    void open(const QString &filePath);
    void clear();

private:
    struct Snapshot { QJsonArray features; std::optional<int> upto; };
    int serial_ = 0;
    QVector<Snapshot> undo_;
    QVector<Snapshot> redo_;
    void checkpoint();
    void changed();
};

}
