#include "detail.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRepAdaptor_Curve.hxx>
#include <BRepLib.hxx>
#include <HLRAlgo_Projector.hxx>
#include <HLRBRep_Algo.hxx>
#include <HLRBRep_HLRToShape.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <gp_Ax2.hxx>
#include <algorithm>
#include <limits>

namespace genform::assembly::detail {
namespace {
QJsonArray polylines(const TopoDS_Shape &shape, QJsonArray *circles = nullptr) {
    QJsonArray result;
    if (shape.IsNull()) return result;
    BRepLib::BuildCurves3d(shape);
    for (TopExp_Explorer explorer(shape, TopAbs_EDGE); explorer.More(); explorer.Next()) {
        BRepAdaptor_Curve curve(TopoDS::Edge(explorer.Current()));
        const double first = curve.FirstParameter(), last = curve.LastParameter();
        if (!std::isfinite(first) || !std::isfinite(last) || last - first < 1e-12) continue;
        if (curve.GetType() == GeomAbs_Circle && circles) {
            const auto circle = curve.Circle();
            circles->append(QJsonArray{circle.Location().X(), circle.Location().Y(), circle.Radius(), last - first >= 2 * std::acos(-1.0) - 1e-6});
        }
        const int count = curve.GetType() == GeomAbs_Line ? 1 : 48;
        QJsonArray line;
        for (int index = 0; index <= count; ++index) {
            const auto position = curve.Value(first + (last - first) * index / count);
            line.append(QJsonArray{position.X(), position.Y()});
        }
        result.append(line);
    }
    return result;
}

void append(QJsonArray &target, const QJsonArray &source) { for (const auto &entry : source) target.append(entry); }
}

QJsonObject drawing(const Part &part, const QJsonObject &args) {
    requireExact({part});
    const double diagonal = std::sqrt(0.5), sixth = 1 / std::sqrt(6.0);
    const QMap<QString, std::pair<gp_Vec, gp_Vec>> frames{
        {"front", {{1, 0, 0}, {0, 0, 1}}}, {"top", {{1, 0, 0}, {0, 1, 0}}},
        {"left", {{0, -1, 0}, {0, 0, 1}}}, {"iso", {{diagonal, diagonal, 0}, {-sixth, sixth, 2 * sixth}}}};
    QJsonArray requested = args["views"].toArray();
    if (requested.isEmpty()) requested = QJsonArray{"front", "top", "left"};
    QJsonObject views;
    for (const auto &entry : requested) {
        const QString name = entry.toString();
        if (!frames.contains(name)) fail("Unknown drawing view: " + name);
        const auto &[horizontal, vertical] = frames[name];
        Handle(HLRBRep_Algo) algorithm = new HLRBRep_Algo;
        algorithm->Add(part.shape);
        algorithm->Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(horizontal.Crossed(vertical)), gp_Dir(horizontal))));
        algorithm->Update();
        algorithm->Hide();
        HLRBRep_HLRToShape output(algorithm);
        QJsonArray circles, hidden;
        auto visible = polylines(output.VCompound(), &circles);
        append(visible, polylines(output.OutLineVCompound()));
        if (args.value("hidden").toBool(true) && name != "iso") {
            hidden = polylines(output.HCompound());
            append(hidden, polylines(output.OutLineHCompound()));
        }
        if (visible.isEmpty()) fail("Drawing projection produced no visible lines");
        double lowX = std::numeric_limits<double>::infinity(), lowY = lowX, highX = -lowX, highY = -lowX;
        for (const auto &line : visible) for (const auto &point : line.toArray()) {
            const auto position = point.toArray();
            lowX = std::min(lowX, position[0].toDouble()); highX = std::max(highX, position[0].toDouble());
            lowY = std::min(lowY, position[1].toDouble()); highY = std::max(highY, position[1].toDouble());
        }
        views[name] = QJsonObject{{"visible", visible}, {"hidden", hidden}, {"circles", circles}, {"box", QJsonArray{lowX, lowY, highX, highY}}};
    }
    int faces = 0;
    for (TopExp_Explorer explorer(part.shape, TopAbs_FACE); explorer.More(); explorer.Next()) ++faces;
    Vector size{};
    for (int axis = 0; axis < 3; ++axis) size[axis] = part.high[axis] - part.low[axis];
    return {{"size", json(size)}, {"exact", true}, {"faces", faces}, {"views", views}};
}

QJsonObject drag(const std::vector<Part> &parts, const QJsonObject &args) {
    if (parts.empty()) fail("Drag estimate requires geometry");
    const double speed = number(args, "speed", 0, true), rho = number(args, "density", 1.225, true), coefficient = number(args, "cd", 1, true);
    const auto direction = coordinates(args["direction"], {0, 1, 0});
    gp_Vec front(direction[0], direction[1], direction[2]);
    if (front.Magnitude() < 1e-12) fail("Wind direction cannot be zero");
    front.Normalize();
    const gp_Vec helper = std::abs(front.Z()) < 0.9 ? gp_Vec(0, 0, 1) : gp_Vec(1, 0, 0);
    const gp_Vec right = helper.Crossed(front).Normalized(), up = front.Crossed(right);
    struct Triangle { std::array<std::array<double, 2>, 3> points; };
    std::vector<Triangle> triangles;
    double lowX = std::numeric_limits<double>::infinity(), lowY = lowX, highX = -lowX, highY = -lowX;
    for (const auto &part : parts) {
        const auto display = mesh(part);
        const auto vertices = display["verts"].toArray();
        for (const auto &entry : display["tris"].toArray()) {
            const auto indices = entry.toArray();
            Triangle triangle;
            for (int corner = 0; corner < 3; ++corner) {
                const auto position = coordinates(vertices[indices[corner].toInt()]);
                const gp_Vec vector(position[0], position[1], position[2]);
                const double horizontal = vector.Dot(right), vertical = vector.Dot(up);
                triangle.points[corner] = {horizontal, vertical};
                lowX = std::min(lowX, horizontal); highX = std::max(highX, horizontal);
                lowY = std::min(lowY, vertical); highY = std::max(highY, vertical);
            }
            triangles.push_back(triangle);
        }
    }
    if (triangles.empty()) fail("No triangles available for drag estimate");
    const int resolution = args.value("resolution").toInt(320);
    if (resolution < 16 || resolution > 2048) fail("Drag raster resolution must be between 16 and 2048");
    const double step = std::max({highX - lowX, highY - lowY, 1e-6}) / resolution;
    const int width = std::max(1, static_cast<int>(std::ceil((highX - lowX) / step))), height = std::max(1, static_cast<int>(std::ceil((highY - lowY) / step)));
    std::vector<bool> covered(static_cast<size_t>(width) * height);
    for (const auto &triangle : triangles) {
        const auto &first = triangle.points[0], &second = triangle.points[1], &third = triangle.points[2];
        const double determinant = (second[1] - third[1]) * (first[0] - third[0]) + (third[0] - second[0]) * (first[1] - third[1]);
        if (std::abs(determinant) < 1e-16) continue;
        const int fromX = std::clamp(static_cast<int>(std::floor((std::min({first[0], second[0], third[0]}) - lowX) / step)), 0, width - 1);
        const int toX = std::clamp(static_cast<int>(std::floor((std::max({first[0], second[0], third[0]}) - lowX) / step)), 0, width - 1);
        const int fromY = std::clamp(static_cast<int>(std::floor((std::min({first[1], second[1], third[1]}) - lowY) / step)), 0, height - 1);
        const int toY = std::clamp(static_cast<int>(std::floor((std::max({first[1], second[1], third[1]}) - lowY) / step)), 0, height - 1);
        for (int horizontal = fromX; horizontal <= toX; ++horizontal)
            for (int vertical = fromY; vertical <= toY; ++vertical) {
                const double pointX = lowX + (horizontal + 0.5) * step, pointY = lowY + (vertical + 0.5) * step;
                const double firstWeight = ((second[1] - third[1]) * (pointX - third[0]) + (third[0] - second[0]) * (pointY - third[1])) / determinant;
                const double secondWeight = ((third[1] - first[1]) * (pointX - third[0]) + (first[0] - third[0]) * (pointY - third[1])) / determinant;
                if (firstWeight >= -1e-9 && secondWeight >= -1e-9 && firstWeight + secondWeight <= 1 + 1e-9) covered[static_cast<size_t>(horizontal) * height + vertical] = true;
            }
    }
    const double area = static_cast<double>(std::count(covered.begin(), covered.end(), true)) * step * step;
    const double pressure = 0.5 * rho * speed * speed, force = pressure * coefficient * area * 1e-6;
    return {{"area", area}, {"force", force}, {"pressure", pressure}, {"power", force * speed},
            {"exact", false}, {"approximate", true}, {"method", "triangle-union projected raster and empirical drag coefficient"},
            {"resolution", resolution}, {"pixel_size_mm", step}, {"certified", false}};
}
}
#endif
