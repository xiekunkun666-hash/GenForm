#include "native.hpp"
#include "kernel.hpp"
#include "file_io.hpp"

#include <QRegularExpression>
#include <algorithm>

#ifdef GENFORM_HAS_OCCT
#include <BRepAlgoAPI_Section.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepLib.hxx>
#include <HLRAlgo_Projector.hxx>
#include <HLRBRep_Algo.hxx>
#include <HLRBRep_HLRToShape.hxx>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <gp_Pln.hxx>
#endif

namespace genform::kernel {
namespace {
using namespace native;
const QString dependencyError = QStringLiteral("OpenCascade C++ SDK is unavailable. Rebuild GenForm with GENFORM_HAS_OCCT and the native OpenCascade libraries. No geometry was generated.");

QJsonObject resolvedParams(const QJsonObject &feature, QMap<QString, double> &variables) {
    auto params = feature["params"].toObject();
    if (feature["type"] == "variables") {
        const auto values = params["values"].toObject();
        static const QRegularExpression identifier(QStringLiteral("^[\\p{L}_][\\p{L}\\p{N}_]*$"));
        QMap<QString, QJsonValue> pending;
        for (auto entry = values.begin(); entry != values.end(); ++entry) {
            if (!identifier.match(entry.key()).hasMatch()) fail("Invalid variable name: " + entry.key());
            pending.insert(entry.key(), entry.value());
        }
        while (!pending.isEmpty()) {
            bool changed = false; QString lastError;
            for (auto entry = pending.begin(); entry != pending.end();) {
                try {
                    const auto value = resolve(entry.value(), variables);
                    bool ok = value.isDouble(); double numeric = value.toDouble();
                    if (value.isString()) numeric = value.toString().toDouble(&ok);
                    if (!ok || !std::isfinite(numeric)) fail("Variable must have a finite numeric value: " + entry.key());
                    variables[entry.key()] = numeric; entry = pending.erase(entry); changed = true;
                } catch (const std::exception &error) { lastError = QString::fromUtf8(error.what()); ++entry; }
            }
            if (!changed) fail("Variable expression cannot be resolved: " + lastError);
        }
        return params;
    }
    return resolve(params, variables).toObject();
}
}

struct Kernel::Impl {
    QJsonArray features;
    std::optional<int> upto;
    QJsonObject result{{"status", QJsonObject{}}, {"sketches", QJsonObject{}}, {"info", QJsonObject{}}, {"has_body", false}};
#ifdef GENFORM_HAS_OCCT
    native::Context context;
#endif
};

Kernel::Kernel() : impl_(std::make_unique<Impl>()) {}
Kernel::~Kernel() = default;

bool Kernel::available() {
#ifdef GENFORM_HAS_OCCT
    return true;
#else
    return false;
#endif
}

QJsonObject Kernel::build(const QJsonArray &features, std::optional<int> upto, Progress progress) {
    const int total = static_cast<int>(features.size());
    const int limit = upto ? std::clamp(*upto, 0, total) : total;
#ifndef GENFORM_HAS_OCCT
    for (int index = 0; index < limit; ++index) {
        const auto feature = features[index].toObject();
        if (!feature["suppressed"].toBool() && feature["type"] != "variables") fail(dependencyError);
    }
#endif
    QMap<QString, double> variables; QJsonObject status; bool failed = false;
#ifdef GENFORM_HAS_OCCT
    native::Context context; context.features = features;
#endif
    for (int index = 0; index < total; ++index) {
        const auto feature = features[index].toObject(); const QString id = feature["id"].toString();
        if (id.isEmpty()) fail("Every feature requires a nonempty id");
        if (status.contains(id)) fail("Duplicate feature id: " + id);
        if (failed || index >= limit) { status[id] = "skipped"; continue; }
        if (feature["suppressed"].toBool()) { status[id] = "suppressed"; continue; }
        const QString kind = feature["type"].toString();
        if (progress && kind != "sketch") progress(index, total, feature.value("name").toString(id));
#ifdef GENFORM_HAS_OCCT
        const auto before = context.body; const auto beforeOwners = context.owners; context.current = id; context.afterCuts.clear();
        auto rollback = [&] {
            context.body = before; context.owners = beforeOwners; context.tools.remove(id); context.sketches.remove(id);
            context.curves.remove(id); context.display.remove(id); context.info.remove(id); context.helixAxes.remove(id); context.afterCuts.clear();
        };
#endif
        try {
            const auto params = resolvedParams(feature, variables);
#ifdef GENFORM_HAS_OCCT
            auto resolvedFeature = feature; resolvedFeature["params"] = params; context.features[index] = resolvedFeature;
            if (kind == "variables") {}
            else if (kind == "sketch") context.sketches[id] = makeSketch(params, context.features);
            else if (kind == "plane" || kind == "axis" || kind == "csys" || kind == "point" || kind == "com" || kind == "bbox") context.display[id] = reference(kind, params, context);
            else if (kind == "sketch3d" || kind.startsWith("curve_")) { context.curves[id] = makeCurve(kind, params, context); context.display[id] = context.curves[id]; }
            else if (kind == "extrude" || kind == "revolve" || kind == "sweep" || kind == "loft" || kind == "boundary" || kind == "hole" || kind == "hole_adv" || kind == "stud" || kind == "screw" || kind == "import_step") {
                const auto tool = makeTool(kind, params, context);
                QString operation = params.value("op").toString(kind == "hole" || kind == "hole_adv" ? "cut" : "add");
                if (operation == "pocket" && number(params, "wall") > 0) operation += ":" + QString::number(number(params, "wall"), 'g', 16);
                context.body = combine(context.body, tool, operation); context.tools[id] = {{tool, operation, id}};
                for (const auto &cut : context.afterCuts) { context.body = combine(context.body, cut, "cut"); context.tools[id].push_back({cut, "cut", id}); }
            } else context.body = modify(kind, params, context);
            if (!empty(context.body)) validateSolid(context.body);
            inheritOwners(context, before);
#else
            Q_UNUSED(params);
#endif
            status[id] = "ok";
#ifdef GENFORM_HAS_OCCT
        } catch (const Standard_Failure &error) {
            rollback(); status[id] = "error: OpenCascade: " + QString::fromUtf8(error.GetMessageString() ? error.GetMessageString() : "operation failed"); failed = true;
#endif
        } catch (const std::exception &error) {
#ifdef GENFORM_HAS_OCCT
            rollback();
#endif
            status[id] = "error: " + QString::fromUtf8(error.what()); failed = true;
        }
    }
#ifdef GENFORM_HAS_OCCT
    context.status = status;
    const QJsonObject result = model(context);
    impl_->context = std::move(context);
#else
    const QJsonObject result{{"status", status}, {"sketches", QJsonObject{}}, {"info", QJsonObject{}}, {"has_body", false}};
#endif
    impl_->features = features; impl_->upto = upto; impl_->result = result;
    return result;
}

QJsonObject Kernel::preview(const QJsonArray &features, std::optional<int> upto) {
    Kernel temporary; const auto result = temporary.build(features, upto); QJsonArray errors;
    const auto status = result["status"].toObject();
    for (const auto &value : features) {
        const auto feature = value.toObject(); const QString id = feature["id"].toString(), state = status[id].toString();
        if (state.startsWith("error: ")) errors.append(feature.value("name").toString(id) + ": " + state.mid(7));
    }
    if (!result["has_body"].toBool()) return {{"verts", QJsonValue::Null}, {"errors", errors}};
    const auto props = result["props"].toObject();
    return {{"verts", result["verts"]}, {"normals", result["normals"]}, {"tris", result["tris"]}, {"low", props["bbox_min"]}, {"high", props["bbox_max"]}, {"errors", errors}};
}

QJsonObject Kernel::query(const QString &what, const QJsonObject &args) {
    if (what == "preview") {
        const auto features = args.contains("features") ? args["features"].toArray() : impl_->features;
        const auto upto = args.contains("upto") && !args["upto"].isNull() ? std::optional<int>(args["upto"].toInt()) : impl_->upto;
        return preview(features, upto);
    }
    if (what == "model") return impl_->result;
    if (what == "status") return impl_->result["status"].toObject();
#ifndef GENFORM_HAS_OCCT
    Q_UNUSED(args);
    fail(dependencyError);
#else
    const auto &context = impl_->context;
    if (what == "properties" || what == "props") {
        if (empty(context.body)) fail("No body exists");
        return properties(context.body);
    }
    if (what == "bounds") {
        if (empty(context.body)) fail("No body exists");
        const auto box = bounds(context.body); return {{"low", box[0]}, {"high", box[1]}};
    }
    if (what == "edges" || what == "list_edges") return {{"edges", impl_->result.value("edges").toArray()}};
    if (what == "faces" || what == "list_faces") return {{"faces", impl_->result.value("faces").toArray()}};
    if (what == "vertices") return {{"vertices", impl_->result.value("vertices").toArray()}};
    if (what == "measure") return measure(context, args);
    if (what == "inspect") return inspect(context, args);
    if (what == "section" || what == "silhouette") {
        if (empty(context.body)) fail("Section requires a body");
        QJsonValue reference = args["frame"];
        if (reference.isArray()) {
            const auto array = reference.toArray(); if (array.size() != 3) fail("Frame requires origin, X and Y vectors"); reference = QJsonObject{{"origin", array[0]}, {"x", array[1]}, {"y", array[2]}};
        }
        const auto plane = args.contains("frame") ? frame(reference, context.features) : frame(args.value("plane").toString("XY"), context.features, number(args, "offset"));
        TopoDS_Shape shape;
        if (what == "section") {
            BRepAlgoAPI_Section maker(context.body, gp_Pln(plane.origin, gp_Dir(plane.normal)), false); maker.Build(); if (!maker.IsDone()) fail("Section computation failed"); shape = maker.Shape();
        } else {
            Handle(HLRBRep_Algo) algorithm = new HLRBRep_Algo; algorithm->Add(context.body); algorithm->Projector(HLRAlgo_Projector(gp_Ax2(plane.origin, gp_Dir(plane.normal), gp_Dir(plane.x)))); algorithm->Update(); algorithm->Hide();
            HLRBRep_HLRToShape converter(algorithm); shape = converter.OutLineVCompound(); if (!shape.IsNull()) BRepLib::BuildCurves3d(shape);
        }
        QJsonArray lines;
        if (!shape.IsNull()) for (const auto &value : segments(shape)) {
            QJsonArray line; for (const auto &endpoint : value.toArray()) {
                const auto position = point(endpoint); const gp_Vec local(plane.origin, position);
                line.append(what == "silhouette" ? QJsonArray{position.X(), position.Y()} : QJsonArray{local.Dot(plane.x), local.Dot(plane.y)});
            } lines.append(line);
        }
        return {{"lines", lines}};
    }
    fail("Native kernel query not yet implemented: " + what);
#endif
    return {};
}

void Kernel::exportFile(const QString &path) {
#ifndef GENFORM_HAS_OCCT
    Q_UNUSED(path);
    fail(dependencyError);
#else
    const auto &body = impl_->context.body; if (empty(body)) fail("There is no body to export");
    file_io::writeShape(body, path);
#endif
}
}
