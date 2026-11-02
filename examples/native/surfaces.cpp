#include "geometry.hpp"
#ifdef GENFORM_HAS_OCCT
#include <BRepIntCurveSurface_Inter.hxx>
#include <gp_Lin.hxx>
#include <QFile>
#include <QTextStream>
#include <algorithm>

namespace examples {
namespace {
QJsonObject feature(const QString &command, const QString &alias, QJsonObject arguments) { return {{"cmd", command}, {"as", alias}, {"args", arguments}}; }
QJsonObject profile(const QString &alias, const QString &plane, double offset, const QJsonArray &shapes) { return feature("sketch", alias, {{"name", "911_" + alias}, {"plane", plane}, {"offset", offset}, {"shapes", shapes}}); }
QJsonObject extrusion(const QString &alias, const QString &name, const QString &source, double distance) { return feature("extrude", alias, {{"name", name}, {"sketch", "$" + source}, {"distance", distance}}); }
QJsonObject circle(double x, double y, double radius) { return {{"type", "circle"}, {"cx", x}, {"cy", y}, {"r", radius}}; }
QJsonObject rectangle(double x, double y, double width, double height) { return {{"type", "rect"}, {"cx", x}, {"cy", y}, {"w", width}, {"h", height}}; }
QJsonArray shell(const QJsonArray &outer, const QJsonArray &inner) {
    QJsonArray reverse; for (qsizetype index = inner.size(); index > 0; --index) reverse.append(inner[index - 1]);
    const auto first = outer.first().toArray(), last = outer.last().toArray(), innerFirst = inner.first().toArray(), innerLast = inner.last().toArray();
    return {QJsonObject{{"type", "spline"}, {"points", outer}}, QJsonObject{{"type", "line"}, {"x1", last[0]}, {"y1", last[1]}, {"x2", innerLast[0]}, {"y2", innerLast[1]}}, QJsonObject{{"type", "spline"}, {"points", reverse}}, QJsonObject{{"type", "line"}, {"x1", innerFirst[0]}, {"y1", innerFirst[1]}, {"x2", first[0]}, {"y2", first[1]}}};
}

double hit(const TopoDS_Shape &shape, double station, double cross, bool vertical) {
    BRepIntCurveSurface_Inter intersector; intersector.Init(shape, gp_Lin(vertical ? gp_Pnt(station, cross, 2000) : gp_Pnt(station, 1400, cross), vertical ? gp_Dir(0, 0, -1) : gp_Dir(0, -1, 0)), 1e-7);
    double maximum = -1e300; while (intersector.More()) { maximum = std::max(maximum, vertical ? intersector.Pnt().Z() : intersector.Pnt().Y()); intersector.Next(); }
    require(maximum > -1e290, "Body surface ray missed at " + QString::number(station) + ", " + QString::number(cross)); return maximum;
}

TopoDS_Shape bodyPrefix(const QString &source) {
    genform::Document document; document.open(source); int stop = -1;
    for (qsizetype index = 0; index < document.features.size(); ++index) if (document.features[index].toObject()["id"] == "f37") stop = static_cast<int>(index + 1);
    require(stop > 0, "Vehicle body prefix f37 not present; refusing a different surface"); return buildShape(document.features, stop);
}

void sample(const QString &source, const QDir &output, bool glazing) {
    const auto shape = bodyPrefix(source); QJsonObject result;
    auto rounded = [](double value) { return std::round(value * 1e5) / 1e5; };
    if (glazing) {
        const QMap<QString, std::vector<std::vector<double>>> groups{
            {"windshield", {{-815,565},{-745,560},{-650,551},{-540,535},{-430,516},{-330,496},{-245,480}}},
            {"rear_screen", {{720,482},{820,507},{940,536},{1060,554},{1180,572},{1300,574},{1380,558}}},
            {"door_window", {{-650,865,885},{-540,864,997},{-390,865,1096},{-220,869,1172},{0,876,1210},{235,883,1209},{460,891,1192}}},
            {"quarter_window", {{535,894,1172},{665,897,1122},{820,900,1046},{960,900,967},{1070,900,910}}}};
        for (auto group = groups.begin(); group != groups.end(); ++group) {
            const bool screen = group.key() == "windshield" || group.key() == "rear_screen"; QJsonArray rows;
            for (const auto &station : group.value()) { QJsonArray values; const double low = screen ? -station[1] : station[1], high = screen ? station[1] : station[2];
                for (int index = 0; index < 9; ++index) { const double cross = low + (high - low) * index / 8; const double height = hit(shape, station[0], cross, screen); values.append(screen ? QJsonArray{rounded(cross), rounded(height)} : QJsonArray{rounded(height), rounded(cross)}); }
                rows.append(QJsonObject{{"station", station[0]}, {"values", values}});
            }
            result[group.key()] = rows;
        }
    } else {
        auto probe = [&](double station, double cross, bool vertical, double offset) { const double value = hit(shape, station, cross, vertical) + offset; return vertical ? QJsonArray{station, cross, value} : QJsonArray{station, value, cross}; };
        const std::vector<std::pair<double,double>> door{{-748,845},{-781,720},{-787,530},{-775,340},{-690,238},{-380,220},{25,220},{335,238},{473,330},{495,550},{492,750},{485,869},{150,856},{-240,848}};
        const std::vector<std::pair<double,double>> bonnet{{-2025,0},{-1980,-270},{-1810,-408},{-1460,-465},{-1090,-505},{-925,-487},{-902,-250},{-900,0},{-902,250},{-925,487},{-1090,505},{-1460,465},{-1810,408},{-1980,270}};
        QJsonArray doors, bonnets, vent;
        for (const auto &[station, cross] : door) doors.append(probe(station, cross, false, 1.2)); for (const auto &[station, cross] : bonnet) bonnets.append(probe(station, cross, true, 1.2));
        for (int index = 0; index < 11; ++index) { QJsonArray rows; for (double cross : {-480., 0., 480.}) rows.append(probe(1480 + index * 30, cross, true, 2.5)); vent.append(rows); }
        result = {{"door", doors}, {"bonnet", bonnets}, {"handle", probe(350, 757, false, 3)}, {"fuel", probe(-1100, 750, false, 2)}, {"vent", vent}};
    }
    saveObject(output.filePath(glazing ? "surface_samples.json" : "trim_samples.json"), result);
}

void glazingSteps(const QJsonObject &data, const QString &name, QJsonArray &steps, QJsonObject &colors) {
    const auto rows = data[name].toArray(); require(!rows.isEmpty(), "Missing surface samples for " + name); const bool screen = name == "windshield" || name == "rear_screen";
    for (const auto &layer : QStringList{"frame", "glass"}) {
        const bool glass = layer == "glass"; QJsonArray references;
        for (qsizetype index = 0; index < rows.size(); ++index) { const auto row = rows[index].toObject(); auto values = row["values"].toArray(); if (glass) { values.removeFirst(); values.removeLast(); } QJsonArray outer, inner;
            for (const auto &value : values) { const auto coordinate = value.toArray(); outer.append(screen ? QJsonArray{coordinate[0], coordinate[1].toDouble() + (glass ? 7 : 4)} : QJsonArray{coordinate[0].toDouble() + (glass ? 7 : 4), coordinate[1]}); inner.append(screen ? QJsonArray{coordinate[0], coordinate[1].toDouble() - 9} : QJsonArray{coordinate[0].toDouble() - 9, coordinate[1]}); }
            double station = row["station"].toDouble(); if (glass && (index == 0 || index == rows.size() - 1)) station += index == 0 ? 20 : -20;
            const QString alias = name + '_' + layer + '_' + QString::number(index); steps.append(profile(alias, "YZ", station, shell(outer, inner))); references.append('$' + alias);
        }
        const QString alias = name + '_' + layer; steps.append(feature("loft", alias, {{"name", "911_" + alias}, {"sketches", references}, {"ruled", false}})); colors[alias] = glass ? "#263F50" : "#141B23";
        if (!screen) { steps.append(feature("mirror", alias + "_left", {{"name", "911_" + alias + "_left"}, {"plane", "XZ"}, {"features", QJsonArray{'$' + alias}}})); colors[alias + "_left"] = colors[alias]; }
    }
}

double interpolate(const QJsonArray &values, double cross, int dimension) {
    require(values.size() >= 2, "Need at least two interpolation samples");
    for (qsizetype index = 1; index < values.size(); ++index) { const auto first = values[index - 1].toArray(), second = values[index].toArray(); if (cross <= second[dimension].toDouble() || index == values.size() - 1) { const double fraction = (cross - first[dimension].toDouble()) / (second[dimension].toDouble() - first[dimension].toDouble()); return first[1 - dimension].toDouble() + fraction * (second[1 - dimension].toDouble() - first[1 - dimension].toDouble()); } }
    throw genform::Error("Interpolation failed");
}

void refineSteps(genform::Document &document, const QString &mode, const QJsonObject &samples, QJsonArray &steps) {
    auto edit = [&](const QJsonObject &source, const QJsonObject &params) { steps.append(feature("edit_feature", source["name"].toString(), {{"id", source["id"]}, {"params", params}})); };
    for (const auto &value : document.features) { const auto source = value.toObject(); const QString name = source["name"].toString(); const auto params = source["params"].toObject();
        if ((mode == "tires" || mode == "all") && name.endsWith("_tire_section")) {
            const bool front = name.contains("_front_"); const double centreX = front ? -1290 : 1160, centreY = (front ? 773 : 755) * (name.contains("_left_") ? -1 : 1), radius = front ? 340 : 358, rim = front ? 254 : 267, half = front ? 122.5 : 152.5;
            QJsonArray points; for (const auto &[radial, width] : std::vector<std::pair<double,double>>{{rim-2,-half+22},{rim+12,-half},{radius-38,-half},{radius-10,-half+12},{radius,-half+36},{radius,half-36},{radius-10,half-12},{radius-38,half},{rim+12,half},{rim-2,half-22}}) points.append(QJsonArray{centreX + radial, centreY + width});
            edit(source, {{"shapes", QJsonArray{QJsonObject{{"type", "polygon"}, {"points", points}}}}});
        }
        if (mode == "wheels" || mode == "all") {
            if (name.endsWith("_disc_profile")) { auto shape = params["shapes"].toArray().first().toObject(); shape["r"] = 175; edit(source, {{"shapes", QJsonArray{shape}}}); }
            if (name.endsWith("_brake_disc")) edit(source, {{"distance", std::copysign(name.contains("_front_") ? 34. : 28., params["distance"].toDouble())}});
            if (name.endsWith("_cap_profile")) { const auto cap = params["shapes"].toArray().first().toObject(); QJsonArray shapes{cap}; for (int index = 0; index < 5; ++index) { const double angle = (index * 72 + 18) * std::acos(-1.0) / 180; shapes.append(QJsonObject{{"type", "ngon"}, {"cx", cap["cx"].toDouble() + 65 * std::cos(angle)}, {"cy", cap["cy"].toDouble() + 65 * std::sin(angle)}, {"r", 9.815}, {"sides", 6}, {"angle", 30}}); } edit(source, {{"shapes", shapes}}); }
        }
    }
    if (mode == "glazing" || mode == "all") for (auto group = samples.begin(); group != samples.end(); ++group) {
        const bool screen = group.key() == "windshield" || group.key() == "rear_screen"; int index = 0;
        for (const auto &value : group.value().toArray()) { const auto values = value.toObject()["values"].toArray(); const int dimension = screen ? 0 : 1; const double low = values.first().toArray()[dimension].toDouble(), high = values.last().toArray()[dimension].toDouble(), inset = std::min(20., (high - low) * .16); QJsonArray outer, inner;
            for (int sampleIndex = 0; sampleIndex < 9; ++sampleIndex) { const double cross = low + inset + (high - low - 2 * inset) * sampleIndex / 8, height = interpolate(values, cross, dimension); outer.append(screen ? QJsonArray{cross,height+7} : QJsonArray{height+7,cross}); inner.append(screen ? QJsonArray{cross,height-9} : QJsonArray{height-9,cross}); }
            edit(document.find("911_" + group.key() + "_glass_" + QString::number(index++)), {{"shapes", shell(outer, inner)}});
        }
    }
}

void trimSteps(const QJsonObject &data, const QString &mode, QJsonArray &steps, QJsonObject &colors) {
    if (mode == "seams") {
        for (const auto &key : QStringList{"door", "bonnet"}) { const auto points = data[key].toArray(); require(points.size() >= 3, "Missing trim seam points"); const auto next = points[1].toArray(), last = points.last().toArray(); QJsonArray tangent; for (int axis = 0; axis < 3; ++axis) tangent.append(next[axis].toDouble() - last[axis].toDouble());
            steps.append(feature("sketch3d", key + "_path", {{"name", "911_" + key + "_panel_gap_path"}, {"points", points}, {"closed", true}, {"kind", "spline"}}));
            steps.append(feature("plane", key + "_plane", {{"name", "911_" + key + "_gap_profile_datum"}, {"origin", QJsonArray{points[0]}}, {"normal", QJsonArray{tangent}}}));
            steps.append(profile(key + "_profile", '$' + key + "_plane", 0, {circle(0,0,2)})); steps.append(feature("sweep", key, {{"name", "911_" + key + "_panel_gap"}, {"sketch", '$' + key + "_profile"}, {"path", '$' + key + "_path"}})); colors[key] = "#303C47";
            if (key == "door") { steps.append(feature("mirror", "door_left", {{"name", "911_door_panel_gap_left"}, {"plane", "XZ"}, {"features", QJsonArray{"$door"}}})); colors["door_left"] = "#303C47"; }
        }
    } else if (mode == "handles") {
        const auto handle = data["handle"].toArray(), fuel = data["fuel"].toArray(); require(handle.size() == 3 && fuel.size() == 3, "Missing trim handle/fuel samples");
        for (int sign : {-1,1}) { const QString side = sign < 0 ? "left" : "right", alias = side + "_handle_profile"; steps.append(profile(alias, "XZ", -sign * handle[1].toDouble(), {QJsonObject{{"type","slot"},{"x1",handle[0].toDouble()-60},{"y1",handle[2]},{"x2",handle[0].toDouble()+60},{"y2",handle[2]},{"w",21}}})); steps.append(extrusion("handle_"+side,"911_flush_door_handle_"+side,alias,sign*10)); colors["handle_"+side]="#748694"; }
        steps.append(feature("plane","fuel_plane",{{"name","911_fuel_cap_datum"},{"origin",QJsonArray{fuel}},{"normal",QJsonArray{QJsonArray{0,.75,.66}}}})); steps.append(profile("fuel_profile","$fuel_plane",0,{circle(0,0,66),circle(0,0,63.5)})); steps.append(extrusion("fuel","911_fuel_filler_outline","fuel_profile",-8)); colors["fuel"]="#34414D";
    } else if (mode == "vents") {
        const auto vents=data["vent"].toArray(); require(vents.size()==11,"Need 11 engine-cover samples"); QJsonArray references;
        for(int index:{0,3,6,10}) { const auto row=vents[index].toArray(); QJsonArray outer,inner; for(const auto &value:row) { const auto coordinate=value.toArray(); outer.append(QJsonArray{coordinate[1],coordinate[2]}); inner.append(QJsonArray{coordinate[1],coordinate[2].toDouble()-8}); } const QString alias="vent_section_"+QString::number(index); steps.append(profile(alias,"YZ",row[0].toArray()[0].toDouble(),shell(outer,inner))); references.append('$'+alias); }
        steps.append(feature("loft","vent_panel",{{"name","911_engine_cover_black_grille"},{"sketches",references}})); colors["vent_panel"]="#121A22";
        for(int index=0;index<9;++index) { const auto row=vents[index+1].toArray(); const double left=row[0].toArray()[2].toDouble()+3,centre=row[1].toArray()[2].toDouble()+3,right=row[2].toArray()[2].toDouble()+3; const QString alias="louvre_profile_"+QString::number(index); steps.append(profile(alias,"YZ",row[0].toArray()[0].toDouble(),{QJsonObject{{"type","polygon"},{"points",QJsonArray{QJsonArray{-470,left},QJsonArray{0,centre},QJsonArray{470,right},QJsonArray{470,right-5},QJsonArray{0,centre-5},QJsonArray{-470,left-5}}}}})); const QString name="louvre_"+QString::number(index); steps.append(extrusion(name,"911_engine_grille_louvre_"+QString::number(index),alias,8)); colors[name]="#48545F"; }
    } else require(false,"Unknown trim phase: "+mode);
}

void panelLines(const QJsonObject &data,QJsonArray &steps,QJsonObject &colors) {
    const auto door=data["door"].toArray(); require(door.size()>=12,"Missing panel line samples");
    for(const auto &name:QStringList{"door_front_seam","door_sill_seam","door_rear_seam","bonnet_seam"}) {
        std::vector<QJsonArray> points; const bool bonnet=name=="bonnet_seam",sill=name.endsWith("sill_seam");
        if(bonnet) { for(const auto &value:data["bonnet"].toArray()) if(value.toArray()[1].toDouble()>=250) points.push_back(value.toArray()); std::sort(points.begin(),points.end(),[](const auto &first,const auto &second){return first[0].toDouble()<second[0].toDouble();}); }
        else { const int first=name=="door_front_seam"?0:sill?4:8,last=name=="door_front_seam"?5:sill?9:12; for(int index=first;index<last;++index) points.push_back(door[index].toArray()); if(name=="door_front_seam") std::sort(points.begin(),points.end(),[](const auto &first,const auto &second){return first[2].toDouble()<second[2].toDouble();}); }
        require(points.size()>=2,"Insufficient panel line stations"); QJsonArray references; int index=0;
        for(const auto &coordinate:points) { const QString alias=(bonnet?"bonnet_edge":name)+'_'+QString::number(index++); const double station=coordinate[0].toDouble(),width=coordinate[1].toDouble(),height=coordinate[2].toDouble(); const QString plane=bonnet||sill?"YZ":"XY"; const double offset=bonnet||sill?station:height; const auto shape=bonnet?rectangle(width,height-1.8,3,6.4):sill?rectangle(width-1.8,height,6.4,3):rectangle(station,width-1.8,3,6.4); steps.append(profile(alias,plane,offset,{shape})); references.append('$'+alias); }
        steps.append(feature("loft",name,{{"name",bonnet?"911_bonnet_edge_seam":"911_"+name},{"sketches",references},{"ruled",false}})); steps.append(feature("mirror",name+"_left",{{"name",bonnet?"911_bonnet_edge_seam_left":"911_"+name+"_left"},{"plane","XZ"},{"features",QJsonArray{'$'+name}}})); colors[name]="#34414C"; colors[name+"_left"]="#34414C";
    }
}
}

int surfaceExamples(const Options &options) {
    require(!options.output.isEmpty(),"Specify --output for samples and the edited vehicle"); QDir directory(options.output); require(QDir().mkpath(directory.absolutePath()),"Cannot create output directory");
    const QString source=options.values.value("source").toString(QDir(sourceRoot()).filePath("models/porsche_911_992/porsche_911_992.gform")),mode=options.positional.value(0,"all");
    require(options.positional.size() <= 1, "Only one vehicle phase is accepted");
    if (options.name.endsWith("refine")) require(QStringList{"all", "tires", "wheels", "glazing"}.contains(mode), "Unknown refinement mode: " + mode);
    if (options.name.endsWith("panel_lines")) require(mode == "all", "panel_lines has no phase argument");
    if(mode=="sample") { require(options.name.endsWith("glazing")||options.name.endsWith("trim"),"Sample phase belongs to glazing or trim"); sample(source,directory,options.name.endsWith("glazing")); return 0; }
    genform::Session session; call(session,"open_document",{{"path",source}}); QJsonArray steps; QJsonObject colors;
    const QDir sampleDirectory(options.values.value("samples").toString(directory.absolutePath()));
    if(options.name.endsWith("glazing")) glazingSteps(loadObject(sampleDirectory.filePath("surface_samples.json")),mode,steps,colors);
    else if(options.name.endsWith("refine")) refineSteps(session.document,mode,(mode=="glazing"||mode=="all")?loadObject(sampleDirectory.filePath("surface_samples.json")):QJsonObject{},steps);
    else if(options.name.endsWith("panel_lines")) panelLines(loadObject(sampleDirectory.filePath("trim_samples.json")),steps,colors);
    else trimSteps(loadObject(sampleDirectory.filePath("trim_samples.json")),mode,steps,colors);
    require(!steps.isEmpty(),"No matching vehicle features for "+mode);
    if(!options.name.endsWith("refine")) for(const auto &value:steps) for(const auto &existing:session.document.features) require(existing.toObject()["name"]!=value.toObject()["args"].toObject()["name"],"Geometry already exists; no duplicate stage is sent");
    const double before = session.builder.query("properties")["volume"].toDouble();
    const auto answer=call(session,"batch",{{"steps",steps}}); validModel(session.builder.query("model")); const auto ids=answer["ids"].toArray();
    if (!options.name.endsWith("refine")) require(!before || session.builder.query("properties")["volume"].toDouble() >= before * .98, "Unexpected additive stage volume decrease");
    require(ids.size() == steps.size(), "Batch did not return one ID per command");
    for(qsizetype index=0;index<steps.size();++index) { const QString alias=steps[index].toObject()["as"].toString(); if(colors.contains(alias)&&index<ids.size()) call(session,"set_appearance",{{"features",QJsonArray{ids[index]}},{"color",colors[alias]}}); }
    call(session,"save_document",{{"path",directory.filePath("porsche_911_992.gform")}}); QTextStream(stdout)<<"SAVED native vehicle stage: "<<steps.size()<<" commands\n"; return 0;
}
}
#endif
