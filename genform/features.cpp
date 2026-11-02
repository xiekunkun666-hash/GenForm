#include "genform/features.hpp"
#include "genform/document.hpp"
#include "genform/domain/geometry.hpp"
#include <QFile>
#include <QCoreApplication>
#include <QDir>
#include <QJsonDocument>
#include <QQuaternion>
#include <QRegularExpression>
#include <cmath>

namespace genform::features {
namespace {
QJsonObject data() {
    static const auto result = [] {
        QFile file(QStringLiteral(":/genform/commands.json"));
        if (!file.open(QIODevice::ReadOnly)) {
            const QStringList paths{QDir(QCoreApplication::applicationDirPath()).filePath("commands.json"),
                QDir(QCoreApplication::applicationDirPath()).filePath("../share/genform/commands.json"),
                QStringLiteral(GENFORM_SOURCE_DIR "/genform/commands.json")};
            for (const auto &path : paths) { file.setFileName(path); if (file.open(QIODevice::ReadOnly)) break; }
            if (!file.isOpen()) throw Error("Cannot read native command catalog: " + file.fileName());
        }
        QJsonParseError error;
        const auto document = QJsonDocument::fromJson(file.readAll(), &error);
        if (error.error != QJsonParseError::NoError || !document.isObject()) throw Error("Invalid native command catalog: " + error.errorString());
        return document.object();
    }();
    return result;
}
QJsonObject type(const QString &name) { return {{"type", name}}; }
QJsonObject choices(const QStringList &names) { return {{"enum", QJsonArray::fromStringList(names)}}; }
QJsonObject array(const QJsonObject &items) { return {{"type", "array"}, {"items", items}}; }
QJsonObject number() { return type("number"); }
QJsonObject text() { return type("string"); }
QJsonObject edges() {
    return {{"description", "Edge list [{point:[x,y,z]}] or selector: all, |X, |Y, |Z, >X, <X, >Y, <Y, >Z, <Z"},
        {"anyOf", QJsonArray{text(), array(QJsonObject{{"type", "object"}, {"properties", QJsonObject{{"point", QJsonObject{{"type", "array"}, {"items", number()}, {"minItems", 3}, {"maxItems", 3}}}}}, {"required", QJsonArray{"point"}}})}}};
}
QJsonObject faces() { return array(QJsonObject{{"type", "object"}, {"properties", QJsonObject{{"point", QJsonObject{{"type", "array"}, {"items", number()}, {"minItems", 3}, {"maxItems", 3}}}}}, {"required", QJsonArray{"point"}}}); }
QJsonObject fieldSchema(const QJsonObject &field) {
    const auto kind = field.value("kind").toString();
    QJsonObject schema;
    if (kind == "number" || kind == "int") schema = {{"type", QJsonArray{kind == "int" ? "integer" : "number", "string"}}};
    else if (kind == "bool") schema = type("boolean");
    else if (kind == "vars") schema = {{"type", "object"}, {"additionalProperties", QJsonObject{{"type", QJsonArray{"number", "string"}}}}};
    else if (kind == "points") schema = array(array(number()));
    else if (kind == "features" || kind == "sketches") schema = array(text());
    else if (kind == "faces") schema = faces();
    else if (kind == "edges") schema = edges();
    else if (kind == "choice") {
        QJsonArray options;
        for (const auto &value : field.value("options").toArray()) options.append(value.toObject().value("value"));
        schema["enum"] = options;
    } else schema = text();
    schema["description"] = field.value("label").toString() + (field.value("help").toString().isEmpty() ? QString{} : QStringLiteral("。") + field.value("help").toString());
    return schema;
}
double numeric(const QJsonValue &value) {
    bool valid = value.isDouble();
    const double result = value.isDouble() ? value.toDouble() : value.toString().toDouble(&valid);
    if (!valid || !std::isfinite(result)) throw Error("Expected a finite number");
    return result;
}
QJsonArray coordinates(const QJsonValue &value, int width) {
    QJsonArray rows;
    if (value.isString()) {
        auto input = value.toString();
        input.replace(QChar(0xff1b), ';').replace(QChar(0xff0c), ',').replace('\n', ';');
        for (const auto &line : input.split(';', Qt::SkipEmptyParts)) {
            QJsonArray row;
            for (const auto &part : line.split(QRegularExpression("[,\\s]+"), Qt::SkipEmptyParts)) row.append(numeric(part));
            if (!row.isEmpty()) rows.append(row);
        }
    } else if (value.isArray()) {
        const auto input = value.toArray();
        if (!input.isEmpty() && !input.first().isArray()) rows.append(input);
        else rows = input;
    } else throw Error("Points must be an array or coordinate text");
    QJsonArray result;
    for (const auto &point : rows) {
        if (!point.isArray()) throw Error("Each point must be an array");
        const auto input = point.toArray();
        if (width > 0 && input.size() != width) throw Error(QStringLiteral("Each point requires %1 coordinates").arg(width));
        QJsonArray row;
        for (const auto &coordinate : input) row.append(numeric(coordinate));
        result.append(row);
    }
    return result;
}
QJsonArray vector(const QVector3D &value) { return {value.x(), value.y(), value.z()}; }
QVector3D vector(const QJsonValue &value) {
    const auto row = value.toArray();
    if (row.size() != 3) throw Error("Expected a three-dimensional vector");
    return QVector3D(float(numeric(row[0])), float(numeric(row[1])), float(numeric(row[2])));
}
}

QJsonObject specs() {
    static const auto definitions = [] {
        auto result = data().value("specs").toObject();
        for (auto iterator = result.begin(); iterator != result.end(); ++iterator) {
            auto item = iterator.value().toObject();
            QJsonArray fields;
            for (const auto &value : item.value("fields").toArray()) {
                const auto row = value.toArray();
                QJsonObject field{{"key", row[0]}, {"kind", row[1]}, {"label", row[0]}, {"default", row[2]}};
                if (row.size() > 3) {
                    if (row[3].isArray()) {
                        QJsonArray options;
                        for (const auto &option : row[3].toArray()) options.append(QJsonObject{{"value", option}, {"label", option}});
                        field["options"] = options;
                    } else {
                        const auto extra = row[3].toObject();
                        for (auto extraIt = extra.begin(); extraIt != extra.end(); ++extraIt) field[extraIt.key()] = extraIt.value();
                    }
                }
                fields.append(field);
            }
            item["fields"] = fields;
            if (!item.contains("short")) item["short"] = item.value("title");
            iterator.value() = item;
        }
        return result;
    }();
    return definitions;
}
QJsonObject spec(const QString &kind) { return specs().value(kind).toObject(); }
QString title(const QString &kind) {
    const QJsonObject basic{{"sketch", QStringLiteral("草图")}, {"extrude", QStringLiteral("拉伸")}, {"fillet", QStringLiteral("圆角")}, {"chamfer", QStringLiteral("倒角")}};
    return basic.contains(kind) ? basic.value(kind).toString() : spec(kind).value("short").toString(kind);
}
QStringList curveKinds() {
    QStringList result;
    const auto definitions = specs();
    for (auto iterator = definitions.begin(); iterator != definitions.end(); ++iterator) if (iterator.value().toObject().value("curve").toBool()) result.append(iterator.key());
    return result;
}
QStringList toolKinds() {
    QStringList result{"extrude"};
    const auto definitions = specs();
    for (auto iterator = definitions.begin(); iterator != definitions.end(); ++iterator) if (iterator.value().toObject().value("tool").toBool()) result.append(iterator.key());
    return result;
}
QJsonObject defaultParams(const QString &kind) {
    QJsonObject result;
    for (const auto &value : spec(kind).value("fields").toArray()) { const auto field = value.toObject(); result[field.value("key").toString()] = field.value("default"); }
    return result;
}
QJsonValue clean(const QJsonObject &field, const QJsonValue &value) {
    const auto kind = field.value("kind").toString();
    if ((kind == "number" || kind == "int") && value.isString() && value.toString().trimmed().startsWith('=')) return value.toString().trimmed();
    if (kind == "number") return numeric(value);
    if (kind == "int") return std::nearbyint(numeric(value));
    if (kind == "bool") { if (!value.isBool()) throw Error("Expected a boolean"); return value; }
    if (kind == "points") return coordinates(value, field.value("width").toInt());
    if (kind == "vars") {
        QJsonObject input;
        if (value.isObject()) input = value.toObject();
        else if (value.isString()) {
            auto source = value.toString(); source.replace(QChar(0xff1b), ';').replace('\n', ';');
            for (const auto &row : source.split(';', Qt::SkipEmptyParts)) {
                const auto split = row.indexOf('=');
                if (split < 0) throw Error("Variables require name=value");
                input[row.left(split).trimmed()] = row.mid(split + 1).trimmed();
            }
        } else throw Error("Variables must be an object or name=value text");
        QJsonObject result;
        const QRegularExpression identifier(QStringLiteral("^[\\p{L}_][\\p{L}\\p{N}_]*$"));
        for (auto iterator = input.begin(); iterator != input.end(); ++iterator) {
            const auto name = iterator.key().trimmed();
            if (!identifier.match(name).hasMatch()) throw Error("Invalid variable name: " + name);
            if (iterator.value().isDouble()) result[name] = numeric(iterator.value());
            else {
                const auto expression = iterator.value().toString().trimmed();
                bool valid = false;
                const double number = (expression.startsWith('=') ? expression.mid(1) : expression).toDouble(&valid);
                result[name] = valid && std::isfinite(number) ? QJsonValue(number) : QJsonValue(expression.startsWith('=') ? expression : "=" + expression);
            }
        }
        return result;
    }
    if (kind == "choice") {
        for (const auto &option : field.value("options").toArray()) if (option.toObject().value("value") == value) return value;
        throw Error("Invalid choice for " + field.value("key").toString());
    }
    if (kind == "features" || kind == "sketches") {
        if (value.isString()) return QJsonArray{value};
        if (!value.isArray()) throw Error("References must be an array");
        for (const auto &item : value.toArray()) if (!item.isString()) throw Error("Feature ids must be strings");
        return value;
    }
    if (kind == "edges" || kind == "faces") {
        if (!value.isString() && !value.isArray()) throw Error("Expected a selector or reference array");
        return value;
    }
    if (!value.isString()) throw Error("Expected a string for " + field.value("key").toString());
    return value;
}

QJsonArray catalog() {
    static const auto tools = [] {
        QJsonArray result;
        auto add = [&result](const QString &name, const QString &description, const QJsonObject &properties = {}, const QJsonArray &required = {}, bool open = false) {
            result.append(QJsonObject{{"name", name}, {"description", description}, {"input_schema", QJsonObject{{"type", "object"}, {"properties", properties}, {"required", required}, {"additionalProperties", open}}}});
        };
        QJsonObject shapeProperties{{"type", choices({"line", "arc", "circle", "rect", "polygon", "ngon", "slot", "arcslot", "ellipse", "spline", "equation", "point", "text"})},
            {"construction", type("boolean")}, {"style", type("boolean")}, {"closed", type("boolean")}, {"flip", type("boolean")},
            {"points", array(QJsonObject{{"type", "array"}, {"items", number()}, {"minItems", 2}, {"maxItems", 2}})}, {"text", text()}, {"font", text()}, {"path", type("object")},
            {"mode", choices({"explicit", "parametric"})}, {"fx", text()}, {"fy", text()}};
        for (const auto &key : QStringList{"x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "w", "h", "a0", "a1", "angle", "height", "t0", "t1", "ox", "oy"}) shapeProperties[key] = number();
        shapeProperties["sides"] = type("integer");
        auto shapes = array(QJsonObject{{"type", "object"}, {"properties", shapeProperties}, {"required", QJsonArray{"type"}}});
        shapes["minItems"] = 1;
        shapes["description"] = "2D sketch geometry in mm and degrees. line:x1 y1 x2 y2; arc:cx cy r a0 a1; circle:cx cy r; rect:cx cy w h; polygon/spline:points; ngon:cx cy r sides angle; slot:x1 y1 x2 y2 w; ellipse:cx cy rx ry angle; arcslot:cx cy r a0 a1 w; equation:mode fx fy t0 t1 ox oy; point:x y; text:x y text height angle font path flip. Closed connected loops form profiles; construction=true excludes geometry.";
        add("sketch", QStringLiteral("新建草图"), {{"plane", text()}, {"offset", number()}, {"shapes", shapes}, {"name", text()}, {"dims", array(type("object"))}}, {"shapes"});
        add("extrude", QStringLiteral("拉伸草图成实体"), {{"sketch", text()}, {"distance", number()}, {"op", choices({"add", "cut", "common", "void", "fill", "pocket"})}, {"wall", number()}, {"symmetric", type("boolean")}, {"end", choices({"blind", "through", "vertex", "surface", "offset", "body", "mid"})}, {"reverse", type("boolean")}, {"distance2", number()}, {"target", type("array")}, {"gap", number()}, {"name", text()}});
        add("fillet", QStringLiteral("给实体的边倒圆角"), {{"edges", edges()}, {"radius", number()}, {"name", text()}}, {"edges", "radius"});
        add("chamfer", QStringLiteral("给实体的边倒斜角"), {{"edges", edges()}, {"distance", number()}, {"name", text()}}, {"edges", "distance"});
        const auto definitions = specs();
        for (auto iterator = definitions.begin(); iterator != definitions.end(); ++iterator) {
            const auto item = iterator.value().toObject();
            QJsonObject properties{{"name", text()}};
            QJsonArray required;
            for (const auto &value : item.value("fields").toArray()) {
                const auto field = value.toObject();
                const auto key = field.value("key").toString();
                const auto kind = field.value("kind").toString();
                properties[key] = fieldSchema(field);
                const auto fallback = field.value("default");
                if ((fallback.isNull() || (fallback.isArray() && fallback.toArray().isEmpty())) && kind != "sketch" && kind != "features" && !field.value("optional").toBool()) required.append(key);
            }
            add(iterator.key(), item.value("title").toString() + QStringLiteral("：") + item.value("about").toString(), properties, required);
        }
        add("edit_feature", QStringLiteral("修改已有特征的参数"), {{"id", text()}, {"params", type("object")}}, {"id", "params"});
        add("delete_feature", QStringLiteral("删除特征"), {{"id", text()}}, {"id"});
        add("suppress_feature", QStringLiteral("抑制或恢复特征"), {{"id", text()}, {"suppressed", type("boolean")}}, {"id"});
        add("rename_feature", QStringLiteral("给特征改名，不重算"), {{"id", text()}, {"name", text()}}, {"id", "name"});
        add("set_folder", QStringLiteral("把特征放入设计树文件夹"), {{"features", array(text())}, {"folder", text()}}, {"features"});
        add("list_processes", QStringLiteral("列出加工工艺"));
        add("get_design_rules", QStringLiteral("查看设计规则"));
        add("set_design_rules", QStringLiteral("修改设计规则"), {{"values", type("object")}, {"scope", choices({"document", "user"})}}, {"values"});
        add("bind_processes", QStringLiteral("自动绑定现实加工工艺"), {{"features", array(text())}, {"batch", type("integer")}});
        add("set_process", QStringLiteral("手动指定或清除加工工艺"), {{"feature", text()}, {"process", text()}, {"cost", QJsonObject{{"type", "number"}, {"minimum", 0}}}, {"spec", text()}}, {"feature"});
        add("check_design", QStringLiteral("执行设计检查"));
        add("rollback", QStringLiteral("回滚特征历史；省略count取消回滚"), {{"count", QJsonObject{{"type", "integer"}, {"minimum", 0}}}});
        add("set_material", QStringLiteral("指定材质；省略name清除"), {{"name", text()}});
        add("set_appearance", QStringLiteral("修改零件或特征颜色和透明度"), {{"color", text()}, {"features", array(text())}, {"opacity", QJsonObject{{"type", "number"}, {"minimum", 0.05}, {"maximum", 1}}}});
        add("undo", QStringLiteral("撤销")); add("redo", QStringLiteral("重做")); add("new_document", QStringLiteral("新建零件"));
        add("save_document", QStringLiteral("保存gform文档"), {{"path", text()}});
        add("open_document", QStringLiteral("打开gform文档"), {{"path", text()}}, {"path"});
        add("load_layout", QStringLiteral("载入装配布局草图"), {{"data", type("object")}}, {"data"});
        add("export", QStringLiteral("导出STEP或STL"), {{"path", text()}}, {"path"});
        add("set_view", QStringLiteral("切换三维视图"), {{"view", choices({"iso", "top", "bottom", "front", "back", "left", "right", "fit"})}}, {"view"});
        add("screenshot", QStringLiteral("保存当前视图PNG"), {{"path", text()}, {"view", choices({"iso", "top", "bottom", "front", "back", "left", "right"})}});
        auto steps = array(QJsonObject{{"type", "object"}, {"properties", QJsonObject{{"cmd", text()}, {"args", type("object")}, {"as", text()}}}, {"required", QJsonArray{"cmd"}}});
        add("batch", QStringLiteral("原子批量修改；用$1或$别名引用先前步骤，仅重算一次"), {{"steps", steps}}, {"steps"});
        add("get_model", QStringLiteral("查看模型、特征参数和状态"), {{"id", text()}, {"brief", type("boolean")}});
        add("list_edges", QStringLiteral("列出边的中点、方向和长度"), {{"type", choices({"line", "circle", "curve"})}});
        add("list_faces", QStringLiteral("列出面类型、中心和面积")); add("get_selection", QStringLiteral("查看当前选择"));
        add("query", QStringLiteral("原生查询：装配、工程图、干涉、材料、工艺、检查与内核查询；未知查询明确失败"), {{"what", text()}}, {"what"}, true);
        add("list_materials", QStringLiteral("列出材料、密度和力学参数"));
        add("list_standard_parts", QStringLiteral("列出标准件"));
        add("screw_lengths", QStringLiteral("列出螺丝标准长度"), {{"size", text()}}, {"size"});
        add("add_standard_part", QStringLiteral("建立标准件特征"), {{"kind", text()}, {"size", text()}, {"length", number()}, {"series", text()}, {"name", text()}}, {"kind", "size"});
        return result;
    }();
    return tools;
}

QJsonObject planeFrame(const QJsonValue &reference, const QJsonArray &features, double offset, int depth) {
    if (depth > 50) throw Error("Cyclic or excessively nested reference plane");
    domain::PlaneFrame result;
    if (reference.isObject() || QStringList{"XY", "XZ", "YZ"}.contains(reference.toString().toUpper())) result = domain::frame(reference.isString() ? QJsonValue(reference.toString().toUpper()) : reference);
    else {
        QJsonObject params;
        for (const auto &value : features) { const auto feature = value.toObject(); if (feature.value("id") == reference && feature.value("type") == "plane") params = feature.value("params").toObject(); }
        if (params.isEmpty()) throw Error("Reference plane not found: " + reference.toString());
        if (!params.value("origin").toArray().isEmpty() && !params.value("normal").toArray().isEmpty()) {
            result.origin = vector(params.value("origin").toArray().first());
            result.normal = vector(params.value("normal").toArray().first());
            if (result.normal.lengthSquared() < 1e-24f) throw Error("Plane normal must not be zero");
            result.normal.normalize();
            const auto helper = std::abs(result.normal.z()) < .9 ? QVector3D(0, 0, 1) : QVector3D(1, 0, 0);
            result.x = QVector3D::crossProduct(helper, result.normal).normalized();
            result.y = QVector3D::crossProduct(result.normal, result.x);
        } else result = domain::frame(planeFrame(params.value("base").toString("XY"), features, 0, depth + 1));
        const float angle = float(params.value("angle").toDouble());
        if (angle != 0) {
            const auto rotation = QQuaternion::fromAxisAndAngle(params.value("about").toString("x") == "x" ? result.x : result.y, angle);
            result.x = rotation.rotatedVector(result.x); result.y = rotation.rotatedVector(result.y); result.normal = QVector3D::crossProduct(result.x, result.y).normalized();
        }
        result.origin += float(params.value("offset").toDouble()) * result.normal;
    }
    result.origin += float(offset) * result.normal;
    return {{"origin", vector(result.origin)}, {"x", vector(result.x)}, {"y", vector(result.y)}};
}

QJsonObject axisOf(const QString &reference, const QJsonArray &features, const QJsonObject &sketchFrame) {
    QVector3D origin, direction;
    const auto name = reference.toUpper();
    if (reference.startsWith('@')) {
        const auto rows = reference.mid(1).split(';');
        if (rows.size() != 2) throw Error("Axis syntax is @x,y,z;dx,dy,dz");
        const auto origins = coordinates(rows[0], 3), directions = coordinates(rows[1], 3);
        if (origins.size() != 1 || directions.size() != 1) throw Error("Axis requires one origin and one direction");
        origin = vector(origins.first());
        direction = vector(directions.first());
    } else if (name == "X") direction = {1, 0, 0};
    else if (name == "Y") direction = {0, 1, 0};
    else if (name == "Z") direction = {0, 0, 1};
    else if ((name == "SX" || name == "SY") && !sketchFrame.isEmpty()) {
        const auto frame = domain::frame(sketchFrame);
        origin = frame.origin;
        direction = name == "SX" ? frame.x : frame.y;
    } else {
        bool found = false;
        for (const auto &value : features) {
            const auto feature = value.toObject();
            if (feature.value("id").toString() != reference || feature.value("type") != "axis") continue;
            const auto params = feature.value("params").toObject();
            if (params.value("origin").toArray().isEmpty() || params.value("direction").toArray().isEmpty()) throw Error("Axis requires origin and direction");
            origin = vector(params.value("origin").toArray().first());
            direction = vector(params.value("direction").toArray().first());
            found = true;
            break;
        }
        if (!found) throw Error("Reference axis not found: " + reference);
    }
    if (direction.lengthSquared() < 1e-24f) throw Error("Axis direction must not be zero");
    return {{"origin", vector(origin)}, {"direction", vector(direction.normalized())}};
}

QJsonObject csysAxes(const QJsonObject &params) {
    const auto origins = params.value("origin").toArray();
    if (origins.isEmpty()) throw Error("Coordinate system requires origin");
    QVector3D axes[3]{{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    const QStringList names{"rx", "ry", "rz"};
    for (int index = 0; index < 3; ++index) {
        const QVector3D axis = index == 0 ? QVector3D(1, 0, 0) : index == 1 ? QVector3D(0, 1, 0) : QVector3D(0, 0, 1);
        const auto rotation = QQuaternion::fromAxisAndAngle(axis, float(numeric(params.contains(names[index]) ? params.value(names[index]) : QJsonValue(0))));
        for (auto &basis : axes) basis = rotation.rotatedVector(basis);
    }
    return {{"origin", vector(vector(origins.first()))}, {"x", vector(axes[0])}, {"y", vector(axes[1])}, {"z", vector(axes[2])}};
}

}
