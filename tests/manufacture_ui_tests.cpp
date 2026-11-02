#include "genform/controller/controller.hpp"
#include "genform/controller/manufacture_ui.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/view/sheet.hpp"
#include "genform/view/viewport.hpp"
#include <QApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonDocument>
#include <QPainter>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickItem>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QTemporaryDir>
#include <QTest>
#include <QTextStream>
#include <memory>
#include <stdexcept>

namespace {
using genform::controller::AppController;
using genform::controller::ManufactureUi;

void require(bool valid,const QString &message) {
    if (!valid) throw std::runtime_error(message.toUtf8().constData());
}

QJsonObject command(genform::Session &session,const QString &name,const QJsonObject &arguments={}) {
    const auto reply=session.execute(name,arguments);
    require(reply.value("ok").toBool(),name+": "+reply.value("error").toString());
    return reply;
}

void settle() { QCoreApplication::processEvents(); QTest::qWait(25); }

void waitCheck(AppController &controller) {
    QElapsedTimer timer; timer.start();
    while (controller.value("checkBusy").toBool() && timer.elapsed()<30000) settle();
    require(!controller.value("checkBusy").toBool(),"check timed out");
}

QVariantMap rule(const AppController &controller,const QString &key) {
    for (const auto &entry : controller.value("designRules").toList()) if (entry.toMap().value("key")==key) return entry.toMap();
    throw std::runtime_error("Missing design rule");
}

bool issueCode(const AppController &controller,const QString &code) {
    for (const auto &entry : controller.value("checkIssues").toList()) if (entry.toMap().value("code")==code) return true;
    return false;
}

QQuickItem *findItem(QQuickItem *root,const QString &name) {
    if (root->objectName()==name) return root;
    for (auto *child : root->childItems()) if (auto *found=findItem(child,name)) return found;
    return nullptr;
}

bool redPixel(const QImage &image) {
    for (int vertical=0;vertical<image.height();++vertical) for (int horizontal=0;horizontal<image.width();++horizontal) {
        const auto color=image.pixelColor(horizontal,vertical);
        if (color.alpha()>150 && color.red()>190 && color.green()<115 && color.blue()<115) return true;
    }
    return false;
}

QImage painted(genform::view::Viewport *viewport) {
    QImage image(480,320,QImage::Format_ARGB32_Premultiplied); image.fill(Qt::transparent);
    QPainter painter(&image); viewport->paint(&painter); return image;
}
}

int main(int argc,char **argv) {
    qputenv("QT_QPA_PLATFORM","offscreen"); qputenv("QSG_RHI_BACKEND","software");
    QApplication application(argc,argv); QQuickStyle::setStyle("Basic");
    QTemporaryDir temporary;
    if (!temporary.isValid()) return 2;
    qputenv("GENFORM_SETTINGS",temporary.filePath("settings.json").toUtf8());
    genform::Session session; AppController controller(&session);
    QStringList warnings; QJsonArray passed,blockers;
    try {
        qmlRegisterType<genform::view::Viewport>("GenForm",1,0,"Viewport");
        QQmlApplicationEngine engine;
        QObject::connect(&engine,&QQmlEngine::warnings,&application,[&](const QList<QQmlError> &errors) { for (const auto &error : errors) warnings.append(error.toString()); });
        engine.rootContext()->setContextProperty("app",&controller);
        engine.rootContext()->setContextProperty("apiText",QString());
        engine.loadData(R"(
import QtQuick
import QtQuick.Controls
import GenForm 1.0
import "."
ApplicationWindow {
    width: 1100; height: 760; visible: true
    Viewport { objectName: "manufactureViewport"; width: 480; height: 320; visible: false }
    ToolBtn { objectName: "bindProcessButton"; text: "Bind"; enabled: !app.binding && !app.busy; onClicked: app.bindProcesses() }
    CheckLog { objectName: "manufactureCheckLog"; width: parent.width; openHeight: 300 }
    SettingsDialog { objectName: "manufactureSettings" }
}
)",QUrl::fromLocalFile(QStringLiteral(GENFORM_SOURCE_DIR "/qml/manufacture_ui_test.qml")));
        require(!engine.rootObjects().isEmpty(),"QML manufacture controls failed to load: "+warnings.join('\n'));
        auto *window=qobject_cast<QQuickWindow *>(engine.rootObjects().first()); require(window,"QML window missing");
        auto *viewport=window->findChild<genform::view::Viewport *>("manufactureViewport"); require(viewport,"viewport missing");
        controller.attach(window,viewport,nullptr); settle();
        auto click=[&](QQuickItem *item) {
            require(item,"QML click target missing");
            QTest::mouseClick(window,Qt::LeftButton,Qt::NoModifier,item->mapToScene(QPointF(item->width()/2,item->height()/2)).toPoint()); settle();
        };
        require(!controller.value("checkCompleted").toBool() && controller.value("checkCounts").toMap().value("error").toInt()==0,"initial state");
        require(controller.value("designRules").toList().size()==genform::domain::rule_table().size(),"real rule table exposed");
        controller.toggleCheckLog(); require(!controller.value("checkCompleted").toBool(),"opening log cannot complete check");
        controller.clearCheck(); require(!controller.value("checkCompleted").toBool(),"clearing log cannot complete check");
        passed.append("initial_open_completed_independence");

        auto *settings=window->findChild<QObject *>("manufactureSettings"); require(settings,"settings popup missing");
        require(QMetaObject::invokeMethod(settings,"openPage",Q_ARG(QVariant,QVariant("rules"))),"rules page method missing");
        settle(); QTest::qWait(220);
        auto *wallInput=window->findChild<QQuickItem *>("designRule_min_wall");
        if (!wallInput) wallInput=findItem(window->contentItem(),"designRule_min_wall");
        require(wallInput,"actual rule input missing");
        click(wallInput); QTest::keyClick(window,Qt::Key_A,Qt::ControlModifier);
        QTest::keyClick(window,Qt::Key_2); QTest::keyClick(window,Qt::Key_Period); QTest::keyClick(window,Qt::Key_5);
        QTest::keyClick(window,Qt::Key_Return); settle();
        require(rule(controller,"min_wall").value("value").toDouble()==2.5,"QML rule editor must call setRule");
        require(genform::controller::GuiSettings().value("rules").toMap().value("min_wall").toDouble()==2.5,"user rule must persist");
        {
            genform::Session reopened; AppController next(&reopened);
            require(rule(next,"min_wall").value("value").toDouble()==2.5,"recreated controller must load user rules");
        }
        const auto stored=genform::controller::GuiSettings().value("rules");
        controller.setRule("min_wall","nan"); controller.setRule("min_wall","-1"); controller.setRule("unknown","2");
        require(genform::controller::GuiSettings().value("rules")==stored,"invalid rule cannot silently clamp or persist");
        click(findItem(window->contentItem(),"resetDesignRules"));
        require(!rule(controller,"min_wall").value("changed").toBool(),"actual reset button clears user rule");
        QMetaObject::invokeMethod(settings,"close"); settle();
        passed.append("real_qml_editor_persistence_reopen_validation");

        const auto savedSettingsPath=qgetenv("GENFORM_SETTINGS");
        const auto directorySettings=temporary.filePath("settings-directory");
        require(QDir().mkpath(directorySettings),"unwritable settings fixture");
        qputenv("GENFORM_SETTINGS",directorySettings.toUtf8());
        {
            genform::Session rejected; genform::controller::GuiSettings rejectedSettings;
            ManufactureUi rejectedUi(&rejected,&rejectedSettings);
            QString failure;
            QObject::connect(&rejectedUi,&ManufactureUi::notice,&application,[&](const QString &message) { failure=message; });
            rejectedUi.setRule("min_wall","20");
            require(!failure.isEmpty() && rejected.property("userDesignRules").toJsonObject().isEmpty(),"failed settings save cannot apply rule in memory");
        }
        qputenv("GENFORM_SETTINGS",savedSettingsPath);
        passed.append("failed_persistence_keeps_previous_rules");

        auto *manufacture=controller.findChild<ManufactureUi *>(); require(manufacture,"manufacture helper missing");
        session.busy=true; controller.runCheck(); require(controller.value("checkBusy").toBool(),"check busy observable before queued work");
        waitCheck(controller); session.busy=false;
        require(!controller.value("checkCompleted").toBool() && issueCode(controller,"check_failed") && controller.value("checkCounts").toMap().value("error").toInt()==1,"backend unavailable cannot report clean");
        controller.clearCheck(); controller.runCheck(); controller.clearCheck(); settle();
        require(!controller.value("checkBusy").toBool() && !controller.value("checkCompleted").toBool() && controller.value("checkIssues").toList().isEmpty(),"cleared queued run cannot repopulate report");
        manufacture->setDocumentKind("assembly"); manufacture->runCheck();
        require(!manufacture->completed() && manufacture->counts().value("error").toInt()==1,"assembly cannot pass a part-only check");
        manufacture->setDocumentKind("part");
        controller.bindProcesses(); require(!controller.value("binding").toBool(),"empty model cannot start or claim binding");
        passed.append("failure_busy_clear_cancellation_and_explicit_scope");

#ifdef GENFORM_HAS_OCCT
        command(session,"new_document");
        const auto sketch=command(session,"sketch",{{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",20},{"h",10}}}}}).value("id").toString();
        const auto body=command(session,"extrude",{{"sketch",sketch},{"distance",2}}).value("id").toString();
        require(session.model.value("has_body").toBool(),"real geometry fixture has body");
        auto expected=command(session,"check_design"); controller.runCheck(); waitCheck(controller);
        require(controller.value("checkCompleted").toBool(),"real backend check completed");
        require(QJsonObject::fromVariantMap(controller.value("checkCounts").toMap())==expected.value("counts").toObject(),"GUI counts match native check");
        require(manufacture->checkedRevision()==session.document.revision && !controller.value("checkStale").toBool(),"checked revision captured");
        const auto counts=controller.value("checkCounts"); controller.closeCheck();
        require(controller.value("checkCompleted").toBool() && controller.value("checkCounts")==counts,"close preserves completion/counts");
        controller.toggleCheckLog(); require(controller.value("checkCompleted").toBool(),"reopen preserves report");
        passed.append("real_geometry_backend_report_and_completed_revision_counts");

        const QString metal=QStringLiteral("铝合金 6061"),polymer=QStringLiteral("ABS");
        const auto materialRevision=session.document.revision;
        require(issueCode(controller,"no_material"),"unspecified material is reported before changing it");
        controller.setMaterial(metal);
        require(session.document.revision==materialRevision && session.document.props.value("material")==metal,"material changes independently of geometry revision");
        require(controller.value("checkCompleted").toBool() && controller.value("checkStale").toBool() && manufacture->redFeatures().isEmpty(),"changing material invalidates the completed report");
        controller.runCheck(); waitCheck(controller);
        require(controller.value("checkCompleted").toBool() && !controller.value("checkStale").toBool() && !issueCode(controller,"no_material"),"rerun consumes the new material and refreshes the snapshot");
        controller.setMaterial(polymer);
        require(session.document.revision==materialRevision && controller.value("checkStale").toBool(),"switching between specified materials invalidates the report");
        controller.setMaterial(metal);
        require(controller.value("checkStale").toBool(),"changing material back cannot revive an invalidated report");
        controller.runCheck(); waitCheck(controller);
        controller.setAppearance("#456789");
        require(session.document.revision==materialRevision && controller.value("checkCompleted").toBool() && !controller.value("checkStale").toBool(),"appearance does not invalidate material-dependent checks");
        passed.append("material_snapshot_invalidation_rerun_and_appearance_independence");

        controller.runCheck();
        require(controller.value("checkBusy").toBool(),"material race fixture has queued work");
        controller.setMaterial(polymer);
        require(session.document.revision==materialRevision && controller.value("checkStale").toBool(),"queued check observes a material change without a revision change");
        waitCheck(controller);
        require(!controller.value("checkCompleted").toBool() && controller.value("checkStale").toBool() && issueCode(controller,"check_failed") && manufacture->redFeatures().isEmpty(),"changed queued inputs cannot produce a completed report");
        controller.runCheck(); waitCheck(controller);
        require(controller.value("checkCompleted").toBool() && !controller.value("checkStale").toBool(),"rerun after queued material change uses a fresh snapshot");
        controller.clearCheck(); controller.setMaterial("");
        require(!manufacture->checkedRevision() && !controller.value("checkStale").toBool(),"clear removes the material snapshot");
        controller.runCheck(); waitCheck(controller);
        require(controller.value("checkCompleted").toBool() && !controller.value("checkStale").toBool() && issueCode(controller,"no_material"),"clearing material is consumed by the next check");
        passed.append("queued_material_change_rejected_clear_and_rerun");

        require(!issueCode(controller,"thin_wall"),"default fixture should not violate min wall");
        controller.setRule("min_wall","20");
        require(controller.value("checkStale").toBool() && manufacture->redFeatures().isEmpty(),"changed rule invalidates check");
        controller.runCheck(); waitCheck(controller);
        if (!controller.value("checkCompleted").toBool()) {
            require(issueCode(controller,"check_failed"),"unapplied user rules must fail explicitly");
            blockers.append("Session must merge property(userDesignRules).toJsonObject() into get_design_rules and check_design/bind_processes effective_rules");
            passed.append("unapplied_user_rule_cannot_report_false_success");
        } else {
            require(issueCode(controller,"thin_wall"),"changing user min_wall must change real native findings");
            passed.append("changed_user_rule_changes_native_findings");
        }

        const auto documentRuleRevision=session.document.revision;
        command(session,"set_design_rules",{{"values",QJsonObject{{"min_wall",0.5}}}});
        require(session.document.revision==documentRuleRevision && controller.value("checkStale").toBool() && manufacture->redFeatures().isEmpty(),"document rule changes invalidate checks without a geometry revision change");
        require(rule(controller,"min_wall").value("source")=="document" && rule(controller,"min_wall").value("value").toDouble()==0.5,"document rules take precedence");
        controller.runCheck(); waitCheck(controller); require(!issueCode(controller,"thin_wall"),"document override changes check findings");
        controller.resetRules(); require(session.document.props.value("rules").toObject().value("min_wall").toDouble()==0.5,"reset must preserve document rules");
        passed.append("document_rule_priority_and_reset_preserves_document");

        auto bindingObserved=std::make_shared<bool>(false);
        QObject::connect(&controller,&AppController::changed,&application,[&,bindingObserved] { if (controller.value("binding").toBool()) *bindingObserved=true; });
        click(findItem(window->contentItem(),"bindProcessButton"));
        QElapsedTimer bindingTimer; bindingTimer.start(); while (controller.value("binding").toBool() && bindingTimer.elapsed()<30000) settle();
        const auto process=session.document.find(body).value("process").toObject(); require(!process.isEmpty() && process.value("auto").toBool(),"real QML bind button must persist process metadata");
        bool badge=false;
        for (const auto &entry : controller.value("tree").toList()) {
            const auto row=entry.toMap(); if (row.value("id")!=body) continue;
            badge=row.value("process")==process.value("short").toVariant() && row.value("processColor")==process.value("color").toVariant() && row.value("processWhy")==process.value("why").toVariant() && row.value("processAuto").toBool();
        }
        require(badge,"tree badge must consume stored process fields");
        require(*bindingObserved && !controller.value("binding").toBool(),"real binding busy state must start and finish");
        require(controller.value("checkStale").toBool(),"process binding invalidates previous findings");
        passed.append("actual_bind_button_and_process_tree_badge");

        command(session,"new_document");
        const auto firstSketch=command(session,"sketch",{{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",10},{"h",10}}}}}).value("id").toString();
        command(session,"extrude",{{"sketch",firstSketch},{"distance",5}});
        const auto secondSketch=command(session,"sketch",{{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",10.25},{"cy",0},{"w",10},{"h",10}}}}}).value("id").toString();
        command(session,"extrude",{{"sketch",secondSketch},{"distance",5}});
        controller.runCheck(); waitCheck(controller);
        require(controller.value("checkCompleted").toBool() && !manufacture->redFeatures().isEmpty(),"gap/floating fixture has error highlight features");
        const bool hasHighlight=viewport->metaObject()->indexOfMethod("setCheckHighlights(QStringList)")>=0;
        if (!hasHighlight) blockers.append("Viewport must implement Q_INVOKABLE void setCheckHighlights(const QStringList &) with real red overlay");
        viewport->setPlanesVisible(false); viewport->fit();
        if (hasHighlight) require(redPixel(painted(viewport)),"renderer must actually paint error red, not ordinary selection");
        const auto originalSelection=session.selection;
        click(findItem(window->contentItem(),"toggleCheckHighlight"));
        require(!redPixel(painted(viewport)) && session.selection==originalSelection,"toggle restores appearance and preserves selection");
        click(findItem(window->contentItem(),"toggleCheckHighlight"));
        if (hasHighlight) require(redPixel(painted(viewport)),"toggle restores error red");
        click(findItem(window->contentItem(),"closeCheckLog"));
        require(controller.value("checkCompleted").toBool() && !redPixel(painted(viewport)),"closing log restores appearance without clearing completion");
        controller.toggleCheckLog(); if (hasHighlight) require(redPixel(painted(viewport)),"opening log restores current error red");
        const auto highlightRevision=session.document.revision;
        controller.setMaterial(metal);
        require(session.document.revision==highlightRevision && controller.value("checkStale").toBool() && manufacture->redFeatures().isEmpty() && !redPixel(painted(viewport)) && session.selection==originalSelection,"material change removes stale red pixels and preserves selection without a revision change");
        controller.runCheck(); waitCheck(controller);
        require(controller.value("checkCompleted").toBool() && !controller.value("checkStale").toBool() && !issueCode(controller,"no_material") && !manufacture->redFeatures().isEmpty(),"material rerun restores valid highlight data");
        if (hasHighlight) require(redPixel(painted(viewport)),"material rerun restores actual red pixels");
        passed.append("material_invalidation_and_rerun_update_real_red_pixels");

        session.document.rename(firstSketch,"Inspection snapshot fixture");
        auto materialChangedInCheck=std::make_shared<bool>(false);
        const auto materialConnection=QObject::connect(&session,&genform::Session::changed,&application,[&,materialChangedInCheck] {
            if (session.busy && !*materialChangedInCheck) { *materialChangedInCheck=true; session.document.setProp("material",polymer); }
        });
        controller.runCheck(); waitCheck(controller);
        QObject::disconnect(materialConnection);
        require(*materialChangedInCheck && controller.value("checkCompleted").toBool() && controller.value("checkStale").toBool() && manufacture->redFeatures().isEmpty() && !redPixel(painted(viewport)),"material changes during native inspection invalidate the captured execution snapshot");
        controller.runCheck(); waitCheck(controller);
        require(controller.value("checkCompleted").toBool() && !controller.value("checkStale").toBool() && !manufacture->redFeatures().isEmpty(),"fresh inspection accepts the material changed during the previous run");
        passed.append("material_change_during_native_inspection_invalidates_snapshot");

        command(session,"rename_feature",{{"id",firstSketch},{"name","Changed sketch"}});
        require(controller.value("checkStale").toBool() && !redPixel(painted(viewport)),"model revision change removes obsolete red");
        passed.append(hasHighlight?"real_red_pixels_toggle_close_reopen_and_revision_invalidation":"highlight_state_toggle_close_reopen_and_revision_invalidation");
#else
        controller.runCheck(); waitCheck(controller);
        require(!controller.value("checkCompleted").toBool() && issueCode(controller,"check_failed"),"missing geometry kernel must fail explicitly");
        passed.append("missing_kernel_explicit_failure");
#endif
        require(warnings.isEmpty(),"Unexpected QML warnings: "+warnings.join('\n'));
        QTextStream(stdout)<<QJsonDocument(QJsonObject{{"ok",blockers.isEmpty()},{"checks",passed},{"count",passed.size()},{"blockers",blockers},{"warnings",QJsonArray::fromStringList(warnings)}}).toJson(QJsonDocument::Compact)<<Qt::endl;
        return blockers.isEmpty()?0:3;
    } catch (const std::exception &error) {
        QTextStream(stderr)<<QJsonDocument(QJsonObject{{"ok",false},{"error",QString::fromUtf8(error.what())},{"checks",passed},{"warnings",QJsonArray::fromStringList(warnings)}}).toJson(QJsonDocument::Compact)<<Qt::endl;
        return 1;
    }
}
