#include "genform/view/sheet.hpp"
#include <QDate>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFont>
#include <QImage>
#include <QJsonDocument>
#include <QMouseEvent>
#include <QPageSize>
#include <QPainter>
#include <QPainterPath>
#include <QPdfWriter>
#include <QSaveFile>
#include <QSvgGenerator>
#include <QUrl>
#include <QVector3D>
#include <QWheelEvent>
#include <algorithm>
#include <cmath>

namespace {
QString localPath(const QString &text) { const QUrl url(text); return url.isLocalFile() ? url.toLocalFile() : text; }
QSizeF paperSize(const QString &name) {
    if (name == "A4") return {297, 210};
    if (name == "A2") return {594, 420};
    if (name == "A1") return {841, 594};
    return {420, 297};
}
QPointF pointOf(const QJsonValue &value) { const auto pair = value.toArray(); return pair.size() >= 2 ? QPointF(pair[0].toDouble(), pair[1].toDouble()) : QPointF(); }
QJsonArray pairOf(const QPointF &point) { return {point.x(), point.y()}; }
QString number(double value) { return QString::number(value, 'g', 5); }
constexpr double drawingScales[]{10,5,2,1,0.5,0.2,0.1,0.05,0.02,0.01,0.005,0.002,0.001};
struct GridPlacement { QPointF centre; double scale; };
struct GridLayout { QMap<QString,GridPlacement> views; bool fits; };
GridLayout drawingGrid(const QSizeF &paper,const QMap<QString,QRectF> &bounds,double scale) {
    const auto extent=[&](const QStringList &names,bool horizontal) {
        double largest=0;
        for (const auto &name : names) if (bounds.contains(name))
            largest=std::max(largest,(horizontal ? bounds[name].width() : bounds[name].height())*scale);
        return largest;
    };
    double column0=extent({"front","top"},true),row0=extent({"front","left"},false);
    double column1=extent({"left"},true),row1=extent({"top"},false);
    if (bounds.contains("iso")) { column1=std::max(column1,70.0); row1=std::max(row1,87.0); }
    if (column0==0) { column0=column1; column1=0; }
    if (row0==0) { row0=row1; row1=0; }
    const QSizeF total(column0+(column1!=0 ? 34+column1 : 0),row0+(row1!=0 ? 34+row1 : 0));
    const double left=(paper.width()-total.width())/2+6,top=(paper.height()-total.height())/2;
    const double columnCentre0=left+column0/2,columnCentre1=column1!=0 ? left+column0+34+column1/2 : columnCentre0;
    const double rowCentre0=top+row0/2,rowCentre1=row1!=0 ? top+row0+34+row1/2 : rowCentre0;
    GridLayout result{{},total.width()<=paper.width()-56 && total.height()<=paper.height()-50};
    if (bounds.contains("front")) result.views["front"]={{columnCentre0,rowCentre0},scale};
    if (bounds.contains("top")) result.views["top"]={{columnCentre0,rowCentre1},scale};
    if (bounds.contains("left")) result.views["left"]={{columnCentre1,rowCentre0},scale};
    if (bounds.contains("iso")) {
        const auto box=bounds["iso"];
        const double cellWidth=column1!=0 ? std::max(column1,70.0) : column0;
        const double cellHeight=(row1!=0 ? row1 : row0)-(row1!=0 ? 32 : 0);
        const double own=std::min({scale,cellWidth/std::max(box.width(),1e-9),std::max(cellHeight,30.0)/std::max(box.height(),1e-9)});
        result.views["iso"]={{column1!=0 ? columnCentre1 : columnCentre0,row1!=0 ? rowCentre1-16 : rowCentre0},own};
    }
    return result;
}
bool finiteNumber(const QJsonValue &value) { return value.isDouble() && std::isfinite(value.toDouble()); }
bool validPoint(const QJsonValue &value) {
    const auto point = value.toArray();
    return point.size() == 2 && finiteNumber(point[0]) && finiteNumber(point[1]);
}
bool validDimension(const QJsonObject &dimension) {
    const auto kind = dimension.value("kind").toString();
    const auto view = dimension.value("view").toString();
    if (view.isEmpty() && dimension.contains("page_a"))
        return kind == "linear" && validPoint(dimension.value("page_a")) && validPoint(dimension.value("page_b")) && validPoint(dimension.value("page_at"))
               && (!dimension.contains("value") || finiteNumber(dimension.value("value")));
    if (!QStringList{"front", "top", "left", "iso"}.contains(view)) return false;
    if (kind == "linear")
        return validPoint(dimension.value("a")) && validPoint(dimension.value("b")) && finiteNumber(dimension.value("at"))
               && QStringList{"h", "v", "a"}.contains(dimension.value("mode").toString());
    return kind == "round" && validPoint(dimension.value("c")) && validPoint(dimension.value("at"))
           && finiteNumber(dimension.value("r")) && dimension.value("r").toDouble() > 0;
}
QPointF toPage(const QJsonObject &placement, const QPointF &point) {
    const auto centre = pointOf(placement.value("centre")), origin = pointOf(placement.value("origin"));
    return centre + (QPointF(point.x(), -point.y()) - origin) * placement.value("scale").toDouble();
}
QPointF toView(const QJsonObject &placement, const QPointF &point) {
    const auto projected = pointOf(placement.value("origin")) + (point - pointOf(placement.value("centre"))) / placement.value("scale").toDouble();
    return {projected.x(), -projected.y()};
}
}

namespace genform::view {
SheetView::SheetView(QQuickItem *parent) : QQuickPaintedItem(parent) {
    setAcceptedMouseButtons(Qt::AllButtons); setAntialiasing(true);
    connect(this, &QQuickItem::widthChanged, this, &SheetView::fit);
    connect(this, &QQuickItem::heightChanged, this, &SheetView::fit);
}
void SheetView::setDark(bool value) { dark_ = value; update(); Q_EMIT changed(); }
void SheetView::setSheet(const QJsonObject &value) { const bool initial = sheet_.isEmpty(); sheet_ = value; if (initial) fit(); update(); }
void SheetView::fit() {
    const auto size = paperSize(sheet_.value("paper").toString("A3"));
    zoom_ = std::max(0.01, std::min((width() - 50) / size.width(), (height() - 50) / size.height())); pan_ = {}; update();
}
QPointF SheetView::pagePoint(const QPointF &point) const {
    const auto size = paperSize(sheet_.value("paper").toString("A3"));
    return (point - QPointF((width() - size.width()*zoom_)/2, (height()-size.height()*zoom_)/2) - pan_) / zoom_;
}
void SheetView::paint(QPainter *painter) {
    const auto size = paperSize(sheet_.value("paper").toString("A3"));
    painter->save(); painter->translate((width()-size.width()*zoom_)/2 + pan_.x(), (height()-size.height()*zoom_)/2 + pan_.y());
    painter->scale(zoom_, zoom_); paintPage(painter); painter->restore();
}
void SheetView::paintPage(QPainter *painter) const {
    const auto size = paperSize(sheet_.value("paper").toString("A3"));
    painter->setRenderHint(QPainter::Antialiasing); painter->fillRect(QRectF(QPointF(), size), Qt::white);
    painter->setPen(QPen(QColor("#17171b"), 0.5)); painter->setBrush(Qt::NoBrush);
    painter->drawRect(QRectF(10, 10, size.width()-20, size.height()-20));
    for (const auto &value : sheet_.value("lines").toArray()) {
        const auto line = value.toObject();
        QPen pen(line.value("selected").toBool() ? QColor("#207be5") : QColor("#202026"), line.value("style").toString() == "hidden" ? 0.18 : 0.35);
        if (line.value("style").toString() == "hidden") pen.setStyle(Qt::DashLine);
        painter->setPen(pen); QPolygonF polygon;
        for (const auto &point : line.value("points").toArray()) polygon << pointOf(point);
        painter->drawPolyline(polygon);
    }
    const double titleWidth = 140, titleHeight = 32;
    const QRectF title(size.width()-10-titleWidth, size.height()-10-titleHeight, titleWidth, titleHeight);
    painter->setPen(QPen(QColor("#17171b"), 0.35)); painter->drawRect(title);
    painter->drawLine(title.left(), title.top()+12, title.right(), title.top()+12);
    painter->drawLine(title.left(), title.top()+22, title.right(), title.top()+22);
    QFont font(QStringLiteral("Microsoft YaHei UI")); font.setPointSizeF(3.2); painter->setFont(font);
    const auto fields = sheet_.value("title").toObject();
    painter->drawText(title.adjusted(3,1,-3,-20), Qt::AlignVCenter | Qt::AlignLeft, fields.value("name").toString());
    painter->drawText(QRectF(title.left()+3,title.top()+12,titleWidth-6,10), Qt::AlignVCenter, QStringLiteral("图号 %1    材料 %2").arg(fields.value("number").toString(), fields.value("material").toString()));
    painter->drawText(QRectF(title.left()+3,title.top()+22,titleWidth-6,10), Qt::AlignVCenter,
                      QStringLiteral("设计 %1   %2   %3").arg(fields.value("designer").toString(), fields.value("date").toString(), sheet_.value("scaleText").toString()));
    for (const auto &value : sheet_.value("texts").toArray()) {
        const auto text = value.toObject();
        font.setPointSizeF(text.value("size").toDouble(3)); painter->setFont(font);
        painter->setPen(QColor(text.value("selected").toBool() ? "#207be5" : "#202026"));
        painter->drawText(QPointF(text.value("x").toDouble(), text.value("y").toDouble()), text.value("text").toString());
    }
}
void SheetView::mousePressEvent(QMouseEvent *event) {
    last_ = event->position(); panning_ = event->button() != Qt::LeftButton || event->modifiers().testFlag(Qt::AltModifier);
    if (!panning_) { const auto point = pagePoint(last_); Q_EMIT pressed(point.x(), point.y()); }
    event->accept();
}
void SheetView::mouseMoveEvent(QMouseEvent *event) {
    if (panning_) { pan_ += event->position() - last_; update(); }
    else { const auto point = pagePoint(event->position()); Q_EMIT moved(point.x(), point.y()); }
    last_ = event->position(); event->accept();
}
void SheetView::mouseReleaseEvent(QMouseEvent *event) {
    if (!panning_) { const auto point = pagePoint(event->position()); Q_EMIT released(point.x(), point.y()); }
    panning_ = false; event->accept();
}
void SheetView::wheelEvent(QWheelEvent *event) {
    const auto before = pagePoint(event->position()); zoom_ = std::clamp(zoom_ * std::pow(1.0015, event->angleDelta().y()), 0.05, 100.0);
    const auto after = pagePoint(event->position()); pan_ += (after - before) * zoom_; update(); event->accept();
}
}

namespace genform::controller {
DrawingBridge::DrawingBridge(Session *session, QObject *parent) : QObject(parent), session_(session) { begin(); }
void DrawingBridge::attach(view::SheetView *view) {
    view_ = view; if (!view_) return;
    connect(view_, &view::SheetView::pressed, this, &DrawingBridge::mousePress);
    connect(view_, &view::SheetView::moved, this, &DrawingBridge::mouseMove);
    connect(view_, &view::SheetView::released, this, &DrawingBridge::mouseRelease);
    refresh();
}
void DrawingBridge::begin() {
    data_ = {{"sheet","A3"},{"scale",0},{"views",QJsonArray{"front","top","left","iso"}}, {"offsets",QJsonObject{}},
             {"hidden",false},{"auto",false},{"centers",false},{"title", QJsonObject{{"name",QFileInfo(session_->document.path).completeBaseName()}, {"date",QDate::currentDate().toString(Qt::ISODate)}}}};
    path_.clear(); source_ = session_->document.path; error_.clear(); projection_ = {}; dimensions_ = {}; dirty_ = false;
    useTool("select"); selectedDimension_ = -1;
    refresh();
}
QVariantMap DrawingBridge::state() const {
    QVariantList papers, scales, views, title;
    for (const auto &name : {QString("A4"),QString("A3"),QString("A2"),QString("A1")}) papers.append(name);
    scales.append(QVariantMap{{"id","auto"},{"title",QStringLiteral("自动")}});
    for (const double scale : drawingScales) scales.append(QVariantMap{{"id",number(scale)}, {"title",scale >= 1 ? number(scale)+":1" : "1:"+number(1/scale)}});
    for (const auto &name : {QString("front"),QString("top"),QString("left"),QString("iso")}) views.append(QVariantMap{{"id",name},{"title",name},{"on",data_.value("views").toArray().contains(name)}});
    const auto fields = data_.value("title").toObject();
    const QStringList labels{QStringLiteral("名称"),QStringLiteral("图号"),QStringLiteral("材料"),QStringLiteral("设计"),QStringLiteral("日期")};
    const QStringList names{"name","number","material","designer","date"};
    for (int index=0; index<names.size(); ++index) title.append(QVariantMap{{"id",names[index]},{"label",labels[index]},{"value",fields.value(names[index]).toString()}});
    QVariantList notes{QStringLiteral("原生三角网格工程投影；非精确 BRep 隐线消除。")};
    for (const auto &warning : dimensionWarnings_) notes.append(warning);
    return {{"running",running_},{"error",error_},{"hint",tool_ == "linear" ? QStringLiteral("依次点击同一视图的边线端点，再点击放置位置") : QStringLiteral("拖动视图调整布局，滚轮缩放，中键平移")},
            {"part",source_},{"source",source_},{"ready",!projection_.isEmpty()},
            {"size",QStringLiteral("%1 × %2 mm").arg(paperSize(data_.value("sheet").toString()).width()).arg(paperSize(data_.value("sheet").toString()).height())},
            {"partName",QFileInfo(source_).fileName()},{"sheet",data_.value("sheet").toString()},{"sheets",papers},
            {"scale",data_.value("scale").toDouble() == 0 ? "auto" : number(data_.value("scale").toDouble())},{"scales",scales},
            {"scaleText",sheet_.value("scaleText").toString()},{"scaleChoice",data_.value("scale").toDouble() == 0 ? "auto" : number(data_.value("scale").toDouble())},
            {"views",views},{"title",title},{"tool",tool_=="linear" ? "dimension" : tool_},{"selected",selectedDimension_>=0},
            {"hidden",data_.value("hidden").toBool()},{"auto",data_.value("auto").toBool()},{"centers",data_.value("centers").toBool()},
            {"moved",!data_.value("offsets").toObject().isEmpty()},{"notes",notes}};
}
void DrawingBridge::setPart(const QString &path) { source_ = localPath(path); project(); dirty_ = true; Q_EMIT changed(); }
void DrawingBridge::project() {
    running_ = true; error_.clear(); projection_ = {}; Q_EMIT changed();
    try {
        QJsonObject model = session_->model;
        if (!source_.isEmpty() && QFileInfo(source_).absoluteFilePath() != QFileInfo(session_->document.path).absoluteFilePath()) {
            Document part; const auto suffix=QFileInfo(source_).suffix().toLower();
            if (suffix=="step" || suffix=="stp") part.add("import_step",{{"path",QFileInfo(source_).absoluteFilePath()}});
            else if (suffix=="gform") part.open(source_);
            else throw Error(QStringLiteral("工程图零件必须是 .gform / .step / .stp。"));
            kernel::Kernel builder; model = builder.build(part.features, part.upto);
        }
        if (!model.value("has_body").toBool()) throw Error(QStringLiteral("没有可投影实体；请先创建或打开有效零件。"));
        const auto segments = model.value("segments").toArray();
        if (segments.isEmpty()) throw Error(QStringLiteral("内核没有返回工程投影需要的边线。"));
        projection_ = {};
        for (const auto &name : {QString("front"),QString("top"),QString("left"),QString("iso")}) {
            QJsonArray lines;
            for (const auto &value : segments) {
                QJsonArray projected;
                for (const auto &point : value.toArray()) {
                    const auto coordinates = point.toArray(); if (coordinates.size() < 3) continue;
                    const double horizontal=coordinates[0].toDouble(), depth=coordinates[1].toDouble(), vertical=coordinates[2].toDouble();
                    QPointF result;
                    if (name == "front") result = {horizontal,-vertical};
                    else if (name == "top") result = {horizontal,-depth};
                    else if (name == "left") result = {-depth,-vertical};
                    else result = {(horizontal+depth)*std::sqrt(0.5), (horizontal-depth)/std::sqrt(6.0)-vertical*std::sqrt(2.0/3.0)};
                    projected.append(pairOf(result));
                }
                if (projected.size() >= 2) lines.append(projected);
            }
            projection_[name] = lines;
        }
    } catch (const std::exception &exception) { error_ = QString::fromUtf8(exception.what()); Q_EMIT notice(error_); }
    running_ = false; refresh(); fit();
}
void DrawingBridge::refresh(bool touch) {
    if (touch) dirty_ = true;
    dimensionHandles_.clear(); dimensionWarnings_.clear();
    QJsonArray lines, texts, placements;
    QMap<QString, QJsonObject> placed;
    const auto size = paperSize(data_.value("sheet").toString("A3"));
    const auto visible = data_.value("views").toArray(); const auto offsets = data_.value("offsets").toObject();
    double scale = data_.value("scale").toDouble();
    QMap<QString,QRectF> bounds;
    for (auto iterator=projection_.begin(); iterator!=projection_.end(); ++iterator) {
        if (!visible.contains(iterator.key())) continue;
        double minX=1e100,minY=1e100,maxX=-1e100,maxY=-1e100;
        for (const auto &line : iterator.value().toArray()) for (const auto &value : line.toArray()) {
            const auto point=pointOf(value); minX=std::min(minX,point.x()); maxX=std::max(maxX,point.x()); minY=std::min(minY,point.y()); maxY=std::max(maxY,point.y());
        }
        if (minX <= maxX) bounds[iterator.key()] = QRectF(minX,minY,maxX-minX,maxY-minY);
    }
    GridLayout layout;
    if (bounds.isEmpty()) scale=1;
    else if (scale>0) layout=drawingGrid(size,bounds,scale);
    else for (const double candidate : drawingScales) {
        scale=candidate; layout=drawingGrid(size,bounds,scale);
        if (layout.fits) break;
    }
    const QStringList ordered{"front","top","left","iso"};
    for (const auto &name : ordered) {
        if (!layout.views.contains(name)) continue;
        const auto grid=layout.views.value(name);
        const auto centre=grid.centre; const double own=grid.scale;
        const auto offset=pointOf(offsets.value(name)); const auto box=bounds[name];
        const auto transform=[&](const QPointF &point) { return centre+offset+(point-box.center())*own; };
        const auto pageBox=QRectF(transform(box.topLeft()),transform(box.bottomRight())).normalized();
        const QJsonObject placement{{"name",name},{"x",pageBox.x()},{"y",pageBox.y()},{"w",pageBox.width()},{"h",pageBox.height()},
                                    {"centre",pairOf(centre+offset)},{"origin",pairOf(box.center())},{"scale",own}};
        placed[name]=placement; placements.append(placement);
        for (const auto &value : projection_.value(name).toArray()) {
            QJsonArray points; for (const auto &point : value.toArray()) points.append(pairOf(transform(pointOf(point))));
            lines.append(QJsonObject{{"style","visible"},{"points",points}});
        }
        texts.append(QJsonObject{{"x",pageBox.left()},{"y",pageBox.bottom()+7},{"text",name},{"size",3.5}});
        if (data_.value("auto").toBool()) {
            const double mark=pageBox.bottom()+12;
            lines.append(QJsonObject{{"points",QJsonArray{QJsonArray{pageBox.left(),mark},QJsonArray{pageBox.right(),mark}}}});
            texts.append(QJsonObject{{"x",pageBox.center().x()},{"y",mark-2},{"text",number(box.width())},{"size",3}});
            texts.append(QJsonObject{{"x",pageBox.right()+4},{"y",pageBox.center().y()},{"text",number(box.height())},{"size",3}});
        }
    }
    for (qsizetype index=0;index<dimensions_.size();++index) {
        const auto dimension=dimensions_[index].toObject();
        const auto name=dimension.value("view").toString();
        if (!name.isEmpty() && !placed.contains(name)) {
            if (visible.contains(name)) dimensionWarnings_.append(QStringLiteral("尺寸 %1 的视图 %2 无可用投影；尺寸数据已保留。").arg(index+1).arg(name));
            continue;
        }
        const bool selected=index==selectedDimension_;
        const auto appendLine=[&](const QPointF &start,const QPointF &end) {
            lines.append(QJsonObject{{"selected",selected},{"points",QJsonArray{pairOf(start),pairOf(end)}}});
        };
        const auto appendArrow=[&](const QPointF &tip,const QPointF &direction) {
            const double length=std::hypot(direction.x(),direction.y());
            if (length<=1e-9) return;
            const auto unit=direction/length, normal=QPointF(-unit.y(),unit.x());
            appendLine(tip,tip+unit*2.5+normal*0.8); appendLine(tip,tip+unit*2.5-normal*0.8);
        };
        const auto appendText=[&](const QPointF &position,const QString &text) {
            texts.append(QJsonObject{{"selected",selected},{"x",position.x()},{"y",position.y()},{"text",text},{"size",3.5}});
            dimensionHandles_[index]=position;
        };
        const auto placement=placed.value(name);
        const double own=placement.value("scale").toDouble(scale);
        if (dimension.value("kind").toString()=="round") {
            const auto centre=toPage(placement,pointOf(dimension.value("c")));
            auto position=toPage(placement,pointOf(dimension.value("at")));
            auto direction=position-centre;
            const double reach=std::hypot(direction.x(),direction.y());
            direction=reach>1e-9 ? direction/reach : QPointF(1,0);
            const double radius=dimension.value("r").toDouble()*own;
            const auto edge=centre+direction*radius;
            if (reach<radius+5) position=centre+direction*(radius+8);
            const bool full=dimension.value("full").toBool(true);
            const auto text=(full ? QString::fromUtf8("Ø") : QString("R"))+number(dimension.value("r").toDouble()*(full ? 2 : 1));
            const auto shelf=position+QPointF((direction.x()>=0 ? 1 : -1)*(text.size()*3.5*0.72+2),0);
            appendLine(edge,position); appendLine(position,shelf); appendArrow(edge,direction);
            appendText((position+shelf)/2-QPointF(0,1.2),text);
            continue;
        }
        QPointF first,second,endA,endB,position;
        double length=0;
        bool vertical=false;
        if (name.isEmpty()) {
            first=pointOf(dimension.value("page_a")); second=pointOf(dimension.value("page_b")); position=pointOf(dimension.value("page_at"));
            vertical=dimension.value("vertical").toBool();
            endA=vertical ? QPointF(position.x(),first.y()) : QPointF(first.x(),position.y());
            endB=vertical ? QPointF(position.x(),second.y()) : QPointF(second.x(),position.y());
            length=dimension.value("value").toDouble((vertical ? std::abs(second.y()-first.y()) : std::abs(second.x()-first.x()))/scale);
            dimensionWarnings_.append(QStringLiteral("尺寸 %1 仅有旧原生纸面坐标，无视图归属；保持原位置与数值，请重建以关联视图。").arg(index+1));
        } else {
            const auto firstLocal=pointOf(dimension.value("a")),secondLocal=pointOf(dimension.value("b"));
            first=toPage(placement,firstLocal); second=toPage(placement,secondLocal);
            const auto mode=dimension.value("mode").toString();
            const double at=dimension.value("at").toDouble();
            vertical=mode=="v";
            if (mode=="h") {
                const double level=toPage(placement,QPointF(0,at)).y();
                endA={first.x(),level}; endB={second.x(),level}; length=std::abs(secondLocal.x()-firstLocal.x());
            } else if (vertical) {
                const double level=toPage(placement,QPointF(at,0)).x();
                endA={level,first.y()}; endB={level,second.y()}; length=std::abs(secondLocal.y()-firstLocal.y());
            } else {
                const auto along=second-first;
                const double span=std::hypot(along.x(),along.y());
                const auto offset=span>1e-9 ? QPointF(-along.y(),along.x())*(at*own/span) : QPointF();
                endA=first+offset; endB=second+offset; length=QLineF(firstLocal,secondLocal).length();
            }
        }
        for (const auto &pair : {QPair<QPointF,QPointF>{first,endA}, {second,endB}, {endA,endB}})
            appendLine(pair.first,pair.second);
        appendArrow(endA,endB-endA); appendArrow(endB,endA-endB);
        appendText((endA+endB)/2+(vertical ? QPointF(2,0) : QPointF(0,-2)),number(length));
    }
    sheet_={{"paper",data_.value("sheet")},{"lines",lines},{"texts",texts},{"placements",placements},{"title",data_.value("title")},
            {"scale",scale},{"scaleText",scale>=1 ? number(scale)+":1" : "1:"+number(1/scale)}};
    if (view_) view_->setSheet(sheet_);
    Q_EMIT changed();
}
void DrawingBridge::fit() { if (view_) view_->fit(); }
void DrawingBridge::resetLayout() { data_["offsets"]=QJsonObject{}; refresh(true); }
void DrawingBridge::setScale(const QString &value) {
    bool valid=false; const double scale=value=="auto" ? 0 : value.toDouble(&valid);
    if (value!="auto" && (!valid || !std::isfinite(scale) || scale<=0)) { Q_EMIT notice(QStringLiteral("图纸比例必须大于零。")); return; }
    data_["scale"]=scale; refresh(true);
}
void DrawingBridge::setSheet(const QString &value) {
    if (!QStringList{"A4","A3","A2","A1"}.contains(value)) { Q_EMIT notice(QStringLiteral("不支持的图纸规格。")); return; }
    data_["sheet"]=value; refresh(true); fit();
}
void DrawingBridge::setTitle(const QString &key,const QString &value) { auto title=data_.value("title").toObject(); title[key]=value; data_["title"]=title; refresh(true); }
void DrawingBridge::toggle(const QString &key) {
    if (key=="hidden" || key=="centers") { Q_EMIT notice(QStringLiteral("软件网格投影尚不支持精确隐藏线或圆心提取。")); return; }
    if (key!="auto") { Q_EMIT notice(QStringLiteral("不支持的工程图选项：%1").arg(key)); return; }
    data_[key]=!data_.value(key).toBool(); refresh(true);
}
void DrawingBridge::toggleView(const QString &name) {
    if (!QStringList{"front","top","left","iso"}.contains(name)) { Q_EMIT notice(QStringLiteral("不支持的工程视图。")); return; }
    auto views=data_.value("views").toArray(); if (views.contains(name)) { for (qsizetype index=views.size()-1;index>=0;--index) if (views[index]==name) views.removeAt(index); }
    else views.append(name);
    data_["views"]=views; selectedDimension_=-1; useTool("select"); refresh(true);
}
void DrawingBridge::useTool(const QString &tool) {
    if (tool!="select" && tool!="linear" && tool!="dimension") { Q_EMIT notice(QStringLiteral("工程图工具尚未原生迁移：%1").arg(tool)); return; }
    tool_=tool=="dimension" ? "linear" : tool; dimensionStarted_=false; movingView_.clear(); dimensionView_.clear(); Q_EMIT changed();
}
void DrawingBridge::deleteSelected() { if (selectedDimension_>=0 && selectedDimension_<dimensions_.size()) { dimensions_.removeAt(selectedDimension_); selectedDimension_=-1; refresh(true); } else Q_EMIT notice(QStringLiteral("请先选中尺寸。")); }
bool DrawingBridge::snapPoint(const QPointF &page,QString &name,QPointF &point) const {
    double nearest=6;
    bool found=false;
    const auto requiredView=name;
    for (const auto &value : sheet_.value("placements").toArray()) {
        const auto placement=value.toObject();
        const auto candidate=placement.value("name").toString();
        if (!requiredView.isEmpty() && candidate!=requiredView) continue;
        for (const auto &lineValue : projection_.value(candidate).toArray()) {
            const auto line=lineValue.toArray();
            if (line.isEmpty()) continue;
            for (const auto &endpoint : {line.first(),line.last()}) {
                const auto projected=pointOf(endpoint);
                const QPointF local(projected.x(),-projected.y());
                const double distance=QLineF(page,toPage(placement,local)).length();
                if (distance<=nearest) { nearest=distance; name=candidate; point=local; found=true; }
            }
        }
    }
    return found;
}
void DrawingBridge::mousePress(double horizontal,double vertical) {
    press_={horizontal,vertical};
    if (tool_=="linear") {
        if (!dimensionStarted_ || movingView_=="dimension_first") {
            auto name=dimensionView_; QPointF point;
            if (!snapPoint(press_,name,point)) { Q_EMIT notice(QStringLiteral("请选择同一视图的边线端点。")); return; }
            if (!dimensionStarted_) { firstDimension_=point; dimensionView_=name; dimensionStarted_=true; movingView_="dimension_first"; }
            else if (QLineF(firstDimension_,point).length()>1e-9) { originalOffset_=point; movingView_="dimension_second"; }
        } else {
            for (const auto &value : sheet_.value("placements").toArray()) {
                const auto placement=value.toObject();
                if (placement.value("name").toString()!=dimensionView_) continue;
                const auto position=toView(placement,press_);
                const double beyondY=std::max({std::min(firstDimension_.y(),originalOffset_.y())-position.y(),position.y()-std::max(firstDimension_.y(),originalOffset_.y()),0.0});
                const double beyondX=std::max({std::min(firstDimension_.x(),originalOffset_.x())-position.x(),position.x()-std::max(firstDimension_.x(),originalOffset_.x()),0.0});
                const auto delta=originalOffset_-firstDimension_;
                QString mode="a";
                double at=(position.x()-firstDimension_.x())*delta.y()-(position.y()-firstDimension_.y())*delta.x();
                at/=std::hypot(delta.x(),delta.y());
                if ((beyondY>0 && beyondY>=beyondX && std::abs(delta.x())>1e-6) || std::abs(delta.y())<=1e-6) { mode="h"; at=position.y(); }
                else if (beyondX>0 || std::abs(delta.x())<=1e-6) { mode="v"; at=position.x(); }
                dimensions_.append(QJsonObject{{"view",dimensionView_},{"kind","linear"},{"mode",mode},{"a",pairOf(firstDimension_)},{"b",pairOf(originalOffset_)},{"at",at}});
                break;
            }
            dimensionStarted_=false; movingView_.clear(); dimensionView_.clear(); refresh(true);
        }
        return;
    }
    selectedDimension_=-1; movingView_.clear();
    double nearest=10;
    for (auto handle=dimensionHandles_.cbegin();handle!=dimensionHandles_.cend();++handle) {
        const double distance=QLineF(press_,handle.value()).length();
        if (distance<nearest) { selectedDimension_=handle.key(); nearest=distance; }
    }
    if (selectedDimension_>=0) { refresh(); return; }
    for (const auto &value : sheet_.value("placements").toArray()) {
        const auto placement=value.toObject();
        if (QRectF(placement.value("x").toDouble()-4,placement.value("y").toDouble()-4,placement.value("w").toDouble()+8,placement.value("h").toDouble()+8).contains(press_)) {
            movingView_=placement.value("name").toString(); originalOffset_=pointOf(data_.value("offsets").toObject().value(movingView_)); break;
        }
    }
    refresh();
}
void DrawingBridge::mouseMove(double horizontal,double vertical) {
    if (tool_!="select" || movingView_.isEmpty()) return;
    auto offsets=data_.value("offsets").toObject(); offsets[movingView_]=pairOf(originalOffset_+QPointF(horizontal,vertical)-press_); data_["offsets"]=offsets; refresh(true);
}
void DrawingBridge::mouseRelease(double,double) { if (tool_=="select") movingView_.clear(); }
bool DrawingBridge::open(const QString &where) {
    try {
        const auto path=localPath(where); QFile file(path); if (!file.open(QIODevice::ReadOnly)) throw Error(file.errorString());
        QJsonParseError parse; const auto json=QJsonDocument::fromJson(file.readAll(),&parse);
        if (parse.error!=QJsonParseError::NoError || !json.isObject() || json.object().value("format").toString()!="genform-drawing") throw Error(QStringLiteral("不是有效的 GenForm 工程图。"));
        const auto loaded=json.object();
        if (!loaded.value("part").isString() || loaded.value("part").toString().isEmpty()) throw Error(QStringLiteral("工程图缺少零件路径；原文件保持不变。"));
        if (!QStringList{"A4","A3","A2","A1"}.contains(loaded.value("sheet").toString("A3"))) throw Error(QStringLiteral("不支持的图纸规格；原文件保持不变。"));
        if (loaded.contains("scale") && (!finiteNumber(loaded.value("scale")) || loaded.value("scale").toDouble()<0)) throw Error(QStringLiteral("图纸比例无效；原文件保持不变。"));
        if (loaded.contains("dimensions") && !loaded.value("dimensions").isArray()) throw Error(QStringLiteral("尺寸列表无效；拒绝忽略尺寸，原文件保持不变。"));
        const auto dimensions=loaded.value("dimensions").toArray();
        for (qsizetype index=0;index<dimensions.size();++index)
            if (!dimensions[index].isObject() || !validDimension(dimensions[index].toObject()))
                throw Error(QStringLiteral("尺寸 %1 的类型、视图或坐标无效/不受支持；拒绝忽略尺寸，原文件保持不变。").arg(index+1));
        data_=loaded; source_=QFileInfo(path).dir().absoluteFilePath(loaded.value("part").toString());
        dimensions_=dimensions; path_=path; dirty_=false; selectedDimension_=-1; useTool("select"); project(); return true;
    } catch (const std::exception &exception) { Q_EMIT notice(QString::fromUtf8(exception.what())); return false; }
}
bool DrawingBridge::save(const QString &where) {
    try {
        QString path=localPath(where); if (path.isEmpty()) path=path_; if (path.isEmpty()) throw Error(QStringLiteral("请指定工程图保存路径。"));
        if (!path.endsWith(".gdrw",Qt::CaseInsensitive)) path+=".gdrw";
        if (source_.isEmpty()) source_=session_->document.path;
        if (source_.isEmpty()) throw Error(QStringLiteral("请先保存零件，工程图需要引用零件文件。"));
        auto data=data_; data["format"]="genform-drawing"; data["version"]=1; data["part"]=QFileInfo(path).dir().relativeFilePath(source_); data["dimensions"]=dimensions_;
        QSaveFile file(path); if (!file.open(QIODevice::WriteOnly)) throw Error(file.errorString());
        if (file.write(QJsonDocument(data).toJson())<0 || !file.commit()) throw Error(file.errorString());
        path_=path; dirty_=false; Q_EMIT changed(); return true;
    } catch (const std::exception &exception) { Q_EMIT notice(QString::fromUtf8(exception.what())); return false; }
}
bool DrawingBridge::exportFile(const QString &where) {
    try {
        const auto path=localPath(where); const auto suffix=QFileInfo(path).suffix().toLower();
        if (!view_ || projection_.isEmpty()) throw Error(QStringLiteral("图纸上没有可导出的投影视图。"));
        const auto size=paperSize(data_.value("sheet").toString("A3"));
        if (suffix=="png") {
            QImage image(QSize(qRound(size.width()*6),qRound(size.height()*6)),QImage::Format_ARGB32_Premultiplied); image.fill(Qt::white);
            QPainter painter(&image); painter.scale(6,6); view_->paintPage(&painter); painter.end(); if (!image.save(path)) throw Error(QStringLiteral("PNG 写入失败。"));
        } else if (suffix=="svg") {
            QSvgGenerator generator; generator.setFileName(path); generator.setSize(QSize(qRound(size.width()*4),qRound(size.height()*4))); generator.setViewBox(QRectF(QPointF(),size));
            QPainter painter; if (!painter.begin(&generator)) throw Error(QStringLiteral("SVG 无法打开。")); view_->paintPage(&painter); painter.end();
        } else if (suffix=="pdf") {
            QPdfWriter writer(path); writer.setPageSize(QPageSize(size,QPageSize::Millimeter)); writer.setPageMargins(QMarginsF(0,0,0,0)); writer.setResolution(300);
            QPainter painter; if (!painter.begin(&writer)) throw Error(QStringLiteral("PDF 无法打开。")); painter.scale(300/25.4,300/25.4); view_->paintPage(&painter); painter.end();
        } else throw Error(QStringLiteral("原生工程图导出支持 PDF / SVG / PNG，暂不支持：%1").arg(suffix));
        return true;
    } catch (const std::exception &exception) { Q_EMIT notice(QString::fromUtf8(exception.what())); return false; }
}
}
