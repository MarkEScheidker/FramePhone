#pragma once
#include "pose_prediction.hpp"

namespace framephone::surface {
/** Visual-only, speed-adaptive filtering inspired by the 1 Euro filter.
 * Filter the signed derivative before choosing the cutoff: raw correction size
 * must not turn stationary jitter into a high-gain motion response. Rotation is
 * interpolated on SO(3); raw registration and sensor histories are untouched. */
class PoseSmoothing {
  public:
    void reset() {
        previous_.reset();
    }
    Matrix update(const Matrix &target, std::uint64_t now) {
        if (!previous_ || now <= stamp_ || now - stamp_ > 120'000'000 ||
            !near(*previous_, target, .15, .6)) {
            previous_ = raw_ = target;
            velocity_ = angular_velocity_ = {};
            stamp_ = now;
            return target;
        }
        const double seconds = double(now - stamp_) / 1e9;
        stamp_ = now;
        const auto motion = log_rotation(compose(inverse(raw_), target));
        const double derivative_alpha = alpha(1., seconds);
        for (int k = 0; k < 3; ++k) {
            velocity_[k] +=
                derivative_alpha * ((target[k * 4 + 3] - raw_[k * 4 + 3]) / seconds - velocity_[k]);
            angular_velocity_[k] += derivative_alpha * (motion[k] / seconds - angular_velocity_[k]);
        }
        raw_ = target;
        const double speed = std::hypot(velocity_[0], velocity_[1], velocity_[2]);
        const double spin =
            std::hypot(angular_velocity_[0], angular_velocity_[1], angular_velocity_[2]);
        // Resting time constants ~106/133ms; motion still retains >=40ms of
        // smoothing. The owner explicitly prefers steadiness over minimal lag.
        const double position_alpha = alpha(std::min(4., 1.5 + speed), seconds);
        const double rotation_alpha = alpha(std::min(4., 1.2 + .6 * spin), seconds);
        const auto error = log_rotation(compose(inverse(*previous_), target));
        auto out = compose(*previous_, angular_step(error, rotation_alpha));
        for (int k = 0; k < 3; ++k)
            out[k * 4 + 3] += position_alpha * (target[k * 4 + 3] - out[k * 4 + 3]);
        previous_ = out;
        return out;
    }

  private:
    static double alpha(double cutoff, double seconds) {
        constexpr double pi = 3.14159265358979323846;
        const double scaled = 2 * pi * cutoff * seconds;
        return scaled / (1 + scaled);
    }
    static std::array<double, 3> log_rotation(const Matrix &delta) {
        const double angle =
            std::acos(std::clamp((delta[0] + delta[5] + delta[10] - 1) / 2, -1., 1.));
        // reset() above bounds this angle away from the pi singularity.
        const double scale = angle < 1e-7 ? .5 : angle / (2 * std::sin(angle));
        return {(delta[9] - delta[6]) * scale, (delta[2] - delta[8]) * scale,
                (delta[4] - delta[1]) * scale};
    }
    std::optional<Matrix> previous_;
    Matrix raw_{};
    std::array<double, 3> velocity_{}, angular_velocity_{};
    std::uint64_t stamp_ = 0;
};
} // namespace framephone::surface
