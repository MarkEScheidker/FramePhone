#pragma once
#include <array>
#include <cmath>
#include <nlohmann/json.hpp>
#include <optional>
#include <stdexcept>

namespace framephone::surface {
using Matrix = std::array<double, 12>;
inline Matrix identity() {
    return {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
}
inline Matrix compose(const Matrix &a, const Matrix &b) {
    Matrix out{};
    for (int row = 0; row < 3; ++row) {
        for (int col = 0; col < 3; ++col)
            for (int k = 0; k < 3; ++k)
                out[row * 4 + col] += a[row * 4 + k] * b[k * 4 + col];
        out[row * 4 + 3] = a[row * 4 + 3];
        for (int k = 0; k < 3; ++k)
            out[row * 4 + 3] += a[row * 4 + k] * b[k * 4 + 3];
    }
    return out;
}
inline std::optional<Matrix> pose(const nlohmann::json &message, std::uint64_t now) {
    if (message.value("status", "") != "measured")
        return {};
    if (message.at("schema") != "framephone-fiducial-pose-v1" || message.at("transform") != "T_HM")
        throw std::runtime_error("unsupported VR pose coordinates");
    const auto &stamp = message.at("processed_host_monotonic_ns");
    if (!stamp.is_number_unsigned())
        throw std::runtime_error("invalid VR pose clock");
    auto time = stamp.get<std::uint64_t>();
    if (time > now || now - time > 250'000'000)
        return {};
    const auto &best = message.at("candidates").at(0);
    auto rotation = best.at("rotation").get<std::array<double, 9>>();
    auto translation = best.at("translation_m").get<std::array<double, 3>>();
    Matrix out{};
    for (int row = 0; row < 3; ++row) {
        for (int col = 0; col < 3; ++col)
            out[row * 4 + col] = rotation[row * 3 + col];
        out[row * 4 + 3] = translation[row];
    }
    for (double value : out)
        if (!std::isfinite(value))
            throw std::runtime_error("nonfinite VR pose");
    for (int a = 0; a < 3; ++a)
        for (int b = 0; b < 3; ++b) {
            double dot = 0;
            for (int k = 0; k < 3; ++k)
                dot += rotation[a * 3 + k] * rotation[b * 3 + k];
            if (std::abs(dot - (a == b ? 1 : 0)) > .001)
                throw std::runtime_error("invalid VR rotation");
        }
    double determinant = rotation[0] * (rotation[4] * rotation[8] - rotation[5] * rotation[7]) -
                         rotation[1] * (rotation[3] * rotation[8] - rotation[5] * rotation[6]) +
                         rotation[2] * (rotation[3] * rotation[7] - rotation[4] * rotation[6]);
    if (std::abs(determinant - 1) > .001 ||
        std::hypot(translation[0], translation[1], translation[2]) > 10)
        throw std::runtime_error("invalid VR transform");
    return out;
}
struct Geometry {
    double width{}, height{}, depth{}, black_edge{};
    static Geometry from_session(const nlohmann::json &config) {
        if (config.at("schema") != "framephone-fiducial-session-v1")
            throw std::runtime_error("unsupported VR session");
        const auto &target = config.at("fiducial");
        double edge = target.at("black_edge_m");
        double width = target.value("screen_width_px", 10);
        double height = target.value("screen_height_px", 10);
        double black = target.value("black_edge_px", 8);
        Geometry result{edge * width / black, edge * height / black,
                        config.value("thickness_m", .008), edge};
        if (!std::isfinite(edge) || edge < .01 || edge > .2 || black <= 0 || width <= 0 ||
            height < width || !std::isfinite(result.width) || !std::isfinite(result.height) ||
            !std::isfinite(result.depth) || result.width < .01 || result.width > .3 ||
            result.height > .8 || result.depth < .001 || result.depth > .1)
            throw std::runtime_error("invalid VR surface dimensions");
        return result;
    }
};
struct Face {
    Matrix transform;
    double width, height;
};
inline std::array<Face, 6> faces(Geometry g) {
    return {{{identity(), g.width, g.height},
             {{-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, -g.depth}, g.width, g.height},
             {{0, 0, -1, -g.width / 2, 0, 1, 0, 0, 1, 0, 0, -g.depth / 2}, g.depth, g.height},
             {{0, 0, 1, g.width / 2, 0, 1, 0, 0, -1, 0, 0, -g.depth / 2}, g.depth, g.height},
             {{1, 0, 0, 0, 0, 0, 1, g.height / 2, 0, -1, 0, -g.depth / 2}, g.width, g.depth},
             {{1, 0, 0, 0, 0, 0, -1, -g.height / 2, 0, 1, 0, -g.depth / 2}, g.width, g.depth}}};
}
} // namespace framephone::surface
