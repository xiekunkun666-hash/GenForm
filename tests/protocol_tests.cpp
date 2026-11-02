#include "genform/api/server.hpp"
#include "genform/api/wire.hpp"
#include "genform/session.hpp"
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QHostAddress>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QProcess>
#include <QProcessEnvironment>
#include <QSet>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QThread>
#include <atomic>
#include <cmath>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <utility>

namespace {

void require(bool condition, const QString &message)
{
    if (!condition)
        throw std::runtime_error(message.toStdString());
}

template<class Predicate>
void waitUntil(Predicate predicate, const QString &message, int timeout = 10000)
{
    QElapsedTimer timer;
    timer.start();
    while (!predicate()) {
        require(timer.elapsed() < timeout, message);
        QCoreApplication::processEvents(QEventLoop::AllEvents, 5);
        QThread::msleep(1);
    }
}

void settle(int milliseconds = 60)
{
    QElapsedTimer timer;
    timer.start();
    waitUntil([&] { return timer.elapsed() >= milliseconds; }, "event loop did not settle", milliseconds + 2000);
}

struct Environment {
    QByteArray name;
    QByteArray previous;
    bool existed;
    explicit Environment(QByteArray key) : name(std::move(key)), previous(qgetenv(name.constData())),
        existed(qEnvironmentVariableIsSet(name.constData())) { qunsetenv(name.constData()); }
    ~Environment() { if (existed) qputenv(name.constData(), previous); else qunsetenv(name.constData()); }
};

quint16 freePort()
{
    QTcpServer probe;
    require(probe.listen(QHostAddress::LocalHost, 0), "cannot reserve loopback port");
    return probe.serverPort();
}

QJsonObject parseObject(const QByteArray &line)
{
    QJsonParseError error;
    const auto document = QJsonDocument::fromJson(line, &error);
    require(error.error == QJsonParseError::NoError && document.isObject(),
            "non-JSON object on protocol stream: " + QString::fromUtf8(line.left(200)));
    return document.object();
}

QJsonObject rpc(const QJsonValue &identifier, const QString &method, const QJsonObject &params = {})
{
    return {{"jsonrpc", "2.0"}, {"id", identifier}, {"method", method}, {"params", params}};
}

QJsonObject call(const QJsonValue &identifier, const QString &name, const QJsonObject &arguments = {})
{
    return rpc(identifier, "tools/call", {{"name", name}, {"arguments", arguments}});
}

QJsonObject profile()
{
    return {{"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"cx", 0}, {"cy", 0}, {"w", 20}, {"h", 10}}}}};
}

QJsonObject buildPlate()
{
    return {{"steps", QJsonArray{
        QJsonObject{{"cmd", "sketch"}, {"args", profile()}, {"as", "profile"}},
        QJsonObject{{"cmd", "extrude"}, {"args", QJsonObject{{"sketch", "$profile"}, {"distance", 5}}}}
    }}};
}

QJsonObject toolValue(const QJsonObject &message)
{
    require(message.contains("result") && !message.contains("error"), "tool call did not return MCP result");
    const auto content = message.value("result").toObject().value("content").toArray();
    require(!content.isEmpty() && content.first().toObject().value("type") == "text", "missing MCP text content");
    const auto result = parseObject(content.first().toObject().value("text").toString().toUtf8());
    require(message.value("result").toObject().value("isError").toBool() == !result.value("ok").toBool(),
            "isError disagrees with native command result");
    return result;
}

void rpcError(const QJsonObject &message, int expected)
{
    require(message.value("error").toObject().value("code").toInt() == expected && !message.contains("result"),
            "wrong JSON-RPC error: " + QString::fromUtf8(genform::api::encode(message)));
}

class TcpClient {
public:
    QTcpSocket socket;
    QByteArray buffer;
    explicit TcpClient(quint16 port)
    {
        socket.connectToHost(QHostAddress::LocalHost, port);
        waitUntil([&] { return socket.state() == QAbstractSocket::ConnectedState; }, "TCP connection failed");
    }
    void raw(const QByteArray &bytes)
    {
        require(socket.write(bytes) == bytes.size(), "TCP write failed");
        socket.flush();
    }
    void send(const QJsonObject &message) { raw(genform::api::encode(message) + '\n'); }
    QJsonObject take()
    {
        waitUntil([&] { buffer += socket.readAll(); return buffer.contains('\n'); }, "TCP response timed out");
        const auto newline = buffer.indexOf('\n');
        const auto line = buffer.left(newline);
        buffer.remove(0, newline + 1);
        return parseObject(line);
    }
    QJsonObject request(const QJsonObject &message) { send(message); return take(); }
    void quiet()
    {
        settle();
        buffer += socket.readAll();
        require(buffer.isEmpty(), "late or duplicate TCP response");
    }
};

class McpProcess {
public:
    QProcess process;
    QByteArray buffer;
    QByteArray diagnostics;
    QList<QJsonObject> replies;
    int lines = 0;
    explicit McpProcess(const QString &executable, const QStringList &arguments,
                        const QString &environmentPort = {})
    {
        auto environment = QProcessEnvironment::systemEnvironment();
        environment.remove("GENFORM_PORT");
        environment.insert("QT_QPA_PLATFORM", "offscreen");
        if (!environmentPort.isNull())
            environment.insert("GENFORM_PORT", environmentPort);
        process.setProcessEnvironment(environment);
        process.setProcessChannelMode(QProcess::SeparateChannels);
        process.start(executable, arguments, QIODevice::ReadWrite);
        require(process.waitForStarted(10000), "cannot start native MCP executable: " + process.errorString());
    }
    ~McpProcess()
    {
        if (process.state() != QProcess::NotRunning) {
            process.kill();
            process.waitForFinished(3000);
        }
    }
    void collect()
    {
        diagnostics += process.readAllStandardError();
        buffer += process.readAllStandardOutput();
        while (buffer.contains('\n')) {
            const auto newline = buffer.indexOf('\n');
            const auto line = buffer.left(newline);
            buffer.remove(0, newline + 1);
            const auto message = parseObject(line);
            require(message.value("jsonrpc") == "2.0" && message.contains("id")
                    && (message.contains("result") != message.contains("error")),
                    "stdout line is not a JSON-RPC response");
            replies.append(message);
            ++lines;
        }
    }
    void raw(const QByteArray &bytes)
    {
        require(process.write(bytes) == bytes.size(), "MCP stdin write failed");
        QElapsedTimer timer;
        timer.start();
        while (process.bytesToWrite() > 0) {
            require(timer.elapsed() < 10000 && process.waitForBytesWritten(10000), "MCP stdin flush failed");
        }
    }
    void send(const QJsonObject &message) { raw(genform::api::encode(message) + '\n'); }
    QJsonObject take(const QJsonValue &identifier)
    {
        int found = -1;
        waitUntil([&] {
            collect();
            for (int index = 0; index < replies.size(); ++index) {
                if (replies[index].value("id") == identifier) { found = index; return true; }
            }
            require(process.state() != QProcess::NotRunning,
                    "MCP exited before response: " + QString::fromUtf8(diagnostics.right(2000)));
            return false;
        }, "MCP response timed out", 20000);
        return replies.takeAt(found);
    }
    QJsonObject request(const QJsonObject &message) { send(message); return take(message.value("id")); }
    void quiet()
    {
        settle();
        collect();
        require(replies.isEmpty() && buffer.isEmpty(), "unexpected, duplicate or incomplete MCP stdout");
    }
    void eof()
    {
        process.closeWriteChannel();
        waitUntil([&] { collect(); return process.state() == QProcess::NotRunning; }, "EOF did not terminate MCP", 15000);
        collect();
        require(process.exitStatus() == QProcess::NormalExit && process.exitCode() == 0,
                "MCP did not exit cleanly: " + QString::fromUtf8(diagnostics.right(2000)));
        require(buffer.isEmpty(), "incomplete/non-JSON stdout at EOF");
    }
};

class Suite {
public:
    int passed = 0;
    void test(const char *name, const std::function<void()> &body)
    {
        body();
        std::cout << "PASS " << ++passed << ' ' << name << '\n';
    }
};

void tcpTests(Suite &suite)
{
    Environment portEnvironment("GENFORM_PORT");
    genform::Session session;
    suite.test("port configuration boundaries", [&] {
        require(genform::api::configuredPort() == 9631 && genform::api::configuredPort(1234) == 1234, "port fallback changed");
        for (const auto &value : QList<QByteArray>{"0", "1", "65535"}) {
            qputenv("GENFORM_PORT", value);
            require(genform::api::configuredPort() == value.toUInt(), "valid environment port rejected");
        }
        for (const auto &value : QList<QByteArray>{"-1", "65536", "abc", "1.5"}) {
            qputenv("GENFORM_PORT", value);
            bool rejected = false;
            try { genform::api::configuredPort(); } catch (const std::invalid_argument &) { rejected = true; }
            require(rejected, "invalid environment port accepted");
        }
        qunsetenv("GENFORM_PORT");
    });
    suite.test("wire failures and interruption contract", [&] {
        const auto error = genform::api::failure("failure", "test");
        require(parseObject(genform::api::encode(error)) == error && !error.value("ok").toBool(), "wire round trip failed");
        for (const bool started : {false, true}) {
            const auto interrupted = genform::api::interrupted("cancelled", "cancelled", started);
            require(interrupted.value("started").toBool() == started && !interrupted.value("hint").toString().isEmpty(),
                    "interruption must disclose possible document changes");
        }
    });
    suite.test("real Session catalog", [&] {
        const auto result = genform::api::execute(&session, {{"cmd", "tools"}});
        require(result.value("ok").toBool() && result.value("tools").toArray() == genform::Session::tools(), "catalog differs from real Session");
    });
    suite.test("closed unsupported and unknown commands", [&] {
        require(genform::api::execute(nullptr, {{"cmd", "get_model"}}).value("code") == "closed", "closed Session accepted");
        require(genform::api::execute(&session, {{"cmd", "ui"}}).value("code") == "unsupported", "Python UI command accepted");
        require(!genform::api::execute(&session, {{"cmd", "does_not_exist"}}).value("ok").toBool(), "unknown command succeeded");
    });
    suite.test("disabled listener", [&] { genform::api::ApiServer disabled(&session, 0); require(disabled.port() == 0, "port zero listened"); });
    suite.test("occupied listener port", [&] {
        QTcpServer occupied;
        require(occupied.listen(QHostAddress::LocalHost, 0), "cannot reserve port");
        bool rejected = false;
        try { genform::api::ApiServer conflict(&session, occupied.serverPort()); } catch (const std::runtime_error &) { rejected = true; }
        require(rejected, "occupied port silently accepted");
    });
    genform::api::ApiServer server(&session, freePort());
    suite.test("desktop TCP ping", [&] {
        TcpClient client(server.port());
        const auto result = client.request({{"cmd", "ping"}});
        require(result.value("ok").toBool() && result.value("pid").toDouble() == QCoreApplication::applicationPid(), "wrong desktop identity");
    });
    suite.test("fragmented TCP frame", [&] {
        TcpClient client(server.port());
        client.raw("{\"cmd\":"); settle(10); require(client.socket.bytesAvailable() == 0, "partial frame executed");
        client.raw("\"ping\"}\r\n"); require(client.take().value("ok").toBool(), "fragmented frame lost");
    });
    suite.test("pipelined TCP frames", [&] {
        TcpClient client(server.port());
        client.raw("\n{\"cmd\":\"ping\"}\n{\"cmd\":\"tools\"}\n");
        require(client.take().value("app") == "GenForm" && !client.take().value("tools").toArray().isEmpty(), "pipeline ordering changed");
    });
    suite.test("malformed TCP frames recover", [&] {
        TcpClient client(server.port());
        for (const auto &line : QList<QByteArray>{"{", "[]", "null", "42"}) {
            client.raw(line + '\n'); require(client.take().value("code") == "invalid_request", "malformed TCP JSON accepted");
        }
        require(client.request({{"cmd", "ping"}}).value("ok").toBool(), "TCP did not recover after invalid JSON");
    });
    suite.test("TCP request field validation", [&] {
        TcpClient client(server.port());
        for (const auto &payload : QList<QJsonObject>{{}, {{"cmd", ""}}, {{"cmd", 1}}, {{"cmd", "ping"}, {"args", QJsonArray{}}}, {{"cmd", "ping"}, {"request_id", 1}}})
            require(client.request(payload).value("code") == "invalid_request", "invalid request fields accepted");
        require(client.request({{"cmd", "ping"}, {"args", QJsonValue::Null}}).value("ok").toBool(), "nullable args compatibility lost");
    });
    suite.test("TCP timeout validation", [&] {
        TcpClient client(server.port());
        for (const auto &timeout : QList<QJsonValue>{0, -1, 301, "bad", "nan", "inf", QJsonValue::Null, true})
            require(client.request({{"cmd", "ping"}, {"timeout_s", timeout}}).value("code") == "invalid_request", "invalid timeout accepted");
        require(client.request({{"cmd", "ping"}, {"timeout_s", "1"}}).value("ok").toBool(), "numeric string timeout rejected");
    });
    suite.test("TCP oversized unterminated frame", [&] {
        TcpClient client(server.port());
        client.raw(QByteArray(genform::api::MaximumLineSize + 1, 'x'));
        require(client.take().value("code") == "invalid_request", "TCP size limit missing");
        waitUntil([&] { return client.socket.state() == QAbstractSocket::UnconnectedState; }, "oversized socket remained connected");
    });
    suite.test("real mutation runs on Qt main thread", [&] {
        bool changed = false;
        bool mainThread = true;
        const auto connection = QObject::connect(&session, &genform::Session::changed, &session, [&] {
            changed = true;
            mainThread = mainThread && QThread::currentThread() == QCoreApplication::instance()->thread();
        }, Qt::DirectConnection);
        TcpClient client(server.port());
        const auto result = client.request({{"cmd", "sketch"}, {"args", profile()}});
        QObject::disconnect(connection);
        require(result.value("ok").toBool() && changed && mainThread && session.document.features.size() == 1, "Session mutation bypassed main thread");
    });
    suite.test("queued deadline skips mutation", [&] {
        const auto revision = session.document.revision;
        TcpClient client(server.port());
        client.send({{"cmd", "sketch"}, {"args", profile()}, {"timeout_s", .03}});
        QThread::msleep(120);
        const auto result = client.take();
        require(result.value("code") == "timeout" && !result.value("started").toBool(), "queued timeout reported as started");
        settle(); require(session.document.revision == revision, "expired queued operation mutated real Session"); client.quiet();
    });
    suite.test("queued cancellation skips mutation", [&] {
        const auto revision = session.document.revision;
        TcpClient request(server.port()), control(server.port());
        request.send({{"cmd", "sketch"}, {"args", profile()}, {"request_id", "cancel-queued"}});
        QThread::msleep(30);
        control.send({{"cmd", "cancel_request"}, {"request_id", "cancel-queued"}});
        QThread::msleep(30);
        const auto cancelled = request.take();
        require(cancelled.value("code") == "cancelled" && !cancelled.value("started").toBool(), "queued cancel did not skip execution");
        require(control.take().value("found").toBool(), "cancel target was not found");
        settle(); require(session.document.revision == revision, "cancelled queued operation mutated Session"); request.quiet();
    });
    suite.test("duplicate live request identifier", [&] {
        TcpClient first(server.port()), duplicate(server.port()), control(server.port());
        first.send({{"cmd", "ping"}, {"request_id", "duplicate"}}); QThread::msleep(30);
        duplicate.send({{"cmd", "ping"}, {"request_id", "duplicate"}}); QThread::msleep(30);
        control.send({{"cmd", "cancel_request"}, {"request_id", "duplicate"}}); QThread::msleep(30);
        require(duplicate.take().value("code") == "invalid_request", "live duplicate identifier accepted");
        require(control.take().value("found").toBool() && first.take().value("code") == "cancelled", "duplicate replaced original operation");
    });
    suite.test("disconnect skips queued mutation", [&] {
        const auto revision = session.document.revision;
        TcpClient client(server.port());
        client.send({{"cmd", "sketch"}, {"args", profile()}}); QThread::msleep(30);
        client.socket.abort(); QThread::msleep(50);
        settle(); require(session.document.revision == revision, "disconnected queued operation mutated Session");
    });
    suite.test("started deadline drops result but cannot interrupt synchronous work", [&] {
        bool completed = false;
        session.viewCommand = [&](const QString &, const QJsonObject &) {
            QThread::msleep(150); completed = true; return QJsonObject{{"ok", true}};
        };
        TcpClient client(server.port());
        const auto result = client.request({{"cmd", "set_view"}, {"args", QJsonObject{{"view", "fit"}}}, {"timeout_s", .05}});
        session.viewCommand = {};
        require(result.value("code") == "timeout" && result.value("started").toBool() && completed,
                "deadline falsely claimed synchronous Session work was interrupted"); client.quiet();
    });
    suite.test("started cancellation drops late result without stopping synchronous work", [&] {
        std::atomic_bool started{false}, acknowledged{false};
        bool completed = false;
        session.viewCommand = [&](const QString &, const QJsonObject &) {
            started = true; QThread::msleep(200); completed = true; return QJsonObject{{"ok", true}};
        };
        const auto port = server.port();
        std::thread cancel([&] {
            QElapsedTimer timer; timer.start();
            while (!started && timer.elapsed() < 5000) QThread::msleep(1);
            if (!started) return;
            QTcpSocket control;
            control.connectToHost(QHostAddress::LocalHost, port);
            if (!control.waitForConnected(2000)) return;
            control.write(genform::api::encode({{"cmd", "cancel_request"}, {"request_id", "started-cancel"}}) + '\n');
            if (!control.waitForReadyRead(2000)) return;
            acknowledged = QJsonDocument::fromJson(control.readAll()).object().value("found").toBool();
        });
        TcpClient client(server.port());
        client.send({{"cmd", "set_view"}, {"args", QJsonObject{{"view", "fit"}}}, {"request_id", "started-cancel"}});
        QJsonObject result;
        try { result = client.take(); } catch (...) { cancel.join(); session.viewCommand = {}; throw; }
        cancel.join(); session.viewCommand = {};
        require(acknowledged && completed && result.value("code") == "cancelled" && result.value("started").toBool(),
                "cancel falsely interrupted synchronous work or lost started state"); client.quiet();
    });
    suite.test("close cancels queued requests and is idempotent", [&] {
        TcpClient client(server.port());
        client.send({{"cmd", "sketch"}, {"args", profile()}}); QThread::msleep(30);
        const auto revision = session.document.revision;
        server.close();
        require(client.take().value("code") == "cancelled" && server.port() == 0, "server close lost cancellation");
        settle(); require(session.document.revision == revision, "closed server executed queued work"); server.close();
    });
}

void processTests(Suite &suite, const QString &executable)
{
    McpProcess headless(executable, {"--headless", "--port", "0"});
    suite.test("headless stdio initialize", [&] {
        const auto message = headless.request(rpc(1, "initialize"));
        const auto result = message.value("result").toObject();
        require(result.value("protocolVersion") == "2024-11-05" && result.value("capabilities").toObject().contains("tools")
                && result.value("serverInfo").toObject().value("name") == "genform", "initialize contract changed");
    });
    suite.test("headless complete tools list schema", [&] {
        const auto tools = headless.request(rpc(2, "tools/list")).value("result").toObject().value("tools").toArray();
        require(tools.size() == genform::Session::tools().size(), "headless tool catalog incomplete");
        QSet<QString> names;
        for (const auto &value : tools) {
            const auto tool = value.toObject();
            require(tool.value("inputSchema").toObject().value("type") == "object" && !tool.contains("input_schema"), "MCP schema conversion failed");
            require(!names.contains(tool.value("name").toString()), "duplicate MCP tool"); names.insert(tool.value("name").toString());
        }
        require(names.contains("export") && names.contains("batch"), "required native tools absent");
    });
    suite.test("MCP ping preserves string numeric and null ids", [&] {
        for (const auto &identifier : QList<QJsonValue>{"unicode-\u6d4b\u8bd5", 3, QJsonValue::Null})
            require(headless.request(rpc(identifier, "ping")).value("result").isObject(), "MCP ping identifier roundtrip failed");
    });
    suite.test("headless native batch constructs OCCT body", [&] {
        const auto value = toolValue(headless.request(call(4, "batch", buildPlate())));
        require(value.value("ok").toBool() && value.value("ids").toArray().size() == 2
                && value.value("model").toObject().value("has_body").toBool(), "real OCCT plate build failed");
    });
    suite.test("headless Session model matches actual geometry", [&] {
        const auto value = toolValue(headless.request(call(5, "get_model")));
        const auto model = value.value("model").isObject() ? value.value("model").toObject() : value;
        require(value.value("ok").toBool() && model.value("features").toArray().size() == 2, "real Session state lost");
        require(std::abs(model.value("body").toObject().value("volume_mm3").toDouble() - 1000) < 1e-5, "real OCCT plate volume changed");
    });
    suite.test("real STEP export keeps every stdout line JSON-RPC", [&] {
        QTemporaryDir directory;
        require(directory.isValid(), "cannot create STEP output directory");
        const auto path = directory.filePath("plate.step");
        headless.collect();
        const auto diagnosticStart = headless.diagnostics.size();
        const auto value = toolValue(headless.request(call(6, "export", {{"path", path}})));
        require(value.value("ok").toBool(), "real STEP export failed");
        QFile step(path);
        require(step.open(QIODevice::ReadOnly), "STEP exporter did not create file");
        const auto bytes = step.readAll();
        require(bytes.startsWith("ISO-10303-21;") && bytes.contains("END-ISO-10303-21;") && bytes.contains("MANIFOLD_SOLID_BREP"),
                "output is not an actual solid STEP document");
        headless.request(rpc("post-step", "ping")); headless.quiet();
        headless.collect();
        const auto exportDiagnostics = headless.diagnostics.mid(diagnosticStart);
        require(exportDiagnostics.contains("Statistics on Transfer") && exportDiagnostics.contains("Transferring Shape"),
                "native OCCT Transfer diagnostics were lost instead of redirected to stderr: "
                    + QString::fromUtf8(exportDiagnostics));
        std::cout << "  STEP bytes=" << bytes.size() << " validated JSON-RPC lines=" << headless.lines
                  << " export diagnostic bytes=" << exportDiagnostics.size() << '\n';
    });
    suite.test("MCP JSON parse error and recovery", [&] {
        for (const auto &line : QList<QByteArray>{"{", "null", "42"}) {
            headless.raw(line + '\n'); rpcError(headless.take(QJsonValue::Null), -32700);
        }
        require(headless.request(rpc(7, "ping")).contains("result"), "parse error poisoned stdio connection");
    });
    suite.test("MCP invalid envelopes", [&] {
        for (const auto &line : QList<QByteArray>{"[]", "{}", "{\"jsonrpc\":\"1.0\",\"id\":8,\"method\":\"ping\"}",
             "{\"jsonrpc\":\"2.0\",\"id\":{},\"method\":\"ping\"}"}) {
            headless.raw(line + '\n'); rpcError(headless.take(QJsonValue::Null), -32600);
        }
    });
    suite.test("MCP invalid parameter types", [&] {
        auto invalid = rpc(9, "ping"); invalid["params"] = QJsonArray{};
        rpcError(headless.request(invalid), -32602);
        for (const auto &params : QList<QJsonObject>{{}, {{"name", ""}}, {{"name", 1}}, {{"name", "get_model"}, {"arguments", QJsonArray{}}}})
            rpcError(headless.request(rpc(10, "tools/call", params)), -32602);
    });
    suite.test("MCP unknown method", [&] { rpcError(headless.request(rpc("missing", "does/not/exist")), -32601); });
    suite.test("native tool failures remain MCP results", [&] {
        for (const auto &name : QStringList{"does_not_exist", "screenshot"})
            require(!toolValue(headless.request(call(name, name))).value("ok").toBool(), "unsupported native tool falsely succeeded");
        require(!toolValue(headless.request(call(11, "extrude", {{"sketch", "absent"}, {"distance", 1}}))).value("ok").toBool(), "invalid feature command succeeded");
    });
    suite.test("MCP notifications and whitespace have no response", [&] {
        headless.raw(" \r\n");
        headless.send({{"jsonrpc", "2.0"}, {"method", "notifications/initialized"}});
        headless.send({{"jsonrpc", "2.0"}, {"method", "tools/call"}, {"params", QJsonObject{{"name", "new_document"}}}});
        const auto model = toolValue(headless.request(call(12, "get_model")));
        const auto state = model.value("model").isObject() ? model.value("model").toObject() : model;
        require(state.value("features").toArray().size() == 2, "notification executed a mutation"); headless.quiet();
    });
    suite.test("headless cancellation and late results do not corrupt stdio", [&] {
        QJsonArray steps;
        for (int index = 0; index < 24; ++index) steps.append(QJsonObject{{"cmd", "sketch"}, {"args", profile()}});
        const auto blocker = call("blocker", "batch", {{"steps", steps}});
        const auto queued = call("cancel-me", "new_document");
        const QJsonObject cancel{{"jsonrpc", "2.0"}, {"method", "notifications/cancelled"}, {"params", QJsonObject{{"requestId", "cancel-me"}}}};
        headless.raw(genform::api::encode(blocker) + '\n' + genform::api::encode(queued) + '\n' + genform::api::encode(cancel) + '\n');
        const auto cancelled = headless.take("cancel-me"); rpcError(cancelled, -32800);
        require(cancelled.value("error").toObject().value("data").toObject().value("code") == "cancelled", "cancel error data missing");
        require(toolValue(headless.take("blocker")).value("ok").toBool(), "blocking real Session batch failed");
        headless.request(rpc("after-cancel", "ping")); headless.quiet();
    });
    suite.test("MCP oversized request and recovery", [&] {
        headless.raw(QByteArray(genform::api::MaximumLineSize + 1, 'x') + '\n');
        rpcError(headless.take(QJsonValue::Null), -32600);
        require(headless.request(rpc(13, "ping")).contains("result"), "oversized frame poisoned stdio");
    });
    suite.test("headless EOF accepts final unterminated frame", [&] {
        headless.raw(genform::api::encode(rpc("last", "ping")));
        headless.eof();
        int found = 0;
        for (const auto &reply : std::as_const(headless.replies)) if (reply.value("id") == "last" && reply.contains("result")) ++found;
        require(found == 1 && headless.replies.size() == 1, "final unterminated frame was lost or duplicated"); headless.replies.clear();
    });
    suite.test("headless EOF with queued work exits cleanly", [&] {
        McpProcess process(executable, {"--headless"});
        process.send(call("eof-work", "batch", buildPlate())); process.eof();
    });
    suite.test("CLI invalid ports environment and explicit override", [&] {
        for (const auto &arguments : QList<QStringList>{{"--port", "-1"}, {"--port=65536"}, {"--port"}, {"--unknown"}}) {
            McpProcess process(executable, arguments);
            waitUntil([&] { return process.process.state() == QProcess::NotRunning; }, "invalid CLI did not exit"); process.collect();
            require(process.process.exitCode() == 2 && process.lines == 0 && process.buffer.isEmpty() && !process.diagnostics.isEmpty(), "invalid CLI polluted stdout or did not fail");
        }
        McpProcess invalid(executable, {}, "bad");
        waitUntil([&] { return invalid.process.state() == QProcess::NotRunning; }, "invalid environment did not exit"); invalid.collect();
        require(invalid.process.exitCode() == 2 && invalid.lines == 0 && invalid.buffer.isEmpty(), "invalid environment accepted");
        McpProcess explicitPort(executable, {"--port=0"}, "bad");
        require(explicitPort.request(rpc(1, "ping")).contains("result"), "explicit port did not override invalid environment"); explicitPort.eof();
    });
    Environment portEnvironment("GENFORM_PORT");
    genform::Session desktop;
    genform::api::ApiServer server(&desktop, freePort());
    McpProcess forward(executable, {"--port", QString::number(server.port())});
    suite.test("desktop MCP forwarding reaches real Session on main thread", [&] {
        bool routed = false;
        desktop.viewCommand = [&](const QString &, const QJsonObject &) {
            routed = QThread::currentThread() == QCoreApplication::instance()->thread(); return QJsonObject{{"ok", true}};
        };
        require(toolValue(forward.request(call(1, "set_view", {{"view", "fit"}}))).value("ok").toBool() && routed, "forwarding bypassed main thread");
        desktop.viewCommand = {};
        require(toolValue(forward.request(call(2, "batch", buildPlate()))).value("ok").toBool() && desktop.document.features.size() == 2,
                "forwarded model changes did not reach real desktop Session");
        const auto tools = forward.request(rpc(3, "tools/list")).value("result").toObject().value("tools").toArray();
        require(tools.size() == genform::Session::tools().size(), "forwarded tools list incomplete");
    });
    suite.test("desktop disabled and disconnected failures preserve fallback catalog", [&] {
        for (const auto port : QList<quint16>{0, freePort()}) {
            McpProcess process(executable, {"--port", QString::number(port)});
            const auto failure = toolValue(process.request(call(1, "get_model")));
            require(!failure.value("ok").toBool() && failure.value("code") == (port ? "connection_error" : "disabled"), "forward failure falsely succeeded");
            require(process.request(rpc(2, "tools/list")).value("result").toObject().value("tools").toArray().size() == genform::Session::tools().size(),
                    "offline tools fallback missing"); process.eof();
        }
    });
    suite.test("desktop MCP cancellation skips queued mutation and drops late reply", [&] {
        const auto revision = desktop.document.revision;
        forward.send(call("remote-cancel", "new_document"));
        QThread::msleep(100);
        forward.send({{"jsonrpc", "2.0"}, {"method", "notifications/cancel"}, {"params", QJsonObject{{"requestId", "remote-cancel"}}}});
        QThread::msleep(100);
        rpcError(forward.take("remote-cancel"), -32800);
        settle(); require(desktop.document.revision == revision, "cancelled desktop mutation executed"); forward.quiet();
    });
    suite.test("desktop MCP EOF cancels pending connection", [&] {
        const auto revision = desktop.document.revision;
        forward.send(call("remote-eof", "new_document")); QThread::msleep(100);
        forward.process.closeWriteChannel();
        require(forward.process.waitForFinished(5000), "MCP did not exit after EOF while main thread was blocked");
        forward.eof(); settle();
        require(desktop.document.revision == revision, "EOF allowed queued desktop mutation");
    });
}

}

int main(int argc, char **argv)
{
    QCoreApplication application(argc, argv);
    try {
        require(argc == 2, "Usage: genform_protocol_tests <native genform_mcp executable>");
        const auto executable = QFileInfo(QString::fromLocal8Bit(argv[1])).absoluteFilePath();
        require(QFileInfo(executable).isFile() && QFileInfo(executable).isExecutable(), "native MCP executable does not exist");
        Suite suite;
        tcpTests(suite);
        processTests(suite, executable);
        require(suite.passed == 42, "protocol suite must run all 42 named regression groups");
        std::cout << "All 42 native protocol regression groups passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "FAIL " << error.what() << '\n';
        return 1;
    }
}
