#include "native.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRep_Tool.hxx>
#include <BRepAdaptor_CompCurve.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Section.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepFeat_SplitShape.hxx>
#include <BRepGProp.hxx>
#include <BRepLib.hxx>
#include <BRepOffset_MakeOffset.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepProj_Projection.hxx>
#include <GProp_GProps.hxx>
#include <Geom2dAPI_Interpolate.hxx>
#include <Geom2dAPI_PointsToBSpline.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <Geom2d_Line.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <ShapeAnalysis_Surface.hxx>
#include <TColgp_Array1OfPnt2d.hxx>
#include <TColgp_HArray1OfPnt2d.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_SequenceOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Dir2d.hxx>
#include <algorithm>

namespace genform::kernel::native {
TopoDS_Shape partition(const TopoDS_Shape &inner, const QJsonObject &params, const Context &context, double thickness) {
    const QJsonObject wallParams{{"sketch", params["walls"]}};
    const auto &walls = sketch(context, wallParams);
    const double wall = number(params, "wall_thickness") != 0 ? number(params, "wall_thickness") : thickness, reach = 2 * modelSize(context.body) + 10;
    if (wall <= 0) fail("Partition thickness must be positive");
    std::vector<TopoDS_Shape> slabs;
    for (TopExp_Explorer explorer(walls.curves, TopAbs_EDGE); explorer.More(); explorer.Next()) {
        BRepAdaptor_Curve curve(TopoDS::Edge(explorer.Current())); if (curve.GetType() != GeomAbs_Line) fail("Partition sketches may contain only straight lines");
        const auto first = curve.Value(curve.FirstParameter()), last = curve.Value(curve.LastParameter()); const gp_Vec chord(first, last);
        if (chord.Magnitude() < 1e-6) continue;
        const auto across = walls.frame.normal.Crossed(chord.Normalized()); const auto start = first.Translated(across * (-wall / 2) - walls.frame.normal * reach);
        BRepBuilderAPI_MakePolygon polygon; polygon.Add(start); polygon.Add(start.Translated(chord)); polygon.Add(start.Translated(chord + across * wall)); polygon.Add(start.Translated(across * wall)); polygon.Close();
        slabs.push_back(BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(polygon.Wire()).Face(), walls.frame.normal * (reach * 2)).Shape());
    }
    if (slabs.empty()) fail("Partition sketch contains no straight lines");
    const auto result = booleanShape(inner, compound(slabs), "cut"); if (!TopExp_Explorer(result, TopAbs_SOLID).More()) fail("Partitions occupy the entire cavity"); return result;
}

TopoDS_Shape modifySurface(const QString &kind, const QJsonObject &params, Context &context) {
    const auto &location = sketch(context, params, kind == "wrap"); const double reach = 2 * modelSize(context.body) + 10;
    if (kind == "rib") {
        const auto spine = path(context, params["sketch"].toString()); BRepAdaptor_CompCurve curve(spine);
        const auto first = curve.Value(curve.FirstParameter()), last = curve.Value(curve.LastParameter()), middle = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2);
        const gp_Vec chord(first, last); if (chord.Magnitude() < 1e-9) fail("Rib requires an open sketch path");
        auto toward = location.frame.normal.Crossed(chord.Normalized()); GProp_GProps props; BRepGProp::VolumeProperties(context.body, props);
        if (gp_Vec(middle, props.CentreOfMass()).Dot(toward) < 0) toward.Reverse();
        if (params["flip"].toBool()) toward.Reverse();
        const double thickness = number(params, "thickness", 0, true);
        const auto sheet = BRepPrimAPI_MakePrism(translated(spine, location.frame.normal * (-thickness / 2)), toward * reach).Shape();
        const auto slab = BRepPrimAPI_MakePrism(sheet, location.frame.normal * thickness).Shape(), pieces = booleanShape(slab, context.body, "cut");
        const auto probe = middle.Translated(toward * 1e-4); TopoDS_Shape selected;
        for (TopExp_Explorer explorer(pieces, TopAbs_SOLID); explorer.More(); explorer.Next()) if (BRepClass3d_SolidClassifier(explorer.Current(), probe, 1e-5).State() == TopAbs_IN) { selected = explorer.Current(); break; }
        if (selected.IsNull()) fail("Rib sketch is inside the body");
        const auto box = bounds(selected); const auto low = point(box[0]), high = point(box[1]); double span = 0;
        for (double x : {low.X(), high.X()}) for (double y : {low.Y(), high.Y()}) for (double z : {low.Z(), high.Z()}) span = std::max(span, std::abs(gp_Vec(middle, {x, y, z}).Dot(toward)));
        if (span > reach * .9) fail("Rib does not reach the body in this direction");
        return combine(context.body, selected, "add");
    }
    if (kind == "split") {
        TopTools_SequenceOfShape traces;
        for (TopExp_Explorer explorer(location.curves, TopAbs_EDGE); explorer.More(); explorer.Next()) {
            const auto blade = BRepPrimAPI_MakePrism(translated(explorer.Current(), location.frame.normal * -reach), location.frame.normal * (reach * 2)).Shape();
            BRepAlgoAPI_Section section(context.body, blade); section.Build(); if (!section.IsDone()) fail("Split section failed");
            for (TopExp_Explorer edges(section.Shape(), TopAbs_EDGE); edges.More(); edges.Next()) traces.Append(edges.Current());
        }
        BRepFeat_SplitShape maker(context.body); if (traces.IsEmpty() || !maker.Add(traces)) fail("Sketch does not split any body face"); maker.Build(); if (!maker.IsDone()) fail("Face split failed");
        TopTools_IndexedMapOfShape before, after; TopExp::MapShapes(context.body, TopAbs_FACE, before); TopExp::MapShapes(maker.Shape(), TopAbs_FACE, after);
        if (before.Extent() == after.Extent()) fail("Sketch did not split any body face");
        return maker.Shape();
    }
    if (kind == "wrap") {
        const auto faces = selectFaces(context.body, params["faces"].toArray()); if (faces.size() != 1) fail("Wrap requires one cylindrical face");
        const auto face = faces.front(); BRepAdaptor_Surface adaptor(face); if (adaptor.GetType() != GeomAbs_Cylinder) fail("Wrap requires a cylindrical face");
        const auto surface = BRep_Tool::Surface(face); const auto cylinder = adaptor.Cylinder(); const gp_Vec along(cylinder.Axis().Direction());
        ShapeAnalysis_Surface analysis(surface); const auto start = analysis.ValueOfUV(location.frame.origin, tolerance);
        const auto around = along.Crossed(gp_Vec(cylinder.Location(), surface->Value(start.X(), start.Y()))).Normalized();
        auto project = [&](const gp_Pnt &spot) {
            const gp_Vec local(location.frame.origin, spot); const double x = local.Dot(location.frame.x), y = local.Dot(location.frame.y);
            return gp_Pnt2d(start.X() + (location.frame.x.Dot(around) * x + location.frame.y.Dot(around) * y) / cylinder.Radius(), start.Y() + location.frame.x.Dot(along) * x + location.frame.y.Dot(along) * y);
        };
        auto body = context.body; const double depth = number(params, "depth", 0, true); const bool emboss = params.value("mode").toString("emboss") == "emboss";
        if (location.wires.empty()) fail("Wrap requires closed sketch contours");
        TopTools_IndexedMapOfShape allWires; TopExp::MapShapes(location.profile, TopAbs_WIRE, allWires);
        if (allWires.Extent() != static_cast<int>(location.wires.size())) fail("Native wrap with nested holes/islands is not yet supported");
        for (const auto &wire : location.wires) {
            BRepBuilderAPI_MakeWire builder;
            for (TopExp_Explorer explorer(wire, TopAbs_EDGE); explorer.More(); explorer.Next()) {
                BRepAdaptor_Curve curve(TopoDS::Edge(explorer.Current())); Handle(Geom2d_Curve) projected;
                const double first = curve.FirstParameter(), last = curve.LastParameter();
                if (curve.GetType() == GeomAbs_Line) {
                    const auto a = project(curve.Value(first)), b = project(curve.Value(last)); projected = new Geom2d_TrimmedCurve(new Geom2d_Line(a, gp_Dir2d(b.X() - a.X(), b.Y() - a.Y())), 0, a.Distance(b));
                } else { TColgp_Array1OfPnt2d points(1, 49); for (int index = 0; index <= 48; ++index) points.SetValue(index + 1, project(curve.Value(first + (last - first) * index / 48))); projected = Geom2dAPI_PointsToBSpline(points).Curve(); }
                auto edge = BRepBuilderAPI_MakeEdge(projected, surface).Edge(); BRepLib::BuildCurves3d(edge); if (explorer.Current().Orientation() == TopAbs_REVERSED) edge.Reverse(); builder.Add(edge);
            }
            if (!builder.IsDone()) fail("Wrapped contour is disconnected");
            BRepBuilderAPI_MakeFace patch(surface, builder.Wire(), true); if (!patch.IsDone()) fail("Wrapped contour cannot form a face");
            BRepOffset_MakeOffset maker; maker.Initialize(patch.Face(), depth * (face.Orientation() == TopAbs_REVERSED ? -1 : 1) * (emboss ? 1 : -1), 1e-4, BRepOffset_Skin, false, false, GeomAbs_Arc, true); maker.MakeOffsetShape();
            if (!maker.IsDone()) fail("Wrapped contour cannot form thickness");
            body = combine(body, maker.Shape(), emboss ? "add" : "cut");
        }
        return body;
    }
    fail("Unknown surface modifier: " + kind); return {};
}

TopoDS_Wire surfaceCurve(const QString &kind, const QJsonObject &params, Context &context) {
    if (empty(context.body)) fail("Surface curves require a body");
    if (kind == "curve_project") {
        const auto &location = sketch(context, params); BRepProj_Projection projection(path(context, params["sketch"].toString()), context.body, gp_Dir(location.frame.normal));
        if (!projection.IsDone()) fail("Sketch projection failed");
        TopExp_Explorer explorer(projection.Shape(), TopAbs_WIRE); if (!explorer.More()) fail("Sketch misses the body");
        context.display[context.current] = projection.Shape(); return TopoDS::Wire(explorer.Current());
    }
    const auto faces = selectFaces(context.body, params["faces"].toArray()); if (faces.size() != 1) fail("Surface curve requires one face");
    const auto face = faces.front(); BRepAdaptor_Surface adaptor(face); const auto rows = params["points"].toArray(); if (rows.size() < 2) fail("Surface curve requires two UV points");
    Handle(TColgp_HArray1OfPnt2d) points = new TColgp_HArray1OfPnt2d(1, static_cast<int>(rows.size()));
    for (qsizetype index = 0; index < rows.size(); ++index) {
        const auto row = rows[index].toArray(); if (row.size() != 2 || !row[0].isDouble() || !row[1].isDouble() || row[0].toDouble() < 0 || row[0].toDouble() > 1 || row[1].toDouble() < 0 || row[1].toDouble() > 1) fail("Surface UV coordinates must be between 0 and 1");
        points->SetValue(static_cast<int>(index) + 1, {adaptor.FirstUParameter() + (adaptor.LastUParameter() - adaptor.FirstUParameter()) * row[0].toDouble(), adaptor.FirstVParameter() + (adaptor.LastVParameter() - adaptor.FirstVParameter()) * row[1].toDouble()});
    }
    Handle(Geom2d_Curve) curve;
    if (rows.size() == 2) { const auto a = points->Value(1), b = points->Value(2); if (a.Distance(b) < 1e-12) fail("Surface curve points coincide"); curve = new Geom2d_TrimmedCurve(new Geom2d_Line(a, gp_Dir2d(b.X() - a.X(), b.Y() - a.Y())), 0, a.Distance(b)); }
    else { Geom2dAPI_Interpolate maker(points, false, 1e-9); maker.Perform(); if (!maker.IsDone()) fail("UV interpolation failed"); curve = maker.Curve(); }
    const auto edge = BRepBuilderAPI_MakeEdge(curve, BRep_Tool::Surface(face)).Edge(); BRepLib::BuildCurves3d(edge); return BRepBuilderAPI_MakeWire(edge).Wire();
}
}
#endif
