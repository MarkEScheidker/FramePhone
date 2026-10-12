#include "framephone/pose.hpp"
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <opencv2/calib3d.hpp>
#include <opencv2/imgproc.hpp>
#include <sstream>
#include <unistd.h>

using namespace framephone;
namespace {
std::string stage;
void check(bool condition, const std::string &message) {
    if (!condition)
        throw std::runtime_error(message);
}
template <class F> void fails(F function) {
    bool failed = false;
    try {
        function();
    } catch (const std::exception &) {
        failed = true;
    }
    check(failed, "expected calibration failure");
}
const std::filesystem::path fixtures = FRAMEPHONE_TEST_DATA;
const auto layout_path = fixtures / "synthetic-phone-layout.json",
           camera_path = fixtures / "synthetic-camera.json";
const cv::Matx33d base(1, 0, 0, 0, -1, 0, 0, 0, -1);
cv::Matx33d tilted() {
    cv::Matx33d tilt;
    cv::Rodrigues(cv::Vec3d(0.28, -0.32, 0.08), tilt);
    return tilt * base;
}
DetectionBatch observations(const PhoneLayout &layout, const CameraCalibration &c,
                            const CameraFrame &frame, const cv::Matx33d &rotation,
                            cv::Vec3d translation) {
    cv::Vec3d r;
    cv::Rodrigues(rotation, r);
    DetectionBatch batch;
    for (const auto &[id, points] : layout.markers) {
        std::vector<cv::Point3d> object;
        for (const auto &p : points)
            object.emplace_back(p.x, p.y, p.z);
        std::vector<cv::Point2d> image;
        cv::Matx33d k(c.fx, 0, c.cx, 0, c.fy, c.cy, 0, 0, 1);
        if (c.model == "fisheye_kb4")
            cv::fisheye::projectPoints(object, image, r, translation, k, c.distortion);
        else
            cv::projectPoints(object, r, translation, k, c.distortion, image);
        TagDetection detection;
        detection.id = id;
        detection.camera_id = frame.camera_id;
        detection.capture_time_ns = frame.capture_time_ns;
        detection.decision_margin = 100;
        for (std::size_t i = 0; i < 4; ++i)
            detection.corners[i] = {image[i].x, image[i].y};
        batch.detections.push_back(detection);
    }
    return batch;
}
void accuracy(const PoseResult &result, const cv::Matx33d &expected, cv::Vec3d translation,
              double meters, double radians) {
    check(
        result.status == "accepted",
        "pose not accepted: " + result.status + " best rms " +
            (result.candidates.empty() ? "none" : std::to_string(result.candidates[0].rms_px)) +
            " second " +
            (result.candidates.size() < 2 ? "none" : std::to_string(result.candidates[1].rms_px)));
    const auto &pose = result.candidates.at(0);
    double trace{}, square{};
    for (std::size_t i = 0; i < 9; ++i)
        trace += pose.rotation_row_major[i] * expected.val[i];
    for (std::size_t i = 0; i < 3; ++i)
        square += std::pow(pose.translation_m[i] - translation[int(i)], 2);
    check(std::sqrt(square) < meters, "translation error: " + std::to_string(std::sqrt(square)));
    check(std::acos(std::clamp((trace - 1) / 2, -1.0, 1.0)) < radians, "rotation error");
}
struct TemporaryJson {
    std::filesystem::path path = std::filesystem::temp_directory_path() /
                                 ("framephone-pose-" + std::to_string(getpid()) + ".json");
    ~TemporaryJson() {
        std::filesystem::remove(path);
    }
    void save(const nlohmann::json &j) {
        std::ofstream(path) << j.dump();
    }
};
} // namespace
int main() {
    try {
        auto layout = load_phone_layout(layout_path);
        auto c = load_camera_calibration(camera_path);
        auto frame = *SyntheticFrameSource().next();
        PlanarPoseEstimator estimator(layout, c);
        AprilTag36h11Detector detector;
        const auto actual = detector.detect(frame);
        check(actual.detections.size() == 4, "real synthetic detector missing tags");
        stage = "real frontal raster";
        accuracy(estimator.estimate(frame, actual), base, {0, 0, 0.2}, 0.001, 0.05);
        const auto rotation = tilted();
        const cv::Vec3d translation(0.01, -0.005, 0.28);
        auto detected = observations(layout, c, frame, rotation, translation);
        stage = "tilted exact corners";
        accuracy(estimator.estimate(frame, detected), rotation, translation, 1e-6, 1e-5);
        for (int q = 0; q < 4; ++q) {
            stage = "tilted roll and nonzero translation " + std::to_string(q);
            cv::Matx33d roll;
            cv::Rodrigues(cv::Vec3d(0, 0, q * CV_PI / 2), roll);
            const auto rr = roll * rotation;
            const auto tt = roll * translation;
            accuracy(estimator.estimate(frame, observations(layout, c, frame, rr, tt)), rr, tt,
                     1e-6, 1e-5);
        }
        auto noisy = detected;
        for (auto &tag : noisy.detections)
            for (std::size_t i = 0; i < 4; ++i) {
                tag.corners[i].x += 0.15 * std::sin(tag.id * 4 + double(i));
                tag.corners[i].y += 0.15 * std::cos(tag.id * 4 + double(i));
            }
        stage = "subpixel corner noise";
        accuracy(estimator.estimate(frame, noisy), rotation, translation, 0.003, 0.03);
        auto bad = detected;
        for (auto &p : bad.detections[0].corners) {
            p.x += 35;
            p.y += 15;
        }
        const auto robust = estimator.estimate(frame, bad);
        stage = "one outlier marker";
        accuracy(robust, rotation, translation, 1e-6, 1e-5);
        check(robust.candidates[0].inlier_ids.size() == 3, "outlier tag was retained");
        auto partial = detected;
        partial.detections.resize(2);
        stage = "two remaining markers";
        accuracy(estimator.estimate(frame, partial), rotation, translation, 1e-6, 1e-5);
        partial.detections.resize(1);
        check(estimator.estimate(frame, partial).status == "insufficient_tags",
              "single tag accepted");
        check(estimator.estimate(frame, {}).status == "insufficient_tags", "blank pose held");
        bad = detected;
        bad.detections.push_back(bad.detections[0]);
        check(estimator.estimate(frame, bad).status == "rejected", "duplicate IDs accepted");
        bad = detected;
        bad.detections[0].capture_time_ns++;
        fails([&] { estimator.estimate(frame, bad); });
        auto wrong = frame;
        wrong.calibration_id = "wrong";
        fails([&] { estimator.estimate(wrong, detected); });
        wrong = frame;
        wrong.camera_id = "wrong";
        fails([&] { estimator.estimate(wrong, detected); });

        // Fisheye observations must be unprojected with KB4, and scored through
        // that model again in original pixels rather than pinhole image space.
        auto fish = c;
        fish.model = "fisheye_kb4";
        fish.distortion = {0.04, -0.01, 0.002, 0.0};
        PlanarPoseEstimator fisheye(layout, fish);
        stage = "fisheye";
        accuracy(fisheye.estimate(frame, observations(layout, fish, frame, rotation, translation)),
                 rotation, translation, 1e-6, 1e-5);

        // A small, distant plane has distinct orientations with nearly equal
        // pixel residuals: report ambiguity, never silently choose one.
        auto distant = observations(layout, c, frame, rotation, {0, 0, 3});
        check(estimator.estimate(frame, distant).status == "ambiguous",
              "distant plane ambiguity hidden");

        // Independently rotate an actual decoded image, checking canonical
        // corner association against the known optical-camera roll.
        for (int q = 0; q < 4; ++q) {
            stage = "raster rotation " + std::to_string(q);
            auto rotated = frame;
            if (q % 2) {
                rotated.width = frame.height;
                rotated.height = frame.width;
                rotated.stride_bytes = rotated.width;
            }
            for (std::uint32_t y = 0; y < frame.height; ++y)
                for (std::uint32_t x = 0; x < frame.width; ++x) {
                    std::uint32_t u = x, v = y;
                    if (q == 1) {
                        u = frame.height - 1 - y;
                        v = x;
                    }
                    if (q == 2) {
                        u = frame.width - 1 - x;
                        v = frame.height - 1 - y;
                    }
                    if (q == 3) {
                        u = y;
                        v = frame.width - 1 - x;
                    }
                    rotated.pixels[std::size_t(v) * rotated.stride_bytes + u] =
                        frame.pixels[std::size_t(y) * frame.stride_bytes + x];
                }
            auto rc = c;
            rc.width = rotated.width;
            rc.height = rotated.height;
            rc.cx = (rc.width - 1) / 2.0;
            rc.cy = (rc.height - 1) / 2.0;
            cv::Matx33d roll;
            cv::Rodrigues(cv::Vec3d(0, 0, q * CV_PI / 2), roll);
            accuracy(PlanarPoseEstimator(layout, rc).estimate(rotated, detector.detect(rotated)),
                     roll * base, {0, 0, 0.2}, 0.001, 0.05);
        }

        // Project the complete raster through a known homography; use decoded
        // pixels (rather than exact generated corner observations) for the pose.
        std::vector<cv::Point3d> plane;
        for (const cv::Point2d &px :
             std::vector<cv::Point2d>{{0, 0}, {639, 0}, {639, 479}, {0, 479}})
            plane.emplace_back((px.x + 0.5 - 320) * 0.00025, (240 - px.y - 0.5) * 0.00025, 0);
        cv::Vec3d r;
        cv::Rodrigues(rotation, r);
        std::vector<cv::Point2d> corners;
        cv::projectPoints(plane, r, translation, cv::Matx33d(800, 0, 319.5, 0, 800, 239.5, 0, 0, 1),
                          cv::noArray(), corners);
        std::vector<cv::Point2f> target;
        for (const auto &p : corners)
            target.emplace_back(float(p.x), float(p.y));
        auto projected = frame;
        cv::Mat input(480, 640, CV_8UC1, frame.pixels.data()),
            output(480, 640, CV_8UC1, projected.pixels.data());
        cv::warpPerspective(
            input, output,
            cv::getPerspectiveTransform(
                std::vector<cv::Point2f>{{0, 0}, {639, 0}, {639, 479}, {0, 479}}, target),
            output.size(), cv::INTER_NEAREST, cv::BORDER_CONSTANT, 24);
        auto projected_tags = detector.detect(projected);
        check(projected_tags.detections.size() == 4, "perspective raster lost tags");
        stage = "projected raster";
        accuracy(estimator.estimate(projected, projected_tags), rotation, translation, 0.004, 0.08);

        TemporaryJson temporary;
        nlohmann::json json;
        std::ifstream(layout_path) >> json;
        const auto original = json;
        // Rotate the exported display coordinate system while preserving phone
        // anchors and counter-rotated raster orientation, as Android does.
        for (int q = 0; q < 4; ++q) {
            json = original;
            const int w = q % 2 ? 480 : 640, h = q % 2 ? 640 : 480;
            json["display"]["logical_px"] = {w, h};
            json["display"]["portrait_quarter_turns"] = q;
            json["display"]["rotation_surface"] = q;
            json["display"]["T_PD"]["quaternion_xyzw"] = {0, 0, std::sin(-q * CV_PI / 4),
                                                          std::cos(-q * CV_PI / 4)};
            for (auto &marker : json["markers"]) {
                std::vector<std::array<double, 2>> pixels;
                for (const auto &point : marker["corners_phone_m"]) {
                    double x = point[0], y = point[1];
                    for (int turn = 0; turn < q; ++turn) {
                        double old = x;
                        x = -y;
                        y = old;
                    }
                    pixels.push_back({x / 0.00025 + w / 2.0, h / 2.0 - y / 0.00025});
                }
                double l = 1e9, t = 1e9, right = -1e9, bottom = -1e9;
                for (const auto &p : pixels) {
                    l = std::min(l, p[0]);
                    t = std::min(t, p[1]);
                    right = std::max(right, p[0]);
                    bottom = std::max(bottom, p[1]);
                }
                const std::array<std::array<double, 2>, 4> sorted{
                    {{l, t}, {right, t}, {right, bottom}, {l, bottom}}};
                marker["corners_display_px"] = sorted;
                for (std::size_t i = 0; i < 4; ++i) {
                    double x = (sorted[i][0] - w / 2.0) * 0.00025,
                           y = (h / 2.0 - sorted[i][1]) * 0.00025;
                    for (int turn = 0; turn < q; ++turn) {
                        double old = x;
                        x = y;
                        y = -old;
                    }
                    marker["corners_phone_m"][i] = {x, y, 0};
                }
                marker["image_rotation_clockwise_deg"] = ((4 - q) % 4) * 90;
            }
            temporary.save(json);
            const auto oriented = load_phone_layout(temporary.path);
            for (const auto &[id, points] : layout.markers)
                for (std::size_t i = 0; i < 4; ++i)
                    check(std::abs(points[i].x - oriented.markers.at(id)[i].x) < 1e-8 &&
                              std::abs(points[i].y - oriented.markers.at(id)[i].y) < 1e-8,
                          "phone rotation changed canonical corners");
        }
        json = original;
        json["markers"][0]["corners_phone_m"][0][0] = 0;
        temporary.save(json);
        fails([&] { load_phone_layout(temporary.path); });
        json = original;
        json["family"] = "other";
        temporary.save(json);
        fails([&] { load_phone_layout(temporary.path); });
        json = original;
        json["markers"][1]["id"] = 0;
        temporary.save(json);
        fails([&] { load_phone_layout(temporary.path); });
        json = original;
        json["calibration"]["status"] = "reported_dpi";
        temporary.save(json);
        fails([&] { load_phone_layout(temporary.path); });
        std::ifstream(camera_path) >> json;
        const auto camera_json = json;
        json["intrinsics"]["fx"] = 0;
        temporary.save(json);
        fails([&] { load_camera_calibration(temporary.path); });
        json = camera_json;
        json["model"] = "fisheye_kb4";
        temporary.save(json);
        fails([&] { load_camera_calibration(temporary.path); });
        json = camera_json;
        json["status"] = "guessed";
        temporary.save(json);
        fails([&] { load_camera_calibration(temporary.path); });
        std::ofstream(temporary.path) << "{\"schema\":1,\"schema\":2}";
        fails([&] { load_phone_layout(temporary.path); });
        std::ostringstream stream;
        auto large = frame;
        large.capture_time_ns = 9'007'199'254'740'993ULL;
        write_pose_jsonl(stream, large, estimator, robust);
        auto exported = nlohmann::json::parse(stream.str());
        check(exported["capture_timestamp_ns"].get<std::uint64_t>() == large.capture_time_ns,
              "JSONL lost timestamp precision");
        check(exported["transform"] == "T_CP" && exported["calibration_status"] == "synthetic",
              "pose export mislabeled");
        std::cout << "Pose tests passed: real raster, 4 rotations, perspective, pinhole/KB4, "
                     "outliers, ambiguity and calibration rejection.\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << stage << ": " << e.what() << '\n';
        return 1;
    }
}
