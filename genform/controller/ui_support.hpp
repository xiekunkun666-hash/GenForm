#pragma once

#include <QJsonObject>
#include <QMap>
#include <QRegularExpression>
#include <QTranslator>
#include <QVariant>

namespace genform::controller {

QString assetPath(const QString &name);
QString translated(const QString &text);
QVariant localizedProperty(const QString &name,const QVariant &value);
QVariantList actionCatalog();

class UiTranslator : public QTranslator {
public:
    explicit UiTranslator(QObject *parent=nullptr);
    bool setLanguage(const QString &code,QString *error=nullptr);
    QString language() const { return language_; }
    bool isEmpty() const override { return false; }
    QString translate(const char *context,const char *sourceText,const char *disambiguation=nullptr,int count=-1) const override;
private:
    QString language_=QStringLiteral("zh");
    QMap<QString,QString> table_;
    QRegularExpression phrases_;
    mutable QMap<QString,QString> cache_;
};

class GuiSettings {
public:
    GuiSettings();
    QVariant value(const QString &key,const QVariant &fallback={}) const;
    bool setValue(const QString &key,const QVariant &value);
    QString fileName() const { return path_; }
    QString error() const { return error_; }
private:
    QString path_,error_;
    QJsonObject data_;
};

}
