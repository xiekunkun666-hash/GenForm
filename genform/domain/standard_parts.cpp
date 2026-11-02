#include "geometry.hpp"

#include <QJsonDocument>
#include <algorithm>
#include <cmath>
#include <numbers>

namespace genform::domain {
namespace {
const QJsonObject& data() {
    static const auto result = QJsonDocument::fromJson(R"json({
"bearings":[
 ["6700 薄壁",[["6700",10,15,4],["6701",12,18,4],["6702",15,21,4],["6703",17,23,4],["6704",20,27,4],["6705",25,32,4],["6706",30,37,4],["6707",35,44,5],["6708",40,50,6],["6709",45,55,6],["6710",50,62,6]]],
 ["6800 / 61800",[["6800",10,19,5],["6801",12,21,5],["6802",15,24,5],["6803",17,26,5],["6804",20,32,7],["6805",25,37,7],["6806",30,42,7],["6807",35,47,7],["6808",40,52,7],["6809",45,58,7],["6810",50,65,7],["61811",55,72,9],["61812",60,78,10]]],
 ["6900",[["6900",10,22,6],["6901",12,24,6],["6902",15,28,7],["6903",17,30,7],["6904",20,37,9],["6905",25,42,9],["6906",30,47,9],["6907",35,55,10],["6908",40,62,12],["6909",45,68,12],["6910",50,72,12]]],
 ["6000",[["6000",10,26,8],["6001",12,28,8],["6002",15,32,9],["6003",17,35,10],["6004",20,42,12],["6005",25,47,12],["6006",30,55,13],["6007",35,62,14],["6008",40,68,15],["6009",45,75,16],["6010",50,80,16]]],
 ["6200",[["6200",10,30,9],["6201",12,32,10],["6202",15,35,11],["6203",17,40,12],["6204",20,47,14],["6205",25,52,15],["6206",30,62,16],["6207",35,72,17],["6208",40,80,18]]],
 ["微型 68x / 69x",[["683",3,7,3],["684",4,9,4],["685",5,11,5],["686",6,13,5],["687",7,14,5],["688",8,16,5],["689",9,17,5],["693",3,8,4],["694",4,11,4],["695",5,13,4],["696",6,15,5],["697",7,17,5],["698",8,19,6],["699",9,20,6]]],
 ["微型 62x",[["623",3,10,4],["624",4,13,5],["625",5,16,5],["626",6,19,6],["627",7,22,7],["628",8,24,8],["629",9,26,8]]],
 ["微型 MR",[["MR52",2,5,2.5],["MR63",3,6,2.5],["MR74",4,7,2.5],["MR85",5,8,2.5],["MR95",5,9,3],["MR105",5,10,4],["MR106",6,10,3],["MR115",5,11,4],["MR117",7,11,3],["MR126",6,12,4],["MR128",8,12,3.5],["MR137",7,13,4],["MR148",8,14,4]]]
],
"needle":[["HK0306",3,6.5,6],["HK0408",4,8,8],["HK0509",5,9,9],["HK0606",6,10,6],["HK0608",6,10,8],["HK0609",6,10,9],["HK0612",6,10,12],["HK0810",8,12,10],["HK0812",8,12,12],["HK1010",10,14,10],["HK1012",10,14,12],["HK1210",12,18,10],["HK1212",12,18,12],["HK1512",15,21,12],["HK1612",16,22,12],["HK2010",20,26,10],["HK2012",20,26,12]],
"dowel":[[1,3,4,5,6,8,10],[1.5,4,5,6,8,10,12,16],[2,4,5,6,8,10,12,16,20],[2.5,6,8,10,12,16,20,24],[3,6,8,10,12,16,20,24,30],[4,8,10,12,16,20,24,30,40],[5,10,12,16,20,24,30,40,50],[6,12,16,20,24,30,40,50,60],[8,16,20,24,30,40,50,60,80],[10,20,24,30,40,50,60,80,100]],
"shaft_clip":[[3,2.8,0.4,0.8],[4,3.8,0.4,0.9],[5,4.8,0.6,1.1],[6,5.7,0.7,1.3],[8,7.6,0.8,1.5],[10,9.6,1,1.8],[12,11.5,1,1.9],[15,14.3,1,2.2],[17,16.2,1,2.3],[20,19,1.2,2.6],[25,23.9,1.2,3],[30,28.6,1.5,3.5],[35,33,1.5,3.9],[40,37.5,1.75,4.3],[45,42.5,1.75,4.6],[50,47,2,5]],
"hole_clip":[[8,8.4,0.8,1.3],[10,10.4,1,1.5],[12,12.5,1,1.7],[15,15.7,1,2],[16,16.8,1,2],[19,20,1,2.2],[22,23,1,2.5],[24,25.2,1.2,2.6],[26,27.2,1.2,2.7],[28,29.4,1.2,2.9],[30,31.4,1.2,3],[32,33.7,1.2,3.2],[35,37,1.5,3.4],[37,39,1.5,3.6],[40,42.5,1.75,3.9],[42,44.5,1.75,4.1],[47,49.5,1.75,4.4],[52,55,2,4.7],[55,58,2,5],[58,61,2,5],[62,65,2,5.2]],
"ball":[1,1.5,2,2.5,3,3.175,3.5,4,4.5,5,6,6.35,7,8,10],
"nut":[["M2",4,1.6],["M2.5",5,2],["M3",5.5,2.4],["M4",7,3.2],["M5",8,4.7],["M6",10,5.2],["M8",13,6.8],["M10",16,8.4],["M12",18,10.8]],
"washer":[["M2",2.2,5,0.3],["M2.5",2.7,6,0.5],["M3",3.2,7,0.5],["M4",4.3,9,0.8],["M5",5.3,10,1],["M6",6.4,12,1.6],["M8",8.4,16,1.6],["M10",10.5,20,2],["M12",13,24,2.5]],
"standoff":[["M2",4],["M2.5",5],["M3",5],["M4",7]],
"standoff_lengths":[3,4,5,6,8,10,12,15,20,25,30],
"screw_heads":[["cap","内六角圆柱头","GB/T 70.1"],["button","内六角圆头 (盘头)","ISO 7380"],["flat","内六角沉头","GB/T 70.3"]],
"screw_sizes":["M2","M2.5","M3","M4","M5","M6","M8"],
"screw_lengths":[3,4,5,6,8,10,12,14,16,18,20,25,30,35,40]
})json").object();
    if (result.isEmpty()) throw DomainError(QStringLiteral("标准件内置数据无法解析"));
    return result;
}
QString numeric(double value) { return QString::number(value, 'g', 12); }
QString identifier(const QJsonValue& value) { return value.isString() ? value.toString() : numeric(value.toDouble()); }
QJsonArray rowFor(const QString& kind, const QString& size) {
    for (const auto& value : data().value(kind).toArray()) { const auto row = value.toArray(); if (!row.isEmpty() && identifier(row.first()) == size) return row; }
    throw DomainError(QStringLiteral("没有这个标准件规格: %1 / %2").arg(kind, size));
}
QJsonObject sketch(const QString& id, const QString& name, const QJsonArray& shapes, const QString& plane = "XY", double offset = 0) {
    return {{"id", id}, {"type", "sketch"}, {"name", name}, {"suppressed", false}, {"params", QJsonObject{{"plane", plane}, {"offset", offset}, {"shapes", shapes}}}};
}
QJsonObject extrude(const QString& id, const QString& name, const QString& sketch, double distance, const QString& op = "add") {
    return {{"id", id}, {"type", "extrude"}, {"name", name}, {"suppressed", false}, {"params", QJsonObject{{"sketch", sketch}, {"distance", distance}, {"op", op}, {"symmetric", false}, {"end", "blind"}, {"reverse", false}, {"distance2", 0.}, {"gap", 0.}, {"target", QJsonArray()}}}};
}
QJsonObject revolve(const QString& id, const QString& name, const QString& sketch) {
    return {{"id", id}, {"type", "revolve"}, {"name", name}, {"suppressed", false}, {"params", QJsonObject{{"sketch", sketch}, {"axis", "Z"}, {"angle", 360.}, {"reverse", false}, {"symmetric", false}, {"op", "add"}}}};
}
double rounded4(double value) { return std::nearbyint(value * 10000) / 10000; }
QJsonObject rect(double x0, double x1, double y0, double y1) { return {{"type", "rect"}, {"cx", rounded4((x0 + x1) / 2)}, {"cy", rounded4((y0 + y1) / 2)}, {"w", rounded4(x1 - x0)}, {"h", rounded4(y1 - y0)}}; }
QJsonObject circle(double radius) { return {{"type", "circle"}, {"cx", 0.}, {"cy", 0.}, {"r", radius}}; }
QJsonObject hexagon(double across) {
    const double radius = across / std::sqrt(3.); QJsonArray points;
    for (int index = 0; index < 6; ++index) { const double angle = (30 + 60 * index) * std::numbers::pi / 180; points.append(QJsonArray{rounded4(radius * std::cos(angle)), rounded4(radius * std::sin(angle))}); }
    return {{"type", "polygon"}, {"points", points}};
}
QJsonObject tapped(const QString& size) {
    return {{"id", "f4"}, {"type", "hole"}, {"name", size + QStringLiteral(" 螺纹 (真实牙)")}, {"suppressed", false}, {"params", QJsonObject{{"sketch", "f3"}, {"kind", "tapped"}, {"size", size}, {"diameter", 2.5}, {"through", true}, {"depth", 10.}, {"head_diameter", 6.}, {"head_depth", 1.}, {"flip", false}, {"thread", true}, {"phase", 0.}}}};
}
QJsonObject document(QJsonArray features, const QString& spec, const QString& material = QStringLiteral("合金钢"), const QString& name = {}) {
    for (int index = 0; index < features.size(); ++index) {
        auto feature = features[index].toObject();
        if (QStringList{"extrude", "revolve", "screw"}.contains(feature.value("type").toString())) {
            feature["process"] = QJsonObject{{"id", "standard"}, {"name", QStringLiteral("标准件 (按规格网购)")}, {"short", QStringLiteral("标准")}, {"color", "#3FB97F"}, {"standard", true}, {"spec", spec}, {"why", spec + QStringLiteral("。标准件库生成")}};
            features[index] = feature; break;
        }
    }
    int serial = 0; for (const auto& value : features) serial = std::max(serial, value.toObject().value("id").toString().mid(1).toInt());
    return {{"format", "genform-document"}, {"version", 1}, {"serial", serial}, {"upto", QJsonValue::Null}, {"props", QJsonObject{{"material", material}, {"standard", QJsonObject{{"spec", spec}, {"name", name}}}}}, {"features", features}};
}
QJsonObject series(const QString& id, const QString& title, const QJsonArray& sizes) { return {{"id", id}, {"title", title}, {"sizes", sizes}}; }
}
QJsonArray screw_lengths(const QString& size) {
    bool valid = false; const double diameter = size.mid(1).toDouble(&valid);
    if (!size.startsWith('M') || !valid || diameter <= 0) throw DomainError(QStringLiteral("无效螺纹规格: %1").arg(size));
    QJsonArray result; for (const auto& length : data().value("screw_lengths").toArray()) if (length.toDouble() >= diameter && length.toDouble() <= 12 * diameter) result.append(length);
    return result;
}
QJsonArray standard_part_catalog() {
    QJsonArray result, bearingSeries;
    for (const auto& value : data().value("bearings").toArray()) {
        const auto row = value.toArray(); QJsonArray sizes;
        for (const auto& dimensions : row[1].toArray()) { const auto item = dimensions.toArray(); sizes.append(QJsonObject{{"id", item[0]}, {"title", QStringLiteral("%1　%2×%3×%4").arg(item[0].toString(), numeric(item[1].toDouble()), numeric(item[2].toDouble()), numeric(item[3].toDouble()))}}); }
        bearingSeries.append(series(row[0].toString(), row[0].toString(), sizes));
    }
    result.append(QJsonObject{{"id", "bearing"}, {"title", QStringLiteral("深沟球轴承")}, {"lengths", QJsonValue::Null}, {"series", bearingSeries}});
    const QVector<std::pair<QString, QString>> titles{{"needle", QStringLiteral("滚针轴承 HK (冲压外圈)")}, {"dowel", QStringLiteral("圆柱销 GB/T 119.2")}, {"screw", QStringLiteral("内六角螺丝")}, {"nut", QStringLiteral("六角螺母 GB/T 6170")}, {"washer", QStringLiteral("平垫圈 GB/T 97.1")}, {"standoff", QStringLiteral("六角铜柱 (双通)")}, {"shaft_clip", QStringLiteral("轴用挡圈 GB/T 894")}, {"hole_clip", QStringLiteral("孔用挡圈 GB/T 893")}, {"ball", QStringLiteral("钢球 GB/T 308")}};
    for (const auto& entry : titles) {
        const auto kind = entry.first; QJsonArray sizes, groups; QJsonValue lengths(QJsonValue::Null);
        if (kind == "screw") {
            QJsonObject choices;
            for (const auto& value : data().value("screw_sizes").toArray()) { sizes.append(QJsonObject{{"id", value}, {"title", value}}); choices[value.toString()] = screw_lengths(value.toString()); }
            for (const auto& value : data().value("screw_heads").toArray()) { const auto row = value.toArray(); groups.append(series(row[0].toString(), row[1].toString() + ' ' + row[2].toString(), sizes)); }
            lengths = choices;
        } else {
            QJsonObject choices;
            for (const auto& value : data().value(kind).toArray()) {
                const auto row = value.isArray() ? value.toArray() : QJsonArray{value}; const auto id = identifier(row[0]); QString title = id;
                if (kind == "needle") title += QStringLiteral("　%1×%2×%3").arg(numeric(row[1].toDouble()), numeric(row[2].toDouble()), numeric(row[3].toDouble()));
                if (kind == "dowel" || kind == "ball") title = QStringLiteral("Ø") + id;
                if (kind == "nut") title += QStringLiteral("　对边 %1 厚 %2").arg(numeric(row[1].toDouble()), numeric(row[2].toDouble()));
                if (kind == "washer") title += QStringLiteral("　%1×%2×%3").arg(numeric(row[1].toDouble()), numeric(row[2].toDouble()), numeric(row[3].toDouble()));
                if (kind == "standoff") title += QStringLiteral("　对边 %1").arg(numeric(row[1].toDouble()));
                if (kind == "shaft_clip" || kind == "hole_clip") title = QStringLiteral("%1 Ø%2　厚 %3").arg(kind == "shaft_clip" ? QStringLiteral("轴") : QStringLiteral("孔"), id, numeric(row[2].toDouble()));
                sizes.append(QJsonObject{{"id", id}, {"title", title}});
                if (kind == "dowel") { auto options = row; options.removeAt(0); choices[id] = options; }
                if (kind == "standoff") choices[id] = data().value("standoff_lengths");
            }
            if (kind == "dowel" || kind == "standoff") lengths = choices;
            const QMap<QString, QString> ids{{"needle", "HK"}, {"standoff", "ff"}, {"shaft_clip", "shaft"}, {"hole_clip", "hole"}};
            const QMap<QString, QString> labels{{"needle", "HK"}, {"dowel", QStringLiteral("淬硬 m6")}, {"nut", QStringLiteral("1 型")}, {"washer", QStringLiteral("A 级")}, {"standoff", "F-F"}, {"shaft_clip", QStringLiteral("A 型")}, {"hole_clip", QStringLiteral("A 型")}, {"ball", "G10"}};
            groups.append(series(ids.value(kind, kind), labels.value(kind), sizes));
        }
        result.append(QJsonObject{{"id", kind}, {"title", entry.second}, {"lengths", lengths}, {"series", groups}});
    }
    return result;
}
std::pair<QString, QJsonObject> make_standard_part(const QString& kind, const QString& size, std::optional<double> length, const QString& series) {
    if (length && (!std::isfinite(*length) || *length <= 0)) throw DomainError(QStringLiteral("标准件长度必须是正有限数"));
    if (kind == "bearing") {
        QJsonArray row;
        for (const auto& value : data().value("bearings").toArray()) for (const auto& item : value.toArray()[1].toArray()) if (item.toArray()[0].toString() == size) row = item.toArray();
        if (row.isEmpty()) throw DomainError(QStringLiteral("没有这个轴承: %1").arg(size));
        const double inner = row[1].toDouble() / 2, outer = row[2].toDouble() / 2, width = row[3].toDouble(), ring = std::max(.3 * (outer - inner), .4), slit = std::min(.15, .05 * (outer - inner)), deep = std::min(.3, .06 * width);
        QJsonArray grooves;
        for (const double radius : {inner + ring, outer - ring}) for (const double z : {0., width - deep}) grooves.append(rect(radius - slit / 2, radius + slit / 2, z, z + deep));
        const auto spec = QStringLiteral("%1-2RS %2×%3×%4").arg(size, numeric(inner * 2), numeric(outer * 2), numeric(width));
        auto cut = revolve("f4", QStringLiteral("内外圈和密封圈的分界缝"), "f3"); auto params = cut.value("params").toObject(); params["op"] = "cut"; cut["params"] = params;
        return {"std_" + size + ".gform", document({sketch("f1", QStringLiteral("截面"), {rect(inner, outer, 0, width)}, "XZ"), revolve("f2", spec, "f1"), sketch("f3", QStringLiteral("分界缝"), grooves, "XZ"), cut}, spec, QStringLiteral("合金钢"), size)};
    }
    if (kind == "needle") {
        const auto row = rowFor(kind, size); const double inner = row[1].toDouble(), outer = row[2].toDouble(), width = row[3].toDouble(), shell = (outer - inner) / 2;
        const QJsonArray shapes{rect(outer / 2 - shell * .25, outer / 2, 0, width), rect(inner / 2, outer / 2 - shell * .25, width * .1, width * .9), rect(inner / 2 + shell * .2, outer / 2, 0, width * .1), rect(inner / 2 + shell * .2, outer / 2, width * .9, width)};
        const auto spec = QStringLiteral("%1 冲压外圈滚针轴承 %2×%3×%4").arg(size, numeric(inner), numeric(outer), numeric(width));
        return {"std_" + size + ".gform", document({sketch("f1", QStringLiteral("截面"), shapes, "XZ"), revolve("f2", spec, "f1")}, spec, QStringLiteral("合金钢"), size)};
    }
    if (kind == "dowel") {
        const auto row = rowFor(kind, size); const double diameter = row[0].toDouble(), span = length.value_or(row[3].toDouble()), bevel = std::min(.1 * diameter, .3);
        const auto spec = QStringLiteral("GB/T 119.2 圆柱销 Ø%1×%2 m6 淬硬").arg(numeric(diameter), numeric(span));
        const QJsonObject shape{{"type", "polygon"}, {"points", QJsonArray{QJsonArray{0, 0}, QJsonArray{diameter / 2 - bevel, 0}, QJsonArray{diameter / 2, bevel}, QJsonArray{diameter / 2, span - bevel}, QJsonArray{diameter / 2 - bevel, span}, QJsonArray{0, span}}}};
        return {QStringLiteral("std_dowel_%1x%2.gform").arg(numeric(diameter), numeric(span)), document({sketch("f1", QStringLiteral("截面"), {shape}, "XZ"), revolve("f2", spec, "f1")}, spec)};
    }
    if (kind == "screw") {
        if (!data().value("screw_sizes").toArray().contains(size)) throw DomainError(QStringLiteral("没有这个螺丝规格: %1").arg(size));
        const auto head = series.isEmpty() ? QString("cap") : series; QJsonArray headRow;
        for (const auto& value : data().value("screw_heads").toArray()) if (value.toArray()[0].toString() == head) headRow = value.toArray();
        if (headRow.isEmpty()) throw DomainError(QStringLiteral("没有这个螺丝头型: %1").arg(head));
        const double span = length.value_or(10); const auto spec = QStringLiteral("%1 %2×%3 %4").arg(headRow[2].toString(), size, numeric(span), headRow[1].toString());
        const QJsonObject screw{{"id", "f2"}, {"type", "screw"}, {"name", QStringLiteral("%1×%2 %3 (真实牙)").arg(size, numeric(span), headRow[1].toString())}, {"suppressed", false}, {"params", QJsonObject{{"sketch", "f1"}, {"size", size}, {"head", head}, {"length", span}, {"flip", false}, {"thread", true}, {"phase", 0.}}}};
        return {QStringLiteral("std_screw_%1x%2_%3.gform").arg(size, numeric(span), head), document({sketch("f1", QStringLiteral("位置"), {QJsonObject{{"type", "point"}, {"x", 0}, {"y", 0}}}), screw}, spec)};
    }
    if (kind == "nut" || kind == "standoff") {
        const auto row = rowFor(kind, size); const double across = row[1].toDouble(), span = kind == "nut" ? row[2].toDouble() : length.value_or(6);
        const auto spec = kind == "nut" ? QStringLiteral("GB/T 6170 %1 六角螺母").arg(size) : QStringLiteral("%1×%2 双通六角铜柱 (F-F) 对边 %3").arg(size, numeric(span), numeric(across));
        auto hole = tapped(size); if (kind == "standoff") hole["name"] = size + QStringLiteral(" 通孔螺纹 (真实牙)");
        const auto doc = document({sketch("f1", QStringLiteral("六角"), {hexagon(across)}), extrude("f2", spec, "f1", span), sketch("f3", QStringLiteral("螺纹孔"), {QJsonObject{{"type", "point"}, {"x", 0}, {"y", 0}}}, "XY", span), hole}, spec, kind == "nut" ? QStringLiteral("合金钢") : QStringLiteral("黄铜"));
        return {kind == "nut" ? QStringLiteral("std_nut_%1.gform").arg(size) : QStringLiteral("std_standoff_%1x%2.gform").arg(size, numeric(span)), doc};
    }
    if (kind == "washer") {
        const auto row = rowFor(kind, size); const double inner = row[1].toDouble(), outer = row[2].toDouble(), thickness = row[3].toDouble();
        const auto spec = QStringLiteral("GB/T 97.1 %1 平垫圈 %2×%3×%4").arg(size, numeric(inner), numeric(outer), numeric(thickness));
        return {QStringLiteral("std_washer_%1.gform").arg(size), document({sketch("f1", QStringLiteral("垫圈"), {circle(outer / 2), circle(inner / 2)}), extrude("f2", spec, "f1", thickness)}, spec)};
    }
    if (kind == "shaft_clip" || kind == "hole_clip") {
        const auto row = rowFor(kind, size); const double diameter = row[0].toDouble(), groove = row[1].toDouble(), thickness = row[2].toDouble(), band = row[3].toDouble();
        const double inner = kind == "shaft_clip" ? groove / 2 : groove / 2 - band, outer = kind == "shaft_clip" ? groove / 2 + band : groove / 2, gap = std::max(band * .8, .6);
        const auto spec = QStringLiteral("%1挡圈 %2 (厚 %3)").arg(kind == "shaft_clip" ? QStringLiteral("GB/T 894 轴用") : QStringLiteral("GB/T 893 孔用"), numeric(diameter), numeric(thickness));
        return {QStringLiteral("std_%1_%2.gform").arg(kind, numeric(diameter)), document({sketch("f1", QStringLiteral("挡圈"), {circle(outer), circle(inner)}), extrude("f2", spec, "f1", thickness), sketch("f3", QStringLiteral("开口"), {rect(-gap / 2, gap / 2, inner - .5, outer + .5)}), extrude("f4", QStringLiteral("开口"), "f3", thickness, "cut")}, spec, QStringLiteral("弹簧钢"))};
    }
    if (kind == "ball") {
        bool valid = false; const double diameter = size.toDouble(&valid); if (!valid || !data().value("ball").toArray().contains(diameter)) throw DomainError(QStringLiteral("没有这个钢球规格: %1").arg(size));
        const auto spec = QStringLiteral("GB/T 308 钢球 Ø%1 G10").arg(numeric(diameter));
        const QJsonArray shapes{QJsonObject{{"type", "arc"}, {"cx", 0}, {"cy", diameter / 2}, {"r", diameter / 2}, {"a0", -90.}, {"a1", 90.}}, QJsonObject{{"type", "line"}, {"x1", 0}, {"y1", diameter}, {"x2", 0}, {"y2", 0}}};
        return {QStringLiteral("std_ball_%1.gform").arg(numeric(diameter)), document({sketch("f1", QStringLiteral("截面"), shapes, "XZ"), revolve("f2", spec, "f1")}, spec)};
    }
    throw DomainError(QStringLiteral("不认识的标准件类别: %1").arg(kind));
}
}
