#include "runner.hpp"
#include "catalog.hpp"
#include "genform/domain/geometry.hpp"
#include <QCryptographicHash>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QSaveFile>
#include <QTcpSocket>
#include <QTextStream>
#include <QTemporaryDir>
#include <QSet>
#include <cmath>
#include <algorithm>

namespace examples {

void require(bool condition, const QString &message) { if (!condition) throw genform::Error(message); }
QString sourceRoot() { return QDir(GENFORM_EXAMPLES_DIR).absoluteFilePath(".."); }

QJsonObject loadObject(const QString &path) {
    QFile file(path); require(file.open(QIODevice::ReadOnly), "Cannot read " + path + ": " + file.errorString());
    QJsonParseError error; const auto document = QJsonDocument::fromJson(file.readAll(), &error);
    require(error.error == QJsonParseError::NoError && document.isObject(), "Invalid JSON object in " + path + ": " + error.errorString());
    return document.object();
}

void saveObject(const QString &path, const QJsonObject &value) {
    require(QDir().mkpath(QFileInfo(path).absolutePath()), "Cannot create output directory");
    QSaveFile file(path); require(file.open(QIODevice::WriteOnly), "Cannot write " + path);
    const auto data = QJsonDocument(value).toJson(QJsonDocument::Indented);
    require(file.write(data) == data.size() && file.commit(), "Atomic save failed: " + path);
}

QString sha256(const QString &path) {
    QFile file(path); require(file.open(QIODevice::ReadOnly), "Cannot hash " + path);
    QCryptographicHash hash(QCryptographicHash::Sha256); require(hash.addData(&file), "Hash read failed: " + path);
    return QString::fromLatin1(hash.result().toHex());
}

QJsonObject call(genform::Session &session, const QString &command, const QJsonObject &arguments) {
    const auto answer = session.execute(command, arguments);
    require(!answer.contains("ok") || answer["ok"].toBool(), command + ": " + QString::fromUtf8(QJsonDocument(answer).toJson(QJsonDocument::Compact)));
    require(!answer.contains("error"), command + ": " + answer["error"].toString());
    return answer;
}

static QJsonObject exchange(QJsonObject request, quint16 port) {
    QTcpSocket socket; socket.connectToHost("127.0.0.1", port);
    require(socket.waitForConnected(5000), "Cannot connect to native GenForm at localhost:" + QString::number(port));
    const auto bytes = QJsonDocument(request).toJson(QJsonDocument::Compact) + '\n';
    require(socket.write(bytes) == bytes.size() && socket.waitForBytesWritten(5000), "Request write failed; do not resend without inspecting state");
    QByteArray response;
    while (!response.contains('\n')) {
        require(socket.waitForReadyRead(295000), "Response uncertain or timed out; action is not resent");
        response += socket.readAll(); require(response.size() < 64 * 1024 * 1024, "Oversized native response");
    }
    QJsonParseError error; const auto answer = QJsonDocument::fromJson(response.left(response.indexOf('\n')), &error).object();
    require(error.error == QJsonParseError::NoError && answer["ok"].toBool(), "Native response failure: " + QString::fromUtf8(QJsonDocument(answer).toJson(QJsonDocument::Compact)));
    return answer;
}

QJsonObject rpc(const QString &command, const QJsonObject &arguments, quint16 port) { return exchange({{"cmd", command}, {"args", arguments}}, port); }
QJsonObject ui(const QString &slot, const QJsonArray &arguments, quint16 port) { return exchange({{"cmd", "ui"}, {"slot", slot}, {"args", arguments}}, port); }

QJsonObject configuration(double angle) {
    const double radians = angle * std::acos(-1.0) / 180;
    const double crankX = -10 * std::sin(radians), crankY = 10 * std::cos(radians);
    const double slider = crankX - std::sqrt(24 * 24 - std::pow(crankY - 10, 2));
    const double link = std::atan2(crankY - 10, crankX - slider);
    return {{"angle", angle}, {"slider", slider}, {"shift", slider + 24}, {"crank", QJsonArray{crankX, crankY}},
            {"link_angle", link * 180 / std::acos(-1.0)}, {"link_move", QJsonArray{slider + 24 * std::cos(link) + 10 * std::sin(link), 10 + 24 * std::sin(link) - 10 * std::cos(link), 0}}};
}

static QJsonObject catalog() {
    return recipes::load(QDir(GENFORM_EXAMPLES_DIR).filePath("recipes/catalog.json.qz.base64"));
}

static void ensureModel(genform::Session &session) {
    const auto model = session.builder.query("model");
    require(model["has_body"].toBool(), "No solid body was generated");
    const auto statuses = model["status"].toObject();
    for (auto iterator = statuses.begin(); iterator != statuses.end(); ++iterator)
        require(iterator.value().toString() == "ok" || iterator.value().toString() == "suppressed", iterator.key() + ": " + iterator.value().toString());
    const auto inspection = session.builder.query("inspect");
    require(inspection["valid"].toBool(), "Generated BRep is invalid");
}

static int build(const Options &options, const QJsonObject &recipe) {
    require(!options.output.isEmpty(), "Specify --output; original models are never overwritten by default");
    const QString phase = options.positional.value(0, "all");
    const auto parts = recipe["parts"].toArray();
    const bool claw = options.name.startsWith("button_claw_latch");
    const bool latch = options.name.startsWith("button_latch");
    if (latch || claw) {
        const QStringList phases = claw ? QStringList{"all", "frame", "mechanism", "hardware", "springs", "assembly", "show"} : QStringList{"all", "core", "springs", "assembly", "show"};
        require(options.positional.size() <= 1 && phases.contains(phase), "Invalid build phase: " + phase);
    } else {
        QSet<QString> filenames; for (const auto &value : parts) filenames.insert(value.toObject()["file"].toString());
        for (const auto &requested : options.positional) require(requested == "all" || filenames.contains(requested), "Unknown part filename: " + requested);
    }
    if (claw && options.values.contains("angle")) require(QStringList{"0", "10", "20", "30", "40"}.contains(options.values["angle"].toString()), "Angle must be 0, 10, 20, 30 or 40");
    QDir output(options.output); require(QDir().mkpath(output.absolutePath()), "Cannot create output directory");
    if (phase == "show") {
        Options present = options; present.name = claw ? "button_claw_latch/validate" : "button_latch/present";
        present.positional = claw ? QStringList{options.values.value("angle").toString("40") == "40" ? "open" : "closed"} : QStringList{};
        present.values["assembly"] = claw ? (options.values.value("angle").toString("40") == "40" ? "claw_latch_open.gasm" : "claw_latch_closed.gasm") : "button_latch_exploded.gasm";
        return verify(present);
    }
    genform::Session session; int count = 0;
    QSet<QString> requested;
    if (!latch && !claw) for (const auto &part : options.positional) requested.insert(part);
    for (const auto &value : parts) {
        const auto part = value.toObject(); const QString filename = part["file"].toString();
        const bool spring = filename.startsWith("spring_");
        if (phase == "assembly") continue;
        if (latch && phase != "all" && ((phase == "core" && spring) || (phase == "springs" && !spring))) continue;
        if (claw && phase != "all" && part["phase"].toString() != phase) continue;
        if (claw && phase == "springs" && part["angle"].toInt() != options.values.value("angle").toString("40").toInt()) continue;
        if (!requested.isEmpty() && !requested.contains(filename) && !requested.contains("all")) continue;
        const QString path = output.filePath(filename);
        if (QFileInfo::exists(path) && !options.force) { QTextStream(stdout) << "SKIP " << path << '\n'; continue; }
        call(session, "new_document");
        QTextStream(stdout) << "BUILD " << filename << " (" << part["steps"].toArray().size() << " native commands)\n";
        call(session, "batch", {{"steps", part["steps"]}}); ensureModel(session);
        if (!part["material"].toString().isEmpty()) call(session, "set_material", {{"name", part["material"]}});
        if (!part["color"].toString().isEmpty()) call(session, "set_appearance", {{"color", part["color"]}});
        call(session, "save_document", {{"path", path}});
        require(QFileInfo(path).size() > 0 && !loadObject(path)["features"].toArray().isEmpty(), "Saved part is empty: " + path); ++count;
    }
    if (phase == "assembly" || phase == "all" || (!claw && !latch)) {
        const auto assemblies = recipe["assemblies"].toObject();
        for (auto iterator = assemblies.begin(); iterator != assemblies.end(); ++iterator) saveObject(output.filePath(iterator.key()), iterator.value().toObject());
    }
    QTextStream(stdout) << "Built " << count << " parts in " << output.absolutePath() << '\n'; return 0;
}

static QJsonObject step(const QString &command, const QString &alias, QJsonObject arguments) { return {{"cmd", command}, {"as", alias}, {"args", arguments}}; }

static int stage(const Options &options, const QJsonArray &recipes) {
    const QString documentPath = options.values.value("source").toString(QDir(sourceRoot()).filePath("models/porsche_911_992/porsche_911_992.gform"));
    require(!options.output.isEmpty(), "Specify --output for the edited vehicle document");
    genform::Session session; call(session, "open_document", {{"path", documentPath}});
    const QString mode = options.positional.value(0) == "lamp" ? "headlamp_" + options.positional.value(1) : options.positional.join('_'); QJsonArray selected;
    for (const auto &value : recipes) {
        const auto recipe = value.toObject(); const QString label = recipe["label"].toString();
        bool matches = mode.isEmpty() || mode == "all" || label == mode || label.endsWith(mode) || label == "911_headlamp_" + mode || (mode == "lamps" && label.startsWith("911_headlamp"));
        if (!matches) continue;
        selected.append(recipe);
    }
    require(!selected.isEmpty(), "No stage matches " + mode);
    QSet<QString> existing; for (const auto &value : session.document.features) existing.insert(value.toObject()["name"].toString());
    for (const auto &recipe : selected) for (const auto &value : recipe.toObject()["steps"].toArray()) { const QString name = value.toObject()["args"].toObject()["name"].toString(); require(!existing.contains(name), "Stage already exists: " + name); existing.insert(name); }
    int total = 0;
    for (const auto &value : selected) {
        const auto recipe = value.toObject(); const auto steps = recipe["steps"].toArray(); const auto colors = recipe["colors"].toObject();
        const auto before = session.builder.query("properties")["volume"].toDouble();
        const auto result = call(session, "batch", {{"steps", steps}}); ensureModel(session);
        require(!before || session.builder.query("properties")["volume"].toDouble() >= before * .98, "Unexpected stage volume decrease");
        const auto ids = result["ids"].toArray(); require(ids.size() == steps.size(), "Batch did not return one ID per command");
        for (qsizetype index = 0; index < steps.size(); ++index) {
            const QString alias = steps[index].toObject()["as"].toString();
            if (colors.contains(alias)) call(session, "set_appearance", {{"features", QJsonArray{ids[index]}}, {"color", colors[alias]}});
        }
        total += steps.size();
    }
    const QString destination = QDir(options.output).filePath("porsche_911_992.gform"); call(session, "save_document", {{"path", destination}});
    QTextStream(stdout) << "SAVED " << destination << " (" << total << " commands)\n"; return 0;
}

static int edits(const Options &options, const QJsonObject &data) {
    require(!options.output.isEmpty(), "Specify --output containing the existing editable parts");
    QDir directory(options.output); genform::Session session;
    const QString partName = options.positional.value(0, "check_all");
    if (options.name.endsWith("repair")) require(partName == "check_all" || data["patches"].toObject().contains(partName), "Unknown repair part: " + partName);
    const auto files = directory.entryList({"*.gform"}, QDir::Files, QDir::Name);
    require(!files.isEmpty(), "No input .gform parts in " + options.output);
    if (options.name.endsWith("repair") && partName != "check_all") require(files.contains(partName + ".gform"), "Missing repair input part: " + partName);
    if (options.name.endsWith("spring_ends")) for (const auto &angle : options.positional) {
        require(QStringList{"0", "10", "20", "30", "40"}.contains(angle), "Spring angle must be 0, 10, 20, 30 or 40");
        require(files.contains(QString("spring_%1.gform").arg(angle.toInt(), 2, 10, QChar('0'))), "Requested spring file is missing");
    }
    for (const auto &file : files) {
        if (options.name.endsWith("repair") && partName != "check_all" && file != partName + ".gform") continue;
        if (options.name.endsWith("spring_ends") && (!file.startsWith("spring_") || (!options.positional.isEmpty() && !options.positional.contains(QString::number(file.mid(7, 2).toInt()))))) continue;
        const QString path = directory.filePath(file); const auto original = loadObject(path);
        call(session, "open_document", {{"path", path}}); QJsonArray steps;
        if (options.name.endsWith("repair") && partName == "check_all") {
            const QString reportPath = directory.filePath("part_check_" + QFileInfo(file).completeBaseName() + ".json");
            const QString beforePath = directory.filePath("part_check_" + QFileInfo(file).completeBaseName() + "_before.json");
            if (QFileInfo::exists(reportPath) && !QFileInfo::exists(beforePath)) require(QFile::copy(reportPath, beforePath), "Cannot preserve previous report");
            const auto report = call(session, "check_design"); saveObject(reportPath, report);
            require(report["counts"].toObject()["error"].toInt() == 0, "Part design check failed: " + file); continue;
        }
        if (options.name.endsWith("processes") && file == "frame.gform") {
            bool relieved = false; for (const auto &value : session.document.features) if (value.toObject()["name"] == "rivet_head_relief") relieved = true;
            if (!relieved) {
                steps.append(step("sketch", "rivet_head_relief", {{"name", "rivet_head_relief"}, {"plane", "XY"}, {"offset", 6.5}, {"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"cx", -33.5}, {"cy", 10}, {"w", 1}, {"h", 6}}}}}));
                steps.append(step("extrude", "guide_front_clearance", {{"name", "guide_front_clearance"}, {"sketch", "$rivet_head_relief"}, {"distance", 11.6}, {"op", "cut"}}));
            }
        }
        if (options.name.endsWith("repair") && partName != "check_all") {
            const auto patches = data["patches"].toObject().value(QFileInfo(file).completeBaseName()).toObject();
            require(!patches.isEmpty(), "No patch for " + file);
            for (auto iterator = patches.begin(); iterator != patches.end(); ++iterator) {
                const auto feature = session.document.find(iterator.key()); const auto params = feature["params"].toObject(); bool changed = false;
                const auto patch = iterator.value().toObject(); for (auto parameter = patch.begin(); parameter != patch.end(); ++parameter) if (params[parameter.key()] != parameter.value()) changed = true;
                if (changed) steps.append(step("edit_feature", {}, {{"id", feature["id"]}, {"params", patch}}));
            }
        }
        if (options.name.endsWith("spring_ends")) {
            const int angle = file.mid(7, 2).toInt(); const double rear = -42 + configuration(angle)["shift"].toDouble();
            bool hasSeat = false; for (const auto &value : session.document.features) if (value.toObject()["name"] == "rear_ground_seat") hasSeat = true;
            if (!hasSeat) for (const auto &seat : QStringList{"rear", "front"}) {
                const QString alias = seat + "_closed_end"; const double offset = seat == "rear" ? rear + .5 : -37;
                const QJsonArray rings{QJsonObject{{"type", "circle"}, {"cx", 10}, {"cy", 10}, {"r", 5.25}}, QJsonObject{{"type", "circle"}, {"cx", 10}, {"cy", 10}, {"r", 4.15}}};
                steps.append(step("sketch", alias, {{"name", alias}, {"plane", "YZ"}, {"offset", offset}, {"shapes", rings}}));
                steps.append(step("extrude", seat + "_ground_seat", {{"name", seat + "_ground_seat"}, {"sketch", "$" + alias}, {"distance", 1}}));
            }
        }
        if (!steps.isEmpty()) call(session, "batch", {{"steps", steps}});
        if (options.name.endsWith("processes") || options.name.endsWith("spring_ends")) {
            const auto proposal = data["processes"].toObject().value(file).toArray();
            const QString process = proposal.isEmpty() ? "purchase" : proposal[0].toString();
            const QString spec = options.name.endsWith("spring_ends") ? QString::fromUtf8("定制压簧几何包络：线径1、平均径9.4、四圈及闭口磨平端；弹力与寿命未校核，报价待定") : proposal.isEmpty() ? QString::fromUtf8("压缩弹簧按图形定制；刚度、预压、材料和报价待定") : proposal[1].toString();
            for (const auto &value : session.document.features) { const auto feature = value.toObject();
                const auto types = options.name.endsWith("spring_ends") ? QStringList{"extrude", "sweep", "curve_helix"} : QStringList{"extrude", "sweep", "screw"};
                if (types.contains(feature["type"].toString())) call(session, "set_process", {{"feature", feature["id"]}, {"process", process}, {"spec", spec}});
            }
        }
        ensureModel(session); call(session, "save_document", {{"path", path}});
        if (options.name.endsWith("repair")) {
            const auto saved = loadObject(path)["features"].toArray(), before = original["features"].toArray();
            require(saved.size() == before.size(), "Repair changed feature count");
            for (qsizetype index = 0; index < saved.size(); ++index) require(saved[index].toObject()["process"] == before[index].toObject()["process"], "Repair changed process metadata");
        }
        const QString reportPath = directory.filePath("part_check_" + QFileInfo(file).completeBaseName() + ".json");
        const QString beforePath = directory.filePath("part_check_" + QFileInfo(file).completeBaseName() + "_before.json");
        if ((options.name.endsWith("repair") || options.name.endsWith("spring_ends")) && QFileInfo::exists(reportPath) && !QFileInfo::exists(beforePath)) require(QFile::copy(reportPath, beforePath), "Cannot preserve previous report");
        auto report = call(session, "check_design"); saveObject(reportPath, report);
        require(report["counts"].toObject()["error"].toInt() == 0, "Part design check failed: " + file);
    }
    return 0;
}

int audit() {
    const auto data = catalog(); const auto summary = recipes::validate(data);
    auto withoutProvenance = data; withoutProvenance.remove("source_sha256");
    require(recipes::validate(withoutProvenance)["native_entry_mappings"].toInt() == 28, "Historical hashes must not be required for native operation");
    auto rejects = [](const QJsonObject &invalid) {
        bool rejected = false; try { recipes::validate(invalid); } catch (const std::exception &) { rejected = true; }
        require(rejected, "Corrupt recipe fixture was accepted");
    };
    auto missingBuild = data; auto builds = data["builds"].toObject(); builds.remove("button_latch/build"); missingBuild["builds"] = builds; rejects(missingBuild);
    auto brokenAlias = data; builds = data["builds"].toObject(); auto buildRecipe = builds["button_latch/build"].toObject(); auto parts = buildRecipe["parts"].toArray();
    auto part = parts[0].toObject(); auto commands = part["steps"].toArray(); auto command = commands[0].toObject(); auto args = command["args"].toObject(); args["plane"] = "$missing_alias";
    command["args"] = args; commands[0] = command; part["steps"] = commands; parts[0] = part; buildRecipe["parts"] = parts; builds["button_latch/build"] = buildRecipe; brokenAlias["builds"] = builds; rejects(brokenAlias);
    auto brokenStage = data; auto stages = data["stages"].toObject(); auto groups = stages["porsche_911/wheels"].toArray(); groups.removeLast(); stages["porsche_911/wheels"] = groups; brokenStage["stages"] = stages; rejects(brokenStage);
    QTextStream(stdout) << "PASS: native resource structure/mappings; no Python source dependency; hash-free and corrupt-resource regression fixtures\n" << QJsonDocument(summary).toJson(QJsonDocument::Indented); return 0;
}

int selfTest() {
    require(std::abs(configuration(0)["shift"].toDouble()) < 1e-10, "Closed crank position mismatch");
    require(configuration(40)["shift"].toDouble() < -6, "Claw travel direction mismatch");
    const QJsonObject circle{{"type", "circle"}, {"cx", 0}, {"cy", 0}, {"r", 2}};
    const auto outlines = genform::domain::polylines(circle);
    require(outlines.size() == 1 && outlines[0].size() == 65, "Circle must use the domain's 64-segment closed outline");
    const double radius = circle["r"].toDouble(), pi = std::acos(-1.0);
    const double expectedPolygonLength = 2 * 64 * radius * std::sin(pi / 64);
    const double measuredLength = genform::domain::length(circle);
    require(std::abs(measuredLength - expectedPolygonLength) < 1e-6, "Native circle polyline length differs from the analytic regular-polygon perimeter");
    const auto primitives = genform::domain::prims(circle);
    require(primitives.size() == 1 && primitives[0].type == "circle" && std::abs(primitives[0].radius - radius) < 1e-12, "Circle primitive radius/type mismatch");
    const auto refinedOutline = genform::domain::sample(primitives[0], 128);
    require(refinedOutline.size() == 129, "Refined circle outline sample count mismatch");
    double refinedLength = 0; for (qsizetype index = 1; index < refinedOutline.size(); ++index) refinedLength += genform::domain::distance(refinedOutline[index - 1], refinedOutline[index]);
    require(std::abs(refinedLength - 2 * 128 * radius * std::sin(pi / 128)) < 1e-6, "Refined circle polyline length mismatch");
    require(measuredLength < refinedLength && refinedLength < 2 * pi * radius, "Circle polyline length must converge from below to the exact circumference");
    QTextStream(stdout) << "Circle: 64-chord=" << QString::number(measuredLength, 'g', 15) << ", analytic polygon=" << QString::number(expectedPolygonLength, 'g', 15) << ", 128-chord=" << QString::number(refinedLength, 'g', 15) << ", exact circumference=" << QString::number(2 * pi * radius, 'g', 15) << '\n';
    QTemporaryDir temporary; require(temporary.isValid(), "Cannot create test directory");
    genform::Document document; const auto sketch = document.add("sketch", {{"plane", "XY"}, {"shapes", QJsonArray{circle}}}, "test_profile");
    document.add("extrude", {{"sketch", sketch}, {"distance", 5}}, "test_cylinder");
    const QString path = temporary.filePath("roundtrip.gform"); document.save(path); genform::Document reopened; reopened.open(path);
    require(reopened.features == document.features, "Native document roundtrip failed");
    if (genform::kernel::Kernel::available()) { genform::Session session; call(session, "open_document", {{"path", path}}); ensureModel(session); require(std::abs(session.builder.query("properties")["volume"].toDouble() - 20 * std::acos(-1.0)) < 1e-5, "Native cylinder volume mismatch"); }
    QTextStream(stdout) << "PASS: kinematics, geometry, document roundtrip" << (genform::kernel::Kernel::available() ? ", Session/kernel cylinder\n" : "; kernel unavailable (not falsely passed)\n"); return 0;
}

int run(const Options &options) {
    if (options.name == "--list") { for (const auto &module : recipes::modules()) QTextStream(stdout) << module << '\n'; return 0; }
    require(recipes::modules().contains(options.name), "Unknown native example mapping: " + options.name);
    const auto data = catalog();
    const auto builds = data["builds"].toObject(); if (builds.contains(options.name)) return build(options, builds[options.name].toObject());
    if (options.name.startsWith("porsche_911/alternate")) return alternate(options);
    if (options.name.contains("skye2")) return skye(options);
    if (options.name.endsWith("/verify") || options.name.endsWith("/present") || options.name.endsWith("/validate") || options.name == "porsche_911/compare") return verify(options);
    if (options.name.endsWith("/repair") || options.name.endsWith("/processes") || options.name.endsWith("/spring_ends")) return edits(options, data);
    if (options.name == "porsche_911/mcp_client") {
        const QString command = options.positional.value(0, "tools"); genform::Session session;
        QJsonObject arguments = options.values.contains("arguments") ? loadObject(options.values["arguments"].toString()) : QJsonObject{};
        QJsonObject answer;
        if (options.values["remote"].toBool()) {
            bool valid = false; const int port = options.values.value("port").toString("9631").toInt(&valid); require(valid && port > 0 && port < 65536, "Port must be 1..65535");
            answer = rpc(command, arguments, static_cast<quint16>(port));
        } else {
            if (options.values.contains("source")) call(session, "open_document", {{"path", options.values["source"]}});
            answer = command == "tools" ? QJsonObject{{"tools", genform::Session::tools()}} : call(session, command, arguments);
        }
        QTextStream(stdout) << QJsonDocument(answer).toJson(QJsonDocument::Indented); return 0;
    }
    const auto stages = data["stages"].toObject();
    if (stages.contains(options.name) && options.positional.value(0) != "sample" && (options.name != "porsche_911/trim" || options.positional.value(0) == "badges")) return stage(options, stages[options.name].toArray());
    return verify(options);
}

}
