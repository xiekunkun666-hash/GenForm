#pragma once

#include <QJsonArray>
#include <QByteArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QMap>
#include <QMatrix4x4>
#include <QStringList>
#include <QVector>
#include <QVector2D>
#include <QVector3D>
#include <optional>
#include <stdexcept>
#include <utility>

namespace genform::domain {

inline constexpr double Join = 1e-6;
inline constexpr double Gap = 0.1;
inline constexpr double Tiny = 1e-3;

class DomainError : public std::runtime_error {
public:
    explicit DomainError(const QString& message);
};

struct Primitive {
    QString type;
    QVector<QVector2D> points;
    QVector2D centre;
    double radius = 0;
    double secondaryRadius = 0;
    double start = 0;
    double end = 0;
    double angle = 0;
};

struct OrientedPrimitive {
    Primitive primitive;
    bool backwards = false;
};

using Loop = QVector<OrientedPrimitive>;

struct LoopResult {
    QVector<Loop> loops;
    int leftover = 0;
};

struct RepairResult {
    QJsonArray shapes;
    int fixed = 0;
};

double distance(const QVector2D& first, const QVector2D& second);
double number(const QJsonObject& object, const QString& key,
              std::optional<double> fallback = std::nullopt, bool positive = false);
bool is_closed(const QJsonObject& shape);
QVector<QVector2D> vertices(const QJsonObject& shape);
QVector<Primitive> prims(const QJsonObject& shape);
QVector<QVector2D> sample(const Primitive& primitive, int fine = 64);
QVector<QVector<QVector2D>> polylines(const QJsonObject& shape, int fine = 64);
double length(const QJsonObject& shape);
std::optional<std::pair<QVector2D, QVector2D>> prim_ends(const Primitive& primitive);
std::optional<std::pair<QVector2D, QVector2D>> ends(const QJsonObject& shape);
QVector2D anchor(const QJsonObject& shape);
QJsonArray key_points(const QJsonObject& shape);
double signed_area(const QVector<QVector2D>& ring);
bool contains(const QVector<QVector2D>& ring, const QVector2D& point);
double evaluate(const QString& expression, const QMap<QString, double>& variables = {});
QVector<QVector2D> equation_points(const QJsonObject& shape);
QVector2D nearest_on_prim(const Primitive& primitive, const QVector2D& point);
std::pair<double, QVector2D> nearest(const QJsonObject& shape, const QVector2D& point);
bool hit(const QJsonObject& shape, const QVector2D& point, double tolerance);
QJsonArray explode(const QJsonObject& shape);
QJsonObject moved(const QJsonObject& shape, double dx, double dy);
QJsonObject rotated(const QJsonObject& shape, const QVector2D& centre, double degrees);
QJsonObject mirrored(const QJsonObject& shape, const QVector2D& first, const QVector2D& second);
std::optional<std::pair<QVector2D, double>> circle3(const QVector2D& first,
                                                const QVector2D& second, const QVector2D& third);
std::optional<QJsonObject> arc3(const QVector2D& start, const QVector2D& end,
                              const QVector2D& through);
QVector<QVector2D> intersections(const Primitive& first, const Primitive& second);
LoopResult loops(const QJsonArray& shapes);
QVector<QVector2D> loop_ring(const Loop& loop, int fine = 48);
QVector<int> chain_of(const QJsonArray& shapes, int index);
QJsonArray diagnose(const QJsonArray& shapes);
RepairResult repair(const QJsonArray& shapes);
QJsonObject offset(const QJsonObject& shape, double amount);
double signed_distance(const QJsonObject& shape, const QVector2D& point);
QJsonArray trim(const QJsonArray& shapes, int index, const QVector2D& point);
QJsonArray extend(const QJsonArray& shapes, int index, const QVector2D& point);
std::optional<QVector2D> corner_near(const QJsonArray& shapes, const QVector2D& point, double tolerance);
QJsonArray fillet(const QJsonArray& shapes, const QVector2D& point, double radius, double tolerance);
QStringList relations_for(const QJsonArray& chosen);
QJsonArray relate(const QJsonArray& shapes, const QVector<int>& selection, const QString& kind);
QJsonObject fit_line(const QVector<QVector2D>& line, double tolerance = 1e-4);
QJsonArray fit_lines(const QVector<QVector<QVector2D>>& lines);
QJsonArray project_edges(const QJsonObject& model, const QJsonValue& plane, double offset = 0);
QVector<QVector3D> text_layout(const QJsonObject& shape, const QVector<double>& advances);

struct PlaneFrame {
    QVector3D origin;
    QVector3D x;
    QVector3D y;
    QVector3D normal;
    QMatrix4x4 matrix() const;
};

PlaneFrame frame(const QJsonValue& plane = QStringLiteral("XY"), double offset = 0);
QVector<QVector3D> to_world(const QVector<QVector2D>& points,
                          const QJsonValue& plane = QStringLiteral("XY"), double offset = 0);
std::optional<QVector2D> from_ray(const QVector3D& origin, const QVector3D& direction,
                                const QJsonValue& plane = QStringLiteral("XY"), double offset = 0);

QJsonArray material_catalog();
std::optional<double> density(const QString& material);
std::optional<QVector3D> mechanics(const QString& material);
QString material_color(const QString& material);
std::optional<QVector3D> rgb(const QString& color);
std::optional<double> mass_grams(double volumeMm3, const QString& material);
QJsonObject mass_properties(const QJsonArray& properties, const QStringList& materials);
QJsonArray rule_table();
QJsonObject clean_rules(const QJsonObject& rules);
QJsonObject effective_rules(const QJsonObject& settings = {}, const QJsonObject& document = {});

QJsonObject describe_document(const QJsonObject& document);
QJsonObject describe(const QString& path);
QJsonArray bill(const QJsonArray& parts, const QJsonObject& documents = {});
QJsonObject bill_totals(const QJsonArray& rows);
QByteArray bill_csv(const QJsonArray& rows);

QJsonObject issue(const QString& level, const QString& code, const QString& title,
                  const QString& detail = {}, const QJsonArray& features = {},
                  const QJsonValue& point = QJsonValue::Null);
QJsonArray galvanic(const QJsonArray& pairs, const QStringList& materials, const QStringList& names);
QJsonArray fasteners(const QJsonArray& pairs, const QStringList& kinds, const QStringList& names);
QJsonArray orphans(const QJsonArray& pairs, const QStringList& kinds, const QStringList& names,
                   const QJsonArray& properties);
QJsonArray duplicates(const QJsonArray& parts);
QJsonArray bill_gaps(const QJsonArray& rows);
QJsonArray mass_issues(const QJsonArray& properties, const QStringList& materials,
                       const QStringList& names, const QJsonArray& size);
QJsonArray motion_issues(const QJsonArray& clashes, const QStringList& jointNames,
                         const QStringList& units);

QStringList solid_kinds();
QJsonArray process_catalog();
std::pair<QString, QString> shape_kind(const QJsonObject& feature, const QJsonObject& metrics,
                                      const QJsonObject& byId, bool hollow = false);
QJsonObject rank_processes(const QJsonObject& feature, const QJsonObject& metrics,
                           const QJsonObject& byId, int batch = 1, const QString& material = {},
                           bool hollow = false, int copies = 1);
QJsonObject choose_process(const QJsonObject& feature, const QJsonObject& metrics,
                           const QJsonObject& byId, int batch = 1, const QString& material = {},
                           bool hollow = false, int copies = 1);
QString standard_spec(const QJsonObject& feature, const QJsonObject& metrics,
                      const QJsonObject& byId, const QString& kind = {});
QJsonObject bind_processes(const QJsonArray& features, const QJsonObject& report,
                           int batch = 1, const QString& material = {}, const QStringList& only = {});
QJsonArray proofing_checks(const QJsonArray& features, const QJsonObject& report,
                           const QString& material = {}, const QJsonObject& rules = {});
QJsonArray design_checks(const QJsonArray& features, const QJsonObject& model,
                         const QJsonObject& report, const QJsonObject& rules = {},
                         const QString& material = {});
QJsonObject issue_summary(const QJsonArray& issues);
QStringList red_features(const QJsonArray& issues);
QJsonArray standard_part_catalog();
QJsonArray screw_lengths(const QString& size);
std::pair<QString, QJsonObject> make_standard_part(const QString& kind, const QString& size,
                                                 std::optional<double> length = std::nullopt,
                                                 const QString& series = {});

}
