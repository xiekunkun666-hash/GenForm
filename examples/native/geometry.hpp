#pragma once

#include "runner.hpp"
#include "genform/kernel/native.hpp"
#include <QFileInfo>
#include <QFile>
#include <QTemporaryDir>
#include <QTextStream>
#include <QMap>
#include <cmath>
#include <memory>
#include <vector>

#ifdef GENFORM_HAS_OCCT
#include <BRep_Builder.hxx>
#include <BRepTools.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <GProp_GProps.hxx>
#include <STEPControl_Reader.hxx>
#include <STEPControl_Writer.hxx>
#include <StlAPI_Reader.hxx>
#include <StlAPI_Writer.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Trsf.hxx>
#endif

namespace examples {
#ifdef GENFORM_HAS_OCCT

inline double volume(const TopoDS_Shape &shape) { if (shape.IsNull()) return 0; GProp_GProps properties; BRepGProp::VolumeProperties(shape, properties); return std::abs(properties.Mass()); }
inline QJsonArray coordinates(const gp_Pnt &point) { return {point.X(), point.Y(), point.Z()}; }
inline gp_Pnt point(const QJsonArray &array) { require(array.size() == 3, "Expected three coordinates"); return {array[0].toDouble(), array[1].toDouble(), array[2].toDouble()}; }
inline TopoDS_Shape compound(const std::vector<TopoDS_Shape> &shapes) { BRep_Builder builder; TopoDS_Compound result; builder.MakeCompound(result); for (const auto &shape : shapes) if (!shape.IsNull()) builder.Add(result, shape); return result; }
inline int count(const TopoDS_Shape &shape, TopAbs_ShapeEnum kind) { int result = 0; for (TopExp_Explorer explorer(shape, kind); explorer.More(); explorer.Next()) ++result; return result; }
inline QJsonObject metrics(const TopoDS_Shape &shape) {
    require(!shape.IsNull(), "Empty shape"); auto result = genform::kernel::native::properties(shape);
    result["valid"] = BRepCheck_Analyzer(shape).IsValid(); result["solids"] = count(shape, TopAbs_SOLID); result["faces"] = count(shape, TopAbs_FACE);
    result["volume_mm3"] = result["volume"]; result["size_mm"] = result["size"]; return result;
}
inline void validModel(const QJsonObject &model) {
    require(model["has_body"].toBool(), "Model has no solid"); const auto statuses = model["status"].toObject();
    for (auto iterator = statuses.begin(); iterator != statuses.end(); ++iterator) require(iterator.value() == "ok" || iterator.value() == "suppressed", iterator.key() + ": " + iterator.value().toString());
}
inline TopoDS_Shape fromKernel(genform::kernel::Kernel &builder) {
    validModel(builder.query("model")); QTemporaryDir temporary; require(temporary.isValid(), "Cannot create native BRep transfer directory");
    const QString path = temporary.filePath("native.brep"); builder.exportFile(path); TopoDS_Shape shape; BRep_Builder topology;
    require(BRepTools::Read(shape, QFile::encodeName(path).constData(), topology), "Cannot read native BRep transfer"); return shape;
}
inline TopoDS_Shape buildShape(const QJsonArray &features, std::optional<int> upto = {}) { genform::kernel::Kernel builder; validModel(builder.build(features, upto)); return fromKernel(builder); }
inline TopoDS_Shape loadShape(const QString &path) {
    require(QFileInfo::exists(path), "Missing geometry input: " + path);
    const auto suffix = QFileInfo(path).suffix().toLower(); TopoDS_Shape shape;
    if (suffix == "gform") { genform::Document document; document.open(path); return buildShape(document.features, document.upto); }
    if (suffix == "brep") { BRep_Builder builder; require(BRepTools::Read(shape, QFile::encodeName(path).constData(), builder), "BREP read failed: " + path); }
    else if (suffix == "step" || suffix == "stp") { STEPControl_Reader reader; require(reader.ReadFile(QFile::encodeName(path).constData()) == IFSelect_RetDone, "STEP read failed: " + path); require(reader.TransferRoots() > 0, "STEP has no transferable roots"); shape = reader.OneShape(); }
    else if (suffix == "stl") { StlAPI_Reader reader; require(reader.Read(shape, QFile::encodeName(path).constData()), "STL read failed: " + path); }
    else require(false, "Unsupported geometry input: " + path);
    require(!shape.IsNull(), "Empty geometry input: " + path); return shape;
}
inline void exportShape(const TopoDS_Shape &shape, const QString &path) {
    require(QDir().mkpath(QFileInfo(path).absolutePath()), "Cannot create geometry output folder");
    if (path.endsWith(".brep")) require(BRepTools::Write(shape, QFile::encodeName(path).constData()), "BREP write failed");
    else if (path.endsWith(".stl")) { BRepMesh_IncrementalMesh mesh(shape, .05, false, .2, true); require(mesh.IsDone(), "STL meshing failed"); StlAPI_Writer writer; writer.ASCIIMode() = false; require(writer.Write(shape, QFile::encodeName(path).constData()), "STL write failed"); }
    else { STEPControl_Writer writer; require(writer.Transfer(shape, STEPControl_AsIs) == IFSelect_RetDone && writer.Write(QFile::encodeName(path).constData()) == IFSelect_RetDone, "STEP write failed: " + path); }
    require(QFileInfo(path).size() > 0, "Empty geometry export");
}
inline TopoDS_Shape placed(const TopoDS_Shape &shape, const QJsonObject &row) {
    require(!row["mirror"].toBool() && !row.contains("swing"), "Example shape placement does not accept mirror/swing; use the native assembly engine for these transforms");
    require(!row.contains("turn") || row["turn"].toArray().size() == 3, "Assembly turn must have three coordinates");
    require(!row.contains("move") || row["move"].toArray().size() == 3, "Assembly move must have three coordinates");
    auto result = shape; const auto turn = row["turn"].toArray();
    for (int axis = 0; axis < 3; ++axis) { const double degrees = axis < turn.size() ? turn[axis].toDouble() : 0; if (!degrees) continue; gp_Trsf transform; transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(axis == 0, axis == 1, axis == 2)), degrees * std::acos(-1.0) / 180); result = BRepBuilderAPI_Transform(result, transform, true).Shape(); }
    const auto move = row["move"].toArray(); if (!move.isEmpty()) { gp_Trsf transform; transform.SetTranslation(gp_Vec(move[0].toDouble(), move[1].toDouble(), move[2].toDouble())); result = BRepBuilderAPI_Transform(result, transform, true).Shape(); }
    return result;
}

class ShapeCache {
    QMap<QString, TopoDS_Shape> shapes_;
public:
    TopoDS_Shape get(const QString &path) { const QString key = QFileInfo(path).absoluteFilePath(); if (!shapes_.contains(key)) shapes_[key] = loadShape(key); return shapes_[key]; }
    std::vector<TopoDS_Shape> rows(const QDir &directory, const QJsonArray &parts) {
        std::vector<TopoDS_Shape> result; for (const auto &value : parts) { const auto row = value.toObject(); const QString path = row.contains("path") ? row["path"].toString() : directory.filePath(row["file"].toString()); result.push_back(placed(get(path), row)); } return result;
    }
    QJsonObject interference(const QDir &directory, const QJsonArray &parts) {
        const auto shapes = rows(directory, parts); QJsonArray clashes; int pairs = 0;
        for (size_t first = 0; first < shapes.size(); ++first) for (size_t second = first + 1; second < shapes.size(); ++second) {
            ++pairs; const auto firstBox = genform::kernel::native::bounds(shapes[first]), secondBox = genform::kernel::native::bounds(shapes[second]); bool separate = false;
            for (int axis = 0; axis < 3; ++axis) if (firstBox[1].toArray()[axis].toDouble() < secondBox[0].toArray()[axis].toDouble() || secondBox[1].toArray()[axis].toDouble() < firstBox[0].toArray()[axis].toDouble()) separate = true;
            if (separate) continue; BRepAlgoAPI_Common operation(shapes[first], shapes[second]); operation.Build(); require(operation.IsDone(), "Assembly Boolean intersection failed");
            const double overlap = volume(operation.Shape()); if (overlap > 1e-5) clashes.append(QJsonObject{{"a", static_cast<int>(first)}, {"b", static_cast<int>(second)}, {"volume_mm3", overlap}});
        }
        return {{"pairs", pairs}, {"clashes", clashes}};
    }
};

inline bool occupied(const TopoDS_Shape &shape, const gp_Pnt &position) {
    for (TopExp_Explorer explorer(shape, TopAbs_SOLID); explorer.More(); explorer.Next()) { BRepClass3d_SolidClassifier classifier(explorer.Current(), position, 1e-6); if (classifier.State() == TopAbs_IN) return true; } return false;
}
inline double intersectionVolume(const TopoDS_Shape &shape, const gp_Pnt &start, const gp_Dir &direction, double radius, double length) { const auto cylinder = BRepPrimAPI_MakeCylinder(gp_Ax2(start, direction), radius, length).Shape(); BRepAlgoAPI_Common intersection(shape, cylinder); intersection.Build(); require(intersection.IsDone(), "Void intersection failed"); return volume(intersection.Shape()); }

int surfaceExamples(const Options &options);
int presentAssembly(const Options &options);
QJsonObject assemblyReport(const QDir &directory, const QJsonArray &parts, ShapeCache &cache);
#endif
}
