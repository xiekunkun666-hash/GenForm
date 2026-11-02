#include "genform/assembly/engine.hpp"
#include "genform/kernel/kernel.hpp"
#include <QCoreApplication>
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QJsonDocument>
#include <QTemporaryDir>
#include <cmath>
#include <functional>
#include <iostream>
#include <stdexcept>

namespace {
using genform::assembly::Engine;
void require(bool condition, const char *message) { if (!condition) throw std::runtime_error(message); }
void close(double value, double expected, double tolerance = 1e-4) { require(std::abs(value - expected) <= tolerance, "Unexpected numeric result"); }
void rejects(const std::function<void()> &operation, const char *message) {
    bool rejected = false;
    try { operation(); } catch (const std::exception &) { rejected = true; }
    require(rejected, message);
}
QJsonArray plate(double width = 20, double height = 10, double depth = 5) {
    return {QJsonObject{{"id", "sketch"}, {"type", "sketch"}, {"params", QJsonObject{{"plane", "XY"}, {"shapes", QJsonArray{QJsonObject{{"type", "rect"}, {"w", width}, {"h", height}}}}}}},
            QJsonObject{{"id", "extrude"}, {"type", "extrude"}, {"params", QJsonObject{{"sketch", "sketch"}, {"distance", depth}}}}};
}
QJsonObject part(const QString &name, double x = 0, double y = 0, double z = 0) {
    return {{"name", name}, {"move", QJsonArray{x, y, z}}, {"turn", QJsonArray{0, 0, 0}}};
}
void writeJson(const QString &path, const QJsonObject &value) {
    QFile file(path);
    require(file.open(QIODevice::WriteOnly), "Cannot write test document");
    const auto data = QJsonDocument(value).toJson();
    require(file.write(data) == data.size(), "Test document short write");
}

void dataTests() {
    Engine engine;
    const QJsonObject assembly{{"format", "genform-assembly"}, {"version", 1},
        {"params", QJsonObject{{"height", 10}, {"above", "=height+5"}}},
        {"parts", QJsonArray{QJsonObject{{"name", "base"}, {"file", "parts/base.gform"}, {"move", QJsonArray{2, 3, "=height"}}}, part("moving", 9, 8, 7)}},
        {"mates", QJsonArray{QJsonObject{{"kind", "coaxial"}, {"part", 1}, {"to", 0}, {"axis", "Z"}},
                             QJsonObject{{"kind", "offset"}, {"part", 1}, {"to", 0}, {"axis", "Z"}, {"value", "=above"}}}}};
    const auto resolved = engine.setAssembly(assembly, QDir::tempPath());
    const auto parts = resolved["parts"].toArray();
    require(QFileInfo(parts[0].toObject()["path"].toString()).isAbsolute(), "Relative part path was not resolved");
    const auto move = parts[1].toObject()["move"].toArray();
    close(move[0].toDouble(), 2); close(move[1].toDouble(), 3); close(move[2].toDouble(), 25);
    rejects([&] { genform::assembly::resolveAssembly({{"parts", QJsonArray{}}, {"params", QJsonObject{{"a", "=b"}, {"b", "=a"}}}}); }, "Cyclic parameters must fail");
    const QJsonArray components{part("base"), part("door", 10)};
    QJsonObject hinge{{"name", "door"}, {"kind", "hinge"}, {"origin", QJsonArray{0, 0, 0}}, {"axis", QJsonArray{0, 0, 1}},
        {"parts", QJsonArray{1}}, {"base", 0}, {"min", 0}, {"max", 90}};
    const auto opened = genform::assembly::pose(components, QJsonArray{hinge}, 1.6);
    const auto matrix = opened["matrices"].toArray()[1].toArray();
    close(matrix[0].toArray()[3].toDouble(), 0); close(matrix[1].toArray()[3].toDouble(), 10);
    close(genform::assembly::pose(components, QJsonArray{hinge}, 4)["values"].toArray()[0].toDouble(), 0);
    hinge["speed"] = 90;
    const auto samples = genform::assembly::motionSamples(components, QJsonArray{hinge});
    require(samples["joints"].toArray()[0].toObject()["poses"].toArray().size() == 8, "Continuous rotation sampling missing");
    auto parent = hinge;
    parent["parts"] = QJsonArray{};
    hinge["on"] = 0;
    hinge["speed"] = -180;
    const auto nested = genform::assembly::pose(components, QJsonArray{parent, hinge}, 1);
    close(nested["values"].toArray()[0].toDouble(), 90);
    close(nested["values"].toArray()[1].toDouble(), -180);
    hinge["on"] = 1;
    rejects([&] { genform::assembly::pose(components, QJsonArray{parent, hinge}); }, "Cyclic joint must fail");
    auto mirrored = part("mirror", 1, 2, 3);
    mirrored["mirror"] = true;
    mirrored["turn"] = QJsonArray{90, 0, 90};
    mirrored["swing"] = QJsonObject{{"origin", QJsonArray{0, 0, 0}}, {"axis", QJsonArray{0, 0, 2}}, {"slide", 4},
        {"then", QJsonObject{{"origin", QJsonArray{0, 0, 0}}, {"axis", QJsonArray{1, 0, 0}}, {"slide", 5}}}};
    const auto transform = genform::assembly::pose(QJsonArray{mirrored}, {})["matrices"].toArray()[0].toArray();
    close(transform[0].toArray()[3].toDouble(), 6); close(transform[1].toArray()[3].toDouble(), 2); close(transform[2].toArray()[3].toDouble(), 7);
    std::cout << "PASS paths, parameter formulas, mates, hinge and slide chains, playback, continuous sampling, cycle errors\n";
}

void modelFileTests(const QString &directory) {
    QDirIterator files(directory, QStringList{"*.gasm"}, QDir::Files, QDirIterator::Subdirectories);
    int count = 0;
    while (files.hasNext()) {
        const QString path = files.next();
        Engine engine;
        const auto loaded = engine.load(path);
        const auto parts = loaded["parts"].toArray();
        require(!parts.isEmpty(), "Real GASM unexpectedly empty");
        for (const auto &entry : parts) {
            const QString source = entry.toObject()["path"].toString();
            require(QFileInfo(source).isAbsolute() && QFileInfo(source).exists(), "Real GASM relative source missing");
        }
        const auto bill = engine.query("bom");
        require(bill["totals"].toObject()["all"].toObject()["count"].toInt() == parts.size(), "Real GASM BOM count mismatch");
        const auto positioned = engine.query("pose", {{"seconds", 0.73}});
        require(positioned["parts"].toArray().size() == parts.size(), "Real GASM pose count mismatch");
        if (!loaded["joints"].toArray().isEmpty()) require(!engine.query("motion_samples")["joints"].toArray().isEmpty(), "Real GASM sampling missing");
        ++count;
    }
    require(count > 0, "No real GASM files tested");
    std::cout << "PASS " << count << " repository GASM files: paths, BOM, joint validation, pose and sampling\n";
}

#ifdef GENFORM_HAS_OCCT
QJsonObject threadFeature(const QString &id, const QString &type, const QJsonObject &params) {
    return {{"id", id}, {"name", id}, {"type", type}, {"params", params}};
}

QJsonObject tappedDocument(bool modeled = true, const QString &material = {}, bool through = false,
                          double phase = 0, bool opposite = false, const QJsonArray &spots = {}) {
    auto features = plate(30, 30, 10);
    const auto points = spots.isEmpty() ? QJsonArray{QJsonObject{{"type", "point"}, {"x", 0}, {"y", 0}}} : spots;
    features.append(threadFeature("locations", "sketch", {{"plane", "XY"}, {"offset", opposite ? 2 : 10}, {"shapes", points}}));
    features.append(threadFeature("tap", "hole", {{"sketch", "locations"}, {"kind", "tapped"}, {"size", "M3"},
        {"diameter", 2.5}, {"through", through}, {"depth", 8}, {"thread", modeled}, {"phase", phase}, {"flip", opposite}}));
    return {{"features", features}, {"props", QJsonObject{{"material", material}}}};
}

QJsonObject screwDocument(double length, bool modeled = true, const QString &head = "cap", double phase = 0,
                         const QString &size = "M3") {
    return {{"features", QJsonArray{
        threadFeature("screw_locations", "sketch", {{"plane", "XY"}, {"shapes", QJsonArray{QJsonObject{{"type", "point"}, {"x", 0}, {"y", 0}}}}}),
        threadFeature("screw", "screw", {{"sketch", "screw_locations"}, {"size", size}, {"head", head},
            {"length", length}, {"thread", modeled}, {"phase", phase}})}}};
}

QJsonObject inlinePart(const QJsonObject &document, const QString &name, double x = 0, double y = 0, double z = 0) {
    auto result = part(name, x, y, z);
    result["features"] = document["features"];
    result["props"] = document["props"].toObject();
    return result;
}

bool problemContains(const QJsonObject &pair, const QString &text) {
    for (const auto &entry : pair["problems"].toArray()) if (entry.toString().contains(text)) return true;
    return false;
}

void fastenerTests() {
    Engine engine;
    const auto base = inlinePart(tappedDocument(), "base");
    const auto screw = inlinePart(screwDocument(6), "screw", 0, 0, 10);
    auto result = engine.query("fasteners", {{"parts", QJsonArray{base, screw}}});
    require(result["complete"].toBool(), "Native fastener metadata should be fully recognized");
    require(result["pairs"].toArray().size() == 1 && result["loose"].toArray().isEmpty(), "Screw/tapped-hole matching failed");
    auto pair = result["pairs"].toArray()[0].toObject();
    require(pair["screw"].toInt() == 1 && pair["hole_part"].toInt() == 0 && pair["feature"] == "tap" && pair["size"] == "M3", "Original fastener JSON fields not preserved");
    close(pair["engaged"].toDouble(), 6, 0.15);
    close(pair["need"].toDouble(), 4.5);
    close(pair["bottom"].toDouble(), 2, 0.1);
    require(pair["phase_ok"].toBool() && pair["problems"].toArray().isEmpty(), "Good threaded screw must not report a problem");
    auto raised = screw;
    raised["move"] = QJsonArray{0, 0, 10.2};
    result = engine.query("fasteners", {{"parts", QJsonArray{base, raised}}});
    pair = result["pairs"].toArray()[0].toObject();
    close(pair["phase_need"].toDouble(), 216, 1e-4);
    require(!pair["phase_ok"].toBool() && problemContains(pair, "相位"), "Thread phase mismatch not detected");
    require(result["fix"].toArray().size() == 1, "Phase fix array missing");
    close(result["fix"].toArray()[0].toObject()["phase"].toDouble(), 216, 1e-4);
    result = engine.query("fasteners", {{"parts", QJsonArray{base, screw, raised}}});
    require(result["fix"].toArray()[0].toObject()["phase"].isNull(), "Modeled screws requiring different phases cannot share one fix");
    require(problemContains(result["pairs"].toArray()[1].toObject(), "几颗螺丝要的相位不一样"), "Conflicting modeled phase requirements must explain why one fix cannot work");
    auto corrected = inlinePart(tappedDocument(true, {}, false, 216), "corrected");
    pair = engine.query("fasteners", {{"parts", QJsonArray{corrected, raised}}})["pairs"].toArray()[0].toObject();
    require(pair["phase_ok"].toBool(), "Applying recommended thread phase must align the pair");
    auto clocked = screw;
    clocked["turn"] = QJsonArray{0, 0, 90};
    pair = engine.query("fasteners", {{"parts", QJsonArray{base, clocked}}})["pairs"].toArray()[0].toObject();
    close(pair["phase_need"].toDouble(), 90);
    require(!pair["phase_ok"].toBool(), "Rotation about thread axis must affect phase");
    const auto shortScrew = inlinePart(screwDocument(3, false), "short", 0, 0, 10);
    pair = engine.query("fasteners", {{"parts", QJsonArray{base, shortScrew}}})["pairs"].toArray()[0].toObject();
    require(problemContains(pair, "拧进去只有"), "Insufficient engagement not detected");
    const auto deepScrew = inlinePart(screwDocument(7.8, false), "deep", 0, 0, 10);
    pair = engine.query("fasteners", {{"parts", QJsonArray{base, deepScrew}}})["pairs"].toArray()[0].toObject();
    close(pair["bottom"].toDouble(), 0.2, 0.1);
    require(problemContains(pair, "孔底"), "Blind hole bottom clearance violation not detected");
    auto plainScrew = inlinePart(screwDocument(6, false), "plain", 0, 0, 10);
    auto counterboredDocument = tappedDocument(false);
    auto counterboredFeatures = counterboredDocument["features"].toArray();
    counterboredFeatures.append(threadFeature("counterbore", "hole", {{"sketch", "locations"}, {"kind", "simple"},
        {"diameter", 8}, {"through", false}, {"depth", 3}}));
    counterboredDocument["features"] = counterboredFeatures;
    pair = engine.query("fasteners", {{"parts", QJsonArray{inlinePart(counterboredDocument, "counterbored"), plainScrew}}})["pairs"].toArray()[0].toObject();
    close(pair["engaged"].toDouble(), 3, 0.02);
    require(problemContains(pair, "拧进去只有"), "Engagement must use final material, not declared hole depth");
    const auto through = inlinePart(tappedDocument(false, "普通碳钢", true), "through");
    pair = engine.query("fasteners", {{"parts", QJsonArray{through, plainScrew}}})["pairs"].toArray()[0].toObject();
    require(pair["bottom"].isNull(), "Open through hole should have no bottom within probe range");
    close(pair["need"].toDouble(), 3);
    const auto plastic = inlinePart(tappedDocument(false, "ABS"), "plastic");
    pair = engine.query("fasteners", {{"parts", QJsonArray{plastic, plainScrew}}})["pairs"].toArray()[0].toObject();
    close(pair["need"].toDouble(), 6);
    auto offAxis = plainScrew;
    offAxis["move"] = QJsonArray{0.2, 0, 10};
    result = engine.query("fasteners", {{"parts", QJsonArray{through, offAxis}}});
    require(result["pairs"].toArray().isEmpty() && result["loose"].toArray().size() == 1, "Off-axis screw must be loose");
    const auto wrongSize = inlinePart(screwDocument(6, false, "cap", 0, "M4"), "M4", 0, 0, 10);
    require(engine.query("fasteners", {{"parts", QJsonArray{through, wrongSize}}})["loose"].toArray().size() == 1, "Mismatched sizes must not match");
    const auto opposite = inlinePart(tappedDocument(false, {}, false, 0, true), "opposite");
    pair = engine.query("fasteners", {{"parts", QJsonArray{opposite, plainScrew}}})["pairs"].toArray()[0].toObject();
    close(pair["engaged"].toDouble(), 6, 0.02);
    const auto oppositeModeled = inlinePart(tappedDocument(true, {}, false, 0, true), "opposite modeled");
    pair = engine.query("fasteners", {{"parts", QJsonArray{oppositeModeled, raised}}})["pairs"].toArray()[0].toObject();
    close(pair["phase_need"].toDouble(), 144, 1e-4);
    require(!pair["phase_ok"].toBool(), "Opposite drill direction must reverse needed phase");
    const auto flat = inlinePart(screwDocument(6, false, "flat"), "flat", 0, 0, 10);
    pair = engine.query("fasteners", {{"parts", QJsonArray{through, flat}}})["pairs"].toArray()[0].toObject();
    close(pair["engaged"].toDouble(), 6 - (6.72 - 3) / 2, 0.02);
    auto turnedBase = base, turnedScrew = screw;
    turnedBase["turn"] = QJsonArray{25, 35, 40};
    turnedScrew["turn"] = QJsonArray{25, 35, 40};
    turnedScrew["move"] = QJsonArray{0, 0, 0};
    turnedScrew["features"] = screwDocument(6)["features"];
    auto turnedFeatures = turnedScrew["features"].toArray();
    auto location = turnedFeatures[0].toObject(), locationParams = location["params"].toObject();
    locationParams["offset"] = 10;
    location["params"] = locationParams;
    turnedFeatures[0] = location;
    turnedScrew["features"] = turnedFeatures;
    pair = engine.query("fasteners", {{"parts", QJsonArray{turnedBase, turnedScrew}}})["pairs"].toArray()[0].toObject();
    close(pair["engaged"].toDouble(), 6, 0.15);
    close(pair["bottom"].toDouble(), 2, 0.1);
    require(pair["phase_ok"].toBool(), "Common arbitrary rotation must preserve phase alignment");
    auto mirroredBase = base, mirroredScrew = screw;
    mirroredBase["mirror"] = true;
    mirroredScrew["mirror"] = true;
    pair = engine.query("fasteners", {{"parts", QJsonArray{mirroredBase, mirroredScrew}}})["pairs"].toArray()[0].toObject();
    require(pair["phase_ok"].toBool(), "Both mirrored threads preserve compatible handedness");
    result = engine.query("fasteners", {{"parts", QJsonArray{base, mirroredScrew}}});
    pair = result["pairs"].toArray()[0].toObject();
    require(!pair["phase_ok"].toBool() && problemContains(pair, "旋向"), "Opposite handedness must not pass thread alignment");
    require(result["fix"].toArray()[0].toObject()["phase"].isNull(), "Opposite handedness cannot be corrected by a phase value");
    const auto points = QJsonArray{QJsonObject{{"type", "point"}, {"x", -5}, {"y", 0}}, QJsonObject{{"type", "point"}, {"x", 5}, {"y", 0}}};
    const auto multiBase = inlinePart(tappedDocument(false, {}, false, 0, false, points), "multi");
    auto left = plainScrew, right = plainScrew;
    left["move"] = QJsonArray{-5, 0, 10};
    right["move"] = QJsonArray{5, 0, 10.2};
    result = engine.query("fasteners", {{"parts", QJsonArray{multiBase, left, right}}});
    require(result["pairs"].toArray().size() == 2 && result["fix"].toArray()[0].toObject()["phase"].isNull(), "Conflicting phase needs within one hole feature require a null fix");
    auto suppressedBase = tappedDocument(false);
    auto suppressedFeatures = suppressedBase["features"].toArray();
    auto suppressedHole = suppressedFeatures[3].toObject();
    suppressedHole["suppressed"] = true;
    suppressedFeatures[3] = suppressedHole;
    suppressedBase["features"] = suppressedFeatures;
    require(engine.query("fasteners", {{"parts", QJsonArray{inlinePart(suppressedBase, "suppressed"), plainScrew}}})["loose"].toArray().size() == 1, "Suppressed tapped hole must not be matched");
    auto rolledBack = inlinePart(tappedDocument(false), "rollback");
    rolledBack["upto"] = 2;
    require(engine.query("fasteners", {{"parts", QJsonArray{rolledBack, plainScrew}}})["loose"].toArray().size() == 1, "Rolled-back hole must not be matched");
    auto patternedDocument = screwDocument(6, false);
    auto patternedFeatures = patternedDocument["features"].toArray();
    patternedFeatures.append(threadFeature("copies", "pattern_linear", {{"features", QJsonArray{"screw"}}, {"axis1", "X"}, {"count1", 2}, {"spacing1", 6}, {"count2", 1}, {"spacing2", 0}}));
    patternedDocument["features"] = patternedFeatures;
    result = engine.query("fasteners", {{"parts", QJsonArray{through, inlinePart(patternedDocument, "patterned", 0, 0, 10)}}});
    require(!result["complete"].toBool() && result["unchecked_parts"].toArray() == QJsonArray{1}, "Patterned thread instances must not be silently considered fully checked");
    QTemporaryDir temporary;
    const QString basePath = temporary.filePath("host.gform"), screwPath = temporary.filePath("screw.gform");
    writeJson(basePath, tappedDocument(false));
    writeJson(screwPath, screwDocument(6, false));
    result = engine.query("fasteners", {{"base_directory", temporary.path()}, {"parts", QJsonArray{
        QJsonObject{{"name", "file base"}, {"file", "host.gform"}}, QJsonObject{{"name", "file screw"}, {"file", "screw.gform"}, {"move", QJsonArray{0, 0, 10}}}}}});
    require(result["pairs"].toArray().size() == 1, "GFORM fastener relative file loading failed");
    auto expressionScrew = screwDocument(6, false);
    auto expressionFeatures = expressionScrew["features"].toArray();
    auto expressionFeature = expressionFeatures[1].toObject(), expressionParams = expressionFeature["params"].toObject();
    expressionParams["length"] = "=length";
    expressionFeature["params"] = expressionParams;
    expressionFeatures[1] = expressionFeature;
    expressionFeatures.prepend(threadFeature("vars", "variables", {{"values", QJsonObject{{"length", 6}}}}));
    expressionScrew["features"] = expressionFeatures;
    Engine expressionEngine;
    expressionEngine.setAssembly({{"parts", QJsonArray{inlinePart(tappedDocument(false), "base"), inlinePart(expressionScrew, "expression screw", 0, 0, 10)}},
        {"params", QJsonObject{{"length", 3}}}});
    pair = expressionEngine.query("fasteners")["pairs"].toArray()[0].toObject();
    close(pair["engaged"].toDouble(), 3, 0.02);
    require(problemContains(pair, "拧进去只有"), "Fastener metadata must use assembly-overridden resolved numeric parameters");
    genform::kernel::Kernel imported;
    imported.build(plate());
    const QString stepPath = temporary.filePath("unrecognized.step"), stlPath = temporary.filePath("mesh.stl");
    imported.exportFile(stepPath);
    imported.exportFile(stlPath);
    result = engine.query("fasteners", {{"parts", QJsonArray{QJsonObject{{"path", stepPath}}, plainScrew}}});
    require(!result["complete"].toBool() && result["unchecked_parts"].toArray() == QJsonArray{0}, "Imported geometry must not claim thread recognition completeness");
    rejects([&] { engine.query("fasteners", {{"parts", QJsonArray{QJsonObject{{"path", stlPath}}, plainScrew}}}); }, "Mesh-only host cannot pass exact fastener checks");
    rejects([&] { engine.query("fasteners", {{"parts", QJsonArray{base}}}); }, "Single-part fastener check must fail");
    std::cout << "PASS fasteners: modeled threads, exact engagement, counterbore material, blind/through bottom, phase and fixes, materials, loose/size/axis, opposite drill, flat head, arbitrary rotation, mirror handedness, conflicting phases, suppression/rollback and GFORM paths\n";
}

void geometryTests() {
    Engine engine;
    engine.setDocument(plate(), {}, {{"material", "铝合金 6061"}});
    const auto separated = QJsonArray{part("base"), part("far", 25)};
    const auto touching = QJsonArray{part("base"), part("touch", 20)};
    const auto overlapping = QJsonArray{part("base"), part("clash", 15)};
    auto result = engine.query("interference", {{"parts", overlapping}});
    require(result["clashes"].toArray().size() == 1, "Box overlap not detected");
    close(result["clashes"].toArray()[0].toObject()["volume"].toDouble(), 250);
    require(engine.query("interference", {{"parts", touching}})["clashes"].toArray().isEmpty(), "Face touching is not a volume clash");
    result = engine.query("measure_parts", {{"parts", separated}});
    close(result["distance"].toDouble(), 5);
    close(result["items"].toArray()[0].toObject()["volume"].toDouble(), 1000);
    result = engine.query("contacts", {{"parts", touching}});
    require(result["pairs"].toArray()[0].toObject()["kind"] == "touch", "Face contact classification wrong");
    require(result["floating"].toArray().isEmpty(), "Contact connectivity not propagated");
    require(engine.query("contacts", {{"parts", touching}})["fresh"].toInt() == 0, "Pair result cache not reused");
    result = engine.query("contacts", {{"parts", QJsonArray{part("base"), part("near", 20.25)}}});
    require(result["pairs"].toArray()[0].toObject()["kind"] == "gap", "Clearance violation not detected");
    require(result["floating"].toArray() == QJsonArray{1}, "Gap cannot imply connectivity");
    result = engine.query("connections", {{"parts", separated}, {"links", QJsonArray{QJsonValue(QJsonArray{0, 1})}}});
    require(result["floating"].toArray().isEmpty(), "Explicit joint link ignored");
    result = engine.query("mass_props", {{"parts", separated}});
    close(result["mass_g"].toDouble(), 5.4);
    close(result["items"].toArray()[1].toObject()["centre"].toArray()[0].toDouble() - result["items"].toArray()[0].toObject()["centre"].toArray()[0].toDouble(), 25);
    auto unweighed = part("unknown");
    unweighed["props"] = QJsonObject{};
    require(!engine.query("mass_props", {{"parts", QJsonArray{unweighed}}})["complete"].toBool(), "Unknown density must not claim a complete mass");
    auto rotated = part("rotated");
    rotated["turn"] = QJsonArray{0, 0, 90};
    rotated["mirror"] = true;
    result = engine.query("measure_parts", {{"parts", QJsonArray{rotated}}});
    close(result["items"].toArray()[0].toObject()["volume"].toDouble(), 1000);
    close(result["items"].toArray()[0].toObject()["size"].toArray()[0].toDouble(), 10);
    result = engine.query("contacts", {{"parts", QJsonArray{part("one"), part("two", 1), part("three", 2)}}, {"budget", 0}});
    require(result["partial"].toBool() && result["floating_provisional"].toBool(), "Time-budgeted contact checks must report provisional connectivity");
    result = engine.query("meshes", {{"parts", separated}});
    require(result["meshes"].toArray().size() == 2, "Mesh array alignment wrong");
    const auto one = result["meshes"].toArray()[0].toObject(), two = result["meshes"].toArray()[1].toObject();
    close(two["verts"].toArray()[0].toArray()[0].toDouble() - one["verts"].toArray()[0].toArray()[0].toDouble(), 25);
    require(one["edge_kind"].toArray().size() == one["edges"].toArray().size(), "Display edge metadata arrays missing");
    auto coloredPart = part("colored");
    coloredPart["props"] = QJsonObject{{"feature_colors", QJsonObject{{"extrude", "#FF0000"}}}, {"feature_opacity", QJsonObject{{"extrude", 0.4}}}};
    const auto colored = engine.query("meshes", {{"parts", QJsonArray{coloredPart}}})["meshes"].toArray()[0].toObject();
    close(colored["tints"].toArray()[0].toArray()[0].toDouble(), 1);
    close(colored["tints"].toArray()[0].toArray()[1].toDouble(), 0);
    close(colored["alpha"].toDouble(), 0.4);
    require(engine.query("sequence", {{"parts", separated}, {"samples", 10}})["ok"].toBool(), "Simple assembly sequence failed");
    require(!engine.query("sequence", {{"parts", overlapping}, {"samples", 10}})["ok"].toBool(), "Overlapping assembly sequence cannot pass");
    require(engine.query("stack", {{"parts", separated}})["exact"] == false, "Bounding-box stack must be labeled approximate");
    QJsonObject slide{{"kind", "slide"}, {"parts", QJsonArray{1}}, {"origin", QJsonArray{0, 0, 0}}, {"axis", QJsonArray{1, 0, 0}}, {"values", QJsonArray{-10, 0, 10}}};
    result = engine.query("sweep", {{"parts", separated}, {"joints", QJsonArray{slide}}});
    require(!result["clashes"].toArray().isEmpty() && result["sampled"].toBool(), "Sampled motion clash not found");
    rejects([&] { engine.query("sweep", {{"parts", separated}}); }, "No-joint motion sweep cannot claim successful analysis");
    result = engine.query("drawing", {{"parts", QJsonArray{part("plate")}}});
    require(result["views"].toObject().contains("front"), "Exact drawing projection missing");
    result = engine.query("drag", {{"parts", QJsonArray{part("plate")}}, {"speed", 10}, {"direction", QJsonArray{0, 0, 1}}});
    close(result["area"].toDouble(), 200, 2);
    close(result["pressure"].toDouble(), 61.25);
    require(result["approximate"].toBool(), "Drag estimate must not claim exactness");
    QTemporaryDir temporary;
    const QString documentPath = temporary.filePath("plate.gform"), assemblyPath = temporary.filePath("test.gasm"), exported = temporary.filePath("assembly.step");
    auto features = plate();
    auto extrude = features[1].toObject();
    extrude["process"] = QJsonObject{{"id", "purchase"}, {"name", "外购"}, {"spec", "plate"}, {"cost", 12.5}};
    features[1] = extrude;
    writeJson(documentPath, {{"format", "genform"}, {"features", features}, {"props", QJsonObject{{"material", "ABS"}}}});
    writeJson(assemblyPath, {{"format", "genform-assembly"}, {"version", 1}, {"parts", QJsonArray{QJsonObject{{"name", "one"}, {"file", "plate.gform"}}, QJsonObject{{"name", "two"}, {"file", "plate.gform"}, {"mirror", true}}}}});
    result = engine.load(assemblyPath);
    require(result["parts"].toArray().size() == 2, "GASM load failed");
    result = engine.query("bom");
    require(result["rows"].toArray().size() == 1, "Purchased mirrored parts must share a BOM row");
    close(result["totals"].toObject()["all"].toObject()["cost"].toDouble(), 25);
    auto customFeatures = features;
    auto customExtrude = customFeatures[1].toObject();
    customExtrude["process"] = QJsonObject{{"id", "machining"}, {"name", "CNC"}, {"cost", 10}};
    customFeatures[1] = customExtrude;
    writeJson(temporary.filePath("custom.gform"), {{"features", customFeatures}});
    result = engine.query("bom", {{"base_directory", temporary.path()}, {"parts", QJsonArray{QJsonObject{{"file", "custom.gform"}}, QJsonObject{{"file", "custom.gform"}, {"mirror", true}}}}});
    require(result["rows"].toArray().size() == 2, "Custom mirrored parts must have distinct BOM rows");
    QJsonArray variableFeatures{QJsonObject{{"id", "variables"}, {"type", "variables"}, {"params", QJsonObject{{"values", QJsonObject{{"width", 20}}}}}}};
    auto variablePlate = plate();
    auto variableSketch = variablePlate[0].toObject();
    auto variableSketchParams = variableSketch["params"].toObject();
    auto shapes = variableSketchParams["shapes"].toArray();
    auto rectangle = shapes[0].toObject();
    rectangle["w"] = "=width";
    shapes[0] = rectangle;
    variableSketchParams["shapes"] = shapes;
    variableSketch["params"] = variableSketchParams;
    variablePlate[0] = variableSketch;
    for (const auto &entry : variablePlate) variableFeatures.append(entry);
    const QString variablePath = temporary.filePath("variable.gform");
    writeJson(variablePath, {{"features", variableFeatures}});
    Engine parameterEngine;
    parameterEngine.setAssembly({{"parts", QJsonArray{QJsonObject{{"file", "variable.gform"}}}}, {"params", QJsonObject{{"width", 30}}}}, temporary.path());
    result = parameterEngine.query("measure_parts");
    close(result["items"].toArray()[0].toObject()["volume"].toDouble(), 1500);
    close(parameterEngine.query("measure_parts", {{"parts", QJsonArray{QJsonObject{{"file", "variable.gform"}}}}})["items"].toArray()[0].toObject()["volume"].toDouble(), 1500);
    QFile unchanged(variablePath);
    require(unchanged.open(QIODevice::ReadOnly), "Cannot read original variable part");
    require(QJsonDocument::fromJson(unchanged.readAll()).object()["features"].toArray()[0].toObject()["params"].toObject()["values"].toObject()["width"].toInt() == 20,
        "Assembly parameter override must not mutate the part file");
    engine.query("assembly_step", {{"parts", separated}, {"path", exported}});
    require(QFileInfo(exported).size() > 0, "Assembly STEP file not written");
    result = engine.query("measure_parts", {{"parts", QJsonArray{QJsonObject{{"path", exported}}}}});
    close(result["items"].toArray()[0].toObject()["volume"].toDouble(), 2000);
    const QString relativeImport = temporary.filePath("imported.gform");
    writeJson(relativeImport, {{"features", QJsonArray{QJsonObject{{"id", "import"}, {"type", "import_step"}, {"params", QJsonObject{{"path", "assembly.step"}}}}}}});
    result = engine.query("measure_parts", {{"parts", QJsonArray{QJsonObject{{"path", relativeImport}}}}});
    close(result["items"].toArray()[0].toObject()["volume"].toDouble(), 2000);
    genform::kernel::Kernel builder;
    builder.build(plate());
    const QString stl = temporary.filePath("plate.stl");
    builder.exportFile(stl);
    const QJsonArray approximate{QJsonObject{{"path", stl}, {"name", "mesh"}}, part("solid")};
    rejects([&] { engine.query("interference", {{"parts", approximate}}); }, "STL must not certify interference");
    require(!engine.query("meshes", {{"parts", approximate}})["meshes"].toArray()[0].toObject()["exact"].toBool(), "STL must retain non-exact label");
    rejects([&] { engine.query("meshes", {{"parts", QJsonArray{QJsonObject{{"path", temporary.filePath("missing.gform")}}}}}); }, "Missing part must fail");
    require(!engine.query("meshes", {{"parts", QJsonArray{QJsonObject{{"path", temporary.filePath("missing.gform")}}}}, {"allow_partial", true}})["complete"].toBool(), "Partial mesh load must report incomplete");
    std::cout << "PASS exact interference, distance, gap, touch graph, mass, meshes, pair cache, motion sweep, sequence, STEP, STL refusal, drawing, drag, BOM\n";

    Engine staticEngine;
    const auto model = builder.build(plate(20, 10, 10));
    staticEngine.setDocument(plate(20, 10, 10));
    QJsonArray fixed, loaded;
    for (const auto &entry : model["faces"].toArray()) {
        const auto face = entry.toObject();
        const auto normal = face["normal"].toArray();
        if (normal.size() == 3 && normal[0].toDouble() < -0.9) fixed.append(face["id"]);
        if (normal.size() == 3 && normal[0].toDouble() > 0.9) loaded.append(face["id"]);
    }
    require(!fixed.isEmpty() && !loaded.isEmpty(), "Static test faces not found");
    result = staticEngine.query("static", {{"fixed", fixed}, {"loaded", loaded}, {"force", QJsonArray{100, 0, 0}},
        {"young", 200000}, {"poisson", 0}, {"yield", 250}, {"quality", "coarse"}, {"time_limit_seconds", 90}});
    require(result["converged"].toBool() && result["approximate"].toBool(), "Static convergence metadata missing");
    require(result["relative_residual"].toDouble() < 5e-7, "Static residual did not converge");
    require(result["max_displacement"].toDouble() > 0 && result["max_stress"].toDouble() > 0, "Static outputs must be physical nonzero values");
    close(result["max_displacement"].toDouble(), 0.0001, 0.00004);
    require(result["stress"].toArray().size() == model["verts"].toArray().size(), "Static display stress array misaligned");
    rejects([&] { staticEngine.query("static", {{"fixed", fixed}, {"loaded", fixed}, {"force", QJsonArray{100, 0, 0}}, {"young", 200000}}); }, "Conflicting static boundary conditions must fail");
    std::cout << "PASS native hexahedral finite elements, tensile displacement, stress, convergence residual, boundary validation\n";
}

void actualGeometryTests(const QString &directory) {
    const QString path = QDir(directory).filePath("button_latch/button_latch_open.gasm");
    Engine engine;
    const auto loaded = engine.load(path);
    const auto parts = loaded["parts"].toArray();
    const auto result = engine.query("measure_parts", {{"parts", QJsonArray{parts[0]}}});
    require(result["items"].toArray()[0].toObject()["volume"].toDouble() > 0, "Real latch housing build produced no volume");
    const auto mass = engine.query("mass_props", {{"parts", QJsonArray{parts[0], parts[1]}}});
    require(mass["items"].toArray().size() == 2, "Real latch mass query row count mismatch");
    std::cout << "PASS repository latch housing and button: native feature rebuild, exact measurement and mass properties\n";
}
#endif
}

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    try {
        const bool fastenersOnly = argc > 1 && QString::fromLocal8Bit(argv[1]) == "--fasteners-only";
        if (fastenersOnly) {
#ifdef GENFORM_HAS_OCCT
            fastenerTests();
#else
            Engine engine;
            rejects([&] { engine.query("fasteners", {{"parts", QJsonArray{part("one"), part("two")}}}); }, "Fasteners without SDK must fail explicitly");
            std::cout << "PASS fasteners: explicit missing SDK error\n";
#endif
            return 0;
        }
        dataTests();
        if (argc > 1) modelFileTests(QString::fromLocal8Bit(argv[1]));
#ifdef GENFORM_HAS_OCCT
        geometryTests();
        fastenerTests();
        if (argc > 1) actualGeometryTests(QString::fromLocal8Bit(argv[1]));
#else
        Engine engine;
        rejects([&] { engine.query("interference", {{"parts", QJsonArray{part("one"), part("two")}}}); }, "Missing SDK must fail explicitly");
        std::cout << "PASS explicit missing SDK error\n";
#endif
        return 0;
    } catch (const std::exception &error) { std::cerr << "FAIL " << error.what() << '\n'; return 1; }
}
