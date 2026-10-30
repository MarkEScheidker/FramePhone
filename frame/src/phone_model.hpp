#pragma once
#include "arcore_handoff.hpp"
#include <iomanip>
#include <sstream>
#include <string_view>
#include <vector>

namespace framephone::surface {
enum class PhoneFace { body, back, screen, edge };
using Vertex = std::array<double, 3>;
struct Surface {
    Matrix local;
    double width, height;
    PhoneFace kind;
    // Empty for rectangles; otherwise normalized texture coordinates (top down).
    std::vector<std::array<double, 2>> mask;
};
inline Vertex subtract(const Vertex &a, const Vertex &b) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}
inline double dot(const Vertex &a, const Vertex &b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}
inline Vertex cross(const Vertex &a, const Vertex &b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
inline Vertex unit(Vertex value) {
    const double length = std::sqrt(dot(value, value));
    for (auto &v : value)
        v /= length;
    return value;
}
inline Surface rectangle(const Vertex &center, const Vertex &x, const Vertex &y, double width,
                         double height, PhoneFace kind) {
    const auto z = cross(x, y);
    return {{x[0], y[0], z[0], center[0], x[1], y[1], z[1], center[1], x[2], y[2], z[2], center[2]},
            width,
            height,
            kind,
            {}};
}
inline Surface triangle(const Vertex &a, Vertex b, Vertex c, const Vertex &core) {
    auto x = unit(subtract(b, a)), normal = unit(cross(x, subtract(c, a)));
    if (dot(normal, subtract(a, core)) < 0) {
        std::swap(b, c);
        x = unit(subtract(b, a));
        normal = unit(cross(x, subtract(c, a)));
    }
    const auto y = cross(normal, x), ab = subtract(b, a), ac = subtract(c, a);
    const double bx = dot(ab, x), cx = dot(ac, x), cy = dot(ac, y);
    const double left = std::min(0., cx), right = std::max(bx, cx), width = right - left;
    Vertex center{};
    for (int k = 0; k < 3; ++k)
        center[k] = a[k] + x[k] * (left + right) / 2 + y[k] * cy / 2;
    auto out = rectangle(center, x, y, width, cy, PhoneFace::edge);
    out.mask = {{{-left / width, 1}, {(bx - left) / width, 1}, {(cx - left) / width, 0}}};
    return out;
}

/** Rounded box = inset rectangular core + a 2mm sphere. Flat faces, all twelve
 * quarter-cylinder edges, and eight spherical corners share their vertices.
 * Short facets approximate the curves without an extra graphics dependency. */
struct PhoneModel {
    Geometry screen;
    static constexpr double radius = .002, bezel = radius + .0005, depth = .010;
    static constexpr double front_z = -.00005;
    double width() const {
        return screen.width + 2 * bezel;
    }
    double height() const {
        return screen.height + 2 * bezel;
    }
    Vertex core_size() const {
        return {width() / 2 - radius, height() / 2 - radius, depth / 2 - radius};
    }
    std::vector<Surface> surfaces() const {
        const auto core = core_size();
        const Vertex center{0, 0, front_z - depth / 2};
        std::vector<Surface> out{rectangle({0, 0, front_z}, {1, 0, 0}, {0, 1, 0}, 2 * core[0],
                                           2 * core[1], PhoneFace::body),
                                 rectangle({0, 0, front_z - depth}, {-1, 0, 0}, {0, 1, 0},
                                           2 * core[0], 2 * core[1], PhoneFace::back),
                                 rectangle({0, 0, 0}, {1, 0, 0}, {0, 1, 0}, screen.width,
                                           screen.height, PhoneFace::screen)};
        for (int axis = 0; axis < 2; ++axis)
            for (int sign : {-1, 1}) {
                Vertex position = center, x{}, y{0, 0, 1};
                position[axis] += sign * (core[axis] + radius);
                x[1 - axis] = axis == 0 ? sign : -sign;
                out.push_back(
                    rectangle(position, x, y, 2 * core[1 - axis], 2 * core[2], PhoneFace::edge));
            }
        constexpr double pi = 3.14159265358979323846;
        // Two segments per quarter-circle. All vertices are on the 2mm surface;
        // the maximum edge chord error is 0.15mm.
        for (int axis = 0; axis < 3; ++axis) {
            const int u = (axis + 1) % 3, v = (axis + 2) % 3;
            for (int su : {-1, 1})
                for (int sv : {-1, 1})
                    for (int step = 0; step < 2; ++step) {
                        Vertex a = center, b = center, along{};
                        const double t0 = step * pi / 4, t1 = (step + 1) * pi / 4;
                        a[u] += su * (core[u] + radius * std::cos(t0));
                        a[v] += sv * (core[v] + radius * std::sin(t0));
                        b[u] += su * (core[u] + radius * std::cos(t1));
                        b[v] += sv * (core[v] + radius * std::sin(t1));
                        auto tangent = unit(subtract(b, a));
                        along[axis] = 1;
                        Vertex middle{};
                        for (int k = 0; k < 3; ++k)
                            middle[k] = (a[k] + b[k]) / 2;
                        if (dot(cross(tangent, along), subtract(middle, center)) < 0)
                            along[axis] = -1;
                        out.push_back(rectangle(middle, tangent, along,
                                                std::sqrt(dot(subtract(b, a), subtract(b, a))),
                                                2 * core[axis], PhoneFace::edge));
                    }
        }
        for (int sx : {-1, 1})
            for (int sy : {-1, 1})
                for (int sz : {-1, 1}) {
                    Vertex corner{sx * core[0], sy * core[1], center[2] + sz * core[2]};
                    auto point = [&](double x, double y, double z) {
                        auto n = unit({sx * x, sy * y, sz * z});
                        for (int k = 0; k < 3; ++k)
                            n[k] = corner[k] + radius * n[k];
                        return n;
                    };
                    const auto x = point(1, 0, 0), y = point(0, 1, 0), z = point(0, 0, 1);
                    const auto xy = point(1, 1, 0), xz = point(1, 0, 1), yz = point(0, 1, 1);
                    for (const auto &vertices : std::array<std::array<Vertex, 3>, 4>{
                             {{x, xy, xz}, {xy, y, yz}, {xz, yz, z}, {xy, yz, xz}}})
                        out.push_back(triangle(vertices[0], vertices[1], vertices[2], corner));
                }
        return out;
    }
};

inline bool facing(const Matrix &surface, const std::array<double, 3> &eye) {
    double dot = 0;
    for (int r = 0; r < 3; ++r)
        dot += surface[r * 4 + 2] * (eye[r] - surface[r * 4 + 3]);
    return dot > 0;
}

struct Image {
    unsigned width, height;
    std::vector<std::uint8_t> rgba;
    Image(unsigned w, unsigned h, std::uint8_t grey) : width(w), height(h), rgba(w * h * 4) {
        for (std::size_t i = 0; i < rgba.size(); i += 4) {
            rgba[i] = rgba[i + 1] = rgba[i + 2] = grey;
            rgba[i + 3] = 255;
        }
    }
};

inline Image surface_texture(const PhoneModel &model, const Surface &surface) {
    const bool front = surface.kind == PhoneFace::body;
    const auto grey = std::uint8_t(42 + 6 * std::abs(surface.local[10]) + 3 * surface.local[6]);
    Image image(front ? 256 : (surface.mask.empty() ? 1 : 64),
                front ? 512 : (surface.mask.empty() ? 1 : 64), grey);
    for (unsigned y = 0; y < image.height; ++y)
        for (unsigned x = 0; x < image.width; ++x) {
            const double u = (x + .5) / image.width, v = (y + .5) / image.height;
            bool inside = true;
            if (front && std::abs(u - .5) * surface.width < model.screen.width / 2 &&
                std::abs(v - .5) * surface.height < model.screen.height / 2)
                inside = false;
            if (!surface.mask.empty()) {
                const auto &a = surface.mask[0], &b = surface.mask[1], &c = surface.mask[2];
                auto edge = [u, v](const auto &p, const auto &q) {
                    return (q[0] - p[0]) * (v - p[1]) - (q[1] - p[1]) * (u - p[0]);
                };
                inside = (edge(a, b) <= 0 && edge(b, c) <= 0 && edge(c, a) <= 0);
            }
            if (!inside)
                image.rgba[(y * image.width + x) * 4 + 3] = 0;
        }
    return image;
}

// Small built-in bitmap alphabet keeps the diagnostic back independent of font
// services, graphics contexts and additional runtime packages.
inline std::array<unsigned, 7> glyph(char c) {
    switch (c) {
    case 'A':
        return {14, 17, 17, 31, 17, 17, 17};
    case 'B':
        return {30, 17, 17, 30, 17, 17, 30};
    case 'C':
        return {14, 17, 16, 16, 16, 17, 14};
    case 'D':
        return {30, 17, 17, 17, 17, 17, 30};
    case 'E':
        return {31, 16, 16, 30, 16, 16, 31};
    case 'F':
        return {31, 16, 16, 30, 16, 16, 16};
    case 'G':
        return {14, 17, 16, 23, 17, 17, 15};
    case 'H':
        return {17, 17, 17, 31, 17, 17, 17};
    case 'I':
        return {14, 4, 4, 4, 4, 4, 14};
    case 'J':
        return {7, 2, 2, 2, 18, 18, 12};
    case 'K':
        return {17, 18, 20, 24, 20, 18, 17};
    case 'L':
        return {16, 16, 16, 16, 16, 16, 31};
    case 'M':
        return {17, 27, 21, 21, 17, 17, 17};
    case 'N':
        return {17, 25, 21, 19, 17, 17, 17};
    case 'O':
        return {14, 17, 17, 17, 17, 17, 14};
    case 'P':
        return {30, 17, 17, 30, 16, 16, 16};
    case 'Q':
        return {14, 17, 17, 17, 21, 18, 13};
    case 'R':
        return {30, 17, 17, 30, 20, 18, 17};
    case 'S':
        return {15, 16, 16, 14, 1, 1, 30};
    case 'T':
        return {31, 4, 4, 4, 4, 4, 4};
    case 'U':
        return {17, 17, 17, 17, 17, 17, 14};
    case 'V':
        return {17, 17, 17, 17, 17, 10, 4};
    case 'W':
        return {17, 17, 17, 21, 21, 21, 10};
    case 'X':
        return {17, 17, 10, 4, 10, 17, 17};
    case 'Y':
        return {17, 17, 10, 4, 4, 4, 4};
    case 'Z':
        return {31, 1, 2, 4, 8, 16, 31};
    case '0':
        return {14, 17, 19, 21, 25, 17, 14};
    case '1':
        return {4, 12, 4, 4, 4, 4, 14};
    case '2':
        return {14, 17, 1, 2, 4, 8, 31};
    case '3':
        return {30, 1, 1, 14, 1, 1, 30};
    case '4':
        return {2, 6, 10, 18, 31, 2, 2};
    case '5':
        return {31, 16, 16, 30, 1, 1, 30};
    case '6':
        return {14, 16, 16, 30, 17, 17, 14};
    case '7':
        return {31, 1, 2, 4, 8, 8, 8};
    case '8':
        return {14, 17, 17, 14, 17, 17, 14};
    case '9':
        return {14, 17, 17, 15, 1, 1, 14};
    case '-':
        return {0, 0, 0, 31, 0, 0, 0};
    case '.':
        return {0, 0, 0, 0, 0, 12, 12};
    case '%':
        return {25, 25, 2, 4, 8, 19, 19};
    default:
        return {};
    }
}
inline void text(Image &image, unsigned x, unsigned y, std::string_view value) {
    for (char c : value) {
        const auto rows = glyph(c);
        for (unsigned r = 0; r < 7; ++r)
            for (unsigned col = 0; col < 5; ++col)
                if (rows[r] & (1 << (4 - col)))
                    for (unsigned dy = 0; dy < 2; ++dy)
                        for (unsigned dx = 0; dx < 2; ++dx) {
                            const unsigned px = x + col * 2 + dx, py = y + r * 2 + dy;
                            if (px < image.width && py < image.height) {
                                const auto offset = (py * image.width + px) * 4;
                                image.rgba[offset] = image.rgba[offset + 1] =
                                    image.rgba[offset + 2] = 220;
                            }
                        }
        x += 12;
    }
}
struct PhoneDiagnostics {
    bool arcore = false, tracking = false, gyro = false;
    double pose_hz = 0, age_ms = 0, prediction_ms = 0, opacity = 1;
};
inline Image diagnostic_texture(const PhoneModel &model, const PhoneDiagnostics &d) {
    Image image(256, 512, 48);
    unsigned y = 44;
    auto line = [&](const std::string &value) {
        text(image, 20, y, value);
        y += 32;
    };
    auto number = [](double value) {
        std::ostringstream out;
        out << std::fixed << std::setprecision(0) << std::clamp(value, 0., 9999.);
        return out.str();
    };
    line("FRAMEPHONE");
    y += 16;
    line(d.tracking ? (d.arcore ? "ARCORE LIVE" : "OPTICAL LIVE") : "TRACKING LOST");
    line("POSE " + number(d.pose_hz) + " HZ");
    line("AGE " + number(d.age_ms) + " MS");
    line("PRED " + number(d.prediction_ms) + " MS");
    line(d.gyro ? "GYRO ON" : "GYRO HOLD");
    line("VISIBLE " + number(d.opacity * 100) + " %");
    y += 16;
    line(number(model.screen.width * 1000) + " X " + number(model.screen.height * 1000) + " MM");
    return image;
}
} // namespace framephone::surface
