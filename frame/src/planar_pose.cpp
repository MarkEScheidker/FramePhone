#include "framephone/planar_pose.hpp"
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
cv::Matx33d rotation(const Pose &p) {
    return cv::Matx33d(p.rotation.data());
}
cv::Vec3d translation(const Pose &p) {
    return cv::Vec3d(p.translation_m.data());
}
Pose pose(cv::Matx33d r, cv::Vec3d t) {
    Pose p;
    std::copy_n(r.val, 9, p.rotation.begin());
    std::copy_n(t.val, 3, p.translation_m.begin());
    return p;
}
void validate_pair(const StereoRig &rig, const StereoPair &pair) {
    require(pair.skew_ns() <= 3'000'000, "planar pair exceeds 3 ms skew");
    require(pair.frames[0].clock_domain == pair.frames[1].clock_domain,
            "planar views require one capture clock");
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &f = pair.frames[v];
        const auto &k = rig.cameras[v].calibration;
        f.validate();
        require(f.camera_id == k.camera_id && f.calibration_id == k.id && f.width == k.width &&
                    f.height == k.height,
                "planar frame/calibration identity or size mismatch");
    }
}
bool valid_corners(const PlanarCorners &c, const CameraCalibration &k) {
    for (std::size_t i = 0; i < 4; ++i) {
        const auto a = c[i], b = c[(i + 1) % 4], d = c[(i + 2) % 4];
        if (!std::isfinite(a.x) || !std::isfinite(a.y) || a.x < 1 || a.y < 1 ||
            a.x >= k.width - 1 || a.y >= k.height - 1 || std::hypot(a.x - b.x, a.y - b.y) < 12 ||
            (b.x - a.x) * (d.y - b.y) - (b.y - a.y) * (d.x - b.x) <= 1)
            return false;
    }
    return true;
}
double angle(const Pose &a, const Pose &b) {
    double trace = 0;
    for (std::size_t i = 0; i < 9; ++i)
        trace += a.rotation[i] * b.rotation[i];
    return std::acos(std::clamp((trace - 1) / 2, -1.0, 1.0));
}
bool same_pose(const Pose &a, const Pose &b) {
    return angle(a, b) < .0174533 && cv::norm(translation(a) - translation(b)) < .001;
}

// One body pose fitted jointly against two calibrated views.
class BodyResidual final : public cv::LMSolver::Callback {
  public:
    BodyResidual(const StereoRig &rig, const PlanarTarget &body, const PlanarObservation &obs)
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
    const PlanarTarget &body_;
    const PlanarObservation &obs_;
};
bool refine(Pose &candidate, const StereoRig &rig, const PlanarTarget &body,
            const PlanarObservation &obs) {
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

void PlanarTarget::validate() const {
    require(std::isfinite(width_m) && std::isfinite(height_m) && std::isfinite(plane_z_m) &&
                width_m >= .01 && width_m <= .5 && height_m >= .01 && height_m <= .8 &&
                std::abs(plane_z_m) <= .1,
            "invalid planar target dimensions in meters");
}
std::array<Point3, 4> PlanarTarget::front() const {
    return {{{-width_m / 2, height_m / 2, plane_z_m},
             {width_m / 2, height_m / 2, plane_z_m},
             {width_m / 2, -height_m / 2, plane_z_m},
             {-width_m / 2, -height_m / 2, plane_z_m}}};
}
PlanarPoseEstimator::PlanarPoseEstimator(PlanarTarget body, StereoRig rig)
    : body_(body), rig_(std::move(rig)) {
    body_.validate();
    validate_stereo_rig(rig_);
}
PoseResult PlanarPoseEstimator::estimate(const StereoPair &pair,
                                         const PlanarObservation &obs) const {
    validate_pair(rig_, pair);
    PoseResult result;
    result.reason = "invalid_or_too_small_front_corners";
    for (std::size_t v = 0; v < 2; ++v)
        if (!valid_corners(obs.corners[v], rig_.cameras[v].calibration))
            return result;
    std::vector<Pose> seeds;
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
                                         hb * cv::Vec3d(0, 0, body_.plane_z_m)));
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
std::vector<std::vector<ImagePoint>> PlanarPoseEstimator::wireframe(const Pose &p,
                                                                    std::size_t view) const {
    const auto corners = body_.front();
    std::vector<std::vector<ImagePoint>> lines;
    for (std::size_t i = 0; i < 4; ++i) {
        std::vector<ImagePoint> line;
        for (int k = 0; k <= 16; ++k) {
            const auto a = vec(corners[i]), b = vec(corners[(i + 1) % 4]);
            double depth;
            const auto uv = rig_.cameras.at(view).project(
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
} // namespace framephone
