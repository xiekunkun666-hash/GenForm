#pragma once

#include <QObject>
#include <cstdio>
#include <memory>

namespace genform {
class Session;
}

namespace genform::api {

class StdioRuntime : public QObject {
    Q_OBJECT
public:
    explicit StdioRuntime(Session *session, quint16 port, FILE *output, QObject *parent = nullptr);
    ~StdioRuntime() override;
    void submit(const QByteArray &line);
    void close();

signals:
    void finished();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}
