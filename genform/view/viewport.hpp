#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QMatrix4x4>
#include <QPolygonF>
#include <QQuickPaintedItem>
#include <QSet>
#include <QVector3D>

namespace genform::controller { class SketchEditor; }
namespace genform::view {

class Viewport : public QQuickPaintedItem {
    Q_OBJECT
    Q_PROPERTY(bool dark READ dark WRITE setDark NOTIFY displayChanged)
    Q_PROPERTY(QVariantList axes READ axes NOTIFY cameraChanged)
    Q_PROPERTY(QVariantList labels READ labels NOTIFY labelsChanged)
    Q_PROPERTY(QVariantList band READ band NOTIFY bandChanged)
    Q_PROPERTY(bool bandCrossing READ bandCrossing NOTIFY bandChanged)
    Q_PROPERTY(QVariantList zoomRect READ zoomRect NOTIFY bandChanged)
    Q_PROPERTY(bool zoomArmed READ zoomArmed NOTIFY displayChanged)
    Q_PROPERTY(bool gestureActive READ gestureActive NOTIFY displayChanged)
    Q_PROPERTY(int gestureIndex READ gestureIndex NOTIFY displayChanged)
    Q_PROPERTY(double gestureX READ gestureX NOTIFY displayChanged)
    Q_PROPERTY(double gestureY READ gestureY NOTIFY displayChanged)
    Q_PROPERTY(bool planesVisible READ planesVisible WRITE setPlanesVisible NOTIFY displayChanged)
public:
    explicit Viewport(QQuickItem *parent = nullptr);
    void paint(QPainter *painter) override;
    bool dark() const { return dark_; }
    void setDark(bool value);
    QVariantList axes() const;
    QVariantList labels() const;
    QVariantList band() const;
    QVariantList zoomRect() const;
    bool bandCrossing() const { return cursor_.x() < press_.x(); }
    bool zoomArmed() const { return zoomArmed_; }
    bool gestureActive() const { return false; }
    int gestureIndex() const { return -1; }
    double gestureX() const { return press_.x(); }
    double gestureY() const { return press_.y(); }
    bool planesVisible() const { return planesVisible_; }
    void setPlanesVisible(bool value);
    void setModel(const QJsonObject &model);
    void setSelection(const QJsonObject &selection);
    void setPickKind(const QString &kind);
    void setPlaneVisible(const QString &plane, bool visible);
    bool planeVisible(const QString &plane) const;
    void fitPlane(const QString &plane);
    void setAppearance(const QJsonObject &properties);
    void cancelInteraction();
    Q_INVOKABLE void setCheckHighlights(const QStringList &identifiers);
    void setHidden(const QSet<QString> &identifiers);
    void setStyle(const QString &style);
    void setColor(const QColor &color);
    void setSketch(const QJsonArray &shapes, const QString &plane, double offset = 0,bool turn=true);
    void setSketchOwner(const QString &identifier);
    void endSketch();
    void setSketchTool(const QString &tool);
    void setSketchSelection(int index);
    void setEditor(controller::SketchEditor *editor);
    void setGridSnap(bool enabled) { gridSnap_ = enabled; if (enabled) snapKinds_.insert("grid"); else snapKinds_.remove("grid"); update(); }
    void setSnaps(const QSet<QString> &enabled,const QString &only={}) { snapKinds_=enabled; quickSnap_=only; gridSnap_=enabled.contains("grid"); update(); }
    void cancelDraft();
    void armZoom();
    QJsonArray sketchShapes() const;
    QJsonObject cameraState() const;
    void restoreCamera(const QJsonObject &state);
    bool saveImage(const QString &path);
    Q_INVOKABLE void fit();
    Q_INVOKABLE void setView(const QString &name);
Q_SIGNALS:
    void displayChanged();
    void cameraChanged();
    void labelsChanged();
    void bandChanged();
    void picked(const QJsonObject &selection, bool additive);
    void contextPicked(const QJsonObject &selection, double x, double y);
    void doublePicked(const QJsonObject &selection);
    void boxed(const QJsonArray &faces, bool additive);
    void sketchEdited(const QJsonArray &shapes);
    void sketchSelectionChanged(int index);
    void menuRequested(const QString &identifier, double x, double y);
    void hoverChanged(const QString &text);
    void quickSnapConsumed();
protected:
    void mousePressEvent(QMouseEvent *event) override;
    void mouseMoveEvent(QMouseEvent *event) override;
    void mouseReleaseEvent(QMouseEvent *event) override;
    void mouseDoubleClickEvent(QMouseEvent *event) override;
    void wheelEvent(QWheelEvent *event) override;
    void hoverMoveEvent(QHoverEvent *event) override;
private:
    struct Triangle { QPolygonF polygon; double depth; int face; QString feature; QVector3D normal; };
    QJsonObject model_, selection_;
    controller::SketchEditor *editor_ = nullptr;
    QJsonArray shapes_;
    QSet<QString> hidden_;
    QSet<QString> hiddenPlanes_, checkHighlights_;
    QJsonObject appearance_;
    QString hoverPlane_;
    QSet<QString> snapKinds_{"end","mid","center","quad","int","near","hv","grid"};
    QString quickSnap_;
    QVector<QVector3D> vertices_;
    QVector<Triangle> triangles_;
    QMatrix4x4 rotation_;
    QVector3D centre_;
    QPointF pan_, press_, last_, cursor_, draftStart_, dragStart_;
    QJsonArray dragShapes_;
    double scale_ = 5, yaw_ = -45, pitch_ = -54.736, sketchOffset_ = 0;
    bool dark_ = true, planesVisible_ = true, sketch_ = false, draft_ = false;
    bool pressed_ = false, orbit_ = false, panning_ = false, boxing_ = false, movingShape_ = false;
    bool gridSnap_ = true, zoomArmed_ = false;
    int selectedShape_ = -1;
    Qt::MouseButton button_ = Qt::NoButton;
    QString plane_ = QStringLiteral("XY"), tool_ = QStringLiteral("select"), style_ = QStringLiteral("shaded_edges");
    QColor bodyColor_ = QColor(QStringLiteral("#91abc6"));
    QString pickKind_;
    QVariantList notifiedLabels_;
    QString editingSketch_;
    void updateRotation();
    void updateLabels();
    bool sketchViewValid(double yaw, double pitch) const;
    QPointF project(const QVector3D &point) const;
    QVector3D world(const QPointF &point) const;
    QPointF sketchPoint(const QPointF &point,bool snap=true) const;
    QJsonObject draftShape(const QPointF &point) const;
    QVector3D planePoint(const QPointF &point) const;
    void drawShape(QPainter *painter, const QJsonObject &shape, bool selected, bool draft = false);
    int hitShape(const QPointF &position) const;
    QJsonObject pick(const QPointF &position) const;
    bool vertexVisible(const QVector3D &point) const;
    QVector<QVector3D> planeCorners(const QString &plane) const;
};

}
