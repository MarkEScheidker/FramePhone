#pragma once
#include "pose_prediction.hpp"

namespace framephone::surface {
/** Visual-only exponential averaging on rigid transforms. A short time constant
 * at rest suppresses jitter; motion shortens it to preserve responsiveness.
 * Raw poses and registration are never filtered. */
class PoseSmoothing {
  public:
    void reset() {
        previous_.reset();
    }
    Matrix update(const Matrix &target, std::uint64_t now) {
        if (!previous_ || now <= stamp_ || now - stamp_ > 120'000'000 ||
            !near(*previous_, target, .15, .6)) {
            previous_ = target;
            stamp_ = now;
            return target;
        }
        const double seconds = double(now - stamp_) / 1e9;
        stamp_ = now;
        auto delta = compose(inverse(*previous_), target);
        const double angle =
            std::acos(std::clamp((delta[0] + delta[5] + delta[10] - 1) / 2, -1., 1.));
        const double distance = std::hypot(delta[3], delta[7], delta[11]);
        // Keep millimeter/degree noise inside the resting filter response.
        const double tau = .035 / (1 + 6 * std::max(0., distance - .006) / seconds +
                                   .25 * std::max(0., angle - .04) / seconds);
        const double alpha = -std::expm1(-seconds / std::max(.008, tau));
        Matrix out = *previous_;
        if (angle > 1e-7) {
            const double scale = angle / (2 * std::sin(angle));
            const auto step =
                angular_step({(delta[9] - delta[6]) * scale, (delta[2] - delta[8]) * scale,
                              (delta[4] - delta[1]) * scale},
                             alpha);
            out = compose(out, step);
        }
        for (int r = 0; r < 3; ++r)
            out[r * 4 + 3] += alpha * (target[r * 4 + 3] - out[r * 4 + 3]);
        previous_ = out;
        return out;
    }

  private:
    std::optional<Matrix> previous_;
    std::uint64_t stamp_ = 0;
};
} // namespace framephone::surface
