#include "genform/session.hpp"
#include "genform/features.hpp"
#include "genform/domain/geometry.hpp"
#include <QCoreApplication>
#include <QJsonDocument>
#include <QSet>
#include <QTemporaryDir>
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
void require(bool condition, const char *message) { if (!condition) throw std::runtime_error(message); }
QJsonObject sketch() { return {{"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"cx", 0}, {"cy", 0}, {"w", 20}, {"h", 10}}}}}; }
QJsonObject step(const QString &command, const QJsonObject &arguments = {}, const QString &alias = {}) {
    QJsonObject result{{"cmd", command}, {"args", arguments}};
    if (!alias.isEmpty()) result["as"] = alias;
    return result;
}
void catalogTests() {
    const auto specs = genform::features::specs();
    require(specs.size() == 37, "Original feature table is incomplete");
    QSet<QString> commands;
    for (const auto &value : genform::features::catalog()) {
        const auto item = value.toObject();
        const auto name = item.value("name").toString();
        require(!commands.contains(name), "Duplicate tool name");
        require(item.value("input_schema").toObject().value("type") == "object", "Invalid tool input schema");
        commands.insert(name);
    }
    for (auto iterator = specs.begin(); iterator != specs.end(); ++iterator) require(commands.contains(iterator.key()), "Feature has no route");
    for (const auto &name : QStringList{"sketch", "extrude", "fillet", "chamfer", "batch", "edit_feature", "delete_feature", "suppress_feature", "rename_feature", "set_folder", "list_processes", "get_design_rules", "set_design_rules", "bind_processes", "set_process", "check_design", "rollback", "set_material", "set_appearance", "undo", "redo", "new_document", "save_document", "load_layout", "open_document", "export", "set_view", "screenshot", "get_model", "list_edges", "list_faces", "get_selection", "query"}) require(commands.contains(name), "Missing original command");
    const auto frame = genform::features::planeFrame("XY", {});
    require(frame.value("origin").toArray().size() == 3, "Invalid plane frame");
    const auto defaults = genform::features::defaultParams("wrap");
    require(defaults.value("mode") == "emboss" && !defaults.contains("kind"), "Original wrap parameters changed");
    const auto cleaned = genform::features::clean({{"kind", "points"}, {"width", 3}}, "1,2,3;4,5,6").toArray();
    require(cleaned.size() == 2 && cleaned[1].toArray()[2] == 6, "Coordinate cleaning failed");
    require(genform::features::clean({{"kind", "number"}}, "=D/2") == "=D/2", "Expression was not preserved");
    require(genform::features::axisOf("Z", {}).value("direction").toArray()[2] == 1, "Native axis resolution failed");
    require(genform::features::curveKinds().size() == 7 && genform::features::toolKinds().contains("extrude"), "Feature classifications changed");
    std::cout << "PASS complete original route catalog and feature defaults\n";
}
#ifndef GENFORM_FEATURE_TABLE_SELFTEST
void mutationContractTests() {
    genform::Document document;
    document.add("sketch", sketch());
    document.undo();
    const auto original = document.toData();
    const auto originalRevision = document.revision;
    bool rejected = false;
    try { document.add("unknown-feature", {}); } catch (const genform::Error &) { rejected = true; }
    require(rejected && document.toData() == original && document.revision == originalRevision && document.canRedo() && !document.canUndo(), "Unknown feature changed document or history");
    document.redo();
    require(document.add("sketch", sketch()) == "f2", "Unknown feature consumed a serial number");

    genform::Session session;
    auto args = sketch();
    args["dims"] = QJsonArray{QJsonObject{{"value", 20}}};
    const auto created = session.execute("sketch", args);
    const auto identifier = created.value("id").toString();
    const auto createdModel = created.value("model").toObject();
    const auto createdParams = createdModel.value("features").toArray().first().toObject().value("params").toObject();
    require(createdParams.value("shapes") == QStringLiteral("1 个图形") && createdParams.value("dims") == QStringLiteral("1 个尺寸") && !createdModel.contains("materials"), "Sketch change reply did not summarize shapes and dimensions");
    const auto fullParams = session.execute("get_model", {{"id", identifier}}).value("features").toArray().first().toObject().value("params").toObject();
    require(fullParams.value("shapes").isArray() && fullParams.value("dims").isArray(), "Compact reply mutated stored sketch parameters");
    const auto renamed = session.execute("rename_feature", {{"id", identifier}, {"name", "Compact"}});
    require(!renamed.value("model").toObject().value("features").toArray().first().toObject().contains("params"), "Rename resent parameters");
    session.execute("undo");
    const auto snapshot = session.document.toData();
    const auto revision = session.document.revision;
    const auto model = session.model;
    int notifications = 0;
    QObject::connect(&session, &genform::Session::changed, &session, [&] { ++notifications; });
    const auto empty = session.execute("batch", {{"steps", QJsonArray{}}});
    require(empty.value("ok").toBool() && empty.value("ids").isArray() && empty.value("ids").toArray().isEmpty() && empty.value("count").toInt(-1) == 0, "Empty batch failed or returned invalid results");
    require(session.document.toData() == snapshot && session.document.revision == revision && session.document.canRedo() && session.model == model && notifications == 0, "Empty batch changed history, model, or notifications");
    session.execute("redo");
    require(session.document.find(identifier).value("name") == "Compact", "Empty batch destroyed redo history");
    session.execute("set_appearance", {{"features", QJsonArray{identifier}}, {"color", "#123456"}});
    const auto brief = session.execute("get_model", {{"brief", true}});
    require(!brief.contains("materials") && !brief.contains("feature_colors") && !brief.value("features").toArray().first().toObject().contains("params"), "Brief model exposed full model metadata");
    const auto batch = session.execute("batch", {{"steps", QJsonArray{step("sketch", sketch(), "new"), step("edit_feature", {{"id", "$new"}, {"params", QJsonObject{{"offset", 3}}}})}}});
    const auto rows = batch.value("model").toObject().value("features").toArray();
    require(rows.size() == 2 && !rows[0].toObject().contains("params") && rows[1].toObject().value("params").toObject().value("offset") == 3, "Batch reply failed to focus created and edited features");
    std::cout << "PASS unknown feature, empty batch history, and compact mutation replies\n";
}
void batchTests() {
    genform::Session session;
    require(!session.execute("not_a_command").value("ok").toBool(), "Unknown command succeeded");
    require(!session.execute("sketch", {{"unknown", 3}}).value("ok").toBool(), "Invalid arguments succeeded");
    require(!session.execute("sketch", {{"shapes", "wrong type"}}).value("ok").toBool(), "Invalid shape type succeeded");
    const auto before = session.document.toData();
    const auto revision = session.document.revision;
    const auto failed = session.execute("batch", {{"steps", QJsonArray{step("sketch", sketch(), "profile"), step("extrude", {{"sketch", "$profile"}})}}});
    require(!failed.value("ok").toBool(), "Invalid batch succeeded");
    require(session.document.toData() == before && session.document.revision == revision && !session.document.canUndo(), "Failed batch changed document or undo stack");
    const auto made = session.execute("batch", {{"steps", QJsonArray{step("sketch", sketch(), "profile"), step("extrude", {{"sketch", "$1"}, {"distance", 5}}, "body"), step("rename_feature", {{"id", "$body"}, {"name", "Plate"}})}}});
    require(session.document.features.size() == 2, "Valid batch did not create features");
    const auto identifiers = made.value("ids").toArray();
    require(identifiers.size() == 3 && identifiers[0] == "f1" && identifiers[1] == "f2", "Batch result/reference ids changed");
    require(session.document.find("f2").value("params").toObject().value("sketch") == "f1", "Numeric batch reference did not resolve");
    require(session.document.find("f2").value("name") == "Plate", "Named reference did not resolve");
    require(session.model.contains("status") && !session.model.contains("statuses"), "Build model must use singular status");
    if (genform::kernel::Kernel::available()) {
        require(made.value("ok").toBool() && session.model.value("has_body").toBool(), "Valid native geometry failed");
        require(std::abs(session.model.value("props").toObject().value("volume").toDouble() - 1000) < 1e-5, "Plate volume is wrong");
    } else require(!made.value("ok").toBool() && session.model.value("status").toObject().value("f1").toString().startsWith("error:"), "Missing geometry SDK falsely succeeded");
    const auto snapshot = session.document.toData();
    for (const auto &command : QStringList{"undo", "redo", "new_document", "open_document", "batch", "get_model"}) {
        require(!session.execute("batch", {{"steps", QJsonArray{step("rename_feature", {{"id", "f2"}, {"name", "changed"}}), step(command)}}}).value("ok").toBool(), "Forbidden batch step succeeded");
        require(session.document.toData() == snapshot, "Forbidden batch step was not atomic");
    }
    require(!session.execute("batch", {{"steps", QJsonArray{step("rename_feature", {{"id", "$99"}, {"name", "bad"}})}}}).value("ok").toBool(), "Unresolved batch reference succeeded");
    session.execute("undo");
    require(session.document.find("f2").value("name") != "Plate", "Undo history was lost");
    session.execute("redo");
    require(session.document.find("f2").value("name") == "Plate", "Redo history was lost");
    const auto badFeature = session.execute("fillet", {{"edges", "all"}, {"radius", -1}});
    require(!badFeature.value("ok").toBool() && session.document.features.size() == 3, "Failed geometry must remain editable");
    std::cout << "PASS atomic batch, numeric/named references, undo/redo and retained geometry errors\n";
}
void metadataTests() {
    genform::Session session;
    session.execute("sketch", sketch());
    const auto material = genform::domain::material_catalog().first().toObject().value("name");
    require(session.execute("set_material", {{"name", material}}).value("ok").toBool(), "Native material selection failed");
    require(!session.execute("set_material", {{"name", "not a material"}}).value("ok").toBool(), "Unknown material succeeded");
    require(session.execute("set_appearance", {{"features", QJsonArray{"f1"}}, {"color", "#112233"}, {"opacity", .5}}).value("ok").toBool(), "Appearance update failed");
    require(session.execute("set_appearance", {{"features", QJsonArray{"f1"}}, {"opacity", .7}}).value("ok").toBool(), "Opacity-only update failed");
    require(session.document.props.value("feature_colors").toObject().value("f1") == "#112233", "Opacity update removed existing color");
    const auto process = genform::domain::process_catalog().first().toObject().value("id");
    require(session.execute("set_process", {{"feature", "f1"}, {"process", process}, {"cost", 12.5}}).value("ok").toBool() || session.document.find("f1").value("process").toObject().value("id") == process, "Process assignment failed");
    require(session.document.find("f1").value("process").toObject().value("cost").toDouble() == 12.5, "Manual process cost missing");
    require(!session.execute("set_process", {{"feature", "f1"}, {"process", process}, {"cost", -1}}).value("ok").toBool(), "Negative process cost succeeded");
    const auto currentRules = session.execute("get_design_rules").value("rules").toObject();
    require(!currentRules.isEmpty(), "Design rules are empty");
    require(session.execute("set_design_rules", {{"values", QJsonObject{{"batch", 100}}}}).value("ok").toBool(), "Document design rules failed");
    require(!session.execute("set_design_rules", {{"values", QJsonObject{{"batch", 100}}}, {"scope", "user"}}).value("ok").toBool(), "Unsupported persistent user rules falsely succeeded");
    QTemporaryDir directory;
    require(directory.isValid(), "Temporary directory unavailable");
    const QString path = directory.filePath("session.gform");
    require(session.execute("save_document", {{"path", path}}).value("ok").toBool(), "Save failed");
    session.execute("new_document");
    session.execute("open_document", {{"path", path}});
    require(session.document.features.size() == 1 && session.document.props.value("material") == material, "Roundtrip lost document or material");
    require(!session.execute("screenshot").value("ok").toBool(), "Headless screenshot falsely succeeded");
    session.viewCommand = [](const QString &command, const QJsonObject &args) { return QJsonObject{{"command", command}, {"view", args.value("view")}}; };
    require(session.execute("set_view", {{"view", "top"}}).value("view") == "top", "View callback failed");
    std::cout << "PASS materials, appearance, processes, rules, save/open and view dispatch\n";
}
void queryTests() {
    genform::Session session;
    require(session.execute("query", {{"what", "materials"}}).value("materials").toArray().size() > 0, "Material query missing");
    require(session.execute("query", {{"what", "processes"}}).value("processes").toArray().size() > 0, "Process query missing");
    require(session.execute("query", {{"what", "standard_parts"}}).value("parts").toArray().size() > 0, "Standard-part catalog missing");
    const QJsonArray parts{QJsonObject{{"name", "base"}, {"move", QJsonArray{0, 0, 0}}}};
    require(session.execute("query", {{"what", "set_assembly"}, {"data", QJsonObject{{"format", "genform-assembly"}, {"parts", parts}}}}).value("ok").toBool(), "Assembly load route failed");
    require(session.execute("query", {{"what", "get_assembly"}}).value("parts").toArray().size() == 1, "Assembly query lost assembly state");
    require(session.execute("query", {{"what", "pose"}, {"parts", parts}, {"joints", QJsonArray{}}}).value("matrices").toArray().size() == 1, "Native assembly pose route failed");
    require(!session.execute("query", {{"what", "fasteners"}}).value("ok").toBool(), "Unsupported fastener check falsely succeeded");
    require(!session.execute("query", {{"what", "unknown_query"}}).value("ok").toBool(), "Unknown query falsely succeeded");
    const auto generated = session.execute("query", {{"what", "make_standard_part"}, {"kind", "screw"}, {"size", "M3"}, {"length", 10}});
    require(generated.value("document").toObject().value("features").toArray().size() > 0 && session.document.features.isEmpty(), "Standard-part generation must be read-only");
    session.execute("add_standard_part", {{"kind", "screw"}, {"size", "M3"}, {"length", 10}});
    const auto firstCount = session.document.features.size();
    session.execute("add_standard_part", {{"kind", "screw"}, {"size", "M3"}, {"length", 10}});
    require(firstCount > 0 && session.document.features.size() == firstCount * 2, "Standard-part insertion did not append features");
    QSet<QString> identifiers;
    for (const auto &value : session.document.features) {
        const auto feature = value.toObject();
        require(!identifiers.contains(feature.value("id").toString()), "Standard-part ids collide");
        identifiers.insert(feature.value("id").toString());
        if (feature.value("params").toObject().contains("sketch")) require(identifiers.contains(feature.value("params").toObject().value("sketch").toString()), "Standard-part reference was not remapped");
    }
    require(!session.execute("query", {{"what", "drawing"}, {"part", QJsonObject{{"path", "missing.gform"}}}}).value("ok").toBool(), "Missing drawing source falsely succeeded");
    std::cout << "PASS assembly/material/process queries and explicit unsupported failures\n";
}
#endif
}

int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    try {
        catalogTests();
#ifndef GENFORM_FEATURE_TABLE_SELFTEST
        mutationContractTests(); batchTests(); metadataTests(); queryTests();
#endif
    }
    catch (const std::exception &error) { std::cerr << "FAIL " << error.what() << '\n'; return 1; }
    std::cout << "All native session tests passed\n";
    return 0;
}
