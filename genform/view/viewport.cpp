#include "genform/view/viewport.hpp"
#include "genform/controller/sketch_editor.hpp"
#include "genform/view/sketch_snap.hpp"
#include "genform/domain/geometry.hpp"
#include <QHoverEvent>
#include <QFontMetricsF>
#include <QImage>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QWheelEvent>
#include <QtMath>
#include <algorithm>
#include <cmath>
#include <limits>

namespace genform::view {
namespace {
QJsonValue element(const QJsonArray &array, qsizetype index) { return index >= 0 && index < array.size() ? array.at(index) : QJsonValue(); }
QJsonObject topology(const QJsonArray &array,int identifier) { const auto direct=element(array,identifier).toObject(); if (direct.value("id").toInt(-1)==identifier) return direct; for (const auto &value : array) if (value.toObject().value("id").toInt(-1)==identifier) return value.toObject(); return {}; }
QVector3D vectorOf(const QJsonValue &value) {
    const auto array = value.toArray();
    return QVector3D(element(array,0).toDouble(), element(array,1).toDouble(), element(array,2).toDouble());
}
double segmentDistance(const QPointF &point, const QPointF &start, const QPointF &end) {
    const QPointF delta = end - start;
    const double square = QPointF::dotProduct(delta, delta);
    const double fraction = square > 0 ? std::clamp(QPointF::dotProduct(point - start, delta) / square, 0.0, 1.0) : 0;
    return QLineF(point, start + fraction * delta).length();
}
QVector<QPointF> shapePoints(const QJsonObject &shape) {
    QVector<QPointF> points;
    try { for (const auto &polyline : domain::polylines(shape,64)) for (const auto &point : polyline) points.append(point.toPointF()); }
    catch (const std::exception &) {}
    if (points.isEmpty() && (shape.value("type")=="text" || shape.value("type")=="point")) points.append({shape.value("x").toDouble(),shape.value("y").toDouble()});
    return points;
}
}

Viewport::Viewport(QQuickItem *parent) : QQuickPaintedItem(parent) {
    setAcceptedMouseButtons(Qt::AllButtons);
    setAcceptHoverEvents(true);
    setAntialiasing(true);
    setOpaquePainting(false);
    connect(this, &QQuickItem::widthChanged, this, [this] { update(); updateLabels(); });
    connect(this, &QQuickItem::heightChanged, this, [this] { update(); updateLabels(); });
    connect(this, &Viewport::cameraChanged, this, &Viewport::updateLabels);
    updateRotation();
}
void Viewport::setDark(bool value) { if (dark_ != value) { dark_ = value; update(); Q_EMIT displayChanged(); } }
void Viewport::setPlanesVisible(bool value) { if (planesVisible_ == value) return; planesVisible_ = value; update(); updateLabels(); Q_EMIT displayChanged(); }
void Viewport::setHidden(const QSet<QString> &value) { hidden_ = value; update(); }
void Viewport::setStyle(const QString &value) { style_ = value; update(); Q_EMIT displayChanged(); }
void Viewport::setColor(const QColor &value) { if (value.isValid()) bodyColor_ = value; update(); }
void Viewport::setSelection(const QJsonObject &value) { if (selection_ == value) return; selection_ = value; update(); updateLabels(); Q_EMIT displayChanged(); }
void Viewport::setPickKind(const QString &kind) { if (pickKind_ == kind) return; pickKind_ = kind; update(); }
void Viewport::setPlaneVisible(const QString &plane, bool visible) { if (hiddenPlanes_.contains(plane) == !visible) return; if (visible) hiddenPlanes_.remove(plane); else hiddenPlanes_.insert(plane); update(); updateLabels(); Q_EMIT displayChanged(); }
bool Viewport::planeVisible(const QString &plane) const { return planesVisible_ && !hiddenPlanes_.contains(plane); }
void Viewport::setAppearance(const QJsonObject &properties) { appearance_ = properties; update(); }
void Viewport::setCheckHighlights(const QStringList &identifiers) { checkHighlights_ = QSet<QString>(identifiers.begin(), identifiers.end()); update(); }
void Viewport::cancelInteraction() { pressed_ = orbit_ = panning_ = boxing_ = movingShape_ = zoomArmed_ = draft_ = false; update(); Q_EMIT bandChanged(); Q_EMIT displayChanged(); }
QVector<QVector3D> Viewport::planeCorners(const QString &plane) const {
    double reach = 25;
    const auto size = model_.value("props").toObject().value("size").toArray();
    for (const auto &value : size) reach = std::max(reach, std::abs(value.toDouble()) * 0.65);
    const auto frame = domain::frame(plane);
    QVector<QVector3D> corners;
    for (const auto &point : {QPointF(-reach,-reach),QPointF(reach,-reach),QPointF(reach,reach),QPointF(-reach,reach)})
        corners.append(frame.origin + float(point.x()) * frame.x + float(point.y()) * frame.y);
    return corners;
}
void Viewport::fitPlane(const QString &plane) {
    const auto corners = planeCorners(plane);
    centre_ = {}; pan_ = {};
    QRectF bounds;
    for (const auto &corner : corners) { const auto point = rotation_.map(corner); const QRectF pixel(point.x(),point.y(),0.01,0.01); bounds = bounds.isNull() ? pixel : bounds.united(pixel); }
    scale_ = std::max(0.001, std::min(width()/std::max(1.0,bounds.width()),height()/std::max(1.0,bounds.height())) * 0.7);
    update(); Q_EMIT cameraChanged(); Q_EMIT displayChanged();
}
QVariantList Viewport::labels() const {
    QVariantList result;
    if (sketch_) return result;
    for (const auto &name : QStringList{"XY","XZ","YZ"}) {
        const bool selected = selection_.value("plane").toString() == name;
        if (!planeVisible(name) && !selected) continue;
        const auto point = project(planeCorners(name).at(2));
        result.append(QVariantMap{{"text",name},{"x",point.x()},{"y",point.y()},{"kind","plane"},{"selected",selected}});
    }
    return result;
}
void Viewport::updateLabels() {
    const auto current = labels();
    if (notifiedLabels_ == current) return;
    notifiedLabels_ = current;
    Q_EMIT labelsChanged();
}
void Viewport::updateRotation() {
    rotation_.setToIdentity();
    rotation_.rotate(pitch_, 1, 0, 0);
    rotation_.rotate(yaw_, 0, 0, 1);
    update();
    Q_EMIT cameraChanged();
}
QPointF Viewport::project(const QVector3D &point) const {
    const auto rotated = rotation_.map(point - centre_);
    return QPointF(width() / 2 + pan_.x() + rotated.x() * scale_, height() / 2 + pan_.y() - rotated.y() * scale_);
}
QVector3D Viewport::world(const QPointF &point) const {
    return rotation_.inverted().map(QVector3D((point.x() - width() / 2 - pan_.x()) / scale_,
                                           -(point.y() - height() / 2 - pan_.y()) / scale_, 0)) + centre_;
}
QVariantList Viewport::axes() const {
    QVariantList result;
    for (const auto &axis : {QVector3D(1, 0, 0), QVector3D(0, 1, 0), QVector3D(0, 0, 1)}) {
        const auto rotated = rotation_.mapVector(axis);
        result.append(QVariant(QVariantList{rotated.x(), -rotated.y(), -rotated.z()}));
    }
    return result;
}
QVariantList Viewport::band() const {
    if (!boxing_ || zoomArmed_) return {};
    const QRectF box = QRectF(press_, cursor_).normalized();
    return {QVariant(QVariantList{box.left(),box.top()}),QVariant(QVariantList{box.right(),box.top()}),
            QVariant(QVariantList{box.right(),box.bottom()}),QVariant(QVariantList{box.left(),box.bottom()})};
}
QVariantList Viewport::zoomRect() const {
    if (!boxing_ || !zoomArmed_) return {};
    const QRectF box = QRectF(press_, cursor_).normalized();
    return {box.x(), box.y(), box.width(), box.height()};
}
void Viewport::setModel(const QJsonObject &model) {
    if (model_ == model) return;
    const bool first = vertices_.isEmpty();
    model_ = model;
    vertices_.clear();
    for (const auto &point : model.value("verts").toArray()) vertices_.append(vectorOf(point));
    if (first && (!vertices_.isEmpty() || !model.value("sketches").toObject().isEmpty())) fit();
    update();
    updateLabels();
}
void Viewport::fit() {
    QVector<QVector3D> points = vertices_;
    const auto sketches = model_.value("sketches").toObject();
    for (auto iterator = sketches.begin(); iterator != sketches.end(); ++iterator) {
        for (const auto &segment : iterator.value().toArray()) {
            const auto pair = segment.toArray();
            if (!pair.isEmpty() && pair.first().isArray()) {
                for (const auto &point : pair) points.append(vectorOf(point));
            } else points.append(vectorOf(segment));
        }
    }
    if (sketch_) for (const auto &shape : shapes_) for (const auto &point : shapePoints(shape.toObject())) points.append(planePoint(point));
    pan_ = {};
    if (points.isEmpty()) { centre_ = {}; scale_ = std::max(1.0, std::min(width(), height()) / 120); }
    else {
        QVector3D low = points.front(), high = low;
        for (const auto &point : points) {
            low.setX(std::min(low.x(), point.x())); low.setY(std::min(low.y(), point.y())); low.setZ(std::min(low.z(), point.z()));
            high.setX(std::max(high.x(), point.x())); high.setY(std::max(high.y(), point.y())); high.setZ(std::max(high.z(), point.z()));
        }
        centre_ = (low + high) / 2;
        QRectF box;
        bool initial = true;
        for (const auto &point : points) {
            const auto rotated = rotation_.map(point - centre_);
            const QPointF projected(rotated.x(), rotated.y());
            if (initial) { box = QRectF(projected, QSizeF(0, 0)); initial = false; }
            else { box.setLeft(std::min(box.left(), projected.x())); box.setRight(std::max(box.right(), projected.x()));
                   box.setTop(std::min(box.top(), projected.y())); box.setBottom(std::max(box.bottom(), projected.y())); }
        }
        scale_ = std::clamp(std::min(std::max(100.0, width() - 100) / std::max(1.0, box.width()),
                                    std::max(100.0, height() - 120) / std::max(1.0, box.height())), 0.001, 10000.0);
    }
    update(); Q_EMIT cameraChanged();
}
void Viewport::setView(const QString &name) {
    const double previousYaw=yaw_,previousPitch=pitch_;
    if (name == "top" || name == "XY") { yaw_ = 0; pitch_ = 0; }
    else if (name == "bottom") { yaw_ = 0; pitch_ = 180; }
    else if (name == "front" || name == "XZ") { yaw_ = 0; pitch_ = -90; }
    else if (name == "back") { yaw_ = 180; pitch_ = -90; }
    else if (name == "right" || name == "YZ") { yaw_ = -90; pitch_ = -90; }
    else if (name == "left") { yaw_ = 90; pitch_ = -90; }
    else if (name == "iso" || name == "isometric") { yaw_ = -45; pitch_ = -54.736; }
    else if (name == "fit") { fit(); return; }
    else return;
    if (!sketchViewValid(yaw_,pitch_)) { yaw_=previousYaw; pitch_=previousPitch; Q_EMIT hoverChanged(QStringLiteral("该视角与当前草图平行；请正视当前草图平面。")); return; }
    updateRotation();
}
bool Viewport::sketchViewValid(double yaw, double pitch) const {
    if (!sketch_) return true;
    QMatrix4x4 rotation;
    rotation.rotate(float(pitch),1,0,0); rotation.rotate(float(yaw),0,0,1);
    return std::abs(QVector3D::dotProduct(domain::frame(plane_,sketchOffset_).normal,rotation.inverted().mapVector(QVector3D(0,0,-1))))>=1e-6;
}
QJsonObject Viewport::cameraState() const {
    return {{"yaw", yaw_}, {"pitch", pitch_}, {"scale", scale_}, {"pan_x", pan_.x()}, {"pan_y", pan_.y()},
            {"centre", QJsonArray{centre_.x(), centre_.y(), centre_.z()}}};
}
void Viewport::restoreCamera(const QJsonObject &state) {
    if (!sketchViewValid(state.value("yaw").toDouble(yaw_),state.value("pitch").toDouble(pitch_))) { Q_EMIT hoverChanged(QStringLiteral("该视角与当前草图平行；请正视当前草图平面。")); return; }
    yaw_ = state.value("yaw").toDouble(yaw_); pitch_ = state.value("pitch").toDouble(pitch_);
    scale_ = std::max(0.001, state.value("scale").toDouble(scale_));
    pan_ = {state.value("pan_x").toDouble(), state.value("pan_y").toDouble()};
    if (state.contains("centre")) centre_ = vectorOf(state.value("centre"));
    updateRotation();
}
void Viewport::setSketch(const QJsonArray &shapes, const QString &plane, double offset,bool turn) {
    const bool beginning = !sketch_ || plane_ != plane;
    shapes_ = shapes; plane_ = plane; sketchOffset_ = offset; sketch_ = true;
    if (editor_) editor_->setShapes(shapes);
    if (beginning) { cancelInteraction(); hoverPlane_.clear(); Q_EMIT hoverChanged({}); selectedShape_ = -1; if (turn || !sketchViewValid(yaw_,pitch_)) { setView(plane); fit(); } }
    update();
    updateLabels();
}
void Viewport::setSketchOwner(const QString &identifier) { if (editingSketch_==identifier) return; editingSketch_=identifier; update(); }
void Viewport::endSketch() { sketch_ = false; editingSketch_.clear(); hoverPlane_.clear(); Q_EMIT hoverChanged({}); cancelInteraction(); selectedShape_ = -1; if (editor_) editor_->escape(); update(); updateLabels(); }
void Viewport::setSketchTool(const QString &tool) { tool_ = tool; if (editor_) editor_->setTool(tool); draft_ = false; update(); }
void Viewport::setSketchSelection(int index) { selectedShape_=index; update(); }
QJsonArray Viewport::sketchShapes() const { return editor_?editor_->shapes():shapes_; }
void Viewport::setEditor(controller::SketchEditor *editor) {
    if (editor_==editor) return;
    if (editor_) disconnect(editor_,nullptr,this,nullptr);
    editor_=editor;
    if (!editor_) return;
    connect(editor_,&controller::SketchEditor::shapesChanged,this,[this](const QJsonArray &shapes) { shapes_=shapes; Q_EMIT sketchEdited(shapes); update(); });
    connect(editor_,&controller::SketchEditor::selectionChanged,this,[this] { const auto selected=editor_->selection(); selectedShape_=selected.isEmpty()?-1:selected.first(); Q_EMIT sketchSelectionChanged(selectedShape_); update(); });
    connect(editor_,&controller::SketchEditor::visualChanged,this,[this] { shapes_=editor_->shapes(); draft_=editor_->drafting(); update(); });
    connect(editor_,&controller::SketchEditor::toolChanged,this,[this] { tool_=editor_->tool(); update(); });
}
void Viewport::cancelDraft() { draft_ = false; if (editor_) editor_->escape(); update(); }
void Viewport::armZoom() { if (zoomArmed_) return; pressed_=orbit_=panning_=boxing_=movingShape_=false; zoomArmed_ = true; Q_EMIT bandChanged(); Q_EMIT displayChanged(); }
QVector3D Viewport::planePoint(const QPointF &point) const {
    if (plane_ == "XZ") return QVector3D(point.x(), -sketchOffset_, point.y());
    if (plane_ == "YZ") return QVector3D(sketchOffset_, point.x(), point.y());
    return QVector3D(point.x(), point.y(), sketchOffset_);
}
QPointF Viewport::sketchPoint(const QPointF &point,bool snap) const {
    const auto vector = world(point); const auto direction=rotation_.inverted().mapVector(QVector3D(0,0,-1));
    const auto basis=domain::frame(plane_,sketchOffset_); const double slope=QVector3D::dotProduct(direction,basis.normal);
    const double reach=std::abs(slope)>1e-9?QVector3D::dotProduct(basis.origin-vector,basis.normal)/slope:0;
    const auto intersection=vector+direction*float(reach)-basis.origin;
    QPointF result(QVector3D::dotProduct(intersection,basis.x),QVector3D::dotProduct(intersection,basis.y));
    if (snap) result=snapSketch(shapes_,QVector2D(result),scale_,snapKinds_,quickSnap_,editor_ && editor_->dragging()?editor_->selection():QVector<int>{},editor_?editor_->draftPoints():QVector<QVector2D>{}).point.toPointF();
    return result;
}
QJsonObject Viewport::draftShape(const QPointF &point) const {
    if (tool_ == "line") return {{"type", "line"}, {"x1", draftStart_.x()}, {"y1", draftStart_.y()}, {"x2", point.x()}, {"y2", point.y()}};
    if (tool_ == "circle") return {{"type", "circle"}, {"cx", draftStart_.x()}, {"cy", draftStart_.y()}, {"r", QLineF(draftStart_, point).length()}};
    if (tool_ == "crect") return {{"type", "rect"}, {"cx", draftStart_.x()}, {"cy", draftStart_.y()},
            {"w", 2 * std::abs(point.x() - draftStart_.x())}, {"h", 2 * std::abs(point.y() - draftStart_.y())}};
    return {{"type", "rect"}, {"cx", (draftStart_.x() + point.x()) / 2}, {"cy", (draftStart_.y() + point.y()) / 2},
            {"w", std::abs(point.x() - draftStart_.x())}, {"h", std::abs(point.y() - draftStart_.y())}};
}
void Viewport::drawShape(QPainter *painter, const QJsonObject &shape, bool selected, bool draft) {
    QPen pen(selected ? QColor("#ffb347") : draft ? QColor("#6bbcff") : QColor("#52b5f9"), selected ? 2.5 : 1.6);
    if (shape.value("construction").toBool()) pen.setStyle(Qt::DashLine);
    painter->setPen(pen); painter->setBrush(Qt::NoBrush);
    try {
        if (shape.value("type")=="text") {
            QFont font(QStringLiteral("Microsoft YaHei UI")); font.setPixelSize(std::max(1,qRound(shape.value("height").toDouble(10)*scale_)));
            const QFontMetricsF metrics(font); const auto text=shape.value("text").toString(); QVector<double> advances;
            const auto characters=text.toUcs4(); for (const auto codepoint : characters) { const char32_t character=codepoint; advances.append(metrics.horizontalAdvance(QString::fromUcs4(&character,1))/scale_); }
            const auto layout=domain::text_layout(shape,advances);
            for (qsizetype index=0;index<layout.size();++index) {
                const auto location=layout[index]; const auto origin=project(planePoint({location.x(),location.y()}));
                const auto heading=project(planePoint({location.x()+std::cos(location.z()),location.y()+std::sin(location.z())}))-origin;
                painter->save(); painter->translate(origin); painter->rotate(qRadiansToDegrees(std::atan2(heading.y(),heading.x()))); painter->setFont(font);
                const char32_t character=characters[index]; painter->drawText(QPointF(),QString::fromUcs4(&character,1)); painter->restore();
            }
            return;
        }
        if (shape.value("type")=="point") {
            const auto point=project(planePoint({shape.value("x").toDouble(),shape.value("y").toDouble()})); painter->drawLine(point-QPointF(4,0),point+QPointF(4,0)); painter->drawLine(point-QPointF(0,4),point+QPointF(0,4)); return;
        }
        for (const auto &points : domain::polylines(shape,64)) {
            QPolygonF polygon; for (const auto &point : points) polygon.append(project(planePoint(point.toPointF()))); painter->drawPolyline(polygon);
        }
        if (selected) {
            painter->setBrush(QColor("#ffb347")); for (const auto &value : domain::key_points(shape)) {
                const auto record=value.toArray(); if (record.size()<2) continue;
                const auto point=record[1].toArray(); if (point.size()>=2) painter->drawEllipse(project(planePoint({point[0].toDouble(),point[1].toDouble()})),2.5,2.5);
            }
        }
    } catch (const std::exception &) {}
}
void Viewport::paint(QPainter *painter) {
    painter->setRenderHint(QPainter::Antialiasing);
    triangles_.clear();
    if (sketch_) {
        const double grid = sketchGridStep(scale_);
        painter->setPen(QPen(dark_ ? QColor("#29313a") : QColor("#d7dde5"), 0.7));
        const auto first=sketchPoint(QPointF(0,0),false),second=sketchPoint(QPointF(width(),0),false),third=sketchPoint(QPointF(0,height()),false),fourth=sketchPoint(QPointF(width(),height()),false);
        const double minX=std::min({first.x(),second.x(),third.x(),fourth.x()}),maxX=std::max({first.x(),second.x(),third.x(),fourth.x()});
        const double minY=std::min({first.y(),second.y(),third.y(),fourth.y()}),maxY=std::max({first.y(),second.y(),third.y(),fourth.y()});
        if (gridSnap_) for (double horizontal = std::floor(minX / grid) * grid; horizontal <= maxX && (maxX - minX) / grid < 500; horizontal += grid)
            painter->drawLine(project(planePoint({horizontal, minY})), project(planePoint({horizontal, maxY})));
        if (gridSnap_) for (double vertical = std::floor(minY / grid) * grid; vertical <= maxY && (maxY - minY) / grid < 500; vertical += grid)
            painter->drawLine(project(planePoint({minX, vertical})), project(planePoint({maxX, vertical})));
        painter->setPen(QPen(QColor("#be5b5b"), 1)); painter->drawLine(project(planePoint({minX, 0})), project(planePoint({maxX, 0})));
        painter->setPen(QPen(QColor("#60a477"), 1)); painter->drawLine(project(planePoint({0, minY})), project(planePoint({0, maxY})));
    }
    const auto faces = model_.value("faces").toArray(), faceNumbers = model_.value("tri_face").toArray();
    const auto indices = model_.value("tris").toArray();
    for (qsizetype index = 0; index < indices.size(); ++index) {
        const auto triplet = indices[index].toArray();
        if (triplet.size() < 3) continue;
        const int first = triplet[0].toInt(-1), second = triplet[1].toInt(-1), third = triplet[2].toInt(-1);
        if (first < 0 || second < 0 || third < 0 || first >= vertices_.size() || second >= vertices_.size() || third >= vertices_.size()) continue;
        const int face = element(faceNumbers,index).toInt(-1);
        const auto info = topology(faces,face);
        const auto feature = info.value("feature").toString();
        if (hidden_.contains(feature)) continue;
        const auto &pointA = vertices_[first], &pointB = vertices_[second], &pointC = vertices_[third];
        Triangle triangle;
        triangle.polygon << project(pointA) << project(pointB) << project(pointC);
        triangle.depth = rotation_.map((pointA + pointB + pointC) / 3 - centre_).z();
        triangle.face = face; triangle.feature = feature;
        triangle.normal = rotation_.mapVector(QVector3D::crossProduct(pointB - pointA, pointC - pointA).normalized());
        triangles_.append(triangle);
    }
    std::stable_sort(triangles_.begin(), triangles_.end(), [](const Triangle &left, const Triangle &right) { return left.depth < right.depth; });
    const auto chosenFaces = selection_.value("faces").toArray();
    const auto chosenFeature = selection_.value("feature").toString();
    const bool featureSelection = chosenFaces.isEmpty() && selection_.value("edges").toArray().isEmpty() && selection_.value("vertices").toArray().isEmpty();
    const bool wire = style_ == "wireframe" || style_ == "wire";
    if (!wire) for (const auto &triangle : triangles_) {
        const bool selected = chosenFaces.contains(triangle.face) || (featureSelection && !chosenFeature.isEmpty() && chosenFeature == triangle.feature);
        const double light = 0.40 + 0.60 * std::abs(QVector3D::dotProduct(triangle.normal, QVector3D(-0.3f, 0.5f, 0.8f).normalized()));
        QColor base = bodyColor_;
        const auto colors = appearance_.value("feature_colors").toObject();
        const auto featureColor = colors.value(triangle.feature);
        if (featureColor.isString() && QColor(featureColor.toString()).isValid()) base = QColor(featureColor.toString());
        else if (featureColor.isObject() && QColor(featureColor.toObject().value("color").toString()).isValid()) base = QColor(featureColor.toObject().value("color").toString());
        const auto opacities = appearance_.value("feature_opacity").toObject();
        base.setAlphaF(std::clamp(opacities.value(triangle.feature).toDouble(1.0),0.05,1.0));
        QColor color = checkHighlights_.contains(triangle.feature) ? QColor("#df4e53") : selected ? QColor("#3d9be5") : base;
        color.setRedF(color.redF() * light); color.setGreenF(color.greenF() * light); color.setBlueF(color.blueF() * light);
        if (sketch_) color.setAlpha(95);
        painter->setPen(QPen(color, 0.5)); painter->setBrush(color); painter->drawPolygon(triangle.polygon);
    }
    if (style_ != "shaded" || wire) {
        painter->setPen(QPen(dark_ ? QColor("#374e62") : QColor("#34495c"), 1));
        const auto segments = model_.value("segments").toArray(), edgeNumbers = model_.value("segment_edge").toArray();
        const auto edges = model_.value("edges").toArray();
        const auto chosen = selection_.value("edges").toArray();
        for (qsizetype index = 0; index < segments.size(); ++index) {
            const auto pair = segments[index].toArray();
            if (pair.size() < 2) continue;
            const int edge = element(edgeNumbers,index).toInt(-1);
            const auto owner = topology(edges,edge).value("feature").toString();
            if (hidden_.contains(owner)) continue;
            const bool flagged = checkHighlights_.contains(owner);
            painter->setPen(QPen(flagged ? QColor("#df4e53") : chosen.contains(edge) ? QColor("#ffb347") : dark_ ? QColor("#526c82") : QColor("#34495c"), flagged || chosen.contains(edge) ? 2.5 : 1));
            painter->drawLine(project(vectorOf(pair[0])), project(vectorOf(pair[1])));
        }
    }
    const auto sketches = model_.value("sketches").toObject();
    for (auto iterator = sketches.begin(); iterator != sketches.end(); ++iterator) {
        if (hidden_.contains(iterator.key()) || (sketch_ && iterator.key() == editingSketch_)) continue;
        painter->setPen(QPen(iterator.key() == chosenFeature ? QColor("#ffb347") : QColor("#4c9ecb"), 1.5));
        const auto lines = iterator.value().toArray();
        if (!lines.isEmpty() && element(lines.first().toArray(),0).isArray()) {
            for (const auto &segment : lines) {
                const auto pair = segment.toArray(); if (pair.size() >= 2) painter->drawLine(project(vectorOf(pair[0])), project(vectorOf(pair[1])));
            }
        } else for (qsizetype index = 0; index + 1 < lines.size(); index += 2) painter->drawLine(project(vectorOf(lines[index])), project(vectorOf(lines[index + 1])));
    }
    if (!sketch_) {
        if (pickKind_=="vertex") {
            const auto points=model_.value("vertices").toArray(),chosen=selection_.value("vertices").toArray();
            for (qsizetype index=0;index<points.size();++index) {
                if (points[index].toArray().size()!=3 || !vertexVisible(vectorOf(points[index]))) continue;
                const bool selected=chosen.contains(int(index));
                painter->setPen(QPen(selected?QColor("#ffb347"):QColor("#4c9ecb"),1));
                painter->setBrush(selected?QColor("#ffb347"):bodyColor_);
                painter->drawEllipse(project(vectorOf(points[index])),selected?4:2.5,selected?4:2.5);
            }
        }
        const QList<QColor> colors{QColor("#427eab"), QColor("#689261"), QColor("#9b6d65")};
        const QStringList names{"XY","XZ","YZ"};
        for (int index = 0; index < names.size(); ++index) {
            const bool selected = selection_.value("plane").toString() == names[index];
            if (!planeVisible(names[index]) && !selected) continue;
            QPolygonF polygon; for (const auto &point : planeCorners(names[index])) polygon << project(point);
            const bool hovered = hoverPlane_ == names[index];
            auto color = selected ? QColor("#49adff") : colors[index];
            auto fill = color; fill.setAlpha(selected ? 85 : hovered ? 50 : 18);
            painter->setBrush(fill); painter->setPen(QPen(color, selected ? 2.5 : hovered ? 1.8 : 1)); painter->drawPolygon(polygon);
        }
    }
    if (sketch_) {
        for (qsizetype index = 0; index < shapes_.size(); ++index) drawShape(painter, shapes_[index].toObject(), editor_?editor_->selection().contains(index):index == selectedShape_);
        if (editor_) for (const auto &shape : editor_->preview()) drawShape(painter,shape.toObject(),false,true);
        else if (draft_) drawShape(painter, draftShape(sketchPoint(cursor_)), false, true);
    }
}
int Viewport::hitShape(const QPointF &position) const {
    for (int index = shapes_.size() - 1; index >= 0; --index) {
        const auto points = shapePoints(shapes_[index].toObject());
        for (int segment = 1; segment < points.size(); ++segment)
            if (segmentDistance(position, project(planePoint(points[segment - 1])), project(planePoint(points[segment]))) < 8) return index;
    }
    return -1;
}
bool Viewport::vertexVisible(const QVector3D &point) const {
    const auto pixel=project(point); const double depth=rotation_.map(point-centre_).z();
    bool shown=hidden_.isEmpty();
    for (const auto &triangle : triangles_) {
        if (std::abs(triangle.normal.z())<1e-6) continue;
        const auto centre=(triangle.polygon[0]+triangle.polygon[1]+triangle.polygon[2])/3;
        const double surface=triangle.depth-(triangle.normal.x()*(pixel.x()-centre.x())-triangle.normal.y()*(pixel.y()-centre.y()))/(scale_*triangle.normal.z());
        if (!shown && std::abs(surface-depth)<1e-3) for (const auto &corner : triangle.polygon) if (QLineF(pixel,corner).length()<0.05) { shown=true; break; }
        if (surface>depth+0.05 && triangle.polygon.containsPoint(pixel,Qt::OddEvenFill)) return false;
    }
    return shown;
}
QJsonObject Viewport::pick(const QPointF &position) const {
    if (pickKind_=="vertex") {
        const auto points=model_.value("vertices").toArray();
        double closest=8,front=std::numeric_limits<double>::lowest();
        int nearest=-1;
        for (qsizetype index=0;index<points.size();++index) {
            if (points[index].toArray().size()!=3) continue;
            const auto point=vectorOf(points[index]);
            if (!vertexVisible(point)) continue;
            const double distance=QLineF(position,project(point)).length(),depth=rotation_.map(point-centre_).z();
            if (distance<closest-0.01 || (distance<8 && std::abs(distance-closest)<=0.01 && depth>front)) { nearest=int(index); closest=distance; front=depth; }
        }
        if (nearest>=0) return {{"vertices",QJsonArray{nearest}},{"edges",QJsonArray{}},{"faces",QJsonArray{}}};
    }
    const auto segments = model_.value("segments").toArray(), edgeNumbers = model_.value("segment_edge").toArray();
    const auto edges = model_.value("edges").toArray();
    double closest = 6;
    int nearest = -1;
    for (qsizetype index = 0; index < segments.size(); ++index) {
        const auto pair = segments[index].toArray(); if (pair.size() < 2) continue;
        const int edge = element(edgeNumbers,index).toInt(-1);
        if (hidden_.contains(topology(edges,edge).value("feature").toString())) continue;
        const auto distance = segmentDistance(position, project(vectorOf(pair[0])), project(vectorOf(pair[1])));
        if (distance < closest) { nearest = edge; closest = distance; }
    }
    if (nearest >= 0) return {{"edges", QJsonArray{nearest}}, {"faces", QJsonArray{}}, {"feature", topology(edges,nearest).value("feature")}};
    for (auto iterator = triangles_.crbegin(); iterator != triangles_.crend(); ++iterator)
        if (iterator->polygon.containsPoint(position, Qt::OddEvenFill)) return {{"faces", QJsonArray{iterator->face}}, {"edges", QJsonArray{}}, {"feature", iterator->feature}};
    const auto sketches = model_.value("sketches").toObject();
    for (auto iterator = sketches.begin(); iterator != sketches.end(); ++iterator) {
        if (hidden_.contains(iterator.key())) continue;
        const auto lines = iterator.value().toArray();
        for (const auto &segment : lines) {
            const auto pair = segment.toArray();
            if (pair.size() >= 2 && pair.first().isArray() && segmentDistance(position, project(vectorOf(pair[0])), project(vectorOf(pair[1]))) < 7)
                return {{"feature", iterator.key()}, {"faces", QJsonArray{}}, {"edges", QJsonArray{}}};
        }
    }
    if (planesVisible_) {
        const QStringList names{"XY","XZ","YZ"};
        for (int index = names.size()-1; index >= 0; --index) {
            if (!planeVisible(names[index])) continue;
            QPolygonF polygon; for (const auto &point : planeCorners(names[index])) polygon << project(point);
            if (polygon.containsPoint(position,Qt::OddEvenFill)) return {{"plane",names[index]},{"faces",QJsonArray{}},{"edges",QJsonArray{}}};
        }
    }
    return {{"faces", QJsonArray{}}, {"edges", QJsonArray{}}};
}
void Viewport::mousePressEvent(QMouseEvent *event) {
    press_ = last_ = cursor_ = event->position(); pressed_ = true; button_ = event->button();
    orbit_ = button_ == Qt::MiddleButton || (button_ == Qt::LeftButton && event->modifiers().testFlag(Qt::AltModifier));
    panning_ = orbit_ && (event->modifiers() & (Qt::ControlModifier | Qt::ShiftModifier));
    if (sketch_ && orbit_) panning_ = true;
    boxing_ = false; movingShape_ = false;
    if (zoomArmed_ && button_==Qt::LeftButton) { orbit_=panning_=false; event->accept(); return; }
    if (zoomArmed_ && button_==Qt::RightButton) { zoomArmed_=pressed_=orbit_=panning_=false; Q_EMIT bandChanged(); Q_EMIT displayChanged(); event->accept(); return; }
    if (sketch_ && !orbit_ && button_ == Qt::LeftButton) {
        const auto normal=domain::frame(plane_,sketchOffset_).normal; const auto direction=rotation_.inverted().mapVector(QVector3D(0,0,-1));
        if (std::abs(QVector3D::dotProduct(normal,direction))<1e-6) { pressed_=false; Q_EMIT hoverChanged(QStringLiteral("当前视线与草图平面平行；请先切换视角。")); event->accept(); return; }
        const auto point = sketchPoint(press_);
        if (editor_) { editor_->press(QVector2D(point),7/std::max(0.001,scale_),event->modifiers().testFlag(Qt::ControlModifier)); if (!quickSnap_.isEmpty()) { quickSnap_.clear(); Q_EMIT quickSnapConsumed(); } event->accept(); return; }
        if (tool_ == "select") {
            selectedShape_ = hitShape(press_); movingShape_ = selectedShape_ >= 0;
            dragShapes_ = shapes_; dragStart_ = point;
            Q_EMIT sketchSelectionChanged(selectedShape_); update();
        } else if (!draft_) { draft_ = true; draftStart_ = point; update(); }
        else if (QLineF(draftStart_, point).length() > 1e-6) {
            auto shape = draftShape(point);
            if (shape.value("type").toString() != "rect" || (shape.value("w").toDouble() > 1e-6 && shape.value("h").toDouble() > 1e-6)) {
                shapes_.append(shape); selectedShape_ = shapes_.size() - 1;
                Q_EMIT sketchEdited(shapes_); Q_EMIT sketchSelectionChanged(selectedShape_);
            }
            draft_ = tool_ == "line"; draftStart_ = point; update();
        }
    }
    event->accept();
}
void Viewport::mouseMoveEvent(QMouseEvent *event) {
    cursor_ = event->position();
    if (zoomArmed_ && !orbit_) { if (pressed_ && button_==Qt::LeftButton) { boxing_=QLineF(press_,cursor_).length()>5; Q_EMIT bandChanged(); } last_=cursor_; event->accept(); return; }
    if (sketch_ && editor_ && !orbit_) {
        const auto point=sketchPoint(cursor_); if (!editor_->dragging() || QLineF(press_,cursor_).length()>=4) editor_->move(QVector2D(point));
        if (pressed_ && button_==Qt::LeftButton && editor_->tool()=="select" && !editor_->dragging() && QLineF(press_,cursor_).length()>5) { boxing_=true; Q_EMIT bandChanged(); }
        last_=cursor_; event->accept(); return;
    }
    if (pressed_ && orbit_) {
        const auto delta = cursor_ - last_;
        if (panning_) pan_ += delta;
        else { yaw_ += delta.x() * 0.5; pitch_ += delta.y() * 0.5; }
        updateRotation();
    } else if (pressed_ && movingShape_ && selectedShape_ >= 0) {
        const auto delta = sketchPoint(cursor_) - dragStart_;
        auto shape = dragShapes_[selectedShape_].toObject();
        for (const auto &key : {QString("x1"),QString("x2"),QString("cx"),QString("x")}) if (shape.contains(key)) shape[key] = shape.value(key).toDouble() + delta.x();
        for (const auto &key : {QString("y1"),QString("y2"),QString("cy"),QString("y")}) if (shape.contains(key)) shape[key] = shape.value(key).toDouble() + delta.y();
        if (shape.contains("points")) {
            QJsonArray points; for (const auto &value : shape.value("points").toArray()) { auto pair = value.toArray(); points.append(QJsonArray{element(pair,0).toDouble() + delta.x(), element(pair,1).toDouble() + delta.y()}); }
            shape["points"] = points;
        }
        shapes_[selectedShape_] = shape; update();
    } else if (pressed_ && !sketch_ && button_ == Qt::LeftButton && QLineF(press_, cursor_).length() > 5) { boxing_ = true; Q_EMIT bandChanged(); }
    else if (draft_) update();
    last_ = cursor_; event->accept();
}
void Viewport::mouseReleaseEvent(QMouseEvent *event) {
    if (!pressed_) { event->accept(); return; }
    cursor_ = event->position();
    if (zoomArmed_ && button_==Qt::LeftButton) {
        const QRectF rectangle=QRectF(press_,cursor_).normalized();
        if (boxing_ && rectangle.width()>1 && rectangle.height()>1) {
            const double next=std::clamp(scale_*std::min(width()/rectangle.width(),height()/rectangle.height()),0.001,10000.0);
            pan_=(QPointF(width()/2,height()/2)+pan_-rectangle.center())*(next/scale_); scale_=next;
            update(); Q_EMIT cameraChanged();
        }
        zoomArmed_=pressed_=orbit_=panning_=boxing_=movingShape_=false;
        Q_EMIT bandChanged(); Q_EMIT displayChanged(); event->accept(); return;
    }
    if (sketch_ && editor_ && !orbit_) {
        const auto point=sketchPoint(cursor_);
        if (boxing_) editor_->box(QVector2D(sketchPoint(press_,false)),QVector2D(sketchPoint(cursor_,false)),bandCrossing(),event->modifiers().testFlag(Qt::ControlModifier));
        else if (button_==Qt::LeftButton) { if (editor_->dragging() && QLineF(press_,cursor_).length()<4) editor_->escape(); else editor_->release(QVector2D(point)); }
        else if (button_==Qt::RightButton) { if (editor_->drafting() && QStringList{"spline","sspline","polygon"}.contains(editor_->tool())) editor_->finishDraft(); else editor_->escape(); }
        pressed_=orbit_=panning_=boxing_=movingShape_=false; Q_EMIT bandChanged(); event->accept(); return;
    }
    if (movingShape_ && shapes_ != dragShapes_) Q_EMIT sketchEdited(shapes_);
    if (boxing_) {
        const QRectF rectangle = QRectF(press_, cursor_).normalized();
        QJsonArray faces;
        for (const auto &triangle : triangles_) {
            const bool hit = bandCrossing() ? rectangle.intersects(triangle.polygon.boundingRect()) : rectangle.contains(triangle.polygon.boundingRect());
            if (hit && triangle.face >= 0 && !faces.contains(triangle.face)) faces.append(triangle.face);
        }
        Q_EMIT boxed(faces, event->modifiers().testFlag(Qt::ControlModifier));
    } else if (!orbit_ && !sketch_ && button_ == Qt::LeftButton) {
        auto selection = pick(cursor_);
        if (!pickKind_.isEmpty()) selection["pick_position"]=QJsonArray{cursor_.x(),cursor_.y()};
        Q_EMIT picked(selection, event->modifiers().testFlag(Qt::ControlModifier));
        Q_EMIT contextPicked(selection,cursor_.x(),cursor_.y());
    }
    else if (button_ == Qt::RightButton && QLineF(press_, cursor_).length() < 6) {
        if (sketch_) { cancelDraft(); tool_ = "select"; }
        else Q_EMIT menuRequested(pick(cursor_).value("feature").toString(), cursor_.x(), cursor_.y());
    }
    pressed_ = orbit_ = panning_ = boxing_ = movingShape_ = false;
    Q_EMIT bandChanged(); event->accept();
}
void Viewport::mouseDoubleClickEvent(QMouseEvent *event) { if (zoomArmed_) { event->accept(); return; } if (!sketch_) { const auto selection = pick(event->position()); if (!selection.isEmpty()) Q_EMIT doublePicked(selection); else fit(); } else if (editor_) editor_->finishDraft(event->modifiers().testFlag(Qt::ShiftModifier)); event->accept(); }
void Viewport::wheelEvent(QWheelEvent *event) {
    const double factor = std::pow(1.0015, event->angleDelta().y());
    const auto anchor = event->position() - QPointF(width()/2, height()/2);
    const double next = std::clamp(scale_ * factor, 0.001, 10000.0);
    pan_ = anchor + (pan_ - anchor) * (next / scale_); scale_ = next;
    update(); Q_EMIT cameraChanged(); event->accept();
}
void Viewport::hoverMoveEvent(QHoverEvent *event) {
    cursor_ = event->position();
    if (sketch_) {
        const auto point = sketchPoint(cursor_); Q_EMIT hoverChanged(QStringLiteral("X %1  Y %2 mm").arg(point.x(), 0, 'f', 2).arg(point.y(), 0, 'f', 2));
        if (editor_ && !zoomArmed_) editor_->move(QVector2D(point));
        if (draft_) update();
    } else {
        const auto selection = pick(cursor_);
        const auto plane = selection.value("plane").toString();
        if (plane != hoverPlane_) { hoverPlane_ = plane; update(); }
        Q_EMIT hoverChanged(!plane.isEmpty() ? plane + QStringLiteral(" 基准面") : selection.value("feature").toString());
    }
}
bool Viewport::saveImage(const QString &path) {
    if (width() <= 0 || height() <= 0) return false;
    QImage image(QSize(qCeil(width()), qCeil(height())), QImage::Format_ARGB32_Premultiplied);
    image.fill(dark_ ? QColor("#141517") : QColor("#f0f3f8"));
    QPainter painter(&image); paint(&painter); painter.end(); return image.save(path);
}

}
