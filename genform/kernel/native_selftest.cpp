#ifdef GENFORM_KERNEL_SELFTEST
#include "native.hpp"
#include "kernel.hpp"
#include <QCoreApplication>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QTemporaryDir>
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
using genform::kernel::Kernel;
void require(bool condition, const char *message) { if (!condition) throw std::runtime_error(message); }
void close(double value, double expected, double tolerance = 1e-4) { require(std::abs(value - expected) <= tolerance, "Unexpected geometric result"); }
QJsonObject feature(const QString &id, const QString &type, const QJsonObject &params) { return {{"id", id}, {"type", type}, {"params", params}}; }
QJsonArray plate() {
    return {feature("sketch", "sketch", {{"plane", "XY"}, {"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"w", 20}, {"h", 10}}}}}),
            feature("extrude", "extrude", {{"sketch", "sketch"}, {"distance", 5}})};
}
double bodyVolume(const QJsonObject &result) { return result["props"].toObject()["volume"].toDouble(); }
void ok(const QJsonObject &result, const QString &id) {
    const QString status = result["status"].toObject()[id].toString();
    if (status != "ok") throw std::runtime_error((id + ": " + status).toStdString());
}
}

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    try {
        using namespace genform::kernel::native;
        close(evaluate("-2^2 + 2**3**2"), 508);
        close(evaluate("sqrt(9)+sin(pi/2)+max(2,7)-(-3)%2"), 10);
        Kernel kernel;
        require(!kernel.build({})["has_body"].toBool(), "Empty document must succeed");
#ifndef GENFORM_HAS_OCCT
        require(!Kernel::available(), "SDK availability must be false");
        bool dependency = false;
        try { kernel.build(plate()); } catch (const std::exception &error) { dependency = QString::fromUtf8(error.what()).contains("OpenCascade C++ SDK"); }
        require(dependency, "Geometry without SDK must raise a dependency error");
        QJsonArray suppressed{QJsonObject{{"id", "hidden"}, {"type", "sketch"}, {"suppressed", true}}};
        require(kernel.build(suppressed)["status"].toObject()["hidden"] == "suppressed", "Suppressed feature should not require SDK");
        std::cout << "PASS expression, empty document, SDK error, suppressed feature\n";
#else
        require(Kernel::available(), "SDK availability must be true");
        auto result = kernel.build(plate()); ok(result, "extrude"); close(bodyVolume(result), 1000);
        require(result["faces"].toArray().size() == 6 && result["edges"].toArray().size() == 12, "Box topology mismatch");
        require(result["verts"].toArray().size() == result["normals"].toArray().size(), "Normals alignment mismatch");
        require(result["tris"].toArray().size() == result["tri_face"].toArray().size(), "Face attribution mismatch");
        const auto originalVolume = bodyVolume(result);
        auto previewFeatures = plate(); auto enlarged = previewFeatures[1].toObject(); enlarged["params"] = QJsonObject{{"sketch", "sketch"}, {"distance", 10}}; previewFeatures[1] = enlarged;
        require(!kernel.preview(previewFeatures)["verts"].toArray().isEmpty(), "Preview must contain triangles");
        close(kernel.query("properties")["volume"].toDouble(), originalVolume);
        auto holeFeatures = plate();
        holeFeatures.append(feature("locations", "sketch", {{"offset", 5}, {"shapes", QJsonArray{QJsonObject{{"type", "point"}, {"x", 0}, {"y", 0}}}}}));
        holeFeatures.append(feature("hole", "hole", {{"sketch", "locations"}, {"diameter", 2}, {"through", true}}));
        result = kernel.build(holeFeatures); ok(result, "hole"); close(bodyVolume(result), 1000 - 5 * pi, 1e-3);
        auto filletFeatures = plate(); filletFeatures.append(feature("fillet", "fillet", {{"radius", 0.5}, {"edges", "|Z"}}));
        result = kernel.build(filletFeatures); ok(result, "fillet"); require(bodyVolume(result) < 1000, "Fillet must remove material");
        auto chamferFeatures = plate(); chamferFeatures.append(feature("chamfer", "chamfer", {{"distance", 0.5}, {"edges", ">Z"}}));
        result = kernel.build(chamferFeatures); ok(result, "chamfer"); require(bodyVolume(result) < 1000, "Chamfer must remove material");
        auto patternFeatures = plate(); patternFeatures.append(feature("pattern", "pattern_linear", {{"axis1", "X"}, {"count1", 3}, {"spacing1", 30}, {"count2", 1}, {"spacing2", 0}}));
        result = kernel.build(patternFeatures); ok(result, "pattern"); close(bodyVolume(result), 3000); require(result["props"].toObject()["bodies"].toInt() == 3, "Pattern solid count mismatch");
        auto ringFeatures = plate(); auto ringSketch = ringFeatures[0].toObject(); ringSketch["params"] = QJsonObject{{"shapes", QJsonArray{QJsonObject{{"type", "circle"}, {"r", 5}}, QJsonObject{{"type", "circle"}, {"r", 2}}}}}; ringFeatures[0] = ringSketch;
        result = kernel.build(ringFeatures); ok(result, "extrude"); close(bodyVolume(result), pi * 21 * 5, 1e-3);
        QJsonArray revolveFeatures{feature("profile", "sketch", {{"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"cx", 5}, {"w", 2}, {"h", 4}}}}}), feature("revolve", "revolve", {{"sketch", "profile"}, {"axis", "SY"}, {"angle", 360}})};
        result = kernel.build(revolveFeatures); ok(result, "revolve"); close(bodyVolume(result), 80 * pi, 1e-3);
        auto failedFeatures = plate(); failedFeatures.append(feature("bad", "extrude", {{"sketch", "missing"}, {"distance", 1}})); failedFeatures.append(feature("later", "extrude", {{"sketch", "sketch"}, {"distance", 2}}));
        result = kernel.build(failedFeatures); require(result["status"].toObject()["bad"].toString().startsWith("error: "), "Failure must be recorded"); require(result["status"].toObject()["later"] == "skipped", "Later feature must be skipped"); close(bodyVolume(result), 1000);
        result = kernel.build(plate(), 1); require(!result["has_body"].toBool() && result["status"].toObject()["extrude"] == "skipped", "Rollback semantics mismatch");
        QJsonArray variableFeatures{feature("vars", "variables", {{"values", QJsonObject{{"width", 20}, {"height", "=width/2"}}}})};
        auto variablePlate = plate(); auto variableSketch = variablePlate[0].toObject(); variableSketch["params"] = QJsonObject{{"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"w", "=width"}, {"h", "=height"}}}}}; variablePlate[0] = variableSketch; for (const auto &value : variablePlate) variableFeatures.append(value);
        result = kernel.build(variableFeatures); ok(result, "extrude"); close(bodyVolume(result), 1000);
        const auto measured = kernel.query("measure", {{"items", QJsonArray{QJsonObject{{"kind", "vertex"}, {"id", 0}}, QJsonObject{{"kind", "vertex"}, {"id", 1}}}}}); require(measured.contains("distance"), "Measurement missing distance");
        QTemporaryDir temporary; require(temporary.isValid(), "Cannot create temporary export folder");
        for (const auto &extension : {QString("step"), QString("stl"), QString("brep")}) { const QString file = temporary.path() + "/solid." + extension; kernel.exportFile(file); require(QFileInfo(file).size() > 0, "Export file is empty"); }
        Kernel imported; auto importedModel = imported.build(QJsonArray{feature("import", "import_step", {{"path", temporary.path() + "/solid.step"}})}); ok(importedModel, "import"); close(bodyVolume(importedModel), 1000, 1e-3);
        QJsonArray hollowFeatures = plate();
        hollowFeatures.append(feature("inside", "sketch", {{"offset", 1}, {"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"w", 16}, {"h", 6}}}}}));
        hollowFeatures.append(feature("void", "extrude", {{"sketch", "inside"}, {"distance", 3}, {"op", "void"}}));
        result = kernel.build(hollowFeatures); ok(result, "void"); close(bodyVolume(result), 712);
        hollowFeatures.append(feature("fill", "extrude", {{"sketch", "inside"}, {"distance", 1}, {"op", "fill"}}));
        result = kernel.build(hollowFeatures); ok(result, "fill"); close(bodyVolume(result), 808);
        auto pocketFeatures = hollowFeatures; pocketFeatures.append(feature("pocket_sketch", "sketch", {{"offset", 5}, {"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"w", 4}, {"h", 2}}}}})); pocketFeatures.append(feature("pocket", "extrude", {{"sketch", "pocket_sketch"}, {"distance", 2}, {"reverse", true}, {"op", "pocket"}, {"wall", .5}}));
        result = kernel.build(pocketFeatures); ok(result, "pocket"); require(bodyVolume(result) > 0, "Pocket must preserve the hollow body");
        auto closedShellFeatures = plate(); closedShellFeatures.append(feature("shell", "shell", {{"thickness", 1}})); result = kernel.build(closedShellFeatures); ok(result, "shell"); close(bodyVolume(result), 568, 1e-3);
        auto shellFeatures = plate(); shellFeatures.append(feature("shell", "shell", {{"thickness", 1}, {"faces", QJsonArray{QJsonObject{{"point", QJsonArray{0, 0, 5}}}}}}));
        result = kernel.build(shellFeatures); ok(result, "shell"); require(bodyVolume(result) < 1000 && bodyVolume(result) > 0, "Shell must form a hollow body");
        QJsonArray loftFeatures{feature("first", "sketch", {{"shapes", QJsonArray{QJsonObject{{"type", "circle"}, {"r", 3}}}}}), feature("second", "sketch", {{"offset", 10}, {"shapes", QJsonArray{QJsonObject{{"type", "circle"}, {"r", 1}}}}}), feature("loft", "loft", {{"sketches", QJsonArray{"first", "second"}}})};
        result = kernel.build(loftFeatures); ok(result, "loft"); close(bodyVolume(result), 130 * pi / 3, 1e-3);
        QJsonArray screwFeatures{feature("locations", "sketch", {{"shapes", QJsonArray{QJsonObject{{"type", "point"}, {"x", 0}, {"y", 0}}}}}), feature("screw", "screw", {{"sketch", "locations"}, {"size", "M3"}, {"head", "cap"}, {"length", 4}})};
        result = kernel.build(screwFeatures); ok(result, "screw"); require(bodyVolume(result) > 50, "Screw must contain real solid geometry");
        QJsonArray textFeatures{feature("text", "sketch", {{"shapes", QJsonArray{QJsonObject{{"type", "text"}, {"text", "A"}, {"font", "Arial"}, {"height", 5}, {"x", 0}, {"y", 0}}}}}), feature("raised", "extrude", {{"sketch", "text"}, {"distance", 1}})};
        result = kernel.build(textFeatures); ok(result, "raised"); require(bodyVolume(result) > 0, "Text must produce extrudable glyph faces");
        auto threadedScrew = screwFeatures; auto threadedFeature = threadedScrew[1].toObject(); auto threadParams = threadedFeature["params"].toObject(); threadParams["thread"] = true; threadedFeature["params"] = threadParams; threadedScrew[1] = threadedFeature;
        const double plainScrewVolume = bodyVolume(kernel.build(screwFeatures));
        result = kernel.build(threadedScrew); ok(result, "screw"); require(bodyVolume(result) > 0 && bodyVolume(result) < plainScrewVolume - 1e-4, "Modeled thread must remove actual material");
        QJsonArray sweepFeatures{feature("profile", "sketch", {{"shapes", QJsonArray{QJsonObject{{"type", "circle"}, {"r", 1}}}}}), feature("path", "sketch3d", {{"points", QJsonArray{QJsonArray{0, 0, 0}, QJsonArray{0, 0, 10}}}}), feature("sweep", "sweep", {{"sketch", "profile"}, {"path", "path"}})};
        result = kernel.build(sweepFeatures); ok(result, "sweep"); close(bodyVolume(result), pi * 10, 1e-3);
        auto splitFeatures = plate(); splitFeatures.append(feature("split_sketch", "sketch", {{"shapes", QJsonArray{QJsonObject{{"type", "line"}, {"x1", -20}, {"y1", 0}, {"x2", 20}, {"y2", 0}}}}})); splitFeatures.append(feature("split", "split", {{"sketch", "split_sketch"}}));
        result = kernel.build(splitFeatures); ok(result, "split"); close(bodyVolume(result), 1000); require(result["faces"].toArray().size() > 6, "Split must add real face topology");
        auto curveFeatures = plate(); curveFeatures.append(feature("surface_curve", "curve_surface", {{"faces", QJsonArray{QJsonObject{{"point", QJsonArray{0, 0, 5}}}}}, {"points", QJsonArray{QJsonArray{.2,.2}, QJsonArray{.8,.8}}}}));
        result = kernel.build(curveFeatures); ok(result, "surface_curve"); require(!result["sketches"].toObject()["surface_curve"].toArray().isEmpty(), "Surface curve must have display edges");
        auto circular = plate(); circular.append(feature("circle_pattern", "pattern_circular", {{"axis", "@40,0,0;0,0,1"}, {"count", 3}, {"angle", 360}}));
        result = kernel.build(circular); ok(result, "circle_pattern"); close(bodyVolume(result), 3000);
        auto variablePattern = plate(); variablePattern.append(feature("variable_pattern", "pattern_variable", {{"features", QJsonArray{"extrude"}}, {"rows", "30,0,0,distance=2;60,0,0,distance=3"}}));
        result = kernel.build(variablePattern); ok(result, "variable_pattern"); close(bodyVolume(result), 2000);
        auto fillPattern = plate(); fillPattern.append(feature("fill_boundary", "sketch", {{"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"w", 18}, {"h", 8}}}}})); fillPattern.append(feature("fill_pattern", "pattern_fill", {{"sketch", "fill_boundary"}, {"spacing", 5}, {"margin", 1}, {"diameter", 1}}));
        result = kernel.build(fillPattern); ok(result, "fill_pattern"); require(bodyVolume(result) < 1000, "Fill pattern must cut real holes");
        result = kernel.build(plate()); const auto report = kernel.query("inspect"); require(report["valid"].toBool() && report["bodies"].toArray().size() == 1 && report["tools"].toObject().contains("extrude"), "Inspect report mismatch");
        const auto section = kernel.query("section", {{"plane", "XY"}, {"offset", 2}}); require(!section["lines"].toArray().isEmpty(), "Section should intersect the box");
        kernel.build(sweepFeatures); const auto silhouette = kernel.query("silhouette", {{"plane", "XZ"}}); require(!silhouette["lines"].toArray().isEmpty(), "Cylinder silhouette should contain outlines");
        auto midFeatures = plate(); auto midFeature = midFeatures[1].toObject(); midFeature["params"] = QJsonObject{{"sketch", "sketch"}, {"distance", 5}, {"end", "mid"}}; midFeatures[1] = midFeature;
        result = kernel.build(midFeatures); ok(result, "extrude"); close(result["props"].toObject()["bbox_min"].toArray()[2].toDouble(), -2.5); close(bodyVolume(result), 1000);
        QJsonArray lines;
        for (const auto &coordinates : QJsonArray{QJsonArray{-5,-3,5,-3}, QJsonArray{5,3,5,-3}, QJsonArray{-5,3,5,3}, QJsonArray{-5,-3,-5,3}}) { const auto row = coordinates.toArray(); lines.append(QJsonObject{{"type", "line"}, {"x1", row[0]}, {"y1", row[1]}, {"x2", row[2]}, {"y2", row[3]}}); }
        QJsonArray lineFeatures{feature("lines", "sketch", {{"shapes", lines}}), feature("extrude", "extrude", {{"sketch", "lines"}, {"distance", 2}})};
        result = kernel.build(lineFeatures); ok(result, "extrude"); close(bodyVolume(result), 120);
        for (const auto &primitive : QJsonArray{QJsonObject{{"type", "slot"}, {"x1", -2}, {"y1", 0}, {"x2", 2}, {"y2", 0}, {"w", 2}}, QJsonObject{{"type", "arcslot"}, {"r", 5}, {"w", 2}, {"a0", 0}, {"a1", 90}}, QJsonObject{{"type", "ellipse"}, {"rx", 3}, {"ry", 2}}}) {
            result = kernel.build(QJsonArray{feature("profile", "sketch", {{"shapes", QJsonArray{primitive}}}), feature("solid", "extrude", {{"sketch", "profile"}, {"distance", 1}})}); ok(result, "solid"); require(bodyVolume(result) > 0, "Primitive should form a solid");
        }
        result = kernel.build(QJsonArray{feature("cw", "sketch", {{"shapes", QJsonArray{QJsonObject{{"type", "polygon"}, {"points", QJsonArray{QJsonArray{0,0}, QJsonArray{0,2}, QJsonArray{3,2}, QJsonArray{3,0}}}}}}}), feature("solid", "extrude", {{"sketch", "cw"}, {"distance", 2}})}); ok(result, "solid"); close(bodyVolume(result), 12);
        auto threadHoleFeatures = holeFeatures; auto holeFeature = threadHoleFeatures[3].toObject(); holeFeature["params"] = QJsonObject{{"sketch", "locations"}, {"diameter", 3}, {"size", "M3"}, {"kind", "tapped"}, {"through", false}, {"depth", 2}, {"thread", true}}; threadHoleFeatures[3] = holeFeature;
        result = kernel.build(threadHoleFeatures); ok(result, "hole"); require(bodyVolume(result) < 1000 - pi * std::pow((3 - 1.082532 * .5) / 2, 2) * 2 - 1e-4, "Tapped thread must remove more than its pilot hole");
        auto draftFeatures = plate(); draftFeatures.append(feature("draft", "draft", {{"faces", QJsonArray{QJsonObject{{"point", QJsonArray{10, 0, 2.5}}}}}, {"plane", "XY"}, {"angle", 2}})); result = kernel.build(draftFeatures); ok(result, "draft"); require(std::abs(bodyVolume(result) - 1000) > 1e-3, "Draft must modify the real body");
        QJsonArray wrapFeatures{feature("circle", "sketch", {{"shapes", QJsonArray{QJsonObject{{"type", "circle"}, {"r", 5}}}}}), feature("cylinder", "extrude", {{"sketch", "circle"}, {"distance", 10}}), feature("sticker", "sketch", {{"plane", QJsonObject{{"origin", QJsonArray{5,0,5}}, {"x", QJsonArray{0,1,0}}, {"y", QJsonArray{0,0,1}}}}, {"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"w", 2}, {"h", 2}}}}}), feature("wrap", "wrap", {{"sketch", "sticker"}, {"faces", QJsonArray{QJsonObject{{"point", QJsonArray{0,0,5}}}}}, {"depth", .5}, {"mode", "emboss"}})};
        result = kernel.build(wrapFeatures); ok(result, "wrap"); require(bodyVolume(result) > pi * 250, "Wrap emboss must add actual material");
        std::cout << "PASS expressions, empty, extrude, mesh/topology, preview isolation, hole, fillet, chamfer, pattern, nested profiles, revolve, failure/rollback, variables, measurement, STEP/STL/BREP export, void/fill, shell, loft, screw, text, modeled thread\n";
        std::cout << "PASS sweep, split, UV surface curve, circular/variable/fill patterns\n";
        std::cout << "PASS STEP roundtrip, inspect, section/silhouette, mid-plane, unordered line loops, slot/arcslot/ellipse, modeled tapped hole, pocket, closed shell, draft, wrap\n";
#endif
        return 0;
    } catch (const std::exception &error) { std::cerr << "FAIL: " << error.what() << '\n'; return 1; }
}
#endif
