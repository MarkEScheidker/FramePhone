#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <nlohmann/json.hpp>
#include <optional>
#include <stdexcept>

namespace framephone::surface {
using Matrix = std::array<double, 12>;
inline std::optional<Matrix> pose(const nlohmann::json &message, std::uint64_t now,
                                  std::uint64_t max_age = 250'000'000) {
    if (message.value("status", "") != "measured")
        return {};
    if (message.at("schema") != "framephone-fiducial-pose-v1" || message.at("transform") != "T_HM")
        throw std::runtime_error("unsupported VR pose coordinates");
    const auto &stamp = message.at("processed_host_monotonic_ns");
    if (!stamp.is_number_unsigned())
        throw std::runtime_error("invalid VR pose clock");
    auto time = stamp.get<std::uint64_t>();
    if (time > now || now - time > max_age)
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
    double width{}, height{};
    static Geometry from_session(const nlohmann::json &config) {
        if (config.at("schema") != "framephone-fiducial-session-v1")
            throw std::runtime_error("unsupported VR session");
        const auto &target = config.at("fiducial");
        for (const auto *key : {"screen_width_px", "screen_height_px", "black_edge_px"})
            if (!target.contains(key))
                throw std::runtime_error(
                    "Phone screen dimensions unavailable; update the Android app and reconnect");
        double edge = target.at("black_edge_m");
        double width = target.at("screen_width_px");
        double height = target.at("screen_height_px");
        double black = target.at("black_edge_px");
        if (!std::isfinite(edge) || edge < .01 || edge > .2 || !std::isfinite(width) ||
            !std::isfinite(height) || !std::isfinite(black) || black <= 0 || black > width ||
            width <= 0 || height < width)
            throw std::runtime_error("invalid VR screen dimensions");
        Geometry result{edge * width / black, edge * height / black};
        if (!std::isfinite(result.width) || !std::isfinite(result.height) || result.width < .01 ||
            result.width > .3 || result.height > .8)
            throw std::runtime_error("invalid VR screen dimensions");
        return result;
    }
    // A square texture is stretched to this physical aspect ratio by OpenVR.
    double texel_aspect() const {
        return width / height;
    }
};

inline constexpr unsigned texture_size = 64;
inline std::array<std::uint8_t, texture_size * texture_size * 4> texture() {
    std::array<std::uint8_t, texture_size * texture_size * 4> pixels{};
    for (unsigned y = 0; y < texture_size; ++y)
        for (unsigned x = 0; x < texture_size; ++x) {
            const bool border = x < 2 || y < 2 || x + 2 >= texture_size || y + 2 >= texture_size;
            auto *pixel = &pixels[(y * texture_size + x) * 4];
            pixel[0] = 40;
            pixel[1] = border ? 230 : 150;
            pixel[2] = border ? 150 : 220;
            pixel[3] = border ? 255 : 100;
        }
    return pixels;
}
} // namespace framephone::surface
