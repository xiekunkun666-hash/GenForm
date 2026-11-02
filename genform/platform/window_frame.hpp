#pragma once

#include <QAbstractNativeEventFilter>
#include <QObject>
#include <QPointer>
#include <QWindow>

namespace genform::platform {

class WindowFrame final : public QObject, public QAbstractNativeEventFilter {
public:
    explicit WindowFrame(QWindow *window);
    ~WindowFrame() override;
    bool nativeEventFilter(const QByteArray &eventType,void *message,qintptr *result) override;

protected:
    bool eventFilter(QObject *watched,QEvent *event) override;

private:
    void apply();
    void scheduleApply();
    QPointer<QWindow> window_;
    quintptr handle_=0;
    bool registered_=false;
    bool frameInitialized_=false;
    bool applying_=false;
    bool applyQueued_=false;
};

WindowFrame *enableNativeWindowFrame(QWindow *window);
bool toggleNativeMaximize(QWindow *window);
bool minimizeNativeWindow(QWindow *window);
bool restoreNativeWindow(QWindow *window);

}
