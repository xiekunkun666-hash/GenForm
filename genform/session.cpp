#include "genform/session.hpp"
#include "genform/features.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/kernel/native.hpp"
#include <QSet>
#include <cmath>

namespace genform {
namespace {
QStringList strings(const QJsonArray &values) {
    QStringList result;
    for (const auto &value : values) result.append(value.toString());
    return result;
}
QJsonValue fillReferences(const QJsonValue &value, const QJsonArray &made, const QJsonObject &names) {
    if (value.isString() && value.toString().startsWith('$')) {
        const QString key = value.toString().mid(1);
        bool numeric = false;
        const int index = key.toInt(&numeric);
        const QJsonValue found = numeric && index > 0 && index <= made.size() ? made[index - 1] : names.value(key);
        if (found.isNull() || found.isUndefined()) throw Error(QStringLiteral("Unresolved batch reference: %1").arg(value.toString()));
        return found;
    }
    if (value.isArray()) {
        QJsonArray result;
        for (const auto &item : value.toArray()) result.append(fillReferences(item, made, names));
        return result;
    }
    if (value.isObject()) {
        QJsonObject result;
        const auto object = value.toObject();
        for (auto it = object.begin(); it != object.end(); ++it) result[it.key()] = fillReferences(it.value(), made, names);
        return result;
    }
    return value;
}
QJsonValue remapReferences(const QJsonValue &value, const QJsonObject &identifiers) {
    if (value.isString() && identifiers.contains(value.toString())) return identifiers.value(value.toString());
    if (value.isArray()) {
        QJsonArray result;
        for (const auto &item : value.toArray()) result.append(remapReferences(item, identifiers));
        return result;
    }
    if (value.isObject()) {
        QJsonObject result;
        const auto object = value.toObject();
        for (auto iterator = object.begin(); iterator != object.end(); ++iterator) result[iterator.key()] = remapReferences(iterator.value(), identifiers);
        return result;
    }
    return value;
}
QJsonArray resolvedFeatures(const QJsonArray &features) {
    QMap<QString, double> variables;
    QJsonArray result;
    for (const auto &value : features) {
        auto feature = value.toObject();
        if (feature.value("suppressed").toBool()) { result.append(feature); continue; }
        auto params = feature.value("params").toObject();
        if (feature.value("type") == "variables") {
            auto pending = params.value("values").toObject();
            while (!pending.isEmpty()) {
                bool changed = false;
                const auto keys = pending.keys();
                for (const auto &name : keys) {
                    try {
                        const auto resolved = kernel::native::resolve(pending.value(name), variables);
                        if (!resolved.isDouble() || !std::isfinite(resolved.toDouble())) throw Error("Invalid variable: " + name);
                        variables[name] = resolved.toDouble();
                        pending.remove(name);
                        changed = true;
                    } catch (const std::exception &) {}
                }
                if (!changed) throw Error("Unresolved or cyclic feature variables");
            }
        } else params = kernel::native::resolve(params, variables).toObject();
        feature["params"] = params;
        result.append(feature);
    }
    return result;
}
bool matchesType(const QJsonValue &value, const QString &type) {
    if (type == "object") return value.isObject();
    if (type == "array") return value.isArray();
    if (type == "string") return value.isString();
    if (type == "boolean") return value.isBool();
    if (type == "number") return value.isDouble() && std::isfinite(value.toDouble());
    if (type == "integer") return value.isDouble() && std::isfinite(value.toDouble()) && std::floor(value.toDouble()) == value.toDouble();
    if (type == "null") return value.isNull();
    return true;
}
void validate(const QJsonValue &value, const QJsonObject &schema, const QString &path) {
    if (schema.contains("anyOf")) {
        bool accepted = false;
        for (const auto &alternative : schema.value("anyOf").toArray()) {
            try { validate(value, alternative.toObject(), path); accepted = true; break; } catch (const Error &) {}
        }
        if (!accepted) throw Error("Invalid argument: " + path);
        return;
    }
    if (schema.contains("type")) {
        const auto types = schema.value("type");
        bool accepted = types.isString() && matchesType(value, types.toString());
        if (types.isArray()) for (const auto &type : types.toArray()) accepted = accepted || matchesType(value, type.toString());
        if (!accepted) throw Error("Invalid type for " + path);
    }
    if (schema.contains("enum") && !schema.value("enum").toArray().contains(value)) throw Error("Invalid choice for " + path);
    if (value.isDouble()) {
        const double number = value.toDouble();
        if (schema.contains("minimum") && number < schema.value("minimum").toDouble()) throw Error("Argument below minimum: " + path);
        if (schema.contains("maximum") && number > schema.value("maximum").toDouble()) throw Error("Argument above maximum: " + path);
    }
    if (value.isArray()) {
        const auto array = value.toArray();
        if (schema.contains("minItems") && array.size() < schema.value("minItems").toInt()) throw Error("Too few items in " + path);
        if (schema.contains("maxItems") && array.size() > schema.value("maxItems").toInt()) throw Error("Too many items in " + path);
        if (schema.value("items").isObject()) for (int index = 0; index < array.size(); ++index) validate(array[index], schema.value("items").toObject(), path + QStringLiteral("[%1]").arg(index));
    }
    if (value.isObject()) {
        const auto object = value.toObject();
        const auto properties = schema.value("properties").toObject();
        for (const auto &required : schema.value("required").toArray()) if (!object.contains(required.toString())) throw Error("Missing argument " + path + "." + required.toString());
        for (auto iterator = object.begin(); iterator != object.end(); ++iterator) {
            if (properties.contains(iterator.key())) validate(iterator.value(), properties.value(iterator.key()).toObject(), path + "." + iterator.key());
            else if (schema.value("additionalProperties").isObject()) validate(iterator.value(), schema.value("additionalProperties").toObject(), path + "." + iterator.key());
            else if (schema.contains("additionalProperties") && !schema.value("additionalProperties").toBool()) throw Error("Unknown argument " + path + "." + iterator.key());
        }
    }
}
void checkArguments(const QString &name, const QJsonObject &arguments) {
    QJsonObject schema;
    bool found = false;
    for (const auto &value : features::catalog()) {
        const auto item = value.toObject();
        if (item.value("name").toString() == name) { schema = item.value("input_schema").toObject(); found = true; break; }
    }
    if (!found) throw Error(QStringLiteral("Unknown command: %1").arg(name));
    const auto properties = schema.value("properties").toObject();
    if (!schema.value("additionalProperties").toBool()) {
        for (auto it = arguments.begin(); it != arguments.end(); ++it)
            if (!properties.contains(it.key())) throw Error(QStringLiteral("Command %1 has no argument %2").arg(name, it.key()));
    }
    for (const auto &value : schema.value("required").toArray())
        if (!arguments.contains(value.toString())) throw Error(QStringLiteral("Command %1 requires %2").arg(name, value.toString()));
    validate(arguments, schema, name);
}
bool changesGeometry(const QString &name) {
    return features::specs().contains(name) || QSet<QString>{"sketch", "extrude", "fillet", "chamfer", "edit_feature", "delete_feature", "suppress_feature", "rollback", "undo", "redo", "new_document", "open_document", "load_layout", "batch", "add_standard_part"}.contains(name);
}
QJsonObject briefModel(QJsonObject model, const QSet<QString> &focus = {}) {
    QJsonArray rows;
    for (const auto &value : model.value("features").toArray()) {
        const auto feature = value.toObject();
        QJsonObject row{{"id", feature.value("id")}, {"type", feature.value("type")},
            {"name", feature.value("name")}, {"status", feature.value("status")}};
        if (focus.contains(feature.value("id").toString())) {
            auto params = feature.value("params").toObject();
            if (feature.value("type") == "sketch") {
                params["shapes"] = QStringLiteral("%1 个图形").arg(params.value("shapes").toArray().size());
                if (!params.value("dims").toArray().isEmpty())
                    params["dims"] = QStringLiteral("%1 个尺寸").arg(params.value("dims").toArray().size());
            }
            row["params"] = params;
        }
        rows.append(row);
    }
    model["features"] = rows;
    model.remove("materials");
    model.remove("feature_colors");
    return model;
}
}

Session::Session(QObject *parent) : QObject(parent),
    model{{"status", QJsonObject{}}, {"sketches", QJsonObject{}}, {"has_body", false}},
    selection{{"faces", QJsonArray{}}, {"edges", QJsonArray{}}, {"feature", QJsonValue::Null}, {"plane", QJsonValue::Null}} {}

QJsonArray Session::tools() { return features::catalog(); }

QJsonObject Session::execute(const QString &command, const QJsonObject &arguments) {
    try {
        checkArguments(command, arguments);
        const auto before = document.revision;
        auto result = dispatch(command, arguments);
        if (result.contains("error") && !result.value("error").toString().isEmpty()) result["ok"] = false;
        if (!result.contains("ok")) result["ok"] = true;
        if (document.revision != before) {
            if (changesGeometry(command == "query" ? arguments.value("what").toString() : command)) { rebuild(); return afterChange(result); }
            if (modelRevision_ == before) modelRevision_ = document.revision;
            Q_EMIT changed();
            if (QSet<QString>{"rename_feature", "set_folder", "set_process"}.contains(command)) {
                auto answer = afterChange(result);
                answer["model"] = briefModel(answer.value("model").toObject());
                return answer;
            }
        }
        return result;
    } catch (const std::exception &error) {
        return {{"ok", false}, {"error", QString::fromUtf8(error.what())}};
    }
}

QJsonObject Session::rebuild() {
    busy = true;
    Q_EMIT changed();
    try {
        model = builder.build(document.features, document.upto, [this](int index, int total, const QString &name) { Q_EMIT progress(index, total, name); });
    } catch (const std::exception &error) {
        QJsonObject status;
        int index = 0;
        for (const auto &value : document.features) {
            const auto feature = value.toObject();
            status[feature.value("id").toString()] = document.upto && index >= *document.upto ? QString("rolled_back") : feature.value("suppressed").toBool() ? QString("suppressed") : QStringLiteral("error: %1").arg(QString::fromUtf8(error.what()));
            ++index;
        }
        model = {{"status", status}, {"sketches", QJsonObject{}}, {"has_body", false}};
    }
    modelRevision_ = document.revision;
    busy = false;
    selection["faces"] = QJsonArray{};
    selection["edges"] = QJsonArray{};
    if (!selection.value("feature").isNull()) {
        bool known = false;
        for (const auto &value : document.features) if (value.toObject().value("id") == selection.value("feature")) known = true;
        if (!known) selection["feature"] = QJsonValue::Null;
    }
    Q_EMIT changed();
    return model;
}

QJsonObject Session::state(const QString &identifier) const {
    const auto statuses = model.value("status").toObject();
    QJsonArray rows;
    for (const auto &value : document.features) {
        auto feature = value.toObject();
        if (!identifier.isEmpty() && feature.value("id").toString() != identifier) continue;
        feature["status"] = statuses.value(feature.value("id").toString()).toString("pending");
        rows.append(feature);
    }
    if (!identifier.isEmpty() && rows.isEmpty()) throw Error(QStringLiteral("Feature not found: %1").arg(identifier));
    QJsonArray materials;
    for (const auto &value : domain::material_catalog()) materials.append(value.toObject().value("name"));
    QJsonObject result{{"features", rows}, {"rollback", document.upto ? QJsonValue(*document.upto) : QJsonValue(QJsonValue::Null)},
                       {"has_body", model.value("has_body").toBool()}, {"path", document.path}, {"unsaved_changes", document.dirty},
                       {"material", document.props.value("material")}, {"materials", materials}, {"busy", busy},
                       {"model_stale", modelRevision_ != document.revision}, {"progress", QJsonValue::Null}, {"query_progress", QJsonValue::Null}};
    if (document.props.contains("feature_colors")) result["feature_colors"] = document.props.value("feature_colors");
    if (model.value("has_body").toBool()) {
        const auto properties = model.value("props").toObject();
        result["body"] = QJsonObject{{"size_mm", properties.value("size")}, {"bbox_min", properties.value("bbox_min")},
            {"bbox_max", properties.value("bbox_max")}, {"volume_mm3", properties.value("volume")}, {"area_mm2", properties.value("area")},
            {"faces", model.value("faces").toArray().size()}, {"edges", model.value("edges").toArray().size()}};
        if (const auto mass = domain::mass_grams(properties.value("volume").toDouble(), document.props.value("material").toString())) result["mass_g"] = *mass;
    }
    return result;
}

QJsonObject Session::afterChange(QJsonObject result) const {
    QStringList errors;
    const auto statuses = model.value("status").toObject();
    for (auto it = statuses.begin(); it != statuses.end(); ++it)
        if (it.value().toString().startsWith("error:")) errors.append(it.key() + ": " + it.value().toString().mid(6).trimmed());
    result["ok"] = errors.isEmpty() && result.value("ok").toBool(true);
    if (!errors.isEmpty()) {
        result["error"] = errors.join(QStringLiteral("；"));
        result["hint"] = "Failed features remain in the document; use edit_feature or undo to correct them.";
    }
    QSet<QString> touched;
    if (!result.value("id").toString().isEmpty()) touched.insert(result.value("id").toString());
    for (const auto &identifier : result.value("ids").toArray())
        if (!identifier.toString().isEmpty()) touched.insert(identifier.toString());
    result["model"] = briefModel(state(), touched);
    return result;
}

QJsonObject Session::dispatch(const QString &command, QJsonObject args) {
    if (command == "batch") {
        const auto steps = args.value("steps").toArray();
        const Document backup = document;
        QJsonArray made;
        QJsonObject names;
        int number = 0;
        QString stepName;
        try {
            for (const auto &value : steps) {
                ++number;
                if (!value.isObject()) throw Error("Each step must be an object");
                const auto step = value.toObject();
                stepName = step.value("cmd").toString();
                const QSet<QString> edits{"edit_feature", "delete_feature", "suppress_feature", "rename_feature", "set_folder", "set_process", "rollback"};
                if (!features::specs().contains(stepName) && !QSet<QString>{"sketch", "extrude", "fillet", "chamfer"}.contains(stepName) && !edits.contains(stepName))
                    throw Error(QStringLiteral("Command is not allowed in batch: %1").arg(stepName));
                if (step.contains("args") && !step.value("args").isObject()) throw Error("Step args must be an object");
                const auto values = fillReferences(step.value("args").toObject(), made, names).toObject();
                checkArguments(stepName, values);
                const auto result = dispatch(stepName, values);
                made.append(result.value("id").isUndefined() ? QJsonValue(QJsonValue::Null) : result.value("id"));
                if (step.contains("as")) names[step.value("as").toString()] = made.last();
            }
        } catch (const std::exception &error) {
            document = backup;
            throw Error(QStringLiteral("Batch step %1 (%2) failed: %3. Entire batch rolled back.").arg(number).arg(stepName, QString::fromUtf8(error.what())));
        }
        return {{"ids", made}, {"count", made.size()}};
    }
    if (command == "sketch") {
        const auto plane = args.value("plane").toString("XY");
        features::planeFrame(plane, document.features);
        QJsonObject params{{"plane", plane}, {"offset", args.value("offset").toDouble()}, {"shapes", args.value("shapes")}};
        if (args.contains("dims")) params["dims"] = args.value("dims");
        return {{"id", document.add("sketch", params, args.value("name").toString())}};
    }
    if (command == "extrude") {
        const QString source = args.value("sketch").toString(document.last("sketch"));
        if (document.find(source).value("type").toString() != "sketch") throw Error("extrude requires a sketch");
        const auto end = args.value("end").toString(args.value("symmetric").toBool() ? "mid" : "blind");
        if ((end == "blind" || end == "mid") && !args.contains("distance")) throw Error("extrude requires distance");
        const auto op = args.value("op").toString("add");
        if (!QStringList{"add", "cut", "common", "void", "fill", "pocket"}.contains(op)) throw Error("Unknown extrude operation");
        QJsonObject params{{"sketch", source}, {"distance", args.value("distance").toDouble(10)}, {"op", op}, {"symmetric", end == "mid"},
            {"end", end}, {"reverse", args.value("reverse").toBool()}, {"distance2", args.value("distance2").toDouble()},
            {"gap", args.value("gap").toDouble()}, {"target", args.value("target").toArray()}};
        if (args.contains("wall")) params["wall"] = args.value("wall");
        return {{"id", document.add(command, params, args.value("name").toString())}};
    }
    if (command == "fillet" || command == "chamfer") {
        auto params = args;
        params.remove("name");
        return {{"id", document.add(command, params, args.value("name").toString())}};
    }
    if (features::specs().contains(command)) {
        QJsonObject params;
        for (const auto &value : features::spec(command).value("fields").toArray()) {
            const auto field = value.toObject();
            const auto key = field.value("key").toString();
            const auto kind = field.value("kind").toString();
            auto item = args.contains(key) ? features::clean(field, args.value(key)) : field.value("default");
            if (!args.contains(key) && kind == "sketch" && !field.value("optional").toBool()) item = document.last("sketch");
            if ((kind == "sketch" || kind == "path") && (!item.toString().isEmpty() || !field.value("optional").toBool())) {
                const auto type = document.find(item.toString()).value("type").toString();
                if (type != "sketch" && (kind != "path" || !features::spec(type).value("curve").toBool())) throw Error(QStringLiteral("Invalid %1 reference: %2").arg(key, item.toString()));
            }
            if (kind == "features" || kind == "sketches") for (const auto &reference : item.toArray()) document.find(reference.toString());
            params[key] = item;
        }
        return {{"id", document.add(command, params, args.value("name").toString())}};
    }
    if (command == "edit_feature") { document.edit(args.value("id").toString(), args.value("params").toObject()); return {{"id", args.value("id")}}; }
    if (command == "delete_feature") { document.remove(args.value("id").toString()); return {}; }
    if (command == "suppress_feature") { document.suppress(args.value("id").toString(), args.value("suppressed").toBool(true)); return {{"id", args.value("id")}}; }
    if (command == "rename_feature") { document.rename(args.value("id").toString(), args.value("name").toString()); return {{"id", args.value("id")}}; }
    if (command == "set_folder") {
        const auto targets = strings(args.value("features").toArray());
        if (targets.isEmpty()) throw Error("features must not be empty");
        document.setFolder(targets, args.value("folder").toString());
        return {{"features", args.value("features")}, {"folder", args.value("folder")}};
    }
    if (command == "undo") { document.undo(); return {}; }
    if (command == "redo") { document.redo(); return {}; }
    if (command == "rollback") { document.rollback(args.contains("count") ? std::optional<int>(args.value("count").toInt()) : std::nullopt); return {}; }
    if (command == "new_document") { document.clear(); assembly_.clearCache(); return {}; }
    if (command == "open_document") { document.open(args.value("path").toString()); return {{"path", document.path}}; }
    if (command == "save_document") { document.save(args.value("path").toString()); Q_EMIT changed(); return {{"path", document.path}}; }
    if (command == "load_layout") { document.loadData(args.value("data").toObject()); return {{"features", document.features.size()}}; }
    if (command == "get_model") {
        auto result = state(args.value("id").toString());
        if (args.value("brief").toBool() && !args.contains("id")) {
            result = briefModel(result);
        }
        return result;
    }
    if (command == "list_edges" || command == "list_faces") {
        QJsonArray rows;
        const bool edges = command == "list_edges";
        for (const auto &value : model.value(edges ? "edges" : "faces").toArray()) {
            const auto item = value.toObject();
            if (edges && args.contains("type") && item.value("type") != args.value("type")) continue;
            QJsonObject row{{"type", item.value("type")}};
            if (edges) { row["point"] = item.value("mid"); row["length"] = item.value("length"); if (item.contains("dir")) row["direction"] = item.value("dir"); }
            else { row["center"] = item.value("center"); row["area"] = item.value("area"); if (item.contains("normal")) row["normal"] = item.value("normal"); }
            if (item.contains("radius")) row["radius"] = item.value("radius");
            rows.append(row);
        }
        return {{edges ? "edges" : "faces", rows}};
    }
    if (command == "get_selection") {
        QJsonObject result{{"feature", selection.value("feature")}, {"plane", selection.value("plane")}};
        for (const auto &kind : QStringList{"edges", "faces"}) {
            QJsonArray rows;
            for (const auto &identifier : selection.value(kind).toArray()) for (const auto &value : model.value(kind).toArray()) {
                const auto item = value.toObject();
                if (item.value("id") == identifier) rows.append(kind == "edges" ? QJsonObject{{"type", item.value("type")}, {"point", item.value("mid")}} : QJsonObject{{"type", item.value("type")}, {"center", item.value("center")}});
            }
            result[kind] = rows;
        }
        return result;
    }
    if (command == "export") {
        const auto built = builder.build(document.features, document.upto);
        const auto statuses = built.value("status").toObject();
        for (auto iterator = statuses.begin(); iterator != statuses.end(); ++iterator)
            if (iterator.value().toString().startsWith("error:")) throw Error("Cannot export a failed document: " + iterator.key() + ": " + iterator.value().toString());
        builder.exportFile(args.value("path").toString());
        return {{"path", args.value("path")}};
    }
    if (command == "set_view" || command == "screenshot") { if (!viewCommand) throw Error("View commands require an open GUI"); return viewCommand(command, args); }
    if (command == "query") { const auto what = args.take("what").toString(); return query(what, args); }
    return query(command, args);
}

QJsonObject Session::query(const QString &what, QJsonObject args) {
    if (what.isEmpty()) throw Error("query requires a nonempty what");
    const QSet<QString> assemblyQueries{"load", "load_assembly", "set_assembly", "assembly", "get_assembly", "capabilities", "fasteners", "motion_samples", "pose", "motion", "bom", "bill", "meshes", "drawing", "drag", "static", "stack", "interference", "contacts", "connections", "measure_parts", "mass_props", "mass", "sequence", "assembly_step", "sweep"};
    if (assemblyQueries.contains(what)) {
        assembly_.setDocument(document.features, document.upto, document.props, document.path);
        return assembly_.query(what, args);
    }
    for (const auto &tool : tools()) if (tool.toObject().value("name").toString() == what && what != "query") { checkArguments(what, args); break; }
    if (what == "model" || what == "get_model") return dispatch("get_model", args);
    if (what == "materials" || what == "list_materials") return {{"materials", domain::material_catalog()}};
    if (what == "processes" || what == "list_processes") return {{"processes", domain::process_catalog()}};
    if (what == "standard_parts" || what == "list_standard_parts") return {{"parts", domain::standard_part_catalog()}};
    if (what == "get_selection" || what == "list_edges" || what == "list_faces") return dispatch(what, args);
    if (what == "get_design_rules") return {{"rules", domain::effective_rules(property("userDesignRules").toJsonObject(), document.props.value("rules").toObject())}, {"table", domain::rule_table()}, {"document", document.props.value("rules").toObject()}};
    if (what == "set_design_rules") {
        if (args.value("scope").toString() == "user") throw Error("User-scoped rules require persistent GUI settings; use document scope");
        const auto clean = domain::clean_rules(args.value("values").toObject());
        if (clean.isEmpty()) throw Error("No recognized design rule in values");
        auto rules = document.props.value("rules").toObject();
        for (auto iterator = clean.begin(); iterator != clean.end(); ++iterator) rules[iterator.key()] = iterator.value();
        document.setProp("rules", rules);
        return {{"rules", domain::effective_rules(property("userDesignRules").toJsonObject(), rules)}};
    }
    if (what == "set_material") {
        const auto name = args.value("name").toString();
        bool known = name.isEmpty();
        for (const auto &value : domain::material_catalog()) if (value.toObject().value("name").toString() == name) known = true;
        if (!known) throw Error(QStringLiteral("Unknown material: %1").arg(name));
        document.setProp("material", name);
        return {{"material", name.isEmpty() ? QJsonValue(QJsonValue::Null) : QJsonValue(name)}};
    }
    if (what == "set_appearance") {
        const QString color = args.value("color").toString();
        if (!color.isEmpty() && !domain::rgb(color)) throw Error("color must be #RRGGBB");
        const auto targets = args.value("features").toArray();
        if (targets.isEmpty()) { document.setProp("color", color); return {{"color", color}}; }
        for (const auto &value : targets) document.find(value.toString());
        const double opacity = args.value("opacity").toDouble(1);
        if (!std::isfinite(opacity) || opacity < .05 || opacity > 1) throw Error("opacity must be between 0.05 and 1");
        auto colors = document.props.value("feature_colors").toObject();
        auto shades = document.props.value("feature_opacity").toObject();
        for (const auto &value : targets) {
            const auto identifier = value.toString();
            if (args.contains("color") || !args.contains("opacity")) { if (color.isEmpty()) colors.remove(identifier); else colors[identifier] = color; }
            if (args.contains("opacity")) { if (opacity == 1) shades.remove(identifier); else shades[identifier] = opacity; }
        }
        document.setProp("feature_colors", colors.isEmpty() ? QJsonValue(QJsonValue::Null) : QJsonValue(colors));
        document.setProp("feature_opacity", shades.isEmpty() ? QJsonValue(QJsonValue::Null) : QJsonValue(shades));
        return {{"features", targets}, {"color", color}, {"opacity", opacity}};
    }
    if (what == "set_process") {
        const auto feature = document.find(args.value("feature").toString());
        const auto identifier = feature.value("id").toString();
        const auto key = args.value("process").toString();
        if (key.isEmpty()) { document.setProcesses({{identifier, QJsonValue::Null}}); return {{"feature", identifier}, {"process", QJsonValue::Null}}; }
        QJsonObject process;
        for (const auto &value : domain::process_catalog()) if (value.toObject().value("id").toString() == key) process = value.toObject();
        if (process.isEmpty()) throw Error(QStringLiteral("Unknown process: %1").arg(key));
        process["auto"] = false;
        process["why"] = QStringLiteral("手动指定");
        process["alternatives"] = QJsonArray{};
        process["kind"] = feature.value("process").toObject().value("kind");
        process["standard"] = QSet<QString>{"standard", "purchase"}.contains(key);
        if (args.contains("cost")) {
            const double cost = args.value("cost").toDouble(-1);
            if (!std::isfinite(cost) || cost < 0) throw Error("cost must be nonnegative");
            process["cost"] = cost; process["unit"] = cost; process["tooling"] = 0;
        }
        if (args.contains("spec")) process["spec"] = args.value("spec");
        document.setProcesses({{identifier, process}});
        return {{"feature", identifier}, {"process", key}};
    }
    if (what == "bind_processes" || what == "check_design") {
        const auto rules = domain::effective_rules(property("userDesignRules").toJsonObject(), document.props.value("rules").toObject());
        if (modelRevision_ != document.revision) rebuild();
        const auto report = builder.query("inspect", what == "check_design" ? QJsonObject{{"rules", rules}} : QJsonObject{});
        if (report.contains("error")) throw Error(report.value("error").toString());
        const auto material = document.props.value("material").toString();
        if (what == "check_design") {
            const auto issues = domain::design_checks(resolvedFeatures(document.features), model, report, rules, material);
            return {{"counts", domain::issue_summary(issues)}, {"issues", issues}, {"red", QJsonArray::fromStringList(domain::red_features(issues))}};
        }
        const auto only = strings(args.value("features").toArray());
        for (const auto &identifier : only) document.find(identifier);
        const int batch = args.value("batch").toInt(rules.value("batch").toInt(1));
        if (batch < 1) throw Error("batch must be positive");
        const auto bound = domain::bind_processes(resolvedFeatures(document.features), report, batch, material, only);
        QJsonObject changed;
        for (auto iterator = bound.begin(); iterator != bound.end(); ++iterator)
            if (document.find(iterator.key()).value("process") != iterator.value()) changed[iterator.key()] = iterator.value();
        if (!changed.isEmpty()) document.setProcesses(changed);
        QJsonObject counts, rows;
        for (auto iterator = bound.begin(); iterator != bound.end(); ++iterator) {
            const auto process = iterator.value().toObject();
            const auto name = process.value("name").toString("No suitable process");
            counts[name] = counts.value(name).toInt() + 1;
            rows[iterator.key()] = QJsonObject{{"process", process.value("id")}, {"name", process.value("name")}, {"why", process.value("why")}};
        }
        return {{"bound", bound.size()}, {"batch", batch}, {"processes", counts}, {"features", rows}};
    }
    if (what == "make_standard_part" || what == "add_standard_part") {
        const auto part = domain::make_standard_part(args.value("kind").toString(), args.value("size").toString(), args.contains("length") ? std::optional<double>(args.value("length").toDouble()) : std::nullopt, args.value("series").toString());
        if (what == "make_standard_part") return {{"filename", part.first}, {"document", part.second}};
        const auto backup = document;
        QJsonObject identifiers, processes;
        QJsonArray made;
        try {
            for (const auto &value : part.second.value("features").toArray()) {
                const auto feature = value.toObject();
                const auto identifier = document.add(feature.value("type").toString(), remapReferences(feature.value("params"), identifiers).toObject(), feature.value("name").toString());
                identifiers[feature.value("id").toString()] = identifier;
                made.append(identifier);
                if (feature.contains("process")) processes[identifier] = feature.value("process");
            }
            if (made.isEmpty()) throw Error("Standard part generator returned no features");
            if (!processes.isEmpty()) document.setProcesses(processes);
            if (backup.features.isEmpty() && part.second.value("props").toObject().contains("material")) document.setProp("material", part.second.value("props").toObject().value("material"));
            if (args.contains("name")) document.rename(made.last().toString(), args.value("name").toString());
        } catch (...) { document = backup; throw; }
        return {{"id", made.last()}, {"ids", made}, {"filename", part.first}};
    }
    if (what == "screw_lengths") return {{"lengths", domain::screw_lengths(args.value("size").toString())}};
    if (what == "describe_document") return domain::describe_document(args.value("data").toObject(document.toData()));
    if (what == "describe_part") return domain::describe(args.value("path").toString());
    if (what == "bill_totals") return domain::bill_totals(args.value("rows").toArray());
    if (what == "proofing_checks") {
        if (modelRevision_ != document.revision) rebuild();
        const auto rules = domain::effective_rules(property("userDesignRules").toJsonObject(), document.props.value("rules").toObject());
        const auto report = builder.query("inspect", {{"rules", rules}});
        if (report.contains("error")) throw Error(report.value("error").toString());
        return {{"issues", domain::proofing_checks(resolvedFeatures(document.features), report, document.props.value("material").toString(), rules)}};
    }
    const QSet<QString> kernelQueries{"preview", "status", "properties", "props", "bounds", "edges", "faces", "vertices", "measure", "inspect", "section", "silhouette"};
    if (!kernelQueries.contains(what)) throw Error("Unknown query: " + what);
    if (modelRevision_ != document.revision) rebuild();
    return builder.query(what, args);
}

}
