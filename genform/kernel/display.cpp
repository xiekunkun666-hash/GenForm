#include "native.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepTools.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GProp_GProps.hxx>
#include <Poly_Triangulation.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <algorithm>
#include <limits>
#include <set>

namespace genform::kernel::native {
namespace {
TopTools_IndexedMapOfShape indexed(const TopoDS_Shape &shape, TopAbs_ShapeEnum kind) {
    TopTools_IndexedMapOfShape result; TopExp::MapShapes(shape, kind, result); return result;
}
QString surfaceName(GeomAbs_SurfaceType kind) {
    switch (kind) {
    case GeomAbs_Plane: return "plane";
    case GeomAbs_Cylinder: return "cylinder";
    case GeomAbs_Cone: return "cone";
    case GeomAbs_Sphere: return "sphere";
    case GeomAbs_Torus: return "torus";
    default: return "surface";
    }
}
QJsonObject faceInfo(const TopoDS_Face &face, int id) {
    BRepAdaptor_Surface surface(face); GProp_GProps props; BRepGProp::SurfaceProperties(face, props);
    QJsonObject info{{"id", id}, {"type", surfaceName(surface.GetType())}, {"center", json(props.CentreOfMass())}, {"area", props.Mass()}, {"normal", QJsonValue::Null}};
    if (surface.GetType() == GeomAbs_Plane) info["normal"] = json(gp_Vec(surface.Plane().Axis().Direction()) * (face.Orientation() == TopAbs_REVERSED ? -1 : 1));
    if (surface.GetType() == GeomAbs_Cylinder) info["radius"] = surface.Cylinder().Radius();
    return info;
}
QJsonObject edgeInfo(const TopoDS_Edge &edge, int id) {
    BRepAdaptor_Curve curve(edge); const double first = curve.FirstParameter(), last = curve.LastParameter();
    QJsonObject info{{"id", id}, {"mid", json(curve.Value((first + last) / 2))}, {"length", GCPnts_AbscissaPoint::Length(curve)},
                     {"type", curve.GetType() == GeomAbs_Line ? "line" : curve.GetType() == GeomAbs_Circle ? "circle" : "curve"}, {"dir", QJsonValue::Null}};
    if (curve.GetType() == GeomAbs_Line) {
        gp_Vec direction(curve.Value(first), curve.Value(last)); if (direction.Magnitude() > 1e-12) info["dir"] = json(direction.Normalized());
    } else if (curve.GetType() == GeomAbs_Circle) {
        const auto circle = curve.Circle(); info["radius"] = circle.Radius(); info["center"] = json(circle.Location()); info["axis"] = json(gp_Vec(circle.Axis().Direction()));
    }
    return info;
}
bool sameSurface(const TopoDS_Face &first, const TopoDS_Face &second) {
    BRepAdaptor_Surface a(first), b(second); if (a.GetType() != b.GetType()) return false;
    if (a.GetType() == GeomAbs_Plane) {
        const auto planeA = a.Plane(), planeB = b.Plane();
        return planeA.Axis().Direction().IsParallel(planeB.Axis().Direction(), 1e-7) && planeA.Distance(planeB.Location()) < 1e-5;
    }
    if (a.GetType() == GeomAbs_Cylinder) {
        const auto cylinderA = a.Cylinder(), cylinderB = b.Cylinder();
        return std::abs(cylinderA.Radius() - cylinderB.Radius()) < 1e-5 && cylinderA.Axis().IsCoaxial(cylinderB.Axis(), 1e-7, 1e-5);
    }
    return BRep_Tool::Surface(first) == BRep_Tool::Surface(second);
}
QJsonObject describe(const QString &kind, const TopoDS_Shape &shape, int id) {
    QJsonObject result{{"kind", kind}, {"id", id}};
    if (kind == "vertex") { result["type"] = "vertex"; result["point"] = json(BRep_Tool::Pnt(TopoDS::Vertex(shape))); return result; }
    if (kind == "edge") {
        result = edgeInfo(TopoDS::Edge(shape), id); result["kind"] = kind; result.remove("mid");
        if (result["type"] == "line") result["dir"] = json(gp_Vec(BRepAdaptor_Curve(TopoDS::Edge(shape)).Line().Direction()));
        return result;
    }
    const auto face = TopoDS::Face(shape); BRepAdaptor_Surface surface(face);
    result = faceInfo(face, id); result["kind"] = kind; result.remove("normal"); result.remove("center");
    if (surface.GetType() == GeomAbs_Plane) {
        result["normal"] = json(gp_Vec(surface.Plane().Axis().Direction()) * (face.Orientation() == TopAbs_REVERSED ? -1 : 1)); result["point"] = json(surface.Plane().Location());
    } else if (surface.GetType() == GeomAbs_Cylinder) {
        result["axis"] = json(gp_Vec(surface.Cylinder().Axis().Direction())); result["axis_point"] = json(surface.Cylinder().Location());
    } else if (surface.GetType() == GeomAbs_Cone) {
        result["axis"] = json(gp_Vec(surface.Cone().Axis().Direction())); result["axis_point"] = json(surface.Cone().Location()); result["half_angle"] = std::abs(surface.Cone().SemiAngle() * 180 / pi);
    } else if (surface.GetType() == GeomAbs_Sphere) { result["radius"] = surface.Sphere().Radius(); result["center"] = json(surface.Sphere().Location()); }
    return result;
}
}

QJsonArray edgeTable(const TopoDS_Shape &body) {
    QJsonArray result; const auto edges = indexed(body, TopAbs_EDGE);
    for (int index = 1; index <= edges.Extent(); ++index) {
        const auto edge = TopoDS::Edge(edges(index)); if (!BRep_Tool::Degenerated(edge)) result.append(edgeInfo(edge, index - 1));
    }
    return result;
}
std::vector<TopoDS_Edge> selectEdges(const TopoDS_Shape &body, const QJsonValue &selection) {
    const auto edges = indexed(body, TopAbs_EDGE); const auto table = edgeTable(body); const double size = modelSize(body);
    std::set<int> selected;
    if (selection.isString()) {
        const auto text = selection.toString().trimmed();
        if (text.toLower() == "all") for (const auto &value : table) selected.insert(value.toObject()["id"].toInt());
        else if (text.size() == 2 && QString("|<>").contains(text[0]) && QString("XYZ").contains(text[1].toUpper())) {
            const int coordinate = QString("XYZ").indexOf(text[1].toUpper()); double extreme = text[0] == '>' ? -std::numeric_limits<double>::infinity() : std::numeric_limits<double>::infinity();
            for (const auto &value : table) {
                const double height = value.toObject()["mid"].toArray()[coordinate].toDouble(); extreme = text[0] == '>' ? std::max(extreme, height) : std::min(extreme, height);
            }
            for (const auto &value : table) {
                const auto entry = value.toObject();
                if (text[0] == '|') {
                    const auto direction = entry["dir"].toArray(); if (!direction.isEmpty() && std::abs(std::abs(direction[coordinate].toDouble()) - 1) < 1e-6) selected.insert(entry["id"].toInt());
                } else if (std::abs(entry["mid"].toArray()[coordinate].toDouble() - extreme) <= size * 1e-4) selected.insert(entry["id"].toInt());
            }
        } else fail("Unknown edge selector: " + text);
    } else {
        for (const auto &value : selection.toArray()) {
            const auto target = point(value.toObject()["point"]); double minimum = std::numeric_limits<double>::infinity(); int nearest = -1;
            for (const auto &entry : table) { const auto info = entry.toObject(); const double distance = target.Distance(point(info["mid"])); if (distance < minimum) { minimum = distance; nearest = info["id"].toInt(); } }
            if (nearest < 0 || minimum > size * 0.25) fail("Referenced edge no longer exists");
            selected.insert(nearest);
        }
    }
    if (selected.empty()) fail("No edges selected");
    std::vector<TopoDS_Edge> result; for (int id : selected) result.push_back(TopoDS::Edge(edges(id + 1))); return result;
}
std::vector<TopoDS_Face> selectFaces(const TopoDS_Shape &body, const QJsonArray &selection) {
    const auto faces = indexed(body, TopAbs_FACE); std::vector<gp_Pnt> centers;
    for (int index = 1; index <= faces.Extent(); ++index) { GProp_GProps props; BRepGProp::SurfaceProperties(faces(index), props); centers.push_back(props.CentreOfMass()); }
    std::set<int> chosen; const double size = modelSize(body);
    for (const auto &value : selection) {
        const auto target = point(value.toObject()["point"]); double minimum = std::numeric_limits<double>::infinity(); int nearest = -1;
        for (size_t index = 0; index < centers.size(); ++index) { const double distance = target.Distance(centers[index]); if (distance < minimum) { minimum = distance; nearest = static_cast<int>(index); } }
        if (nearest < 0 || minimum > size * 0.25) fail("Referenced face no longer exists");
        chosen.insert(nearest);
    }
    std::vector<TopoDS_Face> result; for (int id : chosen) result.push_back(TopoDS::Face(faces(id + 1))); return result;
}
QJsonArray segments(const TopoDS_Shape &body, QJsonArray *owners) {
    QJsonArray result; const auto edges = indexed(body, TopAbs_EDGE);
    for (int index = 1; index <= edges.Extent(); ++index) {
        const auto edge = TopoDS::Edge(edges(index)); if (BRep_Tool::Degenerated(edge)) continue;
        BRepAdaptor_Curve curve(edge); const int count = curve.GetType() == GeomAbs_Line ? 1 : 48;
        const double first = curve.FirstParameter(), last = curve.LastParameter(); if (!std::isfinite(first) || !std::isfinite(last)) fail("Unbounded display curve");
        auto previous = curve.Value(first);
        for (int step = 1; step <= count; ++step) {
            const auto next = curve.Value(first + (last - first) * step / count); result.append(QJsonArray{json(previous), json(next)}); if (owners) owners->append(index - 1); previous = next;
        }
    }
    return result;
}
QJsonObject properties(const TopoDS_Shape &body) {
    const auto bodyMass = mass(body); GProp_GProps area; BRepGProp::SurfaceProperties(body, area);
    const auto box = bounds(body); const auto low = point(box[0]), high = point(box[1]);
    return {{"volume", std::abs(bodyMass.volume)}, {"area", area.Mass()}, {"bodies", indexed(body, TopAbs_SOLID).Extent()},
            {"bbox_min", box[0]}, {"bbox_max", box[1]}, {"size", QJsonArray{high.X() - low.X(), high.Y() - low.Y(), high.Z() - low.Z()}}, {"center_of_mass", json(bodyMass.center)}};
}

void inheritOwners(Context &context, const TopoDS_Shape &before) {
    if (empty(context.body) || (!before.IsNull() && before.IsSame(context.body))) return;
    const auto faces = indexed(context.body, TopAbs_FACE); const auto previous = context.owners; context.owners.clear();
    for (int index = 1; index <= faces.Extent(); ++index) {
        const auto face = TopoDS::Face(faces(index)); Owner owner{face, context.current, {}};
        bool inherited = false;
        for (const auto &old : previous) if (face.IsSame(old.face)) { owner.feature = old.feature; owner.origin = old.origin; inherited = true; break; }
        if (!inherited) for (const auto &old : previous) {
            if (!sameSurface(face, old.face)) continue;
            BRepExtrema_DistShapeShape distance(face, old.face); if (distance.IsDone() && distance.Value() <= 1e-5) { owner.feature = old.feature; owner.origin = old.origin; inherited = true; break; }
        }
        if (!inherited && context.tools.contains(context.current)) for (const auto &copy : context.tools[context.current]) {
            if (copy.origin.isEmpty() || copy.origin == context.current) continue;
            for (TopExp_Explorer explorer(copy.shape, TopAbs_FACE); explorer.More(); explorer.Next()) {
                const auto source = TopoDS::Face(explorer.Current());
                if (face.IsSame(source)) { owner.origin = copy.origin; break; }
                if (sameSurface(face, source)) { BRepExtrema_DistShapeShape distance(face, source); if (distance.IsDone() && distance.Value() <= 1e-5) { owner.origin = copy.origin; break; } }
            }
            if (!owner.origin.isEmpty()) break;
        }
        context.owners.push_back(owner);
    }
}

QJsonObject model(const Context &context) {
    QJsonObject sketchLines; for (auto entry = context.sketches.cbegin(); entry != context.sketches.cend(); ++entry) sketchLines[entry.key()] = segments(entry->curves);
    for (auto entry = context.display.cbegin(); entry != context.display.cend(); ++entry) sketchLines[entry.key()] = segments(entry.value());
    QJsonObject result{{"status", context.status}, {"sketches", sketchLines}, {"info", context.info}, {"has_body", !empty(context.body)}};
    if (empty(context.body)) return result;
    const auto &body = context.body; const double deflection = std::max(0.05, modelSize(body) * 1e-4);
    BRepTools::Clean(body); BRepMesh_IncrementalMesh mesher(body, deflection, false, 0.3, true);
    if (!mesher.IsDone()) fail("OpenCascade tessellation failed");
    QJsonArray vertices, normals, triangles, triangleFaces, faces;
    const auto faceMap = indexed(body, TopAbs_FACE), edgeMap = indexed(body, TopAbs_EDGE);
    QMap<QString,int> featureOrder;
    for (qsizetype index = 0; index < context.features.size(); ++index) featureOrder[context.features[index].toObject().value("id").toString()] = int(index);
    QMap<int,QJsonObject> edgeOwners;
    for (int index = 1; index <= faceMap.Extent(); ++index) {
        const auto face = TopoDS::Face(faceMap(index)); QJsonObject info = faceInfo(face, index - 1);
        info["feature"] = QJsonValue::Null;
        for (const auto &owner : context.owners) if (owner.face.IsSame(face)) { info["feature"] = owner.feature; if (!owner.origin.isEmpty()) info["origin"] = owner.origin; break; }
        QJsonArray around; std::set<int> edgeIds; const auto localEdges = indexed(face, TopAbs_EDGE);
        for (int edgeIndex = 1; edgeIndex <= localEdges.Extent(); ++edgeIndex) if (!BRep_Tool::Degenerated(TopoDS::Edge(localEdges(edgeIndex)))) edgeIds.insert(edgeMap.FindIndex(localEdges(edgeIndex)) - 1);
        for (int edgeId : edgeIds) {
            around.append(edgeId);
            const auto feature = info.value("feature").toString();
            if (!feature.isEmpty() && (!edgeOwners.contains(edgeId) || featureOrder.value(feature,-1) >= featureOrder.value(edgeOwners.value(edgeId).value("feature").toString(),-1))) {
                QJsonObject owner{{"feature",feature}};
                if (info.contains("origin")) owner["origin"] = info.value("origin");
                edgeOwners[edgeId] = owner;
            }
        }
        info["edges"] = around; faces.append(info);
        TopLoc_Location location; const Handle(Poly_Triangulation) mesh = BRep_Tool::Triangulation(face, location);
        if (mesh.IsNull()) continue;
        const int base = static_cast<int>(vertices.size()), count = mesh->NbNodes(); const auto transform = location.Transformation();
        std::vector<gp_Pnt> positions; positions.reserve(count); std::vector<gp_Vec> accumulated(static_cast<size_t>(count), gp_Vec(0, 0, 0));
        for (int node = 1; node <= count; ++node) { const auto value = mesh->Node(node).Transformed(transform); positions.push_back(value); vertices.append(json(value)); }
        const bool reverse = (face.Orientation() == TopAbs_REVERSED) != transform.IsNegative();
        for (int triangleIndex = 1; triangleIndex <= mesh->NbTriangles(); ++triangleIndex) {
            int first, second, third; mesh->Triangle(triangleIndex).Get(first, second, third); if (reverse) std::swap(second, third); --first; --second; --third;
            const gp_Vec normal = gp_Vec(positions[first], positions[second]).Crossed(gp_Vec(positions[first], positions[third]));
            accumulated[first] += normal; accumulated[second] += normal; accumulated[third] += normal;
            triangles.append(QJsonArray{base + first, base + second, base + third}); triangleFaces.append(index - 1);
        }
        for (int node = 1; node <= count; ++node) {
            gp_Vec normal = accumulated[node - 1];
            if (mesh->HasNormals()) { normal = gp_Vec(mesh->Normal(node)); normal.Transform(transform); if (reverse) normal.Reverse(); }
            if (normal.Magnitude() > 1e-15) normal.Normalize();
            normals.append(json(normal));
        }
    }
    if (vertices.isEmpty() || triangles.isEmpty()) fail("A solid produced no display triangles");
    QJsonArray segmentOwners; const auto lines = segments(body, &segmentOwners); QJsonArray points; const auto vertexMap = indexed(body, TopAbs_VERTEX);
    for (int index = 1; index <= vertexMap.Extent(); ++index) points.append(json(BRep_Tool::Pnt(TopoDS::Vertex(vertexMap(index)))));
    auto displayEdges = edgeTable(body);
    for (qsizetype index = 0; index < displayEdges.size(); ++index) {
        auto edge = displayEdges[index].toObject();
        const auto owner = edgeOwners.value(edge.value("id").toInt(-1));
        edge["feature"] = owner.value("feature");
        if (owner.contains("origin")) edge["origin"] = owner.value("origin");
        displayEdges[index] = edge;
    }
    result["verts"] = vertices; result["normals"] = normals; result["tris"] = triangles; result["tri_face"] = triangleFaces; result["faces"] = faces;
    result["segments"] = lines; result["segment_edge"] = segmentOwners; result["edges"] = displayEdges; result["props"] = properties(body); result["vertices"] = points;
    return result;
}

QJsonObject measure(const Context &context, const QJsonObject &args) {
    if (empty(context.body)) fail("Measurement requires a body");
    const auto items = args["items"].toArray(); QJsonArray infos; std::vector<TopoDS_Shape> shapes;
    for (qsizetype index = 0; index < std::min<qsizetype>(2, items.size()); ++index) {
        const auto item = items[index].toObject(); const QString kind = item["kind"].toString(); const int id = item.value("id").toInt(-1);
        const auto code = kind == "face" ? TopAbs_FACE : kind == "edge" ? TopAbs_EDGE : TopAbs_VERTEX;
        if (kind != "face" && kind != "edge" && kind != "vertex") fail("Unknown measurement entity kind");
        const auto mapping = indexed(context.body, code); if (id < 0 || id >= mapping.Extent()) fail("Measurement entity no longer exists");
        shapes.push_back(mapping(id + 1)); infos.append(describe(kind, mapping(id + 1), id));
    }
    QJsonObject result{{"items", infos}};
    if (shapes.size() != 2) return result;
    BRepExtrema_DistShapeShape distance(shapes[0], shapes[1]); if (!distance.IsDone() || distance.NbSolution() < 1) fail("Distance calculation failed");
    const auto first = distance.PointOnShape1(1), second = distance.PointOnShape2(1);
    result["distance"] = distance.Value(); result["points"] = QJsonArray{json(first), json(second)}; result["delta"] = QJsonArray{std::abs(second.X() - first.X()), std::abs(second.Y() - first.Y()), std::abs(second.Z() - first.Z())};
    auto direction = [](const QJsonObject &info, bool &normal) -> QJsonArray {
        normal = info.contains("normal"); if (normal) return info["normal"].toArray();
        if (info.contains("dir") && info["dir"].isArray()) return info["dir"].toArray();
        if (info.contains("axis")) { normal = info["type"] != "cylinder" && info["type"] != "cone"; return info["axis"].toArray(); }
        return {};
    };
    const auto infoA = infos[0].toObject(), infoB = infos[1].toObject(); bool normalA = false, normalB = false;
    const auto directionA = direction(infoA, normalA), directionB = direction(infoB, normalB);
    if (!directionA.isEmpty() && !directionB.isEmpty()) {
        const double angle = std::acos(std::clamp(std::abs(vector(directionA).Normalized().Dot(vector(directionB).Normalized())), 0.0, 1.0)) * 180 / pi;
        result["angle"] = normalA == normalB ? angle : 90 - angle;
        if (infoA["type"] == "plane" && infoB["type"] == "plane" && angle < 1e-6) result["normal_distance"] = std::abs(gp_Vec(point(infoA["point"]), point(infoB["point"])).Dot(vector(directionA)));
    }
    const bool centerA = infoA.contains("center"), centerB = infoB.contains("center");
    const bool axisA = infoA.contains("axis_point"), axisB = infoB.contains("axis_point");
    if ((centerA || axisA) && (centerB || axisB)) {
        const auto a = point(infoA[centerA ? "center" : "axis_point"]), b = point(infoB[centerB ? "center" : "axis_point"]);
        const gp_Vec delta(a, b);
        if (centerA && centerB) result["center_distance"] = a.Distance(b);
        else if (axisA && axisB) {
            const auto alongA = vector(infoA["axis"]), alongB = vector(infoB["axis"]), cross = alongA.Crossed(alongB);
            result["center_distance"] = cross.Magnitude() < 1e-9 ? delta.Crossed(alongA).Magnitude() : std::abs(delta.Dot(cross)) / cross.Magnitude();
        } else result["center_distance"] = delta.Crossed(vector((axisA ? infoA : infoB)["axis"])).Magnitude();
    }
    return result;
}
}
#endif
