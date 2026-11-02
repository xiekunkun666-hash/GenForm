#include "genform/controller/controller.hpp"
#include "genform/controller/manufacture_ui.hpp"
#include "genform/controller/sketch_editor.hpp"
#include "genform/platform/window_frame.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/view/viewport.hpp"
#include "genform/view/sheet.hpp"
#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QEvent>
#include <QFileInfo>
#include <QJsonDocument>
#include <QKeySequence>
#include <QMessageBox>
#include <QTimer>
#include <QUrl>
#include <algorithm>
#include <cmath>

namespace genform::controller {
namespace {
QString localPath(const QString &text) { const QUrl url(text); return url.isLocalFile() ? url.toLocalFile() : text; }
QJsonObject row(const QString &identifier, const QString &title, const QString &icon = {}) {
    return {{"id",identifier},{"title",title},{"tip",title},{"icon",icon.isEmpty() ? identifier : icon},{"enabled",true}};
}
QJsonObject field(const QString &key,const QString &label,const QString &type,const QJsonValue &value,const QJsonArray &options = {},const QString &unit = {}) {
    QJsonObject result{{"key",key},{"label",label},{"type",type},{"value",value},{"unit",unit}};
    if (!options.isEmpty()) result["options"]=options;
    return result;
}
QJsonArray options(const QStringList &names) {
    QJsonArray result; for (const auto &name : names) result.append(QJsonObject{{"value",name},{"label",name}}); return result;
}
QString titleOf(const QString &name) {
    static const QMap<QString,QString> names{{"sketch",QStringLiteral("草图")},{"extrude",QStringLiteral("拉伸凸台")},{"cut",QStringLiteral("拉伸切除")},
        {"fillet",QStringLiteral("圆角")},{"chamfer",QStringLiteral("倒角")},{"revolve",QStringLiteral("旋转")},{"sweep",QStringLiteral("扫描")},
        {"loft",QStringLiteral("放样")},{"shell",QStringLiteral("抽壳")},{"mirror",QStringLiteral("镜像")},{"plane",QStringLiteral("基准面")}};
    return names.value(name,name);
}
QJsonValue element(const QJsonArray &array, qsizetype index) { if (index>=0 && index<array.size() && array[index].toObject().value("id").toInt(-1)==index) return array[index]; for (const auto &value : array) if (value.toObject().value("id").toInt(-1)==index) return value; return {}; }
}

AppController::AppController(Session *session,QObject *parent) : QObject(parent),session_(session),
    simulation_(new SimulationBridge(session,this)),drawing_(new DrawingBridge(session,this)),editor_(new SketchEditor(this)) {
    view_={{"style","shaded_edges"},{"scene","auto"},{"section",false},{"sectionPlane","XZ"},{"sectionOffset",0.0},{"sectionFlip",false},
           {"perspective",false},{"cartoon",false},{"hideAll",false},{"color",""},{"saved",0}};
    actions_=actionCatalog(); for (const auto &entry : actions_) { const auto action=entry.toMap(); defaultKeys_[action.value("id").toString()]=action.value("default"); }
    keys_=defaultKeys_; const auto savedKeys=preferences_.value("shortcuts").toMap(); for (auto entry=savedKeys.begin();entry!=savedKeys.end();++entry) if (keys_.contains(entry.key())) keys_[entry.key()]=entry.value();
    recent_=preferences_.value("recent").toStringList(); dark_=preferences_.value("dark",true).toBool(); rapid_=preferences_.value("rapid",false).toBool();
    const auto storedSnaps=preferences_.value("snaps",QStringList{"end","mid","center","quad","int","near","hv","grid"}).toStringList(); snaps_.clear(); for (const auto &snap : storedSnaps) if (QStringList{"end","mid","center","quad","int","near","hv","grid"}.contains(snap)) snaps_.insert(snap); gridSnap_=snaps_.contains("grid");
    QString languageError; if (!translator_.setLanguage(preferences_.value("language","zh").toString(),&languageError)) QTimer::singleShot(0,this,[this,languageError] { Q_EMIT notice(languageError); });
    QCoreApplication::installTranslator(&translator_);
    if (!preferences_.error().isEmpty()) QTimer::singleShot(0,this,[this] { Q_EMIT notice(preferences_.error()); });
    connect(session_,&Session::changed,this,&AppController::refresh);
    connect(session_,&Session::progress,this,[this](int index,int total,const QString &name) {
        progress_={{"index",index},{"done",index},{"total",total},{"name",name},{"current",index},{"loading",false},{"what","features"},{"active",total>0},{"fraction",total>0 ? double(index)/total : 0.0}};
        Q_EMIT progressChanged(); Q_EMIT changed();
    });
    connect(simulation_,&SimulationBridge::notice,this,&AppController::notice);
    connect(simulation_,&SimulationBridge::changed,this,[this] { Q_EMIT changed(); });
    connect(simulation_,&SimulationBridge::modelChanged,this,[this](const QJsonObject &model) { if (kind_=="assembly" && viewport_) { viewport_->setModel(model); viewport_->setSelection(session_->selection); } Q_EMIT changed(); });
    connect(simulation_,&SimulationBridge::assemblyActivated,this,[this] { kind_="assembly"; tab_="assembly"; start_=false; form_={}; Q_EMIT kindChanged(); Q_EMIT startChanged(); refresh(); if (viewport_) viewport_->fit(); });
    connect(simulation_,&SimulationBridge::openPartRequested,this,&AppController::openDocument);
    connect(drawing_,&DrawingBridge::notice,this,&AppController::notice);
    connect(drawing_,&DrawingBridge::changed,this,[this] { Q_EMIT changed(); });
    connect(editor_,&SketchEditor::error,this,&AppController::notice);
    connect(editor_,&SketchEditor::shapesChanged,this,&AppController::receiveSketch);
    connect(editor_,&SketchEditor::selectionChanged,this,&AppController::syncEditorUi);
    connect(editor_,&SketchEditor::toolChanged,this,&AppController::syncEditorUi);
    connect(editor_,&SketchEditor::visualChanged,this,&AppController::syncEditorUi);
    session_->viewCommand=[this](const QString &command,const QJsonObject &arguments) { return viewCommand(command,arguments); };
}
void AppController::attach(QWindow *window,view::Viewport *viewport,view::SheetView *sheet) {
    window_=window; viewport_=viewport; drawing_->attach(sheet);
    if (window_) window_->installEventFilter(this);
    if (viewport_) viewport_->setEditor(editor_);
    if (!viewport_) { Q_EMIT notice(QStringLiteral("QML Viewport 没有实例化。")); return; }
    connect(viewport_,&view::Viewport::picked,this,&AppController::selected);
    connect(viewport_,&view::Viewport::boxed,this,[this](const QJsonArray &faces,bool additive) { selected({{"faces",faces},{"edges",QJsonArray{}}},additive); });
    connect(viewport_,&view::Viewport::sketchEdited,this,&AppController::receiveSketch);
    connect(viewport_,&view::Viewport::sketchSelectionChanged,this,[this](int index) { selectedShape_=index; Q_EMIT changed(); });
    connect(viewport_,&view::Viewport::quickSnapConsumed,this,[this] { quickSnap_.clear(); Q_EMIT changed(); });
    connect(viewport_,&view::Viewport::hoverChanged,this,[this](const QString &text) { hover_=text; Q_EMIT hoverTextChanged(); });
    connect(viewport_,&view::Viewport::contextPicked,this,[this](const QJsonObject &,double x,double y) {
        if (!sketch_ && !pickingPlane_ && form_.isEmpty() && !measuring_ && !value("sceneContext").toList().isEmpty()) Q_EMIT contextRequested(x,y);
        else Q_EMIT contextRequested(-1,-1);
    });
    connect(viewport_,&view::Viewport::doublePicked,this,[this](const QJsonObject &selection) {
        if (sketch_ || pickingPlane_ || !form_.isEmpty() || measuring_ || kind_!="part") return;
        if (selection.contains("plane")) sketchOn(selection.value("plane").toString());
        else if (!selection.value("feature").toString().isEmpty()) editFeature(selection.value("feature").toString());
    });
    connect(viewport_,&view::Viewport::menuRequested,this,[this](const QString &identifier,double x,double y) { if (!identifier.isEmpty()) selectFeature(identifier); Q_EMIT viewMenuRequested(identifier,x,y); });
    viewport_->setView("iso"); refresh();
}
void AppController::refresh() {
    Q_EMIT treeAboutToChange();
    if (viewport_) {
        viewport_->setModel(kind_=="assembly"?simulation_->displayModel():session_->model); viewport_->setSelection(session_->selection); viewport_->setHidden(hidden_);
        auto color=session_->document.props.value("color").toString();
        if (color.isEmpty()) for (const auto &value : domain::material_catalog()) { const auto material=value.toObject(); if (material.value("name")==session_->document.props.value("material")) { color=material.value("color").toString(); break; } }
        viewport_->setColor(color.isEmpty()?QColor("#91abc6"):QColor(color));
        viewport_->setAppearance(session_->document.props);
    }
    if (!session_->busy) progress_={};
    Q_EMIT changed(); Q_EMIT treeChanged(); Q_EMIT progressChanged();
}
void AppController::unsupported(const QString &command) { Q_EMIT notice(QStringLiteral("此功能尚未原生迁移：%1").arg(command)); }
QJsonObject AppController::execute(const QString &command,const QJsonObject &arguments) {
    QJsonObject result;
    try { result=session_->execute(command,arguments); }
    catch (const std::exception &exception) { result={{"ok",false},{"error",QString::fromUtf8(exception.what())}}; }
    if (!result.value("ok").toBool()) Q_EMIT notice(result.value("error").toString(QStringLiteral("命令失败：%1").arg(command)));
    refresh(); return result;
}
QVariantList AppController::treeRows() const {
    QVariantList result;
    const auto make=[&](const QString &kind,const QString &identifier,const QString &name,int depth) {
        return QVariantMap{{"kind",kind},{"id",identifier},{"name",name},{"type",kind},{"depth",depth},{"state","ok"},{"note",""},
            {"suppressed",false},{"selected",false},{"rolled",false},{"editing",false},{"expandable",false},{"expanded",true},{"line",false},
            {"child",false},{"folders",0},{"mark",""},{"tint","#57b894"},{"process",""},{"processColor",""},{"processName",""},{"processWhy",""},{"processAuto",false},{"flagged",false}};
    };
    QString name=QFileInfo(session_->document.path).completeBaseName(); if (name.isEmpty()) name=QStringLiteral("零件1");
    result.append(make("root","",name,0));
    result.append(make("material","",QStringLiteral("材质 <%1>").arg(session_->document.props.value("material").toString(QStringLiteral("未指定"))),1));
    for (const auto &plane : {QString("XZ"),QString("XY"),QString("YZ")}) {
        auto item=make("plane",plane,plane+QStringLiteral(" 基准面"),1); item["shown"]=viewport_ && viewport_->planeVisible(plane);
        item["selected"]=session_->selection.value("plane").toString()==plane; result.append(item);
    }
    result.append(make("origin","",QStringLiteral("原点"),1));
    const auto statuses=session_->model.value("status").toObject();
    for (qsizetype index=0;index<session_->document.features.size();++index) {
        const auto feature=session_->document.features[index].toObject(); const auto identifier=feature.value("id").toString();
        auto item=make("feature",identifier,feature.value("name").toString(),1);
        const auto status=statuses.value(identifier).toString("pending");
        item["state"]=status.startsWith("error:") ? "error" : status; item["note"]=status.startsWith("error:") ? status.mid(6) : QString();
        item["type"]=feature.value("type").toString(); item["selected"]=session_->selection.value("feature").toString()==identifier;
        item["shown"]=!hidden_.contains(identifier); item["suppressed"]=feature.value("suppressed").toBool();
        item["rolled"]=session_->document.upto && index>=*session_->document.upto;
        item["editing"]=sketch_ && editingSketch_==identifier; item["before"]=index; item["after"]=index+1;
        item["line"]=feature.value("type").toString()=="sketch"; item["icon"]=feature.value("type").toString();
        const auto process=feature.value("process").toObject();
        item["process"]=process.value("short").toString(); item["processColor"]=process.value("color").toString();
        item["processName"]=process.value("name").toString(); item["processWhy"]=process.value("why").toString();
        item["processAuto"]=process.value("auto").toBool();
        result.append(item);
    }
    if (sketch_ && editingSketch_.isEmpty()) { auto item=make("feature","",QStringLiteral("新草图（编辑中）"),1); item["editing"]=true; item["type"]="sketch"; result.append(item); }
    auto rollback=make("rollback","",QStringLiteral("回退"),0); rollback["count"]=session_->document.upto.value_or(session_->document.features.size()); rollback["total"]=session_->document.features.size(); result.append(rollback);
    return result;
}
QVariantList AppController::toolRows() const {
    QVariantList result;
    for (auto iterator=keys_.begin();iterator!=keys_.end();++iterator) if (!iterator.value().toString().isEmpty()) result.append(QVariantMap{{"id",iterator.key()},{"key",iterator.value()}});
    return result;
}
QVariant AppController::value(const QString &key) const {
    if (key=="title") {
        QString path=kind_=="drawing" ? drawing_->path() : kind_=="assembly"?simulation_->path():session_->document.path;
        return (path.isEmpty() ? (kind_=="drawing" ? QStringLiteral("工程图1") : kind_=="assembly"?QStringLiteral("装配体1"):QStringLiteral("零件1")) : QFileInfo(path).fileName())
            + ((kind_=="drawing" ? drawing_->dirty() : kind_=="assembly"?simulation_->dirty():session_->document.dirty) ? " *" : "");
    }
    if (key=="docKind") return kind_;
    if (key=="tab") return tab_;
    if (key=="tree") return treeRows();
    if (key=="startPage") return start_;
    if (key=="busy") return session_->busy;
    if (key=="canUndo") return sketch_ ? !sketchUndo_.isEmpty() : kind_=="drawing"?false:kind_=="assembly"?simulation_->canUndo():session_->document.canUndo();
    if (key=="canRedo") return sketch_ ? !sketchRedo_.isEmpty() : kind_=="drawing"?false:kind_=="assembly"?simulation_->canRedo():session_->document.canRedo();
    if (key=="form") return form_.isEmpty() ? QVariant::fromValue(nullptr) : QVariant(featureForm().toVariantMap());
    if (key=="previewNote") return previewNote_;
    if (key=="bodyText") {
        const auto model=kind_=="assembly"?simulation_->displayModel():session_->model;
        if (!model.value("has_body").toBool()) return QStringLiteral("无实体");
        const auto properties=model.value("props").toObject();
        return QStringLiteral("%1 个面 · 体积 %2 mm³").arg(model.value("faces").toArray().size()).arg(properties.value("volume").toDouble(),0,'g',6);
    }
    if (key=="selectionText") {
        const auto faces=session_->selection.value("faces").toArray(),edges=session_->selection.value("edges").toArray();
        if (!faces.isEmpty() || !edges.isEmpty()) return QStringLiteral("%1 面 · %2 边").arg(faces.size()).arg(edges.size());
        return featureName(session_->selection.value("feature").toString());
    }
    if (key=="hoverText") return hover_;
    if (key=="progress") return progress_.isEmpty() ? QVariant(QVariantMap{{"loading",false},{"total",0},{"done",0},{"name",""},{"what","features"},{"fraction",0.0}}) : QVariant(progress_.toVariantMap());
    if (key=="sketchActive") return sketch_;
    if (key=="sketchTool") return sketchTool_;
    if (key=="sketchTitle") return sketch_ ? QStringLiteral("草图 %1 · %2").arg(plane_,titleOf(sketchTool_)) : QString();
    if (key=="sketchOperation") return sketch_ ? editor_->operation() : QString();
    if (key=="rapidSketch") return rapid_;
    if (key=="pickingPlane") return pickingPlane_;
    if (key=="hint") return pickingPlane_ ? QStringLiteral("选择 XY / XZ / YZ 基准面") : sketch_ ? QStringLiteral("按序点击绘制；Enter / 双击结束曲线；Ctrl 加选；拖框选择；Esc 取消当前操作") : QStringLiteral("中键旋转 · Ctrl+中键平移 · 滚轮缩放");
    if (key=="sketchProps") {
        if (!sketch_) return QVariant::fromValue(nullptr);
        const auto properties=editor_->properties(); return properties.isEmpty()?QVariant::fromValue(nullptr):QVariant(properties.toVariantMap());
    }
    if (key=="quickSnap") return quickSnap_;
    if (key=="quickSnaps" || key=="snapToggles") { QVariantList rows; const QMap<QString,QString> names{{"end",QStringLiteral("端点")},{"mid",QStringLiteral("中点")},{"center",QStringLiteral("中心点")},{"quad",QStringLiteral("象限点")},{"int",QStringLiteral("交叉点")},{"near",QStringLiteral("最近端（线上）")},{"hv",QStringLiteral("水平 / 竖直")},{"grid",QStringLiteral("网格")}}; for (const auto &kind : QStringList{"end","mid","center","quad","int","near","hv","grid"}) { if (key=="quickSnaps" && (kind=="hv" || kind=="grid")) continue; rows.append(QVariantMap{{"id",kind},{"text",names.value(kind)},{"on",snaps_.contains(kind)}}); } return rows; }
    if (key=="planeChoices") return QJsonArray{row("XY","XY"),row("XZ","XZ"),row("YZ","YZ")}.toVariantList();
    if (key=="featureMenus") {
        QJsonArray groups;
        const QList<QStringList> names{{"hole","hole_adv","thread","stud","screw"},{"pattern_linear","pattern_circular","mirror","pattern_curve","pattern_sketch","pattern_table","pattern_fill","pattern_variable"},
            {"plane","axis","csys","point","com","bbox","variables"},{"split","curve_project","curve_composite","curve_xyz","curve_points","curve_helix"},{"sketch3d","curve_surface"}};
        for (const auto &group : names) { QJsonArray items; for (const auto &name : group) items.append(row(name,titleOf(name))); groups.append(QJsonObject{{"items",items}}); }
        return groups.toVariantList();
    }
    if (key=="viewState") { auto state=view_; state["saved"]=savedViews_.size(); state["color"]=session_->document.props.value("color"); return state.toVariantMap(); }
    if (key=="orientations") {
        QJsonArray items; for (const auto &name : {QString("front"),QString("back"),QString("left"),QString("right"),QString("top"),QString("bottom"),QString("iso"),QString("normal")}) items.append(row(name,name,"cube"));
        items.append(row("save_view",QStringLiteral("保存当前视角"),"cube"));
        for (qsizetype index=0;index<savedViews_.size();++index) items.append(row("view:"+QString::number(index),QStringLiteral("视角 %1").arg(index+1),"cube"));
        return items.toVariantList();
    }
    if (key=="displayStyles") return QJsonArray{row("shaded_edges",QStringLiteral("带边线上色")),row("shaded",QStringLiteral("上色")),row("wire",QStringLiteral("线架图"))}.toVariantList();
    if (key=="sceneNames") return QJsonArray{row("auto",QStringLiteral("跟随主题"),"scene")}.toVariantList();
    if (key=="showItems") return QVariantList{QVariantMap{{"id","main_planes"},{"title",QStringLiteral("基准面")},{"icon","reference"},{"checked",viewport_ && viewport_->planesVisible()}}};
    if (key=="appearanceColors") return QVariantList{QStringLiteral("#91abc6"),QStringLiteral("#b6b8bc"),QStringLiteral("#d6a354"),QStringLiteral("#578a67"),QStringLiteral("#b36d65")};
    if (key=="materialList") { QJsonArray rows{row("",QStringLiteral("未指定"),"material")}; for (const auto &value : domain::material_catalog()) { const auto material=value.toObject(); const auto name=material.value("name").toString(); rows.append(row(name,name,"material")); } return rows.toVariantList(); }
    if (key=="sceneContext") {
        const auto plane=session_->selection.value("plane").toString();
        if (!plane.isEmpty()) return QJsonArray{row("sketch",QStringLiteral("绘制草图"),"sketch"),row("toggle",viewport_ && viewport_->planeVisible(plane)?QStringLiteral("隐藏"):QStringLiteral("显示"),"eye"),row("zoom",QStringLiteral("缩放到选择"),"fit"),row("normal",QStringLiteral("正视"),"front")}.toVariantList();
        if (kind_=="assembly") return simulation_->partContext(simulation_->value("picked").toInt());
        return featureContext(session_->selection.value("feature").toString());
    }
    if (key=="sceneTarget") { const auto plane=session_->selection.value("plane").toString(); return !plane.isEmpty()?"plane:"+plane:kind_=="assembly"?"part:"+QString::number(simulation_->value("picked").toInt()):session_->selection.value("feature").toString(); }
    if (key=="recentFiles") {
        QVariantList items; for (const auto &path : recent_) {
            const QFileInfo info(path); items.append(QVariantMap{{"path",path},{"name",info.completeBaseName()},{"folder",info.absolutePath()},{"kind",info.suffix()=="gdrw" ? "drawing" : info.suffix()=="gasm" ? "assembly" : "part"},{"time",info.lastModified().toString("yyyy-MM-dd hh:mm")}});
        } return items;
    }
    if (key=="shortcuts") return toolRows();
    if (key=="keyMap") return keys_;
    if (key=="actionTable") { QVariantList result; for (const auto &entry : actions_) { auto action=entry.toMap(); const auto identifier=action.value("id").toString(); action["key"]=keys_.value(identifier); action["changed"]=keys_.value(identifier)!=defaultKeys_.value(identifier); result.append(action); } return result; }
    if (key=="actionGroups") return QStringList{QStringLiteral("文件"),QStringLiteral("编辑"),QStringLiteral("特征"),QStringLiteral("草图"),QStringLiteral("评估"),QStringLiteral("仿真"),QStringLiteral("视图")};
    if (key=="settings") return QVariantMap{{"dark",dark_},{"snaps",QStringList(snaps_.values())},{"rapid",rapid_},{"language",translator_.language()}};
    if (key=="settingsPath") return preferences_.fileName();
    if (key=="language") return translator_.language();
    if (key=="languages") return QJsonArray{row("zh",QStringLiteral("中文")),row("en","English")}.toVariantList();
    if (key=="aiGuide") return QVariantMap{{"port",apiPort_},{"claude",QStringLiteral("原生 API 与 GUI 共用 Session。")},{"mcp","genform_mcp"},{"raw",apiPort_ ? QStringLiteral("127.0.0.1:%1").arg(apiPort_) : QStringLiteral("API 未启动")},{"doc",QStringLiteral("原生命令与 GUI 共用 Session。")}};
    if (key=="measure") return measurement_.isEmpty() ? QVariant(QVariantMap{{"rows",QVariantList{}},{"hint",""},{"error",""}}) : QVariant(measurement_);
    if (key=="measuring") return measuring_;
    if (key=="checkOpen") return manufactureUi()->isOpen();
    if (key=="checkHighlight") return manufactureUi()->highlight();
    if (key=="checkCompleted") return manufactureUi()->completed();
    if (key=="checkIssues") return manufactureUi()->issues().toVariantList();
    if (key=="checkCounts") return manufactureUi()->counts().toVariantMap();
    if (key=="checkBusy") return manufactureUi()->busy();
    if (key=="checkStale") return manufactureUi()->stale();
    if (key=="binding") return manufactureUi()->binding();
    if (key=="designRules") return manufactureUi()->designRules();
    if (key=="gestureWheels") return QVariantMap{{"model",QVariantList{}},{"sketch",QVariantList{}}};
    if (key=="returnAssembly") return kind_!="assembly" && !simulation_->value("assembly").toList().isEmpty()?simulation_->value("assemblyName").toString():QString();
    if (key=="layoutSketches" || key=="gestures") return QVariantList{};
    return QString();
}
bool AppController::confirmDiscard() {
    if (sketch_) { Q_EMIT notice(QStringLiteral("请先完成或取消当前草图。")); return false; }
    const bool dirty=kind_=="drawing" ? drawing_->dirty() : kind_=="assembly"?simulation_->dirty():session_->document.dirty;
    if (!dirty) return true;
    QMessageBox dialog(QMessageBox::Warning,QStringLiteral("GenForm"),QStringLiteral("当前文档尚未保存。放弃修改？"),QMessageBox::Discard|QMessageBox::Cancel);
    dialog.setDefaultButton(QMessageBox::Cancel); return dialog.exec()==QMessageBox::Discard;
}
bool AppController::eventFilter(QObject *watched,QEvent *event) {
    if (watched==window_ && event->type()==QEvent::Close && !confirmDiscard()) { event->ignore(); return true; }
    return QObject::eventFilter(watched,event);
}
void AppController::newOf(const QString &kind) {
    if (kind!="part" && kind!="drawing" && kind!="assembly") { unsupported("new:"+kind); return; }
    if (!confirmDiscard()) return;
    if (kind=="assembly") { simulation_->beginAssembly(); return; }
    if (kind=="part") { const auto result=execute("new_document"); if (!result.value("ok").toBool()) return; simulation_->close(); }
    else { drawing_->begin(); if (session_->model.value("has_body").toBool()) drawing_->project(); }
    kind_=kind; tab_=kind=="drawing" ? "drawing" : "feature"; start_=false; form_={};
    Q_EMIT kindChanged(); Q_EMIT startChanged(); refresh();
}
void AppController::showStart() { if (!confirmDiscard()) return; start_=true; Q_EMIT startChanged(); Q_EMIT changed(); }
void AppController::remember(const QString &path) {
    recent_.removeAll(path); recent_.prepend(path); while (recent_.size()>20) recent_.removeLast(); preferences_.setValue("recent",recent_); Q_EMIT startChanged();
}
void AppController::openDocument(const QString &where) {
    const auto path=localPath(where); if (path.isEmpty() || !confirmDiscard()) return;
    const auto suffix=QFileInfo(path).suffix().toLower();
    if (suffix=="gasm") { if (simulation_->openAssembly(path)) remember(path); return; }
    if (suffix=="gdrw") { if (!drawing_->open(path)) return; kind_="drawing"; tab_="drawing"; }
    else {
        QJsonObject result;
        if (suffix=="step" || suffix=="stp" || suffix=="stl") {
            if (!session_->document.features.isEmpty()) {
                result=execute("new_document"); if (!result.value("ok").toBool()) return;
            }
            result=execute(suffix=="stl" ? "import_stl" : "import_step",{{"path",path}});
        } else result=execute("open_document",{{"path",path}});
        if (!result.value("ok").toBool() && session_->document.path!=path) return;
        kind_="part"; tab_="feature"; simulation_->close();
    }
    start_=false; form_={}; remember(path); Q_EMIT kindChanged(); Q_EMIT startChanged(); refresh(); if (viewport_) viewport_->fit();
}
void AppController::openFiles(const QVariantList &paths) {
    if (paths.size()==1 && QStringList{"gasm","gdrw"}.contains(QFileInfo(localPath(paths.front().toString())).suffix().toLower())) { openDocument(paths.front().toString()); return; }
    if (kind_=="assembly") { simulation_->addParts(paths); return; }
    if (paths.size()!=1) { Q_EMIT notice(QStringLiteral("请新建装配体后插入多个零件；当前零件文档一次打开一个文件。")); return; }
    openDocument(paths.front().toString());
}
void AppController::dropFiles(const QVariantList &paths) { openFiles(paths); }
void AppController::saveDocument(const QString &where) {
    if (sketch_) { Q_EMIT notice(QStringLiteral("请先完成草图再保存文档。")); return; }
    auto path=localPath(where);
    if (path.isEmpty()) path=kind_=="drawing" ? drawing_->path() : kind_=="assembly"?simulation_->path():session_->document.path;
    if (path.isEmpty()) { Q_EMIT dialogRequested("save"); return; }
    if (kind_=="assembly") { if (simulation_->saveAssembly(path)) remember(simulation_->path()); }
    else if (kind_=="drawing") { if (drawing_->save(path)) remember(drawing_->path()); }
    else {
        if (!path.endsWith(".gform",Qt::CaseInsensitive)) path+=".gform";
        if (execute("save_document",{{"path",path}}).value("ok").toBool()) { remember(path); Q_EMIT notice(QStringLiteral("已保存：%1").arg(path)); }
    }
    refresh();
}
void AppController::exportModel(const QString &where) {
    const auto path=localPath(where);
    if (kind_=="drawing") { if (drawing_->exportFile(path)) Q_EMIT notice(QStringLiteral("工程图已导出：%1").arg(path)); }
    else if (kind_=="assembly") { if (simulation_->exportAssembly(path)) Q_EMIT notice(QStringLiteral("装配体已导出：%1").arg(path)); }
    else if (execute("export",{{"path",path}}).value("ok").toBool()) Q_EMIT notice(QStringLiteral("模型已导出：%1").arg(path));
}
void AppController::forgetRecent(const QString &path) { recent_.removeAll(path); preferences_.setValue("recent",recent_); Q_EMIT startChanged(); Q_EMIT changed(); }
void AppController::setTab(const QString &tab) { tab_=tab; Q_EMIT changed(); }
void AppController::runAction(const QString &identifier) {
    if (identifier.startsWith("cmd:")) { startCommand(identifier.mid(4)); return; }
    if (identifier.startsWith("tool:")) { useSketchTool(identifier.mid(5)); return; }
    if (identifier.startsWith("view:")) { viewAction(identifier.mid(5)); return; }
    if (identifier.startsWith("style:")) { setDisplayStyle(identifier.mid(6)); return; }
    if (identifier=="file.new") Q_EMIT dialogRequested("new");
    else if (identifier=="file.open") Q_EMIT dialogRequested("open");
    else if (identifier=="file.save") saveDocument("");
    else if (identifier=="file.export") Q_EMIT dialogRequested("export");
    else if (identifier=="app.settings") Q_EMIT dialogRequested("settings");
    else if (identifier=="edit.undo") undo();
    else if (identifier=="edit.redo") redo();
    else if (identifier=="edit.delete") { if (kind_=="drawing") drawing_->deleteSelected(); else if (sketch_) sketchAction("delete"); else if (kind_=="assembly") { const auto joint=simulation_->value("pickedJoint").toInt(); const auto part=simulation_->value("picked").toInt(); if (joint>=0) simulation_->deleteJoint(joint); else if (part>=0) simulation_->removePart(part); } else deleteFeature(session_->selection.value("feature").toString()); }
    else if (identifier=="sketch.start") startSketch();
    else if (identifier=="sketch.finish") finishSketch();
    else if (identifier=="sketch.cancel") cancelSketch();
    else if (identifier=="sketch.rapid") toggleRapidSketch();
    else if (identifier.startsWith("sketch.") && QStringList{"pattern","cpattern","relation","repair","silhouette","section"}.contains(identifier.mid(7))) sketchPick(identifier.mid(7));
    else if (identifier=="eval.measure") toggleMeasure();
    else if (identifier=="eval.check") runCheck();
    else if (identifier=="eval.process") bindProcesses();
    else if (identifier.startsWith("sim.")) simulation_->open(identifier.mid(4));
    else if (identifier=="view.planes") toggleShow("main_planes");
    else if (identifier=="view.section") toggleViewSetting("section");
    else if (identifier=="view.perspective") toggleViewSetting("perspective");
    else unsupported(identifier);
}
void AppController::undo() {
    if (!sketch_ && kind_=="drawing") { unsupported("drawing undo"); return; }
    if (!sketch_ && kind_=="assembly") { simulation_->undoAssembly(); return; }
    if (!sketch_) { execute("undo"); return; }
    if (sketchUndo_.isEmpty()) return;
    sketchRedo_.append(shapes_); shapes_=sketchUndo_.takeLast(); selectedShape_=-1; editor_->setSelection({}); pushSketch();
}
void AppController::redo() {
    if (!sketch_ && kind_=="drawing") { unsupported("drawing redo"); return; }
    if (!sketch_ && kind_=="assembly") { simulation_->redoAssembly(); return; }
    if (!sketch_) { execute("redo"); return; }
    if (sketchRedo_.isEmpty()) return;
    sketchUndo_.append(shapes_); shapes_=sketchRedo_.takeLast(); selectedShape_=-1; editor_->setSelection({}); pushSketch();
}
void AppController::escape() {
    if (viewport_) viewport_->cancelInteraction();
    Q_EMIT contextRequested(-1,-1);
    if (measuring_) { measuring_=false; Q_EMIT measureChanged(); Q_EMIT changed(); return; }
    if (!form_.isEmpty()) { cancelForm(); return; }
    if (pickingPlane_) { pickingPlane_=false; Q_EMIT changed(); return; }
    if (sketch_) { editor_->escape(); syncEditorUi(); return; }
    session_->selection={}; if (viewport_) viewport_->setSelection({}); if (kind_=="assembly") simulation_->selectPart(-1); else simulation_->close(); Q_EMIT contextRequested(-1,-1); Q_EMIT changed();
}
void AppController::enterKey() { if (!form_.isEmpty()) acceptForm(); else if (sketch_) { if (editor_->drafting()) editor_->finishDraft(); else if (editor_->tool()!="select") useSketchTool("select"); else finishSketch(); } }
void AppController::toggleMaximize() { if (!window_ || platform::toggleNativeMaximize(window_)) return; if (window_->visibility()==QWindow::Maximized || window_->visibility()==QWindow::FullScreen) window_->showNormal(); else window_->showMaximized(); }
void AppController::minimizeWindow() { if (!window_ || platform::minimizeNativeWindow(window_)) return; window_->setWindowStates(window_->windowStates()|Qt::WindowMinimized); }
void AppController::restoreWindow() { if (!window_ || platform::restoreNativeWindow(window_)) return; window_->showNormal(); }

void AppController::makeForm(const QString &requested,const QString &editing) {
    createFeatureForm(requested,editing);
}
void AppController::startCommand(const QString &command) {
    if (kind_!="part") { unsupported(command); return; }
    if (sketch_) { finishingCommand_=true; finishSketch(); finishingCommand_=false; if (sketch_) return; }
    start_=false; makeForm(command); Q_EMIT startChanged();
}
void AppController::editFeature(const QString &identifier) {
    if (sketch_) { Q_EMIT notice(QStringLiteral("请先完成或取消当前草图，再编辑其他特征。")); return; }
    try {
        const auto feature=session_->document.find(identifier);
        if (feature.value("type").toString()=="sketch") {
            sketchParams_=feature.value("params").toObject(); const auto plane=sketchParams_.value("plane").toString("XY");
            if (!QStringList{"XY","XZ","YZ"}.contains(plane)) { unsupported("sketch on reference plane"); return; }
            sketchTurned_=!rapid_; editingSketch_=identifier; plane_=plane; shapes_=sketchParams_.value("shapes").toArray(); sketch_=true; pickingPlane_=false; selectedShape_=-1;
            if (viewport_) viewport_->setSketchOwner(editingSketch_);
            sketchUndo_.clear(); sketchRedo_.clear(); form_={}; tab_="sketch"; sketchTool_="select"; editor_->reset(shapes_); pushSketch();
        } else { if (pickingPlane_) { pickingPlane_=false; Q_EMIT sketchChanged(); } makeForm(feature.value("type").toString(),identifier); }
    } catch (const std::exception &exception) { Q_EMIT notice(QString::fromUtf8(exception.what())); }
}
void AppController::deleteFeature(const QString &identifier) { if (identifier.isEmpty()) { Q_EMIT notice(QStringLiteral("请先选择特征。")); return; } execute("delete_feature",{{"id",identifier}}); }
void AppController::renameFeature(const QString &identifier,const QString &name) { execute("rename_feature",{{"id",identifier},{"name",name}}); }
void AppController::toggleSuppress(const QString &identifier) {
    try { execute("suppress_feature",{{"id",identifier},{"suppressed",!session_->document.find(identifier).value("suppressed").toBool()}}); }
    catch (const std::exception &exception) { Q_EMIT notice(QString::fromUtf8(exception.what())); }
}
void AppController::rollbackTo(int count) { execute("rollback",count<0 ? QJsonObject{} : QJsonObject{{"count",count}}); }
void AppController::selectFeature(const QString &identifier) { selected({{"feature",identifier},{"faces",QJsonArray{}},{"edges",QJsonArray{}}},false); }
void AppController::selectPlane(const QString &plane) {
    if (sketch_) { Q_EMIT notice(QStringLiteral("正在编辑草图；参考基准面的选择不会切换当前草图平面。")); return; }
    if (pickingPlane_) { sketchOn(plane); return; }
    selected({{"plane",plane},{"faces",QJsonArray{}},{"edges",QJsonArray{}}},false);
}
void AppController::selected(const QJsonObject &selection,bool additive) {
    if (sketch_) { Q_EMIT notice(QStringLiteral("请先完成或取消当前草图，再选择模型特征。")); return; }
    if (pickingPlane_ && !selection.contains("plane")) return;
    if (takeFeatureFormSelection(selection,additive)) return;
    const auto previous=session_->selection;
    if (kind_=="assembly" && selection.value("feature").toString().startsWith("part:")) { simulation_->selectPart(selection.value("feature").toString().mid(5).toInt()); if (additive) session_->selection=previous; }
    else if (kind_=="assembly" && !additive) simulation_->selectPart(-1);
    if (additive) {
        auto merged=session_->selection;
        for (const auto &key : {QString("faces"),QString("edges")}) {
            auto chosen=merged.value(key).toArray();
            for (const auto &value : selection.value(key).toArray()) { const auto position=std::find(chosen.begin(),chosen.end(),value); if (position==chosen.end()) chosen.append(value); else chosen.removeAt(std::distance(chosen.begin(),position)); }
            merged[key]=chosen;
        }
        merged["feature"]=selection.value("feature"); session_->selection=merged;
    } else session_->selection=selection;
    if (pickingPlane_ && selection.contains("plane")) { sketchOn(selection.value("plane").toString()); return; }
    if (!form_.isEmpty()) Q_EMIT formChanged();
    if (viewport_) viewport_->setSelection(session_->selection);
    if (measuring_) measureSelection();
    Q_EMIT changed(); Q_EMIT treeChanged();
}
void AppController::setField(const QString &key,const QVariant &value) {
    if (sketch_) { editor_->setField(key,QJsonValue::fromVariant(value)); syncEditorUi(); return; }
    setFormFields({{key,value}});
}
void AppController::acceptForm() {
    if (form_.isEmpty()) return;
    if (sketch_ && !editor_->operation().isEmpty()) { editor_->acceptOperation(); syncEditorUi(); return; }
    acceptFeatureForm();
}
void AppController::cancelForm() { if (sketch_) editor_->cancelOperation(); form_={}; previewNote_.clear(); Q_EMIT formChanged(); Q_EMIT changed(); }
QString AppController::featureName(const QString &identifier) const { if (identifier.isEmpty()) return {}; try { return session_->document.find(identifier).value("name").toString(); } catch (...) { return identifier; } }
QVariantList AppController::featureContext(const QString &identifier) const {
    if (identifier.isEmpty()) return {};
    return QJsonArray{row("edit",QStringLiteral("编辑"),"edit"),row("hide",hidden_.contains(identifier)?QStringLiteral("显示"):QStringLiteral("隐藏"),"eye"),row("suppress",QStringLiteral("压缩/恢复"),"suppress"),row("delete",QStringLiteral("删除"),"delete")}.toVariantList();
}
QVariantList AppController::featureMenu(const QString &identifier) const { return featureContext(identifier); }
QVariantList AppController::treeMenu(const QString &kind,const QString &identifier) const {
    if (kind=="plane") return QJsonArray{row("sketch",QStringLiteral("绘制草图"),"sketch"),row("normal",QStringLiteral("正视"),"front")}.toVariantList();
    if (kind=="root") return QJsonArray{row("sketch",QStringLiteral("绘制草图"),"sketch"),row("fit",QStringLiteral("缩放到合适"),"fit")}.toVariantList();
    return featureContext(identifier);
}
void AppController::contextAction(const QString &identifier,const QString &action) { applyContext(action,identifier); }
void AppController::treeAction(const QString &kind,const QString &identifier,const QString &action) {
    if (kind=="plane") { planeAction(identifier,action); return; }
    if (kind=="root" && action=="sketch") { startSketch(); return; }
    if (kind=="root" && action=="fit") { viewAction("fit"); return; }
    applyContext(action,identifier);
}
void AppController::applyContext(const QString &action,const QString &identifier) {
    if (identifier.startsWith("plane:")) { planeAction(identifier.mid(6),action); return; }
    if (identifier.startsWith("part:")) { bool ok=false; const auto index=identifier.mid(5).toInt(&ok); if (ok) simulation_->partAction(index,action); return; }
    const auto target=identifier.isEmpty()?session_->selection.value("feature").toString():identifier;
    if (action=="edit") editFeature(target);
    else if (action=="delete") deleteFeature(target);
    else if (action=="suppress") toggleSuppress(target);
    else if (action=="hide" || action=="show") { if (hidden_.contains(target)) hidden_.remove(target); else hidden_.insert(target); refresh(); }
    else if (action=="zoom") { if (viewport_) viewport_->fit(); }
    else unsupported(action);
}
void AppController::planeAction(const QString &plane,const QString &action) {
    if (!QStringList{"XY","XZ","YZ"}.contains(plane)) return;
    if (sketch_ && action=="normal" && plane!=plane_) { Q_EMIT notice(QStringLiteral("该参考面的正视方向与当前草图平行；请正视当前草图平面。")); return; }
    if (action=="sketch") sketchOn(plane);
    else if (action=="normal") { if (viewport_) viewport_->setView(plane); }
    else if (action=="hide" || action=="show" || action=="toggle") { if (viewport_) viewport_->setPlaneVisible(plane,action=="show" || (action=="toggle" && !viewport_->planeVisible(plane))); Q_EMIT changed(); Q_EMIT treeChanged(); }
    else if (action=="zoom") { if (viewport_) viewport_->fitPlane(plane); }
    else unsupported(action);
}
QVariantList AppController::planeChoices(const QString &identifier) const { Q_UNUSED(identifier); return QJsonArray{row("XY","XY"),row("XZ","XZ"),row("YZ","YZ")}.toVariantList(); }
void AppController::sketchPick(const QString &tool) {
    if (sketch_ && QStringList{"pattern","cpattern","relation","repair","rotate","scale"}.contains(tool)) { editor_->beginOperation(tool); syncEditorUi(); return; }
    if (sketch_ && (tool=="section" || tool=="silhouette")) {
        const auto result=execute("query",{{"what",tool},{"plane",plane_},{"offset",sketchParams_.value("offset")}});
        if (!result.value("ok").toBool()) return;
        const auto data=result.value("result").isObject()?result.value("result").toObject():result;
        QVector<QVector<QVector2D>> lines;
        for (const auto &value : data.value("lines").toArray()) {
            QVector<QVector2D> points;
            for (const auto &entry : value.toArray()) { const auto point=entry.toArray(); if (point.size()>=2) points.append(QVector2D(float(point[0].toDouble()),float(point[1].toDouble()))); }
            if (points.size()>=2) lines.append(points);
        }
        try { editor_->importShapes(domain::fit_lines(lines)); } catch (const std::exception &exception) { Q_EMIT notice(QString::fromUtf8(exception.what())); }
        return;
    }
    if (sketch_ && tool=="convert") {
        try {
            const auto references=domain::project_edges(session_->model,plane_,sketchParams_.value("offset").toDouble());
            if (references.isEmpty()) { Q_EMIT notice(QStringLiteral("模型中没有可投影的实体边。")); return; }
            editor_->setReferences(references);
        } catch (const std::exception &exception) { Q_EMIT notice(QString::fromUtf8(exception.what())); return; }
    }
    useSketchTool(tool);
}
void AppController::startSketch() {
    if (sketch_) { finishSketch(); return; }
    Q_EMIT contextRequested(-1,-1);
    sketchTool_="select"; cancelForm();
    const auto plane=session_->selection.value("plane").toString();
    if (!plane.isEmpty()) { sketchOn(plane); return; }
    const auto faces=session_->selection.value("faces").toArray();
    if (faces.size()==1) {
        const auto face=element(session_->model.value("faces").toArray(),faces.first().toInt()).toObject();
        const auto normal=face.value("normal").toArray(), centre=face.value("center").toArray();
        if (normal.size()==3 && centre.size()==3) {
            const double horizontal=normal[0].toDouble(),depth=normal[1].toDouble(),vertical=normal[2].toDouble();
            QString name; double offset=0;
            if (std::abs(vertical)>0.999999) { name="XY"; offset=centre[2].toDouble(); }
            else if (std::abs(depth)>0.999999) { name="XZ"; offset=-centre[1].toDouble(); }
            else if (std::abs(horizontal)>0.999999) { name="YZ"; offset=centre[0].toDouble(); }
            if (!name.isEmpty()) { sketchOn(name); sketchParams_["offset"]=offset; pushSketch(); return; }
        }
        Q_EMIT notice(QStringLiteral("任意斜面草图尚未迁移；请选坐标轴对齐平面。"));
    }
    pickingPlane_=true; if (viewport_) viewport_->setPlanesVisible(true); Q_EMIT notice(QStringLiteral("请在设计树选择 XY / XZ / YZ 基准面。")); Q_EMIT changed(); Q_EMIT sketchChanged();
}
void AppController::sketchOn(const QString &plane) {
    if (kind_=="assembly") { unsupported("assembly layout sketch:布局草图文档尚未接入 Session"); return; }
    if (!QStringList{"XY","XZ","YZ"}.contains(plane)) { unsupported("sketch plane:"+plane); return; }
    if (sketch_) { Q_EMIT notice(QStringLiteral("请先完成当前草图。")); return; }
    sketchTurned_=!rapid_; plane_=plane; shapes_={}; sketchParams_={{"plane",plane},{"offset",0},{"shapes",shapes_}}; editingSketch_.clear();
    if (viewport_) viewport_->setSketchOwner({});
    sketch_=true; pickingPlane_=false; start_=false; selectedShape_=-1; sketchUndo_.clear(); sketchRedo_.clear(); form_={}; tab_="sketch";
    const auto pendingTool=sketchTool_; editor_->reset(); editor_->setTool(pendingTool);
    pushSketch(); Q_EMIT startChanged();
}
void AppController::setSketchPlane(const QString &identifier,const QString &plane) {
    if (!sketch_ && !identifier.isEmpty()) { execute("edit_feature",{{"id",identifier},{"params",QJsonObject{{"plane",plane}}}}); return; }
    if (!sketch_) { sketchOn(plane); return; }
    if (!QStringList{"XY","XZ","YZ"}.contains(plane)) { unsupported("sketch plane:"+plane); return; }
    plane_=plane; sketchParams_["plane"]=plane; pushSketch();
}
void AppController::pushSketch() {
    editor_->setShapes(shapes_);
    sketchTool_=editor_->tool();
    if (viewport_) { viewport_->setSketch(shapes_,plane_,sketchParams_.value("offset").toDouble(),sketchTurned_); viewport_->setSketchTool(editor_->tool()); viewport_->setSketchSelection(selectedShape_); viewport_->setSnaps(snaps_,quickSnap_); }
    Q_EMIT sketchChanged(); Q_EMIT changed(); Q_EMIT treeChanged();
}
void AppController::syncEditorUi() {
    if (!sketch_) return;
    sketchTool_=editor_->tool(); const auto selection=editor_->selection(); selectedShape_=selection.isEmpty()?-1:selection.first();
    const auto panel=editor_->panel(); if (!panel.isEmpty()) form_=panel; else if (form_.value("kind")=="sketch") form_={};
    Q_EMIT changed(); Q_EMIT sketchChanged(); Q_EMIT formChanged();
}
void AppController::receiveSketch(const QJsonArray &shapes) {
    if (!sketch_ || shapes==shapes_) return;
    if (shapes.size()>shapes_.size()) selectedShape_=shapes.size()-1;
    sketchUndo_.append(shapes_); sketchRedo_.clear(); shapes_=shapes; pushSketch();
}
void AppController::finishSketch() {
    if (!sketch_) return;
    if (editor_->drafting()) { editor_->finishDraft(); if (editor_->drafting()) return; }
    if (!editor_->operation().isEmpty()) { Q_EMIT notice(QStringLiteral("请先确认或取消当前草图操作。")); return; }
    if (shapes_.isEmpty()) { Q_EMIT notice(QStringLiteral("草图为空；可取消或至少绘制一个图形。")); return; }
    auto params=sketchParams_; params["plane"]=plane_; params["shapes"]=shapes_;
    const auto result=editingSketch_.isEmpty() ? execute("sketch",params) : execute("edit_feature",{{"id",editingSketch_},{"params",params}});
    if (!result.value("ok").toBool()) {
        const auto identifier=result.value("id").toString(); if (!identifier.isEmpty()) editingSketch_=identifier;
        Q_EMIT changed(); return;
    }
    const auto identifier=result.value("id").toString(editingSketch_);
    const auto pending=editor_->tool(); const bool again=rapid_ && !finishingCommand_ && QStringList{"line","centerline","midline","rect","crect","rect3","crect3","pgram","ngon","polygon","circle","circle3","arc","arc3","ellipse","slot","cslot","aslot3","caslot","spline","sspline","point","text","equation"}.contains(pending);
    sketch_=false; pickingPlane_=false; editingSketch_.clear(); sketchTool_="select"; shapes_={}; sketchUndo_.clear(); sketchRedo_.clear(); tab_="feature";
    if (viewport_) { viewport_->endSketch(); if (sketchTurned_ && !rapid_) viewport_->setView("iso"); }
    if (!identifier.isEmpty()) selectFeature(identifier);
    Q_EMIT sketchChanged(); refresh();
    if (again) { sketchTool_=pending; pickingPlane_=true; tab_="sketch"; session_->selection={}; if (viewport_) { viewport_->setSelection({}); viewport_->setPlanesVisible(true); } Q_EMIT notice(QStringLiteral("快速草图：请点选下一个基准面，继续使用当前工具。")); Q_EMIT sketchChanged(); Q_EMIT changed(); }
}
void AppController::cancelSketch() {
    sketch_=false; pickingPlane_=false; editingSketch_.clear(); shapes_={}; sketchUndo_.clear(); sketchRedo_.clear(); sketchTool_="select"; selectedShape_=-1;
    if (viewport_) { viewport_->endSketch(); if (sketchTurned_ && !rapid_) viewport_->setView("iso"); } tab_="feature"; Q_EMIT sketchChanged(); refresh();
}
void AppController::useSketchTool(const QString &requested) {
    QString tool=requested;
    if (tool=="rectangle") tool="rect";
    if (!SketchEditor::tools().contains(tool)) { unsupported("sketch tool:"+requested); return; }
    sketchTool_=tool;
    if (!sketch_) {
        const auto plane=session_->selection.value("plane").toString();
        if (plane.isEmpty()) { pickingPlane_=true; tab_="sketch"; Q_EMIT notice(QStringLiteral("请先选择基准面。")); Q_EMIT changed(); return; }
        sketchOn(plane);
    } else { editor_->setTool(tool); syncEditorUi(); }
}
void AppController::sketchAction(const QString &action) {
    if (action=="exit") { finishSketch(); return; }
    if (action=="zoom") { if (viewport_) viewport_->fit(); return; }
    if (sketch_) { editor_->action(action); syncEditorUi(); return; }
    unsupported("sketch action:"+action);
}
void AppController::toggleRapidSketch() { setSetting("rapid",!rapid_); Q_EMIT notice(rapid_?QStringLiteral("快速草图已打开：进草图不转视角，画完一个接着点下一个基准面"):QStringLiteral("快速草图已关闭")); }
void AppController::setQuickSnap(const QString &kind) {
    if (!sketch_) { Q_EMIT notice(QStringLiteral("快速捕捉在编辑草图时使用。")); return; }
    if (!QStringList{"end","mid","center","quad","int","near"}.contains(kind)) { unsupported("snap:"+kind); return; }
    quickSnap_=quickSnap_==kind?QString():kind; if (viewport_) viewport_->setSnaps(snaps_,quickSnap_); Q_EMIT changed();
}
void AppController::toggleSnap(const QString &kind) { if (!QStringList{"end","mid","center","quad","int","near","hv","grid"}.contains(kind)) { unsupported("snap:"+kind); return; } auto values=snaps_; if (values.contains(kind)) values.remove(kind); else values.insert(kind); setSetting("snaps",QStringList(values.values())); }
void AppController::viewAction(const QString &action) {
    if (!viewport_) return;
    if (action=="fit") { previousCamera_=viewport_->cameraState(); viewport_->fit(); }
    else if (action=="zoom_box") viewport_->armZoom();
    else if (action=="previous") { const auto current=viewport_->cameraState(); if (!previousCamera_.isEmpty()) viewport_->restoreCamera(previousCamera_); previousCamera_=current; }
    else if (action=="save_view") { savedViews_.append(viewport_->cameraState()); Q_EMIT changed(); }
    else if (action.startsWith("view:")) { const int index=action.mid(5).toInt(); if (index>=0 && index<savedViews_.size()) viewport_->restoreCamera(savedViews_[index]); }
    else if (action=="normal") {
        const auto plane=session_->selection.value("plane").toString();
        if (!plane.isEmpty()) viewport_->setView(plane); else if (sketch_) viewport_->setView(plane_); else Q_EMIT notice(QStringLiteral("请先选择基准面；任意曲面正视尚未迁移。"));
    } else if (QStringList{"front","back","left","right","top","bottom","iso"}.contains(action)) { previousCamera_=viewport_->cameraState(); viewport_->setView(action); }
    else if (action=="appearance") Q_EMIT appearanceRequested();
    else unsupported("view:"+action);
    Q_EMIT viewChanged(); Q_EMIT changed();
}
void AppController::setDisplayStyle(const QString &style) {
    if (!QStringList{"shaded_edges","shaded","wire","wireframe"}.contains(style)) { unsupported("display:"+style); return; }
    view_["style"]=style; if (viewport_) viewport_->setStyle(style); Q_EMIT viewChanged(); Q_EMIT changed();
}
void AppController::setScene(const QString &scene) { if (scene!="auto") { unsupported("scene:"+scene); return; } view_["scene"]=scene; Q_EMIT changed(); }
void AppController::toggleShow(const QString &kind) {
    if (kind!="main_planes") { unsupported("show:"+kind); return; }
    if (viewport_) viewport_->setPlanesVisible(!viewport_->planesVisible());
    Q_EMIT changed(); Q_EMIT treeChanged();
}
void AppController::toggleViewSetting(const QString &key) { unsupported("view setting:"+key); }
void AppController::setSection(const QString &plane,double offset) { Q_UNUSED(plane); Q_UNUSED(offset); unsupported("section"); }
void AppController::setMaterial(const QString &name) { execute("set_material",{{"name",name}}); }
void AppController::setAppearance(const QString &color) {
    if (!color.isEmpty() && !QColor(color).isValid()) { Q_EMIT notice(QStringLiteral("无效颜色。")); return; }
    execute("set_appearance",{{"color",color}});
}
void AppController::setShortcut(const QString &identifier,const QString &key) {
    if (!defaultKeys_.contains(identifier)) { unsupported("shortcut:"+identifier); return; }
    const auto sequence=QKeySequence::fromString(key,QKeySequence::PortableText); const auto canonical=sequence.toString(QKeySequence::PortableText);
    if (!key.isEmpty() && (sequence.isEmpty() || canonical.isEmpty())) { Q_EMIT notice(QStringLiteral("无效快捷键：%1").arg(key)); return; }
    for (int index=0;index<sequence.count();++index) if (sequence[index].key()==Qt::Key_Escape || sequence[index].key()==Qt::Key_Return || sequence[index].key()==Qt::Key_Enter) { Q_EMIT notice(QStringLiteral("Esc 和回车固定用来取消和确认，不能改派给别的功能")); return; }
    if (!canonical.isEmpty()) for (auto entry=keys_.begin();entry!=keys_.end();++entry) if (entry.key()!=identifier && entry.value().toString().compare(canonical,Qt::CaseInsensitive)==0) entry.value()=QString();
    keys_[identifier]=canonical; savePreference("shortcuts",keys_); Q_EMIT settingsChanged(); Q_EMIT changed();
}
void AppController::resetShortcut(const QString &identifier) { if (defaultKeys_.contains(identifier)) setShortcut(identifier,defaultKeys_.value(identifier).toString()); }
void AppController::resetShortcuts() { keys_=defaultKeys_; savePreference("shortcuts",keys_); Q_EMIT settingsChanged(); Q_EMIT changed(); }
QString AppController::keyText(int key,int modifiers) const { if (key==Qt::Key_Control || key==Qt::Key_Shift || key==Qt::Key_Alt || key==Qt::Key_Meta) return {}; return QKeySequence(key|modifiers).toString(QKeySequence::PortableText); }
void AppController::toggleMeasure() {
    measuring_=!measuring_; measurement_={{"title",QStringLiteral("测量")},{"rows",QVariantList{}},{"items",QVariantList{}},{"error",""},{"hint",QStringLiteral("点击面或边；Ctrl 添加第二个对象")}};
    if (measuring_) measureSelection();
    Q_EMIT measureChanged(); Q_EMIT changed();
}
void AppController::measureSelection() {
    try {
        if (kind_=="drawing") throw Error(QStringLiteral("工程图请使用图纸尺寸标注；三维测量不会读取零件以外的当前文档。"));
        measurement_["rows"]=QVariantList{};
        QJsonArray items;
        for (const auto &key : {QString("faces"),QString("edges")}) for (const auto &index : session_->selection.value(key).toArray()) items.append(QJsonObject{{"kind",key=="faces"?"face":"edge"},{"id",index}});
        const auto result=kind_=="assembly"?simulation_->measureSelection(session_->selection):items.isEmpty()?QJsonObject{{"items",QJsonArray{}}}:session_->builder.query("measure",{{"items",items}});
        if (result.contains("error")) throw Error(result.value("error").toString());
        QVariantList rows;
        if (kind_=="assembly") measurement_["hint"]=QStringLiteral("测量零件整体；Ctrl 选择第二个零件测量最短间距（不是局部面边测量）");
        for (const auto &value : result.value("items").toArray()) {
            const auto item=value.toObject();
            for (auto iterator=item.begin();iterator!=item.end();++iterator)
                if (iterator.key()!="id" && iterator.key()!="kind" && !iterator.value().isObject() && !iterator.value().isNull()) {
                    const auto text=iterator.value().isArray()?QString::fromUtf8(QJsonDocument(iterator.value().toArray()).toJson(QJsonDocument::Compact)):iterator.value().toVariant().toString();
                    rows.append(QVariantMap{{"label",item.value("kind").toString()+" "+iterator.key()},{"value",text},{"strong",false}});
                }
        }
        for (auto iterator=result.begin();iterator!=result.end();++iterator) if (!iterator.value().isArray() && !iterator.value().isObject()) rows.append(QVariantMap{{"label",iterator.key()},{"value",iterator.value().toVariant().toString()},{"strong",false}});
        if (rows.isEmpty() && !result.value("items").toArray().isEmpty()) rows.append(QVariantMap{{"label",QStringLiteral("结果")},{"value",QString::fromUtf8(QJsonDocument(result).toJson(QJsonDocument::Compact))},{"strong",false}});
        measurement_["rows"]=rows; measurement_["error"]="";
    } catch (const std::exception &exception) { measurement_["error"]=QString::fromUtf8(exception.what()); Q_EMIT notice(measurement_["error"].toString()); }
    Q_EMIT measureChanged(); Q_EMIT changed();
}
void AppController::runCheck() {
    manufactureUi()->runCheck();
}
void AppController::clearCheck() { manufactureUi()->clearCheck(); }
void AppController::closeCheck() { manufactureUi()->closeCheck(); }
void AppController::toggleCheckLog() { manufactureUi()->toggleCheckLog(); }
void AppController::toggleCheckHighlight() { manufactureUi()->toggleCheckHighlight(); }
void AppController::focusIssue(int index) {
    const auto issues=manufactureUi()->issues();
    if (index<0 || index>=issues.size() || manufactureUi()->stale()) return;
    const auto features=issues[index].toObject().value("features").toArray();
    if (!features.isEmpty()) selectFeature(features.first().toString());
}
void AppController::bindProcesses() { manufactureUi()->bindProcesses(); }
void AppController::setRule(const QString &key,const QString &text) { manufactureUi()->setRule(key,text); }
void AppController::resetRules() { manufactureUi()->resetRules(); }
void AppController::backToPart() { if (kind_=="drawing" && !confirmDiscard()) return; kind_="part"; tab_="feature"; simulation_->close(); Q_EMIT kindChanged(); refresh(); }
void AppController::backToAssembly() { if (sketch_) { Q_EMIT notice(QStringLiteral("请先完成或取消当前草图。")); return; } if (kind_=="part" && session_->document.dirty) { saveDocument(""); if (session_->document.dirty) return; } if (kind_=="drawing" && !confirmDiscard()) return; simulation_->open("assembly"); }
QJsonObject AppController::viewCommand(const QString &command,const QJsonObject &arguments) {
    if (!viewport_) return {{"ok",false},{"error",QStringLiteral("三维视图尚未连接。")}};
    if (command=="set_view") {
        const auto name=arguments.value("name").toString(arguments.value("view").toString("iso"));
        if (!QStringList{"front","back","left","right","top","bottom","iso","fit"}.contains(name)) return {{"ok",false},{"error",QStringLiteral("不支持该视角：%1").arg(name)}};
        viewAction(name); return {{"ok",true},{"view",name}};
    }
    if (command=="screenshot") {
        const auto path=localPath(arguments.value("path").toString());
        if (path.isEmpty() || !viewport_->saveImage(path)) return {{"ok",false},{"error",QStringLiteral("三维截图写入失败。")}};
        return {{"ok",true},{"path",path}};
    }
    return {{"ok",false},{"error",QStringLiteral("GUI 命令尚未迁移：%1").arg(command)}};
}

}
