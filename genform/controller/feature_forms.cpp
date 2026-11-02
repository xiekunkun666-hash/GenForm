#include "genform/controller/controller.hpp"
#include "genform/features.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/view/viewport.hpp"
#include <QJSValue>
#include <QLineF>
#include <algorithm>
#include <cmath>

namespace genform::controller {
namespace {
QString labelFor(const QString &key) {
    static const QMap<QString,QString> labels{
        {"sketch",QStringLiteral("草图")},{"sketches",QStringLiteral("轮廓")},{"path",QStringLiteral("路径")},
        {"features",QStringLiteral("对象")},{"axis",QStringLiteral("旋转轴")},{"axis1",QStringLiteral("方向 1")},{"axis2",QStringLiteral("方向 2")},
        {"plane",QStringLiteral("参考面")},{"base",QStringLiteral("参考面")},{"edges",QStringLiteral("边")},{"faces",QStringLiteral("面")},
        {"angle",QStringLiteral("角度")},{"reverse",QStringLiteral("反向")},{"symmetric",QStringLiteral("两侧对称")},{"op",QStringLiteral("方式")},
        {"ruled",QStringLiteral("直纹")},{"diameter",QStringLiteral("直径")},{"depth",QStringLiteral("深度")},{"thickness",QStringLiteral("厚度")},
        {"length",QStringLiteral("长度")},{"pitch",QStringLiteral("螺距")},{"phase",QStringLiteral("螺纹相位")},{"size",QStringLiteral("规格")},
        {"kind",QStringLiteral("类型")},{"through",QStringLiteral("贯穿")},{"head_diameter",QStringLiteral("沉头直径")},{"head_depth",QStringLiteral("沉头深度")},
        {"flip",QStringLiteral("反向")},{"thread",QStringLiteral("切出螺纹牙")},{"steps",QStringLiteral("孔段 直径,深度")},{"chamfer",QStringLiteral("端部倒角")},
        {"head",QStringLiteral("头型")},{"offset",QStringLiteral("偏移")},{"walls",QStringLiteral("隔板草图")},{"wall_thickness",QStringLiteral("隔板厚度")},
        {"mode",QStringLiteral("方式")},{"count",QStringLiteral("数量")},{"count1",QStringLiteral("方向 1 数量")},{"count2",QStringLiteral("方向 2 数量")},
        {"spacing",QStringLiteral("间距")},{"spacing1",QStringLiteral("方向 1 间距")},{"spacing2",QStringLiteral("方向 2 间距")},
        {"align",QStringLiteral("沿路径对齐")},{"positions",QStringLiteral("实例坐标")},{"rows",QStringLiteral("实例表")},{"layout",QStringLiteral("排布")},
        {"margin",QStringLiteral("离边界")},{"about",QStringLiteral("绕")},{"origin",QStringLiteral("原点")},{"normal",QStringLiteral("法向")},
        {"direction",QStringLiteral("方向")},{"position",QStringLiteral("坐标")},{"rx",QStringLiteral("绕 X")},{"ry",QStringLiteral("绕 Y")},
        {"rz",QStringLiteral("绕 Z")},{"values",QStringLiteral("变量")},{"turns",QStringLiteral("圈数")},{"taper",QStringLiteral("每圈半径增量")},
        {"start",QStringLiteral("起始角")},{"clockwise",QStringLiteral("顺时针")},{"points",QStringLiteral("坐标点")},{"closed",QStringLiteral("闭合")},
        {"fx",QStringLiteral("X 表达式")},{"fy",QStringLiteral("Y 表达式")},{"fz",QStringLiteral("Z 表达式")},
        {"t0",QStringLiteral("参数起点")},{"t1",QStringLiteral("参数终点")},{"samples",QStringLiteral("采样数")}};
    return labels.value(key,key);
}
QString optionLabel(const QString &value) {
    static const QMap<QString,QString> labels{
        {"add",QStringLiteral("加料")},{"cut",QStringLiteral("切除")},{"common",QStringLiteral("相交")},
        {"void",QStringLiteral("挖空腔")},{"fill",QStringLiteral("填空腔")},{"pocket",QStringLiteral("钣金凹槽")},
        {"blind",QStringLiteral("给定深度")},{"through",QStringLiteral("完全贯穿")},{"vertex",QStringLiteral("成形到顶点")},
        {"surface",QStringLiteral("成形到面")},{"offset",QStringLiteral("离指定面指定距离")},{"body",QStringLiteral("成形到实体")},{"mid",QStringLiteral("两侧对称")},
        {"CL",QStringLiteral("草图中心线")},{"SX",QStringLiteral("草图 X 轴")},{"SY",QStringLiteral("草图 Y 轴")},
        {"simple",QStringLiteral("简单孔")},{"counterbore",QStringLiteral("柱形沉头孔")},{"countersink",QStringLiteral("锥形沉头孔")},
        {"tapped",QStringLiteral("螺纹孔")},{"custom",QStringLiteral("自定义")},{"cap",QStringLiteral("圆柱头")},{"button",QStringLiteral("盘头")},
        {"flat",QStringLiteral("沉头")},{"emboss",QStringLiteral("浮雕（凸起）")},{"deboss",QStringLiteral("蚀雕（凹进）")},
        {"square",QStringLiteral("方形")},{"hex",QStringLiteral("交错（蜂窝）")},{"line",QStringLiteral("直线段")},
        {"spline",QStringLiteral("样条曲线")},{"helix",QStringLiteral("螺旋线")},{"spiral",QStringLiteral("涡状线")}};
    return labels.value(value,value);
}
QJsonArray choices(const QStringList &values) {
    QJsonArray result;
    for (const auto &value : values) result.append(QJsonObject{{"value",value},{"label",optionLabel(value)}});
    return result;
}
QJsonArray combined(QJsonArray first,const QJsonArray &second) {
    for (const auto &value : second) first.append(value);
    return first;
}
QJsonObject formField(const QString &key,const QString &kind,const QJsonValue &value,const QString &label={}) {
    return {{"key",key},{"kind",kind},{"label",label.isEmpty()?labelFor(key):label},{"type",kind},{"value",value},{"options",QJsonArray{}},{"unit",""}};
}
QJsonArray namedFeatures(const Session *session,const QStringList &kinds,const QString &editing={}) {
    QJsonArray result;
    for (const auto &value : session->document.features) {
        const auto feature=value.toObject();
        if (feature.value("id").toString()==editing) break;
        if (kinds.contains(feature.value("type").toString())) result.append(QJsonObject{{"value",feature.value("id")},{"label",feature.value("name")}});
    }
    return result;
}
QJsonArray pickedReferences(const Session *session,const QString &kind) {
    QJsonArray result;
    const QString key=kind=="edge"?"edges":kind=="vertex"?"vertices":"faces";
    const auto model=session->model.value(key).toArray();
    for (const auto &selected : session->selection.value(key).toArray()) {
        const int identifier=selected.toInt(-1);
        QJsonValue point;
        if (kind=="vertex") { if (identifier>=0 && identifier<model.size()) point=model[identifier]; }
        else for (const auto &value : model) {
            const auto item=value.toObject();
            if (item.value("id").toInt(-1)==identifier) { point=item.value(kind=="edge"?"mid":"center"); break; }
        }
        if (point.isArray() && point.toArray().size()==3) result.append(QJsonObject{{"point",point}});
    }
    return result;
}
QString pointText(const QJsonValue &value) {
    if (value.isString()) return value.toString();
    auto rows=value.toArray();
    if (!rows.isEmpty() && !rows.first().isArray()) rows=QJsonArray{rows};
    QStringList lines;
    for (const auto &row : rows) {
        QStringList coordinates;
        for (const auto &coordinate : row.toArray()) coordinates.append(QString::number(coordinate.toDouble(),'g',12));
        lines.append(coordinates.join(','));
    }
    return lines.join("; ");
}
QJsonObject pickDefinition(const QString &key,const QString &kind,bool optional=false,int count=0) {
    return {{"key",key},{"kind",kind},{"optional",optional},{"count",count},{"label",labelFor(key)}};
}
QJsonObject arranged(QJsonObject form) {
    if (form.value("kind").toString()!="extrude") return form;
    auto fields=form.value("fields").toArray();
    QString end="blind";
    for (const auto &value : fields) if (value.toObject().value("key")=="end") end=value.toObject().value("value").toString();
    for (qsizetype index=0;index<fields.size();++index) {
        auto item=fields[index].toObject(); const auto key=item.value("key").toString();
        if (key=="distance") { item["hidden"]=end!="blind" && end!="mid"; item["label"]=end=="mid"?QStringLiteral("总深度"):QStringLiteral("深度"); }
        else if (key=="distance2") item["hidden"]=end!="blind";
        else if (key=="gap") item["hidden"]=end!="offset";
        else if (key=="reverse") item["hidden"]=QStringList{"mid","vertex","surface","offset"}.contains(end);
        else if (key=="target") item["hidden"]=!QStringList{"vertex","surface","offset"}.contains(end);
        fields[index]=item;
    }
    form["fields"]=fields;
    if (QStringList{"vertex","surface","offset"}.contains(end)) {
        auto pick=pickDefinition("target",end=="vertex"?"vertex":"face",false,1);
        pick["label"]=end=="vertex"?QStringLiteral("终止顶点"):QStringLiteral("终止面"); form["pick"]=pick;
    } else form.remove("pick");
    return form;
}
}

void AppController::createFeatureForm(const QString &requested,const QString &editing) {
    connect(this,&AppController::formChanged,this,&AppController::syncFeatureFormPick,Qt::UniqueConnection);
    connect(this,&AppController::changed,this,&AppController::syncFeatureFormPick,Qt::UniqueConnection);
    QString command=requested;
    const bool cut=command=="cut" || command.endsWith("_cut");
    if (command=="cut") command="extrude"; else if (command.endsWith("_cut")) command.chop(4);
    QJsonObject params;
    if (!editing.isEmpty()) params=session_->document.find(editing).value("params").toObject();
    const auto spec=features::spec(command);
    if (spec.isEmpty() && !QStringList{"extrude","fillet","chamfer"}.contains(command)) { unsupported(command); return; }
    const auto sketches=namedFeatures(session_,{"sketch"},editing);
    auto sketchDefault=[&] {
        const auto selected=session_->selection.value("feature");
        for (const auto &value : sketches) if (value.toObject().value("value")==selected) return selected;
        return sketches.isEmpty()?QJsonValue(""):sketches.last().toObject().value("value");
    };
    QJsonArray fields;
    auto add=[&](const QString &key,const QString &kind,const QJsonValue &fallback,const QString &label={}) {
        auto item=formField(key,kind,params.contains(key)?params.value(key):fallback,label);
        if (kind=="number") item["unit"]="mm";
        return item;
    };
    QJsonObject pick;
    if (command=="fillet" || command=="chamfer") {
        auto item=formField("edges","info","",QStringLiteral("处理的边")); item["kind"]="edges"; fields.append(item);
        fields.append(add(command=="fillet"?"radius":"distance","number",command=="fillet"?2.0:1.0,command=="fillet"?QStringLiteral("半径"):QStringLiteral("距离")));
        pick=pickDefinition("edges","edge");
    } else if (command=="extrude") {
        auto sketch=add("sketch","choice",sketchDefault()); sketch["kind"]="sketch"; sketch["options"]=sketches; fields.append(sketch);
        const bool hasBody=session_->model.value("has_body").toBool();
        auto end=add("end","choice",params.value("symmetric").toBool()?"mid":cut && hasBody?"through":"blind",QStringLiteral("终止条件"));
        end["options"]=choices({"blind","through","vertex","surface","offset","body","mid"}); fields.append(end);
        auto distance=add("distance","number",10,QStringLiteral("深度"));
        const double oldDistance=distance.value("value").toDouble(); distance["value"]=std::abs(oldDistance); fields.append(distance);
        fields.append(formField("target","info","",QStringLiteral("终止面")));
        fields.append(add("gap","number",0,QStringLiteral("离面的距离")));
        fields.append(add("reverse","bool",params.value("reverse").toBool()!=(oldDistance<0),QStringLiteral("反向")));
        if (oldDistance<0) { auto reverse=fields.last().toObject(); reverse["value"]=!params.value("reverse").toBool(); fields[fields.size()-1]=reverse; }
        fields.append(add("distance2","number",0,QStringLiteral("方向 2 深度")));
        auto op=add("op","choice",cut && hasBody?"cut":"add"); op["options"]=choices({"add","cut","common","void","fill","pocket"}); fields.append(op);
    } else {
        for (const auto &value : spec.value("fields").toArray()) {
            const auto definition=value.toObject(); const auto key=definition.value("key").toString(),kind=definition.value("kind").toString();
            auto content=params.contains(key)?params.value(key):definition.value("default");
            auto item=formField(key,kind,content);
            if (definition.contains("width")) item["width"]=definition.value("width");
            item["optional"]=definition.value("optional").toBool();
            if (kind=="number" || kind=="int") {
                item["type"]="number"; item["expression"]=true; item["unit"]=QStringList{"angle","phase","rx","ry","rz","start"}.contains(key)?QStringLiteral("°"):kind=="int" || key=="turns"?QString():QStringLiteral("mm");
            } else if (kind=="choice") {
                QJsonArray options;
                for (const auto &option : definition.value("options").toArray()) { auto entry=option.toObject(); entry["label"]=optionLabel(entry.value("value").toString()); options.append(entry); }
                item["options"]=options;
                if (cut && key=="op" && editing.isEmpty()) item["value"]="cut";
            } else if (QStringList{"sketch","path","plane","axis"}.contains(kind)) {
                item["type"]="choice"; QJsonArray options;
                if (kind=="sketch" || kind=="path") {
                    options=kind=="sketch"?sketches:namedFeatures(session_,QStringList{"sketch"}+features::curveKinds(),editing);
                    if (content.isNull() || content.isUndefined()) content=kind=="sketch"?sketchDefault():QJsonValue(options.isEmpty()?QJsonValue(""):options.last().toObject().value("value"));
                    if (definition.value("optional").toBool()) options.prepend(QJsonObject{{"value",""},{"label",QStringLiteral("无")}});
                } else if (kind=="plane") options=combined(choices({"XY","XZ","YZ"}),namedFeatures(session_,{"plane"},editing));
                else {
                    options=combined(choices(command=="revolve"?QStringList{"CL","SX","SY","X","Y","Z"}:QStringList{"X","Y","Z"}),namedFeatures(session_,{"axis"},editing));
                    if (content.toString().startsWith('@') || content.toString().startsWith('#')) options.append(QJsonObject{{"value",content},{"label",QStringLiteral("视图中选的轴")}});
                }
                item["options"]=options; item["value"]=content;
            } else if (kind=="sketches" || kind=="features") {
                item["type"]="multi";
                const auto referenceKind=definition.value("of").toString(command=="curve_points"?"point":command=="curve_composite"?"path":"");
                item["options"]=kind=="sketches"?sketches:namedFeatures(session_,referenceKind=="point"?QStringList{"point"}:referenceKind=="path"?QStringList{"sketch"}+features::curveKinds():features::toolKinds(),editing);
                if (!content.isArray()) content=QJsonArray{};
                if (editing.isEmpty() && kind=="features" && command!="pattern_fill" && referenceKind.isEmpty()) {
                    const auto selected=session_->selection.value("feature");
                    for (const auto &option : item.value("options").toArray()) if (option.toObject().value("value")==selected) content=QJsonArray{selected};
                }
                item["value"]=content;
            } else if (kind=="edges" || kind=="faces") {
                item["type"]="info";
                pick=pickDefinition(key,kind=="edges"?"edge":"face",definition.value("optional").toBool(command=="curve_composite"),definition.value("count").toInt(command=="thread" || command=="wrap" || command=="curve_surface"?1:0));
            } else if (kind=="points") { item["type"]="text"; item["value"]=pointText(content); }
            else if (kind=="vars") {
                item["type"]="text";
                if (content.isObject()) { QStringList lines; const auto values=content.toObject(); for (auto entry=values.begin();entry!=values.end();++entry) lines.append(entry.key()+" = "+entry.value().toVariant().toString()); item["value"]=lines.join("; "); }
            }
            fields.append(item);
        }
    }
    if (sketches.isEmpty()) for (const auto &value : fields) if (QStringList{"sketch","sketches"}.contains(value.toObject().value("kind").toString()) && !value.toObject().value("optional").toBool()) { fields.prepend(formField("note","info",QStringLiteral("还没有草图：先在“草图”页里画出轮廓"))); break; }
    QString title=features::title(command);
    if (command=="extrude") title=cut?QStringLiteral("拉伸切除"):QStringLiteral("拉伸凸台");
    if (cut && !spec.isEmpty()) title=title+QStringLiteral("切除");
    if (!editing.isEmpty()) title=QStringLiteral("编辑 %1").arg(featureName(editing));
    form_={{"kind",command},{"title",title},{"editing",editing},{"serial",++formSerial_},{"fields",fields},{"params",params},{"accept",editing.isEmpty()?QStringLiteral("确定"):QStringLiteral("应用")},{"cancel",editing.isEmpty()?QStringLiteral("取消"):QStringLiteral("关闭")}};
    if (command=="extrude" && params.contains("target")) form_["kept_end"]=params.value("end");
    if (!pick.isEmpty()) form_["pick"]=pick;
    form_=arranged(form_);
    previewNote_=QStringLiteral("参数将在确认后交给原生内核重建；暂不提供动态实体预览。");
    Q_EMIT formChanged(); Q_EMIT changed();
}

QJsonObject AppController::featureForm() const {
    auto form=form_;
    const auto pick=form.value("pick").toObject();
    if (pick.isEmpty()) return form;
    const auto key=pick.value("key").toString(),kind=pick.value("kind").toString();
    const auto selected=pickedReferences(session_,kind);
    auto kept=form.value("params").toObject().value(key);
    if (key=="target") for (const auto &value : form.value("fields").toArray()) if (value.toObject().value("key")=="end" && value.toObject().value("value")!=form.value("kept_end")) kept=QJsonValue();
    const QString unit=kind=="edge"?QStringLiteral("条边"):kind=="vertex"?QStringLiteral("个顶点"):QStringLiteral("个面");
    QString text;
    if (!selected.isEmpty()) text=QStringLiteral("已选 %1 %2").arg(selected.size()).arg(unit);
    else if (!form.value("editing").toString().isEmpty() && ((kept.isArray() && !kept.toArray().isEmpty()) || (kept.isString() && !kept.toString().isEmpty()))) text=QStringLiteral("沿用原来选的 %1；在视图中重新点选则替换").arg(kept.isArray()?QString::number(kept.toArray().size())+" "+unit:kept.toString());
    else text=QStringLiteral("在三维视图里点选%1（再点一次取消）").arg(kind=="edge"?QStringLiteral("边"):kind=="vertex"?QStringLiteral("顶点"):QStringLiteral("面"));
    if (pick.value("count").toInt()>0) text+=QStringLiteral("（要 %1 个）").arg(pick.value("count").toInt());
    if (pick.value("optional").toBool()) text+=QStringLiteral("，可以不选");
    auto fields=form.value("fields").toArray();
    for (qsizetype index=0;index<fields.size();++index) { auto item=fields[index].toObject(); if (item.value("key")==key) { item["value"]=text; item["selectedCount"]=selected.size(); fields[index]=item; } }
    form["fields"]=fields;
    return form;
}

bool AppController::updateFeatureFormField(const QString &key,const QJsonValue &value) {
    if (form_.isEmpty()) return false;
    auto fields=form_.value("fields").toArray(); bool updated=false;
    for (qsizetype index=0;index<fields.size();++index) {
        auto item=fields[index].toObject();
        if (item.value("key").toString()!=key) continue;
        if (item.value("type")=="info") return false;
        if (item.value("value")==value) return false;
        item["value"]=value; fields[index]=item; updated=true;
    }
    if (updated) {
        form_["fields"]=fields; form_=arranged(form_);
        if (form_.value("kind")=="extrude" && key=="end") {
            for (const auto &kind : {QString("faces"),QString("edges"),QString("vertices")}) session_->selection[kind]=QJsonArray{};
            if (viewport_) viewport_->setSelection(session_->selection);
        }
    }
    return updated;
}

void AppController::syncFeatureFormPick() {
    if (viewport_) viewport_->setPickKind(form_.isEmpty()?QString():form_.value("pick").toObject().value("kind").toString("reference"));
}

bool AppController::takeFeatureFormReference(const QStringList &kinds,const QJsonValue &value,const QString &label) {
    auto fields=form_.value("fields").toArray();
    QList<qsizetype> candidates;
    qsizetype chosen=-1;
    for (qsizetype index=0;index<fields.size();++index) {
        const auto item=fields[index].toObject();
        if (!kinds.contains(item.value("kind").toString()) || !QStringList{"choice","multi"}.contains(item.value("type").toString()) || item.value("hidden").toBool()) continue;
        candidates.append(index);
        if (item.value("key")==form_.value("active")) chosen=index;
    }
    if (candidates.isEmpty()) return false;
    if (chosen<0) chosen=candidates.first();
    auto item=fields[chosen].toObject();
    auto options=item.value("options").toArray();
    bool allowed=false;
    for (const auto &option : options) if (option.toObject().value("value")==value) { allowed=true; break; }
    if (!allowed) {
        if (item.value("type")=="multi" || label.isEmpty()) return false;
        for (qsizetype index=options.size();index>0;--index) if (options[index-1].toObject().value("label")==label) options.removeAt(index-1);
        options.append(QJsonObject{{"value",value},{"label",label}}); item["options"]=options;
    }
    if (item.value("type")=="multi") {
        auto values=item.value("value").toArray();
        const auto position=std::find(values.begin(),values.end(),value);
        if (position==values.end()) values.append(value); else values.removeAt(std::distance(values.begin(),position));
        item["value"]=values;
    } else {
        item["value"]=value;
        if (candidates.size()>1) form_["active"]=fields[candidates[(candidates.indexOf(chosen)+1)%candidates.size()]].toObject().value("key");
    }
    fields[chosen]=item; form_["fields"]=fields;
    Q_EMIT formChanged(); Q_EMIT changed();
    return true;
}

bool AppController::takeFeatureFormSelection(const QJsonObject &selection,bool additive) {
    Q_UNUSED(additive);
    if (form_.isEmpty() || kind_!="part" || sketch_ || pickingPlane_ || measuring_) return false;
    const auto pick=form_.value("pick").toObject();
    const auto edgeIds=selection.value("edges").toArray(),faceIds=selection.value("faces").toArray(),vertexIds=selection.value("vertices").toArray();
    const auto identifier=selection.value("feature").toString();
    auto lineToken=[](const QVector3D &origin,const QVector3D &direction) {
        auto text=[](const QVector3D &coordinates) { return QString::number(coordinates.x(),'g',6)+","+QString::number(coordinates.y(),'g',6)+","+QString::number(coordinates.z(),'g',6); };
        return "@"+text(origin)+";"+text(direction);
    };
    const auto position=selection.value("pick_position").toArray();
    bool hasAxis=false; QString sketch;
    for (const auto &entry : form_.value("fields").toArray()) {
        const auto item=entry.toObject();
        if (item.value("kind")=="axis") hasAxis=true;
        if (item.value("kind")=="sketch") sketch=item.value("value").toString();
    }
    auto takeSketchLine=[&](const QJsonObject &feature) {
        if (!hasAxis || !viewport_ || position.size()!=2 || feature.value("type")!="sketch" || feature.value("suppressed").toBool() || hidden_.contains(feature.value("id").toString())) return false;
        domain::PlaneFrame frame;
        const auto params=feature.value("params").toObject();
        try { frame=domain::frame(features::planeFrame(params.value("plane").toString("XY"),session_->document.features,params.value("offset").toDouble())); }
        catch (const std::exception &) { return false; }
        const auto camera=viewport_->cameraState(); const auto centre=camera.value("centre").toArray();
        QMatrix4x4 rotation; rotation.rotate(float(camera.value("pitch").toDouble()),1,0,0); rotation.rotate(float(camera.value("yaw").toDouble()),0,0,1);
        const QVector3D origin(float(centre[0].toDouble()),float(centre[1].toDouble()),float(centre[2].toDouble()));
        auto screen=[&](const QVector3D &point) { const auto turned=rotation.map(point-origin); return QPointF(viewport_->width()/2+camera.value("pan_x").toDouble()+turned.x()*camera.value("scale").toDouble(),viewport_->height()/2+camera.value("pan_y").toDouble()-turned.y()*camera.value("scale").toDouble()); };
        const QPointF click(position[0].toDouble(),position[1].toDouble());
        double closest=9; QVector3D start,along; int centreIndex=0,bestCentre=-1; bool found=false;
        for (const auto &entry : params.value("shapes").toArray()) {
            const auto shape=entry.toObject(); if (shape.value("type")!="line") continue;
            const auto first=frame.origin+float(shape.value("x1").toDouble())*frame.x+float(shape.value("y1").toDouble())*frame.y;
            const auto last=frame.origin+float(shape.value("x2").toDouble())*frame.x+float(shape.value("y2").toDouble())*frame.y;
            const auto projected=screen(first),delta=screen(last)-projected;
            const double square=QPointF::dotProduct(delta,delta),fraction=square>1e-12?std::clamp(QPointF::dotProduct(click-projected,delta)/square,0.0,1.0):0;
            const double distance=QLineF(click,projected+fraction*delta).length();
            if ((last-first).lengthSquared()>1e-12 && distance<=closest) { closest=distance; start=first; along=last-first; found=true; bestCentre=shape.value("construction").toBool()?centreIndex:-1; }
            if (shape.value("construction").toBool()) ++centreIndex;
        }
        if (!found || (bestCentre<0 && feature.value("id")!=sketch)) return false;
        if (bestCentre==0 && feature.value("id")==sketch) for (const auto &entry : form_.value("fields").toArray()) {
            const auto item=entry.toObject(); if (item.value("kind")!="axis") continue;
            for (const auto &option : item.value("options").toArray()) if (option.toObject().value("value")=="CL") return takeFeatureFormReference({"axis"},"CL");
        }
        return takeFeatureFormReference({"axis"},lineToken(start,along),QStringLiteral("视图中选的轴"));
    };
    if (edgeIds.isEmpty() && faceIds.isEmpty() && vertexIds.isEmpty() && !identifier.isEmpty()) {
        QJsonObject feature;
        for (const auto &entry : session_->document.features) if (entry.toObject().value("id")==identifier) { feature=entry.toObject(); break; }
        const auto kind=feature.value("type").toString();
        if (kind=="sketch" && takeSketchLine(feature)) return true;
        const QStringList accepts=kind=="axis"?QStringList{"axis"}:kind=="plane"?QStringList{"plane"}:kind=="sketch"?QStringList{"sketch","path","sketches","features"}:features::curveKinds().contains(kind)?QStringList{"path","features"}:QStringList{"features"};
        takeFeatureFormReference(accepts,identifier);
        return true;
    }
    const QString selectedKind=!edgeIds.isEmpty()?"edge":!faceIds.isEmpty()?"face":"";
    if (hasAxis && position.size()==2 && vertexIds.isEmpty() && (pick.isEmpty() || pick.value("kind").toString()!=selectedKind)) {
        for (const auto &entry : session_->document.features) if (entry.toObject().value("id")==sketch && takeSketchLine(entry.toObject())) return true;
        for (const auto &entry : session_->document.features) {
            if (entry.toObject().value("id")==form_.value("editing")) break;
            if (entry.toObject().value("id")!=sketch && takeSketchLine(entry.toObject())) return true;
        }
    }
    const auto plane=selection.value("plane").toString();
    if (!plane.isEmpty() && takeFeatureFormReference({"plane"},plane)) return true;
    if (!edgeIds.isEmpty() && pick.value("kind")!="edge") {
        for (const auto &entry : session_->model.value("edges").toArray()) {
            const auto edge=entry.toObject();
            if (edge.value("id")!=edgeIds.first()) continue;
            const bool straight=edge.value("dir").isArray();
            const auto origin=edge.value(straight?"mid":"center").toArray();
            const auto direction=edge.value(straight?"dir":"axis").toArray();
            if (origin.size()!=3 || direction.size()!=3) break;
            const QVector3D point(float(origin[0].toDouble()),float(origin[1].toDouble()),float(origin[2].toDouble()));
            const QVector3D along(float(direction[0].toDouble()),float(direction[1].toDouble()),float(direction[2].toDouble()));
            if (takeFeatureFormReference({"axis"},lineToken(point,along),QStringLiteral("视图中选的轴"))) return true;
            break;
        }
    }
    if (pick.isEmpty()) {
        if (!identifier.isEmpty() && takeFeatureFormReference({"features"},identifier)) return true;
        return false;
    }
    const auto kind=pick.value("kind").toString();
    const QString key=kind=="edge"?"edges":kind=="vertex"?"vertices":"faces";
    const auto incoming=selection.value(key).toArray();
    if (incoming.isEmpty()) return true;
    const auto model=session_->model.value(key).toArray();
    QJsonArray valid;
    for (const auto &reference : incoming) {
        const int number=reference.toInt(-1);
        if (kind=="vertex") { if (number>=0 && number<model.size() && model[number].toArray().size()==3) valid.append(number); }
        else for (const auto &entry : model) if (entry.toObject().value("id").toInt(-1)==number) { valid.append(number); break; }
    }
    if (valid.isEmpty()) return true;
    auto chosen=pick.value("count").toInt()==1?QJsonArray{}:session_->selection.value(key).toArray();
    if (pick.value("count").toInt()==1) chosen.append(valid.first());
    else for (const auto &reference : valid) { const auto existing=std::find(chosen.begin(),chosen.end(),reference); if (existing==chosen.end()) chosen.append(reference); else chosen.removeAt(std::distance(chosen.begin(),existing)); }
    for (const auto &topologyKind : {QString("faces"),QString("edges"),QString("vertices")}) session_->selection[topologyKind]=QJsonArray{};
    session_->selection.remove("plane"); session_->selection[key]=chosen;
    if (viewport_) viewport_->setSelection(session_->selection);
    Q_EMIT formChanged(); Q_EMIT changed(); Q_EMIT treeChanged();
    return true;
}

void AppController::focusField(const QString &key) {
    if (form_.isEmpty()) return;
    for (const auto &value : form_.value("fields").toArray()) {
        const auto item=value.toObject();
        if (item.value("key")==key && QStringList{"sketch","path","plane","axis","sketches","features"}.contains(item.value("kind").toString())) { form_["active"]=key; Q_EMIT formChanged(); Q_EMIT changed(); return; }
    }
}

void AppController::setFormFields(const QVariantMap &values) {
    bool updated=false;
    for (auto entry=values.begin();entry!=values.end();++entry) {
        const auto value=entry.value().metaType().id()==qMetaTypeId<QJSValue>()?entry.value().value<QJSValue>().toVariant():entry.value();
        updated=updateFeatureFormField(entry.key(),QJsonValue::fromVariant(value)) || updated;
    }
    if (updated) { Q_EMIT formChanged(); Q_EMIT changed(); }
}

void AppController::acceptFeatureForm() {
    const auto command=form_.value("kind").toString(),editing=form_.value("editing").toString();
    auto params=form_.value("params").toObject();
    auto fail=[&](const QString &message) { previewNote_=message; Q_EMIT notice(message); Q_EMIT formChanged(); Q_EMIT changed(); };
    try {
        for (const auto &value : form_.value("fields").toArray()) {
            const auto item=value.toObject(); const auto key=item.value("key").toString(); const auto kind=item.value("kind").toString(); auto content=item.value("value");
            if (item.value("type")=="info" || item.value("hidden").toBool()) continue;
            if (item.value("type")=="number") {
                bool valid=content.isDouble();
                const bool expression=content.isString() && content.toString().trimmed().startsWith('=') && features::spec(command).contains("fields");
                const double number=content.isDouble()?content.toDouble():content.toString().toDouble(&valid);
                if (!expression && (!valid || !std::isfinite(number))) throw Error(QStringLiteral("参数不是有效数值：%1").arg(item.value("label").toString()));
                if (!expression && kind=="int" && std::floor(number)!=number) throw Error(QStringLiteral("%1必须为整数").arg(item.value("label").toString()));
                if (!expression) content=number;
            }
            if (QStringList{"number","int","bool","choice","points","vars","features","sketches"}.contains(kind)) content=features::clean(item,content);
            if (QStringList{"sketch","path"}.contains(kind) && content.toString().isEmpty() && !item.value("optional").toBool()) throw Error(QStringLiteral("还没有可选的%1").arg(item.value("label").toString()));
            if ((kind=="sketch" || kind=="path" || kind=="plane" || kind=="axis") && !content.toString().isEmpty()) {
                bool found=false;
                for (const auto &option : item.value("options").toArray()) if (option.toObject().value("value")==content) found=true;
                if (!found) throw Error(QStringLiteral("%1引用无效").arg(item.value("label").toString()));
            }
            if (kind=="features" || kind=="sketches") for (const auto &reference : content.toArray()) {
                bool found=false; for (const auto &option : item.value("options").toArray()) if (option.toObject().value("value")==reference) found=true;
                if (!found) throw Error(QStringLiteral("对象引用无效：%1").arg(reference.toString()));
            }
            params[key]=content;
        }
        const auto pick=form_.value("pick").toObject();
        if (!pick.isEmpty()) {
            const auto key=pick.value("key").toString();
            const auto chosen=pickedReferences(session_,pick.value("kind").toString());
            const auto kept=params.value(key);
            const bool compatibleTarget=key!="target" || params.value("end")==form_.value("kept_end");
            const bool keep=!editing.isEmpty() && compatibleTarget && ((kept.isArray() && !kept.toArray().isEmpty()) || (kept.isString() && !kept.toString().isEmpty()));
            if (chosen.isEmpty() && !keep && !pick.value("optional").toBool()) throw Error(QStringLiteral("先在三维视图里点选%1").arg(pick.value("label").toString()));
            const int count=pick.value("count").toInt();
            if (!chosen.isEmpty() && count>0 && chosen.size()!=count) throw Error(QStringLiteral("%1要正好选 %2 个").arg(pick.value("label").toString()).arg(count));
            if (!chosen.isEmpty() || !keep) params[key]=chosen;
        }
        if (command=="fillet" || command=="chamfer") {
            const auto key=command=="fillet"?QString("radius"):QString("distance");
            if (params.value(key).toDouble()<=0) throw Error(command=="fillet"?QStringLiteral("半径必须大于 0"):QStringLiteral("距离必须大于 0"));
        }
        if (command=="loft" || command=="boundary") if (params.value("sketches").toArray().size()<2) throw Error(QStringLiteral("至少选择两个草图轮廓"));
        if (command=="pattern_variable" && params.value("features").toArray().isEmpty()) throw Error(QStringLiteral("请先选择阵列对象"));
        if (command=="curve_points" && params.value("points").toArray().size()<2) throw Error(QStringLiteral("至少选择两个参考点"));
        if (command.startsWith("pattern_")) for (const auto &key : {QString("count"),QString("count1"),QString("count2")}) if (params.contains(key) && params.value(key).isDouble() && params.value(key).toDouble()<1) throw Error(QStringLiteral("阵列数量至少为 1"));
        if (command=="revolve" && params.value("angle").isDouble() && (std::abs(params.value("angle").toDouble())<1e-9 || std::abs(params.value("angle").toDouble())>360)) throw Error(QStringLiteral("旋转角度必须大于 0 且不超过 360°"));
        if (command=="draft" && params.value("angle").isDouble() && (std::abs(params.value("angle").toDouble())<1e-9 || std::abs(params.value("angle").toDouble())>=89)) throw Error(QStringLiteral("拔模角度必须非零且小于 89°"));
        if (command=="shell" && params.value("thickness").isDouble() && params.value("thickness").toDouble()<=0) throw Error(QStringLiteral("壁厚必须大于 0"));
        if (command=="extrude") {
            const auto end=params.value("end").toString();
            if ((end=="blind" || end=="mid") && params.value("distance").toDouble()<=0) throw Error(QStringLiteral("深度必须大于 0"));
            if (end=="blind" && params.value("distance2").toDouble()<0) throw Error(QStringLiteral("方向 2 深度不能为负数"));
            params["symmetric"]=end=="mid";
            params["reverse"]=params.value("reverse").toBool() && !QStringList{"mid","vertex","surface","offset"}.contains(end);
            if (end!="blind") params["distance2"]=0;
            if (end!="offset") params["gap"]=0;
        }
    } catch (const std::exception &exception) { fail(QString::fromUtf8(exception.what())); return; }
    const auto result=editing.isEmpty()?execute(command,params):execute("edit_feature",{{"id",editing},{"params",params}});
    if (result.value("ok").toBool()) { form_={}; previewNote_.clear(); if (result.contains("id")) selectFeature(result.value("id").toString()); }
    else {
        if (!result.value("id").toString().isEmpty()) { form_["editing"]=result.value("id"); form_["params"]=params; }
        previewNote_=result.value("error").toString(QStringLiteral("命令失败，请检查参数后重试。"));
    }
    Q_EMIT formChanged(); Q_EMIT changed();
}
}
