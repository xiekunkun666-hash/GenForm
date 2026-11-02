#include "genform/controller/controller.hpp"
#include "genform/controller/sketch_editor.hpp"
#include "genform/view/viewport.hpp"
#include "genform/view/sheet.hpp"
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QMouseEvent>
#include <QTemporaryDir>
#include <QQmlExpression>
#include <QQmlEngine>
#include <QIcon>
#include <QGuiApplication>

namespace genform::controller {
QJsonObject AppController::smokeTest(view::Viewport *viewport) {
    QJsonArray checks;
    const auto require=[&](bool valid,const QString &name) { if (!valid) throw Error(QStringLiteral("GUI 联调失败：%1").arg(name)); checks.append(name); };
    const auto command=[&](const QString &name,const QJsonObject &arguments=QJsonObject{}) { const auto result=execute(name,arguments); if (!result.value("ok").toBool()) throw Error(result.value("error").toString()); return result; };
    QTemporaryDir temporary;
    try {
        require(temporary.isValid(),"temporary directory"); require(viewport!=nullptr,"original QML Viewport");
        require(theme_ && !QGuiApplication::windowIcon().isNull(),"original Theme and deployable application icon");
        const auto languageBefore=translator_.language(); const auto keysBefore=keys_; const auto snapsBefore=snaps_; const bool darkBefore=dark_,rapidBefore=rapid_;
        const auto qmlText=[&] { QQmlExpression expression(QQmlEngine::contextForObject(viewport),viewport,QStringLiteral("qsTr('常规')")); const auto text=expression.evaluate(); require(!expression.hasError(),"original QML translation expression"); return text.toString(); };
        const auto hasText=[&](const QString &text) { const auto objects=window_->findChildren<QObject *>(); return std::any_of(objects.begin(),objects.end(),[&](QObject *object) { return object->metaObject()->indexOfProperty("text")>=0 && object->property("text").toString()==text; }); };
        setLanguage("en"); require(value("language")=="en" && tr(QStringLiteral("常规"))=="General" && qmlText()=="General","native QTranslator switches original QML to English");
        require(hasText("General"),"existing SettingsDialog text retranslated");
        bool englishLine=false; for (const auto &entry : actionTable().toList()) if (entry.toMap().value("id")=="tool:line") englishLine=entry.toMap().value("title")=="Line"; require(englishLine,"native context action labels localized");
        QObject *settingsDialog=nullptr; for (auto *object : window_->findChildren<QObject *>()) if (object->metaObject()->indexOfProperty("allRows")>=0 && object->metaObject()->indexOfProperty("capturing")>=0) { settingsDialog=object; break; }
        require(settingsDialog && settingsDialog->property("allRows").toList()==actionTable().toList(),"existing SettingsDialog action rows refresh after switch");
        const QVariantMap originalField{{"key","name"},{"type","text"},{"label",QStringLiteral("直线")},{"value",QStringLiteral("直线")}}; const auto localizedField=localizedProperty("form",originalField).toMap(); require(localizedField.value("label")=="Line" && localizedField.value("value")==QStringLiteral("直线"),"localization preserves user field values");
        require(GuiSettings().value("language")=="en","language persisted in isolated settings"); setLanguage("zh"); require(qmlText()==QStringLiteral("常规") && hasText(QStringLiteral("常规")),"original QML language restored");
        setShortcut("tool:line","Ctrl+Alt+L"); setShortcut("tool:rect","Ctrl+Alt+L"); require(keys_.value("tool:line").toString().isEmpty() && keys_.value("tool:rect")=="Ctrl+Alt+L","shortcut reassignment clears prior owner");
        setShortcut("tool:rect","Escape"); require(keys_.value("tool:rect")=="Ctrl+Alt+L","reserved Escape cannot be reassigned");
        require(GuiSettings().value("shortcuts").toMap().value("tool:rect")=="Ctrl+Alt+L","shortcut persistence"); resetShortcut("tool:rect"); require(keys_.value("tool:rect")==defaultKeys_.value("tool:rect"),"individual shortcut reset");
        toggleSnap("grid"); require(snaps_.contains("grid")!=snapsBefore.contains("grid") && GuiSettings().value("snaps").toStringList().contains("grid")==snaps_.contains("grid"),"snaps toggle persisted");
        theme_->setProperty("darkMode",!darkBefore); require(dark_!=darkBefore && GuiSettings().value("dark").toBool()==dark_,"original theme button persists native dark setting"); setSetting("dark",darkBefore); require(theme_->property("darkMode").toBool()==darkBefore,"dark theme restored");
        setSetting("snaps",QStringList(snapsBefore.values())); keys_=keysBefore; savePreference("shortcuts",keys_); setSetting("rapid",false); setLanguage(languageBefore);
        command("new_document"); kind_="part"; start_=false;
        useSketchTool("rect"); sketchOn("XY"); require(sketch_ && editor_->tool()=="rect","pending sketch tool");
        const auto camera=viewport->cameraState(); const double scale=camera.value("scale").toDouble(); const auto centre=camera.value("centre").toArray();
        const auto click=[&](double horizontal,double vertical) {
            const QPointF position(viewport->width()/2+camera.value("pan_x").toDouble()+(horizontal-centre[0].toDouble())*scale,
                viewport->height()/2+camera.value("pan_y").toDouble()-(vertical-centre[1].toDouble())*scale);
            QMouseEvent press(QEvent::MouseButtonPress,position,position,Qt::LeftButton,Qt::LeftButton,Qt::NoModifier); QCoreApplication::sendEvent(viewport,&press);
            QMouseEvent release(QEvent::MouseButtonRelease,position,position,Qt::LeftButton,Qt::NoButton,Qt::NoModifier); QCoreApplication::sendEvent(viewport,&release);
        };
        click(-20,-10); click(20,10); require(shapes_.size()==1,"viewport mouse rectangle");
        useSketchTool("select"); click(-20,-10); require(shapes_.size()==1 && shapes_[0].toObject().value("cx").toDouble()==0,"selection click does not move geometry");
        useSketchTool("point"); setQuickSnap("center"); click(0.2,0.1); require(shapes_.size()==2 && quickSnap_.isEmpty() && shapes_[1].toObject().value("x").toDouble()==0,"one-shot centre snap consumed"); undo(); require(shapes_.size()==1,"snap undo");
        const auto rectangle=shapes_; undo(); require(shapes_.isEmpty(),"sketch undo"); redo(); require(shapes_==rectangle,"sketch redo");
        useSketchTool("circle3"); editor_->press({10,0},0.1); editor_->press({0,10},0.1); editor_->press({-10,0},0.1);
        require(shapes_.size()==2 && shapes_[1].toObject().value("type")=="circle","controller three-point circle");
        useSketchTool("select"); editor_->setSelection({1}); sketchPick("pattern"); setField("nx",2); setField("dx",30); acceptForm();
        require(shapes_.size()==3 && editor_->operation().isEmpty() && form_.isEmpty(),"QML operation form commit");
        undo(); require(shapes_.size()==2,"operation single undo checkpoint"); undo(); require(shapes_.size()==1,"circle undo");
        finishSketch(); require(!sketch_ && session_->document.features.size()==1,"sketch Session commit");
        const auto sketch=session_->document.features[0].toObject(); require(sketch.value("params").toObject().value("shapes").toArray()==rectangle,"persisted sketch JSON");
        const auto created=command("extrude",{{"sketch",sketch.value("id")},{"distance",10}});
        Q_UNUSED(created);
        require(session_->model.value("has_body").toBool() && !session_->model.value("tris").toArray().isEmpty(),"real kernel model mesh");
        command("undo"); require(session_->document.features.size()==1,"Session feature undo"); command("redo"); require(session_->document.features.size()==2 && session_->model.value("has_body").toBool(),"Session feature redo");
        const QString part=temporary.filePath("gui-smoke.gform"); command("save_document",{{"path",part}}); require(QFileInfo::exists(part),"save real part document");
        command("new_document"); command("open_document",{{"path",part}}); require(session_->document.features.size()==2 && session_->model.value("has_body").toBool(),"reopen real part document");
        for (const auto &name : {QString("front"),QString("top"),QString("right"),QString("iso")}) viewport->setView(name);
        require(viewport->saveImage(temporary.filePath("model.png")),"paint native triangle model");
        useSketchTool("select"); sketchOn("XY"); sketchPick("convert"); require(editor_->tool()=="convert" && !editor_->preview().isEmpty(),"real model edge references");
        cancelSketch();
        drawing_->begin(); drawing_->project(); require(drawing_->state().value("ready").toBool(),"native sheet projection");
        require(drawing_->exportFile(temporary.filePath("drawing.svg")),"sheet SVG export");
        const auto featureCount=session_->document.features.size(); kind_="drawing"; undo(); redo(); require(session_->document.features.size()==featureCount && !value("canUndo").toBool() && !value("canRedo").toBool(),"drawing history cannot mutate part document"); kind_="part";
        require(simulation_->beginAssembly(),"empty assembly real pose query"); simulation_->addParts({part,part});
        require(simulation_->value("components").toList().size()==2 && simulation_->displayModel().value("has_body").toBool(),"assembly native meshes");
        simulation_->placePart(1,"move",0,50); require(simulation_->value("components").toList()[1].toMap().value("move").toList()[0].toDouble()==50,"assembly part placement");
        simulation_->undoAssembly(); require(simulation_->value("components").toList()[1].toMap().value("move").toList()[0].toDouble()==0,"assembly undo");
        simulation_->redoAssembly(); require(simulation_->value("components").toList()[1].toMap().value("move").toList()[0].toDouble()==50,"assembly redo");
        simulation_->setParam("width",40); simulation_->setParam("spacing","=width+15");
        bool resolved=false; for (const auto &entry : simulation_->value("params").toList()) { const auto row=entry.toMap(); if (row.value("name")=="spacing") resolved=row.value("value").toDouble()==55; } require(resolved,"assembly parameter dependency uses native resolver");
        simulation_->placePart(1,"move",0,"=spacing"); require(simulation_->value("components").toList()[1].toMap().value("move").toList()[0].toDouble()==55,"assembly expression placement");
        QJsonArray chosenFaces; QSet<QString> owners; for (const auto &entry : simulation_->displayModel().value("faces").toArray()) { const auto face=entry.toObject(); const auto owner=face.value("feature").toString(); if (!owners.contains(owner)) { owners.insert(owner); chosenFaces.append(face.value("id")); } }
        require(owners.size()==2,"assembly topology retains both owners"); const auto measured=simulation_->measureSelection({{"feature","part:1"},{"faces",chosenFaces}}); require(!measured.contains("error") && measured.value("items").toArray().size()==2 && measured.value("distance").toDouble(-1)>0,"assembly measures actual posed parts");
        simulation_->selectPart(1); simulation_->addJoint(1); require(simulation_->value("joints").toList().size()==1,"assembly joint create");
        simulation_->setJoint(0,30); require(simulation_->value("joints").toList()[0].toMap().value("value").toDouble()==30,"joint manual value");
        simulation_->setJointField(0,"base",0); require(simulation_->value("joints").toList()[0].toMap().value("baseIndex").toInt()==0,"joint base QML field");
        simulation_->shiftPart(0,1); require(simulation_->value("joints").toList()[0].toMap().value("baseIndex").toInt()==1 && simulation_->value("joints").toList()[0].toMap().value("partIndices").toList()[0].toInt()==0,"assembly reorder remaps joint references"); simulation_->undoAssembly();
        simulation_->removePart(0); require(simulation_->value("joints").toList()[0].toMap().value("baseIndex").toInt()==-1,"assembly removal clears missing joint base"); simulation_->undoAssembly();
        simulation_->scrubMotion(1); require(simulation_->value("motion").toMap().value("time").toDouble()==1,"motion actual pose");
        const QString assembly=temporary.filePath("gui-smoke.gasm"); require(simulation_->saveAssembly(assembly),"save assembly"); require(simulation_->openAssembly(assembly),"open assembly");
        simulation_->runInterference(); require(simulation_->value("state").toMap().value("error").toString().isEmpty(),"real assembly interference query");
        simulation_->exportBill(temporary.filePath("bom.csv")); require(QFileInfo::exists(temporary.filePath("bom.csv")),"real BOM export");
        simulation_->close(); kind_="part"; session_->document.dirty=false; Q_EMIT kindChanged(); refresh();
        command("new_document"); setSetting("rapid",true); viewport->setView("iso"); const auto rapidCamera=viewport->cameraState(); sketchTool_="circle"; sketchOn("XY"); require(viewport->cameraState()==rapidCamera,"rapid sketch preserves current camera"); editor_->press({0,0},0.1); editor_->press({10,0},0.1); finishSketch(); require(!sketch_ && pickingPlane_ && sketchTool_=="circle" && session_->document.features.size()==1,"rapid sketch saves geometry then awaits next plane");
        selected({{"plane","YZ"},{"faces",QJsonArray{}},{"edges",QJsonArray{}}},false); require(sketch_ && editor_->tool()=="circle","rapid sketch repeats tool on next plane"); cancelSketch(); setSetting("rapid",rapidBefore); require(GuiSettings().value("rapid").toBool()==rapidBefore,"rapid preference restored"); session_->document.dirty=false;
        return {{"ok",true},{"checks",checks},{"count",checks.size()}};
    } catch (const std::exception &exception) {
        simulation_->close(); if (sketch_) cancelSketch(); session_->document.dirty=false;
        return {{"ok",false},{"error",QString::fromUtf8(exception.what())},{"checks",checks},{"count",checks.size()}};
    }
}
}
