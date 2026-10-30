#include "../src/arcore_handoff.hpp"
#include <iostream>

using namespace framephone::surface;
using Json = nlohmann::json;
namespace {
void check(bool ok, const char *message) {
    if (!ok)
        throw std::runtime_error(message);
}
Json phone(std::uint64_t time, Matrix device = identity(), bool required = true,
           const char *generation = "anchor-1", const char *acquisition = "scan-1") {
    return {{"schema", "framephone-arcore-v1"},
            {"session", "phone-1"},
            {"clock_valid", true},
            {"received_host_monotonic_ns", time},
            {"poses", Json::array({{{"generation", generation},
                                    {"acquisition", acquisition},
                                    {"host_t_ns", time},
                                    {"state", "tracking"},
                                    {"marker_required", required},
                                    {"translation_m", {device[3], device[7], device[11]}},
                                    {"quaternion_xyzw", {0, 0, 0, 1}}}})}};
}
Json optical(std::uint64_t time, const Matrix &value) {
    return {{"schema", "framephone-fiducial-pose-v1"},
            {"transform", "T_HM"},
            {"status", "measured"},
            {"observed_host_monotonic_ns", time},
            {"processed_host_monotonic_ns", time},
            {"candidates", Json::array({{{"rotation",
                                          {value[0], value[1], value[2], value[4], value[5],
                                           value[6], value[8], value[9], value[10]}},
                                         {"translation_m", {value[3], value[7], value[11]}},
                                         {"rms_px", .4}}})}};
}
std::uint64_t acquire(ArcoreHandoff &handoff, Matrix world_anchor, Matrix head = identity(),
                      std::uint64_t start = 1'000'000'000) {
    for (unsigned i = 0; i <= 1; ++i) {
        auto time = start + i * 100'000'000ULL;
        handoff.head(time, head);
        auto found =
            handoff.update(phone(time), optical(time, compose(inverse(head), world_anchor)), time);
        check(bool(found) == (i == 1), "two consistent observations should acquire");
    }
    return start + 100'000'000;
}
} // namespace
int main() {
    try {
        Matrix anchor{0, -1, 0, .2, 1, 0, 0, .1, 0, 0, 1, -.6};
        check(near(compose(anchor, inverse(anchor)), identity(), 1e-10, 1e-7),
              "rigid transform inverse");
        ArcoreHandoff handoff;
        auto time = acquire(handoff, anchor);
        auto device = identity(), head = identity();
        device[3] = .3;
        head[3] = .2;
        time += 30'000'000;
        handoff.head(time, head);
        auto output = handoff.update(phone(time, device, false), Json::object(), time);
        check(output && near(*output, compose(anchor, device), 1e-10, 1e-7),
              "phone and headset move independently after the marker disappears");
        auto rotation = phone(time);
        rotation["poses"][0]["quaternion_xyzw"] = {0, 0, std::sqrt(.5), std::sqrt(.5)};
        auto rotated = phone_pose(rotation["poses"][0]);
        check(std::abs(rotated[1] + 1) < 1e-10 && std::abs(rotated[4] - 1) < 1e-10,
              "xyzw quaternion orientation");

        auto paused = phone(time, device, false);
        paused["poses"][0]["state"] = "paused";
        check(!handoff.update(paused, Json::object(), time),
              "tracking loss must hide and invalidate");
        check(!handoff.update(phone(time, device, false), Json::object(), time),
              "tracking resumption cannot silently restore an invalidated alignment");
        check(handoff.state["state"] == "acquiring", "loss must request acquisition");

        ArcoreHandoff stale;
        time = acquire(stale, anchor);
        check(!stale.update(phone(time, identity(), false), Json::object(), time + 250'000'001),
              "stale phone poses hide the surface");
        ArcoreHandoff reset;
        time = acquire(reset, anchor);
        auto changed = phone(time, identity(), false, "anchor-2");
        check(!reset.update(changed, Json::object(), time),
              "anchor/session resets invalidate alignment");
        ArcoreHandoff clock;
        time = acquire(clock, anchor);
        auto invalid = phone(time);
        invalid["clock_valid"] = false;
        check(!clock.update(invalid, Json::object(), time), "unverified/stale clock cannot align");
        ArcoreHandoff recenter;
        time = acquire(recenter, anchor);
        recenter.reset("recenter");
        check(!recenter.update(phone(time, identity(), false), Json::object(), time),
              "headset recenter requires a new marker observation");

        ArcoreHandoff moving;
        for (unsigned i = 0; i < 20; ++i) {
            time = 1'000'000'000ULL + i * 100'000'000ULL;
            auto device_pose = identity();
            device_pose[3] = .12 * i;
            moving.head(time, identity());
            check(!moving.update(phone(time, device_pose),
                                 optical(time, compose(anchor, device_pose)), time),
                  "excessive relative motion must not pass the relaxed gate");
        }
        ArcoreHandoff repeated;
        time = 1'000'000'000;
        auto same = optical(time, anchor);
        for (unsigned i = 0; i < 10; ++i) {
            repeated.head(time, identity());
            check(!repeated.update(phone(time), same, time),
                  "one frame cannot satisfy the acquisition count");
        }
        ArcoreHandoff slow;
        Json history = Json::array();
        bool slow_acquired = false;
        for (unsigned i = 0; i <= 21; ++i) {
            time = 1'000'000'000ULL + i * 50'000'000ULL;
            auto packet = phone(time);
            history.push_back(packet["poses"][0]);
            packet["poses"] = history;
            slow.head(time, identity());
            auto observation = 1'000'000'000ULL + (i / 7) * 350'000'000ULL;
            slow_acquired = bool(slow.update(packet, optical(observation, anchor), time));
        }
        check(slow_acquired,
              "350 ms detector cadence must not reset stationary acquisition at render timeout");
        ArcoreHandoff minimum;
        for (unsigned i = 0; i < 2; ++i) {
            time = 1'000'000'000ULL + i * 16'000'000ULL;
            minimum.head(time, identity());
            const auto found = minimum.update(phone(time), optical(time, anchor), time);
            check(bool(found) == (i == 1),
                  "two consistent stereo observations acquire without an artificial dwell");
        }
        ArcoreHandoff walking;
        auto walk_anchor = identity();
        walk_anchor[11] = -.6;
        for (unsigned i = 0; i <= 1; ++i) {
            time = 1'000'000'000ULL + i * 100'000'000ULL;
            auto moving_head = identity(), moving_device = identity();
            moving_head[3] = moving_device[3] = .04 * i;
            walking.head(time, moving_head);
            const auto relative =
                compose(inverse(moving_head), compose(walk_anchor, moving_device));
            auto found = walking.update(phone(time, moving_device), optical(time, relative), time);
            check(bool(found) == (i == 1),
                  "common world movement must not prevent relative acquisition");
        }
        for (double amplitude : {.03, .05}) {
            ArcoreHandoff jitter;
            for (unsigned i = 0; i <= 1; ++i) {
                time = 1'000'000'000ULL + i * 100'000'000ULL;
                auto device_pose = identity();
                device_pose[3] = i % 2 ? amplitude : -amplitude;
                jitter.head(time, identity());
                auto found = jitter.update(phone(time, device_pose),
                                           optical(time, compose(walk_anchor, device_pose)), time);
                check(bool(found) == (i == 1 && amplitude < .04),
                      "relative position spread must remain within 8 cm");
            }
        }
        ArcoreHandoff natural_motion;
        for (unsigned i = 0; i < 2; ++i) {
            time = 1'000'000'000ULL + i * 100'000'000ULL;
            auto device_pose = identity();
            device_pose[3] = .04 * i;
            natural_motion.head(time, identity());
            const auto found = natural_motion.update(
                phone(time, device_pose), optical(time, compose(walk_anchor, device_pose)), time);
            check(bool(found) == (i == 1),
                  "normal movement should not require a fixed phone position");
        }
        ArcoreHandoff inconsistent;
        time = 1'000'000'000;
        inconsistent.head(time, identity());
        check(!inconsistent.update(phone(time), optical(time, anchor), time),
              "first frame must not acquire");
        time += 100'000'000;
        inconsistent.head(time, identity());
        auto outlier = anchor;
        outlier[3] += .2;
        check(!inconsistent.update(phone(time), optical(time, outlier), time),
              "registration disagreement still rejects an outlier");
        auto bad = phone(time);
        bad["poses"][0]["quaternion_xyzw"] = {0, 0, 0, 0};
        bool rejected = false;
        try {
            phone_pose(bad["poses"][0]);
        } catch (const std::exception &) {
            rejected = true;
        }
        check(rejected, "invalid quaternion must be rejected");
        std::cout << "ARCore stationary acquisition, world motion, clock/loss/reset and quaternion "
                     "checks passed.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
