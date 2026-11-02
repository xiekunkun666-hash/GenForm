#include "genform/api/mcp_runtime.hpp"
#include "genform/api/wire.hpp"
#include "genform/session.hpp"
#include <QFile>
#include <QHash>
#include <QHostAddress>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QPointer>
#include <QQueue>
#include <QTcpSocket>
#include <QTimer>
#include <QUuid>
#include <atomic>
#include <chrono>
#include <stdexcept>
#include <utility>

namespace genform::api {
namespace {

using Clock = std::chrono::steady_clock;

const QString Instructions = QStringLiteral(
    "GenForm 是参数化三维建模软件：零件由一串按顺序执行的特征组成，单位毫米，Z 朝上。"
    "基准面：XY = 上视，XZ = 前视，YZ = 右视。\n"
    "典型流程：sketch（在基准面上画封闭轮廓）→ extrude（拉伸成实体；op=cut 是切除）→ fillet / chamfer（修边）→ export（导出 STEP / STL）。"
    "除此之外还有旋转、扫描、放样、孔、抽壳、拔模、筋、镜像、各种阵列、基准面/轴/点、曲线等，全部在工具清单里，每个工具的说明和参数都写在它自己的描述里。\n"
    "要连着做很多步时用 batch：把一串命令一次发过来，全部做完才重算一次，比一条条发快得多（见它的说明，\"$1\" 引用前面步骤的结果）。\n"
    "要点：\n"
    "1. 每次修改都会返回最新的特征列表（id、类型、名称、状态，如 f1、f2；只有这次新建 / 改的特征带参数）和实体尺寸；"
    "后面的命令用这些 id 引用草图和特征。要看别的特征的参数用 get_model（特征多时写 id 只看一个）。\n"
    "2. 某个特征算失败时 ok=false 并写明原因；用 edit_feature 改参数重试，或 undo 撤销。不要在失败的基础上继续往后做。\n"
    "3. 引用边 / 面：先用 list_edges / list_faces 看它们的位置，再用返回的坐标点引用；常见情况也可以直接用选择器（\"|Z\" 平行于 Z 的边，\">Z\" 最高处的）。\n"
    "4. 不确定现在是什么样：get_model 看特征和尺寸，screenshot 看图（图片直接附在结果里；需要 GenForm 窗口开着）。\n"
    "5. 做完一步检查一步：比对返回的实体尺寸和体积是否符合预期，再做下一步。\n"
    "用户能在窗口里看到你做的每一步，也可能自己动手改；开始前先 get_model 看一下现状。");

QString keyFor(const QJsonValue &identifier)
{
    return QString::fromUtf8(QJsonDocument(QJsonArray{identifier}).toJson(QJsonDocument::Compact));
}

QJsonObject rpcError(const QJsonValue &identifier, int code, const QString &message, const QJsonObject &data = {})
{
    QJsonObject error{{"code", code}, {"message", message}};
    if (!data.isEmpty())
        error.insert("data", data);
    return {{"jsonrpc", "2.0"}, {"id", identifier}, {"error", error}};
}

struct Operation {
    QJsonObject message;
    QString key;
    QString transportId = QUuid::createUuid().toString(QUuid::WithoutBraces);
    Clock::time_point deadline = Clock::now() + std::chrono::seconds(290);
    std::atomic_bool finished{false};
    std::atomic_bool started{false};
    bool sent = false;
    bool listing = false;
};

}

struct StdioRuntime::Impl {
    StdioRuntime *owner;
    QPointer<Session> session;
    quint16 port;
    FILE *output;
    bool closed = false;
    QHash<QString, std::shared_ptr<Operation>> pending;
    QQueue<std::shared_ptr<Operation>> queue;
    std::shared_ptr<Operation> active;
    QTcpSocket *socket = nullptr;
    QByteArray buffer;

    Impl(StdioRuntime *runtime, Session *localSession, quint16 tcpPort, FILE *protocolOutput)
        : owner(runtime), session(localSession), port(tcpPort), output(protocolOutput) {}

    void write(const QJsonObject &message)
    {
        if (closed)
            return;
        const auto bytes = encode(message) + '\n';
        if (std::fwrite(bytes.constData(), 1, size_t(bytes.size()), output) != size_t(bytes.size())
            || std::fflush(output) != 0)
            owner->close();
    }

    void finish(const std::shared_ptr<Operation> &operation, const QJsonObject &message)
    {
        if (operation->finished.exchange(true))
            return;
        pending.remove(operation->key);
        if (active == operation)
            active.reset();
        write(message);
        QTimer::singleShot(0, owner, [this] { next(); });
    }

    void result(const std::shared_ptr<Operation> &operation, const QJsonObject &value)
    {
        finish(operation, {{"jsonrpc", "2.0"}, {"id", operation->message.value("id")}, {"result", value}});
    }

    void drop()
    {
        if (socket) {
            auto previous = socket;
            socket = nullptr;
            previous->disconnect(owner);
            previous->abort();
            previous->deleteLater();
        }
        buffer.clear();
    }

    void cancelRemote(const std::shared_ptr<Operation> &operation)
    {
        if (session || !operation->sent || !port)
            return;
        auto control = new QTcpSocket(owner);
        QObject::connect(control, &QTcpSocket::connected, owner, [control, operation] {
            control->write(encode({{"cmd", "cancel_request"}, {"request_id", operation->transportId}}) + '\n');
            control->disconnectFromHost();
        });
        QObject::connect(control, &QTcpSocket::disconnected, control, &QObject::deleteLater);
        QTimer::singleShot(1000, control, [control] { control->abort(); control->deleteLater(); });
        control->connectToHost(QHostAddress::LocalHost, port);
    }

    void cancel(const std::shared_ptr<Operation> &operation, const QString &reason, const QString &code)
    {
        if (operation->finished.load())
            return;
        if (active == operation) {
            cancelRemote(operation);
            drop();
        }
        const auto data = interrupted(reason, code, operation->started);
        finish(operation, rpcError(operation->message.value("id"), code == "cancelled" ? -32800 : -32000,
                                   reason, {{"code", code}, {"started", data.value("started")}, {"hint", data.value("hint")}}));
    }

    void answer(const std::shared_ptr<Operation> &operation, const QJsonObject &answer)
    {
        if (operation->finished.load())
            return;
        if (Clock::now() >= operation->deadline) {
            cancel(operation, QStringLiteral("请求超过总时限，计算可能已经完成"), "timeout");
            return;
        }
        if (operation->listing) {
            QJsonArray tools;
            const auto catalog = answer.value("ok").toBool() && answer.value("tools").isArray()
                ? answer.value("tools").toArray() : Session::tools();
            for (const auto &value : catalog) {
                const auto tool = value.toObject();
                tools.append(QJsonObject{{"name", tool.value("name")}, {"description", tool.value("description")},
                    {"inputSchema", tool.contains("input_schema") ? tool.value("input_schema") : tool.value("inputSchema")}});
            }
            result(operation, {{"tools", tools}});
            return;
        }
        if (answer.value("code") == "timeout" || answer.value("code") == "cancelled") {
            cancel(operation, answer.value("error").toString(), answer.value("code").toString());
            return;
        }
        QJsonArray content{QJsonObject{{"type", "text"}, {"text", QString::fromUtf8(encode(answer))}}};
        const auto params = operation->message.value("params").toObject();
        if (params.value("name") == "screenshot" && answer.value("ok").toBool() && answer.value("path").isString()) {
            QFile image(answer.value("path").toString());
            if (image.open(QIODevice::ReadOnly))
                content.append(QJsonObject{{"type", "image"}, {"data", QString::fromLatin1(image.readAll().toBase64())},
                                           {"mimeType", "image/png"}});
        }
        result(operation, {{"content", content}, {"isError", !answer.value("ok").toBool()}});
    }

    void connectionFailed()
    {
        auto operation = active;
        drop();
        if (operation)
            answer(operation, failure(QStringLiteral("连不上 GenForm（端口 %1）或等待结果时连接中断。命令可能已经执行；请先检查模型，不要直接重发修改命令。")
                                      .arg(port), "connection_error"));
    }

    void send()
    {
        if (!active || active->sent || !socket || socket->state() != QAbstractSocket::ConnectedState)
            return;
        const auto params = active->message.value("params").toObject();
        QJsonObject request{{"cmd", active->listing ? QStringLiteral("tools") : params.value("name").toString()},
                            {"args", params.value("arguments").toObject()}, {"request_id", active->transportId},
                            {"timeout_s", 285}};
        active->sent = true;
        active->started = true;
        if (socket->write(encode(request) + '\n') < 0)
            connectionFailed();
    }

    void exchange()
    {
        if (!port) {
            answer(active, failure(QStringLiteral("GENFORM_PORT/--port 为 0，桌面 TCP 接口已禁用"), "disabled"));
            return;
        }
        if (socket) {
            send();
            return;
        }
        socket = new QTcpSocket(owner);
        auto current = socket;
        QObject::connect(current, &QTcpSocket::connected, owner, [this, current] {
            if (socket == current)
                send();
        });
        QObject::connect(current, &QTcpSocket::readyRead, owner, [this, current] {
            if (socket != current)
                return;
            buffer += current->readAll();
            const auto newline = buffer.indexOf('\n');
            if (buffer.size() > MaximumLineSize * 4) {
                connectionFailed();
                return;
            }
            if (newline < 0)
                return;
            const auto line = buffer.left(newline);
            buffer.remove(0, newline + 1);
            QJsonParseError parseError;
            const auto document = QJsonDocument::fromJson(line, &parseError);
            if (!active || parseError.error != QJsonParseError::NoError || !document.isObject() || !buffer.isEmpty()) {
                connectionFailed();
                return;
            }
            auto operation = active;
            answer(operation, document.object());
        });
        QObject::connect(current, &QTcpSocket::errorOccurred, owner, [this, current] {
            if (socket == current)
                connectionFailed();
        });
        QObject::connect(current, &QTcpSocket::disconnected, owner, [this, current] {
            if (socket == current)
                connectionFailed();
        });
        QTimer::singleShot(3000, owner, [this, current] {
            if (socket == current && current->state() != QAbstractSocket::ConnectedState)
                connectionFailed();
        });
        current->connectToHost(QHostAddress::LocalHost, port);
    }

    void next()
    {
        if (closed || active)
            return;
        while (!queue.isEmpty()) {
            auto operation = queue.dequeue();
            if (operation->finished.load())
                continue;
            active = operation;
            if (Clock::now() >= operation->deadline) {
                cancel(operation, QStringLiteral("请求超过总时限"), "timeout");
                continue;
            }
            if (session) {
                if (operation->listing) {
                    answer(operation, {{"ok", true}, {"tools", Session::tools()}});
                } else {
                    QPointer<StdioRuntime> runtime(owner);
                    QPointer<Session> localSession(session);
                    QMetaObject::invokeMethod(session, [runtime, localSession, operation] {
                        if (operation->finished.load())
                            return;
                        if (Clock::now() >= operation->deadline) {
                            if (runtime)
                                QMetaObject::invokeMethod(runtime, [runtime, operation] {
                                    if (runtime)
                                        runtime->impl_->cancel(operation, QStringLiteral("请求超过总时限"), "timeout");
                                }, Qt::QueuedConnection);
                            return;
                        }
                        operation->started = true;
                        const auto params = operation->message.value("params").toObject();
                        const auto value = execute(localSession, {{"cmd", params.value("name")}, {"args", params.value("arguments")}});
                        if (runtime)
                            QMetaObject::invokeMethod(runtime, [runtime, operation, value] {
                                if (runtime)
                                    runtime->impl_->answer(operation, value);
                            }, Qt::QueuedConnection);
                    }, Qt::QueuedConnection);
                }
            } else {
                exchange();
            }
            return;
        }
    }

    void submit(const QByteArray &line)
    {
        if (closed || line.trimmed().isEmpty())
            return;
        if (line.size() > MaximumLineSize) {
            write(rpcError(QJsonValue::Null, -32600, QStringLiteral("请求行过大")));
            return;
        }
        QJsonParseError parseError;
        const auto document = QJsonDocument::fromJson(line, &parseError);
        if (parseError.error != QJsonParseError::NoError) {
            write(rpcError(QJsonValue::Null, -32700, QStringLiteral("JSON 解析失败")));
            return;
        }
        if (!document.isObject()) {
            write(rpcError(QJsonValue::Null, -32600, QStringLiteral("JSON-RPC 请求必须是对象")));
            return;
        }
        const auto message = document.object();
        const auto identifier = message.value("id");
        if (message.value("jsonrpc") != "2.0" || !message.value("method").isString()
            || (message.contains("id") && !identifier.isString() && !identifier.isDouble() && !identifier.isNull())) {
            write(rpcError(QJsonValue::Null, -32600, QStringLiteral("无效的 JSON-RPC 请求")));
            return;
        }
        const auto method = message.value("method").toString();
        if (method == "notifications/cancelled" || method == "notifications/cancel") {
            const auto requestId = message.value("params").toObject().value("requestId");
            auto operation = pending.value(keyFor(requestId));
            if (operation)
                cancel(operation, QStringLiteral("调用方已取消请求"), "cancelled");
            return;
        }
        if (!message.contains("id"))
            return;
        const auto key = keyFor(identifier);
        if (pending.contains(key)) {
            write(rpcError(identifier, -32600, QStringLiteral("请求 id 正在执行，不可重复提交")));
            return;
        }
        auto operation = std::make_shared<Operation>();
        operation->message = message;
        operation->key = key;
        pending.insert(key, operation);
        if (message.contains("params") && !message.value("params").isObject()) {
            finish(operation, rpcError(identifier, -32602, QStringLiteral("params 必须是对象")));
        } else if (method == "initialize") {
            result(operation, {{"protocolVersion", "2024-11-05"}, {"capabilities", QJsonObject{{"tools", QJsonObject{}}}},
                               {"serverInfo", QJsonObject{{"name", "genform"}, {"version", "0.2.0"}}}, {"instructions", Instructions}});
        } else if (method == "ping") {
            result(operation, {});
        } else if (method == "tools/list" || method == "tools/call") {
            const auto params = message.value("params").toObject();
            if (method == "tools/call" && (!params.value("name").isString() || params.value("name").toString().isEmpty()
                || (params.contains("arguments") && !params.value("arguments").isObject()))) {
                finish(operation, rpcError(identifier, -32602, QStringLiteral("name 必须是字符串，arguments 必须是对象")));
                return;
            }
            operation->listing = method == "tools/list";
            queue.enqueue(operation);
            QTimer::singleShot(0, owner, [this] { next(); });
        } else {
            finish(operation, rpcError(identifier, -32601, QStringLiteral("不支持的方法 %1").arg(method)));
        }
    }
};

StdioRuntime::StdioRuntime(Session *session, quint16 port, FILE *output, QObject *parent)
    : QObject(parent), impl_(std::make_unique<Impl>(this, session, port, output))
{
    if (!output)
        throw std::invalid_argument("StdioRuntime requires a protocol output stream");
    auto timer = new QTimer(this);
    timer->setInterval(20);
    connect(timer, &QTimer::timeout, this, [this] {
        const auto pending = impl_->pending.values();
        for (const auto &operation : pending) {
            if (Clock::now() >= operation->deadline)
                impl_->cancel(operation, QStringLiteral("请求超过总时限，正在执行的计算可能仍将完成"), "timeout");
        }
    });
    timer->start();
}

StdioRuntime::~StdioRuntime() { close(); }

void StdioRuntime::submit(const QByteArray &line)
{
    try {
        impl_->submit(line);
    } catch (const std::exception &error) {
        auto operation = impl_->active;
        if (operation) {
            impl_->drop();
            impl_->finish(operation, rpcError(operation->message.value("id"), -32603, QString::fromUtf8(error.what())));
        } else {
            impl_->write(rpcError(QJsonValue::Null, -32603, QString::fromUtf8(error.what())));
        }
    }
}

void StdioRuntime::close()
{
    if (impl_->closed)
        return;
    impl_->closed = true;
    const bool remotePending = impl_->active && !impl_->session && impl_->active->sent;
    if (impl_->active)
        impl_->cancelRemote(impl_->active);
    for (const auto &operation : std::as_const(impl_->pending))
        operation->finished = true;
    impl_->pending.clear();
    impl_->queue.clear();
    impl_->active.reset();
    impl_->drop();
    if (remotePending)
        QTimer::singleShot(1000, this, [this] { emit finished(); });
    else
        emit finished();
}

}
