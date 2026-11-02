#include "detail.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <GProp_GProps.hxx>
#include <TopTools_ListOfShape.hxx>
#include <algorithm>
#include <gp_Ax2.hxx>

namespace genform::assembly::detail {
namespace {
constexpr double minimumBottom = 0.5;
constexpr double axisGap = 0.1;
struct Thread {
    QString feature, name, size;
    gp_Pnt spot;
    gp_Vec along, side;
    double pitch = 0, phase = 0, start = 0, length = 0;
    std::optional<double> depth;
    bool modeled = false, mirrored = false;
};
struct Threads { std::vector<Thread> screws, holes; bool complete = true; };

double wrapped(double angle) {
    double result = std::fmod(angle, 360);
    if (result < 0) result += 360;
    return result < 1e-8 || 360 - result < 1e-8 ? 0 : result;
}

double angleGap(double first, double second) {
    const double gap = std::abs(wrapped(first) - wrapped(second));
    return std::min(gap, 360 - gap);
}

gp_Vec sideOf(const gp_Vec &along) {
    const gp_Vec reference = std::abs(along.X()) < 0.9 ? gp_Vec(1, 0, 0) : gp_Vec(0, 1, 0);
    return (reference - along * reference.Dot(along)).Normalized();
}

double angleAbout(const gp_Vec &axis, const gp_Vec &side) {
    const auto reference = sideOf(axis);
    return std::atan2(axis.Dot(reference.Crossed(side)), reference.Dot(side)) * 180 / std::acos(-1.0);
}

double neededPhase(const Thread &screw, const Thread &hole) {
    const double sign = hole.along.Dot(screw.along) > 0 ? 1 : -1;
    const double axial = gp_Vec(hole.spot, screw.spot).Dot(screw.along);
    const double angular = angleAbout(screw.along, hole.side) - angleAbout(screw.along, screw.side);
    return wrapped(sign * (screw.phase + 360 * axial / screw.pitch + (screw.mirrored ? -angular : angular)));
}

void variables(const QJsonObject &values, QMap<QString, double> &known) {
    QJsonObject pending = values;
    while (!pending.isEmpty()) {
        QStringList done;
        QString error;
        for (auto entry = pending.constBegin(); entry != pending.constEnd(); ++entry) {
            try { known[entry.key()] = scalar(kernel::native::resolve(entry.value(), known)); done.append(entry.key()); }
            catch (const std::exception &failure) { error = QString::fromUtf8(failure.what()); }
        }
        if (done.isEmpty()) fail("Cannot resolve fastener feature variables: " + error);
        for (const auto &key : done) pending.remove(key);
    }
}

Threads extract(const Part &part) {
    Threads result;
    if (part.buildFeatures.isEmpty()) { result.complete = false; return result; }
    const auto statuses = part.model["status"].toObject();
    QMap<QString, double> known;
    QJsonArray resolved;
    QMap<QString, QJsonObject> sketches;
    const QSet<QString> instanceKinds{"pattern_linear", "pattern_circular", "pattern_curve", "mirror", "move", "rotate", "scale", "import_step", "stud", "hole_adv", "thread"};
    for (const auto &entry : part.buildFeatures) {
        auto feature = entry.toObject();
        const QString id = feature["id"].toString(), kind = feature["type"].toString();
        if (feature["suppressed"].toBool() || statuses[id].toString() != "ok") { resolved.append(feature); continue; }
        if (instanceKinds.contains(kind) || kind.startsWith("pattern_")) result.complete = false;
        auto params = feature["params"].toObject();
        if (kind == "variables") variables(params["values"].toObject(), known);
        else params = kernel::native::resolve(params, known).toObject();
        feature["params"] = params;
        resolved.append(feature);
        if (kind == "sketch") { sketches[id] = params; continue; }
        if (kind != "screw" && !(kind == "hole" && params["kind"] == "tapped")) continue;
        const QString sketchId = params["sketch"].toString();
        if (!sketches.contains(sketchId)) fail("Cannot resolve fastener placement sketch: " + id);
        const auto location = kernel::native::makeSketch(sketches.value(sketchId), resolved);
        const auto along = (location.frame.normal * (params["flip"].toBool() ? 1 : -1)).Normalized();
        const QMap<QString, double> pitches{{"M2", 0.4}, {"M2.5", 0.45}, {"M3", 0.5}, {"M4", 0.7}, {"M5", 0.8}, {"M6", 1}, {"M8", 1.25}, {"M10", 1.5}, {"M12", 1.75}};
        const QString size = params.value("size").toString("M3");
        if (!pitches.contains(size)) fail("Unsupported fastener thread size: " + size + " in " + id);
        Thread common;
        common.feature = id;
        common.name = feature.value("name").toString(id);
        common.size = size;
        common.pitch = pitches.value(size);
        common.phase = number(params, "phase");
        common.modeled = params["thread"].toBool();
        common.mirrored = part.definition["mirror"].toBool();
        const auto matrix = placement(part.definition);
        common.along = kernel::native::vector(json(detail::apply(matrix, coordinates(kernel::native::json(along)), true))).Normalized();
        common.side = kernel::native::vector(json(detail::apply(matrix, coordinates(kernel::native::json(sideOf(along))), true))).Normalized();
        if (kind == "screw") {
            common.length = number(params, "length", 10, true);
            const QString head = params.value("head").toString("cap");
            if (head == "flat") {
                const QMap<QString, double> diameters{{"M2", 4}, {"M2.5", 5}, {"M3", 6.72}, {"M4", 8.96}, {"M5", 11.2}, {"M6", 13.44}, {"M8", 17.92}};
                if (!diameters.contains(size)) fail("Unsupported countersunk screw size: " + size);
                common.start = (diameters.value(size) - size.mid(1).toDouble()) / 2;
            } else if (head != "cap" && head != "button") fail("Unsupported screw head: " + head);
            if (common.length <= common.start) fail("Screw has no usable shank: " + id);
        } else if (!params.value("through").toBool(true)) common.depth = number(params, "depth", 0, true);
        for (const auto &spot : kernel::native::spots(location)) {
            Thread item = common;
            item.spot = kernel::native::point(json(detail::apply(matrix, coordinates(kernel::native::json(spot)))));
            (kind == "screw" ? result.screws : result.holes).push_back(item);
        }
    }
    return result;
}

TopoDS_Shape cylinder(const gp_Pnt &base, const gp_Vec &along, double radius, double height) {
    BRepPrimAPI_MakeCylinder maker(gp_Ax2(base, gp_Dir(along)), radius, height);
    const auto result = maker.Shape();
    if (!maker.IsDone()) fail("Cannot build fastener measurement cylinder");
    return result;
}

TopoDS_Shape intersection(const TopoDS_Shape &first, const TopoDS_Shape &second) {
    BRepAlgoAPI_Common maker;
    TopTools_ListOfShape arguments, tools;
    arguments.Append(first); tools.Append(second);
    maker.SetArguments(arguments); maker.SetTools(tools);
    maker.SetNonDestructive(true);
    maker.Build();
    if (!maker.IsDone() || maker.HasErrors()) fail("Fastener exact intersection failed; no check result is available");
    return maker.Shape();
}

double engagement(const Thread &screw, const TopoDS_Shape &target) {
    const double diameter = screw.size.mid(1).toDouble(), inner = diameter / 2 + 0.10, outer = inner + 0.05;
    const double span = screw.length - screw.start;
    const auto base = screw.spot.Translated(screw.along * screw.start);
    BRepAlgoAPI_Cut tube(cylinder(base, screw.along, outer, span), cylinder(base.Translated(screw.along * -0.01), screw.along, inner, span + 0.02));
    if (!tube.IsDone() || tube.HasErrors() || kernel::native::empty(tube.Shape())) fail("Cannot construct fastener engagement probe");
    const auto common = intersection(tube.Shape(), target);
    if (kernel::native::empty(common)) return 0;
    GProp_GProps volume;
    BRepGProp::VolumeProperties(common, volume);
    const double engaged = std::abs(volume.Mass()) / (std::acos(-1.0) * (outer * outer - inner * inner));
    if (!std::isfinite(engaged) || engaged > span + 1e-3) fail("Invalid fastener engagement intersection volume");
    return std::min(span, engaged);
}

QJsonValue bottomClearance(const Thread &screw, const TopoDS_Shape &target) {
    const auto tip = screw.spot.Translated(screw.along * screw.length);
    const auto common = intersection(cylinder(tip, screw.along, 0.3, minimumBottom * 6), target);
    if (kernel::native::empty(common)) return QJsonValue::Null;
    const auto horizontal = sideOf(screw.along), vertical = screw.along.Crossed(horizontal);
    const gp_Vec origin(tip.X(), tip.Y(), tip.Z());
    gp_Trsf local;
    local.SetValues(horizontal.X(), horizontal.Y(), horizontal.Z(), -horizontal.Dot(origin),
                    vertical.X(), vertical.Y(), vertical.Z(), -vertical.Dot(origin),
                    screw.along.X(), screw.along.Y(), screw.along.Z(), -screw.along.Dot(origin));
    const auto box = kernel::native::bounds(kernel::native::moved(common, local));
    return std::max(0.0, box[0].toArray()[2].toDouble());
}

double engageFactor(const QString &material) {
    const std::vector<std::pair<QString, double>> factors{{"铝", 1.5}, {"塑料", 2}, {"尼龙", 2}, {"ABS", 2}, {"PLA", 2}, {"钢", 1}, {"铜", 1}, {"铁", 1}, {"钛", 1}};
    for (const auto &[name, factor] : factors) if (material.contains(name)) return factor;
    return 1.5;
}

QString partName(const Part &part, int index) { return part.definition.value("name").toString(QString("零件%1").arg(index + 1)); }
}

QJsonObject fasteners(const std::vector<Part> &parts) {
    if (parts.size() < 2) fail("Fastener checks require at least two parts");
    requireExact(parts);
    std::vector<Threads> metadata;
    QJsonArray unchecked;
    for (int index = 0; index < static_cast<int>(parts.size()); ++index) {
        metadata.push_back(extract(parts[index]));
        if (!metadata.back().complete) unchecked.append(index);
    }
    QJsonArray pairs, loose;
    using Key = std::pair<int, QString>;
    QMap<Key, std::vector<double>> wanted;
    QSet<Key> impossible;
    for (int index = 0; index < static_cast<int>(parts.size()); ++index) {
        for (const auto &screw : metadata[index].screws) {
            const Thread *matched = nullptr;
            int target = -1;
            for (int other = 0; other < static_cast<int>(parts.size()) && !matched; ++other) {
                if (other == index) continue;
                for (const auto &hole : metadata[other].holes) {
                    const double alignment = hole.along.Dot(screw.along);
                    if (hole.size != screw.size || std::abs(alignment) < 0.999) continue;
                    const gp_Vec apart(screw.spot, hole.spot);
                    const double reach = apart.Dot(screw.along);
                    if ((apart - screw.along * reach).Magnitude() > axisGap) continue;
                    const double depth = hole.depth.value_or(1e6);
                    const double low = alignment > 0 ? reach : reach - depth, high = alignment > 0 ? reach + depth : reach;
                    if (std::min(high, screw.length) - std::max(low, screw.start) <= 0) continue;
                    matched = &hole; target = other; break;
                }
            }
            if (!matched) {
                loose.append(QJsonObject{{"screw", index}, {"name", partName(parts[index], index)}, {"size", screw.size}});
                continue;
            }
            const auto &hole = *matched;
            const QString material = parts[target].document["props"].toObject()["material"].toString();
            const double diameter = screw.size.mid(1).toDouble(), need = engageFactor(material) * diameter;
            const double engaged = engagement(screw, parts[target].shape);
            const auto bottom = bottomClearance(screw, parts[target].shape);
            const double phase = neededPhase(screw, hole), gap = angleGap(phase, hole.phase);
            const bool handedMismatch = screw.modeled && hole.modeled && screw.mirrored != hole.mirrored;
            const bool phaseOk = !handedMismatch && (gap <= 3 || !(screw.modeled && hole.modeled));
            QJsonArray problems;
            if (engaged + 1e-6 < need) problems.append(QString("拧进去只有 %1 mm, %2里至少要 %3 mm (%4d)").arg(engaged, 0, 'f', 1).arg(material.isEmpty() ? "这种材质" : material).arg(need, 0, 'f', 1).arg(need / diameter));
            if (!bottom.isNull() && bottom.toDouble() < minimumBottom - 1e-3) problems.append(QString("螺丝尖离孔底只有 %1 mm (至少留 0.5 mm): 换短一号的螺丝或把孔打深").arg(bottom.toDouble(), 0, 'f', 2));
            if (handedMismatch) problems.append("镜像使内外螺纹旋向相反，不能通过调整相位啮合");
            else if (!phaseOk) problems.append(QString("螺纹相位对不上: 孔现在 %1°, 要 %2° (点“对齐螺纹相位”)").arg(hole.phase, 0, 'f', 0).arg(phase, 0, 'f', 0));
            const Key key{target, hole.feature};
            wanted[key].push_back(phase);
            if (handedMismatch) impossible.insert(key);
            pairs.append(QJsonObject{{"screw", index}, {"hole_part", target}, {"screw_name", partName(parts[index], index)},
                {"hole_name", partName(parts[target], target)}, {"feature", hole.feature}, {"feature_name", hole.name},
                {"size", screw.size}, {"engaged", engaged}, {"need", need}, {"bottom", bottom}, {"phase", hole.phase},
                {"phase_need", phase}, {"phase_ok", phaseOk}, {"problems", problems}});
        }
    }
    QJsonArray fixes;
    QSet<Key> conflicts;
    for (auto entry = wanted.constBegin(); entry != wanted.constEnd(); ++entry) {
        double spread = 0;
        for (const double first : entry.value()) for (const double second : entry.value()) spread = std::max(spread, angleGap(first, second));
        const bool conflict = spread >= 1;
        if (conflict) conflicts.insert(entry.key());
        fixes.append(QJsonObject{{"part", entry.key().first}, {"feature", entry.key().second},
            {"phase", conflict || impossible.contains(entry.key()) ? QJsonValue(QJsonValue::Null) : QJsonValue(entry.value().front())}});
    }
    for (int index = 0; index < pairs.size(); ++index) {
        auto pair = pairs[index].toObject();
        if (conflicts.contains({pair["hole_part"].toInt(), pair["feature"].toString()}) && !pair["phase_ok"].toBool()) {
            auto problems = pair["problems"].toArray();
            problems.append("这个孔特征上的几颗螺丝要的相位不一样 (螺丝头不在螺距整数倍的平面上): 拆成几个孔特征或改螺丝长度");
            pair["problems"] = problems;
            pairs[index] = pair;
        }
    }
    return {{"pairs", pairs}, {"loose", loose}, {"fix", fixes}, {"complete", unchecked.isEmpty()},
        {"unchecked_parts", unchecked}, {"method", "native screw/tapped-hole feature matching with exact annular engagement and axial bottom probes"},
        {"limitations", QJsonArray{"Only screw and hole(kind=tapped) feature metadata is recognized; imported threads, studs, nuts and patterned instances are not inferred", "Matching preserves Python's first compatible size/axis/span candidate; multiple hosts and multi-start or non-metric threads are not resolved", "Engagement is an annular material-length estimate, not thread shear capacity or preload analysis", "Bottom probing extends 3 mm beyond the screw tip; null means no material found within this range", "Phase fixes are recommendations only and do not modify part files"}}};
}
}
#endif
