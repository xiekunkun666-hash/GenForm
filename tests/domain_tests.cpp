#include "genform/domain/geometry.hpp"

#include <QCoreApplication>
#include <QJsonDocument>
#include <QTextStream>
#include <cmath>
#include <functional>
#include <limits>
#include <numbers>

using namespace genform::domain;

namespace {
int checks = 0;
void require(bool condition, const QString& message) {
    ++checks;
    if (!condition) throw DomainError(message);
}
void near(double actual, double expected, double tolerance = 1e-4) {
    require(std::isfinite(actual) && std::abs(actual - expected) <= tolerance,
            QStringLiteral("expected %1, actual %2, tolerance %3").arg(expected, 0, 'g', 14).arg(actual, 0, 'g', 14).arg(tolerance));
}
void rejects(const std::function<void()>& action) {
    bool rejected = false;
    try { action(); } catch (const DomainError&) { rejected = true; }
    require(rejected, "expected DomainError");
}
QJsonObject object(const char* text) {
    QJsonParseError error;
    const auto document = QJsonDocument::fromJson(text, &error);
    require(error.error == QJsonParseError::NoError && document.isObject(), "invalid test JSON");
    return document.object();
}
QJsonObject lineShape(double x1, double y1, double x2, double y2) { return {{"type", "line"}, {"x1", x1}, {"y1", y1}, {"x2", x2}, {"y2", y2}}; }
bool hasCode(const QJsonArray& issues, const QString& code, const QString& level = {}) {
    for (const auto& value : issues) { const auto row = value.toObject(); if (row.value("code").toString() == code && (level.isEmpty() || row.value("level").toString() == level)) return true; }
    return false;
}
void geometryTests() {
    const auto rectangle = object(R"({"type":"rect","w":40,"h":20})");
    near(signed_area(vertices(rectangle)), 800);
    near(length(rectangle), 120);
    require(prims(rectangle).size() == 4, "rectangle primitive count");
    require(is_closed(rectangle), "closed rectangle");
    near(signed_distance(rectangle, {0, 0}), -10);
    near(signed_distance(rectangle, {30, 0}), 10);
    const auto polygon = rotated(rectangle, {0, 0}, 45);
    require(polygon.value("type") == "polygon", "rotated rectangle becomes polygon");
    near(std::abs(signed_area(vertices(polygon))), 800, .001);
    const auto six = object(R"({"type":"ngon","r":10,"sides":6})");
    require(vertices(six).size() == 6, "hexagon vertices");
    rejects([&] { vertices(object(R"({"type":"ngon","r":10,"sides":2})")); });
    rejects([&] { prims(object(R"({"type":"circle","r":0})")); });
    rejects([&] { prims(object(R"({"type":"line","x1":0})")); });
    rejects([&] { prims(object(R"({"type":"unknown"})")); });
    const auto arc = object(R"({"type":"arc","r":10,"a0":350,"a1":10})");
    const auto primitive = prims(arc).first();
    near(primitive.end - primitive.start, 20 * std::numbers::pi / 180, 1e-12);
    near(nearest(arc, {20, 0}).first, 10);
    require(hit(arc, {10, 0}, .001), "arc hit");
    require(key_points(arc).size() == 4, "arc snap points");
    const auto fullArc = object(R"({"type":"arc","r":10,"a0":15,"a1":15})");
    near(prims(fullArc).first().end - prims(fullArc).first().start, 2 * std::numbers::pi, 1e-12);
    const auto circle = object(R"({"type":"circle","r":10})");
    near(length(circle), 2 * std::numbers::pi * 10, .03);
    require(key_points(circle).size() == 5, "circle quadrants");
    const auto ellipse = object(R"({"type":"ellipse","rx":20,"ry":10,"angle":90})");
    const auto ellipsePoints = sample(prims(ellipse).first(), 64);
    near(ellipsePoints.first().x(), 0);
    near(ellipsePoints.first().y(), 20);
    const auto slot = object(R"({"type":"slot","x1":0,"y1":0,"x2":20,"y2":0,"w":10})");
    auto closed = loops({slot});
    require(closed.loops.size() == 1 && closed.leftover == 0, "slot contour");
    near(std::abs(signed_area(loop_ring(closed.loops.first(), 256))), 200 + std::numbers::pi * 25, .02);
    const auto arcSlot = object(R"({"type":"arcslot","r":20,"w":10,"a0":0,"a1":180})");
    closed = loops({arcSlot});
    near(std::abs(signed_area(loop_ring(closed.loops.first(), 256))), std::numbers::pi * 225, .5);
    rejects([&] { prims(object(R"({"type":"arcslot","r":5,"w":10,"a0":0,"a1":90})")); });
    rejects([&] { prims(object(R"({"type":"slot","x1":0,"y1":0,"x2":0,"y2":0,"w":1})")); });
    const auto spline = object(R"({"type":"spline","points":[[0,0],[10,20],[30,20],[40,0]]})");
    require(prims(spline).size() == 3, "Catmull-Rom segments");
    auto style = spline; style["style"] = true;
    const auto styled = polylines(style, 32).first();
    near(styled.first().x(), 0); near(styled.last().x(), 40);
    for (const auto& point : styled) require(point.y() < 20, "Bezier stays in polygon");
    auto closedSpline = spline; closedSpline["closed"] = true;
    require(prims(closedSpline).size() == 4 && !ends(closedSpline), "closed spline ends");
    const auto foundCircle = circle3({10, 0}, {0, 10}, {-10, 0});
    require(foundCircle.has_value(), "three point circle"); near(foundCircle->second, 10); near(foundCircle->first.length(), 0);
    require(!circle3({0, 0}, {1, 1}, {2, 2}), "collinear circle rejected");
    const auto foundArc = arc3({10, 0}, {-10, 0}, {0, 10});
    require(foundArc.has_value(), "three point arc"); near(prims(*foundArc).first().end - prims(*foundArc).first().start, std::numbers::pi);
    auto translated = moved(circle, 4, 5); near(translated.value("cx").toDouble(), 4); near(translated.value("cy").toDouble(), 5);
    auto reflected = mirrored(arc, {0, 0}, {1, 0}); near(number(reflected, "a0"), -10); near(number(reflected, "a1"), -350);
    const auto construction = object(R"({"type":"rect","w":4,"h":2,"construction":true})");
    require(mirrored(construction, {0, 0}, {1, 1}).value("construction").toBool(), "mirror preserves construction");
    require(explode(construction).size() == 4, "explode rectangle");
    for (const auto& value : explode(construction)) require(value.toObject().value("construction").toBool(), "explode construction");
    near(number(offset(rectangle, 2), "w"), 44);
    near(number(offset(circle, -2), "r"), 8);
    require(offset(circle, -10).isEmpty(), "collapsed offset returns no shape");
    const auto crossing = intersections(prims(lineShape(-20, 0, 20, 0)).first(), prims(circle).first());
    require(crossing.size() == 2, "line circle intersections");
    const auto tangent = intersections(prims(lineShape(-20, 10, 20, 10)).first(), prims(circle).first());
    require(tangent.size() == 1, "tangent intersection dedup");
    const auto lineCross = intersections(prims(lineShape(0, 0, 10, 10)).first(), prims(lineShape(0, 10, 10, 0)).first());
    require(lineCross.size() == 1, "line intersections"); near(lineCross[0].x(), 5);
    const QJsonArray square{lineShape(0, 0, 10, 0), lineShape(10, 10, 10, 0), lineShape(10, 10, 0, 10), lineShape(0, 10, 0, 0)};
    closed = loops(square); require(closed.loops.size() == 1 && closed.leftover == 0, "mixed orientation square"); near(std::abs(signed_area(loop_ring(closed.loops[0]))), 100);
    require(chain_of(square, 2) == QVector<int>({0, 1, 2, 3}), "connected chain");
    require(diagnose(square).isEmpty(), "valid contour diagnostics");
    auto gapped = square; gapped[0] = lineShape(0, 0, 9.95, 0); require(!diagnose(gapped).isEmpty(), "gap diagnosed");
    auto fixed = repair(gapped); require(fixed.fixed >= 1 && loops(fixed.shapes).loops.size() == 1, "gap repaired");
    auto dirty = square; dirty.append(square[0]); dirty.append(lineShape(100, 100, 100.0001, 100));
    fixed = repair(dirty); require(fixed.fixed == 2 && fixed.shapes.size() == 4, "duplicate and tiny removal");
    auto branched = square; branched.append(lineShape(0, 0, -10, 0)); require(loops(branched).loops.isEmpty(), "branches are not loops");
    auto ignored = square; ignored.append(construction); require(loops(ignored).loops.size() == 1, "construction excluded");
    const QJsonArray extended{lineShape(0, 0, 10, 0), lineShape(30, -10, 30, 10)};
    near(extend(extended, 0, {9, 0})[0].toObject().value("x2").toDouble(), 30);
    const QJsonArray trimmed{lineShape(0, 0, 40, 0), lineShape(10, -5, 10, 5), lineShape(30, -5, 30, 5)};
    const auto cut = trim(trimmed, 0, {20, 0}); require(cut.size() == 4, "trim leaves two pieces"); near(length(cut[0].toObject()) + length(cut[1].toObject()), 20);
    near(evaluate("-2^2"), -4); near(evaluate("2**3**2"), 512); near(evaluate("2^-2"), .25);
    near(evaluate("sin(pi/2)+sqrt(9)+min(4,2)"), 6); near(evaluate("-5%3"), 1); near(evaluate("log(8,2)"), 3);
    rejects([] { evaluate("__import__('os')"); }); rejects([] { evaluate("1/0"); }); rejects([] { evaluate("sqrt(-1)"); }); rejects([] { evaluate("x.foo"); });
    const auto equation = object(R"({"type":"equation","fy":"x^2/10","t0":0,"t1":60})");
    near(equation_points(equation).last().y(), 360);
    near(equation_points(moved(equation, 2, 3)).last().y(), 363);
    require(rotated(equation, {0, 0}, 90).value("type") == "spline", "transformed equation sampled to spline");
}
void propertyTests() {
    const auto front = frame("XZ", 5); near(front.normal.y(), -1); near(front.origin.y(), -5);
    const auto world = to_world({{2, 3}}, "XZ", 5); near(world[0].x(), 2); near(world[0].y(), -5); near(world[0].z(), 3);
    require((front.matrix().map(QVector3D(2, 3, 0)) - world[0]).length() < 1e-6, "plane matrix mapping");
    const auto ray = from_ray({2, 3, 10}, {0, 0, -1}); require(ray.has_value(), "ray plane hit"); near(ray->x(), 2); near(ray->y(), 3);
    require(!from_ray({0, 0, 10}, {1, 0, 0}), "parallel ray"); require(!from_ray({0, 0, 10}, {0, 0, 1}), "backward ray");
    rejects([] { frame("BAD"); });
    const auto custom = object(R"({"origin":[1,2,3],"x":[0,1,0],"y":[0,0,1]})"); near(to_world({{4, 5}}, custom, 2)[0].x(), 3);
    require(material_catalog().size() == 20, "material catalog size"); near(density(QStringLiteral("普通碳钢")).value(), 7.85); require(!density("unknown"), "unknown density");
    near(mechanics(QStringLiteral("铝合金 6061"))->x(), 68900); require(!mechanics(QStringLiteral("皮革 + 海绵")), "no fabricated mechanics");
    near(mass_grams(1000000, QStringLiteral("普通碳钢")).value(), 7850); require(!mass_grams(1000, "unknown"), "unknown mass");
    require(rgb("#ff8000").has_value(), "RGB parsed"); near(rgb("#ff8000")->y(), 128 / 255.0); require(!rgb("#zz0000"), "invalid RGB");
    const auto cleaned = clean_rules({{"tolerance", -1}, {"batch", 2.5}, {"bad", 10}, {"min_wall", "2.2"}});
    near(cleaned.value("tolerance").toDouble(), .001); near(cleaned.value("batch").toDouble(), 2); require(!cleaned.contains("bad"), "unknown rule removed");
    const auto rules = effective_rules({{"clearance", 2}}, {{"clearance", 3}}); near(rules.value("clearance").toDouble(), 3); require(rule_table().size() == 11, "rule table");
    const auto partDocument = object(R"({"props":{"material":"ABS"},"features":[{"type":"extrude","process":{"id":"cnc3","name":"CNC","cost":12.345}},{"type":"sketch","process":{"id":"purchase","cost":999}}]})");
    const auto description = describe_document(partDocument); near(description.value("unit").toDouble(), 12.34); require(description.value("kind") == "custom", "BOM custom classification");
    auto purchased = partDocument; auto features = purchased.value("features").toArray(); auto feature = features[0].toObject(); feature["process"] = object(R"({"id":"standard","name":"buy","cost":2,"standard":true,"spec":"M6"})"); features[0] = feature; purchased["features"] = features;
    const auto rows = bill({object(R"({"name":"part","path":"a.gform"})"), object(R"({"name":"part","path":"a.gform"})"), object(R"({"name":"part","path":"a.gform","mirror":true})"), object(R"({"name":"bolt","path":"b.gform","mirror":true})"), object(R"({"name":"bolt","path":"b.gform"})")}, {{"a.gform", partDocument}, {"b.gform", purchased}});
    require(rows.size() == 3, "BOM mirrored custom split and purchased merge");
    const auto totals = bill_totals(rows); require(totals.value("all").toObject().value("count").toInt() == 5, "BOM total count"); near(totals.value("all").toObject().value("cost").toDouble(), 41.02);
    require(bill_csv(rows).startsWith(QByteArray::fromHex("efbbbf")), "BOM CSV UTF-8 BOM");
    require(!describe("missing_nonexistent_file.gform").value("bound").toBool(), "missing file unbound");
}
void editingTests() {
    const auto rectangle = object(R"({"type":"rect","cx":20,"cy":15,"w":40,"h":30})");
    const auto rounded = fillet({rectangle}, {40.1f, 30.1f}, 5, 1);
    require(rounded.size() == 5, "fillet creates four lines and arc");
    int arcs = 0;
    for (const auto& value : rounded) { const auto shape = value.toObject(); if (shape.value("type") == "arc") { ++arcs; near(number(shape, "cx"), 35); near(number(shape, "cy"), 25); near(number(shape, "r"), 5); } }
    require(arcs == 1, "fillet arc count");
    const auto contour = loops(rounded); require(contour.loops.size() == 1, "fillet preserves contour");
    near(std::abs(signed_area(loop_ring(contour.loops[0], 512))), 1200 - 25 + std::numbers::pi * 25 / 4, .01);
    rejects([&] { fillet({rectangle}, {40, 30}, 500, 1); });
    require(!corner_near({rectangle}, {100, 100}, 1), "missing corner");
    const QJsonArray lines{lineShape(0, 0, 10, 10), lineShape(20, 5, 25, 15)};
    require(relations_for(lines).contains("parallel") && relations_for(lines).contains("coincident"), "line relation choices");
    const auto horizontal = relate(lines, {0, 1}, "horizontal");
    for (const auto& value : horizontal) { const auto shape = value.toObject(); near(number(shape, "y1"), number(shape, "y2")); }
    const auto perpendicular = relate(lines, {0, 1}, "perpendicular");
    const auto firstTips = ends(perpendicular[0].toObject()).value(), secondTips = ends(perpendicular[1].toObject()).value();
    near(QVector2D::dotProduct(firstTips.second - firstTips.first, secondTips.second - secondTips.first), 0, .001);
    const auto equal = relate(lines, {0, 1}, "equal"); near(length(equal[0].toObject()), length(equal[1].toObject()));
    const auto collinear = relate(lines, {0, 1}, "collinear"); const auto alignedTips = ends(collinear[1].toObject()).value(); near(alignedTips.first.x(), alignedTips.first.y());
    const QJsonArray circles{object(R"({"type":"circle","cx":0,"cy":0,"r":5})"), object(R"({"type":"circle","cx":10,"cy":20,"r":2})")};
    const auto concentric = relate(circles, {0, 1}, "concentric"); near(number(concentric[1].toObject(), "cx"), 0); near(number(concentric[1].toObject(), "cy"), 0);
    const auto circleEqual = relate(circles, {0, 1}, "equal"); near(number(circleEqual[1].toObject(), "r"), 5);
    const auto tangent = relate({lineShape(-20, 0, 20, 0), object(R"({"type":"circle","cx":0,"cy":10,"r":5})")}, {0, 1}, "tangent"); near(number(tangent[1].toObject(), "cy"), 5);
    const auto oppositeTangent = relate({object(R"({"type":"circle","cx":0,"cy":10,"r":5})"), lineShape(-20, 0, 20, 0)}, {0, 1}, "tangent"); near(number(oppositeTangent[1].toObject(), "y1"), 5);
    rejects([&] { relate(circles, {0, 1}, "horizontal"); }); rejects([&] { relate(lines, {0, 0}, "equal"); });
    near(signed_distance(lineShape(0, 0, 10, 0), {5, -3}), -3);
    near(signed_distance(object(R"({"type":"arc","r":10,"a0":0,"a1":180})"), {0, 5}), -5);
    require(offset(object(R"({"type":"ellipse","rx":20,"ry":10})"), 1).value("type") == "spline", "sampled ellipse offset");
    const auto ngon = object(R"({"type":"ngon","r":10,"sides":6})"); near(number(offset(ngon, 2), "r"), 10 + 2 / std::cos(std::numbers::pi / 6));
    const auto fittedLine = fit_line({{10, 10}, {5, 5}, {0, 0}, {10, 10}}); require(fittedLine.value("type") == "line", "closed collinear sampling becomes line"); near(length(fittedLine), std::sqrt(200.));
    const auto circle = object(R"({"type":"circle","r":10})");
    const auto fittedCircle = fit_line(sample(prims(circle)[0], 96)); require(fittedCircle.value("type") == "circle", "circle fitting"); near(number(fittedCircle, "r"), 10);
    const auto arc = object(R"({"type":"arc","r":5,"a0":0,"a1":90})"); require(fit_line(sample(prims(arc)[0], 96)).value("type") == "arc", "arc fitting");
    require(fit_lines({{{0, 0}, {10, 10}}, {{10, 10}, {0, 0}}}).size() == 1, "fit reversed line deduplicated");
    const auto projected = project_edges(object(R"({"has_body":true,"segments":[[[0,0,5],[10,10,5]],[[10,10,5],[0,0,5]]],"segment_edge":[1,2],"edges":[{"id":1,"type":"line"},{"id":2,"type":"line"}]})"), "XY"); require(projected.size() == 1, "projected duplicate edge removed");
    const auto laidOut = text_layout(object(R"({"type":"text","x":2,"y":3,"angle":90})"), {4, 5}); require(laidOut.size() == 2, "text baseline layout"); near(laidOut[1].x(), 2); near(laidOut[1].y(), 7); near(laidOut[1].z(), std::numbers::pi / 2);
    const auto curvedText = text_layout({{"path", circle}}, {2, 2}); require(curvedText.size() == 2 && curvedText[0].z() < 0, "circle text clockwise");
}
void standardPartTests() {
    const auto catalog = standard_part_catalog(); require(catalog.size() == 10, "standard part categories");
    int generated = 0;
    for (const auto& categoryValue : catalog) {
        const auto category = categoryValue.toObject(); const auto kind = category.value("id").toString();
        for (const auto& seriesValue : category.value("series").toArray()) {
            const auto series = seriesValue.toObject();
            for (const auto& sizeValue : series.value("sizes").toArray()) {
                const auto size = sizeValue.toObject().value("id").toString(); const auto made = make_standard_part(kind, size, {}, kind == "screw" ? series.value("id").toString() : QString());
                require(made.first.endsWith(".gform"), "standard filename extension");
                require(made.second.value("format") == "genform-document" && made.second.value("version").toInt() == 1, "standard JSON document envelope");
                const auto features = made.second.value("features").toArray(); require(!features.isEmpty() && made.second.value("serial").toInt() == features.size(), "standard feature serial");
                require(describe_document(made.second).value("kind") == "standard", "standard BOM classification");
                for (const auto& featureValue : features) {
                    const auto feature = featureValue.toObject();
                    if (feature.value("type") != "sketch") continue;
                    for (const auto& shapeValue : feature.value("params").toObject().value("shapes").toArray()) require(!prims(shapeValue.toObject()).isEmpty(), "standard sketch geometry valid");
                }
                ++generated;
            }
        }
    }
    require(generated == 211, QStringLiteral("standard generated count: %1").arg(generated));
    const auto washer = make_standard_part("washer", "M6").second; const auto shapes = washer.value("features").toArray()[0].toObject().value("params").toObject().value("shapes").toArray(); near(number(shapes[0].toObject(), "r"), 6); near(number(shapes[1].toObject(), "r"), 3.2);
    const auto screw = make_standard_part("screw", "M4", 16, "flat"); require(screw.first == "std_screw_M4x16_flat.gform", "screw filename"); near(screw.second.value("features").toArray()[1].toObject().value("params").toObject().value("length").toDouble(), 16);
    rejects([] { make_standard_part("bearing", "missing"); }); rejects([] { make_standard_part("screw", "M4", -1); }); rejects([] { make_standard_part("ball", "99"); });
    require(screw_lengths("M2").last().toInt() == 20, "screw length diameter range");
    QTextStream(stdout) << "standard_parts: " << generated << " catalog variants generated\n";
}
void proofingBoundaryTests() {
    const auto plateSketch = object(R"({"id":"s","type":"sketch","params":{"plane":"XY","shapes":[{"type":"rect","w":80,"h":50}]}})");
    const auto base = object(R"({"id":"e","type":"extrude","name":"plate","params":{"sketch":"s","distance":12},"process":{"id":"cnc3","kind":"plate","cost":20,"name":"CNC"}})");
    const auto good = object(R"({"has_body":true,"proof":{"box":[[0,0,0],[80,50,12]],"extent":[80,50],"top":[80,50],"bottom":[80,50]}})");
    const auto material = QStringLiteral("铝合金 6061");
    auto sizeReport = good; auto proof = sizeReport.value("proof").toObject(); proof["box"] = QJsonArray{QJsonArray{0, 0, 0}, QJsonArray{80, 50, 31}}; sizeReport["proof"] = proof;
    require(hasCode(proofing_checks({plateSketch, base}, sizeReport, material), "proof_size", "error"), "proof thickness maximum");
    auto twoSided = good; proof = twoSided.value("proof").toObject(); proof["top"] = QJsonArray{20, 20}; proof["bottom"] = QJsonArray{20, 20}; twoSided["proof"] = proof;
    require(hasCode(proofing_checks({plateSketch, base}, twoSided, material), "proof_two_sided", "error"), "two sided bosses");
    auto groove = object(R"({"id":"g","type":"revolve","name":"groove","params":{"axis":"Z","op":"cut"}})");
    auto grooveReport = good; grooveReport["tools"] = QJsonObject{{"g", object(R"({"box":[[5,5,3],[30,30,6]]})")}};
    require(hasCode(proofing_checks({plateSketch, base, groove}, grooveReport, material), "proof_groove", "error"), "internal ring groove");
    const auto holeSketch = object(R"({"id":"h","type":"sketch","params":{"plane":"XY","shapes":[{"type":"point","x":0,"y":0}]}})");
    auto tapped = object(R"({"id":"tap","type":"hole","name":"tap","params":{"sketch":"h","kind":"tapped","size":"M2","through":false,"depth":20,"thread":true}})");
    const auto threadedIssues = proofing_checks({holeSketch, base, tapped}, good, material);
    require(hasCode(threadedIssues, "proof_hole", "error") && hasCode(threadedIssues, "proof_thread", "warning"), "tap drill and thread depth");
    auto simple = object(R"({"id":"tap","type":"hole","name":"H7 pin","params":{"sketch":"h","kind":"simple","diameter":2,"through":true}})");
    auto throughReport = good; throughReport["tools"] = QJsonObject{{"tap", object(R"({"box":[[0,0,-1000],[2,2,1000]]})")}};
    const auto throughIssues = proofing_checks({holeSketch, base, simple}, throughReport, material);
    require(hasCode(throughIssues, "proof_hole", "warning") && !hasCode(throughIssues, "proof_hole", "error"), "through hole clipped to body depth");
    require(hasCode(throughIssues, "proof_fit", "info"), "precision bore modeling allowance");
    const auto slotSketch = object(R"({"id":"slot","type":"sketch","params":{"plane":"XY","shapes":[{"type":"rect","w":1,"h":20}]}})");
    auto slotCut = object(R"({"id":"slotcut","type":"extrude","name":"slot","params":{"sketch":"slot","distance":12,"op":"cut"}})");
    const auto narrowIssues = proofing_checks({slotSketch, base, slotCut}, good, material);
    require(hasCode(narrowIssues, "proof_slot", "error") && hasCode(narrowIssues, "proof_corner", "info"), "slot minimum and automatic corner radius");
    const auto textSketch = object(R"({"id":"t","type":"sketch","params":{"plane":"XY","shapes":[{"type":"text","x":0,"y":0,"height":1}]}})");
    const auto text = object(R"({"id":"text","type":"extrude","name":"logo","params":{"sketch":"t","distance":0.03,"op":"add"}})");
    require(hasCode(proofing_checks({textSketch, base, text}, good, material), "proof_silk", "warning"), "silk emboss is not machining");
    auto engraved = text; auto params = engraved.value("params").toObject(); params["op"] = "cut"; engraved["params"] = params;
    require(hasCode(proofing_checks({textSketch, base, engraved}, good, material), "proof_text", "warning"), "small engraved text");
    const auto chamfer = object(R"({"id":"c","type":"chamfer","params":{"distance":0.6}})");
    require(hasCode(proofing_checks({base, chamfer}, good, material), "proof_chamfer", "warning"), "chamfer limit");
    auto turned = base; turned["type"] = "revolve"; turned["process"] = object(R"({"id":"turning"})");
    const auto latheReport = object(R"({"has_body":true,"proof":{"box":[[0,0,0],[10,10,25]]}})");
    require(hasCode(proofing_checks({turned}, latheReport, QStringLiteral("不锈钢 304")), "proof_lathe", "info"), "lathe valid envelope");
    require(hasCode(proofing_checks({turned}, latheReport, material), "proof_lathe", "warning"), "lathe material restriction");
    auto bought = base; bought["process"] = object(R"({"id":"standard"})");
    require(hasCode(proofing_checks({bought}, good, material), "proof_skip", "info"), "bought part skips proofing");
    const QJsonArray checkedFeatures{slotSketch, object(R"({"id":"slotcut","type":"extrude","name":"slot","params":{"sketch":"slot","distance":12,"op":"cut"},"process":{"id":"cnc3","name":"CNC","kind":"pocket_cut","cost":30}})")};
    require(hasCode(design_checks(checkedFeatures, {{"status", QJsonObject{{"slotcut", "ok"}}}}, good, {}, material), "sharp_corner", "warning"), "CNC sharp internal corner");
    const auto thin = object(R"({"id":"thin","type":"extrude","params":{"sketch":"s","distance":0.2},"process":{"id":"laser","kind":"plate","name":"laser","cost":1}})");
    auto thinReport = good; thinReport["tools"] = QJsonObject{{"thin", object(R"({"size":[0.2,50,80],"thickness":0.2,"area":8000,"volume":800})")}};
    const auto thinIssues = design_checks({plateSketch, thin}, {{"status", QJsonObject{{"thin", "ok"}}}}, thinReport, {}, material);
    require(hasCode(thinIssues, "thin_wall", "warning") && hasCode(thinIssues, "process_infeasible", "error"), "wall and process feasibility");
    require(hasCode(design_checks({plateSketch, base}, {{"status", QJsonObject{{"e", "ok"}}}}, good, {{"proofing", 1}}, material), "proof_summary"), "design proofing integration");
    rejects([] { moved(object(R"({"type":"circle","r":1})"), std::numeric_limits<double>::infinity(), 0); });
    rejects([] { offset(object(R"({"type":"circle","r":1})"), std::numeric_limits<double>::quiet_NaN()); });
}
void assemblyTests() {
    const QStringList names{QStringLiteral("甲"), QStringLiteral("乙"), QStringLiteral("螺栓"), QStringLiteral("盖板")};
    const QJsonArray pairs{object(R"({"a":0,"b":2,"kind":"touch"})"), object(R"({"a":1,"b":2,"kind":"touch"})"), object(R"({"a":0,"b":3,"kind":"touch"})")};
    const auto lonely = fasteners(pairs, {"custom", "custom", "standard", "standard"}, names);
    require(lonely.size() == 1 && lonely[0].toObject().value("features").toArray() == QJsonArray{"part:3"}, "lonely fastener");
    const auto corrosion = galvanic({object(R"({"a":0,"b":1,"kind":"touch","point":[0,0,0]})"), object(R"({"a":1,"b":0,"kind":"clash"})")}, {QStringLiteral("铝合金 6061"), QStringLiteral("不锈钢 304")}, names);
    require(corrosion.size() == 1 && hasCode(corrosion, "galvanic"), "galvanic grouped");
    require(galvanic({object(R"({"a":0,"b":1,"kind":"gap"})")}, {QStringLiteral("铝合金 6061"), QStringLiteral("不锈钢 304")}, names).isEmpty(), "noncontact galvanic ignored");
    const auto buried = orphans({object(R"({"a":0,"b":2,"kind":"clash","volume":30})")}, {"custom", "custom", "standard"}, names, {object(R"({"volume":1000})"), object(R"({"volume":1000})"), object(R"({"volume":100})")}); require(hasCode(buried, "orphan", "error"), "orphan threshold");
    const auto repeated = duplicates({object(R"({"name":"A","path":"a","move":[0,0,0]})"), object(R"({"name":"B","path":"a","move":[0.0004,0,0]})"), object(R"({"name":"C","path":"a","move":[1,0,0]})")}); require(repeated.size() == 1, "duplicate placement rounded to .001");
    const auto gaps = bill_gaps({object(R"({"name":"lamp","kind":"purchase","unit":0,"indices":[3]})"), object(R"({"name":"bolt","kind":"standard","unit":2,"spec":"","indices":[5]})")}); require(hasCode(gaps, "no_price") && hasCode(gaps, "no_spec"), "BOM gaps");
    const QJsonArray props{object(R"({"volume":1000000,"centre":[0,0,0]})"), object(R"({"volume":1000000,"centre":[0,300,0]})"), object(R"({"volume":5,"centre":[0,0,0]})")};
    const auto mass = mass_issues(props, {QStringLiteral("普通碳钢"), QStringLiteral("普通碳钢"), ""}, {QStringLiteral("甲"), QStringLiteral("乙"), QStringLiteral("没材质的")}, {1000, 1000, 500}); require(hasCode(mass, "mass") && hasCode(mass, "off_centre"), "mass and balance"); require(mass[0].toObject().value("title").toString().contains("15.7 kg"), "mass units");
    const auto motion = motion_issues({object(R"({"joint":0,"value":32.5,"a":1,"b":0,"names":["door","body"],"depth":3,"point":[1,2,3]})")}, {QStringLiteral("左车门")}, {QStringLiteral("°")}); require(motion[0].toObject().value("title").toString() == QStringLiteral("运动干涉：左车门 开到 32.5°"), "motion format");
}
void manufacturingTests() {
    const auto sketch = object(R"({"id":"s","type":"sketch","params":{"plane":"XY","shapes":[{"type":"rect","w":100,"h":60}]}})");
    const auto feature = object(R"({"id":"e","type":"extrude","name":"板","params":{"sketch":"s","distance":3}})");
    const auto metrics = object(R"({"size":[3,60,100],"volume":18000,"area":12960,"thickness":3,"solids":1,"faces":{"plane":6}})");
    const QJsonObject byId{{"s", sketch}, {"e", feature}};
    rejects([&] { choose_process(feature, {}, byId); });
    require(process_catalog().size() == 34, "process catalog count");
    const auto single = choose_process(feature, metrics, byId); require(single.value("id") == "laser", "one plate laser cut");
    const auto many = choose_process(feature, metrics, byId, 200000); require(many.value("id") != "laser" && many.value("id") != "waterjet", "batch cost favors tooling");
    const double materialCost = 18 * 7.85 / 1000 * 7 * 1.25;
    const double laserCost = materialCost + (6.4 * std::sqrt(12960. / 2) / (9000. / 4) / 60 + .08) * 300;
    near(single.value("cost").toDouble(), std::nearbyint(laserCost * 100) / 100, 1e-8);
    auto shaft = feature; shaft["type"] = "revolve"; shaft["name"] = QStringLiteral("轴");
    require(choose_process(shaft, object(R"({"size":[20,20,40],"volume":10000,"area":4000})"), byId).value("id") == "turning", "revolved turning");
    auto holeSketch = sketch; auto params = holeSketch.value("params").toObject(); params["shapes"] = QJsonArray{object(R"({"type":"circle","r":4})")}; holeSketch["params"] = params;
    auto hole = feature; params = hole.value("params").toObject(); params["op"] = "cut"; params["distance"] = 20; hole["params"] = params; hole["name"] = QStringLiteral("螺栓孔");
    require(choose_process(hole, object(R"({"size":[8,8,20],"volume":1000,"area":1000})"), {{"s", holeSketch}}).value("id") == "drill", "cut ignores bought name hint");
    auto boltSketch = sketch; params = boltSketch.value("params").toObject(); params["shapes"] = QJsonArray{object(R"({"type":"ngon","r":6,"sides":6})")}; boltSketch["params"] = params;
    auto bolt = feature; bolt["name"] = QStringLiteral("螺栓"); const auto bought = choose_process(bolt, metrics, {{"s", boltSketch}}); require(bought.value("id") == "standard" && bought.value("spec").toString().contains("M6"), "standard hex bolt");
    auto skin = feature; params = skin.value("params").toObject(); params["op"] = "void"; skin["params"] = params;
    require(choose_process(skin, object(R"({"size":[296,396,596],"volume":69800000,"area":1060000})"), byId, 1, {}, true).value("id") == "hand_form", "one hollow skin hand formed");
    auto manual = feature; auto process = single; process["auto"] = false; process["id"] = "waterjet"; manual["process"] = process;
    const auto mirror = object(R"({"id":"m","type":"mirror","params":{"features":["e"]}})");
    const auto bound = bind_processes({sketch, manual, mirror}, {{"tools", QJsonObject{{"e", metrics}}}});
    require(bound.value("e").toObject().value("id") == "waterjet" && bound.value("m").toObject().value("id") == "waterjet", "manual choice and mirror inheritance"); require(!bound.contains("s"), "sketch not bound");
    auto badExpression = feature; params = badExpression.value("params").toObject(); params["distance"] = "=height"; badExpression["params"] = params;
    rejects([&] { choose_process(badExpression, metrics, byId); });
    auto boundFeature = feature; boundFeature["process"] = single;
    const auto report = object(R"({"has_body":true,"valid":false,"voids":1,"bodies":[{"volume":1000,"features":["e"],"center":[0,0,0]},{"volume":50,"features":["lost"],"center":[0,0,10]}],"pairs":[{"kind":"gap","a":"e","b":"lost","value":0.2,"point":[0,0,3]}]})");
    const auto checked = design_checks({sketch, boundFeature}, {{"status", QJsonObject{{"e", "ok"}}}}, report);
    require(hasCode(checked, "invalid_body") && hasCode(checked, "floating") && hasCode(checked, "gap") && hasCode(checked, "no_material") && hasCode(checked, "cost"), "design issue coverage"); require(red_features(checked).contains("lost"), "red feature IDs");
    auto unresolvedFeature = boundFeature; unresolvedFeature["params"] = object(R"({"distance":"=x"})");
    require(hasCode(design_checks({unresolvedFeature}, {{"status", QJsonObject{{"e", "ok"}}}}, {}), "feature_error", "error"), "unresolved checks fail explicitly");
    require(issue_summary(checked).value("error").toInt() >= 3, "issue severity summary");
    const auto proofReport = object(R"({"has_body":true,"proof":{"box":[[0,0,0],[100,60,3]],"extent":[100,60],"top":[100,60],"bottom":[100,60]}})");
    const auto proof = proofing_checks({sketch, boundFeature}, proofReport, QStringLiteral("铝合金 6061"));
    require(!hasCode(proof, "proof_size") && !hasCode(proof, "proof_material") && hasCode(proof, "proof_summary"), "valid proofing metrics");
    require(hasCode(proofing_checks({}, {{"has_body", true}}, QStringLiteral("铝合金 6061")), "proof_incomplete", "warning"), "missing proof metrics not success");
    require(hasCode(proofing_checks({sketch, boundFeature}, proofReport, "ABS"), "proof_material", "error"), "proofing material restriction");
    auto fineHoleSketch = holeSketch; params = fineHoleSketch.value("params").toObject(); params["shapes"] = QJsonArray{object(R"({"type":"circle","r":0.5})")}; fineHoleSketch["params"] = params;
    require(hasCode(proofing_checks({fineHoleSketch, hole}, proofReport, QStringLiteral("铝合金 6061")), "proof_hole", "error"), "proofing small hole");
}
}

int main(int argc, char** argv) {
    QCoreApplication application(argc, argv);
    try {
        geometryTests(); propertyTests(); editingTests(); assemblyTests(); manufacturingTests(); proofingBoundaryTests(); standardPartTests();
        QTextStream(stdout) << "domain_tests: " << checks << " checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        QTextStream(stderr) << "domain_tests failed after " << checks << " checks: " << error.what() << '\n';
        return 1;
    }
}
