#include "native.hpp"
#include "file_io.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRepAdaptor_CompCurve.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepGProp.hxx>
#include <BRepOffsetAPI_DraftAngle.hxx>
#include <BRepOffsetAPI_MakeOffsetShape.hxx>
#include <BRepOffsetAPI_MakePipe.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepOffsetAPI_MakeThickSolid.hxx>
#include <BRepOffsetAPI_ThruSections.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakeHalfSpace.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GProp_GProps.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pln.hxx>
#include <QFileInfo>
#include <QRegularExpression>
#include <algorithm>
#include <limits>

namespace genform::kernel::native {
namespace {
template<class Maker> TopoDS_Shape checked(Maker &maker, const QString &what) {
    maker.Build();
    if (!maker.IsDone() || maker.Shape().IsNull()) fail(what + " failed");
    return maker.Shape();
}
TopoDS_Shape prism(const Sketch &sketch, double start, double stop) {
    if (std::abs(stop - start) < 1e-9) fail("Extrusion thickness is zero");
    const auto profile = std::abs(start) < 1e-12 ? sketch.profile : translated(sketch.profile, sketch.frame.normal * start);
    BRepPrimAPI_MakePrism maker(profile, sketch.frame.normal * (stop - start)); return checked(maker, "Extrusion");
}
TopoDS_Shape extrude(const QJsonObject &params, Context &context) {
    const auto &profile = sketch(context, params, true);
    const auto &frame = profile.frame;
    const double sign = params["reverse"].toBool() ? -1 : 1;
    const QString end = params.value("end").toString(params["symmetric"].toBool() ? "mid" : "blind");
    if (end == "blind") return prism(profile, -sign * std::max(0.0, number(params, "distance2")), sign * number(params, "distance"));
    if (end == "mid") { const double distance = std::abs(number(params, "distance")); return prism(profile, -distance / 2, distance / 2); }
    const auto targets = params["target"].toArray();
    if (end == "vertex") {
        if (targets.isEmpty()) fail("Extrusion requires a target vertex");
        const auto target = point(targets.first().toObject()["point"]);
        return prism(profile, 0, gp_Vec(frame.origin, target).Dot(frame.normal));
    }
    if (empty(context.body)) fail("Extrusion end condition requires an existing body");
    const auto box = bounds(context.body); const auto low = point(box[0]), high = point(box[1]);
    double extreme = sign > 0 ? -std::numeric_limits<double>::infinity() : std::numeric_limits<double>::infinity();
    for (double first : {low.X(), high.X()}) for (double second : {low.Y(), high.Y()}) for (double third : {low.Z(), high.Z()}) {
        const double height = gp_Vec(frame.origin, gp_Pnt(first, second, third)).Dot(frame.normal);
        extreme = sign > 0 ? std::max(extreme, height) : std::min(extreme, height);
    }
    if (extreme * sign <= 1e-6) fail("There is no body in this extrusion direction");
    const double farHeight = extreme + sign;
    if (end == "through") return prism(profile, 0, farHeight);
    if (end == "surface" || end == "offset") {
        const auto faces = selectFaces(context.body, targets);
        if (faces.size() != 1) fail("Select exactly one extrusion end face");
        BRepAdaptor_Surface surface(faces.front());
        if (surface.GetType() == GeomAbs_Plane) {
            const auto plane = surface.Plane(); const gp_Vec facing(plane.Axis().Direction());
            const double slope = facing.Dot(frame.normal);
            if (std::abs(slope) < 1e-6) fail("Extrusion direction is parallel to target face");
            GProp_GProps props; BRepGProp::SurfaceProperties(profile.profile, props);
            const double reach = gp_Vec(props.CentreOfMass(), plane.Location()).Dot(facing) / slope;
            const double toward = reach > 0 ? 1 : -1, gap = end == "offset" ? number(params, "gap") : 0;
            if (std::abs(slope) > 1 - 1e-9) return prism(profile, 0, reach - toward * gap);
            const auto shifted = plane.Location().Translated(frame.normal * (-toward * gap));
            const auto wall = BRepBuilderAPI_MakeFace(gp_Pln(shifted, gp_Dir(facing))).Face();
            const auto half = BRepPrimAPI_MakeHalfSpace(wall, shifted.Translated(frame.normal * toward)).Solid();
            return booleanShape(prism(profile, 0, toward * (std::abs(reach) + 2 * modelSize(context.body) + 10)), half, "cut");
        }
        if (end == "offset") fail("Offset extrusion requires a planar target");
    } else if (end != "body") fail("Unknown extrusion end condition: " + end);
    if (params.value("op").toString("add") != "add") fail("Up-to-body extrusion only supports add");
    const auto pieces = booleanShape(prism(profile, 0, farHeight), context.body, "cut");
    std::vector<TopoDS_Shape> adjacent;
    for (TopExp_Explorer explorer(pieces, TopAbs_SOLID); explorer.More(); explorer.Next()) {
        const auto pieceBox = bounds(explorer.Current()); const auto lower = point(pieceBox[0]), upper = point(pieceBox[1]);
        double minimum = std::numeric_limits<double>::infinity(), maximum = -minimum;
        for (double first : {lower.X(), upper.X()}) for (double second : {lower.Y(), upper.Y()}) for (double third : {lower.Z(), upper.Z()}) {
            const double height = gp_Vec(frame.origin, gp_Pnt(first, second, third)).Dot(frame.normal);
            minimum = std::min(minimum, height); maximum = std::max(maximum, height);
        }
        if (minimum <= 1e-4 && maximum >= -1e-4) adjacent.push_back(explorer.Current());
    }
    if (adjacent.empty()) fail("Up-to-body extrusion has no material adjacent to the sketch");
    return compound(adjacent);
}
struct Step { double first, second, length; };
TopoDS_Shape stack(const gp_Pnt &spot, const gp_Vec &direction, const std::vector<Step> &steps) {
    TopoDS_Shape result; double depth = 0;
    for (const auto &step : steps) {
        if (std::min(step.first, step.second) < 0 || std::max(step.first, step.second) <= 0 || step.length <= 0) fail("Hole/stud dimensions must be positive");
        const gp_Ax2 axis(spot.Translated(direction * depth), gp_Dir(direction));
        const auto solid = std::abs(step.first - step.second) < 1e-9 ? BRepPrimAPI_MakeCylinder(axis, step.first / 2, step.length).Shape()
            : BRepPrimAPI_MakeCone(axis, step.first / 2, step.second / 2, step.length).Shape();
        result = result.IsNull() ? solid : booleanShape(result, solid, "add"); depth += step.length;
    }
    return result;
}
int count(const QJsonObject &params, const QString &key, int fallback = 1) {
    const double value = number(params, key, fallback);
    if (value < 0.5 || value > 500.49) fail("Pattern count must be between 1 and 500");
    return static_cast<int>(std::nearbyint(value));
}
std::vector<Tool> seeds(const Context &context, const QJsonObject &params) {
    std::vector<Tool> result;
    const auto ids = params["features"].toArray();
    if (ids.isEmpty()) { if (empty(context.body)) fail("Pattern requires a body"); return {{context.body, "add", {}}}; }
    for (const auto &id : ids) {
        if (!context.tools.contains(id.toString())) fail("Feature cannot be patterned: " + id.toString());
        const auto &tools = context.tools[id.toString()]; result.insert(result.end(), tools.begin(), tools.end());
    }
    return result;
}
TopoDS_Shape replicate(Context &context, const QJsonObject &params, const std::vector<gp_Trsf> &transforms) {
    if (transforms.size() > 20000) fail("Pattern exceeds 20000 instances");
    const auto originals = seeds(context, params); auto body = context.body;
    std::vector<Tool> copies;
    for (const auto &transform : transforms) for (const auto &seed : originals) {
        const auto copy = moved(seed.shape, transform); body = combine(body, copy, seed.operation);
        copies.push_back({copy, seed.operation, seed.origin});
    }
    context.tools[context.current] = std::move(copies); return body;
}
}

TopoDS_Shape makeTool(const QString &kind, const QJsonObject &params, Context &context) {
    if (kind == "extrude") return extrude(params, context);
    if (kind == "revolve") {
        const auto &profile = sketch(context, params, true);
        gp_Ax1 rotationAxis;
        const QString ref = params.value("axis").toString("SY");
        if (ref.toUpper() == "CL") {
            bool found = false;
            for (const auto &value : profile.shapes) {
                const auto shape = value.toObject();
                if (shape["type"] != "line" || !shape["construction"].toBool()) continue;
                const auto first = profile.frame.point(number(shape, "x1"), number(shape, "y1"));
                const auto second = profile.frame.point(number(shape, "x2"), number(shape, "y2"));
                rotationAxis = gp_Ax1(first, gp_Dir(gp_Vec(first, second))); found = true; break;
            }
            if (!found) fail("Revolve requires a construction centerline");
        } else rotationAxis = axis(ref, context, &profile.frame);
        if (params["reverse"].toBool()) rotationAxis.Reverse();
        const double angle = number(params, "angle");
        if (std::abs(angle) <= 1e-6 || std::abs(angle) > 360 + 1e-9) fail("Revolve angle must be in (0,360]");
        auto shape = profile.profile;
        if (params["symmetric"].toBool() && std::abs(angle) < 360 - 1e-9) { gp_Trsf back; back.SetRotation(rotationAxis, -angle * pi / 360); shape = moved(shape, back); }
        BRepPrimAPI_MakeRevol maker(shape, rotationAxis, angle * pi / 180); return checked(maker, "Revolve");
    }
    if (kind == "sweep") {
        const auto &profile = sketch(context, params, true);
        auto spine = path(context, params["path"].toString());
        BRepAdaptor_CompCurve adaptor(spine); GProp_GProps props; BRepGProp::SurfaceProperties(profile.profile, props);
        if (adaptor.Value(adaptor.LastParameter()).Distance(props.CentreOfMass()) < adaptor.Value(adaptor.FirstParameter()).Distance(props.CentreOfMass()) - 1e-9) spine.Reverse();
        const QString pathId = params["path"].toString();
        if (context.helixAxes.contains(pathId) || adaptor.Continuity() == GeomAbs_C0) {
            if (profile.wires.size() != 1 || TopExp_Explorer(profile.profile, TopAbs_WIRE).More() == false) fail("This sweep requires one closed profile");
            TopTools_IndexedMapOfShape profileWires; TopExp::MapShapes(profile.profile, TopAbs_WIRE, profileWires);
            if (profileWires.Extent() != 1) fail("Sharp-corner and helix sweep profiles with holes are not yet supported");
            BRepOffsetAPI_MakePipeShell maker(spine);
            if (context.helixAxes.contains(pathId)) maker.SetMode(gp_Dir(context.helixAxes[pathId]));
            else maker.SetTransitionMode(BRepBuilderAPI_RightCorner);
            maker.Add(profile.wires.front()); maker.Build();
            if (!maker.IsDone() || !maker.MakeSolid()) fail("Sweep cannot form a closed solid");
            return maker.Shape();
        }
        BRepOffsetAPI_MakePipe maker(spine, profile.profile);
        auto result = checked(maker, "Sweep");
        if (!BRepCheck_Analyzer(result).IsValid()) fail("Sweep self-intersects or does not form a valid solid");
        return result;
    }
    if (kind == "loft" || kind == "boundary") {
        const auto ids = params["sketches"].toArray(); if (ids.size() < 2) fail("Loft requires two profiles");
        BRepOffsetAPI_ThruSections maker(true, params["ruled"].toBool(), tolerance);
        std::vector<int> counts;
        for (const auto &id : ids) {
            const QJsonObject profileParams{{"sketch", id}};
            const auto &profile = sketch(context, profileParams, true);
            if (profile.wires.empty()) fail("Loft profile has no outer wire");
            maker.AddWire(profile.wires.front()); TopTools_IndexedMapOfShape edges; TopExp::MapShapes(profile.wires.front(), TopAbs_EDGE, edges); counts.push_back(edges.Extent());
        }
        maker.CheckCompatibility(!std::all_of(counts.begin(), counts.end(), [&](int value) { return value == counts.front(); }));
        return checked(maker, "Loft");
    }
    if (kind == "hole" || kind == "hole_adv" || kind == "stud") {
        if (kind != "stud" && empty(context.body)) fail("Hole requires an existing body");
        if (kind == "hole_adv" && params["thread"].toBool()) fail("Advanced hole thread parameters are not supported");
        const auto &location = sketch(context, params); gp_Vec direction = location.frame.normal * (params["flip"].toBool() ? 1 : -1);
        std::vector<Step> steps;
        if (kind == "stud") {
            direction.Reverse(); const double diameter = number(params, "diameter", 0, true), length = number(params, "length", 0, true), bevel = number(params, "chamfer");
            if (bevel < 0 || bevel * 2 >= diameter || bevel >= length) fail("Invalid stud chamfer");
            if (params["thread"].toBool()) {
                const double pitch = number(params, "pitch") > 0 ? number(params, "pitch") : coarsePitch(diameter);
                std::vector<TopoDS_Shape> grooves, tips;
                for (const auto &spot : spots(location)) {
                    grooves.push_back(threadGroove(spot, direction, diameter, pitch, pitch, length + pitch, false, number(params, "phase")));
                    tips.push_back(tipTrimmer(spot, direction, diameter, length, bevel));
                }
                context.afterCuts = {compound(grooves), compound(tips)}; steps.push_back({diameter, diameter, length + 3 * pitch});
            } else { steps.push_back({diameter, diameter, length - bevel}); if (bevel > 0) steps.push_back({diameter, diameter - 2 * bevel, bevel}); }
        } else if (kind == "hole_adv") {
            for (const auto &value : params["steps"].toArray()) {
                const auto row = value.toArray(); if (row.size() < 2) fail("Hole steps require [diameter,depth]");
                const double diameter = row[0].toDouble(), depth = row[1].toDouble(); steps.push_back({diameter, diameter, depth > 0 ? depth : 2 * modelSize(context.body) + 10});
            }
            if (steps.empty()) fail("Hole has no steps");
        } else {
            double diameter = number(params, "diameter", 0, true), head = number(params, "head_diameter"), headDepth = number(params, "head_depth");
            const QString holeKind = params.value("kind").toString("simple"), size = params.value("size").toString("custom");
            const QMap<QString, std::vector<double>> standard{{"M2", {2.4, 4.3, 2.2, 4.0, 1.6}}, {"M2.5", {2.9, 5.5, 2.8, 5, 2.05}}, {"M3", {3.4, 6.5, 3.4, 6.72, 2.5}}, {"M4", {4.5, 8, 4.6, 8.96, 3.3}}, {"M5", {5.5, 10, 5.7, 11.2, 4.2}}, {"M6", {6.6, 11, 6.8, 13.44, 5}}, {"M8", {9, 15, 9, 17.92, 6.8}}, {"M10", {11, 18, 11, 22.4, 8.5}}, {"M12", {13.5, 20, 13, 26.88, 10.2}}};
            if (standard.contains(size)) { const auto &values = standard[size]; diameter = values[0]; head = holeKind == "counterbore" ? values[1] : values[3]; headDepth = values[2]; if (holeKind == "tapped") diameter = values[4]; }
            else if (holeKind == "tapped") fail("Tapped hole requires a supported metric size");
            const double depth = params.value("through").toBool(true) ? 2 * modelSize(context.body) + 10 : number(params, "depth", 0, true);
            if (holeKind == "tapped" && params["thread"].toBool()) {
                const double major = size.mid(1).toDouble(), pitch = coarsePitch(major); diameter = major - 1.082532 * pitch;
                std::vector<TopoDS_Shape> grooves;
                for (const auto &spot : spots(location)) grooves.push_back(threadGroove(spot, direction, major, pitch, -.5 * pitch, params.value("through").toBool(true) ? depth + pitch : depth - .5 * pitch, true, number(params, "phase")));
                context.afterCuts = {compound(grooves)};
            }
            if (holeKind == "counterbore" || holeKind == "countersink") {
                if (head <= diameter) fail("Counterbore diameter must exceed hole diameter");
                if (holeKind == "countersink") headDepth = (head - diameter) / 2;
                steps = {{head, holeKind == "counterbore" ? head : diameter, headDepth}, {diameter, diameter, std::max(depth - headDepth, 1e-3)}};
            } else if (holeKind == "simple" || holeKind == "tapped") steps = {{diameter, diameter, depth}};
            else fail("Unknown hole type: " + holeKind);
            if (params["thread"].toBool() && holeKind != "tapped") fail("Modeled hole thread requires the tapped hole type");
        }
        std::vector<TopoDS_Shape> solids; for (const auto &spot : spots(location)) solids.push_back(stack(spot, direction, steps)); return compound(solids);
    }
    if (kind == "screw") return screw(params, context);
    if (kind == "import_step") {
        const QString filename = params["path"].toString(); if (!QFileInfo::exists(filename)) fail("Import file not found: " + filename);
        const QString suffix = QFileInfo(filename).suffix().toLower();
        if (suffix != "step" && suffix != "stp") fail("Native solid import accepts .step/.stp; STL reconstruction is not yet implemented");
        auto result = file_io::readShape(filename);
        if (params.contains("scale")) { const double scale = number(params, "scale", 1, true); gp_Trsf transform; transform.SetScale({0, 0, 0}, scale); result = moved(result, transform); }
        for (const auto &key : {QString("rx"), QString("ry"), QString("rz")}) {
            const double angle = number(params, key); if (angle != 0) { gp_Trsf rotation; rotation.SetRotation(axis(key.right(1), context), angle * pi / 180); result = moved(result, rotation); }
        }
        return translated(result, gp_Vec(number(params, "dx"), number(params, "dy"), number(params, "dz")));
    }
    fail("Native solid feature not implemented: " + kind); return {};
}

TopoDS_Shape modify(const QString &kind, const QJsonObject &params, Context &context) {
    const auto &body = context.body; if (empty(body)) fail("Feature requires an existing body: " + kind);
    if (kind == "thread") {
        const auto edges = selectEdges(body, params["edges"]); if (edges.size() != 1) fail("Thread requires one circular edge");
        BRepAdaptor_Curve curve(edges.front()); if (curve.GetType() != GeomAbs_Circle) fail("Thread requires one circular edge");
        const auto circle = curve.Circle(); const auto center = circle.Location(); const gp_Vec along(circle.Axis().Direction()), side(circle.XAxis().Direction());
        const double radius = circle.Radius(), pitch = number(params, "pitch", 0, true), length = number(params, "length", 0, true), probe = std::min(radius, pitch) * .3;
        if (.6134 * pitch >= radius) fail("Thread pitch is too large for diameter");
        std::vector<int> external, internal;
        for (int sign : {1, -1}) {
            if (BRepClass3d_SolidClassifier(body, center.Translated(along * (sign * probe)), tolerance).State() == TopAbs_IN) external.push_back(sign);
            if (BRepClass3d_SolidClassifier(body, center.Translated(along * (sign * probe) + side * (radius + probe)), tolerance).State() == TopAbs_IN) internal.push_back(sign);
        }
        const bool inside = external.empty() && internal.size() == 1;
        if (external.size() != 1 && !inside) fail("Cannot determine thread direction at this edge");
        const auto direction = along * (inside ? internal.front() : external.front()); const double major = 2 * radius + (inside ? 1.082532 * pitch : 0);
        return combine(body, threadGroove(center, direction, major, pitch, -.5 * pitch, length, inside, number(params, "phase")), "cut");
    }
    if (kind == "fillet" || kind == "chamfer") {
        const double size = number(params, kind == "fillet" ? "radius" : "distance", 0, true);
        const auto edges = selectEdges(body, params["edges"]);
        if (kind == "fillet") { BRepFilletAPI_MakeFillet maker(body); for (const auto &edge : edges) maker.Add(size, edge); return checked(maker, "Fillet"); }
        BRepFilletAPI_MakeChamfer maker(body); for (const auto &edge : edges) maker.Add(size, edge); return checked(maker, "Chamfer");
    }
    if (kind == "draft") {
        const auto faces = selectFaces(body, params["faces"].toArray()); if (faces.empty()) fail("Draft requires selected faces");
        const auto plane = frame(params.contains("plane") ? params["plane"] : QJsonValue("XY"), context.features, number(params, "offset"));
        const double angle = number(params, "angle"); if (std::abs(angle) <= 1e-6 || std::abs(angle) >= 89) fail("Invalid draft angle");
        BRepOffsetAPI_DraftAngle maker(body);
        for (const auto &face : faces) { maker.Add(face, gp_Dir(plane.normal * (params["flip"].toBool() ? -1 : 1)), angle * pi / 180, gp_Pln(plane.origin, gp_Dir(plane.normal))); if (!maker.AddDone()) fail("Face cannot be drafted"); }
        return checked(maker, "Draft");
    }
    if (kind == "shell") {
        const double thickness = number(params, "thickness", 0, true); const auto faces = selectFaces(body, params["faces"].toArray());
        if (!faces.empty()) {
            TopTools_ListOfShape removed; for (const auto &face : faces) removed.Append(face);
            BRepOffsetAPI_MakeThickSolid maker; maker.MakeThickSolidByJoin(body, removed, -thickness, 1e-3); return checked(maker, "Shell");
        }
        BRepOffsetAPI_MakeOffsetShape maker; maker.PerformByJoin(body, -thickness, 1e-3); auto inner = checked(maker, "Inner shell");
        if (!TopExp_Explorer(inner, TopAbs_SOLID).More()) {
            TopExp_Explorer shells(inner, TopAbs_SHELL); if (!shells.More()) fail("Offset did not form a shell");
            inner = BRepBuilderAPI_MakeSolid(TopoDS::Shell(shells.Current())).Solid();
        }
        GProp_GProps props; BRepGProp::VolumeProperties(inner, props); if (props.Mass() < 0) inner.Reverse();
        if (volume(inner) >= volume(body) || !BRepCheck_Analyzer(inner).IsValid()) fail("Shell thickness exceeds the body");
        if (!params["walls"].toString().isEmpty()) inner = partition(inner, params, context, thickness);
        return hollow(body, inner, "void");
    }
    if (kind == "rib" || kind == "split" || kind == "wrap") return modifySurface(kind, params, context);
    if (kind == "pattern_variable") {
        const auto ids = params["features"].toArray(); if (ids.isEmpty()) fail("Variable pattern requires feature ids");
        const QStringList rows = params["rows"].toString().replace(QChar(0xff1b), ';').replace('\n', ';').split(';', Qt::SkipEmptyParts);
        if (rows.isEmpty() || rows.size() > 20000) fail("Variable pattern table is empty or too large");
        auto result = body; std::vector<Tool> copies;
        for (const auto &row : rows) {
            const auto cells = QString(row).replace(QChar(0xff0c), ',').split(',', Qt::SkipEmptyParts); std::vector<double> shift; QJsonObject changes;
            for (const auto &cell : cells) {
                const auto split = cell.split('='); bool ok = false;
                if (split.size() == 1) { const double value = cell.trimmed().toDouble(&ok); if (!ok || !std::isfinite(value)) fail("Invalid variable-pattern translation"); shift.push_back(value); }
                else if (split.size() == 2) { const double value = split[1].trimmed().toDouble(&ok); if (!ok || !std::isfinite(value)) fail("Invalid variable-pattern parameter"); changes[split[0].trimmed()] = value; }
                else fail("Variable pattern rows require dx,dy,dz,key=value");
            }
            if (shift.size() != 3) fail("Variable pattern requires three translation coordinates");
            for (const auto &id : ids) {
                QJsonObject seed; for (const auto &value : context.features) if (value.toObject()["id"] == id) { seed = value.toObject(); break; }
                if (seed.isEmpty() || !context.tools.contains(id.toString())) fail("Variable-pattern seed not found: " + id.toString());
                auto seedParams = seed["params"].toObject();
                for (auto change = changes.begin(); change != changes.end(); ++change) { if (!seedParams.contains(change.key())) fail("Seed has no parameter: " + change.key()); seedParams[change.key()] = change.value(); }
                const auto savedCuts = context.afterCuts; context.afterCuts.clear(); const auto savedBody = context.body; context.body = result;
                TopoDS_Shape solid;
                try { solid = makeTool(seed["type"].toString(), seedParams, context); } catch (...) { context.body = savedBody; context.afterCuts = savedCuts; throw; }
                const auto extraCuts = context.afterCuts; context.afterCuts = savedCuts; context.body = savedBody;
                const gp_Vec translation(shift[0], shift[1], shift[2]); solid = translated(solid, translation);
                const QString operation = seedParams.value("op").toString(seed["type"] == "hole" || seed["type"] == "hole_adv" ? "cut" : "add");
                result = combine(result, solid, operation); copies.push_back({solid, operation, id.toString()});
                for (const auto &cut : extraCuts) { const auto copy = translated(cut, translation); result = combine(result, copy, "cut"); copies.push_back({copy, "cut", id.toString()}); }
            }
        }
        context.tools[context.current] = std::move(copies); return result;
    }
    if (kind == "pattern_fill") {
        const auto &boundary = sketch(context, params, true); if (boundary.wires.empty()) fail("Fill pattern requires an outer contour");
        const double spacing = number(params, "spacing", 0, true), margin = number(params, "margin"); if (margin < 0) fail("Fill margin must be nonnegative");
        double minX = std::numeric_limits<double>::infinity(), minY = minX, maxX = -minX, maxY = -minX;
        for (const auto &value : segments(boundary.curves)) for (const auto &endpoint : value.toArray()) {
            const gp_Vec local(boundary.frame.origin, point(endpoint)); const double x = local.Dot(boundary.frame.x), y = local.Dot(boundary.frame.y);
            minX = std::min(minX, x); minY = std::min(minY, y); maxX = std::max(maxX, x); maxY = std::max(maxY, y);
        }
        const double centerX = (minX + maxX) / 2, centerY = (minY + maxY) / 2, half = std::hypot(maxX - minX, maxY - minY) / 2 + spacing;
        const bool hex = params["layout"] == "hex"; const double rowStep = spacing * (hex ? std::sqrt(3.0) / 2 : 1), angle = number(params, "angle") * pi / 180;
        if ((2 * half / rowStep + 3) * (2 * half / spacing + 5) > 20000) fail("Fill pattern exceeds 20000 candidate instances");
        const int rows = static_cast<int>(half / rowStep) + 1, columns = static_cast<int>(half / spacing) + 1;
        std::vector<gp_Pnt> positions;
        for (int row = -rows; row <= rows; ++row) for (int column = -columns; column <= columns; ++column) {
            const double x = column * spacing + (hex && row % 2 ? spacing / 2 : 0), y = row * rowStep;
            const auto spot = boundary.frame.point(centerX + x * std::cos(angle) - y * std::sin(angle), centerY + x * std::sin(angle) + y * std::cos(angle)); bool inside = false;
            for (TopExp_Explorer explorer(boundary.profile, TopAbs_FACE); explorer.More(); explorer.Next()) if (BRepClass_FaceClassifier(TopoDS::Face(explorer.Current()), spot, tolerance).State() == TopAbs_IN) { inside = true; break; }
            if (!inside) continue;
            const auto vertex = BRepBuilderAPI_MakeVertex(spot).Vertex(); BRepExtrema_DistShapeShape distance(vertex, boundary.curves); if (!distance.IsDone() || distance.Value() < margin) continue; positions.push_back(spot);
        }
        if (positions.empty()) fail("No fill-pattern instances fit inside the boundary");
        if (!params["features"].toArray().isEmpty()) {
            const auto originals = seeds(context, params); GProp_GProps props; BRepGProp::VolumeProperties(originals.front().shape, props); const auto center = props.CentreOfMass(); std::vector<gp_Trsf> transforms;
            for (const auto &spot : positions) { gp_Vec shift(center, spot); shift -= boundary.frame.normal * shift.Dot(boundary.frame.normal); if (shift.Magnitude() > 1e-9) { gp_Trsf transform; transform.SetTranslation(shift); transforms.push_back(transform); } }
            return replicate(context, params, transforms);
        }
        const double radius = number(params, "diameter", 0, true) / 2, reach = modelSize(body) * 2 + 10; std::vector<TopoDS_Shape> cutters;
        for (const auto &spot : positions) cutters.push_back(BRepPrimAPI_MakeCylinder(gp_Ax2(spot.Translated(boundary.frame.normal * -reach), gp_Dir(boundary.frame.normal)), radius, reach * 2).Shape());
        return combine(body, compound(cutters), "cut");
    }
    std::vector<gp_Trsf> transforms;
    if (kind == "mirror") {
        const auto plane = frame(params.contains("plane") ? params["plane"] : QJsonValue("YZ"), context.features, number(params, "offset")); gp_Trsf transform; transform.SetMirror(gp_Ax2(plane.origin, gp_Dir(plane.normal))); transforms.push_back(transform);
    } else if (kind == "pattern_linear") {
        const int count1 = count(params, "count1"), count2 = count(params, "count2"); if (count1 * count2 > 20000) fail("Pattern exceeds 20000 instances");
        const gp_Vec first(axis(params.value("axis1").toString("X"), context).Direction()), second(axis(params.value("axis2").toString("Y"), context).Direction());
        for (int row = 0; row < count2; ++row) for (int column = 0; column < count1; ++column) if (row || column) { gp_Trsf transform; transform.SetTranslation(first * (column * number(params, "spacing1")) + second * (row * number(params, "spacing2"))); transforms.push_back(transform); }
    } else if (kind == "pattern_circular") {
        const int instances = count(params, "count"); const double total = number(params, "angle"), step = instances < 2 ? 0 : total / (std::abs(std::abs(total) - 360) < 1e-9 ? instances : instances - 1);
        for (int index = 1; index < instances; ++index) { gp_Trsf transform; transform.SetRotation(axis(params.value("axis").toString("Z"), context), step * index * pi / 180); transforms.push_back(transform); }
    } else if (kind == "pattern_table" || kind == "pattern_sketch") {
        const auto originals = seeds(context, params); GProp_GProps props; BRepGProp::VolumeProperties(originals.front().shape, props); const auto center = props.CentreOfMass();
        std::vector<gp_Pnt> targets; gp_Vec normal;
        if (kind == "pattern_sketch") { const auto &location = sketch(context, params); targets = spots(location); normal = location.frame.normal; }
        else {
            for (const auto &value : params["points"].toArray()) { auto row = value.toArray(); if (row.size() == 2) row.append(center.Z()); targets.push_back(point(row)); }
            if (targets.empty()) fail("Pattern table is empty");
        }
        for (const auto &target : targets) { gp_Vec shift(center, target); if (kind == "pattern_sketch") shift -= normal * shift.Dot(normal); if (shift.Magnitude() > 1e-9) { gp_Trsf transform; transform.SetTranslation(shift); transforms.push_back(transform); } }
    } else if (kind == "pattern_curve") {
        BRepAdaptor_CompCurve adaptor(path(context, params["path"].toString())); const int instances = count(params, "count");
        const double length = GCPnts_AbscissaPoint::Length(adaptor), spacing = number(params, "spacing");
        if (spacing < 0) fail("Curve pattern spacing must be nonnegative");
        const bool closed = adaptor.Value(adaptor.FirstParameter()).Distance(adaptor.Value(adaptor.LastParameter())) < tolerance;
        const double step = spacing > 0 ? spacing : length / (closed ? instances : std::max(1, instances - 1));
        if (step * (instances - 1) > length + tolerance) fail("Curve path is too short for this count and spacing");
        gp_Pnt start; gp_Vec heading; adaptor.D1(adaptor.FirstParameter(), start, heading);
        for (int index = 1; index < instances; ++index) {
            GCPnts_AbscissaPoint finder(adaptor, std::min(step * index, length), adaptor.FirstParameter()); if (!finder.IsDone()) fail("Curve pattern parameter failed");
            gp_Pnt target; gp_Vec tangent; adaptor.D1(finder.Parameter(), target, tangent);
            gp_Trsf transform; transform.SetTranslation(gp_Vec(start, target));
            if (params["align"].toBool() && heading.Magnitude() > 1e-9 && tangent.Magnitude() > 1e-9) {
                const auto pivot = heading.Crossed(tangent); if (pivot.Magnitude() > 1e-9) { gp_Trsf turn; turn.SetRotation(gp_Ax1(start, gp_Dir(pivot)), heading.Angle(tangent)); transform.Multiply(turn); }
            }
            transforms.push_back(transform);
        }
    } else fail("Native modifier not implemented: " + kind);
    return replicate(context, params, transforms);
}

TopoDS_Wire makeCurve(const QString &kind, const QJsonObject &params, Context &context) {
    if (kind == "curve_project" || kind == "curve_surface") return surfaceCurve(kind, params, context);
    if (kind == "curve_helix") {
        const auto &location = sketch(context, params); QJsonObject circle;
        for (const auto &value : location.shapes) if (value.toObject()["type"] == "circle") { circle = value.toObject(); break; }
        if (circle.isEmpty()) fail("Helix requires a circle sketch");
        const double pitch = number(params, "pitch", 0, true), turns = number(params, "turns", 0, true), taper = number(params, "taper"), radius = number(circle, "r", 0, true);
        if (turns * 24 > 20000) fail("Helix exceeds 20000 samples");
        const int count = std::max(4, static_cast<int>(turns * 24)); const auto center = location.frame.point(number(circle, "cx"), number(circle, "cy"));
        const bool spiral = params["kind"] == "spiral"; const double sense = params["clockwise"].toBool() ? -1 : 1, start = number(params, "start") * pi / 180;
        std::vector<gp_Pnt> points;
        for (int index = 0; index <= count; ++index) {
            const double turn = turns * index / count, reach = radius + (spiral ? pitch : taper) * turn, angle = start + sense * 2 * pi * turn;
            if (reach <= 1e-6) fail("Helix radius becomes nonpositive");
            points.push_back(center.Translated((location.frame.x * std::cos(angle) + location.frame.y * std::sin(angle)) * reach + location.frame.normal * (spiral ? 0 : pitch * turn)));
        }
        if (!spiral) context.helixAxes[context.current] = location.frame.normal;
        return spline(points);
    }
    if (kind == "curve_composite") {
        TopTools_ListOfShape edges;
        if (!params["edges"].toArray().isEmpty() || params["edges"].isString()) for (const auto &edge : selectEdges(context.body, params["edges"])) edges.Append(edge);
        for (const auto &id : params["curves"].toArray()) for (TopExp_Explorer explorer(path(context, id.toString()), TopAbs_EDGE); explorer.More(); explorer.Next()) edges.Append(explorer.Current());
        BRepBuilderAPI_MakeWire maker; maker.Add(edges); if (edges.IsEmpty() || !maker.IsDone()) fail("Composite curves are disconnected"); return maker.Wire();
    }
    std::vector<gp_Pnt> points; bool closed = params["closed"].toBool();
    if (kind == "sketch3d" || kind == "curve_xyz") {
        for (const auto &value : params["points"].toArray()) points.push_back(point(value));
    } else if (kind == "curve_points") {
        for (const auto &id : params["points"].toArray()) {
            bool found = false;
            for (const auto &value : context.features) {
                const auto feature = value.toObject();
                if (feature["id"] == id && feature["type"] == "point") { points.push_back(point(feature["params"].toObject()["position"].toArray().first())); found = true; break; }
            }
            if (!found) fail("Reference point not found: " + id.toString());
        }
    } else fail("Native curve not implemented: " + kind);
    if (kind != "sketch3d" || params["kind"] == "spline") return spline(points, closed);
    if (points.size() < (closed ? 3u : 2u)) fail("3D sketch has too few points");
    BRepBuilderAPI_MakePolygon maker; for (const auto &value : points) maker.Add(value); if (closed) maker.Close();
    if (!maker.IsDone()) fail("3D sketch points do not form a wire");
    return maker.Wire();
}

TopoDS_Shape reference(const QString &kind, const QJsonObject &params, Context &context) {
    const double size = empty(context.body) ? 50 : std::max(10.0, modelSize(context.body) * 0.2);
    std::vector<TopoDS_Shape> edges;
    auto add = [&](const gp_Pnt &first, const gp_Pnt &second) { edges.push_back(BRepBuilderAPI_MakeEdge(first, second).Edge()); };
    if (kind == "plane") {
        const auto plane = frame(context.current, context.features);
        const std::vector<gp_Pnt> corners{plane.point(-size, -size), plane.point(size, -size), plane.point(size, size), plane.point(-size, size)};
        for (size_t index = 0; index < corners.size(); ++index) add(corners[index], corners[(index + 1) % corners.size()]);
    } else if (kind == "axis") {
        const auto line = axis(context.current, context); const gp_Vec direction(line.Direction()); add(line.Location().Translated(direction * -size), line.Location().Translated(direction * size));
    } else if (kind == "point") {
        const auto origin = point(params["position"].toArray().first());
        for (const auto &direction : {gp_Vec(1, 0, 0), gp_Vec(0, 1, 0), gp_Vec(0, 0, 1)}) add(origin.Translated(direction * (-size * 0.05)), origin.Translated(direction * (size * 0.05)));
    } else if (kind == "csys") {
        const auto origin = point(params["origin"].toArray().first()); gp_Trsf total;
        for (const auto &key : {QString("rx"), QString("ry"), QString("rz")}) { gp_Trsf turn; turn.SetRotation(axis(key.right(1), context), number(params, key) * pi / 180); total = turn.Multiplied(total); }
        for (auto direction : {gp_Vec(1, 0, 0), gp_Vec(0, 1, 0), gp_Vec(0, 0, 1)}) { direction.Transform(total); add(origin, origin.Translated(direction * size)); }
    } else if (kind == "com") {
        if (empty(context.body)) fail("Center of mass requires a body");
        GProp_GProps props; BRepGProp::VolumeProperties(context.body, props); const auto center = props.CentreOfMass();
        context.info[context.current] = QString("Center of mass (%1, %2, %3)").arg(center.X()).arg(center.Y()).arg(center.Z());
        for (const auto &direction : {gp_Vec(1, 0, 0), gp_Vec(0, 1, 0), gp_Vec(0, 0, 1)}) add(center.Translated(direction * (-size * 0.1)), center.Translated(direction * (size * 0.1)));
    } else if (kind == "bbox") {
        if (empty(context.body)) fail("Bounding box requires a body");
        const auto box = bounds(context.body); const auto lower = point(box[0]), upper = point(box[1]);
        context.info[context.current] = QString("Bounding box %1 x %2 x %3 mm").arg(upper.X() - lower.X()).arg(upper.Y() - lower.Y()).arg(upper.Z() - lower.Z());
        for (int coordinate = 0; coordinate < 3; ++coordinate) for (int first = 0; first < 2; ++first) for (int second = 0; second < 2; ++second) {
            double start[3]{lower.X(), lower.Y(), lower.Z()}, end[3]{upper.X(), upper.Y(), upper.Z()};
            const int a = (coordinate + 1) % 3, b = (coordinate + 2) % 3;
            start[a] = end[a] = (first ? upper : lower).Coord(a + 1); start[b] = end[b] = (second ? upper : lower).Coord(b + 1);
            add({start[0], start[1], start[2]}, {end[0], end[1], end[2]});
        }
    } else fail("Native reference not implemented: " + kind);
    return compound(edges);
}
}
#endif
