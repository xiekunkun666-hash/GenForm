#include "genform/kernel/kernel.hpp"
#include "catalog.hpp"
#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QSaveFile>
#include <QTextStream>
#include <stdexcept>

namespace {
void require(bool condition, const QString &message) {
    if (!condition) throw std::runtime_error(message.toUtf8().constData());
}

QJsonValue resolve(const QJsonValue &value, const QJsonObject &aliases) {
    if (value.isString() && value.toString().startsWith('$')) {
        const QString alias = value.toString().mid(1);
        require(aliases.contains(alias), "Unresolved recipe alias: " + alias);
        return aliases[alias];
    }
    if (value.isArray()) { QJsonArray result; for (const auto &entry : value.toArray()) result.append(resolve(entry, aliases)); return result; }
    if (value.isObject()) { QJsonObject result; const auto object = value.toObject(); for (auto iterator = object.begin(); iterator != object.end(); ++iterator) result[iterator.key()] = resolve(iterator.value(), aliases); return result; }
    return value;
}

void save(const QString &path, const QJsonObject &value) {
    require(QDir().mkpath(QFileInfo(path).absolutePath()), "Cannot create audit output folder");
    QSaveFile file(path); require(file.open(QIODevice::WriteOnly), "Cannot write audit report");
    const auto bytes = QJsonDocument(value).toJson(QJsonDocument::Indented);
    require(file.write(bytes) == bytes.size() && file.commit(), "Cannot commit audit report");
}
}

int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    try {
        const auto arguments = application.arguments().mid(1);
        require(arguments.size() == 2 || arguments.size() == 3, "Usage: genform_examples_kernel_audit <module|all> <report.json> [part.gform]");
        const auto catalog = examples::recipes::load(QDir(GENFORM_EXAMPLES_DIR).filePath("recipes/catalog.json.qz.base64"));
        const auto resourceAudit = examples::recipes::validate(catalog);
        const auto builds = catalog["builds"].toObject(); require(arguments[0] == "all" || builds.contains(arguments[0]), "Unknown recipe module");
        QJsonArray results; int failures = 0;
        const QString reportPath = arguments[1];
        auto report = [&] { return QJsonObject{{"scope", "Real native Kernel recipe execution; not a Session, assembly, rendering or Python-equivalence test"}, {"command_defaults", "Original hole defaults: diameter=5, head_diameter=10, head_depth=5; metric size overrides them in the kernel"}, {"resource_audit", resourceAudit}, {"cases", results}, {"failures", failures}}; };
        for (auto module = builds.begin(); module != builds.end(); ++module) {
            if (arguments[0] != "all" && arguments[0] != module.key()) continue;
            for (const auto &value : module.value().toObject()["parts"].toArray()) {
                const auto part = value.toObject(); const QString filename = part["file"].toString();
                if (arguments.size() == 3 && arguments[2] != filename) continue;
                QElapsedTimer elapsed; elapsed.start(); QJsonObject result{{"module", module.key()}, {"part", filename}, {"ok", false}};
                QTextStream(stdout) << "START " << module.key() << '/' << filename << Qt::endl;
                try {
                    QJsonArray features; QJsonObject aliases;
                    for (const auto &command : part["steps"].toArray()) {
                        const auto step = command.toObject(); auto params = resolve(step["args"], aliases).toObject();
                        if (step["cmd"] == "hole") {
                            const QJsonObject defaults{{"diameter", 5.}, {"head_diameter", 10.}, {"head_depth", 5.}};
                            for (auto entry = defaults.begin(); entry != defaults.end(); ++entry) if (!params.contains(entry.key())) params[entry.key()] = entry.value();
                        }
                        const QString identifier = "f" + QString::number(features.size() + 1), name = params.take("name").toString(identifier);
                        features.append(QJsonObject{{"id", identifier}, {"type", step["cmd"]}, {"name", name}, {"params", params}, {"suppressed", false}});
                        if (!step["as"].toString().isEmpty()) { require(!aliases.contains(step["as"].toString()), "Duplicate recipe alias"); aliases[step["as"].toString()] = identifier; }
                    }
                    genform::kernel::Kernel kernel;
                    const auto model = kernel.build(features); result["feature_statuses"] = model["status"]; result["features"] = features.size();
                    require(model["has_body"].toBool(), "Recipe generated no solid");
                    const auto statuses = model["status"].toObject();
                    for (auto status = statuses.begin(); status != statuses.end(); ++status) require(status.value() == "ok", status.key() + ": " + status.value().toString());
                    const auto inspection = kernel.query("inspect"); require(inspection["valid"].toBool(), "Recipe BRep invalid");
                    result["metrics"] = kernel.query("properties"); result["valid"] = inspection["valid"]; result["ok"] = true;
                } catch (const std::exception &error) { result["error"] = QString::fromUtf8(error.what()); ++failures; }
                result["runtime_ms"] = elapsed.elapsed(); results.append(result); save(reportPath, report());
                QTextStream(stdout) << (result["ok"].toBool() ? "PASS " : "FAIL ") << filename << " " << elapsed.elapsed() << "ms " << result["error"].toString() << Qt::endl;
            }
        }
        require(!results.isEmpty(), "No part selected"); save(reportPath, report()); return failures ? 1 : 0;
    } catch (const std::exception &error) { QTextStream(stderr) << "STOP: " << error.what() << '\n'; return 1; }
}
