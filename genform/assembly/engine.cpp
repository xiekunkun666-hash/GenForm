#include "detail.hpp"
#include "../kernel/kernel.hpp"
#include "../kernel/file_io.hpp"
#include <QCryptographicHash>
#include <QDateTime>
#include <QTemporaryDir>
#include <algorithm>

#ifdef GENFORM_HAS_OCCT
#include <BRep_Builder.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepTools.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <STEPControl_Reader.hxx>
#include <STEPControl_Writer.hxx>
#include <StlAPI_Reader.hxx>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#endif

namespace genform::assembly {
using namespace detail;

struct Engine::Impl {
    QJsonArray features;
    std::optional<int> upto;
    QJsonObject props;
    QString documentPath;
    QJsonObject data{{"format", "genform-assembly"}, {"version", 1}, {"parts", QJsonArray{}}};
    QString baseDirectory;
#ifdef GENFORM_HAS_OCCT
    QMap<QString, Part> sources;
    QMap<QString, QJsonObject> pairs;

    Part source(const QJsonObject &part, const QMap<QString, double> &parameters) {
        const QString path = part["path"].toString();
        QJsonObject document;
        QString key;
        if (!path.isEmpty()) {
            const QFileInfo file(path);
            if (!file.exists() || !file.isFile()) fail("Part file not found: " + path);
            key = file.canonicalFilePath() + ":" + QString::number(file.lastModified().toMSecsSinceEpoch()) + ":" + QString::number(file.size());
        } else {
            document = {{"features", features}, {"props", props}};
            if (upto) document["upto"] = *upto;
            if (part["features"].isArray()) document["features"] = part["features"];
            if (part["props"].isObject()) document["props"] = part["props"];
            if (part.contains("upto")) document["upto"] = part["upto"];
            key = QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(document).toJson(QJsonDocument::Compact), QCryptographicHash::Sha256).toHex());
        }
        QJsonObject parameterJson;
        for (auto entry = parameters.cbegin(); entry != parameters.cend(); ++entry) parameterJson[entry.key()] = entry.value();
        key += ":" + QString::fromLatin1(QJsonDocument(parameterJson).toJson(QJsonDocument::Compact));
        if (sources.contains(key)) return sources.value(key);
        Part result;
        result.key = key;
        const QString suffix = QFileInfo(path).suffix().toLower();
        if (path.isEmpty() || suffix == "gform") {
            if (!path.isEmpty()) document = readObject(path);
            if (!document["features"].isArray()) fail("Part document has no feature array: " + path);
            auto sourceFeatures = document["features"].toArray();
            for (int index = 0; index < sourceFeatures.size(); ++index) {
                auto feature = sourceFeatures[index].toObject();
                auto params = feature["params"].toObject();
                if (feature["type"] == "import_step" && !params["path"].toString().isEmpty()) {
                    const QString base = path.isEmpty() ? QFileInfo(documentPath).absolutePath() : QFileInfo(path).absolutePath();
                    params["path"] = absolutePath(params["path"].toString(), base);
                    feature["params"] = params;
                    sourceFeatures[index] = feature;
                }
                if (feature["type"] != "variables") continue;
                auto values = params["values"].toObject();
                for (auto entry = parameters.cbegin(); entry != parameters.cend(); ++entry)
                    if (values.contains(entry.key())) values[entry.key()] = entry.value();
                params["values"] = values;
                feature["params"] = params;
                sourceFeatures[index] = feature;
            }
            kernel::Kernel builder;
            result.buildFeatures = sourceFeatures;
            const auto rollback = document["upto"].isDouble() ? std::optional<int>(document["upto"].toInt()) : std::nullopt;
            result.model = builder.build(sourceFeatures, rollback);
            const auto status = result.model["status"].toObject();
            for (auto entry = status.constBegin(); entry != status.constEnd(); ++entry)
                if (entry.value().toString().startsWith("error:")) fail("Part " + path + ", " + entry.key() + ": " + entry.value().toString());
            if (!result.model["has_body"].toBool()) fail("Part contains no body: " + path);
            QTemporaryDir temporary;
            if (!temporary.isValid()) fail("Cannot create temporary BREP directory");
            const QString brep = temporary.filePath("part.brep");
            builder.exportFile(brep);
            result.shape = kernel::file_io::readShape(brep);
        } else if (suffix == "step" || suffix == "stp") {
            result.shape = kernel::file_io::readShape(path);
        } else if (suffix == "stl") {
            result.shape = kernel::file_io::readShape(path);
            result.exact = false;
        } else if (suffix == "brep") {
            result.shape = kernel::file_io::readShape(path);
        } else fail("Part format must be .gform, .step, .stp, .stl or .brep");
        if (kernel::native::empty(result.shape)) fail("Imported part contains no faces: " + path);
        TopTools_IndexedMapOfShape allFaces, solidFaces;
        TopExp::MapShapes(result.shape, TopAbs_FACE, allFaces);
        for (TopExp_Explorer solid(result.shape, TopAbs_SOLID); solid.More(); solid.Next())
            TopExp::MapShapes(solid.Current(), TopAbs_FACE, solidFaces);
        if (solidFaces.Extent() == 0 || solidFaces.Extent() != allFaces.Extent()) result.exact = false;
        if (result.exact) kernel::native::validateSolid(result.shape);
        result.document = document;
        if (result.model.isEmpty()) {
            kernel::native::Context context;
            context.body = result.shape;
            result.model = kernel::native::model(context);
        }
        updateBounds(result);
        if (sources.size() >= 128) sources.clear();
        sources.insert(key, result);
        return result;
    }

    Part placed(const QJsonObject &definition, const QMap<QString, double> &parameters) {
        auto normalized = definition;
        const QString path = definition.value("path").toString(definition["file"].toString());
        if (!path.isEmpty()) normalized["path"] = absolutePath(path, baseDirectory);
        Part part = source(normalized, parameters);
        part.definition = normalized;
        const auto matrix = placement(normalized);
        gp_Trsf transform;
        transform.SetValues(matrix[0][0], matrix[0][1], matrix[0][2], matrix[0][3],
                            matrix[1][0], matrix[1][1], matrix[1][2], matrix[1][3],
                            matrix[2][0], matrix[2][1], matrix[2][2], matrix[2][3]);
        part.shape = kernel::native::moved(part.shape, transform);
        part.key += ":" + QString::fromLatin1(QJsonDocument(json(matrix)).toJson(QJsonDocument::Compact));
        updateBounds(part);
        return part;
    }
#endif
};

Engine::Engine() : impl_(std::make_unique<Impl>()) {}
Engine::~Engine() = default;

void Engine::setDocument(const QJsonArray &features, std::optional<int> upto,
                         const QJsonObject &props, const QString &path) {
    impl_->features = features;
    impl_->upto = upto;
    impl_->props = props;
    impl_->documentPath = path;
    clearCache();
}

QJsonObject Engine::load(const QString &path) {
    const auto full = absolutePath(path, {});
    const auto data = readObject(full);
    if (data["format"] != "genform-assembly") fail("Not a GenForm assembly: " + path);
    auto result = setAssembly(data, QFileInfo(full).absolutePath());
    impl_->data["assembly_path"] = full;
    result["assembly_path"] = full;
    return result;
}

QJsonObject Engine::setAssembly(const QJsonObject &data, const QString &baseDirectory) {
    const auto resolved = resolveAssembly(data, baseDirectory);
    pose(resolved["parts"].toArray(), resolved["joints"].toArray());
    impl_->data = data;
    impl_->baseDirectory = resolved["base_directory"].toString();
    clearCache();
    return assembly();
}

QJsonObject Engine::assembly() const { return resolveAssembly(impl_->data, impl_->baseDirectory); }

void Engine::clearCache() {
#ifdef GENFORM_HAS_OCCT
    impl_->sources.clear();
    impl_->pairs.clear();
#endif
}

QJsonObject Engine::query(const QString &what, const QJsonObject &args) {
    if (what == "load" || what == "load_assembly") return load(args["path"].toString());
    if (what == "set_assembly") return setAssembly(args["data"].toObject(), args["base_directory"].toString());
    if (what == "assembly" || what == "get_assembly") return assembly();
    if (what == "capabilities") return {{"backend", "native-c++-occt"}, {"exact_geometry", kernel::Kernel::available()},
        {"queries", QJsonArray{"meshes", "interference", "contacts", "connections", "measure_parts", "mass_props", "bom", "pose", "motion_samples", "sweep", "sequence", "stack", "assembly_step", "drawing", "drag", "static", "fasteners"}},
        {"unsupported_queries", QJsonArray{}},
        {"limitations", QJsonArray{"Motion and assembly insertion checks are sampled, not continuous collision certificates", "STL and non-solid BREP cannot certify geometry checks", "Static analysis uses approximate voxel hexahedral finite elements, not certified engineering analysis", "Fastener checks require native screw/tapped-hole feature metadata; imported thread recognition, thread load strength and tool access are not implemented"}}};
    QJsonObject request = impl_->data;
    if (args.contains("parts")) {
        request.remove("joints");
        request.remove("mates");
        request.remove("links");
    }
    for (auto entry = args.constBegin(); entry != args.constEnd(); ++entry) request[entry.key()] = entry.value();
    const auto resolved = resolveAssembly(request, args.value("base_directory").toString(impl_->baseDirectory.isEmpty() ? QFileInfo(impl_->documentPath).absolutePath() : impl_->baseDirectory));
    QJsonArray definitions = resolved["parts"].toArray();
    const auto joints = resolved["joints"].toArray();
    if (what == "motion_samples") return motionSamples(definitions, joints, args.value("samples").toInt(8));
    if (what == "pose" || what == "motion")
        return pose(definitions, joints, args.contains("seconds") ? std::optional<double>(scalar(args["seconds"])) : std::nullopt);
    if (what != "sweep" && !joints.isEmpty() && !args.value("posed").toBool()) {
        const auto positioned = pose(definitions, joints, args.contains("seconds") ? std::optional<double>(scalar(args["seconds"])) : std::nullopt);
        definitions = positioned["parts"].toArray();
        if (!request.contains("links")) request["links"] = positioned["links"];
    }
    if (what == "bom" || what == "bill") {
        QJsonArray documents;
        for (const auto &value : definitions) {
            const auto part = value.toObject();
            const QString path = part["path"].toString();
            documents.append(path.isEmpty() ? QJsonObject{{"features", part.value("features").toArray(impl_->features)}, {"props", part.value("props").toObject(impl_->props)}} :
                             QFileInfo(path).suffix().compare("gform", Qt::CaseInsensitive) == 0 ? readObject(path) : QJsonObject{});
        }
        return detail::bom(definitions, documents);
    }
#ifndef GENFORM_HAS_OCCT
    fail("OpenCascade C++ SDK is required for assembly geometry query: " + what);
#else
    try {
        const auto parameters = parameterValues(resolved["params"].toObject());
        if (what == "meshes") {
            QJsonArray meshes;
            bool complete = true;
            for (int index = 0; index < definitions.size(); ++index) {
                const auto definition = definitions[index].toObject();
                try { meshes.append(mesh(impl_->placed(definition, parameters))); }
                catch (const std::exception &error) {
                    if (!args["allow_partial"].toBool()) throw;
                    complete = false;
                    meshes.append(QJsonObject{{"index", index}, {"name", definition["name"]}, {"error", QString::fromUtf8(error.what())}});
                }
            }
            return {{"meshes", meshes}, {"complete", complete}};
        }
        if (what == "drawing" || what == "drag" || what == "static") {
            if (args.contains("part")) definitions = QJsonArray{args["part"]};
            if (definitions.isEmpty()) definitions.append(QJsonObject{{"path", ""}, {"move", QJsonArray{0, 0, 0}}, {"turn", QJsonArray{0, 0, 0}}});
        }
        std::vector<Part> parts;
        parts.reserve(static_cast<size_t>(definitions.size()));
        for (const auto &definition : definitions) parts.push_back(impl_->placed(definition.toObject(), parameters));
        if (what == "stack") return detail::stack(parts, args);
        if (what == "drawing") {
            if (parts.size() != 1) fail("Drawing requires exactly one part");
            return detail::drawing(parts.front(), args);
        }
        if (what == "drag") return detail::drag(parts, args);
        if (what == "static") {
            if (parts.size() != 1) fail("Static analysis requires exactly one part");
            return staticAnalysis(parts.front(), args);
        }
        requireExact(parts);
        if (what == "fasteners") return detail::fasteners(parts);
        if (what == "interference") return detail::interference(parts, args);
        if (what == "contacts" || what == "connections") return detail::contacts(parts, request, impl_->pairs);
        if (what == "measure_parts") return measureParts(parts);
        if (what == "mass_props" || what == "mass") return massProperties(parts);
        if (what == "sequence") return detail::sequence(parts, args);
        if (what == "assembly_step") {
            if (parts.empty()) fail("Cannot export an empty assembly");
            std::vector<TopoDS_Shape> shapes;
            for (const auto &part : parts) shapes.push_back(part.shape);
            const QString output = args["path"].toString();
            if (QFileInfo(output).suffix().compare("step", Qt::CaseInsensitive) != 0 &&
                QFileInfo(output).suffix().compare("stp", Qt::CaseInsensitive) != 0) fail("Assembly export requires .step or .stp");
            kernel::file_io::writeShape(kernel::native::compound(shapes), output);
            return {{"parts", static_cast<int>(parts.size())}, {"exact", true}};
        }
        if (what == "sweep") {
            if (parts.size() < 2) fail("Motion interference sweep requires at least two parts");
            QJsonArray jobs = joints;
            if (jobs.isEmpty()) fail("Motion sweep requires joint definitions or sampled poses");
            bool provided = false;
            for (const auto &entry : jobs) if (entry.toObject().contains("values") || entry.toObject().contains("poses")) provided = true;
            if (!provided) jobs = motionSamples(definitions, joints, args.value("samples").toInt(8))["joints"].toArray();
            const auto rules = args["rules"].toObject();
            const double tolerance = number(rules, "tolerance", 0.1), clearance = std::max(number(rules, "clearance", 0.5), tolerance);
            if (tolerance < 0 || clearance <= 0) fail("Invalid motion sweep contact rules");
            QJsonArray clashes;
            int checked = 0, positions = 0;
            QSet<QString> reported;
            for (int jointIndex = 0; jointIndex < jobs.size(); ++jointIndex) {
                const auto joint = jobs[jointIndex].toObject();
                QJsonArray poses = joint["poses"].toArray();
                for (const auto &value : joint["values"].toArray()) {
                    QJsonObject swings;
                    QJsonObject swing{{"origin", joint["origin"]}, {"axis", joint["axis"]}, {joint["kind"] == "slide" ? "slide" : "angle", scalar(value)}};
                    for (const auto &entry : joint["parts"].toArray()) swings[QString::number(entry.toInt(-1))] = swing;
                    poses.append(QJsonObject{{"value", scalar(value)}, {"swings", swings}, {"rigid_group", true}});
                }
                for (const auto &entry : poses) {
                    if (++positions > 10000) fail("Motion sweep exceeds 10000 positions");
                    const auto sample = entry.toObject(), swings = sample["swings"].toObject();
                    auto positioned = parts;
                    QSet<int> moving;
                    for (auto swing = swings.constBegin(); swing != swings.constEnd(); ++swing) {
                        bool valid = false;
                        const int index = swing.key().toInt(&valid);
                        if (!valid || index < 0 || index >= static_cast<int>(parts.size())) fail("Invalid sweep part reference");
                        auto definition = definitions[index].toObject();
                        definition["swing"] = swing.value();
                        positioned[index] = impl_->placed(definition, parameters);
                        moving.insert(index);
                    }
                    if (moving.isEmpty()) fail("Motion sweep sample contains no moving part");
                    for (int first = 0; first < static_cast<int>(parts.size()); ++first)
                        for (int second = first + 1; second < static_cast<int>(parts.size()); ++second) {
                            if (!moving.contains(first) && !moving.contains(second)) continue;
                            if (sample["rigid_group"].toBool() && moving.contains(first) && moving.contains(second)) continue;
                            ++checked;
                            const auto found = relationship(positioned[first], positioned[second], tolerance, clearance);
                            const QString key = QString::number(jointIndex) + ":" + QString::number(first) + ":" + QString::number(second);
                            if (found["kind"] != "clash" || reported.contains(key)) continue;
                            reported.insert(key);
                            auto row = found;
                            row["joint"] = jointIndex;
                            row["value"] = sample["value"];
                            row["a"] = first;
                            row["b"] = second;
                            row["names"] = QJsonArray{parts[first].definition["name"], parts[second].definition["name"]};
                            clashes.append(row);
                        }
                }
            }
            if (positions == 0) fail("Motion sweep contains no sampled positions");
            return {{"clashes", clashes}, {"checked", checked}, {"positions", positions}, {"sampled", true},
                    {"continuous_collision_detection", false}, {"exact_at_samples", true}, {"complete", true}};
        }
    } catch (const Standard_Failure &error) {
        fail("OpenCascade assembly query failed: " + QString::fromUtf8(error.GetMessageString() ? error.GetMessageString() : "unknown failure"));
    }
#endif
    fail("Native assembly query not implemented: " + what);
    return {};
}
}
