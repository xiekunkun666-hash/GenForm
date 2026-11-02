#include "detail.hpp"

#ifdef GENFORM_HAS_OCCT
#include <QElapsedTimer>
#include <algorithm>
#include <numeric>
#include <unordered_map>

namespace genform::assembly::detail {
namespace {
using StrainMatrix = std::array<std::array<double, 24>, 6>;
using ElasticMatrix = std::array<std::array<double, 6>, 6>;
using StiffnessMatrix = std::array<std::array<double, 24>, 24>;
constexpr int cornerSigns[8][3] = {{-1, -1, -1}, {1, -1, -1}, {1, 1, -1}, {-1, 1, -1},
                                  {-1, -1, 1}, {1, -1, 1}, {1, 1, 1}, {-1, 1, 1}};
constexpr int offsets[8][3] = {{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0},
                              {0, 0, 1}, {1, 0, 1}, {1, 1, 1}, {0, 1, 1}};

StrainMatrix strainMatrix(const Vector &point, double step) {
    StrainMatrix result{};
    for (int node = 0; node < 8; ++node) {
        Vector gradient{};
        for (int axis = 0; axis < 3; ++axis) {
            gradient[axis] = cornerSigns[node][axis] / (4 * step);
            for (int other = 0; other < 3; ++other) if (other != axis) gradient[axis] *= 1 + cornerSigns[node][other] * point[other];
        }
        const int first = node * 3;
        result[0][first] = gradient[0];
        result[1][first + 1] = gradient[1];
        result[2][first + 2] = gradient[2];
        result[3][first] = gradient[1]; result[3][first + 1] = gradient[0];
        result[4][first + 1] = gradient[2]; result[4][first + 2] = gradient[1];
        result[5][first] = gradient[2]; result[5][first + 2] = gradient[0];
    }
    return result;
}

struct Grid {
    double step = 0;
    Vector low{};
    std::array<int, 3> counts{};
    std::vector<std::array<int, 3>> cells;
};

Grid voxelize(const QJsonArray &vertices, const QJsonArray &triangles, int target) {
    Vector low{1e300, 1e300, 1e300}, high{-1e300, -1e300, -1e300};
    std::vector<Vector> points;
    for (const auto &entry : vertices) {
        const auto point = coordinates(entry);
        points.push_back(point);
        for (int axis = 0; axis < 3; ++axis) { low[axis] = std::min(low[axis], point[axis]); high[axis] = std::max(high[axis], point[axis]); }
    }
    Vector size{};
    for (int axis = 0; axis < 3; ++axis) size[axis] = std::max(high[axis] - low[axis], 1e-6);
    double step = std::max(std::cbrt(size[0] * size[1] * size[2] / target), *std::max_element(size.begin(), size.end()) / 160);
    Grid result;
    for (int refinement = 0; refinement < 6; ++refinement) {
        result = {};
        result.step = step;
        result.low = low;
        size_t capacity = 1;
        for (int axis = 0; axis < 3; ++axis) {
            result.counts[axis] = std::max(1, static_cast<int>(std::ceil(size[axis] / step - 1e-9)));
            capacity *= result.counts[axis];
        }
        if (capacity > 2000000) fail("Static voxel grid exceeds two million cells; use a lower quality or simpler model");
        const int width = result.counts[0], height = result.counts[1];
        std::vector<std::vector<double>> columns(static_cast<size_t>(width) * height);
        for (const auto &entry : triangles) {
            const auto indices = entry.toArray();
            if (indices.size() != 3) fail("Invalid surface triangle");
            const auto &first = points.at(indices[0].toInt()), &second = points.at(indices[1].toInt()), &third = points.at(indices[2].toInt());
            const double determinant = (second[1] - third[1]) * (first[0] - third[0]) + (third[0] - second[0]) * (first[1] - third[1]);
            if (std::abs(determinant) < 1e-16) continue;
            const int fromX = std::clamp(static_cast<int>(std::floor((std::min({first[0], second[0], third[0]}) - low[0]) / step)), 0, width - 1);
            const int toX = std::clamp(static_cast<int>(std::floor((std::max({first[0], second[0], third[0]}) - low[0]) / step)), 0, width - 1);
            const int fromY = std::clamp(static_cast<int>(std::floor((std::min({first[1], second[1], third[1]}) - low[1]) / step)), 0, height - 1);
            const int toY = std::clamp(static_cast<int>(std::floor((std::max({first[1], second[1], third[1]}) - low[1]) / step)), 0, height - 1);
            for (int horizontal = fromX; horizontal <= toX; ++horizontal)
                for (int vertical = fromY; vertical <= toY; ++vertical) {
                    const double pointX = low[0] + (horizontal + 0.5) * step, pointY = low[1] + (vertical + 0.5) * step;
                    const double firstWeight = ((second[1] - third[1]) * (pointX - third[0]) + (third[0] - second[0]) * (pointY - third[1])) / determinant;
                    const double secondWeight = ((third[1] - first[1]) * (pointX - third[0]) + (first[0] - third[0]) * (pointY - third[1])) / determinant;
                    if (firstWeight >= -1e-9 && secondWeight >= -1e-9 && firstWeight + secondWeight <= 1 + 1e-9)
                        columns[static_cast<size_t>(horizontal) * height + vertical].push_back(firstWeight * first[2] + secondWeight * second[2] + (1 - firstWeight - secondWeight) * third[2]);
                }
        }
        for (int horizontal = 0; horizontal < width; ++horizontal)
            for (int vertical = 0; vertical < height; ++vertical) {
                auto &hits = columns[static_cast<size_t>(horizontal) * height + vertical];
                std::sort(hits.begin(), hits.end());
                hits.erase(std::unique(hits.begin(), hits.end(), [&](double first, double second) { return std::abs(first - second) < step * 1e-7; }), hits.end());
                if (hits.size() % 2 != 0) fail("Static surface voxelization has an unmatched crossing; geometry is not safely voxelizable");
                for (size_t index = 1; index < hits.size(); index += 2) {
                    const int bottom = std::max(0, static_cast<int>(std::ceil((hits[index - 1] - low[2]) / step - 0.5)));
                    const int top = std::min(result.counts[2] - 1, static_cast<int>(std::floor((hits[index] - low[2]) / step - 0.5)));
                    for (int level = bottom; level <= top; ++level) result.cells.push_back({horizontal, vertical, level});
                }
            }
        if (result.cells.empty() || result.cells.size() >= static_cast<size_t>(target * 0.6)) break;
        step *= std::max(0.6, std::cbrt(result.cells.size() / (target * 0.9)));
    }
    if (result.cells.empty()) fail("Body is too thin for the static voxel mesh");
    if (result.cells.size() > 60000) fail("Static mesh exceeds 60000 elements");
    return result;
}

double percentile(std::vector<double> values, double fraction) {
    std::sort(values.begin(), values.end());
    const double position = (values.size() - 1) * fraction;
    const size_t lower = static_cast<size_t>(position), upper = std::min(lower + 1, values.size() - 1);
    return values[lower] + (values[upper] - values[lower]) * (position - lower);
}
}

QJsonObject staticAnalysis(const Part &part, const QJsonObject &args) {
    requireExact({part});
    const double young = number(args, "young", 0, true), poisson = number(args, "poisson", 0.3);
    const double yield = number(args, "yield");
    if (poisson < 0 || poisson >= 0.5 || yield < 0) fail("Invalid elastic material properties");
    const auto force = coordinates(args["force"]);
    if (std::hypot(force[0], force[1], force[2]) < 1e-15) fail("Static force must be nonzero");
    QSet<int> fixedFaces, loadedFaces;
    for (const auto &entry : args["fixed"].toArray()) fixedFaces.insert(entry.toInt(-1));
    for (const auto &entry : args["loaded"].toArray()) loadedFaces.insert(entry.toInt(-1));
    if (fixedFaces.isEmpty() || loadedFaces.isEmpty()) fail("Static analysis requires fixed and loaded face IDs");
    for (const int face : fixedFaces) if (loadedFaces.contains(face)) fail("A face cannot be both fixed and loaded");
    const auto display = mesh(part);
    const auto vertices = display["verts"].toArray(), triangles = display["tris"].toArray(), faceIds = display["tri_face"].toArray();
    if (faceIds.size() != triangles.size()) fail("Static analysis requires triangle face ownership");
    const QMap<QString, int> qualities{{"coarse", 2500}, {"medium", 7000}, {"fine", 16000}};
    const QString quality = args.value("quality").toString("medium");
    if (!qualities.contains(quality)) fail("Static quality must be coarse, medium or fine");
    const auto grid = voxelize(vertices, triangles, qualities.value(quality));
    const auto nodeKey = [&](int first, int second, int third) {
        return (static_cast<qint64>(first) * (grid.counts[1] + 1) + second) * (grid.counts[2] + 1) + third;
    };
    std::unordered_map<qint64, int> nodeIds;
    std::vector<Vector> positions;
    std::vector<std::array<int, 8>> elements;
    for (const auto &cell : grid.cells) {
        std::array<int, 8> nodes{};
        for (int corner = 0; corner < 8; ++corner) {
            const int first = cell[0] + offsets[corner][0], second = cell[1] + offsets[corner][1], third = cell[2] + offsets[corner][2];
            const auto key = nodeKey(first, second, third);
            const auto [entry, inserted] = nodeIds.emplace(key, static_cast<int>(positions.size()));
            if (inserted) positions.push_back({grid.low[0] + first * grid.step, grid.low[1] + second * grid.step, grid.low[2] + third * grid.step});
            nodes[corner] = entry->second;
        }
        elements.push_back(nodes);
    }
    const auto nearNodes = [&](const Vector &point, double radius) {
        std::vector<int> result;
        std::array<int, 3> start{}, end{};
        for (int axis = 0; axis < 3; ++axis) {
            start[axis] = std::max(0, static_cast<int>(std::floor((point[axis] - radius - grid.low[axis]) / grid.step)));
            end[axis] = std::min(grid.counts[axis], static_cast<int>(std::ceil((point[axis] + radius - grid.low[axis]) / grid.step)));
        }
        for (int first = start[0]; first <= end[0]; ++first)
            for (int second = start[1]; second <= end[1]; ++second)
                for (int third = start[2]; third <= end[2]; ++third) {
                    const auto entry = nodeIds.find(nodeKey(first, second, third));
                    if (entry == nodeIds.end()) continue;
                    const auto &position = positions[entry->second];
                    const double squared = std::pow(position[0] - point[0], 2) + std::pow(position[1] - point[1], 2) + std::pow(position[2] - point[2], 2);
                    if (squared <= radius * radius) result.push_back(entry->second);
                }
        return result;
    };
    QSet<int> held, pushed, seenFaces;
    for (int triangle = 0; triangle < triangles.size(); ++triangle) {
        const int face = faceIds[triangle].toInt(-1);
        if (!fixedFaces.contains(face) && !loadedFaces.contains(face)) continue;
        seenFaces.insert(face);
        const auto indices = triangles[triangle].toArray();
        const auto first = coordinates(vertices[indices[0].toInt()]), second = coordinates(vertices[indices[1].toInt()]), third = coordinates(vertices[indices[2].toInt()]);
        const auto length = [](const Vector &start, const Vector &end) { return std::hypot(start[0] - end[0], start[1] - end[1], start[2] - end[2]); };
        const int divisions = std::clamp(static_cast<int>(std::ceil(std::max({length(first, second), length(second, third), length(first, third)}) / (grid.step * 0.5))), 1, 40);
        for (int firstStep = 0; firstStep <= divisions; ++firstStep)
            for (int secondStep = 0; secondStep <= divisions - firstStep; ++secondStep) {
                Vector point{};
                for (int axis = 0; axis < 3; ++axis) point[axis] = first[axis] + (second[axis] - first[axis]) * firstStep / divisions + (third[axis] - first[axis]) * secondStep / divisions;
                for (const int node : nearNodes(point, grid.step * 0.9)) (fixedFaces.contains(face) ? held : pushed).insert(node);
            }
    }
    for (const int face : fixedFaces) if (!seenFaces.contains(face)) fail("Fixed face ID does not exist");
    for (const int face : loadedFaces) if (!seenFaces.contains(face)) fail("Loaded face ID does not exist");
    for (const int node : held) pushed.remove(node);
    if (held.size() < 3 || pushed.isEmpty()) fail("Selected faces are too small for this static mesh");
    std::vector<int> parent(positions.size());
    std::iota(parent.begin(), parent.end(), 0);
    const auto root = [&](int node) { while (parent[node] != node) { parent[node] = parent[parent[node]]; node = parent[node]; } return node; };
    for (const auto &element : elements) for (int corner = 1; corner < 8; ++corner) parent[root(element[corner])] = root(element[0]);
    QMap<int, std::vector<int>> supports;
    for (const int node : held) supports[root(node)].push_back(node);
    QSet<int> components;
    for (int node = 0; node < static_cast<int>(positions.size()); ++node) components.insert(root(node));
    for (const int component : components) {
        const auto nodes = supports.value(component);
        bool constrained = false;
        if (nodes.size() >= 3) {
            const auto &origin = positions[nodes[0]];
            const auto &second = positions[nodes[1]];
            const gp_Vec along(second[0] - origin[0], second[1] - origin[1], second[2] - origin[2]);
            for (size_t index = 2; index < nodes.size(); ++index) {
                const auto &point = positions[nodes[index]];
                if (along.Crossed(gp_Vec(point[0] - origin[0], point[1] - origin[1], point[2] - origin[2])).Magnitude() > grid.step * grid.step * 1e-6) { constrained = true; break; }
            }
        }
        if (!constrained) fail("Static mesh has an unsupported or underconstrained connected component");
    }
    const double lame = young * poisson / ((1 + poisson) * (1 - 2 * poisson)), shear = young / (2 * (1 + poisson));
    ElasticMatrix material{};
    for (int row = 0; row < 3; ++row) for (int column = 0; column < 3; ++column) material[row][column] = lame + (row == column ? 2 * shear : 0);
    for (int index = 3; index < 6; ++index) material[index][index] = shear;
    StiffnessMatrix stiffness{};
    const double gauss = 1 / std::sqrt(3.0);
    for (const double first : {-gauss, gauss}) for (const double second : {-gauss, gauss}) for (const double third : {-gauss, gauss}) {
        const auto strain = strainMatrix({first, second, third}, grid.step);
        for (int row = 0; row < 24; ++row) for (int column = 0; column < 24; ++column)
            for (int stress = 0; stress < 6; ++stress) for (int component = 0; component < 6; ++component)
                stiffness[row][column] += strain[stress][row] * material[stress][component] * strain[component][column] * std::pow(grid.step / 2, 3);
    }
    const size_t degrees = positions.size() * 3;
    std::vector<bool> fixed(degrees);
    for (const int node : held) for (int axis = 0; axis < 3; ++axis) fixed[static_cast<size_t>(node) * 3 + axis] = true;
    std::vector<double> load(degrees), diagonal(degrees), displacement(degrees);
    for (const int node : pushed) for (int axis = 0; axis < 3; ++axis) load[static_cast<size_t>(node) * 3 + axis] = force[axis] / pushed.size();
    for (const auto &element : elements) for (int corner = 0; corner < 8; ++corner) for (int axis = 0; axis < 3; ++axis)
        diagonal[static_cast<size_t>(element[corner]) * 3 + axis] += stiffness[corner * 3 + axis][corner * 3 + axis];
    const auto multiply = [&](const std::vector<double> &input) {
        std::vector<double> result(degrees);
        for (const auto &element : elements) {
            std::array<double, 24> local{};
            for (int corner = 0; corner < 8; ++corner) for (int axis = 0; axis < 3; ++axis) local[corner * 3 + axis] = input[static_cast<size_t>(element[corner]) * 3 + axis];
            for (int row = 0; row < 24; ++row) {
                double value = 0;
                for (int column = 0; column < 24; ++column) value += stiffness[row][column] * local[column];
                result[static_cast<size_t>(element[row / 3]) * 3 + row % 3] += value;
            }
        }
        for (size_t index = 0; index < degrees; ++index) if (fixed[index]) result[index] = 0;
        return result;
    };
    const auto dot = [](const std::vector<double> &first, const std::vector<double> &second) { return std::inner_product(first.begin(), first.end(), second.begin(), 0.0); };
    auto residual = load;
    std::vector<double> preconditioned(degrees), direction(degrees);
    for (size_t index = 0; index < degrees; ++index) if (!fixed[index]) preconditioned[index] = residual[index] / diagonal[index];
    direction = preconditioned;
    double product = dot(residual, preconditioned), relativeResidual = 1;
    const double loadNorm = std::sqrt(dot(load, load));
    const int maximumIterations = args.value("max_iterations").toInt(4000);
    const double timeLimit = number(args, "time_limit_seconds", 60, true);
    if (maximumIterations < 1 || maximumIterations > 10000) fail("Static iteration limit must be between 1 and 10000");
    QElapsedTimer timer;
    timer.start();
    int iterations = 0;
    for (; iterations < maximumIterations && relativeResidual > 1e-7; ++iterations) {
        if (timer.elapsed() / 1000.0 > timeLimit) fail("Static solve exceeded its time limit without verified convergence");
        const auto result = multiply(direction);
        const double curvature = dot(direction, result);
        if (!std::isfinite(curvature) || curvature <= 0 || !std::isfinite(product)) fail("Static system is singular or indefinite");
        const double alpha = product / curvature;
        for (size_t index = 0; index < degrees; ++index) {
            displacement[index] += alpha * direction[index];
            residual[index] -= alpha * result[index];
        }
        relativeResidual = std::sqrt(dot(residual, residual)) / loadNorm;
        if (relativeResidual <= 1e-7) break;
        for (size_t index = 0; index < degrees; ++index) preconditioned[index] = fixed[index] ? 0 : residual[index] / diagonal[index];
        const double nextProduct = dot(residual, preconditioned), beta = nextProduct / product;
        for (size_t index = 0; index < degrees; ++index) direction[index] = preconditioned[index] + beta * direction[index];
        product = nextProduct;
    }
    if (!std::isfinite(relativeResidual) || relativeResidual > 1e-7) fail("Static finite element solve did not converge");
    const auto verified = multiply(displacement);
    double squaredResidual = 0;
    for (size_t index = 0; index < degrees; ++index) squaredResidual += std::pow(verified[index] - load[index], 2);
    relativeResidual = std::sqrt(squaredResidual) / loadNorm;
    if (!std::isfinite(relativeResidual) || relativeResidual > 5e-7) fail("Static residual verification failed");
    std::array<StrainMatrix, 8> corners;
    for (int corner = 0; corner < 8; ++corner) corners[corner] = strainMatrix({static_cast<double>(cornerSigns[corner][0]), static_cast<double>(cornerSigns[corner][1]), static_cast<double>(cornerSigns[corner][2])}, grid.step);
    std::vector<std::array<double, 6>> stresses(positions.size());
    std::vector<int> shares(positions.size());
    for (const auto &element : elements) {
        std::array<double, 24> local{};
        for (int corner = 0; corner < 8; ++corner) for (int axis = 0; axis < 3; ++axis) local[corner * 3 + axis] = displacement[static_cast<size_t>(element[corner]) * 3 + axis];
        for (int corner = 0; corner < 8; ++corner) {
            std::array<double, 6> strain{};
            for (int component = 0; component < 6; ++component) for (int degree = 0; degree < 24; ++degree) strain[component] += corners[corner][component][degree] * local[degree];
            for (int stress = 0; stress < 6; ++stress) for (int component = 0; component < 6; ++component) stresses[element[corner]][stress] += material[stress][component] * strain[component];
            ++shares[element[corner]];
        }
    }
    std::vector<double> mises(positions.size());
    double maxDisplacement = 0;
    for (size_t node = 0; node < positions.size(); ++node) {
        auto stress = stresses[node];
        for (double &value : stress) value /= shares[node];
        mises[node] = std::sqrt(0.5 * (std::pow(stress[0] - stress[1], 2) + std::pow(stress[1] - stress[2], 2) + std::pow(stress[2] - stress[0], 2)) + 3 * (stress[3] * stress[3] + stress[4] * stress[4] + stress[5] * stress[5]));
        maxDisplacement = std::max(maxDisplacement, std::hypot(displacement[node * 3], displacement[node * 3 + 1], displacement[node * 3 + 2]));
    }
    const double cap = percentile(mises, 0.99);
    for (const int node : held) mises[node] = std::min(mises[node], cap);
    const double peak = *std::max_element(mises.begin(), mises.end()), top = mises.size() > 200 ? percentile(mises, 0.995) : peak;
    QJsonArray shownStress, shownMove;
    for (const auto &entry : vertices) {
        const auto point = coordinates(entry);
        auto nearby = nearNodes(point, grid.step * 2);
        if (nearby.empty()) {
            nearby.resize(positions.size());
            std::iota(nearby.begin(), nearby.end(), 0);
        }
        int nearest = -1;
        double closest = 1e300;
        for (const int node : nearby) {
            const auto &position = positions[node];
            const double distance = std::pow(point[0] - position[0], 2) + std::pow(point[1] - position[1], 2) + std::pow(point[2] - position[2], 2);
            if (distance < closest) { closest = distance; nearest = node; }
        }
        shownStress.append(mises[nearest]);
        shownMove.append(QJsonArray{displacement[static_cast<size_t>(nearest) * 3], displacement[static_cast<size_t>(nearest) * 3 + 1], displacement[static_cast<size_t>(nearest) * 3 + 2]});
    }
    return {{"max_stress", top}, {"peak_stress", peak}, {"max_displacement", maxDisplacement},
        {"safety", yield > 0 && top > 0 ? QJsonValue(yield / top) : QJsonValue(QJsonValue::Null)},
        {"cells", static_cast<int>(elements.size())}, {"nodes", static_cast<int>(positions.size())}, {"cell_size", grid.step},
        {"stress", shownStress}, {"move", shownMove}, {"mesh", QJsonObject{{"verts", vertices}, {"normals", display["normals"]}, {"tris", triangles}, {"stress", shownStress}}},
        {"approximate", true}, {"certified", false}, {"converged", true}, {"iterations", iterations + 1}, {"relative_residual", relativeResidual},
        {"method", "voxel eight-node linear elastic hexahedra, 2x2x2 integration, Jacobi preconditioned conjugate gradients"},
        {"limitations", QJsonArray{"Voxel stair-step geometry and pointwise nodal load approximation", "Linear isotropic small-strain elasticity only", "Display uses original surface tessellation with nearest-node stress", "No plasticity, contact, buckling or fatigue"}}};
}
}
#endif
