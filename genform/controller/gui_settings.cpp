#include "genform/controller/controller.hpp"
#include "genform/view/viewport.hpp"
#include "genform/view/sheet.hpp"
#include <QMetaMethod>
#include <QMetaProperty>

namespace genform::controller {
void AppController::savePreference(const QString &key,const QVariant &value) { if (!preferences_.setValue(key,value)) Q_EMIT notice(QStringLiteral("设置未保存：%1").arg(preferences_.error())); }
void AppController::setLanguage(const QString &code) {
    if (code==translator_.language()) return;
    QString error;
    if (!translator_.setLanguage(code,&error)) { Q_EMIT notice(error); return; }
    savePreference("language",code);
    Q_EMIT languageChanged(); Q_EMIT changed(); Q_EMIT formChanged(); Q_EMIT sketchChanged(); Q_EMIT viewChanged(); Q_EMIT settingsChanged(); Q_EMIT measureChanged(); Q_EMIT hoverTextChanged();
    if (window_) for (auto *object : window_->findChildren<QObject *>()) if (object->metaObject()->indexOfProperty("allRows")>=0 && object->metaObject()->indexOfProperty("capturing")>=0) { object->setProperty("allRows",actionTable()); object->setProperty("group",QString()); }
    Q_EMIT simulation_->changed(); Q_EMIT drawing_->changed();
}
void AppController::attachTheme(QObject *theme) {
    if (!theme || theme->metaObject()->indexOfProperty("darkMode")<0) { Q_EMIT notice(QStringLiteral("原 QML Theme 未连接，主题持久化不可用。")); return; }
    if (theme_) disconnect(theme_,nullptr,this,nullptr);
    theme_=theme; theme_->setProperty("darkMode",dark_);
    const auto property=theme_->metaObject()->property(theme_->metaObject()->indexOfProperty("darkMode"));
    const auto slot=metaObject()->method(metaObject()->indexOfSlot("themeChanged()"));
    if (property.hasNotifySignal()) connect(theme_,property.notifySignal(),this,slot);
}
void AppController::themeChanged() { if (!theme_) return; const bool dark=theme_->property("darkMode").toBool(); if (dark==dark_) return; dark_=dark; savePreference("dark",dark_); Q_EMIT settingsChanged(); Q_EMIT changed(); }
void AppController::setSetting(const QString &key,const QVariant &value) {
    if (key=="language") { setLanguage(value.toString()); return; }
    if (key=="dark") { dark_=value.toBool(); if (theme_) theme_->setProperty("darkMode",dark_); else if (viewport_) viewport_->setDark(dark_); savePreference("dark",dark_); }
    else if (key=="rapid") { rapid_=value.toBool(); savePreference("rapid",rapid_); }
    else if (key=="snaps") {
        QSet<QString> enabled; const auto values=value.toStringList();
        for (const auto &snap : values) { if (!QStringList{"end","mid","center","quad","int","near","hv","grid"}.contains(snap)) { Q_EMIT notice(QStringLiteral("未知捕捉类型：%1").arg(snap)); return; } enabled.insert(snap); }
        snaps_=enabled; gridSnap_=snaps_.contains("grid"); quickSnap_.clear(); if (viewport_) viewport_->setSnaps(snaps_); savePreference("snaps",QStringList(snaps_.values()));
    } else { unsupported("setting:"+key); return; }
    Q_EMIT settingsChanged(); Q_EMIT sketchChanged(); Q_EMIT viewChanged(); Q_EMIT changed();
}
}
