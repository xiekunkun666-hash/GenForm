#include "genform/api/server.hpp"
#include "genform/api/wire.hpp"
#include "genform/session.hpp"
#include <QHash>
#include <QHostAddress>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QPointer>
#include <QSet>
#include <QTcpServer>
#include <QTcpSocket>
#include <QThread>
#include <QTimer>
#include <QUuid>
#include <atomic>
#include <chrono>
#include <cmath>
#include <stdexcept>

namespace genform::api {
namespace {

using Clock = std::chrono::steady_clock;

struct Request {
    QString identifier;
    QPointer<QTcpSocket> socket;
    Clock::time_point deadline;
    std::atomic_bool finished{false};
    std::atomic_bool started{false};
};

class Listener : public QObject {
public:
    explicit Listener(Session *session) : session_(session) {}

    QString start(quint16 port)
    {
        server_ = new QTcpServer(this);
        connect(server_, &QTcpServer::newConnection, this, [this] {
            while (server_->hasPendingConnections()) {
                auto socket = server_->nextPendingConnection();
                buffers_.insert(socket, {});
                connect(socket, &QTcpSocket::readyRead, this, [this, socket] { receive(socket); });
                connect(socket, &QTcpSocket::disconnected, this, [this, socket] {
                    const auto pending = pending_.values();
                    for (const auto &request : pending) {
                        if (request->socket == socket)
                            finish(request, interrupted(QStringLiteral("调用方已断开连接"), "cancelled", request->started));
                    }
                    buffers_.remove(socket);
                    busy_.remove(socket);
                    socket->deleteLater();
                });
                receive(socket);
            }
        });
        if (!server_->listen(QHostAddress::LocalHost, port))
            return server_->errorString();
        port_ = server_->serverPort();
        auto timer = new QTimer(this);
        timer->setInterval(20);
        connect(timer, &QTimer::timeout, this, [this] {
            const auto pending = pending_.values();
            for (const auto &request : pending) {
                if (Clock::now() >= request->deadline)
                    finish(request, interrupted(QStringLiteral("请求超过时限，无法保证正在执行的计算已经停止"),
                                                "timeout", request->started));
            }
        });
        timer->start();
        return {};
    }

    quint16 port() const { return port_; }

    void close()
    {
        closing_ = true;
        if (server_)
            server_->close();
        const auto pending = pending_.values();
        for (const auto &request : pending)
            finish(request, interrupted(QStringLiteral("GenForm 接口正在关闭"), "cancelled", request->started));
        const auto sockets = buffers_.keys();
        for (auto socket : sockets)
            socket->disconnectFromHost();
        port_ = 0;
    }

private:
    void send(QTcpSocket *socket, const QJsonObject &result)
    {
        if (socket && socket->state() == QAbstractSocket::ConnectedState) {
            socket->write(encode(result) + '\n');
            socket->flush();
        }
    }

    void finish(const std::shared_ptr<Request> &request, const QJsonObject &result)
    {
        if (request->finished.exchange(true))
            return;
        pending_.remove(request->identifier);
        if (auto socket = request->socket.data()) {
            send(socket, result);
            busy_.remove(socket);
            QTimer::singleShot(0, this, [this, weak = request->socket] {
                if (weak && !closing_)
                    receive(weak);
            });
        }
    }

    void receive(QTcpSocket *socket)
    {
        if (closing_ || !buffers_.contains(socket))
            return;
        auto &buffer = buffers_[socket];
        buffer += socket->readAll();
        if (buffer.size() > MaximumLineSize) {
            send(socket, failure(QStringLiteral("请求行过大"), "invalid_request"));
            socket->disconnectFromHost();
            return;
        }
        while (!busy_.contains(socket)) {
            const auto newline = buffer.indexOf('\n');
            if (newline < 0)
                break;
            const auto line = buffer.left(newline).trimmed();
            buffer.remove(0, newline + 1);
            if (line.isEmpty())
                continue;
            QJsonParseError error;
            const auto document = QJsonDocument::fromJson(line, &error);
            if (error.error != QJsonParseError::NoError || !document.isObject()) {
                send(socket, failure(QStringLiteral("请求格式错误: 需要 JSON 对象"), "invalid_request"));
                continue;
            }
            const auto payload = document.object();
            if (payload.value("cmd") == "cancel_request") {
                const auto request = pending_.value(payload.value("request_id").toString());
                if (request)
                    finish(request, interrupted(QStringLiteral("调用方已取消请求"), "cancelled", request->started));
                send(socket, {{"ok", true}, {"found", bool(request)}});
                continue;
            }
            if (!payload.value("cmd").isString() || payload.value("cmd").toString().isEmpty()
                || (payload.contains("args") && !payload.value("args").isNull() && !payload.value("args").isObject())
                || (payload.contains("request_id") && !payload.value("request_id").isString())) {
                send(socket, failure(QStringLiteral("cmd/request_id 必须是字符串，args 必须是对象"), "invalid_request"));
                continue;
            }
            bool validTimeout = true;
            double timeout = ReplyTimeout;
            if (payload.contains("timeout_s")) {
                const auto value = payload.value("timeout_s");
                if (value.isString())
                    timeout = value.toString().toDouble(&validTimeout);
                else if (value.isDouble())
                    timeout = value.toDouble();
                else
                    validTimeout = false;
            }
            if (!validTimeout || !std::isfinite(timeout) || timeout <= 0 || timeout > ReplyTimeout) {
                send(socket, failure(QStringLiteral("timeout_s 必须大于 0 且不超过 300 秒"), "invalid_request"));
                continue;
            }
            const auto identifier = payload.contains("request_id") ? payload.value("request_id").toString()
                : QUuid::createUuid().toString(QUuid::WithoutBraces);
            if (pending_.contains(identifier)) {
                send(socket, failure(QStringLiteral("request_id 正在执行，不可重复提交"), "invalid_request"));
                continue;
            }
            auto request = std::make_shared<Request>();
            request->identifier = identifier;
            request->socket = socket;
            request->deadline = Clock::now() + std::chrono::milliseconds(qMax<qint64>(1, qint64(timeout * 1000)));
            pending_.insert(identifier, request);
            busy_.insert(socket);
            if (!session_) {
                finish(request, failure(QStringLiteral("GenForm 会话已关闭"), "closed"));
                return;
            }
            QPointer<Listener> self(this);
            QPointer<Session> session(session_);
            QMetaObject::invokeMethod(session_, [self, session, request, payload] {
                if (request->finished.load())
                    return;
                request->started = true;
                const auto answer = Clock::now() >= request->deadline
                    ? interrupted(QStringLiteral("请求超过时限"), "timeout", false) : execute(session, payload);
                if (self)
                    QMetaObject::invokeMethod(self, [self, request, answer] {
                        if (self) {
                            const auto result = Clock::now() >= request->deadline
                                ? interrupted(QStringLiteral("请求超过时限，计算可能已经完成"), "timeout", request->started) : answer;
                            self->finish(request, result);
                        }
                    }, Qt::QueuedConnection);
            }, Qt::QueuedConnection);
        }
    }

    QPointer<Session> session_;
    QTcpServer *server_ = nullptr;
    quint16 port_ = 0;
    bool closing_ = false;
    QHash<QTcpSocket *, QByteArray> buffers_;
    QSet<QTcpSocket *> busy_;
    QHash<QString, std::shared_ptr<Request>> pending_;
};

}

struct ApiServer::Impl {
    QThread thread;
    Listener *listener = nullptr;
    quint16 port = 0;
};

ApiServer::ApiServer(Session *session, quint16 port, QObject *parent)
    : QObject(parent), impl_(std::make_unique<Impl>())
{
    if (!session)
        throw std::invalid_argument("ApiServer requires a Session");
    port = port == 0 ? 0 : configuredPort(port);
    if (!port)
        return;
    impl_->listener = new Listener(session);
    impl_->listener->moveToThread(&impl_->thread);
    connect(&impl_->thread, &QThread::finished, impl_->listener, &QObject::deleteLater);
    impl_->thread.start();
    QString error;
    QMetaObject::invokeMethod(impl_->listener, [&] {
        error = impl_->listener->start(port);
        impl_->port = impl_->listener->port();
    }, Qt::BlockingQueuedConnection);
    if (!error.isEmpty()) {
        close();
        throw std::runtime_error(QStringLiteral("Cannot listen on 127.0.0.1:%1: %2").arg(port).arg(error).toStdString());
    }
}

ApiServer::~ApiServer() { close(); }

quint16 ApiServer::port() const { return impl_->port; }

void ApiServer::close()
{
    if (impl_->thread.isRunning()) {
        QMetaObject::invokeMethod(impl_->listener, [this] { impl_->listener->close(); }, Qt::BlockingQueuedConnection);
        impl_->thread.quit();
        impl_->thread.wait();
        impl_->listener = nullptr;
    }
    impl_->port = 0;
}

}
