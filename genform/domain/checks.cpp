#include "geometry.hpp"

#include <QRegularExpression>
#include <QSet>
#include <algorithm>
#include <cmath>

namespace genform::domain {
namespace {
QJsonObject lookup(const QJsonArray& features) {
    QJsonObject result; for (const auto& value : features) { const auto feature = value.toObject(); result[feature.value("id").toString()] = feature; } return result;
}
QJsonArray shapesOf(const QJsonObject& feature, const QJsonObject& byId, bool skipConstruction = false) {
    const auto shapes = byId.value(feature.value("params").toObject().value("sketch").toString()).toObject().value("params").toObject().value("shapes").toArray();
    if (!skipConstruction) return shapes;
    QJsonArray result; for (const auto& value : shapes) if (!value.toObject().value("construction").toBool()) result.append(value); return result;
}
int planeAxis(const QJsonObject& feature, const QJsonObject& byId) {
    const auto plane = byId.value(feature.value("params").toObject().value("sketch").toString()).toObject().value("params").toObject().value("plane").toString();
    return QMap<QString, int>{{"XY", 2}, {"XZ", 1}, {"YZ", 0}}.value(plane, -1);
}
std::optional<double> toolExtent(const QJsonObject& tools, const QString& identifier, int axis, const QJsonArray& body = {}) {
    const auto box = tools.value(identifier).toObject().value("box").toArray();
    if (box.size() != 2 || axis < 0 || axis > 2) return {};
    const auto bottom = box[0].toArray(), top = box[1].toArray();
    if (bottom.size() != 3 || top.size() != 3) throw DomainError(QStringLiteral("工具包围盒必须为 2×3 数组"));
    double low = bottom[axis].toDouble(), high = top[axis].toDouble();
    if (body.size() == 2) { low = std::max(low, body[0].toArray()[axis].toDouble()); high = std::min(high, body[1].toArray()[axis].toDouble()); }
    return std::max(high - low, 0.0);
}
QVector<double> boxSizes(const QJsonArray& box) {
    QVector<double> result;
    if (box.size() != 2 || box[0].toArray().size() != 3 || box[1].toArray().size() != 3) return result;
    for (int axis = 0; axis < 3; ++axis) result.append(box[1].toArray()[axis].toDouble() - box[0].toArray()[axis].toDouble());
    std::sort(result.begin(), result.end()); return result;
}
int corners(const QJsonObject& shape) {
    const auto type = shape.value("type").toString();
    if (type == "rect") return shape.value("r").toDouble() > 0 || shape.value("radius").toDouble() > 0 ? 0 : 4;
    if (type == "polygon" || type == "ngon") return shape.value("sides").toInt(int(shape.value("points").toArray().size()));
    return 0;
}
void checkRound(const QString& identifier, const QString& name, double diameter, double depth, QJsonArray& issues) {
    if (diameter <= 0) return;
    if (diameter < 1.2) issues.append(issue("error", "proof_hole", QStringLiteral("孔太小：%1").arg(name), QStringLiteral("Φ%1, 打样孔要 ≥ Φ1.2").arg(diameter, 0, 'f', 2), {identifier}));
    else if (depth > 0 && depth / diameter > 8) issues.append(issue("error", "proof_hole", QStringLiteral("孔太深：%1").arg(name), QStringLiteral("深 %1 / Φ%2 = %3 倍径, 打样最多 8 倍").arg(depth).arg(diameter).arg(depth / diameter), {identifier}));
    else if (depth > 0 && depth / diameter > 5) issues.append(issue("warning", "proof_hole", QStringLiteral("孔偏深：%1").arg(name), QStringLiteral("%1 倍径: 超过 5 倍改用钻头, 精度比铣的低").arg(depth / diameter), {identifier}));
}
void fitCheck(const QString& identifier, const QString& name, const QVector<double>& diameters, QJsonArray& issues) {
    if (!name.contains(QStringLiteral("销")) && !name.contains("H7") && !name.contains(QStringLiteral("精孔"))) return;
    for (const auto diameter : diameters) if (diameter > 0 && std::abs(diameter * 2 - std::nearbyint(diameter * 2)) < 1e-6) {
        issues.append(issue("info", "proof_fit", QStringLiteral("精孔建模放大一点：%1").arg(name), QStringLiteral("打样孔做到 0~+0.02: 销钉孔 Φ%1 建模画成 Φ%2 ~ Φ%3").arg(diameter).arg(diameter + .02).arg(diameter + .03), {identifier})); break;
    }
}
const QMap<QString, double> TapDrills{{"M2", 1.6}, {"M2.5", 2.05}, {"M3", 2.5}, {"M4", 3.3}, {"M5", 4.2}, {"M6", 5}, {"M8", 6.8}, {"M10", 8.5}, {"M12", 10.2}};
bool unresolved(const QJsonValue& value) {
    if (value.isString()) return value.toString().startsWith('=');
    if (value.isArray()) { for (const auto& child : value.toArray()) if (unresolved(child)) return true; }
    if (value.isObject()) { const auto object = value.toObject(); for (auto iterator = object.begin(); iterator != object.end(); ++iterator) if (unresolved(iterator.value())) return true; }
    return false;
}
}

QJsonArray proofing_checks(const QJsonArray& features, const QJsonObject& report, const QString& material, const QJsonObject&) {
    if (!report.value("has_body").toBool()) return {};
    const auto byId = lookup(features); QString main;
    for (const auto& value : features) { const auto feature = value.toObject(); if (!feature.value("suppressed").toBool() && !feature.value("process").toObject().value("id").toString().isEmpty()) { main = feature.value("process").toObject().value("id").toString(); break; } }
    if (main == "standard" || main == "purchase") return {issue("info", "proof_skip", QStringLiteral("标准件 / 外购件：不走打样"), QStringLiteral("按规格直接买"))};
    const auto tools = report.value("tools").toObject(), proof = report.value("proof").toObject(); const auto box = proof.value("box").toArray(); const auto size = boxSizes(box);
    QJsonArray issues;
    if (main == "turning" || main == "millturn") {
        QStringList reasons;
        if (material != QStringLiteral("不锈钢 304")) reasons.append(QStringLiteral("材质 %1 (车铣打样只有 303 / 304 不锈钢)").arg(material.isEmpty() ? QStringLiteral("没指定") : material));
        if (size.size() == 3) { const double diameter = size[1], length = size[2]; if (diameter > 17.9) reasons.append(QStringLiteral("直径 %1 > 17.9").arg(diameter)); else if (length > 3 * diameter) reasons.append(QStringLiteral("长 %1 > 3 倍径 %2").arg(length).arg(3 * diameter)); }
        QStringList cuts;
        for (const auto& value : features) { const auto feature = value.toObject(); const auto type = feature.value("type").toString(); if (!feature.value("suppressed").toBool() && (type == "hole" || feature.value("params").toObject().value("op") == "cut") && type != "revolve" && cuts.size() < 3) cuts.append(feature.value("name").toString(feature.value("id").toString())); }
        if (!cuts.isEmpty()) reasons.append(QStringLiteral("有孔 / 铣的特征 (车铣打样只车外圆): ") + cuts.join(QStringLiteral("、")));
        if (size.isEmpty()) reasons.append(QStringLiteral("缺少零件包围盒，不能验证车铣尺寸"));
        return {issue(reasons.isEmpty() ? "info" : "warning", "proof_lathe", reasons.isEmpty() ? QStringLiteral("车削件符合车铣打样") : QStringLiteral("车削件不在车铣打样范围"), reasons.isEmpty() ? QStringLiteral("外螺纹画大径 (M3 → D2.9)、要画退刀槽和 C 角 (≥ 螺距)") : reasons.join(QStringLiteral("；")) + QStringLiteral("：走普通报价"))};
    }
    if (!QStringList{QStringLiteral("铝合金 6061"), QStringLiteral("铝合金 7075"), QStringLiteral("45# 钢")}.contains(material)) issues.append(issue("error", "proof_material", QStringLiteral("材质不在打样范围：%1").arg(material.isEmpty() ? QStringLiteral("没指定") : material), QStringLiteral("CNC 打样只开放 铝合金 6061、铝合金 7075、45# 钢")));
    if (size.size() == 3) {
        const double minimum[]{1, 10, 10}, maximum[]{30, 440, 650}; const QStringList dimensions{QStringLiteral("厚"), QStringLiteral("宽"), QStringLiteral("长")};
        for (int axis = 0; axis < 3; ++axis) if (size[axis] < minimum[axis] - 1e-6 || size[axis] > maximum[axis] + 1e-6) { issues.append(issue("error", "proof_size", QStringLiteral("外形超出打样范围：%1 %2 mm").arg(dimensions[axis]).arg(size[axis], 0, 'f', 1), QStringLiteral("打样外形 10×10×1 ~ 650×440×30 mm"))); break; }
    } else issues.append(issue("warning", "proof_incomplete", QStringLiteral("缺少打样包围盒"), QStringLiteral("未验证外形尺寸，不能判定打样通过")));
    const auto extent = proof.value("extent").toArray();
    if (extent.size() >= 2 && extent[0].toDouble() > 0 && extent[1].toDouble() > 0) {
        auto cover = [&](const QJsonArray& section) { return section.size() >= 2 ? std::min(section[0].toDouble() / extent[0].toDouble(), section[1].toDouble() / extent[1].toDouble()) : 0.; };
        if (std::max(cover(proof.value("top").toArray()), cover(proof.value("bottom").toArray())) < .98) issues.append(issue("error", "proof_two_sided", QStringLiteral("双面凸台：最大外形不在最高面也不在最低面上"), QStringLiteral("打样要求至少有一面是最大外形；别用薄片凑外形")));
    } else issues.append(issue("warning", "proof_incomplete", QStringLiteral("缺少打样端面截面数据"), QStringLiteral("不能验证双面凸台，需内核提供 extent / top / bottom")));
    for (const auto& value : features) {
        const auto feature = value.toObject(); if (feature.value("suppressed").toBool()) continue;
        const auto params = feature.value("params").toObject(); const auto identifier = feature.value("id").toString(), name = feature.value("name").toString(identifier), type = feature.value("type").toString(), op = params.value("op").toString("add");
        if (unresolved(params)) { issues.append(issue("error", "proof_unresolved", QStringLiteral("参数表达式尚未求值：%1").arg(name), QStringLiteral("调用方必须先解析全局变量"), {identifier})); continue; }
        const auto shapes = shapesOf(feature, byId, true); const int axis = planeAxis(feature, byId);
        if (type == "hole") {
            double diameter = params.value("diameter").toDouble(); if (diameter == 0 && !shapes.isEmpty()) diameter = 2 * shapes.first().toObject().value("r").toDouble();
            const auto kind = params.value("kind").toString(), threadSize = params.value("size").toString();
            if (kind == "tapped" && TapDrills.contains(threadSize)) diameter = TapDrills[threadSize];
            const auto measuredDepth = toolExtent(tools, identifier, axis, box);
            const bool through = params.value("through").toBool(true);
            const double depth = through ? measuredDepth.value_or(0) : params.value("depth").toDouble();
            if (through && !measuredDepth) issues.append(issue("warning", "proof_incomplete", QStringLiteral("缺少贯穿孔深度数据：%1").arg(name), QStringLiteral("不能验证孔深径比，需工具包围盒和草图基准面"), {identifier}));
            checkRound(identifier, name, diameter, depth, issues);
            if (kind == "tapped") {
                if (params.value("thread").toBool()) issues.append(issue("warning", "proof_thread", QStringLiteral("导出前关掉真实牙：%1").arg(name), QStringLiteral("关掉真实螺纹再导出光孔，下单时按 %1 选攻丝").arg(threadSize), {identifier}));
                bool valid = false; const double nominal = threadSize.mid(1).toDouble(&valid);
                if (valid && nominal > 0 && depth > nominal * 5 + 1e-6) issues.append(issue("warning", "proof_thread", QStringLiteral("螺纹太深：%1").arg(name), QStringLiteral("有效螺纹最多 5 倍径"), {identifier}));
            } else if (kind == "simple") fitCheck(identifier, name, {diameter}, issues);
            continue;
        }
        if (type == "chamfer" && params.value("distance").toDouble(params.value("size").toDouble()) > .5) issues.append(issue("warning", "proof_chamfer", QStringLiteral("倒角大于 C0.5：%1").arg(name), QStringLiteral("双面大倒角可能 NG，能不画就不画"), {identifier}));
        if (type == "revolve" && op == "cut") {
            const auto toolBox = tools.value(identifier).toObject().value("box").toArray();
            const auto axisName = params.value("axis").toString("Z").right(1).toUpper(); const int roundAxis = QMap<QString, int>{{"X", 0}, {"Y", 1}, {"Z", 2}}.value(axisName, 2);
            if (toolBox.size() == 2 && box.size() == 2 && toolBox[0].toArray()[roundAxis].toDouble() > box[0].toArray()[roundAxis].toDouble() + .05 && toolBox[1].toArray()[roundAxis].toDouble() < box[1].toArray()[roundAxis].toDouble() - .05) issues.append(issue("error", "proof_groove", QStringLiteral("环槽 / T 槽：%1").arg(name), QStringLiteral("旋转切除两头都没通到端面，打样不支持"), {identifier}));
            continue;
        }
        if (type != "extrude") continue;
        const double depth = std::abs(params.value("distance").toDouble());
        bool hasText = false; double textHeight = 1e9;
        for (const auto& shapeValue : shapes) { const auto shape = shapeValue.toObject(); if (shape.value("type") == "text") { hasText = true; textHeight = std::min(textHeight, shape.value("height").toDouble()); } }
        if (hasText) {
            if (op == "add" && depth < .5) issues.append(issue("warning", "proof_silk", QStringLiteral("丝印 / 薄凸字不是加工特征：%1").arg(name), QStringLiteral("导出 STEP 打样前压掉，丝印另外做"), {identifier}));
            else if (op == "cut" && textHeight < 2) issues.append(issue("warning", "proof_text", QStringLiteral("刻字可能太小：%1").arg(name), QStringLiteral("刻字最小间隙 1.25 mm"), {identifier}));
            continue;
        }
        if (op != "cut") continue;
        QVector<double> diameters, widths; int cornerCount = 0;
        for (const auto& shapeValue : shapes) {
            const auto shape = shapeValue.toObject(); const auto shapeType = shape.value("type").toString();
            if (shapeType == "circle") diameters.append(shape.value("r").toDouble() * 2);
            if (shapeType == "slot" || shapeType == "arcslot") widths.append(shape.value("w").toDouble());
            if (shapeType == "rect") { widths.append(std::min(shape.value("w").toDouble(), shape.value("h").toDouble())); if (shape.value("r").toDouble() == 0) cornerCount += 4; }
            if (shapeType == "polygon") cornerCount += int(shape.value("points").toArray().size());
        }
        if (!diameters.isEmpty() && diameters.size() == shapes.size()) {
            const double measured = toolExtent(tools, identifier, axis, box).value_or(0); checkRound(identifier, name, diameters.first(), measured != 0 ? measured : depth, issues); fitCheck(identifier, name, diameters, issues); continue;
        }
        if (!widths.isEmpty()) {
            const double narrow = *std::min_element(widths.begin(), widths.end());
            if (narrow < 1.25) issues.append(issue("error", "proof_slot", QStringLiteral("槽太窄：%1").arg(name), QStringLiteral("最窄 %1 mm, 内槽要 ≥ 1.25 mm").arg(narrow), {identifier}));
            else if (depth > 5 * std::max(1., narrow - .25) + 1e-6) issues.append(issue("warning", "proof_slot", QStringLiteral("槽太深：%1").arg(name), QStringLiteral("槽深最多刀径的 5 倍"), {identifier}));
        }
        if (cornerCount > 0 && depth > 0) issues.append(issue("info", "proof_corner", QStringLiteral("尖内角会自动加 R：%1").arg(name), QStringLiteral("深 %1 mm → 平台约加 R%2 圆角；需清根请设计避空").arg(depth).arg(std::max(depth / 5, .5)), {identifier}));
    }
    int bad = 0; for (const auto& value : issues) if (value.toObject().value("level") != "info") ++bad;
    issues.append(issue("info", "proof_summary", bad ? QStringLiteral("铨洲 CNC 打样：%1 项要改或补充数据").arg(bad) : QStringLiteral("铨洲 CNC 打样：自动能查的项都过了"), QStringLiteral("侧孔支撑、薄壁和余量等仍需平台仿真；这里只检查输入的几何报告")));
    return issues;
}
QJsonArray design_checks(const QJsonArray& features, const QJsonObject& model, const QJsonObject& report, const QJsonObject& overrides, const QString& material) {
    const auto rules = effective_rules({}, overrides), byId = lookup(features), status = model.value("status").toObject(), tools = report.value("tools").toObject();
    QJsonArray issues, skipped, unbound; QMap<QString, double> costs; double total = 0, tooling = 0;
    auto nameOf = [&](const QString& identifier) { return byId.value(identifier).toObject().value("name").toString(identifier); };
    for (const auto& value : features) {
        const auto feature = value.toObject(); const auto identifier = feature.value("id").toString(), state = status.value(identifier).toString();
        if (state.startsWith("error")) issues.append(issue("error", "feature_error", QStringLiteral("特征出错：%1").arg(feature.value("name").toString()), state.mid(7), {identifier}));
        if (state == "skipped" && skipped.size() < 20) skipped.append(identifier);
    }
    if (!skipped.isEmpty()) issues.append(issue("warning", "feature_error", QStringLiteral("%1 个特征被跳过 (前面有特征出错)").arg(skipped.size()), {}, skipped));
    if (report.value("has_body").toBool()) {
        if (!report.value("valid").toBool(true)) issues.append(issue("error", "invalid_body", QStringLiteral("实体过不了拓扑检查"), QStringLiteral("导出 STEP 可能缺面，请检查最近特征")));
        const auto bodies = report.value("bodies").toArray();
        for (int index = 1; index < bodies.size(); ++index) { const auto body = bodies[index].toObject(); const auto bodyFeatures = body.value("features").toArray(); QStringList names; QJsonArray marked; for (int offset = 0; offset < bodyFeatures.size() && offset < 6; ++offset) { marked.append(bodyFeatures[offset]); if (offset < 4) names.append(nameOf(bodyFeatures[offset].toString())); } issues.append(issue("error", "floating", QStringLiteral("悬空的零件：%1").arg(names.isEmpty() ? QStringLiteral("未知特征") : names.join(QStringLiteral("、"))), QStringLiteral("第 %1 块实体与主体不相连，让相邻件至少压入 %2 mm").arg(index + 1).arg(rules.value("overlap").toDouble()), marked, body.value("center"))); }
        if (report.value("voids").toInt() > 0) issues.append(issue("info", "closed_cavity", QStringLiteral("有 %1 个封闭空腔").arg(report.value("voids").toInt()), QStringLiteral("电泳喷涂防锈需排液排气孔")));
    }
    for (const auto& value : report.value("pairs").toArray()) {
        const auto pair = value.toObject(); const auto kind = pair.value("kind").toString(), first = pair.value("a").toString(), second = pair.value("b").toString();
        const QMap<QString, QString> titles{{"gap", QStringLiteral("间隙太小")}, {"touch", QStringLiteral("只贴着没压进去")}, {"shallow", QStringLiteral("压入太浅")}};
        if (!titles.contains(kind)) continue;
        issues.append(issue("error", kind, QStringLiteral("%1：%2 ↔ %3").arg(titles[kind], nameOf(first), nameOf(second)), QStringLiteral("检查报告值 %1 mm；公差 ±%2、最小间隙 %3、最小压入 %4 mm").arg(pair.value("value").toDouble()).arg(rules.value("tolerance").toDouble()).arg(rules.value("clearance").toDouble()).arg(rules.value("overlap").toDouble()), {first, second}, pair.value("point").isUndefined() ? QJsonValue(QJsonValue::Null) : pair.value("point")));
    }
    if (report.contains("pairs") && report.contains("pairs_checked")) issues.append(issue("info", "pairs", QStringLiteral("比较了 %1 对离得近的件").arg(report.value("pairs_checked").toInt())));
    if (material.isEmpty()) issues.append(issue("warning", "no_material", QStringLiteral("没指定材质"), QStringLiteral("算不了重量，工艺默认按普通碳钢估价")));
    bool hollow = false; for (const auto& value : features) { const auto feature = value.toObject(); if (!feature.value("suppressed").toBool() && (feature.value("type") == "shell" || feature.value("params").toObject().value("op") == "void")) hollow = true; }
    QJsonObject catalog; for (const auto& value : process_catalog()) { const auto process = value.toObject(); catalog[process.value("id").toString()] = process; }
    for (const auto& value : features) {
        const auto feature = value.toObject(); const auto identifier = feature.value("id").toString(), type = feature.value("type").toString(), name = feature.value("name").toString(identifier);
        if (feature.value("suppressed").toBool() || !solid_kinds().contains(type) || !status.value(identifier).toString().startsWith("ok")) continue;
        const auto params = feature.value("params").toObject();
        if (unresolved(params)) { issues.append(issue("error", "feature_error", QStringLiteral("参数表达式尚未求值：%1").arg(name), QStringLiteral("调用方必须先解析全局变量"), {identifier})); continue; }
        const auto metrics = tools.value(identifier).toObject(), process = feature.value("process").toObject(); const auto classified = shape_kind(feature, metrics, byId, hollow); if (classified.first.isEmpty()) continue;
        const auto processId = process.value("id").toString();
        if (process.isEmpty()) { if (unbound.size() < 30) unbound.append(identifier); }
        else if (processId.isEmpty()) issues.append(issue("error", "process_none", QStringLiteral("没有能做它的工艺：%1").arg(name), process.value("why").toString(), {identifier}));
        else {
            if (catalog.contains(processId) && tools.contains(identifier) && classified.first == process.value("kind").toString(classified.first)) {
                const auto ranked = rank_processes(feature, metrics, byId, 1, material, hollow);
                for (const auto& refusedValue : ranked.value("refused").toArray()) { const auto refused = refusedValue.toObject(); if (refused.value("process").toObject().value("id").toString() == processId) issues.append(issue("error", "process_infeasible", QStringLiteral("%1做不了：%2").arg(catalog.value(processId).toObject().value("name").toString(), name), refused.value("reason").toString() + QStringLiteral("：重新绑定工艺，或者改设计"), {identifier})); }
            }
            const double cost = process.value("cost").toDouble(); total += cost; costs[process.value("name").toString("?")] += cost;
            if (!type.startsWith("pattern") && !type.startsWith("mirror")) tooling += process.value("tooling").toDouble();
        }
        const auto kind = classified.first;
        if (!metrics.isEmpty() && QStringList{"plate", "partition", "prism", "freeform", "freeform_small", "revolved"}.contains(kind)) {
            const auto size = metrics.value("size").toArray(); const double thickness = metrics.value("thickness").toDouble(); const double wall = std::min(thickness != 0 ? thickness : 1e9, size.isEmpty() ? 1e9 : size.first().toDouble());
            if (wall > 0 && wall < rules.value("min_wall").toDouble()) issues.append(issue("warning", "thin_wall", QStringLiteral("壁太薄：%1").arg(name), QStringLiteral("约 %1 mm，规则 ≥ %2 mm").arg(wall).arg(rules.value("min_wall").toDouble()), {identifier}));
        }
        const auto shapes = shapesOf(feature, byId); int cornerCount = 0;
        if (kind == "hole") {
            const double depth = params.value("distance").toDouble(params.value("depth").toDouble());
            for (const auto& shapeValue : shapes) {
                const auto shape = shapeValue.toObject(); if (shape.value("type") != "circle" || shape.value("construction").toBool()) continue;
                const double diameter = shape.value("r").toDouble() * 2;
                if (diameter > 0 && diameter < rules.value("min_hole").toDouble()) { issues.append(issue("warning", "small_hole", QStringLiteral("孔太小：%1").arg(name), QStringLiteral("直径 %1 mm，规则 ≥ %2 mm").arg(diameter).arg(rules.value("min_hole").toDouble()), {identifier})); break; }
                if (diameter > 0 && depth / diameter > rules.value("hole_ratio").toDouble()) { issues.append(issue("warning", "deep_hole", QStringLiteral("孔太深：%1").arg(name), QStringLiteral("深径比 %1，规则 ≤ %2").arg(depth / diameter).arg(rules.value("hole_ratio").toDouble()), {identifier})); break; }
            }
        }
        bool smallText = false;
        for (const auto& shapeValue : shapes) { const auto shape = shapeValue.toObject(); if (!shape.value("construction").toBool()) cornerCount += corners(shape); if (shape.value("type") == "text" && shape.value("height").toDouble() < rules.value("min_text").toDouble()) smallText = true; }
        if (QStringList{"cnc3", "cnc5", "millturn"}.contains(processId) && QStringList{"cut", "pocket"}.contains(params.value("op").toString()) && rules.value("corner_radius").toDouble() > 0 && cornerCount > 0) issues.append(issue("warning", "sharp_corner", QStringLiteral("铣不出的尖内角：%1").arg(name), QStringLiteral("%1 个尖角，内角需 R ≥ %2 mm，或改线切割 / 激光").arg(cornerCount).arg(rules.value("corner_radius").toDouble()), {identifier}));
        if (smallText) issues.append(issue("warning", "small_text", QStringLiteral("字太小：%1").arg(name), QStringLiteral("字高低于 %1 mm").arg(rules.value("min_text").toDouble()), {identifier}));
    }
    if (!unbound.isEmpty()) issues.append(issue("warning", "no_process", QStringLiteral("%1 个特征还没绑加工工艺").arg(unbound.size()), QStringLiteral("评估 → 绑定工艺"), unbound));
    if (rules.value("proofing").toInt() != 0) for (const auto& value : proofing_checks(features, report, material, rules)) issues.append(value);
    if (total != 0) {
        QVector<std::pair<QString, double>> ordered; for (auto iterator = costs.begin(); iterator != costs.end(); ++iterator) ordered.append({iterator.key(), iterator.value()}); std::stable_sort(ordered.begin(), ordered.end(), [](const auto& first, const auto& second) { return first.second > second.second; });
        QStringList details; for (int index = 0; index < ordered.size() && index < 5; ++index) details.append(QStringLiteral("%1 ¥%2").arg(ordered[index].first).arg(ordered[index].second, 0, 'f', 2));
        issues.append(issue("info", "cost", QStringLiteral("估算成本：每件约 ¥%1 (模具 / 工装合计 ¥%2)").arg(total, 0, 'f', 2).arg(tooling, 0, 'f', 2), QStringLiteral("大头：") + details.join(QStringLiteral("，"))));
    }
    QVector<QJsonObject> ordered; for (const auto& value : issues) ordered.append(value.toObject());
    const QMap<QString, int> levels{{"error", 0}, {"warning", 1}, {"info", 2}};
    std::stable_sort(ordered.begin(), ordered.end(), [&](const auto& first, const auto& second) { return levels.value(first.value("level").toString()) < levels.value(second.value("level").toString()); });
    QJsonArray result; for (const auto& value : ordered) result.append(value); return result;
}
}
