#include "genform/kernel/inspect_selftest.hpp"
#include <QCoreApplication>
#include <QJsonDocument>
#include <QTextStream>
#include <exception>

int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    try {
#ifdef GENFORM_HAS_OCCT
        const auto result = genform::kernel::native::runInspectSelfTests();
        QTextStream(stdout) << QJsonDocument(result).toJson(QJsonDocument::Compact) << Qt::endl;
#else
        QTextStream(stdout) << "OpenCascade unavailable: geometric inspection is disabled" << Qt::endl;
#endif
        return 0;
    } catch (const std::exception &error) {
        QTextStream(stderr) << error.what() << Qt::endl;
        return 1;
    }
}
