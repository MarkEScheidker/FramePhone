#pragma once
#include "vr_surface.hpp"
#include <algorithm>
#include <deque>
#include <string>
#include <utility>

namespace framephone::surface {
inline std::int64_t pose_time_ns(const nlohmann::json &sample) {
    return sample.value("pose_host_t_ns", sample.at("host_t_ns").get<std::int64_t>());
}
inline Matrix identity() {
    return {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
}
inline Matrix compose(const Matrix &a, const Matrix &b) {
    Matrix out{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c)
            for (int k = 0; k < 3; ++k)
                out[r * 4 + c] += a[r * 4 + k] * b[k * 4 + c];
        out[r * 4 + 3] = a[r * 4 + 3];
        for (int k = 0; k < 3; ++k)
            out[r * 4 + 3] += a[r * 4 + k] * b[k * 4 + 3];
    }
    return out;
}
inline Matrix inverse(const Matrix &a) {
    Matrix out{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c)
            out[r * 4 + c] = a[c * 4 + r];
        for (int k = 0; k < 3; ++k)
            out[r * 4 + 3] -= out[r * 4 + k] * a[k * 4 + 3];
    }
    return out;
}
inline bool near(const Matrix &a, const Matrix &b, double distance = .01, double angle = .025) {
    auto delta = compose(inverse(a), b);
    return std::hypot(delta[3], delta[7], delta[11]) <= distance &&
           std::acos(std::clamp((delta[0] + delta[5] + delta[10] - 1) / 2, -1., 1.)) <= angle;
}
inline Matrix phone_pose(const nlohmann::json &sample) {
    const auto q = sample.at("quaternion_xyzw").get<std::array<double, 4>>();
    const auto p = sample.at("translation_m").get<std::array<double, 3>>();
    double norm = 0;
    for (auto value : q) {
        if (!std::isfinite(value))
            throw std::runtime_error("nonfinite ARCore rotation");
        norm += value * value;
    }
    if (std::abs(norm - 1) > .002)
        throw std::runtime_error("invalid ARCore quaternion");
    for (auto value : p)
        if (!std::isfinite(value) || std::abs(value) > 10000)
            throw std::runtime_error("invalid ARCore translation");
    const double x = q[0], y = q[1], z = q[2], w = q[3];
    return {1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w),     p[0],
            2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w),     p[1],
            2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y), p[2]};
}

/** Relative-stability acquisition prototype. Factory/runtime head and sensor/screen
 * origins are provisional; update timestamps do not claim calibrated exposure
 * clocks. Never preserve an alignment through unknown tracking resets. */
class ArcoreHandoff {
  public:
    using Json = nlohmann::json;
    Json state{{"state", "acquiring"}, {"reason", "waiting for ARCore"}};
    void reset(const std::string &reason) {
        world_anchor_.reset();
        count_ = 0;
        relative_positions_.clear();
        state["state"] = "acquiring";
        state["reason"] = reason;
    }
    void head(std::uint64_t stamp, const Matrix &value) {
        heads_.push_back({stamp, value});
        while (heads_.size() > 180)
            heads_.pop_front();
    }
    std::optional<Matrix> update(const Json &phone, const Json &optical, std::uint64_t now) {
        if (phone.value("schema", "") != "framephone-arcore-v1" ||
            !phone.value("clock_valid", false)) {
            reset("waiting for a low-RTT phone clock exchange");
            return {};
        }
        const auto &samples = phone.at("poses");
        if (!samples.is_array() || samples.empty() || samples.size() > 90) {
            reset("waiting for ARCore poses");
            return {};
        }
        const auto &latest = samples.back();
        const std::string key = phone.at("session").get<std::string>() + ":" +
                                latest.at("generation").get<std::string>() + ":" +
                                latest.at("acquisition").get<std::string>();
        if (key != key_) {
            reset("new phone session or marker acquisition");
            key_ = key;
            state["generation"] = latest.at("generation");
            state["acquisition"] = latest.at("acquisition");
        }
        const auto arrival = phone.at("received_host_monotonic_ns").get<std::uint64_t>();
        const auto stamp = pose_time_ns(latest);
        if (latest.at("state") != "tracking" || arrival > now || now - arrival > 250'000'000 ||
            stamp < 0 || stamp > std::int64_t(now) + 20'000'000 ||
            std::int64_t(now) - stamp > 250'000'000 || heads_.empty()) {
            reset("phone pose stale or ARCore tracking lost; show marker again");
            return {};
        }
        const auto current = phone_pose(latest);
        if (world_anchor_) {
            state["state"] = "tracking";
            state["reason"] = "ARCore pose; optical detection paused";
            return compose(*world_anchor_, current);
        }
        if (!latest.value("marker_required", true)) {
            state["reason"] = "alignment invalid; show marker again";
            return {};
        }
        // Acquisition can span slower detector updates. Rendering still requires
        // a fresh phone pose; an optical timeout between observations must not
        // repeatedly erase an otherwise stationary acquisition batch.
        const auto measured = pose(optical, now, 1'500'000'000);
        if (!measured) {
            reset("waiting for an accepted stereo marker pose");
            return {};
        }
        const auto observed = optical.at("observed_host_monotonic_ns").get<std::uint64_t>();
        if (observed > now || now - observed > 1'500'000'000 ||
            optical.at("candidates").at(0).at("rms_px").get<double>() > 2.5) {
            reset("optical observation too old or uncertain");
            return {};
        }
        auto h = std::min_element(
            heads_.begin(), heads_.end(), [observed](const auto &a, const auto &b) {
                return difference(a.first, observed) < difference(b.first, observed);
            });
        const Json *matched = nullptr;
        for (const auto &sample : samples)
            if (sample.at("state") == "tracking" &&
                sample.at("generation") == latest.at("generation") &&
                sample.at("acquisition") == latest.at("acquisition") &&
                (!matched || difference(pose_time_ns(sample), observed) <
                                 difference(pose_time_ns(*matched), observed)))
                matched = &sample;
        if (difference(h->first, observed) > 40'000'000 || !matched ||
            difference(pose_time_ns(*matched), observed) > 60'000'000) {
            reset("waiting for matching phone/headset pose history");
            return {};
        }
        const auto device = phone_pose(*matched);
        const auto candidate = compose(compose(h->second, *measured), inverse(device));
        // Stability is relative to the headset. Walking together must not be
        // rejected just because either device moved in its own world frame.
        const auto relative_now =
            compose(inverse(heads_.back().second), compose(candidate, current));
        const std::array<double, 3> position{(*measured)[3], (*measured)[7], (*measured)[11]};
        const auto moved = [](const auto &a, const auto &b) {
            return std::hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) > .08;
        };
        const std::array<double, 3> current_position{relative_now[3], relative_now[7],
                                                     relative_now[11]};
        bool unstable = moved(current_position, position);
        for (const auto &previous : relative_positions_)
            unstable = unstable || moved(previous, position) || moved(previous, current_position);
        if (!count_ || unstable || !near(base_alignment_, candidate, .05, .12)) {
            count_ = 1;
            last_ = observed;
            relative_positions_.clear();
            relative_positions_.push_back(position);
            base_alignment_ = candidate;
        } else if (observed > last_) {
            if (observed - last_ > 1'000'000'000) {
                reset("acquisition frames interrupted; hold still");
                return {};
            }
            ++count_;
            last_ = observed;
            relative_positions_.push_back(position);
            if (relative_positions_.size() > 90)
                relative_positions_.pop_front();
        }
        state["reason"] =
            "aligning phone (brief 8 cm motion allowance): " + std::to_string(count_) +
            " good frames";
        if (!unstable && count_ >= 2) {
            world_anchor_ = candidate;
            state["state"] = "tracking";
            state["reason"] = "ARCore pose; optical detection paused";
            return compose(*world_anchor_, current);
        }
        return {};
    }

  private:
    static std::uint64_t difference(std::int64_t a, std::int64_t b) {
        return std::uint64_t(a > b ? a - b : b - a);
    }
    std::deque<std::pair<std::uint64_t, Matrix>> heads_;
    std::optional<Matrix> world_anchor_;
    std::string key_;
    unsigned count_ = 0;
    std::uint64_t last_ = 0;
    Matrix base_alignment_{};
    std::deque<std::array<double, 3>> relative_positions_;
};
} // namespace framephone::surface
