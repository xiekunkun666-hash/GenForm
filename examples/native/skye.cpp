#include "geometry.hpp"
#include "genform/domain/geometry.hpp"
#include <QFile>
#include <QJsonDocument>
#include <QSaveFile>
#include <QTextStream>
#include <QDataStream>

namespace examples {
#ifdef GENFORM_HAS_OCCT
namespace {
const QString assembled = QString::fromUtf8("SKYE2_复现装配.gasm"), exploded = QString::fromUtf8("SKYE2_拆分查看.gasm"), unplugged = QString::fromUtf8("SKYE2_拔塞查看.gasm"), wholeName = QString::fromUtf8("SKYE2_整机复现");
const std::vector<std::pair<double,double>> mounts{{-13.6,-12.15148874334},{-22.63,-12.15148874334},{-13.6,11.64851125666},{-22.63,11.64851125666}};
const gp_Vec direction(.9999294285856908,0,-.011880145129336328);
const gp_Pnt mouth(-101.8214276355,-.269278046942,20.787740084594);

void copyVerified(const QString &source, const QString &target) { require(QFileInfo(source).isFile(), "Missing supplied source: " + source); require(QDir().mkpath(QFileInfo(target).absolutePath()), "Cannot create source-copy folder"); if (!QFileInfo::exists(target)) require(QFile::copy(source,target), "Cannot preserve source copy: " + target); require(sha256(source)==sha256(target), "Source-copy checksum mismatch: " + target); }
QString sourceFile(const QDir &source,const QString &name) { return source.filePath("SKYE2_"+name+"_R20.step"); }
QJsonObject rect(double width,double height) { return {{"type","rect"},{"cx",0},{"cy",0},{"w",width},{"h",height}}; }
QJsonObject circleShape(double radius) { return {{"type","circle"},{"cx",0},{"cy",0},{"r",radius}}; }

void profile(genform::Document &document,const gp_Pnt &origin,const gp_Vec &normal,const QJsonArray &shapes,double depth,const QString &name,const QString &operation="cut") {
    const QString plane=document.add("plane",{{"origin",QJsonArray{coordinates(origin)}},{"normal",QJsonArray{QJsonArray{normal.X(),normal.Y(),normal.Z()}}}},name+QString::fromUtf8(" · 基准面"));
    const QString sketch=document.add("sketch",{{"plane",plane},{"offset",0},{"shapes",shapes}},name+QString::fromUtf8(" · 轮廓"));
    document.add("extrude",{{"sketch",sketch},{"distance",depth},{"op",operation}},name);
}
void circle(genform::Document &document,const gp_Pnt &origin,const gp_Vec &normal,double radius,double depth,const QString &name,const QString &operation="cut") { profile(document,origin,normal,{circleShape(radius)},depth,name,operation); }
void rectangle(genform::Document &document,const gp_Pnt &origin,const gp_Vec &normal,double width,double height,double depth,const QString &name,const QString &operation="cut") { profile(document,origin,normal,{rect(width,height)},depth,name,operation); }

void envelope(const QJsonObject &measured,double tolerance) { const auto size=measured["size"].toArray(); const std::vector<double> expected{101.9,28.2,29.9}; require(size.size()==3,"Missing envelope"); for(int axis=0;axis<3;++axis) require(std::abs(size[axis].toDouble()-expected[axis])<=tolerance,"SKYE2 outer envelope changed"); }

void detailedGeometry(QMap<QString,genform::Document> &documents,const QDir &output) {
    for(const auto &stem:QStringList{"body","cover"}) {
        QJsonArray holes; for(const auto &[x,y]:mounts) holes.append(QJsonObject{{"type","circle"},{"cx",x},{"cy",y},{"r",2}});
        auto &document=documents[stem]; const auto sketch=document.add("sketch",{{"plane","XY"},{"offset",-4.1},{"shapes",holes}},QString::fromUtf8("官网 4×Ø4 · 四孔轮廓")); document.add("extrude",{{"sketch",sketch},{"distance",7.4},{"op","cut"}},QString::fromUtf8("官网 Ø4 安装通孔 · 全厚切除"));
    }
    auto &body=documents["body"]; auto &probe=documents["probe"];
    circle(body,{-12,-5.153858539,12.7},{0,1,0},3.2,1.4,QString::fromUtf8("照片补建 · 侧圆凹区 Ø6.4 深1.3（估算）"));
    circle(probe,mouth.Translated(direction*-.1),direction,2.3,63.1,QString::fromUtf8("前口阶梯孔道 · 内径Ø4.6延伸至后端（推定）"));
    rectangle(body,{-46.5,-5.207298,20.46},{0,1,0},2.6,2.6,1,QString::fromUtf8("照片补建 · 单侧方窗2.6×2.6（估算）"));
    circle(body,{-46.5,-5.207298,20.46},{0,1,0},.38,1.5,QString::fromUtf8("照片补建 · 方窗中心小凹孔Ø0.76（估算）"));
    circle(body,mouth.Translated(direction*50),direction,2.3,22,QString::fromUtf8("对接孔道 · 内径Ø4.6与参考壳腔连通（推定）"));
    const QJsonArray cavityPoints{QJsonArray{-36,3.2},QJsonArray{-4,3.2},QJsonArray{-4,8},QJsonArray{-10,15.5},QJsonArray{-18,20},QJsonArray{-34.2,21.8},QJsonArray{-36,21.5}};
    const auto cavity=body.add("sketch",{{"plane","XZ"},{"offset",-2.75},{"shapes",QJsonArray{QJsonObject{{"type","polygon"},{"points",cavityPoints}}}}},QString::fromUtf8("壳内参考腔 · 截面及壁厚为推定"));
    body.add("extrude",{{"sketch",cavity},{"distance",6},{"op","cut"}},QString::fromUtf8("壳内参考腔 · 宽6mm（推定）"));
    circle(body,{-1.8,-.25148874334,14},{0,0,-1},.5,5,QString::fromUtf8("官网俯视尾端小孔 · Ø1深至Z9（位置与深度估算）"));
    circle(body,{-12,-3.853858539,12.7},{0,1,0},2.2,1.3,QString::fromUtf8("硅胶塞下真实开孔 · 连通内腔Ø4.4（用户确认结构，孔径估算）"));
    genform::Document plug;
    circle(plug,{-12,-4.953858539,12.7},{0,1,0},2.82,1.2,QString::fromUtf8("硅胶塞帽 · Ø5.64止挡肩（外形估算）"),"add");
    circle(plug,{-12,-4.153858539,12.7},{0,1,0},2.18,1.3,QString::fromUtf8("硅胶塞插入段 · Ø4.36（参考配合，非密封认证）"),"add");
    rectangle(plug,{-12,-5,12.7},{0,1,0},4.2,.85,.6,QString::fromUtf8("照片补建 · 横向一字凹槽（估算）")); plug.props={{"color","#252A30"},{"material",QString::fromUtf8("硅胶")},{"reference",QJsonObject{{"density_hardness_grade",QString::fromUtf8("未确认，不使用通用橡胶密度代替")},{"hole_diameter_mm",4.4},{"stem_diameter_mm",4.36},{"fit_status",QString::fromUtf8("参考几何配合；未模拟弹性压缩或验证密封")}}}}; documents["side_plug"]=plug;
    genform::Document connector;
    rectangle(connector,{-23.35,-.17,-3.5},{0,0,1},9.4,5.8,4.7,QString::fromUtf8("底部四针连接器 · 参考包络9.4×5.8（估算）"),"add");
    rectangle(connector,{-23.35,-.17,-3.6},{0,0,1},7.6,3.6,3.3,QString::fromUtf8("连接器插口 · 外观参考（估算）"));
    const auto flange=connector.add("sketch",{{"plane","XY"},{"offset",-1.8},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",-23.35},{"cy",-.17},{"w",12.6},{"h",8.6}},QJsonObject{{"type","rect"},{"cx",-23.35},{"cy",-.17},{"w",7.6},{"h",3.6}}}}},QString::fromUtf8("连接器固定肩台 · 示意轮廓（推定）"));
    connector.add("extrude",{{"sketch",flange},{"distance",.9},{"op","add"}},QString::fromUtf8("连接器固定肩台 · 承托于底盖（推定）")); connector.add("import_step",{{"path",output.filePath("geometry/cover.step")},{"op","cut"}},QString::fromUtf8("固定肩台避让底盖 · 精确扣除交叠")); connector.props["color"]="#C8CAC4"; documents["connector"]=connector;
    for(int index=0;index<4;++index) { genform::Document contact; rectangle(contact,{-25.15+index*1.2,-.17,-2.8},{0,0,1},.35,.6,2.5,QString::fromUtf8("4针触点 %1 · 间距1.2（估算）").arg(index+1),"add"); contact.props["color"]="#C5AB72"; documents["contact_"+QString::number(index+1)]=contact; }
}

int generate(const Options &options,bool complete) {
    require(!options.output.isEmpty()&&options.values.contains("source"),"Specify --source <supplied STEP folder> --output <new folder>"); const QDir source(options.values["source"].toString()),output(options.output),copies(output.filePath("source"));
    require(QDir().mkpath(output.absolutePath()),"Cannot create output directory");
    const QStringList names{QString::fromUtf8("主体"),QString::fromUtf8("底盖"),QString::fromUtf8("探头"),QString::fromUtf8("整机")};
    for(const auto &name:names) copyVerified(sourceFile(source,name),sourceFile(copies,name));
    if(complete) { const QDir reference(options.values.value("reference").toString(QDir(sourceRoot()).filePath("build/skye2-reference"))); for(const auto &file:reference.entryList(QDir::Files)) copyVerified(reference.filePath(file),output.filePath("reference/"+file)); }
    QMap<QString,genform::Document> documents; const QStringList stems{"body","cover","probe"}; const QStringList colors{"#414850","#303740","#C2CAD2"};
    for(int index=0;index<3;++index) { genform::Document document; const QString input=sourceFile(copies,names[index]); const auto sourceShape=loadShape(input); const auto measurement=metrics(sourceShape); require(measurement["valid"].toBool()&&measurement["solids"].toInt()==1,"Supplied component must be one valid solid"); document.add("import_step",{{"path",input},{"op","add"}},"SKYE 2 "+names[index]+(complete?QString::fromUtf8(" · 不完整外形基体"):QString::fromUtf8(" · 原尺寸实体"))); document.props={{"color",complete?"#51585F":colors[index]},{"reference",QJsonObject{{"product","CUAV SKYE 2"},{"source_sha256",sha256(input)},{"method",complete?"Source STEP plus editable reference details":"Exact supplied STEP import"},{"units","mm"}}}}; documents[stems[index]]=document; }
    if(complete) detailedGeometry(documents,output);
    QStringList order=stems; if(complete) order<<"side_plug"<<"connector"<<"contact_1"<<"contact_2"<<"contact_3"<<"contact_4";
    QJsonArray parts,records; std::vector<TopoDS_Shape> shapes; QMap<QString,TopoDS_Shape> byStem; genform::Document whole;
    for(const auto &stem:order) {
        auto &document=documents[stem]; const auto shape=buildShape(document.features); const auto measurement=metrics(shape); require(measurement["valid"].toBool()&&measurement["solids"].toInt()==1,"Invalid completed component: "+stem); byStem[stem]=shape; shapes.push_back(shape);
        const QString file="skye2_"+stem+".gform"; document.save(output.filePath(file)); const QString geometry=output.filePath("geometry/"+stem+".step"); exportShape(shape,geometry);
        parts.append(QJsonObject{{"name",stem},{"file",file},{"move",QJsonArray{0,0,0}},{"turn",QJsonArray{0,0,0}}}); records.append(QJsonObject{{"name",stem},{"file",file},{"geometry",measurement},{"features",document.features.size()}});
        const auto identifier=whole.add("import_step",{{"path",geometry},{"op","add"}},stem); auto featureColors=whole.props["feature_colors"].toObject(); featureColors[identifier]=document.props["color"]; whole.props["feature_colors"]=featureColors;
        QTextStream(stdout)<<"BUILT "<<stem<<" ("<<document.features.size()<<" editable features)\n";
    }
    const auto assembledShape=compound(shapes); const auto measurement=metrics(assembledShape); envelope(measurement,complete?.001:1e-4);
    QJsonObject verification{{"product","CUAV SKYE 2"},{"parts",records},{"replica",measurement},{"identical_to_manufacturer",false},{"limitations",QJsonArray{"Original feature history unavailable.","Reference cavities, side opening/plug and connector details are estimates, not manufacturer drawings.","No electronics, firmware, pressure/heating/calibration, sealing or manufacturing tolerance certification."}}};
    if(!complete) {
        const auto reference=loadShape(sourceFile(copies,names[3])); const auto expected=metrics(reference); envelope(expected,1e-4); const auto referenceBox=expected["size"].toArray(),actualBox=measurement["size"].toArray();
        for(int axis=0;axis<3;++axis) require(std::abs(referenceBox[axis].toDouble()-actualBox[axis].toDouble())<1e-5,"Replica envelope differs from supplied assembly");
        require(std::abs(volume(reference)-volume(assembledShape))<1e-5,"Replica volume differs from supplied assembly");
        std::vector<QJsonObject> referenceParts,replicaParts; for(TopExp_Explorer explorer(reference,TopAbs_SOLID);explorer.More();explorer.Next()) referenceParts.push_back(metrics(explorer.Current())); for(const auto &shape:shapes) replicaParts.push_back(metrics(shape));
        auto compareFaces=[](const auto &first,const auto &second){return first["faces"].toInt()<second["faces"].toInt();}; std::sort(referenceParts.begin(),referenceParts.end(),compareFaces); std::sort(replicaParts.begin(),replicaParts.end(),compareFaces); require(referenceParts.size()==replicaParts.size(),"Replica component count differs");
        QJsonArray comparisons; for(size_t index=0;index<referenceParts.size();++index) { const auto first=referenceParts[index],second=replicaParts[index]; double error=0; for(const auto &side:QStringList{"bbox_min","bbox_max"}) for(int axis=0;axis<3;++axis) error=std::max(error,std::abs(first[side].toArray()[axis].toDouble()-second[side].toArray()[axis].toDouble())); const double relative=std::abs(first["volume"].toDouble()-second["volume"].toDouble())/first["volume"].toDouble(); require(error<=1e-5&&relative<=1e-5,"Replica component comparison failed"); comparisons.append(QJsonObject{{"faces",second["faces"]},{"bbox_max_error_mm",error},{"relative_volume_error",relative}}); } verification["component_comparisons"]=comparisons; verification["reference"]=expected;
    } else {
        int samples=0; for(const auto &[x,y]:mounts) for(int altitude=0;altitude<8;++altitude) for(double radius:{0.,1.3,1.9}) for(int index=0;index<8;++index) { const double angle=index*2*std::acos(-1.)/8; const gp_Pnt position(x+radius*std::cos(angle),y+radius*std::sin(angle),-3.7+6.7*altitude/7); require(!occupied(byStem["body"],position)&&!occupied(byStem["cover"],position),"Completed mounting hole obstructed"); ++samples; }
        QJsonArray forward; for(double distance:{2.,5.,10.,18.,30.,45.,51.,54.,60.,65.,70.}) { const auto position=mouth.Translated(direction*distance); require(!occupied(byStem["body"],position)&&!occupied(byStem["probe"],position),"Front reference cavity blocked"); forward.append(QJsonObject{{"distance_from_mouth_mm",distance},{"state","outside"}}); } verification["mounting_hole_samples"]=samples; verification["forward_checks"]=forward;
    }
    QJsonObject assembly{{"format","genform-assembly"},{"version",1},{"parts",parts}}; saveObject(output.filePath(assembled),assembly);
    auto displaced=parts; for(qsizetype index=0;index<displaced.size();++index) { auto part=displaced[index].toObject(); if(index==1) part["move"]=QJsonArray{0,0,-25}; else if(index==2) part["move"]=QJsonArray{-30,0,8}; else if(complete&&index==3) part["move"]=QJsonArray{0,-17,0}; else if(complete&&index>3) part["move"]=QJsonArray{0,0,-38}; displaced[index]=part; } auto split=assembly; split["parts"]=displaced; saveObject(output.filePath(exploded),split);
    if(complete) { displaced=parts; auto plug=displaced[3].toObject(); plug["move"]=QJsonArray{0,-17,0}; displaced[3]=plug; split=assembly; split["parts"]=displaced; saveObject(output.filePath(unplugged),split); }
    whole.save(output.filePath(wholeName+".gform")); exportShape(assembledShape,output.filePath(wholeName+".step")); exportShape(assembledShape,output.filePath(wholeName+".stl")); saveObject(output.filePath("verification.json"),verification);
    const QString readme=QString::fromUtf8("# SKYE 2 原生参考模型\n\n原始STEP通过SHA-256核对并保存在 source/。分件为可编辑gform，装配坐标保留。\n新增孔道、硅胶塞、四针连接器及固定肩台属于明确标注的参考估算；不是厂家内部气路或制造图复原。\n外形核对101.9×28.2×29.9 mm；不代表密封、疲劳、压力、加热或电子功能验证。\n运行 check_skye2_reference 与 verify_skye2_reference 生成设计及出口孔道验证报告。\n"); QSaveFile file(output.filePath("README.md")); require(file.open(QIODevice::WriteOnly),"Cannot write reference README"); require(file.write(readme.toUtf8())>0&&file.commit(),"Cannot save reference README"); return 0;
}

int check(const Options &options) {
    const QDir directory(options.output.isEmpty()?options.positional.value(0):options.output); require(directory.exists(),"Specify generated reference folder"); const auto assembly=loadObject(directory.filePath(assembled)); QJsonArray summary; genform::Session session;
    for(const auto &value:assembly["parts"].toArray()) { const auto row=value.toObject(); call(session,"open_document",{{"path",directory.filePath(row["file"].toString())}}); auto report=call(session,"check_design"); report["file"]=row["file"]; saveObject(directory.filePath("design_check_"+QFileInfo(row["file"].toString()).completeBaseName()+".json"),report); summary.append(QJsonObject{{"name",row["name"]},{"counts",report["counts"]}}); }
    ShapeCache cache; const auto report = assemblyReport(directory, assembly["parts"].toArray(), cache);
    const auto counts=report["counts"].toObject(); saveObject(directory.filePath("design_check_assembly.json"),report); saveObject(directory.filePath("design_check_summary.json"),{{"assembly",counts},{"parts",summary},{"identical_to_manufacturer",false},{"reason","Public reference lacks internal channels, tolerances, hole depths and connector details"}}); return 0;
}

int verifyReference(const Options &options) {
    const QDir directory(options.output.isEmpty()?options.positional.value(0):options.output); const auto shape=loadShape(directory.filePath(wholeName+".step")); require(BRepCheck_Analyzer(shape).IsValid(),"Exported STEP is invalid"); int samples=0; QJsonArray voids,holes;
    for(const auto &[x,y]:mounts) { for(int altitude=0;altitude<9;++altitude) for(int index=0;index<12;++index) { const double angle=index*2*std::acos(-1.)/12; require(!occupied(shape,{x+1.95*std::cos(angle),y+1.95*std::sin(angle),-3.7+6.7*altitude/8}),"Exported mounting hole blocked"); ++samples; } const double material=intersectionVolume(shape,{x,y,-4},{0,0,1},1.95,7.2); require(material<=1e-5,"Mounting hole contains material"); voids.append(QJsonObject{{"feature","mount"},{"center_xy",QJsonArray{x,y}},{"test_radius_mm",1.95},{"length_mm",7.2},{"intersecting_material_mm3",material}}); }
    const gp_Vec sideways(0,1,0),up=direction.Crossed(sideways);
    for(int distanceIndex=0;distanceIndex<80;++distanceIndex) for(int angleIndex=0;angleIndex<8;++angleIndex) { const double distance=1.1+68.9*distanceIndex/79,angle=angleIndex*2*std::acos(-1.)/8; const gp_Pnt position=mouth.Translated(direction*distance+sideways*(1.9*std::cos(angle))+up*(1.9*std::sin(angle))); require(!occupied(shape,position),"Exported reference bore obstructed"); ++samples; }
    const double bore=intersectionVolume(shape,mouth.Translated(direction*1.1),gp_Dir(direction),1.9,68.9); require(bore<=1e-5,"Reference bore contains material"); voids.append(QJsonObject{{"feature","reference_bore_not_manufacturer_verified"},{"intersecting_material_mm3",bore}});
    const auto plugDocument=loadObject(directory.filePath("skye2_side_plug.gform")); if(plugDocument["props"].toObject()["material"]==QString::fromUtf8("硅胶")) {
        const auto body=loadShape(directory.filePath("geometry/body.step")),plug=loadShape(directory.filePath("geometry/side_plug.step")); const double blocked=intersectionVolume(body,{-12,-5.2,12.7},{0,1,0},2.1,3.2); require(blocked<=1e-5,"Unplugged access hole is blocked"); for(int index=0;index<15;++index) require(!occupied(body,{-12,-4.9+2.8*index/14,12.7}),"Side access hole is not open"); require(occupied(body,{-12,3.2,12.7}),"Access cut removed the opposite wall"); require(occupied(plug,{-12,-3.2,12.7}),"Plug insertion stem is missing"); voids.append(QJsonObject{{"feature","silicone_plug_removed_access_hole"},{"intersecting_material_mm3",blocked},{"opposite_wall_preserved",true},{"plug_stem_present",true}});
    }
    struct Test { QString name; gp_Pnt position; bool expected; };
    const std::vector<Test> tests{{"near_tip_positive_y",{-99.3887170887,3.7,20.809276715806},false},{"near_tip_negative_y",{-99.3887170887,-4.2,20.809276715806},false},{"near_tip_blind_hole_partition_positive",{-99.3887170887,3,20.809276715806},true},{"near_tip_blind_hole_partition_negative",{-99.3887170887,-3.5,20.809276715806},true},{"existing_top_hole",{-18.9,-.25148874334,24.8},false},{"new_tail_hole",{-1.8,-.25148874334,10.5},false},{"single_side_window",{-46.5,-4.3,20.46},false},{"side_plug_slot",{-12,-4.8,12.7},false},{"side_plug_slot_floor",{-12,-4.3,12.7},true}};
    for(const auto &test:tests) { const bool actual=occupied(shape,test.position); require(actual==test.expected,"Local hole verification failed: "+test.name); holes.append(QJsonObject{{"feature",test.name},{"point_mm",coordinates(test.position)},{"contains_material",actual}}); }
    const auto mesh=loadShape(directory.filePath(wholeName+".stl")); envelope(metrics(mesh),.001); const auto assembly=loadObject(directory.filePath("design_check_assembly.json")),summary=loadObject(directory.filePath("design_check_summary.json")); require(assembly["counts"].toObject()["error"].toInt()==0,"Native assembly design errors remain"); for(const auto &value:summary["parts"].toArray()) require(value.toObject()["counts"].toObject()["error"].toInt()==0,"Native part design errors remain");
    saveObject(directory.filePath("export_verification.json"),{{"exported_step_valid",true},{"exported_geometry_hole_samples",samples},{"void_intersection_tests",voids},{"visible_hole_point_tests",holes},{"stl_size_mm",metrics(mesh)["size"]},{"native_assembly_errors",0},{"step_sha256",sha256(directory.filePath(wholeName+".step"))},{"limitations",QJsonArray{"Finite geometry checks only; no equivalence to manufacturer internal design, elastic seal, electronics, pressure, heating or calibration certification."}}});
    QTextStream(stdout)<<"PASS: "<<samples<<" exported geometry void samples and local material checks\n"; return 0;
}
}
#endif

int skye(const Options &options) {
#ifndef GENFORM_HAS_OCCT
    Q_UNUSED(options); require(false,"SKYE2 native examples require the OpenCascade C++ SDK; no Python fallback"); return 1;
#else
    if(options.name=="build_skye2_replica") return generate(options,false);
    if(options.name=="complete_skye2_reference") return generate(options,true);
    if(options.name=="check_skye2_reference") return check(options);
    if(options.name=="verify_skye2_reference") return verifyReference(options);
    Options presentation=options; if(presentation.output.isEmpty()) presentation.output=presentation.positional.value(0); return presentAssembly(presentation);
#endif
}
}
