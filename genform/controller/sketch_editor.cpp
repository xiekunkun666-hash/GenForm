#include "genform/controller/sketch_editor.hpp"
#include "genform/domain/geometry.hpp"
#include <QJsonDocument>
#include <QLineF>
#include <QRectF>
#include <QtMath>
#include <algorithm>
#include <cmath>

namespace genform::controller {
namespace {
QJsonArray pair(const QVector2D &point) { return {point.x(),point.y()}; }
QJsonArray coordinates(const QVector<QVector2D> &points) { QJsonArray result; for (const auto &point : points) result.append(pair(point)); return result; }
double angle(const QVector2D &first,const QVector2D &second) { return qRadiansToDegrees(std::atan2(second.y()-first.y(),second.x()-first.x())); }
QJsonObject line(const QVector2D &first,const QVector2D &second,bool construction=false) {
    QJsonObject shape{{"type","line"},{"x1",first.x()},{"y1",first.y()},{"x2",second.x()},{"y2",second.y()}};
    if (construction) shape["construction"]=true;
    return shape;
}
QJsonObject parameter(const QString &key,const QJsonValue &value,const QString &type=QStringLiteral("number"),const QString &label={}) {
    const auto plain=key.startsWith("opt_")?key.mid(4):key;
    const QMap<QString,QString> names{{"nx",QStringLiteral("X 方向数量")},{"ny",QStringLiteral("Y 方向数量")},{"dx",QStringLiteral("X 间距")},{"dy",QStringLiteral("Y 间距")},{"count",QStringLiteral("数量")},{"factor",QStringLiteral("缩放系数")},{"copy",QStringLiteral("复制原图形")},
        {"cx",QStringLiteral("中心 X")},{"cy",QStringLiteral("中心 Y")},{"r",QStringLiteral("半径")},{"w",QStringLiteral("宽度")},{"h",QStringLiteral("高度")},{"rx",QStringLiteral("X 半轴")},{"ry",QStringLiteral("Y 半轴")},
        {"angle",QStringLiteral("角度")},{"a0",QStringLiteral("起始角")},{"a1",QStringLiteral("终止角")},{"sides",QStringLiteral("边数")},{"radius",QStringLiteral("圆角半径")},{"height",QStringLiteral("字高")},{"text",QStringLiteral("文字")},{"points",QStringLiteral("点列 JSON")},
        {"mode",QStringLiteral("方程模式")},{"fx","x(t)"},{"fy","y=f(x) / y(t)"},{"t0",QStringLiteral("起始参数")},{"t1",QStringLiteral("终止参数")},{"closed",QStringLiteral("闭合")},{"construction",QStringLiteral("构造几何")},{"style",QStringLiteral("样式样条")},{"value",QStringLiteral("尺寸")}};
    QString unit=type=="number"?"mm":"";
    if (QStringList{"angle","a0","a1"}.contains(plain)) unit="°";
    if (QStringList{"nx","ny","count","sides"}.contains(plain)) unit=QStringLiteral("个");
    if (QStringList{"factor","t0","t1"}.contains(plain)) unit.clear();
    return {{"key",key},{"label",label.isEmpty() || label==plain?names.value(plain,plain):label},{"type",type},{"value",value},{"unit",unit}};
}
QString relationTitle(const QString &kind) {
    const QMap<QString,QString> labels{{"horizontal",QStringLiteral("水平")},{"vertical",QStringLiteral("竖直")},{"parallel",QStringLiteral("平行")},
        {"perpendicular",QStringLiteral("垂直")},{"collinear",QStringLiteral("共线")},{"equal",QStringLiteral("相等")},{"concentric",QStringLiteral("同心")},
        {"tangent",QStringLiteral("相切")},{"coincident",QStringLiteral("重合")}};
    return labels.value(kind,kind);
}
QJsonObject scaled(const QJsonObject &source,const QVector2D &centre,double factor) {
    QJsonObject shape=source; const auto type=source.value("type").toString();
    if (type=="equation") {
        QJsonArray points; for (const auto &line : domain::polylines(source,128)) for (const auto &point : line) points.append(pair(centre+(point-centre)*factor));
        shape={{"type","spline"},{"points",points},{"closed",false}}; if (source.value("construction").toBool()) shape["construction"]=true; return shape;
    }
    const auto transform=[&](const QString &horizontal,const QString &vertical) {
        if (!shape.contains(horizontal) || !shape.contains(vertical)) return;
        const QVector2D original(float(shape.value(horizontal).toDouble()),float(shape.value(vertical).toDouble())); const auto target=centre+(original-centre)*factor;
        shape[horizontal]=target.x(); shape[vertical]=target.y();
    };
    transform("x1","y1"); transform("x2","y2"); transform("cx","cy"); transform("x","y");
    if (shape.value("points").isArray()) { QJsonArray points; for (const auto &entry : shape.value("points").toArray()) { const auto coordinates=entry.toArray(); if (coordinates.size()<2) throw domain::DomainError(QStringLiteral("点列缺少二维坐标。")); points.append(pair(centre+(QVector2D(float(coordinates[0].toDouble()),float(coordinates[1].toDouble()))-centre)*factor)); } shape["points"]=points; }
    for (const auto &key : {QString("r"),QString("rx"),QString("ry"),QString("w"),QString("h"),QString("height")}) if (shape.contains(key)) shape[key]=shape.value(key).toDouble()*factor;
    if (shape.value("path").isObject()) shape["path"]=scaled(shape.value("path").toObject(),centre,factor);
    return shape;
}
}
SketchEditor::SketchEditor(QObject *parent) : QObject(parent) {
    options_={{"sides",6},{"radius",2.0},{"height",10.0},{"text",QStringLiteral("GenForm")},{"angle",0.0},{"mode","explicit"},
        {"fx","t"},{"fy","sin(x) * 10"},{"t0",0.0},{"t1",20.0},{"closed",false},{"construction",false}};
}
QStringList SketchEditor::tools() {
    return {"select","line","centerline","midline","rect","crect","rect3","crect3","pgram","circle","circle3","arc","arc3",
        "slot","cslot","aslot3","caslot","ngon","polygon","ellipse","spline","sspline","equation","point","text", "dimension","fillet","trim","extend","offset","mirror","move","rotate","scale","convert"};
}
void SketchEditor::reset(const QJsonArray &shapes) {
    shapes_=shapes; selection_.clear(); points_.clear(); references_={}; operation_={}; textPath_={}; tool_="select"; dragging_=false; source_=-1; sweep_=0;
    Q_EMIT selectionChanged(); Q_EMIT visualChanged(); Q_EMIT toolChanged();
}
void SketchEditor::setShapes(const QJsonArray &shapes) {
    if (shapes_==shapes) return;
    shapes_=shapes;
    selection_.erase(std::remove_if(selection_.begin(),selection_.end(),[this](int index) { return index<0 || index>=shapes_.size(); }),selection_.end());
    points_.clear(); operation_={}; dragging_=false; Q_EMIT visualChanged(); Q_EMIT selectionChanged();
}
void SketchEditor::setSelection(const QVector<int> &selection) {
    selection_.clear(); for (const int index : selection) if (index>=0 && index<shapes_.size() && !selection_.contains(index)) selection_.append(index);
    Q_EMIT selectionChanged(); Q_EMIT visualChanged();
}
QJsonArray SketchEditor::chosen() const { QJsonArray result; for (const int index : selection_) if (index>=0 && index<shapes_.size()) result.append(shapes_[index]); return result; }
bool SketchEditor::setTool(const QString &tool) {
    if (!tools().contains(tool)) { Q_EMIT error(QStringLiteral("不支持的原生草图工具：%1").arg(tool)); return false; }
    if ((tool=="mirror" || tool=="move" || tool=="rotate" || tool=="scale") && selection_.isEmpty()) { Q_EMIT error(QStringLiteral("请先选中需要变换的草图图形。")); return false; }
    if (tool_==tool && operation_.isEmpty()) return true;
    textPath_={};
    if (tool=="text" && selection_.size()==1) { const auto selected=shapes_[selection_.first()].toObject(); if (QStringList{"line","arc","circle","ellipse","spline"}.contains(selected.value("type").toString())) textPath_=selected; }
    tool_=tool; points_.clear(); operation_={}; dragging_=false; source_=-1; sweep_=0;
    if (tool=="rotate" || tool=="scale") { beginOperation(tool); return true; }
    Q_EMIT toolChanged(); Q_EMIT visualChanged(); Q_EMIT selectionChanged(); return true;
}
void SketchEditor::commit(const QJsonArray &shapes) {
    if (shapes==shapes_) return;
    shapes_=shapes;
    selection_.erase(std::remove_if(selection_.begin(),selection_.end(),[this](int index) { return index<0 || index>=shapes_.size(); }),selection_.end());
    Q_EMIT shapesChanged(shapes_); Q_EMIT visualChanged(); Q_EMIT selectionChanged();
}
void SketchEditor::validate(const QJsonObject &shape) const {
    if (shape.isEmpty()) throw domain::DomainError(QStringLiteral("这些点不能构成有效图形。"));
    domain::prims(shape);
    const auto type=shape.value("type").toString();
    if (type=="text" || type=="point") return;
    if (domain::length(shape)<1e-7) throw domain::DomainError(QStringLiteral("图形长度不能为零。"));
    if (type=="rect" && (shape.value("w").toDouble()<=0 || shape.value("h").toDouble()<=0)) throw domain::DomainError(QStringLiteral("矩形宽度和高度必须大于零。"));
    if (type=="polygon") {
        const auto points=domain::vertices(shape); double area=0;
        for (qsizetype index=0;index<points.size();++index) { const auto &first=points[index], &second=points[(index+1)%points.size()]; area+=double(first.x())*second.y()-double(first.y())*second.x(); }
        if (std::abs(area)<1e-7) throw domain::DomainError(QStringLiteral("多边形不能全部共线或面积为零。"));
    }
}
void SketchEditor::add(const QJsonObject &shape) {
    validate(shape);
    auto next=shapes_; next.append(shape); selection_={int(next.size()-1)}; commit(next);
}
int SketchEditor::hit(const QVector2D &point,double tolerance) const {
    for (int index=int(shapes_.size())-1;index>=0;--index) {
        const auto shape=shapes_[index].toObject();
        if (shape.value("type")=="text" && domain::distance(domain::anchor(shape),point)<std::max(tolerance,shape.value("height").toDouble(10))) return index;
        try { if (domain::hit(shape,point,tolerance)) return index; }
        catch (const std::exception &) {}
    }
    return -1;
}
QJsonObject SketchEditor::makeShape(const QVector<QVector2D> &points) const {
    if (points.isEmpty()) return {};
    const auto first=points.first(),last=points.last(); const double reach=domain::distance(first,last);
    if (tool_=="point") return {{"type","point"},{"x",last.x()},{"y",last.y()}};
    if (tool_=="text") { QJsonObject shape{{"type","text"},{"x",last.x()},{"y",last.y()},{"height",options_.value("height")},{"text",options_.value("text")},{"angle",options_.value("angle")}}; if (!textPath_.isEmpty()) shape["path"]=textPath_; return shape; }
    if (tool_=="equation") return {{"type","equation"},{"mode",options_.value("mode")},{"fx",options_.value("fx")},{"fy",options_.value("fy")},
        {"t0",options_.value("t0")},{"t1",options_.value("t1")},{"ox",first.x()},{"oy",first.y()}};
    if (points.size()<2 || (reach<1e-8 && points.size()==2)) return {};
    if (tool_=="line" || tool_=="centerline") return line(first,last,tool_=="centerline" || options_.value("construction").toBool());
    if (tool_=="midline") return line(first*2-last,last,options_.value("construction").toBool());
    if (tool_=="rect" || tool_=="crect") {
        const bool centred=tool_=="crect"; const auto centre=centred ? first : (first+last)/2;
        return {{"type","rect"},{"cx",centre.x()},{"cy",centre.y()},{"w",std::abs(last.x()-first.x())*(centred?2:1)},{"h",std::abs(last.y()-first.y())*(centred?2:1)}};
    }
    if (tool_=="circle") return {{"type","circle"},{"cx",first.x()},{"cy",first.y()},{"r",reach}};
    if (tool_=="ngon") return {{"type","ngon"},{"cx",first.x()},{"cy",first.y()},{"r",reach},{"sides",options_.value("sides")},{"angle",angle(first,last)}};
    if (tool_=="spline" || tool_=="sspline" || tool_=="polygon") return {{"type",tool_=="polygon"?"polygon":"spline"},{"points",coordinates(points)},
        {"closed",tool_=="polygon" || options_.value("closed").toBool()},{"style",tool_=="sspline"}};
    if (points.size()<3) return line(first,last);
    const auto second=points[1],third=points[2]; const auto edge=second-first;
    if (edge.length()<1e-8) return {};
    const auto unit=edge.normalized(); const QVector2D perpendicular(-unit.y(),unit.x());
    const double rise=QVector2D::dotProduct(third-first,perpendicular);
    if (tool_=="circle3") { const auto circle=domain::circle3(first,second,third); return circle ? QJsonObject{{"type","circle"},{"cx",circle->first.x()},{"cy",circle->first.y()},{"r",circle->second}} : QJsonObject{}; }
    if (tool_=="pgram") return {{"type","polygon"},{"points",coordinates({first,second,third,first+third-second})}};
    if (tool_=="rect3") return {{"type","polygon"},{"points",coordinates({first,second,second+perpendicular*rise,first+perpendicular*rise})}};
    if (tool_=="crect3") return {{"type","polygon"},{"points",coordinates({second+perpendicular*rise,second-perpendicular*rise,first*2-second-perpendicular*rise,first*2-second+perpendicular*rise})}};
    if (tool_=="ellipse") return {{"type","ellipse"},{"cx",first.x()},{"cy",first.y()},{"rx",double(edge.length())},{"ry",std::abs(rise)},{"angle",angle(first,second)}};
    if (tool_=="slot" || tool_=="cslot") {
        const auto start=tool_=="cslot" ? first*2-second : first;
        return {{"type","slot"},{"x1",start.x()},{"y1",start.y()},{"x2",second.x()},{"y2",second.y()},{"w",2*std::abs(rise)}};
    }
    if (tool_=="arc3" || tool_=="aslot3") {
        auto arc=domain::arc3(first,second,third); if (!arc) return {};
        if (tool_=="arc3" || points.size()<4) return *arc;
        const QVector2D centre(float(arc->value("cx").toDouble()),float(arc->value("cy").toDouble()));
        (*arc)["type"]="arcslot"; (*arc)["w"]=2*std::abs(domain::distance(centre,last)-arc->value("r").toDouble()); return *arc;
    }
    if (tool_=="arc" || tool_=="caslot") {
        const double begin=angle(first,second); if (std::abs(sweep_)<1e-7) return {};
        const double start=sweep_<0?begin+sweep_:begin,end=sweep_<0?begin:begin+sweep_;
        QJsonObject arc{{"type","arc"},{"cx",first.x()},{"cy",first.y()},{"r",double(edge.length())},{"a0",start},{"a1",end}};
        if (tool_=="caslot" && points.size()>=4) { arc["type"]="arcslot"; arc["w"]=2*std::abs(domain::distance(first,last)-edge.length()); }
        return arc;
    }
    return {};
}
QJsonArray SketchEditor::preview() const {
    try {
        if (tool_=="convert") return references_;
        if (operation()=="pattern" || operation()=="cpattern") {
            QJsonArray result;
            const int horizontal=operation_.value("nx").toInt(1),vertical=operation_.value("ny").toInt(1),count=operation_.value("count").toInt(1);
            if (horizontal<1 || vertical<1 || count<1 || qint64(horizontal)*vertical*std::max<qsizetype>(1,selection_.size())>2000 || qint64(count)*std::max<qsizetype>(1,selection_.size())>2000) return {};
            if (operation()=="pattern") {
                for (int row=0;row<vertical;++row) for (int column=0;column<horizontal;++column) if (row || column)
                    for (const auto &value : chosen()) result.append(domain::moved(value.toObject(),operation_.value("dx").toDouble()*column,operation_.value("dy").toDouble()*row));
            } else {
                const double total=operation_.value("angle").toDouble(),step=total/(std::abs(std::abs(total)-360)<1e-8?count:std::max(1,count-1));
                const QVector2D centre(float(operation_.value("cx").toDouble()),float(operation_.value("cy").toDouble()));
                for (int turn=1;turn<count;++turn) for (const auto &value : chosen()) result.append(domain::rotated(value.toObject(),centre,step*turn));
            }
            return result;
        }
        if (points_.isEmpty()) return {};
        if (tool_=="move" || tool_=="mirror") {
            QJsonArray result;
            if (domain::distance(points_.first(),cursor_)<1e-7) return {};
            for (const auto &value : chosen()) result.append(tool_=="move" ? domain::moved(value.toObject(),cursor_.x()-points_.first().x(),cursor_.y()-points_.first().y()) : domain::mirrored(value.toObject(),points_.first(),cursor_));
            result.append(line(points_.first(),cursor_,true)); return result;
        }
        if (tool_=="offset" && source_>=0) {
            const auto shape=shapes_[source_].toObject(); const auto amount=domain::signed_distance(shape,cursor_);
            if (std::abs(amount)<1e-7) return {};
            return {domain::offset(shape,amount)};
        }
        auto points=points_; if (points.isEmpty() || domain::distance(points.last(),cursor_)>1e-8) points.append(cursor_);
        const auto shape=makeShape(points); return shape.isEmpty()?QJsonArray{}:QJsonArray{shape};
    } catch (const std::exception &) { return {}; }
}
void SketchEditor::press(const QVector2D &point,double tolerance,bool additive) {
    cursor_=point; tolerance_=tolerance; updateSweep(point);
    try {
        if (!operation_.isEmpty()) { Q_EMIT error(QStringLiteral("请先确认或取消当前草图操作面板。")); return; }
        const int index=hit(point,tolerance);
        if (tool_=="select" || tool_=="dimension") {
            if (additive && index>=0) { if (selection_.contains(index)) selection_.removeAll(index); else selection_.append(index); }
            else if (index<0) selection_.clear(); else if (!selection_.contains(index)) selection_={index};
            if (tool_=="dimension" && index>=0) { beginOperation("dimension"); return; }
            dragging_=index>=0 && !additive; dragStart_=point; dragBefore_=shapes_;
            Q_EMIT selectionChanged(); Q_EMIT visualChanged(); return;
        }
        if (tool_=="trim" || tool_=="extend") {
            if (index<0) throw domain::DomainError(QStringLiteral("请点击要裁剪或延伸的线段。"));
            commit(tool_=="trim" ? domain::trim(shapes_,index,point) : domain::extend(shapes_,index,point)); return;
        }
        if (tool_=="fillet") { commit(domain::fillet(shapes_,point,options_.value("radius").toDouble(2),tolerance)); return; }
        if (tool_=="convert") {
            for (const auto &value : references_) if (domain::hit(value.toObject(),point,tolerance)) { add(value.toObject()); return; }
            throw domain::DomainError(QStringLiteral("请点击投影参考边；模型必须包含有效实体和边。"));
        }
        if (tool_=="point" || tool_=="text" || tool_=="equation") { add(makeShape({point})); return; }
        if (tool_=="offset") {
            if (points_.isEmpty()) { if (index<0) throw domain::DomainError(QStringLiteral("请先点击要偏移的轮廓。")); source_=index; points_={point}; }
            else { const auto shape=shapes_[source_].toObject(); add(domain::offset(shape,domain::signed_distance(shape,point))); points_.clear(); source_=-1; }
            Q_EMIT visualChanged(); return;
        }
        if (!points_.isEmpty() && domain::distance(points_.last(),point)<1e-8) return;
        if (points_.isEmpty()) sweep_=0;
        points_.append(point);
        if (tool_=="spline" || tool_=="sspline" || tool_=="polygon") {
            if (tool_=="sspline" && points_.size()>12) throw domain::DomainError(QStringLiteral("样式样条最多支持 12 个控制点。"));
            Q_EMIT visualChanged(); return;
        }
        int steps=2;
        if (QStringList{"circle3","arc","arc3","rect3","crect3","pgram","ellipse","slot","cslot"}.contains(tool_)) steps=3;
        if (tool_=="aslot3" || tool_=="caslot") steps=4;
        if (points_.size()>=steps) {
            if (tool_=="mirror" || tool_=="move") {
                auto next=shapes_;
                for (const int selected : selection_) {
                    auto shape=tool_=="mirror" ? domain::mirrored(shapes_[selected].toObject(),points_.first(),point) : domain::moved(shapes_[selected].toObject(),point.x()-points_.first().x(),point.y()-points_.first().y());
                    if (tool_=="mirror") next.append(shape); else next[selected]=shape;
                }
                points_.clear(); tool_="select"; commit(next); Q_EMIT toolChanged();
            } else {
                auto shape=makeShape(points_); if (options_.value("construction").toBool()) shape["construction"]=true;
                add(shape); points_.clear(); if (tool_=="line" || tool_=="centerline") points_.append(point);
            }
        }
        Q_EMIT visualChanged();
    } catch (const std::exception &exception) { Q_EMIT error(QString::fromUtf8(exception.what())); if (points_.size()>1) points_.removeLast(); }
}
void SketchEditor::move(const QVector2D &point) {
    cursor_=point; updateSweep(point);
    if (dragging_) {
        try { const auto delta=point-dragStart_; auto next=dragBefore_; for (const int index : selection_) next[index]=domain::moved(dragBefore_[index].toObject(),delta.x(),delta.y()); shapes_=next; }
        catch (const std::exception &exception) { shapes_=dragBefore_; dragging_=false; Q_EMIT error(QString::fromUtf8(exception.what())); }
    }
    Q_EMIT visualChanged();
}
void SketchEditor::release(const QVector2D &point) {
    if (!dragging_) return;
    move(point); dragging_=false;
    if (shapes_!=dragBefore_) { Q_EMIT shapesChanged(shapes_); Q_EMIT selectionChanged(); }
}
void SketchEditor::box(const QVector2D &first,const QVector2D &second,bool crossing,bool additive) {
    const QRectF rectangle=QRectF(first.toPointF(),second.toPointF()).normalized(); if (!additive) selection_.clear();
    for (int index=0;index<shapes_.size();++index) {
        try {
            const auto shape=shapes_[index].toObject();
            const auto lines=domain::polylines(shape); bool inside=true,any=false;
            if (lines.isEmpty()) inside=any=rectangle.contains(domain::anchor(shape).toPointF());
            for (const auto &polyline : lines) for (qsizetype offset=0;offset<polyline.size();++offset) {
                const auto point=polyline[offset].toPointF(); const bool contained=rectangle.contains(point); inside=inside && contained; any=any || contained;
                if (offset>0 && crossing) {
                    const QLineF segment(polyline[offset-1].toPointF(),point);
                    for (const auto &edge : {QLineF(rectangle.topLeft(),rectangle.topRight()),QLineF(rectangle.topRight(),rectangle.bottomRight()),QLineF(rectangle.bottomRight(),rectangle.bottomLeft()),QLineF(rectangle.bottomLeft(),rectangle.topLeft())})
                        any=any || segment.intersects(edge,nullptr)==QLineF::BoundedIntersection;
                }
            }
            if ((crossing?any:inside) && !selection_.contains(index)) selection_.append(index);
        } catch (const std::exception &) {}
    }
    Q_EMIT selectionChanged(); Q_EMIT visualChanged();
}
void SketchEditor::finishDraft(bool closed) {
    try {
        if (points_.isEmpty()) return;
        if (tool_=="spline" || tool_=="sspline" || tool_=="polygon") {
            if (points_.size()<(tool_=="polygon" || closed ? 3:2)) throw domain::DomainError(QStringLiteral("完成曲线至少需要两个点，封闭曲线至少需要三个点。"));
            auto shape=makeShape(points_); if (closed) shape["closed"]=true; add(shape);
        }
        points_.clear(); Q_EMIT visualChanged();
    } catch (const std::exception &exception) { Q_EMIT error(QString::fromUtf8(exception.what())); }
}
void SketchEditor::escape() { if (dragging_) shapes_=dragBefore_; points_.clear(); operation_={}; dragging_=false; tool_="select"; sweep_=0; Q_EMIT toolChanged(); Q_EMIT visualChanged(); Q_EMIT selectionChanged(); }
void SketchEditor::updateSweep(const QVector2D &point) {
    if ((tool_!="arc" && tool_!="caslot") || points_.size()!=2 || domain::distance(points_.first(),point)<1e-8) return;
    const double raw=angle(points_[0],point)-angle(points_[0],points_[1]); double best=raw;
    for (int turn=-2;turn<=2;++turn) if (std::abs(raw+turn*360-sweep_)<std::abs(best-sweep_)) best=raw+turn*360;
    sweep_=std::clamp(best,-360.0,360.0);
}
void SketchEditor::importShapes(const QJsonArray &shapes) {
    if (shapes.isEmpty()) { Q_EMIT error(QStringLiteral("转换引用没有可投影的边。")); return; }
    try {
        for (const auto &value : shapes) validate(value.toObject());
        auto next=shapes_; selection_.clear(); for (const auto &value : shapes) { selection_.append(next.size()); next.append(value); } commit(next);
    } catch (const std::exception &exception) { Q_EMIT error(QString::fromUtf8(exception.what())); }
}
void SketchEditor::setReferences(const QJsonArray &shapes) { references_=shapes; Q_EMIT visualChanged(); }
QJsonObject SketchEditor::properties() const {
    QJsonArray fields,relations,actions,options;
    QString title,note,key;
    if (selection_.isEmpty() || !QStringList{"select","dimension","mirror","move"}.contains(tool_)) {
        if (tool_=="select") return {};
        title=QStringLiteral("草图工具：%1").arg(tool_); key="tool:"+tool_;
        note=QStringLiteral("按顺序单击定义几何；样条/多边形按 Enter 或双击完成。Ctrl 加选，拖框多选。关系为一次性几何调整，不是持续约束求解。 ");
        for (const auto &name : {QString("sides"),QString("radius"),QString("height"),QString("text"),QString("angle"),QString("mode"),QString("fx"),QString("fy"),QString("t0"),QString("t1")}) {
            const bool relevant=(name=="sides" && tool_=="ngon") || (name=="radius" && tool_=="fillet") ||
                (QStringList{"height","text","angle"}.contains(name) && tool_=="text") || (QStringList{"mode","fx","fy","t0","t1"}.contains(name) && tool_=="equation");
            if (relevant) fields.append(parameter("opt_"+name,options_.value(name),options_.value(name).isString()?"text":"number",name));
        }
        fields.append(parameter("opt_construction",options_.value("construction"),"bool",QStringLiteral("构造几何")));
    } else {
        title=selection_.size()==1?shapes_[selection_.first()].toObject().value("type").toString():QStringLiteral("已选 %1 个图形").arg(selection_.size());
        for (const int index : selection_) key+=QString::number(index)+",";
        note=QStringLiteral("Ctrl 点击增减选择；可拖动整组图形。关系是一次性调整，不持续求解。");
        if (selection_.size()==1) {
            const auto shape=shapes_[selection_.first()].toObject();
            for (auto iterator=shape.begin();iterator!=shape.end();++iterator) {
                if (iterator.key()=="type" || iterator.key()=="relations") continue;
                QJsonValue value=iterator.value(); QString type=value.isBool()?"bool":value.isDouble()?"number":"text";
                if (value.isArray()) value=QString::fromUtf8(QJsonDocument(value.toArray()).toJson(QJsonDocument::Compact));
                if (value.isObject()) continue;
                fields.append(parameter(iterator.key(),value,type));
            }
        }
        for (const auto &kind : domain::relations_for(chosen())) relations.append(QJsonObject{{"id","rel:"+kind},{"title",relationTitle(kind)},{"icon",kind}});
        actions.append(QJsonObject{{"id","delete"},{"title",QStringLiteral("删除")}});
        actions.append(QJsonObject{{"id","explode"},{"title",QStringLiteral("分解轮廓")}});
        actions.append(QJsonObject{{"id","flag:construction"},{"title",QStringLiteral("切换构造几何")}});
        actions.append(QJsonObject{{"id","rotate"},{"title",QStringLiteral("旋转")}});
        actions.append(QJsonObject{{"id","scale"},{"title",QStringLiteral("缩放")}});
        if (selection_.size()==2 && (chosen()[0].toObject().value("type")=="text" || chosen()[1].toObject().value("type")=="text")) actions.append(QJsonObject{{"id","textpath"},{"title",QStringLiteral("沿所选曲线排文字")}});
    }
    return {{"key",key},{"title",title},{"note",note},{"tool",key.startsWith("tool:")?tool_:QString()}, {"params",fields},{"fields",fields},
        {"relations",relations},{"held",QJsonArray{}},{"options",options},{"actions",actions},{"extra",QJsonArray{}}};
}
void SketchEditor::setField(const QString &key,const QJsonValue &value) {
    try {
        if (!operation_.isEmpty()) {
            if (!operation_.contains(key) || key=="kind" || key=="key") throw domain::DomainError(QStringLiteral("当前操作没有这个参数：%1").arg(key));
            if (value.isDouble() && !std::isfinite(value.toDouble())) throw domain::DomainError(QStringLiteral("参数必须是有限数值。"));
            operation_[key]=value; Q_EMIT visualChanged(); return;
        }
        if (key.startsWith("opt_") || selection_.size()!=1) {
            const auto option=key.startsWith("opt_")?key.mid(4):key;
            if (!options_.contains(option)) throw domain::DomainError(QStringLiteral("请只选一个图形，或编辑当前工具的参数。"));
            if (value.isDouble() && !std::isfinite(value.toDouble())) throw domain::DomainError(QStringLiteral("参数必须是有限数值。"));
            if ((option=="sides" && (value.toDouble()!=std::floor(value.toDouble()) || value.toInt()<3 || value.toInt()>256)) || ((option=="radius" || option=="height") && value.toDouble()<=0)) throw domain::DomainError(QStringLiteral("尺寸必须大于零，多边形边数为 3–256 的整数。"));
            if (option=="mode" && value!="explicit" && value!="parametric") throw domain::DomainError(QStringLiteral("方程模式为 explicit 或 parametric。"));
            options_[option]=value; Q_EMIT visualChanged(); Q_EMIT selectionChanged(); return;
        }
        const int index=selection_.first(); auto shape=shapes_[index].toObject();
        if (!shape.contains(key) && key!="construction" && key!="closed") throw domain::DomainError(QStringLiteral("图形没有这个参数：%1").arg(key));
        auto content=value;
        if (shape.value(key).isArray() && value.isString()) {
            QJsonParseError error; const auto document=QJsonDocument::fromJson(value.toString().toUtf8(),&error);
            if (error.error!=QJsonParseError::NoError || !document.isArray()) throw domain::DomainError(QStringLiteral("点列必须是有效 JSON 数组。"));
            content=document.array();
        }
        shape[key]=content; validate(shape);
        auto next=shapes_; next[index]=shape; commit(next);
    } catch (const std::exception &exception) { Q_EMIT error(QString::fromUtf8(exception.what())); }
}
void SketchEditor::beginOperation(const QString &operation) {
    try {
        if (operation!="repair" && selection_.isEmpty()) throw domain::DomainError(QStringLiteral("请先选择要操作的图形；Ctrl 加选或拖框多选。"));
        dragging_=false;
        points_.clear();
        if (operation=="pattern") operation_={{"kind",operation},{"nx",2},{"ny",1},{"dx",20.0},{"dy",20.0}};
        else if (operation=="cpattern") operation_={{"kind",operation},{"count",6},{"angle",360.0},{"cx",0.0},{"cy",0.0}};
        else if (operation=="rotate") operation_={{"kind",operation},{"angle",90.0},{"cx",0.0},{"cy",0.0},{"copy",false}};
        else if (operation=="scale") operation_={{"kind",operation},{"factor",2.0},{"cx",0.0},{"cy",0.0},{"copy",false}};
        else if (operation=="relation") { const auto choices=domain::relations_for(chosen()); if (choices.isEmpty()) throw domain::DomainError(QStringLiteral("当前选择没有可用的几何关系。")); operation_={{"kind",operation},{"choice",choices.first()}}; }
        else if (operation=="repair") operation_={{"kind",operation}};
        else if (operation=="dimension") {
            if (selection_.size()!=1) throw domain::DomainError(QStringLiteral("请先选择一个图形；多图形距离请直接编辑坐标或使用重合关系。"));
            const auto shape=chosen().first().toObject(); QString key;
            for (const auto &candidate : {QString("r"),QString("w"),QString("rx"),QString("height")}) if (shape.contains(candidate)) { key=candidate; break; }
            if (shape.value("type")=="line") operation_={{"kind",operation},{"key","length"},{"value",domain::length(shape)}};
            else if (!key.isEmpty()) operation_={{"kind",operation},{"key",key},{"value",shape.value(key)}};
            else throw domain::DomainError(QStringLiteral("此图形请在属性面板编辑具体参数。"));
        } else throw domain::DomainError(QStringLiteral("未知草图操作：%1").arg(operation));
        tool_="select"; Q_EMIT toolChanged(); Q_EMIT visualChanged();
    } catch (const std::exception &exception) { Q_EMIT error(QString::fromUtf8(exception.what())); }
}
QJsonObject SketchEditor::panel() const {
    if (operation_.isEmpty()) return {};
    QJsonArray fields; const auto kind=operation();
    for (auto iterator=operation_.begin();iterator!=operation_.end();++iterator) {
        if (iterator.key()=="kind" || iterator.key()=="key") continue;
        if (iterator.key()=="choice") {
            QJsonArray options; for (const auto &relation : domain::relations_for(chosen())) options.append(QJsonObject{{"value",relation},{"label",relationTitle(relation)}});
            auto entry=parameter("choice",iterator.value(),"choice",QStringLiteral("关系")); entry["options"]=options; fields.append(entry);
        } else fields.append(parameter(iterator.key(),iterator.value(),iterator.value().isBool()?"bool":"number"));
    }
    if (kind=="repair") fields.append(parameter("diagnosis",QString::fromUtf8(QJsonDocument(domain::diagnose(shapes_)).toJson(QJsonDocument::Compact)),"info",QStringLiteral("诊断")));
    if (kind=="relation") fields.append(parameter("hint",QStringLiteral("一次性调整：第一个图形不动，其余图形向它对齐；不持续约束。"),"info"));
    return {{"kind","sketch"},{"title",QStringLiteral("草图 %1").arg(kind)},{"fields",fields},{"accept",QStringLiteral("应用")},{"cancel",QStringLiteral("取消")}};
}
void SketchEditor::relate(const QString &kind) { commit(domain::relate(shapes_,selection_,kind)); }
void SketchEditor::acceptOperation() {
    try {
        if (operation_.isEmpty()) return;
        const auto kind=operation(); auto next=shapes_;
        if (kind=="pattern" || kind=="cpattern") {
            const int horizontal=operation_.value("nx").toInt(1),vertical=operation_.value("ny").toInt(1),count=operation_.value("count").toInt(1);
            for (const auto &key : {QString("nx"),QString("ny"),QString("count")}) if (operation_.contains(key)) {
                const double value=operation_.value(key).toDouble();
                if (value!=std::floor(value)) throw domain::DomainError(QStringLiteral("阵列数量必须为整数。"));
            }
            const qint64 copies=kind=="pattern"?qint64(horizontal)*vertical:count;
            if (horizontal<1 || vertical<1 || count<1 || copies*std::max<qsizetype>(1,selection_.size())>10000) throw domain::DomainError(QStringLiteral("阵列数量必须为正整数，输出最多 10000 个图形。"));
            if (kind=="pattern") for (int row=0;row<vertical;++row) for (int column=0;column<horizontal;++column) if (row || column)
                for (const auto &value : chosen()) next.append(domain::moved(value.toObject(),operation_.value("dx").toDouble()*column,operation_.value("dy").toDouble()*row));
            if (kind=="cpattern") {
                const double total=operation_.value("angle").toDouble(), step=total/(std::abs(std::abs(total)-360)<1e-8 ? count : std::max(1,count-1));
                const QVector2D centre(float(operation_.value("cx").toDouble()),float(operation_.value("cy").toDouble()));
                for (int turn=1;turn<count;++turn) for (const auto &value : chosen()) next.append(domain::rotated(value.toObject(),centre,step*turn));
            }
        } else if (kind=="relation") next=domain::relate(shapes_,selection_,operation_.value("choice").toString());
        else if (kind=="repair") { const auto repaired=domain::repair(shapes_); next=repaired.shapes; selection_.clear(); Q_EMIT error(QStringLiteral("修复 %1 处；剩余问题 %2 处。 ").arg(repaired.fixed).arg(domain::diagnose(next).size())); }
        else if (kind=="dimension") {
            const int index=selection_.first(); auto shape=shapes_[index].toObject(); const auto key=operation_.value("key").toString(); const double value=operation_.value("value").toDouble();
            if (value<=0 || !std::isfinite(value)) throw domain::DomainError(QStringLiteral("尺寸必须大于零。"));
            if (key=="length") { const auto tips=domain::ends(shape).value(); const auto end=tips.first+(tips.second-tips.first).normalized()*value; shape["x2"]=end.x(); shape["y2"]=end.y(); }
            else shape[key]=value;
            next[index]=shape;
        } else if (kind=="rotate" || kind=="scale") {
            const QVector2D centre(float(operation_.value("cx").toDouble()),float(operation_.value("cy").toDouble()));
            const double factor=operation_.value("factor").toDouble(1);
            if (factor<=0 || !std::isfinite(factor)) throw domain::DomainError(QStringLiteral("缩放系数必须为正有限数。"));
            for (const int index : selection_) {
                QJsonObject shape=shapes_[index].toObject();
                if (kind=="rotate") shape=domain::rotated(shape,centre,operation_.value("angle").toDouble());
                else shape=scaled(shape,centre,factor);
                if (operation_.value("copy").toBool()) next.append(shape); else next[index]=shape;
            }
        }
        for (const auto &value : next) validate(value.toObject());
        operation_={}; commit(next); Q_EMIT visualChanged();
    } catch (const std::exception &exception) { Q_EMIT error(QString::fromUtf8(exception.what())); }
}
void SketchEditor::cancelOperation() { operation_={}; Q_EMIT visualChanged(); }
void SketchEditor::action(const QString &action) {
    try {
        if (action.startsWith("rel:")) { relate(action.mid(4)); return; }
        if (action=="ok") { if (!operation_.isEmpty()) acceptOperation(); else { finishDraft(); if (!drafting()) { setTool("select"); setSelection({}); } } return; }
        if (action=="delete") { auto next=shapes_; auto selection=selection_; std::sort(selection.begin(),selection.end(),std::greater<int>()); for (const int index : selection) next.removeAt(index); selection_.clear(); commit(next); return; }
        if (action=="flag:construction") { auto next=shapes_; for (const int index : selection_) { auto shape=next[index].toObject(); shape["construction"]=!shape.value("construction").toBool(); next[index]=shape; } commit(next); return; }
        if (action=="explode") { auto next=shapes_; auto selection=selection_; std::sort(selection.begin(),selection.end(),std::greater<int>()); for (const int index : selection) { const auto pieces=domain::explode(next[index].toObject()); next.removeAt(index); for (const auto &piece : pieces) next.append(piece); } selection_.clear(); commit(next); return; }
        if (action=="textpath") {
            if (selection_.size()!=2) throw domain::DomainError(QStringLiteral("文字路径需要同时选择一个文字和一条线、圆弧、圆、椭圆或样条。"));
            int text=-1,path=-1;
            for (const int index : selection_) { if (shapes_[index].toObject().value("type")=="text") text=index; else path=index; }
            if (text<0 || path<0 || !QStringList{"line","arc","circle","ellipse","spline"}.contains(shapes_[path].toObject().value("type").toString())) throw domain::DomainError(QStringLiteral("所选图形不能作为文字路径。"));
            auto next=shapes_; auto shape=next[text].toObject(); shape["path"]=next[path]; next[text]=shape; commit(next); return;
        }
        if (action=="close") { finishDraft(true); return; }
        if (QStringList{"pattern","cpattern","relation","repair","rotate","scale","dimension"}.contains(action)) { beginOperation(action); return; }
        throw domain::DomainError(QStringLiteral("不支持的草图操作：%1").arg(action));
    } catch (const std::exception &exception) { Q_EMIT error(QString::fromUtf8(exception.what())); }
}
}
