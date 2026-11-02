#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QObject>
#include <QStringList>
#include <QVariant>
#include <optional>

namespace genform { class Session; }
namespace genform::controller {

class GuiSettings;

class ManufactureUi : public QObject {
    Q_OBJECT
public:
    ManufactureUi(Session *session, GuiSettings *settings, QObject *parent = nullptr);
    bool isOpen() const { return open_; }
    bool busy() const { return busy_; }
    bool completed() const { return completed_; }
    bool stale() const;
    bool highlight() const { return highlight_; }
    bool binding() const { return binding_; }
    QJsonArray issues() const;
    QJsonObject counts() const { return counts_; }
    QStringList redFeatures() const;
    QVariantList designRules() const;
    std::optional<quint64> checkedRevision() const { return checkedRevision_; }
    void setDocumentKind(const QString &kind);
    void runCheck();
    void clearCheck();
    void closeCheck();
    void toggleCheckLog();
    void toggleCheckHighlight();
    void bindProcesses();
    void setRule(const QString &key, const QString &text);
    void resetRules();
Q_SIGNALS:
    void changed();
    void notice(const QString &message);
private:
    Session *session_;
    GuiSettings *settings_;
    QString kind_ = QStringLiteral("part");
    QJsonArray issues_;
    QJsonObject counts_, userRules_, checkedRules_;
    QStringList red_;
    QString checkedMaterial_;
    std::optional<quint64> checkedRevision_;
    bool open_ = false, busy_ = false, completed_ = false, stale_ = false;
    bool highlight_ = true, binding_ = false;
    quint64 ticket_ = 0;
    QJsonObject effectiveRules() const;
    bool inputsChanged() const;
    QJsonObject execute(const QString &command, const QJsonObject &arguments = {});
    void modelChanged();
    void invalidate();
    void failCheck(const QString &message);
    bool saveRules(const QJsonObject &rules);
};

}
