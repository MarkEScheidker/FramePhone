#pragma once
#include "arcore_handoff.hpp"

namespace framephone::surface {
struct PredictedPose {
    Matrix pose;
    double milliseconds = 0;
    bool gyro = false;
};

inline Matrix angular_step(const std::array<double, 3> &w, double seconds) {
    auto rotation = identity();
    const double magnitude = std::hypot(w[0], w[1], w[2]);
    if (!std::isfinite(magnitude) || magnitude > 35)
        throw std::runtime_error("invalid gyro angular velocity");
    const double theta = magnitude * seconds;
    if (theta < 1e-12)
        return rotation;
    const double x = w[0] / magnitude, y = w[1] / magnitude, z = w[2] / magnitude;
    const double c = std::cos(theta), s = std::sin(theta), v = 1 - c;
    rotation = {c + x * x * v,     x * y * v - z * s, x * z * v + y * s, 0,
                y * x * v + z * s, c + y * y * v,     y * z * v - x * s, 0,
                z * x * v - y * s, z * y * v + x * s, c + z * z * v,     0};
    return rotation;
}

/** Recompute from an ARCore measurement on every render. Predicted values never
 * feed registration or become the next measurement; no unbounded integration. */
inline PredictedPose predict_pose(const Matrix &world, const nlohmann::json &phone,
                                  std::uint64_t now) {
    PredictedPose out{world};
    const auto &poses = phone.at("poses");
    const auto &latest = poses.back();
    const auto base = pose_time_ns(latest);
    if (base < 0 || std::int64_t(now) <= base || std::int64_t(now) - base > 250'000'000)
        return out;
    const auto age = std::int64_t(now) - base;
    if (poses.size() >= 2) {
        const auto &previous = poses[poses.size() - 2];
        const auto dt = base - pose_time_ns(previous);
        if (previous.at("state") == "tracking" &&
            previous.at("generation") == latest.at("generation") &&
            previous.at("acquisition") == latest.at("acquisition") && dt >= 5'000'000 &&
            dt <= 200'000'000) {
            const auto current_device = phone_pose(latest), previous_device = phone_pose(previous);
            std::array<double, 3> velocity{};
            for (int k = 0; k < 3; ++k)
                velocity[k] =
                    (current_device[k * 4 + 3] - previous_device[k * 4 + 3]) / (double(dt) / 1e9);
            const double speed = std::hypot(velocity[0], velocity[1], velocity[2]);
            if (speed <= 3) {
                const auto world_anchor = compose(world, inverse(current_device));
                const double seconds = std::min(age, std::int64_t(60'000'000)) / 1e9;
                const double scale = speed * seconds > .04 ? .04 / (speed * seconds) : 1;
                for (int r = 0; r < 3; ++r)
                    for (int k = 0; k < 3; ++k)
                        out.pose[r * 4 + 3] +=
                            world_anchor[r * 4 + k] * velocity[k] * seconds * scale;
                out.milliseconds = seconds * 1000;
            }
        }
    }
    // Raw IMU rotation requires a verified camera/IMU epoch, not ARCore's
    // unspecified frame timestamp or the later update-completion timestamp.
    if (!latest.contains("capture_t_ns") || !phone.contains("gyro") || phone.at("gyro").empty())
        return out;
    const auto &samples = phone.at("gyro");
    if (!samples.is_array() || samples.size() > 64)
        throw std::runtime_error("invalid gyro history");
    const auto last_time = samples.back().at("host_t_ns").get<std::int64_t>();
    if (last_time > std::int64_t(now) + 5'000'000 || std::int64_t(now) - last_time > 25'000'000)
        return out;
    const auto target = std::min({std::int64_t(now), base + 80'000'000, last_time + 10'000'000});
    std::size_t index = 0;
    while (index + 1 < samples.size() &&
           samples[index + 1].at("host_t_ns").get<std::int64_t>() <= base)
        ++index;
    auto cursor = std::max(base, samples[index].at("host_t_ns").get<std::int64_t>());
    if (std::abs(samples[index].at("host_t_ns").get<std::int64_t>() - base) > 10'000'000 ||
        cursor >= target)
        return out;
    Matrix rotation = identity();
    double total_angle = 0;
    const auto start = cursor;
    while (cursor < target) {
        const auto &sample = samples[index];
        const auto stamp = sample.at("host_t_ns").get<std::int64_t>();
        const auto end =
            index + 1 < samples.size()
                ? std::min(target, samples[index + 1].at("host_t_ns").get<std::int64_t>())
                : target;
        if (end <= cursor || end - stamp > 25'000'000)
            return out;
        const auto w = sample.at("w_rad_s").get<std::array<double, 3>>();
        const double seconds = double(end - cursor) / 1e9;
        total_angle += std::hypot(w[0], w[1], w[2]) * seconds;
        if (!std::isfinite(total_angle) || total_angle > .35)
            return out;
        rotation = compose(rotation, angular_step(w, seconds));
        cursor = end;
        if (index + 1 < samples.size())
            ++index;
    }
    const auto corrected = compose(world, rotation);
    for (int r = 0; r < 3; ++r)
        for (int c = 0; c < 3; ++c)
            out.pose[r * 4 + c] = corrected[r * 4 + c];
    out.gyro = true;
    out.milliseconds = std::max(out.milliseconds, double(cursor - start) / 1e6);
    return out;
}
} // namespace framephone::surface
