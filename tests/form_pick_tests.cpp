#include "genform/controller/controller.hpp"
#include "genform/features.hpp"
#include "genform/view/sheet.hpp"
#include "genform/view/viewport.hpp"
#include <QApplication>
#include <QImage>
#include <QJsonDocument>
#include <QMatrix4x4>
#include <QPainter>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickItem>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QTemporaryDir>
#include <QTest>
#include <QTextStream>
#include <functional>
#include <stdexcept>

namespace {
using genform::controller::AppController;
using genform::view::Viewport;
void require(bool valid,const QString &message) { if (!valid) throw std::runtime_error(message.toUtf8().constData()); }
void settle() { QCoreApplication::processEvents(); QTest::qWait(80); }
QJsonArray coordinates(double first,double second,double third) { QJsonArray result; result.append(QJsonArray{first,second,third}); return result; }
QQuickItem *findItem(QQuickItem *root,const std::function<bool(QQuickItem *)> &accepts) {
    if (accepts(root)) return root;
    for (auto *child : root->childItems()) if (auto *found=findItem(child,accepts)) return found;
    return nullptr;
}
QQuickItem *named(QQuickItem *root,const QString &name) { return findItem(root,[&](QQuickItem *item) { return item->objectName()==name; }); }
QQuickItem *choice(QQuickItem *root,const QString &key,const QString &value) {
    auto *row=named(root,"formField_"+key); require(row,"Choice field must exist: "+key);
    return findItem(row,[&](QQuickItem *item) { return item->property("on").isValid() && item->property("modelData").toMap().value("value")==value; });
}
QJsonObject field(const AppController &controller,const QString &key) {
    for (const auto &entry : controller.value("form").toMap().value("fields").toList()) if (entry.toMap().value("key")==key) return QJsonObject::fromVariantMap(entry.toMap());
    return {};
}
QVector3D vectorOf(const QJsonValue &value) {
    const auto point=value.toArray(); require(point.size()==3,"Real geometry must have three coordinates");
    return {float(point[0].toDouble()),float(point[1].toDouble()),float(point[2].toDouble())};
}
QPointF project(Viewport *viewport,const QVector3D &point) {
    const auto camera=viewport->cameraState(); QMatrix4x4 rotation;
    rotation.rotate(float(camera.value("pitch").toDouble()),1,0,0); rotation.rotate(float(camera.value("yaw").toDouble()),0,0,1);
    const auto turned=rotation.map(point-vectorOf(camera.value("centre")));
    return {viewport->width()/2+camera.value("pan_x").toDouble()+turned.x()*camera.value("scale").toDouble(),viewport->height()/2+camera.value("pan_y").toDouble()-turned.y()*camera.value("scale").toDouble()};
}
void render(Viewport *viewport) {
    QImage image(QSize(qRound(viewport->width()),qRound(viewport->height())),QImage::Format_ARGB32_Premultiplied); image.fill(Qt::transparent);
    QPainter painter(&image); viewport->paint(&painter);
}
}

int main(int argc,char **argv) {
    qputenv("QT_QPA_PLATFORM","offscreen"); qputenv("QSG_RHI_BACKEND","software"); qputenv("GENFORM_PORT","0");
    QApplication application(argc,argv); QTemporaryDir temporary;
    qputenv("GENFORM_SETTINGS",temporary.filePath("settings.json").toUtf8()); QQuickStyle::setStyle("Basic");
    int cases=0; QStringList warnings;
    try {
        require(temporary.isValid(),"Isolated settings must exist");
        genform::Session session; AppController controller(&session); controller.newOf("part");
        qmlRegisterType<Viewport>("GenForm",1,0,"Viewport"); qmlRegisterType<genform::view::SheetView>("GenForm",1,0,"SheetView");
        QQmlApplicationEngine engine;
        QObject::connect(&engine,&QQmlEngine::warnings,&application,[&](const QList<QQmlError> &errors) { for (const auto &error : errors) warnings.append(error.toString()); });
        engine.rootContext()->setContextProperty("app",&controller); engine.rootContext()->setContextProperty("sim",controller.simulation());
        engine.rootContext()->setContextProperty("drawing",controller.drawing()); engine.rootContext()->setContextProperty("apiText",QString());
        engine.load(QUrl::fromLocalFile(QStringLiteral(GENFORM_SOURCE_DIR "/qml/Main.qml")));
        require(!engine.rootObjects().isEmpty(),"Production Main.qml must load: "+warnings.join('\n'));
        auto *window=qobject_cast<QQuickWindow *>(engine.rootObjects().first()); require(window,"Production Main.qml must create its real window");
        auto *root=window->contentItem(); auto *viewport=window->findChild<Viewport *>("viewport");
        require(viewport,"Production viewport must exist"); controller.attach(window,viewport,window->findChild<genform::view::SheetView *>("sheetView"));
        window->resize(1520,1000); window->show(); settle();
        const auto click=[&](QQuickItem *item) {
            require(item && item->isVisible() && item->isEnabled() && item->width()>0 && item->height()>0,"UI click target must be a visible enabled production item");
            const auto point=item->mapToScene({item->width()/2,item->height()/2}).toPoint();
            require(QRect(QPoint(0,0),window->size()).contains(point),"UI click target must be inside the actual window");
            QTest::mouseClick(window,Qt::LeftButton,Qt::NoModifier,point); settle();
        };
        const auto clickWorld=[&](const QVector3D &point) {
            const auto local=project(viewport,point); require(local.x()>340 && local.x()<viewport->width()-24 && local.y()>80 && local.y()<viewport->height()-40,"Geometry click must be unobscured by the actual form and viewport chrome");
            QTest::mouseClick(window,Qt::LeftButton,Qt::NoModifier,viewport->mapToScene(local).toPoint()); settle();
        };
        const auto start=[&](const QString &command) { controller.cancelForm(); controller.startCommand(command); settle(); require(named(root,"featureFormPanel")->isVisible(),"Production feature form must be visible for "+command); };
        const auto focus=[&](const QString &key) {
            auto *row=named(root,"formField_"+key); require(row,"Active field row must exist: "+key);
            const auto label=field(controller,key).value("label").toString();
            click(findItem(row,[&](QQuickItem *item) { return item->property("text").toString()==label && !item->childItems().isEmpty(); }));
            require(controller.value("form").toMap().value("active")==key,"Real field-label click must set active: "+key);
        };
        const auto chosen=[&](const QString &key,const QString &value) {
            require(field(controller,key).value("value")==value,"Controller field must contain picked reference: "+key);
            auto *option=choice(root,key,value);
            require(option && option->property("on").toBool(),"Actual choice chip must reflect reference pick: "+key);
        };
        const auto build=[&](const QString &command,const QJsonObject &params) {
            controller.cancelForm(); const auto result=controller.execute(command,params);
            require(result.value("ok").toBool(),"Real fixture command failed: "+command+" "+result.value("error").toString()); return result.value("id").toString();
        };
        const auto camera=[&](bool body) {
            viewport->setPlanesVisible(!body);
            viewport->restoreCamera({{"yaw",body?-45:0},{"pitch",body?-35:0},{"scale",body?8:4},{"pan_x",120},{"pan_y",50},{"centre",QJsonArray{0,0,0}}}); settle(); render(viewport);
        };
        const auto first=build("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",20},{"h",12}}}}});
        const auto second=build("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","line"},{"x1",25},{"y1",0},{"x2",35},{"y2",0}}}}});
        const auto axisA=build("axis",{{"origin",coordinates(0,20,0)},{"direction",coordinates(1,0,0)}});
        const auto axisB=build("axis",{{"origin",coordinates(0,-20,0)},{"direction",coordinates(1,0,0)}});
        const auto plane=build("plane",{{"base","XY"},{"offset",8}});
        camera(false); start("extrude"); focus("sketch"); clickWorld({0,6,0}); chosen("sketch",first); ++cases;
        start("sweep"); focus("path"); clickWorld({30,0,0}); chosen("path",second); ++cases;
        focus("sketch"); clickWorld({10,0,0}); chosen("sketch",first); ++cases;
        const auto sketchBefore=field(controller,"sketch").value("value"); clickWorld({10,20,0});
        require(field(controller,"sketch").value("value")==sketchBefore,"Axis pick must be rejected by sketch/path reference filters"); ++cases;
        start("pattern_linear"); focus("axis2"); clickWorld({10,20,0}); chosen("axis2",axisA);
        require(controller.value("form").toMap().value("active")=="axis1","Single reference pick must advance to the next compatible field"); ++cases;
        clickWorld({10,-20,0}); chosen("axis1",axisB); require(controller.value("form").toMap().value("active")=="axis2","Axis field rotation must wrap"); ++cases;
        start("revolve"); click(choice(root,"sketch",second)); focus("axis"); clickWorld({30,0,0});
        require(field(controller,"axis").value("value").toString().startsWith('@'),"Clicking a straight line in the form's current sketch must fill the axis"); ++cases;
        const auto centred=build("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",16},{"h",8}},QJsonObject{{"type","line"},{"x1",0},{"y1",10},{"x2",0},{"y2",30},{"construction",true}}}}});
        camera(false); start("revolve"); click(choice(root,"sketch",centred)); focus("axis"); clickWorld({0,16,0}); chosen("axis","CL"); ++cases;
        start("mirror"); focus("plane"); clickWorld({50,25,8}); chosen("plane",plane); ++cases;
        clickWorld({18,10,0}); chosen("plane","XY"); ++cases;
        start("loft"); clickWorld({0,6,0}); clickWorld({30,0,0});
        require(field(controller,"sketches").value("value").toArray()==QJsonArray{first,second},"Multi reference picking must preserve click order without Ctrl");
        require(named(root,"formOption_sketches_"+first)->property("order").toInt()==0 && named(root,"formOption_sketches_"+second)->property("order").toInt()==1,"Real multi chips must display picked order"); ++cases;
        clickWorld({0,6,0}); require(field(controller,"sketches").value("value").toArray()==QJsonArray{second},"Repeated multi pick must remove the reference"); ++cases;
        clickWorld({10,20,0}); require(field(controller,"sketches").value("value").toArray()==QJsonArray{second},"Multi sketch options must reject axis references"); ++cases;
        const auto point=build("point",{{"position",coordinates(25,30,0)}}); camera(false); start("curve_points");
        clickWorld({25,30,0}); require(field(controller,"points").value("value").toArray()==QJsonArray{point},"Reference-point field must accept point features"); ++cases;
        clickWorld({30,0,0}); require(field(controller,"points").value("value").toArray()==QJsonArray{point},"Reference-point field must reject sketches"); ++cases;
        clickWorld({25,30,0}); require(field(controller,"points").value("value").toArray().isEmpty(),"Point reference multi selection must toggle"); ++cases;
        const auto laterPlane=build("plane",{{"origin",coordinates(80,0,0)},{"normal",coordinates(0,0,1)}}); camera(false);
        controller.editFeature(plane); settle(); focus("base"); clickWorld({80,50,0});
        require(field(controller,"base").value("value")=="XY","Editing a reference must reject later features that are excluded from its options");
        for (const auto &option : field(controller,"base").value("options").toArray()) require(option.toObject().value("value")!=laterPlane,"Rejected forward reference must not be appended to the options"); ++cases;
        const auto body=build("extrude",{{"sketch",first},{"distance",10}}); camera(true);
        require(session.model.value("vertices").toArray().size()==8 && !session.model.value("tris").toArray().isEmpty(),"Topology fixture must contain actual kernel vertices and triangles"); ++cases;
        start("mirror"); auto *bodyChip=named(root,"formOption_features_"+body); require(bodyChip,"Solid reference multi chip must exist");
        if (bodyChip->property("order").toInt()>=0) click(bodyChip);
        clickWorld({0,-6,5}); require(field(controller,"features").value("value").toArray()==QJsonArray{body} && named(root,"formOption_features_"+body)->property("order").toInt()==0,"Clicking a real solid face must fill its allowed feature reference and visible chip"); ++cases;
        clickWorld({0,-6,5}); require(field(controller,"features").value("value").toArray().isEmpty(),"Repeated solid reference pick must toggle the feature without Ctrl"); ++cases;
        start("extrude"); click(choice(root,"end","vertex"));
        require(controller.value("form").toMap().value("pick").toMap().value("kind")=="vertex","Real termination click must arm vertex picking"); ++cases;
        const auto corners=session.model.value("vertices").toArray(); int corner=-1;
        for (int index=0;index<corners.size();++index) if ((vectorOf(corners[index])-QVector3D(10,-6,10)).length()<0.001f) { corner=index; break; }
        require(corner>=0,"Real solid must expose an upper termination vertex"); clickWorld(vectorOf(corners[corner]));
        require(session.selection.value("vertices").toArray()==QJsonArray{corner} && session.selection.value("edges").toArray().isEmpty() && session.selection.value("faces").toArray().isEmpty(),"Vertex termination must prefer actual topology vertices over edges/faces");
        require(field(controller,"target").value("selectedCount").toInt()==1,"Real termination info row must receive the vertex pick"); ++cases;
        const auto vertexSelection=session.selection; clickWorld({0,-6,5});
        require(session.selection==vertexSelection,"Wrong topology during vertex picking must leave the valid target intact"); ++cases;
        clickWorld({-10,6,0}); require(session.selection==vertexSelection,"Occluded rear vertex must not replace the visible termination vertex"); ++cases;
        viewport->setHidden({body}); settle(); render(viewport); session.selection={}; viewport->setSelection({}); clickWorld(vectorOf(corners[corner]));
        require(session.selection.value("vertices").toArray().isEmpty(),"Hidden solid vertices must not remain pickable in vertex mode"); ++cases;
        viewport->setHidden({}); settle(); render(viewport); clickWorld(vectorOf(corners[corner]));
        require(session.selection.value("vertices").toArray()==QJsonArray{corner},"Showing a solid again must restore its visible topology picks"); ++cases;
        click(choice(root,"end","surface")); require(session.selection.value("vertices").toArray().isEmpty(),"Changing termination kind must clear obsolete topology without setModel"); ++cases;
        clickWorld({0,-6,5}); require(session.selection.value("faces").toArray().size()==1 && session.selection.value("vertices").toArray().isEmpty(),"Surface mode must stop vertex priority and select a real face"); ++cases;
        click(named(root,"formCancel")); clickWorld(vectorOf(corners[corner]));
        require(session.selection.value("vertices").toArray().isEmpty() && session.selection.value("edges").toArray().size()==1,"Cancel must restore default edge-first picking"); ++cases;
        start("fillet"); session.selection={};
        const auto segments=session.model.value("segments").toArray(),owners=session.model.value("segment_edge").toArray();
        QList<QPointF> edgePoints; QList<int> edgeNumbers;
        for (int index=0;index<segments.size() && edgePoints.size()<2;++index) {
            const int number=owners[index].toInt(-1); if (edgeNumbers.contains(number)) continue;
            const auto segment=segments[index].toArray(); const auto middle=(vectorOf(segment[0])+vectorOf(segment[1]))/2;
            if (middle.z()<4) continue;
            const auto local=project(viewport,middle); if (local.x()<340 || local.y()<80 || local.y()>viewport->height()-40) continue;
            edgePoints.append(local); edgeNumbers.append(number);
        }
        require(edgePoints.size()==2,"Fixture must expose two distinct unobscured edge midpoints");
        const auto clickEdge=[&](int index) { QTest::mouseClick(window,Qt::LeftButton,Qt::NoModifier,viewport->mapToScene(edgePoints[index]).toPoint()); settle(); };
        clickEdge(0); clickEdge(1); require(session.selection.value("edges").toArray()==QJsonArray{edgeNumbers[0],edgeNumbers[1]} && field(controller,"edges").value("selectedCount").toInt()==2,"Edge forms must accumulate topology with ordinary clicks"); ++cases;
        clickEdge(0); require(session.selection.value("edges").toArray()==QJsonArray{edgeNumbers[1]},"Repeated edge click must remove the edge without Ctrl"); ++cases;
        const auto validEdges=session.selection; clickWorld({0,-6,5}); require(session.selection==validEdges,"Face picks must not overwrite an edge form's topology"); ++cases;
        start("pattern_linear"); focus("axis2"); clickEdge(0);
        const auto edgeAxis=field(controller,"axis2").value("value").toString();
        require(edgeAxis.startsWith('@') && edgeAxis.contains(';'),"Solid straight edge must become a native axis reference"); chosen("axis2",edgeAxis); ++cases;
        focus("axis2"); clickEdge(1); const auto replacementAxis=field(controller,"axis2").value("value").toString();
        int pickedAxes=0; for (const auto &option : field(controller,"axis2").value("options").toArray()) if (option.toObject().value("label")==QStringLiteral("视图中选的轴")) ++pickedAxes;
        require(replacementAxis.startsWith('@') && replacementAxis!=edgeAxis && pickedAxes==1,"Repicking a geometric axis must replace the transient option"); chosen("axis2",replacementAxis); ++cases;
        controller.cancelForm(); start("extrude"); click(choice(root,"end","vertex")); clickWorld(vectorOf(corners[corner]));
        click(choice(root,"sketch",first)); click(named(root,"formAccept"));
        require(!named(root,"featureFormPanel")->isVisible() && session.document.features.last().toObject().value("params").toObject().value("target").toArray()==QJsonArray{QJsonObject{{"point",corners[corner]}}},"Real confirm must submit picked vertex coordinates to the native kernel: "+controller.value("previewNote").toString()); ++cases;
        require(session.document.features.last().toObject().value("id")!=body && session.model.value("has_body").toBool(),"Confirmed vertex termination must rebuild a real solid"); ++cases;
        clickWorld(vectorOf(corners[corner])); require(session.selection.value("vertices").toArray().isEmpty() && session.selection.value("edges").toArray().size()==1,"Successful accept must restore default edge-first picking"); ++cases;
        controller.cancelForm(); require(controller.execute("new_document").value("ok").toBool(),"Circle-axis fixture must reset the test document");
        const auto roundSketch=build("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","circle"},{"cx",0},{"cy",0},{"r",10}}}}});
        build("extrude",{{"sketch",roundSketch},{"distance",10}}); camera(true); start("pattern_linear"); focus("axis2"); clickWorld({10,0,10});
        const auto circleAxis=field(controller,"axis2").value("value").toString(); require(circleAxis.startsWith('@'),"Circular solid edge with null dir must supply its axis");
        const auto resolved=genform::features::axisOf(circleAxis,session.document.features);
        require(vectorOf(resolved.value("direction")).normalized().z()>0.99f,"Picked circular edge axis must resolve along the actual cylinder axis"); chosen("axis2",circleAxis); ++cases;
        require(warnings.isEmpty(),"QML warnings: "+warnings.join('\n'));
        QTextStream(stdout)<<QJsonDocument(QJsonObject{{"ok",true},{"cases",cases},{"qmlWarnings",QJsonArray::fromStringList(warnings)}}).toJson(QJsonDocument::Compact)<<Qt::endl;
        return 0;
    } catch (const std::exception &error) {
        QTextStream(stdout)<<QJsonDocument(QJsonObject{{"ok",false},{"cases",cases},{"error",QString::fromUtf8(error.what())},{"qmlWarnings",QJsonArray::fromStringList(warnings)}}).toJson(QJsonDocument::Compact)<<Qt::endl;
        return 2;
    }
}
