#include "genform/document.hpp"
#include "genform/features.hpp"
#include <QFile>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QSaveFile>
#include <QSet>
#include <algorithm>

namespace genform {

QJsonObject Document::find(const QString &identifier) const {
    return features.at(index(identifier)).toObject();
}

int Document::index(const QString &identifier) const {
    for (int position = 0; position < features.size(); ++position)
        if (features[position].toObject().value("id").toString() == identifier) return position;
    throw Error(QStringLiteral("找不到特征 '%1'").arg(identifier));
}

QString Document::last(const QString &kind) const {
    for (int position = features.size() - 1; position >= 0; --position) {
        const auto feature = features[position].toObject();
        if (feature.value("type").toString() == kind) return feature.value("id").toString();
    }
    return {};
}

void Document::checkpoint() {
    undo_.append({features, upto});
    if (undo_.size() > 200) undo_.removeFirst();
    redo_.clear();
}

void Document::changed() { dirty = true; ++revision; }

QString Document::add(const QString &kind, const QJsonObject &params, const QString &name) {
    if (!features::specs().contains(kind) && !QStringList{"sketch", "extrude", "fillet", "chamfer"}.contains(kind))
        throw Error(QStringLiteral("不认识的特征类型 '%1'").arg(kind));
    const QString title = features::title(kind);
    if (title.isEmpty()) throw Error(QStringLiteral("不认识的特征类型 '%1'").arg(kind));
    int count = 1;
    for (const auto &value : features) if (value.toObject().value("type") == kind) ++count;
    checkpoint();
    const QString identifier = QStringLiteral("f%1").arg(++serial_);
    const QJsonObject feature{{"id", identifier}, {"type", kind},
        {"name", name.isEmpty() ? title + QString::number(count) : name},
        {"params", params}, {"suppressed", false}};
    if (upto) { features.insert(*upto, feature); ++*upto; }
    else features.append(feature);
    changed();
    return identifier;
}

void Document::edit(const QString &identifier, const QJsonObject &params) {
    const int position = index(identifier);
    auto feature = features[position].toObject();
    auto merged = feature.value("params").toObject();
    for (auto iterator = params.begin(); iterator != params.end(); ++iterator) merged[iterator.key()] = iterator.value();
    checkpoint();
    feature["params"] = merged;
    features[position] = feature;
    changed();
}

void Document::rename(const QString &identifier, const QString &name) {
    const int position = index(identifier);
    if (name.trimmed().isEmpty()) throw Error(QStringLiteral("名称不能为空"));
    auto feature = features[position].toObject();
    checkpoint();
    feature["name"] = name.trimmed();
    features[position] = feature;
    changed();
}

void Document::setFolder(const QStringList &identifiers, const QString &folder) {
    QString normalized = folder;
    normalized.replace('\\', '/');
    QStringList parts;
    for (const auto &part : normalized.split('/')) if (!part.trimmed().isEmpty()) parts.append(part.trimmed());
    QVector<int> positions;
    for (const auto &identifier : identifiers) positions.append(index(identifier));
    checkpoint();
    for (const int position : positions) {
        auto feature = features[position].toObject();
        if (parts.isEmpty()) feature.remove("folder");
        else feature["folder"] = parts.join('/');
        features[position] = feature;
    }
    changed();
}

void Document::setProcesses(const QJsonObject &bound) {
    QVector<int> positions;
    for (auto iterator = bound.begin(); iterator != bound.end(); ++iterator) positions.append(index(iterator.key()));
    checkpoint();
    int cursor = 0;
    for (auto iterator = bound.begin(); iterator != bound.end(); ++iterator) {
        auto feature = features[positions[cursor]].toObject();
        if (iterator.value().isObject() && !iterator.value().toObject().isEmpty()) feature["process"] = iterator.value();
        else feature.remove("process");
        features[positions[cursor++]] = feature;
    }
    changed();
}

void Document::suppress(const QString &identifier, bool suppressed) {
    const int position = index(identifier);
    auto feature = features[position].toObject();
    checkpoint();
    feature["suppressed"] = suppressed;
    features[position] = feature;
    changed();
}

void Document::remove(const QString &identifier) {
    const int position = index(identifier);
    checkpoint();
    features.removeAt(position);
    if (upto && position < *upto) --*upto;
    changed();
}

void Document::rollback(std::optional<int> count) {
    if (count && *count < 0) throw Error(QStringLiteral("回滚位置不能为负"));
    if (count && *count >= features.size()) count.reset();
    checkpoint();
    upto = count;
    changed();
}

void Document::setProp(const QString &key, const QJsonValue &value) {
    if (value.isNull() || value.isUndefined() || (value.isString() && value.toString().isEmpty())) props.remove(key);
    else props[key] = value;
    dirty = true;
}

bool Document::canUndo() const { return !undo_.isEmpty(); }
bool Document::canRedo() const { return !redo_.isEmpty(); }

void Document::undo() {
    if (!canUndo()) throw Error(QStringLiteral("没有可撤销的操作"));
    redo_.append({features, upto});
    const auto snapshot = undo_.takeLast();
    features = snapshot.features;
    upto = snapshot.upto;
    changed();
}

void Document::redo() {
    if (!canRedo()) throw Error(QStringLiteral("没有可重做的操作"));
    undo_.append({features, upto});
    const auto snapshot = redo_.takeLast();
    features = snapshot.features;
    upto = snapshot.upto;
    changed();
}

QJsonObject Document::toData() const {
    return {{"format", "genform-document"}, {"version", 1}, {"serial", serial_},
        {"upto", upto ? QJsonValue(*upto) : QJsonValue(QJsonValue::Null)}, {"props", props}, {"features", features}};
}

void Document::loadData(const QJsonObject &data) {
    if (data.value("format").toString() != "genform-document") throw Error(QStringLiteral("不是 GenForm 文档"));
    if (data.value("version").toInt() > 1) throw Error(QStringLiteral("这份文档来自更新版本的 GenForm"));
    if (!data.value("features").isArray()) throw Error(QStringLiteral("文档内容损坏：没有特征列表"));
    QJsonArray loaded;
    QSet<QString> identifiers;
    int serial = std::max(0, data.value("serial").toInt());
    for (const auto &value : data.value("features").toArray()) {
        if (!value.isObject()) throw Error(QStringLiteral("文档内容损坏：特征必须是对象"));
        const auto source = value.toObject();
        const auto identifier = source.value("id").toString();
        if (identifier.isEmpty() || !source.value("type").isString() || !source.value("params").isObject())
            throw Error(QStringLiteral("文档内容损坏：特征缺少字段"));
        if (identifiers.contains(identifier)) throw Error(QStringLiteral("文档特征编号重复：%1").arg(identifier));
        identifiers.insert(identifier);
        QJsonObject feature{{"id", identifier}, {"type", source.value("type")},
            {"name", source.value("name").toString().isEmpty() ? identifier : source.value("name").toString()},
            {"params", source.value("params")}, {"suppressed", source.value("suppressed").toBool()}};
        if (source.value("process").isObject()) feature["process"] = source.value("process");
        if (!source.value("folder").toString().isEmpty()) feature["folder"] = source.value("folder");
        loaded.append(feature);
        bool numeric = false;
        const int number = identifier.mid(1).toInt(&numeric);
        if (numeric) serial = std::max(serial, number);
    }
    std::optional<int> rollback;
    if (!data.value("upto").isNull() && !data.value("upto").isUndefined()) {
        const auto value = data.value("upto");
        if (!value.isDouble() || value.toInt(-1) < 0 || value.toDouble() != value.toInt())
            throw Error(QStringLiteral("文档回滚位置无效"));
        if (value.toInt() < loaded.size()) rollback = value.toInt();
    }
    features = loaded;
    upto = rollback;
    props = data.value("props").toObject();
    serial_ = serial;
    undo_.clear();
    redo_.clear();
    dirty = false;
    ++revision;
}

void Document::save(const QString &filePath) {
    const QString target = filePath.isEmpty() ? path : filePath;
    if (target.isEmpty()) throw Error(QStringLiteral("还没有指定保存位置"));
    QSaveFile file(target);
    if (!file.open(QIODevice::WriteOnly)) throw Error(QStringLiteral("保存失败：%1").arg(file.errorString()));
    const auto data = QJsonDocument(toData()).toJson(QJsonDocument::Indented);
    if (file.write(data) != data.size() || !file.commit()) throw Error(QStringLiteral("保存失败：%1").arg(file.errorString()));
    path = target;
    dirty = false;
}

void Document::open(const QString &filePath) {
    QFile file(filePath);
    if (!file.open(QIODevice::ReadOnly)) throw Error(QStringLiteral("打不开文档：%1").arg(file.errorString()));
    QJsonParseError error;
    const auto json = QJsonDocument::fromJson(file.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !json.isObject()) throw Error(QStringLiteral("文档 JSON 无效：%1").arg(error.errorString()));
    loadData(json.object());
    path = filePath;
}

void Document::clear() {
    features = {};
    upto.reset();
    props = {};
    path.clear();
    serial_ = 0;
    undo_.clear();
    redo_.clear();
    dirty = false;
    ++revision;
}

}
