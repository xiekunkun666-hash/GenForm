#include "native.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <gp_Ax2.hxx>
#include <algorithm>

namespace genform::kernel::native {
TopoDS_Shape tipTrimmer(const gp_Pnt &spot, const gp_Vec &along, double diameter, double length, double bevel) {
    const auto beyond = BRepPrimAPI_MakeCylinder(gp_Ax2(spot.Translated(along * length), gp_Dir(along)), diameter, diameter * 3).Shape();
    if (bevel <= 0) return beyond;
    const auto axis = gp_Ax2(spot.Translated(along * (length - bevel)), gp_Dir(along));
    const auto ring = BRepPrimAPI_MakeCylinder(axis, diameter, bevel).Shape(), cone = BRepPrimAPI_MakeCone(axis, diameter / 2, diameter / 2 - bevel, bevel).Shape();
    return booleanShape(beyond, booleanShape(ring, cone, "cut"), "add");
}
TopoDS_Shape screw(const QJsonObject &params, Context &context) {
    const auto &location = sketch(context, params); const QString size = params.value("size").toString("M3"), head = params.value("head").toString("cap");
    const QMap<QString, std::vector<std::vector<double>>> sizes{
        {"M2", {{3.8,2,1.5,1}, {3.5,1.1,1.3,.7}, {4,1,1.3,.6}}}, {"M2.5", {{4.5,2.5,2,1.1}, {4.7,1.35,1.5,.9}, {5,1.25,1.5,.8}}},
        {"M3", {{5.5,3,2.5,1.3}, {5.7,1.65,2,1.04}, {6.72,1.86,2,1.1}}}, {"M4", {{7,4,3,2}, {7.6,2.2,2.5,1.3}, {8.96,2.48,2.5,1.5}}},
        {"M5", {{8.5,5,4,2.5}, {9.5,2.75,3,1.56}, {11.2,3.1,3,1.9}}}, {"M6", {{10,6,5,3}, {10.5,3.3,4,2.08}, {13.44,3.72,4,2.2}}},
        {"M8", {{13,8,6,4}, {14,4.4,5,2.6}, {17.92,4.96,5,3}}}};
    const int headIndex = head == "cap" ? 0 : head == "button" ? 1 : head == "flat" ? 2 : -1;
    if (!sizes.contains(size) || headIndex < 0) fail("Unknown screw size/head");
    const auto dimensions = sizes[size][headIndex]; const double diameter = size.mid(1).toDouble(), length = number(params, "length", 0, true), tip = std::min(.15 * diameter, length * .2);
    const double headDiameter = dimensions[0], headHeight = dimensions[1], socket = dimensions[2], socketDepth = dimensions[3];
    const gp_Vec into = location.frame.normal * (params["flip"].toBool() ? 1 : -1);
    double top = headHeight, shankFrom = 0, shank = length;
    if (head == "flat") { const double cone = (headDiameter - diameter) / 2; if (length <= cone + tip) fail("Countersunk screw is too short"); top = 0; shankFrom = cone; shank -= cone; }
    std::vector<TopoDS_Shape> screws;
    for (const auto &spot : spots(location)) {
        const bool threaded = params["thread"].toBool(); const double pitch = coarsePitch(diameter);
        const auto shankStart = spot.Translated(into * shankFrom); const double shankLength = threaded ? shank + 3 * pitch : shank - tip;
        auto solid = BRepPrimAPI_MakeCylinder(gp_Ax2(shankStart, gp_Dir(into)), diameter / 2, shankLength).Shape();
        if (!threaded) solid = booleanShape(solid, BRepPrimAPI_MakeCone(gp_Ax2(shankStart.Translated(into * (shank - tip)), gp_Dir(into)), diameter / 2, diameter / 2 - tip, tip).Shape(), "add");
        const gp_Ax2 headAxis(spot, gp_Dir(head == "flat" ? into : -into)); TopoDS_Shape cap;
        if (head == "flat") cap = BRepPrimAPI_MakeCone(headAxis, headDiameter / 2, diameter / 2, shankFrom).Shape();
        else {
            const double low = head == "cap" ? headHeight : headHeight * .45; cap = BRepPrimAPI_MakeCylinder(headAxis, headDiameter / 2, low).Shape();
            if (head == "button") cap = booleanShape(cap, BRepPrimAPI_MakeCone(gp_Ax2(spot.Translated(into * -low), gp_Dir(-into)), headDiameter / 2, headDiameter * .31, headHeight - low).Shape(), "add");
        }
        solid = booleanShape(solid, cap, "add");
        if (threaded) { solid = combine(solid, threadGroove(spot, into, diameter, pitch, shankFrom + .25 * pitch, length + pitch, false, number(params, "phase")), "cut"); solid = combine(solid, tipTrimmer(spot, into, diameter, length, tip), "cut"); }
        BRepBuilderAPI_MakePolygon polygon; const auto center = spot.Translated(into * -top); const double radius = socket / std::sqrt(3.0);
        for (int corner = 0; corner < 6; ++corner) { const double angle = pi * corner / 3; polygon.Add(center.Translated((location.frame.x * std::cos(angle) + location.frame.y * std::sin(angle)) * radius - into * .01)); }
        polygon.Close(); const auto recess = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(polygon.Wire()).Face(), into * (socketDepth + .01)).Shape(); screws.push_back(combine(solid, recess, "cut"));
    }
    return compound(screws);
}
}
#endif
