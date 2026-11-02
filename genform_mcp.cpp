#include "genform/api/mcp_runtime.hpp"
#include "genform/api/wire.hpp"
#include "genform/session.hpp"
#include <QCoreApplication>
#include <QGuiApplication>
#include <QThread>
#include <cstdio>
#include <iostream>
#include <memory>
#include <mutex>
#include <thread>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#else
#include <signal.h>
#include <unistd.h>
#endif

namespace {

struct InputTarget {
    std::mutex mutex;
    genform::api::StdioRuntime *runtime = nullptr;
};

FILE *protocolOutput()
{
    std::fflush(stdout);
#ifdef Q_OS_WIN
    const auto descriptor = _dup(_fileno(stdout));
    if (descriptor < 0)
        return nullptr;
    if (_dup2(_fileno(stderr), _fileno(stdout)) != 0) {
        _close(descriptor);
        return nullptr;
    }
    const auto diagnosticHandle = reinterpret_cast<HANDLE>(_get_osfhandle(_fileno(stderr)));
    if (diagnosticHandle == INVALID_HANDLE_VALUE || !SetStdHandle(STD_OUTPUT_HANDLE, diagnosticHandle)) {
        _close(descriptor);
        return nullptr;
    }
    _setmode(descriptor, _O_BINARY);
    _setmode(_fileno(stdin), _O_BINARY);
    auto stream = _fdopen(descriptor, "wb");
    if (!stream)
        _close(descriptor);
#else
    const auto descriptor = dup(fileno(stdout));
    if (descriptor < 0)
        return nullptr;
    if (dup2(fileno(stderr), fileno(stdout)) < 0) {
        ::close(descriptor);
        return nullptr;
    }
    auto stream = fdopen(descriptor, "wb");
    if (!stream)
        ::close(descriptor);
    signal(SIGPIPE, SIG_IGN);
#endif
    return stream;
}

}

int main(int argc, char **argv)
{
    bool headless = false;
    bool explicitPort = false;
    quint16 port = genform::api::DefaultPort;
    for (int index = 1; index < argc; ++index) {
        const auto argument = QString::fromLocal8Bit(argv[index]);
        if (argument == "--help" || argument == "-h") {
            std::fputs("Usage: genform_mcp [--headless] [--port PORT]\n"
                       "Default: forward MCP tools to the desktop at 127.0.0.1:9631.\n"
                       "--headless  Use a local Session (no viewport tools).\n"
                       "--port PORT Override GENFORM_PORT; 0 disables desktop connections.\n"
                       "GENFORM_PORT overrides the default port. Protocol: newline-delimited JSON-RPC on stdio.\n", stdout);
            return 0;
        }
        if (argument == "--headless") {
            headless = true;
        } else if (argument == "--port" || argument.startsWith("--port=")) {
            const auto value = argument.startsWith("--port=") ? argument.mid(7)
                : index + 1 < argc ? QString::fromLocal8Bit(argv[++index]) : QString{};
            bool valid = false;
            const auto number = value.toInt(&valid);
            if (!valid || number < 0 || number > 65535) {
                std::fputs("--port requires an integer between 0 and 65535\n", stderr);
                return 2;
            }
            port = static_cast<quint16>(number);
            explicitPort = true;
        } else {
            std::fprintf(stderr, "Unknown argument: %s\n", argv[index]);
            return 2;
        }
    }
    try {
        if (!explicitPort)
            port = genform::api::configuredPort();
    } catch (const std::exception &error) {
        std::fprintf(stderr, "%s\n", error.what());
        return 2;
    }
    std::unique_ptr<FILE, decltype(&std::fclose)> output(protocolOutput(), &std::fclose);
    if (!output) {
        std::fputs("Cannot create an isolated MCP protocol output stream\n", stderr);
        return 1;
    }
#if defined(Q_OS_UNIX) && !defined(Q_OS_MACOS)
    if (headless && !qEnvironmentVariableIsSet("QT_QPA_PLATFORM") && qEnvironmentVariableIsEmpty("DISPLAY")
        && qEnvironmentVariableIsEmpty("WAYLAND_DISPLAY"))
        qputenv("QT_QPA_PLATFORM", "offscreen");
#endif
    std::unique_ptr<QCoreApplication> application;
    if (headless)
        application = std::make_unique<QGuiApplication>(argc, argv);
    else
        application = std::make_unique<QCoreApplication>(argc, argv);
    QCoreApplication::setApplicationName("genform_mcp");
    QCoreApplication::setApplicationVersion("0.2.0");
    std::unique_ptr<genform::Session> session;
    if (headless)
        session = std::make_unique<genform::Session>();
    QThread protocolThread;
    auto runtime = new genform::api::StdioRuntime(session.get(), port, output.get());
    runtime->moveToThread(&protocolThread);
    QObject::connect(&protocolThread, &QThread::finished, runtime, &QObject::deleteLater);
    QObject::connect(runtime, &genform::api::StdioRuntime::finished, application.get(), &QCoreApplication::quit,
                     Qt::QueuedConnection);
    protocolThread.start();
    const auto target = std::make_shared<InputTarget>();
    target->runtime = runtime;
    std::thread([target] {
        std::string line;
        while (std::getline(std::cin, line)) {
            const auto bytes = QByteArray::fromStdString(line);
            std::lock_guard<std::mutex> lock(target->mutex);
            if (!target->runtime)
                return;
            auto receiver = target->runtime;
            QMetaObject::invokeMethod(receiver, [receiver, bytes] { receiver->submit(bytes); }, Qt::QueuedConnection);
        }
        std::lock_guard<std::mutex> lock(target->mutex);
        if (auto receiver = target->runtime)
            QMetaObject::invokeMethod(receiver, [receiver] { receiver->close(); }, Qt::QueuedConnection);
    }).detach();
    const auto status = application->exec();
    {
        std::lock_guard<std::mutex> lock(target->mutex);
        target->runtime = nullptr;
    }
    QMetaObject::invokeMethod(runtime, [runtime] { runtime->close(); }, Qt::BlockingQueuedConnection);
    protocolThread.quit();
    protocolThread.wait();
    return status;
}
