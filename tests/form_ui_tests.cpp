#include "genform/controller/controller.hpp"
#include "genform/features.hpp"
#include "genform/view/sheet.hpp"
#include "genform/view/viewport.hpp"
#include <QApplication>
#include <QJsonDocument>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickItem>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QTemporaryDir>
#include <QTest>
#include <QTextStream>
#include <stdexcept>

namespace {
void require(bool valid,const QString &message) { if (!valid) throw std::runtime_error(message.toUtf8().constData()); }
QJsonObject currentField(const genform::controller::AppController &controller,const QString &key) {
    for (const auto &value : controller.value("form").toMap().value("fields").toList()) if (value.toMap().value("key")==key) return QJsonObject::fromVariantMap(value.toMap());
    return {};
}
QQuickItem *findItem(QQuickItem *root,const QString &name) {
    if (root->objectName()==name) return root;
    for (auto *child : root->childItems()) if (auto *found=findItem(child,name)) return found;
    return nullptr;
}
void settle() { QCoreApplication::processEvents(); QTest::qWait(20); }
}

int main(int argc,char **argv) {
    qputenv("QT_QPA_PLATFORM","offscreen");
    qputenv("QSG_RHI_BACKEND","software");
    QApplication application(argc,argv);
    QTemporaryDir settings;
    qputenv("GENFORM_SETTINGS",settings.filePath("settings.json").toUtf8());
    QQuickStyle::setStyle("Basic");
    genform::Session session;
    genform::controller::AppController controller(&session);
    qmlRegisterType<genform::view::Viewport>("GenForm",1,0,"Viewport");
    qmlRegisterType<genform::view::SheetView>("GenForm",1,0,"SheetView");
    QQmlApplicationEngine engine;
    QStringList warnings;
    QObject::connect(&engine,&QQmlEngine::warnings,&application,[&](const QList<QQmlError> &errors) { for (const auto &error : errors) warnings.append(error.toString()); });
    engine.rootContext()->setContextProperty("app",&controller);
    engine.rootContext()->setContextProperty("sim",controller.simulation());
    engine.rootContext()->setContextProperty("drawing",controller.drawing());
    engine.rootContext()->setContextProperty("apiText",QString());
    engine.load(QUrl::fromLocalFile(QStringLiteral(GENFORM_SOURCE_DIR "/qml/Main.qml")));
    int cases=0;
    try {
        require(!engine.rootObjects().isEmpty(),"Main.qml must load: "+warnings.join('\n'));
        auto *window=qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        require(window,"Main.qml must create a window");
        auto *root=window->contentItem();
        controller.attach(window,window->findChild<genform::view::Viewport *>("viewport"),window->findChild<genform::view::SheetView *>("sheetView"));
        controller.startCommand("fillet"); settle(); QTest::qWait(300);
        controller.cancelForm(); settle();
        auto click=[&](QQuickItem *item) { require(item,"click target must exist"); QTest::mouseClick(window,Qt::LeftButton,Qt::NoModifier,item->mapToScene(QPointF(item->width()/2,item->height()/2)).toPoint()); settle(); };
        click(findItem(root,"featureCommand_fillet"));
        auto *panel=findItem(root,"featureFormPanel");
        require(panel && panel->isVisible() && panel->width()>100 && panel->height()>80,"fillet panel must be actually visible in Main.qml"); ++cases;
        auto *radius=findItem(panel,"formInput_radius");
        require(radius && radius->isVisible() && radius->width()>0 && radius->height()>0,"fillet radius editor must be visible"); ++cases;
        radius->forceActiveFocus(); QTest::keyClick(window,Qt::Key_A,Qt::ControlModifier); QTest::keyClick(window,'1'); QTest::keyClick(window,'.'); QTest::keyClick(window,'2'); QTest::keyClick(window,'5');
        session.selection["edges"]=QJsonArray{}; Q_EMIT controller.changed(); settle();
        require(findItem(panel,"formInput_radius")->property("text").toString()=="1.25","changing selections must not discard uncommitted numeric input"); ++cases;
        require(currentField(controller,"edges").value("type")=="info" && !findItem(panel,"formInput_edges"),"edge selection must not ask for JSON"); ++cases;
        const auto before=session.document.features.size();
        controller.acceptForm(); settle();
        require(session.document.features.size()==before && panel->isVisible(),"empty edge selection must keep the form open without creating a feature"); ++cases;
        session.model["edges"]=QJsonArray{QJsonObject{{"id",3},{"mid",QJsonArray{1,2,3}}},QJsonObject{{"id",7},{"mid",QJsonArray{4,5,6}}}};
        session.selection["edges"]=QJsonArray{3,7};
        Q_EMIT controller.changed(); settle();
        require(currentField(controller,"edges").value("selectedCount").toInt()==2,"selection info must count current edges"); ++cases;
        radius=findItem(panel,"formInput_radius");
        radius->setProperty("text",QString("not-a-number"));
        QMetaObject::invokeMethod(panel,"accept"); settle();
        require(session.document.features.size()==before && panel->isVisible(),"invalid editor text must not silently submit an old number"); ++cases;
        controller.setField("radius",-2.0); controller.acceptForm(); settle();
        require(session.document.features.size()==before && controller.value("previewNote").toString().contains(QStringLiteral("大于")),"negative radius must be rejected before execution"); ++cases;
        click(findItem(root,"featureCommand_chamfer"));
        require(findItem(panel,"formInput_distance") && currentField(controller,"edges").value("selectedCount").toInt()==2,"chamfer panel must expose distance and edge count"); ++cases;
        click(findItem(panel,"formCancel")); require(!panel->isVisible(),"cancel must hide the panel"); ++cases;
        const auto first=session.document.add("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"w",20},{"h",10}}}}},QStringLiteral("轮廓一"));
        const auto second=session.document.add("sketch",{{"plane","XY"},{"offset",10},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"w",10},{"h",5}}}}},QStringLiteral("轮廓二"));
        session.selection={};
        controller.startCommand("loft"); settle();
        require(currentField(controller,"sketches").value("type")=="multi","loft must have ordered multi-select profiles, not JSON"); ++cases;
        auto *firstChip=findItem(panel,"formOption_sketches_"+first);
        auto *secondChip=findItem(panel,"formOption_sketches_"+second);
        require(firstChip && secondChip && firstChip->isVisible(),"multi-select profile chips must render"); ++cases;
        click(secondChip);
        require(currentField(controller,"sketches").value("value").toArray()==QJsonArray{second},"second profile click must select it: "+QString::fromUtf8(QJsonDocument(currentField(controller,"sketches")).toJson(QJsonDocument::Compact)));
        click(findItem(panel,"formOption_sketches_"+first));
        require(currentField(controller,"sketches").value("value").toArray()==QJsonArray{second,first},"multi-select clicks must preserve selected order: "+QString::fromUtf8(QJsonDocument(currentField(controller,"sketches")).toJson(QJsonDocument::Compact))); ++cases;
        click(findItem(panel,"formOption_sketches_"+second));
        require(currentField(controller,"sketches").value("value").toArray()==QJsonArray{first},"clicking a selected profile again must remove it"); ++cases;
        controller.acceptForm(); require(session.document.features.size()==2 && panel->isVisible(),"loft requires at least two profiles"); ++cases;
        controller.startCommand("extrude"); settle(); controller.setField("end","offset"); settle();
        require(currentField(controller,"distance").value("hidden").toBool() && !currentField(controller,"gap").value("hidden").toBool() && currentField(controller,"target").value("type")=="info","extrude termination must expose only relevant fields"); ++cases;
        for (const auto &command : genform::features::specs().keys()) {
            controller.startCommand(command); settle();
            require(panel->isVisible() && panel->height()>0,"feature panel must render: "+command);
            for (const auto &value : genform::features::spec(command).value("fields").toArray()) {
                const auto definition=value.toObject(),field=currentField(controller,definition.value("key").toString());
                require(!field.isEmpty(),"missing UI field: "+command+"."+definition.value("key").toString());
                auto *fieldItem=findItem(panel,"formField_"+definition.value("key").toString());
                require(fieldItem && fieldItem->isVisible() && fieldItem->width()>0 && fieldItem->height()>0,"feature field must actually render: "+command+"."+definition.value("key").toString());
                if (definition.value("kind")=="number" || definition.value("kind")=="int") require(field.value("type")=="number","numeric schema must create an editor: "+command);
            }
            ++cases;
        }
        controller.startCommand("revolve"); controller.setField("angle",361); controller.acceptForm();
        require(session.document.features.size()==2 && controller.value("previewNote").toString().contains("360"),"invalid revolve angle must not create a feature"); ++cases;
        controller.startCommand("pattern_linear"); controller.setField("count1",2.5); controller.acceptForm();
        require(session.document.features.size()==2 && controller.value("previewNote").toString().contains(QStringLiteral("整数")),"fractional pattern count must not be rounded silently"); ++cases;
        controller.startCommand("axis"); controller.setField("direction","1,2"); controller.acceptForm();
        require(session.document.features.size()==2,"coordinate width must be validated before execution"); ++cases;
        controller.startCommand("thread"); session.selection["edges"]=QJsonArray{3,7}; controller.acceptForm();
        require(session.document.features.size()==2 && controller.value("previewNote").toString().contains(QStringLiteral("正好")),"thread requires exactly one edge"); ++cases;
        session.selection={};
        controller.startCommand("extrude"); controller.setField("sketch",first); settle();
        auto *distance=findItem(panel,"formInput_distance"); require(distance,"extrude distance editor");
        distance->setProperty("text",QString("7.5"));
        click(findItem(panel,"formAccept"));
        require(session.document.features.size()==3 && session.model.value("has_body").toBool() && !panel->isVisible(),"real confirm click must build an extrusion: "+controller.value("previewNote").toString());
        const auto extrusion=session.document.features.last().toObject();
        require(extrusion.value("params").toObject().value("distance").toDouble()==7.5,"confirm must commit the focused editor's current text"); cases+=2;
        controller.startCommand("cut"); controller.acceptForm(); settle();
        require(session.document.features.size()==4 && session.document.features.last().toObject().value("params").toObject().value("op")=="cut","through-cut must not submit invalid hidden numeric fields"); ++cases;
        controller.undo(); settle();
        require(session.document.features.size()==3,"undo test cut before fillet");
        const auto edge=session.model.value("edges").toArray().first().toObject();
        session.selection["edges"]=QJsonArray{edge.value("id")};
        controller.startCommand("fillet"); controller.setField("radius",0.5); controller.acceptForm(); settle();
        require(session.document.features.size()==4 && !panel->isVisible(),"fillet must accept selected edges without JSON: "+controller.value("previewNote").toString());
        const auto fillet=session.document.features.last().toObject();
        require(fillet.value("params").toObject().value("edges").isArray() && !fillet.value("params").toObject().contains("note"),"selection info must not become command text"); cases+=2;
        session.selection={};
        controller.editFeature(fillet.value("id").toString()); settle();
        require(currentField(controller,"edges").value("value").toString().contains(QStringLiteral("沿用")),"edit must explain retained edge references");
        controller.setField("radius",0.75); controller.acceptForm(); settle();
        require(session.document.features.size()==4 && !panel->isVisible() && session.document.find(fillet.value("id").toString()).value("params").toObject().value("radius").toDouble()==0.75,"edit without new picks must retain original references"); cases+=2;
        controller.startCommand("hole"); settle();
        require(panel->height()<=panel->parentItem()->height()-panel->y() && panel->implicitHeight()>=panel->height(),"long forms must stay bounded to the viewport"); ++cases;
        auto *scroller=findItem(panel,"formScroller");
        auto *flickable=scroller->property("contentItem").value<QObject *>();
        require(flickable,"long form must have a scrollable viewport");
        flickable->setProperty("contentY",flickable->property("contentHeight").toDouble()-flickable->property("height").toDouble()); settle();
        const auto bottom=findItem(panel,"formAccept")->mapToItem(panel,QPointF(0,0));
        require(bottom.y()>=0 && bottom.y()+30<=panel->height(),"scrolling a long form must expose confirm buttons"); ++cases;
        const auto pointA=session.document.add("point",{{"position",QJsonArray{QJsonArray{0,0,0}}}},"point A");
        const auto pointB=session.document.add("point",{{"position",QJsonArray{QJsonArray{1,1,1}}}},"point B");
        controller.startCommand("curve_points");
        require(currentField(controller,"points").value("options").toArray()==QJsonArray{QJsonObject{{"value",pointA},{"label","point A"}},QJsonObject{{"value",pointB},{"label","point B"}}},"reference-point curves must offer point features instead of solids"); ++cases;
        controller.startCommand("curve_composite");
        require(controller.value("form").toMap().value("pick").toMap().value("optional").toBool() && currentField(controller,"curves").value("options").toArray().size()>=2,"composite curves must permit sketches without mandatory edge picks"); ++cases;
        controller.cancelForm();
        require(warnings.isEmpty(),"QML warnings: "+warnings.join('\n'));
        QTextStream(stdout)<<QJsonDocument(QJsonObject{{"ok",true},{"cases",cases},{"qmlWarnings",QJsonArray::fromStringList(warnings)}}).toJson(QJsonDocument::Compact)<<Qt::endl;
        return 0;
    } catch (const std::exception &exception) {
        QTextStream(stdout)<<QJsonDocument(QJsonObject{{"ok",false},{"cases",cases},{"error",QString::fromUtf8(exception.what())},{"qmlWarnings",QJsonArray::fromStringList(warnings)}}).toJson(QJsonDocument::Compact)<<Qt::endl;
        return 2;
    }
}
