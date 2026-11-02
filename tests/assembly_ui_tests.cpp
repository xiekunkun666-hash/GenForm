#include "genform/controller/controller.hpp"
#include "genform/view/viewport.hpp"
#include <QApplication>
#include <QFile>
#include <QJsonDocument>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickItem>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QTextStream>
#include <stdexcept>

namespace {
void require(bool valid,const QString &message) { if (!valid) throw std::runtime_error(message.toUtf8().constData()); }
void settle() { QCoreApplication::processEvents(); QTest::qWait(120); }
void writeJson(const QString &path,const QJsonObject &data) {
    QFile file(path); require(file.open(QIODevice::WriteOnly),"Cannot create assembly UI fixture");
    const auto bytes=QJsonDocument(data).toJson(); require(file.write(bytes)==bytes.size(),"Fixture write failed");
}
QByteArray bytesOf(const QString &path) {
    QFile file(path); require(file.open(QIODevice::ReadOnly),"Cannot read fixture"); return file.readAll();
}
QQuickItem *findItem(QQuickItem *root,const QString &name) {
    if (root->objectName()==name) return root;
    for (auto *child : root->childItems()) if (auto *found=findItem(child,name)) return found;
    return nullptr;
}
QQuickItem *findAction(QQuickItem *root,const QString &action,bool contextBar) {
    const auto data=root->property("modelData").toMap();
    if (data.value("id").toString()==action) {
        if (contextBar) return root;
        for (auto *child : root->childItems()) if (child->height()>=28 && child->width()>100) return child;
    }
    for (auto *child : root->childItems()) if (auto *found=findAction(child,action,contextBar)) return found;
    return nullptr;
}
QObject *popup(QObject *root,const QString &name) {
    auto *result=root->findChild<QObject *>(name); require(result,"Missing popup: "+name); return result;
}
QQuickItem *popupContent(QObject *root,const QString &name) {
    auto *content=qobject_cast<QQuickItem *>(popup(root,name)->property("contentItem").value<QObject *>());
    require(content,"Missing popup content: "+name); return content;
}
QStringList actions(const QVariantList &items) {
    QStringList result; for (const auto &entry : items) result.append(entry.toMap().value("id").toString()); return result;
}
}

int main(int argc,char **argv) {
    qputenv("QT_QPA_PLATFORM","offscreen"); qputenv("QSG_RHI_BACKEND","software");
    QApplication application(argc,argv);
    QTemporaryDir temporary; qputenv("GENFORM_SETTINGS",temporary.filePath("settings.json").toUtf8());
    QQuickStyle::setStyle("Basic");
    int cases=0;
    try {
        require(temporary.isValid(),"Temporary fixture directory unavailable");
        const QJsonArray features{QJsonObject{{"id","profile"},{"type","sketch"},{"params",QJsonObject{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"w",20},{"h",10}}}}}}},
            QJsonObject{{"id","body"},{"type","extrude"},{"params",QJsonObject{{"sketch","profile"},{"distance",5}}}}};
        const QString partPath=temporary.filePath("plate.gform"),assemblyPath=temporary.filePath("fixture.gasm");
        writeJson(partPath,{{"format","genform-document"},{"version",1},{"features",features},{"props",QJsonObject{}}});
        const QJsonArray parts{QJsonObject{{"name","Base"},{"file","plate.gform"},{"move",QJsonArray{0,0,0}}},
            QJsonObject{{"name","Door"},{"file","plate.gform"},{"move",QJsonArray{30,0,0}}},
            QJsonObject{{"name","Lid"},{"file","plate.gform"},{"move",QJsonArray{60,0,0}}}};
        const QJsonArray joints{QJsonObject{{"name","Door hinge"},{"kind","hinge"},{"parts",QJsonArray{1}},{"base",0},{"axis",QJsonArray{0,0,1}},{"origin",QJsonArray{30,0,0}},{"min",0},{"max",90}},
            QJsonObject{{"name","Lid hinge"},{"kind","hinge"},{"parts",QJsonArray{2}},{"on",0},{"base",0},{"axis",QJsonArray{0,0,1}},{"origin",QJsonArray{60,0,0}},{"min",0},{"max",90}}};
        writeJson(assemblyPath,{{"format","genform-assembly"},{"version",1},{"parts",parts},{"joints",joints},{"mates",QJsonArray{}}});
        const auto originalPart=bytesOf(partPath),originalAssembly=bytesOf(assemblyPath);
        genform::Session session;
        genform::controller::AppController controller(&session);
        auto *simulation=controller.simulation();
        const bool openedAssembly=simulation->openAssembly(assemblyPath);
        require(openedAssembly,"Real assembly must open: "+simulation->value("paramError").toString());
        require(controller.value("docKind").toString()=="assembly","Real controller must enter assembly mode");
        require(simulation->displayModel().value("tris").toArray().size()>0,"Fixture must produce real geometry, not only metadata"); ++cases;
        QQmlApplicationEngine engine;
        QStringList warnings;
        QObject::connect(&engine,&QQmlEngine::warnings,&application,[&](const QList<QQmlError> &errors) { for (const auto &error : errors) warnings.append(error.toString()); });
        engine.rootContext()->setContextProperty("app",&controller);
        engine.rootContext()->setContextProperty("sim",simulation);
        engine.loadData(R"QML(import QtQuick
import QtQuick.Controls
ApplicationWindow {
    width: 400; height: 800; visible: true
    AssemblyTree { objectName: "assemblyTree"; anchors.fill: parent }
}
)QML",QUrl::fromLocalFile(QStringLiteral(GENFORM_SOURCE_DIR "/qml/AssemblyUiHarness.qml")));
        require(!engine.rootObjects().isEmpty(),"AssemblyTree must load: "+warnings.join('\n'));
        auto *window=qobject_cast<QQuickWindow *>(engine.rootObjects().first()); require(window,"Harness must be a real window"); settle();
        auto *tree=window->findChild<QQuickItem *>("assemblyTree"); require(tree,"Assembly tree missing");
        auto click=[&](QQuickItem *item,Qt::MouseButton button=Qt::LeftButton) {
            require(item && item->isVisible() && item->width()>0 && item->height()>0,"Mouse target must be visible");
            QTest::mouseClick(window,button,Qt::NoModifier,item->mapToScene(QPointF(item->width()/2,item->height()/2)).toPoint()); settle();
        };
        auto clickAction=[&](const QString &name,const QString &action,bool contextBar=false) {
            require(popup(tree,name)->property("visible").toBool(),"Popup must be visible: "+name);
            click(findAction(popupContent(tree,name),action,contextBar));
        };
        auto closePopup=[&](const QString &name) { require(QMetaObject::invokeMethod(popup(tree,name),"close"),"Popup close failed"); settle(); };
        auto checkClear=[&] {
            require(simulation->value("picked").toInt()==-1 && simulation->value("pickedJoint").toInt()==-1,"Selection indices must clear together");
            require(session.selection.value("feature").toString().isEmpty() && session.selection.value("faces").toArray().isEmpty() && session.selection.value("edges").toArray().isEmpty(),"Session selection must not retain a stale part or topology");
        };
        auto rename=[&](const QString &value) {
            auto *dialog=popup(tree,"assemblyRenamePopup"); require(dialog->property("visible").toBool(),"Rename action must open the shared popup");
            auto *input=findItem(window->contentItem(),"assemblyRenameInput"); require(input,"Rename editor must exist");
            input->setProperty("text",value); input->forceActiveFocus(); QTest::keyClick(window,Qt::Key_Return); settle();
            require(!dialog->property("visible").toBool(),"Accept must close rename popup");
        };
        int opened=0,edited=-1; QObject::connect(simulation,&genform::controller::SimulationBridge::openPartRequested,&application,[&](const QString &) { ++opened; });
        QObject::connect(simulation,&genform::controller::SimulationBridge::editRequested,&application,[&](int index) { edited=index; });
        QStringList failures;
        auto runCase=[&](const QString &name,const auto &operation) {
            try {
                closePopup("assemblyPartBar"); closePopup("assemblyPartMenu"); closePopup("assemblyRenamePopup");
                require(simulation->openAssembly(assemblyPath),"Cannot reset real assembly fixture"); settle();
                operation(); ++cases; QTextStream(stdout)<<"PASS "<<name<<'\n';
            } catch (const std::exception &exception) { const QString failure=name+": "+QString::fromUtf8(exception.what()); failures.append(failure); QTextStream(stderr)<<"FAIL "<<failure<<'\n'; }
        };
        auto selectPartThenJoint=[&] {
            click(findItem(window->contentItem(),"assemblyPart_1"));
            require(simulation->value("picked").toInt()==1 && simulation->value("pickedJoint").toInt()==-1,"Part click must select only the part");
            require(popup(tree,"assemblyPartBar")->property("visible").toBool(),"Part click must open real ContextBar");
            closePopup("assemblyPartBar"); session.selection["faces"]=QJsonArray{12}; session.selection["edges"]=QJsonArray{9};
            click(findItem(window->contentItem(),"assemblyJoint_0"));
            require(simulation->value("picked").toInt()==-1 && simulation->value("pickedJoint").toInt()==0,"Joint click must clear the formerly picked part");
            require(session.selection.value("feature").toString().isEmpty() && session.selection.value("faces").toArray().isEmpty() && session.selection.value("edges").toArray().isEmpty(),"Joint selection must clear viewport part and topology highlights");
            for (const auto &entry : simulation->value("components").toList()) require(!entry.toMap().value("selected").toBool(),"No component may remain selected with a joint");
        };
        auto checkJointDeleted=[&] {
            require(simulation->value("assembly").toList().size()==3,"Part -> joint -> Delete must never delete a component");
            require(simulation->value("joints").toList().size()==1,"Delete must delete the selected joint, not merely do nothing");
            require(simulation->value("joints").toList().first().toMap().value("on").toInt()==-1,"Child joint must detach from its deleted parent"); checkClear();
        };
        runCase("part -> joint -> deleteJoint",[&] {
            selectPartThenJoint(); simulation->deleteJoint(simulation->value("pickedJoint").toInt()); checkJointDeleted();
            simulation->undoAssembly(); require(simulation->value("joints").toList().size()==2 && !simulation->dirty(),"Undo must restore joint and saved clean state"); checkClear();
            simulation->redoAssembly(); checkJointDeleted(); require(simulation->dirty(),"Redo must dirty only the joint deletion");
        });
        runCase("real controller Delete dispatch and undo",[&] {
            selectPartThenJoint(); controller.runAction("edit.delete"); checkJointDeleted();
            controller.runAction("edit.undo"); require(simulation->value("joints").toList().size()==2 && !simulation->dirty(),"Controller undo must restore joints and clean state"); checkClear();
            controller.runAction("edit.delete"); require(simulation->value("assembly").toList().size()==3 && simulation->value("joints").toList().size()==2,"Delete after undo with no selection must be a no-op");
            controller.runAction("edit.redo"); checkJointDeleted();
        });
        runCase("joint/part mutual exclusion and membership picking",[&] {
            simulation->selectJoint(0); simulation->selectPart(2);
            require(simulation->value("picked").toInt()==2 && simulation->value("pickedJoint").toInt()==-1 && session.selection.value("feature").toString()=="part:2","Joint -> part must be mutually exclusive");
            require(!simulation->dirty() && !simulation->canUndo(),"Selection alone must not dirty assembly or create history");
            simulation->selectPart(-1); checkClear(); simulation->pickJointParts(0); simulation->selectPart(2);
            require(!simulation->dirty() && !simulation->canUndo() && !simulation->value("paramError").toString().isEmpty(),"A part already owned by another joint must be rejected without dirtying history");
            require(simulation->value("joints").toList().first().toMap().value("partIndices").toList()==QVariantList{1},"Rejected membership must preserve original joint parts");
            simulation->selectPart(1);
            require(simulation->value("picked").toInt()==-1 && simulation->value("pickedJoint").toInt()==0,"Joint part-picking must not turn its clicked part into the Delete target");
            require(simulation->value("joints").toList().first().toMap().value("partIndices").toList().isEmpty(),"Joint part-picking must really remove an existing member");
            simulation->undoAssembly(); checkClear();
        });
        runCase("right-menu rename popup",[&] {
            click(findItem(window->contentItem(),"assemblyPart_1"),Qt::RightButton); clickAction("assemblyPartMenu","rename"); rename("  Door renamed  ");
            require(simulation->value("assembly").toList()[1].toMap().value("name").toString()=="Door renamed" && simulation->dirty(),"Right menu rename must change assembly name and dirty state");
            controller.runAction("edit.undo"); require(!simulation->dirty(),"Rename undo must restore saved state");
        });
        runCase("ContextBar rename popup through real contextAction",[&] {
            click(findItem(window->contentItem(),"assemblyPart_1")); clickAction("assemblyPartBar","rename",true); rename("Toolbar rename");
            require(simulation->value("assembly").toList()[1].toMap().value("name").toString()=="Toolbar rename","ContextBar must use the same rename popup, not unsupported");
        });
        runCase("viewport partAction rename signal",[&] {
            simulation->partAction(2,"rename"); settle(); rename("Viewport rename");
            require(simulation->value("assembly").toList()[2].toMap().value("name").toString()=="Viewport rename","Viewport partAction rename must use the shared popup");
        });
        runCase("right-menu edit-position signal",[&] {
            edited=-1; simulation->selectJoint(0); click(findItem(window->contentItem(),"assemblyPart_1"),Qt::RightButton); clickAction("assemblyPartMenu","edit");
            require(edited==1 && simulation->value("picked").toInt()==1 && simulation->value("pickedJoint").toInt()==-1,"Edit-position must select the exact part and emit editRequested");
            require(!simulation->dirty() && !simulation->canUndo(),"Opening edit-position must not mutate assembly");
        });
        runCase("ContextBar edit-position through real contextAction",[&] {
            edited=-1; click(findItem(window->contentItem(),"assemblyPart_1")); clickAction("assemblyPartBar","edit",true);
            require(edited==1 && simulation->value("picked").toInt()==1,"ContextBar edit-position must emit the real bridge signal, not edit a feature named part:1");
        });
        runCase("ContextBar hide through real contextAction",[&] {
            click(findItem(window->contentItem(),"assemblyPart_1")); clickAction("assemblyPartBar","hide",true);
            require(simulation->value("components").toList()[1].toMap().value("hidden").toBool() && !simulation->dirty() && !simulation->canUndo(),"Hide must change visibility, not dirty assembly or enter undo history");
        });
        runCase("right-menu hide/isolate and restoration",[&] {
            click(findItem(window->contentItem(),"assemblyPart_1"),Qt::RightButton); clickAction("assemblyPartMenu","hide");
            require(simulation->value("components").toList()[1].toMap().value("hidden").toBool(),"Right-menu hide must really hide its part");
            click(findItem(window->contentItem(),"assemblyPart_0"),Qt::RightButton); clickAction("assemblyPartMenu","isolate");
            require(simulation->value("isolatedName").toString()=="Base","Isolation must be real"); simulation->exitIsolation();
            require(simulation->value("components").toList()[1].toMap().value("hidden").toBool() && !simulation->value("components").toList()[2].toMap().value("hidden").toBool(),"Exiting isolation must restore the prior hidden set");
            require(!simulation->dirty() && !simulation->canUndo(),"Visibility and isolation are view-only");
        });
        runCase("ContextBar mirror through real contextAction",[&] {
            click(findItem(window->contentItem(),"assemblyPart_1")); clickAction("assemblyPartBar","mirror",true);
            require(simulation->value("assembly").toList()[1].toMap().value("mirror").toBool() && simulation->dirty(),"Mirror popup must create a real undoable assembly change");
        });
        runCase("openPart dirty guard and mirror undo",[&] {
            simulation->mirrorPart(1); const int before=opened; simulation->openPart(1);
            require(opened==before && controller.value("docKind").toString()=="assembly" && simulation->dirty(),"Open must refuse dirty assembly without a discard dialog");
            simulation->undoAssembly(); require(!simulation->dirty(),"Undo mirror must restore clean state"); checkClear();
        });
        runCase("openPart rejects dirty layout document",[&] {
            const int before=opened; session.document.dirty=true; simulation->openPart(1); session.document.dirty=false;
            require(opened==before && controller.value("docKind").toString()=="assembly" && !simulation->dirty(),"Open must not discard a dirty assembly layout document");
        });
        runCase("right-menu reorder selection and undo",[&] {
            click(findItem(window->contentItem(),"assemblyPart_1"),Qt::RightButton); clickAction("assemblyPartMenu","up");
            require(simulation->value("assembly").toList().first().toMap().value("name").toString()=="Door" && session.selection.value("feature").toString()=="part:0","Reorder must remap assembly and viewport selection together");
            controller.runAction("edit.undo"); checkClear();
        });
        runCase("right-menu part delete and undo",[&] {
            click(findItem(window->contentItem(),"assemblyPart_2"),Qt::RightButton); clickAction("assemblyPartMenu","delete");
            require(simulation->value("assembly").toList().size()==2,"Right-menu Delete must really remove its target"); checkClear();
            controller.runAction("edit.undo"); require(simulation->value("assembly").toList().size()==3 && !simulation->dirty(),"Part delete undo must restore every component"); checkClear();
        });
        runCase("ContextBar open and real assembly return",[&] {
            const int before=opened; click(findItem(window->contentItem(),"assemblyPart_1")); clickAction("assemblyPartBar","open",true);
            require(opened==before+1 && controller.value("docKind").toString()=="part" && session.document.path==partPath,"Open popup must open the real part through AppController");
            require(!simulation->dirty() && simulation->value("assembly").toList().size()==3 && !controller.value("returnAssembly").toString().isEmpty(),"Open must preserve assembly and return navigation");
            controller.backToAssembly(); settle(); require(controller.value("docKind").toString()=="assembly" && simulation->value("assembly").toList().size()==3,"Return must restore original assembly"); checkClear();
            controller.runAction("edit.delete"); require(simulation->value("assembly").toList().size()==3 && simulation->value("joints").toList().size()==2,"Delete after returning with no selection must not delete the previously opened part");
        });
        runCase("right-menu open and real assembly return",[&] {
            const int before=opened; click(findItem(window->contentItem(),"assemblyPart_1"),Qt::RightButton); clickAction("assemblyPartMenu","open");
            require(opened==before+1 && controller.value("docKind").toString()=="part" && session.document.path==partPath,"Right-menu open must open the real part");
            controller.backToAssembly(); require(controller.value("docKind").toString()=="assembly" && !simulation->dirty(),"Returning from a clean part must not dirty assembly"); checkClear();
            controller.runAction("edit.delete"); require(simulation->value("assembly").toList().size()==3 && simulation->value("joints").toList().size()==2,"Delete after return must not delete a stale part target");
        });
        runCase("root visibility and no-op rename",[&] {
            click(findItem(window->contentItem(),"assemblyHead_0"),Qt::RightButton); clickAction("assemblyPartMenu","hide_all");
            for (const auto &entry : simulation->value("components").toList()) require(entry.toMap().value("hidden").toBool(),"Hide all must hide every component");
            click(findItem(window->contentItem(),"assemblyHead_0"),Qt::RightButton); clickAction("assemblyPartMenu","show_all");
            for (const auto &entry : simulation->value("components").toList()) require(!entry.toMap().value("hidden").toBool(),"Show all must show every component");
            simulation->renamePart(1,"  Door  "); require(!simulation->dirty() && !simulation->canUndo(),"Unchanged trimmed rename must not create dirty state or undo entry");
        });
        qmlRegisterType<genform::view::Viewport>("GenForm",1,0,"Viewport");
        QQmlApplicationEngine viewportEngine;
        QObject::connect(&viewportEngine,&QQmlEngine::warnings,&application,[&](const QList<QQmlError> &errors) { for (const auto &error : errors) warnings.append(error.toString()); });
        viewportEngine.loadData(R"QML(import QtQuick
import GenForm 1.0
Window {
    width: 800; height: 600; visible: true
    Viewport { objectName: "assemblySelectionViewport"; anchors.fill: parent }
}
)QML",QUrl::fromLocalFile(QStringLiteral(GENFORM_SOURCE_DIR "/qml/AssemblySelectionViewportHarness.qml")));
        require(!viewportEngine.rootObjects().isEmpty(),"Real Viewport harness must load: "+warnings.join('\n'));
        auto *viewportWindow=qobject_cast<QQuickWindow *>(viewportEngine.rootObjects().first()); require(viewportWindow,"Viewport harness must create a real window");
        auto *viewport=viewportWindow->findChild<genform::view::Viewport *>("assemblySelectionViewport"); require(viewport,"Native Viewport must instantiate");
        controller.attach(viewportWindow,viewport,nullptr); settle();
        QSignalSpy viewportPicks(viewport,&genform::view::Viewport::picked); require(viewportPicks.isValid(),"Native Viewport picked signal must be observable");
        auto viewportClick=[&](bool plane,Qt::KeyboardModifiers modifiers=Qt::NoModifier) {
            viewport->setPlanesVisible(true); viewport->setView("top"); viewport->fit(); settle();
            require(viewport->saveImage(temporary.filePath("assembly-selection-viewport.png")),"Real assembly geometry must render before hit testing");
            QPoint point(16,16);
            if (plane) {
                const auto camera=viewport->cameraState(); const auto centre=camera.value("centre").toArray(); const double scale=camera.value("scale").toDouble();
                point=QPointF(viewport->width()/2+camera.value("pan_x").toDouble()+(10-centre[0].toDouble())*scale,
                              viewport->height()/2+camera.value("pan_y").toDouble()-(-10-centre[1].toDouble())*scale).toPoint();
            }
            require(viewport->contains(QPointF(point)),"Viewport click must be inside the real item");
            const auto before=viewportPicks.size();
            QTest::mouseClick(viewportWindow,Qt::LeftButton,modifiers,viewport->mapToScene(QPointF(point)).toPoint()); settle();
            require(viewportPicks.size()==before+1,"Real viewport mouse click must emit exactly one picked event");
            const auto event=viewportPicks.at(before); const auto selection=qvariant_cast<QJsonObject>(event.at(0));
            require(event.at(1).toBool()==modifiers.testFlag(Qt::ControlModifier),"Viewport must propagate the actual Ctrl modifier");
            require(selection.value("feature").toString().isEmpty() && selection.value("faces").toArray().isEmpty() && selection.value("edges").toArray().isEmpty(),"Blank/plane hit must not accidentally hit assembly geometry");
            require(plane?selection.value("plane").toString()=="XY":!selection.contains("plane"),"Mouse hit must really be the requested blank area or XY plane");
        };
        auto deleteWithoutTarget=[&](const QVariantList &beforeParts,const QVariantList &beforeJoints) {
            checkClear();
            for (const auto &entry : simulation->value("components").toList()) require(!entry.toMap().value("selected").toBool(),"Clearing viewport selection must clear every tree component highlight");
            for (const auto &entry : simulation->value("joints").toList()) require(!entry.toMap().value("selected").toBool(),"Clearing viewport selection must clear every joint highlight");
            controller.runAction("edit.delete"); settle();
            require(simulation->value("assembly").toList()==beforeParts && simulation->value("joints").toList()==beforeJoints,"Delete after a blank or plane click must leave all real parts and joints unchanged");
            require(!simulation->dirty() && !simulation->canUndo() && !simulation->canRedo(),"Clearing selection and deleting with no target must not dirty assembly or create history");
        };
        runCase("part -> real viewport blank -> Delete no-op",[&] {
            const auto beforeParts=simulation->value("assembly").toList(),beforeJoints=simulation->value("joints").toList();
            simulation->selectPart(1); require(simulation->value("picked").toInt()==1,"Blank-click regression must start with a selected part");
            viewportClick(false); deleteWithoutTarget(beforeParts,beforeJoints);
        });
        runCase("joint -> real viewport blank -> Delete no-op",[&] {
            const auto beforeParts=simulation->value("assembly").toList(),beforeJoints=simulation->value("joints").toList();
            simulation->selectJoint(0); require(simulation->value("pickedJoint").toInt()==0,"Blank-click regression must start with a selected joint");
            viewportClick(false); deleteWithoutTarget(beforeParts,beforeJoints);
        });
        runCase("Ctrl+viewport blank preserves picked part",[&] {
            auto expectedParts=simulation->value("assembly").toList(); expectedParts.removeAt(1);
            simulation->selectPart(1); viewportClick(false,Qt::ControlModifier);
            require(simulation->value("picked").toInt()==1 && simulation->value("pickedJoint").toInt()==-1 && simulation->value("components").toList()[1].toMap().value("selected").toBool(),"Ctrl+blank must retain the existing part deletion target");
            require(!simulation->dirty() && !simulation->canUndo(),"Ctrl+blank must only affect selection");
            controller.runAction("edit.delete");
            require(simulation->value("assembly").toList()==expectedParts && simulation->value("joints").toList().size()==2,"Delete after Ctrl+blank must remove only the retained part target");
        });
        runCase("Ctrl+viewport blank preserves picked joint",[&] {
            const auto beforeParts=simulation->value("assembly").toList();
            simulation->selectJoint(0); viewportClick(false,Qt::ControlModifier);
            require(simulation->value("picked").toInt()==-1 && simulation->value("pickedJoint").toInt()==0 && simulation->value("joints").toList().first().toMap().value("selected").toBool(),"Ctrl+blank must retain the existing joint deletion target");
            require(!simulation->dirty() && !simulation->canUndo(),"Ctrl+blank must not modify joint data");
            controller.runAction("edit.delete");
            require(simulation->value("assembly").toList()==beforeParts && simulation->value("joints").toList().size()==1,"Delete after Ctrl+blank must remove only the retained joint target");
        });
        runCase("part -> real viewport plane -> Delete no-op",[&] {
            const auto beforeParts=simulation->value("assembly").toList(),beforeJoints=simulation->value("joints").toList();
            simulation->selectPart(1); viewportClick(true);
            require(session.selection.value("plane").toString()=="XY","Ordinary plane mouse click must select the actual XY plane");
            deleteWithoutTarget(beforeParts,beforeJoints);
        });
        runCase("joint -> real viewport plane -> Delete no-op",[&] {
            const auto beforeParts=simulation->value("assembly").toList(),beforeJoints=simulation->value("joints").toList();
            simulation->selectJoint(0); viewportClick(true);
            require(session.selection.value("plane").toString()=="XY","Plane selection must replace the joint target in Session too");
            deleteWithoutTarget(beforeParts,beforeJoints);
        });
        controller.attach(nullptr,nullptr,nullptr);
        require(actions(simulation->partMenu(-1)).contains("show_all") && !actions(simulation->partContext(1)).contains("delete"),"Root menu and safe ContextBar must keep distinct action contracts");
        require(bytesOf(partPath)==originalPart && bytesOf(assemblyPath)==originalAssembly,"UI mutations and navigation must never silently rewrite part or assembly files");
        for (const auto &warning : warnings) require(!warning.contains("ReferenceError") && !warning.contains("TypeError") && !warning.contains("not a function"),"QML route error: "+warning);
        QTextStream(stdout)<<"RESULT "<<cases<<" passed, "<<failures.size()<<" failed; real selection/Delete/undo, popup routes and open/return; files unchanged\n";
        return failures.isEmpty()?0:1;
    } catch (const std::exception &exception) { QTextStream(stderr)<<"FAIL after "<<cases<<" cases: "<<exception.what()<<'\n'; return 1; }
}
