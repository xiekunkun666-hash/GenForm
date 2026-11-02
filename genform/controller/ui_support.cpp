#include "genform/controller/ui_support.hpp"
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSaveFile>
#include <QSet>
#include <QSettings>
#include <algorithm>

namespace genform::controller {
namespace {
const QRegularExpression chinese(QStringLiteral("[\\x{4e00}-\\x{9fff}]"));
int chineseCount(const QString &text) { int count=0; auto matches=chinese.globalMatch(text); while (matches.hasNext()) { matches.next(); ++count; } return count; }
QVariant localize(const QVariant &value) {
    if (value.metaType().id()==QMetaType::QString) return translated(value.toString());
    if (value.metaType().id()==QMetaType::QStringList) { QStringList result; for (const auto &entry : value.toStringList()) result.append(translated(entry)); return result; }
    if (value.metaType().id()==QMetaType::QVariantList) { QVariantList result; for (const auto &entry : value.toList()) result.append(localize(entry)); return result; }
    if (value.metaType().id()==QMetaType::QVariantMap) {
        auto result=value.toMap();
        const QSet<QString> protectedKeys{"id","icon","key","default","kind","type","mark","tint","state","accept_key","name","path","folder","feature","features","names","tool","command","editing","plane","color","short","part","to","series","size","material","params","formula","fieldsValue"};
        const bool field=result.contains("key") && result.value("type")!="info";
        for (auto entry=result.begin();entry!=result.end();++entry) if (!protectedKeys.contains(entry.key()) && !(field && entry.key()=="value")) entry.value()=localize(entry.value());
        return result;
    }
    return value;
}
}

QString assetPath(const QString &name) {
    const QString application=QCoreApplication::applicationDirPath();
    const QStringList roots{qEnvironmentVariable("GENFORM_ASSETS_DIR"),QStringLiteral(":/genform/assets"),QStringLiteral(":/assets"),application+"/assets",application+"/../share/genform/assets",QString::fromUtf8(GENFORM_SOURCE_DIR)+"/genform/assets"};
    for (const auto &root : roots) { const auto path=root+"/"+name; if (!root.isEmpty() && QFileInfo::exists(path)) return path; }
    return {};
}
QString translated(const QString &text) { const auto bytes=text.toUtf8(); return QCoreApplication::translate("GenForm",bytes.constData()); }
QVariant localizedProperty(const QString &name,const QVariant &value) {
    const QSet<QString> localized{"form","previewNote","bodyText","selectionText","hoverText","progress","sketchTitle","sketchProps","hint","quickSnaps","snapToggles","featureMenus","orientations","displayStyles","sceneNames","showItems","sceneContext","actionTable","actionGroups","aiGuide","measure","checkIssues","gestureWheels","state","components","joints","mates","live","paramError","static","drag"};
    return localized.contains(name)?localize(value):value;
}
UiTranslator::UiTranslator(QObject *parent):QTranslator(parent) {}
bool UiTranslator::setLanguage(const QString &code,QString *error) {
    if (code!="zh" && code!="en") { if (error) *error=QStringLiteral("不支持的界面语言：%1").arg(code); return false; }
    if (code=="en" && table_.isEmpty()) {
        const auto path=assetPath("lang_en.json"); QFile source(path);
        if (path.isEmpty() || !source.open(QIODevice::ReadOnly)) { if (error) *error=QStringLiteral("找不到或无法读取英文翻译资源 assets/lang_en.json。 ")+source.errorString(); return false; }
        QJsonParseError parse; const auto document=QJsonDocument::fromJson(source.readAll(),&parse);
        if (parse.error!=QJsonParseError::NoError || !document.isObject() || document.object().isEmpty()) { if (error) *error=QStringLiteral("英文翻译资源无效：%1").arg(parse.errorString()); return false; }
        QStringList phrases; QMap<QString,QString> translations;
        const auto entries=document.object();
        for (auto entry=entries.begin();entry!=entries.end();++entry) {
            if (!entry.value().isString()) { if (error) *error=QStringLiteral("英文翻译资源包含非字符串项。 "); return false; }
            translations[entry.key()]=entry.value().toString();
            if (entry.key().size()>=2 && chinese.match(entry.key()).hasMatch()) phrases.append(entry.key());
        }
        std::sort(phrases.begin(),phrases.end(),[](const QString &first,const QString &second) { return first.size()==second.size()?first<second:first.size()>second.size(); });
        for (auto &phrase : phrases) phrase=QRegularExpression::escape(phrase);
        phrases_=QRegularExpression(phrases.join('|')); table_=translations;
    }
    language_=code; cache_.clear(); return true;
}
QString UiTranslator::translate(const char *context,const char *sourceText,const char *disambiguation,int count) const {
    Q_UNUSED(context); Q_UNUSED(disambiguation); Q_UNUSED(count);
    if (!sourceText) return {};
    const QString source=QString::fromUtf8(sourceText);
    if (language_!="en" || !chinese.match(source).hasMatch()) return source;
    if (cache_.contains(source)) return cache_.value(source);
    QString result=table_.value(source);
    if (!table_.contains(source)) {
        qsizetype previous=0; auto matches=phrases_.globalMatch(source);
        while (matches.hasNext()) { const auto match=matches.next(); result+=source.mid(previous,match.capturedStart()-previous)+table_.value(match.captured()); previous=match.capturedEnd(); }
        result+=source.mid(previous);
        if (chineseCount(result)*3>chineseCount(source)) result=source;
        result.replace(QStringLiteral("（")," (").replace(QStringLiteral("）"),") ").replace(QStringLiteral("："),": ").replace(QStringLiteral("，"),", ").replace(QStringLiteral("。"),". ").replace(QStringLiteral("；"),"; ").replace(QStringLiteral("、"),", ").replace(QStringLiteral("“"),"\"").replace(QStringLiteral("”"),"\"").replace(QStringLiteral("　"),"  ");
        result=result.trimmed();
    }
    if (cache_.size()<20000) cache_[source]=result;
    return result;
}

GuiSettings::GuiSettings() {
    path_=qEnvironmentVariable("GENFORM_SETTINGS");
    if (path_.isEmpty()) { const QString base=qEnvironmentVariable("APPDATA",QDir::homePath()); path_=QDir(base).filePath("GenForm/settings.json"); }
    QFile source(path_);
    if (source.exists()) {
        if (!source.open(QIODevice::ReadOnly)) { error_=source.errorString(); return; }
        QJsonParseError parse; const auto document=QJsonDocument::fromJson(source.readAll(),&parse);
        if (parse.error!=QJsonParseError::NoError || !document.isObject()) { error_=QStringLiteral("设置文件无效，已使用默认设置：%1").arg(path_); return; }
        data_=document.object(); return;
    }
    if (qEnvironmentVariableIsEmpty("GENFORM_SETTINGS")) {
        QSettings previous("GenForm","GenFormNative");
        for (const auto &key : {QString("shortcuts"),QString("recent"),QString("language"),QString("dark"),QString("snaps"),QString("rapid")}) if (previous.contains(key)) data_[key]=QJsonValue::fromVariant(previous.value(key));
    }
}
QVariant GuiSettings::value(const QString &key,const QVariant &fallback) const { return data_.contains(key)?data_.value(key).toVariant():fallback; }
bool GuiSettings::setValue(const QString &key,const QVariant &value) {
    auto changed=data_; changed[key]=QJsonValue::fromVariant(value);
    if (!QDir().mkpath(QFileInfo(path_).absolutePath())) { error_=QStringLiteral("无法创建设置目录：%1").arg(path_); return false; }
    QSaveFile target(path_); if (!target.open(QIODevice::WriteOnly)) { error_=target.errorString(); return false; }
    const auto bytes=QJsonDocument(changed).toJson(QJsonDocument::Indented);
    if (target.write(bytes)!=bytes.size() || !target.commit()) { error_=target.errorString(); return false; }
    data_=changed; error_.clear(); return true;
}

}
