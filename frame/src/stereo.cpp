#include "framephone/stereo.hpp"
#include "calibration_json.hpp"
#include <algorithm>
#include <numeric>
#include <opencv2/calib3d.hpp>

namespace framephone {
namespace {
using calibration_json::Json;
using calibration_json::require;
cv::Vec3d vec(Point3 p) {
    return {p.x, p.y, p.z};
}
Point3 point(cv::Vec3d p) {
    return {p[0], p[1], p[2]};
}
void validate_frame(const CameraFrame &f, const RigCamera &c) {
    f.validate();
    const auto &k = c.calibration;
    require(f.camera_id == k.camera_id && f.calibration_id == k.id && f.width == k.width &&
                f.height == k.height,
            "stereo frame camera/calibration identity or dimensions mismatch");
}
struct Observation {
    int id;
    std::array<Point3, 4> object, triangulated;
    std::array<std::array<ImagePoint, 4>, 2> pixels;
    bool valid_rays{true};
};
struct Candidate {
    cv::Matx33d r;
    cv::Vec3d t;
    PoseCandidate output;
};
std::optional<Candidate> rigid_fit(const std::vector<Observation> &obs,
                                   const std::vector<int> &indices) {
    cv::Vec3d a{}, b{};
    for (int i : indices)
        for (std::size_t j = 0; j < 4; ++j) {
            if (!obs.at(std::size_t(i)).valid_rays)
                return {};
            a += vec(obs.at(std::size_t(i)).object[j]);
            b += vec(obs.at(std::size_t(i)).triangulated[j]);
        }
    const double count = double(indices.size() * 4);
    a /= count;
    b /= count;
    cv::Matx33d covariance = cv::Matx33d::zeros();
    for (int i : indices)
        for (std::size_t j = 0; j < 4; ++j)
            covariance += (vec(obs.at(std::size_t(i)).object[j]) - a) *
                          (vec(obs.at(std::size_t(i)).triangulated[j]) - b).t();
    cv::Mat w, u, vt;
    cv::SVD::compute(covariance, w, u, vt);
    // Planar points have rank two. Reject collinear/degenerate phone geometry.
    if (w.at<double>(1) <= w.at<double>(0) * 1e-6)
        return {};
    cv::Mat correction = cv::Mat::eye(3, 3, CV_64F);
    correction.at<double>(2, 2) = cv::determinant(vt.t() * u.t()) < 0 ? -1 : 1;
    cv::Mat r = vt.t() * correction * u.t();
    Candidate c;
    std::copy_n(r.ptr<double>(), 9, c.r.val);
    c.t = b - c.r * a;
    return c;
}
class Reprojection final : public cv::LMSolver::Callback {
  public:
    Reprojection(const StereoRig &rig, const std::vector<Observation> &obs,
                 std::vector<int> indices)
        : rig_(rig), obs_(obs), indices_(std::move(indices)) {}
    bool compute(cv::InputArray parameters, cv::OutputArray error,
                 cv::OutputArray jacobian) const override {
        const cv::Mat p = parameters.getMat();
        cv::Mat e;
        if (!evaluate(p, e))
            return false;
        e.copyTo(error);
        if (jacobian.needed()) {
            jacobian.create(e.rows, 6, CV_64F);
            auto j = jacobian.getMat();
            for (int k = 0; k < 6; ++k) {
                const double delta = k < 3 ? 1e-6 : 1e-7;
                auto plus = p.clone(), minus = p.clone();
                plus.at<double>(k) += delta;
                minus.at<double>(k) -= delta;
                cv::Mat ep, em;
                if (!evaluate(plus, ep) || !evaluate(minus, em))
                    return false;
                cv::Mat diff = (ep - em) / (2 * delta);
                diff.copyTo(j.col(k));
            }
        }
        return true;
    }

  private:
    bool evaluate(const cv::Mat &p, cv::Mat &e) const {
        cv::Matx33d r;
        cv::Rodrigues(cv::Vec3d(p.at<double>(0), p.at<double>(1), p.at<double>(2)), r);
        const cv::Vec3d t(p.at<double>(3), p.at<double>(4), p.at<double>(5));
        e.create(int(indices_.size() * 16), 1, CV_64F);
        int row = 0;
        for (int index : indices_) {
            const auto &o = obs_.at(std::size_t(index));
            for (std::size_t v = 0; v < 2; ++v)
                for (std::size_t k = 0; k < 4; ++k) {
                    double depth;
                    const auto uv =
                        rig_.cameras[v].project(point(r * vec(o.object[k]) + t), &depth);
                    if (depth <= 0.001)
                        return false;
                    e.at<double>(row++) = uv.x - o.pixels[v][k].x;
                    e.at<double>(row++) = uv.y - o.pixels[v][k].y;
                }
        }
        return cv::checkRange(e);
    }
    const StereoRig &rig_;
    const std::vector<Observation> &obs_;
    std::vector<int> indices_;
};
bool refine(Candidate &c, const StereoRig &rig, const std::vector<Observation> &obs,
            const std::vector<int> &indices) {
    cv::Vec3d rv;
    cv::Rodrigues(c.r, rv);
    cv::Mat p = (cv::Mat_<double>(6, 1) << rv[0], rv[1], rv[2], c.t[0], c.t[1], c.t[2]);
    const auto callback = cv::makePtr<Reprojection>(rig, obs, indices);
    const int iterations = cv::LMSolver::create(callback, 60, 1e-9)->run(p);
    if (iterations < 0 || iterations >= 60 || !cv::checkRange(p))
        return false;
    cv::Rodrigues(cv::Vec3d(p.at<double>(0), p.at<double>(1), p.at<double>(2)), c.r);
    c.t = {p.at<double>(3), p.at<double>(4), p.at<double>(5)};
    return true;
}
void score(Candidate &c, const StereoRig &rig, const std::vector<Observation> &obs) {
    c.output.inlier_ids.clear();
    double total{};
    const cv::Vec3d normal(c.r(0, 2), c.r(1, 2), c.r(2, 2));
    for (const auto &camera : rig.cameras) {
        const cv::Vec3d origin(camera.origin_m.data());
        if (normal.dot(origin - c.t) <= 0)
            return;
    }
    for (const auto &o : obs) {
        if (!o.valid_rays)
            continue;
        double square{}, maximum{};
        bool valid = true;
        for (std::size_t v = 0; v < 2; ++v)
            for (std::size_t k = 0; k < 4; ++k) {
                double depth;
                const auto uv = rig.cameras[v].project(point(c.r * vec(o.object[k]) + c.t), &depth);
                const double error = std::hypot(uv.x - o.pixels[v][k].x, uv.y - o.pixels[v][k].y);
                valid = valid && depth > 0.001 && std::isfinite(error);
                square += error * error;
                maximum = std::max(maximum, error);
            }
        if (valid && maximum <= 3) {
            c.output.inlier_ids.push_back(o.id);
            total += square;
        }
    }
    c.output.rms_px = c.output.inlier_ids.empty()
                          ? 1e100
                          : std::sqrt(total / (8 * double(c.output.inlier_ids.size())));
    std::copy_n(c.r.val, 9, c.output.rotation_row_major.begin());
    std::copy_n(c.t.val, 3, c.output.translation_m.begin());
}
bool same_pose(const PoseCandidate &a, const PoseCandidate &b) {
    double trace{}, distance{};
    for (std::size_t i = 0; i < 9; ++i)
        trace += a.rotation_row_major[i] * b.rotation_row_major[i];
    for (std::size_t i = 0; i < 3; ++i)
        distance += std::pow(a.translation_m[i] - b.translation_m[i], 2);
    return std::acos(std::clamp((trace - 1) / 2, -1.0, 1.0)) < 0.0174533 && distance < 1e-6;
}
} // namespace

std::uint64_t StereoPair::skew_ns() const {
    const auto a = frames[0].capture_time_ns, b = frames[1].capture_time_ns;
    return a > b ? a - b : b - a;
}
StereoFramePairer::StereoFramePairer(StereoRig rig, std::uint64_t max_skew_ns)
    : rig_(std::move(rig)), max_skew_(max_skew_ns) {
    validate_stereo_rig(rig_);
    require(max_skew_ <= 3'000'000, "capture skew limit must be <=3 ms");
}
void StereoFramePairer::push(CameraFrame f) {
    std::size_t index = 2;
    for (std::size_t i = 0; i < 2; ++i)
        if (f.camera_id == rig_.cameras[i].calibration.camera_id)
            index = i;
    require(index < 2, "unexpected stereo camera");
    validate_frame(f, rig_.cameras[index]);
    require(clock_.empty() || clock_ == f.clock_domain,
            "stereo cameras require one verified shared capture clock");
    require(f.capture_time_ns > last_[index], "stereo capture timestamp did not increase");
    clock_ = f.clock_domain;
    last_[index] = f.capture_time_ns;
    auto &q = pending_[index];
    q.push_back(std::move(f));
    if (q.size() > 4) {
        q.pop_front();
        ++dropped_;
    }
}
std::optional<StereoPair> StereoFramePairer::poll() {
    auto &a = pending_[0];
    auto &b = pending_[1];
    while (!a.empty() && !b.empty()) {
        const auto ta = a.front().capture_time_ns, tb = b.front().capture_time_ns;
        const auto skew = ta > tb ? ta - tb : tb - ta;
        if (skew <= max_skew_) {
            StereoPair p{{std::move(a.front()), std::move(b.front())}};
            a.pop_front();
            b.pop_front();
            return p;
        }
        (ta < tb ? a : b).pop_front();
        ++dropped_;
    }
    return {};
}
StereoPoseEstimator::StereoPoseEstimator(PhoneLayout layout, StereoRig rig)
    : layout_(std::move(layout)), rig_(std::move(rig)) {
    validate_stereo_rig(rig_);
}
StereoPoseResult StereoPoseEstimator::estimate(const StereoPair &pair,
                                               const std::array<DetectionBatch, 2> &batches) const {
    for (std::size_t v = 0; v < 2; ++v)
        validate_frame(pair.frames[v], rig_.cameras[v]);
    require(pair.frames[0].clock_domain == pair.frames[1].clock_domain &&
                pair.skew_ns() <= 3'000'000,
            "unpaired stereo capture timestamps");
    std::array<std::map<int, const TagDetection *>, 2> tags;
    for (std::size_t v = 0; v < 2; ++v)
        for (const auto &tag : batches[v].detections) {
            require(tag.camera_id == pair.frames[v].camera_id &&
                        tag.capture_time_ns == pair.frames[v].capture_time_ns,
                    "stereo detection source identity mismatch");
            if (!layout_.markers.contains(tag.id))
                continue;
            if (!tags[v].emplace(tag.id, &tag).second)
                return {"rejected", {}, 0};
        }
    std::vector<Observation> obs;
    for (const auto &[id, left] : tags[0]) {
        if (!tags[1].contains(id))
            continue;
        const auto *right = tags[1].at(id);
        if (left->hamming != 0 || right->hamming != 0 || !std::isfinite(left->decision_margin) ||
            !std::isfinite(right->decision_margin) || left->decision_margin < 10 ||
            right->decision_margin < 10)
            continue;
        Observation o;
        o.id = id;
        o.object = layout_.markers.at(id);
        o.pixels = {left->corners, right->corners};
        for (std::size_t k = 0; k < 4; ++k) {
            bool inside = true;
            for (std::size_t v = 0; v < 2; ++v) {
                const auto uv = o.pixels[v][k];
                const auto &c = rig_.cameras[v].calibration;
                inside = inside && std::isfinite(uv.x) && std::isfinite(uv.y) && uv.x >= -0.5 &&
                         uv.y >= -0.5 && uv.x < double(c.width) - 0.5 &&
                         uv.y < double(c.height) - 0.5;
            }
            const auto p =
                inside ? triangulate_stereo(rig_, {o.pixels[0][k], o.pixels[1][k]}) : std::nullopt;
            if (p)
                o.triangulated[k] = p->point;
            else
                o.valid_rays = false;
        }
        obs.push_back(o);
    }
    StereoPoseResult result{"insufficient_tags", {}, obs.size()};
    if (obs.size() < 2)
        return result;
    result.status = "rejected";
    try {
        std::vector<Candidate> seeds;
        for (std::size_t i = 0; i < obs.size(); ++i)
            for (std::size_t j = i + 1; j < obs.size(); ++j) {
                auto seed = rigid_fit(obs, {int(i), int(j)});
                if (seed && refine(*seed, rig_, obs, {int(i), int(j)}))
                    seeds.push_back(*seed);
            }
        // Reuse the existing planar solver's alternatives as additional seeds
        // so joint reprojection can expose competing plane poses at weak depth.
        for (std::size_t v = 0; v < 2; ++v) {
            const auto mono = PlanarPoseEstimator(layout_, rig_.cameras[v].calibration)
                                  .estimate(pair.frames[v], batches[v]);
            const cv::Matx33d hc(rig_.cameras[v].rotation.data());
            const cv::Vec3d origin(rig_.cameras[v].origin_m.data());
            std::vector<int> valid;
            for (std::size_t i = 0; i < obs.size(); ++i)
                if (obs[i].valid_rays)
                    valid.push_back(int(i));
            if (valid.size() < 2)
                continue;
            for (const auto &pose : mono.candidates) {
                Candidate c{hc * cv::Matx33d(pose.rotation_row_major.data()),
                            hc * cv::Vec3d(pose.translation_m.data()) + origin,
                            {}};
                if (refine(c, rig_, obs, valid))
                    seeds.push_back(c);
            }
        }
        std::vector<Candidate> fitted;
        for (auto &seed : seeds) {
            score(seed, rig_, obs);
            if (seed.output.inlier_ids.size() < 2)
                continue;
            std::vector<int> indices;
            for (std::size_t i = 0; i < obs.size(); ++i)
                if (std::find(seed.output.inlier_ids.begin(), seed.output.inlier_ids.end(),
                              obs[i].id) != seed.output.inlier_ids.end())
                    indices.push_back(int(i));
            if (!refine(seed, rig_, obs, indices))
                continue;
            score(seed, rig_, obs);
            if (seed.output.inlier_ids.size() >= 2)
                fitted.push_back(seed);
        }
        std::sort(fitted.begin(), fitted.end(), [](const auto &a, const auto &b) {
            return a.output.inlier_ids.size() != b.output.inlier_ids.size()
                       ? a.output.inlier_ids.size() > b.output.inlier_ids.size()
                       : a.output.rms_px < b.output.rms_px;
        });
        if (fitted.empty() ||
            (obs.size() > 2 && fitted[0].output.inlier_ids.size() * 2 <= obs.size()))
            return result;
        for (const auto &c : fitted) {
            if (c.output.inlier_ids.size() < fitted[0].output.inlier_ids.size())
                break;
            if (std::none_of(result.candidates.begin(), result.candidates.end(),
                             [&](const auto &p) { return same_pose(p, c.output); }))
                result.candidates.push_back(c.output);
            if (result.candidates.size() == 2)
                break;
        }
        result.status = result.candidates.size() > 1 &&
                                result.candidates[1].rms_px - result.candidates[0].rms_px < 0.5
                            ? "ambiguous"
                            : "accepted";
    } catch (const cv::Exception &) {
        result.status = "rejected";
        result.candidates.clear();
    }
    return result;
}
void write_stereo_jsonl(std::ostream &out, const StereoPair &pair, const StereoPoseEstimator &e,
                        const StereoPoseResult &result) {
    Json j{{"schema", "framephone.stereo-pose"},
           {"version", 1},
           {"transform", "T_HP"},
           {"units", "meters"},
           {"head_axes", "right_up_back"},
           {"phone_layout_revision", e.layout().revision},
           {"status", result.status},
           {"shared_tags", result.shared_tags},
           {"capture_skew_ns", pair.skew_ns()},
           {"clock_domain", pair.frames[0].clock_domain},
           {"frames", Json::array()},
           {"candidates", Json::array()}};
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &f = pair.frames[v];
        Json frame{{"camera_id", f.camera_id},
                   {"calibration_id", f.calibration_id},
                   {"factory_camera_id", e.rig().cameras[v].factory_camera_id},
                   {"calibration_status", e.rig().cameras[v].calibration.status},
                   {"capture_timestamp_ns", f.capture_time_ns}};
        if (f.ring_transport) {
            const auto &r = *f.ring_transport;
            frame["ring_transport"] = {{"frame_number", r.frame_number},
                                       {"dequeue_monotonic_ns", r.dequeue_monotonic_ns},
                                       {"publish_monotonic_ns", r.publish_monotonic_ns},
                                       {"v4l2_sequence", r.v4l2_sequence},
                                       {"skipped_since_previous", r.skipped_since_previous}};
        }
        j["frames"].push_back(frame);
    }
    for (const auto &c : result.candidates)
        j["candidates"].push_back({{"rotation_row_major", c.rotation_row_major},
                                   {"translation_m", c.translation_m},
                                   {"rms_px", c.rms_px},
                                   {"inlier_ids", c.inlier_ids}});
    out << j.dump() << '\n';
    if (!out)
        throw std::runtime_error("failed writing stereo JSONL");
}
} // namespace framephone
