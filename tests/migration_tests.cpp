#include "genform/document.hpp"
#include "genform/session.hpp"
#include "genform/features.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/kernel/native.hpp"
#include <QCoreApplication>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QTemporaryDir>
#include <cmath>
#include <functional>
#include <iostream>
#include <iterator>
#include <stdexcept>

namespace {
void require(bool condition, const QString &message) {
    if (!condition) throw std::runtime_error(message.toStdString());
}
void near(double actual, double expected, double tolerance = 1e-6) {
    require(std::isfinite(actual) && std::abs(actual - expected) <= tolerance,
            QString("Expected %1, got %2").arg(expected, 0, 'g', 14).arg(actual, 0, 'g', 14));
}
void rejects(const std::function<void()> &operation) {
    bool rejected = false;
    try { operation(); } catch (const std::exception &error) { rejected = !QString::fromUtf8(error.what()).isEmpty(); }
    require(rejected, "Expected an explicit nonempty error");
}
QJsonObject success(genform::Session &session, const QString &command, const QJsonObject &arguments = {}) {
    const auto reply = session.execute(command, arguments);
    require(reply.value("ok").toBool(), command + ": " + QString::fromUtf8(QJsonDocument(reply).toJson(QJsonDocument::Compact)));
    return reply;
}
QJsonObject feature(const QString &identifier, const QString &kind, const QJsonObject &params) {
    return {{"id", identifier}, {"type", kind}, {"params", params}, {"suppressed", false}};
}
QJsonObject rectangle(double width = 20, double height = 10) {
    return {{"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"w", width}, {"h", height}}}}};
}
QJsonObject step(const QString &command, const QJsonObject &arguments = {}, const QString &alias = {}) {
    QJsonObject result{{"cmd", command}, {"args", arguments}};
    if (!alias.isEmpty()) result["as"] = alias;
    return result;
}
void writeBytes(const QString &path, const QByteArray &bytes) {
    QFile file(path);
    require(file.open(QIODevice::WriteOnly) && file.write(bytes) == bytes.size(), "Cannot write fixture " + path);
}
QByteArray readBytes(const QString &path) {
    QFile file(path);
    require(file.open(QIODevice::ReadOnly), "Cannot read fixture " + path);
    return file.readAll();
}

void documentMetadataRoundtrip() {
    QTemporaryDir temporary;
    require(temporary.isValid(), "Temporary directory unavailable");
    genform::Document document;
    document.add("variables", {{"values", QJsonObject{{"thickness", 4}}}});
    const auto identifier = document.add("extrude", {{"distance", "=thickness"}}, QString::fromUtf8("卡爪"));
    const QJsonObject process{{"id", "laser"}, {"kind", "plate"}, {"spec", "4 mm blank"},
        {"alternatives", QJsonArray{QJsonObject{{"id", "cnc3"}}}}};
    document.setProcesses({{identifier, process}});
    document.setFolder({identifier}, " Lock\\ Claw // ");
    document.setProp("material", "migration-fixture");
    document.setProp("feature_colors", QJsonObject{{identifier, "#123456"}});
    document.rollback(1);
    const auto original = document.toData();
    const auto revision = document.revision;
    const auto path = temporary.filePath(QString::fromUtf8("零件.gform"));
    document.save(path);
    require(!document.dirty && document.path == path && document.revision == revision, "Save changed revision or left document dirty");
    genform::Document loaded;
    loaded.open(path);
    require(loaded.toData() == original && loaded.path == path, "Document roundtrip changed data or path");
    require(loaded.find(identifier).value("process").toObject() == process, "Nested process metadata was lost");
    require(loaded.find(identifier).value("folder") == "Lock/Claw", "Folder was not normalized or preserved");
    require(!loaded.canUndo() && !loaded.canRedo() && !loaded.dirty && loaded.upto == 1, "Open did not restore clean history and rollback");
    loaded.save();
    genform::Document savedAgain;
    savedAgain.open(path);
    require(savedAgain.toData() == original, "Save without path changed reopened document");
    auto source = original;
    genform::Document detached;
    detached.loadData(source);
    auto rows = source.value("features").toArray();
    auto changed = rows[1].toObject();
    auto changedProcess = changed.value("process").toObject();
    changedProcess["alternatives"] = QJsonArray{QJsonObject{{"id", "changed"}}};
    changed["process"] = changedProcess;
    rows[1] = changed;
    source["features"] = rows;
    require(detached.find(identifier).value("process").toObject() == process && loaded.find(identifier).value("process").toObject() == process,
            "Loaded metadata aliases source JSON");
    genform::Document legacy;
    legacy.loadData({{"format", "genform-document"}, {"version", 1},
                     {"features", QJsonArray{feature("f12", "extrude", {{"distance", 4}})}}});
    require(!legacy.find("f12").contains("process") && !legacy.find("f12").contains("folder"), "Legacy documents gained optional metadata");
    require(legacy.find("f12").value("name") == "f12", "Legacy unnamed feature did not get identifier fallback");
    require(legacy.add("sketch", rectangle()) == "f13", "Legacy serial inference reused an identifier");
}

void documentHistoryAndRollback() {
    genform::Document document;
    const auto first = document.add("sketch", rectangle());
    const auto second = document.add("extrude", {{"sketch", first}, {"distance", 5}, {"op", "add"}});
    document.edit(second, {{"distance", 7}});
    require(document.find(second).value("params").toObject().value("sketch") == first, "Edit replaced rather than merged parameters");
    document.undo();
    near(document.find(second).value("params").toObject().value("distance").toDouble(), 5);
    document.redo();
    near(document.find(second).value("params").toObject().value("distance").toDouble(), 7);
    document.rename(second, "  Plate  ");
    require(document.find(second).value("name") == "Plate", "Rename did not trim whitespace");
    document.suppress(second);
    require(document.find(second).value("suppressed").toBool(), "Suppression was not stored");
    document.undo();
    require(!document.find(second).value("suppressed").toBool(), "Undo did not restore suppression");
    document.rollback(1);
    const auto inserted = document.add("sketch", rectangle(4, 3));
    require(document.upto == 2 && document.features[1].toObject().value("id") == inserted && document.features[2].toObject().value("id") == second,
            "Adding during rollback did not insert at the active prefix");
    document.remove(first);
    require(document.upto == 1 && document.last("extrude") == second, "Delete did not adjust rollback or last feature lookup");
    document.undo();
    require(document.upto == 2 && document.features.size() == 3, "Undo did not restore rollback and deleted feature");
    document.undo();
    require(document.upto == 1 && document.features.size() == 2, "Undo did not remove rollback insertion");
    const auto fresh = document.add("sketch", rectangle());
    require(fresh != inserted && !document.canRedo(), "Branch after undo reused identifier or retained redo history");
    document.rollback(999);
    require(!document.upto.has_value(), "Rollback beyond end must return to full history");
    const auto before = document.toData();
    const auto revision = document.revision;
    rejects([&] { document.rollback(-1); });
    require(document.toData() == before && document.revision == revision, "Rejected rollback modified document");
    document.clear();
    require(document.features.isEmpty() && document.props.isEmpty() && document.path.isEmpty() && !document.upto && !document.dirty && !document.canUndo() && !document.canRedo(),
            "Clear retained document data, dirty state or history");
    rejects([&] { document.undo(); });
    rejects([&] { document.redo(); });
    require(document.add("sketch", rectangle()) == "f1", "New document did not reset serial");
}

void documentAtomicFailures() {
    QTemporaryDir temporary;
    require(temporary.isValid(), "Temporary directory unavailable");
    genform::Document document;
    const auto identifier = document.add("sketch", rectangle());
    document.rename(identifier, "original");
    document.undo();
    document.setProp("material", "preserved");
    const auto path = temporary.filePath("original.gform");
    document.save(path);
    const auto before = document.toData();
    const auto revision = document.revision;
    const auto undoAvailable = document.canUndo();
    const auto redoAvailable = document.canRedo();
    const auto untouched = [&] {
        require(document.toData() == before && document.revision == revision && document.path == path && !document.dirty &&
                document.canUndo() == undoAvailable && document.canRedo() == redoAvailable, "Rejected operation changed data, path, revision or history");
    };
    const QJsonArray malformed{
        QJsonObject{{"format", "other"}, {"features", QJsonArray{}}},
        QJsonObject{{"format", "genform-document"}, {"version", 2}, {"features", QJsonArray{}}},
        QJsonObject{{"format", "genform-document"}, {"version", 1}},
        QJsonObject{{"format", "genform-document"}, {"features", QJsonArray{42}}},
        QJsonObject{{"format", "genform-document"}, {"features", QJsonArray{feature("dup", "sketch", {}), feature("dup", "sketch", {})}}},
        QJsonObject{{"format", "genform-document"}, {"features", QJsonArray{QJsonObject{{"id", "missing-params"}, {"type", "sketch"}}}}},
        QJsonObject{{"format", "genform-document"}, {"features", QJsonArray{}}, {"upto", -1}},
        QJsonObject{{"format", "genform-document"}, {"features", QJsonArray{}}, {"upto", 0.5}}
    };
    for (const auto &invalid : malformed) { rejects([&] { document.loadData(invalid.toObject()); }); untouched(); }
    rejects([&] { document.rename(identifier, "   "); }); untouched();
    rejects([&] { document.setFolder({identifier, "missing"}, "changed"); }); untouched();
    rejects([&] { document.setProcesses({{identifier, QJsonObject{{"id", "laser"}}}, {"missing", QJsonObject{{"id", "cnc3"}}}}); }); untouched();
    rejects([&] { document.remove("missing"); }); untouched();
    const auto corrupt = temporary.filePath("broken.gform");
    writeBytes(corrupt, "{not-json");
    rejects([&] { document.open(corrupt); }); untouched();
    writeBytes(corrupt, "[]");
    rejects([&] { document.open(corrupt); }); untouched();
    rejects([&] { document.open(temporary.filePath("missing.gform")); }); untouched();
    rejects([&] { document.save(temporary.filePath("missing/subdir/part.gform")); }); untouched();
    require(QJsonDocument::fromJson(readBytes(path)).object() == before, "Failed save damaged the previous file");
    document.redo();
    require(document.find(identifier).value("name") == "original", "Failure discarded a usable redo snapshot");
}

void expressionsAndValueIsolation() {
    using genform::kernel::native::evaluate;
    using genform::kernel::native::resolve;
    near(evaluate("-2^2 + 2**3**2"), 508);
    near(evaluate("2^-2 + 1e-3"), 0.251);
    near(evaluate("(-3)%2"), 1);
    near(evaluate("3%-2"), -1);
    near(evaluate("degrees(atan2(1, 1)) + sqrt(9) + max(2, 7, 4)"), 55);
    near(evaluate("H / 2 + W", {{"H", 20}, {"W", 3}}), 13);
    near(evaluate("sin(pi/2) + cos(0) + log(8,2)"), 5);
    const QJsonObject input{{"distance", " =H/2 + 1 "}, {"name", "not an expression"},
        {"nested", QJsonArray{QJsonObject{{"radius", "=H/4"}}, true, QJsonValue::Null}}};
    const auto resolved = resolve(input, {{"H", 20}}).toObject();
    near(resolved.value("distance").toDouble(), 11);
    near(resolved.value("nested").toArray()[0].toObject().value("radius").toDouble(), 5);
    require(resolved.value("name") == input.value("name") && resolved.value("nested").toArray()[1] == true && resolved.value("nested").toArray()[2].isNull(),
            "Expression resolution changed non-expression values");
    require(input.value("distance").isString() && input.value("nested").toArray()[0].toObject().value("radius").isString(), "Resolver mutated source JSON");
    for (const auto &expression : QStringList{"Q + 1", "1/0", "1%0", "sqrt(-1)", "pow(10, 999)", "sin()", "unknown(1)", "1 trailing", "(2+3", "__import__('os')", "H.value"})
        rejects([&] { evaluate(expression); });
    rejects([&] { evaluate(QString(16385, '1')); });
    rejects([&] { evaluate(QString(140, '(') + "1" + QString(140, ')')); });
    const auto variables = genform::features::clean({{"kind", "vars"}}, "D = 112; H = D/2").toObject();
    require(variables.value("D").toDouble() == 112 && variables.value("H") == "=D/2", "Variable form parser lost formulas");
    require(genform::features::clean({{"kind", "number"}}, "=H-3") == "=H-3", "Number form parser evaluated formula prematurely");
}

void sessionCommandContracts() {
    genform::Session session;
    const auto unchanged = session.document.toData();
    const QJsonArray invalid{
        step("extrud"), step("extrude"), step("extrude", {{"distance", 1}, {"depth", 2}}),
        step("extrude", {{"distance", 5}}), step("delete_feature", {{"id", "missing"}}),
        step("sketch", {{"shapes", "not an array"}}), step("query", {{"what", "missing-query"}}),
        step("screenshot"), step("set_view", {{"view", "top"}})
    };
    for (const auto &value : invalid) {
        const auto operation = value.toObject();
        const auto reply = session.execute(operation.value("cmd").toString(), operation.value("args").toObject());
        require(!reply.value("ok").toBool() && !reply.value("error").toString().isEmpty(), "Invalid command did not return an explicit error");
        require(session.document.toData() == unchanged && !session.document.canUndo() && !session.busy, "Invalid command left partial document changes");
    }
    const auto identifier = success(session, "sketch", rectangle()).value("id").toString();
    const auto full = success(session, "get_model");
    require(full.value("features").toArray().size() == 1 && full.value("features").toArray()[0].toObject().contains("params") && full.contains("materials"),
            "Full model reply dropped feature parameters or material catalog");
    const auto brief = success(session, "get_model", {{"brief", true}});
    require(!brief.value("features").toArray()[0].toObject().contains("params") && !brief.contains("materials"), "Brief model reply still contains large fields");
    const auto single = success(session, "get_model", {{"brief", true}, {"id", identifier}});
    require(single.value("features").toArray().size() == 1 && single.value("features").toArray()[0].toObject().contains("params"), "Single-feature lookup lost parameters");
    require(!session.execute("get_model", {{"id", "missing"}}).value("ok").toBool(), "Unknown feature lookup succeeded");
    const auto model = session.model;
    int progressCount = 0;
    QObject::connect(&session, &genform::Session::progress, &session, [&](int, int, const QString &) { ++progressCount; });
    success(session, "rename_feature", {{"id", identifier}, {"name", "Renamed"}});
    success(session, "set_folder", {{"features", QJsonArray{identifier}}, {"folder", "Assembly/Base"}});
    require(progressCount == 0 && session.model == model && !success(session, "get_model").value("model_stale").toBool(),
            "Non-geometric metadata edit rebuilt or invalidated geometry");
    session.selection = {{"feature", identifier}, {"edges", QJsonArray{99}}, {"faces", QJsonArray{88}}};
    success(session, "delete_feature", {{"id", identifier}});
    require(session.selection.value("feature").isNull() && session.selection.value("edges").toArray().isEmpty() && session.selection.value("faces").toArray().isEmpty(),
            "Rebuild retained deleted feature or obsolete topology selection");
    session.viewCommand = [](const QString &command, const QJsonObject &arguments) {
        if (command == "screenshot") return QJsonObject{{"mimeType", "image/png"}, {"data", "native-test-image"}};
        return QJsonObject{{"view", arguments.value("view")}};
    };
    require(success(session, "set_view", {{"view", "top"}}).value("view") == "top", "View callback did not receive arguments");
    require(success(session, "screenshot").value("data") == "native-test-image", "Screenshot route lost callback payload");
}

void sessionBatchHistoryAndAtomicity() {
    genform::Session session;
    const auto identifier = success(session, "sketch", rectangle()).value("id").toString();
    success(session, "rename_feature", {{"id", identifier}, {"name", "before-undo"}});
    success(session, "undo");
    const auto original = session.document.toData();
    const auto originalRevision = session.document.revision;
    const auto originalModel = session.model;
    session.selection = {{"feature", identifier}, {"edges", QJsonArray{4}}, {"faces", QJsonArray{2}}};
    const auto originalSelection = session.selection;
    const auto checkFailed = [&](const QJsonArray &steps) {
        const auto reply = session.execute("batch", {{"steps", steps}});
        require(!reply.value("ok").toBool() && !reply.value("error").toString().isEmpty(), "Invalid batch did not fail explicitly");
        require(session.document.toData() == original && session.document.revision == originalRevision && session.document.canRedo() &&
                session.model == originalModel && session.selection == originalSelection, "Failed batch changed data, revision, redo, model or selection");
    };
    for (const auto &invalid : QJsonArray{step("extrude"), step("sketch", {{"shapes", QJsonArray{}}, {"unknown", 1}}),
            step("extrude", {{"distance", "invalid"}}), step("rename_feature", {{"id", "$missing"}, {"name", "bad"}}),
            step("delete_feature", {{"id", "missing"}}), step("set_appearance", {{"color", "#123456"}})}) {
        checkFailed({step("rename_feature", {{"id", identifier}, {"name", "temporary"}}), invalid});
    }
    QJsonArray longBatch;
    for (int index = 0; index < 205; ++index) longBatch.append(step("rename_feature", {{"id", identifier}, {"name", QString("temporary-%1").arg(index)}}));
    longBatch.append(step("delete_feature", {{"id", "missing"}}));
    checkFailed(longBatch);
    checkFailed({step("edit_feature", {{"id", identifier}, {"params", QJsonObject{{"offset", 12}}}}),
        step("suppress_feature", {{"id", identifier}}), step("rollback", {{"count", 0}}), step("delete_feature", {{"id", identifier}}),
        step("rename_feature", {{"id", "missing"}, {"name", "bad"}})});
    success(session, "redo");
    require(session.document.find(identifier).value("name") == "before-undo", "Batch failure lost original redo history");
    success(session, "undo");
    const auto made = success(session, "batch", {{"steps", QJsonArray{step("sketch", rectangle(3, 2), "profile"),
        step("set_folder", {{"features", QJsonArray{"$profile"}}, {"folder", "Batch/Profiles"}}),
        step("rename_feature", {{"id", "$1"}, {"name", "Batch profile"}})}}});
    const auto identifiers = made.value("ids").toArray();
    require(identifiers.size() == 3 && identifiers[0].isString(), "Batch did not retain one result per step");
    const auto created = identifiers[0].toString();
    require(session.document.find(created).value("folder") == "Batch/Profiles" && session.document.find(created).value("name") == "Batch profile",
            "Nested array or positional batch reference was not resolved");
    success(session, "undo");
    require(session.document.find(created).value("name") != "Batch profile", "Successful batch did not retain per-step rename history");
    success(session, "undo");
    require(!session.document.find(created).contains("folder"), "Successful batch did not retain folder history");
    success(session, "undo");
    require(session.document.features.size() == 1, "Successful batch did not retain feature insertion history");
}

void materialsAppearanceAndProcesses() {
    genform::Session session;
    const auto identifier = success(session, "sketch", rectangle()).value("id").toString();
    const auto materials = success(session, "query", {{"what", "materials"}}).value("materials").toArray();
    require(!materials.isEmpty(), "Missing material catalog");
    const auto material = materials.first().toObject().value("name").toString();
    success(session, "set_material", {{"name", material}});
    require(session.document.props.value("material") == material, "Material selection was not stored");
    require(!session.execute("set_material", {{"name", "not-a-material"}}).value("ok").toBool() && session.document.props.value("material") == material,
            "Invalid material replaced valid metadata");
    const auto density = genform::domain::density(material);
    require(density.has_value(), "Catalog material has no density");
    near(*genform::domain::mass_grams(1000, material), *density);
    require(!genform::domain::mass_grams(1000, "not-a-material"), "Unknown material produced a fabricated mass");
    success(session, "set_appearance", {{"features", QJsonArray{identifier}}, {"color", "#203040"}, {"opacity", 0.3}});
    success(session, "set_appearance", {{"features", QJsonArray{identifier}}, {"opacity", 0.5}});
    require(session.document.props.value("feature_colors").toObject().value(identifier) == "#203040", "Opacity-only edit removed existing color");
    const auto appearance = session.document.props;
    for (const auto &arguments : QJsonArray{QJsonObject{{"features", QJsonArray{identifier}}, {"opacity", 0}},
            QJsonObject{{"features", QJsonArray{identifier}}, {"color", "bad-color"}},
            QJsonObject{{"features", QJsonArray{identifier, "missing"}}, {"color", "#112233"}}}) {
        require(!session.execute("set_appearance", arguments.toObject()).value("ok").toBool() && session.document.props == appearance, "Rejected appearance partially modified metadata");
    }
    success(session, "set_appearance", {{"features", QJsonArray{identifier}}, {"opacity", 1}});
    require(!session.document.props.contains("feature_opacity") && session.document.props.value("feature_colors").toObject().value(identifier) == "#203040",
            "Opaque reset did not remove opacity override independently");
    success(session, "set_appearance", {{"features", QJsonArray{identifier}}, {"color", ""}});
    require(!session.document.props.contains("feature_colors"), "Empty color did not clear override");
    success(session, "set_process", {{"feature", identifier}, {"process", "waterjet"}, {"cost", 12.5}});
    const auto process = session.document.find(identifier).value("process").toObject();
    require(process.value("id") == "waterjet" && process.value("auto") == false, "Manual process metadata is missing");
    near(process.value("cost").toDouble(), 12.5);
    for (const auto &arguments : QJsonArray{QJsonObject{{"feature", identifier}, {"process", "waterjet"}, {"cost", -1}},
            QJsonObject{{"feature", identifier}, {"process", "unknown"}}}) {
        require(!session.execute("set_process", arguments.toObject()).value("ok").toBool() && session.document.find(identifier).value("process").toObject() == process,
                "Rejected process assignment modified prior process");
    }
    success(session, "set_design_rules", {{"values", QJsonObject{{"clearance", 0.2}, {"batch", 100}}}});
    const auto rules = session.document.props.value("rules").toObject();
    near(success(session, "get_design_rules").value("rules").toObject().value("clearance").toDouble(), 0.2);
    require(!session.execute("set_design_rules", {{"values", QJsonObject{{"not-a-rule", 5}}}}).value("ok").toBool() && session.document.props.value("rules").toObject() == rules,
            "Unrecognized rules silently changed document");
    success(session, "set_process", {{"feature", identifier}, {"process", ""}});
    require(!session.document.find(identifier).contains("process"), "Clearing a process retained optional metadata");
    success(session, "set_material", {{"name", ""}});
    require(!session.document.props.contains("material"), "Clearing material retained a stale value");
}

void billFilesAndCsv() {
    QTemporaryDir temporary;
    require(temporary.isValid(), "Temporary directory unavailable");
    genform::Document custom;
    const auto sketch = custom.add("sketch", rectangle());
    const auto body = custom.add("extrude", {{"sketch", sketch}, {"distance", 4}});
    const auto disabled = custom.add("extrude", {{"sketch", sketch}, {"distance", 2}});
    custom.setProcesses({{sketch, QJsonObject{{"id", "cnc3"}, {"cost", 1000}}},
        {body, QJsonObject{{"id", "laser"}, {"name", "Laser"}, {"spec", "4 mm blank"}, {"cost", 12.5}, {"standard", false}}},
        {disabled, QJsonObject{{"id", "cnc3"}, {"cost", 2000}}}});
    custom.suppress(disabled);
    custom.setProp("material", "fixture-material");
    const auto path = temporary.filePath("plate.gform");
    custom.save(path);
    const auto description = genform::domain::describe(path);
    require(description == genform::domain::describe_document(custom.toData()) && description.value("kind") == "custom" && description.value("bound").toBool(),
            "File metadata differs from document metadata");
    near(description.value("unit").toDouble(), 12.5);
    require(description.value("spec") == "4 mm blank" && description.value("material") == "fixture-material", "Description lost process spec or material");
    auto standard = custom;
    standard.setProcesses({{body, QJsonObject{{"id", "standard"}, {"name", "Catalog"}, {"spec", "M4"}, {"cost", 2}, {"standard", true}}}});
    const auto standardPath = temporary.filePath("screw.gform");
    standard.save(standardPath);
    const QJsonArray parts{QJsonObject{{"path", path}, {"name", "Plate, \"left\""}}, QJsonObject{{"path", path}, {"name", "duplicate"}},
        QJsonObject{{"path", path}, {"name", "mirror"}, {"mirror", true}}, QJsonObject{{"path", standardPath}, {"name", "Screw"}},
        QJsonObject{{"path", standardPath}, {"name", "mirrored screw"}, {"mirror", true}}};
    const auto rows = genform::domain::bill(parts);
    require(rows.size() == 3, "BOM must split custom mirrored parts but merge standard mirrored parts");
    int counted = 0;
    for (const auto &value : rows) counted += value.toObject().value("count").toInt();
    require(counted == parts.size(), "BOM grouping lost component counts");
    const auto totals = genform::domain::bill_totals(rows);
    require(totals.value("all").toObject().value("count").toInt() == 5 && totals.value("all").toObject().value("types").toInt() == 3 && totals.value("unbound").toInt() == 0,
            "BOM totals disagree with grouped rows");
    near(totals.value("all").toObject().value("cost").toDouble(), 41.5);
    const auto csv = genform::domain::bill_csv(rows);
    require(csv.startsWith(QByteArray::fromHex("efbbbf")) && csv.contains("\"Plate, \"\"left\"\"\""), "CSV is missing UTF-8 BOM or escaped quote/comma");
    require(csv.count("\r\n") == rows.size() + 1, "CSV header/data row count mismatch");
    require(!genform::domain::describe(temporary.filePath("missing.gform")).value("bound").toBool(), "Missing document claimed manufacturing metadata");
}

void unknownDocumentFeatureIsRejected() {
    genform::Document document;
    document.add("sketch", rectangle());
    const auto original = document.toData();
    const auto revision = document.revision;
    rejects([&] { document.add("unknown-feature", {}); });
    require(document.toData() == original && document.revision == revision, "Unknown document feature changed serial or history");
}

void emptyBatchIsANoop() {
    genform::Session session;
    success(session, "sketch", rectangle());
    const auto original = session.document.toData();
    const auto revision = session.document.revision;
    const auto model = session.model;
    const auto reply = success(session, "batch", {{"steps", QJsonArray{}}});
    require(reply.value("ids").toArray().isEmpty() && reply.value("count").toInt(-1) == 0 && session.document.toData() == original &&
            session.document.revision == revision && session.model == model, "Empty batch must return zero results without mutation or rebuild");
}

void compactChangeReplies() {
    genform::Session session;
    const auto first = success(session, "sketch", rectangle()).value("id").toString();
    const auto reply = success(session, "sketch", rectangle(4, 3));
    const auto rows = reply.value("model").toObject().value("features").toArray();
    require(rows.size() == 2 && !rows[0].toObject().contains("params") && rows[1].toObject().contains("params"),
            "Change reply must omit old feature parameters and retain new feature parameters");
    const auto renamed = success(session, "rename_feature", {{"id", first}, {"name", "compact"}});
    for (const auto &value : renamed.value("model").toObject().value("features").toArray())
        require(!value.toObject().contains("params"), "Rename reply must not resend feature parameter trees");
}

QJsonArray plateFeatures(double width = 20, double height = 10, double distance = 5) {
    return {feature("profile", "sketch", rectangle(width, height)),
        feature("body", "extrude", {{"sketch", "profile"}, {"distance", distance}})};
}
void kernelOk(const QJsonObject &model, const QString &identifier) {
    const auto status = model.value("status").toObject().value(identifier).toString();
    require(status == "ok", identifier + ": " + status);
}
double volume(const QJsonObject &model) { return model.value("props").toObject().value("volume").toDouble(); }

void expressionFeatureRoundtrip() {
    genform::Session session;
    const auto variables = success(session, "variables", {{"values", QJsonObject{{"H", 20}, {"W", "=H*2"}, {"A", "=Z/2"}, {"Z", 6}}}}).value("id").toString();
    const auto profile = success(session, "sketch", rectangle(20, 20)).value("id").toString();
    const auto body = success(session, "extrude", {{"sketch", profile}, {"distance", 5}}).value("id").toString();
    success(session, "edit_feature", {{"id", body}, {"params", QJsonObject{{"distance", "=H/2 + 1"}}}});
    near(volume(session.model), 4400);
    success(session, "set_process", {{"feature", body}, {"process", "waterjet"}, {"cost", 9.75}});
    const auto process = session.document.find(body).value("process");
    QTemporaryDir temporary;
    require(temporary.isValid(), "Temporary directory unavailable");
    const auto path = temporary.filePath("formula.gform");
    success(session, "save_document", {{"path", path}});
    genform::Session reopened;
    success(reopened, "open_document", {{"path", path}});
    near(volume(reopened.model), 4400);
    require(reopened.document.find(body).value("process") == process && reopened.document.find(body).value("params").toObject().value("distance").isString(),
            "Formula save/open lost process metadata or source expression");
    const auto bad = reopened.execute("edit_feature", {{"id", body}, {"params", QJsonObject{{"distance", "=Unknown+1"}}}});
    require(!bad.value("ok").toBool() && reopened.model.value("status").toObject().value(body).toString().startsWith("error:"), "Unknown variable was not attached to failing feature");
    success(reopened, "edit_feature", {{"id", body}, {"params", QJsonObject{{"distance", "=A+1"}}}});
    near(volume(reopened.model), 1600);
    const auto cycle = reopened.execute("edit_feature", {{"id", variables}, {"params", QJsonObject{{"values", QJsonObject{{"H", "=Z"}, {"Z", "=H"}}}}}});
    require(!cycle.value("ok").toBool() && reopened.model.value("status").toObject().value(variables).toString().startsWith("error:") &&
            reopened.model.value("status").toObject().value(body) == "skipped", "Cyclic variables did not fail at variable feature and skip dependents");
}

void manufacturingCommandIntegration() {
    genform::Session session;
    success(session, "sketch", rectangle(80, 50));
    const auto body = success(session, "extrude", {{"distance", 3}}).value("id").toString();
    success(session, "set_process", {{"feature", body}, {"process", "waterjet"}, {"cost", 9.75}});
    const auto process = session.document.find(body).value("process");
    const auto revision = session.document.revision;
    int builds = 0;
    QObject::connect(&session, &genform::Session::progress, &session, [&](int, int, const QString &) { ++builds; });
    success(session, "bind_processes");
    require(session.document.find(body).value("process") == process && builds == 0 && session.document.revision == revision,
            "Rebinding rebuilt geometry or replaced manual process");
    const auto checked = success(session, "check_design");
    require(checked.value("issues").isArray() && checked.value("counts").isObject() && checked.value("red").isArray(), "Design check returned an incomplete report");
}

void sessionGeometryRecoveryAndExport() {
    genform::Session session;
    const auto profile = success(session, "sketch", rectangle(40, 30)).value("id").toString();
    const auto body = success(session, "extrude", {{"distance", 10}}).value("id").toString();
    near(volume(session.model), 12000);
    const auto failed = session.execute("fillet", {{"edges", "|Z"}, {"radius", 80}});
    const auto fillet = failed.value("id").toString();
    require(!failed.value("ok").toBool() && !fillet.isEmpty() && !failed.value("hint").toString().isEmpty() && session.document.features.size() == 3,
            "Failed feature must remain editable with identifier and recovery hint");
    near(volume(session.model), 12000);
    QTemporaryDir temporary;
    require(temporary.isValid(), "Temporary directory unavailable");
    const auto blocked = temporary.filePath("failed.step");
    require(!session.execute("export", {{"path", blocked}}).value("ok").toBool() && !QFileInfo::exists(blocked), "Export silently wrote prefix of failed document");
    success(session, "edit_feature", {{"id", fillet}, {"params", QJsonObject{{"radius", 2}}}});
    const auto roundedVolume = volume(session.model);
    require(roundedVolume < 12000 && roundedVolume > 0, "Fixing failed fillet did not produce geometry");
    success(session, "suppress_feature", {{"id", fillet}, {"suppressed", true}});
    near(volume(session.model), 12000);
    success(session, "undo");
    near(volume(session.model), roundedVolume);
    success(session, "rollback", {{"count", 2}});
    near(volume(session.model), 12000);
    require(session.model.value("status").toObject().value(fillet) == "skipped", "Rollback did not mark later feature skipped");
    success(session, "rollback");
    near(volume(session.model), roundedVolume);
    success(session, "edit_feature", {{"id", body}, {"params", QJsonObject{{"distance", 25}}}});
    near(session.model.value("props").toObject().value("size").toArray()[2].toDouble(), 25);
    require(!success(session, "list_edges").value("edges").toArray().isEmpty() && !success(session, "list_faces").value("faces").toArray().isEmpty(),
            "Topology routes returned no references after edit");
    const auto saved = temporary.filePath("plate.gform");
    success(session, "save_document", {{"path", saved}});
    const auto expected = session.document.toData();
    success(session, "new_document");
    require(!session.model.value("has_body").toBool(), "New document retained previous body");
    success(session, "open_document", {{"path", saved}});
    require(session.document.toData() == expected && session.document.last("sketch") == profile, "Session document file roundtrip changed history data");
    const auto exported = temporary.filePath("plate.step");
    success(session, "export", {{"path", exported}});
    require(QFileInfo(exported).size() > 500, "STEP export did not write a substantive model");
    require(!session.execute("export", {{"path", temporary.filePath("unsupported.xyz")}}).value("ok").toBool(), "Unsupported export format succeeded");
}

void importSourceRefreshAndRoundtrip() {
    QTemporaryDir temporary;
    require(temporary.isValid(), "Temporary directory unavailable");
    const auto path = temporary.filePath("source.step");
    genform::kernel::Kernel writer;
    kernelOk(writer.build(plateFeatures()), "body");
    writer.exportFile(path);
    const auto originalBytes = readBytes(path);
    const QJsonArray imported{feature("imported", "import_step", {{"path", path}})};
    genform::kernel::Kernel reader;
    auto model = reader.build(imported);
    kernelOk(model, "imported");
    near(volume(model), 1000, 1e-3);
    kernelOk(writer.build(plateFeatures(20, 10, 12)), "body");
    writer.exportFile(path);
    require(readBytes(path) != originalBytes, "Updated STEP fixture did not change source bytes");
    model = reader.build(imported);
    kernelOk(model, "imported");
    near(volume(model), 2400, 1e-3);
    genform::kernel::Kernel coldReader;
    near(volume(coldReader.build(imported)), 2400, 1e-3);
    auto cut = imported;
    cut.append(feature("cut-profile", "sketch", {{"offset", 12}, {"shapes", QJsonArray{QJsonObject{{"type", "circle"}, {"r", 2}}}}}));
    cut.append(feature("cut", "extrude", {{"sketch", "cut-profile"}, {"distance", -4}, {"op", "cut"}}));
    model = reader.build(cut);
    kernelOk(model, "cut");
    near(volume(model), 2400 - std::acos(-1.0) * 16, 1e-3);
    require(QFile::remove(path), "Cannot remove source fixture");
    model = reader.build(imported);
    require(model.value("status").toObject().value("imported").toString().startsWith("error:") && !model.value("has_body").toBool(),
            "Deleted import source reused stale geometry");
}

void sessionBatchGeometryFailureAndRepair() {
    genform::Session session;
    int progressCount = 0;
    QObject::connect(&session, &genform::Session::progress, &session, [&](int, int, const QString &) { ++progressCount; });
    const auto reply = session.execute("batch", {{"steps", QJsonArray{step("sketch", rectangle(), "profile"),
        step("extrude", {{"sketch", "$profile"}, {"distance", 5}}, "body"), step("fillet", {{"edges", "|Z"}, {"radius", 80}})}}});
    const auto identifiers = reply.value("ids").toArray();
    require(!reply.value("ok").toBool() && identifiers.size() == 3 && reply.value("count").toInt() == 3 && !reply.value("hint").toString().isEmpty(),
            "Geometry-failed batch discarded feature ids or recovery information");
    require(progressCount == 2 && session.document.features.size() == 3, "Batch must build once after all commands and retain failed features");
    const auto failedId = identifiers[2].toString();
    require(session.model.value("status").toObject().value(failedId).toString().startsWith("error:"), "Geometry failure was not attached to the bad batch feature");
    near(volume(session.model), 1000);
    success(session, "undo");
    require(session.document.features.size() == 2, "Undo after geometry-failed batch removed more than final feature");
    near(volume(session.model), 1000);
    const auto redone = session.execute("redo");
    require(!redone.value("ok").toBool() && session.document.features.size() == 3 &&
            session.model.value("status").toObject().value(failedId).toString().startsWith("error:"), "Redo did not reproduce retained geometry failure");
}

void profileNestingBoundaryRegressions() {
    genform::kernel::Kernel kernel;
    const auto area = [&](const QJsonArray &shapes) {
        const auto model = kernel.build({feature("profile", "sketch", {{"shapes", shapes}}),
            feature("solid", "extrude", {{"sketch", "profile"}, {"distance", 1}})});
        kernelOk(model, "solid");
        return volume(model);
    };
    near(area({QJsonObject{{"type", "rect"}, {"w", 10}, {"h", 10}},
        QJsonObject{{"type", "rect"}, {"cx", 10.0000000001}, {"w", 10}, {"h", 10}},
        QJsonObject{{"type", "rect"}, {"cx", 20}, {"w", 10}, {"h", 10}}}), 300, 1e-5);
    for (const double centerY : {0.0, -3.0})
        near(area({QJsonObject{{"type", "rect"}, {"w", 10}, {"h", 10}},
            QJsonObject{{"type", "rect"}, {"cx", 2.5}, {"cy", centerY}, {"w", 5}, {"h", 4}}}), 80, 1e-5);
    near(area({QJsonObject{{"type", "circle"}, {"r", 10}}, QJsonObject{{"type", "circle"}, {"r", 6}},
        QJsonObject{{"type", "circle"}, {"r", 3}}}), std::acos(-1.0) * 73, 1e-4);
}

void booleanFailurePreservesPrefix() {
    genform::kernel::Kernel kernel;
    for (const auto &operation : QStringList{"cut", "common"}) {
        auto features = plateFeatures();
        features.append(feature("remote-profile", "sketch", {{"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"cx", 100}, {"w", 2}, {"h", 2}}}}}));
        features.append(feature("bad", "extrude", {{"sketch", "remote-profile"}, {"distance", 2}, {"op", operation}}));
        features.append(feature("later", "extrude", {{"sketch", "profile"}, {"distance", 10}}));
        const auto model = kernel.build(features);
        kernelOk(model, "body");
        require(model.value("status").toObject().value("bad").toString().startsWith("error:") && model.value("status").toObject().value("later") == "skipped",
                "No-op cut or empty common failed to stop downstream rebuild");
        near(volume(model), 1000);
        const auto inspected = kernel.query("inspect");
        require(!inspected.value("tools").toObject().contains("bad"), "Failed boolean leaked tool into inspect result");
    }
}
}

int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    const std::pair<const char *, std::function<void()>> tests[]{
        {"documentMetadataRoundtrip", documentMetadataRoundtrip},
        {"documentHistoryAndRollback", documentHistoryAndRollback},
        {"documentAtomicFailures", documentAtomicFailures},
        {"expressionsAndValueIsolation", expressionsAndValueIsolation},
        {"sessionCommandContracts", sessionCommandContracts},
        {"sessionBatchHistoryAndAtomicity", sessionBatchHistoryAndAtomicity},
        {"materialsAppearanceAndProcesses", materialsAppearanceAndProcesses},
        {"billFilesAndCsv", billFilesAndCsv},
        {"unknownDocumentFeatureIsRejected", unknownDocumentFeatureIsRejected},
        {"emptyBatchIsANoop", emptyBatchIsANoop},
        {"compactChangeReplies", compactChangeReplies},
        {"expressionFeatureRoundtrip", expressionFeatureRoundtrip},
        {"manufacturingCommandIntegration", manufacturingCommandIntegration},
        {"sessionGeometryRecoveryAndExport", sessionGeometryRecoveryAndExport},
        {"importSourceRefreshAndRoundtrip", importSourceRefreshAndRoundtrip},
        {"sessionBatchGeometryFailureAndRepair", sessionBatchGeometryFailureAndRepair},
        {"profileNestingBoundaryRegressions", profileNestingBoundaryRegressions},
        {"booleanFailurePreservesPrefix", booleanFailurePreservesPrefix}
    };
    int failures = 0;
    for (const auto &test : tests) {
        try { test.second(); std::cout << "PASS " << test.first << '\n'; }
        catch (const std::exception &error) { ++failures; std::cerr << "FAIL " << test.first << ": " << error.what() << '\n'; }
    }
    std::cout << "Migration regression groups: " << std::size(tests) << ", failures: " << failures << '\n';
    return failures == 0 ? 0 : 1;
}
