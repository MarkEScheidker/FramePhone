#pragma once
#include "pose_prediction.hpp"

namespace framephone::surface {
struct PhonePresentation {
    std::optional<Matrix> pose;
    double opacity = 0;
    bool gyro = false;
};

/** Presentation only: a lost alignment stays lost. Live body-axis gyro may
 * advance the last rendered orientation during the loss fade. Position is
 * held; integrating raw accelerometer data here would add gravity/bias drift. */
class TrackingFade {
  public:
    static constexpr std::uint64_t duration_ns = 500'000'000, fade_in_ns = 250'000'000;
    void reset() {
        last_.reset();
        loss_.reset();
        opacity_ = 0;
    }
    PhonePresentation update(const std::optional<Matrix> &measured, std::uint64_t now,
                             const nlohmann::json &gyro, bool allow_gyro) {
        if (last_ && now < stamp_)
            reset();
        if (measured) {
            if (!last_ || loss_) {
                rise_from_ = loss_ ? lost_opacity(now) : 0;
                rise_ = now;
            }
            last_ = measured;
            loss_.reset();
            stamp_ = now;
            const double t = std::clamp(double(now - rise_) / fade_in_ns, 0., 1.);
            opacity_ = rise_from_ + (1 - rise_from_) * t;
            return {last_, opacity_, false};
        }
        if (!last_)
            return {};
        if (!loss_) {
            loss_ = now;
            loss_from_ = opacity_;
        }
        opacity_ = lost_opacity(now);
        if (opacity_ <= 0) {
            reset();
            return {};
        }
        bool predicted = false;
        if (allow_gyro && now > stamp_ && now - stamp_ <= 50'000'000) {
            if (const auto delta = rotation(gyro, stamp_, now)) {
                last_ = compose(*last_, *delta);
                predicted = true;
            }
        }
        stamp_ = now; // Never accumulate a missed interval or replay stale samples.
        return {last_, opacity_, predicted};
    }

  private:
    double lost_opacity(std::uint64_t now) const {
        return loss_from_ * (1 - std::clamp(double(now - *loss_) / duration_ns, 0., 1.));
    }
    static std::optional<Matrix> rotation(const nlohmann::json &samples, std::uint64_t from,
                                          std::uint64_t to) {
        if (!samples.is_array() || samples.empty() || samples.size() > 64)
            return {};
        const auto end = samples.back().at("host_t_ns").get<std::int64_t>();
        if (end > std::int64_t(to) + 5'000'000 || std::int64_t(to) - end > 25'000'000)
            return {};
        std::size_t index = 0;
        while (index + 1 < samples.size() &&
               samples[index + 1].at("host_t_ns").get<std::int64_t>() <= std::int64_t(from))
            ++index;
        auto cursor = std::int64_t(from);
        auto out = identity();
        double angle = 0;
        while (cursor < std::int64_t(to)) {
            const auto stamp = samples[index].at("host_t_ns").get<std::int64_t>();
            const auto next = index + 1 < samples.size()
                                  ? samples[index + 1].at("host_t_ns").get<std::int64_t>()
                                  : std::int64_t(to);
            const auto until = std::min(next, std::int64_t(to));
            if (stamp > cursor || cursor - stamp > 25'000'000 || until <= cursor ||
                until - stamp > 25'000'000 || until > end + 10'000'000)
                return {};
            const auto w = samples[index].at("w_rad_s").get<std::array<double, 3>>();
            const double seconds = double(until - cursor) / 1e9;
            angle += std::hypot(w[0], w[1], w[2]) * seconds;
            if (!std::isfinite(angle) || angle > .35)
                return {};
            out = compose(out, angular_step(w, seconds));
            cursor = until;
            if (index + 1 < samples.size())
                ++index;
        }
        return out;
    }
    std::optional<Matrix> last_;
    std::optional<std::uint64_t> loss_;
    std::uint64_t stamp_ = 0, rise_ = 0;
    double opacity_ = 0, rise_from_ = 0, loss_from_ = 0;
};
} // namespace framephone::surface
