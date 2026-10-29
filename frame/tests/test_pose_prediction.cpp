#include "../src/headset_presence.hpp"
#include "../src/pose_smoothing.hpp"
#include <iostream>

using namespace framephone::surface;
using Json = nlohmann::json;
namespace {
void check(bool ok, const char *message) {
    if (!ok)
        throw std::runtime_error(message);
}
Json sample(std::uint64_t time, double x) {
    return {{"generation", "anchor"},     {"acquisition", "scan"},          {"state", "tracking"},
            {"host_t_ns", time},          {"pose_host_t_ns", time},         {"capture_t_ns", time},
            {"translation_m", {x, 0, 0}}, {"quaternion_xyzw", {0, 0, 0, 1}}};
}
Json packet(std::uint64_t time, double previous_x = 0, double current_x = 0,
            unsigned span_ms = 20) {
    Json p{{"poses", Json::array({sample(time - 20'000'000, 2 * previous_x - current_x),
                                  sample(time - 10'000'000, previous_x), sample(time, current_x)})},
           {"gyro", Json::array()}};
    for (unsigned i = 0; i <= span_ms / 5; ++i)
        p["gyro"].push_back({{"host_t_ns", time + i * 5'000'000ULL}, {"w_rad_s", {1, 0, 0}}});
    return p;
}
} // namespace
int main() {
    try {
        const std::uint64_t stamp = 1'000'000'000;
        Matrix world{0, -1, 0, .2, 1, 0, 0, .1, 0, 0, 1, -.6};
        auto data = packet(stamp);
        auto rotated = predict_pose(world, data, stamp + 20'000'000);
        // Body X rotates around world Y for this 90-degree world/anchor rotation.
        check(rotated.gyro && std::abs(rotated.pose[2] - std::sin(.02)) < 1e-9 &&
                  std::abs(rotated.pose[9] - std::sin(.02)) < 1e-9,
              "gyro must integrate in device axes");
        check(rotated.pose[3] == .2 && rotated.pose[7] == .1, "gyro must not integrate position");
        data = packet(stamp, 0, .01);
        auto translated = predict_pose(world, data, stamp + 20'000'000);
        check(std::abs(translated.pose[7] - .12) < 1e-10 && translated.pose[3] == .2,
              "anchor velocity must rotate into world space");
        data = packet(stamp, 0, .01, 100);
        auto later = predict_pose(world, data, stamp + 100'000'000);
        check(std::abs(later.pose[7] - .12) < 1e-10 && later.milliseconds <= 80,
              "translation must stop at 2 cm and rotation at 80 ms");
        for (int i = 0; i < 100; ++i)
            check(
                near(predict_pose(world, data, stamp + 100'000'000).pose, later.pose, 1e-10, 1e-7),
                "prediction must never feed itself and drift with repeated render calls");
        data["poses"][2].erase("capture_t_ns");
        check(!predict_pose(world, data, stamp + 20'000'000).gyro,
              "unknown capture clock must disable gyro prediction");
        data = packet(stamp, 0, 0, 60);
        data["gyro"].erase(data["gyro"].begin() + 2, data["gyro"].begin() + 10);
        check(!predict_pose(world, data, stamp + 60'000'000).gyro,
              "gyro gaps must not be integrated");
        data = packet(stamp);
        data["gyro"] = Json::array({{{"host_t_ns", stamp}, {"w_rad_s", {1, 0, 0}}}});
        check(!predict_pose(world, data, stamp + 50'000'000).gyro,
              "stale gyro must not continue rotating");
        data = packet(stamp, 0, .01);
        data["poses"][0]["generation"] = "retired";
        auto reset = predict_pose(world, data, stamp + 20'000'000);
        check(reset.pose[7] == world[7], "retired anchor cannot supply velocity");
        check(near(predict_pose(world, data, stamp + 250'000'001).pose, world, 1e-10, 1e-7),
              "stale poses must not be predicted");
        data = packet(stamp, 0, 0, 80);
        for (auto &g : data["gyro"])
            g["w_rad_s"] = {10, 0, 0};
        check(!predict_pose(world, data, stamp + 80'000'000).gyro,
              "angular displacement must be bounded");
        // Stationary +/-3mm and +/-0.01rad noise must be attenuated at each
        // headset cadence, without corrupting the rigid rotation matrix.
        for (const unsigned hz : {60, 90, 120}) {
            PoseSmoothing filter;
            Matrix target = identity();
            auto t = stamp;
            filter.update(target, t);
            double error = 0;
            for (unsigned i = 0; i < hz; ++i) {
                target = angular_step({0, 0, (i % 2 ? 1. : -1.)}, .01);
                target[3] = i % 2 ? .003 : -.003;
                t += 1'000'000'000 / hz;
                const auto smoothed = filter.update(target, t);
                error += std::abs(smoothed[3]);
                check(std::abs(compose(inverse(smoothed), smoothed)[0] - 1) < 1e-10,
                      "smoothing must preserve rigid rotation");
            }
            check(error / hz < .001, "stationary jitter should be reduced");
            filter.reset();
            target = identity();
            filter.update(target, t);
            for (unsigned i = 0; i < hz; ++i) {
                target[3] += 1. / hz;
                t += 1'000'000'000 / hz;
                const auto smoothed = filter.update(target, t);
                check(target[3] - smoothed[3] < .045,
                      "motion lag must stay bounded with light smoothing");
            }
            filter.reset();
            target = identity();
            filter.update(target, t);
            for (unsigned i = 1; i <= hz; ++i) {
                target = angular_step({0, 0, 1}, double(i) / hz);
                t += 1'000'000'000 / hz;
                const auto smoothed = filter.update(target, t);
                const auto delta = compose(inverse(smoothed), target);
                const double error =
                    std::acos(std::clamp((delta[0] + delta[5] + delta[10] - 1) / 2, -1., 1.));
                check(error < .055, "rotational lag must stay bounded with light smoothing");
            }
            filter.reset();
            target[3] = 10;
            check(filter.update(target, t)[3] == 10,
                  "reacquisition must not blend retired alignment");
            target[3] = 20;
            check(filter.update(target, t + 200'000'000)[3] == 20, "pause must reset smoothing");
        }
        // Hold each measured target between sparse ARCore arrivals; filtering
        // must still reduce jitter when the source is slower than rendering.
        for (unsigned source_hz : {10, 30}) {
            PoseSmoothing filter;
            auto target = identity();
            auto t = stamp;
            filter.update(target, t);
            double jitter = 0;
            for (unsigned tick = 0; tick < 180; ++tick) {
                target[3] = (tick * source_hz / 90) % 2 ? .003 : -.003;
                t += 1'000'000'000 / 90;
                const auto smoothed = filter.update(target, t);
                if (tick >= 90)
                    jitter += std::abs(smoothed[3]);
            }
            check(jitter / 90 < .0022, "sparse pose arrivals must still be smoothed");
        }
        data = packet(stamp, 0, 0);
        data["poses"] = Json::array();
        for (unsigned i = 0; i < 6; ++i)
            data["poses"].push_back(
                sample(stamp - 50'000'000 + i * 10'000'000, i % 2 ? .003 : -.003));
        const auto fitted = measured_velocity(data["poses"]);
        check(fitted && std::abs((*fitted)[0]) < .06,
              "history regression must suppress alternating position noise");
        data["poses"].back()["translation_m"][0] = .15;
        check(!measured_velocity(data["poses"]), "large history residual must disable prediction");
        data = packet(stamp, 0, .01);
        data["poses"].erase(data["poses"].begin());
        check(!measured_velocity(data["poses"]),
              "two samples must not amplify noisy position differences");
        HeadsetPresence presence;
        check(!presence.update(stamp, false, true, true).available,
              "disconnected headset cannot enable marker");
        check(!presence.update(stamp, true, {}, {}).available,
              "unknown runtime state must remain unavailable");
        check(!presence.update(stamp, true, {}, false).worn, "initial idle must not enable marker");
        check(!presence.update(stamp + 100'000'000, true, {}, true).worn,
              "activity fallback must debounce startup");
        auto fallback = presence.update(stamp + 600'000'000, true, {}, true);
        check(fallback.available && fallback.worn && !fallback.proximity,
              "missing proximity binding must not block a stable active headset");
        check(!presence.update(stamp + 700'000'000, true, false, true).worn,
              "explicit unworn proximity must override active fallback");
        check(presence.update(stamp + 800'000'000, true, true, false).worn,
              "explicit worn proximity must override idle fallback");
        presence.update(stamp + 900'000'000, true, {}, false);
        check(!presence.update(stamp + 1'400'000'000, true, {}, false).worn,
              "stable idle must disable acquisition");
        check(!presence.update(stamp + 1'500'000'000, true, {}, {}).worn,
              "losing both signals must clear previous permission");
        std::cout << "Timestamped body gyro, world velocity, bounded horizons, gaps and reset "
                     "checks passed.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
