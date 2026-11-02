#include "native.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRepAlgoAPI_Section.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepClass3d.hxx>
#include <BRepLib.hxx>
#include <BRepOffsetAPI_MakeOffsetShape.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>

namespace genform::kernel::native {
namespace {
struct Skins { TopoDS_Shell outer; std::vector<TopoDS_Shape> voids; };
TopoDS_Solid solidFrom(const TopoDS_Shell &shell) {
    auto solid = BRepBuilderAPI_MakeSolid(shell).Solid();
    if (!BRepLib::OrientClosedSolid(solid)) fail("Cavity shell is not closed");
    return solid;
}
Skins splitSkins(const TopoDS_Shape &body) {
    if (empty(body)) fail("Hollow operations require an existing body");
    TopoDS_Solid solid; int count = 0;
    for (TopExp_Explorer explorer(body, TopAbs_SOLID); explorer.More(); explorer.Next()) { solid = TopoDS::Solid(explorer.Current()); ++count; }
    if (count != 1) fail("Hollow operations require exactly one solid");
    Skins result{BRepClass3d::OuterShell(solid), {}};
    for (TopExp_Explorer explorer(solid, TopAbs_SHELL); explorer.More(); explorer.Next()) {
        const auto shell = TopoDS::Shell(explorer.Current()); if (shell.IsSame(result.outer)) continue;
        result.voids.push_back(solidFrom(TopoDS::Shell(shell.Reversed())));
    }
    return result;
}
TopoDS_Shape assemble(const TopoDS_Shell &outer, const TopoDS_Shape &voids) {
    BRepBuilderAPI_MakeSolid maker(outer);
    if (!voids.IsNull()) for (TopExp_Explorer explorer(voids, TopAbs_SHELL); explorer.More(); explorer.Next()) maker.Add(TopoDS::Shell(explorer.Current().Reversed()));
    auto result = maker.Solid();
    if (!BRepLib::OrientClosedSolid(result) || !BRepCheck_Analyzer(result).IsValid() || volume(result) <= 1e-9) fail("Cavities do not form a valid hollow body");
    return result;
}
}

TopoDS_Shape hollow(const TopoDS_Shape &body, const TopoDS_Shape &tool, const QString &operation) {
    const auto skins = splitSkins(body);
    if (empty(tool) || !BRepCheck_Analyzer(tool).IsValid() || volume(tool) <= 1e-9) fail("Hollow operation requires a valid solid tool");
    if (operation == "void") {
        const auto outerSolid = solidFrom(skins.outer);
        const auto outside = booleanShape(tool, outerSolid, "cut");
        if (volume(outside) > std::max(1e-6, volume(tool) * 1e-8)) fail("Cavity tool must be entirely inside the outer skin");
        BRepAlgoAPI_Section section(skins.outer, tool); section.Build();
        if (!section.IsDone() || TopExp_Explorer(section.Shape(), TopAbs_EDGE).More()) fail("Cavity tool intersects the outer skin");
        TopoDS_Shape merged = tool;
        for (const auto &old : skins.voids) merged = booleanShape(merged, old, "add");
        return assemble(skins.outer, merged);
    }
    if (operation == "fill") {
        if (skins.voids.empty()) fail("Body has no closed cavities to fill");
        const auto voids = compound(skins.voids); const auto remaining = booleanShape(voids, tool, "cut");
        if (volume(voids) - volume(remaining) < 1e-6 * std::max(volume(voids), 1.0)) fail("Fill tool does not reach a cavity");
        return assemble(skins.outer, remaining);
    }
    if (operation == "pocket" || operation.startsWith("pocket:")) {
        bool ok = true; const double wall = operation == "pocket" ? 2 : operation.mid(7).toDouble(&ok);
        if (!ok || !std::isfinite(wall) || wall <= 0) fail("Pocket wall must be positive");
        auto lined = body;
        if (!skins.voids.empty()) {
            std::vector<TopoDS_Shape> linings;
            for (TopExp_Explorer explorer(tool, TopAbs_SOLID); explorer.More(); explorer.Next()) {
                BRepOffsetAPI_MakeOffsetShape maker; maker.PerformByJoin(explorer.Current(), wall, 1e-3);
                if (!maker.IsDone() || maker.Shape().IsNull()) fail("Pocket lining offset failed");
                linings.push_back(maker.Shape());
            }
            const auto lining = compound(linings), voids = compound(skins.voids);
            const auto remaining = booleanShape(voids, lining, "cut"); lined = assemble(skins.outer, remaining);
        }
        return combine(lined, tool, "cut");
    }
    fail("Unknown hollow operation: " + operation); return {};
}
}
#endif
