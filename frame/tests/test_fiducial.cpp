#include "framephone/fiducial.hpp"
#include "framephone/stereo_recording.hpp"
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <opencv2/calib3d.hpp>

using namespace framephone;
namespace {
using Json = nlohmann::json;
const std::filesystem::path fixtures = FRAMEPHONE_TEST_DATA;
const cv::Matx33d hc(1, 0, 0, 0, -1, 0, 0, 0, -1);
const std::array<std::string, 10> bitmap{{"0000000000", "0111111110", "0100101010", "0110001010",
                                          "0110011110", "0101011110", "0110100110", "0111101110",
                                          "0111111110", "0000000000"}};
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
    check(failed, "expected invalid input failure");
}
cv::Vec3d origin(std::size_t v) {
    return {v ? .032 : -.032, 0, 0};
}
cv::Matx33d intrinsic(const CameraCalibration &k) {
    return {k.fx, 0, k.cx, 0, k.fy, k.cy, 0, 0, 1};
}
StereoPair render(const StereoRig &rig, cv::Matx33d hm, cv::Vec3d t, std::uint64_t time,
                  unsigned damaged_cells = 0) {
    StereoPair pair;
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &k = rig.cameras[v].calibration;
        auto &f = pair.frames[v];
        f = {k.camera_id,
             k.width,
             k.height,
             k.width,
             PixelFormat::Gray8,
             time + v * 100000,
             "synthetic-shared",
             k.id,
             {},
             std::vector<std::uint8_t>(std::size_t(k.width) * k.height, 160)};
        std::vector<cv::Point2d> pixels, rays;
        for (std::uint32_t y = 0; y < k.height; ++y)
            for (std::uint32_t x = 0; x < k.width; ++x)
                pixels.emplace_back(x, y);
        cv::fisheye::undistortPoints(pixels, rays, intrinsic(k), k.distortion);
        const auto camera_m = hm.t() * (origin(v) - t);
        for (std::size_t i = 0; i < rays.size(); ++i) {
            const auto ray = hm.t() * hc * cv::Vec3d(rays[i].x, rays[i].y, 1);
            const double distance = -camera_m[2] / ray[2];
            const auto p = camera_m + ray * distance;
            // Independent per-pixel intersection with a 60mm black square.
            if (distance > 0 && std::abs(p[0]) < .0375 && std::abs(p[1]) < .0375) {
                const auto x = std::size_t((p[0] + .0375) / .0075),
                           y = std::size_t((.0375 - p[1]) / .0075);
                if (x < 10 && y < 10) {
                    bool black = bitmap[y][x] == '1';
                    if (y == 2 && x >= 2 && x < 2 + damaged_cells)
                        black = !black;
                    f.pixels[i] = black ? 0 : 255;
                }
            }
        }
    }
    return pair;
}
void accuracy(const PoseResult &result, cv::Matx33d r, cv::Vec3d t, double meters, double radians) {
    check(result.status == "measured", "pose rejected: " + result.reason);
    const auto &p = result.candidates[0];
    check(cv::norm(cv::Vec3d(p.translation_m.data()) - t) < meters, "translation accuracy");
    double trace = 0;
    for (std::size_t i = 0; i < 9; ++i)
        trace += p.rotation[i] * r.val[i];
    check(std::acos(std::clamp((trace - 1) / 2, -1., 1.)) < radians, "rotation accuracy");
}
void trial(const std::filesystem::path &directory, const StereoRig &rig) {
    check(std::filesystem::create_directory(directory), "fixture directory must be new");
    std::filesystem::copy(fixtures / "stereo-factory", directory / "factory",
                          std::filesystem::copy_options::recursive);
    Json config{{"schema", "framephone-fiducial-session-v1"},
                {"phone_session", "synthetic-phone"},
                {"fiducial",
                 {{"family", "tag36h11"},
                  {"id", 0},
                  {"black_edge_m", .06},
                  {"origin", "black_square_center"},
                  {"axes", "right_up_front"},
                  {"size_source", "manual_black_edge"}}},
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
    cv::Rodrigues(cv::Vec3d(.12, -.2, .15), r);
    StereoRecorder recorder(directory / "motion");
    for (std::uint64_t i = 1; i <= 5; ++i) {
        auto pair = render(rig, r, {.003 * double(i), -.01, -.6}, 1'000'000'000 + i * 33'333'333);
        if (i == 3)
            for (auto &f : pair.frames)
                std::fill(f.pixels.begin(), f.pixels.end(), 160);
        recorder.write(pair, i);
    }
}
} // namespace
int main(int argc, char **argv) {
    try {
        auto all = load_frametop_calibration(fixtures / "stereo-factory", "synthetic-factory-v1");
        StereoRig rig{{all.at("slam_left"), all.at("slam_right")}};
        if (argc == 3 && std::string(argv[1]) == "--write-trial") {
            trial(argv[2], rig);
            return 0;
        }
        TagDetector detector;
        const auto raster = render_tag();
        check(raster.width == 320 && raster.height == 320, "raster dimensions");
        for (std::uint32_t y = 0; y < 10; ++y)
            for (std::uint32_t x = 0; x < 10; ++x)
                check((raster.pixels[std::size_t(y * 32 + 16) * 320 + x * 32 + 16] == 0) ==
                          (bitmap[y][x] == '1'),
                      "Android bitmap differs from official family");
        const auto tags = detector.detect(raster);
        check(tags.size() == 1 && tags[0].id == 0, "ID0 not decoded");
        const std::array<ImagePoint, 4> expected{{{32, 32}, {288, 32}, {288, 288}, {32, 288}}};
        for (std::size_t i = 0; i < 4; ++i)
            check(std::hypot(tags[0].corners[i].x - expected[i].x,
                             tags[0].corners[i].y - expected[i].y) < 2,
                  "decoded physical corner order");
        check(detector.detect(render_tag(1)).at(0).id == 1, "wrong ID fixture");
        for (unsigned errors = 1; errors <= 3; ++errors) {
            auto damaged = raster;
            for (unsigned cell = 0; cell < errors; ++cell)
                for (unsigned y = 64; y < 96; ++y)
                    for (unsigned x = (cell + 2) * 32; x < (cell + 3) * 32; ++x)
                        damaged.pixels[y * damaged.stride_bytes + x] ^= 255;
            const auto decoded = detector.detect(damaged);
            if (errors <= 2)
                check(decoded.size() == 1 && decoded[0].id == 0 &&
                          decoded[0].hamming == int(errors),
                      "one/two corrupted data cells must be corrected");
            else
                check(decoded.empty(), "beyond two corrected cells must not decode");
        }
        for (unsigned errors = 1; errors <= 2; ++errors) {
            cv::Matx33d tilted;
            cv::Rodrigues(cv::Vec3d(.2, -.3, .1), tilted);
            const auto damaged = render(rig, tilted, {0, 0, -.6}, 1'000'000'000, errors);
            FiducialTracker corrected(.06, rig);
            const auto found = corrected.update(damaged);
            accuracy(found.pose, tilted, {0, 0, -.6}, .012, .07);
            check(found.detections[0].at(0).hamming == int(errors),
                  "stereo must accept bounded corrected codes");
        }
        auto pair = render(rig, cv::Matx33d::eye(), {0, 0, -.6}, 1'000'000'000);
        StereoFramePairer pairer(rig);
        pair.frames[1].capture_time_ns = 1'003'000'000;
        pairer.push(pair.frames[0]);
        pairer.push(pair.frames[1]);
        check(pairer.poll()->skew_ns() == 3'000'000 && !pairer.poll(), "3ms boundary/frame reuse");
        fails([&] { pairer.push(pair.frames[0]); });
        pair.frames[0].capture_time_ns += 10'000'000;
        pair.frames[0].clock_domain = "unrelated";
        fails([&] { pairer.push(pair.frames[0]); });
        for (cv::Vec3d rv : {cv::Vec3d(0, 0, 0), cv::Vec3d(.2, -.3, .1), cv::Vec3d(.05, .1, 1.6)}) {
            cv::Matx33d r;
            cv::Rodrigues(rv, r);
            const cv::Vec3d t(.01, -.02, -.6);
            auto pair = render(rig, r, t, 1'000'000'000);
            FiducialTracker tracker(.06, rig);
            const auto found = tracker.update(pair);
            accuracy(found.pose, r, t, .012, .07);
            auto blank = pair;
            for (auto &f : blank.frames)
                std::fill(f.pixels.begin(), f.pixels.end(), 160);
            const auto lost = tracker.update(blank);
            check(lost.pose.status == "lost" && lost.pose.candidates.empty(), "blank reused pose");
            accuracy(tracker.update(pair).pose, r, t, .012, .07);
            auto bad = pair;
            bad.frames[0].calibration_id = "wrong";
            fails([&] { tracker.update(bad); });
            bad = pair;
            bad.frames[1].capture_time_ns += 4'000'000;
            fails([&] { tracker.update(bad); });
        }
        fails([&] { FiducialTracker invalid(0, rig); });
        std::cout << "Single AprilTag bitmap, decode orientation, independent KB4 raster pose, "
                     "loss/reacquisition and provenance passed\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
