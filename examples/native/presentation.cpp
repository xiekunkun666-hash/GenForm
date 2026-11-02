#include "geometry.hpp"
#ifdef GENFORM_HAS_OCCT
#include "genform/view/viewport.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/assembly/engine.hpp"
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <QFile>
#include <QJsonDocument>
#include <QSaveFile>
#include <QTextStream>
#include <QSet>

namespace examples {

QJsonObject assemblyReport(const QDir &directory, const QJsonArray &parts, ShapeCache &cache) {
    require(!parts.isEmpty(), "Cannot check an empty assembly");
    const auto rules = genform::domain::effective_rules();
    genform::assembly::Engine engine; engine.setAssembly({{"format", "genform-assembly"}, {"version", 1}, {"parts", parts}}, directory.absolutePath());
    const auto contacts = engine.query("contacts", {{"rules", rules}});
    require(contacts["complete"].toBool() && !contacts["partial"].toBool(), "Native assembly contacts incomplete");
    QJsonArray issues, resolved, properties; QJsonObject documents; QStringList materials, names, kinds;
    const auto shapes = cache.rows(directory, parts);
    for (qsizetype index = 0; index < parts.size(); ++index) {
        auto row = parts[index].toObject(); const QString path = row.contains("path") ? row["path"].toString() : directory.filePath(row["file"].toString());
        const auto document = loadObject(path), description = genform::domain::describe_document(document);
        documents[path] = document; row["path"] = path; resolved.append(row);
        materials.append(document["props"].toObject()["material"].toString()); names.append(row["name"].toString()); kinds.append(description["bound"].toBool() ? description["kind"].toString() : QString());
        auto measured = metrics(shapes[index]); measured["centre"] = measured["center_of_mass"]; properties.append(measured);
    }
    auto append = [&](const QJsonArray &more) { for (const auto &issue : more) issues.append(issue); };
    const auto pairs = contacts["pairs"].toArray(); int touches = 0;
    for (const auto &value : pairs) {
        const auto pair = value.toObject(); const QString kind = pair["kind"].toString();
        if (kind == "touch") ++touches;
        if (kind == "clash" || kind == "gap") issues.append(genform::domain::issue(kind == "clash" ? "error" : "warning", kind, kind == "clash" ? "Assembly interference" : "Assembly clearance below default rule", QString("%1 / %2: depth=%3 mm, distance=%4 mm, volume=%5 mm3").arg(names.value(pair["a"].toInt()), names.value(pair["b"].toInt())).arg(pair["depth"].toDouble()).arg(pair["distance"].toDouble()).arg(pair["volume"].toDouble()), QJsonArray{"part:" + QString::number(pair["a"].toInt()), "part:" + QString::number(pair["b"].toInt())}, pair["point"]));
    }
    for (const auto &value : contacts["floating"].toArray()) issues.append(genform::domain::issue("error", "floating", "Part has no connection to the assembly base", names.value(value.toInt()), QJsonArray{"part:" + QString::number(value.toInt())}));
    const auto bill = genform::domain::bill(resolved, documents); const auto totals = genform::domain::bill_totals(bill);
    if (totals["unbound"].toInt()) issues.append(genform::domain::issue("warning", "no_process", "Parts have no assigned manufacturing process", QString::number(totals["unbound"].toInt())));
    append(genform::domain::duplicates(resolved)); append(genform::domain::galvanic(pairs, materials, names)); append(genform::domain::fasteners(pairs, kinds, names)); append(genform::domain::bill_gaps(bill));
    append(genform::domain::mass_issues(properties, materials, names, metrics(compound(shapes))["size"].toArray())); append(genform::domain::orphans(pairs, kinds, names, properties));
    issues.append(genform::domain::issue("info", "contacts", QString::number(touches) + " assembly contacts", QString::number(contacts["checked"].toInt()) + " candidate pairs checked"));
    for (const auto &kind : QStringList{"custom", "purchase", "standard"}) { const auto total = totals[kind].toObject(); if (total["types"].toInt()) issues.append(genform::domain::issue("info", "bom_" + kind, kind + " parts", QString::fromUtf8(QJsonDocument(total).toJson(QJsonDocument::Compact)))); }
    issues.append(genform::domain::issue("info", "cost", "Indicative manufacturing total; not a supplier quote", QString::fromUtf8(QJsonDocument(totals["all"].toObject()).toJson(QJsonDocument::Compact))));
    return {{"scope", "Native default-rule contacts, connectivity, BOM and domain checks; no manufacturer certification"}, {"rules", rules}, {"contacts", contacts}, {"issues", issues}, {"counts", genform::domain::issue_summary(issues)}, {"stale", false}, {"live_error", ""}, {"limitations", QJsonArray{"These examples have no assembly joints; separate mechanism verification samples the prescribed stroke.", "Default-rule checks are not a production-tolerance, thread-engagement or continuous-motion certificate."}}};
}

static void image(const QJsonArray &parts, const QDir &directory, ShapeCache &cache, const QString &view, const QString &destination, const QSet<int> &hidden = {}, const QString &section = {}, const QJsonArray &focus = {}) {
    std::vector<TopoDS_Shape> shapes; int index = 0;
    for (const auto &value : parts) {
        const auto row = value.toObject(); if (hidden.contains(index++)) continue;
        auto shape = placed(cache.get(directory.filePath(row["file"].toString())), row);
        if (!section.isEmpty()) { TopoDS_Shape cutter;
            if (section == "XZ") cutter = BRepPrimAPI_MakeBox(gp_Pnt(-10000, -.25148874334, -10000), 20000, 20000, 20000).Shape();
            else cutter = BRepPrimAPI_MakeBox(gp_Pnt(-12, -10000, -10000), 20000, 20000, 20000).Shape();
            BRepAlgoAPI_Cut cut(shape, cutter); cut.Build(); require(cut.IsDone(), "Presentation section cut failed"); shape = cut.Shape();
        }
        shapes.push_back(shape);
    }
    QTemporaryDir temporary; require(temporary.isValid(), "Cannot create rendering transfer directory"); const QString geometry = temporary.filePath("assembly.step"); exportShape(compound(shapes), geometry);
    genform::Document document; document.add("import_step", {{"path", geometry}, {"op", "add"}}, "native assembly preview"); genform::kernel::Kernel builder; auto model = builder.build(document.features); validModel(model);
    genform::view::Viewport viewport; viewport.setWidth(1440); viewport.setHeight(1000); viewport.setDark(false); viewport.setPlanesVisible(false); viewport.setStyle("shaded"); viewport.setModel(model); viewport.setView(view); viewport.fit();
    if (focus.size() == 2) { const auto camera = viewport.cameraState(); QJsonObject adjusted = camera; const auto low = focus[0].toArray(), high = focus[1].toArray(); adjusted["centre"] = QJsonArray{(low[0].toDouble()+high[0].toDouble())/2,(low[1].toDouble()+high[1].toDouble())/2,(low[2].toDouble()+high[2].toDouble())/2}; double diagonal = 0; for (int axis = 0; axis < 3; ++axis) diagonal += std::pow(high[axis].toDouble() - low[axis].toDouble(), 2); adjusted["scale"] = 880 / std::max(1., std::sqrt(diagonal)); viewport.restoreCamera(adjusted); }
    require(viewport.saveImage(destination), "Native viewport image failed: " + destination); require(QFileInfo(destination).size() > 0, "Empty screenshot");
}

int presentAssembly(const Options &options) {
    require(!options.output.isEmpty(), "Specify --output containing generated parts and assemblies"); QDir directory(options.output); ShapeCache cache; QJsonArray records;
    const bool skye = options.name.contains("skye2"), claw = options.name.startsWith("button_claw_latch");
    struct Frame { QString assembly, view, filename, section; QSet<int> hidden; QJsonArray focus; };
    std::vector<Frame> frames;
    if (skye) {
        const QString assembled = QString::fromUtf8("SKYE2_复现装配.gasm"), exploded = QString::fromUtf8("SKYE2_拆分查看.gasm"), unplugged = QString::fromUtf8("SKYE2_拔塞查看.gasm");
        frames = {{assembled,"iso",QString::fromUtf8("SKYE2_整机预览.png"),{},{}},{assembled,"front",QString::fromUtf8("SKYE2_侧视.png"),{},{}},{assembled,"top",QString::fromUtf8("SKYE2_俯视.png"),{},{}},{exploded,"iso",QString::fromUtf8("SKYE2_拆分预览.png"),{},{}}};
        if (QFileInfo::exists(directory.filePath("skye2_side_plug.gform"))) {
            frames.push_back({assembled,"left",QString::fromUtf8("SKYE2_前口近景.png"),{}, {}}); frames.push_back({assembled,"bottom",QString::fromUtf8("SKYE2_安装孔及接口.png"),{}, {}});
            frames.push_back({assembled,"front",QString::fromUtf8("SKYE2_侧圆口近景.png"),{}, {}}); frames.push_back({assembled,"top",QString::fromUtf8("SKYE2_尾端孔近景.png"),{}, {}}); frames.push_back({assembled,"front",QString::fromUtf8("SKYE2_孔道剖视.png"),"XZ", {}});
        }
        if (QFileInfo::exists(directory.filePath(unplugged))) { frames.push_back({unplugged,"iso",QString::fromUtf8("SKYE2_拔塞露孔.png"),{}, {}}); frames.push_back({unplugged,"right",QString::fromUtf8("SKYE2_硅胶塞下开孔剖视.png"),"YZ", {}}); }
    } else if (claw) {
        const QString state = options.positional.value(0, "open"); require(QStringList{"closed","middle","open"}.contains(state), "State must be closed, middle or open");
        const QString assembly = state == "middle" ? "claw_latch_angle_20.gasm" : "claw_latch_" + state + ".gasm";
        frames = {{assembly,"iso","claw_latch_"+state+".png",{}, {9,12,13,14,15,16,17,18,19}}};
    } else frames = {{"button_latch_pressed.gasm","iso","button_latch_pressed.png",{}, {4,5,6,7,8}}, {"button_latch_open.gasm","iso","button_latch_open.png",{}, {4,5,6,7,8}}};
    if (skye && frames.size() > 4) {
        frames[4].focus = QJsonArray{QJsonArray{-102, -6.4, 14.1}, QJsonArray{-94., 5.9, 27}};
        frames[6].focus = QJsonArray{QJsonArray{-21, -5.5, 7}, QJsonArray{-5, -3.5, 20}};
        frames[7].focus = QJsonArray{QJsonArray{-6, -3, 8}, QJsonArray{.1, 2.5, 16}};
        if (frames.size() > 10) { frames[9].focus = QJsonArray{QJsonArray{-23, -23, 5}, QJsonArray{-2, 4.8, 24}}; frames[10].focus = QJsonArray{QJsonArray{-12.1, -24, 7}, QJsonArray{-11.9, 6, 19}}; }
    }
    if (!options.values["assembly"].toString().isEmpty()) frames = {{options.values["assembly"].toString(), "iso", "build_show.png", {}, {}, {}}};
    for (const auto &frame : frames) {
        const auto assembly = loadObject(directory.filePath(frame.assembly)); const auto parts = assembly["parts"].toArray(); require(parts.size() == (skye ? QFileInfo::exists(directory.filePath("skye2_side_plug.gform")) ? 9 : 3 : claw ? 20 : 9), "Unexpected assembly part count");
        if (!skye) {
            const auto config = claw ? configuration(options.positional.value(0) == "closed" ? 0 : options.positional.value(0) == "middle" ? 20 : 40) : QJsonObject{};
            const auto bolt = placed(cache.get(directory.filePath(claw ? "pushrod.gform" : "button_bolt.gform")), parts[claw ? 2 : 1].toObject());
            const auto bounds = genform::kernel::native::bounds(bolt); const double shift = claw ? config["shift"].toDouble() : parts[1].toObject()["move"].toArray()[0].toDouble();
            require(std::abs(bounds[0].toArray()[0].toDouble() - ((claw ? -64 : -40) + shift)) < .05, "Rendered slider placement is stale or incorrect");
            if (!claw) {
                require(std::abs(bounds[1].toArray()[0].toDouble() - (26 + shift)) < .05, "Rendered bolt tip is incorrect");
                const auto spring = parts[3].toObject(); const auto springBounds = genform::kernel::native::bounds(placed(cache.get(directory.filePath(spring["file"].toString())), spring));
                require(std::abs(springBounds[0].toArray()[0].toDouble() - (-17.995 + shift)) < .05, "Rendered return spring is not in the requested state");
            }
        }
        if (claw || (skye && options.values["inspect"].toBool())) {
            const auto report = assemblyReport(directory, parts, cache); const QString state = options.positional.value(0, "open"); saveObject(directory.filePath(claw ? "design_check_" + state + ".json" : "design_check_assembly.json"), report); require(report["counts"].toObject()["error"].toInt() == 0, "Native assembly design check failed");
        }
        const QString target = directory.filePath(frame.filename); image(parts, directory, cache, frame.view, target, frame.hidden, frame.section, frame.focus);
        const QString state = frame.assembly.contains("pressed") ? "pressed" : "open";
        if (!skye && (!claw || options.values["export"].toBool())) exportShape(compound(cache.rows(directory, parts)), directory.filePath((claw ? "claw_latch_" + options.positional.value(0,"open") : "button_latch_" + state) + ".step"));
        records.append(QJsonObject{{"assembly", frame.assembly}, {"view", frame.view}, {"section", frame.section}, {"focus_bounds_mm", frame.focus}, {"image", frame.filename}, {"sha256", sha256(target)}, {"parts", parts}, {"renderer", "native GenForm Viewport; offscreen CAD preview, not an application-window screenshot"}});
        QTextStream(stdout) << "CAPTURED " << target << '\n';
    }
    if (!skye && !claw && records.size() == 2) require(records[0].toObject()["sha256"] != records[1].toObject()["sha256"], "Open/pressed previews are identical");
    saveObject(directory.filePath("presentation.json"), {{"records", records}, {"limitations", QJsonArray{"Offscreen native CAD previews replace the old Python GUI automation.", "Application window chrome is not fabricated; geometry placement and state are checked directly.", "Current Viewport uses a uniform shaded material; per-part colours remain in the generated documents."}}}); return 0;
}
}
#endif
