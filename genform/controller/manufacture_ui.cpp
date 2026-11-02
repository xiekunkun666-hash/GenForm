#include "genform/controller/manufacture_ui.hpp"
#include "genform/controller/controller.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/view/viewport.hpp"
#include <QMetaMethod>
#include <QTimer>
#include <cmath>

namespace genform::controller {
namespace {
QJsonObject emptyCounts() { return {{"error",0},{"warning",0},{"info",0}}; }
}

ManufactureUi::ManufactureUi(Session *session,GuiSettings *settings,QObject *parent)
    : QObject(parent),session_(session),settings_(settings),counts_(emptyCounts()),
      userRules_(domain::clean_rules(QJsonObject::fromVariantMap(settings->value("rules").toMap()))) {
    session_->setProperty("userDesignRules",QVariant::fromValue(userRules_));
    connect(session_,&Session::changed,this,&ManufactureUi::modelChanged);
    if (auto *controller=qobject_cast<AppController *>(parent)) {
        connect(controller,&AppController::changed,this,[this] { if (inputsChanged()) invalidate(); });
    }
}

QJsonObject ManufactureUi::effectiveRules() const {
    return domain::effective_rules(userRules_,session_->document.props.value("rules").toObject());
}

QJsonObject ManufactureUi::execute(const QString &command,const QJsonObject &arguments) {
    try { return session_->execute(command,arguments); }
    catch (const std::exception &error) { return {{"ok",false},{"error",QString::fromUtf8(error.what())}}; }
}

bool ManufactureUi::inputsChanged() const {
    return checkedRevision_ && (*checkedRevision_!=session_->document.revision || checkedRules_!=effectiveRules()
        || checkedMaterial_!=session_->document.props.value("material").toString());
}

bool ManufactureUi::stale() const { return stale_ || inputsChanged(); }

QJsonArray ManufactureUi::issues() const {
    QJsonObject names;
    for (const auto &entry : session_->document.features) {
        const auto feature=entry.toObject(); const auto identifier=feature.value("id").toString();
        names[identifier]=feature.value("name").toString(identifier);
    }
    QJsonArray result;
    for (const auto &entry : issues_) {
        auto issue=entry.toObject(); QJsonArray labels;
        for (const auto &identifier : issue.value("features").toArray()) labels.append(names.value(identifier.toString()).toString(identifier.toString()));
        issue["names"]=labels; result.append(issue);
    }
    return result;
}

QStringList ManufactureUi::redFeatures() const {
    return kind_=="part" && completed_ && open_ && highlight_ && !stale() ? red_ : QStringList{};
}

QVariantList ManufactureUi::designRules() const {
    const auto values=effectiveRules();
    const auto document=domain::clean_rules(session_->document.props.value("rules").toObject());
    QVariantList result;
    for (const auto &entry : domain::rule_table()) {
        auto rule=entry.toObject(); const auto key=rule.value("key").toString();
        rule["value"]=values.value(key); rule["changed"]=userRules_.contains(key);
        rule["userValue"]=domain::effective_rules(userRules_).value(key);
        rule["document"]=document.contains(key);
        rule["source"]=document.contains(key)?"document":userRules_.contains(key)?"user":"default";
        result.append(rule.toVariantMap());
    }
    return result;
}

void ManufactureUi::setDocumentKind(const QString &kind) {
    if (kind_==kind) return;
    kind_=kind; clearCheck(); open_=false; Q_EMIT changed();
}

void ManufactureUi::invalidate() {
    if ((!completed_ && !busy_) || stale_) return;
    stale_=true; Q_EMIT changed();
}

void ManufactureUi::modelChanged() {
    if (inputsChanged()) invalidate();
    Q_EMIT changed();
}

void ManufactureUi::failCheck(const QString &message) {
    busy_=false; completed_=false; red_.clear();
    issues_={QJsonObject{{"level","error"},{"code","check_failed"},{"title",QStringLiteral("设计检查未完成")},
        {"detail",message},{"features",QJsonArray{}}}};
    counts_=domain::issue_summary(issues_);
    Q_EMIT notice(message); Q_EMIT changed();
}

void ManufactureUi::runCheck() {
    if (busy_ || binding_) return;
    ++ticket_; open_=true; busy_=true; completed_=false; stale_=false;
    issues_={}; counts_=emptyCounts(); red_.clear();
    checkedRevision_=session_->document.revision; checkedRules_=effectiveRules(); checkedMaterial_=session_->document.props.value("material").toString();
    Q_EMIT changed();
    if (kind_!="part") {
        failCheck(kind_=="assembly" ? QStringLiteral("零件设计检查不适用于装配体；请在装配面板运行干涉、紧固件及运动检查。")
                                  : QStringLiteral("工程图不支持零件设计检查。"));
        return;
    }
    const auto ticket=ticket_;
    QTimer::singleShot(0,this,[this,ticket] {
        if (ticket!=ticket_) return;
        if (session_->busy) { failCheck(QStringLiteral("模型正在重建，请完成后重新检查。")); return; }
        if (inputsChanged()) {
            stale_=true; failCheck(QStringLiteral("检查前文档、规则或材质发生变化，请重新检查。")); return;
        }
        const auto rules=execute("get_design_rules");
        if (!rules.value("ok").toBool()) { failCheck(rules.value("error").toString(QStringLiteral("读取设计规则失败。"))); return; }
        if (rules.value("rules").toObject()!=checkedRules_) {
            failCheck(QStringLiteral("检查后端尚未接入当前用户规则，不能以默认规则报告检查通过。")); return;
        }
        const auto reply=execute("check_design");
        if (ticket!=ticket_) return;
        if (!reply.value("ok").toBool()) { failCheck(reply.value("error").toString(QStringLiteral("设计检查失败。"))); return; }
        if (!reply.value("issues").isArray() || !reply.value("counts").isObject() || !reply.value("red").isArray()) {
            failCheck(QStringLiteral("设计检查返回不完整，未取得有效的检查报告。")); return;
        }
        const auto issues=reply.value("issues").toArray();
        for (const auto &entry : issues) {
            const auto issue=entry.toObject();
            if (!QStringList{"error","warning","info"}.contains(issue.value("level").toString()) || !issue.value("features").isArray()) {
                failCheck(QStringLiteral("设计检查返回了无效的问题条目。")); return;
            }
        }
        if (reply.value("counts").toObject()!=domain::issue_summary(issues)) {
            failCheck(QStringLiteral("设计检查计数与问题列表不一致。")); return;
        }
        issues_=issues; counts_=reply.value("counts").toObject();
        for (const auto &identifier : reply.value("red").toArray()) if (identifier.isString() && !red_.contains(identifier.toString())) red_.append(identifier.toString());
        busy_=false; completed_=true;
        stale_=stale_ || inputsChanged();
        Q_EMIT changed();
    });
}

void ManufactureUi::clearCheck() {
    ++ticket_; busy_=false; completed_=false; stale_=false;
    issues_={}; counts_=emptyCounts(); red_.clear(); checkedRevision_.reset(); checkedRules_={}; checkedMaterial_.clear();
    Q_EMIT changed();
}

void ManufactureUi::closeCheck() { open_=false; Q_EMIT changed(); }
void ManufactureUi::toggleCheckLog() { open_=!open_; Q_EMIT changed(); }
void ManufactureUi::toggleCheckHighlight() { highlight_=!highlight_; Q_EMIT changed(); }

void ManufactureUi::bindProcesses() {
    if (binding_ || busy_) return;
    if (kind_!="part") { Q_EMIT notice(QStringLiteral("请打开零件文档后绑定工艺。")); return; }
    if (!session_->model.value("has_body").toBool()) { Q_EMIT notice(QStringLiteral("还没有实体，无法绑定工艺。")); return; }
    binding_=true; Q_EMIT changed();
    const auto revision=session_->document.revision;
    QTimer::singleShot(0,this,[this,revision] {
        if (kind_!="part" || session_->document.revision!=revision || session_->busy) {
            binding_=false; Q_EMIT notice(QStringLiteral("绑定前模型发生变化，请重新绑定工艺。")); Q_EMIT changed(); return;
        }
        const auto reply=execute("bind_processes",{{"batch",effectiveRules().value("batch")}});
        binding_=false;
        if (!reply.value("ok").toBool()) Q_EMIT notice(reply.value("error").toString(QStringLiteral("绑定工艺失败。")));
        else if (!reply.value("bound").isDouble() || !reply.value("processes").isObject()) Q_EMIT notice(QStringLiteral("工艺绑定未返回有效结果。"));
        else {
            QStringList summary; const auto processes=reply.value("processes").toObject();
            for (auto entry=processes.begin();entry!=processes.end();++entry) summary.append(QStringLiteral("%1 %2").arg(entry.key()).arg(entry.value().toInt()));
            Q_EMIT notice(QStringLiteral("按 %1 件批量绑定了 %2 个特征的工艺：%3").arg(reply.value("batch").toInt()).arg(reply.value("bound").toInt()).arg(summary.join(QStringLiteral("、"))));
        }
        Q_EMIT changed();
    });
}

bool ManufactureUi::saveRules(const QJsonObject &rules) {
    if (!settings_->setValue("rules",rules.toVariantMap())) { Q_EMIT notice(QStringLiteral("设计规则未保存：%1").arg(settings_->error())); Q_EMIT changed(); return false; }
    const auto previous=effectiveRules(); userRules_=rules;
    session_->setProperty("userDesignRules",QVariant::fromValue(userRules_));
    if (previous!=effectiveRules()) invalidate();
    Q_EMIT changed(); return true;
}

void ManufactureUi::setRule(const QString &key,const QString &text) {
    bool valid=false; const double number=text.toDouble(&valid);
    QJsonObject specification;
    for (const auto &entry : domain::rule_table()) if (entry.toObject().value("key").toString()==key) { specification=entry.toObject(); break; }
    if (!valid || !std::isfinite(number) || specification.isEmpty() || number<specification.value("min").toDouble() || number>specification.value("max").toDouble()) {
        Q_EMIT notice(QStringLiteral("设计规则需要填写范围内的有效数字。")); Q_EMIT changed(); return;
    }
    const auto cleaned=domain::clean_rules({{key,number}});
    auto rules=userRules_;
    if (cleaned.value(key)==specification.value("default")) rules.remove(key); else rules[key]=cleaned.value(key);
    if (rules!=userRules_) saveRules(rules);
}

void ManufactureUi::resetRules() { if (!userRules_.isEmpty()) saveRules({}); }

ManufactureUi *AppController::manufactureUi() const {
    auto *controller=const_cast<AppController *>(this);
    if (!manufacture_) {
        manufacture_=new ManufactureUi(session_,&controller->preferences_,controller);
        manufacture_->setDocumentKind(kind_);
        connect(manufacture_,&ManufactureUi::notice,controller,&AppController::notice);
        connect(manufacture_,&ManufactureUi::changed,controller,&AppController::changed);
        connect(controller,&AppController::changed,controller,&AppController::updateCheckHighlights);
        connect(controller,&AppController::kindChanged,manufacture_,[controller] { controller->manufacture_->setDocumentKind(controller->kind_); });
    }
    return manufacture_;
}

void AppController::updateCheckHighlights() {
    if (!viewport_ || !manufacture_) return;
    const auto method=viewport_->metaObject()->indexOfMethod("setCheckHighlights(QStringList)");
    if (method>=0) viewport_->metaObject()->method(method).invoke(viewport_,Qt::DirectConnection,Q_ARG(QStringList,manufacture_->redFeatures()));
    else if (!manufacture_->redFeatures().isEmpty() && !property("checkHighlightUnavailable").toBool()) {
        setProperty("checkHighlightUnavailable",true);
        Q_EMIT notice(QStringLiteral("检查报告已生成，但当前三维视图未提供错误标红接口。"));
    }
}

}
