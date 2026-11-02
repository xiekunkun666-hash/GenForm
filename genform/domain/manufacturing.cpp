#include "geometry.hpp"

#include <QRegularExpression>
#include <QSet>
#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>

namespace genform::domain {
namespace {
struct Stock { QString family; double price; };
const QMap<QString, Stock> Stocks{
    {QStringLiteral("普通碳钢"), {"steel", 7}}, {QStringLiteral("合金钢"), {"steel", 12}},
    {QStringLiteral("不锈钢 304"), {"steel", 22}}, {QStringLiteral("铸铁"), {"iron", 6}},
    {QStringLiteral("铝合金 6061"), {"light", 28}}, {QStringLiteral("铝合金 7075"), {"light", 45}},
    {QStringLiteral("45# 钢"), {"steel", 8}}, {QStringLiteral("黄铜"), {"copper", 55}},
    {QStringLiteral("紫铜"), {"copper", 75}}, {QStringLiteral("钛合金 Ti-6Al-4V"), {"titanium", 380}},
    {"ABS", {"plastic", 22}}, {QStringLiteral("尼龙 PA12"), {"plastic", 60}},
    {QStringLiteral("聚碳酸酯 PC"), {"plastic", 30}}, {"PLA", {"plastic", 25}},
    {QStringLiteral("聚丙烯 PP"), {"plastic", 14}}, {QStringLiteral("PMMA 亚克力"), {"plastic", 35}},
    {QStringLiteral("铸造铝合金 A356"), {"light", 24}}, {QStringLiteral("钢化玻璃"), {"glass", 12}},
    {QStringLiteral("橡胶"), {"rubber", 30}}, {QStringLiteral("皮革 + 海绵"), {"soft", 160}}
};
const QStringList Metals{"steel", "iron", "light", "copper", "titanium"};
const QMap<QString, double> Prices{{"tyre", 1800}, {"fastener", 1.5}, {"bought", 600}, {"standard", 20}};
double roundMoney(double amount) { return std::nearbyint(amount * 100) / 100; }
struct Measure {
    QVector<double> size;
    double length = 0;
    double volume = 0;
    double area = 0;
    double thickness = 0;
    int copies = 1;
    int featuresCount = 1;
    QString materialName;
    Stock stockType;
    double density = 7.85;
    QString hint;
    QJsonObject params;
    QJsonObject faces;
    Measure(const QJsonObject& metrics, const QString& material, const QString& shapeHint = {}, const QJsonObject& parameters = {}, int count = 1)
        : copies(std::max(count, 1)), materialName(material.isEmpty() ? QStringLiteral("普通碳钢") : material), hint(shapeHint), params(parameters), faces(metrics.value("faces").toObject()) {
        for (const auto& value : metrics.value("size").toArray()) size.append(value.toDouble());
        if (size.isEmpty()) size = {0, 0, 0};
        length = *std::max_element(size.begin(), size.end());
        volume = metrics.value("volume").toDouble(); area = metrics.value("area").toDouble(); thickness = metrics.value("thickness").toDouble();
        if (size[0] > 0) thickness = thickness != 0 ? std::min(thickness, size[0]) : size[0];
        stockType = Stocks.value(materialName, {"steel", 7}); density = genform::domain::density(materialName).value_or(7.85);
        if (hint == "skin") { thickness = 2; volume = area * 2; }
    }
    double volumeCm3() const { return volume / 1000; }
    double areaCm2() const { return area / 100; }
    double sheetCm2() const { return area / 200; }
    double bboxCm3() const { return size.size() == 3 ? std::max(size[0] * size[1] * size[2], volume) / 1000 : volumeCm3(); }
    double removedCm3() const { return std::max(bboxCm3() * 1.15 - volumeCm3(), 0.0); }
    double cutLength() const { return 6.4 * std::sqrt(std::max(area / 2, 1.0)); }
    double depth() const { const double value = params.value("distance").toDouble(); return value != 0 ? value : length; }
    double mrr() const { return QMap<QString, double>{{"light", 40}, {"plastic", 60}, {"copper", 25}, {"steel", 12}, {"iron", 15}, {"titanium", 5}}.value(stockType.family, 12); }
    bool flat() const { return faces.value("freeform").toInt() == 0 && faces.value("cylinder").toInt() == 0; }
    double purchasePrice() const { return Prices.value(hint, 50); }
    double material(double waste = 1.2) const { return volumeCm3() * density / 1000 * stockType.price * waste; }
    double stock(double waste = 1) const { return bboxCm3() * 1.15 * density / 1000 * stockType.price * waste; }
};
struct Process {
    QString id;
    QString name;
    QString shortName;
    QString color;
    QString family;
    QString about;
    QStringList kinds;
    QStringList metals;
    double wall;
    double size;
    double tolerance;
    int days;
    std::function<double(const Measure&)> tooling;
    std::function<double(const Measure&)> unit;
    QJsonObject json() const { return {{"id", id}, {"name", name}, {"short", shortName}, {"color", color}, {"family", family}, {"about", about}, {"wall", wall}, {"size", size}, {"tolerance", tolerance}, {"days", days}}; }
};
double hours(double duration, double rate, double setup = 0) { return (duration + setup) * rate; }
const QVector<Process>& processes() {
    static const QVector<Process> result{
        {"laser", QStringLiteral("激光切割"), QStringLiteral("激光"), "#E0605A", QStringLiteral("板材"), QStringLiteral("光纤激光切平板，不用模具"), {"plate", "letters"}, {}, .5, 3000, .1, 3,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return m.material(1.25) + hours(m.cutLength() / (9000 / (1 + m.thickness)) / 60, 300, .08); }},
        {"waterjet", QStringLiteral("水刀切割"), QStringLiteral("水刀"), "#4C94FF", QStringLiteral("板材"), QStringLiteral("高压水加砂切，无热影响"), {"plate", "letters", "glass"}, {}, .5, 3000, .2, 4,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return m.material(1.3) + hours(m.cutLength() / (1500 / (1 + m.thickness / 5)) / 60, 260, .12); }},
        {"plasma", QStringLiteral("等离子切割"), QStringLiteral("等离"), "#B685E0", QStringLiteral("板材"), QStringLiteral("厚钢板粗下料"), {"plate"}, {"steel", "iron"}, 6, 6000, .8, 2,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return m.material(1.3) + hours(m.cutLength() / 3000 / 60, 180, .08); }},
        {"bend", QStringLiteral("激光切割 + 折弯 + 焊接"), QStringLiteral("折弯"), "#E98A3C", QStringLiteral("板材"), QStringLiteral("平板下料折边焊接"), {"plate", "partition"}, Metals, .5, 4000, .3, 5,
         [](const Measure&) { return 500.; }, [](const Measure& m) { return m.material(1.3) + hours(m.cutLength() / 6000 / 60 + .4, 260, .15); }},
        {"punch", QStringLiteral("数控冲床"), QStringLiteral("冲床"), "#D9A441", QStringLiteral("板材"), QStringLiteral("通用模冲孔"), {"plate", "hole_sheet"}, Metals, .5, 2500, .15, 4,
         [](const Measure&) { return 2000.; }, [](const Measure& m) { return m.material(1.2) + 3 + .4 * m.featuresCount; }},
        {"stamping", QStringLiteral("冲压 (开钢模)"), QStringLiteral("冲压"), "#C0392B", QStringLiteral("钣金成形"), QStringLiteral("拉延修边冲孔翻边钢模"), {"skin", "pocket", "plate", "partition"}, Metals, .5, 4500, .3, 120,
         [](const Measure& m) { return 80000 + 22 * m.sheetCm2(); }, [](const Measure& m) { return m.material(1.6) + 1.5 + .004 * m.sheetCm2(); }},
        {"hand_form", QStringLiteral("手工钣金成形 (英式滚轮 + 锤形)"), QStringLiteral("手工"), "#8E9AAF", QStringLiteral("钣金成形"), QStringLiteral("木制型架手工滚压锤打双曲面"), {"skin", "pocket"}, {"steel", "light"}, .6, 6000, 1, 45,
         [](const Measure& m) { return 3000 + .6 * m.sheetCm2(); }, [](const Measure& m) { return m.material(1.5) + hours(m.sheetCm2() / 900, 180, 4); }},
        {"hydroform", QStringLiteral("液压成形 (软模)"), QStringLiteral("液压"), "#35A7A0", QStringLiteral("钣金成形"), QStringLiteral("半钢模和橡胶垫或液压"), {"skin", "pocket", "partition"}, Metals, .5, 3000, .4, 50,
         [](const Measure& m) { return 30000 + 5 * m.sheetCm2(); }, [](const Measure& m) { return m.material(1.5) + 60 + .02 * m.sheetCm2(); }},
        {"composite", QStringLiteral("碳纤维 / 玻纤铺层 (树脂模)"), QStringLiteral("碳纤"), "#3C4148", QStringLiteral("复合材料"), QStringLiteral("铺层真空袋热固化"), {"skin", "pocket", "freeform"}, {}, 1, 6000, .5, 30,
         [](const Measure& m) { return 15000 + 2.5 * m.sheetCm2(); }, [](const Measure& m) { return hours(m.sheetCm2() / 1500, 160, 2) + .25 * m.sheetCm2(); }},
        {"vacuum", QStringLiteral("真空吸塑"), QStringLiteral("吸塑"), "#5FC38A", QStringLiteral("塑料成形"), QStringLiteral("加热塑料板吸附软模"), {"skin", "pocket", "freeform"}, {"plastic"}, 1, 2500, .5, 10,
         [](const Measure& m) { return 3000 + .4 * m.sheetCm2(); }, [](const Measure& m) { return m.material(1.8) + 10 + .01 * m.sheetCm2(); }},
        {"cnc3", QStringLiteral("三轴 CNC 铣"), QStringLiteral("三轴"), "#4C94FF", QStringLiteral("切削"), QStringLiteral("整块料加工平面型腔孔"), {"prism", "profile", "pocket_cut", "hole", "revolved", "letters", "freeform_small"}, {}, .5, 2000, .02, 5,
         [](const Measure&) { return 300.; }, [](const Measure& m) { return m.stock() + hours(m.removedCm3() / (60 * m.mrr()) + m.areaCm2() / 6000, 220, .5); }},
        {"cnc5", QStringLiteral("五轴 CNC 铣"), QStringLiteral("五轴"), "#2E6FD8", QStringLiteral("切削"), QStringLiteral("多方向加工自由曲面"), {"prism", "pocket_cut", "hole", "revolved", "freeform", "freeform_small"}, {}, .5, 1500, .02, 8,
         [](const Measure&) { return 800.; }, [](const Measure& m) { return m.stock() + hours(m.removedCm3() / (60 * m.mrr()) + m.areaCm2() / 2500, 480, 1); }},
        {"turning", QStringLiteral("数控车削"), QStringLiteral("车削"), "#35A7A0", QStringLiteral("切削"), QStringLiteral("回转件车削"), {"revolved"}, {}, .5, 900, .01, 4,
         [](const Measure&) { return 200.; }, [](const Measure& m) { return m.stock(.85) + hours(m.removedCm3() / (60 * m.mrr() * 1.6) + m.areaCm2() / 9000, 150, .3); }},
        {"millturn", QStringLiteral("车铣复合"), QStringLiteral("车铣"), "#6FA8DC", QStringLiteral("切削"), QStringLiteral("回转件一次装夹车铣"), {"revolved"}, {}, .5, 700, .01, 6,
         [](const Measure&) { return 500.; }, [](const Measure& m) { return m.stock(.9) + hours(m.removedCm3() / (60 * m.mrr() * 1.3) + m.areaCm2() / 5000, 320, .5); }},
        {"drill", QStringLiteral("钻孔 / 攻丝"), QStringLiteral("钻孔"), "#9A9EA3", QStringLiteral("切削"), QStringLiteral("钻铰攻丝，按孔估价"), {"hole", "hole_sheet"}, {}, 0, 3000, .02, 1,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return 2 + 3 * m.copies + m.depth() / 30; }},
        {"edm", QStringLiteral("慢走丝线切割"), QStringLiteral("线切"), "#8E97A3", QStringLiteral("切削"), QStringLiteral("金属放电切窄缝尖内角"), {"plate", "pocket_cut", "letters"}, Metals, .1, 600, .005, 6,
         [](const Measure&) { return 300.; }, [](const Measure& m) { return m.material(1.2) + hours(m.cutLength() * std::max(m.thickness, 5.) / 9000, 140, .5); }},
        {"sand_cast", QStringLiteral("砂型铸造 + 机加工"), QStringLiteral("砂铸"), "#A8A39A", QStringLiteral("铸锻"), QStringLiteral("木模或打印砂型，配合面再加工"), {"revolved", "prism", "freeform", "freeform_small"}, {"steel", "iron", "light", "copper"}, 4, 3000, 1, 25,
         [](const Measure& m) { return 6000 + .8 * std::pow(m.bboxCm3(), .66) * 40; }, [](const Measure& m) { return m.material(1.15) * 1.6 + 120 + m.areaCm2() * .03; }},
        {"investment", QStringLiteral("熔模精密铸造"), QStringLiteral("精铸"), "#C9A24A", QStringLiteral("铸锻"), QStringLiteral("蜡模型壳近净成形"), {"freeform_small", "prism", "revolved"}, Metals, 1.5, 600, .2, 30,
         [](const Measure&) { return 6000.; }, [](const Measure& m) { return m.material(1.1) * 3 + 80 + m.volumeCm3() * .3; }},
        {"die_cast", QStringLiteral("高压压铸 (开钢模)"), QStringLiteral("压铸"), "#7F8894", QStringLiteral("铸铁"), QStringLiteral("铝锌镁合金高压钢模成形"), {"prism", "freeform", "freeform_small", "revolved"}, {"light", "copper"}, 1.5, 1500, .1, 90,
         [](const Measure& m) { return 250000 + 8 * std::pow(m.bboxCm3(), .66) * 40; }, [](const Measure& m) { return m.material(1.1) * 1.3 + 8; }},
        {"forging", QStringLiteral("模锻 + 机加工"), QStringLiteral("锻造"), "#5E6268", QStringLiteral("铸锻"), QStringLiteral("加热锻模压形成形"), {"revolved", "prism", "freeform_small"}, {"steel", "light", "titanium"}, 3, 1200, .5, 60,
         [](const Measure&) { return 120000.; }, [](const Measure& m) { return m.material(1.3) * 1.5 + 60 + m.areaCm2() * .05; }},
        {"extrusion", QStringLiteral("型材挤压"), QStringLiteral("挤压"), "#B9C0C8", QStringLiteral("铸锻"), QStringLiteral("铝塑料铜恒截面型材挤压"), {"profile"}, {"light", "plastic", "copper"}, 1, 12000, .2, 20,
         [](const Measure&) { return 10000.; }, [](const Measure& m) { return m.material(1.1) * 1.4 + 10; }},
        {"tube_bend", QStringLiteral("管材弯管"), QStringLiteral("弯管"), "#9DA3A8", QStringLiteral("铸锻"), QStringLiteral("成品管数控弯管"), {"tube"}, Metals, .8, 6000, .5, 7,
         [](const Measure&) { return 1500.; }, [](const Measure& m) { return m.material(1.2) + 30; }},
        {"injection", QStringLiteral("注塑 (开钢模)"), QStringLiteral("注塑"), "#4C94FF", QStringLiteral("塑料成形"), QStringLiteral("塑料钢模注塑"), {"freeform_small", "prism", "revolved", "lens", "letters"}, {"plastic"}, .8, 1200, .05, 45,
         [](const Measure& m) { return 40000 + 3 * std::pow(m.bboxCm3(), .66) * 40; }, [](const Measure& m) { return m.material(1.1) + 2; }},
        {"fdm", QStringLiteral("FDM 熔融挤出打印"), "FDM", "#E2B43C", QStringLiteral("3D 打印"), QStringLiteral("塑料熔融挤出打印"), {"freeform_small", "prism", "revolved", "letters", "lens"}, {"plastic"}, .8, 400, .3, 2,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return 15 + m.volumeCm3() * .4; }},
        {"sls_print", QStringLiteral("尼龙 SLS / MJF 打印"), "SLS", "#E9E4DA", QStringLiteral("3D 打印"), QStringLiteral("尼龙粉末床烧结打印"), {"freeform", "freeform_small", "prism", "revolved", "letters", "lens"}, {"plastic"}, .7, 380, .2, 4,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return 30 + m.volumeCm3() * 1.2; }},
        {"sla", QStringLiteral("SLA 光固化打印"), "SLA", "#C7D7E6", QStringLiteral("3D 打印"), QStringLiteral("光敏树脂精细打印"), {"freeform_small", "prism", "revolved", "letters", "lens"}, {"plastic"}, .5, 600, .1, 3,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return 30 + m.volumeCm3() * 1.8; }},
        {"slm", QStringLiteral("金属 SLM 打印"), "SLM", "#A8A39A", QStringLiteral("3D 打印"), QStringLiteral("金属粉末激光熔化打印"), {"freeform_small", "prism", "revolved"}, {"steel", "light", "titanium"}, .4, 400, .1, 10,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return 300 + m.volumeCm3() * 25; }},
        {"engrave", QStringLiteral("激光雕刻 / 打标"), QStringLiteral("雕刻"), "#C9A227", QStringLiteral("表面"), QStringLiteral("激光刻字打标"), {"engraving"}, {}, 0, 1500, .05, 1,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return 5 + m.areaCm2() * .05; }},
        {"glass", QStringLiteral("钢化 / 热弯玻璃 (外协)"), QStringLiteral("玻璃"), "#2A3A48", QStringLiteral("外协"), QStringLiteral("玻璃切割磨边热弯钢化"), {"glass"}, {}, 3, 3200, .5, 15,
         [](const Measure& m) { return m.flat() ? 0. : 8000.; }, [](const Measure& m) { return 60 + m.sheetCm2() * .06; }},
        {"upholstery", QStringLiteral("软包 (发泡 + 皮革缝制)"), QStringLiteral("软包"), "#7A4A2C", QStringLiteral("外协"), QStringLiteral("发泡块切形蒙皮缝制"), {"soft"}, {}, 0, 2000, 3, 20,
         [](const Measure&) { return 2000.; }, [](const Measure& m) { return 150 + m.areaCm2() * .15; }},
        {"standard", QStringLiteral("标准件 (按规格网购)"), QStringLiteral("标准"), "#3FB97F", QStringLiteral("标准件"), QStringLiteral("按国标和通用规格采购"), {"fastener", "tyre", "standard"}, {}, 0, 1e9, 0, 2,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return m.purchasePrice(); }},
        {"purchase", QStringLiteral("外购总成"), QStringLiteral("外购"), "#5E6268", QStringLiteral("标准件"), QStringLiteral("成熟总成采购"), {"bought"}, {}, 0, 1e9, 0, 10,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return m.purchasePrice(); }},
        {"laser5", QStringLiteral("五轴激光修边 / 开孔"), QStringLiteral("修边"), "#E0605A", QStringLiteral("板材"), QStringLiteral("成形车皮五轴切窗洞格栅"), {"trim"}, {}, .3, 6000, .1, 5,
         [](const Measure&) { return 3000.; }, [](const Measure& m) { return hours(m.cutLength() / 4000 / 60, 450, .3); }},
        {"hand_trim", QStringLiteral("划线手工修边"), QStringLiteral("手修"), "#8E9AAF", QStringLiteral("板材"), QStringLiteral("样板划线手工切割打磨"), {"trim"}, {}, .3, 1e9, 1, 2,
         [](const Measure&) { return 0.; }, [](const Measure& m) { return hours(m.cutLength() / 400 / 60, 160, .2); }}
    };
    return result;
}
QJsonArray sketchShapes(const QJsonObject& feature, const QJsonObject& byId) {
    return byId.value(feature.value("params").toObject().value("sketch").toString()).toObject().value("params").toObject().value("shapes").toArray();
}
bool hollowDocument(const QJsonArray& features) {
    for (const auto& value : features) { const auto feature = value.toObject(); if (!feature.value("suppressed").toBool() && (feature.value("type") == "shell" || feature.value("params").toObject().value("op") == "void")) return true; }
    return false;
}
bool sheet(const QString& kind, const Process& process) {
    return QStringList{"plate", "partition", "skin"}.contains(kind) && QStringList{QStringLiteral("板材"), QStringLiteral("钣金成形")}.contains(process.family);
}
std::pair<bool, QString> feasible(const Process& process, const Measure& measure, const QString& kind) {
    if (!process.kinds.contains(kind)) return {false, QStringLiteral("形状不对")};
    const auto family = kind == "glass" ? QString("glass") : measure.stockType.family;
    if (!process.metals.isEmpty() && !process.metals.contains(family) && !QStringList{"glass", "soft", "tyre", "fastener", "bought"}.contains(kind)) return {false, QStringLiteral("不能用%1").arg(measure.materialName)};
    if (measure.length > process.size && !sheet(kind, process)) return {false, QStringLiteral("零件长 %1 mm, 超过这种工艺的 %2 mm").arg(measure.length, 0, 'f', 0).arg(process.size, 0, 'f', 0)};
    if (QStringList{"plate", "skin", "pocket", "partition", "freeform", "freeform_small", "prism", "revolved"}.contains(kind) && measure.thickness > 0 && measure.thickness < process.wall) return {false, QStringLiteral("壁厚 %1 mm 比这种工艺的下限 %2 mm 薄").arg(measure.thickness, 0, 'g', 2).arg(process.wall)};
    return {true, {}};
}
int segments(const Process& process, const Measure& measure, const QString& kind) { return sheet(kind, process) && measure.length > process.size ? int(std::ceil(measure.length / process.size)) : 1; }
QString moneyText(double value) {
    if (value >= 1e8) return QStringLiteral("%1 亿").arg(value / 1e8, 0, 'f', 2);
    if (value >= 1e4) return QStringLiteral("%1 万").arg(value / 1e4, 0, 'f', 1);
    return QString::number(value, 'f', value >= 10 ? 0 : 2);
}
void rejectUnresolved(const QJsonValue& value) {
    if (value.isString() && value.toString().startsWith('=')) throw DomainError(QStringLiteral("领域 API 需要已求值的参数，尚不支持全局变量表达式"));
    if (value.isArray()) for (const auto& child : value.toArray()) rejectUnresolved(child);
    if (value.isObject()) { const auto object = value.toObject(); for (auto iterator = object.begin(); iterator != object.end(); ++iterator) rejectUnresolved(iterator.value()); }
}
}

QStringList solid_kinds() {
    return {"extrude", "fillet", "chamfer", "hole", "revolve", "sweep", "loft", "boundary", "import_step", "hole_adv", "thread", "stud", "screw", "rib", "draft", "shell", "wrap", "split", "pattern_linear", "pattern_circular", "mirror", "pattern_curve", "pattern_sketch", "pattern_table", "pattern_fill", "pattern_variable", "plane", "axis", "csys", "point", "com", "bbox", "variables", "curve_helix", "sketch3d", "curve_surface", "curve_xyz", "curve_points", "curve_project", "curve_composite"};
}
QJsonArray process_catalog() { QJsonArray result; for (const auto& process : processes()) result.append(process.json()); return result; }
std::pair<QString, QString> shape_kind(const QJsonObject& feature, const QJsonObject& metrics, const QJsonObject& byId, bool hollow) {
    const auto type = feature.value("type").toString(); const auto params = feature.value("params").toObject();
    const QStringList noProcess{"sketch", "plane", "axis", "point", "helix", "curve3d", "composite_curve", "projected_curve", "split"};
    auto solids = solid_kinds();
    if (byId.contains("__solid_kinds__")) { solids.clear(); for (const auto& value : byId.value("__solid_kinds__").toArray()) solids.append(value.toString()); }
    if (noProcess.contains(type) || !solids.contains(type)) return {{}, {}};
    rejectUnresolved(params);
    const auto name = feature.value("name").toString(), op = params.value("op").toString("add");
    const QVector<std::pair<QString, QString>> hints{
        {QStringLiteral("玻璃|挡风|窗玻"), "glass"}, {QStringLiteral("轮胎"), "tyre"}, {QStringLiteral("螺栓|螺丝|螺钉|螺母|垫圈|气门嘴|铆钉"), "fastener"},
        {QStringLiteral("减振器|弹簧(?!座)|轴承|点火线圈|涡轮|发动机总成|变速箱|卡钳|刹车盘"), "bought"},
        {QStringLiteral("坐垫|靠背|包边|头枕|扶手|座椅$"), "soft"}, {QStringLiteral("灯罩|透镜|镜片"), "lens"}, {QStringLiteral("排气尾管|排气管|管路"), "tube"}
    };
    for (const auto& hint : hints) if (op != "cut" && QRegularExpression(hint.first).match(name).hasMatch()) return {hint.second, QStringLiteral("名字是 “%1”").arg(name)};
    auto size = metrics.value("size").toArray(); if (size.isEmpty()) size = {0, 0, 0};
    const double thin = size.first().toDouble(); double largest = 0; for (const auto& value : size) largest = std::max(largest, value.toDouble());
    const auto faces = metrics.value("faces").toObject(); const auto shapes = sketchShapes(feature, byId);
    bool text = false, circles = !shapes.isEmpty();
    for (const auto& value : shapes) { const auto shape = value.toObject(); text = text || shape.value("type") == "text"; if (!shape.value("construction").toBool() && shape.value("type") != "circle") circles = false; }
    if (op == "void" || type == "shell") return {"skin", QStringLiteral("空心件的内形: 外形和内形之间就是一层车皮")};
    if (op == "fill") return {"partition", QStringLiteral("只长在空腔里的板: 地板、隔板这类焊在车皮上的平板")};
    if (op == "pocket") return {"pocket", QStringLiteral("空心件上的凹槽: 和车皮一起成形")};
    if (text) return op == "cut" || thin <= 1.5 ? std::pair<QString, QString>{"engraving", QStringLiteral("刻在表面上的字")} : std::pair<QString, QString>{"letters", QStringLiteral("凸起的字: 一个个切出来贴上去")};
    if (op == "cut") {
        if (type == "hole" || (circles && type == "extrude")) return {"hole", QStringLiteral("圆孔")};
        if (hollow && largest > 200) return {"trim", QStringLiteral("在成形好的车皮上开的窗洞、格栅")};
        return {"pocket_cut", QStringLiteral("切出来的槽、窗、缺口")};
    }
    if (type == "hole" || type == "thread") return {"hole", QStringLiteral("孔 / 螺纹")};
    if (type == "revolve") return {"revolved", QStringLiteral("旋转出来的回转体")};
    if (type == "extrude" && circles && faces.value("freeform").toInt() == 0 && thin > 12) return {"revolved", QStringLiteral("圆柱 (棒料车出来)")};
    if (QStringList{"loft", "sweep", "boundary"}.contains(type) && hollow && largest > 800) return {"skin", QStringLiteral("空心件的外形曲面: 做出来是一层车皮")};
    if (QStringList{"loft", "sweep", "boundary", "wrap"}.contains(type) || faces.value("freeform").toInt() != 0) return {largest <= 400 ? "freeform_small" : "freeform", QStringLiteral("自由曲面")};
    if (type == "extrude" && thin <= 12 && faces.value("freeform").toInt() == 0) return {"plate", QStringLiteral("厚 %1 mm 的平板").arg(thin, 0, 'g', 3)};
    if (type == "extrude" && size.size() == 3 && size[2].toDouble() > 5 * std::max(size[1].toDouble(), 1e-9) && size[1].toDouble() <= 200 && size[2].toDouble() > 300) return {"profile", QStringLiteral("截面不变的长条")};
    return {"prism", QStringLiteral("有厚度的实体")};
}
QJsonObject rank_processes(const QJsonObject& feature, const QJsonObject& metrics, const QJsonObject& byId, int batch, const QString& material, bool hollow, int copies) {
    const auto classified = shape_kind(feature, metrics, byId, hollow); const auto kind = classified.first;
    QJsonObject result{{"kind", kind.isEmpty() ? QJsonValue(QJsonValue::Null) : QJsonValue(kind)}, {"why", classified.second}, {"options", QJsonArray()}, {"refused", QJsonArray()}};
    if (kind.isEmpty()) return result;
    if (!Prices.contains(kind)) {
        const auto dimensions = metrics.value("size").toArray();
        bool complete = dimensions.size() == 3;
        for (const auto& dimension : dimensions) complete = complete && dimension.isDouble() && dimension.toDouble() >= 0;
        for (const auto& field : QStringList{"volume", "area"}) complete = complete && metrics.value(field).isDouble() && metrics.value(field).toDouble() >= 0;
        if (!complete) throw DomainError(QStringLiteral("缺少有效的工艺几何指标 size / volume / area，不能伪造加工估价"));
    }
    const auto hint = Prices.contains(kind) || kind == "skin" ? kind : QString();
    copies = std::max({1, copies, metrics.value("solids").toInt(1)});
    const Measure measure(metrics, kind == "lens" ? QStringLiteral("聚碳酸酯 PC") : material, hint, feature.value("params").toObject(), copies);
    QVector<QJsonObject> options; QJsonArray refused; batch = std::max(batch, 1);
    for (const auto& process : processes()) {
        const auto accepted = feasible(process, measure, kind);
        if (!accepted.first) { if (accepted.second != QStringLiteral("形状不对")) refused.append(QJsonObject{{"process", process.json()}, {"reason", accepted.second}}); continue; }
        const int pieces = segments(process, measure, kind);
        const double tooling = process.tooling(measure) * pieces, unit = process.unit(measure) * copies + 300.0 * (pieces - 1) * copies;
        const double cost = tooling / batch + unit;
        if (!std::isfinite(cost) || cost < 0) throw DomainError(QStringLiteral("工艺估价出现无效费用"));
        options.append({{"cost", cost}, {"process", process.json()}, {"tooling", tooling}, {"unit", unit}, {"segments", pieces}});
    }
    std::stable_sort(options.begin(), options.end(), [](const auto& first, const auto& second) {
        const double firstCost = roundMoney(first.value("cost").toDouble()), secondCost = roundMoney(second.value("cost").toDouble());
        return firstCost != secondCost ? firstCost < secondCost : first.value("process").toObject().value("tolerance").toDouble() < second.value("process").toObject().value("tolerance").toDouble();
    });
    QJsonArray ranked; for (const auto& option : options) ranked.append(option);
    result["options"] = ranked; result["refused"] = refused; return result;
}
QJsonObject choose_process(const QJsonObject& feature, const QJsonObject& metrics, const QJsonObject& byId, int batch, const QString& material, bool hollow, int copies) {
    batch = std::max(batch, 1); const auto ranked = rank_processes(feature, metrics, byId, batch, material, hollow, copies);
    const auto kind = ranked.value("kind").toString(), why = ranked.value("why").toString(); if (kind.isEmpty()) return {};
    const auto options = ranked.value("options").toArray();
    if (options.isEmpty()) {
        QStringList reasons; for (const auto& value : ranked.value("refused").toArray()) { const auto row = value.toObject(); reasons.append(row.value("process").toObject().value("name").toString() + QStringLiteral("：") + row.value("reason").toString()); if (reasons.size() == 4) break; }
        return {{"id", ""}, {"name", QStringLiteral("没有合适的工艺")}, {"short", "?"}, {"color", "#E0605A"}, {"kind", kind}, {"auto", true}, {"batch", batch}, {"why", why + QStringLiteral("。") + (reasons.isEmpty() ? QStringLiteral("没有能做这种形状的工艺") : reasons.join(QStringLiteral("；")))}, {"alternatives", QJsonArray()}};
    }
    const auto best = options.first().toObject(), process = best.value("process").toObject();
    const double cost = best.value("cost").toDouble(), tooling = best.value("tooling").toDouble(), unit = best.value("unit").toDouble();
    const auto identifier = process.value("id").toString(); const bool standard = identifier == "standard" || identifier == "purchase";
    const auto spec = standard ? standard_spec(feature, metrics, byId, kind) : QString();
    QString note = QStringLiteral("%1 → %2：做 %3 件, 每件约 ¥%4").arg(why, process.value("name").toString()).arg(batch).arg(moneyText(cost));
    if (best.value("segments").toInt() > 1) note += QStringLiteral(" (超过设备行程: 分 %1 段做再焊起来)").arg(best.value("segments").toInt());
    if (tooling > 0) note += QStringLiteral(" (模具 / 工装 ¥%1 摊下来 ¥%2 + 单件 ¥%3)").arg(moneyText(tooling), moneyText(tooling / batch), moneyText(unit));
    int breakEven = 0; QString nextName; QJsonArray alternatives;
    for (int index = 1; index < options.size(); ++index) {
        const auto other = options[index].toObject(), otherProcess = other.value("process").toObject();
        if (index < 4) alternatives.append(QJsonObject{{"id", otherProcess.value("id")}, {"name", otherProcess.value("name")}, {"cost", roundMoney(other.value("cost").toDouble())}});
        const double otherTooling = other.value("tooling").toDouble(), otherUnit = other.value("unit").toDouble();
        if (otherUnit < unit && otherTooling > tooling) { const double count = std::ceil((otherTooling - tooling) / (unit - otherUnit)); if (count <= std::numeric_limits<int>::max() && (breakEven == 0 || count < breakEven)) { breakEven = int(count); nextName = otherProcess.value("name").toString(); } }
    }
    if (options.size() > 1) { const auto other = options[1].toObject(); note += QStringLiteral("；第二是 %1 ¥%2").arg(other.value("process").toObject().value("name").toString(), moneyText(other.value("cost").toDouble())); }
    if (breakEven > 0) note += QStringLiteral("；做到 %1 件以上换成 %2 更划算").arg(breakEven).arg(nextName);
    if (!spec.isEmpty()) note = spec + QStringLiteral("。") + note;
    return {{"id", identifier}, {"name", process.value("name")}, {"short", process.value("short")}, {"color", process.value("color")}, {"kind", kind}, {"auto", true}, {"batch", batch}, {"cost", roundMoney(cost)}, {"tooling", roundMoney(tooling)}, {"unit", roundMoney(unit)}, {"standard", standard}, {"spec", spec}, {"why", note}, {"alternatives", alternatives}};
}
QString standard_spec(const QJsonObject& feature, const QJsonObject& metrics, const QJsonObject& byId, const QString& kind) {
    const auto name = feature.value("name").toString(); const auto params = feature.value("params").toObject();
    QJsonArray hexes, circles;
    for (const auto& value : sketchShapes(feature, byId)) { const auto shape = value.toObject(); if (shape.value("construction").toBool()) continue; if (shape.value("type") == "ngon" && shape.value("sides").toInt() == 6) hexes.append(shape); if (shape.value("type") == "circle") circles.append(shape); }
    auto closest = [](const QVector<std::pair<QString, double>>& table, double value) { return *std::min_element(table.begin(), table.end(), [&](const auto& first, const auto& second) { return std::abs(first.second - value) < std::abs(second.second - value); }); };
    if (!hexes.isEmpty()) {
        const double flats = hexes.first().toObject().value("r").toDouble() * std::sqrt(3.0);
        const auto found = closest({{"M5", 8}, {"M6", 10}, {"M8", 13}, {"M10", 16}, {"M12", 18}, {"M14", 21}, {"M16", 24}, {"M20", 30}, {"M24", 36}}, flats);
        QString text = name.contains(QStringLiteral("螺母")) ? QStringLiteral("GB/T 6170 %1 六角螺母").arg(found.first) : QStringLiteral("GB/T 5782 %1×%2 六角头螺栓").arg(found.first).arg(std::max(std::nearbyint(params.value("distance").toDouble() * 2), 10.0));
        if (std::abs(flats - found.second) > .5) text += QStringLiteral(" (现在对边 %1 mm, 标准是 %2 mm: 改成 %2 mm 才买得到)").arg(flats, 0, 'f', 1).arg(found.second);
        return text;
    }
    if (!circles.isEmpty() && name.contains(QStringLiteral("垫圈"))) {
        const double diameter = circles.first().toObject().value("r").toDouble() * 2;
        const auto found = closest({{"M5", 10}, {"M6", 12}, {"M8", 16}, {"M10", 20}, {"M12", 24}, {"M14", 28}, {"M16", 30}, {"M20", 37}, {"M24", 44}}, diameter);
        QString text = QStringLiteral("GB/T 97.1 %1 平垫圈").arg(found.first);
        if (std::abs(diameter - found.second) > .5) text += QStringLiteral(" (现在外径 %1 mm, 标准是 %2 mm)").arg(diameter, 0, 'f', 1).arg(found.second);
        return text;
    }
    if (!circles.isEmpty() && QRegularExpression(QStringLiteral("螺丝|螺钉")).match(name).hasMatch()) {
        const double diameter = circles.first().toObject().value("r").toDouble() * 2;
        const auto found = closest({{"M3", 5.6}, {"M4", 8}, {"M5", 9.5}, {"M6", 12}, {"M8", 16}, {"M10", 20}}, diameter);
        QString text = QStringLiteral("GB/T 818 %1 十字盘头螺钉").arg(found.first);
        if (std::abs(diameter - found.second) > .8) text += QStringLiteral(" (现在头部 %1 mm, 标准是 %2 mm)").arg(diameter, 0, 'f', 1).arg(found.second);
        return text;
    }
    const auto size = metrics.value("size").toArray();
    if (name.contains(QStringLiteral("气门嘴"))) return QStringLiteral("TR414 无内胎气门嘴");
    if (kind == "tyre" && size.size() == 3 && size[2].toDouble() > 0) {
        const double outer = size[2].toDouble(), width = size[0].toDouble(); int rim = 0;
        for (int inch = 13; inch < 24; ++inch) {
            const double sidewall = (outer - inch * 25.4) / 2;
            if (width > 0 && sidewall / width >= .25 && sidewall / width <= .8
                && (rim == 0 || std::abs(sidewall / width - .4) < std::abs((outer - rim * 25.4) / 2 / width - .4))) rim = inch;
        }
        if (rim > 0) return QStringLiteral("%1/%2 R%3 轮胎").arg(int(std::nearbyint(width / 5) * 5)).arg(int(std::nearbyint((outer - rim * 25.4) / 2 / width * 20) * 5)).arg(rim);
        return QStringLiteral("轮胎 (按外径 / 断面宽选规格)");
    }
    return name;
}
QJsonObject bind_processes(const QJsonArray& features, const QJsonObject& report, int batch, const QString& material, const QStringList& only) {
    QJsonObject byId; for (const auto& value : features) { const auto feature = value.toObject(); rejectUnresolved(feature.value("params")); byId[feature.value("id").toString()] = feature; }
    QJsonObject bound; QJsonObject last, skin; QString skinName; const bool hollow = hollowDocument(features); const auto tools = report.value("tools").toObject();
    for (const auto& value : features) {
        const auto feature = value.toObject(); if (feature.value("suppressed").toBool()) continue;
        const auto identifier = feature.value("id").toString(), type = feature.value("type").toString(); const auto params = feature.value("params").toObject(), current = feature.value("process").toObject();
        if (!only.isEmpty() && !only.contains(identifier)) { if (!current.isEmpty()) last = current; continue; }
        if (!current.isEmpty() && !current.value("auto").toBool(true)) { bound[identifier] = current; last = current; continue; }
        if (type.startsWith("pattern_") || type == "mirror") {
            for (const auto& seed : params.value("features").toArray()) {
                auto process = bound.value(seed.toString()).toObject(); if (process.isEmpty()) process = byId.value(seed.toString()).toObject().value("process").toObject();
                if (process.value("id").toString().isEmpty()) continue;
                process["why"] = QStringLiteral("复制原件 → 和原件一样用%1").arg(process.value("name").toString()); process["auto"] = true; bound[identifier] = process; break;
            }
            continue;
        }
        if (type == "fillet" || type == "chamfer") {
            if (!last.value("id").toString().isEmpty()) { auto process = last; process["why"] = QStringLiteral("%1在%2的时候一起做出来").arg(type == "fillet" ? QStringLiteral("圆角") : QStringLiteral("倒角"), last.value("name").toString()); process["auto"] = true; bound[identifier] = process; }
            continue;
        }
        auto choice = choose_process(feature, tools.value(identifier).toObject(), byId, batch, material, hollow);
        if (choice.isEmpty()) continue;
        if (QStringList{"skin", "pocket"}.contains(choice.value("kind").toString()) && !skin.isEmpty()) {
            choice = skin; choice["cost"] = 0.; choice["tooling"] = 0.; choice["unit"] = 0.; choice["auto"] = true; choice["alternatives"] = QJsonArray();
            choice["why"] = QStringLiteral("和车皮一起成形 → %1 (费用算在 “%2” 里)").arg(skin.value("name").toString(), skinName);
        }
        bound[identifier] = choice;
        if (!choice.value("id").toString().isEmpty()) last = choice;
        if (choice.value("kind") == "skin" && skin.isEmpty() && !choice.value("id").toString().isEmpty()) { skin = choice; skinName = feature.value("name").toString(identifier); }
    }
    return bound;
}
}
