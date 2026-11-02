#include "native.hpp"

#ifdef GENFORM_HAS_OCCT
#include <StdPrs_BRepFont.hxx>
#include <TCollection_AsciiString.hxx>
#include <gp_Ax3.hxx>
#include <algorithm>

namespace genform::kernel::native {
std::vector<TopoDS_Shape> makeText(const QJsonObject &shape, const Frame &plane) {
    const double height = number(shape, "height", 10, true); const QString name = shape.value("font").toString("Microsoft YaHei");
    StdPrs_BRepFont font;
    if (!font.FindAndInit(TCollection_AsciiString(name.toUtf8().constData()), Font_FontAspect_Regular, height)) fail("Font not found: " + name);
    const auto text = shape["text"].toString().toUcs4(); std::vector<TopoDS_Shape> glyphs; std::vector<double> advances;
    for (const auto letter : text) { glyphs.push_back(font.RenderGlyph(letter)); advances.push_back(font.AdvanceX(letter)); }
    struct Placement { double x, y, angle; }; std::vector<Placement> placements;
    if (shape["path"].isObject() && !shape["path"].toObject().isEmpty()) {
        const auto pathShape = shape["path"].toObject(); const auto pathSketch = makeSketch({{"shapes", QJsonArray{pathShape}}}, {});
        std::vector<gp_Pnt> line;
        for (const auto &value : segments(pathSketch.curves)) { const auto segment = value.toArray(); if (line.empty()) line.push_back(point(segment[0])); line.push_back(point(segment[1])); }
        if (line.size() < 2) fail("Text baseline has no curve");
        const QString kind = pathShape["type"].toString(); if ((kind == "arc" || kind == "circle") != shape["flip"].toBool()) std::reverse(line.begin(), line.end());
        std::vector<double> marks{0}; for (size_t index = 1; index < line.size(); ++index) marks.push_back(marks.back() + line[index - 1].Distance(line[index]));
        double run = 0; size_t segment = 0;
        for (double advance : advances) {
            const double middle = run + advance / 2; while (segment + 2 < line.size() && marks[segment + 1] < middle) ++segment;
            const auto direction = gp_Vec(line[segment], line[segment + 1]).Normalized(); const auto origin = line[segment].Translated(direction * (middle - marks[segment] - advance / 2));
            placements.push_back({origin.X(), origin.Y(), std::atan2(direction.Y(), direction.X())}); run += advance;
        }
    } else {
        const double angle = number(shape, "angle") * pi / 180, x = number(shape, "x"), y = number(shape, "y"); double run = 0;
        for (double advance : advances) { placements.push_back({x + run * std::cos(angle), y + run * std::sin(angle), angle}); run += advance; }
    }
    gp_Trsf toPlane; toPlane.SetTransformation(gp_Ax3(plane.origin, gp_Dir(plane.normal), gp_Dir(plane.x)), gp_Ax3());
    std::vector<TopoDS_Shape> result;
    for (size_t index = 0; index < glyphs.size(); ++index) {
        if (glyphs[index].IsNull()) continue;
        gp_Trsf turn, shift; turn.SetRotation(gp_Ax1({0, 0, 0}, {0, 0, 1}), placements[index].angle); shift.SetTranslation(gp_Vec(placements[index].x, placements[index].y, 0));
        result.push_back(moved(glyphs[index], toPlane.Multiplied(shift).Multiplied(turn)));
    }
    return result;
}
}
#endif
