#include "framephone/markerless.hpp"
#include <algorithm>
#include <cmath>
#include <opencv2/calib3d.hpp>
#include <opencv2/imgproc.hpp>

namespace framephone {
namespace {
void require(bool ok, const char *message) {
    if (!ok)
        throw std::invalid_argument(message);
}
cv::Vec3d vec(Point3 p) {
    return {p.x, p.y, p.z};
}
Point3 point(cv::Vec3d p) {
    return {p[0], p[1], p[2]};
}
cv::Matx33d rotation(const BodyPose &p) {
    return cv::Matx33d(p.rotation.data());
}
cv::Vec3d translation(const BodyPose &p) {
    return cv::Vec3d(p.translation_m.data());
}
cv::Matx33d intrinsic(const CameraCalibration &k) {
    return {k.fx, 0, k.cx, 0, k.fy, k.cy, 0, 0, 1};
}
BodyPose pose(cv::Matx33d r, cv::Vec3d t) {
    BodyPose p;
    std::copy_n(r.val, 9, p.rotation.begin());
    std::copy_n(t.val, 3, p.translation_m.begin());
    return p;
}
void validate_pair(const StereoRig &rig, const StereoPair &pair) {
    require(pair.skew_ns() <= 3'000'000, "markerless pair exceeds 3 ms skew");
    require(pair.frames[0].clock_domain == pair.frames[1].clock_domain,
            "markerless views require one capture clock");
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &f = pair.frames[v];
        const auto &k = rig.cameras[v].calibration;
        f.validate();
        require(f.camera_id == k.camera_id && f.calibration_id == k.id && f.width == k.width &&
                    f.height == k.height,
                "markerless frame/calibration identity or size mismatch");
    }
}
bool valid_corners(const BodyCorners &c, const CameraCalibration &k) {
    for (std::size_t i = 0; i < 4; ++i) {
        const auto a = c[i], b = c[(i + 1) % 4], d = c[(i + 2) % 4];
        if (!std::isfinite(a.x) || !std::isfinite(a.y) || a.x < 1 || a.y < 1 ||
            a.x >= k.width - 1 || a.y >= k.height - 1 || std::hypot(a.x - b.x, a.y - b.y) < 12 ||
            (b.x - a.x) * (d.y - b.y) - (b.y - a.y) * (d.x - b.x) <= 1)
            return false;
    }
    return true;
}
double angle(const BodyPose &a, const BodyPose &b) {
    double trace = 0;
    for (std::size_t i = 0; i < 9; ++i)
        trace += a.rotation[i] * b.rotation[i];
    return std::acos(std::clamp((trace - 1) / 2, -1.0, 1.0));
}
bool same_pose(const BodyPose &a, const BodyPose &b) {
    return angle(a, b) < .0174533 && cv::norm(translation(a) - translation(b)) < .001;
}

// One body pose fitted jointly against two calibrated views.
class BodyResidual final : public cv::LMSolver::Callback {
  public:
    BodyResidual(const StereoRig &rig, const PhoneBodyModel &body, const BodyObservation &obs)
        : rig_(rig), body_(body), obs_(obs) {}
    bool compute(cv::InputArray input, cv::OutputArray error,
                 cv::OutputArray jacobian) const override {
        const auto p = input.getMat();
        cv::Mat e;
        if (!evaluate(p, e))
            return false;
        e.copyTo(error);
        if (jacobian.needed()) {
            jacobian.create(16, 6, CV_64F);
            auto j = jacobian.getMat();
            for (int k = 0; k < 6; ++k) {
                const double step = k < 3 ? 1e-6 : 1e-7;
                auto plus = p.clone(), minus = p.clone();
                plus.at<double>(k) += step;
                minus.at<double>(k) -= step;
                cv::Mat ep, em;
                if (!evaluate(plus, ep) || !evaluate(minus, em))
                    return false;
                cv::Mat difference = (ep - em) / (2 * step);
                difference.copyTo(j.col(k));
            }
        }
        return true;
    }

  private:
    bool evaluate(const cv::Mat &p, cv::Mat &e) const {
        cv::Matx33d r;
        cv::Rodrigues(cv::Vec3d(p.at<double>(0), p.at<double>(1), p.at<double>(2)), r);
        const cv::Vec3d t(p.at<double>(3), p.at<double>(4), p.at<double>(5));
        e.create(16, 1, CV_64F);
        int row = 0;
        const auto points = body_.front();
        for (std::size_t v = 0; v < 2; ++v)
            for (std::size_t k = 0; k < 4; ++k) {
                double depth;
                auto uv = rig_.cameras[v].project(point(r * vec(points[k]) + t), &depth);
                if (depth <= .01)
                    return false;
                e.at<double>(row++) = uv.x - obs_.corners[v][k].x;
                e.at<double>(row++) = uv.y - obs_.corners[v][k].y;
            }
        return cv::checkRange(e);
    }
    const StereoRig &rig_;
    const PhoneBodyModel &body_;
    const BodyObservation &obs_;
};
bool refine(BodyPose &candidate, const StereoRig &rig, const PhoneBodyModel &body,
            const BodyObservation &obs) {
    cv::Vec3d rv;
    cv::Rodrigues(rotation(candidate), rv);
    const auto t = translation(candidate);
    cv::Mat p = (cv::Mat_<double>(6, 1) << rv[0], rv[1], rv[2], t[0], t[1], t[2]);
    auto residual = cv::makePtr<BodyResidual>(rig, body, obs);
    const int iterations = cv::LMSolver::create(residual, 60, 1e-8)->run(p);
    if (iterations < 0 || iterations >= 60 || !cv::checkRange(p))
        return false;
    cv::Matx33d r;
    cv::Rodrigues(cv::Vec3d(p.at<double>(0), p.at<double>(1), p.at<double>(2)), r);
    candidate = pose(r, {p.at<double>(3), p.at<double>(4), p.at<double>(5)});
    const auto normal = r * cv::Vec3d(0, 0, 1);
    for (const auto &camera : rig.cameras)
        if (normal.dot(cv::Vec3d(camera.origin_m.data()) - translation(candidate)) <= 0)
            return false;
    cv::Mat e;
    if (!residual->compute(p, e, cv::noArray()))
        return false;
    candidate.rms_px = cv::norm(e) / std::sqrt(8.0);
    for (int i = 0; i < 16; i += 2)
        candidate.max_error_px =
            std::max(candidate.max_error_px, std::hypot(e.at<double>(i), e.at<double>(i + 1)));
    return std::isfinite(candidate.rms_px);
}
} // namespace

void PhoneBodyModel::validate() const {
    require(std::isfinite(width_m) && std::isfinite(height_m) && std::isfinite(thickness_m) &&
                width_m >= .02 && width_m <= .5 && height_m >= width_m && height_m <= .8 &&
                thickness_m >= .001 && thickness_m <= .1,
            "invalid phone body dimensions in meters");
}
std::array<Point3, 4> PhoneBodyModel::front() const {
    return {{{-width_m / 2, height_m / 2, thickness_m / 2},
             {width_m / 2, height_m / 2, thickness_m / 2},
             {width_m / 2, -height_m / 2, thickness_m / 2},
             {-width_m / 2, -height_m / 2, thickness_m / 2}}};
}
MarkerlessPoseEstimator::MarkerlessPoseEstimator(PhoneBodyModel body, StereoRig rig)
    : body_(body), rig_(std::move(rig)) {
    body_.validate();
    validate_stereo_rig(rig_);
}
BodyPoseResult MarkerlessPoseEstimator::estimate(const StereoPair &pair,
                                                 const BodyObservation &obs) const {
    validate_pair(rig_, pair);
    BodyPoseResult result;
    result.reason = "invalid_or_too_small_front_corners";
    for (std::size_t v = 0; v < 2; ++v)
        if (!valid_corners(obs.corners[v], rig_.cameras[v].calibration))
            return result;
    std::vector<BodyPose> seeds;
    std::vector<cv::Point3d> planar;
    for (const auto p : body_.front())
        planar.emplace_back(p.x, p.y, 0);
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &camera = rig_.cameras[v];
        const cv::Matx33d hc(camera.rotation.data());
        std::vector<cv::Point2d> normalized;
        for (auto pixel : obs.corners[v]) {
            const auto ray = hc.t() * vec(camera.ray(pixel));
            if (ray[2] <= .01)
                return result;
            normalized.emplace_back(ray[0] / ray[2], ray[1] / ray[2]);
        }
        std::vector<cv::Mat> rs, ts;
        cv::solvePnPGeneric(planar, normalized, cv::Matx33d::eye(), cv::noArray(), rs, ts, false,
                            cv::SOLVEPNP_IPPE);
        for (std::size_t i = 0; i < rs.size(); ++i) {
            if (!cv::checkRange(rs[i]) || !cv::checkRange(ts[i]))
                continue;
            cv::Matx33d cb;
            cv::Rodrigues(rs[i], cb);
            const cv::Vec3d face_t(ts[i].ptr<double>());
            const auto hb = hc * cb;
            // IPPE's plane origin is the FRONT center; publish BODY center.
            seeds.push_back(pose(hb, hc * face_t + cv::Vec3d(camera.origin_m.data()) -
                                         hb * cv::Vec3d(0, 0, body_.thickness_m / 2)));
        }
    }
    // An independently triangulated rigid fit also seeds the exact frontal case,
    // where planar IPPE implementations can return singular alternatives.
    std::array<cv::Vec3d, 4> target;
    cv::Vec3d a{}, b{};
    const auto object = body_.front();
    bool triangulated = true;
    for (std::size_t k = 0; k < 4; ++k) {
        const auto p = triangulate_stereo(rig_, {obs.corners[0][k], obs.corners[1][k]});
        if (!p) {
            triangulated = false;
            break;
        }
        target[k] = vec(p->point);
        a += vec(object[k]) / 4;
        b += target[k] / 4;
    }
    if (triangulated) {
        cv::Matx33d covariance = cv::Matx33d::zeros();
        for (std::size_t k = 0; k < 4; ++k)
            covariance += (vec(object[k]) - a) * (target[k] - b).t();
        cv::Mat w, u, vt;
        cv::SVD::compute(covariance, w, u, vt);
        cv::Mat correction = cv::Mat::eye(3, 3, CV_64F);
        correction.at<double>(2, 2) = cv::determinant(vt.t() * u.t()) < 0 ? -1 : 1;
        cv::Mat fit = vt.t() * correction * u.t();
        const cv::Matx33d r(fit.ptr<double>());
        seeds.push_back(pose(r, b - r * a));
    }
    for (auto seed : seeds) {
        if (!refine(seed, rig_, body_, obs))
            continue;
        auto duplicate = std::find_if(result.candidates.begin(), result.candidates.end(),
                                      [&](const auto &other) { return same_pose(seed, other); });
        if (duplicate == result.candidates.end())
            result.candidates.push_back(seed);
        else if (seed.rms_px < duplicate->rms_px)
            *duplicate = seed;
    }
    std::sort(result.candidates.begin(), result.candidates.end(),
              [](const auto &a, const auto &b) { return a.rms_px < b.rms_px; });
    result.reason = "stereo_reprojection_failed";
    if (result.candidates.empty() || result.candidates[0].rms_px > 2.5 ||
        result.candidates[0].max_error_px > 4)
        return result;
    if (result.candidates.size() > 1 &&
        result.candidates[1].rms_px <= result.candidates[0].rms_px + .25) {
        result.status = "ambiguous";
        result.reason = "competing_pose_hypotheses";
        return result;
    }
    result.status = "measured";
    result.reason = "labelled_front_corners";
    return result;
}
std::vector<std::vector<ImagePoint>> MarkerlessPoseEstimator::wireframe(const BodyPose &p,
                                                                        std::size_t view) const {
    const auto front = body_.front();
    std::array<Point3, 8> points;
    for (std::size_t i = 0; i < 4; ++i) {
        points[i] = front[i];
        points[i + 4] = {front[i].x, front[i].y, -body_.thickness_m / 2};
    }
    std::vector<std::vector<ImagePoint>> lines;
    for (std::size_t i = 0; i < 4; ++i)
        for (auto ends :
             {std::pair{i, (i + 1) % 4}, std::pair{i + 4, (i + 1) % 4 + 4}, std::pair{i, i + 4}}) {
            std::vector<ImagePoint> line;
            for (int k = 0; k <= 16; ++k) {
                const auto a = vec(points[ends.first]), b = vec(points[ends.second]);
                double depth;
                auto uv = rig_.cameras.at(view).project(
                    point(rotation(p) * (a + (b - a) * (double(k) / 16)) + translation(p)), &depth);
                if (depth <= .01 || !std::isfinite(uv.x) || !std::isfinite(uv.y)) {
                    line.clear();
                    break;
                }
                line.push_back(uv);
            }
            lines.push_back(std::move(line));
        }
    return lines;
}

struct MarkerlessTracker::Impl {
    explicit Impl(MarkerlessPoseEstimator e) : estimator(std::move(e)) {
        for (std::size_t v = 0; v < 2; ++v) {
            const auto &k = estimator.rig().cameras[v].calibration;
            require(std::uint64_t(k.width) * k.height <= 16'777'216,
                    "markerless rectification exceeds the image size limit");
            cv::fisheye::initUndistortRectifyMap(
                intrinsic(k), k.distortion, cv::Matx33d::eye(), intrinsic(k),
                cv::Size(int(k.width), int(k.height)), CV_32FC1, maps[v][0], maps[v][1]);
        }
    }
    MarkerlessPoseEstimator estimator;
    std::array<std::array<cv::Mat, 2>, 2> maps;
    std::optional<BodyPose> previous;
    std::array<std::uint64_t, 2> last{};
    bool first_live{true};

    struct Outline {
        BodyCorners raw;
        std::array<double, 4> coverage;
        double movement{};
    };
    std::vector<Outline> outlines(const CameraFrame &frame, std::size_t v) {
        const auto &camera = estimator.rig().cameras[v];
        const auto &k = camera.calibration;
        const auto ch = cv::Matx33d(camera.rotation.data()).t();
        std::array<cv::Point2f, 4> expected;
        const auto points = estimator.body().front();
        for (std::size_t i = 0; i < 4; ++i) {
            const auto c = ch * (rotation(*previous) * vec(points[i]) + translation(*previous) -
                                 cv::Vec3d(camera.origin_m.data()));
            if (c[2] <= .01)
                return {};
            expected[i] = {float(k.fx * c[0] / c[2] + k.cx), float(k.fy * c[1] / c[2] + k.cy)};
        }
        cv::Mat gray(int(frame.height), int(frame.width), CV_8UC1,
                     const_cast<std::uint8_t *>(frame.pixels.data()), frame.stride_bytes);
        cv::Mat rectified, edges, distance;
        cv::remap(gray, rectified, maps[v][0], maps[v][1], cv::INTER_LINEAR);
        auto roi = cv::boundingRect(std::vector<cv::Point2f>(expected.begin(), expected.end()));
        roi = cv::Rect(roi.x - 28, roi.y - 28, roi.width + 56, roi.height + 56) &
              cv::Rect(0, 0, rectified.cols, rectified.rows);
        if (roi.empty())
            return {};
        cv::GaussianBlur(rectified(roi), edges, cv::Size(3, 3), .7);
        cv::Canny(edges, edges, 40, 100);
        cv::distanceTransform(255 - edges, distance, cv::DIST_L2, 3);
        std::vector<std::vector<cv::Point>> contours;
        cv::findContours(edges, contours, cv::RETR_LIST, cv::CHAIN_APPROX_NONE);
        std::vector<Outline> found;
        for (const auto &contour : contours) {
            if (contour.size() < 40 || std::abs(cv::contourArea(contour)) < 200)
                continue;
            std::vector<cv::Point> quad;
            cv::approxPolyDP(contour, quad, .025 * cv::arcLength(contour, true), true);
            if (quad.size() != 4 || !cv::isContourConvex(quad))
                continue;
            // Fit the straight interior of each side; don't mistake rounded arc
            // endpoints for physical rectangle corners.
            std::array<cv::Vec4f, 4> lines;
            bool valid = true;
            for (std::size_t i = 0; i < 4; ++i) {
                const cv::Point2f a(quad[i]), b(quad[(i + 1) % 4]);
                const auto delta = b - a;
                const double length = cv::norm(delta);
                std::vector<cv::Point2f> support;
                for (auto pixel : contour) {
                    const auto offset = cv::Point2f(pixel) - a;
                    const double along = offset.dot(delta) / (length * length);
                    const double across =
                        std::abs(offset.x * delta.y - offset.y * delta.x) / length;
                    if (along > .2 && along < .8 && across < 3)
                        support.push_back(pixel);
                }
                if (length < 12 || support.size() < 8) {
                    valid = false;
                    break;
                }
                cv::fitLine(support, lines[i], cv::DIST_HUBER, 0, .01, .01);
            }
            if (!valid)
                continue;
            std::array<cv::Point2f, 4> fitted;
            for (std::size_t i = 0; i < 4; ++i) {
                const auto a = lines[(i + 3) % 4], b = lines[i];
                const double det = a[0] * b[1] - a[1] * b[0];
                if (std::abs(det) < .1) {
                    valid = false;
                    break;
                }
                const double t = ((b[2] - a[2]) * b[1] - (b[3] - a[3]) * b[0]) / det;
                fitted[i] = {float(a[2] + t * a[0] + roi.x), float(a[3] + t * a[1] + roi.y)};
            }
            if (!valid)
                continue;
            std::array<cv::Point2f, 4> ordered;
            double best = 1e100;
            for (int direction : {-1, 1})
                for (int start = 0; start < 4; ++start) {
                    double score = 0;
                    std::array<cv::Point2f, 4> option;
                    for (int i = 0; i < 4; ++i) {
                        option[std::size_t(i)] =
                            fitted[std::size_t((start + direction * i + 8) % 4)];
                        score += cv::norm(option[std::size_t(i)] - expected[std::size_t(i)]);
                    }
                    if (score < best) {
                        best = score;
                        ordered = option;
                    }
                }
            Outline out;
            out.movement = best / 4;
            for (std::size_t i = 0; i < 4; ++i) {
                if (cv::norm(ordered[i] - expected[i]) > 24)
                    valid = false;
                int hits = 0;
                for (int s = 0; s < 20; ++s) {
                    const float t = .15f + .7f * (float(s) + .5f) / 20;
                    const auto pixel = ordered[i] * (1 - t) + ordered[(i + 1) % 4] * t;
                    const auto x = std::lround(pixel.x) - roi.x, y = std::lround(pixel.y) - roi.y;
                    if (x >= 0 && y >= 0 && x < distance.cols && y < distance.rows &&
                        distance.at<float>(int(y), int(x)) <= 1.8f)
                        ++hits;
                }
                out.coverage[i] = double(hits) / 20;
                if (out.coverage[i] < .7)
                    valid = false;
            }
            if (!valid)
                continue;
            std::vector<cv::Point2d> normalized, raw;
            for (auto p : ordered)
                normalized.emplace_back((p.x - k.cx) / k.fx, (p.y - k.cy) / k.fy);
            cv::fisheye::distortPoints(normalized, raw, intrinsic(k), k.distortion);
            for (std::size_t i = 0; i < 4; ++i)
                out.raw[i] = {raw[i].x, raw[i].y};
            // Canny's inside/outside contours often describe the same edge.
            const bool duplicate = std::any_of(found.begin(), found.end(), [&](const auto &a) {
                double difference = 0;
                for (std::size_t i = 0; i < 4; ++i)
                    difference += std::hypot(a.raw[i].x - out.raw[i].x, a.raw[i].y - out.raw[i].y);
                return difference < 6;
            });
            if (!duplicate)
                found.push_back(out);
        }
        std::sort(found.begin(), found.end(),
                  [](auto &a, auto &b) { return a.movement < b.movement; });
        if (found.size() > 4)
            found.resize(4);
        return found;
    }
};
MarkerlessTracker::MarkerlessTracker(MarkerlessPoseEstimator estimator)
    : impl_(std::make_unique<Impl>(std::move(estimator))) {}
MarkerlessTracker::~MarkerlessTracker() = default;
bool MarkerlessTracker::active() const {
    return impl_->previous.has_value();
}
BodyPoseResult MarkerlessTracker::initialize(const StereoPair &pair, const BodyObservation &obs) {
    impl_->previous.reset();
    auto result = impl_->estimator.estimate(pair, obs);
    if (result.status == "measured")
        impl_->previous = result.candidates[0];
    impl_->last = {pair.frames[0].capture_time_ns, pair.frames[1].capture_time_ns};
    impl_->first_live = true;
    return result;
}
BodyPoseResult MarkerlessTracker::update(const StereoPair &pair) {
    try {
        validate_pair(impl_->estimator.rig(), pair);
    } catch (...) {
        impl_->previous.reset();
        throw;
    }
    BodyPoseResult lost;
    lost.reason = "select_phone_again";
    if (!impl_->previous)
        return lost;
    for (std::size_t v = 0; v < 2; ++v) {
        const auto time = pair.frames[v].capture_time_ns;
        if (time <= impl_->last[v] || (!impl_->first_live && time - impl_->last[v] > 250'000'000)) {
            impl_->previous.reset();
            lost.reason = "capture_gap_or_reordered_frame";
            return lost;
        }
        impl_->last[v] = time;
    }
    impl_->first_live = false;
    const auto left = impl_->outlines(pair.frames[0], 0),
               right = impl_->outlines(pair.frames[1], 1);
    std::vector<BodyPoseResult> fits;
    for (const auto &a : left)
        for (const auto &b : right) {
            auto fit = impl_->estimator.estimate(pair, {{a.raw, b.raw}});
            if (fit.status != "measured")
                continue;
            if (angle(fit.candidates[0], *impl_->previous) > .5 ||
                cv::norm(translation(fit.candidates[0]) - translation(*impl_->previous)) > .08)
                continue;
            fit.edge_coverage = {a.coverage, b.coverage};
            fit.reason = "stereo_front_outline";
            auto duplicate = std::find_if(fits.begin(), fits.end(), [&](const auto &other) {
                return same_pose(fit.candidates[0], other.candidates[0]);
            });
            if (duplicate == fits.end())
                fits.push_back(fit);
            else if (fit.candidates[0].rms_px < duplicate->candidates[0].rms_px)
                *duplicate = fit;
        }
    std::sort(fits.begin(), fits.end(), [](const auto &a, const auto &b) {
        return a.candidates[0].rms_px < b.candidates[0].rms_px;
    });
    if (fits.empty()) {
        impl_->previous.reset();
        lost.reason = "front_outline_missing_or_inconsistent";
        return lost;
    }
    if (fits.size() > 1 && fits[1].candidates[0].rms_px <= fits[0].candidates[0].rms_px + .25) {
        impl_->previous.reset();
        auto result = fits[0];
        result.status = "ambiguous";
        result.reason = "competing_outlines_select_again";
        result.candidates.push_back(fits[1].candidates[0]);
        return result;
    }
    impl_->previous = fits[0].candidates[0];
    return fits[0];
}
} // namespace framephone
