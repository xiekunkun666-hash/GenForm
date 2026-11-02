#include "native.hpp"

#ifdef GENFORM_HAS_OCCT
#include <QStringList>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Section.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Pln.hxx>
#include <algorithm>
#include <array>
#include <numeric>
#include <utility>

namespace genform::kernel::native {
namespace {
TopTools_IndexedMapOfShape parts(const TopoDS_Shape &shape, TopAbs_ShapeEnum kind) {
    TopTools_IndexedMapOfShape result;
    if (!shape.IsNull()) TopExp::MapShapes(shape, kind, result);
    return result;
}

QJsonObject metrics(const TopoDS_Shape &shape) {
    const auto props = properties(shape); QJsonObject faces;
    const auto shapeFaces = parts(shape, TopAbs_FACE);
    for (int index = 1; index <= std::min(shapeFaces.Extent(), 400); ++index) {
        const auto kind = BRepAdaptor_Surface(TopoDS::Face(shapeFaces(index)), false).GetType(); QString name;
        switch (kind) {
        case GeomAbs_Plane: name = "plane"; break;
        case GeomAbs_Cylinder: name = "cylinder"; break;
        case GeomAbs_Cone: name = "cone"; break;
        case GeomAbs_Sphere: name = "sphere"; break;
        case GeomAbs_Torus: name = "torus"; break;
        case GeomAbs_BSplineSurface: case GeomAbs_BezierSurface: name = "freeform"; break;
        default: name = "other";
        }
        faces[name] = faces[name].toInt() + 1;
    }
    auto sizes = props["size"].toArray(); std::vector<double> values; for (const auto &size : sizes) values.push_back(size.toDouble()); std::sort(values.begin(), values.end()); sizes = {}; for (double value : values) sizes.append(value);
    const double volume = props["volume"].toDouble(), area = props["area"].toDouble();
    return {{"box", QJsonArray{props["bbox_min"], props["bbox_max"]}}, {"size", sizes}, {"volume", volume}, {"area", area}, {"thickness", area > 1e-12 ? 2 * volume / area : 0}, {"faces", faces}, {"solids", props["bodies"]}};
}

QJsonObject proof(const TopoDS_Shape &body) {
    const auto box = bounds(body);
    const auto low = box[0].toArray(), high = box[1].toArray();
    std::array<double, 3> size;
    for (int coordinate = 0; coordinate < 3; ++coordinate) size[coordinate] = high[coordinate].toDouble() - low[coordinate].toDouble();
    const int axis = static_cast<int>(std::min_element(size.begin(), size.end()) - size.begin());
    std::array<int, 2> others;
    int next = 0;
    for (int coordinate = 0; coordinate < 3; ++coordinate) if (coordinate != axis) others[next++] = coordinate;
    QJsonObject result{{"box", box}, {"axis", axis}, {"extent", QJsonArray{size[others[0]], size[others[1]]}}};
    const double inset = std::min(0.05, size[axis] / 4);
    for (const auto &level : {std::make_pair(QString("top"), high[axis].toDouble() - inset),
                              std::make_pair(QString("bottom"), low[axis].toDouble() + inset)}) {
        result[level.first] = QJsonValue(QJsonValue::Null);
        std::array<double, 3> location{}, normal{};
        location[axis] = level.second;
        normal[axis] = 1;
        try {
            BRepAlgoAPI_Section section(body, gp_Pln(gp_Pnt(location[0], location[1], location[2]), gp_Dir(normal[0], normal[1], normal[2])));
            section.Build();
            if (!section.IsDone()) continue;
            const auto shape = section.Shape();
            if (shape.IsNull() || parts(shape, TopAbs_EDGE).IsEmpty()) continue;
            const auto sectionBox = bounds(shape);
            const auto sectionLow = sectionBox[0].toArray(), sectionHigh = sectionBox[1].toArray();
            result[level.first] = QJsonArray{sectionHigh[others[0]].toDouble() - sectionLow[others[0]].toDouble(),
                                             sectionHigh[others[1]].toDouble() - sectionLow[others[1]].toDouble()};
        } catch (const Standard_Failure &) {
        } catch (const std::exception &) {
        }
    }
    return result;
}

struct Piece {
    QString feature;
    TopoDS_Shape shape;
    std::array<double, 3> low, high;
};

std::vector<Piece> pieces(const Context &context) {
    std::vector<Piece> result;
    QStringList identifiers;
    for (const auto &value : context.features) {
        const auto identifier = value.toObject()["id"].toString();
        if (context.tools.contains(identifier) && !identifiers.contains(identifier)) identifiers.append(identifier);
    }
    for (auto entry = context.tools.cbegin(); entry != context.tools.cend(); ++entry) if (!identifiers.contains(entry.key())) identifiers.append(entry.key());
    for (const auto &identifier : identifiers) {
        const auto entry = context.tools.constFind(identifier);
        for (std::size_t copy = 0; copy < std::min<std::size_t>(entry.value().size(), 64); ++copy) {
            const auto &tool = entry.value()[copy];
            if (tool.operation != "add" || tool.shape.IsNull()) continue;
            const auto solids = parts(tool.shape, TopAbs_SOLID);
            for (int index = 1; index <= solids.Extent(); ++index) {
                const auto box = bounds(solids(index));
                const auto low = box[0].toArray(), high = box[1].toArray();
                Piece item{identifier, solids(index), {}, {}};
                double largest = 0;
                for (int coordinate = 0; coordinate < 3; ++coordinate) {
                    item.low[coordinate] = low[coordinate].toDouble();
                    item.high[coordinate] = high[coordinate].toDouble();
                    largest = std::max(largest, item.high[coordinate] - item.low[coordinate]);
                }
                if (largest <= 2500) result.push_back(item);
            }
        }
    }
    return result;
}

bool boxesNear(const Piece &first, const Piece &second, double margin) {
    for (int coordinate = 0; coordinate < 3; ++coordinate) {
        if (first.low[coordinate] - margin > second.high[coordinate] || second.low[coordinate] - margin > first.high[coordinate]) return false;
    }
    return true;
}

class Connections {
public:
    explicit Connections(std::size_t count) : parents(count) { std::iota(parents.begin(), parents.end(), std::size_t{0}); }
    std::size_t root(std::size_t index) {
        while (parents[index] != index) {
            parents[index] = parents[parents[index]];
            index = parents[index];
        }
        return index;
    }
    void join(std::size_t first, std::size_t second) { parents[root(first)] = root(second); }
private:
    std::vector<std::size_t> parents;
};

std::pair<QJsonArray, int> pairs(const Context &context, const QJsonObject &rules) {
    const double clearance = number(rules, "clearance", 0.5), overlap = number(rules, "overlap", 0.3);
    const double machiningTolerance = number(rules, "tolerance", 0.1);
    const double gapLimit = std::max(clearance, machiningTolerance * 2), depthLimit = std::max(overlap, machiningTolerance * 2);
    const double requestedLimit = number(rules, "pair_limit", 600);
    if (requestedLimit < 0 || requestedLimit > 2147483647.0) fail("Inspect pair_limit must be a non-negative integer within the native range");
    const int limit = static_cast<int>(requestedLimit);
    if (!limit) return {QJsonArray{}, 0};
    const auto items = pieces(context);
    std::vector<std::pair<std::size_t, std::size_t>> candidates;
    for (std::size_t first = 0; first < items.size() && candidates.size() < static_cast<std::size_t>(limit); ++first) {
        for (std::size_t second = first + 1; second < items.size() && candidates.size() < static_cast<std::size_t>(limit); ++second) {
            if (items[first].feature != items[second].feature && boxesNear(items[first], items[second], gapLimit)) candidates.push_back({first, second});
        }
    }
    struct Finding { std::size_t first, second; QJsonObject item; };
    std::vector<Finding> findings;
    Connections connected(items.size());
    for (const auto &candidate : candidates) {
        const auto &first = items[candidate.first], &second = items[candidate.second];
        try {
            BRepExtrema_DistShapeShape distance(first.shape, second.shape);
            if (!distance.IsDone() || distance.NbSolution() < 1) continue;
            const double gap = distance.Value();
            if (gap > gapLimit) continue;
            const auto firstPoint = distance.PointOnShape1(1), secondPoint = distance.PointOnShape2(1);
            QJsonObject item{{"point", QJsonArray{(firstPoint.X() + secondPoint.X()) / 2, (firstPoint.Y() + secondPoint.Y()) / 2, (firstPoint.Z() + secondPoint.Z()) / 2}}};
            if (gap > 1e-6) {
                item["kind"] = "gap";
                item["value"] = gap;
            } else {
                BRepAlgoAPI_Common common(first.shape, second.shape);
                common.Build();
                const auto shape = common.IsDone() ? common.Shape() : TopoDS_Shape{};
                if (shape.IsNull() || parts(shape, TopAbs_SOLID).IsEmpty()) {
                    item["kind"] = "touch";
                    item["value"] = 0.0;
                } else {
                    const auto box = bounds(shape);
                    const auto low = box[0].toArray(), high = box[1].toArray();
                    std::array<double, 3> size, center;
                    for (int coordinate = 0; coordinate < 3; ++coordinate) {
                        size[coordinate] = high[coordinate].toDouble() - low[coordinate].toDouble();
                        center[coordinate] = (high[coordinate].toDouble() + low[coordinate].toDouble()) / 2;
                    }
                    const double depth = *std::min_element(size.begin(), size.end());
                    if (depth >= depthLimit) {
                        connected.join(candidate.first, candidate.second);
                        continue;
                    }
                    item["kind"] = "shallow";
                    item["value"] = depth;
                    item["point"] = QJsonArray{center[0], center[1], center[2]};
                }
            }
            item["a"] = std::min(first.feature, second.feature);
            item["b"] = std::max(first.feature, second.feature);
            findings.push_back({candidate.first, candidate.second, item});
        } catch (const Standard_Failure &) {
        } catch (const std::exception &) {
        }
    }
    QMap<std::pair<QString, QString>, std::size_t> positions;
    std::vector<QJsonObject> worst;
    for (const auto &finding : findings) {
        if (finding.item["kind"].toString() == "gap" && connected.root(finding.first) == connected.root(finding.second)) continue;
        const auto key = std::make_pair(finding.item["a"].toString(), finding.item["b"].toString());
        const auto position = positions.constFind(key);
        if (position == positions.cend()) {
            positions.insert(key, worst.size());
            worst.push_back(finding.item);
        } else if (finding.item["value"].toDouble() < worst[position.value()]["value"].toDouble()) {
            worst[position.value()] = finding.item;
        }
    }
    std::stable_sort(worst.begin(), worst.end(), [](const auto &first, const auto &second) { return first["value"].toDouble() < second["value"].toDouble(); });
    QJsonArray result;
    for (const auto &item : worst) result.append(item);
    return {result, static_cast<int>(candidates.size())};
}
}
QJsonObject inspect(const Context &context, const QJsonObject &args) {
    QJsonObject tools;
    for (auto entry = context.tools.cbegin(); entry != context.tools.cend(); ++entry) {
        if (entry.value().empty() || entry.value().front().shape.IsNull()) continue;
        try {
            auto info = metrics(entry.value().front().shape); info["copies"] = static_cast<int>(entry.value().size()); info["op"] = entry.value().front().operation; tools[entry.key()] = info;
        } catch (const Standard_Failure &) {
        } catch (const std::exception &) {
        }
    }
    QJsonObject report{{"tools", tools}, {"bodies", QJsonArray{}}, {"valid", true}, {"has_body", !empty(context.body)}, {"status", context.status}};
    if (empty(context.body)) return report;
    report["valid"] = BRepCheck_Analyzer(context.body).IsValid(); std::vector<QJsonObject> rows;
    const auto solids = parts(context.body, TopAbs_SOLID);
    for (int index = 1; index <= solids.Extent(); ++index) {
        const auto solid = solids(index); const auto props = properties(solid);
        std::vector<std::pair<QString, int>> ordered;
        const auto faces = parts(solid, TopAbs_FACE);
        for (int face = 1; face <= faces.Extent(); ++face) for (const auto &owner : context.owners) if (faces(face).IsSame(owner.face)) {
            if (!owner.feature.isEmpty()) {
                auto found = std::find_if(ordered.begin(), ordered.end(), [&](const auto &entry) { return entry.first == owner.feature; });
                if (found == ordered.end()) ordered.push_back({owner.feature, 1});
                else ++found->second;
            }
            break;
        }
        std::stable_sort(ordered.begin(), ordered.end(), [](const auto &first, const auto &second) { return first.second > second.second; }); QJsonArray features; for (const auto &owner : ordered) features.append(owner.first);
        rows.push_back({{"volume", props["volume"]}, {"box", QJsonArray{props["bbox_min"], props["bbox_max"]}}, {"center", props["center_of_mass"]}, {"features", features}});
    }
    std::stable_sort(rows.begin(), rows.end(), [](const auto &first, const auto &second) { return first["volume"].toDouble() > second["volume"].toDouble(); }); QJsonArray bodies; for (const auto &row : rows) bodies.append(row); report["bodies"] = bodies;
    report["voids"] = parts(context.body, TopAbs_SHELL).Extent() - static_cast<int>(rows.size());
    const auto rules = args["rules"].toObject();
    if (!rules.isEmpty()) {
        const auto checked = pairs(context, rules);
        report["pairs"] = checked.first;
        report["pairs_checked"] = checked.second;
        const auto enabled = rules["proofing"];
        if (enabled.toBool() || (enabled.isDouble() && enabled.toDouble() != 0)) report["proof"] = proof(context.body);
    }
    return report;
}
}
#endif
