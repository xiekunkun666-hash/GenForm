#pragma once

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QMap>
#include <QSet>
#include <QStringList>
#include <stdexcept>

namespace examples::recipes {

inline void check(bool condition, const QString &message) {
    if (!condition) throw std::runtime_error(message.toUtf8().constData());
}

inline QStringList modules() {
    return {"build_skye2_replica", "check_skye2_reference", "complete_skye2_reference", "present_skye2_replica", "verify_skye2_reference",
            "button_claw_latch/build", "button_claw_latch/processes", "button_claw_latch/repair", "button_claw_latch/spring_ends", "button_claw_latch/validate", "button_claw_latch/verify",
            "button_latch/build", "button_latch/present", "button_latch/verify",
            "porsche_911/alternate", "porsche_911/alternate_runtime", "porsche_911/compare", "porsche_911/details", "porsche_911/fasteners", "porsche_911/glazing", "porsche_911/mcp_client", "porsche_911/panel_lines", "porsche_911/refine", "porsche_911/trim", "porsche_911/wheels",
            "powder_pump/build", "powder_pump/lance", "powder_pump_fan/build"};
}

inline QJsonObject load(const QString &path) {
    QFile file(path); check(file.open(QIODevice::ReadOnly), "Cannot read modelling resource: " + path);
    const auto decoded = qUncompress(QByteArray::fromBase64(file.readAll()));
    check(!decoded.isEmpty(), "Corrupt compressed modelling resource");
    QJsonParseError error; const auto document = QJsonDocument::fromJson(decoded, &error);
    check(error.error == QJsonParseError::NoError && document.isObject(), "Invalid modelling resource JSON: " + error.errorString());
    return document.object();
}

inline void references(const QJsonValue &value, const QSet<QString> &aliases) {
    if (value.isString() && value.toString().startsWith('$')) check(aliases.contains(value.toString().mid(1)), "Undefined recipe alias: " + value.toString());
    else if (value.isArray()) for (const auto &entry : value.toArray()) references(entry, aliases);
    else if (value.isObject()) {
        const auto object = value.toObject();
        for (auto entry = object.begin(); entry != object.end(); ++entry) references(entry.value(), aliases);
    }
}

inline QSet<QString> steps(const QJsonValue &value, int &commands) {
    check(value.isArray() && !value.toArray().isEmpty(), "Empty or invalid command sequence");
    const QSet<QString> commandsSupported{"axis", "chamfer", "curve_helix", "extrude", "fillet", "hole", "loft", "pattern_circular", "plane", "revolve", "screw", "sketch", "stud", "sweep"};
    QSet<QString> aliases, names;
    for (const auto &entry : value.toArray()) {
        check(entry.isObject(), "Command must be an object"); const auto command = entry.toObject();
        check(command["cmd"].isString() && commandsSupported.contains(command["cmd"].toString()) && command["args"].isObject(), "Invalid modelling command");
        references(command["args"], aliases);
        const auto name = command["args"].toObject().value("name");
        if (!name.isUndefined()) {
            check(name.isString() && !name.toString().isEmpty() && !names.contains(name.toString()), "Invalid or duplicate explicit feature name"); names.insert(name.toString());
        }
        if (command.contains("as")) {
            const auto alias = command["as"];
            check(alias.isString() && !alias.toString().isEmpty() && !aliases.contains(alias.toString()), "Invalid or duplicate recipe alias"); aliases.insert(alias.toString());
        }
        ++commands;
    }
    return aliases;
}

inline void filename(const QString &name, const QString &suffix) {
    check(!name.isEmpty() && name.endsWith(suffix) && !name.contains('/') && !name.contains('\\') && !name.contains(':') && !name.contains(".."), "Unsafe recipe filename: " + name);
}

inline QJsonObject validate(const QJsonObject &data) {
    check(data["schema"].isDouble() && data["schema"].toDouble() == 1, "Unsupported recipe schema");
    const auto mapped = modules(); const QSet<QString> known(mapped.begin(), mapped.end());
    check(mapped.size() == 28 && known.size() == 28, "Expected 28 unique native entry mappings");
    const QMap<QString, int> expectedParts{{"button_latch/build", 7}, {"button_claw_latch/build", 16}, {"powder_pump/build", 9}, {"powder_pump/lance", 6}, {"powder_pump_fan/build", 14}};
    const QMap<QString, int> expectedStages{{"porsche_911/details", 56}, {"porsche_911/fasteners", 27}, {"porsche_911/wheels", 60}, {"porsche_911/trim", 8}};
    check(data["builds"].isObject() && data["builds"].toObject().size() == expectedParts.size(), "Expected five build mappings");
    check(data["stages"].isObject() && data["stages"].toObject().size() == expectedStages.size(), "Expected four fixed-stage mappings");
    int parts = 0, commands = 0, stageCommands = 0, stageGroups = 0, assemblies = 0;
    QSet<QString> clawFiles;
    QMap<QString, QSet<QString>> clawFeatures;
    const auto builds = data["builds"].toObject();
    for (auto module = expectedParts.begin(); module != expectedParts.end(); ++module) {
        check(known.contains(module.key()) && builds[module.key()].isObject(), "Missing build mapping: " + module.key());
        const auto recipe = builds[module.key()].toObject();
        check(recipe["parts"].isArray() && recipe["parts"].toArray().size() == module.value(), "Incorrect part count: " + module.key());
        QSet<QString> files;
        for (const auto &entry : recipe["parts"].toArray()) {
            check(entry.isObject(), "Part must be an object"); const auto part = entry.toObject();
            check(part["file"].isString(), "Part filename must be a string"); const QString file = part["file"].toString(); filename(file, ".gform");
            check(!files.contains(file), "Duplicate part file: " + file); files.insert(file);
            steps(part["steps"], commands); ++parts;
            for (const auto &key : {"name", "color", "material", "phase"}) if (part.contains(key)) check(part[key].isString() && !part[key].toString().isEmpty(), "Invalid part metadata");
            if (module.key() == "button_claw_latch/build") {
                QSet<QString> names;
                for (const auto &command : part["steps"].toArray()) names.insert(command.toObject()["args"].toObject()["name"].toString());
                clawFeatures[file] = names;
            }
        }
        if (module.key() == "button_claw_latch/build") clawFiles = files;
        check(recipe["assemblies"].isObject() && !recipe["assemblies"].toObject().isEmpty(), "Missing assembly data");
        const auto assemblyData = recipe["assemblies"].toObject();
        for (auto item = assemblyData.begin(); item != assemblyData.end(); ++item) {
            filename(item.key(), ".gasm"); check(item.value().isObject(), "Invalid assembly object"); const auto assembly = item.value().toObject();
            check(assembly["format"] == "genform-assembly" && assembly["version"].isDouble() && assembly["parts"].isArray() && !assembly["parts"].toArray().isEmpty(), "Invalid assembly header");
            for (const auto &component : assembly["parts"].toArray()) {
                check(component.isObject(), "Invalid assembly component"); const auto part = component.toObject();
                check(part["file"].isString() && files.contains(part["file"].toString()), "Assembly references a missing part");
                check(part["name"].isString() && !part["name"].toString().isEmpty(), "Missing assembly component display name");
                for (const auto &key : {"move", "turn"}) if (part.contains(key)) {
                    check(part[key].isArray() && part[key].toArray().size() == 3, "Invalid assembly transform");
                    for (const auto &coordinate : part[key].toArray()) check(coordinate.isDouble(), "Transform coordinate must be numeric");
                }
            }
            ++assemblies;
        }
    }
    const auto stages = data["stages"].toObject();
    for (auto module = expectedStages.begin(); module != expectedStages.end(); ++module) {
        check(known.contains(module.key()) && stages[module.key()].isArray() && !stages[module.key()].toArray().isEmpty(), "Missing stage mapping: " + module.key());
        const int before = stageCommands; QSet<QString> labels;
        for (const auto &entry : stages[module.key()].toArray()) {
            check(entry.isObject(), "Invalid stage group"); const auto group = entry.toObject(); const QString label = group["label"].toString();
            check(!label.isEmpty() && !labels.contains(label), "Missing or duplicate stage label"); labels.insert(label);
            const auto aliases = steps(group["steps"], stageCommands); check(group["colors"].isObject(), "Missing stage appearance mapping");
            const auto colors = group["colors"].toObject();
            for (auto color = colors.begin(); color != colors.end(); ++color) check(aliases.contains(color.key()) && color.value().isString() && !color.value().toString().isEmpty(), "Appearance references a missing alias");
            ++stageGroups;
        }
        check(stageCommands - before == module.value(), "Incomplete stage commands: " + module.key());
    }
    check(data["patches"].isObject() && data["patches"].toObject().size() == 4, "Expected four repair targets");
    const auto patches = data["patches"].toObject();
    for (const auto &name : {"frame", "pushrod", "door_striker", "link_rivet"}) {
        check(patches[name].isObject() && !patches[name].toObject().isEmpty(), "Missing repair target"); const auto features = patches[name].toObject();
        for (auto feature = features.begin(); feature != features.end(); ++feature) check(clawFeatures[QString(name) + ".gform"].contains(feature.key()) && feature.value().isObject() && !feature.value().toObject().isEmpty(), "Invalid repair feature mapping");
    }
    check(data["processes"].isObject() && data["processes"].toObject().size() == 11, "Expected eleven process proposals");
    const auto processes = data["processes"].toObject();
    for (auto proposal = processes.begin(); proposal != processes.end(); ++proposal) {
        check(clawFiles.contains(proposal.key()) && proposal.value().isArray() && proposal.value().toArray().size() == 2, "Invalid process part mapping");
        for (const auto &field : proposal.value().toArray()) check(field.isString() && !field.toString().isEmpty(), "Invalid process proposal");
    }
    int historicalHashes = 0;
    if (data.contains("source_sha256")) {
        check(data["source_sha256"].isObject(), "Invalid optional source provenance"); const auto hashes = data["source_sha256"].toObject();
        for (auto hash = hashes.begin(); hash != hashes.end(); ++hash) {
            check(hash.key().endsWith(".py") && known.contains(hash.key().chopped(3)) && hash.value().isString(), "Unknown historical source mapping");
            const QString digest = hash.value().toString(); check(digest.size() == 64, "Invalid historical SHA-256 length");
            for (const auto character : digest) check(QString("0123456789abcdef").contains(character), "Invalid historical SHA-256 encoding");
            ++historicalHashes;
        }
    }
    check(parts == 52 && commands == 367 && stageGroups == 10 && stageCommands == 151 && assemblies == 13, "Incomplete recipe coverage");
    return {{"native_entry_mappings", mapped.size()}, {"build_modules", expectedParts.size()}, {"parts", parts}, {"part_commands", commands}, {"stage_modules", expectedStages.size()}, {"stage_groups", stageGroups}, {"stage_commands", stageCommands}, {"assemblies", assemblies}, {"historical_source_hashes", historicalHashes}, {"python_sources_required", false}};
}

}
