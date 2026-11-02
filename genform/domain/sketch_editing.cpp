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
double dot(const QVector2D& first, const QVector2D& second) { return double(first.x()) * second.x() + double(first.y()) * second.y(); }
QVector2D unit(const QVector2D& value) { const double magnitude = std::hypot(value.x(), value.y()); return magnitude > 0 ? value / float(magnitude) : QVector2D(1, 0); }
QJsonArray json(const QVector2D& value) { return {double(value.x()), double(value.y())}; }
QJsonArray json(const QVector<QVector2D>& values) { QJsonArray result; for (const auto& value : values) result.append(json(value)); return result; }
QVector2D readPoint(const QJsonValue& value) { const auto array = value.toArray(); if (array.size() < 2) throw DomainError(QStringLiteral("点缺少坐标")); return {float(array[0].toDouble()), float(array[1].toDouble())}; }
QVector2D segmentFoot(const QVector2D& value, const QVector2D& first, const QVector2D& second, bool bounded = true) {
    const auto delta = second - first; const double squared = dot(delta, delta); double fraction = squared > 0 ? dot(value - first, delta) / squared : 0;
    if (bounded) fraction = std::clamp(fraction, 0., 1.);
    return first + delta * float(fraction);
}
QJsonObject lineShape(const QVector2D& first, const QVector2D& second) { return {{"type", "line"}, {"x1", double(first.x())}, {"y1", double(first.y())}, {"x2", double(second.x())}, {"y2", double(second.y())}}; }
QJsonObject turnedLine(const QJsonObject& shape, double heading, std::optional<double> span = {}) {
    const auto tips = ends(shape).value(); const auto middle = (tips.first + tips.second) / 2;
    const double half = span.value_or(distance(tips.first, tips.second)) / 2, current = std::atan2(double(tips.second.y()) - tips.first.y(), double(tips.second.x()) - tips.first.x());
    if (std::cos(heading - current) < 0) heading += Pi;
    const QVector2D delta(float(half * std::cos(heading)), float(half * std::sin(heading)));
    auto result = shape; const auto coordinates = lineShape(middle - delta, middle + delta);
    for (auto iterator = coordinates.begin(); iterator != coordinates.end(); ++iterator) result[iterator.key()] = iterator.value();
    return result;
}
double heading(const QJsonObject& shape) { return std::atan2(number(shape, "y2") - number(shape, "y1"), number(shape, "x2") - number(shape, "x1")); }
QByteArray shapeKey(const QJsonObject& shape) {
    std::function<QJsonValue(const QJsonValue&)> rounded = [&](const QJsonValue& value) -> QJsonValue {
        if (value.isDouble()) return std::nearbyint(value.toDouble() * 1e6) / 1e6;
        if (value.isArray()) { QJsonArray array; for (const auto& item : value.toArray()) array.append(rounded(item)); return array; }
        if (value.isObject()) { auto object = value.toObject(); for (auto iterator = object.begin(); iterator != object.end(); ++iterator) iterator.value() = rounded(iterator.value()); return object; }
        return value;
    };
    return QJsonDocument(rounded(shape).toObject()).toJson(QJsonDocument::Compact);
}
}
std::optional<QVector2D> corner_near(const QJsonArray& shapes, const QVector2D& value, double tolerance) {
    QVector<QVector2D> corners;
    for (const auto& shapeValue : shapes) {
        const auto shape = shapeValue.toObject(); const auto type = shape.value("type").toString();
        if (type == "rect" || type == "polygon" || type == "ngon") corners += vertices(shape);
        if (type == "line") { const auto tips = ends(shape).value(); corners.append(tips.first); corners.append(tips.second); }
    }
    std::optional<QVector2D> result; double best = tolerance;
    for (const auto& corner : corners) { const double gap = distance(corner, value); if (gap <= best) { result = corner; best = gap; } }
    return result;
}
QJsonArray fillet(const QJsonArray& shapes, const QVector2D& value, double radius, double tolerance) {
    if (!std::isfinite(radius) || radius <= 0) throw DomainError(QStringLiteral("圆角半径必须为正数"));
    const auto corner = corner_near(shapes, value, tolerance);
    if (!corner) throw DomainError(QStringLiteral("附近没有可做圆角的顶点"));
    QJsonArray result;
    for (const auto& shapeValue : shapes) {
        const auto shape = shapeValue.toObject(); const auto type = shape.value("type").toString(); bool touches = false;
        if (type == "rect" || type == "polygon" || type == "ngon") for (const auto& vertex : vertices(shape)) if (distance(vertex, *corner) <= Join) touches = true;
        if (touches) for (const auto& piece : explode(shape)) result.append(piece);
        else result.append(shape);
    }
    QVector<std::pair<int, int>> meeting;
    for (int index = 0; index < result.size(); ++index) {
        const auto shape = result[index].toObject(); if (shape.value("type") != "line") continue;
        const auto tips = ends(shape).value(); if (distance(tips.first, *corner) <= Join) meeting.append({index, 0}); if (distance(tips.second, *corner) <= Join) meeting.append({index, 1});
    }
    if (meeting.size() != 2 || meeting[0].first == meeting[1].first) throw DomainError(QStringLiteral("圆角必须正好两条直线交在顶点"));
    QVector<QVector2D> away; QVector<double> spans;
    for (const auto& item : meeting) { const auto tips = ends(result[item.first].toObject()).value(); const auto far = item.second ? tips.first : tips.second; away.append(unit(far - *corner)); spans.append(distance(far, *corner)); }
    const double cosine = std::clamp(dot(away[0], away[1]), -1., 1.);
    if (std::abs(cosine) > 1 - 1e-9) throw DomainError(QStringLiteral("共线直线不能做圆角"));
    const double half = std::acos(cosine) / 2, setback = radius / std::tan(half);
    if (setback > std::min(spans[0], spans[1]) - Join) throw DomainError(QStringLiteral("圆角半径太大，线不够长"));
    const QVector<QVector2D> tangents{*corner + away[0] * float(setback), *corner + away[1] * float(setback)};
    const auto centre = *corner + unit(away[0] + away[1]) * float(radius / std::sin(half));
    for (int offset = 0; offset < 2; ++offset) {
        auto shape = result[meeting[offset].first].toObject(); const bool second = meeting[offset].second != 0;
        shape[second ? "x2" : "x1"] = double(tangents[offset].x()); shape[second ? "y2" : "y1"] = double(tangents[offset].y()); result[meeting[offset].first] = shape;
    }
    double first = std::atan2(double(tangents[0].y()) - centre.y(), double(tangents[0].x()) - centre.x()), second = std::atan2(double(tangents[1].y()) - centre.y(), double(tangents[1].x()) - centre.x());
    double sweep = second - first; sweep -= std::floor(sweep / (2 * Pi)) * 2 * Pi; if (sweep > Pi) std::swap(first, second);
    result.append(QJsonObject{{"type", "arc"}, {"cx", double(centre.x())}, {"cy", double(centre.y())}, {"r", radius}, {"a0", first * 180 / Pi}, {"a1", second * 180 / Pi}});
    return result;
}
QStringList relations_for(const QJsonArray& chosen) {
    int lines = 0, rounds = 0; bool centred = true, text = false;
    for (const auto& value : chosen) { const auto type = value.toObject().value("type").toString(); lines += type == "line"; rounds += QStringList{"circle", "arc", "arcslot"}.contains(type); centred = centred && QStringList{"circle", "arc", "arcslot", "ellipse", "ngon", "rect"}.contains(type); text = text || type == "text"; }
    const int count = int(chosen.size()); QStringList result;
    if (lines == count && count >= 1) result += QStringList{"horizontal", "vertical"};
    if (lines == count && count >= 2) result += QStringList{"parallel", "perpendicular", "collinear", "equal"};
    if (rounds == count && count >= 2) result.append("equal");
    if (count >= 2 && centred) result.append("concentric");
    if (count == 2 && lines == 1 && rounds == 1) result.append("tangent");
    if (count >= 2 && !text) result.append("coincident");
    return result;
}
QJsonArray relate(const QJsonArray& source, const QVector<int>& selection, const QString& kind) {
    QJsonArray chosen; QSet<int> seen;
    for (const int index : selection) { if (index < 0 || index >= source.size() || seen.contains(index)) throw DomainError(QStringLiteral("无效的图形选择")); seen.insert(index); chosen.append(source[index]); }
    if (!relations_for(chosen).contains(kind)) throw DomainError(QStringLiteral("选中的图形不能添加关系: %1").arg(kind));
    const auto lead = chosen.first().toObject(); auto result = source;
    for (int offset = kind == "horizontal" || kind == "vertical" ? 0 : 1; offset < selection.size(); ++offset) {
        const int index = selection[offset]; auto shape = result[index].toObject();
        if (kind == "horizontal" || kind == "vertical") shape = turnedLine(shape, kind == "horizontal" ? 0 : Pi / 2);
        else if (kind == "parallel" || kind == "perpendicular") shape = turnedLine(shape, heading(lead) + (kind == "perpendicular" ? Pi / 2 : 0));
        else if (kind == "collinear") {
            shape = turnedLine(shape, heading(lead)); const auto tips = ends(shape).value(), leadTips = ends(lead).value(); const auto middle = (tips.first + tips.second) / 2, foot = segmentFoot(middle, leadTips.first, leadTips.second, false); shape = moved(shape, foot.x() - middle.x(), foot.y() - middle.y());
        } else if (kind == "equal") {
            if (shape.value("type") == "line") { const auto tips = ends(lead).value(); shape = turnedLine(shape, heading(shape), distance(tips.first, tips.second)); }
            else shape["r"] = lead.value("r");
        } else if (kind == "concentric") shape = moved(shape, number(lead, "cx", 0) - number(shape, "cx", 0), number(lead, "cy", 0) - number(shape, "cy", 0));
        else if (kind == "tangent") {
            const bool leadLine = lead.value("type") == "line"; const auto line = leadLine ? lead : shape, round = leadLine ? shape : lead; const auto tips = ends(line).value();
            const QVector2D centre(float(number(round, "cx", 0)), float(number(round, "cy", 0))); const auto foot = segmentFoot(centre, tips.first, tips.second, false); const double gap = distance(centre, foot);
            const auto direction = gap > 1e-9 ? unit(centre - foot) : QVector2D(float(-std::sin(heading(line))), float(std::cos(heading(line))));
            const double shift = (number(round, "r") - gap) * (leadLine ? 1 : -1); shape = moved(shape, direction.x() * shift, direction.y() * shift);
        } else if (kind == "coincident") {
            const auto mine = key_points(shape), theirs = key_points(lead); double best = std::numeric_limits<double>::infinity(); QVector2D shift;
            for (const auto& first : mine) for (const auto& second : theirs) { const auto from = readPoint(first.toArray()[1]), to = readPoint(second.toArray()[1]); const double gap = distance(from, to); if (gap < best) { best = gap; shift = to - from; } }
            if (!std::isfinite(best)) throw DomainError(QStringLiteral("图形缺少重合参考点"));
            shape = moved(shape, shift.x(), shift.y());
        }
        result[index] = shape;
    }
    return result;
}
QJsonObject fit_line(const QVector<QVector2D>& values, double tolerance) {
    if (values.size() < 2) throw DomainError(QStringLiteral("拟合至少需要两个点"));
    const int count = int(values.size()); const bool whole = distance(values.first(), values.last()) <= 1e-5;
    const auto far = *std::max_element(values.begin(), values.end(), [&](const auto& first, const auto& second) { return distance(first, values.first()) < distance(second, values.first()); });
    double widest = 0;
    for (const auto& value : values) widest = std::max(widest, distance(value, segmentFoot(value, values.first(), far)));
    if (widest < 1e-6) {
        const auto sorted = std::minmax_element(values.begin(), values.end(), [](const auto& first, const auto& second) { return first.x() != second.x() ? first.x() < second.x() : first.y() < second.y(); });
        return lineShape(*sorted.first, *sorted.second);
    }
    if (count >= 5) {
        const auto circle = circle3(values[0], values[count / 3], values[2 * count / 3]); bool round = circle.has_value();
        if (circle) for (const auto& value : values) if (std::abs(distance(value, circle->first) - circle->second) > tolerance * std::max(1., circle->second)) round = false;
        if (round) {
            if (whole) return {{"type", "circle"}, {"cx", double(circle->first.x())}, {"cy", double(circle->first.y())}, {"r", circle->second}};
            if (const auto arc = arc3(values.first(), values.last(), values[count / 2])) return *arc;
        }
    }
    QVector<QVector2D> picked;
    for (int index = 0; index < count - 1; index += 4) picked.append(values[index]);
    if (!whole) picked.append(values.last());
    if (picked.size() < (whole ? 3 : 2)) { picked = values; if (whole) picked.removeLast(); }
    return {{"type", "spline"}, {"points", json(picked)}, {"closed", whole}};
}
QJsonArray fit_lines(const QVector<QVector<QVector2D>>& lines) {
    QJsonArray result; QSet<QByteArray> seen;
    for (const auto& values : lines) {
        if (values.size() < 2) continue;
        const auto shape = fit_line(values); if (length(shape) < Tiny) continue;
        const auto key = shapeKey(shape); QByteArray twin = key;
        if (shape.value("type") == "line") { const auto tips = ends(shape).value(); twin = shapeKey(lineShape(tips.second, tips.first)); }
        if (!seen.contains(key) && !seen.contains(twin)) { result.append(shape); seen.insert(key); }
    }
    return result;
}
QJsonArray project_edges(const QJsonObject& model, const QJsonValue& plane, double offset) {
    if (!model.value("has_body").toBool()) return {};
    const auto basis = frame(plane, offset); const auto segments = model.value("segments").toArray(), owners = model.value("segment_edge").toArray();
    if (segments.size() != owners.size()) throw DomainError(QStringLiteral("边线段和所属边数组长度不一致"));
    auto vector = [](const QJsonValue& value) { const auto array = value.toArray(); if (array.size() != 3) throw DomainError(QStringLiteral("投影点必须包含三维坐标")); return QVector3D(float(array[0].toDouble()), float(array[1].toDouble()), float(array[2].toDouble())); };
    auto flat = [&](const QJsonValue& value) { const auto local = vector(value) - basis.origin; return QVector2D(QVector3D::dotProduct(local, basis.x), QVector3D::dotProduct(local, basis.y)); };
    QMap<int, QVector<int>> byEdge;
    for (int index = 0; index < owners.size(); ++index) byEdge[owners[index].toInt()].append(index);
    QJsonArray found; QSet<QByteArray> seen;
    for (const auto& edgeValue : model.value("edges").toArray()) {
        const auto edge = edgeValue.toObject(); const auto indices = byEdge.value(edge.value("id").toInt()); if (indices.isEmpty()) continue;
        QVector<QVector2D> values;
        for (const int index : indices) { const auto segment = segments[index].toArray(); if (segment.size() != 2) throw DomainError(QStringLiteral("边线段必须有两个端点")); values.append(flat(segment[0])); }
        values.append(flat(segments[indices.last()].toArray()[1])); QJsonObject shape;
        if (edge.value("type") == "line") shape = lineShape(values.first(), values.last());
        else if (edge.value("type") == "circle" && edge.contains("center") && edge.contains("axis") && std::abs(QVector3D::dotProduct(vector(edge.value("axis")), basis.normal)) > 1 - 1e-9) {
            const auto centre = flat(edge.value("center")); const double radius = edge.value("radius").toDouble();
            shape = {{"type", "circle"}, {"cx", double(centre.x())}, {"cy", double(centre.y())}, {"r", radius}};
            if (distance(values.first(), values.last()) > 1e-5) {
                auto angle = [&](const QVector2D& value) { return std::atan2(double(value.y()) - centre.y(), double(value.x()) - centre.x()); };
                double first = angle(values.first()), second = angle(values.last()); double step = angle(values[1]) - first + Pi; step -= std::floor(step / (2 * Pi)) * 2 * Pi; step -= Pi;
                if (step < 0) std::swap(first, second);
                shape["type"] = "arc"; shape["a0"] = first * 180 / Pi; shape["a1"] = second * 180 / Pi;
            }
        } else shape = fit_line(values);
        if (length(shape) < Tiny) continue;
        const auto key = shapeKey(shape); QByteArray twin = key;
        if (shape.value("type") == "line") { const auto tips = ends(shape).value(); twin = shapeKey(lineShape(tips.second, tips.first)); }
        if (!seen.contains(key) && !seen.contains(twin)) { found.append(shape); seen.insert(key); }
    }
    return found;
}
QVector<QVector3D> text_layout(const QJsonObject& shape, const QVector<double>& advances) {
    QVector<QVector3D> result;
    for (const double advance : advances) if (!std::isfinite(advance) || advance < 0) throw DomainError(QStringLiteral("字宽必须是非负有限数字"));
    const auto path = shape.value("path").toObject(); double run = 0;
    if (path.isEmpty()) {
        const double angle = number(shape, "angle", 0) * Pi / 180;
        for (const double advance : advances) { result.append(QVector3D(float(number(shape, "x") + std::cos(angle) * run), float(number(shape, "y") + std::sin(angle) * run), float(angle))); run += advance; }
        return result;
    }
    QVector<QVector2D> values;
    for (const auto& part : polylines(path, 96)) for (int index = values.isEmpty() ? 0 : 1; index < part.size(); ++index) values.append(part[index]);
    if (values.size() < 2) throw DomainError(QStringLiteral("文字路径没有可用线段"));
    if (QStringList{"arc", "circle"}.contains(path.value("type").toString()) != shape.value("flip").toBool()) std::reverse(values.begin(), values.end());
    QVector<double> marks{0}; for (int index = 1; index < values.size(); ++index) marks.append(marks.last() + distance(values[index - 1], values[index]));
    int segment = 0;
    for (const double advance : advances) {
        const double middle = run + advance / 2;
        while (segment < values.size() - 2 && marks[segment + 1] < middle) ++segment;
        const auto direction = unit(values[segment + 1] - values[segment]); const auto location = values[segment] + direction * float(middle - marks[segment] - advance / 2);
        result.append({location.x(), location.y(), float(std::atan2(direction.y(), direction.x()))}); run += advance;
    }
    return result;
}
}
