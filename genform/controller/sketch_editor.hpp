#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QObject>
#include <QVector2D>

namespace genform::controller {

class SketchEditor : public QObject {
    Q_OBJECT
public:
    explicit SketchEditor(QObject *parent = nullptr);
    QJsonArray shapes() const { return shapes_; }
    QVector<int> selection() const { return selection_; }
    QString tool() const { return tool_; }
    QString operation() const { return operation_.value("kind").toString(); }
    QJsonArray preview() const;
    QJsonObject properties() const;
    QJsonObject panel() const;
    void reset(const QJsonArray &shapes = {});
    void setShapes(const QJsonArray &shapes);
    void setSelection(const QVector<int> &selection);
    bool setTool(const QString &tool);
    void setField(const QString &key, const QJsonValue &value);
    void beginOperation(const QString &operation);
    void acceptOperation();
    void cancelOperation();
    void escape();
    void finishDraft(bool closed = false);
    void action(const QString &action);
    void press(const QVector2D &point, double tolerance, bool additive = false);
    void move(const QVector2D &point);
    void release(const QVector2D &point);
    void box(const QVector2D &first, const QVector2D &second, bool crossing, bool additive);
    void importShapes(const QJsonArray &shapes);
    void setReferences(const QJsonArray &shapes);
    int hit(const QVector2D &point, double tolerance) const;
    bool drafting() const { return !points_.isEmpty(); }
    bool dragging() const { return dragging_; }
    QVector<QVector2D> draftPoints() const { return points_; }
    static QStringList tools();
Q_SIGNALS:
    void shapesChanged(const QJsonArray &shapes);
    void selectionChanged();
    void visualChanged();
    void toolChanged();
    void error(const QString &message);
private:
    QJsonArray shapes_, dragBefore_, references_;
    QVector<int> selection_;
    QVector<QVector2D> points_;
    QVector2D cursor_, dragStart_;
    QString tool_ = QStringLiteral("select");
    QJsonObject options_, operation_, textPath_;
    bool dragging_ = false;
    int source_ = -1;
    double tolerance_ = 1;
    double sweep_ = 0;
    QJsonObject makeShape(const QVector<QVector2D> &points) const;
    QJsonArray chosen() const;
    void commit(const QJsonArray &shapes);
    void add(const QJsonObject &shape);
    void relate(const QString &kind);
    void validate(const QJsonObject &shape) const;
    void updateSweep(const QVector2D &point);
};

}
