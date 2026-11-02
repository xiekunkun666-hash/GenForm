#include "detail.hpp"
#include <algorithm>
#include <functional>
#include <limits>

namespace genform::assembly::detail {

double scalar(const QJsonValue &value, double fallback) {
    if (value.isUndefined() || value.isNull()) return fallback;
    bool valid = value.isDouble();
    const double result = value.isString() ? value.toString().toDouble(&valid) : value.toDouble();
    if (!valid || !std::isfinite(result)) fail("Expected a finite number");
    return result;
}

Vector coordinates(const QJsonValue &value, Vector fallback) {
    if (value.isUndefined() || value.isNull()) return fallback;
    if (!value.isArray() || value.toArray().size() != 3) fail("Expected three coordinates");
    const auto values = value.toArray();
    return {scalar(values[0]), scalar(values[1]), scalar(values[2])};
}

QJsonArray json(const Vector &value) { return {value[0], value[1], value[2]}; }

Matrix identity() {
    Matrix result{};
    for (int index = 0; index < 4; ++index) result[index][index] = 1;
    return result;
}

Matrix multiply(const Matrix &first, const Matrix &second) {
    Matrix result{};
    for (int row = 0; row < 4; ++row)
        for (int column = 0; column < 4; ++column)
            for (int inner = 0; inner < 4; ++inner)
                result[row][column] += first[row][inner] * second[inner][column];
    return result;
}

Vector apply(const Matrix &matrix, const Vector &value, bool direction) {
    Vector result{};
    for (int row = 0; row < 3; ++row) {
        result[row] = direction ? 0 : matrix[row][3];
        for (int column = 0; column < 3; ++column) result[row] += matrix[row][column] * value[column];
    }
    return result;
}

namespace {
Matrix rotation(Vector axis, double degrees, const Vector &origin) {
    const double length = std::hypot(axis[0], axis[1], axis[2]);
    if (length < 1e-12) fail("Motion axis cannot be zero");
    for (double &value : axis) value /= length;
    const double angle = degrees * std::acos(-1.0) / 180;
    const double cosine = std::cos(angle), sine = std::sin(angle);
    const double cross[3][3] = {{0, -axis[2], axis[1]}, {axis[2], 0, -axis[0]}, {-axis[1], axis[0], 0}};
    Matrix result = identity();
    for (int row = 0; row < 3; ++row)
        for (int column = 0; column < 3; ++column)
            result[row][column] = (row == column ? cosine : 0) + sine * cross[row][column] +
                                  (1 - cosine) * axis[row] * axis[column];
    const auto turned = apply(result, origin, true);
    for (int index = 0; index < 3; ++index) result[index][3] = origin[index] - turned[index];
    return result;
}
}

Matrix swingMatrix(const QJsonObject &swing, int depth) {
    if (swing.isEmpty()) return identity();
    if (depth > 64) fail("Motion nesting exceeds 64 levels");
    const auto axis = coordinates(swing["axis"]);
    const auto origin = coordinates(swing["origin"]);
    const double length = std::hypot(axis[0], axis[1], axis[2]);
    if (length < 1e-12) fail("Motion axis cannot be zero");
    Matrix result = identity();
    if (swing.contains("slide") && !swing["slide"].isNull()) {
        const double distance = scalar(swing["slide"]);
        for (int index = 0; index < 3; ++index) result[index][3] = axis[index] * distance / length;
    } else result = rotation(axis, scalar(swing["angle"]), origin);
    if (swing["then"].isObject()) result = multiply(swingMatrix(swing["then"].toObject(), depth + 1), result);
    return result;
}

Matrix placement(const QJsonObject &part) {
    Matrix result = identity();
    if (part["mirror"].toBool()) result[1][1] = -1;
    const auto turn = coordinates(part["turn"]), move = coordinates(part["move"]);
    for (int axis = 0; axis < 3; ++axis) {
        Vector direction{};
        direction[axis] = 1;
        result = multiply(rotation(direction, turn[axis], {0, 0, 0}), result);
    }
    for (int axis = 0; axis < 3; ++axis) result[axis][3] += move[axis];
    return multiply(swingMatrix(part["swing"].toObject()), result);
}

QJsonArray json(const Matrix &value) {
    QJsonArray result;
    for (const auto &row : value) result.append(QJsonArray{row[0], row[1], row[2], row[3]});
    return result;
}

QJsonObject readObject(const QString &path) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) fail("Cannot open " + path + ": " + file.errorString());
    QJsonParseError error;
    const auto document = QJsonDocument::fromJson(file.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) fail("Invalid JSON document " + path + ": " + error.errorString());
    return document.object();
}

QString absolutePath(const QString &path, const QString &baseDirectory) {
    const QFileInfo info(path);
    const QString full = info.isAbsolute() ? info.absoluteFilePath() : QDir(baseDirectory.isEmpty() ? QDir::currentPath() : baseDirectory).absoluteFilePath(path);
    const QString canonical = QFileInfo(full).canonicalFilePath();
    return QDir::cleanPath(canonical.isEmpty() ? full : canonical);
}

QMap<QString, double> parameterValues(const QJsonObject &params) {
    QMap<QString, double> known;
    QJsonObject pending = params;
    while (!pending.isEmpty()) {
        QStringList resolved;
        for (auto entry = pending.constBegin(); entry != pending.constEnd(); ++entry) {
            try {
                const auto value = kernel::native::resolve(entry.value(), known);
                known[entry.key()] = scalar(value);
                resolved.append(entry.key());
            } catch (const std::exception &) {}
        }
        if (resolved.isEmpty()) fail("Unresolved or cyclic assembly parameters: " + pending.keys().join(", "));
        for (const auto &key : resolved) pending.remove(key);
    }
    return known;
}
}

namespace genform::assembly {
using namespace detail;

QJsonObject resolveAssembly(const QJsonObject &data, const QString &baseDirectory) {
    if (data.contains("format") && data["format"] != "genform-assembly") fail("Not a GenForm assembly");
    if (data.contains("version") && data["version"].toInt() != 1) fail("Unsupported assembly version");
    if (!data["parts"].isArray()) fail("Assembly parts must be an array");
    const auto known = parameterValues(data["params"].toObject());
    QJsonArray parts;
    for (const auto &entry : data["parts"].toArray()) {
        if (!entry.isObject()) fail("Assembly part must be an object");
        auto part = entry.toObject();
        const QString source = part.value("path").toString(part["file"].toString());
        if (!source.isEmpty()) part["path"] = absolutePath(source, baseDirectory);
        else part["path"] = "";
        part.remove("file");
        for (const auto &field : {QString("move"), QString("turn")}) {
            auto values = part.value(field);
            if (values.isUndefined()) values = QJsonArray{0, 0, 0};
            auto resolved = kernel::native::resolve(values, known);
            const auto formulas = part["formula"].toObject()[field].toArray();
            if (!formulas.isEmpty()) {
                if (formulas.size() != 3) fail("Placement formula must have three entries");
                auto array = resolved.toArray();
                if (array.size() != 3) fail("Placement must have three entries");
                for (int axis = 0; axis < 3; ++axis)
                    if (!formulas[axis].isNull() && !formulas[axis].toString().isEmpty()) array[axis] = kernel::native::resolve(formulas[axis], known);
                resolved = array;
            }
            part[field] = json(coordinates(resolved));
        }
        if (part["name"].toString().isEmpty()) part["name"] = source.isEmpty() ? QString("零件%1").arg(parts.size() + 1) : QFileInfo(source).completeBaseName();
        placement(part);
        parts.append(part);
    }
    for (const auto &entry : data["mates"].toArray()) {
        const auto mate = entry.toObject();
        const int moving = mate["part"].toInt(-1), target = mate["to"].toInt(-1);
        const QString kind = mate["kind"].toString(), axisName = mate.value("axis").toString("Z").toUpper();
        const int axis = QString("XYZ").indexOf(axisName);
        if (moving < 0 || moving >= parts.size() || target < 0 || target >= parts.size() || target == moving || axisName.size() != 1 || axis < 0)
            fail("Invalid assembly mate reference");
        auto part = parts[moving].toObject();
        auto move = coordinates(part["move"]);
        const auto base = coordinates(parts[target].toObject()["move"]);
        if (kind == "coaxial") {
            for (int other = 0; other < 3; ++other) if (other != axis) move[other] = base[other];
        } else if (kind == "offset") move[axis] = base[axis] + scalar(kernel::native::resolve(mate.value("value"), known));
        else fail("Unknown mate kind: " + kind);
        part["move"] = json(move);
        parts[moving] = part;
    }
    QJsonObject result = data;
    QJsonObject values;
    for (auto entry = known.cbegin(); entry != known.cend(); ++entry) values[entry.key()] = entry.value();
    result["parts"] = parts;
    result["parameter_values"] = values;
    result["base_directory"] = baseDirectory.isEmpty() ? QDir::currentPath() : QDir(baseDirectory).absolutePath();
    return result;
}

QJsonObject pose(const QJsonArray &parts, const QJsonArray &definitions, std::optional<double> seconds) {
    if (seconds && (!std::isfinite(*seconds) || *seconds < 0)) fail("Motion time must be finite and nonnegative");
    QJsonArray joints = definitions;
    double slowest = std::numeric_limits<double>::infinity();
    for (const auto &entry : joints) {
        if (!entry.isObject()) fail("Joint definition must be an object");
        const double speed = scalar(entry.toObject()["speed"]);
        if (speed != 0) slowest = std::min(slowest, std::abs(speed));
    }
    const bool spinning = std::isfinite(slowest);
    const double length = spinning ? 360 / slowest : 4.0;
    QJsonArray values;
    for (int index = 0; index < joints.size(); ++index) {
        auto joint = joints[index].toObject();
        const QString kind = joint.value("kind").toString("hinge");
        if (kind != "hinge" && kind != "slide") fail("Unknown joint kind: " + kind);
        joint["kind"] = kind;
        if (!joint["parts"].isArray() || !joint["axis"].isArray() || !joint["origin"].isArray()) fail("Joint requires parts, axis and origin arrays");
        const auto axis = coordinates(joint["axis"]);
        coordinates(joint["origin"]);
        if (std::hypot(axis[0], axis[1], axis[2]) < 1e-12) fail("Joint axis cannot be zero");
        const double minimum = scalar(joint["min"]), maximum = scalar(joint["max"], 90);
        if (minimum > maximum) fail("Joint minimum exceeds maximum");
        double value = scalar(joint["value"]);
        if (seconds) {
            if (spinning) value = std::fmod(scalar(joint["speed"]) * *seconds, 360.0);
            else {
                const auto ease = [](double fraction) { fraction = std::clamp(fraction, 0.0, 1.0); return fraction * fraction * (3 - 2 * fraction); };
                const double fraction = *seconds <= 1.6 ? ease(*seconds / 1.6) : *seconds <= 2.4 ? 1 : 1 - ease((*seconds - 2.4) / 1.6);
                const double closed = minimum <= 0 && maximum >= 0 ? 0 : minimum;
                value = closed + (maximum - closed) * fraction;
            }
        }
        joint["value"] = value;
        joints[index] = joint;
        values.append(value);
    }
    std::vector<int> visiting(static_cast<size_t>(joints.size()));
    std::vector<QJsonObject> swings(static_cast<size_t>(joints.size()));
    std::function<QJsonObject(int)> compute = [&](int index) -> QJsonObject {
        if (visiting[index] == 1) fail("Cyclic joint parent dependency");
        if (visiting[index] == 2) return swings[index];
        visiting[index] = 1;
        const auto joint = joints[index].toObject();
        const int parent = joint["on"].toInt(-1);
        if (parent < -1 || parent >= joints.size() || parent == index) fail("Invalid joint parent reference");
        QJsonObject inherited = parent >= 0 ? compute(parent) : QJsonObject{};
        const double value = scalar(joint["value"]);
        QJsonObject swing = inherited;
        if (std::abs(value) >= 1e-12) {
            swing = {{"origin", json(coordinates(joint["origin"]))}, {"axis", json(coordinates(joint["axis"]))},
                     {joint["kind"] == "slide" ? "slide" : "angle", value}};
            if (!inherited.isEmpty()) swing["then"] = inherited;
        }
        visiting[index] = 2;
        swings[index] = swing;
        return swing;
    };
    QJsonArray resultParts = parts, links;
    QSet<int> owned;
    for (int index = 0; index < joints.size(); ++index) {
        const auto joint = joints[index].toObject();
        const auto swing = compute(index);
        const int base = joint["base"].toInt(0);
        if (base < -1 || base >= parts.size()) fail("Invalid joint base reference");
        for (const auto &entry : joint["parts"].toArray()) {
            const int partIndex = entry.toInt(-1);
            if (partIndex < 0 || partIndex >= parts.size()) fail("Invalid joint part reference");
            if (owned.contains(partIndex)) fail("A part cannot belong to multiple joints");
            owned.insert(partIndex);
            auto part = resultParts[partIndex].toObject();
            part.remove("swing");
            if (!swing.isEmpty()) part["swing"] = swing;
            resultParts[partIndex] = part;
            if (base >= 0 && base != partIndex) links.append(QJsonArray{base, partIndex});
        }
    }
    QJsonArray matrices;
    for (const auto &part : resultParts) matrices.append(json(placement(part.toObject())));
    return {{"parts", resultParts}, {"joints", joints}, {"values", values}, {"links", links},
            {"matrices", matrices}, {"length", length}, {"spinning", spinning}};
}

QJsonObject motionSamples(const QJsonArray &parts, const QJsonArray &joints, int samples) {
    if (samples < 2 || samples > 1000) fail("Motion samples must be between 2 and 1000");
    const auto initial = pose(parts, joints);
    QJsonArray sampled;
    if (initial["spinning"].toBool()) {
        QJsonArray poses;
        for (int step = 0; step < samples; ++step) {
            const double seconds = initial["length"].toDouble() * (step + 0.37) / samples;
            const auto positioned = pose(parts, joints, seconds);
            QJsonObject swings;
            const auto posedParts = positioned["parts"].toArray();
            for (int index = 0; index < posedParts.size(); ++index) {
                const auto swing = posedParts[index].toObject()["swing"].toObject();
                if (!swing.isEmpty()) swings[QString::number(index)] = swing;
            }
            poses.append(QJsonObject{{"value", seconds}, {"swings", swings}});
        }
        sampled.append(QJsonObject{{"name", "continuous motion"}, {"poses", poses}});
    } else {
        for (const auto &entry : joints) {
            auto joint = entry.toObject();
            QJsonArray values;
            const double minimum = scalar(joint["min"]), maximum = scalar(joint["max"], 90);
            for (int step = 0; step < samples; ++step) values.append(minimum + (maximum - minimum) * step / (samples - 1));
            joint["values"] = values;
            sampled.append(joint);
        }
    }
    return {{"joints", sampled}, {"sampled", true}, {"continuous_collision_detection", false},
            {"length", initial["length"]}, {"samples", samples}};
}
}
