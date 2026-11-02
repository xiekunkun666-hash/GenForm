#pragma once

#include <QObject>
#include <memory>

namespace genform {
class Session;
}

namespace genform::api {

class ApiServer : public QObject {
    Q_OBJECT
public:
    explicit ApiServer(Session *session, quint16 port = 9631, QObject *parent = nullptr);
    ~ApiServer() override;
    quint16 port() const;
    void close();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}
