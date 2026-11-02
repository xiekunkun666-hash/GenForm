#include "genform/controller/controller.hpp"
#include "genform/controller/sketch_editor.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/view/sheet.hpp"
#include "genform/view/viewport.hpp"
#include <QApplication>
#include <QImage>
#include <QJsonDocument>
#include <QLineF>
#include <QMatrix4x4>
#include <QPainter>
#include <QPointer>
#include <QPolygonF>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickItem>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QTextStream>
#include <QWheelEvent>
#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <stdexcept>

#if defined(_MSC_VER) && !defined(_CPPUNWIND)
#error selection_ui_tests requires /EHsc so failed assertions destroy QSignalSpy connections
#endif

namespace {
using genform::controller::AppController;
using genform::view::Viewport;

void require(bool valid,const QString &message) {
    if (!valid) throw std::runtime_error(message.toUtf8().constData());
}

void settle() { QCoreApplication::processEvents(); QTest::qWait(120); }

QQuickItem *findItem(QQuickItem *root,const QString &name) {
    require(root,"Cannot search a null QML item for "+name);
    if (root->objectName()==name) return root;
    for (auto *child : root->childItems()) if (auto *found=findItem(child,name)) return found;
    return nullptr;
}

QQuickItem *findIcon(QQuickItem *root,const QString &icon) {
    require(root,"Cannot search a null QML item for icon "+icon);
    if (root->property("icon").toString()==icon) return root;
    for (auto *child : root->childItems()) if (auto *found=findIcon(child,icon)) return found;
    return nullptr;
}

QQuickItem *featureItem(QQuickItem *root,const QString &identifier) {
    const auto data=root->property("modelData").toMap();
    if (data.value("kind").toString()=="feature" && data.value("id").toString()==identifier) return root;
    for (auto *child : root->childItems()) if (auto *found=featureItem(child,identifier)) return found;
    return nullptr;
}

QList<QQuickItem *> planeLabels(QQuickItem *root) {
    QList<QQuickItem *> result;
    const auto data=root->property("modelData").toMap();
    if (data.value("kind").toString()=="plane" && QStringList{"XY","XZ","YZ"}.contains(data.value("text").toString())) result.append(root);
    for (auto *child : root->childItems()) result.append(planeLabels(child));
    return result;
}

QQuickItem *planeLabel(QQuickItem *root,const QString &plane) {
    for (auto *item : planeLabels(root)) if (item->property("modelData").toMap().value("text").toString()==plane) return item;
    throw std::runtime_error(("Missing production ViewLabels delegate for "+plane).toStdString());
}

QQuickItem *contentOf(QObject *popup) {
    require(popup,"Popup must exist before reading its contentItem");
    auto *content=qobject_cast<QQuickItem *>(popup->property("contentItem").value<QObject *>());
    require(content,"Popup must expose its real contentItem");
    return content;
}

QImage renderViewport(Viewport *viewport) {
    QImage image(QSize(qRound(viewport->width()),qRound(viewport->height())),QImage::Format_ARGB32_Premultiplied);
    image.fill(Qt::transparent);
    QPainter painter(&image);
    viewport->paint(&painter);
    return image;
}

QPointF project(Viewport *viewport,const QVector3D &point) {
    const auto state=viewport->cameraState();
    const auto centre=state.value("centre").toArray();
    QMatrix4x4 rotation;
    rotation.rotate(float(state.value("pitch").toDouble()),1,0,0);
    rotation.rotate(float(state.value("yaw").toDouble()),0,0,1);
    const auto rotated=rotation.map(point-QVector3D(float(centre[0].toDouble()),float(centre[1].toDouble()),float(centre[2].toDouble())));
    return {viewport->width()/2+state.value("pan_x").toDouble()+rotated.x()*state.value("scale").toDouble(),
        viewport->height()/2+state.value("pan_y").toDouble()-rotated.y()*state.value("scale").toDouble()};
}

QVector3D vectorOf(const QJsonValue &value) {
    const auto coordinates=value.toArray();
    require(coordinates.size()==3,"Fixture geometry must expose three-dimensional vertices");
    return {float(coordinates[0].toDouble()),float(coordinates[1].toDouble()),float(coordinates[2].toDouble())};
}

double edgeClearance(Viewport *viewport,const QJsonObject &model,const QPointF &point) {
    double nearest=std::numeric_limits<double>::max();
    for (const auto &entry : model.value("segments").toArray()) {
        const auto segment=entry.toArray();
        require(segment.size()==2,"Fixture edge segment must have two endpoints");
        const auto start=project(viewport,vectorOf(segment[0])),end=project(viewport,vectorOf(segment[1]));
        const auto delta=end-start;
        const double square=QPointF::dotProduct(delta,delta);
        const double fraction=square>0?std::clamp(QPointF::dotProduct(point-start,delta)/square,0.0,1.0):0;
        nearest=std::min(nearest,QLineF(point,start+fraction*delta).length());
    }
    return nearest;
}

QPointF solidPosition(Viewport *viewport,const QJsonObject &model,const QString &identifier) {
    const auto vertices=model.value("verts").toArray(),triangles=model.value("tris").toArray();
    const auto numbers=model.value("tri_face").toArray(),faces=model.value("faces").toArray();
    require(!vertices.isEmpty() && !triangles.isEmpty() && triangles.size()==numbers.size(),"Solid click fixture must have indexed face triangles");
    const QRectF safeArea(32,110,viewport->width()-64,viewport->height()-150);
    double bestClearance=0;
    QPointF best;
    for (int index=0;index<triangles.size();++index) {
        const auto indices=triangles[index].toArray();
        require(indices.size()==3,"Solid fixture triangle must have three indices");
        const int faceNumber=numbers[index].toInt(-1);
        bool belongs=false;
        for (const auto &entry : faces) {
            const auto face=entry.toObject();
            if (face.value("id").toInt(-1)==faceNumber && face.value("feature").toString()==identifier) { belongs=true; break; }
        }
        if (!belongs) continue;
        QVector<QVector3D> corners;
        for (const auto &entry : indices) {
            const int vertex=entry.toInt(-1);
            require(vertex>=0 && vertex<vertices.size(),"Solid triangle index must reference a real vertex");
            corners.append(vectorOf(vertices[vertex]));
        }
        for (int first=1;first<5;++first) for (int second=1;second<5-first;++second) {
            const auto world=(corners[0]*float(first)+corners[1]*float(second)+corners[2]*float(5-first-second))/5;
            const QPointF point=project(viewport,world).toPoint();
            if (!safeArea.contains(point)) continue;
            const double clearance=edgeClearance(viewport,model,point);
            if (clearance>bestClearance) { bestClearance=clearance; best=point; }
        }
    }
    require(bestClearance>8,QString("Solid face click must stay outside the 6px edge-picking tolerance; best clearance=%1px").arg(bestClearance));
    return best;
}

QPointF planePosition(Viewport *viewport,const QJsonObject &model,const QString &plane) {
    const QStringList planes{"XY","XZ","YZ"};
    QList<QPolygonF> polygons;
    for (const auto &name : planes) {
        QPolygonF polygon;
        for (const auto &point : genform::domain::to_world({{-25,-25},{25,-25},{25,25},{-25,25}},name)) polygon.append(project(viewport,point));
        polygons.append(polygon);
    }
    QRectF bodyBounds;
    bool first=true;
    for (const auto &entry : model.value("verts").toArray()) {
        const auto coordinates=entry.toArray();
        const auto point=project(viewport,{float(coordinates[0].toDouble()),float(coordinates[1].toDouble()),float(coordinates[2].toDouble())});
        const QRectF pixel(point,QSizeF(1,1));
        bodyBounds=first?pixel:bodyBounds.united(pixel); first=false;
    }
    const QRectF safeArea(32,110,viewport->width()-64,viewport->height()-150);
    for (int vertical=-18;vertical<=18;vertical+=3) for (int horizontal=-18;horizontal<=18;horizontal+=3) {
        const auto world=genform::domain::to_world({QVector2D(float(horizontal),float(vertical))},plane).first();
        const auto point=project(viewport,world);
        if (!safeArea.contains(point) || (!first && bodyBounds.adjusted(-12,-12,12,12).contains(point))) continue;
        QString frontPlane;
        for (int index=planes.size()-1;index>=0;--index) {
            if (viewport->planeVisible(planes[index]) && polygons[index].containsPoint(point,Qt::OddEvenFill)) { frontPlane=planes[index]; break; }
        }
        if (frontPlane==plane) return point;
    }
    throw std::runtime_error(("No unobscured viewport click position for "+plane).toStdString());
}

QVariantMap treePlane(const AppController &controller,const QString &plane) {
    for (const auto &entry : controller.value("tree").toList()) {
        const auto row=entry.toMap();
        if (row.value("kind").toString()=="plane" && row.value("id").toString()==plane) return row;
    }
    throw std::runtime_error(("Missing tree plane "+plane).toStdString());
}
}

int main(int argc,char **argv) {
    qputenv("QT_QPA_PLATFORM","offscreen");
    qputenv("QSG_RHI_BACKEND","software");
    qputenv("GENFORM_PORT","0");
    QApplication application(argc,argv);
    QTemporaryDir temporary;
    qputenv("GENFORM_SETTINGS",temporary.filePath("settings.json").toUtf8());
    QQuickStyle::setStyle("Basic");
    QStringList warnings,failures;
    int cases=0;
    try {
        require(temporary.isValid(),"Temporary settings directory must exist");
        genform::Session session;
        AppController controller(&session);
        controller.newOf("part");
        qmlRegisterType<Viewport>("GenForm",1,0,"Viewport");
        qmlRegisterType<genform::view::SheetView>("GenForm",1,0,"SheetView");
        QQmlApplicationEngine engine;
        QObject::connect(&engine,&QQmlEngine::warnings,&application,[&](const QList<QQmlError> &errors) {
            for (const auto &error : errors) warnings.append(error.toString());
        });
        engine.rootContext()->setContextProperty("app",&controller);
        engine.rootContext()->setContextProperty("sim",controller.simulation());
        engine.rootContext()->setContextProperty("drawing",controller.drawing());
        engine.rootContext()->setContextProperty("apiText",QString());
        engine.load(QUrl::fromLocalFile(QStringLiteral(GENFORM_SOURCE_DIR "/qml/Main.qml")));
        require(!engine.rootObjects().isEmpty(),"Real Main.qml must load: "+warnings.join('\n'));
        auto *window=qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        require(window,"Main.qml must create a real QQuickWindow");
        auto *root=window->contentItem();
        auto *viewport=window->findChild<Viewport *>("viewport");
        auto *sheet=window->findChild<genform::view::SheetView *>("sheetView");
        require(viewport && sheet,"Main.qml must instantiate the production viewport and sheet");
        controller.attach(window,viewport,sheet);
        auto *editor=controller.findChild<genform::controller::SketchEditor *>();
        require(editor,"Production controller must own its actual sketch editor");
        window->resize(1360,860); window->show(); window->requestActivate(); settle();
        auto *planeBar=window->findChild<QObject *>("designPlaneBar");
        auto *sceneBar=window->findChild<QObject *>("sceneContextBar");
        require(planeBar && sceneBar,"Required popup objectNames: designPlaneBar and sceneContextBar");
        const QStringList planes{"XY","XZ","YZ"};
        for (const auto &plane : planes) require(findItem(root,"designPlane_"+plane),"Required tree row objectName: designPlane_"+plane);

        const auto click=[&](QQuickItem *item) {
            require(item && item->isVisible() && item->isEnabled() && item->width()>0 && item->height()>0,"Click target must be a visible, enabled production QML item");
            const auto point=item->mapToScene({item->width()/2,item->height()/2}).toPoint();
            require(QRect(QPoint(0,0),window->size()).contains(point),"Click target must be inside the real window");
            QTest::mouseClick(window,Qt::LeftButton,Qt::NoModifier,point); settle();
        };
        const auto clickViewport=[&](const QPointF &point) {
            require(viewport->contains(point),"Viewport click must be inside the production item");
            QTest::mouseClick(window,Qt::LeftButton,Qt::NoModifier,viewport->mapToScene(point).toPoint()); settle();
        };
        const auto escape=[&] { viewport->forceActiveFocus(); QTest::keyClick(window,Qt::Key_Escape); settle(); };
        const auto emptyPosition=[&] { return QPointF(viewport->width()-32,viewport->height()-36); };
        const auto solidClickPosition=[&] {
            require(!session.document.features.isEmpty(),"Solid click fixture must contain an extrusion feature");
            return solidPosition(viewport,session.model,session.document.features.last().toObject().value("id").toString());
        };
        const auto reset=[&](bool body) {
            QMetaObject::invokeMethod(planeBar,"close"); QMetaObject::invokeMethod(sceneBar,"close");
            if (controller.value("sketchActive").toBool()) controller.cancelSketch();
            if (controller.value("rapidSketch").toBool()) controller.toggleRapidSketch();
            controller.cancelForm();
            if (controller.value("measuring").toBool()) controller.toggleMeasure();
            controller.escape();
            require(controller.execute("new_document").value("ok").toBool(),"Selection fixture must reset the real document");
            if (body) {
                const auto sketch=controller.execute("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",20},{"h",10}}}}});
                require(sketch.value("ok").toBool(),"Selection fixture sketch must build");
                const auto extrusion=controller.execute("extrude",{{"sketch",sketch.value("id")},{"distance",5}});
                require(extrusion.value("ok").toBool() && session.model.value("has_body").toBool() && !session.model.value("tris").toArray().isEmpty(),"Selection fixture must have real triangulated solid geometry");
                QVector3D low(std::numeric_limits<float>::max(),std::numeric_limits<float>::max(),std::numeric_limits<float>::max());
                QVector3D high(std::numeric_limits<float>::lowest(),std::numeric_limits<float>::lowest(),std::numeric_limits<float>::lowest());
                for (const auto &entry : session.model.value("verts").toArray()) {
                    const auto point=vectorOf(entry);
                    low={std::min(low.x(),point.x()),std::min(low.y(),point.y()),std::min(low.z(),point.z())};
                    high={std::max(high.x(),point.x()),std::max(high.y(),point.y()),std::max(high.z(),point.z())};
                }
                require((low-QVector3D(-10,-5,0)).length()<0.001f && (high-QVector3D(10,5,5)).length()<0.001f,"Centered rectangle fixture must span [-10,10] x [-5,5] x [0,5]");
            } else require(!session.model.value("has_body").toBool(),"Empty fixture must have no solid");
            viewport->setPlanesVisible(true);
            for (const auto &plane : planes) viewport->setPlaneVisible(plane,true);
            viewport->restoreCamera({{"yaw",-45},{"pitch",-54.736},{"scale",6},{"pan_x",0},{"pan_y",0},{"centre",QJsonArray{0,0,0}}});
            viewport->forceActiveFocus(); settle(); renderViewport(viewport);
            require(!planeBar->property("visible").toBool() && !sceneBar->property("visible").toBool(),"Fixture must begin without selection toolbars");
        };
        const auto checkLabels=[&](const QJsonObject &model) {
            require(planeLabels(root).size()==planes.size(),"Real Main.qml must instantiate exactly three plane label delegates outside sketch mode");
            double reach=25;
            for (const auto &entry : model.value("props").toObject().value("size").toArray()) reach=std::max(reach,std::abs(entry.toDouble())*0.65);
            for (const auto &plane : planes) {
                auto *label=planeLabel(root,plane);
                const auto corner=genform::domain::to_world({QVector2D(float(reach),float(reach))},plane).first();
                const auto expected=project(viewport,corner);
                require(label->isVisible() && label->width()>0 && label->height()>0,"Main.qml plane labels must be visible text delegates: "+plane);
                require(QLineF(label->position(),expected).length()<0.01,"Real plane label position must follow the current camera, viewport and model size: "+plane);
            }
        };
        const auto checkSketchLabels=[&] {
            require(planeLabels(root).isEmpty(),"Sketch entry must remove real Main.qml plane label delegates, not just clear the C++ getter");
            for (const auto &plane : planes) {
                auto *row=findItem(root,"designPlane_"+plane);
                require(row && row->isVisible() && treePlane(controller,plane).value("shown").toBool(),"Hiding canvas labels in sketch mode must preserve visible DesignTree planes: "+plane);
            }
        };
        const auto checkPlane=[&](const QString &plane) {
            require(session.selection.value("plane").toString()==plane && session.selection.value("feature").toString().isEmpty(),"UI click must select only the requested plane: "+plane);
            require(session.selection.value("faces").toArray().isEmpty() && session.selection.value("edges").toArray().isEmpty(),"Plane selection must not retain old solid topology");
            for (const auto &name : planes) {
                auto *row=findItem(root,"designPlane_"+name);
                require(row && row->property("chosen").toBool()==(name==plane) && row->property("modelData").toMap().value("selected").toBool()==(name==plane),"Real DesignTree delegate highlight must follow selection: "+name);
                require(treePlane(controller,name).value("selected").toBool()==(name==plane),"Controller tree selection must match the real delegate: "+name);
            }
            int selectedLabels=0;
            for (const auto &entry : viewport->labels()) {
                const auto label=entry.toMap();
                if (label.value("selected").toBool()) { ++selectedLabels; require(label.value("text").toString()==plane,"Viewport highlight must identify the selected plane"); }
            }
            require(selectedLabels==1,"Viewport must expose exactly one highlighted plane label");
            int chosenDelegates=0;
            for (auto *label : planeLabels(root)) if (label->property("modelData").toMap().value("selected").toBool()) {
                ++chosenDelegates;
                require(label->isVisible() && label->property("modelData").toMap().value("text").toString()==plane,"Real ViewLabels delegate selection must follow the selected plane");
            }
            require(chosenDelegates==1,"Main.qml must update exactly one selected plane label delegate");
        };
        const auto checkEmpty=[&] {
            require(session.selection.value("plane").toString().isEmpty() && session.selection.value("feature").toString().isEmpty() && session.selection.value("faces").toArray().isEmpty() && session.selection.value("edges").toArray().isEmpty(),"Empty viewport click must clear plane, feature, face and edge selection");
            require(!sceneBar->property("visible").toBool() && !planeBar->property("visible").toBool(),"Empty viewport click must dismiss both context toolbars");
            for (const auto &plane : planes) {
                auto *row=findItem(root,"designPlane_"+plane);
                require(row && !row->property("chosen").toBool(),"Empty click must preserve the plane row and remove its DesignTree highlight: "+plane);
            }
        };
        const auto runCase=[&](const QString &name,const std::function<void()> &test) {
            ++cases; QTextStream(stdout)<<"RUN "<<name<<Qt::endl;
            try { test(); QTextStream(stdout)<<"PASS "<<name<<Qt::endl; }
            catch (const std::exception &error) { const auto message=name+": "+QString::fromUtf8(error.what()); failures.append(message); QTextStream(stderr)<<"FAIL "<<message<<Qt::endl; }
        };

        for (bool body : {false,true}) {
            const QString fixture=body?"solid":"empty";
            for (const auto &plane : planes) {
                runCase(fixture+" tree click "+plane,[&] {
                    reset(body); const auto document=session.document.toData();
                    if (body) {
                        clickViewport(solidClickPosition());
                        require(!session.selection.value("feature").toString().isEmpty() && !session.selection.value("faces").toArray().isEmpty(),"Solid fixture must first select real face topology before changing to a tree plane");
                    }
                    const auto before=renderViewport(viewport);
                    click(findItem(root,"designPlane_"+plane)); checkPlane(plane);
                    require(planeBar->property("visible").toBool() && planeBar->property("plane").toString()==plane && planeBar->property("shown").toBool(),"Ordinary tree click must show the targeted planeBar even when app.hint is nonempty");
                    require(!controller.value("sketchActive").toBool() && !controller.property("pickingPlane").toBool(),"Ordinary tree click must not enter or arm a sketch");
                    require(renderViewport(viewport)!=before,"Plane selection must visibly change the production viewport painting");
                    require(session.document.toData()==document,"Plane selection must not change document geometry");
                    clickViewport(emptyPosition()); checkEmpty();
                });
                runCase(fixture+" viewport plane context "+plane,[&] {
                    reset(body); QSignalSpy picked(viewport,&Viewport::picked),context(viewport,&Viewport::contextPicked);
                    const auto point=planePosition(viewport,session.model,plane); clickViewport(point); checkPlane(plane);
                    require(picked.count()==1 && context.count()==1 && context.first()[0].value<QJsonObject>().value("plane").toString()==plane,"Real viewport click must emit picked and contextPicked exactly once for the plane");
                    require(sceneBar->property("visible").toBool() && sceneBar->property("target").toString()=="plane:"+plane && sceneBar->property("items").toList().size()>=4,"Viewport plane click must open the production scene context popup with plane actions");
                    require(!planeBar->property("visible").toBool(),"Viewport click must not open the tree-local plane toolbar");
                    clickViewport(emptyPosition()); checkEmpty();
                });
                runCase(fixture+" pending sketch tree click "+plane,[&] {
                    reset(body); const auto count=session.document.features.size();
                    viewport->forceActiveFocus(); QTest::keyClick(window,Qt::Key_S); settle();
                    require(controller.property("pickingPlane").toBool() && !controller.value("sketchActive").toBool(),"Real sketch shortcut must expose pickingPlane while waiting for a plane");
                    QSignalSpy planeVisibility(planeBar,SIGNAL(visibleChanged())),sceneVisibility(sceneBar,SIGNAL(visibleChanged()));
                    click(findItem(root,"designPlane_"+plane));
                    require(controller.value("sketchActive").toBool() && !controller.property("pickingPlane").toBool() && controller.value("tab").toString()=="sketch","Pending sketch tree click must enter sketch mode rather than remain in plane-picking mode");
                    require(viewport->cameraState().value("yaw").toDouble()==(plane=="YZ"?-90:0) && viewport->cameraState().value("pitch").toDouble()==(plane=="XY"?0:-90),"Pending sketch must orient to the clicked plane");
                    require(planeVisibility.isValid() && sceneVisibility.isValid() && planeVisibility.isEmpty() && sceneVisibility.isEmpty() && !planeBar->property("visible").toBool() && !sceneBar->property("visible").toBool(),"Sketch-plane picking must not even transiently open either toolbar");
                    require(session.document.features.size()==count,"Entering an empty sketch must not commit a feature");
                    checkSketchLabels();
                    controller.cancelSketch(); settle(); checkLabels(session.model);
                });
            }
            runCase(fixture+" individual plane hide and show",[&] {
                reset(body); const auto document=session.document.toData();
                for (const auto &plane : planes) {
                    click(findItem(root,"designPlane_"+plane));
                    click(findIcon(contentOf(planeBar),"eye_off"));
                    require(!viewport->planeVisible(plane) && !treePlane(controller,plane).value("shown").toBool() && !planeBar->property("shown").toBool(),"Hide UI button must hide only its selected plane and refresh tree/popup state");
                    for (const auto &other : planes) if (other!=plane) require(viewport->planeVisible(other) && treePlane(controller,other).value("shown").toBool(),"Single-plane hide must preserve the other two planes");
                    checkPlane(plane);
                    clickViewport(emptyPosition()); checkEmpty();
                    for (const auto &entry : viewport->labels()) require(entry.toMap().value("text").toString()!=plane,"Deselected hidden plane must not retain a visible label");
                    click(findItem(root,"designPlane_"+plane));
                    require(!planeBar->property("shown").toBool(),"Selecting a hidden plane must offer Show, not stale Hide state");
                    click(findIcon(contentOf(planeBar),"eye"));
                    require(viewport->planeVisible(plane) && treePlane(controller,plane).value("shown").toBool() && planeBar->property("shown").toBool(),"Show UI button must restore only the targeted plane");
                    clickViewport(emptyPosition()); checkEmpty();
                }
                require(session.document.toData()==document,"Plane visibility UI must not modify model features");
            });
            runCase(fixture+" hover does not rebuild tree",[&] {
                reset(body); const auto tree=controller.value("tree"); const auto selection=session.selection;
                QList<QPointer<QQuickItem>> rows; for (const auto &plane : planes) rows.append(findItem(root,"designPlane_"+plane));
                QSignalSpy changed(&controller,&AppController::changed),treeChanged(&controller,&AppController::treeChanged),rebuilding(&controller,&AppController::treeAboutToChange),hover(viewport,&Viewport::hoverChanged);
                for (const auto &plane : planes) { const auto point=planePosition(viewport,session.model,plane); QTest::mouseMove(window,viewport->mapToScene(point).toPoint(),20); }
                QTest::mouseMove(window,viewport->mapToScene(emptyPosition()).toPoint(),20); settle();
                require(hover.count()>=3,"Hover regression must deliver real pointer movements to Viewport, not test an idle controller");
                require(changed.isEmpty() && treeChanged.isEmpty() && rebuilding.isEmpty(),"Viewport hover must not emit AppController changed/treeChanged/treeAboutToChange");
                require(controller.value("tree")==tree && session.selection==selection,"Hover must not mutate tree data or selection");
                for (int index=0;index<planes.size();++index) require(rows[index] && rows[index].data()==findItem(root,"designPlane_"+planes[index]),"Hover must preserve actual DesignTree delegate identities");
            });
            runCase(fixture+" pending sketch viewport click",[&] {
                reset(body); const auto point=planePosition(viewport,session.model,"XY");
                QTest::keyClick(window,Qt::Key_S); settle(); require(controller.property("pickingPlane").toBool(),"Sketch shortcut must arm viewport plane picking");
                QSignalSpy visibility(sceneBar,SIGNAL(visibleChanged())); clickViewport(point);
                require(controller.value("sketchActive").toBool() && !controller.property("pickingPlane").toBool(),"Real viewport plane click must enter the pending sketch");
                require(visibility.isValid() && visibility.isEmpty() && !sceneBar->property("visible").toBool() && !planeBar->property("visible").toBool(),"contextPicked after sketch entry must not flash a toolbar");
            });
            runCase(fixture+" Escape cancels measurement",[&] {
                reset(body); const auto document=session.document.toData(); const auto camera=viewport->cameraState();
                QTest::keyClick(window,Qt::Key_M,Qt::ControlModifier); settle(); require(controller.value("measuring").toBool(),"Real Ctrl+M shortcut must enter measurement mode");
                clickViewport(body?solidClickPosition():planePosition(viewport,session.model,"XY"));
                require(!sceneBar->property("visible").toBool(),"Measurement clicks must suppress the scene context toolbar");
                escape();
                require(!controller.value("measuring").toBool() && !viewport->zoomArmed() && viewport->zoomRect().isEmpty() && viewport->band().isEmpty(),"Real Escape shortcut must cancel measurement and transient viewport interactions");
                require(viewport->cameraState()==camera && session.document.toData()==document,"Cancel measurement must not move the camera or alter geometry");
            });
        }

        runCase("Main.qml rapid sketch label lifecycle without camera turn",[&] {
            reset(false); checkLabels(session.model); const auto camera=viewport->cameraState();
            QList<QPointer<QQuickItem>> previous; for (auto *label : planeLabels(root)) previous.append(label);
            controller.toggleRapidSketch();
            QSignalSpy labelsChanged(viewport,&Viewport::labelsChanged);
            controller.sketchOn("XY"); settle(); checkSketchLabels();
            require(viewport->cameraState()==camera && labelsChanged.count()==1,"Rapid sketch must notify label removal even when no camera change occurs");
            for (const auto &label : previous) require(label.isNull(),"Entering sketch must destroy stale ViewLabels delegates at their old 3D positions");
            labelsChanged.clear(); viewport->setSketch({},"XY",0,false); settle();
            require(labelsChanged.isEmpty(),"Unchanged active sketch updates must not rebuild the label repeater");
            controller.cancelSketch(); settle(); checkLabels(session.model);
            require(viewport->cameraState()==camera && labelsChanged.count()==1,"Leaving rapid sketch must restore delegates with no camera-change dependency");
            controller.toggleRapidSketch();
        });
        runCase("Main.qml finished sketch restores plane label delegates",[&] {
            reset(false);
            const auto sketch=controller.execute("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",20},{"h",10}}}}});
            require(sketch.value("ok").toBool(),"Label lifecycle fixture must create a real editable sketch");
            controller.editFeature(sketch.value("id").toString()); settle();
            require(controller.value("sketchActive").toBool(),"Editing a real sketch feature must enter the production sketch editor");
            checkSketchLabels(); controller.finishSketch(); settle();
            require(!controller.value("sketchActive").toBool(),"Finishing the real sketch must leave sketch mode");
            checkLabels(session.model);
        });
        runCase("Main.qml plane labels follow camera without rebuilding tree",[&] {
            reset(false); checkLabels(session.model);
            const auto tree=controller.value("tree");
            QList<QPointer<QQuickItem>> rows; for (const auto &plane : planes) rows.append(findItem(root,"designPlane_"+plane));
            QSignalSpy changed(&controller,&AppController::changed),treeChanged(&controller,&AppController::treeChanged),rebuilding(&controller,&AppController::treeAboutToChange);
            QSignalSpy labelsChanged(viewport,&Viewport::labelsChanged),displayChanged(viewport,&Viewport::displayChanged);
            const auto moved=[&](const std::function<void()> &action) {
                const auto before=planeLabel(root,"XY")->position(); labelsChanged.clear();
                action(); settle(); checkLabels(session.model);
                require(labelsChanged.count()>0 && QLineF(before,planeLabel(root,"XY")->position()).length()>0.1,"Camera changes must move the real Main.qml labels");
            };
            moved([&] { viewport->setView("top"); });
            moved([&] { viewport->restoreCamera({{"yaw",-30},{"pitch",-40},{"scale",7},{"pan_x",20},{"pan_y",15},{"centre",QJsonArray{1,2,3}}}); });
            const auto drag=[&](Qt::KeyboardModifiers modifiers) {
                const auto start=viewport->mapToScene({viewport->width()/2,viewport->height()/2}).toPoint(),end=start+QPoint(48,27);
                QTest::mousePress(window,Qt::MiddleButton,modifiers,start); QTest::mouseMove(window,end,30); QTest::mouseRelease(window,Qt::MiddleButton,modifiers,end);
            };
            moved([&] { drag(Qt::NoModifier); });
            moved([&] { drag(Qt::ShiftModifier); });
            moved([&] {
                const auto anchor=viewport->mapToScene({viewport->width()/2,viewport->height()/2});
                QWheelEvent wheel(anchor,QPointF(window->mapToGlobal(anchor.toPoint())),QPoint(),QPoint(0,120),Qt::NoButton,Qt::NoModifier,Qt::NoScrollPhase,false);
                QCoreApplication::sendEvent(window,&wheel);
            });
            moved([&] { viewport->fit(); });
            labelsChanged.clear(); viewport->restoreCamera(viewport->cameraState()); settle();
            require(labelsChanged.isEmpty(),"Restoring the unchanged camera must preserve the label model");
            require(displayChanged.isEmpty() && changed.isEmpty() && treeChanged.isEmpty() && rebuilding.isEmpty(),"Camera label updates must not emit broad display/controller/tree changes");
            require(controller.value("tree")==tree,"Camera label updates must preserve tree data");
            for (int index=0;index<planes.size();++index) require(rows[index] && rows[index].data()==findItem(root,"designPlane_"+planes[index]),"Camera label updates must preserve actual tree delegate identities");
        });
        runCase("Main.qml plane labels follow viewport resize without tree rebuild",[&] {
            reset(false); checkLabels(session.model);
            const auto original=window->size(); const QSizeF viewportSize(viewport->width(),viewport->height());
            const auto before=planeLabel(root,"XY")->position(); const auto camera=viewport->cameraState();
            QPointer<QQuickItem> row=findItem(root,"designPlane_XY");
            QSignalSpy changed(&controller,&AppController::changed),treeChanged(&controller,&AppController::treeChanged),rebuilding(&controller,&AppController::treeAboutToChange);
            QSignalSpy labelsChanged(viewport,&Viewport::labelsChanged),displayChanged(viewport,&Viewport::displayChanged);
            window->resize(original+QSize(160,100)); settle(); checkLabels(session.model);
            const auto shift=planeLabel(root,"XY")->position()-before;
            require(labelsChanged.count()>0 && std::abs(shift.x()-(viewport->width()-viewportSize.width())/2)<0.01 && std::abs(shift.y()-(viewport->height()-viewportSize.height())/2)<0.01 && shift.manhattanLength()>0,"Window resize must reposition real labels by the viewport centre change");
            require(viewport->cameraState()==camera && displayChanged.isEmpty() && changed.isEmpty() && treeChanged.isEmpty() && rebuilding.isEmpty() && row && row.data()==findItem(root,"designPlane_XY"),"Resizing labels must not mutate the camera or rebuild tree delegates");
            window->resize(original); settle(); checkLabels(session.model);
        });
        runCase("Main.qml plane labels follow model extent and ignore unrelated state",[&] {
            reset(false); checkLabels(session.model); const auto camera=viewport->cameraState();
            const auto before=planeLabel(root,"XY")->position(); auto enlarged=session.model; auto properties=enlarged.value("props").toObject();
            properties["size"]=QJsonArray{140,100,80}; enlarged["props"]=properties;
            QSignalSpy changed(&controller,&AppController::changed),treeChanged(&controller,&AppController::treeChanged),rebuilding(&controller,&AppController::treeAboutToChange);
            QSignalSpy labelsChanged(viewport,&Viewport::labelsChanged);
            viewport->setModel(enlarged); settle(); checkLabels(enlarged);
            require(labelsChanged.count()==1 && viewport->cameraState()==camera && QLineF(before,planeLabel(root,"XY")->position()).length()>1,"Model extent alone must update actual label positions without a camera notification");
            QPointer<QQuickItem> label=planeLabel(root,"XY"); labelsChanged.clear();
            properties["labelTest"]=true; enlarged["props"]=properties;
            viewport->setModel(enlarged); viewport->setSelection({{"faces",QJsonArray{1}}}); viewport->setStyle("shaded_edges");
            const bool dark=viewport->dark(); viewport->setDark(!dark); viewport->setDark(dark); viewport->setPlanesVisible(true); viewport->setPlaneVisible("XY",true); settle();
            require(labelsChanged.isEmpty() && label && label.data()==planeLabel(root,"XY"),"Unrelated model, selection, theme and unchanged visibility updates must preserve label delegates");
            require(changed.isEmpty() && treeChanged.isEmpty() && rebuilding.isEmpty(),"Local label updates must not cause controller/tree notification loops");
            viewport->setModel(session.model); viewport->setSelection(session.selection); settle(); checkLabels(session.model);
        });

        runCase("solid viewport click and empty dismissal",[&] {
            reset(true); const auto document=session.document.toData(); const auto identifier=session.document.features.last().toObject().value("id").toString();
            QSignalSpy picked(viewport,&Viewport::picked),context(viewport,&Viewport::contextPicked);
            clickViewport(solidClickPosition());
            require(picked.count()==1 && context.count()==1 && session.selection.value("feature").toString()==identifier && !session.selection.value("faces").toArray().isEmpty(),"Real solid interior click must select a face belonging to the extrusion");
            require(sceneBar->property("visible").toBool() && sceneBar->property("target").toString()==identifier && !sceneBar->property("items").toList().isEmpty(),"Solid face click must open feature actions in sceneContextBar");
            clickViewport(emptyPosition()); checkEmpty(); require(session.document.toData()==document,"Context popup selection must not edit the solid");
        });
        for (const auto &plane : planes) runCase("viewport double-click sketch "+plane,[&] {
            reset(false); QSignalSpy doubled(viewport,&Viewport::doublePicked);
            const auto point=planePosition(viewport,session.model,plane);
            QTest::mouseDClick(window,Qt::LeftButton,Qt::NoModifier,viewport->mapToScene(point).toPoint()); settle();
            require(doubled.count()==1 && doubled.first()[0].value<QJsonObject>().value("plane").toString()==plane,"Real viewport double click must emit doublePicked for its plane");
            require(controller.value("sketchActive").toBool() && !controller.property("pickingPlane").toBool() && !sceneBar->property("visible").toBool(),"Viewport plane doublePicked must be attached to sketch entry, not only emitted");
            require(viewport->cameraState().value("yaw").toDouble()==(plane=="YZ"?-90:0) && viewport->cameraState().value("pitch").toDouble()==(plane=="XY"?0:-90),"Viewport double-click must enter a sketch on the clicked plane");
        });
        runCase("viewport double-click edits solid feature",[&] {
            reset(true); const auto identifier=session.document.features.last().toObject().value("id").toString(); QSignalSpy doubled(viewport,&Viewport::doublePicked);
            QTest::mouseDClick(window,Qt::LeftButton,Qt::NoModifier,viewport->mapToScene(solidClickPosition()).toPoint()); settle();
            require(doubled.count()==1 && doubled.first()[0].value<QJsonObject>().value("feature").toString()==identifier,"Real solid double click must identify the production feature");
            auto *panel=findItem(root,"featureFormPanel");
            require(controller.value("form").toMap().value("editing").toString()==identifier && panel && panel->isVisible(),"Viewport doublePicked must open the real existing-feature editor");
        });
        runCase("Escape cancels pending plane picking",[&] {
            reset(false); QTest::keyClick(window,Qt::Key_S); settle(); require(controller.property("pickingPlane").toBool(),"Sketch shortcut must arm plane selection");
            escape(); require(!controller.property("pickingPlane").toBool() && !controller.value("sketchActive").toBool(),"Escape must leave plane-picking mode without creating a sketch");
            click(findItem(root,"designPlane_XY")); require(planeBar->property("visible").toBool() && !controller.value("sketchActive").toBool(),"Tree click after cancelling plane picking must return to ordinary plane selection");
        });
        runCase("Escape cancels armed box zoom",[&] {
            reset(true); const auto camera=viewport->cameraState(); click(findIcon(root,"zoom_box")); require(viewport->zoomArmed(),"Real ViewBar box-zoom button must arm zoom");
            escape(); require(!viewport->zoomArmed() && viewport->zoomRect().isEmpty() && viewport->band().isEmpty() && viewport->cameraState()==camera,"Escape before dragging must disarm box zoom without moving the camera");
        });
        runCase("Escape cancels active zoom rectangle and late release",[&] {
            reset(true); const auto camera=viewport->cameraState(); const auto document=session.document.toData(); click(findIcon(root,"zoom_box"));
            const auto start=viewport->mapToScene({viewport->width()-240,viewport->height()-150}).toPoint();
            const auto end=start+QPoint(130,85);
            QTest::mousePress(window,Qt::LeftButton,Qt::NoModifier,start); QTest::mouseMove(window,end,30); settle();
            const bool rectangleCreated=viewport->zoomArmed() && viewport->zoomRect().size()==4;
            escape(); const bool rectangleCancelled=!viewport->zoomArmed() && viewport->zoomRect().isEmpty() && viewport->band().isEmpty();
            QSignalSpy picked(viewport,&Viewport::picked),boxed(viewport,&Viewport::boxed),context(viewport,&Viewport::contextPicked);
            QTest::mouseRelease(window,Qt::LeftButton,Qt::NoModifier,end); settle();
            require(rectangleCreated,"Real mouse drag must create an active production zoom rectangle");
            require(rectangleCancelled,"Escape while dragging must clear zoom state and rectangle immediately");
            require(picked.isEmpty() && boxed.isEmpty() && context.isEmpty(),"Releasing a cancelled drag must not become a new selection or reopen a context toolbar");
            require(viewport->cameraState()==camera && session.document.toData()==document && !sceneBar->property("visible").toBool(),"Cancelled zoom release must not zoom, modify geometry or reopen context actions");
        });
        runCase("Escape dismisses viewport context popup",[&] {
            reset(false); clickViewport(planePosition(viewport,session.model,"XY")); require(sceneBar->property("visible").toBool(),"Escape popup test must start with a real open context bar");
            QSignalSpy requested(&controller,&AppController::contextRequested),visibility(sceneBar,SIGNAL(visibleChanged()));
            QTest::keyClick(window,Qt::Key_Escape); settle();
            require(!sceneBar->property("visible").toBool(),QString("Real Escape key must dismiss sceneContextBar; contextRequested=%1, visibleChanged=%2, opened=%3, activeFocus=%4, selection=%5, popupFocus=%6, popupActiveFocus=%7")
                .arg(requested.count()).arg(visibility.count()).arg(sceneBar->property("opened").toBool())
                .arg(window->activeFocusItem()?window->activeFocusItem()->objectName():QStringLiteral("<none>"))
                .arg(QString::fromUtf8(QJsonDocument(session.selection).toJson(QJsonDocument::Compact)))
                .arg(sceneBar->property("focus").toBool()).arg(sceneBar->property("activeFocus").toBool()));
        });
        for (bool tree : {false,true}) runCase(QString("Main.qml existing %1 plane toolbar closes on sketch shortcut").arg(tree?"tree":"scene"),[&] {
            reset(false);
            if (tree) click(findItem(root,"designPlane_XY")); else clickViewport(planePosition(viewport,session.model,"XY"));
            require((tree?planeBar:sceneBar)->property("visible").toBool(),"Fixture must open the real plane toolbar before S");
            viewport->forceActiveFocus(); QTest::keyClick(window,Qt::Key_S); settle();
            require(controller.value("sketchActive").toBool() && !controller.property("pickingPlane").toBool(),"S on an already selected plane must enter sketch mode");
            require(!sceneBar->property("visible").toBool() && !planeBar->property("visible").toBool() && sceneBar->property("target").toString().isEmpty() && planeBar->property("plane").toString().isEmpty(),"Mode entry must close old actual toolbars and clear their targets");
            checkSketchLabels();
            const auto camera=viewport->cameraState(); QSignalSpy notice(&controller,&AppController::notice);
            controller.planeAction("XZ","normal"); settle();
            require(viewport->cameraState()==camera && !notice.isEmpty(),"A stale reference-plane normal action must not make the active sketch edge-on and must explain why");
            viewport->setView("iso"); const auto oblique=viewport->cameraState();
            controller.planeAction("XY","normal"); settle();
            require(viewport->cameraState()!=oblique && viewport->cameraState().value("pitch").toDouble()==0,"Normal to the active sketch must remain usable");
            viewport->setView("XZ"); require(viewport->cameraState().value("pitch").toDouble()==0,"Direct ViewBar standard views must also reject parallel active-sketch views");
            controller.cancelSketch(); settle();
            click(findItem(root,"designPlane_XZ")); require(planeBar->property("visible").toBool(),"Reference planes remain accessible after leaving sketch");
            click(findIcon(contentOf(planeBar),"normal"));
            require(viewport->cameraState().value("pitch").toDouble()==-90,"Reference-plane normals remain fully available outside sketch mode");
        });
        runCase("Main.qml context cleanup is mode based not every changed",[&] {
            reset(false); click(findItem(root,"designPlane_XY"));
            controller.setTab("feature"); settle();
            require(planeBar->property("visible").toBool() && planeBar->property("plane").toString()=="XY","Ordinary controller changed must not dismiss a valid tree context toolbar");
            QMetaObject::invokeMethod(planeBar,"close"); clickViewport(planePosition(viewport,session.model,"XY"));
            controller.setTab("sketch"); settle();
            require(sceneBar->property("visible").toBool() && sceneBar->property("target").toString()=="plane:XY","Changing ribbon tabs without a mode change must preserve a valid scene context");
        });
        runCase("Main.qml edit owner ignores model tree selections and old saved sketch",[&] {
            reset(false);
            const auto first=controller.execute("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",20},{"h",10}}}}});
            const auto second=controller.execute("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","circle"},{"cx",35},{"cy",0},{"r",3}}}}});
            require(first.value("ok").toBool() && second.value("ok").toBool(),"Owner fixture must create two independent saved sketches");
            const auto owner=first.value("id").toString(),other=second.value("id").toString();
            controller.selectFeature(owner); controller.editFeature(owner); settle();
            const auto selection=session.selection,document=session.document.toData(),camera=viewport->cameraState(); const auto shapes=viewport->sketchShapes();
            QSignalSpy notice(&controller,&AppController::notice),changed(&controller,&AppController::changed),treeChanged(&controller,&AppController::treeChanged);
            click(featureItem(root,other));
            require(session.selection==selection && viewport->sketchShapes()==shapes && viewport->cameraState()==camera && session.document.toData()==document,"Clicking another real tree feature must not replace model selection, editing shapes, camera or document during sketch editing");
            auto *featureBar=window->findChild<QObject *>("designFeatureBar");
            require(featureBar && !featureBar->property("visible").toBool() && !notice.isEmpty() && changed.isEmpty() && treeChanged.isEmpty(),"Rejected model selection must not open a feature toolbar or rebuild the tree");
            controller.editFeature(other); settle();
            require(viewport->sketchShapes()==shapes && session.selection==selection && controller.value("form").toMap().isEmpty(),"Double-click editing another saved feature must not replace the current editor");
            viewport->setSelection({{"feature",other}});
            const auto before=renderViewport(viewport); auto withoutOwner=session.model; auto sketches=withoutOwner.value("sketches").toObject();
            sketches.remove(owner); withoutOwner["sketches"]=sketches; viewport->setModel(withoutOwner);
            require(renderViewport(viewport)==before,"Viewport must omit the saved active owner independently of session selection");
            sketches.remove(other); withoutOwner["sketches"]=sketches; viewport->setModel(withoutOwner);
            require(renderViewport(viewport)!=before,"Unrelated saved reference sketches must remain rendered");
            viewport->setModel(session.model); viewport->setSelection(session.selection);
            clickViewport(project(viewport,{0,5,0}));
            require(!editor->selection().isEmpty() && viewport->sketchShapes()==shapes,"Editor shape selection must remain available while ordinary model tree selection is protected");
            controller.cancelSketch(); settle();
        });
        runCase("Main.qml pending plane picking double-click opens existing sketch cleanly",[&] {
            reset(false);
            const auto sketch=controller.execute("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",20},{"h",10}}}}});
            require(sketch.value("ok").toBool(),"Pending-plane fixture must create a saved sketch");
            viewport->forceActiveFocus(); QTest::keyClick(window,Qt::Key_S); settle();
            require(controller.property("pickingPlane").toBool(),"Fixture must wait for a plane before tree double click");
            auto *item=featureItem(root,sketch.value("id").toString()); require(item && item->isVisible(),"Saved sketch must have a real visible DesignTree row");
            const auto rowPoint=item->mapToScene({item->width()/2,item->height()/2}).toPoint();
            QPointer<QQuickItem> original=item; QTest::mouseClick(window,Qt::LeftButton,Qt::NoModifier,rowPoint);
            require(original && original.data()==featureItem(root,sketch.value("id").toString()),"Pending-plane selection must preserve the real row long enough for a double click");
            QTest::mouseDClick(window,Qt::LeftButton,Qt::NoModifier,rowPoint); settle();
            require(controller.value("sketchActive").toBool() && !controller.property("pickingPlane").toBool(),"Real tree double-click must clear pending plane mode before editing the existing sketch");
            const auto shapes=viewport->sketchShapes(); click(findItem(root,"designPlane_XZ"));
            require(controller.value("sketchActive").toBool() && !controller.property("pickingPlane").toBool() && viewport->sketchShapes()==shapes && controller.value("sketchTitle").toString().contains("XY"),"Later tree plane clicks must not create or switch the already active sketch");
            checkSketchLabels(); controller.cancelSketch(); settle();
        });
        for (bool drafting : {false,true}) runCase(QString("Main.qml sketch box zoom preserves %1").arg(drafting?"draft":"shape selection"),[&] {
            reset(false); controller.sketchOn("XY"); settle();
            if (drafting) {
                controller.useSketchTool("line"); settle(); clickViewport(project(viewport,{0,0,0}));
                require(editor->drafting(),"Box zoom fixture must start an actual uncommitted line draft");
            } else {
                editor->importShapes(QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",20},{"h",10}}}); settle();
                clickViewport(project(viewport,{0,5,0})); require(!editor->selection().isEmpty(),"Box zoom fixture must select an actual sketch shape");
            }
            const auto shapes=viewport->sketchShapes(); const auto document=session.document.toData(),camera=viewport->cameraState();
            const auto selection=editor->selection(); const auto points=editor->draftPoints(); const auto tool=editor->tool();
            click(findIcon(root,"zoom_box")); require(viewport->zoomArmed(),"Sketch ViewBar box zoom must visibly arm");
            QSignalSpy edited(viewport,&Viewport::sketchEdited),selected(editor,&genform::controller::SketchEditor::selectionChanged),picked(viewport,&Viewport::picked),boxed(viewport,&Viewport::boxed);
            const auto start=viewport->mapToScene({viewport->width()/2-110,viewport->height()/2-65}).toPoint(),end=start+QPoint(220,130);
            QTest::mousePress(window,Qt::LeftButton,Qt::NoModifier,start); QTest::mouseMove(window,end,30); settle();
            require(viewport->zoomRect().size()==4 && viewport->band().isEmpty(),"Sketch drag must show a zoom rectangle, not an editor selection band");
            QTest::mouseRelease(window,Qt::LeftButton,Qt::NoModifier,end); settle();
            require(viewport->cameraState().value("scale").toDouble()>camera.value("scale").toDouble() && !viewport->zoomArmed() && viewport->zoomRect().isEmpty(),"Sketch box zoom must actually zoom and fully disarm");
            require(viewport->sketchShapes()==shapes && session.document.toData()==document && editor->selection()==selection && editor->draftPoints()==points && editor->tool()==tool,"Sketch box zoom must preserve committed shapes, selection, draft points and drawing tool");
            require(edited.isEmpty() && selected.isEmpty() && picked.isEmpty() && boxed.isEmpty(),"Sketch box zoom must not emit editing or selection actions");
            if (drafting) { clickViewport(project(viewport,{12,4,0})); require(viewport->sketchShapes().size()==1,"The same line draft must still finish after box zoom"); }
            controller.cancelSketch(); settle();
        });
        runCase("Main.qml sketch transitions clear hover and armed zoom",[&] {
            reset(false); const auto point=viewport->mapToScene(planePosition(viewport,session.model,"XY")).toPoint();
            QTest::mouseMove(window,point,20); settle(); require(controller.value("hoverText").toString().contains("XY"),"Hover fixture must display an actual plane name");
            click(findIcon(root,"zoom_box")); controller.sketchOn("XY"); settle();
            require(!viewport->zoomArmed() && viewport->zoomRect().isEmpty() && !controller.value("hoverText").toString().contains("基准面"),"Sketch entry must clear old model hover and unrelated armed zoom");
            click(findIcon(root,"zoom_box")); controller.cancelSketch(); settle();
            require(!viewport->zoomArmed() && viewport->zoomRect().isEmpty() && viewport->band().isEmpty() && controller.value("hoverText").toString().isEmpty(),"Sketch exit must clear zoom and sketch hover state");
        });
        runCase("Main.qml has no selection route warnings",[&] {
            for (const auto &warning : warnings) require(!warning.contains("ReferenceError") && !warning.contains("TypeError") && !warning.contains("not a function") && !warning.contains("Cannot assign [undefined]"),"QML selection route warning: "+warning);
        });
        QTextStream(stdout)<<QJsonDocument(QJsonObject{{"ok",failures.isEmpty()},{"cases",cases},{"passed",cases-failures.size()},{"failures",QJsonArray::fromStringList(failures)},{"qmlWarnings",QJsonArray::fromStringList(warnings)}}).toJson(QJsonDocument::Compact)<<Qt::endl;
        return failures.isEmpty()?0:1;
    } catch (const std::exception &error) {
        QTextStream(stderr)<<QJsonDocument(QJsonObject{{"ok",false},{"cases",cases},{"error",QString::fromUtf8(error.what())},{"qmlWarnings",QJsonArray::fromStringList(warnings)}}).toJson(QJsonDocument::Compact)<<Qt::endl;
        return 2;
    }
}
