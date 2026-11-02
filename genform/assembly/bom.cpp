#include "detail.hpp"
#include <QCryptographicHash>
#include <algorithm>

namespace genform::assembly::detail {

double density(const QString &material) {
    static const QMap<QString, double> values{{"普通碳钢", 7.85}, {"合金钢", 7.70}, {"不锈钢 304", 7.93},
        {"铸铁", 7.20}, {"铝合金 6061", 2.70}, {"铝合金 7075", 2.81}, {"45# 钢", 7.85}, {"黄铜", 8.50},
        {"紫铜", 8.90}, {"钛合金 Ti-6Al-4V", 4.43}, {"ABS", 1.04}, {"尼龙 PA12", 1.01}, {"聚碳酸酯 PC", 1.20},
        {"PLA", 1.24}, {"聚丙烯 PP", 0.91}, {"PMMA 亚克力", 1.19}, {"铸造铝合金 A356", 2.68},
        {"钢化玻璃", 2.50}, {"橡胶", 1.15}, {"皮革 + 海绵", 0.35}};
    return values.value(material, -1);
}

QJsonObject bom(const QJsonArray &parts, const QJsonArray &documents) {
    std::vector<QJsonObject> rows;
    QMap<QString, int> seen;
    const QSet<QString> references{"sketch", "plane", "axis", "point", "curve", "helix", "coordinate"};
    const QMap<QString, QString> kinds{{"standard", "标准件"}, {"purchase", "外购件"}, {"custom", "非标件"}};
    for (int index = 0; index < parts.size(); ++index) {
        const auto part = parts[index].toObject(), document = documents[index].toObject();
        QJsonArray processes;
        for (const auto &entry : document["features"].toArray()) {
            const auto feature = entry.toObject(), process = feature["process"].toObject();
            if (!references.contains(feature["type"].toString()) && !feature["suppressed"].toBool() && !process["id"].toString().isEmpty()) processes.append(process);
        }
        QString kind = "custom", spec;
        QJsonObject main;
        double total = 0, highest = -1e300;
        bool standard = !processes.isEmpty();
        for (const auto &entry : processes) {
            const auto process = entry.toObject();
            const double cost = number(process, "cost");
            total += cost;
            if (cost > highest) { highest = cost; main = process; }
            if (spec.isEmpty()) spec = process["spec"].toString();
            standard = standard && process["standard"].toBool();
        }
        if (main["id"] == "purchase") kind = "purchase";
        else if (standard) kind = "standard";
        const bool handed = part["mirror"].toBool() && kind == "custom";
        const QString path = part["path"].toString();
        QString normalized = path;
#ifdef Q_OS_WIN
        normalized = normalized.toCaseFolded();
#endif
        const QString source = normalized.isEmpty() ? QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(document).toJson(QJsonDocument::Compact), QCryptographicHash::Sha256).toHex()) : normalized;
        const QString key = source + (handed ? ":mirror" : ":normal");
        if (!seen.contains(key)) {
            seen[key] = static_cast<int>(rows.size());
            rows.push_back({{"name", part["name"].toString() + (handed ? "（镜像件）" : "")}, {"path", path},
                {"mirror", handed}, {"kind", kind}, {"kind_name", kinds.value(kind)}, {"spec", spec},
                {"process", main["name"].toString()}, {"material", document["props"].toObject()["material"].toString()},
                {"unit", std::round(total * 100) / 100}, {"bound", !processes.isEmpty()}, {"count", 0}, {"indices", QJsonArray{}}});
        }
        auto &row = rows[seen[key]];
        row["count"] = row["count"].toInt() + 1;
        auto indices = row["indices"].toArray();
        indices.append(index);
        row["indices"] = indices;
    }
    const QMap<QString, int> order{{"custom", 0}, {"purchase", 1}, {"standard", 2}};
    std::stable_sort(rows.begin(), rows.end(), [&](const auto &first, const auto &second) {
        const int firstOrder = order.value(first["kind"].toString()), secondOrder = order.value(second["kind"].toString());
        return firstOrder == secondOrder ? first["name"].toString() < second["name"].toString() : firstOrder < secondOrder;
    });
    QJsonObject totals;
    for (const auto &kind : {QString("custom"), QString("purchase"), QString("standard"), QString("all")})
        totals[kind] = QJsonObject{{"types", 0}, {"count", 0}, {"cost", 0}};
    QJsonArray result;
    int unbound = 0;
    for (auto row : rows) {
        row["total"] = std::round(row["unit"].toDouble() * row["count"].toInt() * 100) / 100;
        for (const auto &kind : {row["kind"].toString(), QString("all")}) {
            auto total = totals[kind].toObject();
            total["types"] = total["types"].toInt() + 1;
            total["count"] = total["count"].toInt() + row["count"].toInt();
            total["cost"] = std::round((total["cost"].toDouble() + row["total"].toDouble()) * 100) / 100;
            totals[kind] = total;
        }
        if (!row["bound"].toBool()) ++unbound;
        result.append(row);
    }
    totals["unbound"] = unbound;
    return {{"rows", result}, {"totals", totals}};
}
}
