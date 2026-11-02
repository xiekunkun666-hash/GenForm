#include "genform/platform/window_frame.hpp"

#include <QCoreApplication>
#include <QEvent>
#include <QGuiApplication>
#include <QPlatformSurfaceEvent>
#include <QTimer>
#include <algorithm>
#include <cmath>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <windowsx.h>
#include <dwmapi.h>
#endif

namespace genform::platform {
namespace {
#ifdef Q_OS_WIN
constexpr DWORD cornerPreferenceAttribute=33;
constexpr DWORD borderColorAttribute=34;
constexpr int roundedCorners=2;
constexpr int squareCorners=1;
constexpr COLORREF noBorderColor=0xfffffffe;

UINT windowDpi(HWND handle,qreal ratio) {
    using GetDpiForWindowFunction=UINT (WINAPI *)(HWND);
    static const auto getDpi=reinterpret_cast<GetDpiForWindowFunction>(GetProcAddress(GetModuleHandleW(L"user32.dll"),"GetDpiForWindow"));
    const UINT dpi=getDpi?getDpi(handle):0;
    return dpi?dpi:static_cast<UINT>(std::lround(96.0*ratio));
}

int systemMetric(int index,UINT dpi) {
    using GetSystemMetricsForDpiFunction=int (WINAPI *)(int,UINT);
    using GetDpiForSystemFunction=UINT (WINAPI *)();
    static const auto getMetric=reinterpret_cast<GetSystemMetricsForDpiFunction>(GetProcAddress(GetModuleHandleW(L"user32.dll"),"GetSystemMetricsForDpi"));
    static const auto getSystemDpi=reinterpret_cast<GetDpiForSystemFunction>(GetProcAddress(GetModuleHandleW(L"user32.dll"),"GetDpiForSystem"));
    if (getMetric) return getMetric(index,dpi);
    return MulDiv(GetSystemMetrics(index),static_cast<int>(dpi),static_cast<int>(getSystemDpi?getSystemDpi():96));
}

bool fullscreen(QWindow *window,HWND handle) {
    return window->windowState()==Qt::WindowFullScreen && !IsZoomed(handle);
}

bool monitorInfo(HWND handle,MONITORINFO &info) {
    info.cbSize=sizeof(info);
    return GetMonitorInfoW(MonitorFromWindow(handle,MONITOR_DEFAULTTONEAREST),&info)!=FALSE;
}

LONG nativeSize(int size,qreal ratio) {
    return std::max<LONG>(1,static_cast<LONG>(std::ceil(size*ratio)));
}
#endif
}

WindowFrame::WindowFrame(QWindow *window) : QObject(window),window_(window) {
#ifdef Q_OS_WIN
    if (!window_ || QGuiApplication::platformName()!=QStringLiteral("windows")) return;
    QCoreApplication::instance()->installNativeEventFilter(this);
    registered_=true;
    window_->installEventFilter(this);
    connect(window_,&QWindow::screenChanged,this,[this] { scheduleApply(); });
    window_->create();
    apply();
#endif
}

WindowFrame::~WindowFrame() {
    if (registered_ && QCoreApplication::instance()) QCoreApplication::instance()->removeNativeEventFilter(this);
}

void WindowFrame::scheduleApply() {
    if (applyQueued_) return;
    applyQueued_=true;
    QTimer::singleShot(0,this,[this] { applyQueued_=false; apply(); });
}

void WindowFrame::apply() {
#ifdef Q_OS_WIN
    if (!registered_ || !window_ || !window_->handle() || applying_) return;
    applying_=true;
    const auto handle=reinterpret_cast<HWND>(window_->winId());
    if (!handle) { applying_=false; return; }
    if (handle_!=reinterpret_cast<quintptr>(handle)) frameInitialized_=false;
    handle_=reinterpret_cast<quintptr>(handle);
    const bool isFullscreen=fullscreen(window_,handle);
    if (!isFullscreen) {
        const auto style=GetWindowLongPtrW(handle,GWL_STYLE);
        const auto desired=style|WS_CAPTION|WS_THICKFRAME|WS_SYSMENU|WS_MINIMIZEBOX|WS_MAXIMIZEBOX;
        if (style!=desired) SetWindowLongPtrW(handle,GWL_STYLE,desired);
        if (!frameInitialized_ || style!=desired) {
            frameInitialized_=true;
            SetWindowPos(handle,nullptr,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_NOZORDER|SWP_NOACTIVATE|SWP_FRAMECHANGED);
        }
    }
    const BOOL transitionsDisabled=FALSE;
    DwmSetWindowAttribute(handle,DWMWA_TRANSITIONS_FORCEDISABLED,&transitionsDisabled,sizeof(transitionsDisabled));
    BOOL composition=FALSE;
    if (SUCCEEDED(DwmIsCompositionEnabled(&composition)) && composition) {
        const int corners=isFullscreen?squareCorners:roundedCorners;
        DwmSetWindowAttribute(handle,cornerPreferenceAttribute,&corners,sizeof(corners));
        DwmSetWindowAttribute(handle,borderColorAttribute,&noBorderColor,sizeof(noBorderColor));
        const MARGINS margins=isFullscreen?MARGINS{0,0,0,0}:MARGINS{1,1,1,1};
        DwmExtendFrameIntoClientArea(handle,&margins);
    }
    applying_=false;
#endif
}

bool WindowFrame::eventFilter(QObject *watched,QEvent *event) {
#ifdef Q_OS_WIN
    if (watched==window_) {
        switch (event->type()) {
        case QEvent::PlatformSurface:
            if (static_cast<QPlatformSurfaceEvent *>(event)->surfaceEventType()==QPlatformSurfaceEvent::SurfaceAboutToBeDestroyed) {
                handle_=0;
                frameInitialized_=false;
            } else scheduleApply();
            break;
        case QEvent::Show:
        case QEvent::WindowStateChange:
        case QEvent::ScreenChangeInternal:
#if QT_VERSION >= QT_VERSION_CHECK(6,9,0)
        case QEvent::DevicePixelRatioChange:
#endif
            scheduleApply();
            break;
        default:
            break;
        }
    }
#endif
    return QObject::eventFilter(watched,event);
}

bool WindowFrame::nativeEventFilter(const QByteArray &eventType,void *message,qintptr *result) {
#ifdef Q_OS_WIN
    if (eventType!="windows_generic_MSG" || !message || !result || !window_ || !handle_) return false;
    const auto *native=static_cast<const MSG *>(message);
    const auto handle=reinterpret_cast<HWND>(handle_);
    if (native->hwnd!=handle) return false;
    const bool isFullscreen=fullscreen(window_,handle);
    switch (native->message) {
    case WM_NCCALCSIZE: {
        if (!native->lParam) return false;
        auto *rect=native->wParam?&reinterpret_cast<NCCALCSIZE_PARAMS *>(native->lParam)->rgrc[0]:reinterpret_cast<RECT *>(native->lParam);
        MONITORINFO info{};
        if (!isFullscreen && IsZoomed(handle) && monitorInfo(handle,info)) {
            rect->left=std::max(rect->left,info.rcWork.left);
            rect->top=std::max(rect->top,info.rcWork.top);
            rect->right=std::min(rect->right,info.rcWork.right);
            rect->bottom=std::min(rect->bottom,info.rcWork.bottom);
        }
        *result=0;
        return true;
    }
    case WM_NCHITTEST: {
        RECT rect{};
        if (!GetWindowRect(handle,&rect)) return false;
        const POINT point{GET_X_LPARAM(native->lParam),GET_Y_LPARAM(native->lParam)};
        if (!PtInRect(&rect,point)) return false;
        *result=HTCLIENT;
        if (isFullscreen || IsZoomed(handle)) return true;
        const UINT dpi=windowDpi(handle,window_->devicePixelRatio());
        const int horizontal=systemMetric(SM_CXSIZEFRAME,dpi)+systemMetric(SM_CXPADDEDBORDER,dpi);
        const int vertical=systemMetric(SM_CYSIZEFRAME,dpi)+systemMetric(SM_CXPADDEDBORDER,dpi);
        const int corner=std::max({horizontal,vertical,MulDiv(10,static_cast<int>(dpi),96)});
        const bool resizeWidth=window_->minimumWidth()<window_->maximumWidth();
        const bool resizeHeight=window_->minimumHeight()<window_->maximumHeight();
        const bool left=resizeWidth && point.x<rect.left+horizontal;
        const bool right=resizeWidth && point.x>=rect.right-horizontal;
        const bool top=resizeHeight && point.y<rect.top+vertical;
        const bool bottom=resizeHeight && point.y>=rect.bottom-vertical;
        const bool cornerLeft=resizeWidth && point.x<rect.left+corner;
        const bool cornerRight=resizeWidth && point.x>=rect.right-corner;
        const bool cornerTop=resizeHeight && point.y<rect.top+corner;
        const bool cornerBottom=resizeHeight && point.y>=rect.bottom-corner;
        if ((top && cornerLeft) || (left && cornerTop)) *result=HTTOPLEFT;
        else if ((top && cornerRight) || (right && cornerTop)) *result=HTTOPRIGHT;
        else if ((bottom && cornerLeft) || (left && cornerBottom)) *result=HTBOTTOMLEFT;
        else if ((bottom && cornerRight) || (right && cornerBottom)) *result=HTBOTTOMRIGHT;
        else if (left) *result=HTLEFT;
        else if (right) *result=HTRIGHT;
        else if (top) *result=HTTOP;
        else if (bottom) *result=HTBOTTOM;
        return true;
    }
    case WM_GETMINMAXINFO: {
        if (isFullscreen || !native->lParam) return false;
        auto *limits=reinterpret_cast<MINMAXINFO *>(native->lParam);
        MONITORINFO info{};
        if (!monitorInfo(handle,info)) return false;
        const UINT dpi=windowDpi(handle,window_->devicePixelRatio());
        const LONG horizontal=systemMetric(SM_CXSIZEFRAME,dpi)+systemMetric(SM_CXPADDEDBORDER,dpi);
        const LONG vertical=systemMetric(SM_CYSIZEFRAME,dpi)+systemMetric(SM_CXPADDEDBORDER,dpi);
        limits->ptMaxPosition={info.rcWork.left-info.rcMonitor.left-horizontal,info.rcWork.top-info.rcMonitor.top-vertical};
        limits->ptMaxSize={info.rcWork.right-info.rcWork.left+2*horizontal,info.rcWork.bottom-info.rcWork.top+2*vertical};
        const qreal ratio=window_->devicePixelRatio();
        limits->ptMinTrackSize={nativeSize(window_->minimumWidth(),ratio),nativeSize(window_->minimumHeight(),ratio)};
        if (window_->maximumWidth()<16777215) limits->ptMaxTrackSize.x=nativeSize(window_->maximumWidth(),ratio);
        if (window_->maximumHeight()<16777215) limits->ptMaxTrackSize.y=nativeSize(window_->maximumHeight(),ratio);
        limits->ptMaxTrackSize.x=std::max(limits->ptMaxTrackSize.x,limits->ptMinTrackSize.x);
        limits->ptMaxTrackSize.y=std::max(limits->ptMaxTrackSize.y,limits->ptMinTrackSize.y);
        *result=0;
        return true;
    }
    case WM_DPICHANGED:
    case WM_DWMCOMPOSITIONCHANGED:
    case WM_THEMECHANGED:
    case WM_SETTINGCHANGE:
    case WM_ACTIVATE:
        scheduleApply();
        break;
    case WM_STYLECHANGED:
        if (native->wParam==static_cast<WPARAM>(GWL_STYLE) && !applying_ && !isFullscreen) {
            const auto style=GetWindowLongPtrW(handle,GWL_STYLE);
            const LONG_PTR required=WS_CAPTION|WS_THICKFRAME|WS_SYSMENU|WS_MINIMIZEBOX|WS_MAXIMIZEBOX;
            if ((style&required)!=required) scheduleApply();
        }
        break;
    case WM_NCDESTROY:
        handle_=0;
        frameInitialized_=false;
        break;
    default:
        break;
    }
#else
    Q_UNUSED(eventType);
    Q_UNUSED(message);
    Q_UNUSED(result);
#endif
    return false;
}

WindowFrame *enableNativeWindowFrame(QWindow *window) {
    if (!window) return nullptr;
    for (auto *child : window->children()) if (auto *frame=dynamic_cast<WindowFrame *>(child)) return frame;
    return new WindowFrame(window);
}

bool toggleNativeMaximize(QWindow *window) {
#ifdef Q_OS_WIN
    if (!window || QGuiApplication::platformName()!=QStringLiteral("windows")) return false;
    const auto handle=reinterpret_cast<HWND>(window->winId());
    if (!handle) return false;
    if (window->windowState()==Qt::WindowFullScreen && !IsZoomed(handle)) { window->showNormal(); return true; }
    return PostMessageW(handle,WM_SYSCOMMAND,IsZoomed(handle)?SC_RESTORE:SC_MAXIMIZE,0)!=FALSE;
#else
    Q_UNUSED(window);
    return false;
#endif
}

bool minimizeNativeWindow(QWindow *window) {
#ifdef Q_OS_WIN
    if (!window || QGuiApplication::platformName()!=QStringLiteral("windows")) return false;
    enableNativeWindowFrame(window);
    const auto handle=reinterpret_cast<HWND>(window->winId());
    return handle && PostMessageW(handle,WM_SYSCOMMAND,SC_MINIMIZE,0)!=FALSE;
#else
    Q_UNUSED(window);
    return false;
#endif
}

bool restoreNativeWindow(QWindow *window) {
#ifdef Q_OS_WIN
    if (!window || QGuiApplication::platformName()!=QStringLiteral("windows")) return false;
    if (window->windowState()==Qt::WindowFullScreen) { window->showNormal(); return true; }
    enableNativeWindowFrame(window);
    const auto handle=reinterpret_cast<HWND>(window->winId());
    return handle && PostMessageW(handle,WM_SYSCOMMAND,SC_RESTORE,0)!=FALSE;
#else
    Q_UNUSED(window);
    return false;
#endif
}

}
