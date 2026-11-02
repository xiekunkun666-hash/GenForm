#include "genform/view/sketch_snap.hpp"
#include "genform/domain/geometry.hpp"
#include <algorithm>
#include <cmath>
#include <limits>

namespace genform::view {
double sketchGridStep(double pixelsPerUnit) {
    for (const double step : {0.1,0.5,1.0,5.0,10.0,50.0,100.0}) if (step*std::max(0.001,pixelsPerUnit)>=7) return step;
    return std::pow(10.0,std::ceil(std::log10(7/std::max(0.001,pixelsPerUnit))));
}
SketchSnap snapSketch(const QJsonArray &shapes,const QVector2D &point,double pixelsPerUnit,const QSet<QString> &enabled,
    const QString &only,const QVector<int> &skip,const QVector<QVector2D> &draft) {
    const auto active=only.isEmpty()?enabled:QSet<QString>{only};
    const double pixel=1/std::max(0.001,pixelsPerUnit),reach=(only.isEmpty()?9:28)*pixel;
    const QStringList order{"end","int","center","quad","mid","origin"};
    SketchSnap result{point,{}}; double best=std::numeric_limits<double>::infinity(); int priority=order.size();
    QVector<QJsonObject> close; QVector<QVector2D> alignment{{0,0}};
    const auto candidate=[&](const QString &kind,const QVector2D &target) {
        const double gap=domain::distance(point,target); const int rank=order.indexOf(kind);
        if (gap<=reach && (gap<best-1e-7 || (std::abs(gap-best)<=1e-7 && rank<priority))) { best=gap; priority=rank; result={target,kind}; }
    };
    if (active.contains("end") && only.isEmpty()) candidate("origin",{0,0});
    for (qsizetype index=0;index<shapes.size();++index) {
        if (skip.contains(index)) continue;
        try {
            const auto shape=shapes[index].toObject();
            for (const auto &value : domain::key_points(shape)) {
                const auto entry=value.toArray(); const auto coordinates=entry[1].toArray();
                const auto kind=entry[0].toString(); const QVector2D target(float(coordinates[0].toDouble()),float(coordinates[1].toDouble()));
                if (active.contains(kind)) candidate(kind,target);
                if (kind=="end" || kind=="center") alignment.append(target);
            }
            if ((active.contains("int") || active.contains("near")) && shape.value("type")!="text" && shape.value("type")!="point" && domain::hit(shape,point,reach)) close.append(shape);
        } catch (const std::exception &) {}
    }
    if (active.contains("end") && draft.size()>=3) candidate("end",draft.first());
    if (active.contains("int")) for (qsizetype first=0;first<close.size();++first) for (qsizetype second=first+1;second<close.size();++second) {
        try { for (const auto &firstPrimitive : domain::prims(close[first])) for (const auto &secondPrimitive : domain::prims(close[second])) for (const auto &crossing : domain::intersections(firstPrimitive,secondPrimitive)) candidate("int",crossing); }
        catch (const std::exception &) {}
    }
    if (!result.kind.isEmpty()) return result;
    if (active.contains("near")) {
        double nearest=(only.isEmpty()?7:28)*pixel;
        for (const auto &shape : close) try { const auto foot=domain::nearest(shape,point); if (foot.first<=nearest) { nearest=foot.first; result={foot.second,"near"}; } } catch (const std::exception &) {}
        if (!result.kind.isEmpty()) return result;
    }
    const double grid=sketchGridStep(pixelsPerUnit);
    if (active.contains("grid")) { result.point={float(std::round(point.x()/grid)*grid),float(std::round(point.y()/grid)*grid)}; result.kind="grid"; }
    if (active.contains("hv") && only.isEmpty()) for (int axis=0;axis<2;++axis) {
        double distance=std::numeric_limits<double>::infinity(); float target=point[axis];
        for (const auto &own : draft) { const double gap=std::abs(own[axis]-point[axis]); if (gap<distance) { distance=gap; target=own[axis]; } }
        const bool own=distance<=5*pixel;
        if (!own) for (const auto &other : alignment) { const double gap=std::abs(other[axis]-point[axis]); if (gap<distance) { distance=gap; target=other[axis]; } }
        if (distance<=5*pixel && (own || !active.contains("grid") || distance<std::abs(result.point[axis]-point[axis]))) { result.point[axis]=target; result.kind="hv"; }
    }
    return result;
}
}
