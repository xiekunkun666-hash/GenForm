#include "geometry.hpp"
#include <QFile>
#include <QJsonDocument>
#include <QTextStream>
#include <QSet>
#include <algorithm>
#include <numeric>

#ifdef GENFORM_HAS_OCCT
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRep_Tool.hxx>
#include <Extrema_ExtFlag.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <gp_Pnt2d.hxx>
#endif

namespace examples {
#ifdef GENFORM_HAS_OCCT

static QJsonObject row(const QString &name, const QString &file, const QJsonArray &move = {0, 0, 0}, double angle = 0) { return {{"name", name}, {"file", file}, {"move", move}, {"turn", QJsonArray{0, 0, angle}}}; }

static int latchVerification(const Options &options) {
    const bool claw = options.name.startsWith("button_claw_latch");
    QDir directory(options.output.isEmpty() ? QDir(sourceRoot()).filePath(claw ? "models/button_claw_latch" : "models/button_latch") : options.output);
    const auto files = directory.entryList({"*.gform"}, QDir::Files, QDir::Name);
    require(files.size() >= (claw ? 16 : 7), "Incomplete latch input: missing .gform parts");
    ShapeCache cache; QJsonObject parts, inputs;
    for (const auto &file : files) { const auto shape = cache.get(directory.filePath(file)); const auto measurement = metrics(shape); require(measurement["valid"].toBool() && (!claw || measurement["solids"].toInt() == 1), "Invalid or disconnected part: " + file); parts[file] = measurement; inputs[file] = sha256(directory.filePath(file)); QTextStream(stdout) << "VALID " << file << '\n'; }
    QJsonObject report{{"parts", parts}, {"limitations", QJsonArray{"Discrete checks, not a continuous collision proof.", "No load, friction, fatigue, spring-force or production-tolerance certification.", "All native design warnings are retained, not filtered."}}};
    if (!claw) {
        QJsonObject states; QJsonArray stroke;
        for (const auto &state : QStringList{"open", "pressed"}) {
            const QString file = "button_latch_" + state + ".gasm"; const auto assembly = loadObject(directory.filePath(file)); inputs[file] = sha256(directory.filePath(file));
            const auto result = cache.interference(directory, assembly["parts"].toArray()); QJsonArray expected, unexpected;
            for (const auto &value : result["clashes"].toArray()) { const auto pair = value.toObject(); if (pair["a"].toInt() == 0 && pair["b"].toInt() >= 5) expected.append(pair); else unexpected.append(pair); }
            states[state] = QJsonObject{{"pair_count", result["pairs"]}, {"unexpected_clashes", unexpected}, {"simplified_thread_envelope_overlaps", expected}};
            require(unexpected.isEmpty(), "Unexpected collision in state " + state);
        }
        for (int travel = 0; travel < 9; ++travel) { const auto result = cache.interference(directory, {row("housing", "housing.gform"), row("keeper", "keeper.gform"), row("bolt", "button_bolt.gform", {travel, 0, 0})}); require(result["clashes"].toArray().isEmpty(), "Unexpected stroke collision at " + QString::number(travel)); stroke.append(QJsonObject{{"travel_mm", travel}, {"clashes", result["clashes"]}}); }
        report["states"] = states; report["stroke_samples"] = stroke; report["stroke_mm"] = 8; report["open_gap_mm"] = 4; report["pressed_engagement_mm"] = 4;
        report["keeper_entry_mm"] = 30; report["open_tip_mm"] = 26; report["pressed_tip_mm"] = 34; report["guide_radial_clearance_mm"] = .3; report["receiver_radial_clearance_mm"] = .4;
    } else {
        QJsonArray assemblies, seats, stroke, release;
        for (int angle : {0, 10, 20, 30, 40}) {
            const QString state = angle == 0 ? "closed" : angle == 40 ? "open" : QString("angle_%1").arg(angle, 2, 10, QChar('0'));
            const QString file = "claw_latch_" + state + ".gasm"; auto result = cache.interference(directory, loadObject(directory.filePath(file))["parts"].toArray());
            inputs[file] = sha256(directory.filePath(file)); require(result["clashes"].toArray().isEmpty(), "Claw assembly collision: " + state); result["angle"] = angle; assemblies.append(result);
            const auto spring = cache.get(directory.filePath(QString("spring_%1.gform").arg(angle, 2, 10, QChar('0'))));
            const auto config = configuration(angle);
            for (const auto &seat : QStringList{"moving", "fixed"}) {
                const double position = seat == "moving" ? -42 + config["shift"].toDouble() : -36;
                const auto washer = placed(cache.get(directory.filePath("spring_seat.gform")), {{"move", QJsonArray{position, 0, 0}}});
                BRepExtrema_DistShapeShape distance(spring, washer); require(distance.IsDone() && distance.Value() <= 1e-5, "Spring loses " + seat + " seat at " + state);
                seats.append(QJsonObject{{"angle", angle}, {"seat", seat}, {"gap_mm", distance.Value()}});
            }
        }
        for (int angle = 0; angle <= 40; angle += 2) {
            const auto config = configuration(angle); const auto crank = config["crank"].toArray();
            const QJsonArray members{row("frame", "frame.gform"), row("claw", "rotary_claw.gform", {0, 0, 0}, angle), row("pushrod", "pushrod.gform", {config["shift"], 0, 0}), row("link", "connecting_link.gform", config["link_move"].toArray(), config["link_angle"].toDouble()), row("striker", "door_striker.gform"), row("crank_rivet", "link_rivet.gform", {crank[0], crank[1], 0}), row("slider_rivet", "link_rivet.gform", {config["slider"], 10, 0})};
            auto result = cache.interference(directory, members); require(result["clashes"].toArray().isEmpty(), "Rigid mechanism collision at angle " + QString::number(angle)); result["angle"] = angle; result["button_travel_mm"] = config["shift"]; stroke.append(result);
        }
        for (int index = 0; index < 37; ++index) { const double travel = index * .5; auto result = cache.interference(directory, {row("claw", "rotary_claw.gform", {0, 0, 0}, 40), row("striker", "door_striker.gform", {travel, 0, 0})}); require(result["clashes"].toArray().isEmpty(), "Release collision at " + QString::number(travel)); result["travel_mm"] = travel; release.append(result); }
        const auto blocking = cache.interference(directory, {row("claw", "rotary_claw.gform"), row("striker", "door_striker.gform", {.5, 0, 0})}); require(!blocking["clashes"].toArray().isEmpty(), "Closed claw fails to block the striker");
        QJsonObject exports; for (const auto &state : QStringList{"open", "closed"}) { const QString file = "claw_latch_" + state + ".step"; auto measurement = metrics(loadShape(directory.filePath(file))); require(measurement["valid"].toBool() && measurement["solids"].toInt() == 20, "Invalid/incomplete STEP: " + file); measurement["sha256"] = sha256(directory.filePath(file)); exports[file] = measurement; }
        report["assemblies"] = assemblies; report["spring_seats"] = seats; report["stroke"] = stroke; report["open_door_path"] = release; report["exports"] = exports;
        report["closed_blocking_test"] = QJsonObject{{"forced_door_travel_mm", .5}, {"expected_blocking_collision", blocking["clashes"]}};
    }
    report["input_sha256"] = inputs; saveObject(directory.filePath("verification.json"), report);
    QTextStream(stdout) << "PASS: native solid, assembly and motion verification\n"; return 0;
}

struct Sample { gp_Pnt position; int face; QString kind; };

static std::pair<std::vector<Sample>, QJsonObject> sampleFaces(const TopoDS_Shape &shape, int ugrid, int vgrid, double tolerance) {
    std::vector<Sample> samples; QJsonArray perFace, failed, boundaryOnly; int faceIndex = 0, evaluationErrors = 0;
    for (TopExp_Explorer explorer(shape, TopAbs_FACE); explorer.More(); explorer.Next()) {
        const auto face = TopoDS::Face(explorer.Current()); ++faceIndex; QSet<QString> seen; int accepted = 0, rejected = 0, vertexCount = 0, edgeCount = 0; QJsonArray errors;
        auto add = [&](const gp_Pnt &position, const QString &kind) { const QString key = QString::number(position.X(), 'g', 17) + ',' + QString::number(position.Y(), 'g', 17) + ',' + QString::number(position.Z(), 'g', 17); if (seen.contains(key)) return; seen.insert(key); samples.push_back({position, faceIndex, kind}); if (kind == "uv_accepted") ++accepted; else if (kind == "vertex_samples") ++vertexCount; else ++edgeCount; };
        try {
            double umin, umax, vmin, vmax; BRepTools::UVBounds(face, umin, umax, vmin, vmax);
            require(std::isfinite(umin) && std::isfinite(umax) && std::isfinite(vmin) && std::isfinite(vmax), "Non-finite UV bounds"); BRepAdaptor_Surface surface(face, true);
            for (int uindex = 0; uindex < ugrid; ++uindex) for (int vindex = 0; vindex < vgrid; ++vindex) { const double u = umin + (umax - umin) * (uindex + .5) / ugrid, v = vmin + (vmax - vmin) * (vindex + .5) / vgrid; BRepClass_FaceClassifier classifier(face, gp_Pnt2d(u, v), tolerance); if (classifier.State() == TopAbs_IN || classifier.State() == TopAbs_ON) add(surface.Value(u, v), "uv_accepted"); else ++rejected; }
        } catch (const Standard_Failure &error) { errors.append(QString::fromUtf8(error.GetMessageString())); } catch (const std::exception &error) { errors.append(QString::fromUtf8(error.what())); }
        try {
            for (TopExp_Explorer vertex(face, TopAbs_VERTEX); vertex.More(); vertex.Next()) add(BRep_Tool::Pnt(TopoDS::Vertex(vertex.Current())), "vertex_samples");
            if (!accepted) for (TopExp_Explorer edge(face, TopAbs_EDGE); edge.More(); edge.Next()) { BRepAdaptor_Curve curve(TopoDS::Edge(edge.Current())); const double parameter = (curve.FirstParameter() + curve.LastParameter()) / 2; if (std::isfinite(parameter)) add(curve.Value(parameter), "edge_samples"); }
        } catch (const Standard_Failure &error) { errors.append(QString::fromUtf8(error.GetMessageString())); }
        if (seen.isEmpty()) failed.append(faceIndex); if (!accepted) boundaryOnly.append(faceIndex); evaluationErrors += errors.size();
        perFace.append(QJsonObject{{"face", faceIndex}, {"uv_accepted", accepted}, {"uv_rejected", rejected}, {"vertex_samples", vertexCount}, {"edge_samples", edgeCount}, {"errors", errors}, {"samples", seen.size()}});
    }
    return {samples, {{"face_count", faceIndex}, {"covered_faces", faceIndex - failed.size()}, {"failed_faces", failed}, {"boundary_only_faces", boundaryOnly}, {"evaluation_error_count", evaluationErrors}, {"sample_count", static_cast<int>(samples.size())}, {"per_face", perFace}}};
}

static QJsonObject distances(const std::vector<Sample> &samples, const TopoDS_Shape &target, double tolerance, bool classify) {
    std::vector<TopoDS_Shape> faces; for (TopExp_Explorer explorer(target, TopAbs_FACE); explorer.More(); explorer.Next()) faces.push_back(explorer.Current());
    const auto boundary = compound(faces); BRepExtrema_DistShapeShape solver; solver.SetFlag(Extrema_ExtFlag_MIN); solver.SetDeflection(tolerance); solver.LoadS2(boundary);
    std::vector<double> values; QJsonArray errors; QJsonObject worst, states{{"inside", 0}, {"outside", 0}, {"on", 0}, {"unknown", 0}}; double largest = -1;
    for (size_t index = 0; index < samples.size(); ++index) {
        const auto &sample = samples[index];
        try {
            solver.LoadS1(BRepBuilderAPI_MakeVertex(sample.position).Vertex()); solver.Perform(); require(solver.IsDone() && solver.NbSolution() > 0, "Distance solver incomplete");
            const double value = solver.Value(); require(std::isfinite(value) && value >= 0, "Invalid distance"); values.push_back(value);
            if (value > largest) { largest = value; worst = {{"point", coordinates(sample.position)}, {"face", sample.face}, {"kind", sample.kind}, {"distance", value}, {"target_point", coordinates(solver.PointOnShape2(1))}}; }
            if (classify) { bool any = false, inside = false, on = false, unknown = false; for (TopExp_Explorer solid(target, TopAbs_SOLID); solid.More(); solid.Next()) { any = true; BRepClass3d_SolidClassifier classifier(solid.Current(), sample.position, tolerance); const auto state = classifier.State(); inside = inside || state == TopAbs_IN; on = on || state == TopAbs_ON; unknown = unknown || (state != TopAbs_IN && state != TopAbs_ON && state != TopAbs_OUT); } const QString state = inside ? "inside" : on ? "on" : !any || unknown ? "unknown" : "outside"; states[state] = states[state].toInt() + 1; }
        } catch (const std::exception &error) { errors.append(QJsonObject{{"sample", static_cast<int>(index)}, {"point", coordinates(sample.position)}, {"error", QString::fromUtf8(error.what())}}); }
        catch (const Standard_Failure &error) { errors.append(QJsonObject{{"sample", static_cast<int>(index)}, {"error", QString::fromUtf8(error.GetMessageString())}}); }
    }
    require(!values.empty(), "No distance samples succeeded"); std::sort(values.begin(), values.end()); const double position = (values.size() - 1) * .95;
    const double p95 = values[static_cast<size_t>(std::floor(position))] + (values[static_cast<size_t>(std::ceil(position))] - values[static_cast<size_t>(std::floor(position))]) * (position - std::floor(position));
    const double sum = std::accumulate(values.begin(), values.end(), 0.0), squares = std::inner_product(values.begin(), values.end(), values.begin(), 0.0);
    return {{"attempted", static_cast<int>(samples.size())}, {"successful", static_cast<int>(values.size())}, {"failed", errors.size()}, {"errors", errors}, {"worst", worst}, {"classification", classify ? QJsonValue(states) : QJsonValue(QJsonValue::Null)}, {"statistics", QJsonObject{{"min", values.front()}, {"mean", sum / values.size()}, {"rms", std::sqrt(squares / values.size())}, {"p95", p95}, {"max", values.back()}}}};
}

static int comparisonSelfTest();

static int compare(const Options &options) {
    if (options.values["self-test"].toBool()) return comparisonSelfTest();
    const QDir models(QDir(sourceRoot()).filePath("models/porsche_911_992"));
    QString first = options.positional.value(0, models.filePath("porsche_911_992.gform")), second = options.positional.value(1, models.filePath("porsche_911_992_method_b.gform"));
    const QString reportPath = options.values.value("report").toString(QDir(options.output.isEmpty() ? QDir::currentPath() : options.output).filePath("porsche_911_comparison.json"));
    require(options.positional.size() <= 2, "Comparison accepts at most two input files");
    require(!options.values.contains("cache-dir"), "Native comparator deliberately has no Python/OCP cache; omit --cache-dir");
    const auto resolved = [](const QString &path) { const QFileInfo file(path); if (file.exists()) return QDir::cleanPath(file.canonicalFilePath()); QDir parent(file.absolutePath()); QStringList missing{file.fileName()}; while (!parent.exists()) { missing.prepend(parent.dirName()); require(parent.cdUp(), "Cannot resolve output path"); } return QDir::cleanPath(parent.canonicalPath() + '/' + missing.join('/')); };
    const QString report = resolved(reportPath);
    for (const auto &input : {first, second}) {
        const QString directory = QFileInfo(resolved(input)).absolutePath() + '/';
        require(report != resolved(input) && !report.startsWith(directory, Qt::CaseInsensitive), "Comparison report must be outside both input directories");
    }
    QJsonObject result{{"ok", false}, {"status", "failed"}, {"equivalence", "not_asserted"}, {"limitations", QJsonArray{"Finite UV and boundary samples are not a strict Hausdorff distance.", "No assertion of exact geometric equivalence.", "UV spacing is not area-uniform; small trims and internal differences may be missed.", "Native comparison does not reuse Python/OCP geometry caches."}}};
    try {
        const auto firstHash = sha256(first), secondHash = sha256(second); const auto firstShape = loadShape(first), secondShape = loadShape(second);
        const auto firstMetrics = metrics(firstShape), secondMetrics = metrics(secondShape); require(firstMetrics["valid"].toBool() && secondMetrics["valid"].toBool(), "Comparison input BRep invalid");
        require(!(options.values.contains("uv-grid") && options.values.contains("samples-per-face")), "Choose --uv-grid or --samples-per-face, not both");
        const int budget = options.values.value("samples-per-face").toString("36").toInt(); require(budget > 0 && budget <= 10000, "Sampling budget must be in 1..10000");
        int ugrid = static_cast<int>(std::ceil(std::sqrt(budget))), vgrid = static_cast<int>(std::ceil(static_cast<double>(budget) / ugrid));
        if (options.values.contains("uv-grid")) { const auto grid = options.values["uv-grid"].toArray(); require(grid.size() == 2, "--uv-grid requires U V"); ugrid = grid[0].toString().toInt(); vgrid = grid[1].toString().toInt(); }
        require(ugrid > 0 && vgrid > 0 && static_cast<qint64>(ugrid) * vgrid <= 10000, "UV grid budget must be in 1..10000 samples per face");
        const double tolerance = options.values.value("tolerance").toString("0.0000001").toDouble(); require(std::isfinite(tolerance) && tolerance > 0, "Positive finite tolerance required");
        result["parameters"] = QJsonObject{{"uv_grid", QJsonArray{ugrid, vgrid}}, {"tolerance", tolerance}, {"distance_target", "compound of all target faces; MIN"}};
        result["inputs"] = QJsonArray{QJsonObject{{"path", first}, {"source_sha256", firstHash}, {"metrics", firstMetrics}}, QJsonObject{{"path", second}, {"source_sha256", secondHash}, {"metrics", secondMetrics}}};
        QJsonObject sampling, measured; const auto forward = sampleFaces(firstShape, ugrid, vgrid, tolerance), reverse = sampleFaces(secondShape, ugrid, vgrid, tolerance);
        sampling["a_to_b"] = forward.second; sampling["b_to_a"] = reverse.second;
        measured["a_to_b"] = distances(forward.first, secondShape, tolerance, options.values["classify"].toBool()); measured["b_to_a"] = distances(reverse.first, firstShape, tolerance, options.values["classify"].toBool());
        result["sampling"] = sampling; result["distances"] = measured;
        const double firstVolume = firstMetrics["volume"].toDouble(), volumeDelta = secondMetrics["volume"].toDouble() - firstVolume;
        result["delta_b_minus_a"] = QJsonObject{{"volume", volumeDelta}, {"area", secondMetrics["area"].toDouble() - firstMetrics["area"].toDouble()}, {"relative_volume", firstVolume ? QJsonValue(volumeDelta / firstVolume) : QJsonValue(QJsonValue::Null)}};
        require(forward.second["failed_faces"].toArray().isEmpty() && reverse.second["failed_faces"].toArray().isEmpty() && forward.second["evaluation_error_count"].toInt() == 0 && reverse.second["evaluation_error_count"].toInt() == 0, "Incomplete face sampling");
        require(measured["a_to_b"].toObject()["failed"].toInt() == 0 && measured["b_to_a"].toObject()["failed"].toInt() == 0, "Distance errors");
        require(firstHash == sha256(first) && secondHash == sha256(second), "Input changed during comparison"); result["ok"] = true; result["status"] = "completed";
    } catch (const Standard_Failure &error) { result["errors"] = QJsonArray{"OpenCascade: " + QString::fromUtf8(error.GetMessageString())}; saveObject(reportPath, result); throw; }
    catch (const std::exception &error) { result["errors"] = QJsonArray{QString::fromUtf8(error.what())}; saveObject(reportPath, result); throw; }
    saveObject(reportPath, result); QTextStream(stdout) << "Comparison completed (equivalence not asserted): " << reportPath << '\n'; return 0;
}

static int comparisonSelfTest() {
    const auto cylinder = BRepPrimAPI_MakeCylinder(2, 5).Shape();
    const auto sampling = sampleFaces(cylinder, 4, 5, 1e-7);
    require(sampling.second["failed_faces"].toArray().isEmpty(), "Cylinder face sampling incomplete");
    const auto identity = distances(sampling.first, cylinder, 1e-7, true);
    require(identity["statistics"].toObject()["max"].toDouble() < 1e-6, "Identity boundary comparison failed");
    const auto interior = distances({{{1, 0, 2.5}, 0, "self_test_interior"}}, cylinder, 1e-7, true);
    require(std::abs(interior["statistics"].toObject()["min"].toDouble() - 1) < 1e-6 && interior["classification"].toObject()["inside"].toInt() == 1, "Solid interior must measure distance to boundary, not zero");
    const auto shifted = placed(cylinder, {{"move", QJsonArray{.5, 0, 0}}});
    const double coarseMaximum = distances(sampling.first, shifted, 1e-7, false)["statistics"].toObject()["max"].toDouble();
    const auto originalBounds = genform::kernel::native::bounds(cylinder), shiftedBounds = genform::kernel::native::bounds(shifted);
    for (int side = 0; side < 2; ++side) require(std::abs(shiftedBounds[side].toArray()[0].toDouble() - originalBounds[side].toArray()[0].toDouble() - .5) < 1e-6, "Cylinder translation did not move both X bounds by 0.5 mm");
    auto translationSamples = sampling.first;
    translationSamples.push_back({gp_Pnt(-2, 0, 2.5), 0, "analytic_negative_x_extremum"});
    translationSamples.push_back({gp_Pnt(2, 0, 2.5), 0, "analytic_positive_x_extremum"});
    const auto translated = distances(translationSamples, shifted, 1e-7, true);
    require(translated["failed"].toInt() == 0 && translated["successful"].toInt() == static_cast<int>(translationSamples.size()), "Translation comparison must measure every sample");
    const double translatedMaximum = translated["statistics"].toObject()["max"].toDouble();
    require(translatedMaximum > .4, "Translated cylinder difference was missed");
    require(std::abs(translatedMaximum - .5) < 1e-6, "Cylinder extremal boundary distance must equal the 0.5 mm translation");
    const auto extrema = distances({{gp_Pnt(-2, 0, 2.5), 0, "outside_extremum"}, {gp_Pnt(2, 0, 2.5), 0, "inside_extremum"}}, shifted, 1e-7, true);
    require(std::abs(extrema["statistics"].toObject()["min"].toDouble() - .5) < 1e-6 && extrema["classification"].toObject()["inside"].toInt() == 1 && extrema["classification"].toObject()["outside"].toInt() == 1, "Both analytic cylinder extrema must be 0.5 mm from the boundary with opposite classifications");
    QTextStream(stdout) << "Translation: coarse UV maximum=" << QString::number(coarseMaximum, 'g', 15) << " mm, with analytic extrema=" << QString::number(translatedMaximum, 'g', 15) << " mm (expected 0.5)\n";
    QTemporaryDir temporary; require(temporary.isValid(), "Cannot create comparison self-test folder");
    const QString first = temporary.filePath("sources/a.brep"), second = temporary.filePath("sources/b.brep"); exportShape(cylinder, first); exportShape(shifted, second);
    Options options; options.positional = {first, second}; options.values = {{"report", temporary.filePath("report.json")}, {"uv-grid", QJsonArray{"4", "5"}}, {"classify", true}}; compare(options);
    require(loadObject(temporary.filePath("report.json"))["ok"].toBool(), "Comparison report was not completed");
    options.values["report"] = first; bool rejected = false; try { compare(options); } catch (const std::exception &) { rejected = true; }
    require(rejected && !loadShape(first).IsNull(), "Input overwrite protection failed");
    QTextStream(stdout) << "PASS: native identity/translation, rectangular UV grid, interior boundary distance, report and input protection; cache parity is not claimed\n"; return 0;
}
#endif

int verify(const Options &options) {
#ifndef GENFORM_HAS_OCCT
    Q_UNUSED(options); require(false, "Native example verification requires the OpenCascade C++ SDK; no Python fallback is used"); return 1;
#else
    if (options.name == "porsche_911/compare") return compare(options);
    if (options.name == "button_latch/verify" || options.name == "button_claw_latch/verify") return latchVerification(options);
    if (options.name.endsWith("/present") || options.name.endsWith("/validate")) return presentAssembly(options);
    if (options.name == "porsche_911/glazing" || options.name == "porsche_911/refine" || options.name == "porsche_911/panel_lines" || options.name == "porsche_911/trim") return surfaceExamples(options);
    require(false, "Unknown example or phase: " + options.name); return 1;
#endif
}
}
