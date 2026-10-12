#include "framephone/stereo.hpp"
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <opencv2/calib3d.hpp>
#include <sstream>
#include <unistd.h>

using namespace framephone;
namespace {
const std::filesystem::path fixtures = FRAMEPHONE_TEST_DATA;
void check(bool b, const std::string &message) {
    if (!b)
        throw std::runtime_error(message);
}
template <class F> void fails(F f) {
    bool failed = false;
    try {
        f();
    } catch (const std::exception &) {
        failed = true;
    }
    check(failed, "expected failure");
}
cv::Vec3d v(Point3 p) {
    return {p.x, p.y, p.z};
}
CameraFrame frame(const RigCamera &c, std::uint64_t time = 1'000'000'000) {
    auto f = *SyntheticFrameSource().next();
    f.camera_id = c.calibration.camera_id;
    f.calibration_id = c.calibration.id;
    f.clock_domain = "synthetic-shared";
    f.capture_time_ns = time;
    return f;
}
// Independent OpenCV projection, explicitly using the fixture's known T_HC.
DetectionBatch observations(const PhoneLayout &layout, const CameraFrame &f, const RigCamera &c,
                            const cv::Matx33d &hp, cv::Vec3d translation) {
    const cv::Matx33d ch(1, 0, 0, 0, -1, 0, 0, 0, -1);
    const cv::Vec3d origin(f.camera_id == "slam_left" ? -.032 : .032, 0, 0);
    cv::Vec3d rotation;
    cv::Rodrigues(ch * hp, rotation);
    const auto &k = c.calibration;
    DetectionBatch batch;
    for (const auto &[id, points] : layout.markers) {
        std::vector<cv::Point3d> object;
        for (auto p : points)
            object.emplace_back(p.x, p.y, p.z);
        std::vector<cv::Point2d> image;
        cv::fisheye::projectPoints(object, image, rotation, ch * (translation - origin),
                                   cv::Matx33d(k.fx, 0, k.cx, 0, k.fy, k.cy, 0, 0, 1),
                                   k.distortion);
        TagDetection tag;
        tag.id = id;
        tag.camera_id = f.camera_id;
        tag.capture_time_ns = f.capture_time_ns;
        tag.decision_margin = 100;
        for (std::size_t i = 0; i < 4; ++i)
            tag.corners[i] = {image[i].x, image[i].y};
        batch.detections.push_back(tag);
    }
    return batch;
}
void accuracy(const StereoPoseResult &result, const cv::Matx33d &r, cv::Vec3d t, double meters,
              double radians) {
    check(result.status == "accepted", "expected accepted, got " + result.status);
    const auto &p = result.candidates.at(0);
    double trace{}, distance{};
    for (int i = 0; i < 9; ++i)
        trace += p.rotation_row_major[std::size_t(i)] * r.val[i];
    for (int i = 0; i < 3; ++i)
        distance += std::pow(p.translation_m[std::size_t(i)] - t[i], 2);
    check(std::sqrt(distance) < meters, "translation accuracy");
    check(std::acos(std::clamp((trace - 1) / 2, -1.0, 1.0)) < radians, "rotation accuracy");
}
// Render both distorted views using independently undistorted OpenCV rays and
// the existing official AprilTag texture. No library-generated detections.
CameraFrame render(const RigCamera &c, const cv::Matx33d &hp, cv::Vec3d t) {
    auto f = frame(c);
    const auto texture = *SyntheticFrameSource().next();
    std::vector<cv::Point2d> image, normalized;
    for (std::uint32_t y = 0; y < f.height; ++y)
        for (std::uint32_t x = 0; x < f.width; ++x)
            image.emplace_back(x, y);
    const auto &k = c.calibration;
    cv::fisheye::undistortPoints(image, normalized,
                                 cv::Matx33d(k.fx, 0, k.cx, 0, k.fy, k.cy, 0, 0, 1), k.distortion);
    const cv::Matx33d hc(1, 0, 0, 0, -1, 0, 0, 0, -1);
    const cv::Vec3d origin(f.camera_id == "slam_left" ? -.032 : .032, 0, 0);
    const auto camera_p = hp.t() * (origin - t);
    for (std::size_t i = 0; i < normalized.size(); ++i) {
        const auto ray = hp.t() * hc * cv::Vec3d(normalized[i].x, normalized[i].y, 1);
        const double distance = -camera_p[2] / ray[2];
        const auto p = camera_p + distance * ray;
        const auto x = std::lround(p[0] / .00025 + 319.5), y = std::lround(239.5 - p[1] / .00025);
        f.pixels[i] = distance > 0 && x >= 0 && x < 640 && y >= 0 && y < 480
                          ? texture.pixels[std::size_t(y * 640 + x)]
                          : 24;
    }
    return f;
}
} // namespace
int main() {
    std::string stage;
    try {
        stage = "factory calibration";
        const auto all =
            load_frametop_calibration(fixtures / "stereo-factory", "synthetic-factory-v1");
        const StereoRig rig{{all.at("slam_left"), all.at("slam_right")}};
        validate_stereo_rig(rig);
        check(std::abs(rig.cameras[0].origin_m[0] + .032) < 1e-12, "millimeters to meters");
        check(rig.cameras[0].rotation[4] == -1 && rig.cameras[0].rotation[8] == -1,
              "optical to OpenVR axes");
        auto invalid = rig;
        invalid.cameras[1].origin_m = invalid.cameras[0].origin_m;
        fails([&] { validate_stereo_rig(invalid); });
        invalid = rig;
        invalid.cameras[0].rotation[0] = 2;
        fails([&] { validate_stereo_rig(invalid); });
        invalid = rig;
        invalid.cameras[0].calibration.distortion = {-10, 0, 0, 0};
        fails([&] { validate_stereo_rig(invalid); });
        stage = "pairing";
        StereoFramePairer pairing(rig);
        pairing.push(frame(rig.cameras[1], 1'003'000'000));
        check(!pairing.poll(), "unpaired view");
        pairing.push(frame(rig.cameras[0]));
        auto pair = pairing.poll();
        check(pair && pair->skew_ns() == 3'000'000, "3 ms boundary");
        check(!pairing.poll(), "pair reused");
        pairing.push(frame(rig.cameras[0], 1'100'000'000));
        pairing.push(frame(rig.cameras[1], 1'103'000'001));
        check(!pairing.poll() && pairing.dropped_frames() == 1, "skew rejection");
        pairing.push(frame(rig.cameras[0], 1'104'000'000));
        check(bool(pairing.poll()), "recover after skew drop");
        fails([&] { pairing.push(frame(rig.cameras[0], 1'104'000'000)); });
        auto wrong = frame(rig.cameras[0], 2'000'000'000);
        wrong.clock_domain = "another-clock";
        fails([&] { pairing.push(wrong); });
        wrong = frame(rig.cameras[0], 2'000'000'000);
        wrong.width = 639;
        fails([&] { pairing.push(wrong); });
        StereoFramePairer bounded(rig);
        for (std::uint64_t i = 1; i <= 7; ++i)
            bounded.push(frame(rig.cameras[0], i));
        check(bounded.dropped_frames() == 3, "bounded queue");
        stage = "stereo geometry";
        const auto layout = load_phone_layout(fixtures / "synthetic-phone-layout.json");
        StereoPoseEstimator estimator(layout, rig);
        StereoPair input{{frame(rig.cameras[0]), frame(rig.cameras[1], 1'000'100'000)}};
        cv::Matx33d rotation;
        cv::Rodrigues(cv::Vec3d(.18, -.22, .12), rotation);
        const cv::Vec3d translation(.008, .003, -.31);
        std::array<DetectionBatch, 2> batch;
        for (std::size_t v = 0; v < 2; ++v)
            batch[v] = observations(layout, input.frames[v], rig.cameras[v], rotation, translation);
        for (std::size_t corner = 0; corner < 4; ++corner) {
            const auto p = triangulate_stereo(rig, {batch[0].detections[0].corners[corner],
                                                    batch[1].detections[0].corners[corner]});
            check(bool(p), "triangulation failed");
            check(cv::norm(v(p->point) -
                           (rotation * v(layout.markers.at(0)[corner]) + translation)) < 1e-8,
                  "independent triangulation accuracy");
        }
        accuracy(estimator.estimate(input, batch), rotation, translation, 1e-7, 1e-6);
        auto noisy = batch;
        for (std::size_t view = 0; view < 2; ++view)
            for (std::size_t tag = 0; tag < 4; ++tag)
                for (std::size_t k = 0; k < 4; ++k) {
                    noisy[view].detections[tag].corners[k].x +=
                        .15 * std::sin(double(13 * view + 3 * tag + k));
                    noisy[view].detections[tag].corners[k].y +=
                        .15 * std::cos(double(7 * view + 5 * tag + k));
                }
        accuracy(estimator.estimate(input, noisy), rotation, translation, .001, .02);
        auto corrupt = batch;
        corrupt[1].detections[3].corners[0].y += 30;
        const auto consensus = estimator.estimate(input, corrupt);
        accuracy(consensus, rotation, translation, 1e-7, 1e-6);
        check(consensus.candidates[0].inlier_ids.size() == 3, "whole-marker outlier rejection");
        auto blank = batch;
        blank[1].detections.clear();
        check(estimator.estimate(input, blank).status == "insufficient_tags",
              "missing second view");
        auto duplicate = batch;
        duplicate[0].detections.push_back(duplicate[0].detections[0]);
        check(estimator.estimate(input, duplicate).status == "rejected", "duplicate tag");
        auto swap = batch;
        for (std::size_t v = 0; v < 2; ++v)
            for (std::size_t i = 0; i < 4; ++i)
                swap[v].detections[i].corners = batch[1 - v].detections[i].corners;
        check(estimator.estimate(input, swap).status == "rejected", "camera name swap");
        check(!triangulate_stereo(rig, {{{319.5, 239.5}, {319.5, 239.5}}}), "parallel rays");
        auto badpair = input;
        badpair.frames[1].capture_time_ns += 4'000'000;
        fails([&] { estimator.estimate(badpair, batch); });
        stage = "JSONL metadata";
        std::ostringstream output;
        write_stereo_jsonl(output, input, estimator, consensus);
        const auto json = nlohmann::json::parse(output.str());
        check(json["transform"] == "T_HP" && json["capture_skew_ns"] == 100000 &&
                  json["frames"][1]["capture_timestamp_ns"] == 1'000'100'000,
              "stereo provenance");
        stage = "real raster detection in both cameras";
        StereoPair rendered{{render(rig.cameras[0], rotation, translation),
                             render(rig.cameras[1], rotation, translation)}};
        AprilTag36h11Detector detector;
        std::array<DetectionBatch, 2> detected{detector.detect(rendered.frames[0]),
                                               detector.detect(rendered.frames[1])};
        check(detected[0].detections.size() == 4 && detected[1].detections.size() == 4,
              "both rendered views must decode");
        accuracy(estimator.estimate(rendered, detected), rotation, translation, .003, .04);
        stage = "factory transform composition and validation";
        const auto temp = std::filesystem::temp_directory_path() /
                          ("framephone-factory-" + std::to_string(getpid()));
        struct Cleanup {
            std::filesystem::path p;
            ~Cleanup() {
                std::filesystem::remove_all(p);
            }
        } cleanup{temp};
        std::filesystem::create_directories(temp / "persist");
        auto read = [](auto p) {
            std::ifstream f(p);
            return nlohmann::json::parse(f);
        };
        auto dev = read(fixtures / "stereo-factory/persist/device_config.json");
        auto factory = read(fixtures / "stereo-factory/persist/xrservice.json");
        // CAD<-head rotates 90 deg about Z and translates. CAD<-cam0 retains
        // the original rotation but also translates; expected head origin is
        // R_head^T * (CAD_camera_origin - CAD_head_origin).
        dev["head"]["plus_x"] = {0, 1, 0};
        dev["head"]["position"] = {.1, .2, .3};
        dev["cv"]["cad_from_cal"]["position"] = {.4, .5, .6};
        auto save = [&] {
            std::ofstream(temp / "persist/device_config.json") << dev;
            std::ofstream(temp / "persist/xrservice.json") << factory;
        };
        save();
        const auto composed = load_frametop_calibration(temp, "test").at("slam_left");
        check(std::abs(composed.origin_m[0] - .3) < 1e-12 &&
                  std::abs(composed.origin_m[1] + .268) < 1e-12 &&
                  std::abs(composed.origin_m[2] - .3) < 1e-12,
              "nonidentity CAD/head composition");
        dev["head"]["plus_x"] = {0, 2, 0};
        save();
        fails([&] { load_frametop_calibration(temp, "test"); });
        dev["head"]["plus_x"] = {0, 1, 0};
        factory["cameras"][0]["intrinsics"][0].erase("k1");
        save();
        fails([&] { load_frametop_calibration(temp, "test"); });
        std::cout << "Stereo calibration, pairing, joint pose and real detector checks passed\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << stage << ": " << e.what() << '\n';
        return 1;
    }
}
