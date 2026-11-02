#include "runner.hpp"
#include <QCryptographicHash>
#include <QFile>
#include <QJsonDocument>
#include <QSaveFile>
#include <QSet>
#include <QTemporaryDir>
#include <QTextStream>
#include <algorithm>

namespace examples {
namespace {
QString digest(const QJsonObject &value) { return QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(value).toJson(QJsonDocument::Compact),QCryptographicHash::Sha256).toHex()); }
bool featureId(const QString &value) { if(value.size()<2||value[0]!='f') return false; for(qsizetype index=1;index<value.size();++index) if(!value[index].isDigit()) return false; return true; }
bool auxiliary(const QString &kind) { return QSet<QString>{"sketch","axis","plane","point","csys","sketch3d","bbox","com"}.contains(kind)||kind.startsWith("curve_"); }

QJsonArray halfShapes(const QJsonObject &params,int count) {
    const auto shapes=params["shapes"].toArray(); require(params["plane"]=="YZ"&&shapes.size()==1,"Expected a single symmetric YZ Catmull section"); const auto shape=shapes[0].toObject(); const auto points=shape["points"].toArray();
    require(shape["type"]=="spline"&&shape["closed"].toBool()&&!shape["style"].toBool()&&points.size()==count*2,"Unexpected closed Catmull section topology");
    const auto top=points[0].toArray(),bottom=points[count].toArray(); require(top[0].toDouble()==0&&bottom[0].toDouble()==0&&top[1].toDouble()>bottom[1].toDouble(),"Section must start at the top centre and reach bottom centre");
    for(int index=1;index<count;++index) { const auto right=points[index].toArray(),left=points[points.size()-index].toArray(); require(right[0].toDouble()>0&&left==QJsonArray{-right[0].toDouble(),right[1]},"Refusing asymmetric half-section conversion"); }
    QJsonArray result;
    for(int index=0;index<count;++index) { const auto before=points[(index-1+points.size())%points.size()].toArray(),start=points[index].toArray(),end=points[index+1].toArray(),after=points[(index+2)%points.size()].toArray(); QJsonArray firstControl,secondControl;
        for(int axis=0;axis<2;++axis) { firstControl.append(start[axis].toDouble()+(end[axis].toDouble()-before[axis].toDouble())/6); secondControl.append(end[axis].toDouble()-(after[axis].toDouble()-start[axis].toDouble())/6); }
        result.append(QJsonObject{{"type","spline"},{"style",true},{"closed",false},{"points",QJsonArray{start,firstControl,secondControl,end}}});
    }
    result.append(QJsonObject{{"type","line"},{"x1",bottom[0]},{"y1",bottom[1]},{"x2",top[0]},{"y2",top[1]}}); return result;
}

struct Plan {
    genform::Document document;
    QJsonObject source,mapping,colors,orphans;
    QJsonArray rows;

    explicit Plan(QJsonObject data):source(std::move(data)) {
        require(source["upto"].isNull()||!source.contains("upto"),"Source A must not have rollback");
        const auto props=source["props"].toObject(); for(auto iterator=props.begin();iterator!=props.end();++iterator) require(QStringList{"color","material","feature_colors"}.contains(iterator.key()),"Unknown source property cannot be represented: "+iterator.key());
        QMap<QString,QJsonObject> byName,byId; for(const auto &value:source["features"].toArray()) { const auto row=value.toObject(); const QString name=row["name"].toString(),identifier=row["id"].toString(); require(!byName.contains(name)&&!byId.contains(identifier),"Source feature names and IDs must be unique"); byName[name]=row; byId[identifier]=row; }
        const QMap<QString,int> halves{{QString::fromUtf8("911_连续曲面车身"),7},{QString::fromUtf8("911_经典弧顶与后溜背"),5}}; QMap<QString,int> sections;
        for(auto iterator=halves.begin();iterator!=halves.end();++iterator) { const auto loft=byName.value(iterator.key()); require(loft["type"]=="loft"&&loft["params"].toObject().value("op").toString("add")=="add","Missing expected additive body/roof loft: "+iterator.key()); for(const auto &reference:loft["params"].toObject()["sketches"].toArray()) { require(byId.contains(reference.toString()),"Missing loft section"); sections[byId[reference.toString()]["name"].toString()]=iterator.value(); } }
        for(const auto &value:source["features"].toArray()) {
            const auto original=value.toObject(); const QString name=original["name"].toString(),kind=original["type"].toString(),identifier=original["id"].toString();
            QString left; auto tokens=name.split('_'); const auto token=std::find(tokens.begin(),tokens.end(),QString("right"));
            if(token!=tokens.end()&&!name.contains("window",Qt::CaseInsensitive)&&!name.contains("glass",Qt::CaseInsensitive)&&!name.contains("mirror_right",Qt::CaseInsensitive)) { *token="left"; if(byName.contains(tokens.join('_'))) left=tokens.join('_'); }
            QJsonObject params=left.isEmpty()?remap(original["params"]).toObject():QJsonObject{}; QJsonArray made; QString strategy;
            if(sections.contains(name)) { params["shapes"]=halfShapes(original["params"].toObject(),sections[name]); made.append(add(kind,params,name,original)); strategy="exact-positive-Y-Bezier-section"; }
            else if(halves.contains(name)) { const QString seed=add("loft",params,name+"__B_positiveY",original); made.append(seed); made.append(add("mirror",{{"plane","XZ"},{"offset",0},{"features",QJsonArray{seed}}},name,original)); strategy="half-YZ-loft-plus-feature-mirror-XZ"; }
            else if(!left.isEmpty()) {
                const auto seed=byName[left]; require(original["suppressed"].toBool()==seed["suppressed"].toBool(),"Asymmetric suppression: "+name);
                if(auxiliary(kind)) strategy="omitted-right-auxiliary; original retained in manifest";
                else { require(QSet<QString>{"extrude","revolve","loft","sweep","mirror","stud","hole","screw"}.contains(kind),"Unsupported paired feature mirror: "+kind); const auto seeds=mapping[seed["id"].toString()].toObject()["features"].toArray(); require(!seeds.isEmpty(),"Left seed must precede its right mirror"); made.append(add("mirror",{{"plane","XZ"},{"offset",0},{"features",seeds}},name,original)); strategy="left-seed-feature-mirror-XZ"; }
            } else { made.append(add(kind,params,name,original)); strategy="unchanged-source-replay"; }
            mapping[identifier]=QJsonObject{{"name",name},{"primary",made.isEmpty()?QJsonValue(QJsonValue::Null):made.last()},{"features",made},{"strategy",strategy}};
        }
        const auto originalColors=props["feature_colors"].toObject(); for(auto iterator=originalColors.begin();iterator!=originalColors.end();++iterator) {
            if(!byId.contains(iterator.key())) { orphans[iterator.key()]=iterator.value(); continue; }
            const auto mapped=mapping[iterator.key()].toObject()["features"].toArray(); require(!mapped.isEmpty(),"Colored right auxiliary cannot be dropped"); for(const auto &identifier:mapped) colors[identifier.toString()]=iterator.value();
        }
    }

    QJsonValue remap(const QJsonValue &value,const QString &field={}) const {
        if(value.isString()&&featureId(value.toString())) { const auto mapped=mapping[value.toString()].toObject(); require(!mapped["primary"].isNull()&&mapped.contains("primary"),"Unresolved or omitted reference "+value.toString()+" in "+field); return mapped["primary"]; }
        if(value.isArray()) { QJsonArray result; for(const auto &item:value.toArray()) { if(field=="features") { const auto identifiers=mapping[item.toString()].toObject()["features"].toArray(); require(!identifiers.isEmpty(),"Omitted feature-list reference"); for(const auto &identifier:identifiers) result.append(identifier); } else result.append(remap(item,field)); } return result; }
        if(value.isObject()) { QJsonObject result; const auto object=value.toObject(); for(auto iterator=object.begin();iterator!=object.end();++iterator) result[iterator.key()]=remap(iterator.value(),iterator.key()); return result; } return value;
    }

    QString add(const QString &kind,QJsonObject params,const QString &name,const QJsonObject &original) {
        const QString identifier=document.add(kind,params,name); if(original["suppressed"].toBool()) document.suppress(identifier,true); params["name"]=name;
        rows.append(QJsonObject{{"cmd",kind},{"args",params},{"id",identifier},{"source_id",original["id"]},{"suppressed",original["suppressed"].toBool()},{"feature",document.find(identifier)}}); return identifier;
    }
    QJsonObject manifest() const { return {{"strategy_version",1},{"source_parameter_sha256",digest(source)},{"source_features",source["features"]},{"source_props",source["props"]},{"old_to_new",mapping},{"planned_B_features",document.features},{"mapped_feature_colors",colors},{"orphan_source_colors",orphans},{"limits",QJsonArray{"Exact cubic controls preserve the section; loft equivalence must be measured independently.","Finite boundary comparison never asserts exact equivalence.","Orphan colors are retained, not reassigned to unrelated IDs."}}}; }
};

QJsonValue aliasize(const QJsonValue &value,const QSet<QString> &aliases) { if(value.isString()&&aliases.contains(value.toString())) return '$'+value.toString(); if(value.isArray()) { QJsonArray result; for(const auto &item:value.toArray()) result.append(aliasize(item,aliases)); return result; } if(value.isObject()) { QJsonObject result; const auto object=value.toObject(); for(auto iterator=object.begin();iterator!=object.end();++iterator) result[iterator.key()]=aliasize(iterator.value(),aliases); return result; } return value; }

bool sameFeatures(const QJsonArray &actual,const QJsonArray &expected) { if(actual.size()!=expected.size()) return false; for(qsizetype index=0;index<actual.size();++index) { const auto first=actual[index].toObject(),second=expected[index].toObject(); for(const auto &key:QStringList{"id","type","name","params"}) if(first[key]!=second[key]) return false; if(first["suppressed"].toBool()!=second["suppressed"].toBool()) return false; } return true; }

QJsonObject expectedProps(const Plan &plan, int completed) {
    QJsonObject result; const auto source = plan.source["props"].toObject();
    for (const auto &key : QStringList{"material", "color"}) if (source.contains(key)) result[key] = source[key];
    QJsonObject colors; for (int index = 0; index < completed; ++index) { const QString identifier = plan.rows[index].toObject()["id"].toString(); if (plan.colors.contains(identifier)) colors[identifier] = plan.colors[identifier]; }
    if (!colors.isEmpty()) result["feature_colors"] = colors;
    return result;
}

bool sameState(const QJsonObject &actual, const QJsonArray &features, const QJsonObject &props) {
    if (!sameFeatures(actual["features"].toArray(), features) || (!actual["upto"].isNull() && actual.contains("upto"))) return false;
    auto normalized = actual["props"].toObject(); if (normalized["feature_colors"].toObject().isEmpty()) normalized.remove("feature_colors");
    return normalized == props;
}

void validateHistory(genform::Session &session) {
    const auto model = session.builder.query("model"); const auto statuses = model["status"].toObject();
    for (const auto &value : session.document.features) { const auto feature = value.toObject(); const auto status = statuses[feature["id"].toString()].toString(); require(status == "ok" || (feature["suppressed"].toBool() && status == "suppressed"), "Method B native build error: " + feature["name"].toString() + " / " + status); }
}

int journalSelfTest() {
    QTemporaryDir temporary; require(temporary.isValid(),"Cannot create journal self-test folder"); const QString path=temporary.filePath("progress.json"); const QJsonObject pending{{"key","batch-1"},{"expected_features",QJsonArray{QJsonObject{{"id","f1"},{"type","sketch"},{"name","test"},{"params",QJsonObject{}}}}}};
    saveObject(path,{{"pending",pending},{"done",QJsonArray{}}}); require(loadObject(path)["pending"]==pending,"Write-ahead journal roundtrip failed"); require(!sameFeatures({},pending["expected_features"].toArray()),"Partial action must not reconcile");
    auto committed=loadObject(path); committed["pending"]=QJsonValue::Null; committed["done"]=QJsonArray{"batch-1"}; saveObject(path,committed); require(loadObject(path)["done"].toArray().size()==1,"Journal commit failed"); QTextStream(stdout)<<"PASS: atomic write-ahead journal, partial-state rejection and commit\n"; return 0;
}
}

int alternate(const Options &options) {
    if(options.name.endsWith("alternate_runtime")||options.values["self-test"].toBool()) return journalSelfTest();
    const QString source=QFileInfo(options.values.value("source").toString(QDir(sourceRoot()).filePath("models/porsche_911_992/porsche_911_992.gform"))).absoluteFilePath();
    const auto data=loadObject(source); const Plan plan(data); const auto manifest=plan.manifest();
    if(!options.values["execute"].toBool()&&!options.values["resume"].toBool()) {
        QTextStream(stdout)<<QJsonDocument(QJsonObject{{"offline_preview",true},{"source_features",data["features"].toArray().size()},{"B_features",plan.rows.size()},{"source_parameter_sha256",digest(data)},{"manifest_sha256",digest(manifest)},{"orphan_colors",plan.orphans}}).toJson(QJsonDocument::Indented);
        if(!options.output.isEmpty()) saveObject(QDir(options.output).filePath("strategy.json"),manifest); return 0;
    }
    require(!options.output.isEmpty(),"Specify --output for method B; source A is never overwritten");
    require(!options.values["execute"].toBool()||options.values["new-document"].toBool(),"--execute requires explicit --new-document");
    const QDir output(options.output),folder(options.values.value("state-dir").toString(output.filePath("method_b.run"))); const QString destination=output.filePath("porsche_911_992_method_b.gform"),progress=folder.filePath("progress.json");
    require(QFileInfo(destination).absoluteFilePath()!=source,"A and B must differ"); const int batchSize=options.values.value("batch-size").toString("3").toInt(); require(batchSize>=2&&batchSize<=6,"Batch size must be 2..6");
    QJsonObject state; genform::Session session; int completed=0;
    if(options.values["resume"].toBool()) {
        state=loadObject(progress); require(state["source"]==source&&state["output"]==QFileInfo(destination).absoluteFilePath()&&state["batch_size"].toInt()==batchSize,"Resume paths/batch size differ from journal"); require(state["source_sha256"]==digest(data)&&state["plan_sha256"]==digest(manifest),"Source or plan changed; cannot mix revisions");
        const auto pending=state["pending"].toObject(); QString checkpoint=state["checkpoint"].toString();
        if(!pending.isEmpty()) {
            checkpoint=pending["checkpoint"].toString(); require(QFileInfo::exists(checkpoint),"Pending action is absent or uncertain; inspect checkpoint manually. No action is resent."); const auto saved=loadObject(checkpoint); require(sameState(saved,pending["expected_features"].toArray(),pending["expected_props"].toObject()),"Pending action parameters, colors or rollback diverged; not resent");
            state["completed_rows"]=pending["end"]; state["checkpoint"]=checkpoint; state["checkpoint_sha256"]=sha256(checkpoint); state["pending"]=QJsonValue::Null; saveObject(progress,state);
        }
        completed=state["completed_rows"].toInt(); require(completed >= 0 && completed <= plan.rows.size(), "Invalid completed-row count");
        require(!checkpoint.isEmpty()&&sha256(checkpoint)==state["checkpoint_sha256"].toString(),"Owned checkpoint integrity failure"); call(session,"open_document",{{"path",checkpoint}});
        QJsonArray expected; for(int index=0;index<completed;++index) expected.append(plan.rows[index].toObject()["feature"]); require(sameState(session.document.toData(),expected,expectedProps(plan,completed)),"Checkpoint does not match planned feature history/properties");
        if (state["complete"].toBool()) { require(QFileInfo::exists(destination) && sha256(destination) == state["output_sha256"].toString(), "Completed B output was changed or removed"); QTextStream(stdout) << "Already complete; verified output, no command resent\n"; return 0; }
        require(!QFileInfo::exists(destination), "Uncommitted final output exists; inspect it manually rather than overwrite");
    } else {
        require(!QFileInfo::exists(progress)&&!QFileInfo::exists(destination),"B/progress already exists; use --resume or a fresh output folder"); call(session,"new_document");
        const auto props=data["props"].toObject(); if(props.contains("material")) call(session,"set_material",{{"name",props["material"]}}); if(props.contains("color")) call(session,"set_appearance",{{"color",props["color"]}});
        const QString checkpoint = folder.filePath("checkpoints/rows_00000.gform"); require(!QFileInfo::exists(checkpoint), "Unowned initial checkpoint exists");
        call(session, "save_document", {{"path", checkpoint}}); require(sameState(loadObject(checkpoint), {}, expectedProps(plan, 0)), "Initial properties diverged");
        state={{"source",source},{"output",QFileInfo(destination).absoluteFilePath()},{"source_sha256",digest(data)},{"plan_sha256",digest(manifest)},{"batch_size",batchSize},{"completed_rows",0},{"checkpoint",checkpoint},{"checkpoint_sha256",sha256(checkpoint)},{"pending",QJsonValue::Null},{"execution","isolated native Session; never replaces a live UI document"}}; saveObject(progress,state);
    }
    saveObject(folder.filePath("strategy.json"),manifest);
    while(completed<plan.rows.size()) {
        require(digest(loadObject(source))==state["source_sha256"].toString(),"Source changed during method B build"); int end=completed,solids=0; QJsonArray steps; QSet<QString> aliases;
        while(end<plan.rows.size()&&end-completed<16&&solids<batchSize) { const auto planned=plan.rows[end].toObject(); const QString identifier=planned["id"].toString(); steps.append(QJsonObject{{"cmd",planned["cmd"]},{"as",identifier},{"args",aliasize(planned["args"],aliases)}}); aliases.insert(identifier); if(planned["suppressed"].toBool()) steps.append(QJsonObject{{"cmd","suppress_feature"},{"args",QJsonObject{{"id",'$'+identifier},{"suppressed",true}}}}); if(!auxiliary(planned["cmd"].toString())) ++solids; ++end; }
        QJsonArray expected; for(int index=0;index<end;++index) expected.append(plan.rows[index].toObject()["feature"]);
        const QString checkpoint=folder.filePath(QString("checkpoints/rows_%1.gform").arg(end,5,10,QChar('0'))); require(!QFileInfo::exists(checkpoint),"Unowned checkpoint exists: "+checkpoint);
        state["pending"]=QJsonObject{{"start",completed},{"end",end},{"checkpoint",checkpoint},{"expected_features",expected},{"expected_props",expectedProps(plan,end)},{"command","batch"},{"arguments",QJsonObject{{"steps",steps}}}}; saveObject(progress,state);
        call(session,"batch",{{"steps",steps}}); require(sameFeatures(session.document.features,expected),"Batch parameters diverged; journal retained and not replayed");
        for(int index=completed;index<end;++index) { const QString identifier=plan.rows[index].toObject()["id"].toString(); if(plan.colors.contains(identifier)) call(session,"set_appearance",{{"features",QJsonArray{identifier}},{"color",plan.colors[identifier]}}); }
        validateHistory(session); call(session,"save_document",{{"path",checkpoint}}); require(sameState(loadObject(checkpoint),expected,expectedProps(plan,end)),"Saved checkpoint differs from expected history/properties");
        completed=end; state["completed_rows"]=completed; state["checkpoint"]=checkpoint; state["checkpoint_sha256"]=sha256(checkpoint); state["pending"]=QJsonValue::Null; saveObject(progress,state);
        saveObject(folder.filePath("source_map.json"),{{"source_sha256",state["source_sha256"]},{"old_to_new",plan.mapping},{"completed_rows",completed},{"checkpoint",checkpoint}}); QTextStream(stdout)<<"CHECKPOINT "<<completed<<'/'<<plan.rows.size()<<'\n';
    }
    call(session,"save_document",{{"path",destination}}); state["complete"]=true; state["output_sha256"]=sha256(destination); saveObject(progress,state); QTextStream(stdout)<<"SAVED method B: "<<destination<<"; run porsche_911/compare independently\n"; return 0;
}
}
