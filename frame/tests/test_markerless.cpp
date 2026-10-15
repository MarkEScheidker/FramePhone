#include "framephone/markerless.hpp"
#include "framephone/stereo_recording.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <nlohmann/json.hpp>
#include <opencv2/calib3d.hpp>

using namespace framephone;
namespace {
using Json = nlohmann::json;
const std::filesystem::path fixtures = FRAMEPHONE_TEST_DATA;
const PhoneBodyModel body{.07, .15, .009};
const cv::Matx33d hc(1, 0, 0, 0, -1, 0, 0, 0, -1);
void check(bool ok, const std::string &message) {
    if (!ok)
        throw std::runtime_error(message);
}
template <typename F> void fails(F f) {
    bool failed = false;
    try {
        f();
    } catch (const std::exception &) {
        failed = true;
    }
    check(failed, "expected invalid input to fail");
}
cv::Vec3d origin(std::size_t v) {
    return {v == 0 ? -.032 : .032, 0, 0};
}
cv::Matx33d intrinsic(const CameraCalibration &k) {
    return {k.fx, 0, k.cx, 0, k.fy, k.cy, 0, 0, 1};
}
BodyObservation observations(const StereoRig &rig, cv::Matx33d hb, cv::Vec3d t) {
    // Independent OpenCV projection with the fixture's known extrinsics.
    // Explicit dimensions/face offset avoid testing a model against itself.
    const std::vector<cv::Point3d> corners{
        {-.035, .075, .0045}, {.035, .075, .0045}, {.035, -.075, .0045}, {-.035, -.075, .0045}};
    BodyObservation result;
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &k = rig.cameras[v].calibration;
        cv::Vec3d rv;
        cv::Rodrigues(hc.t() * hb, rv);
        std::vector<cv::Point2d> pixels;
        cv::fisheye::projectPoints(corners, pixels, rv, hc.t() * (t - origin(v)), intrinsic(k),
                                   k.distortion);
        for (std::size_t i = 0; i < 4; ++i)
            result.corners[v][i] = {pixels[i].x, pixels[i].y};
    }
    return result;
}
StereoPair render(const StereoRig &rig, cv::Matx33d hb, cv::Vec3d t, std::uint64_t time) {
    StereoPair result;
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &k = rig.cameras[v].calibration;
        auto &f = result.frames[v];
        f = {k.camera_id,
             k.width,
             k.height,
             k.width,
             PixelFormat::Gray8,
             time + v * 100000,
             "synthetic-shared",
             k.id,
             {},
             std::vector<std::uint8_t>(std::size_t(k.width) * k.height)};
        std::vector<cv::Point2d> pixels, rays;
        for (std::uint32_t y = 0; y < k.height; ++y)
            for (std::uint32_t x = 0; x < k.width; ++x)
                pixels.emplace_back(x, y);
        cv::fisheye::undistortPoints(pixels, rays, intrinsic(k), k.distortion);
        const auto camera_b = hb.t() * (origin(v) - t);
        for (std::size_t i = 0; i < rays.size(); ++i) {
            const auto ray = hb.t() * hc * cv::Vec3d(rays[i].x, rays[i].y, 1);
            const double distance = (.0045 - camera_b[2]) / ray[2];
            const auto point = camera_b + ray * distance;
            f.pixels[i] =
                distance > 0 && std::abs(point[0]) < .035 && std::abs(point[1]) < .075 ? 220 : 24;
        }
    }
    return result;
}
void accuracy(const BodyPoseResult &result, cv::Matx33d r, cv::Vec3d t, double meters,
              double radians) {
    check(result.status == "measured",
          "expected measured: " + result.status + " / " + result.reason);
    const auto &p = result.candidates[0];
    const double translation_error = cv::norm(cv::Vec3d(p.translation_m.data()) - t);
    check(translation_error < meters,
          "body center translation error " + std::to_string(translation_error));
    double trace = 0;
    for (std::size_t i = 0; i < 9; ++i)
        trace += p.rotation[i] * r.val[i];
    check(std::acos(std::clamp((trace - 1) / 2, -1.0, 1.0)) < radians, "body rotation error");
}
Json frames_json(const StereoPair &pair) {
    Json frames = Json::array();
    for (const auto &f : pair.frames)
        frames.push_back({{"camera_id", f.camera_id},
                          {"calibration_id", f.calibration_id},
                          {"capture_timestamp_ns", f.capture_time_ns},
                          {"clock", f.clock_domain},
                          {"width", f.width},
                          {"height", f.height}});
    return frames;
}
void trial(const std::filesystem::path &directory, const StereoRig &rig) {
    check(std::filesystem::create_directory(directory), "fixture output must be new");
    std::filesystem::copy(fixtures / "stereo-factory", directory / "factory",
                          std::filesystem::copy_options::recursive);
    Json config{{"schema", "framephone-markerless-session-v1"},
                {"phone_session", "synthetic-phone"},
                {"phone_body", {{"width_m", .07}, {"height_m", .15}, {"thickness_m", .009}}},
                {"calibration_id", "synthetic-factory-v1"},
                {"left", "slam_left"},
                {"right", "slam_right"},
                {"left_stream", "slam_left"},
                {"right_stream", "slam_right"},
                {"capture_clock", "synthetic-shared"},
                {"record", false},
                {"max_pairs", 20}};
    std::ofstream(directory / "session.json") << config.dump();
    cv::Matx33d r;
    cv::Rodrigues(cv::Vec3d(.08, -.12, .03), r);
    const cv::Vec3d t(.005, 0, -.6);
    auto initial = render(rig, r, t, 1'000'000'000);
    StereoRecorder(directory / "initial").write(initial, 1);
    std::ofstream(directory / "capture.json") << Json{{"frames", frames_json(initial)}};
    const auto obs = observations(rig, r, t);
    Json corners = Json::array();
    for (auto view : obs.corners) {
        Json pixels = Json::array();
        for (auto p : view)
            pixels.push_back({p.x, p.y});
        corners.push_back(pixels);
    }
    std::ofstream(directory / "corners.json") << Json{{"schema", "framephone-body-corners-v1"},
                                                      {"physical_top_and_front_labelled", true},
                                                      {"frames", frames_json(initial)},
                                                      {"corners", corners}};
    StereoRecorder recording(directory / "motion");
    for (std::uint64_t i = 1; i <= 5; ++i) {
        auto moving =
            render(rig, r, t + cv::Vec3d(.0005 * double(i), 0, 0), 1'000'000'000 + i * 33'333'333);
        if (i == 5)
            for (auto &f : moving.frames)
                std::fill(f.pixels.begin(), f.pixels.end(), 24);
        recording.write(moving, i);
    }
}
} // namespace
int main(int argc, char **argv) {
    std::string stage;
    try {
        const auto all =
            load_frametop_calibration(fixtures / "stereo-factory", "synthetic-factory-v1");
        const StereoRig rig{{all.at("slam_left"), all.at("slam_right")}};
        if (argc == 3 && std::string(argv[1]) == "--write-trial") {
            trial(argv[2], rig);
            return 0;
        }
        MarkerlessPoseEstimator estimator(body, rig);
        stage = "shared stereo pairing boundaries and provenance";
        const auto fixture = render(rig, cv::Matx33d::eye(), {0, 0, -.6}, 1'000'000'000);
        auto frame = [&](std::size_t view, std::uint64_t timestamp) {
            auto f = fixture.frames[view];
            f.capture_time_ns = timestamp;
            return f;
        };
        StereoFramePairer pairer(rig);
        pairer.push(frame(0, 1'000'000'000));
        pairer.push(frame(1, 1'003'000'000));
        const auto boundary = pairer.poll();
        check(boundary && boundary->skew_ns() == 3'000'000, "3ms boundary rejected");
        check(!pairer.poll(), "frame reused");
        fails([&] { pairer.push(frame(0, 1'000'000'000)); });
        auto wrong_clock = frame(0, 1'010'000'000);
        wrong_clock.clock_domain = "unrelated-clock";
        fails([&] { pairer.push(wrong_clock); });
        auto wrong_calibration = frame(0, 1'010'000'000);
        wrong_calibration.calibration_id = "unrelated-calibration";
        fails([&] { pairer.push(wrong_calibration); });
        pairer.push(frame(0, 1'010'000'000));
        pairer.push(frame(1, 1'013'000'001));
        check(!pairer.poll() && pairer.dropped_frames() == 1, "over-skew frame retained");
        pairer.push(frame(0, 1'014'000'000));
        check(bool(pairer.poll()) && !pairer.poll(), "fresh pair not consumed once");
        StereoFramePairer bounded(rig);
        for (std::uint64_t i = 1; i <= 5; ++i)
            bounded.push(frame(0, i * 10'000'000));
        check(bounded.dropped_frames() == 1, "unpaired queue must be bounded");
        stage = "exact frontal and tilted independent projection";
        for (cv::Vec3d rotation : {cv::Vec3d(0, 0, 0), cv::Vec3d(.2, -.3, .1)}) {
            cv::Matx33d r;
            cv::Rodrigues(rotation, r);
            const cv::Vec3d t(.01, -.02, -.6);
            const auto pair = render(rig, r, t, 1'000'000'000);
            auto obs = observations(rig, r, t);
            accuracy(estimator.estimate(pair, obs), r, t, 1e-6, 1e-5);
            stage = "bad corner, order, identity and timestamps";
            auto bad = obs;
            bad.corners[1][2].y += 30;
            check(estimator.estimate(pair, bad).status == "lost", "stereo outlier accepted");
            bad = obs;
            std::swap(bad.corners[0][1], bad.corners[0][2]);
            check(estimator.estimate(pair, bad).status == "lost", "crossed corners accepted");
            bad = obs;
            bad.corners[0][0].x = std::numeric_limits<double>::quiet_NaN();
            check(estimator.estimate(pair, bad).status == "lost", "nonfinite corner accepted");
            auto wrong = pair;
            wrong.frames[0].calibration_id = "different";
            fails([&] { estimator.estimate(wrong, obs); });
            wrong = pair;
            wrong.frames[1].capture_time_ns += 4'000'000;
            fails([&] { estimator.estimate(wrong, obs); });
            stage = "independent distorted raster outline tracking";
            MarkerlessTracker tracker(estimator);
            accuracy(tracker.initialize(pair, obs), r, t, 1e-6, 1e-5);
            const auto next_t = t + cv::Vec3d(.0005, 0, 0);
            const auto moved = render(rig, r, next_t, 1'033'333'333);
            // Binary raster quantization at a ~90 px phone width can shift
            // fitted depth several millimeters; this bounds that image error.
            accuracy(tracker.update(moved), r, next_t, .005, .04);
            auto blank = render(rig, r, next_t, 1'066'666'666);
            for (auto &f : blank.frames)
                std::fill(f.pixels.begin(), f.pixels.end(), 24);
            check(tracker.update(blank).status == "lost" && !tracker.active(),
                  "blank must latch loss");
            check(tracker.update(render(rig, r, next_t, 1'100'000'000)).status == "lost",
                  "silently reacquired after loss");
            tracker.initialize(pair, obs);
            tracker.update(moved);
            check(tracker.update(render(rig, r, next_t, 1'500'000'000)).status == "lost",
                  "long gap retained pose");
            tracker.initialize(pair, obs);
            fails([&] { tracker.update(wrong); });
            check(!tracker.active(), "invalid frame must invalidate tracker state");
            tracker.initialize(pair, obs);
            fails([&] { tracker.initialize(wrong, obs); });
            check(!tracker.active(), "failed initialization must clear the previous target");
        }
        fails([&] { MarkerlessPoseEstimator invalid({.07, .15, 0}, rig); });
        std::cout << "Markerless independent geometry, distorted raster, loss and provenance "
                     "checks passed\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << stage << ": " << e.what() << '\n';
        return 1;
    }
}
