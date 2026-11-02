#include "genform/view/sheet.hpp"
#include <QFile>
#include <QGuiApplication>
#include <QJsonDocument>
#include <QLineF>
#include <QTemporaryDir>
#include <QTextStream>
#include <cmath>
#include <stdexcept>

namespace {
void require(bool condition,const QString &message) {
    if (!condition) throw std::runtime_error(message.toUtf8().constData());
}
QJsonArray pair(const QPointF &point) { return {point.x(),point.y()}; }
QPointF point(const QJsonValue &value) {
    const auto coordinates=value.toArray();
    return {coordinates[0].toDouble(),coordinates[1].toDouble()};
}
void requirePoint(const QPointF &actual,const QPointF &expected,const QString &message) {
    require(QLineF(actual,expected).length()<1e-6,message);
}
QByteArray readBytes(const QString &path) {
    QFile file(path); require(file.open(QIODevice::ReadOnly),file.errorString()); return file.readAll();
}
void writeDocument(const QString &path,const QJsonObject &document) {
    QFile file(path); require(file.open(QIODevice::WriteOnly),file.errorString());
    const auto bytes=QJsonDocument(document).toJson();
    require(file.write(bytes)==bytes.size(),file.errorString());
}
QJsonObject readDocument(const QString &path) { return QJsonDocument::fromJson(readBytes(path)).object(); }
QJsonObject placement(const genform::view::SheetView &view,const QString &name) {
    for (const auto &value : view.sheet().value("placements").toArray())
        if (value.toObject().value("name").toString()==name) return value.toObject();
    throw std::runtime_error("Expected view placement is missing");
}
QPointF pagePoint(const QJsonObject &place,const QPointF &local) {
    return point(place.value("centre"))+(QPointF(local.x(),-local.y())-point(place.value("origin")))*place.value("scale").toDouble();
}
QPointF textPoint(const genform::view::SheetView &view,const QString &text) {
    for (const auto &value : view.sheet().value("texts").toArray()) {
        const auto entry=value.toObject();
        if (entry.value("text").toString()==text) return {entry.value("x").toDouble(),entry.value("y").toDouble()};
    }
    throw std::runtime_error(QString("Missing rendered dimension: %1").arg(text).toStdString());
}
bool hasText(const genform::view::SheetView &view,const QString &text) {
    for (const auto &value : view.sheet().value("texts").toArray())
        if (value.toObject().value("text").toString()==text) return true;
    return false;
}
void click(genform::view::SheetView &view,const QPointF &position) {
    view.pressed(position.x(),position.y()); view.released(position.x(),position.y());
}
void moveView(genform::view::SheetView &view,const QString &name,const QPointF &delta) {
    const auto place=placement(view,name);
    const QPointF start(place.value("x").toDouble()+2,place.value("y").toDouble()+place.value("h").toDouble()-2);
    view.pressed(start.x(),start.y()); view.moved(start.x()+delta.x(),start.y()+delta.y());
    view.released(start.x()+delta.x(),start.y()+delta.y());
}
QJsonObject document(const QJsonArray &dimensions) {
    return {{"format","genform-drawing"},{"version",1},{"part","part.gform"},{"sheet","A3"},{"scale",1},
            {"views",QJsonArray{"front","top","left","iso"}},{"offsets",QJsonObject{}},{"auto",false},
            {"dimensions",dimensions},{"title",QJsonObject{{"name","Drawing regression"}}},{"extension","keep"}};
}
QJsonObject linear(const QString &view,const QString &mode,const QPointF &first,const QPointF &second,double at) {
    return {{"view",view},{"kind","linear"},{"mode",mode},{"a",pair(first)},{"b",pair(second)},{"at",at}};
}
QJsonObject roundDimension(bool full) {
    return {{"view","front"},{"kind","round"},{"c",QJsonArray{20,15}},{"r",5},{"full",full},
            {"at",full ? QJsonArray{35,30} : QJsonArray{5,30}},{"extension","retained"}};
}
void setModel(genform::Session &session,const QString &path,double factor=1) {
    session.document.path=path;
    QJsonArray segments;
    const double width=40*factor,depth=20*factor,height=30*factor;
    const QList<QJsonArray> corners{{0,0,0},{width,0,0},{width,0,height},{0,0,height},{0,depth,0},{width,depth,0},{width,depth,height},{0,depth,height}};
    for (const auto &indices : QList<QPair<int,int>>{{0,1},{1,2},{2,3},{3,0},{4,5},{5,6},{6,7},{7,4},{0,4},{1,5},{2,6},{3,7}})
        segments.append(QJsonArray{corners[indices.first],corners[indices.second]});
    session.model={{"has_body",true},{"segments",segments}};
}
void legacyGridLayout(genform::Session &session,const QString &directory) {
    struct GridCase {
        QString name,paper;
        QJsonArray views;
        double requested,selected;
        QMap<QString,QPointF> centres;
        double isoScale;
    };
    const double isoWidth=60*std::sqrt(0.5),isoHeight=60/std::sqrt(6.0)+30*std::sqrt(2.0/3.0);
    const QList<GridCase> cases{
        {"four","A3",{"front","top","left","iso"},1,1,{{"front",{164,88}},{"top",{164,180.5}},{"left",{253,88}},{"iso",{253,164.5}}},1},
        {"permuted","A3",{"iso","left","front","top"},1,1,{{"front",{164,88}},{"top",{164,180.5}},{"left",{253,88}},{"iso",{253,164.5}}},1},
        {"orthographic","A3",{"front","top","left"},1,1,{{"front",{189,121.5}},{"top",{189,180.5}},{"left",{253,121.5}}},1},
        {"front","A3",{"front"},1,1,{{"front",{216,148.5}}},1},
        {"top","A3",{"top"},1,1,{{"top",{216,148.5}}},1},
        {"left","A3",{"left"},1,1,{{"left",{216,148.5}}},1},
        {"iso","A3",{"iso"},5,5,{{"iso",{216,148.5}}},70/isoWidth},
        {"front-iso","A3",{"front","iso"},5,5,{{"front",{164,88}},{"iso",{333,224.5}}},55/isoHeight},
        {"front-top","A3",{"front","top"},1,1,{{"front",{216,121.5}},{"top",{216,180.5}}},1},
        {"front-left","A3",{"front","left"},1,1,{{"front",{189,148.5}},{"left",{253,148.5}}},1},
        {"auto-a3","A3",{"front","top","left","iso"},0,2,{{"front",{164,88}},{"top",{164,195.5}},{"left",{273,88}},{"iso",{273,179.5}}},55/isoHeight},
        {"auto-a4","A4",{"front","top","left","iso"},0,1,{{"front",{102.5,44.5}},{"top",{102.5,137}},{"left",{191.5,44.5}},{"iso",{191.5,121}}},1},
        {"none","A3",{},0,1,{},1}
    };
    const QJsonObject offsets{{"front",QJsonArray{13,-7}},{"top",QJsonArray{-11,9}},{"left",QJsonArray{5,4}},{"iso",QJsonArray{-8,-6}}};
    const QJsonArray dimensions{linear("front","h",{0,0},{40,0},-10),linear("top","h",{0,0},{20,0},-8),
                                linear("left","v",{0,0},{0,9},5),linear("iso","h",{0,0},{12,0},-10)};
    for (const auto &scenario : cases) {
        const auto path=directory+"/grid-"+scenario.name+".gdrw",saved=directory+"/grid-"+scenario.name+"-saved.gdrw";
        auto fixture=document(dimensions); fixture["views"]=scenario.views; fixture["scale"]=scenario.requested;
        fixture["sheet"]=scenario.paper; fixture["offsets"]=offsets;
        writeDocument(path,fixture); const auto original=readBytes(path);
        genform::view::SheetView view;
        genform::controller::DrawingBridge bridge(&session); bridge.attach(&view);
        require(bridge.open(path),"Legacy grid must open: "+scenario.name);
        require(!bridge.dirty(),"Reading legacy layout must not alter document");
        require(std::abs(view.sheet().value("scale").toDouble()-scenario.selected)<1e-9,"Legacy standard scale must match: "+scenario.name);
        require(view.sheet().value("placements").toArray().size()==scenario.centres.size(),"Only shown views may occupy legacy grid");
        for (auto expected=scenario.centres.cbegin();expected!=scenario.centres.cend();++expected) {
            const auto place=placement(view,expected.key());
            const double own=expected.key()=="iso" ? scenario.isoScale : scenario.selected;
            requirePoint(point(place.value("centre")),expected.value()+point(offsets.value(expected.key())),"Legacy grid centre and stored offset must match: "+scenario.name+"/"+expected.key());
            require(std::abs(place.value("scale").toDouble()-own)<1e-9,"Each view must retain its legacy scale");
            const double width=expected.key()=="iso" ? isoWidth : expected.key()=="left" ? 20 : 40;
            const double height=expected.key()=="iso" ? isoHeight : expected.key()=="top" ? 20 : 30;
            require(std::abs(place.value("w").toDouble()-width*own)<1e-6 && std::abs(place.value("h").toDouble()-height*own)<1e-6,"Projection extent must use its view scale: "+scenario.name+"/"+expected.key());
        }
        if (scenario.centres.contains("front"))
            requirePoint(textPoint(view,"40"),scenario.centres["front"]+point(offsets.value("front"))+QPointF(0,25*scenario.selected-2),"Old front dimension must retain absolute paper position");
        else require(!hasText(view,"40"),"Hidden front dimensions must remain hidden");
        if (scenario.centres.contains("top"))
            requirePoint(textPoint(view,"20"),scenario.centres["top"]+point(offsets.value("top"))+QPointF(-10*scenario.selected,18*scenario.selected-2),"Old top dimension must retain absolute paper position");
        else require(!hasText(view,"20"),"Hidden top dimensions must remain hidden");
        if (scenario.centres.contains("left"))
            requirePoint(textPoint(view,"9"),scenario.centres["left"]+point(offsets.value("left"))+QPointF(15*scenario.selected+2,10.5*scenario.selected),"Old left dimension must retain absolute paper position");
        else require(!hasText(view,"9"),"Hidden left dimensions must remain hidden");
        if (scenario.centres.contains("iso")) {
            const QPointF origin(30*std::sqrt(0.5),10/std::sqrt(6.0)-15*std::sqrt(2.0/3.0));
            requirePoint(textPoint(view,"12"),scenario.centres["iso"]+point(offsets.value("iso"))+(QPointF(6,10)-origin)*scenario.isoScale-QPointF(0,2),"Old isometric dimension must retain its independent scale");
        } else require(!hasText(view,"12"),"Hidden isometric dimensions must remain hidden");
        require(bridge.save(saved),"Legacy grid Save As must succeed");
        require(readDocument(saved)==fixture,"Grid reconstruction must not migrate or rewrite offsets or dimensions");
        require(readBytes(path)==original,"Layout validation must not modify source fixture bytes");
    }
    const auto path=directory+"/grid-iso-dimensions.gdrw";
    auto fixture=document({linear("iso","a",{0,0},{3,4},2),QJsonObject{{"kind","round"},{"view","iso"},{"c",QJsonArray{0,0}},{"r",1},{"full",true},{"at",QJsonArray{7,0}}}});
    fixture["views"]=QJsonArray{"front","iso"}; fixture["scale"]=5; writeDocument(path,fixture);
    genform::view::SheetView view;
    genform::controller::DrawingBridge bridge(&session); bridge.attach(&view); require(bridge.open(path),"Independent isometric scale fixture must open");
    const auto iso=placement(view,"iso");
    const double own=55/isoHeight;
    const auto first=pagePoint(iso,{0,0}),second=pagePoint(iso,{3,4});
    requirePoint(textPoint(view,"5"),(first+second)/2+QPointF(4,3)*(2*own/5)-QPointF(0,2),"Aligned isometric offsets must use own scale");
    requirePoint(textPoint(view,QString::fromUtf8("Ø2")),pagePoint(iso,{7,0})+QPointF((2*3.5*0.72+2)/2,-1.2),"Round isometric leaders must use own radius scale");
    setModel(session,session.document.path,1000); fixture=document({}); fixture["scale"]=0; writeDocument(path,fixture);
    require(bridge.open(path) && std::abs(view.sheet().value("scale").toDouble()-0.002)<1e-12,"Automatic scale must include old 1:500 choice");
    setModel(session,session.document.path,10000);
    require(bridge.open(path) && std::abs(view.sheet().value("scale").toDouble()-0.001)<1e-12,"Oversized drawings must retain legacy minimum-scale fallback");
    setModel(session,session.document.path);
}
void legacyDimensions(genform::Session &session,const QString &directory) {
    const QJsonArray dimensions{linear("front","h",{0,0},{40,0},-10),linear("front","v",{0,0},{0,30},-10),
                                linear("front","a",{0,0},{40,30},10),roundDimension(true),roundDimension(false),
                                linear("iso","h",{0,0},{12,0},-10)};
    const auto path=directory+"/legacy.gdrw", saved=directory+"/legacy-saved.gdrw";
    writeDocument(path,document(dimensions)); const auto original=readBytes(path);
    genform::view::SheetView view;
    genform::controller::DrawingBridge bridge(&session); bridge.attach(&view);
    require(bridge.open(path),"Python-format drawing must open");
    require(!bridge.dirty(),"Opening must not modify document state");
    for (const auto &label : {QString("40"),QString("30"),QString("50"),QString::fromUtf8("Ø10"),QString("R5"),QString("12")})
        require(hasText(view,label),"All legacy dimension kinds must render: "+label);
    const auto front=placement(view,"front"), iso=placement(view,"iso");
    requirePoint(point(iso.value("origin")),{30*std::sqrt(0.5),10/std::sqrt(6.0)-15*std::sqrt(2.0/3.0)},"Isometric frame must match Python coordinates");
    requirePoint(textPoint(view,"40"),pagePoint(front,{20,-10})-QPointF(0,2),"Horizontal dimension must use upward view coordinates");
    requirePoint(textPoint(view,"30"),pagePoint(front,{-10,15})+QPointF(2,0),"Vertical dimension must use upward view coordinates");
    const auto alignedOffset=QPointF(30,40)*(10.0/50.0);
    requirePoint(textPoint(view,"50"),(pagePoint(front,{0,0})+pagePoint(front,{40,30}))/2+alignedOffset-QPointF(0,2),"Aligned dimension must preserve signed offset and true length");
    const auto horizontal=textPoint(view,"40"), round=textPoint(view,QString::fromUtf8("Ø10")), isometric=textPoint(view,"12");
    bridge.useTool("dimension"); click(view,pagePoint(front,{0,0})); bridge.useTool("select");
    moveView(view,"front",{13,7});
    requirePoint(textPoint(view,"40"),horizontal+QPointF(13,7),"Moving a view must move linear dimensions");
    requirePoint(textPoint(view,QString::fromUtf8("Ø10")),round+QPointF(13,7),"Moving a view must move round dimensions");
    requirePoint(textPoint(view,"12"),isometric,"Moving front must not move isometric dimensions");
    bridge.setScale("2");
    const auto scaled=placement(view,"front");
    requirePoint(textPoint(view,"40"),pagePoint(scaled,{20,-10})-QPointF(0,2),"Scaling must transform annotation anchors");
    requirePoint(textPoint(view,"30"),pagePoint(scaled,{-10,15})+QPointF(2,0),"Scaling must transform vertical anchors");
    requirePoint(textPoint(view,"50"),(pagePoint(scaled,{0,0})+pagePoint(scaled,{40,30}))/2+alignedOffset*2-QPointF(0,2),"Scaling must transform aligned offsets");
    requirePoint(textPoint(view,QString::fromUtf8("Ø10")),pagePoint(scaled,{35,30})+QPointF((3*3.5*0.72+2)/2,-1.2),"Scaling must transform diameter leader anchors");
    requirePoint(textPoint(view,"R5"),pagePoint(scaled,{5,30})+QPointF(-(2*3.5*0.72+2)/2,-1.2),"Scaling must transform radius leader anchors");
    require(hasText(view,QString::fromUtf8("Ø10")) && hasText(view,"R5"),"Round values must remain independent of paper scale");
    const auto beforeHide=textPoint(view,"40");
    bridge.toggleView("front");
    for (const auto &label : {QString("40"),QString("30"),QString("50"),QString::fromUtf8("Ø10"),QString("R5")})
        require(!hasText(view,label),"Hiding a view must hide all its dimensions: "+label);
    click(view,beforeHide);
    require(!bridge.state().value("selected").toBool(),"Hidden dimension handles must not remain selectable");
    require(hasText(view,"12"),"Other visible views must retain dimensions");
    bridge.toggleView("front"); requirePoint(textPoint(view,"40"),beforeHide,"Showing a view must restore associated dimensions");
    require(bridge.save(saved),"Legacy drawing save must succeed");
    require(readDocument(saved).value("dimensions").toArray()==dimensions,"Legacy dimension objects must round-trip unchanged");
    require(readDocument(saved).value("extension").toString()=="keep","Unknown document data must survive save");
    require(readBytes(path)==original,"Opening and saving a copy must leave original file unchanged");
    genform::view::SheetView reopenedView;
    genform::controller::DrawingBridge reopened(&session); reopened.attach(&reopenedView);
    require(reopened.open(saved),"Saved dimensions must reopen");
    requirePoint(textPoint(reopenedView,"40"),beforeHide,"Saved scale and offsets must reproduce placement");
    const auto centre=point(placement(view,"front").value("centre")), handle=textPoint(view,QString::fromUtf8("Ø10"));
    view.pressed(handle.x(),handle.y()); view.moved(handle.x()+20,handle.y()+20); view.released(handle.x()+20,handle.y()+20);
    require(bridge.state().value("selected").toBool(),"Round dimension handle must be selectable");
    requirePoint(point(placement(view,"front").value("centre")),centre,"Selecting a dimension must not start moving its view");
    bridge.deleteSelected(); require(!hasText(view,QString::fromUtf8("Ø10")),"Selected round dimension must delete");
}
void newDimensions(genform::Session &session,const QString &directory) {
    const auto path=directory+"/new.gdrw",saved=directory+"/new-saved.gdrw";
    writeDocument(path,document({}));
    genform::view::SheetView view;
    genform::controller::DrawingBridge bridge(&session); bridge.attach(&view); require(bridge.open(path),"Empty fixture must open");
    bridge.useTool("dimension");
    const auto front=placement(view,"front");
    click(view,point(front.value("centre")));
    click(view,pagePoint(front,{0,0}));
    click(view,pagePoint(placement(view,"top"),{40,0}));
    click(view,pagePoint(front,{40,0})); click(view,pagePoint(front,{20,-10}));
    require(bridge.save(saved),"New dimension must save");
    auto dimensions=readDocument(saved).value("dimensions").toArray();
    require(dimensions.size()==1,"Unsnapped and cross-view clicks must not create dimensions");
    require(dimensions[0].toObject()==linear("front","h",{0,0},{40,0},-10),"New dimensions must store view coordinates, not paper coordinates");
    const auto initial=textPoint(view,"40"); bridge.useTool("select"); moveView(view,"front",{11,9});
    requirePoint(textPoint(view,"40"),initial+QPointF(11,9),"New dimensions must follow view movement");
    bridge.setScale("0.5");
    requirePoint(textPoint(view,"40"),pagePoint(placement(view,"front"),{20,-10})-QPointF(0,2),"New dimensions must follow scale changes");
    bridge.toggleView("front"); require(!hasText(view,"40"),"New dimensions must hide with their view");
    require(bridge.save(saved),"Hidden dimensions must remain saveable");
    require(readDocument(saved).value("dimensions").toArray()==dimensions,"Hide must not delete dimensions");
    bridge.toggleView("front"); bridge.resetLayout(); bridge.setScale("1"); bridge.useTool("dimension");
    const auto reset=placement(view,"front");
    click(view,pagePoint(reset,{0,0})); click(view,pagePoint(reset,{40,30})); click(view,pagePoint(reset,{20,10}));
    require(hasText(view,"50"),"New aligned dimensions must show true length");
    require(bridge.save(saved),"Aligned dimension must save");
    dimensions=readDocument(saved).value("dimensions").toArray();
    require(dimensions.size()==2 && dimensions[1].toObject().value("mode").toString()=="a","Inside placement must retain aligned dimension mode");
    bridge.setScale("auto");
    requirePoint(textPoint(view,"40"),pagePoint(placement(view,"front"),{20,-10})-QPointF(0,2),"Automatic scale must preserve association");
    bridge.setSheet("A4");
    requirePoint(textPoint(view,"40"),pagePoint(placement(view,"front"),{20,-10})-QPointF(0,2),"Paper changes must transform dimension anchors");
    bridge.setSheet("A3"); bridge.setScale("1");
    bridge.useTool("select"); moveView(view,"front",{8,6}); bridge.resetLayout();
    requirePoint(textPoint(view,"40"),pagePoint(placement(view,"front"),{20,-10})-QPointF(0,2),"Reset layout must transform dimension anchors");
    bridge.useTool("dimension");
    click(view,pagePoint(reset,{0,0})); require(bridge.open(path),"Opening a new drawing must cancel any draft");
    require(bridge.state().value("tool").toString()=="select","Opening must clear dimension interaction");
    require(!hasText(view,"40"),"Opening must not retain old dimensions");
}
void dataSafety(genform::Session &session,const QString &directory) {
    const QJsonObject paper{{"kind","linear"},{"vertical",false},{"value",40},{"page_a",QJsonArray{20,20}},
                            {"page_b",QJsonArray{60,20}},{"page_at",QJsonArray{40,40}}};
    const auto path=directory+"/paper.gdrw",saved=directory+"/paper-saved.gdrw",invalid=directory+"/invalid.gdrw";
    writeDocument(path,document({paper}));
    genform::view::SheetView view;
    genform::controller::DrawingBridge bridge(&session); bridge.attach(&view); require(bridge.open(path),"Native paper-only legacy dimension must remain readable");
    require(bridge.state().value("notes").toList().size()>1,"Missing view association must be explicitly reported");
    bridge.useTool("select"); moveView(view,"front",{8,6});
    requirePoint(textPoint(view,"40"),{40,38},"Unassociated old data must not be guessed or moved");
    require(bridge.save(saved) && readDocument(saved).value("dimensions").toArray()==QJsonArray{paper},"Paper-only data must remain lossless");
    const auto activePath=bridge.path();
    const auto current=view.sheet();
    const auto malformed=linear("front","h",{0,0},{40,0},-10);
    for (const auto &bad : QJsonArray{QJsonObject{{"kind","unknown"}},QJsonObject{{"kind","linear"},{"view","front"}},
                                    QJsonObject{{"kind","linear"},{"page_a",QJsonArray{0,0}}},QString("not an object"),
                                    QJsonObject{{"kind","linear"},{"view","unrecognized"},{"a",QJsonArray{0,0}},{"b",QJsonArray{40,0}},{"at",-10},{"mode","h"}}}) {
        writeDocument(invalid,document({malformed,bad})); const auto original=readBytes(invalid);
        QString notice;
        const auto connection=QObject::connect(&bridge,&genform::controller::DrawingBridge::notice,[&](const QString &text){notice=text;});
        require(!bridge.open(invalid),"Unsupported or malformed dimensions must fail explicitly, not disappear");
        QObject::disconnect(connection);
        require(notice.contains("2"),"Failure must identify the offending dimension");
        require(bridge.path()==activePath && view.sheet()==current,"Failed open must not replace current document");
        require(readBytes(invalid)==original,"Failed migration must not modify source bytes");
    }
    const auto missing=directory+"/missing-part.gdrw";
    auto unavailable=document({linear("front","h",{0,0},{40,0},-10)}); unavailable["part"]="unavailable.gform";
    writeDocument(missing,unavailable);
    require(bridge.open(missing),"Unavailable source must not discard readable dimensions");
    require(!bridge.state().value("error").toString().isEmpty(),"Unavailable source must report projection error");
    require(bridge.state().value("notes").toList().size()>1,"Unrendered dimension data must be reported");
    require(bridge.save(saved) && readDocument(saved).value("dimensions")==unavailable.value("dimensions"),"Unavailable source must not lose dimension records on Save As");
}
}

int main(int argc,char **argv) {
    qputenv("QT_QPA_PLATFORM","offscreen");
    QGuiApplication application(argc,argv);
    try {
        QTemporaryDir temporary; require(temporary.isValid(),"Unable to create isolated temporary directory");
        genform::Session session; setModel(session,temporary.path()+"/part.gform");
        legacyGridLayout(session,temporary.path());
        legacyDimensions(session,temporary.path());
        newDimensions(session,temporary.path());
        dataSafety(session,temporary.path());
        QTextStream(stdout)<<"drawing regression tests passed: legacy grid/offsets/scales, linear/aligned/round, lossless round-trip, view association, safety\n";
        return 0;
    } catch (const std::exception &exception) {
        QTextStream(stderr)<<"drawing regression failure: "<<exception.what()<<'\n'; return 1;
    }
}
