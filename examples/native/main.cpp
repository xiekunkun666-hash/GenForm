#include "runner.hpp"
#include <QGuiApplication>
#include <QTextStream>
#include <QSet>
#ifdef GENFORM_HAS_OCCT
#include <Standard_Failure.hxx>
#endif

int main(int argc, char **argv) {
    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) qputenv("QT_QPA_PLATFORM", "offscreen");
    QGuiApplication application(argc, argv);
    application.setApplicationName("genform_examples");
    const auto arguments = application.arguments().mid(1);
    try {
        if (arguments.isEmpty() || arguments.contains("--help")) {
            QTextStream(stdout) << "Native GenForm examples (no Python runtime)\n"
                << "  genform_examples --list | --audit | --self-test\n"
                << "  genform_examples <original/path/without.py> [phase] --output <directory>\n"
                << "Options: --source <path> --reference <directory> --report <path> --force\n"
                << "         --angle <degrees> --execute --resume --state-dir <directory>\n"
                << "See MIGRATION.md for per-example inputs, outputs and limitations.\n";
            return 0;
        }
        if (arguments == QStringList{"--audit"}) return examples::audit();
        if (arguments == QStringList{"--self-test"}) return examples::selfTest();
        examples::Options options;
        options.name = arguments.first();
        if (options.name.startsWith("examples/")) options.name.remove(0, 9);
        if (options.name.endsWith(".py")) options.name.chop(3);
        const QSet<QString> flags{"force", "execute", "resume", "new-document", "export", "inspect", "self-test", "classify", "remote"};
        const QSet<QString> valued{"output", "source", "reference", "report", "angle", "state-dir", "batch-size", "samples", "arguments", "port", "samples-per-face", "tolerance", "cache-dir"};
        for (int index = 1; index < arguments.size(); ++index) {
            const QString argument = arguments[index];
            if (!argument.startsWith("--")) { options.positional.append(argument); continue; }
            const QString key = argument.mid(2);
            if (key == "uv-grid") {
                examples::require(index + 2 < arguments.size(), "--uv-grid requires U V");
                options.values[key] = QJsonArray{arguments[++index], arguments[++index]};
            } else if (flags.contains(key)) options.values[key] = true;
            else {
                examples::require(valued.contains(key), "Unknown option: " + argument);
                examples::require(index + 1 < arguments.size() && !arguments[index + 1].startsWith("--"), "Missing value for " + argument);
                options.values[key] = arguments[++index];
            }
        }
        options.output = options.values["output"].toString();
        options.force = options.values["force"].toBool();
        return examples::run(options);
    }
#ifdef GENFORM_HAS_OCCT
    catch (const Standard_Failure &error) {
        QTextStream(stderr) << "STOP: OpenCascade: " << QString::fromUtf8(error.GetMessageString()) << '\n';
        return 1;
    }
#endif
    catch (const std::exception &error) {
        QTextStream(stderr) << "STOP: " << QString::fromUtf8(error.what()) << '\n';
        return 1;
    }
}
