#include "framephone/pose.hpp"

#include "calibration_json.hpp"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <numeric>
#include <opencv2/calib3d.hpp>
#include <set>

namespace framephone {
namespace {
using namespace calibration_json;
bool near(double a, double b) {
    return std::abs(a - b) <= 1e-8;
}
cv::Matx33d intrinsics(const CameraCalibration &c) {
    return {c.fx, 0, c.cx, 0, c.fy, c.cy, 0, 0, 1};
}
struct Observation {
    int id;
    std::array<cv::Point3d, 4> object;
    std::array<cv::Point2d, 4> image;
};
struct Candidate {
    cv::Mat r, t;
    PoseCandidate output;
};
std::vector<cv::Point2d> project(const std::vector<cv::Point3d> &object, const cv::Mat &r,
                                 const cv::Mat &t, const CameraCalibration &c) {
    std::vector<cv::Point2d> image;
    if (c.model == "fisheye_kb4")
        cv::fisheye::projectPoints(object, image, r, t, intrinsics(c), c.distortion);
    else
        cv::projectPoints(object, r, t, intrinsics(c), c.distortion, image);
    return image;
}
std::vector<Candidate> solve(const std::vector<Observation> &obs, const std::vector<int> &indices,
                             const CameraCalibration &c) {
    std::vector<cv::Point3d> object;
    std::vector<cv::Point2d> image, normalized;
    for (int i : indices) {
        // Solve in a right-handed plane basis whose normal points away from
        // the viewer. A front-facing phone then has near-identity rotation,
        // avoiding IPPE's 180-degree Rodrigues singularity at camera rolls.
        for (const auto &p : obs.at(std::size_t(i)).object)
            object.emplace_back(p.x, -p.y, -p.z);
        image.insert(image.end(), obs.at(std::size_t(i)).image.begin(),
                     obs.at(std::size_t(i)).image.end());
    }
    if (c.model == "fisheye_kb4")
        cv::fisheye::undistortPoints(image, normalized, intrinsics(c), c.distortion);
    else
        cv::undistortPoints(image, normalized, intrinsics(c), c.distortion);
    // Remove approximate image-plane roll in a virtual optical camera before
    // IPPE. In OpenCV 4.5, exact 180-degree plane rotations can produce invalid
    // Rodrigues outputs. Rotating rays preserves their geometry and distortion
    // model; restore both rotation AND translation into real C afterwards.
    const auto image_edge = normalized[1] - normalized[0];
    const auto object_edge = object[1] - object[0];
    const double roll =
        std::atan2(image_edge.y, image_edge.x) - std::atan2(object_edge.y, object_edge.x);
    const double cosine = std::cos(roll), sine = std::sin(roll);
    const cv::Mat camera_rotation(cv::Matx33d(cosine, -sine, 0, sine, cosine, 0, 0, 0, 1));
    for (auto &p : normalized) {
        const double x = p.x;
        p.x = cosine * x + sine * p.y;
        p.y = -sine * x + cosine * p.y;
    }
    std::vector<cv::Mat> rotations, translations;
    // IPPE accepts the actual rectangular quantized geometry and returns both
    // plane hypotheses. IPPE_SQUARE would impose an incorrect square/order.
    cv::solvePnPGeneric(object, normalized, cv::Matx33d::eye(), cv::noArray(), rotations,
                        translations, false, cv::SOLVEPNP_IPPE);
    std::vector<Candidate> result;
    for (std::size_t i = 0; i < rotations.size(); ++i) {
        Candidate candidate{rotations[i], translations[i], {}};
        cv::Mat rotation;
        cv::Rodrigues(candidate.r, rotation);
        rotation = camera_rotation * rotation;
        candidate.t = camera_rotation * candidate.t;
        bool valid = cv::checkRange(rotation) && cv::checkRange(candidate.t);
        for (const auto &p : object) {
            const double depth = rotation.at<double>(2, 0) * p.x + rotation.at<double>(2, 1) * p.y +
                                 candidate.t.at<double>(2);
            valid = valid && depth > 0.001;
        }
        if (!valid)
            continue;
        // Convert T_CB back to T_CP. This is a proper rotation, not a reflection.
        rotation = rotation * cv::Mat(cv::Matx33d(1, 0, 0, 0, -1, 0, 0, 0, -1));
        cv::Rodrigues(rotation, candidate.r);
        // Phone front (+Z_P) must face the camera, never its back.
        double facing{};
        for (int j = 0; j < 3; ++j)
            facing += rotation.at<double>(j, 2) * candidate.t.at<double>(j);
        if (!valid || facing >= 0)
            continue;
        result.push_back(std::move(candidate));
    }
    return result;
}
void score(Candidate &candidate, const std::vector<Observation> &observations,
           const CameraCalibration &c) {
    candidate.output.inlier_ids.clear();
    cv::Mat rotation;
    cv::Rodrigues(candidate.r, rotation);
    double total{};
    for (const auto &obs : observations) {
        const std::vector<cv::Point3d> object(obs.object.begin(), obs.object.end());
        const auto projected = project(object, candidate.r, candidate.t, c);
        double square{}, maximum{};
        bool positive_depth = true;
        for (std::size_t j = 0; j < 4; ++j) {
            const auto &p = object[j];
            positive_depth = positive_depth &&
                             rotation.at<double>(2, 0) * p.x + rotation.at<double>(2, 1) * p.y +
                                     rotation.at<double>(2, 2) * p.z + candidate.t.at<double>(2) >
                                 0.001;
            const double error = cv::norm(projected[j] - obs.image[j]);
            square += error * error;
            maximum = std::max(maximum, error);
        }
        // Reject whole markers. A single wrong corner cannot contribute three
        // apparently good points to a pose fit.
        if (positive_depth && std::isfinite(square) && maximum <= 3.0) {
            candidate.output.inlier_ids.push_back(obs.id);
            total += square;
        }
    }
    candidate.output.rms_px =
        candidate.output.inlier_ids.empty()
            ? 1e100
            : std::sqrt(total / (4 * double(candidate.output.inlier_ids.size())));
    for (int i = 0; i < 3; ++i) {
        candidate.output.translation_m[std::size_t(i)] = candidate.t.at<double>(i);
        for (int j = 0; j < 3; ++j)
            candidate.output.rotation_row_major[std::size_t(3 * i + j)] = rotation.at<double>(i, j);
    }
}
double rotation_distance(const PoseCandidate &a, const PoseCandidate &b) {
    double trace{};
    for (std::size_t i = 0; i < 9; ++i)
        trace += a.rotation_row_major[i] * b.rotation_row_major[i];
    return std::acos(std::clamp((trace - 1) / 2, -1.0, 1.0));
}
} // namespace

PhoneLayout load_phone_layout(const std::filesystem::path &path) {
    const auto j = read_json(path);
    require(j.at("schema") == "framephone.phone-layout" && j.at("layout_version") == 1 &&
                j.at("units") == "meters" && j.at("family") == "tag36h11",
            "unsupported phone layout schema/family/units");
    require(j.at("size_definition") == "detector_boundary_excluding_white_quiet_zone" &&
                j.at("corner_reference") == "rendered_tag_image_pixel_edges" &&
                j.at("corner_order") ==
                    Json({"top_left", "top_right", "bottom_right", "bottom_left"}),
            "unsupported phone corner convention");
    const auto &cal = j.at("calibration");
    require(cal.at("status") == "manual_measured" && cal.at("version") == 1,
            "phone requires measured display calibration v1");
    const double portrait_w = number(cal.at("portrait_width_m")),
                 portrait_h = number(cal.at("portrait_height_m"));
    require(portrait_w > 0 && portrait_h > 0 && portrait_w <= 2 && portrait_h <= 2,
            "invalid measured display size");
    const auto &display = j.at("display");
    array(display.at("logical_px"), 2);
    array(display.at("meters_per_pixel_xy"), 2);
    const int w = integer(display.at("logical_px")[0], 1, 65536),
              h = integer(display.at("logical_px")[1], 1, 65536);
    const int q = integer(display.at("portrait_quarter_turns"), 0, 3);
    require(display.at("natural_portrait").is_boolean(), "natural_portrait must be boolean");
    require(q == (integer(display.at("rotation_surface"), 0, 3) -
                  (display.at("natural_portrait").get<bool>() ? 0 : 1) + 4) %
                     4,
            "inconsistent display rotation");
    const double sx = number(display.at("meters_per_pixel_xy")[0]),
                 sy = number(display.at("meters_per_pixel_xy")[1]);
    require(near(sx, (q % 2 ? portrait_h : portrait_w) / w) &&
                near(sy, (q % 2 ? portrait_w : portrait_h) / h),
            "display scale disagrees with measured dimensions");
    const auto &transform = display.at("T_PD");
    array(transform.at("translation_m"), 3);
    array(transform.at("quaternion_xyzw"), 4);
    for (const auto &v : transform.at("translation_m"))
        require(near(number(v), 0), "unsupported display translation");
    const double angle = -q * std::acos(-1.0) / 2;
    const std::array<double, 4> quaternion{0, 0, std::sin(angle / 2), std::cos(angle / 2)};
    for (std::size_t i = 0; i < 4; ++i)
        require(near(number(transform.at("quaternion_xyzw")[i]), quaternion[i]),
                "inconsistent display transform");
    PhoneLayout result;
    result.revision = string(j.at("revision"));
    require(j.at("markers").is_array() && j.at("markers").size() <= 6, "invalid marker array");
    for (const auto &marker : j.at("markers")) {
        const int id = integer(marker.at("id"), 0, 5),
                  rotation = integer(marker.at("image_rotation_clockwise_deg"), 0, 270);
        require(rotation % 90 == 0, "marker raster rotation must be quarter turns");
        array(marker.at("corners_display_px"), 4);
        array(marker.at("corners_phone_m"), 4);
        std::array<Point3, 4> points;
        std::array<std::array<double, 2>, 4> pixels;
        for (std::size_t i = 0; i < 4; ++i) {
            array(marker.at("corners_display_px")[i], 2);
            array(marker.at("corners_phone_m")[i], 3);
            const auto &px = marker.at("corners_display_px")[i];
            const double u = number(px[0]), v = number(px[1]);
            require(u >= 0 && u <= w && v >= 0 && v <= h, "marker outside display");
            pixels[i] = {u, v};
            double x = (u - w / 2.0) * sx, y = (h / 2.0 - v) * sy;
            for (int turn = 0; turn < q; ++turn) {
                const double previous = x;
                x = y;
                y = -previous;
            }
            const auto &p = marker.at("corners_phone_m")[i];
            require(near(number(p[0]), x) && near(number(p[1]), y) && near(number(p[2]), 0),
                    "exported phone corners disagree with display calibration");
            points[i] = {x, y, 0};
        }
        require(pixels[0][0] < pixels[1][0] && pixels[0][1] < pixels[3][1] &&
                    pixels[0][1] == pixels[1][1] && pixels[1][0] == pixels[2][0] &&
                    pixels[2][1] == pixels[3][1] && pixels[3][0] == pixels[0][0],
                "marker corners must be display TL/TR/BR/BL");
        std::array<Point3, 4> canonical;
        for (std::size_t i = 0; i < 4; ++i)
            canonical[i] = points[(3 - i + std::size_t(rotation / 90)) % 4];
        require(result.markers.emplace(id, canonical).second, "duplicate marker ID");
    }
    const std::map<std::string, std::set<int>> layouts{{"FOUR_CORNERS", {0, 1, 2, 3}},
                                                       {"TWO_DIAGONAL", {0, 2}},
                                                       {"FOUR_EDGES", {0, 1, 2, 3}},
                                                       {"SIX_PHONE_FRAME", {0, 1, 2, 3, 4, 5}}};
    const auto selected = layouts.find(string(j.at("layout")));
    require(selected != layouts.end(), "unknown phone marker layout");
    std::set<int> ids;
    for (const auto &[id, points] : result.markers) {
        (void)points;
        ids.insert(id);
    }
    require(ids == selected->second, "marker ID set does not match selected layout");
    return result;
}

CameraCalibration load_camera_calibration(const std::filesystem::path &path) {
    const auto j = read_json(path);
    require(j.at("schema") == "framephone.camera-calibration" && j.at("version") == 1 &&
                j.at("pixel_convention") == "opencv_pixel_centers",
            "unsupported camera calibration schema/convention");
    CameraCalibration c;
    c.id = string(j.at("calibration_id"));
    c.camera_id = string(j.at("camera_id"));
    c.model = string(j.at("model"));
    c.status = string(j.at("status"));
    require(c.status == "calibrated" || c.status == "synthetic",
            "camera calibration must be calibrated or explicitly synthetic");
    require(c.model == "pinhole" || c.model == "fisheye_kb4", "unsupported camera model");
    array(j.at("image_size_px"), 2);
    c.width = static_cast<std::uint32_t>(integer(j.at("image_size_px")[0], 1, 16384));
    c.height = static_cast<std::uint32_t>(integer(j.at("image_size_px")[1], 1, 16384));
    const auto &k = j.at("intrinsics");
    c.fx = number(k.at("fx"));
    c.fy = number(k.at("fy"));
    c.cx = number(k.at("cx"));
    c.cy = number(k.at("cy"));
    require(c.fx > 0 && c.fy > 0 && c.cx >= 0 && c.cx < c.width && c.cy >= 0 && c.cy < c.height,
            "invalid camera intrinsics");
    const auto &d = j.at("distortion");
    require(d.is_array(), "distortion must be array");
    require(c.model == "fisheye_kb4" ? d.size() == 4
                                     : d.empty() || d.size() == 4 || d.size() == 5 || d.size() == 8,
            "incorrect distortion coefficient count");
    for (const auto &v : d)
        c.distortion.push_back(number(v));
    return c;
}

PlanarPoseEstimator::PlanarPoseEstimator(PhoneLayout layout, CameraCalibration calibration)
    : layout_(std::move(layout)), calibration_(std::move(calibration)) {}

PoseResult PlanarPoseEstimator::estimate(const CameraFrame &frame,
                                         const DetectionBatch &batch) const {
    frame.validate();
    require(frame.camera_id == calibration_.camera_id && frame.calibration_id == calibration_.id &&
                frame.width == calibration_.width && frame.height == calibration_.height,
            "frame camera/calibration identity or dimensions mismatch");
    std::vector<Observation> observations;
    std::set<int> seen;
    for (const auto &tag : batch.detections) {
        if (!layout_.markers.contains(tag.id))
            continue;
        require(tag.camera_id == frame.camera_id && tag.capture_time_ns == frame.capture_time_ns,
                "detection frame identity mismatch");
        if (!seen.insert(tag.id).second)
            return {"rejected", {}};
        if (tag.hamming != 0 || !std::isfinite(tag.decision_margin) || tag.decision_margin < 10)
            continue;
        Observation obs;
        obs.id = tag.id;
        for (std::size_t i = 0; i < 4; ++i) {
            const auto &p = layout_.markers.at(tag.id)[i];
            obs.object[i] = {p.x, p.y, p.z};
            const auto &v = tag.corners[i];
            if (!std::isfinite(v.x) || !std::isfinite(v.y) || v.x < 0 || v.y < 0 ||
                v.x >= frame.width || v.y >= frame.height)
                return {"rejected", {}};
            obs.image[i] = {v.x, v.y};
        }
        observations.push_back(obs);
    }
    if (observations.size() < 2)
        return {"insufficient_tags", {}};
    try {
        std::vector<Candidate> hypotheses;
        // At most six tags: enumerate all pairs rather than random trials.
        // Both IPPE hypotheses are scored against every marker in original pixels.
        for (std::size_t a = 0; a < observations.size(); ++a)
            for (std::size_t b = a + 1; b < observations.size(); ++b) {
                for (auto &candidate : solve(observations, {int(a), int(b)}, calibration_)) {
                    score(candidate, observations, calibration_);
                    if (candidate.output.inlier_ids.size() >= 2)
                        hypotheses.push_back(std::move(candidate));
                }
            }
        if (hypotheses.empty())
            return {"rejected", {}};
        auto better = [](const Candidate &a, const Candidate &b) {
            if (a.output.inlier_ids.size() != b.output.inlier_ids.size())
                return a.output.inlier_ids.size() > b.output.inlier_ids.size();
            return a.output.rms_px < b.output.rms_px;
        };
        std::sort(hypotheses.begin(), hypotheses.end(), better);
        // With three or more observations, a tied pair consensus is not enough
        // evidence to choose which half of the phone is correct.
        if (observations.size() > 2 &&
            hypotheses.front().output.inlier_ids.size() * 2 <= observations.size())
            return {"rejected", {}};
        // Refit each distinct consensus using all its points. Pair fits are
        // seeds, not independent ambiguity hypotheses: keeping them would
        // falsely label noisy variations of the same minimum as ambiguity.
        std::set<std::vector<int>> consensus_sets;
        const auto best_count = hypotheses.front().output.inlier_ids.size();
        for (const auto &h : hypotheses)
            if (h.output.inlier_ids.size() == best_count)
                consensus_sets.insert(h.output.inlier_ids);
        std::vector<Candidate> fitted;
        for (const auto &consensus : consensus_sets) {
            std::vector<int> indices;
            for (std::size_t i = 0; i < observations.size(); ++i)
                if (std::find(consensus.begin(), consensus.end(), observations[i].id) !=
                    consensus.end())
                    indices.push_back(int(i));
            for (auto &candidate : solve(observations, indices, calibration_)) {
                score(candidate, observations, calibration_);
                if (candidate.output.inlier_ids.size() >= 2)
                    fitted.push_back(std::move(candidate));
            }
        }
        if (fitted.empty())
            return {"rejected", {}};
        hypotheses = std::move(fitted);
        std::sort(hypotheses.begin(), hypotheses.end(), better);
        if (observations.size() > 2 &&
            hypotheses.front().output.inlier_ids.size() * 2 <= observations.size())
            return {"rejected", {}};
        PoseResult result{"accepted", {}};
        for (const auto &candidate : hypotheses) {
            if (candidate.output.inlier_ids.size() < hypotheses.front().output.inlier_ids.size())
                continue;
            bool duplicate = false;
            for (const auto &accepted : result.candidates) {
                double distance{};
                for (std::size_t i = 0; i < 3; ++i)
                    distance +=
                        std::pow(candidate.output.translation_m[i] - accepted.translation_m[i], 2);
                if (rotation_distance(candidate.output, accepted) < 0.0174533 &&
                    distance < 0.001 * 0.001)
                    duplicate = true;
            }
            if (!duplicate)
                result.candidates.push_back(candidate.output);
            if (result.candidates.size() == 2)
                break;
        }
        if (result.candidates.size() > 1 &&
            result.candidates[1].rms_px - result.candidates[0].rms_px < 0.5)
            result.status = "ambiguous";
        return result;
    } catch (const cv::Exception &) {
        return {"rejected", {}};
    }
}

void write_pose_jsonl(std::ostream &output, const CameraFrame &frame,
                      const PlanarPoseEstimator &estimator, const PoseResult &pose) {
    Json j{{"schema", "framephone.camera-pose"},
           {"version", 1},
           {"transform", "T_CP"},
           {"units", "meters"},
           {"camera_id", frame.camera_id},
           {"calibration_id", frame.calibration_id},
           {"calibration_status", estimator.calibration().status},
           {"phone_layout_revision", estimator.layout().revision},
           {"capture_timestamp_ns", frame.capture_time_ns},
           {"clock_domain", frame.clock_domain},
           {"status", pose.status},
           {"candidates", Json::array()}};
    if (frame.ring_transport) {
        const auto &r = *frame.ring_transport;
        j["ring_transport"] = {{"frame_number", r.frame_number},
                               {"dequeue_monotonic_ns", r.dequeue_monotonic_ns},
                               {"publish_monotonic_ns", r.publish_monotonic_ns},
                               {"v4l2_sequence", r.v4l2_sequence},
                               {"skipped_since_previous", r.skipped_since_previous}};
    }
    for (const auto &candidate : pose.candidates)
        j["candidates"].push_back({{"rotation_row_major", candidate.rotation_row_major},
                                   {"translation_m", candidate.translation_m},
                                   {"rms_px", candidate.rms_px},
                                   {"inlier_ids", candidate.inlier_ids}});
    output << j.dump() << '\n';
    if (!output)
        throw std::runtime_error("failed writing pose JSONL");
}
} // namespace framephone
