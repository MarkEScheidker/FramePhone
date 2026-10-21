#include "framephone/photo.hpp"
#include "framephone/stereo_recording.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <opencv2/calib3d.hpp>
#include <opencv2/imgproc.hpp>

using namespace framephone;
namespace {
using Json = nlohmann::json;
const cv::Matx33d hc(1, 0, 0, 0, -1, 0, 0, 0, -1);
std::string scenario = "setup";
void check(bool ok, const std::string &why) {
    if (!ok)
        throw std::runtime_error(scenario + ": " + why);
}
StereoRig rig() {
    StereoRig r;
    for (std::size_t v = 0; v < 2; ++v) {
        auto &c = r.cameras[v];
        c.calibration = {
            "test", v ? "right" : "left",     "fisheye_kb4", "synthetic", 640, 480, 600, 610, 319.5,
            239.5,  {.04, -.01, .001, -.0001}};
        std::copy_n(hc.val, 9, c.rotation.begin());
        c.origin_m = {v ? .032 : -.032, 0, 0};
    }
    return r;
}
StereoPair blank(const StereoRig &r) {
    StereoPair pair;
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &k = r.cameras[v].calibration;
        pair.frames[v] = {k.camera_id,
                          k.width,
                          k.height,
                          k.width,
                          PixelFormat::Gray8,
                          1'000'000'000 + v * 100000,
                          "synthetic",
                          k.id,
                          {},
                          std::vector<std::uint8_t>(std::size_t(k.width) * k.height, 100)};
    }
    return pair;
}
std::array<ImagePoint, 2> project(const StereoRig &rig, cv::Vec3d p) {
    std::array<ImagePoint, 2> out;
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &k = rig.cameras[v].calibration;
        cv::Vec3d camera = cv::Matx33d(rig.cameras[v].rotation.data()).t() *
                           (p - cv::Vec3d(rig.cameras[v].origin_m.data()));
        std::vector<cv::Point3d> points{{camera[0], camera[1], camera[2]}};
        std::vector<cv::Point2d> pixels;
        cv::fisheye::projectPoints(points, pixels, cv::Vec3d{}, cv::Vec3d{},
                                   cv::Matx33d(k.fx, 0, k.cx, 0, k.fy, k.cy, 0, 0, 1),
                                   k.distortion);
        out[v] = {pixels[0].x, pixels[0].y};
    }
    return out;
}
CameraFrame reference() {
    CameraFrame f{"reference",
                  480,
                  720,
                  480,
                  PixelFormat::Gray8,
                  1,
                  "static_reference",
                  "synthetic-photo",
                  {},
                  std::vector<std::uint8_t>(480 * 720)};
    cv::Mat image(720, 480, CV_8U, f.pixels.data());
    image.setTo(210);
    cv::RNG rng(516829);
    for (int i = 0; i < 380; ++i) {
        // Function argument evaluation order differs between GCC's AMD64 and
        // ARM64 targets. Sequence RNG draws explicitly to render the same photo
        // on both, preserving the original AMD64 fixture's draw order.
        const auto y = rng.uniform(4, 716);
        const auto x = rng.uniform(4, 476);
        cv::Point p(x, y);
        int radius = rng.uniform(3, 19);
        const auto thickness = rng.uniform(1, 4);
        const auto intensity = rng.uniform(0, 255);
        cv::circle(image, p, radius, cv::Scalar(intensity), thickness, cv::LINE_AA);
        if (i % 4 == 0) {
            const auto line_intensity = rng.uniform(0, 255);
            const auto end_y = rng.uniform(0, 720);
            const auto end_x = rng.uniform(0, 480);
            cv::line(image, p, cv::Point(end_x, end_y), cv::Scalar(line_intensity), 1, cv::LINE_AA);
        }
    }
    return f;
}
StereoPair render(const StereoRig &r, const CameraFrame &ref, cv::Matx33d rotation, cv::Vec3d t) {
    auto pair = blank(r);
    double width = .072, height = width * ref.height / ref.width;
    cv::Mat image(int(ref.height), int(ref.width), CV_8U,
                  const_cast<std::uint8_t *>(ref.pixels.data()));
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &k = r.cameras[v].calibration;
        auto &f = pair.frames[v];
        std::vector<cv::Point2d> native, rays;
        for (unsigned y = 0; y < k.height; ++y)
            for (unsigned x = 0; x < k.width; ++x)
                native.emplace_back(x, y);
        cv::fisheye::undistortPoints(
            native, rays, cv::Matx33d(k.fx, 0, k.cx, 0, k.fy, k.cy, 0, 0, 1), k.distortion);
        cv::Mat mapx(int(k.height), int(k.width), CV_32F), mapy(mapx.size(), CV_32F);
        auto origin = rotation.t() * (cv::Vec3d(r.cameras[v].origin_m.data()) - t);
        for (std::size_t i = 0; i < rays.size(); ++i) {
            auto ray = rotation.t() * cv::Matx33d(r.cameras[v].rotation.data()) *
                       cv::Vec3d(rays[i].x, rays[i].y, 1);
            double distance = -origin[2] / ray[2];
            auto p = origin + ray * distance;
            mapx.at<float>(int(i)) =
                distance > 0 ? float((p[0] / width + .5) * ref.width - .5) : -100;
            mapy.at<float>(int(i)) =
                distance > 0 ? float((.5 - p[1] / height) * ref.height - .5) : -100;
        }
        cv::Mat output(int(f.height), int(f.width), CV_8U, f.pixels.data());
        cv::remap(image, output, mapx, mapy, cv::INTER_LINEAR, cv::BORDER_CONSTANT,
                  cv::Scalar(100));
        cv::GaussianBlur(output, output, {3, 3}, .45);
    }
    return pair;
}
void accuracy(const PhotoPose &p, cv::Matx33d r, cv::Vec3d t, double meters, double radians) {
    check(p.status == "measured",
          "rejected: " + p.reason + " inliers " + std::to_string(p.view_inliers[0]) + "/" +
              std::to_string(p.view_inliers[1]) + " candidates " +
              std::to_string(p.descriptor_matches[0]) + "/" +
              std::to_string(p.descriptor_matches[1]) + " scene " +
              std::to_string(p.scene_features[0]) + "/" + std::to_string(p.scene_features[1]));
    check(cv::norm(cv::Vec3d(p.pose.translation_m.data()) - t) < meters, "translation error");
    double trace = 0;
    for (int i = 0; i < 9; ++i)
        trace += p.pose.rotation[std::size_t(i)] * r.val[i];
    check(std::acos(std::clamp((trace - 1) / 2, -1., 1.)) < radians, "orientation error");
    check(std::abs(p.width_m - .072) < meters, "stereo width error");
}
} // namespace
int main(int argc, char **argv) {
    try {
        cv::setNumThreads(2);
        auto r = rig();
        auto pair = blank(r);
        auto ref = reference();
        cv::Matx33d rotation;
        cv::Rodrigues(cv::Vec3d(.14, -.25, .19), rotation);
        cv::Vec3d t(.012, -.015, -.45);
        if (argc == 3 && std::string(argv[1]) == "--write-trial") {
            std::filesystem::path directory = argv[2];
            check(std::filesystem::create_directory(directory), "new fixture required");
            std::filesystem::copy(std::filesystem::path(FRAMEPHONE_TEST_DATA) / "stereo-factory",
                                  directory / "factory", std::filesystem::copy_options::recursive);
            // Render using imported calibration so ring/CLI/GUI share the exact fixture identity.
            auto all = load_frametop_calibration(directory / "factory", "synthetic-factory-v1");
            r = {{all.at("slam_left"), all.at("slam_right")}};
            std::filesystem::create_directory(directory / "reference");
            write_pgm(directory / "reference/photo.pgm", ref);
            std::ofstream(directory / "reference/manifest.tsv")
                << "framephone-recording-v1\nreference\t1\tstatic_reference\tsynthetic-photo\t-"
                   "\tphoto.pgm\n";
            Json config{{"schema", "framephone-photo-session-v1"},
                        {"reference_id", "synthetic-photo"},
                        {"phone_session", "synthetic-phone"},
                        {"calibration_id", "synthetic-factory-v1"},
                        {"left", "slam_left"},
                        {"right", "slam_right"},
                        {"left_stream", "slam_left"},
                        {"right_stream", "slam_right"},
                        {"capture_clock", "synthetic"},
                        {"record", false}};
            std::ofstream(directory / "session.json") << config.dump();
            StereoRecorder recorder(directory / "motion");
            for (std::uint64_t i = 1; i <= 3; ++i) {
                auto frames = i == 2 ? blank(r) : render(r, ref, rotation, t);
                for (std::size_t v = 0; v < 2; ++v)
                    frames.frames[v].capture_time_ns = 1'000'000'000 + i * 33'333'333 + v * 100000;
                recorder.write(frames, i);
            }
            return 0;
        }
        std::vector<PhotoMatch> matches;
        for (int y = 0; y < 7; ++y)
            for (int x = 0; x < 6; ++x) {
                ImagePoint p{-.42 + x * .16, .65 - y * .21};
                auto world = rotation * cv::Vec3d(p.x * .072, p.y * .072, 0) + t;
                matches.push_back({p, project(r, world)});
            }
        scenario = "exact stereo correspondences";
        auto estimate = estimate_photo_pose(r, pair, matches, 1.5);
        accuracy(estimate, rotation, t, 1e-5, 1e-4);
        scenario = "opposite quarter-turn camera mounts";
        auto rolled = r;
        for (std::size_t v = 0; v < 2; ++v) {
            cv::Matx33d roll;
            cv::Rodrigues(cv::Vec3d(0, 0, v ? CV_PI / 2 : -CV_PI / 2), roll);
            auto orientation = hc * roll;
            std::copy_n(orientation.val, 9, rolled.cameras[v].rotation.begin());
        }
        auto rolled_matches = matches;
        for (auto &m : rolled_matches)
            m.pixels = project(
                rolled, rotation * cv::Vec3d(m.reference.x * .072, m.reference.y * .072, 0) + t);
        accuracy(estimate_photo_pose(rolled, pair, rolled_matches, 1.5), rotation, t, 1e-5, 1e-4);
        scenario = "previous-pose initialization";
        auto moved_matches = matches;
        const auto moved_t = t + cv::Vec3d(.01, -.005, .015);
        for (auto &m : moved_matches)
            m.pixels = project(
                r, rotation * cv::Vec3d(m.reference.x * .072, m.reference.y * .072, 0) + moved_t);
        accuracy(estimate_photo_pose(r, pair, moved_matches, 1.5, &estimate), rotation, moved_t,
                 1e-5, 1e-4);
        check(estimate_photo_pose(r, pair, {}, 1.5, &estimate).status == "lost",
              "previous pose substituted for missing observations");
        scenario = "outlier rejection";
        for (std::size_t i = 0; i < 8; ++i) {
            auto wrong = matches[i];
            wrong.reference.x += .25;
            wrong.reference.y -= .25;
            matches.push_back(wrong);
        }
        accuracy(estimate_photo_pose(r, pair, matches, 1.5), rotation, t, 1e-5, 1e-4);
        scenario = "spatial coverage rejection";
        auto clustered = matches;
        for (auto &m : clustered) {
            m.reference.x *= .1;
            m.reference.y *= .1;
        }
        check(estimate_photo_pose(r, pair, clustered, 1.5).status != "measured",
              "clustered matches accepted");
        std::vector<PhotoMatch> low_coverage;
        for (int y = 0; y < 4; ++y)
            for (int x = 0; x < 4; ++x) {
                ImagePoint p{-.2 + x * .03, .2 - y * .03};
                low_coverage.push_back(
                    {p, project(r, rotation * cv::Vec3d(p.x * .072, p.y * .072, 0) + t)});
            }
        auto small_patch = estimate_photo_pose(r, pair, low_coverage, 1.5);
        check(small_patch.status == "lost" && small_patch.reason == "insufficient_spatial_coverage",
              "small patch accepted as a full photo pose");
        check(estimate_photo_pose(r, pair, low_coverage, 1.5, &estimate).status == "lost",
              "previous pose bypassed current coverage requirement");
        scenario = "calibration and clock rejection";
        auto wrong = pair;
        wrong.frames[1].calibration_id = "wrong";
        bool rejected = false;
        try {
            estimate_photo_pose(r, wrong, matches, 1.5);
        } catch (const std::invalid_argument &) {
            rejected = true;
        }
        check(rejected, "calibration mismatch accepted");
        wrong = pair;
        wrong.frames[1].capture_time_ns = wrong.frames[0].capture_time_ns + 3'000'001;
        rejected = false;
        try {
            estimate_photo_pose(r, wrong, matches, 1.5);
        } catch (const std::invalid_argument &) {
            rejected = true;
        }
        check(rejected, "excessive stereo capture skew accepted");
        scenario = "raster acquisition";
        PhotoTracker tracker(ref, r);
        auto photo = render(r, ref, rotation, t);
        auto result = tracker.update(photo);
        accuracy(result, rotation, t, .008, .08);
        check(result.matches.size() >= 12, "not enough stereo features");
        scenario = "blank image";
        auto lost = tracker.update(blank(r));
        check(lost.status == "lost" && lost.reason == "too_few_camera_features" &&
                  lost.scene_features[0] == 0 && lost.scene_features[1] == 0 &&
                  lost.matches.empty(),
              "lost photo reused previous pose or hid diagnostic stage");
        scenario = "one-camera visibility";
        auto one_eye = photo;
        one_eye.frames[1] = blank(r).frames[1];
        auto partial = tracker.update(one_eye);
        check(partial.status == "lost" && partial.view_inliers[0] >= 12 &&
                  !partial.view_points[0].empty() && partial.view_points[1].empty() &&
                  partial.stereo_candidates == 0 && partial.matches.empty(),
              "one-view recognition was hidden or promoted to a stereo pose");
        scenario = "inconsistent stereo";
        auto inconsistent = photo;
        inconsistent.frames[1] = render(r, ref, rotation, t + cv::Vec3d(0, .05, 0)).frames[1];
        auto bad_stereo = tracker.update(inconsistent);
        check(bad_stereo.status == "lost" && bad_stereo.view_inliers[0] >= 12 &&
                  bad_stereo.view_inliers[1] >= 12 && bad_stereo.matches.empty(),
              "inconsistent stereo views accepted or image evidence hidden");
        scenario = "reacquisition";
        accuracy(tracker.update(photo), rotation, t, .008, .08);
        auto angled = r;
        for (std::size_t v = 0; v < 2; ++v) {
            cv::Matx33d change;
            cv::Rodrigues(cv::Vec3d(.015, v ? .14 : -.12, v ? .02 : -.01), change);
            auto extrinsic = hc * change;
            std::copy_n(extrinsic.val, 9, angled.cameras[v].rotation.begin());
            angled.cameras[v].origin_m = {v ? .034 : -.031, v ? -.004 : .006, v ? -.005 : .003};
        }
        scenario = "nonparallel cameras";
        PhotoTracker angled_tracker(ref, angled);
        accuracy(angled_tracker.update(render(angled, ref, rotation, t)), rotation, t, .008, .08);
        auto wide = r;
        auto soft = ref;
        cv::Mat texture(int(soft.height), int(soft.width), CV_8U, soft.pixels.data());
        cv::GaussianBlur(texture, texture, {}, 4);
        for (double focal : {300., 340.}) {
            for (auto &camera : wide.cameras) {
                camera.calibration.fx = focal;
                camera.calibration.fy = focal;
            }
            PhotoTracker trial(soft, wide);
            auto visible = render(wide, soft, rotation, t);
            scenario = "small target, focal " + std::to_string(int(focal));
            accuracy(trial.update(visible), rotation, t, .015, .15);
            for (auto &frame : visible.frames)
                for (auto &pixel : frame.pixels)
                    pixel = std::uint8_t(75 + .45 * pixel);
            scenario += ", low contrast";
            accuracy(trial.update(visible), rotation, t, .02, .2);
        }
        auto high_resolution = r;
        for (auto &camera : high_resolution.cameras) {
            auto &k = camera.calibration;
            k.width = 1280;
            k.height = 1024;
            k.fx = 520;
            k.fy = 530;
            k.cx = 639.5;
            k.cy = 511.5;
        }
        scenario = "1280-pixel camera detail";
        PhotoTracker full_detail(ref, high_resolution);
        accuracy(full_detail.update(render(high_resolution, ref, rotation, t)), rotation, t, .012,
                 .12);
        std::cout
            << "Photo tests passed: independent fisheye raster, stereo scale/pose, outliers, "
               "small/low-contrast targets, 1280px detail, one-view diagnostics, inconsistent "
               "stereo, loss and reacquisition.\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
