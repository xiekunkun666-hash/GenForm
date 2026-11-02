#include "geometry.hpp"

#include <QJsonDocument>
#include <QSet>
#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <numbers>

namespace genform::domain {
namespace {
constexpr double Pi = std::numbers::pi;
constexpr double Tau = 2 * Pi;
double radians(double degrees) { return degrees * Pi / 180; }
double degrees(double angle) { return angle * 180 / Pi; }
double modulo(double value, double divisor = Tau) { return value - std::floor(value / divisor) * divisor; }
QVector2D point(double x, double y) {
    if (!std::isfinite(x) || !std::isfinite(y) || std::abs(x) > std::numeric_limits<float>::max() || std::abs(y) > std::numeric_limits<float>::max())
        throw DomainError(QStringLiteral("坐标超出有限 QVector2D 范围"));
    return {float(x), float(y)};
}
QJsonArray json(const QVector2D& value) { return {double(value.x()), double(value.y())}; }
QJsonArray json(const QVector<QVector2D>& values) {
    QJsonArray result;
    for (const auto& value : values) result.append(json(value));
    return result;
}
QVector2D readPoint(const QJsonValue& value) {
    const auto values = value.toArray();
    if (values.size() < 2 || !values[0].isDouble() || !values[1].isDouble()
        || !std::isfinite(values[0].toDouble()) || !std::isfinite(values[1].toDouble()))
        throw DomainError(QStringLiteral("点必须包含两个有限数字"));
    return point(values[0].toDouble(), values[1].toDouble());
}
QVector<QVector2D> points(const QJsonObject& shape, int least) {
    QVector<QVector2D> result;
    for (const auto& value : shape.value("points").toArray()) result.append(readPoint(value));
    if (result.size() < least) throw DomainError(QStringLiteral("%1 至少要 %2 个点").arg(shape.value("type").toString()).arg(least));
    return result;
}
QVector2D polar(const QVector2D& centre, double radius, double angle) {
    return point(centre.x() + radius * std::cos(angle), centre.y() + radius * std::sin(angle));
}
double angle(const QVector2D& centre, const QVector2D& value) { return std::atan2(double(value.y()) - centre.y(), double(value.x()) - centre.x()); }
double dot(const QVector2D& first, const QVector2D& second) { return double(first.x()) * second.x() + double(first.y()) * second.y(); }
double cross(const QVector2D& first, const QVector2D& second) { return double(first.x()) * second.y() - double(first.y()) * second.x(); }
QVector2D unit(const QVector2D& vector) {
    const double magnitude = std::hypot(vector.x(), vector.y());
    return magnitude > 0 ? point(vector.x() / magnitude, vector.y() / magnitude) : QVector2D(1, 0);
}
bool inSweep(double value, double start, double end, double slack = 1e-9) { return modulo(value - start + slack) <= end - start + 2 * slack; }
Primitive line(const QVector2D& first, const QVector2D& second) {
    Primitive result;
    result.type = "line";
    result.points = {first, second};
    return result;
}
Primitive roundPrimitive(const QString& type, const QVector2D& centre, double radius, double start = 0, double end = Tau) {
    Primitive result;
    result.type = type;
    result.centre = centre;
    result.radius = radius;
    result.start = start;
    result.end = end;
    return result;
}
QVector<Primitive> splines(const QVector<QVector2D>& values, bool closed) {
    QVector<Primitive> result;
    const int count = int(values.size());
    if (count == 2) closed = false;
    auto at = [&](int index) { return values[closed ? (index + count) % count : std::clamp(index, 0, count - 1)]; };
    for (int index = 0; index < (closed ? count : count - 1); ++index) {
        const auto before = at(index - 1), start = at(index), end = at(index + 1), after = at(index + 2);
        Primitive primitive;
        primitive.type = "bezier";
        primitive.points = {start, start + (end - before) / 6, end - (after - start) / 6, end};
        result.append(primitive);
    }
    return result;
}
Loop oriented(const QVector<Primitive>& parts) {
    Loop result;
    if (parts.isEmpty()) return result;
    if (parts.size() == 1) return {{parts[0], false}};
    const auto first = prim_ends(parts[0]).value(), second = prim_ends(parts[1]).value();
    const bool reverse = std::min(distance(first.first, second.first), distance(first.first, second.second))
        < std::min(distance(first.second, second.first), distance(first.second, second.second));
    auto tail = reverse ? first.first : first.second;
    result.append({parts[0], reverse});
    for (qsizetype index = 1; index < parts.size(); ++index) {
        const auto tips = prim_ends(parts[index]).value();
        const bool backwards = distance(tips.second, tail) < distance(tips.first, tail);
        result.append({parts[index], backwards});
        tail = backwards ? tips.first : tips.second;
    }
    return result;
}
QVector2D nearestSegment(const QVector2D& value, const QVector2D& first, const QVector2D& second) {
    const auto delta = second - first;
    const double squared = dot(delta, delta);
    const double fraction = squared > 0 ? std::clamp(dot(value - first, delta) / squared, 0.0, 1.0) : 0;
    return first + delta * float(fraction);
}
class Expression {
public:
    Expression(QString text, const QMap<QString, double>& variables) : text_(std::move(text)), variables_(variables) {}
    double run() {
        if (text_.size() > 8192) fail();
        const double result = sum();
        whitespace();
        if (position_ != text_.size() || !std::isfinite(result)) fail();
        return result;
    }
private:
    QString text_;
    const QMap<QString, double>& variables_;
    qsizetype position_ = 0;
    int depth_ = 0;
    [[noreturn]] void fail() const { throw DomainError(QStringLiteral("方程式无法计算: %1").arg(text_)); }
    void whitespace() { while (position_ < text_.size() && text_[position_].isSpace()) ++position_; }
    bool take(QChar token) {
        whitespace();
        if (position_ < text_.size() && text_[position_] == token) { ++position_; return true; }
        return false;
    }
    double sum() {
        double result = product();
        while (true) {
            if (take('+')) result += product();
            else if (take('-')) result -= product();
            else return result;
        }
    }
    double product() {
        double result = unary();
        while (true) {
            whitespace();
            if (text_.mid(position_, 2) == "**") return result;
            if (take('*')) result *= unary();
            else if (take('/')) { const auto divisor = unary(); if (divisor == 0) fail(); result /= divisor; }
            else if (take('%')) { const auto divisor = unary(); if (divisor == 0) fail(); result = modulo(result, divisor); }
            else return result;
        }
    }
    double unary() {
        if (++depth_ > 128) fail();
        double result;
        if (take('+')) result = unary();
        else if (take('-')) result = -unary();
        else {
            result = atom();
            whitespace();
            if (text_.mid(position_, 2) == "**") { position_ += 2; result = std::pow(result, unary()); }
            else if (take('^')) result = std::pow(result, unary());
        }
        --depth_;
        return result;
    }
    double atom() {
        if (take('(')) { const double result = sum(); if (!take(')')) fail(); return result; }
        whitespace();
        const auto start = position_;
        if (position_ < text_.size() && (text_[position_].isDigit() || text_[position_] == '.')) {
            while (position_ < text_.size() && (text_[position_].isDigit() || text_[position_] == '.')) ++position_;
            if (position_ < text_.size() && (text_[position_] == 'e' || text_[position_] == 'E')) {
                ++position_;
                if (position_ < text_.size() && (text_[position_] == '+' || text_[position_] == '-')) ++position_;
                while (position_ < text_.size() && text_[position_].isDigit()) ++position_;
            }
            bool valid = false;
            const double result = text_.mid(start, position_ - start).toDouble(&valid);
            if (!valid) fail();
            return result;
        }
        while (position_ < text_.size() && (text_[position_].isLetterOrNumber() || text_[position_] == '_')) ++position_;
        const auto name = text_.mid(start, position_ - start);
        if (name.isEmpty()) fail();
        if (!take('(')) {
            if (variables_.contains(name)) return variables_[name];
            if (name == "pi") return Pi;
            if (name == "e") return std::numbers::e;
            fail();
        }
        QVector<double> arguments;
        if (!take(')')) {
            do { arguments.append(sum()); } while (take(','));
            if (!take(')')) fail();
        }
        if ((name == "min" || name == "max") && !arguments.isEmpty())
            return name == "min" ? *std::min_element(arguments.begin(), arguments.end()) : *std::max_element(arguments.begin(), arguments.end());
        if (arguments.size() == 2) {
            if (name == "atan2") return std::atan2(arguments[0], arguments[1]);
            if (name == "pow") return std::pow(arguments[0], arguments[1]);
            if (name == "log") return std::log(arguments[0]) / std::log(arguments[1]);
        }
        if (arguments.size() != 1) fail();
        const double value = arguments[0];
        if (name == "sin") return std::sin(value);
        if (name == "cos") return std::cos(value);
        if (name == "tan") return std::tan(value);
        if (name == "asin") return std::asin(value);
        if (name == "acos") return std::acos(value);
        if (name == "atan") return std::atan(value);
        if (name == "sinh") return std::sinh(value);
        if (name == "cosh") return std::cosh(value);
        if (name == "tanh") return std::tanh(value);
        if (name == "sqrt") return std::sqrt(value);
        if (name == "exp") return std::exp(value);
        if (name == "log") return std::log(value);
        if (name == "log10") return std::log10(value);
        if (name == "floor") return std::floor(value);
        if (name == "ceil") return std::ceil(value);
        if (name == "abs") return std::abs(value);
        if (name == "radians") return radians(value);
        if (name == "degrees") return degrees(value);
        fail();
    }
};
QJsonObject mapped(QJsonObject shape, const std::function<QVector2D(QVector2D)>& transform,
                   const std::function<double(double)>& turn = {}, bool flips = false) {
    auto kind = shape.value("type").toString();
    if (kind == "equation") {
        QJsonObject replacement{{"type", "spline"}, {"points", json(equation_points(shape))}, {"closed", false}};
        if (shape.value("construction").toBool()) replacement["construction"] = true;
        shape = replacement;
        kind = "spline";
    }
    auto result = shape;
    if (shape.contains("points")) {
        auto values = points(shape, 0);
        for (auto& value : values) value = transform(value);
        result["points"] = json(values);
    }
    auto apply = [&](const QString& xKey, const QString& yKey) {
        const auto value = transform(point(number(shape, xKey, 0), number(shape, yKey, 0)));
        result[xKey] = double(value.x()); result[yKey] = double(value.y());
    };
    if (kind == "line" || kind == "slot") { apply("x1", "y1"); apply("x2", "y2"); }
    if (kind == "point" || kind == "text") {
        apply("x", "y");
        if (shape.value("path").isObject()) result["path"] = mapped(shape.value("path").toObject(), transform, turn, flips);
    }
    if (QStringList{"rect", "circle", "ngon", "ellipse", "arc", "arcslot"}.contains(kind)) apply("cx", "cy");
    if (turn) {
        if (kind == "ngon" || kind == "ellipse" || (kind == "text" && !flips && !shape.contains("path"))) result["angle"] = turn(number(shape, "angle", 0));
        if (kind == "arc" || kind == "arcslot") {
            const double first = turn(number(shape, "a0")), second = turn(number(shape, "a1"));
            result["a0"] = flips ? second : first; result["a1"] = flips ? first : second;
        }
    }
    return result;
}
QJsonValue roundedJson(const QJsonValue& value) {
    if (value.isDouble()) return std::nearbyint(value.toDouble() * 1e6) / 1e6;
    if (value.isArray()) { QJsonArray result; for (const auto& item : value.toArray()) result.append(roundedJson(item)); return result; }
    if (value.isObject()) { auto result = value.toObject(); for (auto iterator = result.begin(); iterator != result.end(); ++iterator) iterator.value() = roundedJson(iterator.value()); return result; }
    return value;
}
struct Tip { int shape; int which; QVector2D point; };
QVector<Tip> openTips(const QJsonArray& shapes) {
    QVector<Tip> result;
    for (int index = 0; index < shapes.size(); ++index) {
        const auto shape = shapes[index].toObject();
        if (shape.value("construction").toBool()) continue;
        if (const auto tips = ends(shape)) { result.append({index, 0, tips->first}); result.append({index, 1, tips->second}); }
    }
    return result;
}
std::pair<QVector<int>, QVector<QVector2D>> nodes(const QVector<QVector2D>& values) {
    QVector<int> numbers;
    QVector<QVector2D> spots;
    for (const auto& value : values) {
        int found = -1;
        for (int index = 0; index < spots.size(); ++index) if (distance(spots[index], value) <= Join) { found = index; break; }
        if (found < 0) { found = int(spots.size()); spots.append(value); }
        numbers.append(found);
    }
    return {numbers, spots};
}
bool setTip(QJsonArray& shapes, const Tip& tip, const QVector2D& value) {
    auto shape = shapes[tip.shape].toObject();
    const auto type = shape.value("type").toString();
    if (type == "line") {
        shape[tip.which ? "x2" : "x1"] = double(value.x());
        shape[tip.which ? "y2" : "y1"] = double(value.y());
    } else if (type == "spline") {
        auto values = shape.value("points").toArray();
        values[tip.which ? values.size() - 1 : 0] = json(value);
        shape["points"] = values;
    } else return false;
    shapes[tip.shape] = shape;
    return true;
}
QJsonObject piece(const Primitive& primitive, double start, double end) {
    if (primitive.type == "line") {
        const auto direction = unit(primitive.points[1] - primitive.points[0]);
        const auto first = primitive.points[0] + direction * float(start), second = primitive.points[0] + direction * float(end);
        return {{"type", "line"}, {"x1", double(first.x())}, {"y1", double(first.y())}, {"x2", double(second.x())}, {"y2", double(second.y())}};
    }
    const double base = primitive.type == "arc" ? primitive.start : 0;
    return {{"type", "arc"}, {"cx", double(primitive.centre.x())}, {"cy", double(primitive.centre.y())}, {"r", primitive.radius},
            {"a0", degrees(base + start / primitive.radius)}, {"a1", degrees(base + end / primitive.radius)}};
}
double along(const Primitive& primitive, const QVector2D& value) {
    if (primitive.type == "line") return distance(primitive.points[0], nearestSegment(value, primitive.points[0], primitive.points[1]));
    return modulo(angle(primitive.centre, value) - (primitive.type == "arc" ? primitive.start : 0)) * primitive.radius;
}
}

DomainError::DomainError(const QString& message) : std::runtime_error(message.toUtf8().constData()) {}
double distance(const QVector2D& first, const QVector2D& second) { return std::hypot(double(first.x()) - second.x(), double(first.y()) - second.y()); }
double number(const QJsonObject& object, const QString& key, std::optional<double> fallback, bool positive) {
    const auto value = object.value(key);
    double result;
    if (value.isUndefined() && fallback) result = *fallback;
    else if (value.isDouble()) result = value.toDouble();
    else if (value.isBool()) result = value.toBool() ? 1 : 0;
    else if (value.isString()) { bool valid = false; result = value.toString().toDouble(&valid); if (!valid) throw DomainError(QStringLiteral("参数 %1 不是数字").arg(key)); }
    else throw DomainError(QStringLiteral("缺少数字参数 %1").arg(key));
    if (!std::isfinite(result) || (positive && result <= 0)) throw DomainError(QStringLiteral("参数 %1 超出有效范围").arg(key));
    return result;
}
bool is_closed(const QJsonObject& shape) {
    const auto type = shape.value("type").toString();
    return QStringList{"rect", "circle", "polygon", "ngon", "slot", "arcslot", "ellipse"}.contains(type)
        || (type == "spline" && shape.value("closed").toBool());
}
QVector<QVector2D> vertices(const QJsonObject& shape) {
    const auto type = shape.value("type").toString();
    const double cx = number(shape, "cx", 0), cy = number(shape, "cy", 0);
    if (type == "rect") {
        const double halfWidth = number(shape, "w", {}, true) / 2, halfHeight = number(shape, "h", {}, true) / 2;
        return {point(cx - halfWidth, cy - halfHeight), point(cx + halfWidth, cy - halfHeight), point(cx + halfWidth, cy + halfHeight), point(cx - halfWidth, cy + halfHeight)};
    }
    if (type == "ngon") {
        const double rawSides = number(shape, "sides", 6);
        if (rawSides < 3 || rawSides >= 101) throw DomainError(QStringLiteral("正多边形边数必须在 3 到 100 之间"));
        const int sides = int(rawSides);
        const double radius = number(shape, "r", {}, true), start = radians(number(shape, "angle", 0));
        QVector<QVector2D> result;
        for (int index = 0; index < sides; ++index) result.append(polar(point(cx, cy), radius, start + Tau * index / sides));
        return result;
    }
    return points(shape, 3);
}
QVector<Primitive> prims(const QJsonObject& shape) {
    const auto type = shape.value("type").toString();
    auto centre = [&]() { return point(number(shape, "cx", 0), number(shape, "cy", 0)); };
    if (type == "line") return {line(point(number(shape, "x1"), number(shape, "y1")), point(number(shape, "x2"), number(shape, "y2")))};
    if (type == "rect" || type == "polygon" || type == "ngon") {
        const auto ring = vertices(shape);
        QVector<Primitive> result;
        for (int index = 0; index < ring.size(); ++index) result.append(line(ring[index], ring[(index + 1) % ring.size()]));
        return result;
    }
    if (type == "circle") return {roundPrimitive(type, centre(), number(shape, "r", {}, true))};
    if (type == "arc" || type == "arcslot") {
        const auto origin = centre();
        const double radius = number(shape, "r", {}, true), start = radians(number(shape, "a0"));
        double sweep = modulo(radians(number(shape, "a1")) - start);
        if (sweep == 0) sweep = Tau;
        const double end = start + sweep;
        if (type == "arc") return {roundPrimitive(type, origin, radius, start, end)};
        const double half = number(shape, "w", {}, true) / 2;
        if (half >= radius) throw DomainError(QStringLiteral("圆弧槽口的槽宽必须小于圆弧直径"));
        return {roundPrimitive("arc", origin, radius + half, start, end), roundPrimitive("arc", polar(origin, radius, end), half, end, end + Pi),
                roundPrimitive("arc", origin, radius - half, start, end), roundPrimitive("arc", polar(origin, radius, start), half, start + Pi, start + Tau)};
    }
    if (type == "ellipse") {
        auto result = roundPrimitive(type, centre(), number(shape, "rx", {}, true));
        result.secondaryRadius = number(shape, "ry", {}, true); result.angle = radians(number(shape, "angle", 0));
        return {result};
    }
    if (type == "slot") {
        const auto first = point(number(shape, "x1"), number(shape, "y1")), second = point(number(shape, "x2"), number(shape, "y2"));
        const double half = number(shape, "w", {}, true) / 2;
        if (distance(first, second) < Join) throw DomainError(QStringLiteral("直槽口的两个圆心不能重合"));
        const auto direction = unit(second - first), normal = point(-direction.y() * half, direction.x() * half);
        const double turn = std::atan2(-normal.y(), -normal.x());
        return {line(first - normal, second - normal), roundPrimitive("arc", second, half, turn, turn + Pi), line(second + normal, first + normal), roundPrimitive("arc", first, half, turn + Pi, turn + Tau)};
    }
    if (type == "spline") {
        const auto values = points(shape, 2);
        if (shape.value("style").toBool()) {
            if (values.size() > 12) throw DomainError(QStringLiteral("样式样条最多 12 个控制点"));
            Primitive result; result.type = "bezier"; result.points = values; return {result};
        }
        return splines(values, shape.value("closed").toBool());
    }
    if (type == "equation") return splines(equation_points(shape), false);
    if (type == "point") { Primitive result; result.type = type; result.points = {point(number(shape, "x"), number(shape, "y"))}; return {result}; }
    if (type == "text") { number(shape, "height", 10, true); return {}; }
    throw DomainError(QStringLiteral("不认识的轮廓类型: %1").arg(type));
}
QVector<QVector2D> sample(const Primitive& primitive, int fine) {
    if (fine < 1 || fine > 1000000) throw DomainError(QStringLiteral("采样精度超出范围"));
    const auto& type = primitive.type;
    if (type == "line") return primitive.points;
    QVector<QVector2D> result;
    if (type == "circle" || type == "arc") {
        const double start = type == "arc" ? primitive.start : 0, end = type == "arc" ? primitive.end : Tau;
        const int count = std::max(2, int(std::ceil(fine * (end - start) / Tau)));
        for (int index = 0; index <= count; ++index) result.append(polar(primitive.centre, primitive.radius, start + (end - start) * index / count));
    } else if (type == "ellipse") {
        const double cosine = std::cos(primitive.angle), sine = std::sin(primitive.angle);
        for (int index = 0; index <= fine; ++index) {
            const double x = primitive.radius * std::cos(Tau * index / fine), y = primitive.secondaryRadius * std::sin(Tau * index / fine);
            result.append(point(primitive.centre.x() + x * cosine - y * sine, primitive.centre.y() + x * sine + y * cosine));
        }
    } else if (type == "bezier") {
        if (primitive.points.size() < 2) throw DomainError(QStringLiteral("贝塞尔曲线缺少控制点"));
        const int count = std::max(6, fine / 5) * std::max(1, int((primitive.points.size() - 1) / 3));
        for (int index = 0; index <= count; ++index) {
            auto level = primitive.points;
            const float fraction = float(double(index) / count);
            while (level.size() > 1) {
                for (int offset = 0; offset + 1 < level.size(); ++offset) level[offset] += (level[offset + 1] - level[offset]) * fraction;
                level.removeLast();
            }
            result.append(level[0]);
        }
    }
    return result;
}
QVector<QVector<QVector2D>> polylines(const QJsonObject& shape, int fine) {
    QVector<QVector<QVector2D>> result;
    for (const auto& primitive : prims(shape)) { auto values = sample(primitive, fine); if (values.size() >= 2) result.append(values); }
    return result;
}
double length(const QJsonObject& shape) {
    double result = 0;
    for (const auto& values : polylines(shape)) for (int index = 1; index < values.size(); ++index) result += distance(values[index - 1], values[index]);
    return result;
}
std::optional<std::pair<QVector2D, QVector2D>> prim_ends(const Primitive& primitive) {
    if (primitive.type == "line" || primitive.type == "bezier") return std::pair{primitive.points.first(), primitive.points.last()};
    if (primitive.type == "arc") return std::pair{polar(primitive.centre, primitive.radius, primitive.start), polar(primitive.centre, primitive.radius, primitive.end)};
    return {};
}
std::optional<std::pair<QVector2D, QVector2D>> ends(const QJsonObject& shape) {
    const auto type = shape.value("type").toString();
    if (type == "line" || type == "arc") return prim_ends(prims(shape).first());
    if (type == "spline" && (!shape.value("closed").toBool() || shape.value("style").toBool())) { const auto values = points(shape, 2); return std::pair{values.first(), values.last()}; }
    if (type == "equation") { const auto values = equation_points(shape); return std::pair{values.first(), values.last()}; }
    return {};
}
QVector2D anchor(const QJsonObject& shape) {
    const auto type = shape.value("type").toString();
    if (shape.contains("cx") || QStringList{"rect", "circle", "ngon", "ellipse", "arc"}.contains(type)) return point(number(shape, "cx", 0), number(shape, "cy", 0));
    if (type == "line" || type == "slot") return point(number(shape, "x1"), number(shape, "y1"));
    if (type == "point" || type == "text") return point(number(shape, "x"), number(shape, "y"));
    if (type == "equation") return equation_points(shape).first();
    return points(shape, 1).first();
}
QJsonArray key_points(const QJsonObject& shape) {
    QJsonArray result;
    auto append = [&](const QString& kind, const QVector2D& value) { result.append(QJsonArray{kind, json(value)}); };
    const auto type = shape.value("type").toString();
    if (type == "point" || type == "text") { append("end", anchor(shape)); return result; }
    if (type == "spline") {
        const auto values = points(shape, 2);
        if (shape.value("style").toBool()) { append("end", values.first()); append("end", values.last()); }
        else for (const auto& value : values) append("end", value);
        return result;
    }
    if (type == "equation") { const auto tips = ends(shape).value(); append("end", tips.first); append("end", tips.second); return result; }
    for (const auto& primitive : prims(shape)) {
        if (primitive.type == "line") {
            append("end", primitive.points[0]); append("mid", (primitive.points[0] + primitive.points[1]) / 2);
            if (type == "line" || type == "slot") append("end", primitive.points[1]);
        } else if (primitive.type == "arc") {
            append("center", primitive.centre);
            if (type == "arc") { const auto tips = prim_ends(primitive).value(); append("end", tips.first); append("end", tips.second); append("mid", polar(primitive.centre, primitive.radius, (primitive.start + primitive.end) / 2)); }
        } else if (primitive.type == "circle" || primitive.type == "ellipse") {
            append("center", primitive.centre);
            const auto ring = sample(primitive, 4);
            for (int index = 0; index < 4; ++index) append("quad", ring[index]);
        }
    }
    if (type == "rect" || type == "ngon") append("center", point(number(shape, "cx", 0), number(shape, "cy", 0)));
    return result;
}
double signed_area(const QVector<QVector2D>& ring) {
    double result = 0;
    for (int index = 0; index < ring.size(); ++index) result += cross(ring[index], ring[(index + 1) % ring.size()]);
    return result / 2;
}
bool contains(const QVector<QVector2D>& ring, const QVector2D& value) {
    bool result = false;
    for (int index = 0; index < ring.size(); ++index) {
        const auto& first = ring[index]; const auto& second = ring[(index + 1) % ring.size()];
        if ((first.y() > value.y()) != (second.y() > value.y())
            && value.x() < first.x() + (double(value.y()) - first.y()) * (double(second.x()) - first.x()) / (double(second.y()) - first.y())) result = !result;
    }
    return result;
}
double evaluate(const QString& expression, const QMap<QString, double>& variables) { return Expression(expression, variables).run(); }
QVector<QVector2D> equation_points(const QJsonObject& shape) {
    const double start = number(shape, "t0", 0), end = number(shape, "t1", 1), ox = number(shape, "ox", 0), oy = number(shape, "oy", 0);
    if (std::abs(end - start) < 1e-12) throw DomainError(QStringLiteral("方程式曲线起止范围不能相同"));
    const bool parametric = shape.value("mode").toString() == "parametric";
    QVector<QVector2D> result;
    for (int index = 0; index <= 60; ++index) {
        const double value = start + (end - start) * index / 60;
        const double x = parametric ? evaluate(shape.value("fx").toString("t"), {{"t", value}}) : value;
        const double y = evaluate(shape.value("fy").toString("0"), {{parametric ? "t" : "x", value}});
        result.append(point(x + ox, y + oy));
    }
    return result;
}
QVector2D nearest_on_prim(const Primitive& primitive, const QVector2D& value) {
    if (primitive.type == "point") return primitive.points.first();
    if (primitive.type == "line") return nearestSegment(value, primitive.points[0], primitive.points[1]);
    if (primitive.type == "circle" || primitive.type == "arc") {
        const double direction = distance(primitive.centre, value) > 1e-12 ? angle(primitive.centre, value) : 0;
        if (primitive.type == "circle" || inSweep(direction, primitive.start, primitive.end)) return polar(primitive.centre, primitive.radius, direction);
        const auto tips = prim_ends(primitive).value();
        return distance(tips.first, value) <= distance(tips.second, value) ? tips.first : tips.second;
    }
    const auto values = sample(primitive, 96);
    if (values.size() < 2) throw DomainError(QStringLiteral("曲线没有可测量的线段"));
    QVector2D result;
    double best = std::numeric_limits<double>::infinity();
    for (int index = 1; index < values.size(); ++index) { const auto found = nearestSegment(value, values[index - 1], values[index]); const double gap = distance(value, found); if (gap < best) { best = gap; result = found; } }
    return result;
}
std::pair<double, QVector2D> nearest(const QJsonObject& shape, const QVector2D& value) {
    if (shape.value("type") == "text") { const auto found = anchor(shape); return {distance(found, value), found}; }
    std::pair<double, QVector2D> result{std::numeric_limits<double>::infinity(), {}};
    for (const auto& primitive : prims(shape)) { const auto found = nearest_on_prim(primitive, value); const double gap = distance(found, value); if (gap < result.first) result = {gap, found}; }
    if (!std::isfinite(result.first)) throw DomainError(QStringLiteral("图形没有可测量的曲线"));
    return result;
}
bool hit(const QJsonObject& shape, const QVector2D& value, double tolerance) { return nearest(shape, value).first <= tolerance; }
QJsonArray explode(const QJsonObject& shape) {
    if (!QStringList{"rect", "polygon", "ngon", "slot", "arcslot"}.contains(shape.value("type").toString())) return {shape};
    QJsonArray result;
    for (const auto& primitive : prims(shape)) {
        auto value = piece(primitive, 0, primitive.type == "line" ? distance(primitive.points[0], primitive.points[1]) : primitive.radius * (primitive.end - primitive.start));
        if (shape.value("construction").toBool()) value["construction"] = true;
        result.append(value);
    }
    return result;
}
QJsonObject moved(const QJsonObject& shape, double dx, double dy) {
    if (!std::isfinite(dx) || !std::isfinite(dy)) throw DomainError(QStringLiteral("移动距离必须是有限数字"));
    if (shape.value("type") == "equation") { auto result = shape; result["ox"] = number(shape, "ox", 0) + dx; result["oy"] = number(shape, "oy", 0) + dy; return result; }
    return mapped(shape, [=](QVector2D value) { return value + point(dx, dy); });
}
QJsonObject rotated(const QJsonObject& source, const QVector2D& centre, double rotation) {
    if (!std::isfinite(rotation)) throw DomainError(QStringLiteral("旋转角必须是有限数字"));
    auto shape = source;
    const double cosine = std::cos(radians(rotation)), sine = std::sin(radians(rotation));
    if (shape.value("type") == "rect" && std::abs(sine) > 1e-12) {
        shape = {{"type", "polygon"}, {"points", json(vertices(source))}};
        if (source.value("construction").toBool()) shape["construction"] = true;
    }
    return mapped(shape, [=](QVector2D value) { const auto delta = value - centre; return centre + point(delta.x() * cosine - delta.y() * sine, delta.x() * sine + delta.y() * cosine); }, [=](double value) { return value + rotation; });
}
QJsonObject mirrored(const QJsonObject& source, const QVector2D& first, const QVector2D& second) {
    const auto direction = unit(second - first);
    const double axis = degrees(std::atan2(direction.y(), direction.x()));
    auto shape = source;
    if (shape.value("type") == "rect" && std::abs(direction.x() * direction.y()) > 1e-12) {
        shape = {{"type", "polygon"}, {"points", json(vertices(source))}};
        if (source.value("construction").toBool()) shape["construction"] = true;
    }
    return mapped(shape, [=](QVector2D value) { const auto delta = value - first; return first + direction * float(2 * dot(delta, direction)) - delta; }, [=](double value) { return 2 * axis - value; }, true);
}
std::optional<std::pair<QVector2D, double>> circle3(const QVector2D& first, const QVector2D& second, const QVector2D& third) {
    const double ax = first.x(), ay = first.y(), bx = second.x(), by = second.y(), cx = third.x(), cy = third.y();
    const double determinant = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by));
    if (std::abs(determinant) < 1e-12) return {};
    const auto centre = point(((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / determinant,
                              ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / determinant);
    return std::pair{centre, distance(centre, first)};
}
std::optional<QJsonObject> arc3(const QVector2D& start, const QVector2D& end, const QVector2D& through) {
    const auto found = circle3(start, end, through);
    if (!found) return {};
    double first = angle(found->first, start), second = angle(found->first, end);
    const double middle = angle(found->first, through);
    if (modulo(middle - first) > modulo(second - first)) std::swap(first, second);
    return QJsonObject{{"type", "arc"}, {"cx", double(found->first.x())}, {"cy", double(found->first.y())}, {"r", found->second}, {"a0", degrees(first)}, {"a1", degrees(second)}};
}
QVector<QVector2D> intersections(const Primitive& first, const Primitive& second) {
    auto simple = [](const Primitive& primitive) {
        if (QStringList{"line", "circle", "arc"}.contains(primitive.type)) return QVector<Primitive>{primitive};
        QVector<Primitive> result; const auto values = sample(primitive, 96);
        for (int index = 1; index < values.size(); ++index) result.append(line(values[index - 1], values[index]));
        return result;
    };
    auto onRound = [](const Primitive& primitive, const QVector2D& value) { return primitive.type == "circle" || inSweep(angle(primitive.centre, value), primitive.start, primitive.end, 1e-7); };
    QVector<QVector2D> result;
    for (const auto& firstPart : simple(first)) for (const auto& secondPart : simple(second)) {
        auto firstCurve = firstPart, secondCurve = secondPart;
        if (firstCurve.type == "line" && secondCurve.type == "line") {
            const auto firstDelta = firstCurve.points[1] - firstCurve.points[0], secondDelta = secondCurve.points[1] - secondCurve.points[0], delta = secondCurve.points[0] - firstCurve.points[0];
            const double determinant = cross(firstDelta, secondDelta);
            if (std::abs(determinant) < 1e-12 * std::max(1.0, std::abs(double(firstDelta.x())) + std::abs(double(firstDelta.y()))) * std::max(1.0, std::abs(double(secondDelta.x())) + std::abs(double(secondDelta.y())))) continue;
            const double fraction = cross(delta, secondDelta) / determinant, otherFraction = cross(delta, firstDelta) / determinant;
            if (fraction >= -1e-9 && fraction <= 1 + 1e-9 && otherFraction >= -1e-9 && otherFraction <= 1 + 1e-9) result.append(firstCurve.points[0] + firstDelta * float(fraction));
        } else if (firstCurve.type == "line" || secondCurve.type == "line") {
            if (secondCurve.type == "line") std::swap(firstCurve, secondCurve);
            const auto delta = firstCurve.points[1] - firstCurve.points[0], relative = firstCurve.points[0] - secondCurve.centre;
            const double quadratic = dot(delta, delta), linear = 2 * dot(relative, delta), constant = dot(relative, relative) - secondCurve.radius * secondCurve.radius;
            if (quadratic == 0) continue;
            const double discriminant = linear * linear - 4 * quadratic * constant;
            if (discriminant < -1e-9 * quadratic * secondCurve.radius * secondCurve.radius) continue;
            const double root = std::sqrt(std::max(discriminant, 0.0));
            for (const double fraction : QVector<double>{(-linear - root) / (2 * quadratic), (-linear + root) / (2 * quadratic)}) {
                const auto value = firstCurve.points[0] + delta * float(fraction);
                if (fraction >= -1e-9 && fraction <= 1 + 1e-9 && onRound(secondCurve, value) && (result.isEmpty() || distance(result.last(), value) > 1e-9)) result.append(value);
            }
        } else {
            const double gap = distance(firstCurve.centre, secondCurve.centre), firstRadius = firstCurve.radius, secondRadius = secondCurve.radius;
            if (gap < 1e-12 || gap > firstRadius + secondRadius + 1e-9 || gap < std::abs(firstRadius - secondRadius) - 1e-9) continue;
            const double reach = (firstRadius * firstRadius - secondRadius * secondRadius + gap * gap) / (2 * gap), height = std::sqrt(std::max(firstRadius * firstRadius - reach * reach, 0.0));
            const auto direction = unit(secondCurve.centre - firstCurve.centre), base = firstCurve.centre + direction * float(reach), normal = point(-direction.y() * height, direction.x() * height);
            QVector<QVector2D> values{base + normal}; if (height >= 1e-9) values.append(base - normal);
            for (const auto& value : values) if (onRound(firstCurve, value) && onRound(secondCurve, value)) result.append(value);
        }
    }
    return result;
}
LoopResult loops(const QJsonArray& shapes) {
    LoopResult result;
    QVector<Primitive> loose;
    for (const auto& value : shapes) {
        const auto shape = value.toObject();
        if (shape.value("construction").toBool() || shape.value("type") == "point" || shape.value("type") == "text") continue;
        const auto parts = prims(shape);
        if (is_closed(shape)) result.loops.append(oriented(parts));
        else for (const auto& primitive : parts) { const auto tips = prim_ends(primitive).value(); if (primitive.type != "line" || distance(tips.first, tips.second) > Join) loose.append(primitive); }
    }
    QVector<QVector2D> tips;
    for (const auto& primitive : loose) { const auto both = prim_ends(primitive).value(); tips.append(both.first); tips.append(both.second); }
    const auto clustered = nodes(tips);
    const auto& numbers = clustered.first;
    QMap<int, QVector<std::pair<int, int>>> adjacency;
    for (int index = 0; index < loose.size(); ++index) for (int which = 0; which < 2; ++which) adjacency[numbers[2 * index + which]].append({index, which});
    QSet<int> used;
    for (int start = 0; start < loose.size(); ++start) {
        if (used.contains(start)) continue;
        Loop chain;
        int index = start, which = 0;
        bool good = true;
        while (true) {
            used.insert(index); chain.append({loose[index], which == 1});
            const auto at = adjacency[numbers[2 * index + 1 - which]];
            if (at.size() != 2) { good = false; break; }
            const auto next = at[0] == std::pair{index, 1 - which} ? at[1] : at[0];
            index = next.first; which = next.second;
            if (index == start) break;
            if (used.contains(index)) { good = false; break; }
        }
        if (good && adjacency[numbers[2 * start]].size() == 2) result.loops.append(chain);
        else ++result.leftover;
    }
    return result;
}
QVector<QVector2D> loop_ring(const Loop& loop, int fine) {
    QVector<QVector2D> result;
    for (const auto& part : loop) { auto values = sample(part.primitive, fine); if (part.backwards) std::reverse(values.begin(), values.end()); if (!values.isEmpty()) values.removeLast(); result += values; }
    return result;
}
QVector<int> chain_of(const QJsonArray& shapes, int index) {
    if (index < 0 || index >= shapes.size()) throw DomainError(QStringLiteral("图形序号越界"));
    QMap<int, std::pair<QVector2D, QVector2D>> tips;
    for (int number = 0; number < shapes.size(); ++number) if (const auto both = ends(shapes[number].toObject())) tips[number] = *both;
    QSet<int> found{index}; QVector<int> pending{index};
    while (!pending.isEmpty()) {
        const int current = pending.takeLast();
        if (!tips.contains(current)) continue;
        const auto currentTips = tips[current];
        for (auto iterator = tips.cbegin(); iterator != tips.cend(); ++iterator) {
            if (found.contains(iterator.key())) continue;
            const auto candidate = iterator.value();
            if (std::min({distance(currentTips.first, candidate.first), distance(currentTips.first, candidate.second), distance(currentTips.second, candidate.first), distance(currentTips.second, candidate.second)}) <= Join) { found.insert(iterator.key()); pending.append(iterator.key()); }
        }
    }
    QVector<int> result(found.begin(), found.end()); std::sort(result.begin(), result.end()); return result;
}
QJsonArray diagnose(const QJsonArray& shapes) {
    QJsonArray issues, sound;
    auto append = [&](const QString& kind, const QString& text, const QVector2D& value, bool fixable) { issues.append(QJsonObject{{"kind", kind}, {"text", text}, {"point", json(value)}, {"fixable", fixable}}); };
    for (int index = 0; index < shapes.size(); ++index) {
        const auto shape = shapes[index].toObject(); const auto type = shape.value("type").toString();
        if (type == "point" || type == "text" || shape.value("construction").toBool()) continue;
        if (length(shape) < Tiny) { append("tiny", QStringLiteral("%1 长度接近 0").arg(type), anchor(shape), true); continue; }
        bool duplicate = false;
        for (int before = 0; before < index; ++before) if (roundedJson(shape) == roundedJson(shapes[before])) { duplicate = true; break; }
        if (duplicate) append("duplicate", QStringLiteral("%1 和另一个完全重合").arg(type), anchor(shape), true);
        else sound.append(shape);
    }
    const auto tips = openTips(sound); QVector<QVector2D> values; for (const auto& tip : tips) values.append(tip.point);
    const auto clustered = nodes(values); QMap<int, int> counts; for (const int number : clustered.first) ++counts[number];
    QSet<int> near;
    for (int first = 0; first < clustered.second.size(); ++first) for (int second = first + 1; second < clustered.second.size(); ++second) {
        const double gap = distance(clustered.second[first], clustered.second[second]);
        if (gap <= Gap) { near.insert(first); near.insert(second); append("gap", QStringLiteral("两个端点差 %1 mm 没接上").arg(gap, 0, 'g', 3), clustered.second[first], true); }
    }
    for (int number = 0; number < clustered.second.size(); ++number) {
        if (counts[number] >= 3) append("branch", QStringLiteral("%1 条线交在同一点（围不成单一轮廓）").arg(counts[number]), clustered.second[number], false);
        else if (counts[number] == 1 && !near.contains(number)) append("open", QStringLiteral("线头没有接上别的线（开口轮廓不能拉伸）"), clustered.second[number], false);
    }
    return issues;
}
RepairResult repair(const QJsonArray& shapes) {
    RepairResult result;
    for (const auto& value : shapes) {
        const auto shape = value.toObject(); const auto type = shape.value("type").toString();
        bool duplicate = false; for (const auto& kept : result.shapes) if (roundedJson(value) == roundedJson(kept)) { duplicate = true; break; }
        if (type != "point" && type != "text" && (length(shape) < Tiny || duplicate)) ++result.fixed;
        else result.shapes.append(value);
    }
    auto tips = openTips(result.shapes);
    for (int first = 0; first < tips.size(); ++first) for (int second = first + 1; second < tips.size(); ++second) {
        const double gap = distance(tips[first].point, tips[second].point);
        if (gap <= Join || gap > Gap) continue;
        if (setTip(result.shapes, tips[second], tips[first].point)) { tips[second].point = tips[first].point; ++result.fixed; }
        else if (setTip(result.shapes, tips[first], tips[second].point)) { tips[first].point = tips[second].point; ++result.fixed; }
    }
    return result;
}
double signed_distance(const QJsonObject& shape, const QVector2D& value) {
    const double gap = nearest(shape, value).first;
    if (is_closed(shape)) return contains(loop_ring(oriented(prims(shape)), 64), value) ? -gap : gap;
    if (shape.value("type") == "arc") return distance(point(number(shape, "cx", 0), number(shape, "cy", 0)), value) >= number(shape, "r") ? gap : -gap;
    QVector<QVector2D> values;
    for (const auto& part : polylines(shape, 96)) values += part;
    if (values.size() < 2) throw DomainError(QStringLiteral("图形没有可测量的线段"));
    double best = std::numeric_limits<double>::infinity(), side = 0;
    for (int index = 1; index < values.size(); ++index) {
        const double found = distance(nearestSegment(value, values[index - 1], values[index]), value);
        if (found < best) { best = found; side = cross(values[index] - values[index - 1], value - values[index - 1]); }
    }
    return side >= 0 ? gap : -gap;
}
QJsonObject offset(const QJsonObject& shape, double amount) {
    if (!std::isfinite(amount)) throw DomainError(QStringLiteral("等距距离必须是有限数字"));
    auto result = shape;
    const auto type = shape.value("type").toString();
    if (type == "circle" || type == "arc") {
        const double radius = number(shape, "r") + amount;
        if (radius <= Tiny) return {};
        result["r"] = radius;
    } else if (type == "rect") {
        const double width = number(shape, "w") + 2 * amount, height = number(shape, "h") + 2 * amount;
        if (width <= Tiny || height <= Tiny) return {};
        result["w"] = width; result["h"] = height;
    } else if (type == "slot" || type == "arcslot") {
        const double width = number(shape, "w") + 2 * amount;
        if (width <= Tiny || (type == "arcslot" && width >= 2 * number(shape, "r") - Tiny)) return {};
        result["w"] = width;
    } else if (type == "line") {
        const auto primitive = prims(shape).first(); const auto direction = unit(primitive.points[1] - primitive.points[0]);
        result = moved(shape, -direction.y() * amount, direction.x() * amount);
    } else if (type == "ngon") {
        const double radius = number(shape, "r") + amount / std::cos(Pi / int(number(shape, "sides", 6)));
        if (radius <= Tiny) return {};
        result["r"] = radius;
    } else if (type == "polygon") {
        const auto ring = vertices(shape); const double sign = signed_area(ring) >= 0 ? 1 : -1;
        QVector<QVector2D> shifted;
        for (int index = 0; index < ring.size(); ++index) {
            const auto previous = ring[(index + ring.size() - 1) % ring.size()], current = ring[index], next = ring[(index + 1) % ring.size()];
            const auto before = unit(current - previous), after = unit(next - current);
            const auto first = current + point(before.y() * sign * amount, -before.x() * sign * amount), second = current + point(after.y() * sign * amount, -after.x() * sign * amount);
            const double determinant = cross(before, after);
            shifted.append(std::abs(determinant) < 1e-12 ? first : first + before * float(cross(second - first, after) / determinant));
        }
        for (int index = 0; index < ring.size(); ++index)
            if (dot(ring[(index + 1) % ring.size()] - ring[index], shifted[(index + 1) % ring.size()] - shifted[index]) <= Tiny) return {};
        result = {{"type", "polygon"}, {"points", json(shifted)}};
        if (shape.value("construction").toBool()) result["construction"] = true;
    } else if (type == "ellipse" || type == "spline" || type == "equation") {
        const bool closed = is_closed(shape);
        QVector<QVector2D> values;
        if (closed) values = loop_ring(oriented(prims(shape)), 64);
        else for (const auto& part : polylines(shape, 96)) { for (int index = values.isEmpty() ? 0 : 1; index < part.size(); ++index) values.append(part[index]); }
        if (values.size() < 2) return {};
        const double turn = closed ? (signed_area(values) > 0 ? -1 : 1) : 1;
        const int count = int(values.size()), step = std::max(1, count / 32);
        QVector<QVector2D> shifted;
        for (int index = 0; index < count; index += step) {
            const auto before = values[closed ? (index + count - 1) % count : std::max(0, index - 1)], after = values[closed ? (index + 1) % count : std::min(count - 1, index + 1)];
            const auto direction = unit(after - before); shifted.append(values[index] + point(-direction.y() * amount * turn, direction.x() * amount * turn));
        }
        if (!closed && (count - 1) % step != 0) { const auto direction = unit(values.last() - values[count - 2]); shifted.append(values.last() + point(-direction.y() * amount, direction.x() * amount)); }
        if (closed && signed_area(shifted) * signed_area(values) <= 0) return {};
        result = {{"type", "spline"}, {"points", json(shifted)}, {"closed", closed}};
    } else return {};
    return result;
}
QJsonArray trim(const QJsonArray& source, int index, const QVector2D& value) {
    if (index < 0 || index >= source.size()) throw DomainError(QStringLiteral("图形序号越界"));
    QJsonArray shapes = source;
    const auto pieces = explode(shapes[index].toObject());
    if (pieces.size() > 1) {
        shapes.removeAt(index); int selected = 0; double best = std::numeric_limits<double>::infinity();
        for (int offset = 0; offset < pieces.size(); ++offset) { shapes.insert(index + offset, pieces[offset]); const double gap = nearest(pieces[offset].toObject(), value).first; if (gap < best) { best = gap; selected = offset; } }
        index += selected;
    }
    const auto target = shapes[index].toObject(); const auto type = target.value("type").toString();
    if (!QStringList{"line", "arc", "circle"}.contains(type)) throw DomainError(QStringLiteral("此图形暂不支持剪裁: %1").arg(type));
    const auto primitive = prims(target).first();
    const double total = type == "line" ? distance(primitive.points[0], primitive.points[1]) : primitive.radius * (type == "arc" ? primitive.end - primitive.start : Tau);
    QVector<double> cuts;
    for (int other = 0; other < shapes.size(); ++other) {
        const auto shape = shapes[other].toObject(); if (other == index || shape.value("type") == "text" || shape.value("type") == "point") continue;
        for (const auto& otherPrimitive : prims(shape)) for (const auto& crossing : intersections(primitive, otherPrimitive)) {
            const double where = std::round(along(primitive, crossing) * 1e7) / 1e7;
            if ((type == "circle" || (where > Join && where < total - Join)) && !cuts.contains(where)) cuts.append(where);
        }
    }
    std::sort(cuts.begin(), cuts.end());
    const double click = along(primitive, nearest_on_prim(primitive, value));
    if (type == "circle") {
        if (cuts.size() < 2) { shapes.removeAt(index); return shapes; }
        double lower = cuts.last() - total, upper = cuts.first() + total;
        for (const auto cut : cuts) { if (cut <= click) lower = cut; if (cut > click) { upper = cut; break; } }
        shapes[index] = piece(primitive, upper, lower + total); return shapes;
    }
    double lower = 0, upper = total;
    for (const auto cut : cuts) { if (cut <= click) lower = cut; else { upper = cut; break; } }
    shapes.removeAt(index);
    if (upper < total) { auto retained = piece(primitive, upper, total); if (target.value("construction").toBool()) retained["construction"] = true; shapes.insert(index, retained); }
    if (lower > 0) { auto retained = piece(primitive, 0, lower); if (target.value("construction").toBool()) retained["construction"] = true; shapes.insert(index, retained); }
    return shapes;
}
QJsonArray extend(const QJsonArray& source, int index, const QVector2D& value) {
    if (index < 0 || index >= source.size()) throw DomainError(QStringLiteral("图形序号越界"));
    auto shapes = source; auto target = shapes[index].toObject(); const auto type = target.value("type").toString();
    if (type != "line" && type != "arc") throw DomainError(QStringLiteral("此图形暂不支持延伸: %1").arg(type));
    const auto primitive = prims(target).first(); const auto tips = prim_ends(primitive).value();
    const bool second = distance(tips.second, value) < distance(tips.first, value);
    const auto tip = second ? tips.second : tips.first;
    Primitive probe;
    if (type == "line") probe = line(tip, tip + unit(tip - (second ? tips.first : tips.second)) * 100000);
    else {
        const double spare = Tau - (primitive.end - primitive.start);
        if (spare < 1e-9) throw DomainError(QStringLiteral("这已经是一整个圆"));
        probe = roundPrimitive("arc", primitive.centre, primitive.radius, second ? primitive.end : primitive.start - spare, second ? primitive.end + spare : primitive.start);
    }
    double best = std::numeric_limits<double>::infinity(); QVector2D found;
    for (int other = 0; other < shapes.size(); ++other) {
        const auto shape = shapes[other].toObject(); if (other == index || shape.value("type") == "point" || shape.value("type") == "text") continue;
        for (const auto& otherPrimitive : prims(shape)) for (const auto& crossing : intersections(probe, otherPrimitive)) {
            const double reach = type == "line" ? distance(crossing, tip) : modulo(second ? angle(primitive.centre, crossing) - primitive.end : primitive.start - angle(primitive.centre, crossing)) * primitive.radius;
            if (reach > Join && reach < best) { best = reach; found = crossing; }
        }
    }
    if (!std::isfinite(best)) throw DomainError(QStringLiteral("这一头延伸出去碰不到别的线"));
    if (type == "line") { target[second ? "x2" : "x1"] = double(found.x()); target[second ? "y2" : "y1"] = double(found.y()); }
    else target[second ? "a1" : "a0"] = number(target, second ? "a1" : "a0") + (second ? 1 : -1) * degrees(best / primitive.radius);
    shapes[index] = target; return shapes;
}

}
