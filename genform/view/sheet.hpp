#pragma once

#include "genform/session.hpp"
#include <QQuickPaintedItem>
#include <QMap>
#include <QPointF>
#include <QStringList>

namespace genform::view {

class SheetView : public QQuickPaintedItem {
    Q_OBJECT
    Q_PROPERTY(bool dark READ dark WRITE setDark NOTIFY changed)
public:
    explicit SheetView(QQuickItem *parent = nullptr);
    bool dark() const { return dark_; }
    void setDark(bool dark);
    void setSheet(const QJsonObject &sheet);
    const QJsonObject &sheet() const { return sheet_; }
    void paint(QPainter *painter) override;
    void paintPage(QPainter *painter) const;
    Q_INVOKABLE void fit();
Q_SIGNALS:
    void changed();
    void pressed(double x, double y);
    void moved(double x, double y);
    void released(double x, double y);
protected:
    void mousePressEvent(QMouseEvent *event) override;
    void mouseMoveEvent(QMouseEvent *event) override;
    void mouseReleaseEvent(QMouseEvent *event) override;
    void wheelEvent(QWheelEvent *event) override;
private:
    QJsonObject sheet_;
    bool dark_ = true, panning_ = false;
    double zoom_ = 1;
    QPointF pan_, last_;
    QPointF pagePoint(const QPointF &position) const;
};

}

namespace genform::controller {

class DrawingBridge : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantMap state READ state NOTIFY changed)
public:
    explicit DrawingBridge(Session *session, QObject *parent = nullptr);
    void attach(view::SheetView *view);
    void begin();
    QVariantMap state() const;
    bool open(const QString &path);
    bool save(const QString &path);
    bool exportFile(const QString &path);
    QString path() const { return path_; }
    bool dirty() const { return dirty_; }
    Q_INVOKABLE void setPart(const QString &path);
    Q_INVOKABLE void project();
    Q_INVOKABLE void fit();
    Q_INVOKABLE void resetLayout();
    Q_INVOKABLE void setScale(const QString &scale);
    Q_INVOKABLE void setSheet(const QString &sheet);
    Q_INVOKABLE void setTitle(const QString &key, const QString &value);
    Q_INVOKABLE void toggle(const QString &key);
    Q_INVOKABLE void toggleView(const QString &name);
    Q_INVOKABLE void useTool(const QString &tool);
    Q_INVOKABLE void deleteSelected();
Q_SIGNALS:
    void changed();
    void notice(const QString &text);
private:
    Session *session_;
    view::SheetView *view_ = nullptr;
    QJsonObject data_, projection_, sheet_;
    QJsonArray dimensions_;
    QString path_, source_, error_, tool_ = QStringLiteral("select"), movingView_;
    QString dimensionView_;
    QStringList dimensionWarnings_;
    QMap<int, QPointF> dimensionHandles_;
    QPointF press_, originalOffset_, firstDimension_;
    bool dirty_ = false, running_ = false, dimensionStarted_ = false;
    int selectedDimension_ = -1;
    void refresh(bool touch = false);
    bool snapPoint(const QPointF &page, QString &name, QPointF &point) const;
    void mousePress(double x, double y);
    void mouseMove(double x, double y);
    void mouseRelease(double x, double y);
};

}
