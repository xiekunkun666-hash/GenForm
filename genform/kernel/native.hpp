#pragma once

#include <cmath>
#include <QJsonArray>
#include <QJsonObject>
#include <QMap>
#include <QString>
#include <stdexcept>
#include <vector>

namespace genform::kernel::native {

inline void fail(const QString &message) { throw std::runtime_error(message.toStdString()); }
double number(const QJsonObject &object, const QString &key, double fallback = 0, bool positive = false);
double evaluate(const QString &expression, const QMap<QString, double> &variables = {});
QJsonValue resolve(const QJsonValue &value, const QMap<QString, double> &variables);

}

#ifdef GENFORM_HAS_OCCT
#include <TopoDS_Shape.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Wire.hxx>
#include <TopoDS_Edge.hxx>
#include <gp_Ax1.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>

namespace genform::kernel::native {

constexpr double pi = 3.14159265358979323846;
constexpr double tolerance = 1e-6;
struct Frame {
    gp_Pnt origin{0, 0, 0};
    gp_Vec x{1, 0, 0}, y{0, 1, 0}, normal{0, 0, 1};
    gp_Pnt point(double first, double second) const;
};
struct Sketch {
    Frame frame;
    TopoDS_Shape profile, curves;
    std::vector<TopoDS_Wire> wires;
    QJsonArray shapes;
};
struct Tool {
    TopoDS_Shape shape;
    QString operation, origin;
};
struct Owner {
    TopoDS_Face face;
    QString feature, origin;
};
struct Context {
    QJsonArray features;
    QMap<QString, Sketch> sketches;
    QMap<QString, TopoDS_Wire> curves;
    QMap<QString, gp_Vec> helixAxes;
    QMap<QString, TopoDS_Shape> display;
    QMap<QString, std::vector<Tool>> tools;
    QJsonObject info, status;
    TopoDS_Shape body;
    std::vector<Owner> owners;
    std::vector<TopoDS_Shape> afterCuts;
    QString current;
};

QJsonArray json(const gp_Pnt &point);
QJsonArray json(const gp_Vec &vector);
gp_Pnt point(const QJsonValue &value);
gp_Vec vector(const QJsonValue &value);
Frame frame(const QJsonValue &reference, const QJsonArray &features, double offset = 0, int depth = 0);
gp_Ax1 axis(const QString &reference, const Context &context, const Frame *sketch = nullptr);
TopoDS_Shape compound(const std::vector<TopoDS_Shape> &shapes);
TopoDS_Shape moved(const TopoDS_Shape &shape, const gp_Trsf &transform);
TopoDS_Shape translated(const TopoDS_Shape &shape, const gp_Vec &translation);
bool empty(const TopoDS_Shape &shape);
double volume(const TopoDS_Shape &shape);
struct Mass { double volume; gp_Pnt center; double error; };
Mass mass(const TopoDS_Shape &shape);
void validateSolid(const TopoDS_Shape &shape);
double modelSize(const TopoDS_Shape &shape);
QJsonArray bounds(const TopoDS_Shape &shape);
TopoDS_Shape combine(const TopoDS_Shape &body, const TopoDS_Shape &tool, const QString &operation);
TopoDS_Shape booleanShape(const TopoDS_Shape &body, const TopoDS_Shape &tool, const QString &operation);
Sketch makeSketch(const QJsonObject &params, const QJsonArray &features);
std::vector<TopoDS_Shape> makeText(const QJsonObject &shape, const Frame &frame);
const Sketch &sketch(const Context &context, const QJsonObject &params, bool requireProfile = false);
std::vector<gp_Pnt> spots(const Sketch &sketch);
TopoDS_Wire path(const Context &context, const QString &id);
TopoDS_Wire spline(const std::vector<gp_Pnt> &points, bool closed = false);
TopoDS_Shape makeTool(const QString &kind, const QJsonObject &params, Context &context);
TopoDS_Shape modify(const QString &kind, const QJsonObject &params, Context &context);
TopoDS_Shape modifySurface(const QString &kind, const QJsonObject &params, Context &context);
TopoDS_Shape partition(const TopoDS_Shape &inner, const QJsonObject &params, const Context &context, double thickness);
TopoDS_Wire surfaceCurve(const QString &kind, const QJsonObject &params, Context &context);
TopoDS_Wire makeCurve(const QString &kind, const QJsonObject &params, Context &context);
TopoDS_Shape reference(const QString &kind, const QJsonObject &params, Context &context);
TopoDS_Shape hollow(const TopoDS_Shape &body, const TopoDS_Shape &tool, const QString &operation);
TopoDS_Shape threadGroove(const gp_Pnt &spot, const gp_Vec &along, double major, double pitch, double start, double stop, bool internal, double phase = 0);
double coarsePitch(double diameter);
TopoDS_Shape screw(const QJsonObject &params, Context &context);
TopoDS_Shape tipTrimmer(const gp_Pnt &spot, const gp_Vec &along, double diameter, double length, double bevel);
std::vector<TopoDS_Edge> selectEdges(const TopoDS_Shape &body, const QJsonValue &selection);
std::vector<TopoDS_Face> selectFaces(const TopoDS_Shape &body, const QJsonArray &selection);
QJsonArray edgeTable(const TopoDS_Shape &body);
QJsonArray segments(const TopoDS_Shape &body, QJsonArray *owners = nullptr);
QJsonObject properties(const TopoDS_Shape &body);
QJsonObject model(const Context &context);
void inheritOwners(Context &context, const TopoDS_Shape &before);
QJsonObject measure(const Context &context, const QJsonObject &args);
QJsonObject inspect(const Context &context, const QJsonObject &args);

}
#endif
