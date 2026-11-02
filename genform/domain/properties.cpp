#include "geometry.hpp"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QSet>
#include <algorithm>
#include <cmath>

namespace genform::domain {
namespace {
struct Material {
    const char* name;
    double density;
    const char* color;
    double elastic;
    double poisson;
    double yield;
};
const Material Materials[] = {
    {"普通碳钢", 7.85, "#8E97A3", 210000, .29, 235}, {"合金钢", 7.70, "#7F8894", 210000, .28, 620},
    {"不锈钢 304", 7.93, "#B9C0C8", 193000, .29, 215}, {"铸铁", 7.20, "#6B6F76", 110000, .26, 200},
    {"铝合金 6061", 2.70, "#C9CED6", 68900, .33, 276}, {"铝合金 7075", 2.81, "#C4CAD2", 71700, .33, 503},
    {"45# 钢", 7.85, "#858C96", 209000, .29, 355}, {"黄铜", 8.50, "#C9A24A", 100000, .34, 200},
    {"紫铜", 8.90, "#C07A4E", 117000, .34, 70}, {"钛合金 Ti-6Al-4V", 4.43, "#A8A39A", 113800, .34, 880},
    {"ABS", 1.04, "#E6E1D3", 2200, .35, 40}, {"尼龙 PA12", 1.01, "#DDDAD2", 1700, .39, 48},
    {"聚碳酸酯 PC", 1.20, "#C7D7E6", 2300, .37, 62}, {"PLA", 1.24, "#E9E4DA", 3500, .36, 60},
    {"聚丙烯 PP", .91, "#2F3135", 1500, .42, 30}, {"PMMA 亚克力", 1.19, "#D9E4EC", 3000, .37, 70},
    {"铸造铝合金 A356", 2.68, "#B8BDC4", 72400, .33, 165}, {"钢化玻璃", 2.50, "#2A3A48", 70000, .22, 120},
    {"橡胶", 1.15, "#1E1F21", 5, .49, 15}, {"皮革 + 海绵", .35, "#7A4A2C", 0, 0, 0}
};
struct Rule {
    const char* key;
    const char* label;
    const char* unit;
    double value;
    double low;
    double high;
    bool integer;
    const char* help;
};
const Rule Rules[] = {
    {"tolerance", "加工公差 (±)", "mm", .1, .001, 5, false, "零件制造公差"},
    {"clearance", "件与件最小间隙", "mm", .5, 0, 50, false, "不应接触的零件最小间隙"},
    {"overlap", "连接最小压入量", "mm", .3, 0, 50, false, "焊接、粘接、压装最小重叠"},
    {"min_wall", "最小壁厚", "mm", 1, .05, 50, false, "工艺另有壁厚下限"},
    {"min_hole", "最小孔径", "mm", 1, .05, 50, false, "小孔钻头容易折断"},
    {"hole_ratio", "孔最大深径比", "", 10, 1, 100, false, "孔深除以孔径"},
    {"corner_radius", "铣削内角最小圆角", "mm", 1, 0, 50, false, "铣刀半径限制"},
    {"min_text", "最小字高", "mm", 2, .1, 100, false, "刻字、铸字最小高度"},
    {"proofing", "按铨洲智造 CNC 打样检查", "", 0, 0, 1, true, "按设计建议 8.14 版检查，最终以平台仿真为准"},
    {"batch", "生产数量", "件", 1, 1, 10000000, true, "模具费摊销批量"},
    {"pair_limit", "间隙检查最多比较的件数", "件", 600, 10, 5000, true, "几何内核比较数量上限"}
};
QVector3D vector3(const QJsonValue& value) {
    const auto array = value.toArray();
    if (array.size() != 3) throw DomainError(QStringLiteral("三维向量必须包含三个数字"));
    for (const auto& item : array) if (!item.isDouble() || !std::isfinite(item.toDouble())) throw DomainError(QStringLiteral("三维向量必须包含有限数字"));
    return {float(array[0].toDouble()), float(array[1].toDouble()), float(array[2].toDouble())};
}
QJsonArray json3(double x, double y, double z) { return {x, y, z}; }
double money(double value) { return std::nearbyint(value * 100) / 100; }
QJsonObject emptyDescription() { return {{"kind", "custom"}, {"spec", ""}, {"process", ""}, {"material", ""}, {"unit", 0.0}, {"bound", false}}; }
QString partId(int index) { return QStringLiteral("part:%1").arg(index); }
QJsonArray ids(const QVector<int>& indices) { QJsonArray result; for (const int index : indices) result.append(partId(index)); return result; }
QString joinedNames(const QStringList& names, const QVector<int>& indices, int limit) {
    QStringList found;
    for (int index = 0; index < std::min(limit, int(indices.size())); ++index) found.append(names.value(indices[index]));
    return found.join(QStringLiteral("、")) + (indices.size() > limit ? QStringLiteral("…") : QString());
}
}

QMatrix4x4 PlaneFrame::matrix() const {
    QMatrix4x4 result;
    result.setColumn(0, QVector4D(x, 0)); result.setColumn(1, QVector4D(y, 0));
    result.setColumn(2, QVector4D(normal, 0)); result.setColumn(3, QVector4D(origin, 1));
    return result;
}
PlaneFrame frame(const QJsonValue& plane, double offset) {
    if (!std::isfinite(offset)) throw DomainError(QStringLiteral("平面偏移必须是有限数字"));
    PlaneFrame result;
    if (plane.isObject()) {
        const auto object = plane.toObject();
        result.origin = vector3(object.value("origin")); result.x = vector3(object.value("x")); result.y = vector3(object.value("y"));
    } else {
        const auto name = plane.toString().toUpper();
        if (name == "XY") { result.x = {1, 0, 0}; result.y = {0, 1, 0}; }
        else if (name == "XZ") { result.x = {1, 0, 0}; result.y = {0, 0, 1}; }
        else if (name == "YZ") { result.x = {0, 1, 0}; result.y = {0, 0, 1}; }
        else throw DomainError(QStringLiteral("未知基准面: %1").arg(name));
    }
    result.normal = QVector3D::crossProduct(result.x, result.y);
    if (result.normal.lengthSquared() < 1e-20f) throw DomainError(QStringLiteral("平面坐标轴不能共线"));
    result.origin += result.normal * float(offset);
    return result;
}
QVector<QVector3D> to_world(const QVector<QVector2D>& points, const QJsonValue& plane, double offset) {
    const auto basis = frame(plane, offset); QVector<QVector3D> result;
    for (const auto& point : points) result.append(basis.origin + basis.x * point.x() + basis.y * point.y());
    return result;
}
std::optional<QVector2D> from_ray(const QVector3D& origin, const QVector3D& direction, const QJsonValue& plane, double offset) {
    const auto basis = frame(plane, offset);
    const double slope = QVector3D::dotProduct(direction, basis.normal);
    if (std::abs(slope) < 1e-9) return {};
    const double reach = QVector3D::dotProduct(basis.origin - origin, basis.normal) / slope;
    if (reach <= 0) return {};
    const auto hit = origin + direction * float(reach) - basis.origin;
    return QVector2D(QVector3D::dotProduct(hit, basis.x), QVector3D::dotProduct(hit, basis.y));
}
QJsonArray material_catalog() {
    QJsonArray result;
    for (const auto& material : Materials) {
        QJsonObject row{{"name", QString::fromUtf8(material.name)}, {"density", material.density}, {"color", material.color}};
        row["mechanics"] = material.elastic > 0 ? QJsonValue(QJsonArray{material.elastic, material.poisson, material.yield}) : QJsonValue(QJsonValue::Null);
        result.append(row);
    }
    return result;
}
std::optional<double> density(const QString& name) { for (const auto& material : Materials) if (name == QString::fromUtf8(material.name)) return material.density; return {}; }
std::optional<QVector3D> mechanics(const QString& name) { for (const auto& material : Materials) if (name == QString::fromUtf8(material.name) && material.elastic > 0) return QVector3D(float(material.elastic), float(material.poisson), float(material.yield)); return {}; }
QString material_color(const QString& name) { for (const auto& material : Materials) if (name == QString::fromUtf8(material.name)) return QString::fromLatin1(material.color); return {}; }
std::optional<QVector3D> rgb(const QString& source) {
    QString text = source; while (text.startsWith('#')) text.remove(0, 1);
    if (text.size() != 6) return {};
    QVector3D result;
    for (int index = 0; index < 3; ++index) {
        const auto pair = text.mid(index * 2, 2);
        for (const QChar character : pair) if (!QStringLiteral("0123456789abcdefABCDEF").contains(character)) return {};
        bool valid = false; const int value = pair.toInt(&valid, 16); if (!valid) return {}; result[index] = float(value / 255.0);
    }
    return result;
}
std::optional<double> mass_grams(double volumeMm3, const QString& material) {
    if (!std::isfinite(volumeMm3) || volumeMm3 < 0) throw DomainError(QStringLiteral("体积必须是非负有限数字"));
    const auto found = density(material);
    return found ? std::optional<double>(volumeMm3 / 1000 * *found) : std::nullopt;
}
QJsonObject mass_properties(const QJsonArray& properties, const QStringList& materials) {
    double total = 0, moments[3] = {0, 0, 0}; QJsonArray missing;
    for (int index = 0; index < properties.size(); ++index) {
        const auto row = properties[index].toObject(); const auto grams = mass_grams(number(row, "volume", 0), materials.value(index));
        if (!grams) { missing.append(index); continue; }
        const auto centre = row.value("centre").toArray();
        if (centre.size() != 3) throw DomainError(QStringLiteral("质量属性缺少 centre 三维坐标"));
        total += *grams; for (int axis = 0; axis < 3; ++axis) moments[axis] += *grams * centre[axis].toDouble();
    }
    return {{"grams", total}, {"kg", total / 1000}, {"centre", total > 0 ? QJsonValue(json3(moments[0] / total, moments[1] / total, moments[2] / total)) : QJsonValue(QJsonValue::Null)}, {"missing", missing}};
}
QJsonArray rule_table() {
    QJsonArray result;
    for (const auto& rule : Rules) result.append(QJsonObject{{"key", rule.key}, {"label", QString::fromUtf8(rule.label)}, {"unit", rule.unit}, {"default", rule.value}, {"min", rule.low}, {"max", rule.high}, {"help", QString::fromUtf8(rule.help)}});
    return result;
}
QJsonObject clean_rules(const QJsonObject& values) {
    QJsonObject result;
    for (const auto& rule : Rules) {
        const auto value = values.value(rule.key); if (value.isUndefined() || value.isNull()) continue;
        bool valid = value.isDouble() || value.isBool(); double numeric = value.isBool() ? (value.toBool() ? 1 : 0) : value.toDouble();
        if (value.isString()) numeric = value.toString().toDouble(&valid);
        if (!valid || !std::isfinite(numeric)) continue;
        numeric = std::clamp(numeric, rule.low, rule.high); result[rule.key] = rule.integer ? std::nearbyint(numeric) : numeric;
    }
    return result;
}
QJsonObject effective_rules(const QJsonObject& settings, const QJsonObject& document) {
    QJsonObject result; for (const auto& rule : Rules) result[rule.key] = rule.value;
    for (const auto& source : {clean_rules(settings), clean_rules(document)}) for (auto iterator = source.begin(); iterator != source.end(); ++iterator) result[iterator.key()] = iterator.value();
    return result;
}
QJsonObject describe_document(const QJsonObject& document) {
    const QSet<QString> excluded{"sketch", "plane", "axis", "point", "curve", "helix", "coordinate"};
    auto result = emptyDescription(); result["material"] = document.value("props").toObject().value("material").toString();
    QJsonArray processes;
    for (const auto& value : document.value("features").toArray()) {
        const auto feature = value.toObject(), process = feature.value("process").toObject();
        if (!excluded.contains(feature.value("type").toString()) && !feature.value("suppressed").toBool() && !process.value("id").toString().isEmpty()) processes.append(process);
    }
    if (processes.isEmpty()) return result;
    bool standard = true; double total = 0, maximum = -std::numeric_limits<double>::infinity(); QJsonObject main; QString spec;
    for (const auto& value : processes) {
        const auto process = value.toObject(); const double cost = process.value("cost").toDouble(); total += cost;
        if (cost > maximum) { maximum = cost; main = process; }
        standard = standard && process.value("standard").toBool();
        if (spec.isEmpty()) spec = process.value("spec").toString();
    }
    result["kind"] = main.value("id") == "purchase" ? "purchase" : standard ? "standard" : "custom";
    result["spec"] = spec; result["process"] = main.value("name").toString(); result["unit"] = money(total); result["bound"] = true;
    return result;
}
QJsonObject describe(const QString& path) {
    QFile file(path); if (!file.open(QIODevice::ReadOnly)) return emptyDescription();
    QJsonParseError error; const auto document = QJsonDocument::fromJson(file.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) return emptyDescription();
    return describe_document(document.object());
}
QJsonArray bill(const QJsonArray& parts, const QJsonObject& documents) {
    QVector<QJsonObject> rows; QMap<QString, int> seen; QMap<QString, QJsonObject> known;
    const QMap<QString, QString> kinds{{"standard", QStringLiteral("标准件")}, {"purchase", QStringLiteral("外购件")}, {"custom", QStringLiteral("非标件")}};
    for (int index = 0; index < parts.size(); ++index) {
        const auto part = parts[index].toObject(); const auto path = part.value("path").toString();
        if (!known.contains(path)) known[path] = documents.contains(path) ? describe_document(documents.value(path).toObject()) : path.isEmpty() ? emptyDescription() : describe(path);
        const auto info = known[path]; const bool handed = part.value("mirror").toBool() && info.value("kind") == "custom";
        auto normalized = path.isEmpty() ? QString() : QDir::cleanPath(QFileInfo(path).absoluteFilePath());
#ifdef Q_OS_WIN
        normalized = normalized.toLower();
#endif
        const QString key = normalized + QChar(0) + (handed ? '1' : '0');
        if (!seen.contains(key)) {
            auto row = info; auto name = part.value("name").toString(); if (name.isEmpty()) name = QFileInfo(path).completeBaseName();
            row["name"] = name + (handed ? QStringLiteral("（镜像件）") : QString()); row["path"] = path; row["mirror"] = handed;
            row["count"] = 0; row["indices"] = QJsonArray(); row["kind_name"] = kinds.value(info.value("kind").toString());
            seen[key] = int(rows.size()); rows.append(row);
        }
        auto& row = rows[seen[key]]; row["count"] = row.value("count").toInt() + 1;
        auto indices = row.value("indices").toArray(); indices.append(index); row["indices"] = indices;
    }
    const QMap<QString, int> order{{"custom", 0}, {"purchase", 1}, {"standard", 2}};
    for (auto& row : rows) row["total"] = money(row.value("unit").toDouble() * row.value("count").toInt());
    std::stable_sort(rows.begin(), rows.end(), [&](const auto& first, const auto& second) {
        const int firstOrder = order.value(first.value("kind").toString()), secondOrder = order.value(second.value("kind").toString());
        return firstOrder != secondOrder ? firstOrder < secondOrder : first.value("name").toString() < second.value("name").toString();
    });
    QJsonArray result; for (const auto& row : rows) result.append(row); return result;
}
QJsonObject bill_totals(const QJsonArray& rows) {
    QJsonObject result; for (const auto& kind : QStringList{"standard", "purchase", "custom", "all"}) result[kind] = QJsonObject{{"types", 0}, {"count", 0}, {"cost", 0.0}};
    int unbound = 0;
    for (const auto& value : rows) {
        const auto row = value.toObject(); if (!row.value("bound").toBool()) ++unbound;
        for (const auto& kind : QStringList{row.value("kind").toString(), "all"}) {
            auto total = result.value(kind).toObject(); total["types"] = total.value("types").toInt() + 1; total["count"] = total.value("count").toInt() + row.value("count").toInt(); total["cost"] = money(total.value("cost").toDouble() + row.value("total").toDouble()); result[kind] = total;
        }
    }
    result["unbound"] = unbound; return result;
}
QByteArray bill_csv(const QJsonArray& rows) {
    QByteArray result = QByteArray::fromHex("efbbbf");
    auto append = [&](const QStringList& columns) {
        QStringList escaped;
        for (auto column : columns) { if (column.contains(',') || column.contains('"') || column.contains('\r') || column.contains('\n')) { column.replace("\"", "\"\""); column = '"' + column + '"'; } escaped.append(column); }
        result += escaped.join(',').toUtf8() + "\r\n";
    };
    append({QStringLiteral("序号"), QStringLiteral("名称"), QStringLiteral("类别"), QStringLiteral("规格"), QStringLiteral("工艺"), QStringLiteral("材质"), QStringLiteral("数量"), QStringLiteral("单价 (元)"), QStringLiteral("小计 (元)"), QStringLiteral("文件")});
    int index = 0;
    for (const auto& value : rows) {
        const auto row = value.toObject(); append({QString::number(++index), row.value("name").toString(), row.value("kind_name").toString(), row.value("spec").toString(), row.value("process").toString(), row.value("material").toString(), QString::number(row.value("count").toInt()), QString::number(row.value("unit").toDouble(), 'f', 2), QString::number(row.value("total").toDouble(), 'f', 2), row.value("path").toString()});
    }
    return result;
}
QJsonObject issue(const QString& level, const QString& code, const QString& title, const QString& detail, const QJsonArray& features, const QJsonValue& point) {
    QJsonArray filtered; for (const auto& feature : features) if (!feature.toString().isEmpty()) filtered.append(feature);
    return {{"level", level}, {"code", code}, {"title", title}, {"detail", detail}, {"features", filtered}, {"point", point}};
}
QJsonArray galvanic(const QJsonArray& pairs, const QStringList& materials, const QStringList& names) {
    const QMap<QString, double> anodic{{QStringLiteral("铝合金 6061"), .90}, {QStringLiteral("铸造铝合金 A356"), .90}, {QStringLiteral("普通碳钢"), .85}, {QStringLiteral("合金钢"), .85}, {QStringLiteral("铸铁"), .85}, {QStringLiteral("不锈钢 304"), .50}, {QStringLiteral("黄铜"), .40}, {QStringLiteral("紫铜"), .35}, {QStringLiteral("钛合金 Ti-6Al-4V"), .15}};
    QMap<QString, QJsonArray> groups;
    for (const auto& value : pairs) {
        const auto pair = value.toObject(); if (pair.value("kind") != "touch" && pair.value("kind") != "clash") continue;
        auto first = materials.value(pair.value("a").toInt()), second = materials.value(pair.value("b").toInt());
        if (!anodic.contains(first) || !anodic.contains(second) || first == second || std::abs(anodic[first] - anodic[second]) <= .25) continue;
        if (first > second) std::swap(first, second);
        groups[first + QChar(0) + second].append(pair);
    }
    QJsonArray result;
    for (auto iterator = groups.begin(); iterator != groups.end(); ++iterator) {
        const auto keys = iterator.key().split(QChar(0)); const auto first = keys[0], second = keys[1]; const auto rows = iterator.value();
        QSet<QString> identifiers; QStringList where;
        for (int index = 0; index < rows.size(); ++index) { const auto row = rows[index].toObject(); const int a = row.value("a").toInt(), b = row.value("b").toInt(); identifiers.insert(partId(a)); identifiers.insert(partId(b)); if (index < 4) where.append(names.value(a) + QStringLiteral(" ↔ ") + names.value(b)); }
        auto ordered = identifiers.values(); std::sort(ordered.begin(), ordered.end());
        result.append(issue("warning", "galvanic", QStringLiteral("电化学腐蚀：%1 贴着 %2").arg(first, second), QStringLiteral("两种金属差 %1 V（超过 0.25 V），潮湿时 %2 会被腐蚀：中间加绝缘垫片 / 涂层，或换材料。%3 处：%4%5").arg(std::abs(anodic[first] - anodic[second]), 0, 'f', 2).arg(anodic[first] > anodic[second] ? first : second).arg(rows.size()).arg(where.join(QStringLiteral("、")), rows.size() > 4 ? QStringLiteral("…") : QString()), QJsonArray::fromStringList(ordered), rows.first().toObject().value("point").isUndefined() ? QJsonValue(QJsonValue::Null) : rows.first().toObject().value("point")));
    }
    return result;
}
QJsonArray fasteners(const QJsonArray& pairs, const QStringList& kinds, const QStringList& names) {
    QMap<int, QSet<int>> touching;
    for (const auto& value : pairs) { const auto pair = value.toObject(); if (pair.value("kind") == "touch" || pair.value("kind") == "clash") { const int first = pair.value("a").toInt(), second = pair.value("b").toInt(); touching[first].insert(second); touching[second].insert(first); } }
    QVector<int> lonely; for (int index = 0; index < kinds.size(); ++index) if (kinds[index] == "standard" && touching[index].size() < 2) lonely.append(index);
    if (lonely.isEmpty()) return {};
    return {issue("warning", "fastener", QStringLiteral("%1 个紧固件没起作用").arg(lonely.size()), joinedNames(names, lonely, 6) + QStringLiteral("：只贴着一个件（或一个都没贴着），没把两个件连在一起——长度不够、孔没对上，或者放错了地方"), ids(lonely))};
}
QJsonArray orphans(const QJsonArray& pairs, const QStringList& kinds, const QStringList& names, const QJsonArray& properties) {
    QMap<int, QJsonArray> buried;
    for (const auto& value : pairs) {
        const auto pair = value.toObject(); if (pair.value("kind") != "clash") continue;
        const int first = pair.value("a").toInt(), second = pair.value("b").toInt();
        for (const auto& indices : QVector<std::pair<int, int>>{{first, second}, {second, first}}) if (kinds.value(indices.first) == "standard") buried[indices.first].append(QJsonObject{{"other", indices.second}, {"volume", pair.value("volume")}, {"point", pair.value("point").isUndefined() ? QJsonValue(QJsonValue::Null) : pair.value("point")}});
    }
    QJsonArray result;
    for (auto iterator = buried.begin(); iterator != buried.end(); ++iterator) {
        const int index = iterator.key(); const double own = index >= 0 && index < properties.size() ? properties[index].toObject().value("volume").toDouble() : 0;
        double volume = 0; QVector<int> hosts;
        for (const auto& value : iterator.value()) { const auto row = value.toObject(); volume += row.value("volume").toDouble(); hosts.append(row.value("other").toInt()); }
        if (own <= 0 || volume < own * .25) continue;
        auto features = ids({index}); for (const auto& identifier : ids(hosts)) features.append(identifier);
        result.append(issue("error", "orphan", QStringLiteral("孤立的标准件：%1").arg(names.value(index)), QStringLiteral("%1% 的体积埋在 %2 的实料里：它装的孔多半被删了或挪了，件还留在原处——删掉这个件，或把孔补回来").arg(volume / own * 100, 0, 'f', 0).arg(joinedNames(names, hosts, int(hosts.size()))), features, iterator.value().first().toObject().value("point")));
    }
    return result;
}
QJsonArray duplicates(const QJsonArray& parts) {
    QMap<QByteArray, int> seen; QJsonArray result;
    for (int index = 0; index < parts.size(); ++index) {
        const auto part = parts[index].toObject(); QJsonArray key{part.value("path").toString()};
        for (const auto& field : QStringList{"move", "turn"}) { auto vector = part.value(field).toArray(); if (vector.isEmpty()) vector = {0, 0, 0}; QJsonArray rounded; for (const auto& value : vector) rounded.append(std::nearbyint(value.toDouble() * 1000) / 1000); key.append(rounded); }
        key.append(part.value("mirror").toBool()); const auto encoded = QJsonDocument(key).toJson(QJsonDocument::Compact);
        if (seen.contains(encoded)) { const int first = seen[encoded]; result.append(issue("error", "duplicate", QStringLiteral("重复摆放：%1").arg(part.value("name").toString()), QStringLiteral("和“%1”是同一个零件、摆在同一个位置，完全重在一起：删掉多的那个").arg(parts[first].toObject().value("name").toString()), ids({first, index}))); }
        else seen[encoded] = index;
    }
    return result;
}
QJsonArray bill_gaps(const QJsonArray& rows) {
    QJsonArray result;
    for (const auto& kind : QStringList{"purchase", "standard"}) {
        QVector<int> indices; QStringList names;
        for (const auto& value : rows) { const auto row = value.toObject(); if (row.value("kind").toString() != kind || (kind == "purchase" ? row.value("unit").toDouble() != 0 : !row.value("spec").toString().isEmpty())) continue; const auto source = row.value("indices").toArray(); if (source.isEmpty()) throw DomainError(QStringLiteral("BOM 行缺少 indices")); indices.append(source.first().toInt()); if (names.size() < 8) names.append(row.value("name").toString()); }
        if (indices.isEmpty()) continue;
        result.append(issue(kind == "purchase" ? "warning" : "info", kind == "purchase" ? "no_price" : "no_spec", QStringLiteral("%1 种%2").arg(indices.size()).arg(kind == "purchase" ? QStringLiteral("外购件没报价") : QStringLiteral("标准件没写规格")), names.join(QStringLiteral("、")) + (kind == "purchase" ? QStringLiteral("：打开零件给“外购”工艺填上报价，成本才算得准") : QStringLiteral("：写上规格（比如 M6×20 GB/T 5783），采购照着买")), ids(indices)));
    }
    return result;
}
QJsonArray mass_issues(const QJsonArray& properties, const QStringList& materials, const QStringList& names, const QJsonArray& size) {
    const auto propertiesResult = mass_properties(properties, materials); if (propertiesResult.value("grams").toDouble() <= 0) return {};
    const auto centre = propertiesResult.value("centre").toArray();
    QString detail = QStringLiteral("重心在 X %1　Y %2　Z %3 mm").arg(centre[0].toDouble(), 0, 'f', 0).arg(centre[1].toDouble(), 0, 'f', 0).arg(centre[2].toDouble(), 0, 'f', 0);
    QVector<int> missing; for (const auto& value : propertiesResult.value("missing").toArray()) missing.append(value.toInt());
    if (!missing.isEmpty()) detail += QStringLiteral("；%1 个零件没定材质，没算进去（%2）").arg(missing.size()).arg(joinedNames(names, missing, 4));
    QJsonArray result{issue("info", "mass", QStringLiteral("整套约 %1 kg").arg(propertiesResult.value("kg").toDouble(), 0, 'f', 1), detail, {}, centre)};
    const double width = size.size() > 1 ? size[1].toDouble() : 0, sideways = centre[1].toDouble();
    if (width > 0 && std::abs(sideways) > width * .02) result.append(issue("warning", "off_centre", QStringLiteral("重心偏%1 %2 mm").arg(sideways < 0 ? QStringLiteral("左") : QStringLiteral("右")).arg(std::abs(sideways), 0, 'f', 0), QStringLiteral("超过总宽 %1 mm 的 2%：左右重量不平衡，看看是不是少装了对面的件").arg(width, 0, 'f', 0), {}, centre));
    return result;
}
QJsonArray motion_issues(const QJsonArray& clashes, const QStringList& jointNames, const QStringList& units) {
    QJsonArray result;
    for (const auto& value : clashes) {
        const auto row = value.toObject(); const int joint = row.value("joint").toInt(); const auto names = row.value("names").toArray();
        result.append(issue("error", "motion_clash", QStringLiteral("运动干涉：%1 开到 %2%3").arg(jointNames.value(joint)).arg(row.value("value").toDouble(), 0, 'g', 6).arg(units.value(joint)), QStringLiteral("%1 撞上 %2，压进去 %3 mm：改铰链的位置、开的范围，或者让开").arg(names.size() > 0 ? names[0].toString() : QString(), names.size() > 1 ? names[1].toString() : QString()).arg(row.value("depth").toDouble(), 0, 'g', 2), ids({row.value("a").toInt(), row.value("b").toInt()}), row.value("point").isUndefined() ? QJsonValue(QJsonValue::Null) : row.value("point")));
    }
    return result;
}
QJsonObject issue_summary(const QJsonArray& issues) {
    QJsonObject result{{"error", 0}, {"warning", 0}, {"info", 0}};
    for (const auto& value : issues) { const auto level = value.toObject().value("level").toString(); if (result.contains(level)) result[level] = result.value(level).toInt() + 1; }
    return result;
}
QStringList red_features(const QJsonArray& issues) {
    QStringList result;
    for (const auto& value : issues) { const auto row = value.toObject(); if (row.value("level") != "error" || row.value("code") == "feature_error") continue; for (const auto& feature : row.value("features").toArray()) if (!result.contains(feature.toString())) result.append(feature.toString()); }
    return result;
}
}
