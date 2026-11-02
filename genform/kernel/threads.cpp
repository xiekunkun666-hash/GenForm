#include "native.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <algorithm>

namespace genform::kernel::native {
double coarsePitch(double diameter) {
    const std::vector<std::pair<double, double>> pitches{{2, .4}, {2.5, .45}, {3, .5}, {4, .7}, {5, .8}, {6, 1}, {8, 1.25}, {10, 1.5}, {12, 1.75}};
    for (const auto &[major, pitch] : pitches) if (std::abs(major - diameter) < 1e-6) return pitch;
    return std::round(.15 * diameter * 100) / 100;
}
TopoDS_Shape threadGroove(const gp_Pnt &spot, const gp_Vec &direction, double major, double pitch, double start, double stop, bool internal, double phase) {
    if (!std::isfinite(major) || !std::isfinite(pitch) || !std::isfinite(start) || !std::isfinite(stop) || !std::isfinite(phase) || major <= 0 || pitch <= 0 || stop <= start) fail("Invalid thread dimensions");
    if ((stop - start) / pitch > 500) fail("Thread exceeds 500 turns");
    const auto along = direction.Normalized();
    const double height = .866025 * pitch, crest = major / 2 + height / 8, root = major / 2 - 7 * height / 8, widen = .02 * height / pitch;
    const double tip = internal ? crest + widen : root - widen, base = internal ? (major - 1.082532 * pitch) / 2 - .02 : major / 2 + .02;
    const double half = (pitch * (internal ? crest - base : base - root) / height + .02) / 2;
    if (std::min(tip, base) <= 0 || half >= pitch / 2) fail("Thread pitch is too large for diameter");
    const gp_Vec helper = std::abs(along.X()) < .9 ? gp_Vec(1, 0, 0) : gp_Vec(0, 1, 0);
    const auto side = (helper - along * helper.Dot(along)).Normalized(), cross = along.Crossed(side);
    const double shift = pitch * (phase / 360 - std::floor(phase / 360)) + (internal ? pitch / 2 : 0), middle = (tip + base) / 2;
    std::vector<TopoDS_Shape> cuts;
    for (double first = start; first < stop - 1e-12;) {
        const double last = stop - first > 4.5 * pitch ? first + 3 * pitch : stop, turns = (last - first) / pitch, angle = 2 * pi * (first - shift) / pitch;
        const int count = std::max(4, static_cast<int>(std::ceil(turns * 36)));
        std::vector<gp_Pnt> points;
        for (int index = 0; index <= count; ++index) {
            const double turn = turns * index / count, theta = angle + 2 * pi * turn;
            points.push_back(spot.Translated(along * (first + pitch * turn) + (side * std::cos(theta) + cross * std::sin(theta)) * middle));
        }
        const auto at = spot.Translated(along * first); const auto out = side * std::cos(angle) + cross * std::sin(angle);
        BRepBuilderAPI_MakePolygon polygon; polygon.Add(at.Translated(out * base - along * half)); polygon.Add(at.Translated(out * base + along * half)); polygon.Add(at.Translated(out * tip)); polygon.Close();
        BRepOffsetAPI_MakePipeShell maker(spline(points)); maker.SetMode(gp_Dir(along)); maker.Add(polygon.Wire()); maker.Build();
        if (!maker.IsDone() || !maker.MakeSolid()) fail("Native thread sweep failed");
        cuts.push_back(maker.Shape()); first = last;
    }
    return cuts.size() == 1 ? cuts.front() : compound(cuts);
}
}
#endif
