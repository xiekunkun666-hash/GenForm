#include "inspect_selftest.hpp"

#if defined(GENFORM_INSPECT_SELFTEST) && defined(GENFORM_HAS_OCCT)
#include "native.hpp"
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <algorithm>

namespace genform::kernel::native {
namespace {
void requireInspect(bool condition, const QString &message) {
    if (!condition) fail("Inspect self-test: " + message);
}

void closeInspect(double actual, double expected, const QString &message) {
    requireInspect(std::isfinite(actual) && std::abs(actual - expected) < 1e-5, message);
}

TopoDS_Shape box(double first = 0, double second = 0, double third = 0, double width = 10, double height = 10, double depth = 10) {
    return BRepPrimAPI_MakeBox(gp_Pnt(first, second, third), width, height, depth).Shape();
}

Context scene(const std::vector<std::pair<QString, Tool>> &entries) {
    Context context;
    std::vector<TopoDS_Shape> solids;
    for (const auto &entry : entries) {
        if (!context.tools.contains(entry.first)) context.features.append(QJsonObject{{"id", entry.first}});
        context.tools[entry.first].push_back(entry.second);
        context.status[entry.first] = "ok";
        if (entry.second.operation == "add" && !entry.second.shape.IsNull()) solids.push_back(entry.second.shape);
    }
    if (!solids.empty()) context.body = compound(solids);
    return context;
}

Context twoBoxes(double position, const QString &operation = "add") {
    return scene({{"a", {box(), "add", "a"}}, {"b", {box(position), operation, "b"}}});
}

QJsonObject checked(const Context &context, const QJsonObject &overrides = {}) {
    QJsonObject rules{{"clearance", 0.5}, {"overlap", 0.3}, {"tolerance", 0.1}, {"pair_limit", 600}, {"proofing", 1}};
    for (auto entry = overrides.begin(); entry != overrides.end(); ++entry) rules[entry.key()] = entry.value();
    return inspect(context, {{"rules", rules}});
}

QJsonObject finding(const QJsonObject &report, const QString &kind, double value, int compared = 1) {
    const auto pairs = report["pairs"].toArray();
    requireInspect(pairs.size() == 1, kind + " finding count");
    requireInspect(report["pairs_checked"].toInt() == compared, kind + " comparison count");
    const auto item = pairs.first().toObject();
    requireInspect(item["kind"].toString() == kind, kind + " finding kind");
    requireInspect(item["a"] == "a" && item["b"] == "b", kind + " ordered feature ids");
    requireInspect(item["point"].toArray().size() == 3, kind + " point");
    closeInspect(item["value"].toDouble(), value, kind + " value");
    return item;
}
}

QJsonObject runInspectSelfTests() {
    QJsonArray passed;
    auto report = checked(Context{});
    requireInspect(!report["has_body"].toBool() && report["valid"].toBool() && !report.contains("pairs") && !report.contains("proof"), "empty body report");
    passed.append("empty_body");

    auto context = scene({{"a", {box(1, 2, 3, 20, 10, 4), "add", "a"}}});
    report = inspect(context, {});
    requireInspect(!report.contains("pairs") && !report.contains("proof"), "rules absent");
    const auto metrics = report["tools"].toObject()["a"].toObject();
    requireInspect(metrics["size"].toArray() == QJsonArray{4, 10, 20}, "sorted tool dimensions");
    closeInspect(metrics["volume"].toDouble(), 800, "tool volume");
    closeInspect(metrics["area"].toDouble(), 640, "tool area");
    closeInspect(metrics["thickness"].toDouble(), 2.5, "tool thickness");
    requireInspect(metrics["faces"].toObject()["plane"].toInt() == 6 && metrics["solids"].toInt() == 1 && metrics["copies"].toInt() == 1 && metrics["op"] == "add", "tool topology and operation");
    requireInspect(report["bodies"].toArray().size() == 1 && report["voids"].toInt() == 0 && report["status"].toObject()["a"] == "ok", "base report fields");
    passed.append("metrics_and_base_report");

    report = checked(context);
    const auto proof = report["proof"].toObject();
    requireInspect(proof["axis"].toInt() == 2 && proof["box"].toArray() == metrics["box"].toArray(), "proof axis and bounds");
    for (const auto &key : {"extent", "top", "bottom"}) {
        const auto size = proof[key].toArray();
        requireInspect(size.size() == 2, QString(key) + " section fields");
        closeInspect(size[0].toDouble(), 20, QString(key) + " width");
        closeInspect(size[1].toDouble(), 10, QString(key) + " height");
    }
    requireInspect(!checked(context, {{"proofing", 0}}).contains("proof") && checked(context, {{"proofing", true}}).contains("proof"), "numeric and boolean proofing switch");
    requireInspect(inspect(context, {{"rules", QJsonObject{{"batch", 1}}}}).contains("pairs"), "non-pair effective rules use pair defaults");
    passed.append("proof_sections_and_switch");

    report = checked(scene({{"a", {box(0, 0, 0, 2, 30, 20), "add", "a"}}}));
    requireInspect(report["proof"].toObject()["axis"].toInt() == 0, "proof X axis");
    requireInspect(report["proof"].toObject()["extent"].toArray() == QJsonArray{30, 20}, "proof X remaining axes");
    report = checked(scene({{"a", {box(0, 0, 0, 30, 2, 20), "add", "a"}}}));
    requireInspect(report["proof"].toObject()["axis"].toInt() == 1, "proof Y axis");
    passed.append("proof_axis_selection");

    finding(checked(twoBoxes(10.25)), "gap", 0.25);
    passed.append("gap");
    finding(checked(twoBoxes(10)), "touch", 0);
    passed.append("touch");
    const auto shallow = finding(checked(twoBoxes(9.8)), "shallow", 0.2);
    closeInspect(shallow["point"].toArray()[0].toDouble(), 9.9, "overlap center");
    passed.append("shallow");

    report = checked(twoBoxes(9.5));
    requireInspect(report["pairs"].toArray().isEmpty() && report["pairs_checked"].toInt() == 1, "sufficient overlap");
    finding(checked(twoBoxes(9.5), {{"tolerance", 0.3}}), "shallow", 0.5);
    report = checked(twoBoxes(10.25), {{"clearance", 0.1}, {"tolerance", 0.01}});
    requireInspect(report["pairs_checked"].toInt() == 0, "clearance rule applied");
    finding(checked(twoBoxes(10.25), {{"clearance", 0.1}, {"tolerance", 0.2}}), "gap", 0.25);
    passed.append("overlap_clearance_and_tolerance");

    report = checked(twoBoxes(20));
    requireInspect(report["pairs"].toArray().isEmpty() && report["pairs_checked"].toInt() == 0, "distant bodies");
    report = checked(twoBoxes(10.1, "cut"));
    requireInspect(report["pairs_checked"].toInt() == 0 && report["tools"].toObject()["b"].toObject()["op"] == "cut", "cut tools excluded only from pairs");
    report = checked(scene({{"a", {box(), "add", "a"}}, {"a", {box(10.1), "add", "a"}}}));
    requireInspect(report["pairs_checked"].toInt() == 0 && report["tools"].toObject()["a"].toObject()["copies"].toInt() == 2, "same feature copies excluded");
    passed.append("candidate_filters");

    context = scene({{"a", {box(), "add", "a"}}, {"a", {box(30), "add", "a"}},
                     {"b", {box(10.4), "add", "b"}}, {"b", {box(40.2), "add", "b"}}});
    finding(checked(context), "gap", 0.2, 2);
    passed.append("worst_copy_per_feature_pair");

    context = scene({{"a", {box(), "add", "a"}}, {"b", {box(10.2), "add", "b"}}, {"c", {box(8, 0, 0, 5), "add", "c"}}});
    report = checked(context);
    requireInspect(report["pairs"].toArray().isEmpty() && report["pairs_checked"].toInt() == 3, "connected gap suppression");
    context.tools["b"].front().shape = box(10);
    finding(checked(context), "touch", 0, 3);
    context.tools["b"].front().shape = box(9.8);
    finding(checked(context), "shallow", 0.2, 3);
    passed.append("transitive_connections_keep_touch_and_shallow");

    context = scene({{"b", {box(), "add", "b"}}, {"a", {box(10.1), "add", "a"}}, {"c", {box(20.2), "add", "c"}}});
    finding(checked(context, {{"pair_limit", 1}}), "gap", 0.1);
    report = checked(context, {{"pair_limit", 0}});
    requireInspect(report["pairs_checked"].toInt() == 0 && report["pairs"].toArray().isEmpty(), "zero pair limit");
    passed.append("pair_limit_and_insertion_order");

    context = scene({{"a", {box(0, 0, 0, 2501), "add", "a"}}, {"b", {box(2501.1), "add", "b"}}});
    requireInspect(checked(context)["pairs_checked"].toInt() == 0, "large skin excluded");
    passed.append("large_body_filter");

    std::vector<std::pair<QString, Tool>> entries;
    for (int copy = 0; copy < 64; ++copy) entries.push_back({"a", {box(100 + copy * 20), "add", "a"}});
    entries.push_back({"a", {box(), "add", "a"}});
    entries.push_back({"b", {box(10.1), "add", "b"}});
    report = checked(scene(entries));
    requireInspect(report["pairs_checked"].toInt() == 0 && report["tools"].toObject()["a"].toObject()["copies"].toInt() == 65, "64 copy geometry limit retains metrics count");
    passed.append("copy_limit");

    context = scene({{"a", {box(), "add", "a"}}, {"b", {TopoDS_Shape{}, "add", "b"}}});
    report = checked(context);
    requireInspect(!report["tools"].toObject().contains("b") && report["pairs_checked"].toInt() == 0, "null tool skipped");
    passed.append("null_tools");

    context = scene({{"a", {box(0, 0, 2, 20, 10, 2), "add", "a"}},
                     {"b", {box(5, 3, 0, 10, 4, 2), "add", "b"}}, {"c", {box(5, 3, 4, 10, 4, 2), "add", "c"}}});
    const auto doubleSided = checked(context)["proof"].toObject();
    for (const auto &key : {"top", "bottom"}) {
        const auto section = doubleSided[key].toArray();
        requireInspect(section.size() == 2, "two-sided section exists");
        closeInspect(section[0].toDouble(), 10, "two-sided section width");
        closeInspect(section[1].toDouble(), 4, "two-sided section height");
    }
    passed.append("double_sided_proof_geometry");

    context = scene({{"a", {box(), "add", "a"}}});
    context.body = BRepAlgoAPI_Cut(box(), box(2, 2, 2, 6, 6, 6)).Shape();
    report = checked(context);
    requireInspect(report["voids"].toInt() == 1 && report["valid"].toBool(), "closed internal cavity");
    passed.append("closed_cavity");

    context = scene({{"a", {box(), "add", "a"}}});
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(context.body, TopAbs_FACE, faces);
    context.owners = {{TopoDS::Face(faces(1)), "z", {}}, {TopoDS::Face(faces(2)), "a", {}}};
    report = checked(context);
    requireInspect(report["bodies"].toArray().first().toObject()["features"].toArray() == QJsonArray{"z", "a"}, "owner count ties retain topology order");
    passed.append("body_feature_owners");

    return {{"passed", passed.size()}, {"cases", passed}};
}
}
#endif
