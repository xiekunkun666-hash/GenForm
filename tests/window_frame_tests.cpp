#include "genform/platform/window_frame.hpp"

#include <QCoreApplication>
#include <QElapsedTimer>
#include <QEvent>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QQuickWindow>
#include <QScreen>
#include <QTextStream>
#include <QThread>
#include <QWindow>
#include <cmath>
#include <functional>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <windowsx.h>
#include <dwmapi.h>
#endif

namespace {
QJsonArray failures;
int checks=0;

void check(bool passed,const QString &label) {
    ++checks;
    if (!passed) failures.append(label);
}

void settle(int milliseconds=120) {
    QElapsedTimer timer;
    timer.start();
    while (timer.elapsed()<milliseconds) {
        QCoreApplication::processEvents(QEventLoop::AllEvents,10);
        QThread::msleep(5);
    }
}

bool waitUntil(const std::function<bool()> &predicate) {
    QElapsedTimer timer;
    timer.start();
    while (!predicate() && timer.elapsed()<3000) settle(10);
    settle();
    return predicate();
}

#ifdef Q_OS_WIN
QJsonArray nativeRect(const RECT &rect) { return {static_cast<int>(rect.left),static_cast<int>(rect.top),static_cast<int>(rect.right),static_cast<int>(rect.bottom)}; }

RECT clientRect(HWND handle) {
    RECT rect{};
    GetClientRect(handle,&rect);
    POINT origin{rect.left,rect.top};
    ClientToScreen(handle,&origin);
    OffsetRect(&rect,origin.x,origin.y);
    return rect;
}

LRESULT hitTest(HWND handle,int horizontal,int vertical) {
    return SendMessageW(handle,WM_NCHITTEST,0,MAKELPARAM(horizontal,vertical));
}

QJsonObject testWindow(QWindow &window) {
    auto *frame=genform::platform::enableNativeWindowFrame(&window);
    check(frame!=nullptr,QStringLiteral("native frame exists"));
    check(frame==genform::platform::enableNativeWindowFrame(&window),QStringLiteral("attach is idempotent"));
    window.show();
    settle();
    const auto handle=reinterpret_cast<HWND>(window.winId());
    const LONG_PTR required=WS_CAPTION|WS_THICKFRAME|WS_SYSMENU|WS_MINIMIZEBOX|WS_MAXIMIZEBOX;
    const auto style=GetWindowLongPtrW(handle,GWL_STYLE);
    check((style&required)==required,QStringLiteral("native system and resize styles"));
    check(window.flags().testFlag(Qt::FramelessWindowHint),QStringLiteral("Qt remains frameless"));
    RECT normal{};
    GetWindowRect(handle,&normal);
    const auto normalClient=clientRect(handle);
    check(EqualRect(&normal,&normalClient),QStringLiteral("no native caption or visible frame inset"));
    int corners=0;
    const HRESULT cornerResult=DwmGetWindowAttribute(handle,33,&corners,sizeof(corners));
    check(FAILED(cornerResult) || corners==2,QStringLiteral("supported DWM corner preference is round"));
    COLORREF border=0;
    const HRESULT borderResult=DwmGetWindowAttribute(handle,34,&border,sizeof(border));
    const COLORREF noBorder=0xfffffffe;
    const HRESULT borderSetResult=DwmSetWindowAttribute(handle,34,&noBorder,sizeof(noBorder));
    check(FAILED(borderSetResult) || FAILED(borderResult) || border==noBorder,QStringLiteral("readable DWM border is suppressed"));
    BOOL transitionsDisabled=FALSE;
    const HRESULT transitionResult=DwmGetWindowAttribute(handle,DWMWA_TRANSITIONS_FORCEDISABLED,&transitionsDisabled,sizeof(transitionsDisabled));
    const HRESULT transitionSetResult=DwmSetWindowAttribute(handle,DWMWA_TRANSITIONS_FORCEDISABLED,&transitionsDisabled,sizeof(transitionsDisabled));
    check(SUCCEEDED(transitionSetResult),QStringLiteral("native DWM transitions can be enabled"));
    BOOL nonclientRendering=FALSE;
    const HRESULT nonclientResult=DwmGetWindowAttribute(handle,DWMWA_NCRENDERING_ENABLED,&nonclientRendering,sizeof(nonclientRendering));
    check(SUCCEEDED(nonclientResult) && nonclientRendering,QStringLiteral("DWM nonclient rendering remains available"));
    const int centerX=(normal.left+normal.right)/2;
    const int centerY=(normal.top+normal.bottom)/2;
    check(hitTest(handle,normal.left+1,centerY)==HTLEFT,QStringLiteral("left resize hit"));
    check(hitTest(handle,normal.right-2,centerY)==HTRIGHT,QStringLiteral("right resize hit"));
    check(hitTest(handle,centerX,normal.top+1)==HTTOP,QStringLiteral("top resize hit"));
    check(hitTest(handle,centerX,normal.bottom-2)==HTBOTTOM,QStringLiteral("bottom resize hit"));
    check(hitTest(handle,normal.left+1,normal.top+1)==HTTOPLEFT,QStringLiteral("top-left resize hit"));
    check(hitTest(handle,normal.right-2,normal.top+1)==HTTOPRIGHT,QStringLiteral("top-right resize hit"));
    check(hitTest(handle,normal.left+1,normal.bottom-2)==HTBOTTOMLEFT,QStringLiteral("bottom-left resize hit"));
    check(hitTest(handle,normal.right-2,normal.bottom-2)==HTBOTTOMRIGHT,QStringLiteral("bottom-right resize hit"));
    check(hitTest(handle,centerX,normal.top+30)==HTCLIENT,QStringLiteral("QML title bar remains client-owned"));
    check(hitTest(handle,centerX,centerY)==HTCLIENT,QStringLiteral("content remains client-owned"));
    MINMAXINFO limits{};
    limits.ptMaxTrackSize={100000,100000};
    SendMessageW(handle,WM_GETMINMAXINFO,0,reinterpret_cast<LPARAM>(&limits));
    const UINT dpi=GetDpiForWindow(handle);
    const qreal ratio=window.devicePixelRatio();
    check(limits.ptMinTrackSize.x==static_cast<LONG>(std::ceil(window.minimumWidth()*ratio)),QStringLiteral("DPI-scaled minimum width"));
    check(limits.ptMinTrackSize.y==static_cast<LONG>(std::ceil(window.minimumHeight()*ratio)),QStringLiteral("DPI-scaled minimum height"));
    check(limits.ptMaxTrackSize.x==static_cast<LONG>(std::ceil(window.maximumWidth()*ratio)),QStringLiteral("DPI-scaled maximum width"));
    check(limits.ptMaxTrackSize.y==static_cast<LONG>(std::ceil(window.maximumHeight()*ratio)),QStringLiteral("DPI-scaled maximum height"));
    window.setMaximumSize(QSize(16777215,16777215));
    check(genform::platform::toggleNativeMaximize(&window),QStringLiteral("native maximize command posted"));
    check(waitUntil([handle] { return IsZoomed(handle)!=FALSE; }),QStringLiteral("native maximize completed"));
    MONITORINFO monitor{};
    monitor.cbSize=sizeof(monitor);
    GetMonitorInfoW(MonitorFromWindow(handle,MONITOR_DEFAULTTONEAREST),&monitor);
    const auto maximizedClient=clientRect(handle);
    check(EqualRect(&maximizedClient,&monitor.rcWork),QStringLiteral("maximized client exactly fits monitor work area"));
    check(hitTest(handle,monitor.rcWork.left+1,monitor.rcWork.top+30)==HTCLIENT,QStringLiteral("maximized edges do not resize"));
    check(genform::platform::minimizeNativeWindow(&window),QStringLiteral("native minimize from maximized posted"));
    check(waitUntil([handle] { return IsIconic(handle)!=FALSE; }),QStringLiteral("native minimize from maximized completed"));
    WINDOWPLACEMENT minimizedPlacement{};
    minimizedPlacement.length=sizeof(minimizedPlacement);
    check(GetWindowPlacement(handle,&minimizedPlacement)!=FALSE && (minimizedPlacement.flags&WPF_RESTORETOMAXIMIZED),QStringLiteral("minimize preserves restore-to-maximized placement"));
    check(genform::platform::restoreNativeWindow(&window),QStringLiteral("native restore from minimized posted"));
    check(waitUntil([handle] { return !IsIconic(handle) && IsZoomed(handle); }),QStringLiteral("minimized maximized window restores maximized"));
    check(genform::platform::toggleNativeMaximize(&window),QStringLiteral("native restore command posted"));
    check(waitUntil([handle,&window] { return !IsZoomed(handle) && window.windowState()==Qt::WindowNoState; }),QStringLiteral("native restore completed"));
    RECT restored{};
    GetWindowRect(handle,&restored);
    check(EqualRect(&restored,&normal),QStringLiteral("normal geometry restored"));
    check(genform::platform::minimizeNativeWindow(&window),QStringLiteral("native minimize from normal posted"));
    check(waitUntil([handle] { return IsIconic(handle)!=FALSE; }),QStringLiteral("native minimize from normal completed"));
    check(genform::platform::restoreNativeWindow(&window),QStringLiteral("native restore to normal posted"));
    check(waitUntil([handle] { return !IsIconic(handle) && !IsZoomed(handle); }),QStringLiteral("minimized normal window restores normal"));
    GetWindowRect(handle,&restored);
    check(EqualRect(&restored,&normal),QStringLiteral("minimize and restore preserve normal geometry"));
    SetWindowLongPtrW(handle,GWL_STYLE,GetWindowLongPtrW(handle,GWL_STYLE)&~(WS_CAPTION|WS_THICKFRAME));
    settle();
    check((GetWindowLongPtrW(handle,GWL_STYLE)&required)==required,QStringLiteral("native styles repaired after external style refresh"));
    window.showFullScreen();
    settle();
    check(window.windowState()==Qt::WindowFullScreen,QStringLiteral("Qt fullscreen entered"));
    check(genform::platform::toggleNativeMaximize(&window),QStringLiteral("fullscreen restore handled"));
    check(waitUntil([&window] { return window.windowState()==Qt::WindowNoState; }),QStringLiteral("fullscreen restores instead of maximizing again"));
    check((GetWindowLongPtrW(handle,GWL_STYLE)&required)==required,QStringLiteral("native styles survive fullscreen restore"));
    QEvent dpiChange(QEvent::ScreenChangeInternal);
    QCoreApplication::sendEvent(&window,&dpiChange);
    settle();
    check((GetWindowLongPtrW(handle,GWL_STYLE)&required)==required,QStringLiteral("native styles survive DPI refresh"));
    window.setMinimumSize(window.size());
    window.setMaximumSize(window.size());
    settle();
    RECT fixed{};
    GetWindowRect(handle,&fixed);
    check(hitTest(handle,fixed.left+1,(fixed.top+fixed.bottom)/2)==HTCLIENT,QStringLiteral("fixed-width window does not offer resize"));
    window.hide();
    return {{"dpi",static_cast<int>(dpi)},{"devicePixelRatio",ratio},{"style",QString::number(style,16)},{"cornerHresult",QString::number(static_cast<quint32>(cornerResult),16)},
        {"cornerPreference",corners},{"borderHresult",QString::number(static_cast<quint32>(borderResult),16)},
        {"borderSetHresult",QString::number(static_cast<quint32>(borderSetResult),16)},
        {"transitionGetHresult",QString::number(static_cast<quint32>(transitionResult),16)},
        {"transitionSetHresult",QString::number(static_cast<quint32>(transitionSetResult),16)},
        {"nonclientRendering",nonclientRendering!=FALSE},{"normal",nativeRect(normal)},
        {"workArea",nativeRect(monitor.rcWork)},{"maximizedClient",nativeRect(maximizedClient)}};
}
#endif
}

int main(int argc,char **argv) {
    QGuiApplication application(argc,argv);
    QJsonObject report{{"platform",QGuiApplication::platformName()},{"qtVersion",QString::fromLatin1(qVersion())}};
    check(genform::platform::enableNativeWindowFrame(nullptr)==nullptr,QStringLiteral("null attach is safe"));
    check(!genform::platform::toggleNativeMaximize(nullptr),QStringLiteral("null maximize is safe"));
    check(!genform::platform::minimizeNativeWindow(nullptr),QStringLiteral("null minimize is safe"));
    check(!genform::platform::restoreNativeWindow(nullptr),QStringLiteral("null restore is safe"));
#ifdef Q_OS_WIN
    if (QGuiApplication::platformName()==QStringLiteral("windows")) {
        BOOL composition=FALSE;
        const HRESULT compositionResult=DwmIsCompositionEnabled(&composition);
        report["dwmComposition"]=SUCCEEDED(compositionResult) && composition;
        QJsonArray results;
        for (auto *screen : QGuiApplication::screens()) {
            QWindow window;
            window.setTitle(QStringLiteral("GenForm isolated window frame verification"));
            window.setFlags(Qt::Window|Qt::FramelessWindowHint|Qt::WindowDoesNotAcceptFocus);
            window.setScreen(screen);
            window.setGeometry(QRect(screen->availableGeometry().topLeft()+QPoint(80,80),QSize(640,480)));
            window.setMinimumSize(QSize(320,240));
            window.setMaximumSize(QSize(1000,800));
            window.show();
            settle();
            auto result=testWindow(window);
            result["screen"]=screen->name();
            results.append(result);
        }
        QQuickWindow quickWindow;
        quickWindow.setTitle(QStringLiteral("GenForm isolated Qt Quick frame verification"));
        quickWindow.setFlags(Qt::Window|Qt::FramelessWindowHint|Qt::WindowDoesNotAcceptFocus);
        quickWindow.setColor(Qt::white);
        quickWindow.setGeometry(QRect(QGuiApplication::primaryScreen()->availableGeometry().topLeft()+QPoint(100,100),QSize(640,480)));
        quickWindow.setMinimumSize(QSize(320,240));
        quickWindow.setMaximumSize(QSize(1000,800));
        quickWindow.show();
        settle();
        report["quickWindow"]=testWindow(quickWindow);
        QWindow lifecycle;
        lifecycle.setFlags(Qt::Window|Qt::FramelessWindowHint);
        auto *frame=genform::platform::enableNativeWindowFrame(&lifecycle);
        check(lifecycle.handle()!=nullptr,QStringLiteral("attach creates native handle"));
        QEvent dpiChange(QEvent::ScreenChangeInternal);
        QCoreApplication::sendEvent(&lifecycle,&dpiChange);
        lifecycle.destroy();
        settle();
        check(lifecycle.handle()==nullptr,QStringLiteral("queued refresh does not recreate destroyed native handle"));
        lifecycle.create();
        settle();
        check(frame==genform::platform::enableNativeWindowFrame(&lifecycle),QStringLiteral("frame survives native handle recreation"));
        const auto recreated=reinterpret_cast<HWND>(lifecycle.winId());
        check((GetWindowLongPtrW(recreated,GWL_STYLE)&WS_THICKFRAME)!=0,QStringLiteral("recreated handle receives resize style"));
        report["windows"]=results;
    } else
#endif
    {
        QWindow window;
        window.setFlags(Qt::Window|Qt::FramelessWindowHint);
        auto *frame=genform::platform::enableNativeWindowFrame(&window);
        check(frame!=nullptr,QStringLiteral("fallback attach is safe"));
        check(frame==genform::platform::enableNativeWindowFrame(&window),QStringLiteral("fallback attach is idempotent"));
        check(!genform::platform::toggleNativeMaximize(&window),QStringLiteral("fallback defers maximize to Qt"));
        check(!genform::platform::minimizeNativeWindow(&window),QStringLiteral("fallback defers minimize to Qt"));
        check(!genform::platform::restoreNativeWindow(&window),QStringLiteral("fallback defers restore to Qt"));
    }
    report["checks"]=checks;
    report["failures"]=failures;
    report["ok"]=failures.isEmpty();
    QTextStream(stdout)<<QJsonDocument(report).toJson(QJsonDocument::Compact)<<Qt::endl;
    return failures.isEmpty()?0:1;
}
