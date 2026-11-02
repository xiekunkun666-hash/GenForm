#include "genform/controller/controller.hpp"
#include "genform/platform/window_frame.hpp"
#include "genform/view/sheet.hpp"
#include "genform/view/viewport.hpp"

#include <QAbstractNativeEventFilter>
#include <QApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMetaMethod>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQmlExpression>
#include <QQuickItem>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QSettings>
#include <QSGRendererInterface>
#include <QTemporaryDir>
#include <QTest>
#include <QTextStream>
#include <functional>
#include <stdexcept>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <dwmapi.h>
#endif

#if defined(_MSC_VER) && !defined(_CPPUNWIND)
#error window_controls_tests requires /EHsc for native event filter cleanup
#endif

namespace {
QJsonArray failures;
QJsonArray checkResults;
QJsonArray environmentNotes;

bool check(bool passed,const QString &label) {
    checkResults.append(QJsonObject{{"label",label},{"passed",passed}});
    if (!passed) failures.append(label);
    return passed;
}

void require(bool passed,const QString &label) {
    if (!check(passed,label)) throw std::runtime_error(label.toStdString());
}

bool waitUntil(const std::function<bool()> &predicate) {
    QElapsedTimer timer;
    timer.start();
    while (!predicate() && timer.elapsed()<5000) QTest::qWait(25);
    QTest::qWait(250);
    return predicate();
}

QQuickItem *findItem(QQuickItem *root,const QString &name) {
    if (!root) return nullptr;
    if (root->objectName()==name) return root;
    for (auto *child : root->childItems()) if (auto *found=findItem(child,name)) return found;
    return nullptr;
}

QString handleText(quintptr handle) { return QStringLiteral("0x")+QString::number(handle,16); }

class SystemCommands final : public QAbstractNativeEventFilter {
public:
    explicit SystemCommands(bool enabled) : enabled_(enabled) {
        clock_.start();
        if (enabled_) QCoreApplication::instance()->installNativeEventFilter(this);
    }
    ~SystemCommands() override {
        if (enabled_) QCoreApplication::instance()->removeNativeEventFilter(this);
    }
    void setTarget(quintptr target) { target_=target; }
    void setAction(const QString &action) { action_=action; }
    int count() const { return static_cast<int>(messages_.size()); }
    QJsonArray messages() const { return messages_; }
    bool matchesSince(int start,const QString &expected) const {
        return count()==start+1 && messages_.at(start).toObject().value("command").toString()==expected;
    }
    bool nativeEventFilter(const QByteArray &eventType,void *message,qintptr *result) override {
        Q_UNUSED(result);
#ifdef Q_OS_WIN
        if (!enabled_ || !target_ || !message || (eventType!="windows_generic_MSG" && eventType!="windows_dispatcher_MSG")) return false;
        const auto *native=static_cast<const MSG *>(message);
        if (reinterpret_cast<quintptr>(native->hwnd)!=target_ || native->message!=WM_SYSCOMMAND) return false;
        DWORD process=0;
        GetWindowThreadProcessId(native->hwnd,&process);
        if (process!=GetCurrentProcessId() || process==9916) return false;
        const auto command=native->wParam&static_cast<WPARAM>(0xfff0);
        QString name=QStringLiteral("OTHER");
        if (command==SC_MAXIMIZE) name=QStringLiteral("SC_MAXIMIZE");
        else if (command==SC_RESTORE) name=QStringLiteral("SC_RESTORE");
        else if (command==SC_MINIMIZE) name=QStringLiteral("SC_MINIMIZE");
        messages_.append(QJsonObject{{"action",action_},{"hwnd",handleText(target_)},{"pid",static_cast<int>(process)},
            {"message","WM_SYSCOMMAND"},{"command",name},{"commandValue",static_cast<int>(command)},
            {"wParam",QString::number(static_cast<qulonglong>(native->wParam),16)},
            {"eventType",QString::fromLatin1(eventType)},{"elapsedMs",static_cast<double>(clock_.elapsed())}});
#else
        Q_UNUSED(eventType);
        Q_UNUSED(message);
#endif
        return false;
    }
private:
    bool enabled_=false;
    quintptr target_=0;
    QString action_;
    QElapsedTimer clock_;
    QJsonArray messages_;
};

QJsonObject animationSettings() {
    QJsonObject result{{"readOnly",true},{"settingsModified",false}};
#ifdef Q_OS_WIN
    ANIMATIONINFO animation{};
    animation.cbSize=sizeof(animation);
    SetLastError(ERROR_SUCCESS);
    const bool animationRead=SystemParametersInfoW(SPI_GETANIMATION,sizeof(animation),&animation,0)!=FALSE;
    const DWORD animationError=animationRead?ERROR_SUCCESS:GetLastError();
    BOOL clientAnimation=FALSE;
    SetLastError(ERROR_SUCCESS);
    const bool clientRead=SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION,0,&clientAnimation,0)!=FALSE;
    const DWORD clientError=clientRead?ERROR_SUCCESS:GetLastError();
    result["SPI_GETANIMATION"]=QJsonObject{{"available",animationRead},{"iMinAnimate",animationRead?QJsonValue(animation.iMinAnimate):QJsonValue(QJsonValue::Null)},
        {"win32Error",static_cast<int>(animationError)}};
    result["clientAnimation"]=QJsonObject{{"query","SPI_GETCLIENTAREAANIMATION"},{"available",clientRead},
        {"enabled",clientRead?QJsonValue(clientAnimation!=FALSE):QJsonValue(QJsonValue::Null)},{"win32Error",static_cast<int>(clientError)}};
    result["windowAnimationDisabledBySystem"]=animationRead?QJsonValue(animation.iMinAnimate==0):QJsonValue(QJsonValue::Null);
    if (!animationRead) environmentNotes.append("SPI_GETANIMATION could not be read; animation availability is unknown, not a code failure.");
    else if (!animation.iMinAnimate) environmentNotes.append("Windows has disabled minimize/maximize animations; settings are not changed and this is not a code failure.");
    if (!clientRead) environmentNotes.append("SPI_GETCLIENTAREAANIMATION could not be read; client animation availability is unknown.");
    else if (!clientAnimation) environmentNotes.append("Windows client-area animations are disabled; settings are not changed and this is not a code failure.");
#else
    result["SPI_GETANIMATION"]=QJsonObject{{"available",false},{"reason","Windows only"}};
    result["clientAnimation"]=QJsonObject{{"available",false},{"reason","Windows only"}};
#endif
    return result;
}

#ifdef Q_OS_WIN
QString hresultText(HRESULT result) { return QStringLiteral("0x")+QString::number(static_cast<quint32>(result),16); }

QJsonObject nativeSnapshot(QQuickWindow *window,HWND handle,const QString &stage,Qt::WindowFlags originalFlags) {
    DWORD process=0;
    const DWORD thread=GetWindowThreadProcessId(handle,&process);
    require(IsWindow(handle) && thread && process==GetCurrentProcessId() && process!=9916,stage+": HWND belongs only to this isolated test process");
    require(reinterpret_cast<HWND>(window->winId())==handle,stage+": production native handle is unchanged");
    const LONG_PTR required=WS_CAPTION|WS_THICKFRAME|WS_SYSMENU|WS_MINIMIZEBOX|WS_MAXIMIZEBOX;
    const LONG_PTR style=GetWindowLongPtrW(handle,GWL_STYLE);
    check(window->flags()==originalFlags,stage+": Qt window flags are preserved");
    check(window->flags().testFlag(Qt::FramelessWindowHint),stage+": Qt frameless flag remains set");
    check((style&required)==required,stage+": native caption, resize, system-menu, minimize and maximize styles remain set");
    BOOL composition=FALSE;
    const HRESULT compositionResult=DwmIsCompositionEnabled(&composition);
    int corners=0;
    const HRESULT cornerResult=DwmGetWindowAttribute(handle,33,&corners,sizeof(corners));
    BOOL transitionsDisabled=FALSE;
    const HRESULT transitionResult=DwmGetWindowAttribute(handle,DWMWA_TRANSITIONS_FORCEDISABLED,&transitionsDisabled,sizeof(transitionsDisabled));
    BOOL nonclientRendering=FALSE;
    const HRESULT nonclientResult=DwmGetWindowAttribute(handle,DWMWA_NCRENDERING_ENABLED,&nonclientRendering,sizeof(nonclientRendering));
    if (SUCCEEDED(compositionResult) && composition) {
        if (SUCCEEDED(cornerResult)) check(corners==2,stage+": supported DWM corner preference remains DWMWCP_ROUND");
        if (SUCCEEDED(transitionResult)) check(!transitionsDisabled,stage+": per-window DWM transitions are not forced disabled");
        if (SUCCEEDED(nonclientResult)) check(nonclientRendering,stage+": DWM nonclient rendering remains enabled");
    }
    WINDOWPLACEMENT placement{};
    placement.length=sizeof(placement);
    const bool placementRead=GetWindowPlacement(handle,&placement)!=FALSE;
    return {{"stage",stage},{"hwnd",handleText(reinterpret_cast<quintptr>(handle))},{"pid",static_cast<int>(process)},
        {"qtFlags",QString::number(static_cast<quint32>(window->flags().toInt()),16)},
        {"nativeStyle",QString::number(static_cast<quintptr>(style),16)},{"qtState",static_cast<int>(window->windowStates().toInt())},
        {"iconic",IsIconic(handle)!=FALSE},{"zoomed",IsZoomed(handle)!=FALSE},
        {"placementAvailable",placementRead},{"showCommand",placementRead?QJsonValue(static_cast<int>(placement.showCmd)):QJsonValue(QJsonValue::Null)},
        {"placementFlags",placementRead?QJsonValue(static_cast<int>(placement.flags)):QJsonValue(QJsonValue::Null)},
        {"normalRect",placementRead?QJsonValue(QJsonArray{static_cast<int>(placement.rcNormalPosition.left),static_cast<int>(placement.rcNormalPosition.top),
            static_cast<int>(placement.rcNormalPosition.right),static_cast<int>(placement.rcNormalPosition.bottom)}):QJsonValue(QJsonValue::Null)},
        {"dwmComposition",SUCCEEDED(compositionResult)?QJsonValue(composition!=FALSE):QJsonValue(QJsonValue::Null)},
        {"dwmCompositionHresult",hresultText(compositionResult)},{"cornerHresult",hresultText(cornerResult)},
        {"cornerPreference",SUCCEEDED(cornerResult)?QJsonValue(corners):QJsonValue(QJsonValue::Null)},
        {"transitionsHresult",hresultText(transitionResult)},
        {"transitionsForcedDisabled",SUCCEEDED(transitionResult)?QJsonValue(transitionsDisabled!=FALSE):QJsonValue(QJsonValue::Null)},
        {"nonclientHresult",hresultText(nonclientResult)},
        {"nonclientRendering",SUCCEEDED(nonclientResult)?QJsonValue(nonclientRendering!=FALSE):QJsonValue(QJsonValue::Null)}};
}
#endif
}

int main(int argc,char **argv) {
    QTemporaryDir temporary(QDir::tempPath()+QStringLiteral("/GenForm-window-controls-XXXXXX"));
    if (!temporary.isValid()) {
        QTextStream(stdout)<<QJsonDocument(QJsonObject{{"ok",false},{"checks",0},{"systemCommands",QJsonArray{}},
            {"failures",QJsonArray{"Cannot create isolated settings directory; no application or window was started."}}}).toJson(QJsonDocument::Compact)<<Qt::endl;
        return 2;
    }
    qputenv("GENFORM_PORT","0");
    qputenv("GENFORM_SETTINGS",temporary.filePath("settings.json").toUtf8());
    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) {
#ifdef Q_OS_WIN
        qputenv("QT_QPA_PLATFORM","windows");
#else
        qputenv("QT_QPA_PLATFORM","offscreen");
#endif
    }
    QApplication application(argc,argv);
    application.setQuitOnLastWindowClosed(false);
    QCoreApplication::setOrganizationName(QStringLiteral("GenFormWindowControlsTest"));
    QCoreApplication::setApplicationName(QStringLiteral("GenForm isolated window controls regression"));
    QSettings::setDefaultFormat(QSettings::IniFormat);
    QSettings::setPath(QSettings::IniFormat,QSettings::UserScope,temporary.path());
    QSettings::setPath(QSettings::IniFormat,QSettings::SystemScope,temporary.path());
    QQuickStyle::setStyle(QStringLiteral("Basic"));
    QQuickWindow::setGraphicsApi(QSGRendererInterface::Software);
    const bool nativeBackend=
#ifdef Q_OS_WIN
        QGuiApplication::platformName()==QStringLiteral("windows");
#else
        false;
#endif
    SystemCommands commands(nativeBackend);
    QStringList warnings;
    QJsonArray snapshots;
    QJsonArray actions;
    QJsonObject report{{"platform",QGuiApplication::platformName()},{"qtVersion",QString::fromLatin1(qVersion())},
        {"pid",static_cast<double>(QCoreApplication::applicationPid())},{"protectedUserPid",9916},
        {"mode",nativeBackend?"windows-native":"qml-fallback"},{"GENFORM_PORT",0},{"settingsIsolated",true},
        {"settingsPath",temporary.filePath("settings.json")},{"globalMouseOrKeyboardInput",false},
        {"userDocumentsOpenedOrSaved",false},{"nativeChecksExecuted",false},{"completed",false},
        {"animationVisualEvidence",QJsonObject{{"visuallyVerified",false},{"screenCapturePerformed",false},
            {"note","QTest input, native command delivery and final state are regression evidence, not visual proof of animation or rounded pixels."}}}};
    report["animationSettings"]=animationSettings();
    report["dwmComposition"]=QJsonValue(QJsonValue::Null);
#ifdef Q_OS_WIN
    BOOL composition=FALSE;
    const HRESULT compositionResult=DwmIsCompositionEnabled(&composition);
    report["dwmCompositionHresult"]=hresultText(compositionResult);
    if (SUCCEEDED(compositionResult)) report["dwmComposition"]=composition!=FALSE;
    if (FAILED(compositionResult) || !composition) environmentNotes.append("DWM composition is unavailable or disabled; visual DWM effects cannot be established in this environment, not a code failure.");
#endif
    int exitCode=0;
    try {
        require(QCoreApplication::applicationPid()!=9916,"Test process is not the protected user process PID 9916");
        require(genform::platform::enableNativeWindowFrame(nullptr)==nullptr,"Null native-frame attachment is safe");
        require(!genform::platform::toggleNativeMaximize(nullptr),"Null native maximize is safe");
        require(!genform::platform::minimizeNativeWindow(nullptr),"Null native minimize is safe");
        require(!genform::platform::restoreNativeWindow(nullptr),"Null native restore is safe");
        genform::Session session;
        genform::controller::AppController controller(&session);
        controller.newOf(QStringLiteral("part"));
        for (const auto *method : {"toggleMaximize()","minimizeWindow()","restoreWindow()"}) {
            const int index=controller.metaObject()->indexOfMethod(method);
            require(index>=0 && controller.metaObject()->method(index).access()==QMetaMethod::Public,
                QStringLiteral("Production controller exposes QML callable ")+QString::fromLatin1(method));
        }
        qmlRegisterType<genform::view::Viewport>("GenForm",1,0,"Viewport");
        qmlRegisterType<genform::view::SheetView>("GenForm",1,0,"SheetView");
        QQmlApplicationEngine engine;
        QObject::connect(&engine,&QQmlEngine::warnings,&application,[&](const QList<QQmlError> &errors) {
            for (const auto &error : errors) warnings.append(error.toString());
        });
        engine.rootContext()->setContextProperty("app",&controller);
        engine.rootContext()->setContextProperty("sim",controller.simulation());
        engine.rootContext()->setContextProperty("drawing",controller.drawing());
        engine.rootContext()->setContextProperty("apiText",QString());
        engine.setInitialProperties({{"visible",false}});
        engine.load(QUrl::fromLocalFile(QStringLiteral(GENFORM_SOURCE_DIR "/qml/Main.qml")));
        require(!engine.rootObjects().isEmpty(),"Real production Main.qml loads: "+warnings.join('\n'));
        auto *window=qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        require(window,"Main.qml root is a real QQuickWindow");
        auto *viewport=window->findChild<genform::view::Viewport *>(QStringLiteral("viewport"));
        auto *sheet=window->findChild<genform::view::SheetView *>(QStringLiteral("sheetView"));
        require(viewport && sheet,"Production Main.qml creates its real Viewport and SheetView");
        controller.attach(window,viewport,sheet);
        auto *frame=genform::platform::enableNativeWindowFrame(window);
        require(frame && frame==genform::platform::enableNativeWindowFrame(window),"Production WindowFrame is connected once and attachment is idempotent");
        const auto originalFlags=window->flags();
        require(originalFlags.testFlag(Qt::FramelessWindowHint),"Production Main.qml initially declares Qt::FramelessWindowHint");
        auto *minimize=findItem(window->contentItem(),QStringLiteral("windowMinimizeButton"));
        auto *maximize=findItem(window->contentItem(),QStringLiteral("windowMaximizeButton"));
        require(minimize && maximize,"Real production window minimize and maximize buttons exist by objectName");
        window->setTitle(QStringLiteral("GenForm isolated window controls test (PID %1)").arg(QCoreApplication::applicationPid()));
        window->resize(1100,720);
#ifdef Q_OS_WIN
        const auto handle=nativeBackend?reinterpret_cast<HWND>(window->winId()):nullptr;
        if (nativeBackend) {
            DWORD owner=0;
            GetWindowThreadProcessId(handle,&owner);
            require(IsWindow(handle) && owner==GetCurrentProcessId() && owner!=9916,"Native target HWND belongs to this test, never PID 9916");
            commands.setTarget(reinterpret_cast<quintptr>(handle));
            report["targetHwnd"]=handleText(reinterpret_cast<quintptr>(handle));
        }
#endif
        window->show();
        require(QTest::qWaitForWindowExposed(window,5000),"The isolated production QML window becomes exposed");
        QTest::qWait(300);
        const auto documentBefore=session.document.toData();
        const auto normalSize=window->size();
        const auto capture=[&](const QString &stage) {
#ifdef Q_OS_WIN
            if (nativeBackend) {
                const auto snapshot=nativeSnapshot(window,handle,stage,originalFlags);
                if (snapshots.isEmpty()) {
                    if (snapshot.value("cornerPreference").isNull()) environmentNotes.append("DWM corner preference is not readable/supported on this host; rounded pixels are not visually verified.");
                    if (snapshot.value("transitionsForcedDisabled").isNull()) environmentNotes.append("Per-window DWM transition policy is not readable on this host; see its HRESULT.");
                    if (snapshot.value("nonclientRendering").isNull()) environmentNotes.append("DWM nonclient-rendering state is not readable on this host; see its HRESULT.");
                }
                snapshots.append(snapshot);
                return;
            }
#endif
            check(window->flags()==originalFlags,stage+": fallback Qt flags are preserved");
            snapshots.append(QJsonObject{{"stage",stage},{"qtState",static_cast<int>(window->windowStates().toInt())},
                {"visibility",static_cast<int>(window->visibility())}});
        };
        const auto hasState=[&](Qt::WindowState expected) {
            const auto states=window->windowStates();
            const bool qtMatches=expected==Qt::WindowNoState?states==Qt::WindowNoState:
                states.testFlag(expected) && (expected==Qt::WindowMinimized || !states.testFlag(Qt::WindowMinimized));
#ifdef Q_OS_WIN
            if (nativeBackend) {
                const bool nativeMatches=expected==Qt::WindowMinimized?IsIconic(handle)!=FALSE:
                    expected==Qt::WindowMaximized?IsZoomed(handle)!=FALSE && !IsIconic(handle):!IsIconic(handle) && !IsZoomed(handle);
                return qtMatches && nativeMatches;
            }
#endif
            return qtMatches;
        };
        const auto perform=[&](const QString &stage,const QString &expectedCommand,Qt::WindowState expected,QQuickItem *button) {
            commands.setAction(stage);
            const int start=commands.count();
            QJsonObject action{{"stage",stage},{"input",button?"QTest::mouseClick(QQuickWindow*)":"QQmlExpression: app.restoreWindow()"},
                {"expectedCommand",nativeBackend?QJsonValue(expectedCommand):QJsonValue(QJsonValue::Null)}};
            actions.append(action);
            if (button) {
                require(button->window()==window && button->isVisible() && button->isEnabled() && button->width()>0 && button->height()>0,
                    stage+": click target is a visible enabled production button in the test window");
                require(!window->windowStates().testFlag(Qt::WindowMinimized),stage+": mouse click is never sent to a minimized window");
                const auto point=button->mapToScene(QPointF(button->width()/2,button->height()/2)).toPoint();
                require(QRect(QPoint(0,0),window->size()).contains(point),stage+": click lies inside this test window");
                QTest::mouseClick(window,Qt::LeftButton,Qt::NoModifier,point);
            } else {
                QQmlExpression expression(engine.rootContext(),window,QStringLiteral("app.restoreWindow()"));
                expression.evaluate();
                require(!expression.hasError(),stage+": restoreWindow executes through the real QML context: "+expression.error().toString());
            }
            if (nativeBackend) require(waitUntil([&] { return commands.count()>start; }),stage+": target HWND receives WM_SYSCOMMAND");
            require(waitUntil([&] { return hasState(expected); }),stage+": expected Qt and applicable native window state is reached");
            if (nativeBackend) require(commands.matchesSince(start,expectedCommand),stage+": exactly the expected native system command was observed");
            capture(stage);
        };
        require(waitUntil([&] { return hasState(Qt::WindowNoState); }),"Fixture starts as a normal non-minimized window");
        report["nativeChecksExecuted"]=nativeBackend;
        capture(QStringLiteral("initial normal"));
        perform(QStringLiteral("normal -> maximize button"),QStringLiteral("SC_MAXIMIZE"),Qt::WindowMaximized,maximize);
        check(maximize->property("icon").toString()==QStringLiteral("restore"),"Maximized production button advertises restore");
        perform(QStringLiteral("maximized -> minimize button"),QStringLiteral("SC_MINIMIZE"),Qt::WindowMinimized,minimize);
        if (nativeBackend) {
            perform(QStringLiteral("minimized maximized -> QML restore"),QStringLiteral("SC_RESTORE"),Qt::WindowMaximized,nullptr);
            check(maximize->property("icon").toString()==QStringLiteral("restore"),"Restoring a minimized maximized window retains the restore icon and maximized state");
            perform(QStringLiteral("maximized -> restore button"),QStringLiteral("SC_RESTORE"),Qt::WindowNoState,maximize);
        } else {
            environmentNotes.append("Fallback/offscreen validates real QML mouse routing and safe state changes only; native HWND commands, DWM and maximize-after-minimize restore semantics are not asserted.");
            perform(QStringLiteral("fallback minimized -> QML restore"),QString(),Qt::WindowNoState,nullptr);
            perform(QStringLiteral("fallback normal -> maximize button"),QString(),Qt::WindowMaximized,maximize);
            perform(QStringLiteral("fallback maximized -> restore button"),QString(),Qt::WindowNoState,maximize);
            check(!genform::platform::toggleNativeMaximize(window),"Fallback native maximize safely defers to Qt");
            check(!genform::platform::minimizeNativeWindow(window),"Fallback native minimize safely defers to Qt");
            check(!genform::platform::restoreNativeWindow(window),"Fallback native restore safely defers to Qt");
        }
        check(maximize->property("icon").toString()==QStringLiteral("max"),"Normal production button advertises maximize");
        check(window->size()==normalSize,"Maximize and restore preserve the normal client size");
        perform(QStringLiteral("normal -> minimize button"),QStringLiteral("SC_MINIMIZE"),Qt::WindowMinimized,minimize);
        perform(QStringLiteral("minimized normal -> QML restore"),QStringLiteral("SC_RESTORE"),Qt::WindowNoState,nullptr);
        check(window->size()==normalSize,"Minimize and restore preserve the normal client size");
        check(maximize->property("icon").toString()==QStringLiteral("max"),"Restoring a minimized normal window retains the maximize icon and normal state");
        check(session.document.toData()==documentBefore,"Window controls do not mutate the isolated in-memory document");
        for (const auto &warning : warnings) check(!warning.contains("ReferenceError") && !warning.contains("TypeError") &&
            !warning.contains("not a function") && !warning.contains("Cannot assign [undefined]"),"No QML call-routing error: "+warning);
        report["completed"]=true;
        window->hide();
    } catch (const std::exception &error) {
        report["error"]=QString::fromUtf8(error.what());
        if (failures.isEmpty()) failures.append(QString::fromUtf8(error.what()));
        exitCode=2;
    }
    report["animationSettingsAfter"]=animationSettings();
    report["systemCommands"]=commands.messages();
    report["actions"]=actions;
    report["snapshots"]=snapshots;
    report["checks"]=checkResults.size();
    report["checkResults"]=checkResults;
    report["failures"]=failures;
    report["qmlWarnings"]=QJsonArray::fromStringList(warnings);
    report["environmentNotes"]=environmentNotes;
    report["ok"]=failures.isEmpty() && report.value("completed").toBool();
    QTextStream(stdout)<<QJsonDocument(report).toJson(QJsonDocument::Compact)<<Qt::endl;
    return exitCode?exitCode:(failures.isEmpty()?0:1);
}
