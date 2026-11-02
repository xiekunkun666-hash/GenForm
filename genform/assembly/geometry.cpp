#include "detail.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRepAlgoAPI_Common.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <QElapsedTimer>
#include <TopExp_Explorer.hxx>
#include <TopTools_ListOfShape.hxx>
#include <algorithm>
#include <limits>
#include <optional>

namespace genform::assembly::detail {
namespace {
bool boxesTouch(const Part &first, const Part &second, double gap = 0) {
    for (int axis = 0; axis < 3; ++axis)
        if (first.low[axis] > second.high[axis] + gap || second.low[axis] > first.high[axis] + gap) return false;
    return true;
}

struct Overlap {
    double volume = 0;
    double depth = 0;
    QJsonValue center = QJsonValue::Null;
};

Overlap overlap(const TopoDS_Shape &first, const TopoDS_Shape &second) {
    BRepAlgoAPI_Common boolean;
    TopTools_ListOfShape arguments, tools;
    arguments.Append(first);
    tools.Append(second);
    boolean.SetArguments(arguments);
    boolean.SetTools(tools);
    boolean.SetNonDestructive(true);
    boolean.Build();
    if (!boolean.IsDone() || boolean.HasErrors()) fail("Exact intersection failed; collision result is unknown");
    const auto common = boolean.Shape();
    if (kernel::native::empty(common)) return {};
    GProp_GProps volume, area;
    BRepGProp::VolumeProperties(common, volume);
    BRepGProp::SurfaceProperties(common, area);
    const double amount = std::abs(volume.Mass());
    if (!std::isfinite(amount)) fail("Intersection returned non-finite volume");
    double thickness = area.Mass() > 1e-12 ? 2 * amount / area.Mass() : 0;
    const auto bounds = kernel::native::bounds(common);
    const auto low = coordinates(bounds[0]), high = coordinates(bounds[1]);
    for (int axis = 0; axis < 3; ++axis) thickness = std::min(thickness, high[axis] - low[axis]);
    return {amount, std::max(thickness, 0.0), kernel::native::json(volume.CentreOfMass())};
}

QJsonObject distance(const Part &first, const Part &second) {
    BRepExtrema_DistShapeShape meter(first.shape, second.shape);
    if (!meter.IsDone() || meter.NbSolution() < 1) fail("Exact part distance computation failed");
    const auto pointFirst = meter.PointOnShape1(1), pointSecond = meter.PointOnShape2(1);
    return {{"distance", meter.Value()}, {"points", QJsonArray{kernel::native::json(pointFirst), kernel::native::json(pointSecond)}},
            {"delta", kernel::native::json(gp_Vec(pointFirst, pointSecond))}, {"point", kernel::native::json(pointFirst)}};
}

QString name(const Part &part, int index) { return part.definition.value("name").toString(QString("零件%1").arg(index + 1)); }

std::optional<QJsonArray> rgb(const QString &color) {
    if (color.size() != 7 || !color.startsWith('#')) return {};
    bool valid = false;
    const auto value = color.mid(1).toUInt(&valid, 16);
    if (!valid) return {};
    return QJsonArray{((value >> 16) & 255) / 255.0, ((value >> 8) & 255) / 255.0, (value & 255) / 255.0};
}
}

void requireExact(const std::vector<Part> &parts) {
    for (const auto &part : parts)
        if (!part.exact) fail("Exact solid BREP required: STL meshes and non-solid geometry cannot certify interference, clearance, mass, sequence or export checks: " + part.definition["name"].toString());
}

void updateBounds(Part &part) {
    const auto bounds = kernel::native::bounds(part.shape);
    part.low = coordinates(bounds[0]);
    part.high = coordinates(bounds[1]);
}

QJsonObject mesh(const Part &part) {
    QJsonObject result = part.model;
    const auto transform = placement(part.definition);
    for (const auto &field : {QString("verts"), QString("normals"), QString("vertices")}) {
        QJsonArray values;
        for (const auto &entry : part.model[field].toArray()) values.append(json(detail::apply(transform, coordinates(entry), field == "normals")));
        result[field] = values;
    }
    QJsonArray segments;
    for (const auto &entry : part.model["segments"].toArray()) {
        QJsonArray line;
        for (const auto &position : entry.toArray()) line.append(json(detail::apply(transform, coordinates(position))));
        segments.append(line);
    }
    result["segments"] = segments;
    QJsonArray edgeKinds, edgeLengths, edgeRadii;
    for (const auto &entry : part.model["edges"].toArray()) {
        const auto edge = entry.toObject();
        const QString type = edge["type"].toString();
        edgeKinds.append(type == "line" ? 0 : type == "circle" ? 1 : 2);
        edgeLengths.append(edge["length"]);
        edgeRadii.append(edge.contains("radius") ? edge["radius"] : QJsonValue(QJsonValue::Null));
    }
    result["edge_kind"] = edgeKinds;
    result["edge_length"] = edgeLengths;
    result["edge_radius"] = edgeRadii;
    for (const auto &field : {QString("edges"), QString("faces")}) {
        QJsonArray entities;
        for (const auto &entry : part.model[field].toArray()) {
            auto entity = entry.toObject();
            for (const auto &key : {QString("mid"), QString("center"), QString("point"), QString("axis_point")})
                if (entity[key].isArray()) entity[key] = json(detail::apply(transform, coordinates(entity[key])));
            for (const auto &key : {QString("normal"), QString("dir"), QString("axis")})
                if (entity[key].isArray()) entity[key] = json(detail::apply(transform, coordinates(entity[key]), true));
            entities.append(entity);
        }
        result[field] = entities;
    }
    if (part.definition["mirror"].toBool()) {
        QJsonArray reversed;
        for (const auto &entry : part.model["tris"].toArray()) {
            const auto indices = entry.toArray();
            reversed.append(QJsonArray{indices[2], indices[1], indices[0]});
        }
        result["tris"] = reversed;
    }
    const auto props = part.document["props"].toObject();
    result["name"] = part.definition["name"];
    result["low"] = json(part.low);
    result["high"] = json(part.high);
    result["geometry"] = part.exact ? "brep" : "mesh";
    result["exact"] = part.exact;
    const QMap<QString, QString> materialColors{{"普通碳钢", "#8E97A3"}, {"合金钢", "#7F8894"}, {"不锈钢 304", "#B9C0C8"},
        {"铸铁", "#6B6F76"}, {"铝合金 6061", "#C9CED6"}, {"铝合金 7075", "#C4CAD2"}, {"45# 钢", "#858C96"},
        {"黄铜", "#C9A24A"}, {"紫铜", "#C07A4E"}, {"钛合金 Ti-6Al-4V", "#A8A39A"}, {"ABS", "#E6E1D3"},
        {"尼龙 PA12", "#DDDAD2"}, {"聚碳酸酯 PC", "#C7D7E6"}, {"PLA", "#E9E4DA"}, {"聚丙烯 PP", "#2F3135"},
        {"PMMA 亚克力", "#D9E4EC"}, {"铸造铝合金 A356", "#B8BDC4"}, {"钢化玻璃", "#2A3A48"}, {"橡胶", "#1E1F21"}, {"皮革 + 海绵", "#7A4A2C"}};
    const auto own = rgb(props["color"].toString()), material = rgb(materialColors.value(props["material"].toString()));
    const QJsonArray tint = own ? *own : material ? *material : QJsonArray{0.72, 0.74, 0.77};
    QJsonArray tints;
    for (int index = 0; index < result["verts"].toArray().size(); ++index) tints.append(tint);
    const auto painted = props["feature_colors"].toObject(), shades = props["feature_opacity"].toObject();
    const auto faces = part.model["faces"].toArray(), faceIds = part.model["tri_face"].toArray(), triangles = part.model["tris"].toArray();
    double minimumAlpha = 1, maximumAlpha = 0;
    for (const auto &entry : faces) {
        const auto face = entry.toObject();
        const QString owner = face["feature"].toString(), origin = face["origin"].toString();
        const double alpha = scalar(shades.value(owner), scalar(shades.value(origin), 1));
        if (alpha < 0 || alpha > 1) fail("Feature opacity must be between zero and one");
        minimumAlpha = std::min(minimumAlpha, alpha); maximumAlpha = std::max(maximumAlpha, alpha);
    }
    for (int triangle = 0; triangle < triangles.size() && triangle < faceIds.size(); ++triangle) {
        const int faceIndex = faceIds[triangle].toInt(-1);
        if (faceIndex < 0 || faceIndex >= faces.size()) continue;
        const auto face = faces[faceIndex].toObject();
        const auto primary = rgb(painted[face["feature"].toString()].toString()), inherited = rgb(painted[face["origin"].toString()].toString());
        const auto shade = primary ? *primary : inherited ? *inherited : tint;
        for (const auto &vertex : triangles[triangle].toArray()) tints[vertex.toInt()] = shade;
    }
    const double alpha = props.contains("alpha") ? number(props, "alpha", 1) : !faces.isEmpty() && maximumAlpha < 1 ? minimumAlpha : 1;
    if (alpha < 0 || alpha > 1) fail("Part opacity must be between zero and one");
    result["alpha"] = alpha;
    result["tints"] = tints;
    result.remove("props");
    return result;
}

QJsonObject interference(const std::vector<Part> &parts, const QJsonObject &args) {
    if (parts.size() < 2) fail("Interference requires at least two parts");
    const double threshold = number(args, "volume_tolerance", 0.01);
    if (threshold < 0) fail("Volume tolerance must be nonnegative");
    QJsonArray clashes;
    int pairs = 0;
    for (int first = 0; first < static_cast<int>(parts.size()); ++first)
        for (int second = first + 1; second < static_cast<int>(parts.size()); ++second) {
            ++pairs;
            if (!boxesTouch(parts[first], parts[second])) continue;
            const auto found = overlap(parts[first].shape, parts[second].shape);
            if (found.volume > threshold)
                clashes.append(QJsonObject{{"a", first}, {"b", second}, {"names", QJsonArray{name(parts[first], first), name(parts[second], second)}},
                    {"volume", found.volume}, {"center", found.center}, {"depth", found.depth}});
        }
    return {{"clashes", clashes}, {"pairs", pairs}, {"exact", true}, {"complete", true}};
}

QJsonObject relationship(const Part &first, const Part &second, double tolerance, double clearance) {
    if (tolerance < 0 || clearance <= 0) fail("Contact tolerance must be nonnegative and clearance positive");
    if (!boxesTouch(first, second, clearance)) return {};
    const auto measured = distance(first, second);
    const double gap = measured["distance"].toDouble();
    if (gap > tolerance && gap >= clearance - 1e-3) return {};
    if (gap <= tolerance) {
        const auto common = overlap(first.shape, second.shape);
        const QString kind = common.volume > 0.01 && common.depth > tolerance ? "clash" : "touch";
        return {{"kind", kind}, {"distance", gap}, {"volume", common.volume}, {"depth", common.depth},
                {"point", kind == "clash" && !common.center.isNull() ? common.center : measured["point"]}};
    }
    return {{"kind", "gap"}, {"distance", gap}, {"volume", 0}, {"depth", 0}, {"point", measured["point"]}};
}

QJsonObject contacts(const std::vector<Part> &parts, const QJsonObject &args, QMap<QString, QJsonObject> &cache) {
    if (parts.empty()) fail("Connection query requires at least one part");
    const auto rules = args["rules"].toObject();
    const double tolerance = number(rules, "tolerance", 0.1), clearance = std::max(number(rules, "clearance", 0.5), tolerance);
    if (tolerance < 0 || clearance <= 0) fail("Invalid contact rules");
    const double budget = args.contains("budget") ? number(args, "budget") : -1;
    if (args.contains("budget") && budget < 0) fail("Budget must be nonnegative");
    std::vector<std::pair<int, int>> candidates;
    for (int first = 0; first < static_cast<int>(parts.size()); ++first)
        for (int second = first + 1; second < static_cast<int>(parts.size()); ++second)
            if (boxesTouch(parts[first], parts[second], clearance)) candidates.emplace_back(first, second);
    std::vector<QSet<int>> links(parts.size());
    for (const auto &entry : args["links"].toArray()) {
        const auto pair = entry.toArray();
        if (pair.size() != 2) fail("Connection link requires two part indices");
        const int first = pair[0].toInt(-1), second = pair[1].toInt(-1);
        if (first < 0 || second < 0 || first >= static_cast<int>(parts.size()) || second >= static_cast<int>(parts.size())) fail("Invalid connection link reference");
        links[first].insert(second);
        links[second].insert(first);
    }
    QElapsedTimer timer;
    timer.start();
    QJsonArray pairs;
    int done = 0, fresh = 0;
    for (const auto &[first, second] : candidates) {
        const QString key = parts[first].key + "|" + parts[second].key + "|" + QString::number(tolerance, 'g', 17) + "|" + QString::number(clearance, 'g', 17);
        QJsonObject found;
        if (cache.contains(key)) found = cache.value(key);
        else {
            if (budget >= 0 && fresh > 0 && timer.elapsed() / 1000.0 > budget) break;
            found = relationship(parts[first], parts[second], tolerance, clearance);
            if (cache.size() >= 20000) cache.clear();
            cache.insert(key, found);
            ++fresh;
        }
        ++done;
        if (found.isEmpty()) continue;
        if (found["kind"] == "clash" || found["kind"] == "touch") {
            links[first].insert(second);
            links[second].insert(first);
        }
        found["a"] = first;
        found["b"] = second;
        found["names"] = QJsonArray{name(parts[first], first), name(parts[second], second)};
        pairs.append(found);
    }
    QSet<int> reached{0};
    std::vector<int> waiting{0};
    while (!waiting.empty()) {
        const int current = waiting.back();
        waiting.pop_back();
        for (const int other : links[current]) if (!reached.contains(other)) { reached.insert(other); waiting.push_back(other); }
    }
    QJsonArray floating;
    for (int index = 0; index < static_cast<int>(parts.size()); ++index) if (!reached.contains(index)) floating.append(index);
    const bool partial = done < static_cast<int>(candidates.size());
    return {{"pairs", pairs}, {"floating", floating}, {"checked", static_cast<int>(candidates.size())},
            {"done", done}, {"total", static_cast<int>(candidates.size())}, {"fresh", fresh}, {"partial", partial},
            {"complete", !partial}, {"floating_provisional", partial}, {"exact", true}};
}

QJsonObject measureParts(const std::vector<Part> &parts) {
    if (parts.empty() || parts.size() > 2) fail("Measurement requires one or two parts");
    QJsonArray items;
    for (const auto &part : parts) {
        const auto props = kernel::native::properties(part.shape);
        Vector size{};
        for (int axis = 0; axis < 3; ++axis) size[axis] = part.high[axis] - part.low[axis];
        items.append(QJsonObject{{"size", json(size)}, {"low", json(part.low)}, {"high", json(part.high)},
            {"volume", props["volume"]}, {"area", props["area"]}});
    }
    QJsonObject result{{"items", items}, {"exact", true}};
    if (parts.size() == 2) {
        const auto measured = distance(parts[0], parts[1]);
        for (const auto &key : {QString("distance"), QString("points"), QString("delta")}) result[key] = measured[key];
    }
    return result;
}

QJsonObject massProperties(const std::vector<Part> &parts) {
    if (parts.empty()) fail("Mass query requires at least one part");
    QJsonArray items, missing;
    Vector moment{};
    double total = 0;
    for (int index = 0; index < static_cast<int>(parts.size()); ++index) {
        const auto &part = parts[index];
        const auto mass = kernel::native::mass(part.shape);
        const auto centre = coordinates(kernel::native::json(mass.center));
        const auto properties = part.document["props"].toObject();
        const QString material = part.definition.value("material").toString(properties["material"].toString());
        double rho = density(material);
        if (part.definition.contains("density")) rho = number(part.definition, "density", 0, true);
        else if (properties.contains("density")) rho = number(properties, "density", 0, true);
        QJsonObject row{{"volume", std::abs(mass.volume)}, {"centre", json(centre)}, {"material", material}, {"index", index}};
        if (rho > 0) {
            const double grams = std::abs(mass.volume) / 1000 * rho;
            row["density"] = rho;
            row["mass_g"] = grams;
            total += grams;
            for (int axis = 0; axis < 3; ++axis) moment[axis] += grams * centre[axis];
        } else {
            row["mass_g"] = QJsonValue::Null;
            missing.append(index);
        }
        items.append(row);
    }
    QJsonValue centre = QJsonValue::Null;
    if (total > 0) { for (double &value : moment) value /= total; centre = json(moment); }
    return {{"items", items}, {"mass_g", total}, {"centre", centre}, {"missing_materials", missing},
            {"complete", missing.isEmpty()}, {"exact_geometry", true}, {"density_unit", "g/cm3"}, {"volume_unit", "mm3"}};
}

QJsonObject sequence(const std::vector<Part> &parts, const QJsonObject &args) {
    if (parts.size() < 2) fail("Assembly sequence requires at least two parts");
    const int samples = args.value("samples").toInt(36);
    if (samples < 10 || samples > 1000) fail("Sequence samples must be between 10 and 1000");
    const std::array<QString, 6> labels{"+X", "-X", "+Y", "-Y", "+Z", "-Z"};
    std::vector<bool> remaining(parts.size(), true);
    std::vector<QJsonObject> rows(parts.size());
    std::vector<int> removed;
    for (int index = 0; index < static_cast<int>(parts.size()); ++index)
        rows[index] = {{"index", index}, {"name", name(parts[index], index)}, {"order", QJsonValue::Null},
            {"ok", index == 0}, {"directions", QJsonArray{}}, {"blocked", QJsonObject{}}, {"clash", QJsonValue::Null}, {"threaded", false}};
    bool progress = true;
    while (progress) {
        progress = false;
        for (int index = static_cast<int>(parts.size()) - 1; index > 0; --index) {
            if (!remaining[index]) continue;
            QJsonArray free;
            QJsonObject blocked;
            QJsonValue clash = QJsonValue::Null;
            for (int other = 0; other < static_cast<int>(parts.size()); ++other) {
                if (other == index || !remaining[other] || !boxesTouch(parts[index], parts[other])) continue;
                if (overlap(parts[index].shape, parts[other].shape).volume > 0.01) { clash = name(parts[other], other); break; }
            }
            if (clash.isNull()) {
                for (int direction = 0; direction < 6; ++direction) {
                    const int axis = direction / 2;
                    const double sign = direction % 2 == 0 ? 1.0 : -1.0;
                    double travel = 1;
                    for (int other = 0; other < static_cast<int>(parts.size()); ++other) if (remaining[other] && other != index)
                        travel = std::max(travel, (sign > 0 ? parts[other].high[axis] - parts[index].low[axis] : parts[index].high[axis] - parts[other].low[axis]) + 1);
                    int blocker = -1;
                    for (int step = 1; step <= samples && blocker < 0; ++step) {
                        gp_Vec shift(0, 0, 0);
                        shift.SetCoord(axis + 1, sign * travel * step / samples);
                        Part moved = parts[index];
                        moved.shape = kernel::native::translated(moved.shape, shift);
                        updateBounds(moved);
                        for (int other = 0; other < static_cast<int>(parts.size()); ++other)
                            if (remaining[other] && other != index && boxesTouch(moved, parts[other]) && overlap(moved.shape, parts[other].shape).volume > 0.01) { blocker = other; break; }
                    }
                    if (blocker < 0) free.append(labels[direction]);
                    else blocked[labels[direction]] = name(parts[blocker], blocker);
                }
            }
            rows[index]["directions"] = free;
            rows[index]["blocked"] = blocked;
            rows[index]["clash"] = clash;
            rows[index]["ok"] = !free.isEmpty();
            if (!free.isEmpty()) { remaining[index] = false; removed.push_back(index); progress = true; }
        }
    }
    QJsonArray output, stuck;
    rows[0]["order"] = 0;
    rows[0]["directions"] = QJsonArray{"+X", "-X", "+Y", "-Y", "+Z", "-Z"};
    output.append(rows[0]);
    for (auto entry = removed.rbegin(); entry != removed.rend(); ++entry) { rows[*entry]["order"] = output.size(); output.append(rows[*entry]); }
    for (int index = 1; index < static_cast<int>(parts.size()); ++index) if (remaining[index]) { output.append(rows[index]); stuck.append(index); }
    return {{"steps", output}, {"ok", stuck.isEmpty()}, {"stuck", stuck}, {"sampled", true},
            {"certified", false}, {"samples", samples}, {"method", "sampled six-axis rigid straight-line disassembly"},
            {"limitations", QJsonArray{"Thin blockers may fall between samples", "Thread unscrewing, elastic insertion and tool access are not modeled"}}};
}

QJsonObject stack(const std::vector<Part> &parts, const QJsonObject &args) {
    const QString axisName = args.value("axis").toString("Z").toUpper();
    const int axis = QString("XYZ").indexOf(axisName);
    if (axisName.size() != 1 || axis < 0) fail("Stack axis must be X, Y or Z");
    QJsonArray table, segments;
    std::vector<double> cuts;
    double low = std::numeric_limits<double>::infinity(), high = -low;
    for (int index = 0; index < static_cast<int>(parts.size()); ++index) {
        const auto &part = parts[index];
        low = std::min(low, part.low[axis]); high = std::max(high, part.high[axis]);
        cuts.push_back(std::round(part.low[axis] * 1000) / 1000);
        cuts.push_back(std::round(part.high[axis] * 1000) / 1000);
        table.append(QJsonObject{{"index", index}, {"name", name(part, index)}, {"from", part.low[axis]}, {"to", part.high[axis]}, {"height", part.high[axis] - part.low[axis]}});
    }
    std::sort(cuts.begin(), cuts.end());
    cuts.erase(std::unique(cuts.begin(), cuts.end()), cuts.end());
    for (size_t index = 1; index < cuts.size(); ++index) {
        const double middle = (cuts[index - 1] + cuts[index]) / 2;
        QJsonArray names, indices;
        for (int partIndex = 0; partIndex < static_cast<int>(parts.size()); ++partIndex)
            if (parts[partIndex].low[axis] <= middle && parts[partIndex].high[axis] >= middle) {
                names.append(name(parts[partIndex], partIndex)); indices.append(partIndex);
            }
        segments.append(QJsonObject{{"from", cuts[index - 1]}, {"to", cuts[index]}, {"height", cuts[index] - cuts[index - 1]}, {"parts", names}, {"indices", indices}});
    }
    return {{"axis", axisName}, {"low", parts.empty() ? 0 : low}, {"high", parts.empty() ? 0 : high},
            {"total", parts.empty() ? 0 : high - low}, {"parts", table}, {"segments", segments},
            {"method", "bounding-box layers, not material occupancy"}, {"exact", false}};
}
}
#endif
