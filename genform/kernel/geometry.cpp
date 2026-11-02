#include "native.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRep_Builder.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRep_Tool.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepGProp.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <Geom_BezierCurve.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>
#include <gp_Elips.hxx>
#include <algorithm>
#include <limits>

namespace genform::kernel::native {

QJsonArray json(const gp_Pnt &value) { return {value.X(), value.Y(), value.Z()}; }
QJsonArray json(const gp_Vec &value) { return {value.X(), value.Y(), value.Z()}; }
gp_Pnt point(const QJsonValue &value) {
    const auto coordinates = value.toArray();
    if (coordinates.size() != 3) fail("Expected three coordinates");
    for (const auto &coordinate : coordinates)
        if (!coordinate.isDouble() || !std::isfinite(coordinate.toDouble())) fail("Coordinates must be finite numbers");
    return {coordinates[0].toDouble(), coordinates[1].toDouble(), coordinates[2].toDouble()};
}
gp_Vec vector(const QJsonValue &value) { const auto valuePoint = point(value); return {valuePoint.X(), valuePoint.Y(), valuePoint.Z()}; }
gp_Pnt Frame::point(double first, double second) const { return origin.Translated(x * first + y * second); }

Frame frame(const QJsonValue &reference, const QJsonArray &features, double offset, int depth) {
    if (depth > 50) fail("Cyclic reference plane dependency");
    Frame result;
    if (reference.isObject()) {
        const auto object = reference.toObject();
        result.origin = point(object["origin"]);
        result.x = vector(object["x"]); result.y = vector(object["y"]);
    } else {
        const QString name = reference.toString("XY");
        if (name.toUpper() == "XZ") { result.x = {1, 0, 0}; result.y = {0, 0, 1}; }
        else if (name.toUpper() == "YZ") { result.x = {0, 1, 0}; result.y = {0, 0, 1}; }
        else if (name.toUpper() != "XY") {
            QJsonObject params;
            bool found = false;
            for (const auto &value : features) {
                const auto feature = value.toObject();
                if (feature["id"].toString() == name && feature["type"] == "plane") {
                    params = feature["params"].toObject(); found = true; break;
                }
            }
            if (!found) fail("Reference plane not found: " + name);
            if (!params["origin"].toArray().isEmpty() && !params["normal"].toArray().isEmpty()) {
                result.origin = point(params["origin"].toArray().first());
                result.normal = vector(params["normal"].toArray().first());
                if (result.normal.Magnitude() < 1e-12) fail("Zero plane normal");
                result.normal.Normalize();
                const gp_Vec helper = std::abs(result.normal.Z()) < 0.9 ? gp_Vec(0, 0, 1) : gp_Vec(1, 0, 0);
                result.x = helper.Crossed(result.normal).Normalized();
                result.y = result.normal.Crossed(result.x);
            } else result = frame(params.contains("base") ? params["base"] : QJsonValue("XY"), features, 0, depth + 1);
            result.normal = result.x.Crossed(result.y);
            const double angle = number(params, "angle") * pi / 180;
            if (params.value("about").toString("x") == "x") result.y = result.y * std::cos(angle) + result.normal * std::sin(angle);
            else result.x = result.x * std::cos(angle) - result.normal * std::sin(angle);
            result.normal = result.x.Crossed(result.y);
            result.origin.Translate(result.normal * number(params, "offset"));
        }
    }
    if (result.x.Magnitude() < 1e-12 || result.y.Magnitude() < 1e-12) fail("Invalid plane axes");
    result.x.Normalize(); result.y.Normalize();
    if (std::abs(result.x.Dot(result.y)) > 1e-6) fail("Plane axes must be perpendicular");
    result.normal = result.x.Crossed(result.y).Normalized();
    result.origin.Translate(result.normal * offset);
    return result;
}

gp_Ax1 axis(const QString &reference, const Context &context, const Frame *sketchFrame) {
    const QString upper = reference.toUpper();
    if (upper == "X") return {{0, 0, 0}, {1, 0, 0}};
    if (upper == "Y") return {{0, 0, 0}, {0, 1, 0}};
    if (upper == "Z") return {{0, 0, 0}, {0, 0, 1}};
    if ((upper == "SX" || upper == "SY") && sketchFrame)
        return {sketchFrame->origin, gp_Dir(upper == "SX" ? sketchFrame->x : sketchFrame->y)};
    if (reference.startsWith('@')) {
        const auto halves = reference.mid(1).split(';');
        if (halves.size() != 2) fail("Axis must be @x,y,z;dx,dy,dz");
        QJsonArray origin, direction;
        for (const auto &half : halves) {
            QJsonArray values;
            for (const auto &entry : half.split(',')) {
                bool ok = false; const double value = entry.toDouble(&ok);
                if (!ok || !std::isfinite(value)) fail("Invalid axis coordinates");
                values.append(value);
            }
            if (origin.isEmpty()) origin = values; else direction = values;
        }
        return {point(origin), gp_Dir(vector(direction))};
    }
    for (const auto &value : context.features) {
        const auto feature = value.toObject();
        if (feature["id"] == reference && feature["type"] == "axis") {
            const auto params = feature["params"].toObject();
            return {point(params["origin"].toArray().first()), gp_Dir(vector(params["direction"].toArray().first()))};
        }
    }
    fail("Reference axis not found: " + reference);
    return {};
}

TopoDS_Shape compound(const std::vector<TopoDS_Shape> &shapes) {
    BRep_Builder builder; TopoDS_Compound result; builder.MakeCompound(result);
    for (const auto &shape : shapes) if (!shape.IsNull()) builder.Add(result, shape);
    return result;
}
TopoDS_Shape moved(const TopoDS_Shape &shape, const gp_Trsf &transform) { return BRepBuilderAPI_Transform(shape, transform, true).Shape(); }
TopoDS_Shape translated(const TopoDS_Shape &shape, const gp_Vec &translation) {
    gp_Trsf transform; transform.SetTranslation(translation); return moved(shape, transform);
}
bool empty(const TopoDS_Shape &shape) {
    if (shape.IsNull()) return true;
    return !TopExp_Explorer(shape, TopAbs_FACE).More();
}
double volume(const TopoDS_Shape &shape) {
    return std::abs(mass(shape).volume);
}
Mass mass(const TopoDS_Shape &shape) {
    if (shape.IsNull()) return {0, {0, 0, 0}, 0};
    static thread_local std::vector<std::pair<TopoDS_Shape, Mass>> cache;
    for (const auto &entry : cache) if (entry.first.IsEqual(shape)) return entry.second;
    bool freeform = false;
    for (TopExp_Explorer explorer(shape, TopAbs_FACE); explorer.More(); explorer.Next()) {
        const auto type = BRepAdaptor_Surface(TopoDS::Face(explorer.Current())).GetType();
        if (type == GeomAbs_BSplineSurface || type == GeomAbs_BezierSurface || type == GeomAbs_OffsetSurface || type == GeomAbs_OtherSurface) { freeform = true; break; }
    }
    GProp_GProps props; double relativeError = 0;
    if (freeform) relativeError = BRepGProp::VolumeProperties(shape, props, 1e-7);
    else BRepGProp::VolumeProperties(shape, props);
    if (!std::isfinite(props.Mass()) || !std::isfinite(relativeError)) fail("Volume integration did not converge");
    const Mass result{props.Mass(), props.CentreOfMass(), std::abs(relativeError * props.Mass())};
    if (cache.size() >= 128) cache.erase(cache.begin());
    cache.push_back({shape, result}); return result;
}
void validateSolid(const TopoDS_Shape &shape) {
    if (shape.IsNull()) fail("Feature produced a null solid");
    if (shape.ShapeType() == TopAbs_COMPOUND || shape.ShapeType() == TopAbs_COMPSOLID) {
        bool found = false;
        for (TopoDS_Iterator iterator(shape); iterator.More(); iterator.Next()) { found = true; validateSolid(iterator.Value()); }
        if (!found) fail("Feature produced an empty solid compound");
        return;
    }
    if (shape.ShapeType() != TopAbs_SOLID) fail("Feature left unclosed faces, shells or wires instead of solids");
    for (TopExp_Explorer explorer(shape, TopAbs_SHELL); explorer.More(); explorer.Next()) if (!BRep_Tool::IsClosed(explorer.Current())) fail("Feature produced an open shell");
    BRepClass3d_SolidClassifier classifier(shape); classifier.PerformInfinitePoint(1e-7);
    if (classifier.State() != TopAbs_OUT || mass(shape).volume <= 1e-9 || !BRepCheck_Analyzer(shape).IsValid()) fail("Feature produced an invalid, reversed or non-finite solid");
}
QJsonArray bounds(const TopoDS_Shape &shape) {
    if (shape.IsNull()) fail("Cannot bound an empty shape");
    Bnd_Box box; BRepBndLib::AddOptimal(shape, box, false, false);
    if (box.IsVoid() || box.IsOpen()) fail("Shape has no finite bounds");
    return {json(box.CornerMin()), json(box.CornerMax())};
}
double modelSize(const TopoDS_Shape &shape) {
    if (shape.IsNull()) return 100;
    const auto box = bounds(shape); return std::max(1.0, point(box[0]).Distance(point(box[1])));
}
TopoDS_Shape booleanShape(const TopoDS_Shape &body, const TopoDS_Shape &tool, const QString &operation) {
    auto perform = [&](auto &maker) {
        TopTools_ListOfShape arguments, tools; arguments.Append(body);
        TopTools_IndexedMapOfShape solids;
        if (tool.ShapeType() == TopAbs_COMPOUND) TopExp::MapShapes(tool, TopAbs_SOLID, solids);
        if (solids.Extent() > 1) for (int index = 1; index <= solids.Extent(); ++index) tools.Append(solids(index));
        else tools.Append(tool);
        maker.SetArguments(arguments); maker.SetTools(tools); maker.SetNonDestructive(true);
        maker.SetRunParallel(true); maker.SetUseOBB(true); maker.SetFuzzyValue(1e-7); maker.Build();
        if (!maker.IsDone() || maker.HasErrors()) fail("OpenCascade boolean failed: " + operation);
        return maker.Shape();
    };
    if (operation == "add") { BRepAlgoAPI_Fuse maker; return perform(maker); }
    if (operation == "cut") { BRepAlgoAPI_Cut maker; return perform(maker); }
    if (operation == "common") { BRepAlgoAPI_Common maker; return perform(maker); }
    fail("Unsupported boolean operation: " + operation);
    return {};
}
TopoDS_Shape combine(const TopoDS_Shape &body, const TopoDS_Shape &tool, const QString &operation) {
    if (operation == "void" || operation == "fill" || operation == "pocket" || operation.startsWith("pocket:")) return hollow(body, tool, operation);
    if (operation != "add" && operation != "cut" && operation != "common")
        fail("Native kernel does not yet implement operation: " + operation);
    validateSolid(tool);
    if (empty(body)) {
        if (operation != "add") fail("A body is required for cut/common");
        return tool;
    }
    TopoDS_Shape result = booleanShape(body, tool, operation);
    if (empty(result) || volume(result) < 1e-9) fail("Boolean removed the entire body or produced no intersection");
    validateSolid(result);
    const double before = volume(body), after = volume(result), toolVolume = volume(tool);
    const double slack = std::max({1e-5, before * 1e-7, toolVolume * 1e-7}) + 2 * (mass(body).error + mass(tool).error + mass(result).error);
    if ((operation == "cut" && (after > before + slack || before - after > toolVolume + slack)) ||
        (operation == "common" && after > std::min(before, toolVolume) + slack) ||
        (operation == "add" && (after < std::max(before, toolVolume) - slack || after > before + toolVolume + slack)))
        fail("Boolean failed volume conservation validation");
    if (operation == "cut" && std::abs(after - before) <= std::max(1e-6, before * 1e-9)) fail("Cut did not change the body");
    ShapeUpgrade_UnifySameDomain unify(result, true, true, false); unify.Build();
    const auto unified = unify.Shape();
    if (!empty(unified) && BRepCheck_Analyzer(unified).IsValid() && std::abs(volume(unified) - after) <= slack) result = unified;
    return result;
}

namespace {
struct Point2 { double x, y; };
Point2 coordinates(const QJsonValue &value) {
    const auto array = value.toArray();
    if (array.size() < 2 || !array[0].isDouble() || !array[1].isDouble()) fail("Expected a 2D point");
    if (!std::isfinite(array[0].toDouble()) || !std::isfinite(array[1].toDouble())) fail("Non-finite sketch point");
    return {array[0].toDouble(), array[1].toDouble()};
}
std::vector<TopoDS_Edge> primitiveEdges(const QJsonObject &shape, const Frame &frame) {
    const QString kind = shape["type"].toString();
    std::vector<TopoDS_Edge> edges;
    auto at = [&](Point2 point) { return frame.point(point.x, point.y); };
    auto line = [&](Point2 first, Point2 second) {
        if (at(first).Distance(at(second)) < 1e-9) fail("Zero-length sketch edge");
        edges.push_back(BRepBuilderAPI_MakeEdge(at(first), at(second)).Edge());
    };
    auto arc = [&](Point2 center, double radius, double start, double end, bool reverse = false) {
        BRepBuilderAPI_MakeEdge maker(gp_Circ(gp_Ax2(at(center), gp_Dir(frame.normal), gp_Dir(frame.x)), radius), start, end);
        if (!maker.IsDone()) fail("Invalid circular arc");
        auto edge = maker.Edge(); if (reverse) edge.Reverse(); edges.push_back(edge);
    };
    auto bezier = [&](const std::vector<Point2> &poles) {
        if (poles.size() < 2 || poles.size() > 25) fail("Bezier needs 2 to 25 poles");
        TColgp_Array1OfPnt points(1, static_cast<int>(poles.size()));
        for (size_t index = 0; index < poles.size(); ++index) points.SetValue(static_cast<int>(index) + 1, at(poles[index]));
        edges.push_back(BRepBuilderAPI_MakeEdge(new Geom_BezierCurve(points)).Edge());
    };
    const Point2 center{number(shape, "cx"), number(shape, "cy")};
    if (kind == "point" || kind == "text") return {};
    if (kind == "line") line({number(shape, "x1"), number(shape, "y1")}, {number(shape, "x2"), number(shape, "y2")});
    else if (kind == "rect" || kind == "polygon" || kind == "ngon") {
        std::vector<Point2> points;
        if (kind == "rect") {
            const double halfWidth = number(shape, "w", 0, true) / 2, halfHeight = number(shape, "h", 0, true) / 2;
            points = {{center.x - halfWidth, center.y - halfHeight}, {center.x + halfWidth, center.y - halfHeight},
                      {center.x + halfWidth, center.y + halfHeight}, {center.x - halfWidth, center.y + halfHeight}};
        } else if (kind == "ngon") {
            const int sides = static_cast<int>(number(shape, "sides", 6));
            if (sides < 3 || sides > 100) fail("Polygon sides must be between 3 and 100");
            const double radius = number(shape, "r", 0, true), turn = number(shape, "angle") * pi / 180;
            for (int index = 0; index < sides; ++index) points.push_back({center.x + radius * std::cos(turn + 2 * pi * index / sides), center.y + radius * std::sin(turn + 2 * pi * index / sides)});
        } else for (const auto &value : shape["points"].toArray()) points.push_back(coordinates(value));
        if (points.size() < 3) fail("Polygon needs three points");
        for (size_t index = 0; index < points.size(); ++index) line(points[index], points[(index + 1) % points.size()]);
    } else if (kind == "circle" || kind == "arc") {
        const double radius = number(shape, "r", 0, true);
        if (kind == "circle") edges.push_back(BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(at(center), gp_Dir(frame.normal), gp_Dir(frame.x)), radius)).Edge());
        else {
            const double start = number(shape, "a0") * pi / 180;
            double sweep = std::fmod(number(shape, "a1") * pi / 180 - start, 2 * pi);
            if (sweep <= 0) sweep += 2 * pi;
            arc(center, radius, start, start + sweep);
        }
    } else if (kind == "ellipse") {
        double major = number(shape, "rx", 0, true), minor = number(shape, "ry", 0, true), turn = number(shape, "angle") * pi / 180;
        if (minor > major) { std::swap(major, minor); turn += pi / 2; }
        const gp_Vec along = frame.x * std::cos(turn) + frame.y * std::sin(turn);
        edges.push_back(BRepBuilderAPI_MakeEdge(gp_Elips(gp_Ax2(at(center), gp_Dir(frame.normal), gp_Dir(along)), major, minor)).Edge());
    } else if (kind == "slot") {
        Point2 first{number(shape, "x1"), number(shape, "y1")}, second{number(shape, "x2"), number(shape, "y2")};
        const double length = std::hypot(second.x - first.x, second.y - first.y), half = number(shape, "w", 0, true) / 2;
        if (length < 1e-9) fail("Slot centers coincide");
        const double nx = -(second.y - first.y) * half / length, ny = (second.x - first.x) * half / length, turn = std::atan2(-ny, -nx);
        line({first.x - nx, first.y - ny}, {second.x - nx, second.y - ny}); arc(second, half, turn, turn + pi);
        line({second.x + nx, second.y + ny}, {first.x + nx, first.y + ny}); arc(first, half, turn + pi, turn + 2 * pi);
    } else if (kind == "arcslot") {
        const double radius = number(shape, "r", 0, true), half = number(shape, "w", 0, true) / 2, start = number(shape, "a0") * pi / 180;
        if (half >= radius) fail("Arc slot width exceeds diameter");
        double sweep = std::fmod(number(shape, "a1") * pi / 180 - start, 2 * pi); if (sweep <= 0) sweep += 2 * pi;
        const double end = start + sweep;
        arc(center, radius + half, start, end);
        arc({center.x + radius * std::cos(end), center.y + radius * std::sin(end)}, half, end, end + pi);
        arc(center, radius - half, start, end, true);
        arc({center.x + radius * std::cos(start), center.y + radius * std::sin(start)}, half, start + pi, start + 2 * pi);
    } else if (kind == "spline" || kind == "equation") {
        std::vector<Point2> points;
        if (kind == "equation") {
            const double start = number(shape, "t0"), stop = number(shape, "t1", 1);
            if (std::abs(start - stop) < 1e-12) fail("Equation range is empty");
            for (int index = 0; index <= 60; ++index) {
                const double value = start + (stop - start) * index / 60;
                Point2 result;
                if (shape.value("mode").toString("explicit") == "parametric") result = {evaluate(shape.value("fx").toString("t"), {{"t", value}}), evaluate(shape.value("fy").toString("0"), {{"t", value}})};
                else result = {value, evaluate(shape.value("fy").toString("0"), {{"x", value}})};
                result.x += number(shape, "ox"); result.y += number(shape, "oy"); points.push_back(result);
            }
        } else for (const auto &value : shape["points"].toArray()) points.push_back(coordinates(value));
        if (points.size() < 2) fail("Spline needs two points");
        if (shape["style"].toBool()) {
            if (points.size() > 12) fail("Style spline exceeds 12 control points");
            bezier(points);
        } else {
            const int count = static_cast<int>(points.size()); const bool closed = shape["closed"].toBool() && count > 2;
            auto atIndex = [&](int index) { return points[closed ? (index + count) % count : std::clamp(index, 0, count - 1)]; };
            for (int index = 0; index < (closed ? count : count - 1); ++index) {
                const auto before = atIndex(index - 1), start = atIndex(index), end = atIndex(index + 1), after = atIndex(index + 2);
                bezier({start, {start.x + (end.x - before.x) / 6, start.y + (end.y - before.y) / 6}, {end.x - (after.x - start.x) / 6, end.y - (after.y - start.y) / 6}, end});
            }
        }
    } else fail("Native sketch primitive not implemented: " + kind);
    return edges;
}
}

Sketch makeSketch(const QJsonObject &params, const QJsonArray &features) {
    Sketch result; result.frame = frame(params.contains("plane") ? params["plane"] : QJsonValue("XY"), features, number(params, "offset"));
    result.shapes = params["shapes"].toArray();
    if (result.shapes.isEmpty()) fail("Sketch has no shapes");
    std::vector<TopoDS_Edge> pending;
    std::vector<TopoDS_Shape> curves;
    for (const auto &value : result.shapes) {
        const auto shape = value.toObject();
        if (shape["construction"].toBool()) continue;
        for (const auto &edge : primitiveEdges(shape, result.frame)) { pending.push_back(edge); curves.push_back(edge); }
    }
    result.curves = compound(curves);
    std::vector<TopoDS_Wire> loops;
    while (!pending.empty()) {
        auto firstEdge = pending.front(); pending.erase(pending.begin());
        TopoDS_Vertex startVertex, endVertex; TopExp::Vertices(firstEdge, startVertex, endVertex, true);
        gp_Pnt start = BRep_Tool::Pnt(startVertex), end = BRep_Tool::Pnt(endVertex);
        BRepBuilderAPI_MakeWire builder; builder.Add(firstEdge);
        while (start.Distance(end) > tolerance) {
            bool extended = false;
            for (auto entry = pending.begin(); entry != pending.end(); ++entry) {
                TopoDS_Vertex first, second; TopExp::Vertices(*entry, first, second, true);
                const gp_Pnt head = BRep_Tool::Pnt(first), tail = BRep_Tool::Pnt(second);
                if (end.Distance(head) > tolerance && end.Distance(tail) > tolerance) continue;
                TopoDS_Edge edge = *entry;
                if (end.Distance(head) > tolerance) { edge.Reverse(); end = head; } else end = tail;
                builder.Add(edge); pending.erase(entry); extended = true; break;
            }
            if (!extended) break;
        }
        if (!builder.IsDone()) fail("Sketch edges do not form a connected wire");
        if (start.Distance(end) <= tolerance) loops.push_back(builder.Wire());
    }
    std::vector<TopoDS_Shape> loopFaces;
    for (const auto &wire : loops) {
        BRepBuilderAPI_MakeFace maker(wire, true);
        if (!maker.IsDone()) fail("Sketch loop cannot form a planar face");
        auto face = maker.Face(); BRepAdaptor_Surface surface(face);
        const double facing = gp_Vec(surface.Plane().Axis().Direction()).Dot(result.frame.normal) * (face.Orientation() == TopAbs_REVERSED ? -1 : 1);
        if (facing < 0) face.Reverse();
        loopFaces.push_back(face);
    }
    std::vector<double> areas;
    for (const auto &face : loopFaces) { GProp_GProps props; BRepGProp::SurfaceProperties(face, props); areas.push_back(props.Mass()); }
    std::vector<std::vector<bool>> inside(loops.size(), std::vector<bool>(loops.size(), false));
    std::vector<int> depths(loops.size(), 0);
    for (size_t outer = 0; outer < loops.size(); ++outer) for (size_t inner = 0; inner < loops.size(); ++inner) {
        if (areas[outer] <= areas[inner] + 1e-9) continue;
        const auto overlap = booleanShape(loopFaces[outer], loopFaces[inner], "common");
        GProp_GProps props; if (!overlap.IsNull()) BRepGProp::SurfaceProperties(overlap, props);
        if (std::abs(props.Mass() - areas[inner]) <= std::max(1e-8, areas[inner] * 1e-7)) { inside[outer][inner] = true; ++depths[inner]; }
    }
    std::vector<TopoDS_Shape> faces;
    for (size_t index = 0; index < loops.size(); ++index) {
        if (depths[index] % 2) continue;
        auto face = loopFaces[index];
        for (size_t hole = 0; hole < loops.size(); ++hole)
            if (depths[hole] == depths[index] + 1 && inside[index][hole]) face = booleanShape(face, loopFaces[hole], "cut");
        faces.push_back(face); if (depths[index] == 0) result.wires.push_back(loops[index]);
    }
    for (const auto &value : result.shapes) {
        const auto shape = value.toObject();
        if (shape["type"] == "text" && !shape["construction"].toBool()) {
            const auto letters = makeText(shape, result.frame);
            faces.insert(faces.end(), letters.begin(), letters.end()); curves.insert(curves.end(), letters.begin(), letters.end());
        }
    }
    result.curves = compound(curves);
    if (!faces.empty()) result.profile = faces.size() == 1 ? faces.front() : compound(faces);
    return result;
}

const Sketch &sketch(const Context &context, const QJsonObject &params, bool requireProfile) {
    const QString id = params["sketch"].toString();
    const auto found = context.sketches.constFind(id);
    if (found == context.sketches.cend()) fail("Sketch not found: " + id);
    if (requireProfile && found->profile.IsNull()) fail("Sketch has no closed profile");
    return found.value();
}
std::vector<gp_Pnt> spots(const Sketch &sketch) {
    std::vector<gp_Pnt> result;
    for (const auto &value : sketch.shapes) {
        const auto shape = value.toObject(); const QString kind = shape["type"].toString();
        if (kind == "point") result.push_back(sketch.frame.point(number(shape, "x"), number(shape, "y")));
        if (kind == "circle" || kind == "arc") result.push_back(sketch.frame.point(number(shape, "cx"), number(shape, "cy")));
    }
    if (result.empty()) fail("Location sketch has no points or circle centers");
    return result;
}
TopoDS_Wire path(const Context &context, const QString &id) {
    if (context.curves.contains(id)) return context.curves[id];
    if (!context.sketches.contains(id)) fail("Path not found: " + id);
    TopTools_ListOfShape edges;
    for (TopExp_Explorer explorer(context.sketches[id].curves, TopAbs_EDGE); explorer.More(); explorer.Next()) edges.Append(explorer.Current());
    BRepBuilderAPI_MakeWire maker; maker.Add(edges);
    if (edges.IsEmpty() || !maker.IsDone()) fail("Path is disconnected or branched");
    return maker.Wire();
}
TopoDS_Wire spline(const std::vector<gp_Pnt> &points, bool closed) {
    if (points.size() < (closed ? 3u : 2u)) fail("Not enough spline points");
    Handle(TColgp_HArray1OfPnt) array = new TColgp_HArray1OfPnt(1, static_cast<int>(points.size()));
    for (size_t index = 0; index < points.size(); ++index) array->SetValue(static_cast<int>(index) + 1, points[index]);
    GeomAPI_Interpolate maker(array, closed, tolerance); maker.Perform();
    if (!maker.IsDone()) fail("Spline interpolation failed");
    return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(maker.Curve()).Edge()).Wire();
}
}
#endif
