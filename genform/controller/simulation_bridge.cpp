#include "genform/controller/controller.hpp"
#include "genform/assembly/engine.hpp"
#include "genform/domain/geometry.hpp"
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QSaveFile>
#include <QUrl>
#include <algorithm>
#include <cmath>

namespace genform::controller {
namespace {
QString localFile(const QString &value) { const QUrl url(value); return url.isLocalFile()?url.toLocalFile():value; }
double numeric(const QVariant &value) {
    bool valid=false; const double number=value.toDouble(&valid);
    if (!valid || !std::isfinite(number)) throw Error(QStringLiteral("请输入有限数值。"));
    return number;
}
QJsonArray triple() { return {0,0,0}; }
QJsonObject menu(const QString &id,const QString &title,const QString &icon) { return {{"id",id},{"title",title},{"tip",title},{"icon",icon},{"enabled",true}}; }
QString shown(const QJsonValue &value) {
    if (value.isDouble()) return QString::number(value.toDouble(),'g',7);
    if (value.isBool()) return value.toBool()?QStringLiteral("是"):QStringLiteral("否");
    if (value.isString()) return value.toString();
    if (value.isArray()) return QString::fromUtf8(QJsonDocument(value.toArray()).toJson(QJsonDocument::Compact));
    if (value.isObject()) return QString::fromUtf8(QJsonDocument(value.toObject()).toJson(QJsonDocument::Compact));
    return QStringLiteral("未提供");
}
}

SimulationBridge::SimulationBridge(Session *session,QObject *parent) : QObject(parent),session_(session) {
    parameters_={{"force",QVariantList{0.0,0.0,-1000.0}},{"speed",20.0},{"density",1.225},{"cd",1.0},{"axis","X"}};
    motionTimer_.setInterval(100);
    connect(&motionTimer_,&QTimer::timeout,this,[this] {
        const double length=pose_.value("length").toDouble(4);
        seconds_+=motionTimer_.interval()/1000.0;
        if (seconds_>length) { seconds_=length; motionTimer_.stop(); }
        refreshAssembly();
    });
    connect(session_,&Session::changed,this,[this] { Q_EMIT changed(); });
}

QJsonObject SimulationBridge::query(const QString &what,QJsonObject arguments) {
    arguments["what"]=what;
    try {
        const auto response=session_->execute("query",arguments);
        if (response.contains("error") || (response.contains("ok") && !response.value("ok").toBool() && !response.contains("steps"))) throw Error(response.value("error").toString(QStringLiteral("查询失败：%1").arg(what)));
        const auto result=response.value("result").isObject()?response.value("result").toObject():response;
        if (result.contains("error")) throw Error(result.value("error").toString());
        error_.clear(); return result;
    } catch (const std::exception &exception) {
        error_=QString::fromUtf8(exception.what()); Q_EMIT notice(error_); Q_EMIT changed();
        return {{"ok",false},{"error",error_}};
    }
}

QVariantMap SimulationBridge::staticState() const {
    return {{"fixed",fixed_.toVariantList()},{"loaded",loaded_.toVariantList()},{"force",parameters_.value("force")},{"result",result_},{"error",error_}};
}
QVariantList SimulationBridge::resultRows() const {
    QVariantList result;
    const QJsonObject data=QJsonObject::fromVariantMap(result_);
    const auto append=[&](const QString &label,const QString &value,bool strong=false,bool bad=false) { result.append(QVariantMap{{"label",label},{"value",value},{"strong",strong},{"bad",bad}}); };
    if (data.value("clashes").isArray()) {
        const auto clashes=data.value("clashes").toArray(); append(QStringLiteral("干涉检查"),clashes.isEmpty()?QStringLiteral("没有干涉"):QStringLiteral("%1 处干涉").arg(clashes.size()),true,!clashes.isEmpty());
        for (const auto &value : clashes) { const auto clash=value.toObject(); QStringList names; for (const auto &name : clash.value("names").toArray()) names.append(name.toString()); append(names.join(" ↔ "),QStringLiteral("%1 mm³").arg(clash.value("volume").toDouble(),0,'g',7),false,true); }
    }
    if (data.value("steps").isArray()) {
        for (const auto &value : data.value("steps").toArray()) { const auto step=value.toObject(); QStringList directions; for (const auto &direction : step.value("directions").toArray()) directions.append(direction.toString()); const bool valid=step.value("ok").toBool(); append(step.value("name").toString(),valid?(step.value("index").toInt()==0?QStringLiteral("基座"):QStringLiteral("装入方向：%1").arg(directions.join(" / "))):QStringLiteral("未找到无干涉装入路径"),false,!valid); }
    }
    const QMap<QString,QPair<QString,QString>> metrics{{"area",{QStringLiteral("迎风面积"),"mm²"}},{"force",{QStringLiteral("阻力"),"N"}},{"pressure",{QStringLiteral("动压"),"Pa"}},{"power",{QStringLiteral("克服阻力功率"),"W"}},
        {"max_stress",{QStringLiteral("最大应力"),"MPa"}},{"max_displacement",{QStringLiteral("最大位移"),"mm"}},{"safety",{QStringLiteral("安全系数"),""}},{"mass_g",{QStringLiteral("总质量"),"g"}},{"total",{QStringLiteral("总尺寸"),"mm"}}};
    const QSet<QString> bulky{"mesh","meshes","stress","move","parts","matrices","normals","verts","tris","clashes","steps"};
    for (auto iterator=data.begin();iterator!=data.end();++iterator) {
        if (bulky.contains(iterator.key()) || iterator.key()=="limitations" || iterator.key()=="ok") continue;
        if (metrics.contains(iterator.key()) && iterator.value().isDouble()) { const auto metric=metrics.value(iterator.key()); append(metric.first,shown(iterator.value())+(metric.second.isEmpty()?QString():" "+metric.second),true,iterator.key()=="safety" && iterator.value().toDouble()<1); continue; }
        QString text=shown(iterator.value()); if (text.size()>160) text=text.left(157)+"...";
        append(iterator.key(),text);
    }
    return result;
}
QVariantList SimulationBridge::componentRows() const {
    QVariantList rows; const auto parts=assembly_.value("parts").toArray(),resolved=pose_.value("parts").toArray();
    for (qsizetype index=0;index<parts.size();++index) {
        auto part=parts[index].toObject(); const auto path=part.value("path").toString();
        const auto name=part.value("name").toString(QFileInfo(path).completeBaseName());
        int jointIndex=-1;
        const auto joints=assembly_.value("joints").toArray();
        for (qsizetype number=0;number<joints.size();++number) if (joints[number].toObject().value("parts").toArray().contains(int(index))) { jointIndex=number; break; }
        QJsonArray mated;
        for (const auto &value : assembly_.value("mates").toArray()) {
            const auto mate=value.toObject(); if (mate.value("part").toInt(-1)!=index) continue;
            if (mate.value("kind")=="fix") mated={0,1,2};
            else { const int axis=QStringLiteral("XYZ").indexOf(mate.value("axis").toString("Z")); for (int dimension=0;dimension<3;++dimension) if (axis>=0 && (mate.value("kind")=="coaxial"?dimension!=axis:dimension==axis) && !mated.contains(dimension)) mated.append(dimension); }
        }
        auto formula=part.value("formula").toObject(); if (!formula.contains("move")) formula["move"]=QJsonArray{"","",""}; if (!formula.contains("turn")) formula["turn"]=QJsonArray{"","",""};
        part["index"]=int(index); part["label"]=name; part["name"]=name; part["file"]=path; part["selected"]=picked_==index;
        part["hidden"]=hiddenParts_.contains(index); part["joint"]=jointIndex; part["bad"]=!path.isEmpty() && !QFileInfo::exists(path);
        const auto position=index<resolved.size()?resolved[index].toObject():part;
        part["move"]=position.value("move").toArray(triple()); part["turn"]=position.value("turn").toArray(triple());
        part["formula"]=formula; part["mated"]=mated; part["fixed"]=index==0; part["mirror"]=part.value("mirror").toBool(); part["kindColor"]="";
        part["note"]=part.value("bad").toBool()?QStringLiteral("零件文件不存在"):QString();
        QStringList status,clashes; bool failed=part.value("bad").toBool(); if (failed) status.append(part.value("note").toString());
        for (const auto &value : result_.value("clashes").toList()) { const auto clash=value.toMap(); const int first=clash.value("a",-1).toInt(),second=clash.value("b",-1).toInt(); if (first!=index && second!=index) continue; const int other=first==index?second:first; const auto otherName=other>=0 && other<parts.size()?parts[other].toObject().value("name").toString():QString::number(other); clashes.append(otherName); status.append(QStringLiteral("和“%1”干涉").arg(otherName)); failed=true; }
        for (const auto &value : result_.value("steps").toList()) { const auto step=value.toMap(); if (step.value("index",-1).toInt()!=index) continue; QStringList directions; for (const auto &direction : step.value("directions").toList()) directions.append(direction.toString()); const bool valid=step.value("ok").toBool(); status.append(valid?(index==0?QStringLiteral("基座"):QStringLiteral("装入方向：%1").arg(directions.join(" / "))):QStringLiteral("未找到无干涉装入路径")); failed|=!valid; }
        part["status"]=status.join(QStringLiteral("；")); part["state"]=failed?"bad":status.isEmpty()?"":"good"; part["bad"]=failed; part["clash"]=QJsonArray::fromStringList(clashes); part["tint"]=part.value("color").toString();
        for (const auto &key : {QString("material"),QString("kind"),QString("process"),QString("spec")}) if (!part.contains(key)) part[key]="";
        part["unit"]=part.value("unit").toDouble(); rows.append(part.toVariantMap());
    }
    return rows;
}
QVariantList SimulationBridge::jointRows() const {
    QVariantList result; const auto joints=pose_.value("joints").toArray(assembly_.value("joints").toArray());
    for (qsizetype index=0;index<joints.size();++index) {
        auto joint=joints[index].toObject(); const bool sliding=joint.value("kind")=="slide";
        joint["index"]=int(index); joint["name"]=joint.value("name").toString(QStringLiteral("运动副 %1").arg(index+1)); joint["selected"]=joint_==index;
        joint["min"]=joint.value("min").toDouble(); joint["max"]=joint.value("max").toDouble(90); joint["value"]=joint.value("value").toDouble();
        joint["unit"]=sliding?"mm":"°"; joint["spin"]=joint.value("speed").toDouble()!=0; joint["speed"]=joint.value("speed").toDouble();
        joint["on"]=joint.value("on").toInt(-1); const int parent=joint.value("on").toInt(-1); joint["onName"]=parent>=0 && parent<joints.size()?joints[parent].toObject().value("name").toString():QString(); joint["adding"]=pickingJoint_==index;
        const auto parts=assembly_.value("parts").toArray(); const int base=joint.value("base").toInt(0); joint["baseIndex"]=base; joint["base"]=base>=0 && base<parts.size()?parts[base].toObject().value("name").toString():QStringLiteral("固定坐标系");
        const auto origin=joint.value("origin").toArray(triple()),axis=joint.value("axis").toArray(QJsonArray{0,0,1});
        for (int dimension=0;dimension<3;++dimension) { joint[QString("origin%1").arg(dimension)]=origin[dimension]; joint[QString("axis%1").arg(dimension)]=axis[dimension]; }
        QStringList names; for (const auto &part : joint.value("parts").toArray()) { const int number=part.toInt(-1); if (number>=0 && number<parts.size()) names.append(parts[number].toObject().value("name").toString()); }
        joint["partIndices"]=joint.value("parts"); joint["parts"]=QJsonArray::fromStringList(names); result.append(joint.toVariantMap());
    }
    return result;
}
QVariant SimulationBridge::value(const QString &key) const {
    if (key=="mode") return mode_;
    if (key=="assembly") return assembly_.value("parts").toArray().toVariantList();
    if (key=="assemblyName") return path_.isEmpty()?QStringLiteral("装配体1"):QFileInfo(path_).completeBaseName();
    if (key=="components") return componentRows();
    if (key=="joints") return jointRows();
    if (key=="mates") { QVariantList rows; int index=0; const auto parts=assembly_.value("parts").toArray(); for (const auto &value : assembly_.value("mates").toArray()) { auto mate=value.toObject(); mate["index"]=index++; const int target=mate.value("to").toInt(-1); mate["toName"]=target>=0 && target<parts.size()?parts[target].toObject().value("name").toString():QString(); mate["title"]=mate.value("kind")=="coaxial"?QStringLiteral("同轴"):QStringLiteral("距离"); mate["value"]=shown(mate.value("value")); rows.append(mate.toVariantMap()); } return rows; }
    if (key=="standardCatalog") return domain::standard_part_catalog().toVariantList();
    if (key=="motion") return QVariantMap{{"playing",motionTimer_.isActive()},{"count",assembly_.value("joints").toArray().size()},{"time",seconds_},{"length",pose_.value("length").toDouble(4)},{"duration",pose_.value("length").toDouble(4)},{"enabled",!assembly_.value("joints").toArray().isEmpty()}};
    if (key=="live") return QVariantMap{{"on",false},{"running",false},{"enabled",false},{"clashes",0},{"gaps",0},{"done",0},{"total",0},{"count",0},{"busy",false},{"error",QStringLiteral("自动实时检查尚未接入；请手动执行干涉检查。")}};
    if (key=="params") { QVariantList rows; const auto params=assembly_.value("params").toObject(); for (auto iterator=params.begin();iterator!=params.end();++iterator) rows.append(QVariantMap{{"name",iterator.key()},{"text",shown(iterator.value())},{"value",resolvedParameters_.contains(iterator.key())?shown(resolvedParameters_.value(iterator.key())):QStringLiteral("未提供解析值")}}); return rows; }
    if (key=="paramError") return error_;
    if (key=="picked") return picked_;
    if (key=="pickedJoint") return joint_;
    if (key=="isolatedName") { const auto parts=assembly_.value("parts").toArray(); return isolatedPart_>=0 && isolatedPart_<parts.size()?parts[isolatedPart_].toObject().value("name").toString():QString(); }
    if (key=="drag") return QVariantMap{{"speed",parameters_.value("speed")},{"density",parameters_.value("density")},{"cd",parameters_.value("cd")},{"result",result_},{"error",error_}};
    if (key=="state") {
        QVariantList notes; for (const auto &note : QJsonObject::fromVariantMap(result_).value("limitations").toArray()) notes.append(note.toString());
        if (result_.value("approximate").toBool()) notes.prepend(QStringLiteral("该结果为近似计算，不是工程认证或连续碰撞证明。"));
        return QVariantMap{{"mode",mode_},{"pinned",mode_=="assembly"},{"busy",session_->busy},{"running",session_->busy},{"error",error_},{"result",result_},{"fields",QVariantList{}},
            {"static",staticState()},{"drag",value("drag")},{"parts",componentRows()},{"components",componentRows()},{"joints",jointRows()},{"mates",value("mates")},
            {"fixed",fixed_.size()},{"loaded",loaded_.size()},{"force",parameters_.value("force")},{"axis",parameters_.value("axis")},
            {"speed",parameters_.value("speed")},{"density",parameters_.value("density")},{"cd",parameters_.value("cd")},{"quality",quality_},
            {"qualities",QVariantList{QVariantMap{{"id","coarse"},{"title",QStringLiteral("粗")}},QVariantMap{{"id","medium"},{"title",QStringLiteral("中")}},QVariantMap{{"id","fine"},{"title",QStringLiteral("细")}}}},
            {"rows",resultRows()},{"notes",notes},{"legend",""},{"params",value("params")}};
    }
    return QString();
}
void SimulationBridge::unsupported(const QString &command) { error_=QStringLiteral("仿真/装配功能尚未接入：%1").arg(command); Q_EMIT notice(error_); Q_EMIT changed(); }
void SimulationBridge::open(const QString &mode) {
    if (!QStringList{"static","drag","assembly"}.contains(mode)) { unsupported(mode); return; }
    mode_=mode; error_.clear(); result_={};
    if (mode=="assembly" && assembly_.isEmpty()) {
        QJsonArray parts;
        if (session_->model.value("has_body").toBool()) parts.append(QJsonObject{{"name",QFileInfo(session_->document.path).completeBaseName()},{"path",""},{"features",session_->document.features},{"props",session_->document.props},{"move",triple()},{"turn",triple()}});
        if (!commitAssembly({{"format","genform-assembly"},{"version",1},{"parts",parts}})) { mode_.clear(); Q_EMIT changed(); return; }
    }
    if (mode=="assembly") { pickingJoint_=-1; setAssemblySelection(-1,-1); refreshAssembly(); Q_EMIT assemblyActivated(); }
    Q_EMIT changed();
}
void SimulationBridge::close() { motionTimer_.stop(); if (mode_=="assembly") { pickingJoint_=-1; setAssemblySelection(-1,-1); } mode_.clear(); Q_EMIT changed(); }
void SimulationBridge::setParam(const QString &key,const QVariant &value) {
    auto data=assembly_; auto params=data.value("params").toObject(); if (value.toString().trimmed().isEmpty()) params.remove(key); else params[key]=QJsonValue::fromVariant(value); data["params"]=params; commitAssembly(data);
}
void SimulationBridge::setForce(const QString &key,const QVariant &value) {
    try { bool valid=false; const int index=key.toInt(&valid); if (!valid || index<0 || index>2) throw Error(QStringLiteral("力方向索引必须是 0、1、2。")); auto force=parameters_.value("force").toList(); force[index]=numeric(value); parameters_["force"]=force; result_={}; Q_EMIT changed(); }
    catch (const std::exception &exception) { error_=QString::fromUtf8(exception.what()); Q_EMIT notice(error_); Q_EMIT changed(); }
}
void SimulationBridge::setDrag(const QString &key,const QVariant &value) {
    try {
        if (key=="axis") { if (!QStringList{"X","Y","Z"}.contains(value.toString())) throw Error(QStringLiteral("方向必须是 X、Y 或 Z。")); parameters_[key]=value; }
        else if (QStringList{"speed","density","cd"}.contains(key)) { const double number=numeric(value); if (number<=0) throw Error(QStringLiteral("风阻参数必须大于零。")); parameters_[key]=number; }
        else throw Error(QStringLiteral("未知风阻参数：%1").arg(key));
        result_={}; Q_EMIT changed();
    } catch (const std::exception &exception) { error_=QString::fromUtf8(exception.what()); Q_EMIT notice(error_); Q_EMIT changed(); }
}
void SimulationBridge::setQuality(const QString &quality) { if (!QStringList{"coarse","medium","fine"}.contains(quality)) { unsupported("quality:"+quality); return; } quality_=quality; result_={}; Q_EMIT changed(); }
void SimulationBridge::takeFaces(const QString &role) {
    const auto faces=session_->selection.value("faces").toArray();
    if (faces.isEmpty()) { error_=QStringLiteral("请先在模型上选择面，再指定固定面或受力面。 "); Q_EMIT notice(error_); Q_EMIT changed(); return; }
    if (role=="fixed") fixed_=faces; else if (role=="loaded") loaded_=faces; else { unsupported("faces:"+role); return; }
    result_={}; Q_EMIT changed();
}
void SimulationBridge::showFaces(const QString &role) { if (role!="fixed" && role!="loaded") { unsupported("faces:"+role); return; } session_->selection={{"faces",role=="fixed"?fixed_:loaded_},{"edges",QJsonArray{}}}; Q_EMIT session_->changed(); }
void SimulationBridge::run(const QString &mode) {
    QJsonObject arguments;
    if (mode_=="assembly") arguments=assembly_;
    if (mode=="static") {
        const auto material=domain::mechanics(session_->document.props.value("material").toString());
        if (!material) { error_=QStringLiteral("请先给零件指定具有弹性参数的材料。 "); Q_EMIT notice(error_); Q_EMIT changed(); return; }
        arguments["force"]=QJsonValue::fromVariant(parameters_.value("force")); arguments["fixed"]=fixed_; arguments["loaded"]=loaded_; arguments["quality"]=quality_;
        arguments["young"]=material->x(); arguments["poisson"]=material->y(); arguments["yield"]=material->z();
    } else if (mode=="drag") {
        arguments["speed"]=parameters_.value("speed").toDouble(); arguments["density"]=parameters_.value("density").toDouble(); arguments["cd"]=parameters_.value("cd").toDouble();
        const auto axis=parameters_.value("axis").toString(); arguments["direction"]=QJsonArray{axis=="X"?1:0,axis=="Y"?1:0,axis=="Z"?1:0};
    }
    const auto result=query(mode,arguments); if (!result.contains("error")) result_=result.toVariantMap(); else result_={}; Q_EMIT changed();
}
void SimulationBridge::runStatic() { run("static"); }
void SimulationBridge::runDrag() { run("drag"); }

bool SimulationBridge::commitAssembly(const QJsonObject &data,bool checkpoint,bool resetSelection) {
    QJsonObject parameters;
    try { parameters=assembly::resolveAssembly(data,QFileInfo(path_).absolutePath()).value("parameter_values").toObject(); }
    catch (const std::exception &exception) { error_=QString::fromUtf8(exception.what()); Q_EMIT notice(error_); Q_EMIT changed(); return false; }
    const auto validated=query("pose",data); if (validated.contains("error")) return false;
    if (checkpoint && data!=assembly_) { undo_.append(assembly_.isEmpty()?QJsonObject{{"format","genform-assembly"},{"version",1},{"parts",QJsonArray{}}}:assembly_); redo_.clear(); while (undo_.size()>100) undo_.removeFirst(); dirty_=true; }
    assembly_=data; pose_=validated; resolvedParameters_=parameters; result_={}; seconds_=0; timeline_=false; motionTimer_.stop(); if (resetSelection) { pickingJoint_=-1; setAssemblySelection(-1,-1); } refreshAssembly(); Q_EMIT changed(); return true;
}
bool SimulationBridge::beginAssembly() {
    if (!commitAssembly({{"format","genform-assembly"},{"version",1},{"parts",QJsonArray{}},{"joints",QJsonArray{}},{"mates",QJsonArray{}}},false,true)) return false;
    path_.clear(); savedAssembly_=assembly_; dirty_=false; undo_.clear(); redo_.clear(); mode_="assembly"; hiddenParts_.clear(); beforeIsolation_.clear(); isolatedPart_=-1; Q_EMIT assemblyActivated(); Q_EMIT changed(); return true;
}
bool SimulationBridge::openAssembly(const QString &where) {
    QFile file(localFile(where)); if (!file.open(QIODevice::ReadOnly)) { error_=file.errorString(); Q_EMIT notice(error_); return false; }
    QJsonParseError parse; auto data=QJsonDocument::fromJson(file.readAll(),&parse).object();
    if (parse.error!=QJsonParseError::NoError || data.value("format")!="genform-assembly" || !data.value("parts").isArray()) { error_=QStringLiteral("不是有效的 GenForm 装配体文档。 "); Q_EMIT notice(error_); return false; }
    auto parts=data.value("parts").toArray(); const QDir base(QFileInfo(file).absolutePath());
    for (qsizetype index=0;index<parts.size();++index) { auto part=parts[index].toObject(); const auto path=part.value("path").toString(part.value("file").toString()); if (!path.isEmpty()) part["path"]=QFileInfo(path).isAbsolute()?path:base.absoluteFilePath(path); part.remove("file"); parts[index]=part; }
    data["parts"]=parts; if (!commitAssembly(data,false,true)) return false;
    path_=QFileInfo(file).absoluteFilePath(); savedAssembly_=assembly_; mode_="assembly"; dirty_=false; undo_.clear(); redo_.clear(); hiddenParts_.clear(); beforeIsolation_.clear(); isolatedPart_=-1; refreshAssembly(); Q_EMIT assemblyActivated(); Q_EMIT changed(); return true;
}
bool SimulationBridge::saveAssembly(const QString &where) {
    QString path=localFile(where); if (path.isEmpty()) path=path_; if (path.isEmpty()) { unsupported("save:missing path"); return false; }
    if (!path.endsWith(".gasm",Qt::CaseInsensitive)) path+=".gasm";
    QSaveFile file(path); if (!file.open(QIODevice::WriteOnly)) { error_=file.errorString(); Q_EMIT notice(error_); return false; }
    auto data=assembly_; auto parts=data.value("parts").toArray(); const QDir directory(QFileInfo(path).absolutePath());
    for (qsizetype index=0;index<parts.size();++index) { auto part=parts[index].toObject(); const auto source=part.value("path").toString(); if (!source.isEmpty()) part["file"]=directory.relativeFilePath(source); else if (!part.value("features").isArray()) { file.cancelWriting(); error_=QStringLiteral("嵌入零件缺少可保存的特征数据。 "); Q_EMIT notice(error_); return false; } if (!source.isEmpty()) part.remove("path"); parts[index]=part; }
    data["parts"]=parts; const auto content=QJsonDocument(data).toJson(QJsonDocument::Indented);
    if (file.write(content)!=content.size() || !file.commit()) { error_=file.errorString(); Q_EMIT notice(error_); return false; }
    path_=QFileInfo(path).absoluteFilePath(); savedAssembly_=assembly_; dirty_=false; Q_EMIT notice(QStringLiteral("已保存：%1").arg(path_)); Q_EMIT changed(); return true;
}
void SimulationBridge::undoAssembly() { if (undo_.isEmpty()) return; const auto target=undo_.last(),before=assembly_; if (commitAssembly(target,false,true)) { redo_.append(before); undo_.removeLast(); dirty_=assembly_!=savedAssembly_; Q_EMIT changed(); } }
void SimulationBridge::redoAssembly() { if (redo_.isEmpty()) return; const auto target=redo_.last(); const auto before=assembly_; if (commitAssembly(target,false,true)) { undo_.append(before); redo_.removeLast(); dirty_=assembly_!=savedAssembly_; Q_EMIT changed(); } }

void SimulationBridge::refreshAssembly() {
    if (assembly_.isEmpty()) return;
    auto arguments=assembly_; if (timeline_ && !assembly_.value("joints").toArray().isEmpty()) arguments["seconds"]=seconds_;
    const auto positioned=query("pose",arguments); if (positioned.contains("error")) { display_={}; motionTimer_.stop(); Q_EMIT modelChanged(display_); return; } pose_=positioned;
    if (assembly_.value("parts").toArray().isEmpty()) { display_={}; Q_EMIT modelChanged(display_); return; }
    const auto response=query("meshes",arguments);
    if (response.contains("error")) { display_={}; motionTimer_.stop(); Q_EMIT modelChanged(display_); return; }
    if (!response.value("meshes").isArray()) { display_={}; motionTimer_.stop(); Q_EMIT modelChanged(display_); unsupported("meshes:后端没有返回 meshes 数组"); return; }
    QJsonArray verts,normals,tris,faces,triFace,edges,segments,segmentEdge,vertices; int partIndex=0; double volume=0;
    for (const auto &entry : response.value("meshes").toArray()) {
        const auto mesh=entry.toObject(); const int owner=partIndex++;
        if (hiddenParts_.contains(owner)) continue;
        if (mesh.contains("error")) { error_=mesh.value("error").toString(); Q_EMIT notice(error_); continue; }
        const int vertexBase=verts.size(); const auto feature="part:"+QString::number(owner); QHash<int,int> faceIds,edgeIds;
        for (const auto &point : mesh.value("verts").toArray()) verts.append(point);
        for (const auto &normal : mesh.value("normals").toArray()) normals.append(normal);
        for (const auto &point : mesh.value("vertices").toArray()) vertices.append(point);
        for (const auto &value : mesh.value("tris").toArray()) { const auto triplet=value.toArray(); if (triplet.size()==3) tris.append(QJsonArray{triplet[0].toInt()+vertexBase,triplet[1].toInt()+vertexBase,triplet[2].toInt()+vertexBase}); }
        for (const auto &value : mesh.value("edges").toArray()) { auto edge=value.toObject(); const int original=edge.value("id").toInt(-1); edgeIds[original]=edges.size(); edge["source_id"]=original; edge["id"]=edges.size(); edge["feature"]=feature; edges.append(edge); }
        for (const auto &value : mesh.value("faces").toArray()) { auto face=value.toObject(); const int original=face.value("id").toInt(-1); faceIds[original]=faces.size(); face["source_id"]=original; face["id"]=faces.size(); face["feature"]=feature; QJsonArray around; for (const auto &edge : face.value("edges").toArray()) if (edgeIds.contains(edge.toInt(-1))) around.append(edgeIds.value(edge.toInt())); face["edges"]=around; faces.append(face); }
        for (const auto &value : mesh.value("tri_face").toArray()) triFace.append(faceIds.value(value.toInt(-1),-1));
        for (const auto &value : mesh.value("segments").toArray()) segments.append(value);
        for (const auto &value : mesh.value("segment_edge").toArray()) segmentEdge.append(edgeIds.value(value.toInt(-1),-1));
        volume+=mesh.value("props").toObject().value("volume").toDouble();
    }
    display_={{"verts",verts},{"normals",normals},{"tris",tris},{"faces",faces},{"tri_face",triFace},{"edges",edges},{"segments",segments},{"segment_edge",segmentEdge},{"vertices",vertices},{"has_body",!tris.isEmpty()},{"props",QJsonObject{{"volume",volume}}},{"sketches",QJsonObject{}},{"status",QJsonObject{}}};
    Q_EMIT modelChanged(display_); Q_EMIT changed();
}

QJsonObject SimulationBridge::measureSelection(const QJsonObject &selection) {
    QSet<int> selected;
    const auto add=[&](const QString &feature) { if (feature.startsWith("part:")) { bool valid=false; const int index=feature.mid(5).toInt(&valid); if (valid) selected.insert(index); } };
    add(selection.value("feature").toString());
    for (const auto &kind : {QString("faces"),QString("edges")}) {
        for (const auto &identifier : selection.value(kind).toArray()) {
            for (const auto &element : display_.value(kind).toArray()) {
                const auto item=element.toObject(); if (item.value("id")==identifier) { add(item.value("feature").toString()); break; }
            }
        }
    }
    if (selected.isEmpty()) return {{"items",QJsonArray{}}};
    if (selected.size()>2) return {{"error",QStringLiteral("装配测量请只选择一个或两个零件；当前测量零件整体尺寸、面积、体积及最短间距，不是局部面边尺寸。")}};
    const auto parts=pose_.value("parts").toArray(); QJsonArray chosen; QList<int> indices=selected.values(); std::sort(indices.begin(),indices.end());
    for (const int index : indices) {
        if (index<0 || index>=parts.size()) return {{"error",QStringLiteral("装配测量选择已失效，请重新选择零件。")}};
        auto part=parts[index].toObject(); part.remove("formula"); chosen.append(part);
    }
    return query("measure_parts",{{"parts",chosen},{"params",assembly_.value("params")},{"posed",true}});
}

void SimulationBridge::addParts(const QVariantList &paths) {
    if (assembly_.isEmpty() && !beginAssembly()) return;
    auto data=assembly_; auto parts=data.value("parts").toArray();
    for (const auto &value : paths) {
        const auto path=QFileInfo(localFile(value.toString())).absoluteFilePath();
        if (!QFileInfo::exists(path) || !QStringList{"gform","step","stp","stl","brep"}.contains(QFileInfo(path).suffix().toLower())) { error_=QStringLiteral("不支持或不存在的零件文件：%1").arg(path); Q_EMIT notice(error_); return; }
        parts.append(QJsonObject{{"path",path},{"name",QFileInfo(path).completeBaseName()},{"move",triple()},{"turn",triple()},{"mirror",false}});
    }
    data["parts"]=parts; commitAssembly(data);
}
void SimulationBridge::addStandardPart(const QString &kind,const QString &series,const QString &size,const QString &length) {
    if (path_.isEmpty()) { unsupported("standard:请先保存装配体"); return; }
    try {
        const auto part=domain::make_standard_part(kind,size,length.trimmed().isEmpty()?std::nullopt:std::optional<double>(numeric(length)),series);
        QDir directory(QFileInfo(path_).absolutePath()); if (!directory.mkpath("standard")) throw Error(QStringLiteral("不能创建 standard 目录。"));
        const auto path=directory.filePath("standard/"+part.first);
        if (!QFileInfo::exists(path)) { QSaveFile file(path); if (!file.open(QIODevice::WriteOnly)) throw Error(file.errorString()); const auto bytes=QJsonDocument(part.second).toJson(QJsonDocument::Indented); if (file.write(bytes)!=bytes.size() || !file.commit()) throw Error(file.errorString()); }
        addParts({path});
    } catch (const std::exception &exception) { error_=QString::fromUtf8(exception.what()); Q_EMIT notice(error_); Q_EMIT changed(); }
}
void SimulationBridge::renamePart(int index,const QString &name) { auto data=assembly_; auto parts=data.value("parts").toArray(); const auto trimmed=name.trimmed(); if (index<0 || index>=parts.size() || trimmed.isEmpty()) { unsupported("rename:无效零件或空名称"); return; } auto part=parts[index].toObject(); if (part.value("name").toString()==trimmed) return; part["name"]=trimmed; parts[index]=part; data["parts"]=parts; commitAssembly(data); }
void SimulationBridge::setAssemblySelection(int part,int joint) {
    picked_=part; joint_=joint;
    session_->selection={{"feature",part<0?QString():"part:"+QString::number(part)},{"faces",QJsonArray{}},{"edges",QJsonArray{}}};
    Q_EMIT session_->changed(); Q_EMIT changed();
}
void SimulationBridge::selectPart(int index) {
    if (index<-1 || index>=assembly_.value("parts").toArray().size()) return;
    if (pickingJoint_>=0 && index>=0) {
        auto data=assembly_; auto joints=data.value("joints").toArray();
        if (pickingJoint_<joints.size()) { auto joint=joints[pickingJoint_].toObject(); auto parts=joint.value("parts").toArray(); const auto found=std::find(parts.begin(),parts.end(),QJsonValue(index)); if (found==parts.end()) parts.append(index); else parts.removeAt(std::distance(parts.begin(),found)); joint["parts"]=parts; joints[pickingJoint_]=joint; data["joints"]=joints; commitAssembly(data); return; }
    }
    pickingJoint_=-1; setAssemblySelection(index,-1);
}
void SimulationBridge::openPart(int index) {
    const auto parts=assembly_.value("parts").toArray(); if (index<0 || index>=parts.size()) return;
    const auto path=parts[index].toObject().value("path").toString(); if (path.isEmpty()) { unsupported("open embedded part"); return; }
    if (dirty_ || (mode_=="assembly" && session_->document.dirty)) { error_=QStringLiteral("装配体有未保存的修改：请先保存装配体，再打开零件。"); Q_EMIT notice(error_); Q_EMIT changed(); return; }
    if (!QFileInfo::exists(path)) { error_=QStringLiteral("零件文件不存在：%1").arg(path); Q_EMIT notice(error_); Q_EMIT changed(); return; }
    Q_EMIT openPartRequested(path);
}
QVariantList SimulationBridge::partMenu(int index) const {
    const auto parts=assembly_.value("parts").toArray();
    if (index==-1) return QJsonArray{menu("show_all",QStringLiteral("显示所有零部件"),"eye"),menu("hide_all",QStringLiteral("隐藏所有零部件"),"eye_off")}.toVariantList();
    if (index<0 || index>=parts.size()) return {};
    QJsonArray result; if (!parts[index].toObject().value("path").toString().isEmpty()) result.append(menu("open",QStringLiteral("打开零件"),"open"));
    result.append(menu("edit",QStringLiteral("编辑位置"),"move")); result.append(menu("rename",QStringLiteral("重命名"),"text"));
    result.append(menu("mirror",parts[index].toObject().value("mirror").toBool()?QStringLiteral("取消镜像"):QStringLiteral("镜像"),"mirror"));
    result.append(menu("hide",hiddenParts_.contains(index)?QStringLiteral("显示"):QStringLiteral("隐藏"),hiddenParts_.contains(index)?"eye":"eye_off"));
    result.append(menu("isolate",isolatedPart_==index?QStringLiteral("退出孤立"):QStringLiteral("孤立"),"isolate"));
    if (index>0) result.append(menu("up",QStringLiteral("往前挪（早一步装）"),"up"));
    if (index+1<parts.size()) result.append(menu("down",QStringLiteral("往后挪（晚一步装）"),"down"));
    result.append(menu("delete",QStringLiteral("删除"),"trash")); return result.toVariantList();
}
QVariantList SimulationBridge::partContext(int index) const {
    auto result=partMenu(index); for (qsizetype offset=result.size();offset>0;--offset) if (QStringList{"up","down","delete"}.contains(result[offset-1].toMap().value("id").toString())) result.removeAt(offset-1); return result;
}
void SimulationBridge::partAction(int index,const QString &action) {
    const int count=assembly_.value("parts").toArray().size();
    if (action=="show_all" || action=="hide_all") { isolatedPart_=-1; beforeIsolation_.clear(); hiddenParts_.clear(); if (action=="hide_all") for (int number=0;number<count;++number) hiddenParts_.insert(number); refreshAssembly(); return; }
    if (index<0 || index>=count) return;
    if (action=="open") openPart(index); else if (action=="edit") { selectPart(index); Q_EMIT editRequested(index); }
    else if (action=="rename") { if (index>=0 && index<assembly_.value("parts").toArray().size()) Q_EMIT renameRequested(index); }
    else if (action=="delete") removePart(index); else if (action=="mirror") mirrorPart(index);
    else if (action=="hide") { if (isolatedPart_>=0) { hiddenParts_=beforeIsolation_; beforeIsolation_.clear(); isolatedPart_=-1; } if (hiddenParts_.contains(index)) hiddenParts_.remove(index); else hiddenParts_.insert(index); refreshAssembly(); }
    else if (action=="isolate") { if (isolatedPart_==index) { exitIsolation(); return; } if (isolatedPart_<0) beforeIsolation_=hiddenParts_; isolatedPart_=index; hiddenParts_.clear(); for (int number=0;number<count;++number) if (number!=index) hiddenParts_.insert(number); refreshAssembly(); }
    else if (action=="up" || action=="down") shiftPart(index,action=="up"?-1:1);
    else unsupported("part action:"+action);
}
void SimulationBridge::mirrorPart(int index) { auto data=assembly_; auto parts=data.value("parts").toArray(); if (index<0 || index>=parts.size()) return; auto part=parts[index].toObject(); part["mirror"]=!part.value("mirror").toBool(); parts[index]=part; data["parts"]=parts; commitAssembly(data); }
void SimulationBridge::placePart(int index,const QString &field,int axis,const QVariant &value) {
    auto data=assembly_; auto parts=data.value("parts").toArray(); if (index<0 || index>=parts.size() || axis<0 || axis>2 || !QStringList{"move","turn"}.contains(field)) { unsupported("placement:无效坐标"); return; }
    auto part=parts[index].toObject(); auto coordinates=part.value(field).toArray(triple()); auto formula=part.value("formula").toObject(); auto expressions=formula.value(field).toArray(QJsonArray{"","",""});
    bool valid=false; const double number=value.toDouble(&valid);
    if (valid && std::isfinite(number)) { coordinates[axis]=number; expressions[axis]=""; } else { const auto expression=value.toString().trimmed(); if (expression.isEmpty()) { unsupported("placement:空表达式"); return; } expressions[axis]=expression; }
    part[field]=coordinates; formula[field]=expressions; part["formula"]=formula; parts[index]=part; data["parts"]=parts; commitAssembly(data);
}
void SimulationBridge::removePart(int index) {
    auto data=assembly_; auto parts=data.value("parts").toArray(); if (index<0 || index>=parts.size()) return; parts.removeAt(index); data["parts"]=parts;
    auto joints=data.value("joints").toArray(); for (qsizetype number=0;number<joints.size();++number) { auto joint=joints[number].toObject(); QJsonArray references; for (const auto &value : joint.value("parts").toArray()) { const int part=value.toInt(); if (part!=index) references.append(part>index?part-1:part); } joint["parts"]=references; const int base=joint.value("base").toInt(0); joint["base"]=base==index?-1:base>index?base-1:base; joints[number]=joint; } data["joints"]=joints;
    QJsonArray mates; for (const auto &value : data.value("mates").toArray()) { auto mate=value.toObject(); if (mate.value("part").toInt(-1)==index || mate.value("to").toInt(-1)==index) continue; for (const auto &field : {QString("part"),QString("to")}) if (mate.value(field).toInt(-1)>index) mate[field]=mate.value(field).toInt()-1; mates.append(mate); } data["mates"]=mates;
    if (commitAssembly(data,true,true)) { hiddenParts_.clear(); beforeIsolation_.clear(); isolatedPart_=-1; refreshAssembly(); Q_EMIT changed(); }
}
void SimulationBridge::shiftPart(int index,int step) {
    auto data=assembly_; auto parts=data.value("parts").toArray(); const int target=index+step; if (index<0 || target<0 || index>=parts.size() || target>=parts.size()) return;
    const QJsonValue swap=parts[index]; parts[index]=parts[target]; parts[target]=swap; data["parts"]=parts;
    const auto remap=[index,target](int number) { return number==index?target:number==target?index:number; };
    auto joints=data.value("joints").toArray(); for (qsizetype number=0;number<joints.size();++number) { auto joint=joints[number].toObject(); auto references=joint.value("parts").toArray(); for (qsizetype offset=0;offset<references.size();++offset) references[offset]=remap(references[offset].toInt()); joint["parts"]=references; joint["base"]=remap(joint.value("base").toInt(0)); joints[number]=joint; } data["joints"]=joints;
    auto mates=data.value("mates").toArray(); for (qsizetype number=0;number<mates.size();++number) { auto mate=mates[number].toObject(); mate["part"]=remap(mate.value("part").toInt(-1)); mate["to"]=remap(mate.value("to").toInt(-1)); mates[number]=mate; } data["mates"]=mates;
    if (commitAssembly(data)) { QSet<int> hidden,before; for (const int number : hiddenParts_) hidden.insert(remap(number)); for (const int number : beforeIsolation_) before.insert(remap(number)); hiddenParts_=hidden; beforeIsolation_=before; isolatedPart_=remap(isolatedPart_); setAssemblySelection(remap(picked_),joint_); refreshAssembly(); Q_EMIT changed(); }
}

void SimulationBridge::addJoint(const QVariant &source) {
    bool isIndex=false; const int selected=source.toInt(&isIndex);
    const QString kind=isIndex || !source.isValid()?QStringLiteral("hinge"):source.toString();
    const int part=isIndex?selected:picked_;
    if (part<0 || part>=assembly_.value("parts").toArray().size()) { unsupported("joint:请先选择一个零部件"); return; }
    if (!QStringList{"hinge","slide","spin"}.contains(kind)) { unsupported("joint:"+kind); return; }
    auto data=assembly_; auto joints=data.value("joints").toArray(); joints.append(QJsonObject{{"name",QStringLiteral("运动副 %1").arg(joints.size()+1)},{"kind",kind=="slide"?"slide":"hinge"},{"origin",triple()},{"axis",QJsonArray{0,0,1}},{"parts",QJsonArray{part}},{"min",0},{"max",kind=="slide"?50:90},{"value",0},{"speed",kind=="spin"?90:0}}); data["joints"]=joints; if (commitAssembly(data)) selectJoint(joints.size()-1);
}
void SimulationBridge::selectJoint(int index) { if (index<-1 || index>=assembly_.value("joints").toArray().size()) return; pickingJoint_=-1; setAssemblySelection(-1,index); }
void SimulationBridge::pickJointParts(int index) { if (index<0 || index>=assembly_.value("joints").toArray().size()) { unsupported("joint:索引无效"); return; } pickingJoint_=pickingJoint_==index?-1:index; setAssemblySelection(-1,index); }
void SimulationBridge::setJoint(int index,double value) { setJointField(index,"value",value); }
void SimulationBridge::setJointField(int index,const QString &field,const QVariant &value) {
    try {
        auto data=assembly_; auto joints=data.value("joints").toArray(); if (index<0 || index>=joints.size()) throw Error(QStringLiteral("运动副索引无效。")); auto joint=joints[index].toObject();
        if (field=="name") joint[field]=value.toString();
        else if (field=="kind") { const auto kind=value.toString(); if (!QStringList{"hinge","slide","spin"}.contains(kind)) throw Error(QStringLiteral("未知运动副类型。")); joint[field]=kind=="spin"?"hinge":kind; joint["speed"]=kind=="spin"?90:0; }
        else if (field=="axis" && QStringList{"X","Y","Z"}.contains(value.toString())) { const auto axis=value.toString(); joint["axis"]=QJsonArray{axis=="X"?1:0,axis=="Y"?1:0,axis=="Z"?1:0}; }
        else if (field=="on" || field=="base") { const double number=numeric(value); if (number!=std::trunc(number)) throw Error(QStringLiteral("运动副引用必须是整数索引。")); joint[field]=int(number); }
        else if (QStringList{"value","min","max","speed"}.contains(field)) joint[field]=numeric(value);
        else if (field.startsWith("origin") && field.size()==7) { bool valid=false; const int axis=field.right(1).toInt(&valid); if (!valid || axis<0 || axis>2) throw Error(QStringLiteral("无效运动中心轴。")); auto origin=joint.value("origin").toArray(triple()); origin[axis]=numeric(value); joint["origin"]=origin; }
        else throw Error(QStringLiteral("不支持的运动副字段：%1").arg(field));
        joints[index]=joint; data["joints"]=joints; commitAssembly(data);
    } catch (const std::exception &exception) { error_=QString::fromUtf8(exception.what()); Q_EMIT notice(error_); Q_EMIT changed(); }
}
void SimulationBridge::jointAction(int index,const QString &action) { const auto joints=assembly_.value("joints").toArray(); if (index<0 || index>=joints.size()) return; const auto joint=joints[index].toObject(); const double low=joint.value("min").toDouble(),high=joint.value("max").toDouble(90); if (action=="open") setJoint(index,high); else if (action=="close") setJoint(index,low); else if (action=="half") setJoint(index,(low+high)/2); else unsupported("joint action:"+action); }
void SimulationBridge::jointCentre(int index) {
    const auto jointsBefore=assembly_.value("joints").toArray(); if (index<0 || index>=jointsBefore.size()) return;
    QVector3D low,high; bool found=false; const auto vertices=display_.value("verts").toArray(),triangles=display_.value("tris").toArray(),owners=display_.value("tri_face").toArray(),faces=display_.value("faces").toArray();
    for (qsizetype number=0;number<triangles.size() && number<owners.size();++number) {
        const int face=owners[number].toInt(-1); if (face<0 || face>=faces.size() || faces[face].toObject().value("feature").toString()!="part:"+QString::number(picked_)) continue;
        for (const auto &vertex : triangles[number].toArray()) { const int point=vertex.toInt(-1); if (point<0 || point>=vertices.size()) continue; const auto coordinates=vertices[point].toArray(); if (coordinates.size()!=3) continue; const QVector3D position(float(coordinates[0].toDouble()),float(coordinates[1].toDouble()),float(coordinates[2].toDouble())); if (!found) { low=high=position; found=true; } else for (int axis=0;axis<3;++axis) { low[axis]=std::min(low[axis],position[axis]); high[axis]=std::max(high[axis],position[axis]); } }
    }
    if (!found) { unsupported("joint centre:请选择已显示的零部件"); return; }
    auto data=assembly_; auto joints=jointsBefore; auto joint=joints[index].toObject(); const auto centre=(low+high)/2; joint["origin"]=QJsonArray{centre.x(),centre.y(),centre.z()}; joints[index]=joint; data["joints"]=joints; commitAssembly(data);
}
void SimulationBridge::deleteJoint(int index) { auto data=assembly_; auto joints=data.value("joints").toArray(); if (index<0 || index>=joints.size()) return; joints.removeAt(index); for (qsizetype number=0;number<joints.size();++number) { auto joint=joints[number].toObject(); const int parent=joint.value("on").toInt(-1); if (parent==index) joint["on"]=-1; else if (parent>index) joint["on"]=parent-1; joints[number]=joint; } data["joints"]=joints; if (commitAssembly(data,true,true)) pickingJoint_=-1; }
void SimulationBridge::addMate(int part,int target,const QString &kind,const QString &axis) { auto data=assembly_; auto mates=data.value("mates").toArray(); mates.append(QJsonObject{{"part",part},{"to",target},{"kind",kind},{"axis",axis},{"value",0}}); data["mates"]=mates; commitAssembly(data); }
void SimulationBridge::setMateField(int index,const QString &field,const QVariant &value) { auto data=assembly_; auto mates=data.value("mates").toArray(); if (index<0 || index>=mates.size()) return; if (field=="delete") mates.removeAt(index); else { auto mate=mates[index].toObject(); if (!QStringList{"value","kind","axis","to","part"}.contains(field)) { unsupported("mate field:"+field); return; } mate[field]=QJsonValue::fromVariant(value); mates[index]=mate; } data["mates"]=mates; commitAssembly(data); }
void SimulationBridge::playMotion() { if (motionTimer_.isActive()) motionTimer_.stop(); else if (!assembly_.value("joints").toArray().isEmpty()) { if (seconds_>=pose_.value("length").toDouble(4)) seconds_=0; timeline_=true; motionTimer_.start(); } else { unsupported("motion:没有运动副"); return; } Q_EMIT changed(); }
void SimulationBridge::scrubMotion(double seconds) { if (!std::isfinite(seconds) || seconds<0) { unsupported("motion:无效时间"); return; } motionTimer_.stop(); timeline_=true; seconds_=seconds; refreshAssembly(); }
void SimulationBridge::settleJoint() { refreshAssembly(); }
void SimulationBridge::runFasteners() { const auto result=query("fasteners",assembly_); result_=result.contains("error")?QVariantMap{}:result.toVariantMap(); Q_EMIT changed(); }
void SimulationBridge::runInterference() { const auto result=query("interference",assembly_); result_=result.contains("error")?QVariantMap{}:result.toVariantMap(); Q_EMIT changed(); }
void SimulationBridge::runSequence() { const auto result=query("sequence",assembly_); result_=result.contains("error")?QVariantMap{}:result.toVariantMap(); Q_EMIT changed(); }
void SimulationBridge::runStack(const QString &axis) { auto arguments=assembly_; arguments["axis"]=axis; const auto result=query("stack",arguments); result_=result.contains("error")?QVariantMap{}:result.toVariantMap(); Q_EMIT changed(); }
void SimulationBridge::exitIsolation() { if (isolatedPart_<0) return; hiddenParts_=beforeIsolation_; beforeIsolation_.clear(); isolatedPart_=-1; refreshAssembly(); }
void SimulationBridge::exportBill(const QString &where) { const auto result=query("bom",assembly_); if (result.contains("error")) return; QSaveFile file(localFile(where)); if (!file.open(QIODevice::WriteOnly)) { error_=file.errorString(); Q_EMIT notice(error_); return; } const auto bytes=domain::bill_csv(result.value("rows").toArray()); if (file.write(bytes)!=bytes.size() || !file.commit()) { error_=file.errorString(); Q_EMIT notice(error_); } }
bool SimulationBridge::exportAssembly(const QString &where) { auto arguments=assembly_; auto path=localFile(where); if (!path.endsWith(".step",Qt::CaseInsensitive) && !path.endsWith(".stp",Qt::CaseInsensitive)) path+=".step"; arguments["path"]=path; if (timeline_) arguments["seconds"]=seconds_; return !query("assembly_step",arguments).contains("error"); }
}
